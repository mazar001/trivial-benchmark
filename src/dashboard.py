"""Dashboard Streamlit sur les 7 tables de la couche gold (décision 21).

Lancement (depuis la racine du projet) :
    streamlit run src/dashboard.py

Les tables sont lues dans gold/warehouse.duckdb (produit par `dbt build`).
Chaque requête ouvre une connexion DuckDB courte en lecture seule puis la
referme : `dbt build` reste possible pendant que le dashboard tourne. Les
résultats sont mis en cache ; le bouton « Recharger » vide ce cache.

Les filtres de la barre latérale (modèle, prompt, catégorie, difficulté, type)
sont traduits en clauses WHERE paramétrées et appliqués dans DuckDB, sur chaque
table qui possède la colonne filtrée. Les taux sont stockés non arrondis en gold :
l'arrondi se fait ici, à l'affichage.

Un onglet par axe des KPI :
    1. Performance           accuracy_by_model_prompt
    2. Influence des prompts prompt_effect
    3. Domaines              accuracy_by_category, category_model_gap,
                             accuracy_by_difficulty, accuracy_by_type
    4. Questions pièges      question_consensus
    + Données                toutes les tables, téléchargeables
"""

from pathlib import Path

import altair as alt
import duckdb
import pandas as pd
import streamlit as st

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

RACINE = Path(__file__).resolve().parent.parent
CHEMIN_BASE = RACINE / "gold" / "warehouse.duckdb"

MARTS = [
    "accuracy_by_model_prompt",
    "prompt_effect",
    "accuracy_by_category",
    "category_model_gap",
    "accuracy_by_difficulty",
    "accuracy_by_type",
    "question_consensus",
]

# Libellés lisibles (les identifiants restent ceux de gold).
MODELES = {
    "google/gemma-4-e2b": "Gemma 4 E2B",
    "mistralai/ministral-3-3b": "Ministral 3B",
}
PROMPTS = {
    "P1_choices": "P1 · consigne",
    "P2_expert": "P2 · + expert",
    "P3_expert_advanced": "P3 · + analyse",
}
PROMPTS_COURTS = {"P1_choices": "P1", "P2_expert": "P2", "P3_expert_advanced": "P3"}
DIFFICULTES = {"easy": "Facile", "medium": "Moyen", "hard": "Difficile"}
TYPES = {"multiple": "QCM", "boolean": "Vrai/faux", "all": "Tous types"}
STATUTS = ["toujours réussie", "mixte", "toujours ratée"]

# Couleurs : une par modèle, fixe (la couleur suit le modèle, jamais son rang).
COULEURS_MODELES = {"Gemma 4 E2B": "#257de0", "Ministral 3B": "#f47230"}
# Répartition des réponses : juste / fausse / hors format.
COULEURS_REPONSES = {
    "Juste": "#0aac23",
    "Fausse au bon format": "#dc3c3d",
    "Hors format": "#b4b2a9",
}
# Questions gagnées / perdues : deux pôles opposés.
COULEURS_TRANSITIONS = {"Gagnées": "#257de0", "Perdues": "#ec4647"}
GRIS_TEXTE = "#666666"
# Étiquettes d'axe : milliers séparés par une espace, sans signe moins.
MILLIERS_FR = "replace(format(abs(datum.value), ','), ',', ' ')"
BLEUS = ["#cce3fd", "#84b9f3", "#338ced", "#1b64be", "#0e3d7e"]  # du clair au foncé

# Colonnes filtrables (barre latérale) -> clé de session_state.
FILTRES = {
    "model": "f_modeles",
    "prompt_id": "f_prompts",
    "category": "f_categories",
    "difficulty": "f_difficultes",
    "type": "f_types",
}

st.set_page_config(page_title="Trivial Benchmark — gold", page_icon="🎲", layout="wide")

# --------------------------------------------------------------------------- #
# Accès aux données
# --------------------------------------------------------------------------- #


@st.cache_data(show_spinner="Requête DuckDB…")
def requete(sql: str, params: tuple = ()) -> pd.DataFrame:
    """Exécute une requête sur la base gold (connexion courte, lecture seule)."""
    with duckdb.connect(str(CHEMIN_BASE), read_only=True) as con:
        return con.execute(sql, list(params)).df()


@st.cache_data
def colonnes(table: str) -> set[str]:
    return set(
        requete(
            "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
            (table,),
        )["column_name"]
    )


def where(table: str, ignorer: tuple[str, ...] = (), extra: str = "") -> tuple[str, tuple]:
    """Clause WHERE paramétrée : filtres de la barre latérale sur les colonnes présentes."""
    conditions, params = [], []
    for col, cle in FILTRES.items():
        valeurs = st.session_state.get(cle) or []
        if col in ignorer or col not in colonnes(table) or not valeurs:
            continue
        conditions.append(f"{col} IN ({', '.join('?' * len(valeurs))})")
        params += list(valeurs)
    if extra:
        conditions.append(extra)
    return ("WHERE " + " AND ".join(conditions) if conditions else ""), tuple(params)


def lire(table: str, ordre: str = "", ignorer: tuple[str, ...] = (), extra: str = "") -> pd.DataFrame:
    clause, params = where(table, ignorer, extra)
    df = requete(f"SELECT * FROM {table} {clause} {ordre}", params)
    return libelles(df)


