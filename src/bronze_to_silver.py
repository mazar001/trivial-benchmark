"""Transforme les questions brutes de bronze/ et les écrit en Parquet dans silver/.

Entrées : bronze/questions_raw.csv    (réponses de l'API telles quelles, encodées url3986)
          bronze/categories_raw.csv   (liste des catégories : id, name)
          Produites par src/scrape_opentdb.py, jamais modifiées ici.
Sortie  : silver/questions.parquet    (une ligne par question, colonnes typées)

Nettoyage technique : fiabiliser les textes et les listes sans en modifier le sens.
Il s'applique à question, correct_answer, chaque élément de incorrect_answers et category.
  02. Décodage des textes : encodage URL (url3986, "The%20Panama%20Canal" -> "The Panama Canal"),
      puis entités HTML bien formées (&quot; &#039; &amp;...) si présentes.
  03. Conversion des listes : incorrect_answers, texte JSON -> liste de chaînes. Le JSON est lu
      AVANT de décoder les éléments, pour qu'un caractère décodé (", virgule) ne casse pas la liste.
  04. Normalisation Unicode NFC (même caractère, même écriture interne ; aucune reformulation).
  05. Nettoyage des espaces : espaces en début/fin retirés, espaces multiples (tabulation,
      retour à la ligne, espace insécable compris) réduits à un seul.
Chaque étape compte les textes qu'elle a réellement changés (résumé en fin d'exécution).

Ensuite :
- category_id : identifiant officiel OpenTDB, retrouvé par le nom de la catégorie dans
  categories_raw.csv (contrôlé : ids et noms uniques ; aucune question sans category_id) ;
- question_id : calculé sur les textes après les étapes 02 et 03 (décodage URL), AVANT 04-05.
  Formule figée : les réponses du benchmark (silver/llm_answers/) y font référence ;
- category conservée telle quelle (nom officiel, après nettoyage) : pas de découpage (décision 11) ;
- nb_choices ajouté (4 pour un QCM, 2 pour un vrai/faux).

07. Corrections linguistiques VALIDÉES par l'équipe, lues dans
    referentiels/corrections_linguistiques.csv (question_id, champ, avant, apres, motif,
    date_decision). Appliquées après le nettoyage, sur question ou correct_answer.
    Contrôle bloquant : identifiant connu, champ autorisé, texte « avant » identique au
    texte actuel (sinon la correction ne correspond plus à la donnée), motif présent.
    Trace avant/après : silver/_qualite/corrections_appliquees.csv.
    question_id n'est pas touché (il est calculé avant le nettoyage).

08. Second contrôle des doublons (après nettoyage) :
- exclusions VALIDÉES par l'équipe, lues dans referentiels/exclusions_doublons.csv
  (question_id_exclu, question_id_garde, motif, date_decision) : la ligne exclue est
  retirée de silver. Contrôle bloquant : les deux identifiants existent et sont bien
  doublons l'un de l'autre (même question à la casse et à la ponctuation près) ;
- les doublons restants sont listés dans silver/_qualite/doublons.csv, pour décision.
  Aucune exclusion automatique.

Aucun dédoublonnage : si bronze contenait deux fois la même question, le contrôle
« identifiant en double » bloquerait l'écriture et il faudrait décider quoi en faire.

Contrôles de qualité (le fichier n'est pas écrit si l'un d'eux échoue) :
catégorie connue, identifiants uniques, textes non vides, type et difficulté autorisés,
nombre de mauvaises réponses cohérent avec le type, bonne réponse distincte des mauvaises.

Usage :
    python src/bronze_to_silver.py
"""

import argparse
import csv
import hashlib
import html
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from urllib.parse import unquote

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent.parent
BRONZE_FILE = ROOT / "bronze" / "questions_raw.csv"
CATEGORIES_FILE = ROOT / "bronze" / "categories_raw.csv"
SILVER_FILE = ROOT / "silver" / "questions.parquet"
EXCLUSIONS_FILE = ROOT / "referentiels" / "exclusions_doublons.csv"
CORRECTIONS_FILE = ROOT / "referentiels" / "corrections_linguistiques.csv"
CORRECTIONS_REPORT = ROOT / "silver" / "_qualite" / "corrections_appliquees.csv"
CORRECTABLE_FIELDS = {"question", "correct_answer"}
DUPLICATES_REPORT = ROOT / "silver" / "_qualite" / "doublons.csv"

QUESTIONS_SCHEMA = pa.schema([
    ("question_id", pa.string()),
    ("category_id", pa.int32()),
    ("category", pa.string()),
    ("type", pa.string()),               # multiple | boolean
    ("difficulty", pa.string()),         # easy | medium | hard
    ("question", pa.string()),
    ("correct_answer", pa.string()),
    ("incorrect_answers", pa.list_(pa.string())),
    ("nb_choices", pa.int32()),
])

