-- Axe 4 (idée reprise de la proposition de Cécile) : chaque question doit avoir
-- une réponse de chacune des configurations modèle x prompt. Sinon, une question
-- « toujours ratée » pourrait simplement manquer de réponses.
-- Le test échoue s'il renvoie au moins une ligne.
SELECT q.question_id, q.nb_configurations
FROM {{ ref('question_consensus') }} AS q
WHERE q.nb_configurations <> (
    SELECT count(DISTINCT model || '|' || prompt_id)
    FROM {{ ref('int_answers_enriched') }}
)
