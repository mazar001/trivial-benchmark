-- Axe 1 : justes + fausses au bon format + hors format = toutes les réponses.
-- Le test échoue s'il renvoie au moins une ligne.
SELECT *
FROM {{ ref('accuracy_by_model_prompt') }}
WHERE nb_correct + nb_incorrect_format_ok + nb_out_of_format <> nb_answers