def libelles(df: pd.DataFrame) -> pd.DataFrame:
    """Ajoute les libellés lisibles à côté des identifiants."""
    df = df.copy()
    if "model" in df:
        df["modele"] = df["model"].map(MODELES).fillna(df["model"])
    if "prompt_id" in df:
        df["prompt"] = df["prompt_id"].map(PROMPTS).fillna(df["prompt_id"])
    if "difficulty" in df:
        df["difficulte"] = df["difficulty"].map(DIFFICULTES).fillna(df["difficulty"])
    if "type" in df:
        df["type_lib"] = df["type"].map(TYPES).fillna(df["type"])
    if {"model", "prompt_id"} <= set(df.columns):
        df["configuration"] = df["modele"] + " · " + df["prompt_id"].map(PROMPTS_COURTS)
    return df


# --------------------------------------------------------------------------- #
# Mise en forme (à la française) et graphiques
# --------------------------------------------------------------------------- #


def fr(x: float, decimales: int = 1) -> str:
    return f"{x:,.{decimales}f}".replace(",", " ").replace(".", ",")


def pct(x: float, decimales: int = 1) -> str:
    return f"{fr(x, decimales)} %"


def points(x: float) -> str:
    signe = "+" if x > 0 else ("−" if x < 0 else "±")
    return f"{signe}{fr(abs(x))} pt"


def nombre(n: float) -> str:
    return fr(n, 0)


def ordre_present(valeurs: dict, presents) -> list[str]:
    """Libellés dans l'ordre de référence, limités à ceux présents."""
    presents = set(presents)
    return [v for v in valeurs.values() if v in presents]


def echelle_modeles(df: pd.DataFrame) -> alt.Scale:
    noms = ordre_present({k: k for k in COULEURS_MODELES}, df["modele"])
    return alt.Scale(domain=noms, range=[COULEURS_MODELES[n] for n in noms])


def legende_haut() -> alt.Legend:
    return alt.Legend(orient="top", title=None, labelFontSize=12)


def ligne_hasard(valeur: float, texte: str) -> alt.Chart:
    """Ligne pointillée horizontale du hasard (expliquée sous le graphique)."""
    return alt.Chart(pd.DataFrame({"y": [valeur / 100], "t": [texte]})).mark_rule(
        strokeDash=[4, 4], color=GRIS_TEXTE, size=1.5
    ).encode(y="y:Q", tooltip=alt.Tooltip("t:N", title="Hasard"))


def barres_groupees(
    df: pd.DataFrame,
    categorie: str,
    ordre: list[str],
    valeur: str,
    titre_y: str,
    tooltip: list,
    format_y: str = ".0%",
    hauteur: int = 320,
) -> alt.Chart:
    """Barres verticales groupées : une barre par modèle dans chaque catégorie."""
    return (
        alt.Chart(df)
        .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
        .encode(
            x=alt.X(f"{categorie}:N", sort=ordre, title=None, axis=alt.Axis(labelAngle=0)),
            xOffset=alt.XOffset("modele:N", sort=list(COULEURS_MODELES), scale=alt.Scale(paddingInner=0.06)),
            y=alt.Y(f"{valeur}:Q", title=titre_y, axis=alt.Axis(format=format_y)),
            color=alt.Color("modele:N", scale=echelle_modeles(df), legend=legende_haut()),
            tooltip=tooltip,
        )
        .properties(height=hauteur)
    )


def afficher(chart) -> None:
    st.altair_chart(chart, width="stretch")


def filtres_actifs(table: str, ignorer: tuple[str, ...] = ()) -> None:
    """Rappelle sous un graphique les filtres qui s'appliquent à sa table."""
    noms = {"model": "modèle", "prompt_id": "prompt", "category": "catégorie",
            "difficulty": "difficulté", "type": "type"}
    actifs = [
        noms[c] for c, cle in FILTRES.items()
        if st.session_state.get(cle) and c in colonnes(table) and c not in ignorer
    ]
    texte = f"Table `{table}`"
    if actifs:
        texte += " · filtres appliqués : " + ", ".join(actifs)
    st.caption(texte)


AUCUN_RESULTAT = "Aucun résultat avec les filtres actuels."

# --------------------------------------------------------------------------- #
# Vérifications préalables
# --------------------------------------------------------------------------- #

if not CHEMIN_BASE.exists():
    st.error(f"Base introuvable : `{CHEMIN_BASE}`. Lancer `dbt build` depuis la racine du projet.")
    st.stop()

try:
    presentes = set(requete("SELECT table_name FROM information_schema.tables")["table_name"])
except duckdb.IOException:
    st.error("La base est verrouillée (un `dbt build` est sans doute en cours). Réessayer dans un instant.")
    st.stop()

manquants = [m for m in MARTS if m not in presentes]
if manquants:
    st.error("Tables absentes de gold : " + ", ".join(f"`{m}`" for m in manquants) + ". Lancer `dbt build`.")
    st.stop()

# --------------------------------------------------------------------------- #
# Barre latérale : filtres
# --------------------------------------------------------------------------- #

CATEGORIES = requete("SELECT DISTINCT category FROM accuracy_by_category ORDER BY category")["category"].tolist()
VALEURS_FILTRES = {
    "f_modeles": list(MODELES),
    "f_prompts": list(PROMPTS),
    "f_categories": CATEGORIES,
    "f_difficultes": list(DIFFICULTES),
    "f_types": ["multiple", "boolean"],
}
for cle in VALEURS_FILTRES:
    st.session_state.setdefault(cle, [])


def reinitialiser_filtres() -> None:
    for cle in VALEURS_FILTRES:
        st.session_state[cle] = []


