"""Acceptance — serveur MCP, matrice d'accès et journal (exigences DSI E4, E5)."""

from __future__ import annotations

from tests.conftest import ALL_TOOLS, TOOLS_BY_PROFILE, gateway_session, read_journal


async def test_matrice_d_acces_respectee():
    # E4 : un client au profil autorisé n'accède qu'aux tools prévus par la
    # matrice ; tout tool hors matrice est refusé.
    for profile, autorises in TOOLS_BY_PROFILE.items():
        async with gateway_session(profile) as call:
            for tool in ALL_TOOLS:
                if tool in autorises:
                    continue
                result = await call(tool, {})
                assert result["status"] == "refused", f"{profile} ne doit pas accéder à {tool}"


async def test_refus_message_clair_et_journalise(journal_path):
    # E4 + E5 : un appel non autorisé est refusé avec un message clair et
    # journalisé.
    async with gateway_session("support", journal_path) as call:
        result = await call("get_schema", {})
    assert result["status"] == "refused"
    assert result["message"].strip()

    entries = read_journal(journal_path)
    assert any(
        e["profile"] == "support" and e["tool"] == "get_schema" and e["status"] == "refused"
        for e in entries
    )


async def test_briques_du_rag_utilisables_separement():
    # E4 : un client qui veut chercher sans générer enchaîne search_docs puis
    # get_document — les briques fonctionnent séparément.
    async with gateway_session("commercial") as call:
        search = await call(
            "search_docs", {"query": "retour d'un produit défectueux sous garantie"}
        )
        assert search["status"] == "ok"
        assert search["payload"]["hits"]

        doc_id = search["payload"]["hits"][0]["doc_id"]
        document = await call("get_document", {"doc_id": doc_id})
    assert document["status"] == "ok"
    assert document["payload"]["text"].strip()
    assert document["payload"]["metadata"]


async def test_journal_exhaustif_autorises_et_refuses(journal_path):
    # E5 : sur une session de démonstration, tous les appels — autorisés comme
    # refusés — figurent au journal.
    calls = [
        ("answer_question", {"question": "délai d'un échange standard ?"}),
        ("check_stock", {"reference": "REF-8842"}),
        ("get_schema", {}),  # hors matrice pour le profil support
    ]
    async with gateway_session("support", journal_path) as call:
        for tool, arguments in calls:
            await call(tool, arguments)

    entries = read_journal(journal_path)
    assert len(entries) == len(calls)
    assert [e["tool"] for e in entries] == [tool for tool, _ in calls]
    statuses = {e["status"] for e in entries}
    assert "refused" in statuses
    assert statuses - {"refused"}, "le journal doit aussi tracer les appels autorisés"
