-- Axe 4, questions pièges : une ligne par question.
-- Combien des 6 configurations (2 modèles x 3 prompts) réussissent chaque question ?
--
-- Lignes lues : les 31 740 lignes de int_answers_enriched, sans filtre.
-- Regroupement : GROUP BY question_id (et ses colonnes descriptives, qui ont une
--   seule valeur par question) -> 5 290 lignes.
-- Jointure : LEFT JOIN avec la réponse fausse la plus donnée (wrong_answers),
--   ON question_id. LEFT, car une question toujours réussie n'a pas de réponse
--   fausse : elle garde sa ligne, avec une valeur vide.
--
-- L'ordre des choix est le même pour les 6 configurations (une seule lettre attendue
-- par question, vérifié le 25/11) : une lettre désigne donc la même proposition partout.
-- Contrôle (tests/assert_question_consensus_complete.sql) : chaque question a reçu
-- une réponse de chacune des configurations, sinon le statut serait faux.
WITH wrong_answers AS (
    -- Réponses fausses mais au bon format, comptées par question ;
    -- rang 1 = la plus fréquente (départage par la réponse elle-même).
    SELECT
        question_id,
        ai_answer,
        count(*) AS nb_times,
        row_number() OVER (
            PARTITION BY question_id
            ORDER BY count(*) DESC, ai_answer
        ) AS answer_rank
    FROM {{ ref('int_answers_enriched') }}
    WHERE format_ok AND NOT ai_correct
    GROUP BY question_id, ai_answer
),

per_question AS (
    SELECT
        question_id,
        category,
        difficulty,
        type,
        question,
        correct_answer,
        expected_letter,
        count(*) AS nb_configurations,
        count_if(ai_correct) AS nb_correct_configurations,
        string_agg(
            split_part(model, '/', 2) || ' ' || split_part(prompt_id, '_', 1),
            ', '
            ORDER BY model, prompt_id
        ) FILTER (WHERE ai_correct) AS correct_configurations
    FROM {{ ref('int_answers_enriched') }}
    GROUP BY question_id, category, difficulty, type, question, correct_answer, expected_letter
)

SELECT
    q.question_id,
    q.category,
    q.difficulty,
    q.type,
    q.question,
    q.correct_answer,
    q.expected_letter,
    q.nb_configurations,
    q.nb_correct_configurations,
    CASE
        WHEN q.nb_correct_configurations = q.nb_configurations THEN 'toujours réussie'
        WHEN q.nb_correct_configurations = 0 THEN 'toujours ratée'
        ELSE 'mixte'
    END AS status,
    q.correct_configurations,
    w.ai_answer AS most_common_wrong_answer,
    w.nb_times AS nb_most_common_wrong_answer
FROM per_question AS q
LEFT JOIN wrong_answers AS w
    ON w.question_id = q.question_id
    AND w.answer_rank = 1
ORDER BY q.nb_correct_configurations, q.category, q.question_id
