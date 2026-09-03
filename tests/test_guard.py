"""Le garde SQL et les tools figés — la partie de l'étape 4 qui n'appelle pas le LLM.

La suite d'acceptance couvre le chemin complet ; ici on épingle les décisions
qu'un modèle indisponible ne doit pas pouvoir masquer : ce qui est refusé, avec
quel code, et pourquoi.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from gateway.access import set_profile
from sql.db import db_path
from sql.generate import EXEMPLES, consignes, prompt
from sql.guard import LIMIT_DEFAUT, Refus, valide


@pytest.fixture(autouse=True)
def journal(tmp_path, monkeypatch):
    monkeypatch.setenv("GATEWAY_JOURNAL", str(tmp_path / "journal.jsonl"))


@pytest.mark.parametrize(
    ("profile", "sql", "code"),
    [
        # Écriture : rien de ce qui modifie ne passe, sous aucune forme.
        ("commercial", "DELETE FROM commandes", "write_attempt"),
        ("commercial", "UPDATE produits SET prix_vente_ht = 1", "write_attempt"),
        ("commercial", "INSERT INTO clients VALUES ('x','y','z','w','v')", "write_attempt"),
        ("commercial", "SELECT 1; DROP TABLE ventes", "write_attempt"),
        ("commercial", "PRAGMA query_only = OFF", "write_attempt"),
        # Périmètre : la colonne et la table sensibles, pour le seul profil visé.
        ("support", "SELECT marge_pct FROM produits", "forbidden_column"),
        ("support", "SELECT prix_achat_ht FROM produits", "forbidden_column"),
        ("support", "SELECT * FROM ventes", "forbidden_column"),
        # Hors schéma : ni la table, ni la colonne n'existent nulle part.
        ("commercial", "SELECT temperature FROM meteo", "out_of_schema"),
        ("commercial", "SELECT chiffre_affaires FROM produits", "out_of_schema"),
    ],
)
def test_le_garde_refuse_avec_le_bon_code(profile, sql, code):
    with pytest.raises(Refus) as leve:
        valide(sql, profile)
    assert leve.value.code == code
    # Le message ne nomme jamais ce qu'il protège.
    assert "marge" not in leve.value.message.lower()
    assert "prix_achat" not in leve.value.message.lower()


def test_le_meme_sql_passe_pour_commercial():
    # La même requête, deux profils : c'est la matrice qui tranche, pas le SQL.
    assert "marge_pct" in valide("SELECT marge_pct FROM produits", "commercial")


def test_limit_injecte_quand_il_manque():
    assert f"LIMIT {LIMIT_DEFAUT}" in valide("SELECT ref FROM produits", "commercial")
    assert "LIMIT 5" in valide("SELECT ref FROM produits LIMIT 5", "commercial")


def test_etoile_expansee_sur_les_colonnes_du_profil():
    # `SELECT *` ne fuit pas : il s'expanse sur ce que le profil peut lire.
    rendu = valide("SELECT * FROM produits", "support")
    assert "produits.nom" in rendu
    assert "prix_achat_ht" not in rendu


def test_la_connexion_refuse_l_ecriture():
    # Barrière 1 : même sans garde, la connexion ne peut pas écrire.
    from sql.db import connect

    with pytest.raises(sqlite3.Error), connect() as con:
        con.execute("DELETE FROM commandes")


def test_les_exemples_du_prompt_sont_executables():
    # Un exemple montré doit être un exemple valide : sinon on enseigne au
    # modèle du SQL que le garde refusera.
    with sqlite3.connect(f"file:{db_path()}?mode=ro", uri=True) as con:
        for _, sql in EXEMPLES:
            con.execute(sql).fetchone()


@pytest.mark.parametrize("interdit", ["marge_pct", "marge_ht", "prix_achat_ht", "ventes"])
def test_le_prompt_du_support_ne_nomme_aucune_donnee_protegee(interdit):
    # DDL, exemples et consignes sont filtrés ensemble : un profil ne doit pas
    # apprendre dans son propre prompt le nom de ce qu'on lui refuse ailleurs.
    assert interdit not in prompt("peu importe", "support")
    assert interdit in prompt("peu importe", "commercial")


def test_les_consignes_gardent_les_regles_du_perimetre():
    assert "marge" not in consignes("support")
    assert "marge_pct" in consignes("commercial")


def test_check_stock_et_order_status_sans_llm():
    from gateway import tools

    set_profile("support")
    stock = json.loads(tools.check_stock(reference="ref-8842"))
    assert stock["status"] == "ok"
    assert stock["payload"]["total"] == sum(e["quantite"] for e in stock["payload"]["entrepots"])

    with sqlite3.connect(f"file:{db_path()}?mode=ro", uri=True) as con:
        commande = con.execute("SELECT id FROM commandes LIMIT 1").fetchone()[0]

    etat = json.loads(tools.order_status(order_id=commande))
    assert etat["status"] == "ok"
    assert etat["payload"]["id"] == commande
    assert json.loads(tools.order_status(order_id="CMD-0000-0000"))["status"] == "refused"
