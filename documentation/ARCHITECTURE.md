# Architecture

## Flux de données

| Couche | Fichier(s) | Format | Produit par | Contenu |
|--------|-----------|--------|-------------|---------|
| Bronze | `bronze/questions_raw.csv` | CSV | `src/scrape_opentdb.py` | Questions OpenTDB telles que renvoyées par l'API (5 299), textes encodés |
| Bronze | `bronze/categories_raw.csv` | CSV | `src/scrape_opentdb.py` | Liste des catégories `api_category.php` (`id`, `name`) |
| Silver | `silver/questions.parquet` | Parquet | `src/bronze_to_silver.py` | Questions nettoyées et typées (5 290 après exclusion de 9 doublons validés et 8 corrections validées) |
| Silver | `silver/_qualite/doublons.csv` | CSV | `src/bronze_to_silver.py` | Rapport : doublons restants, à décider |
| Référentiel | `referentiels/exclusions_doublons.csv` | CSV | **l'équipe, à la main** | Exclusions de doublons validées (id exclu, id gardé, motif, date) |
| Référentiel | `referentiels/corrections_linguistiques.csv` | CSV | **l'équipe, à la main** | Corrections linguistiques validées (id, champ, avant, après, motif, date) |
| Référentiel | `referentiels/runs_exclus.csv` | CSV | **l'équipe, à la main** | Runs de `bronze/llm_answers/` écartés de silver (run_id, modèle, motif, date ; décision 19) |
| Bronze | `bronze/llm_answers/*.csv` | CSV (lots de 25) | `src/run_benchmark.py` | Une ligne par appel : requête envoyée (prompt, ordre des choix, réglages) + corps JSON de la réponse **tel quel**, temps, erreur |
| Silver | `silver/llm_answers/llm_answers.parquet` | Parquet | `src/answers_to_silver.py` | **Toutes** les réponses (nos runs + runs importés), notées avec les mêmes règles : texte, réponse nettoyée, lettre attendue, juste/faux, tokens |
| Bronze | `bronze/llm_answers_import/*.parquet` | Parquet (tel que reçu) | `src/import_llm_answers.py` | Runs déjà faits par l'équipe (Gemma 4 E2B, Ministral 3B, LM Studio), copiés octet pour octet depuis le dépôt de Cécile : réponses brutes + son corpus `questions_clean` (ordre des choix, ses ids) |
| Gold | `gold/warehouse.duckdb` | DuckDB | `dbt build` | Vues de staging + tables d'indicateurs |

`silver/_tests_invalides/` contient d'anciens essais exclus ; il n'est lu par personne.

**Pourquoi CSV en bronze** : une question = une ligne, lisible à l'œil, et l'écriture en ajout permet de reprendre un scraping interrompu.
**Bronze = brut** : aucune transformation, aucune colonne ajoutée ou calculée, doublons conservés (décision 9). Décodage, identifiants et nettoyage sont faits en silver.
**Pourquoi Parquet en silver** : colonnes typées (listes, dates), compressé, lu nativement par DuckDB et pandas.
**Pourquoi DuckDB + dbt en gold** : SQL versionné, tests de qualité, documentation générée, aucune base à installer.

## Extraction (bronze)

