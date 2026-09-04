"""Les GRANT produits par `scripts/roles.py` appliquent bien la matrice.

C'est la barrière 1 d'E3, et la seule qui se vérifie *dans la base* : le garde
et le `LIMIT` sont testés ailleurs, sur l'arbre de la requête. Ici on ouvre une
vraie connexion par rôle et on demande ce qui doit être refusé.

Les tests sautent si aucun PostgreSQL n'écoute : `make up && make migrate &&
make roles` les active, la CI les joue à chaque exécution.
"""

from __future__ import annotations

import os

import pytest

psycopg = pytest.importorskip("psycopg")

from gateway.access import sql_scope  # noqa: E402
from sql.db import conninfo  # noqa: E402


def _connexion(profil: str):
    """Une connexion sous le rôle du profil, construite **comme la gateway
    construit ses pools** : tester une autre connexion que la sienne ne
    prouverait rien."""
    if not os.environ.get(f"PG_{profil.upper()}") or not os.environ.get("DATABASE_URL"):
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


def test_les_grant_couvrent_exactement_la_matrice() -> None:
    """`has_column_privilege` rend ce qu'`access.yaml` déclare, colonne à colonne.

    C'est l'invariant que la PR suivante exploitera : `sql_scope()` lira les
    GRANT au lieu du YAML, et les deux doivent déjà dire la même chose.

    **Le contrôle se fait colonne par colonne, jamais par table** :
    `has_table_privilege('produits')` vaut `False` pour le support alors qu'il
    lit neuf colonnes sur onze — un `GRANT SELECT (colonnes)` ne confère aucun
    droit au niveau de la table. Un `sql_scope()` écrit sur
    `has_table_privilege` fermerait donc `produits` en entier.
    """
    autorisees, interdites = sql_scope("support")
    with _connexion("support") as con:

        def colonne_lisible(table: str, nom: str) -> bool:
            rendu = con.execute(
                "SELECT has_column_privilege(%s, %s, 'SELECT')", (table, nom)
            ).fetchone()
            assert rendu is not None
            return bool(rendu[0])

        for colonne in interdites:
            table, nom = colonne.split(".", 1)
            assert not colonne_lisible(table, nom), f"{colonne} devrait être refusée"

        assert colonne_lisible("produits", "nom")
        assert con.execute("SELECT has_table_privilege('produits', 'SELECT')").fetchone() == (
            False,
        ), "un GRANT par colonnes ne donne pas le privilège de table — ne pas s'y fier"

        assert "ventes" not in autorisees
        assert not colonne_lisible("ventes", "marge_ht")
        assert not colonne_lisible("ventes", "quantite")
