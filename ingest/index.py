"""Indexation du corpus dans Chroma — un document, un chunk.

Le plus long document du corpus fait une page : le découper n'apporterait rien
et couperait une caractéristique de son titre. Le chunking arrivera si le corpus
grossit ; en attendant, `doc_id` identifie à la fois le document et son vecteur.

Usage : ``make ingest``.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path

# Avant l'import : la télémétrie de Chroma 0.5 échoue bruyamment sur stderr, et
# la coupure par `Settings` arrive trop tard.
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

import chromadb  # noqa: E402

from ingest.parse import Document, dedupe, load_corpus  # noqa: E402
from retrieval.embed import embed  # noqa: E402

# Même désactivée, Chroma 0.5.23 tente l'envoi et journalise l'échec en `error`.
# C'est un bug connu de cette version, sans effet — mais « Failed » dans la
# sortie de `make ingest` laisse croire à une panne.
logging.getLogger("chromadb.telemetry").setLevel(logging.CRITICAL)

REPO_ROOT = Path(__file__).resolve().parent.parent
CHROMA_PATH = Path(os.environ.get("CHROMA_PATH", REPO_ROOT / ".chroma"))
COLLECTION = "sorabel"


@lru_cache(maxsize=1)
def client() -> chromadb.ClientAPI:
    """Client persistant sur disque — l'index est embarqué, pas un service.

    Le corpus est statique : rien à synchroniser, et l'image de production
    contient déjà l'index construit au build. Mis en cache : ouvrir un client
    par requête rouvrait la base à chaque appel.
    """
    return chromadb.PersistentClient(
        path=str(CHROMA_PATH),
        settings=chromadb.Settings(anonymized_telemetry=False),
    )


def collection(create: bool = False):
    api = client()
    if create:
        return api.get_or_create_collection(COLLECTION, metadata={"hnsw:space": "cosine"})
    return api.get_collection(COLLECTION)


def metadata_of(doc: Document) -> dict[str, str]:
    """Chroma n'accepte que des scalaires : les références citées sont aplaties."""
    return {
        "doc_id": doc.doc_id,
        "doc_type": doc.doc_type,
        "titre": doc.titre,
        "reference": doc.reference or "",
        "version": doc.version,
        "date": doc.date,
        "path": str(doc.path.relative_to(REPO_ROOT)),
        "mentioned_refs": " ".join(doc.mentioned_refs),
    }


def build() -> dict:
    documents = load_corpus()
    kept, dropped = dedupe(documents)

    api = client()
    if COLLECTION in [c.name for c in api.list_collections()]:
        api.delete_collection(COLLECTION)
    coll = api.get_or_create_collection(COLLECTION, metadata={"hnsw:space": "cosine"})

    # Le titre est répété avant le corps : il porte le libellé produit ou le nom
    # de la procédure, que les questions en langage naturel reprennent presque
    # mot pour mot. Mesuré : sans cette pondération, le Recall@5 des questions
    # `couverte` tombe de 93 % à 86 %.
    passages = [f"{doc.titre}\n{doc.titre}\n{doc.text}" for doc in kept]
    coll.add(
        ids=[doc.doc_id for doc in kept],
        documents=passages,
        embeddings=embed(passages),
        metadatas=[metadata_of(doc) for doc in kept],
    )
    return {"indexes": len(kept), "ecartes": dropped, "fichiers": len(documents)}


def main() -> None:
    rapport = build()
    print(f"Index construit : {CHROMA_PATH}")
    print(f"  {rapport['fichiers']} fichiers lus")
    print(f"  {rapport['indexes']} documents indexés")
    print(f"  {len(rapport['ecartes'])} versions écartées (dédoublonnage par doc_id) :")
    for doc in rapport["ecartes"][:5]:
        print(f"    {doc.path.name} — v{doc.version} remplacée")
    if len(rapport["ecartes"]) > 5:
        print(f"    … et {len(rapport['ecartes']) - 5} autres")


if __name__ == "__main__":
    main()
