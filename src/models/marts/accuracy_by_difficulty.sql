-- Axe 3, réussite par difficulté : une ligne par modèle x prompt x difficulté x type,
-- plus une ligne type = 'all' par difficulté (tous types confondus).
--
-- Lignes lues : les 31 740 lignes de int_answers_enriched, sans filtre.
-- Regroupement : deux regroupements dans la même requête (GROUPING SETS) :
--   (model, prompt_id, difficulty, type) -> 36 lignes, par type
--   (model, prompt_id, difficulty)       -> 18 lignes, type = 'all'
--
-- Pourquoi la ligne 'all' a son propre hasard : les difficultés n'ont pas la même
-- part de vrai/faux (359 en easy, 97 en hard). chance_pct est donc la moyenne du
-- hasard de ses questions (25 % par QCM, 50 % par vrai/faux), pas un 25 % fixe.
--
-- Attention : les lignes 'all' recomptent les mêmes réponses que les lignes par type.
-- Filtrer sur type avant d'additionner.
-- Taux non arrondis : l'arrondi se fait à l'affichage (dashboard).
SELECT
    model,
    prompt_id,
    difficulty,
    CASE WHEN grouping(type) = 1 THEN 'all' ELSE type END AS type,
    count(*) AS nb_answers,
    count_if(ai_correct) AS nb_correct,
    100.0 * count_if(ai_correct) / count(*) AS pct_correct,
    avg(chance_pct) AS chance_pct,
    100.0 * count_if(ai_correct) / count(*) - avg(chance_pct) AS pct_above_chance
FROM {{ ref('int_answers_enriched') }}
GROUP BY GROUPING SETS (
    (model, prompt_id, difficulty, type),
    (model, prompt_id, difficulty)
)
ORDER BY
    model,
    prompt_id,
    CASE difficulty WHEN 'easy' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
    CASE WHEN grouping(type) = 1 THEN 3 WHEN type = 'multiple' THEN 1 ELSE 2 END
