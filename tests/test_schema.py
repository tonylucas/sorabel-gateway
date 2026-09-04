"""Le schéma lu dans la base — ce que l'introspection doit garantir.

`tests/test_guard.py` vérifie déjà qu'un profil ne lit pas dans son prompt le
nom de ce qu'on lui refuse. Ici on épingle ce que la bascule vers
l'introspection a changé : d'où viennent les descriptions, et ce que le DDL ne
doit pas laisser deviner.
"""

from __future__ import annotations

import pytest

from sql.schema import columns, ddl, sqlglot_schema


def test_les_descriptions_viennent_de_la_base() -> None:
    """Les `COMMENT ON` posés par la migration ressortent dans le DDL.

    Sans eux le modèle perd les levées d'ambiguïté du schéma — en-tête contre
    lignes de détail, deux marges — et c'est là que le Text-to-SQL se joue.
    """
    rendu = ddl("commercial")
    assert "-- commandes : entêtes de commandes." in rendu
    assert "format CMD-AAAA-NNNN" in rendu
    # La dernière colonne d'une table est le cas que sqlglot rate : son
    # commentaire est accroché à la contrainte, pas à la définition.
    assert "total HT de la commande" in rendu


def test_la_politique_ne_part_pas_en_commentaire() -> None:
    """Un commentaire de base décrit une colonne, il ne dit pas qui la lit.

    « SENSIBLE : … — ne sort jamais pour le profil support » n'est servi qu'au
    profil qui a le droit de lire la colonne, puisque le filtrage l'a déjà
    retirée à l'autre. Le modèle qui lit « ne sort jamais » refuse : mesuré sur
    SQL-11.
    """
    assert "ne sort jamais" not in ddl("commercial")
    assert "SENSIBLE" not in ddl("commercial")


def test_le_ddl_du_support_ne_reference_pas_une_table_fermee() -> None:
    """Une clé étrangère vers `ventes` apprendrait son existence au support."""
    rendu = ddl("support")
    assert "ventes" not in rendu
    assert "REFERENCES clients(id)" in rendu


def test_le_type_rendu_est_celui_de_postgresql() -> None:
    """Le prompt annonce PostgreSQL : le DDL ne doit plus parler SQLite.

    `REAL NOT NULL` et `INTEGER PRIMARY KEY AUTOINCREMENT` venaient du fichier ;
    la base rend ses propres types.
    """
    assert "AUTOINCREMENT" not in ddl("commercial")
    assert sqlglot_schema("commercial")["commandes"]["montant_ht"] == "real"


@pytest.mark.parametrize(
    ("table", "colonne"), [("produits", "prix_achat_ht"), ("ventes", "marge_ht")]
)
def test_l_ossature_reste_complete(table: str, colonne: str) -> None:
    """`columns()` ne filtre rien : le garde en a besoin pour distinguer une
    colonne interdite d'une colonne inexistante."""
    assert colonne in columns()[table]
