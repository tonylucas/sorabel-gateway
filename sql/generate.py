"""Question en français → une requête SQL, ou un refus motivé.

Le tri et la génération tiennent dans **un seul appel au modèle** : lui demander
d'abord « cette question est-elle traitable ? » puis « écris le SQL » doublerait
la latence et le quota pour une décision qu'il prend de toute façon en lisant le
schéma. Il répond donc en JSON, avec une décision parmi quatre.

Ce module ne décide rien de la sécurité : il propose une requête, `sql.guard`
l'autorise ou non. Une instruction de prompt n'est pas une barrière.
"""

from __future__ import annotations

import json
import os
import sys
from functools import lru_cache
from pathlib import Path

from dotenv import dotenv_values

from sql.guard import Refus, valide
from sql.schema import ddl, sqlglot_schema

REPO_ROOT = Path(__file__).resolve().parent.parent


@lru_cache(maxsize=1)
def _fichier_env() -> dict[str, str | None]:
    return dotenv_values(REPO_ROOT / ".env")


def reglage(nom: str, defaut: str = "") -> str:
    """L'environnement d'abord, `.env` en repli — sans injecter le fichier entier.

    `load_dotenv()` pousserait tout `.env` dans `os.environ` et rendrait actives
    des variables que d'autres modules lisent (`EMBEDDING_MODEL`, `CHROMA_URL`,
    `SORABEL_PROFILE`) : on changerait le comportement de code qui ne demande
    rien. Ici on ne lit que les deux réglages du générateur.
    """
    return os.environ.get(nom) or _fichier_env().get(nom) or defaut


#: `flash-lite` suffit : le schéma tient en une page et la tâche est cadrée.
#: Le free tier facture surtout en latence — la suite d'acceptance coupe à 30 s.
MODELE = reglage("SORABEL_SQL_MODEL", "gemini-3.5-flash-lite")

#: Bornes réelles du jeu de données, calculées par `scripts/seed.py`. Sans elles,
#: « en avril » devient `EXTRACT(MONTH) = 4`, toutes années confondues.
PERIODE = ("2025-09-04", "2026-08-19")

REFUS_HORS_SCHEMA = "Cette question porte sur des données que la base Sorabel ne contient pas."
REFUS_INDISPONIBLE = (
    "Le service de génération de requêtes est momentanément indisponible. "
    "Réessayez dans un instant."
)

#: Un exemple par piège, pas pour la variété. Chacun est filtré par le garde
#: avant d'entrer dans le prompt : un profil ne découvre pas dans un exemple la
#: structure d'une table qu'on lui refuse.
EXEMPLES: tuple[tuple[str, str], ...] = (
    (
        "combien de commandes en avril ?",
        "SELECT COUNT(*) FROM commandes "
        "WHERE date_commande >= '2026-04-01' AND date_commande < '2026-05-01'",
    ),
    (
        "quel est le stock total de la REF-8842 ?",
        "SELECT SUM(quantite) AS stock_total FROM stocks WHERE ref = 'REF-8842'",
    ),
    (
        "quelles références sont sous leur seuil de réapprovisionnement à Lyon ?",
        "SELECT ref, entrepot, quantite, seuil_reappro FROM stocks "
        "WHERE entrepot = 'LYON' AND quantite < seuil_reappro",
    ),
    (
        "liste des commandes livrées en juin 2026",
        "SELECT id, client_id, date_commande, montant_ht FROM commandes "
        "WHERE statut = 'livree' "
        "AND date_commande >= '2026-06-01' AND date_commande < '2026-07-01'",
    ),
    (
        "les 5 produits les plus vendus en quantité",
        "SELECT p.ref, p.nom, SUM(v.quantite) AS total FROM ventes v "
        "JOIN produits p ON p.ref = v.ref GROUP BY p.ref, p.nom ORDER BY total DESC LIMIT 5",
    ),
    (
        "prix de vente HT du disjoncteur tétrapolaire 40 A",
        "SELECT ref, nom, prix_vente_ht FROM produits "
        "WHERE nom LIKE '%tétrapolaire%' AND nom LIKE '%40 A%'",
    ),
    (
        # Le seul pattern que le schéma commenté n'enseigne pas tout seul : une
        # agrégation sur `ventes` filtrée par période exige la jointure vers
        # `commandes`, qui seule porte la date. Question volontairement
        # différente de SQL-11 du jeu d'éval : on enseigne la jointure, pas
        # la réponse.
        "combien d'unités vendues en février 2026 ?",
        "SELECT SUM(v.quantite) AS unites FROM ventes v "
        "JOIN commandes c ON c.id = v.commande_id "
        "WHERE c.date_commande >= '2026-02-01' AND c.date_commande < '2026-03-01'",
    ),
    (
        "montant total des commandes de mars 2026",
        "SELECT SUM(montant_ht) FROM commandes "
        "WHERE date_commande >= '2026-03-01' AND date_commande < '2026-04-01'",
    ),
)

