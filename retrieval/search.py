"""Recherche documentaire : dense, lexicale, et leur fusion.

Les trois modes restent accessibles : le dense n'est pas une étape jetable, il
est la **baseline** que E6 demande de comparer. C'est aussi l'instrument de
mesure de `eval/run_eval.py`.

Chroma 0.5 n'a pas de recherche hybride native — la fusion RRF est faite ici,
sur les rangs des deux listes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

from ingest.index import collection

REF_PATTERN = re.compile(r"REF-\d{4}", re.IGNORECASE)
TOKEN_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")

MODES = ("dense", "lexical", "hybride")
DEFAULT_MODE = "hybride"

#: Constante de la fusion RRF. 60 est la valeur de l'article d'origine : elle
#: aplatit l'écart entre les premiers rangs, donc un document trouvé par les
#: deux moteurs passe devant un premier de liste trouvé par un seul.
RRF_K = 60

#: Porte de pertinence, calibrée sur les 30 questions de `eval/questions_rag.jsonl`
#: (voir `eval/rapport_gain.md`). Deux signaux, comme la recherche elle-même :
#: aucun des deux ne sépare seul le corpus du hors-corpus.
SEUIL_COSINUS = 0.48
SEUIL_LEXICAL = 18.0


@dataclass
class Hit:
    doc_id: str
    score: float
    text: str
    metadata: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "score": round(self.score, 4),
            "text": self.text,
            "metadata": self.metadata,
        }


def tokenize(text: str) -> list[str]:
    """`REF-8842` reste un seul token : c'est ce qui rend la référence trouvable."""
    return TOKEN_PATTERN.findall(text.lower())


@lru_cache(maxsize=1)
def _corpus() -> tuple[list[str], list[str], list[dict]]:
    """Le corpus indexé, chargé une fois. 350 documents courts : tout tient en RAM."""
    try:
        data = collection().get(include=["documents", "metadatas"])
    except Exception as exc:  # collection absente
        raise RuntimeError("index documentaire introuvable — lancer `make ingest` d'abord") from exc
    return data["ids"], data["documents"], data["metadatas"]


@lru_cache(maxsize=1)
def _bm25():
    from rank_bm25 import BM25Okapi

    _, documents, _ = _corpus()
    return BM25Okapi([tokenize(doc) for doc in documents])


def _autorises(doc_types: frozenset[str] | None, refs: tuple[str, ...]) -> set[str] | None:
    """Identifiants candidats après filtrage par profil et routage par référence.

    `None` = aucun filtre. Le filtrage par profil s'applique **dans tous les
    modes** : c'est une règle d'accès, pas une optimisation. Le routage par
    référence, lui, fait partie de la stratégie hybride.

    Le routage est **abandonné s'il ne laisse rien** : mieux vaut une recherche
    large qu'une réponse vide sur une référence absente du corpus.
    """
    ids, _, metadatas = _corpus()
    candidats = set(ids)

    if doc_types is not None:
        candidats &= {i for i, m in zip(ids, metadatas) if m.get("doc_type") in doc_types}

    if refs:
        cibles = {i for i, m in zip(ids, metadatas) if m.get("reference") in refs}
        if cibles:
            candidats &= cibles

    return candidats


def _dense(query: str, n: int, candidats: set[str] | None) -> list[tuple[str, float]]:
    """Rangs denses et cosinus. Chroma renvoie une distance : 1 - distance.

    Le filtrage est passé à Chroma, pas appliqué après coup : sinon un document
    autorisé mais classé 300e disparaîtrait au lieu de remonter.
    """
    from retrieval.embed import embed_query

    ids, _, _ = _corpus()
    where = None
    if candidats is not None and len(candidats) < len(ids):
        where = {"doc_id": {"$in": sorted(candidats)}}

    result = collection().query(
        query_embeddings=[embed_query(query)],
        n_results=min(n, len(candidats) if candidats is not None else len(ids)),
        where=where,
        include=["distances"],
    )
    return [(i, 1.0 - d) for i, d in zip(result["ids"][0], result["distances"][0])]


def _lexical(query: str, n: int, candidats: set[str] | None) -> list[tuple[str, float]]:
    ids, _, _ = _corpus()
    scores = _bm25().get_scores(tokenize(query))
    pairs = [(i, float(s)) for i, s in zip(ids, scores) if s > 0]
    if candidats is not None:
        pairs = [(i, s) for i, s in pairs if i in candidats]
    return sorted(pairs, key=lambda p: p[1], reverse=True)[:n]


