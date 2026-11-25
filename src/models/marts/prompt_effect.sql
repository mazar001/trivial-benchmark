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
-- Taux (%) et temps (s) non arrondis : l'arrondi se fait à l'affichage (dashboard).
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
    100.0 * count_if(correct_ref) / count(*) AS pct_correct_ref,
    100.0 * count_if(correct_compared) / count(*) AS pct_correct_compared,
    100.0 * count_if(correct_compared) / count(*)
        - 100.0 * count_if(correct_ref) / count(*) AS delta_pct_correct,
    -- Questions gagnées, perdues, inchangées
    count_if(NOT correct_ref AND correct_compared) AS nb_gained,
    count_if(correct_ref AND NOT correct_compared) AS nb_lost,
    count_if(NOT correct_ref AND correct_compared)
        - count_if(correct_ref AND NOT correct_compared) AS nb_net,
    count_if(correct_ref AND correct_compared) AS nb_both_correct,
    count_if(NOT correct_ref AND NOT correct_compared) AS nb_both_wrong,
    -- Conformité au format
    100.0 * count_if(format_ok_ref) / count(*) AS pct_format_ok_ref,
    100.0 * count_if(format_ok_compared) / count(*) AS pct_format_ok_compared,
    100.0 * count_if(format_ok_compared) / count(*)
        - 100.0 * count_if(format_ok_ref) / count(*) AS delta_pct_format_ok,
    -- Temps de réponse
    avg(time_ref_s) AS avg_time_ref_s,
    avg(time_compared_s) AS avg_time_compared_s,
    avg(time_compared_s) - avg(time_ref_s) AS delta_avg_time_s
FROM paired
GROUP BY model, prompt_ref, prompt_compared
ORDER BY model, prompt_ref, prompt_compared
