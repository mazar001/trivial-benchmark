-- Questions nettoyées et typées par src/bronze_to_silver.py (silver/questions.parquet).
-- Le décodage et le nettoyage (identifiants, espaces, types) sont faits en amont :
-- ce modèle ne fait que sélectionner les colonnes utiles aux analyses.
SELECT
    question_id,
    category_id,
    category,
    type,
    difficulty,
    question,
    correct_answer,
    incorrect_answers,
    nb_choices
FROM {{ source('silver', 'questions') }}
