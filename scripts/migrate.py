"""SQLite de référence → PostgreSQL : structure, commentaires et données.

Joué à la main (`make migrate`), jamais par un pipeline : la base métier est
statique, elle se remplit une fois par environnement.

**Une seule source de schéma.** Le DDL PostgreSQL n'est pas écrit ici : il est
transposé de `docs/schema.sql` par sqlglot, qui sert déjà à `sql.schema`. Un
second fichier de schéma finirait par diverger du premier, et c'est justement
ce que la lecture unique de `docs/schema.sql` évite depuis le chantier 4.

Les commentaires `--` du fichier deviennent des `COMMENT ON` : PostgreSQL sait
les stocker, SQLite non. C'est ce qui permettra à `sql.schema` de lire le DDL
commenté depuis la base plutôt que depuis le fichier.

Connexion : `DATABASE_URL`, prise dans l'environnement ou dans `.env`. En
administrateur — c'est la seule opération qui l'exige, la gateway ne connaît
que les rôles.
"""

from __future__ import annotations

import os
import re
import sqlite3
import sys
from pathlib import Path

import psycopg
import sqlglot
from psycopg import sql as pgsql
from sqlglot import exp

from scripts._pg import cible, connect

#: La SQLite de référence, source de la migration. `sql/db.py` ne la connaît
#: plus : depuis la bascule, la gateway ne parle qu'à PostgreSQL.
SQLITE_PATH = Path(os.environ.get("SORABEL_DB") or Path(__file__).resolve().parent.parent
                   / "data" / "sorabel.db")

#: `docs/schema.sql` est écrit en SQLite — il sert aussi `scripts/seed.py` — et
#: n'est plus lu que par ce script : depuis l'introspection, `sql/schema.py` tient
#: le schéma de la base, pas d'un fichier.
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "docs" / "schema.sql"
DIALECTE_SOURCE = "sqlite"
DIALECTE_CIBLE = "postgres"

#: `SENSIBLE : prix d'achat fournisseur — ne sort jamais pour le profil support`.
#: Seule la description part en `COMMENT ON` ; la politique, non.
#:
#: Un commentaire de base décrit une colonne, il ne prescrit pas qui la lit —
#: c'est le rôle d'`access.yaml`, et des `GRANT` qui en découlent. Le garder
#: coûterait deux fois : la phrase serait servie au profil qui a le droit de
#: lire la colonne (le filtrage ayant déjà retiré la colonne à l'autre), et un
#: modèle qui lit « ne sort jamais » refuse. Mesuré sur SQL-11.
_SENSIBLE = re.compile(r"SENSIBLE\s*:\s*(.*?)\s*—\s*ne sort jamais[^\n]*")

#: `produits : le catalogue Sorabel (…)` — la ligne de commentaire qui décrit la
#: table, parmi les tirets de séparation et l'en-tête du fichier.
_DESCRIPTION = re.compile(r"^\s*(\w+)\s*:\s*(.+?)\s*$")


def _statements() -> list[exp.Create]:
    arbres = sqlglot.parse(SCHEMA_PATH.read_text(encoding="utf-8"), read=DIALECTE_SOURCE)
    return [s for s in arbres if isinstance(s, exp.Create)]


def _table(create: exp.Create) -> str:
    table = create.find(exp.Table)
    assert table is not None, "CREATE TABLE sans nom de table"
    return table.name


def _commentaires(create: exp.Create) -> tuple[str | None, dict[str, str]]:
    """La description de la table et celle de chacune de ses colonnes.

    La description de table se reconnaît à sa forme `nom : …` — les autres
    lignes du bloc sont les tirets de séparation et, pour la première table,
    l'en-tête du fichier.
    """
    nom = _table(create)
    table = None
    for ligne in create.comments or []:
        trouve = _DESCRIPTION.match(ligne)
        if trouve and trouve.group(1) == nom:
            table = trouve.group(2)

    colonnes = {}
    for definition in create.find_all(exp.ColumnDef):
        # Parcourir le sous-arbre, et non lire `definition.comments` : sur la
        # dernière colonne d'un `CREATE TABLE`, sqlglot accroche le commentaire
        # de fin de ligne à la contrainte (`NotNullColumnConstraint`) plutôt qu'à
        # la définition. Trois descriptions sur cinq tables s'y perdaient.
        texte = " ".join(
            c.strip() for noeud in definition.walk() for c in (noeud.comments or ())
        )
        if texte:
            colonnes[definition.name] = _SENSIBLE.sub(r"\1", texte).strip()
    return table, colonnes


def _cree_les_tables(pg: psycopg.Connection) -> list[str]:
    """(Re)construit le schéma. Rend les tables dans l'ordre des dépendances."""
    creates = _statements()
    noms = [_table(c) for c in creates]

    # En ordre inverse : `ventes` référence `commandes`, qui référence `clients`.
    # `CASCADE` couvre les contraintes, pas un objet tiers — il n'y en a pas.
    for nom in reversed(noms):
        pg.execute(pgsql.SQL("DROP TABLE IF EXISTS {} CASCADE").format(pgsql.Identifier(nom)))

    for create in creates:
        nom = _table(create)
        # Les commentaires repartent en `COMMENT ON` : les garder ici en ferait
        # des `/* … */` inertes, que l'introspection ne verrait pas.
        pg.execute(create.sql(dialect=DIALECTE_CIBLE, comments=False))

        description, colonnes = _commentaires(create)
        if description:
            pg.execute(
                pgsql.SQL("COMMENT ON TABLE {} IS {}").format(
                    pgsql.Identifier(nom), pgsql.Literal(description)
                )
            )
        for colonne, texte in colonnes.items():
            pg.execute(
                pgsql.SQL("COMMENT ON COLUMN {}.{} IS {}").format(
                    pgsql.Identifier(nom), pgsql.Identifier(colonne), pgsql.Literal(texte)
                )
            )
    return noms


def _copie(pg: psycopg.Connection, lite: sqlite3.Connection, table: str) -> int:
    """Recopie une table entière par `COPY` — un aller-retour, pas un `INSERT` par ligne."""
    curseur = lite.execute(f"SELECT * FROM {table}")  # noqa: S608 — nom issu du DDL, pas du client
    colonnes = [d[0] for d in curseur.description]

    ordre = pgsql.SQL("COPY {} ({}) FROM STDIN").format(
        pgsql.Identifier(table),
        pgsql.SQL(", ").join(pgsql.Identifier(c) for c in colonnes),
    )
    lignes = 0
    with pg.cursor() as cur, cur.copy(ordre) as copie:
        for ligne in curseur:
            copie.write_row(ligne)
            lignes += 1
    return lignes


def main() -> int:
    if not SQLITE_PATH.exists():
        print(f"{SQLITE_PATH} absente — lancer `make seed` d'abord.", file=sys.stderr)
        return 1

    base, hote = cible()
    print(f"Migration vers {base} sur {hote}…")

    with sqlite3.connect(f"file:{SQLITE_PATH}?mode=ro", uri=True) as lite, connect() as pg:
        tables = _cree_les_tables(pg)
        for table in tables:
            print(f"  {table:<12} {_copie(pg, lite, table):>6} lignes")
        pg.commit()

    print("Terminé. Créer les rôles avec `make roles`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
