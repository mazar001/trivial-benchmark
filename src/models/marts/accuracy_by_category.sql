-- Axe 3, réussite par catégorie (et par catégorie x prompt) : une ligne par
-- modèle x prompt x catégorie. Lignes lues : les 31 740 lignes de int_answers_enriched.
-- Regroupement : GROUP BY model, prompt_id, category -> 144 lignes (6 x 24).
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
