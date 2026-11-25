-- Axe 3 : pour chaque configuration, les types et les difficultés couvrent
-- toutes les réponses, et chaque ligne 'all' = la somme de ses deux types.
-- Le test échoue s'il renvoie au moins une ligne.
WITH total AS (
    SELECT model, prompt_id, nb_answers
    FROM {{ ref('accuracy_by_model_prompt') }}
),
by_type AS (
    SELECT model, prompt_id, sum(nb_answers) AS nb_answers
    FROM {{ ref('accuracy_by_type') }}
    GROUP BY model, prompt_id
),
by_difficulty_all AS (
    SELECT model, prompt_id, sum(nb_answers) AS nb_answers
    FROM {{ ref('accuracy_by_difficulty') }}
    WHERE type = 'all'
    GROUP BY model, prompt_id
),
all_vs_types AS (
    SELECT model, prompt_id, difficulty,
        sum(CASE WHEN type = 'all' THEN nb_answers ELSE 0 END) AS nb_all,
        sum(CASE WHEN type <> 'all' THEN nb_answers ELSE 0 END) AS nb_types
    FROM {{ ref('accuracy_by_difficulty') }}
    GROUP BY model, prompt_id, difficulty
)
SELECT t.model, t.prompt_id, 'total par type' AS controle
FROM total AS t
LEFT JOIN by_type AS bt USING (model, prompt_id)
WHERE bt.nb_answers IS DISTINCT FROM t.nb_answers
UNION ALL
SELECT t.model, t.prompt_id, 'total par difficulté'
FROM total AS t
LEFT JOIN by_difficulty_all AS bd USING (model, prompt_id)
WHERE bd.nb_answers IS DISTINCT FROM t.nb_answers
UNION ALL
SELECT model, prompt_id, 'ligne all <> somme des types (' || difficulty || ')'
FROM all_vs_types
WHERE nb_all <> nb_types
