-- Chaque réponse jointe à sa question (catégorie, difficulté, type),
-- avec un indicateur "le modèle a respecté le format demandé".
-- Tous les prompts (src/prompts.py) demandent une lettre A-D (QCM)
-- ou True/False (vrai/faux). Règle stricte de Cécile (décision 20) : la réponse,
-- sans les espaces autour, doit être exactement l'une de ces valeurs.
SELECT
    a.question_id,
    a.model,
    a.prompt_id,
    q.category,
    q.difficulty,
    q.type,
    q.question,
    q.correct_answer,
    a.expected_letter,
    a.ai_answer,
    a.ai_correct,
    a.has_error,
    a.response_time_s,
    a.completion_tokens,
    CASE
        WHEN q.type = 'multiple'
            THEN a.ai_answer IN ('A', 'B', 'C', 'D')
        ELSE a.ai_answer IN ('True', 'False')
    END AS format_ok,
    a.run_id,
    a.answered_at
FROM {{ ref('stg_llm_answers') }} AS a
INNER JOIN {{ ref('stg_questions') }} AS q
    ON a.question_id = q.question_id
