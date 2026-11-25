-- Axe 2, influence des prompts : une ligne par modèle x couple de prompts.
-- On compare deux prompts SUR LES MÊMES QUESTIONS (comparaison appariée) :
--   P1 -> P2 : effet du rôle d'expert
--   P1 -> P3 : effet du rôle d'expert + de la consigne d'analyse
--   P2 -> P3 : effet de la consigne d'analyse seule
--
-- Lignes lues : int_answers_enriched, deux fois (auto-jointure).
--   ref  = la réponse avec le prompt de départ
--   comp = la réponse à la même question, du même modèle, avec le prompt comparé
-- Après la jointure : 2 modèles x 3 couples x 5 290 questions = 31 740 lignes.
-- Regroupement : GROUP BY model, prompt_ref, prompt_compared -> 6 lignes.
--
-- Question gagnée = fausse avec le prompt de départ, juste avec le prompt comparé.
-- Question perdue = juste avec le prompt de départ, fausse avec le prompt comparé.
-- Contrôle (tests/assert_prompt_effect_coherent.sql) :
--   gagnées + perdues + justes des 2 côtés + fausses des 2 côtés = nb_questions
--   delta_pct_correct = 100 x (gagnées - perdues) / nb_questions
WITH prompt_pairs AS (
    -- Les 3 couples comparés, écrits explicitement.
    SELECT *
    FROM (
        VALUES
            ('P1_choices', 'P2_expert'),
            ('P1_choices', 'P3_expert_advanced'),
            ('P2_expert', 'P3_expert_advanced')
    ) AS pairs (prompt_ref, prompt_compared)
),

paired AS (
    SELECT
        ref.model,
        pairs.prompt_ref,
        pairs.prompt_compared,
        coalesce(ref.ai_correct, false) AS correct_ref,
        coalesce(comp.ai_correct, false) AS correct_compared,
        coalesce(ref.format_ok, false) AS format_ok_ref,
        coalesce(comp.format_ok, false) AS format_ok_compared,
        ref.response_time_s AS time_ref_s,
        comp.response_time_s AS time_compared_s
    FROM {{ ref('int_answers_enriched') }} AS ref
    INNER JOIN prompt_pairs AS pairs
        ON ref.prompt_id = pairs.prompt_ref
    INNER JOIN {{ ref('int_answers_enriched') }} AS comp
        ON comp.question_id = ref.question_id
        AND comp.model = ref.model
        AND comp.prompt_id = pairs.prompt_compared
)

SELECT
    model,
    prompt_ref,
    prompt_compared,
    count(*) AS nb_questions,
    -- Réussite
    round(100 * avg(CAST(correct_ref AS INTEGER)), 1) AS pct_correct_ref,
    round(100 * avg(CAST(correct_compared AS INTEGER)), 1) AS pct_correct_compared,
    round(
        100 * (avg(CAST(correct_compared AS INTEGER)) - avg(CAST(correct_ref AS INTEGER))),
        1
    ) AS delta_pct_correct,
    -- Questions gagnées, perdues, inchangées
    count_if(NOT correct_ref AND correct_compared) AS nb_gained,
    count_if(correct_ref AND NOT correct_compared) AS nb_lost,
    count_if(NOT correct_ref AND correct_compared)
        - count_if(correct_ref AND NOT correct_compared) AS nb_net,
    count_if(correct_ref AND correct_compared) AS nb_both_correct,
    count_if(NOT correct_ref AND NOT correct_compared) AS nb_both_wrong,
    -- Conformité au format
    round(100 * avg(CAST(format_ok_ref AS INTEGER)), 1) AS pct_format_ok_ref,
    round(100 * avg(CAST(format_ok_compared AS INTEGER)), 1) AS pct_format_ok_compared,
    round(
        100 * (avg(CAST(format_ok_compared AS INTEGER)) - avg(CAST(format_ok_ref AS INTEGER))),
        1
    ) AS delta_pct_format_ok,
    -- Temps de réponse
    round(avg(time_ref_s), 2) AS avg_time_ref_s,
    round(avg(time_compared_s), 2) AS avg_time_compared_s,
    round(avg(time_compared_s) - avg(time_ref_s), 2) AS delta_avg_time_s
FROM paired
GROUP BY model, prompt_ref, prompt_compared
ORDER BY model, prompt_ref, prompt_compared
