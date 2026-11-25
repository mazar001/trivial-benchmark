"""Transforme TOUTES les réponses brutes des modèles (bronze) en réponses notées (silver, Parquet).

Entrées : bronze/llm_answers/*.csv              (src/run_benchmark.py : requête + JSON brut de l'API)
          bronze/llm_answers_import/*.parquet   (src/import_llm_answers.py : runs déjà faits par
                                                 l'équipe sur LM Studio, Gemma 4 E2B et Ministral 3B)
          silver/questions.parquet               (src/bronze_to_silver.py : type et bonne réponse)
Sortie  : silver/llm_answers/llm_answers.parquet (lu par dbt : source silver.llm_answers)

Une seule règle pour toutes les réponses, quelle que soit leur origine (décisions 15 à 17) :
- question_id : le NÔTRE. Les runs importés utilisent une autre formule ; on les relie par le
  contenu (catégorie + question + bonne réponse, espaces réduits), correspondance un pour un ;
- prompt_id : celui du projet (src/prompts.py). Le texte exact est vérifié : reconstruit et
  comparé au prompt envoyé (nos runs), ou à l'empreinte SHA-256 enregistrée (runs importés) ;
- runs écartés : ceux de referentiels/runs_exclus.csv (décision 19, nos anciens prompts) ne
  sont pas lus ; ils restent en bronze et sont comptés dans le résumé ;
- notation : clean_answer et is_correct ci-dessous, règle STRICTE de Cécile (décision 20) :
  seule une réponse exactement « A »…« D » ou « True » / « False » peut être juste ;
  le respect du format est mesuré dans dbt (format_ok, même règle).
Toutes les lignes de bronze sont gardées, relances comprises : dbt (stg_llm_answers) ne
garde que la plus récente par (question, modèle, prompt).

Contrôles bloquants (silver non écrit) : JSON illisible, question absente de silver,
correspondance des questions importées qui n'est pas un pour un, prompt dont le texte ne
correspond à aucun prompt connu, bonne réponse absente des choix présentés, run écarté sans
motif ou introuvable en bronze.

Usage :
    python src/answers_to_silver.py
"""

import csv
import json
import re
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from prompts import LETTERS, PROMPTS, build_prompt, prompt_fingerprint

ROOT = Path(__file__).resolve().parent.parent
BRONZE_DIR = ROOT / "bronze" / "llm_answers"
EXCLUDED_RUNS_FILE = ROOT / "referentiels" / "runs_exclus.csv"
IMPORT_DIR = ROOT / "bronze" / "llm_answers_import"
IMPORT_QUESTIONS = IMPORT_DIR / "questions_clean.parquet"
QUESTIONS_FILE = ROOT / "silver" / "questions.parquet"
SILVER_FILE = ROOT / "silver" / "llm_answers" / "llm_answers.parquet"

ANSWERS_SCHEMA = pa.schema([
    ("question_id", pa.string()),
    ("model", pa.string()),
    ("prompt_id", pa.string()),
    ("prompt_text", pa.string()),
    ("options_order", pa.string()),
    ("expected_letter", pa.string()),
    ("ai_answer_raw", pa.string()),
    ("ai_answer", pa.string()),
    ("ai_correct", pa.bool_()),
    ("response_time", pa.float64()),
    ("completion_tokens", pa.int64()),
    ("error", pa.string()),
    ("temperature", pa.float64()),
    ("max_tokens", pa.int64()),
    ("reasoning_effort", pa.string()),
    ("machine", pa.string()),
    ("run_id", pa.string()),
    ("answered_at", pa.string()),
])


# ---------------------------------------------------------------- notation
REPONSES_ADMISES = {"multiple": tuple(LETTERS), "boolean": ("True", "False")}


def clean_answer(raw: str) -> str:
    """Réponse brute sans les espaces autour (rien d'autre n'est retiré)."""
    return (raw or "").strip()


def is_correct(answer: str, qtype: str, correct: str, expected_letter: str | None) -> bool:
    """Notation stricte de Cécile (sa DEC-022, notre décision 20).

    Juste seulement si la réponse est EXACTEMENT une réponse admise (A, B, C, D pour un QCM,
    True ou False pour un vrai/faux) et égale à la réponse attendue. Une réponse hors format
    (« **A** », « False. », « The correct answer is A ») est fausse.
    Notre ancienne règle, tolérante sur la forme : archives/notation_tolerante/.
    """
    expected = expected_letter if qtype == "multiple" else correct
    return answer in REPONSES_ADMISES[qtype] and answer == expected


# ---------------------------------------------------------------- lecture de la réponse brute
def parse_response(raw: str) -> tuple[str, int | None]:
    """Texte et nombre de tokens, depuis le corps JSON (HTTP) ou le JSON du backend SDK."""
    d = json.loads(raw)
    if "sdk_content" in d:
        return d["sdk_content"] or "", d.get("predicted_tokens_count")
    content = d["choices"][0]["message"].get("content") or ""
    return content, (d.get("usage") or {}).get("completion_tokens")