- API OpenTDB : catégories → comptage → questions par paquets de 50, avec un **token de session** (pas de doublon renvoyé).
- `encode=url3986` : les textes arrivent encodés en URL (`The%20Panama%20Canal`) et sont **écrits tels quels**. Le décodage est exact (pas d'entités HTML `&quot;`), il est fait en silver.
- Colonnes de `questions_raw.csv` = champs de l'API : `type`, `difficulty`, `category`, `question`, `correct_answer`, `incorrect_answers`. Seule contrainte du CSV : la liste `incorrect_answers` est écrite en texte JSON, valeurs encodées comprises.
- Pas de `category_id` (l'API ne renvoie que le nom), pas de date de récupération, pas d'identifiant.
- Limite de l'API : 1 appel / 5 s → pause de 5,5 s. Retry jusqu'à 15 fois (pause 10 s → 60 s), session HTTP recréée après une erreur réseau.
- Reprise par catégorie : les questions d'une catégorie sont écrites quand elle est complète ; relancé, le script saute les catégories déjà présentes.
- Contrôle final : nombre de lignes = `total_num_of_verified_questions` de `api_count_global.php`, et détail par catégorie.

## Nettoyage (bronze → silver)

`src/bronze_to_silver.py`. **Nettoyage technique** : fiabiliser les textes et les listes sans en modifier le sens. Il s'applique à `question`, `correct_answer`, chaque élément de `incorrect_answers` et `category`. Chaque étape compte les textes qu'elle change (résumé affiché).

| Étape | Règle | Effet mesuré (24/11) |
|-------|-------|----------------------|
| 02. Décodage | URL (url3986), puis entités HTML **bien formées** (avec `;`, donc `AT&T` intact) | 18 498 textes décodés de l'URL ; 0 entité HTML |
| 03. Listes | `incorrect_answers` : JSON lu **avant** de décoder les éléments (un `"` décodé ne casse pas la liste) ; doit être une liste de chaînes | 5 299 listes (3 éléments par QCM, 1 par vrai/faux) |
| 04. Unicode | normalisation NFC | 0 texte changé (déjà NFC) |
| 05. Espaces | début/fin retirés, espaces multiples (tabulation, espace insécable compris) réduits à un | 342 textes |

Ensuite : `category_id` → `question_id` (calculé après 02-URL et 03, **avant** 02-HTML, 04 et 05) → `nb_choices`. La catégorie n'est **pas découpée** (décision 11).

**`category_id`** : `categories_raw.csv` est contrôlé (non vide, ids entiers, ids et noms uniques, sinon arrêt) ; une question sans catégorie connue bloque l'écriture. Bilan affiché à chaque exécution : `lues − exclues (validées) = écrites`, nombre de questions sans `category_id` (0) et de catégories (24) ; arrêt si des questions sont perdues.

**07. Corrections linguistiques validées** (après nettoyage, avant les contrôles) : lues dans `referentiels/corrections_linguistiques.csv`, champs `question` ou `correct_answer` uniquement.
- Contrôles bloquants : id connu, champ autorisé, une seule correction par champ, texte « avant » **identique** au texte actuel (sinon la correction ne correspond plus à la donnée), « après » non vide et différent, motif renseigné.
- Trace avant/après : `silver/_qualite/corrections_appliquees.csv`. `question_id` ne change pas (calculé avant le nettoyage).
- 24/11 : 8 corrections (6 questions, 2 bonnes réponses : H20 → H2O, Cascading Style Sheet → Sheets), reprises du silver de Cécile avec son accord.

**08. Second contrôle des doublons** (après nettoyage) : clé de comparaison = question sans casse, ponctuation ni espaces multiples.
- Les exclusions **validées** dans `referentiels/exclusions_doublons.csv` sont appliquées : la ligne exclue est **retirée** de silver. Contrôles bloquants : les deux ids existent, sont différents, sont bien doublons l'un de l'autre, et le motif est renseigné.
- Les doublons restants sont écrits dans `silver/_qualite/doublons.csv`. **Aucune exclusion automatique.**
- 24/11 : 9 groupes trouvés, 9 exclusions validées (4 puis 5), 0 groupe restant : silver = 5 290 questions.

Caractères invisibles présents mais **non traités** (hors périmètre validé) : 16 traits d'union conditionnels `\xad`, 3 marques de direction `\u200e`.

- **`category_id`** : retrouvé par le nom de la catégorie dans `bronze/categories_raw.csv` (24 noms distincts, correspondance vérifiée).
- **`question_id`** = sha1 (16 caractères) de `catégorie || question || bonne réponse || mauvaises réponses triées`, calculé sur les textes **décodés, avant** le nettoyage des espaces. OpenTDB contient de vrais doublons (même question dans deux catégories, ou même question avec d'autres choix) : avec seulement question + réponse, 2 questions étaient fusionnées. **Formule figée** : les réponses de `silver/llm_answers/` y font référence.
- Pas de dédoublonnage : un identifiant en double bloque l'écriture.

Schéma `QUESTIONS_SCHEMA` :

| Colonne | Type | Nettoyage |
|---------|------|-----------|
| `question_id` | string | calculé (voir ci-dessus) |
| `category_id` | int32 | retrouvé dans `categories_raw.csv` |
| `category` | string | nom officiel OpenTDB, décodé et nettoyé, non découpé |
| `type`, `difficulty` | string | décodés, minuscules |
| `question`, `correct_answer` | string | décodés, espaces en début/fin retirés, espaces multiples réduits |
| `incorrect_answers` | list<string> | texte JSON → liste, décodée, même nettoyage des espaces |
| `nb_choices` | int32 | ajouté : 4 (QCM) ou 2 (vrai/faux) |

Contrôles bloquants (le fichier n'est pas écrit si l'un échoue) : catégorie connue, ids uniques, textes non vides, type et difficulté autorisés, 3 mauvaises réponses par QCM et 1 par vrai/faux, choix distincts. Écriture atomique (`.parquet.tmp` puis renommage).

## Benchmark (silver)

- **LM Studio** tourne sous Windows ; depuis WSL, Windows est la passerelle par défaut (`ip route show default`, actuellement `172.22.96.1`). Il faut « Serve on Local Network » (puis redémarrer LM Studio) et une règle de pare-feu :
  ```powershell
  New-NetFirewallRule -DisplayName "LM Studio (WSL)" -Direction Inbound -Protocol TCP -LocalPort 1234 -RemoteAddress 172.16.0.0/12 -InterfaceAlias "vEthernet (WSL (Hyper-V firewall))" -Action Allow -Profile Any
  ```
- **Serveur distant** (`--remote`) : API compatible OpenAI derrière un proxy (actuellement `Gemma-4-12b`). `API_URL` (base terminée par `/v1`, sans `/models`) et `API_KEY` sont lus dans `.env` (non versionné) via `python-dotenv` ; la clé part en en-tête `Authorization: Bearer`. Force le backend `http`.
- **Backend `http`** (API compatible OpenAI) avec `--no-think` : envoie `reasoning_effort: "none"`. Bonsai et Gemma 4 sont des modèles « qui réfléchissent » ; sans cela, leur raisonnement épuise `max_tokens` avant la réponse (réponse vide, vérifié avec Gemma le 24/11). Avec : `reasoning_tokens: 0`, 2 tokens générés. Le suffixe `/no_think` dans le prompt est ignoré.
- **Prompts et ordre des choix du projet** (`src/prompts.py`, décision 15) : 3 prompts ; choix triés par empreinte SHA-256 (graine 42), identiques pour tous les modèles ; en vrai/faux, les choix `True` / `False` sont affichés dans le prompt.
- **Réponses brutes en bronze** (décision 13) : `run_benchmark.py` n'interprète rien ; il écrit `bronze/llm_answers/<modèle>_<run_id>_<lot>.csv` (écriture atomique `.csv.tmp` puis renommage). Une erreur HTTP est gardée dans `error` (avec le corps renvoyé) et le run continue.
- Reprenable : les appels (question, modèle, prompt, **texte exact du prompt**) déjà répondus **sans erreur** dans `bronze/llm_answers/` sont sautés ; les erreurs sont refaites (dbt garde la réponse la plus récente). Le texte est comparé pour qu'une réponse à un ancien texte du même `prompt_id` ne compte pas pour le prompt actuel.
- **Notation en silver** (`src/answers_to_silver.py`, nos runs et runs importés) : texte = `choices[0].message.content`, tokens = `usage.completion_tokens`. `prompt_id` vérifié : le texte envoyé est reconstruit et comparé au prompt du projet. Les runs de `referentiels/runs_exclus.csv` (décision 19 : nos anciens prompts) ne sont pas lus et sont comptés dans le résumé. Contrôles bloquants : JSON illisible, question absente de silver, texte de prompt inconnu, bonne réponse absente des choix présentés, run exclu sans motif ou absent de bronze.
- **Notation stricte** (décision 20, règle de Cécile) : `clean_answer()` retire seulement les espaces autour ; `is_correct()` est vrai si la réponse vaut exactement `A`–`D` (QCM) ou `True` / `False` (vrai/faux) **et** la réponse attendue. dbt (`int_answers_enriched.format_ok`) applique la même liste de réponses admises. Ancienne règle tolérante : `archives/notation_tolerante/`.

## Projet commun avec le travail de Cécile

Décisions 15 à 18. Cécile a construit en parallèle le même benchmark (même corpus de 5 290 questions) et a déjà fait tourner Gemma 4 E2B et Ministral 3B sur LM Studio. On a fusionné les deux projets en **un seul pipeline** :

| Partie | Reprise de | Pourquoi |
|--------|-----------|----------|
| Bronze brut, `question_id`, référentiels, nettoyage, contrôles bloquants | notre projet | bronze strictement brut ; formule d'identifiant figée |
| 8 corrections linguistiques (24/11) | Cécile | son diagnostic linguistique complet (1 019 propositions) |
| Prompts `P1_choices`, `P2_expert`, `P3_expert_advanced` | Cécile | ses modèles ont déjà répondu avec ; P3 = 3ᵉ test |
| Ordre des choix (empreinte SHA-256, graine 42, `answer_choices` dans `src/prompts.py`) | Cécile | ne dépend que du contenu : même ordre pour tous les modèles |
| Runs Gemma 4 E2B et Ministral 3B | Cécile (importés) | pas de recalcul ; même corpus |
| Choix des modèles (tests de faisabilité Bonsai, Qwen, Ministral) | Cécile | méthode documentée dans son dépôt |
| Traçabilité par empreintes SHA-256 | Cécile | import et prompts vérifiables |
| Script de run, réponses JSON brutes, notation, dbt, gold, tests | notre projet | elle n'a pas de couche gold |

**Bronze, `src/import_llm_answers.py`** : télécharge depuis `raw.githubusercontent.com` les fichiers listés dans `FICHIERS`, au commit `COMMIT` (figé, pas la branche). Chaque fichier doit avoir l'empreinte SHA-256 attendue, sinon il n'est pas écrit ; écriture atomique ; un fichier déjà conforme n'est pas retéléchargé. Rien n'est transformé.

**Silver, `src/answers_to_silver.py`** traite les runs importés avec les mêmes règles que les nôtres :

| Étape | Règle | Résultat (25/11) |
|-------|-------|------------------|
| Identifiants | Leurs `question_id` (SHA-256) ≠ les nôtres (sha1, figés). Correspondance par contenu : catégorie + question + bonne réponse, espaces réduits (2 questions ne diffèrent que par un espace insécable). Un pour un, même type et même difficulté. | 5 290 / 5 290 reliées |
| Prompt | L'empreinte des gabarits du projet (`prompt_fingerprint`) doit égaler le `prompt_sha256` de leur configuration. | P1 et P2 vérifiés |
| Choix et lettre | Ordre des choix lu dans leur `questions_clean` ; lettre attendue = position de notre bonne réponse. | 0 incohérence |
| Notation | règle stricte de Cécile (décision 20), dans `is_correct`. | 31 740 réponses, 0 différence avec sa notation (justes et format) |

Non enregistrés dans ces runs : `completion_tokens`, `answered_at` (NULL). `machine` = version de LM Studio et quantification.

Commit importé : `7169dbb` (25/11), 6 runs complets (Gemma 4 E2B et Ministral 3B × 3 prompts, 31 740 réponses) + `questions_clean`. Pour un nouveau fichier : nouveau `COMMIT` et nouvelle ligne dans `FICHIERS` (avec `sha256sum`), puis `python src/import_llm_answers.py`, `python src/answers_to_silver.py`, `dbt build`. Ministral n'a pas de réglage de raisonnement : `reasoning_effort` est NULL pour ses réponses.

## Transformation (gold, dbt)

```
source('silver', 'questions')     source('silver', 'llm_answers')    ← src/models/sources.yml
  └─ staging/       stg_questions        stg_llm_answers               (vues)
      └─ intermediate/  int_answers_enriched                           (vue)
          └─ marts/     7 tables (décision 21), voir ci-dessous       (tables)
macros/gold_tests.sql   tests génériques gold : gold_grain, gold_concordance
tests/                  5 tests métier (un fichier SQL = une règle qui ne doit renvoyer aucune ligne)
```

| Axe | Mart | Grain (lignes) | Construction |
|-----|------|----------------|--------------|
| 1 | `accuracy_by_model_prompt` | modèle × prompt (6) | `GROUP BY model, prompt_id` |
| 2 | `prompt_effect` | modèle × couple de prompts P1→P2, P1→P3, P2→P3 (6) | auto-jointure de `int_answers_enriched` sur `question_id` + `model`, puis `GROUP BY` |
| 3 | `accuracy_by_category` | modèle × prompt × catégorie (144) | `GROUP BY model, prompt_id, category` |
| 3 | `category_model_gap` | prompt × catégorie (72) | lit `accuracy_by_category`, `row_number()` (départage par nom de modèle), puis `GROUP BY prompt_id, category` |
| 3 | `accuracy_by_difficulty` | modèle × prompt × difficulté × type, + `type = 'all'` (54) | `GROUP BY GROUPING SETS` ; filtrer sur `type` avant d'additionner |
| 3 | `accuracy_by_type` | modèle × prompt × type (12) | `GROUP BY model, prompt_id, type` |
| 4 | `question_consensus` | question (5 290) | `GROUP BY question_id`, `LEFT JOIN` sur la réponse fausse la plus donnée |

Les marts n'ont pas le même grain : ne pas les joindre ni additionner leurs effectifs.

- `stg_llm_answers` : une ligne par (question, modèle, prompt), la plus récente si relancé.
- `int_answers_enriched` : jointure réponse ↔ question + `format_ok` (réponse exactement A–D ou True/False, pour tous les prompts).
- `int_answers_enriched.chance_pct` = 100 / `nb_choices` (25 % QCM, 50 % vrai/faux) : seule définition du hasard. Les marts en font la moyenne (`chance_pct`) et en déduisent `pct_above_chance` ; la moyenne tient compte de la part de vrai/faux de chaque groupe (ex. `type = 'all'`).
- Ordre des choix identique pour les 6 configurations (une seule lettre attendue par question, vérifié le 25/11) : `question_consensus.most_common_wrong_answer` désigne la même proposition partout.
- Tests dans `sources.yml` : unicité et non-nullité des ids, valeurs autorisées, relation réponses → questions. Tests des marts (idée reprise du dbt de Cécile, commit `6d17118`) : **`gold_grain`** sur les 7 tables (une seule ligne par clé, clé jamais vide, nombre de lignes exact : 6, 6, 144, 72, 54, 12, 5 290 ; les données sont figées) ; **recalcul indépendant** des indicateurs depuis `int_answers_enriched` par un autre calcul (`gold_concordance` : `sum(CASE …)`, format recalculé depuis la réponse ; `prompt_effect` par pivot au lieu de l'auto-jointure ; `category_model_gap` sans classement ; `question_consensus` par `bool_and` / `bool_or`), plus les contrôles de cohérence (répartition complète, totaux par type et difficulté, 6 configurations par question). Vérifié par sabotage : chaque test échoue si on fausse une valeur. `dbt build` : 44 PASS.
- **Taux et temps non arrondis en gold** (`100.0 * count_if(...) / count(*)`, type DOUBLE) : l'arrondi se fait à l'affichage (dashboard). Les valeurs sont identiques à celles du gold de Cécile.
- Profil `trivial_tp` (`profiles.yml`) → `gold/warehouse.duckdb`.
