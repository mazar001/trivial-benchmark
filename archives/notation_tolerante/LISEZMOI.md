# Archive : notation tolérante (la nôtre, avant le 25/11)

Copie faite le 25/11/2026, juste avant d'adopter la **notation stricte de Cécile**
(décision 20, qui remplace la décision 17). Rien ici n'est lu par le pipeline.

## Contenu

| Fichier | Ce que c'est |
|---------|--------------|
| `answers_to_silver.py` | le script de silver tel qu'il était : `clean_answer()` (retire un bloc `<think>`), `normalize()` et `is_correct()` (notation tolérante) |
| `int_answers_enriched.sql` | le modèle dbt tel qu'il était : `format_ok` tolérant (accepte `(A)`, `a.`, `False.`…) |

## La règle tolérante

- QCM : la réponse est juste si elle **commence** par la bonne lettre, même entourée de `*`, `(` ou
  d'espaces (`**A**`, `(A)`, `A.`), ou si elle contient le texte de la bonne option.
- Vrai/faux : juste si le premier mot (après nettoyage) est la bonne réponse (`False.`, `**False**`).
- Le respect strict du format était mesuré à part (`format_ok`).

## Résultats obtenus avec elle (31 740 réponses, commit 7169dbb de Cécile)

| Modèle | P1_choices | P2_expert | P3_expert_advanced |
|--------|-----------:|----------:|-------------------:|
| Gemma 4 E2B | 54,1 % | 53,9 % | 52,0 % |
| Ministral 3B | 53,9 % | 53,6 % | 47,2 % (format 79,3 %) |

Avec la notation stricte, seul Ministral change : 53,8 %, 52,5 %, 41,2 %.

## Pour la reprendre

1. Remettre les deux fichiers à leur place :
   `cp archives/notation_tolerante/answers_to_silver.py src/`
   `cp archives/notation_tolerante/int_answers_enriched.sql src/models/intermediate/`
2. Relancer : `python src/answers_to_silver.py` puis `dbt build`.
3. Noter le changement dans `documentation/DECISIONS.md` (nouvelle décision).

Attention : ces copies datent du 25/11. Si `src/answers_to_silver.py` a changé depuis (autre
chose que la notation), ne pas écraser : recopier seulement les fonctions `normalize`,
`clean_answer` et `is_correct`.
