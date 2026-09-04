"""Un rôle PostgreSQL par profil, avec ses `GRANT SELECT` colonne par colonne.

C'est la **barrière 1** des trois qu'exige E3 : quoi qu'il arrive dans le
générateur ou dans le garde, la connexion ne peut ni écrire, ni lire une colonne
hors du périmètre de son profil.

**Les `GRANT` sont dérivés d'`access.yaml`, pas recopiés.** Un `roles.sql` écrit
à la main serait un second exemplaire de la matrice, à tenir en phase avec le
premier ; ici, ajouter une colonne interdite au YAML et rejouer `make roles`
suffit. C'est la même lecture — `gateway.access.sql_scope()` — que celle du
garde, donc les deux ne peuvent pas diverger.

Les mots de passe viennent de l'environnement ou de `.env`, un par rôle :
`PG_SUPPORT`, `PG_COMMERCIAL`, `PG_DEV`, `PG_CATALOG`.

Joué à la main (`make roles`), en administrateur, après `make migrate`.
"""

from __future__ import annotations

import psycopg
from psycopg import sql as pgsql

from gateway.access import matrice, sql_scope
from scripts._pg import connect, env_libpq
from sql.generate import reglage
from sql.schema import columns

#: Rôle technique du catalogue : il ne lit aucune donnée métier, seulement
#: `information_schema` — ouvert à `PUBLIC` par défaut. Il sert à `get_schema` et
#: aux appels `has_column_privilege` faits pour le compte des autres profils.
CATALOGUE = "catalog"

#: Une requête qui part en boucle sur une base partagée pénalise l'autre
#: application du serveur, pas seulement la gateway.
STATEMENT_TIMEOUT = "15s"


def nom_du_role(profil: str) -> str:
    return f"sorabel_{profil}"


def _mot_de_passe(profil: str) -> str:
    variable = f"PG_{profil.upper()}"
    valeur = reglage(variable)
    if not valeur:
        raise SystemExit(
            f"{variable} manquant — un mot de passe par rôle, dans `.env` "
            "(cf. docs/deploiement.md § 1.7)."
        )
    return valeur


def _cree_le_role(pg: psycopg.Connection, role: str, mot_de_passe: str) -> None:
    """Crée le rôle, ou remet son mot de passe s'il existe déjà.

    Rejouer `make roles` doit être sans effet de bord : le script est une
    convergence vers l'état décrit par `access.yaml`, pas une migration à jouer
    une fois.
    """
    existe = pg.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
    verbe = "ALTER" if existe else "CREATE"
    pg.execute(
        pgsql.SQL("{} ROLE {} LOGIN PASSWORD {}").format(
            pgsql.SQL(verbe), pgsql.Identifier(role), pgsql.Literal(mot_de_passe)
        )
    )
    # `default_transaction_read_only` porte sur le rôle, pas sur la session : un
    # client qui ouvrirait sa propre connexion avec ces identifiants l'hérite.
    pg.execute(
        pgsql.SQL("ALTER ROLE {} SET default_transaction_read_only = on").format(
            pgsql.Identifier(role)
        )
    )
    pg.execute(
        pgsql.SQL("ALTER ROLE {} SET statement_timeout = {}").format(
            pgsql.Identifier(role), pgsql.Literal(STATEMENT_TIMEOUT)
        )
    )


def _perimetre(pg: psycopg.Connection, role: str, base: str, profil: str) -> list[str]:
    """Applique le périmètre du profil. Rend le résumé de ce qui a été accordé."""
    pg.execute(
        pgsql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
            pgsql.Identifier(base), pgsql.Identifier(role)
        )
    )
    pg.execute(pgsql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(pgsql.Identifier(role)))
    # Le périmètre est reconstruit à chaque exécution : sans cette révocation,
    # retirer une table d'`access.yaml` laisserait son `GRANT` en place.
    pg.execute(
        pgsql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}").format(
            pgsql.Identifier(role)
        )
    )

    autorisees, interdites = sql_scope(profil)
    resume = []
    for table, toutes in columns().items():
        if table not in autorisees:
            continue
        gardees = [c for c in toutes if f"{table}.{c}" not in interdites]
        if len(gardees) == len(toutes):
            pg.execute(
                pgsql.SQL("GRANT SELECT ON {} TO {}").format(
                    pgsql.Identifier(table), pgsql.Identifier(role)
                )
            )
            resume.append(table)
        else:
            # `GRANT SELECT (colonnes)` et non `GRANT SELECT` : c'est ce qui rend
            # `SELECT *` inopérant sur une colonne interdite, sans avoir à fermer
            # la table entière.
            pg.execute(
                pgsql.SQL("GRANT SELECT ({}) ON {} TO {}").format(
                    pgsql.SQL(", ").join(pgsql.Identifier(c) for c in gardees),
                    pgsql.Identifier(table),
                    pgsql.Identifier(role),
                )
            )
            resume.append(f"{table} ({len(gardees)}/{len(toutes)} colonnes)")
    return resume


def main() -> int:
    cible = env_libpq()
    base = cible["PGDATABASE"]

    with connect() as pg:
        for profil in matrice():
            role = nom_du_role(profil)
            _cree_le_role(pg, role, _mot_de_passe(profil))
            resume = _perimetre(pg, role, base, profil)
            print(f"{role:<22} {', '.join(resume)}")

        catalogue = nom_du_role(CATALOGUE)
        _cree_le_role(pg, catalogue, _mot_de_passe(CATALOGUE))
        pg.execute(
            pgsql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                pgsql.Identifier(base), pgsql.Identifier(catalogue)
            )
        )
        pg.execute(
            pgsql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(pgsql.Identifier(catalogue))
        )
        print(f"{catalogue:<22} information_schema seulement")
        pg.commit()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
