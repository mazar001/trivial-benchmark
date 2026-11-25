-- Axe 2 : chaque question comparée est dans un seul des 4 cas
-- (gagnée, perdue, juste des 2 côtés, fausse des 2 côtés), et l'écart de réussite
-- est égal à 100 x (gagnées - perdues) / nb_questions (deux calculs indépendants).
-- Le test échoue s'il renvoie au moins une ligne.
SELECT *
FROM {{ ref('prompt_effect') }}
WHERE nb_gained + nb_lost + nb_both_correct + nb_both_wrong <> nb_questions
   OR abs(delta_pct_correct - 100.0 * (nb_gained - nb_lost) / nb_questions) > 0.051