with st.sidebar:
    st.title("🎲 Trivial Benchmark")
    st.caption("Couche gold · 7 tables dbt · DuckDB")

    col_a, col_b = st.columns(2)
    if col_a.button("🔄 Recharger", width="stretch", help="Relit la base gold (après un dbt build)."):
        st.cache_data.clear()
        st.rerun()
    col_b.button("↺ Réinitialiser", width="stretch", on_click=reinitialiser_filtres,
                 help="Remet tous les filtres à « tous ».")

    st.header("Filtres", divider="gray")
    st.caption("Vide = tout. Chaque filtre s'applique aux tables qui ont la colonne.")
    st.multiselect("Modèles", VALEURS_FILTRES["f_modeles"], key="f_modeles",
                   format_func=MODELES.get, placeholder="Tous les modèles")
    st.multiselect("Prompts", VALEURS_FILTRES["f_prompts"], key="f_prompts",
                   format_func=PROMPTS.get, placeholder="Tous les prompts")
    st.multiselect("Catégories", CATEGORIES, key="f_categories", placeholder="Toutes les catégories")
    st.multiselect("Difficultés", VALEURS_FILTRES["f_difficultes"], key="f_difficultes",
                   format_func=DIFFICULTES.get, placeholder="Toutes les difficultés")
    st.multiselect("Types de question", VALEURS_FILTRES["f_types"], key="f_types",
                   format_func=TYPES.get, placeholder="QCM et vrai/faux")

    st.divider()
    st.caption(
        "P1 = consigne seule · P2 = P1 + rôle d'expert · P3 = P2 + consigne d'analyse. "
        "Notation stricte : seule une réponse exactement A–D ou True/False peut être juste."
    )
    st.caption(f"Base : `{CHEMIN_BASE.relative_to(RACINE)}`")

# --------------------------------------------------------------------------- #
# En-tête
# --------------------------------------------------------------------------- #

st.title("Les LLM sont-ils bons au Trivial Poursuite ?")
st.caption(
    "5 290 questions vérifiées d'Open Trivia DB · 2 modèles (Gemma 4 E2B, Ministral 3B, LM Studio) "
    "× 3 prompts = 31 740 réponses."
)

onglet_perf, onglet_prompts, onglet_domaines, onglet_questions, onglet_donnees = st.tabs(
    ["📊 Performance", "🧪 Influence des prompts", "🗂️ Domaines", "🪤 Questions pièges", "📋 Données"]
)

# --------------------------------------------------------------------------- #
# Onglet 1 : performance des modèles et des prompts
# --------------------------------------------------------------------------- #

