-- Réponses des modèles : une seule ligne par (question, modèle, prompt).
-- Si un couple a été relancé, on garde la réponse la plus récente.
SELECT
    question_id,
    model,
    prompt_id,
    prompt_text,
    expected_letter,
    ai_answer_raw,
    trim(ai_answer) AS ai_answer,
    ai_correct,
    response_time AS response_time_s,
    completion_tokens,
    error,
    error IS NOT NULL AS has_error,
    run_id,
    CAST(answered_at AS TIMESTAMPTZ) AS answered_at
FROM {{ source('silver', 'llm_answers') }}
QUALIFY row_number() OVER (
    PARTITION BY question_id, model, prompt_id
    ORDER BY answered_at DESC, run_id DESC
) = 1
