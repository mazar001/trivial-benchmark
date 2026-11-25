-- Axe 2 : prompt_effect recalculé d'une autre façon, puis comparé.
-- 1. Sans auto-jointure : on pivote les réponses (une ligne par modèle x question,
--    une colonne juste/faux par prompt), puis on compte gagnées, perdues, inchangées.
-- 2. Les taux avant / après doivent être ceux de accuracy_by_model_prompt
--    (même réussite, même conformité, même temps moyen).
-- 3. Les 4 cas couvrent toutes les questions, et
--    delta_pct_correct = 100 x (gagnées - perdues) / nb_questions.
-- Le test échoue s'il renvoie au moins une ligne.
WITH per_question AS (
    SELECT
        model,
        question_id,
        bool_or(ai_correct) FILTER (WHERE prompt_id = 'P1_choices') AS p1,
        bool_or(ai_correct) FILTER (WHERE prompt_id = 'P2_expert') AS p2,
        bool_or(ai_correct) FILTER (WHERE prompt_id = 'P3_expert_advanced') AS p3
    FROM {{ ref('int_answers_enriched') }}
    GROUP BY model, question_id
),

pairs AS (
    SELECT model, 'P1_choices' AS prompt_ref, 'P2_expert' AS prompt_compared, p1 AS before, p2 AS after
    FROM per_question
    UNION ALL
    SELECT model, 'P1_choices', 'P3_expert_advanced', p1, p3 FROM per_question
    UNION ALL
    SELECT model, 'P2_expert', 'P3_expert_advanced', p2, p3 FROM per_question
),

expected AS (
    SELECT
        model,
        prompt_ref,
        prompt_compared,
        count(*) AS nb_questions,
        sum(CASE WHEN NOT before AND after THEN 1 ELSE 0 END) AS nb_gained,
        sum(CASE WHEN before AND NOT after THEN 1 ELSE 0 END) AS nb_lost,
        sum(CASE WHEN before AND after THEN 1 ELSE 0 END) AS nb_both_correct,
        sum(CASE WHEN NOT before AND NOT after THEN 1 ELSE 0 END) AS nb_both_wrong
    FROM pairs
    GROUP BY model, prompt_ref, prompt_compared
)

SELECT e.model, e.prompt_ref, e.prompt_compared, 'transitions différentes' AS controle
FROM expected AS e
FULL OUTER JOIN {{ ref('prompt_effect') }} AS o
    USING (model, prompt_ref, prompt_compared)
WHERE e.nb_questions IS DISTINCT FROM o.nb_questions
    OR e.nb_gained IS DISTINCT FROM o.nb_gained
    OR e.nb_lost IS DISTINCT FROM o.nb_lost
    OR e.nb_both_correct IS DISTINCT FROM o.nb_both_correct
    OR e.nb_both_wrong IS DISTINCT FROM o.nb_both_wrong

UNION ALL

SELECT o.model, o.prompt_ref, o.prompt_compared, 'incohérent avec accuracy_by_model_prompt'
FROM {{ ref('prompt_effect') }} AS o
LEFT JOIN {{ ref('accuracy_by_model_prompt') }} AS ref
    ON ref.model = o.model AND ref.prompt_id = o.prompt_ref
LEFT JOIN {{ ref('accuracy_by_model_prompt') }} AS comp
    ON comp.model = o.model AND comp.prompt_id = o.prompt_compared
WHERE o.nb_questions IS DISTINCT FROM ref.nb_answers
    OR o.nb_questions IS DISTINCT FROM comp.nb_answers
    OR NOT coalesce(abs(o.pct_correct_ref - ref.pct_correct) <= 1e-9, false)
    OR NOT coalesce(abs(o.pct_correct_compared - comp.pct_correct) <= 1e-9, false)
    OR NOT coalesce(abs(o.pct_format_ok_ref - ref.pct_format_ok) <= 1e-9, false)
    OR NOT coalesce(abs(o.pct_format_ok_compared - comp.pct_format_ok) <= 1e-9, false)
    OR NOT coalesce(abs(o.avg_time_ref_s - ref.avg_response_time_s) <= 1e-9, false)
    OR NOT coalesce(abs(o.avg_time_compared_s - comp.avg_response_time_s) <= 1e-9, false)

UNION ALL

SELECT model, prompt_ref, prompt_compared, 'calcul interne incohérent'
FROM {{ ref('prompt_effect') }}
WHERE nb_gained + nb_lost + nb_both_correct + nb_both_wrong <> nb_questions
    OR nb_net <> nb_gained - nb_lost
    OR abs(delta_pct_correct - 100.0 * (nb_gained - nb_lost) / nb_questions) > 1e-9
    OR abs(delta_pct_correct - (pct_correct_compared - pct_correct_ref)) > 1e-9
    OR abs(delta_pct_format_ok - (pct_format_ok_compared - pct_format_ok_ref)) > 1e-9
    OR abs(delta_avg_time_s - (avg_time_compared_s - avg_time_ref_s)) > 1e-9
