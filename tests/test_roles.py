"""Les GRANT produits par `scripts/roles.py` appliquent bien la matrice.

C'est la barrière 1 d'E3, et la seule qui se vérifie *dans la base* : le garde
et le `LIMIT` sont testés ailleurs, sur l'arbre de la requête. Ici on ouvre une
vraie connexion par rôle et on demande ce qui doit être refusé.

Les tests sautent si aucun PostgreSQL n'écoute : `make up && make migrate &&
make roles` les active, la CI les joue à chaque exécution.
"""

from __future__ import annotations

import pytest

psycopg = pytest.importorskip("psycopg")

from gateway.access import sql_declare, sql_scope  # noqa: E402
from sql.db import conninfo  # noqa: E402
from sql.reglages import reglage  # noqa: E402


def _connexion(profil: str):
    """Une connexion sous le rôle du profil, construite **comme la gateway
    construit ses pools** : tester une autre connexion que la sienne ne
    prouverait rien."""
    if not reglage(f"PG_{profil.upper()}") or not reglage("DATABASE_URL"):
        pytest.skip(f"pas de PostgreSQL de test pour le profil {profil}")
    try:
        return psycopg.connect(conninfo(profil))
    except psycopg.OperationalError as exc:
        pytest.skip(f"PostgreSQL injoignable : {exc}")


@pytest.mark.parametrize("profil", ["support", "commercial"])
def test_le_role_ne_peut_pas_ecrire(profil: str) -> None:
    """`default_transaction_read_only` tient, quel que soit le verbe."""
    with _connexion(profil) as con, pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        con.execute("DELETE FROM commandes")


def test_le_support_ne_lit_pas_les_tables_hors_perimetre() -> None:
    with _connexion("support") as con, pytest.raises(psycopg.errors.InsufficientPrivilege):
        con.execute("SELECT count(*) FROM ventes")


def test_le_support_ne_lit_pas_les_colonnes_interdites() -> None:
    """Le GRANT porte sur des colonnes : la table reste lisible, pas la colonne."""
    with _connexion("support") as con:
        assert con.execute("SELECT nom FROM produits LIMIT 1").fetchone()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            con.execute("SELECT prix_achat_ht FROM produits LIMIT 1")


def test_le_commercial_lit_les_marges() -> None:
    """Le pendant du test précédent : sans lui, un GRANT vide passerait pour un succès."""
    with _connexion("commercial") as con:
        assert con.execute("SELECT sum(marge_ht) FROM ventes").fetchone()


def test_le_catalogue_ne_lit_aucune_donnee_metier() -> None:
    """Le rôle du catalogue sert `get_schema` et `has_column_privilege`, rien d'autre."""
    with _connexion("catalog") as con:
        assert con.execute("SELECT count(*) FROM information_schema.columns").fetchone()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            con.execute("SELECT count(*) FROM produits")


def test_les_grant_disent_exactement_ce_que_la_matrice_declare() -> None:
    """L'intention et le fait doivent coïncider — c'est tout l'objet de `make roles`.

    `sql_declare()` lit `access.yaml`, `sql_scope()` lit les `GRANT`. Le premier
    est ce qu'on a voulu, le second ce que la base applique et ce que le garde
    consulte. Les voir s'écarter, c'est avoir oublié de rejouer `make roles`
    après avoir amendé la matrice — ou avoir élargi un `GRANT` à la main.
    """
    for profil in ("support", "commercial"):
        _connexion(profil).close()  # saute proprement si la base est absente
        assert sql_scope(profil) == sql_declare(profil), profil


def test_le_perimetre_se_lit_colonne_par_colonne() -> None:
    """`has_table_privilege` ne peut pas servir de raccourci.

    Il rend `False` sur `produits` pour le support, qui en lit pourtant sept
    colonnes sur neuf : un `GRANT SELECT (colonnes)` ne confère aucun privilège
    au niveau de la table. Un `sql_scope()` écrit dessus fermerait `produits` en
    entier — et le support n'aurait plus de catalogue.
    """
    with _connexion("support") as con:
        assert con.execute("SELECT has_table_privilege('produits', 'SELECT')").fetchone() == (
            False,
        )
    tables, interdites = sql_scope("support")
    assert "produits" in tables
    assert interdites == {"produits.prix_achat_ht", "produits.marge_pct"}
    assert "ventes" not in tables
