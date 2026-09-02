"""Ingestion et recherche — les règles qui ne se voient pas dans un score."""

from __future__ import annotations

from pathlib import Path

import pytest

from ingest.parse import Document, dedupe, doc_id_from, load_corpus
from retrieval.search import pertinent, search


@pytest.mark.parametrize(
    ("nom", "attendu"),
    [
        ("REF-1024-v2.1.pdf", "REF-1024"),
        ("notice-REF-1459-v1.1.pdf", "notice-REF-1459"),
        ("proc-casse-transport-01-v2.0.html", "proc-casse-transport-01"),
        ("note-2024-01-02-reunion-achat-32.md", "note-2024-01-02-reunion-achat-32"),
    ],
)
def test_doc_id_retire_le_suffixe_de_version(nom, attendu):
    assert doc_id_from(Path(nom)) == attendu


def test_dedoublonnage_garde_la_version_la_plus_recente():
    def doc(version: str, date: str) -> Document:
        return Document(
            doc_id="REF-1",
            path=Path(f"REF-1-v{version}.pdf"),
            doc_type="fiche",
            titre="t",
            version=version,
            date=date,
            text="x",
        )

    kept, dropped = dedupe(
        [doc("1.0", "2022-01-01"), doc("2.1", "2024-01-01"), doc("2.0", "2023-01-01")]
    )
    assert [d.version for d in kept] == ["2.1"]
    assert sorted(d.version for d in dropped) == ["1.0", "2.0"]


def test_la_fiche_et_la_notice_d_une_meme_reference_sont_deux_documents():
    # Dédoublonner par référence produit en écraserait un.
    kept, _ = dedupe(load_corpus())
    ids = {d.doc_id for d in kept}
    assert {"REF-1459", "notice-REF-1459"} <= ids


def test_une_reference_citee_en_exemple_n_est_pas_la_reference_du_document():
    # Les procédures SAV citent une référence à titre d'exemple : un grep global
    # ferait passer une procédure générique pour une fiche produit.
    kept, _ = dedupe(load_corpus())
    sav = [d for d in kept if d.doc_type == "procedure_sav"]
    assert sav
    assert all(d.reference is None for d in sav)
    assert any(d.mentioned_refs for d in sav)


def test_recherche_par_reference_exacte_remonte_la_fiche_en_tete():
    hits = search("REF-8842", k=5)
    assert hits[0].metadata["reference"] == "REF-8842"
    assert hits[0].metadata["doc_type"] == "fiche_technique"


def test_le_dense_seul_rate_les_references():
    # La raison d'être de l'hybride, et ce que chiffre eval/rapport_gain.md.
    dense = search("REF-8842", k=5, mode="dense")
    assert all(hit.metadata["reference"] != "REF-8842" for hit in dense)


def test_le_perimetre_du_profil_filtre_les_resultats():
    perimetre = frozenset({"fiche_technique", "notice", "procedure_sav"})
    hits = search("politique tarifaire et remises fournisseurs", k=10, doc_types=perimetre)
    assert hits
    assert all(hit.metadata["doc_type"] != "note_interne" for hit in hits)


def test_hors_corpus_ne_passe_pas_la_porte():
    question = "quelle est la politique de télétravail chez Sorabel ?"
    repond, _, _ = pertinent(question, search(question, k=5))
    assert not repond


def test_question_couverte_passe_la_porte():
    question = "quelle est la procédure de retour d'un produit défectueux sous garantie ?"
    repond, _, _ = pertinent(question, search(question, k=5))
    assert repond
