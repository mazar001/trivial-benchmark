# Spécification — Dashboard

> Version du 24/11/2026, établie à partir de ce que le pipeline produit réellement (tables gold ; prompts `P1_choices` et `P2_expert` depuis le 24/11). Non implémenté. À confronter aux échanges menés sur claude.ai (dossier cours / projet Trivial) dès qu'ils sont disponibles.

> **25/11 : gold refait en 7 marts (décision 21).** Le dashboard Streamlit reste un livrable ; ses vues sont à réorganiser selon les 4 axes : performance (`accuracy_by_model_prompt`), influence des prompts (`prompt_effect`), domaines (`accuracy_by_category`, `category_model_gap`, `accuracy_by_difficulty`, `accuracy_by_type`), questions pièges (`question_consensus`, remplace la vue « explorer les erreurs » ou la complète). Attention : `accuracy_by_difficulty` contient des lignes `type = 'all'`, à filtrer avant d'additionner.

## Objectif

Répondre à deux questions à partir de la couche gold :
1. **Le modèle est-il bon au Trivial Poursuite ?** (et mieux que le hasard ?)
2. **Où se trompe-t-il ?** (catégories, difficultés, types de questions)

Public : le correcteur et l'équipe, en local.

## Données

Lecture seule de `gold/warehouse.duckdb` (produit par `dbt build`) :

| Table / vue | Vue du dashboard |
|-------------|------------------|
| `accuracy_by_model_prompt` | 1. Indicateurs clés |
| `accuracy_by_category` | 2. Score par catégorie |
| `accuracy_by_difficulty` | 3. Difficulté × type |
| `int_answers_enriched` | 4. Explorer les erreurs, filtres |

## Vues retenues

### 1. Indicateurs clés
Questions posées, % de bonnes réponses, % de réponses au bon format, temps moyen par réponse.

### 2. Score par catégorie
Barres horizontales triées par % de bonnes réponses, une barre par catégorie officielle (`category`, 24 catégories, pas de regroupement). Le nombre de réponses est affiché ; les catégories sous **10 réponses** sont signalées comme peu fiables.

### 3. Difficulté × type
% de bonnes réponses par difficulté (easy → hard), séparé QCM / vrai-faux, avec la **ligne du hasard** (25 % / 50 %) et `pct_above_chance`.

### 4. Explorer les erreurs
Tableau des questions ratées : catégorie, difficulté, question, bonne réponse, réponse du modèle, format respecté ou non. Filtrable et triable.

Filtres communs (barre latérale) : catégorie, difficulté, type.

## Évolution prévue

**25/11 : projet commun** (décisions 15 à 18) : 3 prompts (`P1_choices`, `P2_expert`, `P3_expert_advanced`) et 2 modèles comparables, tous deux importés le 25/11 (Gemma 4 E2B et Ministral 3B : 6 combinaisons × 5 290 questions). Le run Gemma-4-12b arrêté (anciens prompts) n'est plus en silver (décision 19) : rien à masquer.

**Comparaison des prompts / modèles** : n'apparaît que si `silver/llm_answers/` contient plus d'un prompt ou d'un modèle (`--prompts P1_choices P2_expert`, plusieurs `--model`). Les filtres modèle et prompt s'ajoutent alors automatiquement. Avec le run prévu (P1_choices et P2_expert), cette vue devient utile : effet du rôle d'expert (P2 − P1). À intégrer aux vues retenues, à valider.

## Contraintes techniques

- `src/dashboard.py`, lancé par `streamlit run src/dashboard.py` (comme le projet de cours).
- Connexions DuckDB **courtes et en lecture seule** : `dbt build` reste possible pendant que le dashboard tourne. Résultats mis en cache, bouton « Recharger les données ».
- Filtres traduits en requêtes paramétrées.
- Ajouter `altair` (graphiques) à `requirements.txt` si utilisé.