TYPES = {"multiple": 3, "boolean": 1}    # type -> nombre de mauvaises réponses attendu
DIFFICULTIES = {"easy", "medium", "hard"}


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        sys.exit(f"{path} introuvable : lancer d'abord python src/scrape_opentdb.py")
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))   # DictReader gère les questions sur plusieurs lignes


def question_id(category_id: int, q: str, answer: str, incorrect: list[str]) -> str:
    """Identifiant stable d'une question (textes décodés, avant nettoyage des espaces).

    On inclut la catégorie et les mauvaises réponses (triées, car l'API ne garantit
    pas leur ordre) : OpenTDB contient de vrais doublons, par ex. la même question
    dans deux catégories, ou la même question avec d'autres choix de réponses.
    Ne pas modifier : les réponses de silver/llm_answers/ y font référence.
    """
    key = "||".join([str(category_id), q, answer, *sorted(incorrect)])
    return hashlib.sha1(key.encode()).hexdigest()[:16]


# Entité HTML bien formée uniquement (avec « ; ») : « AT&T » ou « R&B » ne sont pas touchés.
HTML_ENTITY = re.compile(r"&(#\d+|#x[0-9a-fA-F]+|[a-zA-Z][a-zA-Z0-9]*);")

STATS: Counter = Counter()  # nombre de textes réellement changés par chaque étape


def counted(step: str, before: str, after: str) -> str:
    if after != before:
        STATS[step] += 1
    return after


def decode_url(s: str) -> str:
    """02a. Décodage de l'encodage URL (url3986) demandé à l'API."""
    return counted("02. décodage URL", s, unquote(s))


def decode_html(s: str) -> str:
    """02b. Décodage des entités HTML bien formées, si présentes."""
    return counted("02. décodage HTML", s, HTML_ENTITY.sub(lambda m: html.unescape(m.group(0)), s))


def parse_list(s: str) -> list[str]:
    """03. Texte JSON -> liste de chaînes (avant tout décodage des éléments)."""
    values = json.loads(s)
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        raise ValueError(f"incorrect_answers n'est pas une liste de chaînes : {s!r}")
    STATS["03. listes converties"] += 1
    return values


def normalize_nfc(s: str) -> str:
    """04. Normalisation Unicode NFC."""
    return counted("04. normalisation NFC", s, unicodedata.normalize("NFC", s))


def clean_spaces(s: str) -> str:
    """05. Espaces en début/fin retirés, espaces multiples réduits à un seul."""
    return counted("05. nettoyage des espaces", s, re.sub(r"\s+", " ", s).strip())


def clean_text(s: str) -> str:
    """Étapes 02b, 04 et 05 sur un texte déjà décodé de l'URL."""
    return clean_spaces(normalize_nfc(decode_html(s)))


def load_categories() -> dict[str, int]:
    """Lit categories_raw.csv et vérifie la liste : non vide, ids entiers, ids et noms uniques."""
    cats = read_csv(CATEGORIES_FILE)
    ids = [c["id"] for c in cats]
    names = [c["name"] for c in cats]
    problems = []
    if not cats:
        problems.append("liste vide")
    if not all(i.isdigit() for i in ids):
        problems.append("identifiant non entier")
    if len(set(ids)) != len(ids):
        problems.append("identifiant en double")
    if len(set(names)) != len(names):
        problems.append("nom en double")
    if problems:
        sys.exit(f"{CATEGORIES_FILE} invalide : {', '.join(problems)}")
    return {c["name"]: int(c["id"]) for c in cats}


def decode_row(raw: dict) -> dict:
    """Étapes 03 puis 02a : liste lue en JSON, puis chaque texte décodé de l'URL."""
    return {
        "type": unquote(raw["type"]),
        "difficulty": unquote(raw["difficulty"]),
        "category": decode_url(raw["category"]),
        "question": decode_url(raw["question"]),
        "correct_answer": decode_url(raw["correct_answer"]),
        "incorrect_answers": [decode_url(a) for a in parse_list(raw["incorrect_answers"])],
    }


def clean_row(d: dict, category_ids: dict[str, int]) -> dict:
    """question_id et category_id sur la ligne décodée, puis étapes 02b, 04, 05 et colonnes dérivées."""
    cid = category_ids.get(d["category"])  # None si catégorie inconnue (signalé par check)
    qid = question_id(cid, d["question"], d["correct_answer"], d["incorrect_answers"])
    category = clean_text(d["category"])
    incorrect = [clean_text(a) for a in d["incorrect_answers"]]
    return {
        "question_id": qid,
        "category_id": cid,
        "category": category,
        "type": d["type"].strip().lower(),
        "difficulty": d["difficulty"].strip().lower(),
        "question": clean_text(d["question"]),
        "correct_answer": clean_text(d["correct_answer"]),
        "incorrect_answers": incorrect,
        "nb_choices": len(incorrect) + 1,
    }