#: Chaque règle déclare les colonnes dont elle parle : une règle qui cite une
#: colonne hors du périmètre est retirée du prompt. Sans ce filtre, le profil
#: support lirait le nom `produits.marge_pct` dans ses propres consignes — la
#: fuite exacte que le DDL filtré cherche à éviter — et le modèle générerait un
#: SQL voué au refus, donc un appel gâché.
REGLES: tuple[tuple[tuple[str, ...], str], ...] = (
    (
        ("ventes.commande_id",),
        "- `commandes` est l'en-tête d'une commande : `montant_ht` y est **déjà "
        "agrégé**.\n  Un total sur une période se somme là, jamais sur les lignes de "
        "`ventes`.\n- `ventes` en est le détail, une ligne par produit commandé. Elle "
        "n'a pas de\n  date propre : passer par `commandes.date_commande` via "
        "`commande_id`.",
    ),
    (
        ("produits.marge_pct", "ventes.marge_ht"),
        "- Deux marges, deux unités : `produits.marge_pct` est la marge théorique du\n"
        "  catalogue en % (une référence, un classement) ; `ventes.marge_ht` est la "
        "marge\n  réalisée en euros (une période, un client, une commande). Sommer des\n"
        "  pourcentages n'a pas de sens.",
    ),
    (
        (),
        "- Trois conventions de casse cohabitent : `commandes.statut` sans accent\n"
        "  (`en_attente`, `preparee`, `expediee`, `livree`, `annulee`),\n"
        "  `stocks.entrepot` en majuscules (`LYON`), `clients.ville` capitalisée\n"
        "  (`Lyon`), `produits.categorie` accentuée (`Protection électrique`).",
    ),
    (
        (),
        "- Les dates sont du texte ISO `AAAA-MM-JJ`. Comparer par intervalle\n"
        "  demi-ouvert (`>= '2026-04-01' AND < '2026-05-01'`), pas avec `strftime`.\n"
        f"- Les données couvrent {PERIODE[0]} à {PERIODE[1]}. Une question sans année\n"
        "  désigne l'occurrence la plus récente : « en avril » = avril 2026.\n"
        "- Un libellé produit n'est jamais cité exactement : filtrer par fragments avec\n"
        "  `LIKE '%…%'`.",
    ),
)

DECISION = """\
Décision, à rendre dans le champ `decision` — les tester dans cet ordre :

1. `ecriture` — la question demande de modifier, supprimer ou insérer des données.
2. `hors_schema` — avant de conclure, relire les colonnes du schéma une par
   une : la bonne y est souvent sous un autre nom. `hors_schema` ne vaut que
   si **aucune** ne porte l'information — météo, dirigeants, actualité,
   documentation produit. Le schéma ci-dessus est complet : ne jamais inventer
   une colonne, et ne jamais répondre avec une colonne voisine faute d'avoir
   trouvé la bonne.
3. `ambigue` — l'information **est** dans le schéma, mais la question admet
   plusieurs lectures chiffrées incompatibles (« le meilleur client » : par
   chiffre d'affaires, par nombre de commandes ?). Remplir `precision` avec la
   question à reposer, en français. Deux garde-fous, à vérifier avant de
   choisir `ambigue` : chacune des lectures possibles doit se calculer avec
   une colonne du schéma ci-dessus — si aucune ne le peut, c'est
   `hors_schema`, pas `ambigue` ; et une question qui nomme déjà sa grandeur
   (« montant », « quantité », « nombre de… ») n'est pas ambiguë,
   même si le classement pourrait se faire autrement.
4. `sql` — sinon. Remplir `sql` avec une requête SQLite de lecture, seule.

Ne rien commenter, ne rien expliquer hors du JSON.\
"""

EN_TETE = """\
Tu traduis une question métier en français en **une** requête SQLite de lecture.

Règles de lecture du schéma, dans l'ordre où elles font échouer les réponses :
"""


