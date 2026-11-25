"""Prompts standardisés et versionnés du benchmark, et présentation des choix.

Chaque prompt a un identifiant stable (prompt_id) enregistré avec chaque réponse,
ce qui permet de comparer les prompts dans la couche gold.
Un prompt modifié doit changer d'identifiant, sinon les résultats ne sont plus comparables.

Prompts du projet (décision 15, 25/11) : ceux de Cécile, avec lesquels Gemma 4 E2B et
Ministral 3B ont été interrogés sur les 5 290 questions. Les reprendre permet de comparer
les modèles sans relancer de calcul.
- P1_choices         : consigne + question + choix, réponse contrainte (lettre ou True/False).
                       Référence.
- P2_expert          : P1 précédé d'un rôle d'expert. Mesure l'effet du rôle.
- P3_expert_advanced : P2 + consigne d'analyse (évaluer chaque choix, vérifier).
                       Mesure l'effet d'une consigne de « réflexion » sans raisonnement.
Leurs textes sont recopiés de son pilote_gemma.py (commit 917fbe1) ; src/answers_to_silver.py
vérifie qu'ils redonnent les empreintes SHA-256 enregistrées dans ses fichiers.

Nos premiers prompts ne sont plus dans le code (décision 19) : les réponses obtenues avec eux
(run Gemma-4-12b arrêté le 25/11) restent en bronze et sont écartées en silver
(referentiels/runs_exclus.csv).
"""
from __future__ import annotations

import hashlib
import json

LETTERS = "ABCD"

# ---------------------------------------------------------------- prompts du projet
CONSIGNE = "Answer the following general knowledge question."
CONSIGNE_FORMAT = {
    "multiple": "Reply with only one uppercase letter: A, B, C, or D.",
    "boolean": "Reply with only True or False.",
}
ROLE_EXPERT = "You are a general knowledge expert."
CONSIGNE_ANALYSE = {
    "multiple": (
        "Carefully analyze the question and evaluate each answer choice.\n"
        "Use your factual knowledge to eliminate incorrect options.\n"
        "Check your answer before responding."
    ),
    "boolean": (
        "Carefully evaluate the statement using your factual knowledge.\n"
        "Check its accuracy before responding."
    ),
}
PROMPTS = ("P1_choices", "P2_expert", "P3_expert_advanced")


def build_prompt(prompt_id: str, qtype: str, question: str, choices: list[str]) -> str:
    """Prompt exact envoyé au modèle. choices = ordre présenté (voir answer_choices)."""
    if qtype == "multiple":
        choices = [f"{letter}. {text}" for letter, text in zip(LETTERS, choices, strict=True)]
    text = "\n\n".join((f"{CONSIGNE} {CONSIGNE_FORMAT[qtype]}", question, "\n".join(choices)))
    if prompt_id == "P3_expert_advanced":
        return f"{ROLE_EXPERT}\n{CONSIGNE_ANALYSE[qtype]}\n{text}"
    if prompt_id == "P2_expert":
        return f"{ROLE_EXPERT}\n{text}"
    if prompt_id == "P1_choices":
        return text
    raise KeyError(prompt_id)


def _empreinte(*valeurs) -> str:
    return hashlib.sha256(json.dumps(valeurs, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def prompt_fingerprint(prompt_id: str) -> str:
    """Empreinte des deux gabarits (QCM puis vrai/faux), calculée comme dans les fichiers de Cécile."""
    return _empreinte(
        build_prompt(prompt_id, "multiple", "{question}", [f"{{choix_{i}}}" for i in range(4)]),
        build_prompt(prompt_id, "boolean", "{question}", [f"{{choix_{i}}}" for i in range(2)]),
    )


def answer_choices(category: str, difficulty: str, qtype: str, question: str,
                   correct: str, incorrect: list[str]) -> list[str]:
    """Ordre des choix présentés : celui de Cécile, déterministe (graine 42), même pour tous les modèles.

    Tri par empreinte SHA-256 de (« choix », 42, empreinte de la question, réponse). Ne dépend
    que du contenu : vérifié identique à son fichier sur 5 288 / 5 290 questions (les 2 autres
    ne diffèrent que par un espace insécable que notre silver a nettoyé).
    """
    ident = _empreinte(category, difficulty, qtype, question, correct, sorted(incorrect))
    return sorted([correct, *incorrect], key=lambda r: (_empreinte("choix", 42, ident, r), r))

