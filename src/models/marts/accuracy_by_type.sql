-- Axe 3, réussite par type de question : une ligne par modèle x prompt x type.
-- Lignes lues : les 31 740 lignes de int_answers_enriched, sans filtre.
-- Regroupement : GROUP BY model, prompt_id, type -> 12 lignes.
-- Le hasard donne 25 % sur un QCM (4 choix) et 50 % sur un vrai/faux :
-- pct_above_chance = pct_correct - chance_pct (en points).
SELECT
    model,
    prompt_id,
    type,
    count(*) AS nb_answers,
    count_if(ai_correct) AS nb_correct,
    round(100 * avg(CAST(ai_correct AS INTEGER)), 1) AS pct_correct,
    round(avg(chance_pct), 1) AS chance_pct,
    round(100 * avg(CAST(ai_correct AS INTEGER)) - avg(chance_pct), 1) AS pct_above_chance,
    round(100 * avg(CAST(coalesce(format_ok, false) AS INTEGER)), 1) AS pct_format_ok
FROM {{ ref('int_answers_enriched') }}
GROUP BY model, prompt_id, type
ORDER BY model, prompt_id, type