@lru_cache(maxsize=8)
def consignes(profile: str) -> str:
    """Les consignes du profil : celles qui ne parlent que de colonnes visibles."""
    visibles = {
        f"{table}.{colonne}"
        for table, colonnes in sqlglot_schema(profile).items()
        for colonne in colonnes
    }
    regles = [texte for requises, texte in REGLES if set(requises) <= visibles]
    return f"{EN_TETE}\n" + "\n".join(regles) + f"\n\n{DECISION}"


REPONSE = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["sql", "ecriture", "hors_schema", "ambigue"]},
        "sql": {"type": "string"},
        "precision": {"type": "string"},
    },
    "required": ["decision"],
}


@lru_cache(maxsize=8)
def _exemples(profile: str) -> str:
    """Les exemples que ce profil a le droit de voir — filtrés *par le garde*.

    Réutiliser le garde plutôt que refaire le test de périmètre garantit qu'un
    exemple montré est un exemple exécutable : la règle ne peut pas diverger.
    """
    lignes = []
    for question, sql in EXEMPLES:
        try:
            valide(sql, profile)
        except Refus:
            continue
        lignes.append(f"Q : {question}\nSQL : {sql}")
    return "\n\n".join(lignes)


#: Le free tier répond entre 1 s et 35 s pour le même prompt, et rend des `429`
#: (15 requêtes/minute) et des `504` sporadiques. Ce plafond borne l'attente pour
#: qu'un appel qui ne reviendra pas se solde par un refus lisible et journalisé,
#: plutôt que par un délai de protocole côté client.
#:
#: Il doit rester **sous** le budget par appel de la suite d'acceptance
#: (`GATEWAY_TEST_TIMEOUT`, que le `Makefile` relève à 60 s) : le couper plus
#: court transformerait un appel lent mais valide en échec.
TIMEOUT_MS = int(reglage("SORABEL_SQL_TIMEOUT_MS", "45000"))


@lru_cache(maxsize=1)
def _client():
    """Chargé paresseusement : la suite d'acceptance relance un process par session."""
    from google import genai
    from google.genai import types

    cle = reglage("GOOGLE_API_KEY")
    if not cle:
        raise Refus("llm_indisponible", REFUS_INDISPONIBLE)
    return genai.Client(api_key=cle, http_options=types.HttpOptions(timeout=TIMEOUT_MS))


def prompt(question: str, profile: str) -> str:
    return (
        f"{consignes(profile)}\n\n"
        f"--- Schéma de la base ---\n{ddl(profile)}\n\n"
        f"--- Exemples ---\n{_exemples(profile)}\n\n"
        f"--- Question ---\n{question}"
    )


def genere(question: str, profile: str) -> str:
    """Rend la requête SQL proposée, ou lève `Refus` si la question n'en appelle pas."""
    from google.genai import errors, types

    try:
        reponse = _client().models.generate_content(
            model=MODELE,
            contents=prompt(question, profile),
            config=types.GenerateContentConfig(
                temperature=0,
                response_mime_type="application/json",
                response_json_schema=REPONSE,
                # Le schéma tient en une page et la tâche est cadrée par huit
                # exemples : le raisonnement coûterait des secondes sans rien ajouter.
                thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL),
            ),
        )
    except errors.APIError as exc:
        # Le free tier rend des 429 (15 requêtes/minute) et des 504 sporadiques.
        # Le détail va au flux d'erreur — que le canal stdio tient séparé du
        # protocole, et que Cloud Logging capture — et pas au client.
        print(f"Génération SQL indisponible : {exc}", file=sys.stderr)
        raise Refus("llm_indisponible", REFUS_INDISPONIBLE) from exc

    return _decide(reponse.text or "")


def _decide(brut: str) -> str:
    try:
        rendu = json.loads(brut)
    except json.JSONDecodeError as exc:
        raise Refus("invalid_sql", REFUS_INDISPONIBLE) from exc

    decision = rendu.get("decision")
    if decision == "sql" and rendu.get("sql"):
        return str(rendu["sql"])
    if decision == "ecriture":
        from sql.guard import REFUS_ECRITURE

        raise Refus("write_attempt", REFUS_ECRITURE)
    if decision == "ambigue":
        precision = rendu.get("precision") or "Pouvez-vous préciser votre question ?"
        raise Refus("ambiguous", str(precision), status="clarification")
    raise Refus("out_of_schema", REFUS_HORS_SCHEMA)
