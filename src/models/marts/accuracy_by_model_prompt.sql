-- Score global de chaque modèle pour chaque prompt :
-- taux de bonnes réponses, respect du format, temps de réponse
SELECT
    model,
    prompt_id,
    count(*) AS nb_answers,
    count_if(ai_correct) AS nb_correct,
    round(100 * avg(CAST(ai_correct AS INTEGER)), 1) AS pct_correct,
    round(100 * avg(CAST(format_ok AS INTEGER)), 1) AS pct_format_ok,
    count_if(has_error) AS nb_errors,
    round(avg(response_time_s), 2) AS avg_response_time_s,
    round(median(response_time_s), 2) AS median_response_time_s,
    round(max(response_time_s), 2) AS max_response_time_s
FROM {{ ref('int_answers_enriched') }}
GROUP BY model, prompt_id
ORDER BY pct_correct DESC, model, prompt_id
