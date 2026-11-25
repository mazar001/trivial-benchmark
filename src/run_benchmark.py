"""Interroge un modèle sur chaque question et écrit ses réponses BRUTES en bronze (CSV).

Exemples :
    # 0) vérifier la connexion et lister les modèles
    python src/run_benchmark.py --host 172.22.96.1:1234 --list-models   # LM Studio local
    python src/run_benchmark.py --remote --list-models                   # serveur distant (.env)

    # 1) test sur 5 questions x 3 prompts (P1_choices, P2_expert, P3_expert_advanced)
    python src/run_benchmark.py --remote --model Gemma-4-12b --no-think --limit 5

    # 2) run complet : toutes les questions de silver, les trois prompts
    python src/run_benchmark.py --remote --model Gemma-4-12b --no-think

    # LM Studio local (Bonsai) : --host 172.22.96.1:1234 --model prism-ml/bonsai-27b --backend http --no-think

--remote : serveur compatible OpenAI, API_URL et API_KEY lus dans .env (jamais affichés).
--no-think : envoie reasoning_effort="none" ; sans lui, les modèles « qui réfléchissent »
(Bonsai, Gemma 4) consomment les 16 tokens avant d'écrire la lettre (réponse vide).

Entrée : silver/questions.parquet (src/bronze_to_silver.py).
Sortie : bronze/llm_answers/*.csv, un fichier par lot. Bronze = ce qui a été envoyé (prompt,
ordre des choix, réglages) et ce que l'API a renvoyé, TEL QUEL (corps JSON complet de la
réponse). Aucun calcul ici : réponse nettoyée, lettre attendue et juste/faux sont calculés
en silver par src/answers_to_silver.py.
Prompts et ordre des choix : ceux du projet commun (src/prompts.py, décision 15), identiques
pour tous les modèles.
Reprenable : relancé, il saute les appels (question, modèle, prompt, texte exact du prompt)
déjà répondus sans erreur ; les appels en erreur sont refaits (silver garde la réponse la plus
récente). Le texte est comparé : une réponse obtenue avec un ancien texte du même prompt_id
(nos premiers prompts, décision 19) n'est pas prise pour une réponse au prompt actuel.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import socket
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from prompts import PROMPTS, answer_choices, build_prompt

QUESTIONS = Path("silver/questions.parquet")   # questions nettoyées (src/bronze_to_silver.py)
BRONZE = Path("bronze/llm_answers")             # réponses brutes du modèle (CSV)
SEED = 42
TEMPERATURE = 0.0

# Colonnes du CSV bronze : la requête envoyée, puis la réponse telle que reçue.
ANSWER_FIELDS = [
    "question_id", "model", "prompt_id", "prompt_text", "options_order",
    "backend", "temperature", "max_tokens", "reasoning_effort",
    "response_raw", "response_time", "error",
    "machine", "run_id", "answered_at",
]


# ---------------------------------------------------------------- client LM Studio
class SDKBackend:
    """API Python officielle de LM Studio (pip install lmstudio)."""

    def __init__(self, host: str, model_key: str):
        import lmstudio as lms
        self.client = lms.Client(host)
        self.model = self.client.llm.model(model_key)

    reasoning_effort = ""

    def ask(self, prompt: str, max_tokens: int) -> str:
        """Pas de corps HTTP avec l'API Python : on enregistre le texte et le nombre de tokens."""
        res = self.model.respond(prompt, config={"temperature": TEMPERATURE, "maxTokens": max_tokens})
        tokens = getattr(getattr(res, "stats", None), "predicted_tokens_count", None)
        return json.dumps({"sdk_content": res.content, "predicted_tokens_count": tokens}, ensure_ascii=False)


class HTTPBackend:
    """Secours : endpoint compatible OpenAI exposé par le serveur LM Studio."""

    def __init__(self, base_url: str, model_key: str, no_think: bool = False, api_key: str | None = None):
        import requests
        self.s = requests.Session()
        if api_key:
            self.s.headers["Authorization"] = f"Bearer {api_key}"
        self.url = f"{base_url}/chat/completions"
        self.model_key = model_key
        # désactive la phase de raisonnement des modèles "thinking" (Bonsai, Gemma 4) ;
        # le suffixe /no_think dans le prompt est ignoré par ces modèles
        self.reasoning_effort = "none" if no_think else ""

    def ask(self, prompt: str, max_tokens: int) -> str:
        """Renvoie le corps de la réponse HTTP tel quel (texte JSON), sans l'interpréter."""
        payload = {
            "model": self.model_key,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": TEMPERATURE,
            "max_tokens": max_tokens,
        }
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort
        r = self.s.post(self.url, timeout=600, json=payload)
        if not r.ok:  # le corps d'erreur est gardé dans l'exception, donc en bronze
            raise RuntimeError(f"HTTP {r.status_code} : {r.text[:500]}")
        return r.text


def list_models(base_url: str, api_key: str | None = None) -> None:
    import requests
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    r = requests.get(f"{base_url}/models", headers=headers, timeout=10)
    r.raise_for_status()
    for m in r.json()["data"]:
        print(m["id"])


# ---------------------------------------------------------------- données
def load_questions(sample: int | None, limit: int | None) -> pd.DataFrame:
    if not QUESTIONS.exists():
        raise SystemExit(f"{QUESTIONS} introuvable : lancer d'abord python src/bronze_to_silver.py")
    df = pd.read_parquet(QUESTIONS)
    if sample:
        # échantillon stratifié catégorie x difficulté, reproductible
        frac = min(1.0, sample / len(df))
        df = (df.groupby(["category", "difficulty"], group_keys=False)
                .apply(lambda g: g.sample(max(1, round(len(g) * frac)), random_state=SEED)))
    df = df.sample(frac=1, random_state=SEED)  # ordre mélangé : résultats partiels représentatifs
    return df.head(limit) if limit else df


