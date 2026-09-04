"""La connexion administrateur des scripts de migration — commune à `migrate` et `roles`.

Ces deux scripts sont les seuls du dépôt à se connecter en administrateur : ils
créent le schéma et les rôles. La gateway, elle, ne connaît que les rôles.
"""

from __future__ import annotations

import os

import psycopg

from sql.generate import reglage

#: Les variables libpq que les deux scripts attendent. `psycopg.connect()` sans
#: argument les lit dans l'environnement : rien à assembler en DSN, et un mot de
#: passe n'a pas à traverser une ligne de commande pour arriver là.
VARIABLES = ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD", "PGSSLMODE")


def env_libpq() -> dict[str, str]:
    """Complète l'environnement depuis `.env` et rend ce qui est connu."""
    valeurs = {nom: reglage(nom) for nom in VARIABLES}
    for nom, valeur in valeurs.items():
        if valeur:
            os.environ[nom] = valeur
    manquantes = [n for n in ("PGHOST", "PGDATABASE", "PGUSER") if not valeurs[n]]
    if manquantes:
        raise SystemExit(
            f"Variables de connexion manquantes : {', '.join(manquantes)}. "
            "Les renseigner dans `.env` (cf. docs/deploiement.md § 3.1)."
        )
    return valeurs


def connect() -> psycopg.Connection:
    env_libpq()
    return psycopg.connect(autocommit=False)