with onglet_perf:
    perf = lire("accuracy_by_model_prompt", "ORDER BY pct_correct DESC, model, prompt_id")
    if perf.empty:
        st.info(AUCUN_RESULTAT)
    else:
        # Hasard moyen des configurations affichées (25 % par QCM, 50 % par vrai/faux).
        types = lire("accuracy_by_type", ignorer=("type",))
        hasard = (types["chance_pct"] * types["nb_answers"]).sum() / types["nb_answers"].sum()

        meilleur, pire = perf.iloc[0], perf.iloc[-1]
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Meilleure configuration", meilleur["configuration"], pct(meilleur["pct_correct"]),
                  delta_color="off", delta_arrow="off", border=True,
                  help="Taux de réussite le plus élevé parmi les configurations filtrées.")
        k2.metric("Moins bonne configuration", pire["configuration"], pct(pire["pct_correct"]),
                  delta_color="off", delta_arrow="off", border=True)
        k3.metric("Conformité la plus basse", pct(perf["pct_format_ok"].min()),
                  perf.loc[perf["pct_format_ok"].idxmin(), "configuration"],
                  delta_color="off", delta_arrow="off", border=True,
                  help="Part des réponses exactement au format demandé (lettre A–D ou True/False).")
        k4.metric("Réponse au hasard", pct(hasard), "25 % par QCM, 50 % par vrai/faux",
                  delta_color="off", delta_arrow="off", border=True,
                  help="Taux qu'obtiendrait un modèle qui répond au hasard, sur ces questions.")

        ordre_prompts = ordre_present(PROMPTS, perf["prompt"])
        perf = perf.assign(
            part=perf["pct_correct"] / 100,
            t_reussite=perf["pct_correct"].map(pct),
            t_format=perf["pct_format_ok"].map(pct),
            t_temps=perf["avg_response_time_s"].map(lambda s: f"{fr(s, 2)} s"),
        )

        col_g, col_d = st.columns(2, gap="large")
        with col_g:
            st.markdown("**Taux de réussite**")
            barres = barres_groupees(
                perf, "prompt", ordre_prompts, "part", "Bonnes réponses",
                tooltip=[alt.Tooltip("modele:N", title="Modèle"), alt.Tooltip("prompt:N", title="Prompt"),
                         alt.Tooltip("t_reussite:N", title="Réussite"),
                         alt.Tooltip("nb_correct:Q", title="Bonnes réponses", format=","),
                         alt.Tooltip("nb_answers:Q", title="Réponses", format=",")],
            )
            valeurs = barres.mark_text(dy=-7, fontSize=11, color=GRIS_TEXTE).encode(
                text="t_reussite:N", color=alt.value(GRIS_TEXTE))
            afficher((barres + valeurs + ligne_hasard(hasard, pct(hasard)))
                     .resolve_scale(color="independent"))
            st.caption(f"Ligne pointillée = réponse au hasard ({pct(hasard)}).")
        with col_d:
            st.markdown("**Temps de réponse moyen**")
            afficher(barres_groupees(
                perf, "prompt", ordre_prompts, "avg_response_time_s", "Secondes par réponse",
                format_y=".1f",
                tooltip=[alt.Tooltip("modele:N", title="Modèle"), alt.Tooltip("prompt:N", title="Prompt"),
                         alt.Tooltip("t_temps:N", title="Temps moyen"),
                         alt.Tooltip("median_response_time_s:Q", title="Médiane (s)", format=".2f"),
                         alt.Tooltip("max_response_time_s:Q", title="Maximum (s)", format=".2f")],
            ))

        st.markdown("**Répartition des réponses** : justes, fausses au bon format, hors format (comptées fausses)")
        rep = perf.melt(
            id_vars=["configuration", "modele", "prompt_id"],
            value_vars=["nb_correct", "nb_incorrect_format_ok", "nb_out_of_format"],
            var_name="statut", value_name="nb",
        )
        rep["statut"] = rep["statut"].map({"nb_correct": "Juste", "nb_incorrect_format_ok": "Fausse au bon format",
                                           "nb_out_of_format": "Hors format"})
        rep["part"] = rep["nb"] / rep.groupby("configuration")["nb"].transform("sum")
        rep["t_part"] = (rep["part"] * 100).map(pct)
        rep["ordre_statut"] = rep["statut"].map({s: i for i, s in enumerate(COULEURS_REPONSES)})
        ordre_config = perf.sort_values(["model", "prompt_id"])["configuration"].tolist()
        afficher(
            alt.Chart(rep)
            .mark_bar(stroke="white", strokeWidth=2)
            .encode(
                y=alt.Y("configuration:N", sort=ordre_config, title=None, axis=alt.Axis(labelLimit=220)),
                x=alt.X("part:Q", stack="normalize", title="Part des réponses", axis=alt.Axis(format=".0%")),
                color=alt.Color("statut:N", legend=legende_haut(),
                                scale=alt.Scale(domain=list(COULEURS_REPONSES), range=list(COULEURS_REPONSES.values()))),
                order=alt.Order("ordre_statut:Q"),
                tooltip=[alt.Tooltip("configuration:N", title="Configuration"), alt.Tooltip("statut:N", title="Réponse"),
                         alt.Tooltip("nb:Q", title="Nombre", format=","), alt.Tooltip("t_part:N", title="Part")],
            )
            .properties(height=36 * len(ordre_config) + 40)
        )
        st.info(
            "**À retenir.** Les deux modèles font environ deux fois mieux que le hasard. "
            "La consigne d'analyse (P3) fait baisser Ministral surtout parce qu'il ne respecte plus le format : "
            "une réponse hors format compte comme fausse."
        )

        with st.expander("Tableau détaillé"):
            st.dataframe(
                perf[["modele", "prompt", "nb_answers", "nb_correct", "pct_correct", "nb_incorrect_format_ok",
                      "nb_out_of_format", "pct_format_ok", "avg_response_time_s", "median_response_time_s",
                      "max_response_time_s", "nb_errors"]],
                hide_index=True, width="stretch",
                column_config={
                    "modele": "Modèle", "prompt": "Prompt", "nb_answers": "Réponses",
                    "nb_correct": "Justes",
                    "pct_correct": st.column_config.NumberColumn("Réussite (%)", format="%.1f"),
                    "nb_incorrect_format_ok": "Fausses au bon format", "nb_out_of_format": "Hors format",
                    "pct_format_ok": st.column_config.NumberColumn("Conformité (%)", format="%.1f"),
                    "avg_response_time_s": st.column_config.NumberColumn("Temps moyen (s)", format="%.2f"),
                    "median_response_time_s": st.column_config.NumberColumn("Temps médian (s)", format="%.2f"),
                    "max_response_time_s": st.column_config.NumberColumn("Temps max (s)", format="%.2f"),
                    "nb_errors": "Erreurs",
                },
            )
    filtres_actifs("accuracy_by_model_prompt")

# --------------------------------------------------------------------------- #
# Onglet 2 : influence des prompts
# --------------------------------------------------------------------------- #

