"""Étape 1 — Scraping complet d'Open Trivia DB vers la couche bronze.

Usage :
    python src/scrape_opentdb.py                    # tout le dataset -> bronze/
    python src/scrape_opentdb.py --max-per-cat 50   # test rapide
    python src/scrape_opentdb.py --check-only       # compare le CSV au total OpenTDB

Bronze = les données telles que renvoyées par l'API, sans aucune transformation :
- bronze/categories_raw.csv : la liste api_category.php (id, name) ;
- bronze/questions_raw.csv  : un champ de l'API = une colonne, textes encore encodés
  (encode=url3986, ex. "The%20Panama%20Canal"), doublons conservés, aucune colonne
  ajoutée ou calculée. Seule contrainte du CSV : la liste incorrect_answers est écrite
  telle quelle sous forme de texte JSON.

Décodage, question_id, category_id et nettoyage : src/bronze_to_silver.py.

Principe :
- liste des catégories (api_category.php) puis nombre de questions par catégorie (api_count.php)
- un session token pour que l'API ne renvoie pas deux fois la même question
- respect de la limite de l'API : 1 appel / 5 s (on attend 5,5 s)
- reprise possible par catégorie : les questions d'une catégorie sont écrites quand
  elle est terminée ; relancé, le script saute les catégories déjà présentes dans le CSV
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path
from urllib.parse import unquote

import requests

BASE = "https://opentdb.com"
SLEEP = 5.5
OUT_DEFAULT = Path("bronze/questions_raw.csv")
CATEGORIES_FILE = "categories_raw.csv"  # écrit dans le même dossier que --out
FIELDS = ["type", "difficulty", "category", "question", "correct_answer", "incorrect_answers"]
CATEGORY_FIELDS = ["id", "name"]

session = requests.Session()
_last_call = 0.0


MAX_ATTEMPTS = 15


def call(path: str, **params) -> dict:
    """Appel à l'API en respectant la limite de débit, avec retry.

    Pause croissante entre les essais (10 s, 20 s, 30 s... plafonnée à 60 s).
    Sur erreur réseau, la session est recréée pour repartir sur une connexion neuve.
    """
    global _last_call, session
    for attempt in range(1, MAX_ATTEMPTS + 1):
        wait = SLEEP - (time.time() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.time()
        pause = min(10 * attempt, 60)
        try:
            r = session.get(f"{BASE}/{path}", params=params, timeout=30)
            if r.status_code == 429:
                cause = "HTTP 429 (trop de requêtes)"
            else:
                r.raise_for_status()
                data = r.json()
                if data.get("response_code") == 5:
                    cause = "response_code 5 (limite de débit OpenTDB)"
                else:
                    return data
        except (requests.RequestException, ValueError) as e:
            cause = f"erreur réseau {type(e).__name__}: {e}"
            session.close()
            session = requests.Session()  # connexion neuve au prochain essai
        if attempt == MAX_ATTEMPTS:
            print(f"  ! {path} essai {attempt}/{MAX_ATTEMPTS} : {cause} -> abandon")
            break
        print(f"  ! {path} essai {attempt}/{MAX_ATTEMPTS} : {cause} -> pause {pause} s")
        time.sleep(pause)
    raise RuntimeError(f"Échec répété sur {path} {params}")


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))  # DictReader gère les questions sur plusieurs lignes


def write_categories(path: Path, cats: list[dict]) -> None:
    """Écrit la liste des catégories telle que renvoyée par api_category.php."""
    tmp = path.with_suffix(".csv.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CATEGORY_FIELDS)
        writer.writeheader()
        writer.writerows({"id": c["id"], "name": c["name"]} for c in cats)
    tmp.replace(path)


def categories_done(out: Path) -> set[str]:
    """Catégories déjà présentes dans le CSV (nom décodé, uniquement pour comparer)."""
    if not out.exists():
        return set()
    with out.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != FIELDS:
            raise SystemExit(f"{out} n'a pas les colonnes attendues {FIELDS} : "
                             "ancien format ? le supprimer avant de relancer.")
        return {unquote(row["category"]) for row in reader}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT_DEFAULT)
    ap.add_argument("--max-per-cat", type=int, default=None, help="limite pour tester")
    ap.add_argument("--check-only", action="store_true",
                    help="ne scrape pas, compare seulement le CSV au total OpenTDB")
    args = ap.parse_args()
    categories_path = args.out.parent / CATEGORIES_FILE

    if args.check_only:
        verifier_completude(args.out, categories_path)
        return

    args.out.parent.mkdir(parents=True, exist_ok=True)
    done = categories_done(args.out)

    cats = call("api_category.php")["trivia_categories"]
    write_categories(categories_path, cats)
    token = call("api_token.php", command="request")["token"]
    print(f"{len(cats)} catégories ({categories_path}), {len(done)} déjà en bronze")

    new_file = not args.out.exists()
    f = args.out.open("a", newline="", encoding="utf-8")
    writer = csv.DictWriter(f, fieldnames=FIELDS)
    if new_file:
        writer.writeheader()

    for cat in cats:
        cid, cname = cat["id"], cat["name"]
        if cname in done:
            print(f"- [{cid}] {cname}: déjà en bronze, ignorée")
            continue
        total = call("api_count.php", category=cid)["category_question_count"]["total_question_count"]
        target = min(total, args.max_per_cat) if args.max_per_cat else total
        rows: list[dict] = []
        amount = 50
        print(f"- [{cid}] {cname}: {total} questions")
        while len(rows) < target:
            amount = max(1, min(amount, target - len(rows)))
            data = call("api.php", amount=amount, category=cid, token=token, encode="url3986")
            code = data["response_code"]
            if code == 3:  # token inconnu -> nouveau token
                token = call("api_token.php", command="request")["token"]
                continue
            if code in (1, 4):  # plus assez de questions pour ce "amount"
                if amount == 1:
                    break
                amount = amount // 2
                continue
            if code != 0:
                raise RuntimeError(f"response_code inattendu: {data}")
            for q in data["results"]:
                # valeurs écrites telles que reçues ; la liste est sérialisée en JSON pour le CSV
                rows.append({
                    "type": q["type"],
                    "difficulty": q["difficulty"],
                    "category": q["category"],
                    "question": q["question"],
                    "correct_answer": q["correct_answer"],
                    "incorrect_answers": json.dumps(q["incorrect_answers"]),
                })
            print(f"    {len(rows)}/{target}")
        # la catégorie n'est écrite qu'une fois complète : une coupure ne laisse pas de catégorie partielle
        writer.writerows(rows)
        f.flush()
    f.close()
    print(f"Terminé : {args.out}")
    verifier_completude(args.out, categories_path)


def verifier_completude(out: Path, categories_path: Path) -> None:
    """Compare le nombre de questions vérifiées annoncé par OpenTDB au contenu du CSV."""
    data = call("api_count_global.php")
    api_total = data["overall"]["total_num_of_verified_questions"]

    rows = read_csv(out)
    ids = {c["name"]: c["id"] for c in read_csv(categories_path)}

    print("\nVérification de complétude")
    print(f"  questions vérifiées sur OpenTDB : {api_total}")
    print(f"  lignes dans le CSV              : {len(rows)}  ({out})")
    print(f"  écart (API - CSV)               : {api_total - len(rows):+d}")

    # détail des catégories qui ne collent pas, pour savoir où chercher
    par_cat: dict[str, int] = {}
    for r in rows:
        cid = ids.get(unquote(r["category"]), "?")
        par_cat[cid] = par_cat.get(cid, 0) + 1
    for cid, c in data.get("categories", {}).items():
        attendu = c["total_num_of_verified_questions"]
        if attendu != par_cat.get(cid, 0):
            print(f"    catégorie {cid} : API {attendu} / CSV {par_cat.get(cid, 0)}")
    if "?" in par_cat:
        print(f"    {par_cat['?']} questions avec une catégorie absente de {categories_path}")


if __name__ == "__main__":
    main()
