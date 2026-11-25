-- Axe 3, réussite par type de question : une ligne par modèle x prompt x type.
-- Lignes lues : les 31 740 lignes de int_answers_enriched, sans filtre.
-- Regroupement : GROUP BY model, prompt_id, type -> 12 lignes.
-- Le hasard donne 25 % sur un QCM (4 choix) et 50 % sur un vrai/faux :
-- pct_above_chance = pct_correct - chance_pct (en points).
-- Taux non arrondis : l'arrondi se fait à l'affichage (dashboard).
SELECT
    model,
    prompt_id,
    type,
    count(*) AS nb_answers,
    count_if(ai_correct) AS nb_correct,
    100.0 * count_if(ai_correct) / count(*) AS pct_correct,
    avg(chance_pct) AS chance_pct,
    100.0 * count_if(ai_correct) / count(*) - avg(chance_pct) AS pct_above_chance,
    100.0 * count_if(coalesce(format_ok, false)) / count(*) AS pct_format_ok
FROM {{ ref('int_answers_enriched') }}
GROUP BY model, prompt_id, type
ORDER BY model, prompt_id, type
