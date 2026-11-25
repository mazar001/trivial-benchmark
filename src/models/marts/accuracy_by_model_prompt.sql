-- Axe 1, performance des modèles et des prompts : une ligne par modèle x prompt.
-- Taux de réussite, taux de conformité (format), temps de réponse,
-- et répartition des réponses en trois groupes qui ne se recoupent pas :
--   juste                 = au bon format et égale à la réponse attendue
--   fausse au bon format  = lettre (ou True/False) valide, mais pas la bonne
--   hors format           = tout le reste (phrase, réponse vide, erreur)
-- Une réponse juste est toujours au bon format (décision 20), donc
-- nb_correct + nb_incorrect_format_ok + nb_out_of_format = nb_answers.
SELECT
    model,
    prompt_id,
    count(*) AS nb_answers,
    count_if(ai_correct) AS nb_correct,
    count_if(coalesce(format_ok, false) AND NOT ai_correct) AS nb_incorrect_format_ok,
    count_if(NOT coalesce(format_ok, false)) AS nb_out_of_format,
    round(100 * avg(CAST(ai_correct AS INTEGER)), 1) AS pct_correct,
    round(100 * avg(CAST(coalesce(format_ok, false) AND NOT ai_correct AS INTEGER)), 1)
        AS pct_incorrect_format_ok,
    round(100 * avg(CAST(NOT coalesce(format_ok, false) AS INTEGER)), 1) AS pct_out_of_format,
    round(100 * avg(CAST(coalesce(format_ok, false) AS INTEGER)), 1) AS pct_format_ok,
    count_if(has_error) AS nb_errors,
    round(avg(response_time_s), 2) AS avg_response_time_s,
    round(median(response_time_s), 2) AS median_response_time_s,
    round(max(response_time_s), 2) AS max_response_time_s
FROM {{ ref('int_answers_enriched') }}
GROUP BY model, prompt_id
ORDER BY pct_correct DESC, model, prompt_id
