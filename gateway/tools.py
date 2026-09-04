"""Le catalogue : les huit tools exposés par la gateway.

Chaque fonction porte sa description — c'est elle que lira le LLM d'un host
qu'on ne contrôle pas, et donc le seul levier sur le choix du tool. Elles disent
toutes quand s'en servir **et quand ne pas** s'en servir.

Les moteurs sont importés **dans** les fonctions : la suite d'acceptance relance
un process par session et coupe à 30 s, un import lourd au démarrage la ferait
tomber avant le premier appel.
"""

from __future__ import annotations

from gateway.access import (
    clarification,
    collections,
    current_profile,
    hors_corpus,
    ok,
    refused,
    tool_access,
)


def _perimetre() -> frozenset[str]:
    """Types de documents visibles par le profil courant — filtre appliqué au retrieval."""
    return collections(current_profile())


# ── Documentaire ─────────────────────────────────────────────────────────────


@tool_access("answer_question")
def answer_question(question: str) -> dict:
    """Répond à une question sur la documentation Sorabel, sources à l'appui.

    À utiliser quand l'utilisateur attend une réponse rédigée : procédure SAV,
    garantie, caractéristiques d'un produit. Chaque réponse cite ses sources —
    titre, référence, date, et le **nom exact du fichier** dont elle vient
    (`payload.sources[].fichier`), à citer à l'utilisateur. Hors du corpus,
    l'outil le dit au lieu d'inventer.

    Ne pas l'utiliser pour obtenir une liste de documents à parcourir soi-même
    (voir `search_docs`), ni pour un stock ou une commande (voir `check_stock`,
    `order_status`, `ask_database`).
    """
    from retrieval.answer import REFUS_HORS_CORPUS, redige
    from retrieval.search import pertinent, search

    hits = search(question, k=5, doc_types=_perimetre())
    repond, cosinus, bm25 = pertinent(question, hits)
    if not repond:
        # Sous le seuil, on ne rédige pas : E1 veut un aveu d'ignorance, pas une
        # réponse plausible bâtie sur des passages hors sujet.
        return hors_corpus(REFUS_HORS_CORPUS, cosinus=round(cosinus, 3), bm25=round(bm25, 2))

    texte, sources = redige(hits)
    return ok(answer=texte, sources=sources, cosinus=round(cosinus, 3))


@tool_access("search_docs")
def search_docs(query: str, k: int = 5, mode: str = "hybride") -> dict:
    """Cherche des passages dans le corpus documentaire et renvoie les meilleurs.

    À utiliser quand on veut des sources à examiner plutôt qu'une réponse
    rédigée — le cas d'un IDE, ou d'un enchaînement avec `get_document`. Accepte
    aussi bien une question en langage naturel qu'une référence exacte
    (« REF-8842 »).

    `mode` vaut `hybride` (défaut, dense + lexical fusionnés), `dense` ou
    `lexical` — les deux derniers servent à mesurer, pas à répondre.

    Ne pas l'utiliser quand l'utilisateur attend une réponse en français :
    prendre `answer_question`.
    """
    from retrieval.search import DEFAULT_MODE, MODES, search

    if mode not in MODES:
        return refused("bad_argument", f"Mode de recherche inconnu : {mode!r}.")

    hits = search(query, k=k, mode=mode, doc_types=_perimetre())
    return ok(hits=[hit.as_dict() for hit in hits], query=query, k=k, mode=mode or DEFAULT_MODE)


@tool_access("get_document")
def get_document(doc_id: str) -> dict:
    """Renvoie le texte intégral d'un document et ses métadonnées.

    À utiliser après `search_docs`, avec le `doc_id` d'un résultat, quand un
    extrait ne suffit pas.

    Ne pas l'utiliser pour chercher : le `doc_id` doit être connu.
    """
    from retrieval.search import get_document as lire

    trouve = lire(doc_id)
    if trouve is None:
        return refused("not_found", f"Aucun document ne porte l'identifiant « {doc_id} ».")

    text, metadata = trouve
    if metadata.get("doc_type") not in _perimetre():
        # Même message que l'absence : dire « existe mais interdit » renseigne
        # sur ce qu'on protège.
        return refused("not_found", f"Aucun document ne porte l'identifiant « {doc_id} ».")

    return ok(text=text, metadata=metadata, doc_id=doc_id)


