-- Axe 3, écart entre modèles par catégorie : une ligne par prompt x catégorie.
-- Quel modèle est le plus performant dans chaque domaine, et de combien ?
--
-- Lignes lues : les 144 lignes de accuracy_by_category (6 configurations x 24
-- catégories), pour reprendre exactement les mêmes taux.
-- Étape 1, classement (sans regroupement) : dans chaque prompt x catégorie, les
--   modèles sont numérotés du meilleur au moins bon ; en cas d'égalité, départage
--   par le nom du modèle (critère déterministe).
-- Étape 2, regroupement : GROUP BY prompt_id, category -> 72 lignes.
-- Le projet compte 2 modèles : best = rang 1, worst = rang 2.
-- Taux non arrondis : l'arrondi se fait à l'affichage (dashboard).
WITH ranked AS (
    SELECT
        prompt_id,
        category,
        model,
        nb_answers,
        nb_correct,
        pct_correct,
        row_number() OVER (
            PARTITION BY prompt_id, category
            ORDER BY nb_correct DESC, model
        ) AS model_rank
    FROM {{ ref('accuracy_by_category') }}
)

SELECT
    prompt_id,
    category,
    max(nb_answers) AS nb_questions,
    max(CASE WHEN model_rank = 1 THEN model END) AS best_model,
    max(CASE WHEN model_rank = 1 THEN pct_correct END) AS pct_correct_best,
    max(CASE WHEN model_rank = 2 THEN model END) AS worst_model,
    max(CASE WHEN model_rank = 2 THEN pct_correct END) AS pct_correct_worst,
    -- Écart calculé sur les nombres de bonnes réponses (même dénominateur pour les deux).
    100.0 * (
        max(CASE WHEN model_rank = 1 THEN nb_correct END)
        - max(CASE WHEN model_rank = 2 THEN nb_correct END)
    ) / max(nb_answers) AS gap_pct_points,
    min(nb_correct) = max(nb_correct) AS is_tie
FROM ranked
GROUP BY prompt_id, category
ORDER BY prompt_id, gap_pct_points DESC, category
