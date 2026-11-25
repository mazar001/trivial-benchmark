{#
  Tests génériques de la couche gold (idée reprise du dbt de Cécile, commit 6d17118).
  Un test dbt est une requête qui doit renvoyer ZÉRO ligne ; sinon dbt build échoue.
  Les données sont figées (31 740 réponses) : le nombre de lignes attendu est fixe.
#}


{#
  gold_grain : vérifie le grain d'une table.
  - chaque combinaison de `keys` n'apparaît qu'une fois et n'est jamais vide ;
  - la table a exactement `row_count` lignes.
#}
{% test gold_grain(model, keys, row_count) %}
WITH grain_errors AS (
    SELECT {{ keys | join(', ') }}
    FROM {{ model }}
    GROUP BY {{ keys | join(', ') }}
    HAVING count(*) <> 1
        {% for key in keys %} OR {{ key }} IS NULL {% endfor %}
)
SELECT 'ligne en double ou clé vide' AS controle, count(*) AS nb
FROM grain_errors
HAVING count(*) > 0
UNION ALL
SELECT 'nombre de lignes : ' || count(*) || ' au lieu de {{ row_count }}', count(*)
FROM {{ model }}
HAVING count(*) <> {{ row_count }}
{% endtest %}


{#
  gold_concordance : recalcule les indicateurs d'une table directement depuis
  int_answers_enriched, d'une autre façon (sum(CASE ...) au lieu de count_if,
  format recalculé depuis la réponse), et compare ligne à ligne.
  - dimensions : colonnes de regroupement en plus de model et prompt_id ;
  - where : filtre sur la table testée (ex. lignes type = 'all') ;
  - check_chance / check_format / check_time : contrôles en plus.
  Les taux sont des nombres à virgule : tolérance de 1e-9.
#}
{% test gold_concordance(model, dimensions=[], where=none, check_chance=false, check_format=false, check_time=false) %}
{%- set keys = ['model', 'prompt_id'] + dimensions -%}
WITH expected AS (
    SELECT
        {{ keys | join(', ') }},
        sum(1) AS nb_answers,
        sum(CASE WHEN ai_correct THEN 1 ELSE 0 END) AS nb_correct,
        avg(CASE WHEN type = 'boolean' THEN 50.0 ELSE 25.0 END) AS chance,
        sum(
            CASE
                WHEN type = 'multiple' AND ai_answer IN ('A', 'B', 'C', 'D') THEN 1
                WHEN type = 'boolean' AND ai_answer IN ('True', 'False') THEN 1
                ELSE 0
            END
        ) AS nb_format_ok,
        sum(response_time_s) / count(response_time_s) AS avg_time
    FROM {{ ref('int_answers_enriched') }}
    GROUP BY {{ keys | join(', ') }}
),

observed AS (
    SELECT *
    FROM {{ model }}
    {% if where %} WHERE {{ where }} {% endif %}
)

SELECT
    {% for key in keys %}coalesce(e.{{ key }}, o.{{ key }}) AS {{ key }}, {% endfor %}
    CASE
        WHEN e.nb_answers IS NULL THEN 'ligne en trop dans la table'
        WHEN o.nb_answers IS NULL THEN 'ligne manquante dans la table'
        ELSE 'valeur différente'
    END AS controle
FROM expected AS e
FULL OUTER JOIN observed AS o
    ON {% for key in keys %}e.{{ key }} = o.{{ key }}{% if not loop.last %} AND {% endif %}{% endfor %}
WHERE e.nb_answers IS NULL
    OR o.nb_answers IS NULL
    OR e.nb_answers <> o.nb_answers
    OR e.nb_correct <> o.nb_correct
    OR abs(o.pct_correct - 100.0 * e.nb_correct / e.nb_answers) > 1e-9
    {% if check_chance %}
    OR abs(o.chance_pct - e.chance) > 1e-9
    OR abs(o.pct_above_chance - (100.0 * e.nb_correct / e.nb_answers - e.chance)) > 1e-9
    {% endif %}
    {% if check_format %}
    OR abs(o.pct_format_ok - 100.0 * e.nb_format_ok / e.nb_answers) > 1e-9
    {% endif %}
    {% if check_time %}
    OR abs(o.avg_response_time_s - e.avg_time) > 1e-9
    {% endif %}
{% endtest %}
