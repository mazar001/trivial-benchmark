# AGENTS.md

## Contexte

Projet d'école ETL « Trivial Poursuite » : mesurer la capacité de LLM (LM Studio en local, ou serveur distant compatible OpenAI : Gemma-4-12b) à répondre aux questions vérifiées d'**Open Trivia DB**. Pipeline en architecture médaillon bronze → silver → gold : Python pour l'ingestion et le nettoyage, dbt + DuckDB pour la transformation, Streamlit pour le dashboard.

Présentation, installation et commandes : voir [README.md](README.md).

## Objectifs

- Un pipeline reproductible et reprenable, des données brutes OpenTDB jusqu'aux indicateurs.
- Des résultats comparables entre modèles et entre prompts (taux de bonnes réponses, respect du format, temps de réponse).
- Un dashboard qui présente ces résultats.
- Rendu : jeudi 26/11/2026.

## Fichiers à consulter selon la tâche

| Tâche | Lire d'abord |
|-------|--------------|
| Reprendre le travail, savoir où on en est | `documentation/CURRENT.md` |
| Toucher au pipeline, aux formats, à dbt, à LM Studio | `documentation/ARCHITECTURE.md` |
| Changer une règle de notation, un prompt, le périmètre des données | `documentation/DECISIONS.md` |
| Travailler sur le dashboard | `documentation/specifications/DASHBOARD.md` |
| Lancer ou installer quelque chose | `README.md` |

## Règles permanentes

- **Langue** : code, commentaires, logs et documentation en français.
- **Pas de décision structurante sans accord** : proposer, expliquer, laisser l'équipe arbitrer. Une décision validée est notée dans `ARCHITECTURE.md` (technique) ou `DECISIONS.md` (métier).
- **`documentation/CURRENT.md` est mis à jour à la fin de chaque tâche significative.**
- **Bronze = données brutes des API** : aucune transformation, aucune colonne ajoutée, doublons conservés. Ne jamais modifier `bronze/` à la main. Seuls trois scripts y écrivent : `src/scrape_opentdb.py` (questions OpenTDB), `src/run_benchmark.py` (`bronze/llm_answers/` : requête envoyée + réponse JSON du modèle telle quelle) et `src/import_llm_answers.py` (`bronze/llm_answers_import/` : runs déjà faits par l'équipe, copiés octet pour octet depuis le dépôt de Cécile, commit figé, SHA-256 vérifié). Décodage, identifiants, nettoyage et notation se font en silver (`src/bronze_to_silver.py`, `src/answers_to_silver.py`).
- **Secrets** : `API_URL` / `API_KEY` uniquement dans `.env` (non versionné). Ne jamais afficher, journaliser ni committer la clé.
- **`referentiels/` est rempli par l'équipe uniquement** (décisions validées : exclusions de doublons, corrections, runs écartés). Ne jamais y ajouter une ligne sans accord explicite ; chaque ligne porte un motif.
- **dbt ne lit que silver** (`source('silver', ...)`), jamais bronze. Toujours référencer via `{{ ref(...) }}` / `{{ source(...) }}`.
- **Si le schéma silver change**, mettre à jour ensemble : `QUESTIONS_SCHEMA` dans `src/bronze_to_silver.py`, `src/models/sources.yml` et `ARCHITECTURE.md`.
- **La formule de `question_id` (dans `src/bronze_to_silver.py`) ne doit jamais changer** : les réponses de `bronze/llm_answers/` et `silver/llm_answers/` y font référence.
- **Un prompt modifié change d'identifiant** dans `src/prompts.py`, sinon les résultats ne sont plus comparables. Prompts du projet : `P1_choices`, `P2_expert`, `P3_expert_advanced` (décision 15) ; nos anciens textes sont retirés et leurs runs écartés en silver (`referentiels/runs_exclus.csv`, décision 19).
- **Un seul pipeline pour toutes les réponses** (décisions 15 à 20) : mêmes `question_id`, mêmes prompts, même ordre des choix, même notation (`is_correct` de `src/answers_to_silver.py`, règle stricte de Cécile, décision 20), qu'elles viennent de nos runs ou des runs importés. Pas de colonne ni de préfixe par personne.
- **Calculs longs sans accord interdits** : scraping complet (≈ 10 min, limite de l'API), run du benchmark au-delà d'un test `--limit` (plusieurs heures).
- **Actions côté Windows** (pare-feu, LM Studio) : donner la manipulation exacte à l'utilisateur, ne pas la faire soi-même.
- Requêtes de classement : critère de départage déterministe dans `ORDER BY` avant un `LIMIT`.
- Fichiers générés, à ne pas éditer ni committer : `target/`, `logs/`, `gold/*.duckdb`, `__pycache__/`, `.venv/`, `.user.yml`, `*.log`.

## Vérification après modification

1. Script Python modifié → le relancer sur un petit échantillon (`--limit`, `--max-per-cat`, `--check-only`) et lire le résumé final.
2. Modèle dbt modifié → `dbt build --select <modele>+`, vérifier `PASS` sans `ERROR`, puis `dbt docs generate` (couper `dbt docs serve` avant s'il tourne, le relancer après).
3. Contrôler dans DuckDB : `duckdb gold/warehouse.duckdb -c "SELECT * FROM <modele> LIMIT 10"`. Fermer la CLI avant de relancer dbt (verrou DuckDB).

## Conventions de commit et de push

- Messages en français, à l'impératif, préfixés par le type : `feat:`, `fix:`, `docs:`, `data:`, `refactor:` (ex. `feat: nettoyage des questions vers silver`).
- Un commit = une modification cohérente ; la doc touchée par le changement est dans le même commit.
- Avant de committer : `dbt build` sans erreur, et `CURRENT.md` à jour.
- Ne jamais committer de secrets, ni les fichiers générés listés plus haut.
- **Pas de `git push` sans accord explicite.**
