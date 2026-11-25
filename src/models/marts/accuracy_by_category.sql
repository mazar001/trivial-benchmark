-- Taux de bonnes réponses par catégorie, pour chaque modèle et prompt
SELECT
    model,
    prompt_id,
    category,
    count(*) AS nb_answers,
    count_if(ai_correct) AS nb_correct,
    round(100 * avg(CAST(ai_correct AS INTEGER)), 1) AS pct_correct
FROM {{ ref('int_answers_enriched') }}
GROUP BY model, prompt_id, category
ORDER BY model, prompt_id, pct_correct DESC, category
