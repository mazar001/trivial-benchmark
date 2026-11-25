# Trivial Benchmark

Benchmark de LLM locaux sur les questions de culture générale d'[Open Trivia DB](https://opentdb.com) : le modèle répond à chaque question, et on mesure son taux de bonnes réponses par catégorie, difficulté et prompt.

Projet d'école ETL, en architecture médaillon :

```
OpenTDB (API) ──scrape_opentdb.py──▶ bronze/questions_raw.csv + categories_raw.csv (brut)
                                          │  bronze_to_silver.py (décodage, ids, nettoyage)
                                          ▼
                                  silver/questions.parquet ──run_benchmark.py + modèle──▶ bronze/llm_answers/*.csv (brut)
                                          │                                                │
runs déjà faits par l'équipe (GitHub) ──import_llm_answers.py──▶ bronze/llm_answers_import/ (brut)
                                          │                                                │
                                          │                        answers_to_silver.py (une seule notation)
                                          │                                                ▼
                                          │                                   silver/llm_answers/llm_answers.parquet
                                          │                                                │
                                          └──────────────────────── dbt build ─────────────┘
                                                                        ▼
                                                              gold/warehouse.duckdb ──▶ dashboard
```

Détails techniques : [documentation/ARCHITECTURE.md](documentation/ARCHITECTURE.md).

## Prérequis

- WSL2 + Debian, Python 3.13
- [LM Studio](https://lmstudio.ai) sous Windows, avec un modèle chargé (ici `prism-ml/bonsai-27b`), le serveur lancé et **« Serve on Local Network »** activé
- Une règle de pare-feu Windows autorisant le port 1234 depuis WSL (voir `documentation/ARCHITECTURE.md`)

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Lancement

Toutes les commandes se lancent **depuis la racine du projet**, venv activé.

```bash
# 1. Bronze : récupérer les questions (≈ 10 min, reprenable)
python src/scrape_opentdb.py
python src/scrape_opentdb.py --check-only     # vérifier le CSV contre le total OpenTDB

# 2. Silver : décoder, identifier et nettoyer les questions
python src/bronze_to_silver.py

# 3. Interroger le modèle -> bronze/llm_answers/ (réponses brutes)
#    serveur distant : API_URL et API_KEY dans .env (jamais committé)
python src/run_benchmark.py --remote --list-models                      # tester la connexion
python src/run_benchmark.py --remote --model Gemma-4-12b --no-think --limit 5   # test rapide (3 prompts)
python src/run_benchmark.py --remote --model Gemma-4-12b --no-think             # run complet (5 290 x 3, ≈ 4 h 15)
#    LM Studio local (adresse de Windows vue de WSL : ip route show default)
python src/run_benchmark.py --host 172.22.96.1:1234                     # tester la connexion
python src/run_benchmark.py --host 172.22.96.1:1234 --model prism-ml/bonsai-27b \
    --backend http --no-think --limit 20                                # test rapide
python src/run_benchmark.py --host 172.22.96.1:1234 --model prism-ml/bonsai-27b \
    --backend http --no-think                                           # run complet (12-18 s/appel : trop lent)

# 3 bis. Silver : noter les réponses brutes
python src/answers_to_silver.py

# 3 ter. Runs déjà faits par l'équipe (Gemma 4 E2B, Ministral 3B) : import brut, commit figé, SHA-256 vérifié
python src/import_llm_answers.py
python src/answers_to_silver.py                # note toutes les réponses, nos runs et les runs importés

# 4. Gold : transformations et tests
dbt build
dbt docs generate && dbt docs serve           # documentation dbt sur http://localhost:8080
```

Le benchmark est reprenable : relancé, il saute les questions déjà traitées.

## Utilisation

Consulter les résultats :

```bash
duckdb gold/warehouse.duckdb -c "SELECT * FROM accuracy_by_model_prompt"
duckdb gold/warehouse.duckdb -c "SELECT * FROM accuracy_by_category"
duckdb gold/warehouse.duckdb -c "SELECT * FROM accuracy_by_difficulty"
```

Dashboard : à venir (voir `documentation/specifications/DASHBOARD.md`).

## Structure

```
├── README.md, AGENTS.md
├── documentation/          # architecture, décisions, état d'avancement, spécifications
├── bronze/                 # données brutes : questions OpenTDB, réponses du modèle (llm_answers/), runs importés de l'équipe (llm_answers_import/)
├── silver/                 # questions nettoyées + réponses des modèles (Parquet), rapports qualité (_qualite/)
├── referentiels/           # décisions validées par l'équipe (exclusions de doublons, corrections, runs écartés)
├── archives/               # anciennes versions gardées pour pouvoir les reprendre (notation tolérante) ; non lues par le pipeline
├── gold/                   # base DuckDB produite par dbt
├── src/                    # scripts Python + modèles dbt (src/models/)
├── dbt_project.yml, profiles.yml
└── requirements.txt
```
