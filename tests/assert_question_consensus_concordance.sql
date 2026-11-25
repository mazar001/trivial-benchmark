-- Axe 4 : question_consensus recalculé d'une autre façon, puis comparé.
-- 1. Chaque question a une réponse de chacune des configurations modèle x prompt
--    (idée reprise de Cécile) : sinon une question « toujours ratée » pourrait
--    simplement manquer de réponses.
-- 2. Nombre de configurations justes recompté en configurations distinctes, et
--    statut recalculé avec bool_and / bool_or au lieu d'un CASE sur le compte.
-- 3. La réponse fausse la plus donnée ne peut pas l'être plus souvent qu'il n'y a
--    de réponses fausses, et une question toujours réussie n'en a pas.
-- Le test échoue s'il renvoie au moins une ligne.
WITH nb_configurations AS (
    SELECT count(DISTINCT (model, prompt_id)) AS n
    FROM {{ ref('int_answers_enriched') }}
),

expected AS (
    SELECT
        question_id,
        count(DISTINCT (model, prompt_id)) AS nb_configurations,
        count(DISTINCT (model, prompt_id)) FILTER (WHERE ai_correct) AS nb_correct_configurations,
        CASE
            WHEN bool_and(ai_correct) THEN 'toujours réussie'
            WHEN NOT bool_or(ai_correct) THEN 'toujours ratée'
            ELSE 'mixte'
        END AS status
    FROM {{ ref('int_answers_enriched') }}
    GROUP BY question_id
)

SELECT coalesce(e.question_id, o.question_id) AS question_id, 'valeur différente' AS controle
FROM expected AS e
FULL OUTER JOIN {{ ref('question_consensus') }} AS o
    USING (question_id)
WHERE e.nb_configurations IS DISTINCT FROM o.nb_configurations
    OR e.nb_correct_configurations IS DISTINCT FROM o.nb_correct_configurations
    OR e.status IS DISTINCT FROM o.status

UNION ALL

SELECT o.question_id, 'configuration manquante'
FROM {{ ref('question_consensus') }} AS o
CROSS JOIN nb_configurations AS c
WHERE o.nb_configurations <> c.n

UNION ALL

SELECT question_id, 'réponse fausse la plus donnée incohérente'
FROM {{ ref('question_consensus') }}
WHERE nb_most_common_wrong_answer > nb_configurations - nb_correct_configurations
    OR (status = 'toujours réussie' AND most_common_wrong_answer IS NOT NULL)
