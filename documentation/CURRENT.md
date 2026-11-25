# État d'avancement

*Mis à jour le 25/11/2026. Rendu : jeudi 26/11/2026.*

## Fait

- [x] Bronze : 5 299 questions, égal au total vérifié d'OpenTDB (`--check-only` : écart 0).
- [x] Bronze strictement brut (décision 9, 24/11) : réimport complet, champs de l'API tels quels (textes encodés), `categories_raw.csv` ajouté ; décodage, `category_id` et `question_id` déplacés en silver, `fetched_at` supprimé. Silver identique à l'ancien (mêmes 5 299 `question_id`, mêmes valeurs).
- [x] Scraping tolérant aux coupures (15 essais, session recréée).
- [x] Silver questions : `src/bronze_to_silver.py` → `silver/questions.parquet` (5 290 questions après 9 exclusions de doublons et 8 corrections validées, 0 erreur).
- [x] Nettoyage technique silver en 4 étapes (02 décodage URL + HTML, 03 listes, 04 NFC, 05 espaces), avec compteurs : 18 498 textes décodés, 0 entité HTML, 0 texte non NFC, 342 textes aux espaces corrigés. Silver inchangé (mêmes ids et valeurs), `dbt build` 18 PASS.
- [x] Étape 08, doublons après nettoyage : 9 groupes trouvés, **9 exclusions validées** (`referentiels/exclusions_doublons.csv`), 0 restant, silver = **5 290 questions**, `dbt build` 18 PASS. Les 5 derniers doublons sont transmis à Cécile (`documentation/partage/doublons_a_exclure_pour_cecile.csv`, avec ses `question_id`).
- [x] `pyspellchecker` ajouté (diagnostic orthographique hors ligne) ; diagnostic exploratoire : 250 mots inconnus dans 275 questions, surtout britannique / latin / jargon.
- [x] Catégories : `category_id` contrôlé (`categories_raw.csv` vérifié, 0 question sans id, bilan lues − exclues = écrites) ; pas de découpage (décision 11), `category_main` / `category_sub` supprimées. Silver : 9 colonnes, `dbt build` 18 PASS.
- [x] Connexion WSL → LM Studio (Serve on Local Network + règle de pare-feu).
- [x] Benchmark : test sur 20 questions avec Bonsai 27B / P3_choices → 17/20 au bon format, 12/20 justes, 13,1 s/appel en moyenne (rangé dans `silver/_tests_invalides/` le 24/11).
- [x] Prompts réduits à deux (décision 3, 24/11) : `P1_choices` (texte de l'ancien P3, vérifié identique sur 20 prompts) et `P2_expert` (+ rôle d'expert). Test `--limit 3` : 6/6 justes et au bon format, ≈ 18 s/appel ; `dbt build` 18 PASS.
- [x] Serveur distant (24/11) : option `--remote` de `run_benchmark.py` (`API_URL` / `API_KEY` dans `.env`). Test `--limit 10` avec Gemma-4-12b, P1 + P2 : 20/20 justes, 20/20 au bon format, 0,9 s/appel, 0 erreur (fichier rangé dans `silver/_tests_invalides/`).
- [x] Réponses brutes en bronze (décision 13) : `run_benchmark.py` → `bronze/llm_answers/*.csv` (requête + JSON tel quel) ; nouveau `src/answers_to_silver.py` → `silver/llm_answers/llm_answers.parquet`. Prompts vérifiés identiques (20/20). Test `--limit 5` Gemma : 10/10 justes, 1,2 s/appel, `dbt build` 18 PASS.
- [x] Run Gemma-4-12b **arrêté** le 25/11 à ≈ 9 h 55 (décision 18) : anciens prompts (≈ 72 % de bonnes réponses sur ≈ 3 440 questions, non comparable). Pas de relance prévue.
- [x] **Anciens prompts retirés** (décision 19, 25/11) : textes v1 supprimés de `src/prompts.py` ; les 4 runs Gemma-4-12b (6 910 lignes) restent en bronze et sont écartés en silver via `referentiels/runs_exclus.csv` (motif par run). Silver = 10 580 réponses, uniquement aux prompts du projet. `dbt build` 18 PASS.
- [x] **Projet commun avec Cécile** (25/11, décisions 15 à 18) : un seul pipeline. Prompts et ordre des choix = les siens (`P1_choices`, `P2_expert`, `P3_expert_advanced`) ; ses runs importés au lieu d'être relancés (`src/import_llm_answers.py` → `bronze/llm_answers_import/`, commit `917fbe1`, SHA-256 vérifiés) ; `src/answers_to_silver.py` note **toutes** les réponses avec nos règles (5 290 / 5 290 questions reliées, prompts vérifiés, 0 désaccord avec sa notation). Gemma 4 E2B : 54,1 % (P1), 53,9 % (P2). `dbt build` 18 PASS.
- [x] Corrections : désactivation du raisonnement (`reasoning_effort`), notation des réponses « A ».
- [x] Gold : projet dbt, `dbt build` → 18 PASS (6 modèles, 12 tests), lit uniquement silver.
- [x] Documentation projet (README, AGENTS, documentation/) et documentation dbt générée.

