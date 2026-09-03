"""Le schéma, lu une seule fois : `docs/schema.sql` sert au prompt *et* au garde.

Le DDL commenté envoyé au modèle et le dictionnaire de colonnes passé à
`sqlglot.qualify()` sortent du même fichier. Ce que le modèle croit
interrogeable ne peut donc pas diverger de ce que le garde autorise — c'est
tout l'intérêt de n'avoir qu'une source.

Le filtrage par profil s'applique aux deux : un profil ne découvre pas dans le
DDL le nom d'une colonne qu'on lui refusera à l'exécution.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import sqlglot
from sqlglot import exp

from gateway.access import sql_scope

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "docs" / "schema.sql"

#: Dialecte de la base. Bascule PostgreSQL à l'étape 6 : le reste du module,
#: le garde et les few-shots sont écrits pour ne dépendre que de cette constante.
DIALECT = "sqlite"

#: `-- SENSIBLE : … — ne sort jamais pour le profil support`. Le filtrage par
#: profil ayant déjà retiré la colonne à qui elle est interdite, l'annotation ne
#: décrit plus qu'une règle qui ne s'applique pas au lecteur — et un modèle qui
#: lit « ne sort jamais » sur une colonne qu'il a le droit de lire conclut au
#: refus. Mesuré sur SQL-11 (« marge totale sur les ventes de mai 2026 »).
_SENSIBLE = re.compile(r"SENSIBLE\s*:\s*(.*?)\s*—\s*ne sort jamais[^\n]*")

#: Un bloc = ligne vide, règle `-- -----`, description de la table, `CREATE TABLE`.
#: Découper sur la règle seule couperait aussi entre la description et son
#: `CREATE TABLE` — or c'est cette description que le modèle doit lire.
_BLOC = re.compile(r"\n\n+(?=-- -{10,})")


def _text() -> str:
    return SCHEMA_PATH.read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def columns() -> dict[str, tuple[str, ...]]:
    """`{table: (colonne, …)}` — l'ossature, extraite par sqlglot."""
    out: dict[str, tuple[str, ...]] = {}
    for statement in sqlglot.parse(_text(), read=DIALECT):
        if not isinstance(statement, exp.Create):
            continue
        table = statement.find(exp.Table)
        defs = statement.find_all(exp.ColumnDef)
        if table is not None:
            out[table.name] = tuple(d.name for d in defs)
    return out


def sqlglot_schema(profile: str) -> dict[str, dict[str, str]]:
    """Le schéma tel que `qualify()` doit le voir : celui du profil, pas le complet.

    Restreint, `SELECT *` s'expanse sur les seules colonnes autorisées — la
    requête devient légale au lieu d'être refusée, et le refus reste réservé à
    une colonne nommée explicitement.
    """
    autorisees, interdites = sql_scope(profile)
    return {
        table: {col: "TEXT" for col in cols if f"{table}.{col}" not in interdites}
        for table, cols in columns().items()
        if table in autorisees
    }


def ddl(profile: str) -> str:
    """Le DDL commenté du profil — celui du prompt et celui que rend `get_schema`."""
    autorisees, interdites = sql_scope(profile)
    blocs = []
    for bloc in _BLOC.split(_text()):
        table = next((m.group(1) for m in [re.search(r"CREATE TABLE (\w+)", bloc)] if m), None)
        if table is None:
            continue  # l'en-tête du fichier
        if table not in autorisees:
            continue
        blocs.append(_sans_colonnes(bloc, {c.split(".", 1)[1] for c in interdites
                                           if c.startswith(f"{table}.")}))
    return _SENSIBLE.sub(r"\1", "\n".join(blocs)).strip()


def _sans_colonnes(bloc: str, noms: set[str]) -> str:
    """Retire les lignes de définition des colonnes citées, virgule finale recousue."""
    if not noms:
        return bloc
    gardees = [ligne for ligne in bloc.splitlines()
               if ligne.strip().split(" ")[0] not in noms]
    # La colonne retirée pouvait être la dernière : sans ce recousage, il reste
    # une virgule orpheline avant le `);` et le DDL n'est plus parsable.
    for i in range(len(gardees) - 1, -1, -1):
        if gardees[i].strip().startswith(")"):
            gardees[i - 1] = re.sub(r",(\s*(--.*)?)$", r"\1", gardees[i - 1])
            break
    return "\n".join(gardees)