def to_int(s: str) -> int | None:
    return int(s) if s not in ("", None) else None


def space_key(*texts: str) -> tuple[str, ...]:
    """Clé de correspondance : espaces (insécables compris) réduits à un."""
    return tuple(re.sub(r"\s+", " ", t).strip() for t in texts)


def letter_of(qtype: str, correct: str, options: list[str]) -> str | None:
    """Lettre attendue (QCM) : position de la bonne réponse dans les choix présentés."""
    if qtype != "multiple":
        return None
    keys = [space_key(o) for o in options]
    k = space_key(correct)
    return LETTERS[keys.index(k)] if k in keys else ""


# ---------------------------------------------------------------- nos runs (CSV)
def canonical_prompt(b: dict, q: dict, options: list[str]) -> str | None:
    """prompt_id du projet si le texte envoyé est exactement celui du prompt actuel."""
    sent = b["prompt_text"].removesuffix(" /no_think")
    pid = b["prompt_id"]
    if pid in PROMPTS and sent == build_prompt(pid, q["type"], q["question"], options):
        return pid
    return None


def read_excluded_runs(errors: list[str]) -> set[tuple[str, str]]:
    """(run_id, modèle) écartés par l'équipe (décision 19), chacun avec un motif."""
    if not EXCLUDED_RUNS_FILE.exists():
        return set()
    excluded = set()
    with EXCLUDED_RUNS_FILE.open(encoding="utf-8", newline="") as fh:
        for n, r in enumerate(csv.DictReader(fh), 2):
            if not (r["run_id"] and r["model"] and r["motif"].strip()):
                errors.append(f"{EXCLUDED_RUNS_FILE.name} ligne {n} : run_id, model ou motif vide")
            excluded.add((r["run_id"], r["model"]))
    return excluded


def read_runs(questions: dict, errors: list[str]) -> tuple[list[dict], dict]:
    """Réponses de nos runs ; renvoie aussi le nombre de lignes écartées par run exclu."""
    excluded = read_excluded_runs(errors)
    skipped = {key: 0 for key in excluded}
    rows = []
    for f in sorted(BRONZE_DIR.glob("*.csv")):
        with f.open(encoding="utf-8", newline="") as fh:
            for n, b in enumerate(csv.DictReader(fh), 2):
                where = f"{f.name} ligne {n}"
                if (b["run_id"], b["model"]) in excluded:
                    skipped[(b["run_id"], b["model"])] += 1
                    continue
                q = questions.get(b["question_id"])
                if q is None:
                    errors.append(f"{where} : question {b['question_id']} absente de silver")
                    continue
                options = json.loads(b["options_order"])
                pid = canonical_prompt(b, q, options)
                if pid is None:
                    errors.append(f"{where} : texte du prompt {b['prompt_id']} inconnu")
                    continue
                letter = letter_of(q["type"], q["correct_answer"], options)
                if letter == "":
                    errors.append(f"{where} : bonne réponse absente des choix présentés "
                                  f"({b['question_id']}, question modifiée depuis l'appel ?)")
                    continue
                text, tokens = "", None
                if not b["error"]:
                    try:
                        text, tokens = parse_response(b["response_raw"])
                    except (ValueError, KeyError, IndexError, TypeError) as e:
                        errors.append(f"{where} : réponse brute illisible ({e!r})")
                        continue
                answer = clean_answer(text)
                rows.append({
                    "question_id": b["question_id"],
                    "model": b["model"],
                    "prompt_id": pid,
                    "prompt_text": b["prompt_text"],
                    "options_order": b["options_order"],
                    "expected_letter": letter,
                    "ai_answer_raw": text,
                    "ai_answer": answer,
                    "ai_correct": False if b["error"] else is_correct(answer, q["type"], q["correct_answer"], letter),
                    "response_time": float(b["response_time"]),
                    "completion_tokens": tokens,
                    "error": b["error"] or None,
                    "temperature": float(b["temperature"]),
                    "max_tokens": to_int(b["max_tokens"]),
                    "reasoning_effort": b["reasoning_effort"] or None,
                    "machine": b["machine"],
                    "run_id": b["run_id"],
                    "answered_at": b["answered_at"],
                })
    for (run_id, model), count in skipped.items():
        if count == 0:
            errors.append(f"{EXCLUDED_RUNS_FILE.name} : run {run_id} ({model}) introuvable en bronze")
    return rows, skipped


# ---------------------------------------------------------------- runs importés (Parquet)
def import_mapping(questions: dict, errors: list[str]) -> dict:
    """question_id importé -> (notre question, choix présentés). Correspondance un pour un."""
    ours = {space_key(q["category"], q["question"], q["correct_answer"]): q for q in questions.values()}
    mapping, used = {}, set()
    imported = pq.read_table(IMPORT_QUESTIONS).to_pylist()
    for q in imported:
        n = ours.get(space_key(q["category"], q["question"], q["correct_answer"]))
        if n is None:
            errors.append(f"question importée sans équivalent chez nous : {q['question_id']}")
        elif n["question_id"] in used:
            errors.append(f"deux questions importées pour notre {n['question_id']}")
        elif (n["type"], n["difficulty"]) != (q["type"], q["difficulty"]):
            errors.append(f"type ou difficulté différents pour {q['question_id']}")
        else:
            used.add(n["question_id"])
            mapping[q["question_id"]] = (n, list(q["answer_choices"]), q["question"])
    if len(imported) != len(questions):
        errors.append(f"{len(imported)} questions importées pour {len(questions)} chez nous")
    return mapping