## En cours / à faire

- [x] Étape 07 : 8 corrections validées, reprises du silver de Cécile (`referentiels/corrections_linguistiques.csv`, trace `silver/_qualite/corrections_appliquees.csv`). Silver aligné sur le sien (5 293/5 295 identiques avant nos 5 nouvelles exclusions ; les 2 autres : espaces insécables nettoyés chez nous). `dbt build` 18 PASS.
- [x] **Gemma P3 et Ministral 3B importés** (25/11) : poussés par Cécile dans le commit `7169dbb` (le lien `0b1080c` qu'elle avait envoyé était le commit d'avant, sans les fichiers). 4 nouveaux fichiers, SHA-256 et empreintes git vérifiés ; les 3 anciens inchangés. Silver = **31 740 réponses** (6 combinaisons × 5 290), comme son OBT ; `dbt build` 18 PASS. Résultats : voir la ligne « Notation de Cécile adoptée ».
- [x] **Notation de Cécile adoptée** (décision 20, 25/11) : règle stricte, identique à la sienne (0 différence sur 31 740 réponses, justes et format). Résultats : Gemma P1 54,1 %, P2 53,9 %, P3 52,0 % ; Ministral P1 53,8 %, P2 52,5 %, P3 41,2 % (format 78,8 %). Notre ancienne règle (tolérante, Ministral P3 à 47,2 %) est copiée dans `archives/notation_tolerante/` avec un `LISEZMOI.md` pour la reprendre. `dbt build` 18 PASS.
- [x] **Gold : 7 marts, KPI de la décision 21** (25/11) : `accuracy_by_model_prompt` (+ répartition des réponses), `prompt_effect` (auto-jointure, P1→P2, P1→P3, P2→P3), `accuracy_by_category`, `category_model_gap`, `accuracy_by_difficulty` (+ lignes `all`, hasard pondéré), `accuracy_by_type`, `question_consensus`. `chance_pct` ajouté à `int_answers_enriched`. Tests renforcés (idées du gold de Cécile) : `gold_grain` (clé unique + nombre de lignes exact) et recalcul indépendant de chaque indicateur (`macros/gold_tests.sql`, 5 tests dans `tests/`), vérifiés par sabotage ; taux et temps **non arrondis** en gold (arrondi à l'affichage). `dbt build` **44 PASS**. Résultats clés : Ministral P3 perd 817 questions et en gagne 155 face à P1 ; en vrai/faux, les deux modèles font à peine mieux que le hasard (+5 points en P1), Ministral P3 fait pire (−15) ; 1 379 questions toujours réussies, 1 278 toujours ratées (dont 308 avec la même réponse fausse pour les 6).
- [ ] Étape 06 (facultative) : diagnostic linguistique propre au projet, si on veut aller au-delà des 8 corrections.
- [ ] **Valider** la décision 7 de `DECISIONS.md` (guillemets typographiques).
- [ ] (Facultatif) Bonsai en local : trop lent pour le run complet (mémoire GPU saturée, 12–18 s/appel) ; éventuel point de comparaison partiel.
- [ ] (Non bloquant, `--sample` n'est plus utilisé) bug pandas 3 de l'échantillonnage : `groupby().apply()` retire `category` et `difficulty`.
- [x] **Dashboard Streamlit** (25/11) : `src/dashboard.py`, `streamlit run src/dashboard.py`. 5 onglets (performance, influence des prompts, domaines, questions pièges, données), filtres modèle / prompt / catégorie / difficulté / type, hasard affiché, taux arrondis à l'affichage. Vérifié avec `streamlit.testing` (filtres compris), graphiques rendus et relus. `altair` ajouté à `requirements.txt`. Spécification : `specifications/DASHBOARD.md`. Habillage en dégradé de rose (thème `.streamlit/config.toml`, bandeau, cartes, onglets).
- [ ] Prévenir Cécile que l'équipe a retenu les 7 marts (et non sa proposition à 4 marts), pour un seul gold.
- [ ] Finaliser le README (captures du dashboard, résultats).
- [x] GitHub (25/11) : dépôt privé `mazar001/trivial-benchmark`, commit `afd429d` (7 marts gold) poussé sur `main`.

## Blocages et points d'attention

- **Pushs de Cécile `0b1080c` puis `7169dbb` (25/11), à arbitrer avec l'équipe** : elle a ajouté son propre projet dbt (`dbt/` : 7 vues `staging`, une OBT de 31 740 lignes en `intermediate`, 27 tests ; Gold « réservé aux futurs marts », pas encore fait) et un registre `DECISIONS.md` (DEC-001 à DEC-034). Trois écarts avec notre projet : (1) deux pipelines dbt en parallèle ; (2) notation : réglé, on a pris la sienne (décision 20) ; (3) son README ne cite plus Streamlit dans les livrables (Gold pour Power BI, Qlik…). Ses 3 fichiers déjà importés sont inchangés (SHA-256 identiques).
- **Push de Cécile `cceaa05` (25/11, « Compléter les marts Gold avec la référence du hasard et le consensus incorrect »)** : ses 7 marts, exécutés sur nos données (`int_answers_enriched` renommé avec les colonnes de son OBT), donnent **0 écart** avec nos 7 tables (effectifs exacts, taux à 1e-9 près), y compris le hasard, les lignes `all` et les 308 consensus incorrects (207 QCM, 101 vrai/faux). Les deux gold sont cohérents ; le dashboard utilise le nôtre (choix de l'utilisatrice).
- **Push de Cécile `6d17118` (25/11, « Construire et valider les sept marts Gold »)** : elle a construit ses 7 marts dans son propre dbt, sur son OBT, avec les mêmes grains et les mêmes chiffres que les nôtres (mêmes gains / pertes, mêmes 1 379 / 1 278 / 2 633). Différences : pas d'écart au hasard ni de lignes `all` chez elle ; écart Gemma − Ministral signé au lieu de meilleur / moins bon ; taux non arrondis ; 14 tests gold (grain + volume + recalcul indépendant depuis l'OBT). Aucun fichier de données modifié : pas de réimport. Deux gold en parallèle : lequel sert au rendu et au dashboard, à trancher.
- En attente de ces arbitrages : retrait de nos anciens runs (`bronze/llm_answers/`, `silver/_tests_invalides/`, `run_gemma.log`), rien n'est supprimé.

- Temps de réponse irréguliers (≈ 3–4 s ou ≈ 18–20 s pour 2 tokens) : vérifier le **GPU Offload** du modèle dans LM Studio. Cause non confirmée.
- L'IP de Windows vue de WSL peut changer au redémarrage (`ip route show default`).
- Windows ne doit pas se mettre en veille pendant un run long.
