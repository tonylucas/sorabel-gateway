"""Le décorateur d'accès : autorise, exécute, journalise — une fois par appel."""

from __future__ import annotations

import json

import pytest

from gateway import access, tools


@pytest.fixture(autouse=True)
def journal(tmp_path, monkeypatch):
    path = tmp_path / "journal.jsonl"
    monkeypatch.setenv("GATEWAY_JOURNAL", str(path))
    return path


def entries(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_tool_autorise_repond_et_journalise(journal):
    access.set_profile("support")
    envelope = json.loads(tools.check_stock(reference="REF-8842"))

    assert envelope["status"] == "ok"
    (entry,) = entries(journal)
    assert entry["profile"] == "support"
    assert entry["tool"] == "check_stock"
    assert entry["status"] == "ok"
    assert entry["arguments"] == {"reference": "REF-8842"}


def test_tool_hors_matrice_refuse_sans_executer(journal):
    access.set_profile("support")
    envelope = json.loads(tools.get_schema())

    assert envelope["status"] == "refused"
    assert envelope["payload"]["code"] == "unauthorized_tool"
    assert envelope["message"].strip()
    # Le refus ne nomme pas ce qu'il protège.
    assert "get_schema" not in envelope["message"]

    (entry,) = entries(journal)
    assert entry["status"] == "refused"


def test_une_entree_par_appel_ni_plus_ni_moins(journal):
    access.set_profile("support")
    tools.list_sources()
    tools.get_schema()  # refusé
    tools.answer_question(question="délai d'un échange standard ?")

    journalisees = entries(journal)
    assert [e["tool"] for e in journalisees] == ["list_sources", "get_schema", "answer_question"]
    assert journalisees[0]["status"] == "ok"
    assert journalisees[1]["status"] == "refused"


@pytest.mark.parametrize(
    ("profile", "attendu"),
    [("support", "refused"), ("commercial", "ok"), ("dev", "ok")],
)
def test_get_schema_suit_la_matrice(profile, attendu):
    access.set_profile(profile)
    assert json.loads(tools.get_schema())["status"] == attendu


def test_profil_inconnu_retombe_sur_support():
    access.set_profile("root")
    assert access.current_profile() == "support"
    assert json.loads(tools.get_schema())["status"] == "refused"


def test_le_catalogue_est_complet():
    assert {fn.__name__ for fn in tools.CATALOGUE} == set(access.ALL_TOOLS)


def test_une_exception_devient_une_enveloppe(journal):
    # Sans le filet, elle ressortirait en erreur de protocole MCP : le client
    # ne recevrait pas d'enveloppe, et l'appel manquerait au journal.
    @access.tool_access("check_stock")
    def explose(**_):
        raise ValueError("boum")

    access.set_profile("support")
    envelope = json.loads(explose(reference="REF-8842"))

    assert envelope["status"] == "refused"
    assert envelope["payload"]["code"] == "erreur_interne"
    assert "boum" not in envelope["message"]  # le détail reste au journal

    (entry,) = entries(journal)
    assert entry["status"] == "refused"
    assert "ValueError: boum" == entry["erreur"]