def check(rows: list[dict]) -> list[str]:
    """Renvoie la liste des anomalies (vide si tout est correct)."""
    errors = []
    seen = set()
    for r in rows:
        qid = r["question_id"]
        if r["category_id"] is None:
            errors.append(f"{qid} : catégorie inconnue {r['category']!r}")
        if qid in seen:
            errors.append(f"{qid} : identifiant en double")
        seen.add(qid)
        if not r["question"] or not r["correct_answer"]:
            errors.append(f"{qid} : question ou bonne réponse vide")
        if r["type"] not in TYPES:
            errors.append(f"{qid} : type inconnu {r['type']!r}")
        elif len(r["incorrect_answers"]) != TYPES[r["type"]]:
            errors.append(f"{qid} : {len(r['incorrect_answers'])} mauvaises réponses pour un {r['type']}")
        if r["difficulty"] not in DIFFICULTIES:
            errors.append(f"{qid} : difficulté inconnue {r['difficulty']!r}")
        if r["type"] == "boolean" and r["correct_answer"] not in ("True", "False"):
            errors.append(f"{qid} : réponse vrai/faux invalide {r['correct_answer']!r}")
        options = [r["correct_answer"], *r["incorrect_answers"]]
        if any(not o for o in options) or len(set(options)) != len(options):
            errors.append(f"{qid} : choix vides ou en double après nettoyage")
    return errors


def apply_corrections(rows: list[dict]) -> tuple[list[dict], list[str]]:
    """07. Applique les corrections validées. Renvoie (corrections appliquées, anomalies)."""
    if not CORRECTIONS_FILE.exists():
        return [], []
    by_id = {r["question_id"]: r for r in rows}
    errors, applied, seen = [], [], set()
    for c in read_csv(CORRECTIONS_FILE):
        qid, field = c["question_id"], c["champ"]
        label = f"correction {qid} ({field})"
        if qid not in by_id:
            errors.append(f"{label} : identifiant introuvable dans les questions")
        elif field not in CORRECTABLE_FIELDS:
            errors.append(f"{label} : champ non corrigeable (autorisés : {sorted(CORRECTABLE_FIELDS)})")
        elif (qid, field) in seen:
            errors.append(f"{label} : deux corrections pour le même champ")
        elif by_id[qid][field] != c["avant"]:
            errors.append(f"{label} : le texte « avant » ne correspond plus au texte actuel "
                          f"{by_id[qid][field]!r}")
        elif not c["apres"].strip() or c["apres"] == c["avant"]:
            errors.append(f"{label} : texte « apres » vide ou identique à « avant »")
        elif not c["motif"].strip():
            errors.append(f"{label} : motif manquant")
        else:
            by_id[qid][field] = c["apres"]
            applied.append(c)
        seen.add((qid, field))
    return applied, errors


def write_corrections_report(applied: list[dict]) -> None:
    """07. Trace avant/après des corrections réellement appliquées."""
    CORRECTIONS_REPORT.parent.mkdir(parents=True, exist_ok=True)
    tmp = CORRECTIONS_REPORT.with_suffix(".csv.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["question_id", "champ", "avant", "apres", "motif", "date_decision"])
        for c in sorted(applied, key=lambda c: (c["question_id"], c["champ"])):
            w.writerow([c["question_id"], c["champ"], c["avant"], c["apres"], c["motif"], c["date_decision"]])
    tmp.replace(CORRECTIONS_REPORT)


def duplicate_key(question: str) -> str:
    """Clé de comparaison des doublons : casse, ponctuation et espaces ignorés."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", question.casefold())).strip()


def apply_exclusions(rows: list[dict]) -> tuple[list[dict], list[str]]:
    """08. Retire les doublons dont l'exclusion a été validée. Renvoie (lignes, anomalies)."""
    if not EXCLUSIONS_FILE.exists():
        return rows, []
    by_id = {r["question_id"]: r for r in rows}
    errors, excluded = [], set()
    for e in read_csv(EXCLUSIONS_FILE):
        out, keep = e["question_id_exclu"], e["question_id_garde"]
        if out not in by_id or keep not in by_id:
            errors.append(f"exclusion {out} -> {keep} : identifiant introuvable dans les questions")
        elif out == keep:
            errors.append(f"exclusion {out} : la ligne exclue et la ligne gardée sont identiques")
        elif duplicate_key(by_id[out]["question"]) != duplicate_key(by_id[keep]["question"]):
            errors.append(f"exclusion {out} -> {keep} : ces deux questions ne sont pas doublons")
        elif not e["motif"].strip():
            errors.append(f"exclusion {out} : motif manquant")
        else:
            excluded.add(out)
    return [r for r in rows if r["question_id"] not in excluded], errors


def write_duplicates_report(rows: list[dict]) -> int:
    """08. Liste les doublons restants (pour décision). Renvoie le nombre de groupes."""
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(duplicate_key(r["question"]), []).append(r)
    dups = [g for g in groups.values() if len(g) > 1]
    DUPLICATES_REPORT.parent.mkdir(parents=True, exist_ok=True)
    tmp = DUPLICATES_REPORT.with_suffix(".csv.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["groupe", "question_id", "category", "type", "difficulty",
                    "question", "correct_answer", "incorrect_answers"])
        for n, g in enumerate(sorted(dups, key=lambda g: g[0]["question"]), 1):
            for r in sorted(g, key=lambda r: r["question_id"]):
                w.writerow([n, r["question_id"], r["category"], r["type"], r["difficulty"],
                            r["question"], r["correct_answer"], " | ".join(r["incorrect_answers"])])
    tmp.replace(DUPLICATES_REPORT)
    return len(dups)