with onglet_prompts:
    st.subheader("Ajouter un rôle d'expert ou une consigne d'analyse aide-t-il ?")
    st.caption("Comparaison sur les mêmes questions : une question est gagnée si elle passe de fausse à juste, "
               "perdue si elle passe de juste à fausse.")
    couples = {
        "P1 → P2 (rôle d'expert)": ("P1_choices", "P2_expert"),
        "P1 → P3 (expert + analyse)": ("P1_choices", "P3_expert_advanced"),
        "P2 → P3 (analyse seule)": ("P2_expert", "P3_expert_advanced"),
    }
    choix = st.segmented_control("Couples de prompts", list(couples), default=list(couples),
                                 selection_mode="multi", key="couples")
    effet = lire("prompt_effect", "ORDER BY model, prompt_ref, prompt_compared")
    choisis = [couples[c] for c in (choix or [])]
    effet = effet[[(r, c) in choisis for r, c in zip(effet["prompt_ref"], effet["prompt_compared"])]]
    if st.session_state["f_prompts"]:
        garder = set(st.session_state["f_prompts"])
        effet = effet[effet["prompt_ref"].isin(garder) & effet["prompt_compared"].isin(garder)]

    if effet.empty:
        st.info(AUCUN_RESULTAT)
    else:
        effet = effet.assign(
            couple=effet["prompt_ref"].map(PROMPTS_COURTS) + " → " + effet["prompt_compared"].map(PROMPTS_COURTS),
        )
        effet["ligne"] = effet["modele"] + " · " + effet["couple"]

        cols = st.columns(len(effet["modele"].unique()))
        for col, (modele, g) in zip(cols, effet.groupby("modele", sort=False)):
            with col:
                st.markdown(f"**{modele}**")
                for _, r in g.iterrows():
                    st.metric(
                        f"{r['couple']} · réussite", pct(r["pct_correct_compared"]), points(r["delta_pct_correct"]),
                        border=True,
                        help=f"{nombre(r['nb_gained'])} gagnées, {nombre(r['nb_lost'])} perdues "
                             f"(net {nombre(r['nb_net'])}). Conformité {points(r['delta_pct_format_ok'])}, "
                             f"temps {fr(r['delta_avg_time_s'], 2)} s.",
                    )

        st.markdown("**Questions gagnées et perdues**")
        trans = pd.concat([
            effet.assign(sens="Gagnées", valeur=effet["nb_gained"], nb=effet["nb_gained"]),
            effet.assign(sens="Perdues", valeur=-effet["nb_lost"], nb=effet["nb_lost"]),
        ])
        ordre_lignes = effet["ligne"].tolist()
        base = alt.Chart(trans).encode(
            y=alt.Y("ligne:N", sort=ordre_lignes, title=None, axis=alt.Axis(labelLimit=240)),
            x=alt.X("valeur:Q", title="← perdues · gagnées →", axis=alt.Axis(labelExpr=MILLIERS_FR)),
        )
        barres = base.mark_bar(cornerRadiusEnd=4, height={"band": 0.6}).encode(
            color=alt.Color("sens:N", legend=legende_haut(),
                            scale=alt.Scale(domain=list(COULEURS_TRANSITIONS), range=list(COULEURS_TRANSITIONS.values()))),
            tooltip=[alt.Tooltip("modele:N", title="Modèle"), alt.Tooltip("couple:N", title="Couple"),
                     alt.Tooltip("sens:N", title=" "), alt.Tooltip("nb:Q", title="Questions", format=",")],
        )
        zero =alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(color="#c2c2c2").encode(x="x:Q")
        etiquettes = base.mark_text(fontSize=11, color=GRIS_TEXTE, dx=alt.expr("datum.valeur < 0 ? -14 : 14")).encode(
            text=alt.Text("nb:Q", format=","))
        afficher((barres + zero + etiquettes).properties(height=48 * len(ordre_lignes) + 40))

        st.info(
            "**À retenir.** Aucun prompt n'améliore le score : chaque ajout fait perdre plus de questions qu'il n'en "
            "fait gagner. Le rôle d'expert ne change presque rien ; la consigne d'analyse dégrade nettement Ministral."
        )
        with st.expander("Tableau détaillé"):
            st.dataframe(
                effet[["modele", "couple", "nb_questions", "pct_correct_ref", "pct_correct_compared",
                       "delta_pct_correct", "nb_gained", "nb_lost", "nb_net", "nb_both_correct", "nb_both_wrong",
                       "delta_pct_format_ok", "delta_avg_time_s"]],
                hide_index=True, width="stretch",
                column_config={
                    "modele": "Modèle", "couple": "Couple", "nb_questions": "Questions",
                    "pct_correct_ref": st.column_config.NumberColumn("Réussite avant (%)", format="%.1f"),
                    "pct_correct_compared": st.column_config.NumberColumn("Réussite après (%)", format="%.1f"),
                    "delta_pct_correct": st.column_config.NumberColumn("Écart (pt)", format="%+.1f"),
                    "nb_gained": "Gagnées", "nb_lost": "Perdues", "nb_net": "Net",
                    "nb_both_correct": "Justes des 2 côtés", "nb_both_wrong": "Fausses des 2 côtés",
                    "delta_pct_format_ok": st.column_config.NumberColumn("Écart conformité (pt)", format="%+.1f"),
                    "delta_avg_time_s": st.column_config.NumberColumn("Écart temps (s)", format="%+.2f"),
                },
            )
    st.caption("Table `prompt_effect` · filtres appliqués : modèle, prompt (un couple est gardé si ses deux prompts "
               "sont sélectionnés)")

# --------------------------------------------------------------------------- #
# Onglet 3 : domaines de compétence
# --------------------------------------------------------------------------- #

