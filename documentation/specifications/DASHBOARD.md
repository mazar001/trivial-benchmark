# Spécification — Dashboard

> Version du 25/11/2026 : **implémenté** dans `src/dashboard.py`, sur les 7 tables gold de la décision 21.

## Objectif

Répondre aux 4 axes des KPI à partir de la couche gold :
1. **Performance** : quel modèle et quel prompt choisir ?
2. **Influence des prompts** : le rôle d'expert ou la consigne d'analyse aident-ils ?
3. **Domaines** : où les modèles sont-ils forts ou faibles (catégorie, difficulté, type), et mieux que le hasard ?
4. **Questions pièges** : quelles questions sont ratées par tout le monde ?

Public : le correcteur et l'équipe, en local, et la soutenance.

## Lancement

```bash
source .venv/bin/activate
streamlit run src/dashboard.py        # depuis la racine du projet, après dbt build
```

## Données

Lecture seule de `gold/warehouse.duckdb` :

| Onglet | Tables |
|--------|--------|
| 📊 Performance | `accuracy_by_model_prompt` (+ `accuracy_by_type` pour le taux du hasard) |
| 🧪 Influence des prompts | `prompt_effect` |
| 🗂️ Domaines | `accuracy_by_category`, `category_model_gap`, `accuracy_by_difficulty`, `accuracy_by_type` |
| 🪤 Questions pièges | `question_consensus` |
| 📋 Données | les 7 tables, téléchargeables en CSV |

## Filtres

**Barre latérale** (vide = tout) : modèles, prompts, catégories, difficultés, types de question. Chaque filtre s'applique aux tables qui ont la colonne ; sous chaque vue, une ligne rappelle la table lue et les filtres appliqués. Boutons « Recharger » (après un `dbt build`) et « Réinitialiser ».

**Dans les onglets** : couples de prompts (P1→P2, P1→P3, P2→P3) ; prompt affiché et modèle de la carte catégorie × prompt (Domaines) ; difficulté tous types confondus ou par type ; statut, nombre de configurations réussies et recherche dans le texte (Questions pièges) ; application ou non des filtres (Données).

## Vues

| Onglet | Contenu |
|--------|---------|
| Performance | 4 indicateurs (meilleure et moins bonne configuration, conformité la plus basse, taux du hasard) ; réussite par prompt et modèle avec la ligne du hasard ; temps moyen ; répartition juste / fausse au bon format / hors format |
| Influence des prompts | réussite après et écart par couple ; barres divergentes questions perdues / gagnées ; tableau détaillé |
| Domaines | catégories : un point par modèle, trait = écart, tri par taux moyen ; meilleur modèle par catégorie ; carte catégorie × prompt. Difficulté et type : barres par modèle, trait blanc cerclé = hasard |
| Questions pièges | toujours réussies / toujours ratées / même réponse fausse ; distribution 0–6 par difficulté ; explorateur de questions téléchargeable |
| Données | table brute (taux non arrondis), téléchargeable |

## Choix de présentation

- **Thème en dégradé de rose** (25/11, demande de l'utilisatrice) : `.streamlit/config.toml` (couleurs de base) et feuille de style dans `src/dashboard.py` (bandeau en dégradé, cartes d'indicateurs, onglets, encadrés « À retenir »).
- **Une couleur par modèle, fixe** (Gemma rose foncé `#880e4f`, Ministral rose `#f06292`) : un filtre ne change jamais la couleur d'un modèle. Les deux roses diffèrent fortement en luminosité (écart OKLab ≈ 28, cible ≥ 8), donc restent distinguables pour les daltoniens. Gagnées / perdues : rose / violet ; cartes et répartitions : dégradé de rose ; hasard : trait blanc cerclé.
- **Taux arrondis à l'affichage seulement** (gold les garde non arrondis), format français (virgule, espace des milliers).
- **Hasard toujours visible** là où il compte : ligne pointillée (performance), trait blanc cerclé (difficulté, type).
- Connexions DuckDB **courtes et en lecture seule**, résultats en cache : `dbt build` reste possible pendant que le dashboard tourne. Requêtes paramétrées pour les filtres.
- Graphiques **Altair** (comme le projet de cours).

## Vérification (25/11)

Exécuté sans erreur avec `streamlit.testing` (tous les onglets, puis filtres Ministral + vrai/faux + Science & Nature, prompt P3, difficulté par type, réinitialisation) ; les 9 graphiques ont été rendus en image et relus ; serveur lancé, `/_stcore/health` répond `ok`.