def read_imports(questions: dict, errors: list[str]) -> tuple[list[dict], int]:
    files = sorted(p for p in IMPORT_DIR.glob("*.parquet") if p != IMPORT_QUESTIONS)
    if not files:
        return [], 0
    mapping = import_mapping(questions, errors)
    checked, rows = set(), []
    for f in files:
        for n, b in enumerate(pq.read_table(f).to_pylist(), 1):
            where = f"{f.name} ligne {n}"
            config = json.loads(b["configuration"])
            pid = b["prompt_id"]
            fingerprint = config["prompt_sha256"].get(pid)
            if (pid, fingerprint) not in checked:
                if pid not in PROMPTS or fingerprint != prompt_fingerprint(pid):
                    errors.append(f"{where} : texte du prompt {pid} différent de celui du projet")
                    continue
                checked.add((pid, fingerprint))
            pair = mapping.get(b["question_id"])
            if pair is None:
                errors.append(f"{where} : question {b['question_id']} non reliée")
                continue
            q, options, question_sent = pair
            letter = letter_of(q["type"], q["correct_answer"], options)
            if letter == "":
                errors.append(f"{where} : bonne réponse absente des choix présentés")
                continue
            error = None if b["status"] == "received" else f"{b['status']} : {b['error_type']} {b['error_message']}"
            text = b["raw_response"] or ""
            answer = clean_answer(text)
            gen = config["generation"]
            rows.append({
                "question_id": q["question_id"],
                "model": b["model_id"],
                "prompt_id": pid,
                "prompt_text": build_prompt(pid, q["type"], question_sent, options),
                "options_order": json.dumps(options, ensure_ascii=False),
                "expected_letter": letter,
                "ai_answer_raw": text,
                "ai_answer": answer,
                "ai_correct": False if error else is_correct(answer, q["type"], q["correct_answer"], letter),
                "response_time": b["response_time"],
                "completion_tokens": None,       # non enregistré dans ces runs
                "error": error,
                "temperature": float(gen["temperature"]),
                "max_tokens": gen["max_output_tokens"],
                "reasoning_effort": gen.get("reasoning"),   # absent pour Ministral (pas de raisonnement)
                "machine": f"LM Studio {config['lm_studio_version']} local, "
                           f"{config['model']['quantization']['name']}",
                "run_id": str(b["segment_id"]),
                "answered_at": None,             # non enregistré dans ces runs
            })
    return rows, len(files)


def main() -> None:
    questions = {r["question_id"]: r for r in pq.read_table(
        QUESTIONS_FILE, columns=["question_id", "category", "type", "difficulty",
                                 "question", "correct_answer"]).to_pylist()}
    errors: list[str] = []
    runs, skipped = read_runs(questions, errors)
    imports, n_import_files = read_imports(questions, errors)
    rows = runs + imports
    if not rows and not errors and not skipped:
        sys.exit("Aucune réponse en bronze : lancer src/run_benchmark.py ou src/import_llm_answers.py")

    if errors:
        print(f"{len(errors)} anomalie(s), silver non écrit :")
        for e in errors[:20]:
            print("  -", e)
        sys.exit(1)

    SILVER_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SILVER_FILE.with_suffix(".parquet.tmp")
    pq.write_table(pa.Table.from_pylist(rows, schema=ANSWERS_SCHEMA), tmp, compression="snappy")
    tmp.replace(SILVER_FILE)

    print(f"{len(runs)} réponses de nos runs ({BRONZE_DIR.relative_to(ROOT)}/), "
          f"{len(imports)} réponses importées ({n_import_files} fichier(s) de {IMPORT_DIR.relative_to(ROOT)}/)")
    if skipped:
        print(f"{sum(skipped.values())} réponses écartées, {len(skipped)} run(s) de "
              f"{EXCLUDED_RUNS_FILE.relative_to(ROOT)} (restent en bronze) :")
        for (run_id, model), count in sorted(skipped.items()):
            print(f"  {model:<22} run {run_id} : {count:>5} réponses")
    groups: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        groups.setdefault((r["model"], r["prompt_id"]), []).append(r)
    for (model, pid), rs in sorted(groups.items()):
        ok = [r for r in rs if not r["error"]]
        print(f"  {model:<22} {pid:<20} {len(rs):>5} réponses, {len(rs) - len(ok)} en erreur, "
              f"{sum(r['ai_correct'] for r in ok)} justes")
    print(f"Terminé : {len(rows)} réponses écrites dans {SILVER_FILE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