def write_parquet(table: pa.Table, path: Path) -> None:
    # Écriture dans un fichier temporaire puis renommage : un fichier
    # interrompu ne sera jamais pris pour un fichier complet.
    tmp_path = path.with_suffix(".parquet.tmp")
    pq.write_table(table, tmp_path, compression="snappy")
    tmp_path.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Bronze (CSV brut) -> Silver (Parquet) : questions nettoyées")
    parser.parse_args()

    raw_rows = read_csv(BRONZE_FILE)
    category_ids = load_categories()

    decoded = [decode_row(r) for r in raw_rows]
    rows = [clean_row(d, category_ids) for d in decoded]
    modified = sum(
        r["question"] != d["question"] or r["correct_answer"] != d["correct_answer"]
        or r["incorrect_answers"] != d["incorrect_answers"]
        for r, d in zip(rows, decoded)
    )

    applied, errors = apply_corrections(rows)
    errors += check(rows)
    nb_before = len(rows)
    rows, exclusion_errors = apply_exclusions(rows)
    errors += exclusion_errors
    if errors:
        print(f"{len(errors)} anomalie(s), silver non écrit :")
        for e in errors[:20]:
            print("  -", e)
        sys.exit(1)

    write_corrections_report(applied)
    nb_groups = write_duplicates_report(rows)
    SILVER_FILE.parent.mkdir(exist_ok=True)
    table = pa.Table.from_pylist(rows, schema=QUESTIONS_SCHEMA)
    write_parquet(table, SILVER_FILE)

    print(f"{len(raw_rows)} questions lues dans {BRONZE_FILE.relative_to(ROOT)}")
    print(f"{len(category_ids)} catégories lues dans {CATEGORIES_FILE.relative_to(ROOT)}")
    print("Nettoyage technique (textes réellement changés par étape) :")
    for step in ("02. décodage URL", "02. décodage HTML", "03. listes converties",
                 "04. normalisation NFC", "05. nettoyage des espaces"):
        print(f"  {step:<28} {STATS[step]}")
    print(f"{modified} questions dont la question ou une réponse a changé après le décodage URL")
    print(f"07. corrections linguistiques appliquées (validées dans "
          f"{CORRECTIONS_FILE.relative_to(ROOT)}) : {len(applied)} ({CORRECTIONS_REPORT.relative_to(ROOT)})")
    print(f"08. doublons exclus (validés dans {EXCLUSIONS_FILE.relative_to(ROOT)}) : {nb_before - len(rows)}")
    print(f"08. groupes de doublons restants, à décider : {nb_groups} ({DUPLICATES_REPORT.relative_to(ROOT)})")
    sans_id = sum(r["category_id"] is None for r in rows)
    print(f"Bilan : {len(raw_rows)} lues - {nb_before - len(rows)} exclues (validées) = {table.num_rows} écrites ; "
          f"{sans_id} sans category_id ; {len({r['category_id'] for r in rows})} catégories")
    if len(raw_rows) - (nb_before - len(rows)) != table.num_rows:
        sys.exit("Questions perdues en route : silver ne doit pas être utilisé")
    print(f"Terminé : {table.num_rows} questions écrites dans {SILVER_FILE.relative_to(ROOT)}, 0 en erreur.")


if __name__ == "__main__":
    main()