def _rrf(*listes: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """Fusion par rang, pas par score : les échelles cosinus et BM25 sont incomparables."""
    fusion: dict[str, float] = {}
    for liste in listes:
        for rang, (doc_id, _) in enumerate(liste, start=1):
            fusion[doc_id] = fusion.get(doc_id, 0.0) + 1.0 / (RRF_K + rang)
    return sorted(fusion.items(), key=lambda p: p[1], reverse=True)


def search(
    query: str,
    k: int = 5,
    mode: str = DEFAULT_MODE,
    doc_types: frozenset[str] | None = None,
) -> list[Hit]:
    if mode not in MODES:
        raise ValueError(f"mode inconnu : {mode!r} (attendu : {', '.join(MODES)})")

    # Le routage par référence appartient à la stratégie hybride : le mode dense
    # doit rester la baseline nue que E6 demande de comparer.
    refs = tuple(ref.upper() for ref in REF_PATTERN.findall(query)) if mode == "hybride" else ()
    candidats = _autorises(doc_types, refs)
    profondeur = max(k * 4, 20)

    if mode == "dense":
        classement = _dense(query, profondeur, candidats)
    elif mode == "lexical":
        classement = _lexical(query, profondeur, candidats)
    else:
        classement = _rrf(
            _dense(query, profondeur, candidats),
            _lexical(query, profondeur, candidats),
        )

    ids, documents, metadatas = _corpus()
    par_id = {i: (t, m) for i, t, m in zip(ids, documents, metadatas)}
    return [
        Hit(doc_id=doc_id, score=score, text=par_id[doc_id][0], metadata=dict(par_id[doc_id][1]))
        for doc_id, score in classement[:k]
        if doc_id in par_id
    ]


def cosinus_max(query: str, hits: list[Hit], doc_types: frozenset[str] | None = None) -> float:
    """Cosinus du meilleur résultat — l'échelle sur laquelle le seuil est posé.

    Les scores RRF ne sont pas comparables d'une question à l'autre ; le cosinus,
    si. Le seuil se lit donc toujours sur le dense, quel que soit le mode.
    """
    if not hits:
        return 0.0
    dense = dict(_dense(query, len(hits), {hit.doc_id for hit in hits}))
    return max(dense.values(), default=0.0)


def pertinent(query: str, hits: list[Hit]) -> tuple[bool, float, float]:
    """La porte : répond-on, et sur quelles valeurs ? → (décision, cosinus, BM25).

    Trois preuves, par ordre de force :

    1. **une référence produit de la question figure dans les résultats** — c'est
       une correspondance exacte, et le cosinus d'une requête réduite à
       `REF-8842` est structurellement bas : l'exiger ferait refuser ce que E2
       impose de traiter ;
    2. le cosinus du meilleur résultat passe le seuil ;
    3. son score BM25 le passe — un recouvrement lexical fort est une preuve que
       le sémantique peut manquer (« que faire si un colis arrive endommagé ? »).

    Sous les trois, `answer_question` refuse au lieu de rédiger.
    """
    if not hits:
        return False, 0.0, 0.0

    cos = cosinus_max(query, hits)
    lexical = dict(_lexical(query, len(hits), {hit.doc_id for hit in hits}))
    bm25 = max(lexical.values(), default=0.0)

    refs_query = {ref.upper() for ref in REF_PATTERN.findall(query)}
    if refs_query & {hit.metadata.get("reference", "") for hit in hits}:
        return True, cos, bm25

    return cos >= SEUIL_COSINUS or bm25 >= SEUIL_LEXICAL, cos, bm25


def get_document(doc_id: str) -> tuple[str, dict] | None:
    ids, documents, metadatas = _corpus()
    for i, text, meta in zip(ids, documents, metadatas):
        if i == doc_id:
            return text, dict(meta)
    return None


def list_doc_types(doc_types: frozenset[str] | None = None) -> list[dict]:
    """Périmètre documentaire visible : un compte par type de document."""
    _, _, metadatas = _corpus()
    comptes: dict[str, int] = {}
    for meta in metadatas:
        doc_type = meta.get("doc_type", "")
        if doc_types is None or doc_type in doc_types:
            comptes[doc_type] = comptes.get(doc_type, 0) + 1
    return [{"doc_type": t, "documents": n} for t, n in sorted(comptes.items())]