with onglet_domaines:
    prompt_vue = st.segmented_control(
        "Prompt affiché", list(PROMPTS), default="P1_choices", format_func=PROMPTS.get,
        required=True, key="prompt_domaines",
        help="Les vues par catégorie, difficulté et type montrent un prompt à la fois.",
    )
    sous_cat, sous_diff, sous_type = st.tabs(["Catégories", "Difficulté", "Type de question"])

    # --- Catégories ---
    with sous_cat:
        clause, params = where("accuracy_by_category", ignorer=("prompt_id",), extra="prompt_id = ?")
        cat = libelles(requete(f"SELECT * FROM accuracy_by_category {clause}", params + (prompt_vue,)))
        if cat.empty:
            st.info(AUCUN_RESULTAT)
        else:
            cat["part"] = cat["pct_correct"] / 100
            cat["t_reussite"] = cat["pct_correct"].map(pct)
            ordre_cat = (cat.groupby("category")["pct_correct"].mean()
                         .sort_values(ascending=False).index.tolist())
            st.markdown(f"**Réussite par catégorie** · {PROMPTS[prompt_vue]} · triée par taux moyen")
            ecarts = cat.groupby("category", as_index=False).agg(mini=("part", "min"), maxi=("part", "max"))
            regle = alt.Chart(ecarts).mark_rule(color="#c2c2c2", size=2).encode(
                y=alt.Y("category:N", sort=ordre_cat), x="mini:Q", x2="maxi:Q")
            points_cat = alt.Chart(cat).mark_circle(size=110, opacity=1, stroke="white", strokeWidth=1.5).encode(
                y=alt.Y("category:N", sort=ordre_cat, title=None, axis=alt.Axis(labelLimit=300)),
                x=alt.X("part:Q", title="Bonnes réponses", axis=alt.Axis(format=".0%"),
                        scale=alt.Scale(zero=False, padding=10)),
                color=alt.Color("modele:N", scale=echelle_modeles(cat), legend=legende_haut()),
                tooltip=[alt.Tooltip("category:N", title="Catégorie"), alt.Tooltip("modele:N", title="Modèle"),
                         alt.Tooltip("t_reussite:N", title="Réussite"),
                         alt.Tooltip("nb_correct:Q", title="Bonnes réponses"),
                         alt.Tooltip("nb_answers:Q", title="Questions")],
            )
            afficher((regle + points_cat).properties(height=26 * len(ordre_cat) + 50))
            st.caption("Un point par modèle ; le trait relie les deux modèles et montre l'écart. "
                       "Plus petite catégorie : 36 questions.")

            st.markdown(f"**Meilleur modèle par catégorie** · {PROMPTS[prompt_vue]}")
            clause, params = where("category_model_gap", ignorer=("prompt_id",), extra="prompt_id = ?")
            gap = requete(f"SELECT * FROM category_model_gap {clause} ORDER BY gap_pct_points DESC, category",
                          params + (prompt_vue,))
            gap["meilleur"] = gap["best_model"].map(MODELES)
            gap.loc[gap["is_tie"], "meilleur"] = "égalité"
            victoires = gap[~gap["is_tie"]]["meilleur"].value_counts()
            st.caption(" · ".join(f"**{m}** gagne {n} catégorie(s)" for m, n in victoires.items())
                       + (f" · {int(gap['is_tie'].sum())} égalité(s)" if gap["is_tie"].any() else ""))
            st.dataframe(
                gap[["category", "meilleur", "pct_correct_best", "pct_correct_worst", "gap_pct_points", "nb_questions"]],
                hide_index=True, width="stretch", height=300,
                column_config={
                    "category": "Catégorie", "meilleur": "Meilleur modèle",
                    "pct_correct_best": st.column_config.NumberColumn("Son taux (%)", format="%.1f"),
                    "pct_correct_worst": st.column_config.NumberColumn("L'autre (%)", format="%.1f"),
                    "gap_pct_points": st.column_config.ProgressColumn(
                        "Écart (pt)", format="%.1f", min_value=0,
                        max_value=float(max(gap["gap_pct_points"].max(), 1))),
                    "nb_questions": "Questions",
                },
            )
            st.caption("Table `category_model_gap` · filtre appliqué : catégorie")

            st.markdown("**Réussite par catégorie × prompt** : quels domaines profitent d'une formulation ?")
            modele_carte = st.segmented_control(
                "Modèle", list(MODELES), default=list(MODELES)[0], format_func=MODELES.get,
                required=True, key="modele_carte")
            clause, params = where("accuracy_by_category", ignorer=("model",), extra="model = ?")
            carte = libelles(requete(f"SELECT * FROM accuracy_by_category {clause}", params + (modele_carte,)))
            if not carte.empty:
                carte["part"] = carte["pct_correct"] / 100
                carte["t_reussite"] = carte["pct_correct"].map(lambda x: fr(x, 0))
                carte["prompt_court"] = carte["prompt_id"].map(PROMPTS_COURTS)
                ordre_carte = (carte.groupby("category")["pct_correct"].mean()
                               .sort_values(ascending=False).index.tolist())
                fond = alt.Chart(carte).mark_rect(stroke="white", strokeWidth=2).encode(
                    x=alt.X("prompt_court:N", title=None, sort=["P1", "P2", "P3"],
                            axis=alt.Axis(orient="top", labelAngle=0)),
                    y=alt.Y("category:N", sort=ordre_carte, title=None, axis=alt.Axis(labelLimit=300)),
                    color=alt.Color("part:Q", title="Réussite", scale=alt.Scale(range=BLEUS),
                                    legend=alt.Legend(format=".0%", orient="top")),
                    tooltip=[alt.Tooltip("category:N", title="Catégorie"), alt.Tooltip("prompt:N", title="Prompt"),
                             alt.Tooltip("pct_correct:Q", title="Réussite (%)", format=".1f"),
                             alt.Tooltip("nb_answers:Q", title="Questions")],
                )
                texte = alt.Chart(carte).mark_text(fontSize=11).encode(
                    x=alt.X("prompt_court:N", sort=["P1", "P2", "P3"]),
                    y=alt.Y("category:N", sort=ordre_carte),
                    text="t_reussite:N",
                    color=alt.condition("datum.part > 0.6", alt.value("white"), alt.value("#191919")),
                )
                afficher((fond + texte).properties(height=24 * len(ordre_carte) + 60))
                st.caption("Taux de réussite en %, du plus clair (faible) au plus foncé (élevé). "
                           "Table `accuracy_by_category`.")

    # --- Difficulté ---
    with sous_diff:
        mode = st.radio("Affichage", ["Tous types confondus", "QCM et vrai/faux séparés"], horizontal=True,
                        key="mode_difficulte")
        tous = mode == "Tous types confondus"
        clause, params = where(
            "accuracy_by_difficulty", ignorer=("prompt_id",) + (("type",) if tous else ()),
            extra="prompt_id = ? AND " + ("type = 'all'" if tous else "type <> 'all'"))
        diff = libelles(requete(f"SELECT * FROM accuracy_by_difficulty {clause}", params + (prompt_vue,)))
        if diff.empty:
            st.info(AUCUN_RESULTAT)
        else:
            diff["part"] = diff["pct_correct"] / 100
            diff["hasard"] = diff["chance_pct"] / 100
            diff["t_reussite"] = diff["pct_correct"].map(pct)
            diff["t_hasard"] = diff["chance_pct"].map(pct)
            diff["t_ecart"] = diff["pct_above_chance"].map(points)
            ordre_diff = ordre_present(DIFFICULTES, diff["difficulte"])
            infos = [alt.Tooltip("modele:N", title="Modèle"), alt.Tooltip("difficulte:N", title="Difficulté"),
                     alt.Tooltip("type_lib:N", title="Type"), alt.Tooltip("t_reussite:N", title="Réussite"),
                     alt.Tooltip("t_hasard:N", title="Hasard"), alt.Tooltip("t_ecart:N", title="Au-dessus du hasard"),
                     alt.Tooltip("nb_answers:Q", title="Questions")]

            def graphe_difficulte(d: pd.DataFrame) -> alt.LayerChart:
                barres = barres_groupees(d, "difficulte", ordre_diff, "part", "Bonnes réponses", infos, hauteur=300)
                hasard_ticks = barres.mark_tick(color="#191919", thickness=2, size=22).encode(
                    y="hasard:Q", color=alt.value("#191919"))
                return (barres + hasard_ticks).resolve_scale(color="independent")

            if tous:
                afficher(graphe_difficulte(diff))
            else:
                cols = st.columns(2, gap="large")
                for col, t in zip(cols, ["multiple", "boolean"]):
                    d = diff[diff["type"] == t]
                    with col:
                        st.markdown(f"**{TYPES[t]}**")
                        if d.empty:
                            st.info(AUCUN_RESULTAT)
                        else:
                            afficher(graphe_difficulte(d))
            st.caption("Le trait noir sur chaque barre = taux du hasard pour ces questions "
                       "(25 % par QCM, 50 % par vrai/faux ; « tous types » : moyenne selon leur part).")
            st.dataframe(
                diff[["modele", "difficulte", "type_lib", "nb_answers", "pct_correct", "chance_pct", "pct_above_chance"]],
                hide_index=True, width="stretch",
                column_config={
                    "modele": "Modèle", "difficulte": "Difficulté", "type_lib": "Type", "nb_answers": "Questions",
                    "pct_correct": st.column_config.NumberColumn("Réussite (%)", format="%.1f"),
                    "chance_pct": st.column_config.NumberColumn("Hasard (%)", format="%.1f"),
                    "pct_above_chance": st.column_config.NumberColumn("Au-dessus du hasard (pt)", format="%+.1f"),
                },
            )
        filtres_actifs("accuracy_by_difficulty", ignorer=("prompt_id",))

    # --- Type ---
    with sous_type:
        clause, params = where("accuracy_by_type", ignorer=("prompt_id",), extra="prompt_id = ?")
        typ = libelles(requete(f"SELECT * FROM accuracy_by_type {clause}", params + (prompt_vue,)))
        if typ.empty:
            st.info(AUCUN_RESULTAT)
        else:
            typ["part"] = typ["pct_correct"] / 100
            typ["hasard"] = typ["chance_pct"] / 100
            typ["t_reussite"] = typ["pct_correct"].map(pct)
            typ["t_ecart"] = typ["pct_above_chance"].map(points)
            typ["t_format"] = typ["pct_format_ok"].map(pct)
            ordre_types = ordre_present({k: v for k, v in TYPES.items() if k != "all"}, typ["type_lib"])
            barres = barres_groupees(
                typ, "type_lib", ordre_types, "part", "Bonnes réponses", hauteur=320,
                tooltip=[alt.Tooltip("modele:N", title="Modèle"), alt.Tooltip("type_lib:N", title="Type"),
                         alt.Tooltip("t_reussite:N", title="Réussite"), alt.Tooltip("t_ecart:N", title="Au-dessus du hasard"),
                         alt.Tooltip("t_format:N", title="Conformité"), alt.Tooltip("nb_answers:Q", title="Questions")])
            ticks = barres.mark_tick(color="#191919", thickness=2, size=40).encode(
                y="hasard:Q", color=alt.value("#191919"))
            valeurs = barres.mark_text(dy=-7, fontSize=11).encode(text="t_ecart:N", color=alt.value(GRIS_TEXTE))
            col_g, col_d = st.columns([3, 2], gap="large")
            with col_g:
                afficher((barres + ticks + valeurs).resolve_scale(color="independent"))
                st.caption("Trait noir = hasard (25 % QCM, 50 % vrai/faux). Au-dessus des barres : "
                           "écart au hasard, en points.")
            with col_d:
                st.info(
                    "**À retenir.** En QCM, les modèles font environ deux fois mieux que le hasard. "
                    "En vrai/faux, ils font à peine mieux que pile ou face ; avec la consigne d'analyse (P3), "
                    "Ministral fait même pire que le hasard."
                )
                st.dataframe(
                    typ[["modele", "type_lib", "nb_answers", "pct_correct", "chance_pct", "pct_above_chance",
                         "pct_format_ok"]],
                    hide_index=True, width="stretch",
                    column_config={
                        "modele": "Modèle", "type_lib": "Type", "nb_answers": "Questions",
                        "pct_correct": st.column_config.NumberColumn("Réussite (%)", format="%.1f"),
                        "chance_pct": st.column_config.NumberColumn("Hasard (%)", format="%.0f"),
                        "pct_above_chance": st.column_config.NumberColumn("Écart (pt)", format="%+.1f"),
                        "pct_format_ok": st.column_config.NumberColumn("Conformité (%)", format="%.1f"),
                    },
                )
        filtres_actifs("accuracy_by_type", ignorer=("prompt_id",))

