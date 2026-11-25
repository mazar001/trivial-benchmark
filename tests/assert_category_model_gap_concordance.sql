-- Axe 3 : category_model_gap recalculé directement depuis int_answers_enriched
-- (sans passer par accuracy_by_category ni par un classement), puis comparé :
-- meilleur taux = taux maximal, autre taux = taux minimal, écart = différence,
-- égalité si les deux modèles ont autant de bonnes réponses, et le modèle désigné
-- comme meilleur a bien le plus de bonnes réponses.
-- Le test échoue s'il renvoie au moins une ligne.
WITH per_model AS (
    SELECT
        prompt_id,
        category,
        model,
        sum(1) AS nb_answers,
        sum(CASE WHEN ai_correct THEN 1 ELSE 0 END) AS nb_correct
    FROM {{ ref('int_answers_enriched') }}
    GROUP BY prompt_id, category, model
),

expected AS (
    SELECT
        prompt_id,
        category,
        max(nb_answers) AS nb_questions,
        100.0 * max(nb_correct) / max(nb_answers) AS pct_best,
        100.0 * min(nb_correct) / max(nb_answers) AS pct_worst,
        100.0 * (max(nb_correct) - min(nb_correct)) / max(nb_answers) AS gap,
        max(nb_correct) = min(nb_correct) AS is_tie,
        max(nb_correct) AS nb_correct_best
    FROM per_model
    GROUP BY prompt_id, category
)

SELECT coalesce(e.prompt_id, o.prompt_id) AS prompt_id, coalesce(e.category, o.category) AS category
FROM expected AS e
FULL OUTER JOIN {{ ref('category_model_gap') }} AS o
    USING (prompt_id, category)
LEFT JOIN per_model AS best
    ON best.prompt_id = o.prompt_id
    AND best.category = o.category
    AND best.model = o.best_model
WHERE e.nb_questions IS DISTINCT FROM o.nb_questions
    OR NOT coalesce(abs(o.pct_correct_best - e.pct_best) <= 1e-9, false)
    OR NOT coalesce(abs(o.pct_correct_worst - e.pct_worst) <= 1e-9, false)
    OR NOT coalesce(abs(o.gap_pct_points - e.gap) <= 1e-9, false)
    OR o.is_tie IS DISTINCT FROM e.is_tie
    OR best.nb_correct IS DISTINCT FROM e.nb_correct_best
    OR o.best_model = o.worst_model
