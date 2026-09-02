"""Réponse documentaire : le passage retenu, et ses citations.

**La citation est construite depuis les métadonnées, jamais rédigée.** C'est
l'invariant E1 : un modèle qui invente un titre ou une date produit une réponse
d'apparence sourcée et fausse.

La réponse elle-même est extractive — le passage du document retenu. Les
documents du corpus font une page : le passage *est* la réponse, et la mise en
forme revient au LLM du host, qui reçoit ce résultat comme *tool result*. Un
appel de génération de plus côté serveur coûterait une latence et un quota pour
reformuler ce qu'on a déjà.

ponytail: extractif ; passer à une synthèse Gemini côté serveur si un client
sans LLM doit un jour lire ces réponses directement.
"""

from __future__ import annotations

from retrieval.search import Hit

REFUS_HORS_CORPUS = (
    "Je ne trouve rien dans la documentation Sorabel qui réponde à cette "
    "question. Elle sort du périmètre du corpus (fiches techniques, notices, "
    "procédures SAV, notes internes)."
)


def citation(hit: Hit) -> dict[str, str]:
    """Titre, référence, date — les trois champs que E1 impose sur toute réponse.

    Les procédures SAV et les notes internes n'ont pas de référence produit :
    leur `doc_id` en tient lieu, c'est la référence du document.
    """
    meta = hit.metadata
    return {
        "titre": meta.get("titre") or meta.get("doc_id", ""),
        "reference": meta.get("reference") or meta.get("doc_id", ""),
        "date": meta.get("date", ""),
        "doc_type": meta.get("doc_type", ""),
        "doc_id": meta.get("doc_id", ""),
        "version": meta.get("version", ""),
    }


def redige(hits: list[Hit], n: int = 2) -> tuple[str, list[dict]]:
    """(réponse, citations) à partir des `n` meilleurs passages."""
    retenus = hits[:n]
    if not retenus:
        return "", []

    blocs = [f"[{citation(hit)['reference']}] {hit.text.strip()}" for hit in retenus]
    return "\n\n".join(blocs), [citation(hit) for hit in retenus]
