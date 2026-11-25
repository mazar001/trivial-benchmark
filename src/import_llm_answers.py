"""Importe en bronze, tels quels, les runs du benchmark déjà faits par l'équipe (décision 15).

Les runs Gemma 4 E2B et Ministral 3B ont été faits par Cécile sur LM Studio (son PC), avec les
prompts du projet (src/prompts.py). Ils sont publiés dans son dépôt GitHub ; on les récupère
au lieu de les relancer (plusieurs heures de calcul).

Source : https://github.com/CecileGUICHARD/trivial-pursuit-data-engineering, à un commit FIGÉ
(pas la branche, qui peut bouger).
Sortie : bronze/llm_answers_import/<fichier>, octet pour octet identique au fichier publié.

Fichiers importés (FICHIERS ci-dessous) :
- les réponses BRUTES : une ligne par appel au modèle, réponse texte telle que renvoyée par
  LM Studio, temps de réponse, statut, configuration complète (dont l'empreinte des prompts) ;
- le corpus questions_clean.parquet de ce dépôt : il donne l'ordre des choix présentés et
  ses question_id (autre formule que la nôtre), pour relier ces réponses à nos questions.
  dbt ne le lit jamais.

Contrôles bloquants : empreinte SHA-256 attendue (un fichier modifié chez elle n'est pas
importé en silence), écriture atomique (.tmp puis renommage). Un fichier déjà présent et
conforme n'est pas retéléchargé.

Pour ajouter un fichier : mettre à jour COMMIT,
ajouter une ligne à FICHIERS avec son empreinte (sha256sum), relancer ce script puis
src/answers_to_silver.py.

Usage :
    python src/import_llm_answers.py
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
BRONZE = ROOT / "bronze" / "llm_answers_import"

DEPOT = "CecileGUICHARD/trivial-pursuit-data-engineering"
COMMIT = "7169dbb355a243a861896a165e592991f5b9a3be"   # « Publier les données définitives pour le travail collaboratif », 25/11
URL = f"https://raw.githubusercontent.com/{DEPOT}/{COMMIT}/{{chemin}}"

# nom local -> (chemin dans son dépôt, SHA-256 attendu)
FICHIERS = {
    "questions_clean.parquet": (
        "data/silver/questions_clean.parquet",
        "af2e683573b68effb0832fff695e3acfeb138e3a67449ebd306814a00f67a92e"),
    "gemma_p1_choices.parquet": (
        "data/bronze/benchmark_lot4/gemma_p1_choices.parquet",
        "6b0f710570de50dc8869d8a546b2586d8c6b01f5356963083da140a84e6bf553"),
    "gemma_p2_expert.parquet": (
        "data/bronze/benchmark_lot4/gemma_p2_expert.parquet",
        "fc8c0188188f595dddf9b64379e948acb6398978ecf669ebe61f0e60b983f1c1"),
    "gemma_p3_expert_advanced.parquet": (
        "data/bronze/benchmark_lot4/gemma_p3_expert_advanced.parquet",
        "1795e0d12b476f1b24a0ea82232af2aabb64e27da2a9eb0dfeabb587c978cbad"),
    "ministral_p1_choices.parquet": (
        "data/bronze/benchmark_ministral_lot4/ministral_p1_choices.parquet",
        "190818901cc4f699e3ea3cee2bc8c15e38e14a59be76f725acfe1d7320fd146e"),
    "ministral_p2_expert.parquet": (
        "data/bronze/benchmark_ministral_lot4/ministral_p2_expert.parquet",
        "9e038ab6bd73f033587fc3bd5c05cec4f32797dcc24b662ec43e93b51ef34d57"),
    "ministral_p3_expert_advanced.parquet": (
        "data/bronze/benchmark_ministral_lot4/ministral_p3_expert_advanced.parquet",
        "953469c4000f8f5353b4ff6bdf9785c91c32cebb8f8d3cac0c63d7da2b1feaae"),
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    BRONZE.mkdir(parents=True, exist_ok=True)
    erreurs = 0
    for nom, (chemin, attendu) in FICHIERS.items():
        cible = BRONZE / nom
        if cible.exists() and sha256(cible.read_bytes()) == attendu:
            print(f"  déjà présent et conforme : {nom}")
            continue
        try:
            r = requests.get(URL.format(chemin=chemin), timeout=60)
            r.raise_for_status()
        except requests.RequestException as e:
            print(f"  ÉCHEC du téléchargement de {chemin} : {e}")
            erreurs += 1
            continue
        recu = sha256(r.content)
        if recu != attendu:
            print(f"  ÉCHEC {nom} : empreinte {recu[:12]}… au lieu de {attendu[:12]}… (fichier non écrit)")
            erreurs += 1
            continue
        tmp = cible.with_suffix(cible.suffix + ".tmp")
        tmp.write_bytes(r.content)
        tmp.replace(cible)
        taille = f"{len(r.content):_}".replace("_", " ")
        print(f"  importé : {nom} ({taille} octets, SHA-256 vérifié)")

    if erreurs:
        sys.exit(f"{erreurs} fichier(s) non importé(s)")
    print(f"Terminé : {len(FICHIERS)} fichier(s) conformes dans {BRONZE.relative_to(ROOT)}/ (commit {COMMIT[:7]})")


if __name__ == "__main__":
    main()
