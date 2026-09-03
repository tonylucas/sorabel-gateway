"""Le décorateur d'accès : autorise, exécute, journalise — une fois par appel."""

from __future__ import annotations

import json

import pytest

from gateway import access, tools
from gateway.access import ALL_TOOLS


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


# ── access.yaml : la matrice hors du code ────────────────────────────────────


def test_le_yaml_livre_dit_la_matrice_de_la_specification():
    # `tests/conftest.py` est fourni et fait foi : le fichier de gouvernance
    # doit dire la même chose que la spécification, sinon il ne gouverne rien.
    assert access.tools_of("support") == frozenset(ALL_TOOLS) - {"get_schema"}
    assert access.tools_of("commercial") == frozenset(ALL_TOOLS)
    assert "note_interne" not in access.collections("support")
    assert "note_interne" in access.collections("commercial")

    tables, interdites = access.sql_scope("support")
    assert "ventes" not in tables
    assert interdites == {"produits.prix_achat_ht", "produits.marge_pct"}


def test_profil_inconnu_n_a_droit_a_rien():
    # Le repli sur `support` se joue à la résolution du profil, pas ici : un
    # profil hors matrice qui hériterait du périmètre du support serait une
    # élévation de privilège silencieuse.
    assert access.tools_of("root") == frozenset()
    assert access.collections("root") == frozenset()
    assert access.sql_scope("root") == (frozenset(), frozenset())


@pytest.mark.parametrize(
    ("bloc", "attendu"),
    [
        ("tools: [get_shema]", "tools inconnus"),
        ("tools: []\n    collections: [note_intern]", "collections inconnues"),
        (
            "tools: []\n    sql:\n      tables: [produits]\n      colonnes_interdites: [marge_pct]",
            "colonne interdite",
        ),
        (
            "tools: []\n    sql:\n      tables: [produits]\n      colonnes_interdites: [ventes.marge_ht]",
            "colonne interdite",
        ),
    ],
)
def test_une_faute_de_frappe_arrete_le_demarrage(tmp_path, bloc, attendu):
    # Une faute dans ce fichier ouvre ou ferme un accès sans rien signaler :
    # elle doit coûter un démarrage, pas une fuite.
    path = tmp_path / "access.yaml"
    path.write_text(f"profils:\n  support:\n    {bloc}\n", encoding="utf-8")
    with pytest.raises(ValueError, match=attendu):
        access._charge(path)


def test_le_profil_de_repli_doit_exister(tmp_path):
    path = tmp_path / "access.yaml"
    path.write_text("profils:\n  commercial:\n    tools: []\n", encoding="utf-8")
    with pytest.raises(ValueError, match="repli"):
        access._charge(path)


# ── tools/list filtré ────────────────────────────────────────────────────────


async def test_le_catalogue_annonce_est_filtre_par_profil():
    from mcp_server.app import build_server

    serveur = build_server()

    access.set_profile("support")
    assert {t.name for t in await serveur.list_tools()} == access.tools_of("support")

    access.set_profile("commercial")
    assert {t.name for t in await serveur.list_tools()} == frozenset(ALL_TOOLS)


async def test_un_tool_non_annonce_reste_appelable_et_refuse(journal):
    # Le filtrage porte sur la découverte, pas sur l'exécution : `get_schema`
    # appelé quand même doit rendre un refus métier journalisé, pas une erreur
    # de protocole « unknown tool » — invisible au journal, et lue comme une
    # panne par le host.
    from mcp_server.app import build_server

    serveur = build_server()
    access.set_profile("support")

    assert "get_schema" not in {t.name for t in await serveur.list_tools()}
    resultat = await serveur.call_tool("get_schema", {})

    (entry,) = entries(journal)
    assert entry["status"] == "refused"
    assert resultat