def options_of(row) -> list[str]:
    """Ordre des choix présentés : ordre commun du projet (src/prompts.py, answer_choices)."""
    return answer_choices(row["category"], row["difficulty"], row["type"], row["question"],
                          row["correct_answer"], list(row["incorrect_answers"]))


def already_done(model: str) -> set[tuple[str, str, str]]:
    """Appels (question, prompt, texte du prompt) déjà répondus SANS erreur pour ce modèle."""
    done = set()
    for f in BRONZE.glob("*.csv"):
        with f.open(encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                if r["model"] == model and not r["error"]:
                    # le backend SDK ajoute « /no_think » au prompt : on compare le texte sans
                    done.add((r["question_id"], r["prompt_id"], r["prompt_text"].removesuffix(" /no_think")))
    return done


def write_batch(rows: list[dict], path: Path) -> None:
    """Écriture atomique : un lot interrompu n'est jamais pris pour un lot complet."""
    tmp = path.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=ANSWER_FIELDS)
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


# ---------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="localhost:1234", help="ip:port du serveur LM Studio")
    ap.add_argument("--remote", action="store_true",
                    help="serveur distant compatible OpenAI : API_URL et API_KEY lus dans .env (force --backend http)")
    ap.add_argument("--model", help="identifiant du modèle (voir --list-models)")
    ap.add_argument("--prompts", nargs="+", default=list(PROMPTS), choices=list(PROMPTS))
    ap.add_argument("--backend", choices=["sdk", "http"], default="sdk")
    ap.add_argument("--sample", type=int, help="échantillon stratifié de N questions")
    ap.add_argument("--limit", type=int, help="nombre max de questions (test)")
    ap.add_argument("--max-tokens", type=int, default=16)
    ap.add_argument("--no-think", action="store_true",
                    help="désactive le raisonnement (http : reasoning_effort=none ; sdk : /no_think)")
    ap.add_argument("--batch", type=int, default=25, help="taille des lots Parquet")
    ap.add_argument("--list-models", action="store_true", help="liste les modèles et quitte")
    args = ap.parse_args()

    if args.remote:
        from dotenv import load_dotenv
        load_dotenv()
        base_url, api_key = os.environ["API_URL"].rstrip("/"), os.environ.get("API_KEY")
        args.backend = "http"
    else:
        base_url, api_key = f"http://{args.host}/v1", None

    if args.list_models or args.model is None:
        list_models(base_url, api_key)
        return

    if args.backend == "http":
        backend = HTTPBackend(base_url, args.model, no_think=args.no_think, api_key=api_key)
    else:
        backend = SDKBackend(args.host, args.model)
    questions = load_questions(args.sample, args.limit)
    done = already_done(args.model)
    todo = [(r, p) for _, r in questions.iterrows() for p in args.prompts
            if (r["question_id"], p, build_prompt(p, r["type"], r["question"], options_of(r))) not in done]
    print(f"{len(todo)} appels à faire ({len(done)} déjà faits) — modèle {args.model}")

    BRONZE.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    machine = socket.gethostname()
    buffer, part, t_start, n_errors = [], 0, time.time(), 0

    def flush():
        nonlocal buffer, part
        if buffer:
            safe = re.sub(r"[^A-Za-z0-9_.-]", "_", args.model)
            write_batch(buffer, BRONZE / f"{safe}_{run_id}_{part:04d}.csv")
            buffer, part = [], part + 1

    try:
        for i, (row, pid) in enumerate(todo, 1):
            options = options_of(row)
            prompt = build_prompt(pid, row["type"], row["question"], options)
            if args.no_think and args.backend == "sdk":
                prompt += " /no_think"  # en http, on passe par reasoning_effort (voir HTTPBackend)
            t0 = time.perf_counter()
            raw, error = "", ""
            try:
                raw = backend.ask(prompt, args.max_tokens)
            except Exception as e:  # on garde la trace de l'erreur sans arrêter le run
                error = repr(e)[:800]
                n_errors += 1
            dt = time.perf_counter() - t0
            buffer.append({
                "question_id": row["question_id"],
                "model": args.model,
                "prompt_id": pid,
                "prompt_text": prompt,
                "options_order": json.dumps(options, ensure_ascii=False),
                "backend": args.backend,
                "temperature": TEMPERATURE,
                "max_tokens": args.max_tokens,
                "reasoning_effort": backend.reasoning_effort,
                "response_raw": raw,
                "response_time": round(dt, 4),
                "error": error,
                "machine": machine,
                "run_id": run_id,
                "answered_at": datetime.now(timezone.utc).isoformat(),
            })
            if len(buffer) >= args.batch:
                flush()
            if i % 10 == 0 or i == len(todo):
                elapsed = time.time() - t_start
                eta = elapsed / i * (len(todo) - i)
                print(f"  {i}/{len(todo)}  moy {elapsed / i:.2f}s/appel  reste ~{eta / 3600:.1f} h"
                      f"  erreurs {n_errors}", flush=True)
    finally:
        flush()
    print(f"Terminé : {len(todo)} appels, {n_errors} en erreur, réponses brutes dans {BRONZE}/")
    print("Ensuite : python src/answers_to_silver.py, puis dbt build")


if __name__ == "__main__":
    main()
