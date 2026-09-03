"""La connexion à la base métier — en lecture seule, c'est la première barrière.

Barrière 1 des trois qu'exige E3 : quoi qu'il arrive en amont, cette connexion
ne peut pas écrire. Le garde (`sql.guard`) et le `LIMIT` sont les deux autres ;
aucune ne suffit seule.

À l'étape 6, ce module bascule sur PostgreSQL et la lecture seule devient un
rôle `GRANT SELECT` — le contrat de `run()` ne change pas.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Plafond de lignes rendues, appliqué en plus du `LIMIT` injecté dans la requête.
MAX_ROWS = 200


def db_path() -> Path:
    return Path(os.environ.get("SORABEL_DB") or REPO_ROOT / "data" / "sorabel.db")


def connect() -> sqlite3.Connection:
    """Connexion en lecture seule, deux verrous : URI `mode=ro` et `query_only`.

    `mode=ro` refuse l'ouverture en écriture au niveau du fichier ; `query_only`
    refuse l'écriture au niveau du moteur, y compris sur les tables temporaires.
    """
    con = sqlite3.connect(f"file:{db_path()}?mode=ro", uri=True)
    con.execute("PRAGMA query_only = ON")
    return con


def run(sql: str, params: Sequence[Any] = ()) -> tuple[list[str], list[list[Any]]]:
    """Exécute et rend `(colonnes, lignes)`, les lignes en listes.

    Le contrat d'intégration veut `payload.rows` en liste de listes — la suite
    d'acceptance lit `rows[0][0]`.

    `params` sert aux tools figés (`check_stock`, `order_status`) : leur SQL est
    écrit ici, seule la valeur vient du client, et elle passe par un paramètre lié.
    """
    with connect() as con:
        cur = con.execute(sql, params)
        colonnes = [d[0] for d in cur.description or []]
        return colonnes, [list(row) for row in cur.fetchmany(MAX_ROWS)]


def explain(sql: str) -> None:
    """Valide syntaxe et noms de colonnes sans exécuter. Lève `sqlite3.Error`."""
    with connect() as con:
        con.execute("EXPLAIN " + sql)