# --------------------------------------------------------------------------- #
# Onglet 4 : questions pièges
# --------------------------------------------------------------------------- #

with onglet_questions:
    st.subheader("Quelles questions piègent tous les modèles ?")
    qc = lire("question_consensus", "ORDER BY nb_correct_configurations, category, question_id")
    if qc.empty:
        st.info(AUCUN_RESULTAT)
    else:
        nb_conf = int(qc["nb_configurations"].max())
        comptes = qc["status"].value_counts()
        k1, k2, k3 = st.columns(3)
        k1.metric("Toujours réussies", nombre(comptes.get("toujours réussie", 0)),
                  f"{pct(100 * comptes.get('toujours réussie', 0) / len(qc))} des questions",
                  delta_color="off", delta_arrow="off", border=True,
                  help=f"Réussies par les {nb_conf} configurations (2 modèles × 3 prompts).")
        k2.metric("Toujours ratées", nombre(comptes.get("toujours ratée", 0)),
                  f"{pct(100 * comptes.get('toujours ratée', 0) / len(qc))} des questions",
                  delta_color="off", delta_arrow="off", border=True,
                  help=f"Ratées par les {nb_conf} configurations.")
        meme = qc[(qc["status"] == "toujours ratée") & (qc["nb_most_common_wrong_answer"] == nb_conf)]
        k3.metric("Ratées avec la même réponse fausse", nombre(len(meme)),
                  f"les {nb_conf} configurations se trompent pareil", delta_color="off", delta_arrow="off",
                  border=True)

        st.markdown(f"**Nombre de configurations (sur {nb_conf}) qui réussissent chaque question**")
        distrib = qc.groupby(["nb_correct_configurations", "difficulte"], as_index=False).size()
        distrib["ordre"] = distrib["difficulte"].map({v: i for i, v in enumerate(DIFFICULTES.values())})
        couleurs_diff = dict(zip(DIFFICULTES.values(), [BLEUS[1], BLEUS[2], BLEUS[4]]))
        afficher(
            alt.Chart(distrib)
            .mark_bar(stroke="white", strokeWidth=2)
            .encode(
                x=alt.X("nb_correct_configurations:O", title="Configurations qui réussissent la question",
                        axis=alt.Axis(labelAngle=0)),
                y=alt.Y("size:Q", title="Questions", stack="zero", axis=alt.Axis(labelExpr=MILLIERS_FR)),
                color=alt.Color("difficulte:N", title=None, legend=legende_haut(),
                                scale=alt.Scale(domain=list(couleurs_diff), range=list(couleurs_diff.values()))),
                order=alt.Order("ordre:Q"),
                tooltip=[alt.Tooltip("nb_correct_configurations:O", title="Réussie par"),
                         alt.Tooltip("difficulte:N", title="Difficulté"),
                         alt.Tooltip("size:Q", title="Questions", format=",")],
            )
            .properties(height=320)
        )
        st.caption("0 = ratée par toutes les configurations ; 6 = réussie par toutes. "
                   "Couleur = difficulté annoncée par OpenTDB.")

        st.markdown("**Explorer les questions**")
        c1, c2, c3 = st.columns([2, 2, 3])
        statuts = c1.multiselect("Statut", STATUTS, default=["toujours ratée"], key="statuts",
                                 placeholder="Tous les statuts")
        reussies = c2.slider("Réussie par (configurations)", 0, nb_conf, (0, nb_conf), key="reussies")
        recherche = c3.text_input("Texte de la question contient", key="recherche",
                                  placeholder="ex. invented, capital, Pokémon…")
        vue = qc[qc["nb_correct_configurations"].between(*reussies)]
        if statuts:
            vue = vue[vue["status"].isin(statuts)]
        if recherche.strip():
            vue = vue[vue["question"].str.contains(recherche.strip(), case=False, regex=False)]
        st.caption(f"{nombre(len(vue))} question(s)")
        colonnes_vue = ["category", "difficulte", "type_lib", "question", "correct_answer", "expected_letter",
                        "most_common_wrong_answer", "nb_most_common_wrong_answer", "nb_correct_configurations",
                        "correct_configurations", "status"]
        st.dataframe(
            vue[colonnes_vue], hide_index=True, width="stretch", height=420,
            column_config={
                "category": "Catégorie", "difficulte": "Difficulté", "type_lib": "Type",
                "question": st.column_config.TextColumn("Question", width="large"),
                "correct_answer": "Bonne réponse", "expected_letter": "Lettre attendue",
                "most_common_wrong_answer": "Réponse fausse la plus donnée",
                "nb_most_common_wrong_answer": "… donnée par",
                "nb_correct_configurations": st.column_config.ProgressColumn(
                    "Réussie par", format="%d", min_value=0, max_value=nb_conf),
                "correct_configurations": "Configurations justes", "status": "Statut",
            },
        )
        st.download_button("Télécharger ces questions (CSV)", vue[colonnes_vue].to_csv(index=False).encode("utf-8"),
                           file_name="questions_pieges.csv", mime="text/csv")
    filtres_actifs("question_consensus")

# --------------------------------------------------------------------------- #
# Onglet 5 : données des tables gold
# --------------------------------------------------------------------------- #

with onglet_donnees:
    table = st.selectbox("Table gold", MARTS)
    filtrer = st.toggle("Appliquer les filtres de la barre latérale", value=True)
    clause, params = where(table) if filtrer else ("", ())
    nb_lignes = requete(f"SELECT count(*) AS n FROM {table} {clause}", params).iloc[0]["n"]
    apercu = requete(f"SELECT * FROM {table} {clause} LIMIT 6000", params)
    st.caption(f"{nombre(nb_lignes)} ligne(s) · valeurs telles qu'en gold (taux non arrondis)")
    st.dataframe(apercu, hide_index=True, width="stretch")
    st.download_button("Télécharger (CSV)", apercu.to_csv(index=False).encode("utf-8"),
                       file_name=f"{table}.csv", mime="text/csv")
