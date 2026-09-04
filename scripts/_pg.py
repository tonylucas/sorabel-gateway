"""La connexion administrateur des scripts de migration — commune à `migrate` et `roles`.

Ces deux scripts sont les seuls du dépôt à se connecter en administrateur : ils
créent le schéma et les rôles. La gateway, elle, n'ouvre que des connexions de
rôle — et les dérive de cette même `DATABASE_URL`, dont elle ne remplace que
l'identité. L'adresse du serveur n'est donc déclarée qu'une fois.
"""

from __future__ import annotations

import psycopg
from psycopg import conninfo

from sql.reglages import reglage


def database_url() -> str:
    """L'URL de connexion administrateur, de l'environnement ou de `.env`."""
    url = reglage("DATABASE_URL")
    if not url:
        raise SystemExit(
            "DATABASE_URL absente. La renseigner dans `.env` — par exemple "
            "`postgresql://sorabel:sorabel@localhost:8003/sorabel` "
            "(cf. docs/deploiement.md § 3.1)."
        )
    return url


def cible() -> tuple[str, str]:
    """`(base, hôte)` — de quoi dire à l'exploitant où il est en train d'écrire."""
    infos = conninfo.conninfo_to_dict(database_url())
    return str(infos.get("dbname", "?")), str(infos.get("host", "?"))


def connect() -> psycopg.Connection:
    return psycopg.connect(database_url())
