-- Taux de bonnes réponses par difficulté et type de question.
-- Le hasard donne 25 % sur les questions à 4 choix et 50 % sur les vrai/faux :
-- la colonne pct_above_chance indique l'écart par rapport au hasard.
SELECT
    model,
    prompt_id,
    difficulty,
    type,
    count(*) AS nb_answers,
    count_if(ai_correct) AS nb_correct,
    round(100 * avg(CAST(ai_correct AS INTEGER)), 1) AS pct_correct,
    round(
        100 * avg(CAST(ai_correct AS INTEGER))
        - CASE WHEN type = 'boolean' THEN 50 ELSE 25 END,
        1
    ) AS pct_above_chance
FROM {{ ref('int_answers_enriched') }}
GROUP BY model, prompt_id, difficulty, type
ORDER BY
    model,
    prompt_id,
    CASE difficulty WHEN 'easy' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
    type