@tool_access("list_sources")
def list_sources() -> dict:
    """Liste les catégories de documents visibles par le profil courant.

    À utiliser pour savoir ce que couvre le corpus avant d'y chercher quoi que
    ce soit.

    Ne pas l'utiliser pour répondre à une question : elle ne renvoie aucun
    contenu, seulement le périmètre.
    """
    from retrieval.search import list_doc_types

    return ok(sources=list_doc_types(_perimetre()))


# ── Données ──────────────────────────────────────────────────────────────────


@tool_access("ask_database")
def ask_database(question: str) -> dict:
    """Interroge la base Sorabel en langage naturel, en lecture seule.

    À utiliser pour toute question chiffrée qui n'a pas de tool dédié : nombre
    de commandes sur une période, chiffre d'affaires, produits les plus vendus,
    clients par ville. Renvoie toujours la requête SQL exécutée avec le
    résultat.

    Ne pas l'utiliser pour le stock d'une référence connue (`check_stock`) ni
    pour l'état d'une commande dont on a l'identifiant (`order_status`) : ces
    deux-là sont plus rapides et plus sûrs.
    """
    from sql import db
    from sql.generate import genere
    from sql.guard import Refus, valide

    profile = current_profile()
    try:
        sql = valide(genere(question, profile), profile)
    except Refus as refus:
        # Sur refus, la requête ne repart pas au client : lui rendre
        # `SELECT marge_ht …` lui apprendrait le nom de la colonne protégée.
        # Le journal, lui, la conserve.
        if refus.status == "clarification":
            return clarification(refus.code, refus.message)
        return refused(refus.code, refus.message)

    colonnes, lignes = db.run(sql)
    return ok(sql=sql, rows=lignes, columns=colonnes, question=question)


@tool_access("get_schema")
def get_schema() -> dict:
    """Renvoie le schéma de la base, commenté et restreint au profil courant.

    À utiliser pour comprendre les tables et colonnes disponibles avant
    d'écrire une question — l'outil de l'IDE.

    Ne pas l'utiliser pour obtenir des données : il ne renvoie que la structure.
    """
    from sql.schema import ddl, sqlglot_schema

    profile = current_profile()
    schema = sqlglot_schema(profile)
    return ok(ddl=ddl(profile), tables={table: list(cols) for table, cols in schema.items()})


@tool_access("check_stock")
def check_stock(reference: str) -> dict:
    """Donne le stock d'une référence produit, entrepôt par entrepôt.

    À utiliser dès qu'une référence au format « REF-8842 » est connue : réponse
    immédiate, sans génération de requête.

    Ne pas l'utiliser si la référence est inconnue — chercher d'abord le produit
    avec `ask_database` ou `search_docs`.
    """
    from sql import db

    colonnes, lignes = db.run(
        "SELECT entrepot, quantite, seuil_reappro FROM stocks "
        "WHERE ref = %s ORDER BY entrepot",
        (reference.strip().upper(),),
    )
    if not lignes:
        return refused("not_found", f"Aucun stock connu pour la référence « {reference} ».")

    entrepots = [dict(zip(colonnes, ligne, strict=True)) for ligne in lignes]
    return ok(
        reference=reference.strip().upper(),
        entrepots=entrepots,
        total=sum(e["quantite"] for e in entrepots),
        sous_seuil=[e["entrepot"] for e in entrepots if e["quantite"] < e["seuil_reappro"]],
    )


@tool_access("order_status")
def order_status(order_id: str) -> dict:
    """Donne l'état d'une commande à partir de son identifiant.

    À utiliser quand l'identifiant est connu, au format « CMD-2026-0042 ».

    Ne pas l'utiliser pour retrouver les commandes d'un client ou d'une période :
    c'est le travail d'`ask_database`.
    """
    from sql import db

    colonnes, lignes = db.run(
        "SELECT c.id, c.date_commande, c.statut, c.montant_ht, cl.raison_sociale "
        "FROM commandes c JOIN clients cl ON cl.id = c.client_id WHERE c.id = %s",
        (order_id.strip().upper(),),
    )
    if not lignes:
        return refused("not_found", f"Aucune commande ne porte l'identifiant « {order_id} ».")

    return ok(**dict(zip(colonnes, lignes[0], strict=True)))


#: Le catalogue, dans l'ordre du cadrage. Les canaux enregistrent cette liste.
CATALOGUE = (
    answer_question,
    search_docs,
    get_document,
    list_sources,
    ask_database,
    get_schema,
    check_stock,
    order_status,
)
