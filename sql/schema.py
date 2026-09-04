"""Le schéma, lu **dans la base** : une source pour le prompt et pour le garde.

Le DDL commenté envoyé au modèle et le dictionnaire de colonnes passé à
`sqlglot.qualify()` sortent de la même introspection. Ce que le modèle croit
interrogeable ne peut donc pas diverger de ce que le garde autorise — ni,
désormais, de ce que la base contient réellement.

C'est ce que la bascule PostgreSQL apporte : `docs/schema.sql` décrivait un
schéma, la base *est* le schéma. Un `ALTER TABLE` appliqué sans repasser par le
fichier ne peut plus rendre le prompt faux. Les descriptions viennent des
`COMMENT ON` posés par `scripts/migrate.py`, que SQLite ne savait pas stocker.

L'introspection passe par `pg_catalog` et non par `information_schema` : le
second est filtré par les droits du rôle qui l'interroge, et le rôle du
catalogue n'a aucun `GRANT` sur les tables métier — il ne verrait rien. Le
filtrage par profil est fait ici, à partir de la matrice.

Le filtrage s'applique au DDL comme au dictionnaire : un profil ne découvre pas
le nom d'une colonne qu'on lui refusera à l'exécution.
"""

from __future__ import annotations

from functools import lru_cache
from typing import NamedTuple

from gateway.access import sql_scope

#: Dialecte de la base. Le garde et les few-shots ne dépendent que de cette
#: constante — c'est ce qui a fait tenir la bascule PostgreSQL en une ligne.
DIALECT = "postgres"

#: Rôle technique de l'introspection : aucun `GRANT` sur les tables métier, donc
#: aucune donnée lisible. Il ne sert qu'à lire le catalogue système.
PROFIL_CATALOGUE = "catalog"

#: Largeur de la colonne des noms dans le DDL rendu. Purement lisibilité : un
#: DDL aligné se lit mieux, par un humain comme par un modèle.
_LARGEUR_NOM = 17

_COLONNES = """
SELECT c.relname,
       obj_description(c.oid, 'pg_class'),
       a.attname,
       format_type(a.atttypid, a.atttypmod),
       a.attnotnull,
       col_description(c.oid, a.attnum)
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_attribute a ON a.attrelid = c.oid
WHERE n.nspname = 'public' AND c.relkind = 'r' AND a.attnum > 0 AND NOT a.attisdropped
ORDER BY c.relname, a.attnum
"""

#: Clés primaires et étrangères. `conkey` et `confkey` sont des tableaux de
#: numéros de colonne : on les retraduit en noms ici plutôt que de parser le
#: texte de `pg_get_constraintdef`, qu'il faudrait ensuite filtrer par profil.
_CONTRAINTES = """
SELECT c.relname,
       con.contype,
       (SELECT array_agg(att.attname ORDER BY k.ord)
          FROM unnest(con.conkey) WITH ORDINALITY AS k(num, ord)
          JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = k.num),
       cf.relname,
       (SELECT array_agg(att.attname ORDER BY k.ord)
          FROM unnest(con.confkey) WITH ORDINALITY AS k(num, ord)
          JOIN pg_attribute att ON att.attrelid = con.confrelid AND att.attnum = k.num)
FROM pg_constraint con
JOIN pg_class c ON c.oid = con.conrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_class cf ON cf.oid = con.confrelid
WHERE n.nspname = 'public' AND con.contype IN ('p', 'f')
ORDER BY c.relname, con.contype DESC
"""


class Colonne(NamedTuple):
    """Une colonne telle que la base la décrit."""

    nom: str
    type: str
    non_nul: bool
    commentaire: str


@lru_cache(maxsize=1)
def _introspection() -> tuple[dict[str, str], dict[str, list[Colonne]]]:
    """`({table: description}, {table: [colonne, …]})` — une requête, un cache.

    Chargé une fois par process : le schéma d'une base métier ne bouge pas entre
    deux appels, et la suite d'acceptance relance un process par session.
    """
    from sql import db

    _, lignes = db.run(_COLONNES, profile=PROFIL_CATALOGUE)
    descriptions: dict[str, str] = {}
    colonnes: dict[str, list[Colonne]] = {}
    for table, description, nom, type_, non_nul, commentaire in lignes:
        descriptions.setdefault(table, description or "")
        colonnes.setdefault(table, []).append(Colonne(nom, type_, non_nul, commentaire or ""))
    return descriptions, colonnes


@lru_cache(maxsize=1)
def _contraintes() -> dict[str, list[tuple[str, list[str], str | None, list[str] | None]]]:
    """`{table: [(type, colonnes, table_visée, colonnes_visées), …]}`."""
    from sql import db

    _, lignes = db.run(_CONTRAINTES, profile=PROFIL_CATALOGUE)
    out: dict[str, list[tuple[str, list[str], str | None, list[str] | None]]] = {}
    for table, contype, cols, ftable, fcols in lignes:
        out.setdefault(table, []).append((contype, list(cols or ()), ftable, fcols))
    return out


#: Le périmètre SQL, tel que la base l'applique. `has_column_privilege` est
#: évalué pour le rôle **de la connexion** : la requête part sur le pool du
#: profil, donc la réponse est la sienne.
#:
#: Colonne par colonne, jamais par table : un `GRANT SELECT (colonnes)` ne
#: confère aucun privilège au niveau de la table, et `has_table_privilege`
#: rendrait `false` sur `produits` pour le support — qui en lit pourtant sept
#: colonnes sur neuf. Épinglé par `tests/test_roles.py`.
_PERIMETRE = """
SELECT c.relname,
       a.attname,
       has_column_privilege(c.oid, a.attnum, 'SELECT')
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_attribute a ON a.attrelid = c.oid
WHERE n.nspname = 'public' AND c.relkind = 'r' AND a.attnum > 0 AND NOT a.attisdropped
ORDER BY c.relname, a.attnum
"""


@lru_cache(maxsize=8)
def perimetre(profile: str) -> tuple[frozenset[str], frozenset[str]]:
    """`(tables lisibles, colonnes interdites)` — ce que la base accorde au profil.

    Appelé par `gateway.access.sql_scope()`, qui reste la seule porte de
    l'autorisation. Mis en cache par profil : les `GRANT` ne changent qu'avec
    `make roles`, donc entre deux démarrages.

    Un rôle existant mais sans aucun `GRANT` obtient un périmètre vide : tout
    lui est refusé, ce qui est le repli qu'on veut. Un profil déclaré dont le
    rôle ou le mot de passe manque lève, en revanche : c'est une erreur de
    déploiement, elle doit se voir au journal plutôt que passer pour un refus
    métier. `gateway.access.sql_scope()` écarte les profils hors matrice avant
    d'arriver ici.
    """
    from sql import db

    _, lignes = db.run(_PERIMETRE, profile=profile)
    lisibles: dict[str, set[str]] = {}
    refusees: set[str] = set()
    for table, colonne, accorde in lignes:
        if accorde:
            lisibles.setdefault(table, set()).add(colonne)
        else:
            refusees.add(f"{table}.{colonne}")

    tables = frozenset(lisibles)
    # Une colonne refusée sur une table hors périmètre est déjà couverte par le
    # refus de la table : la lister brouillerait les messages du garde.
    return tables, frozenset(c for c in refusees if c.split(".", 1)[0] in tables)


def columns() -> dict[str, tuple[str, ...]]:
    """`{table: (colonne, …)}` — l'ossature complète, sans filtrage."""
    _, colonnes = _introspection()
    return {table: tuple(c.nom for c in cols) for table, cols in colonnes.items()}


def _visibles(profile: str) -> dict[str, list[Colonne]]:
    """Les colonnes que ce profil a le droit de voir, table par table."""
    autorisees, interdites = sql_scope(profile)
    _, colonnes = _introspection()
    return {
        table: [c for c in cols if f"{table}.{c.nom}" not in interdites]
        for table, cols in colonnes.items()
        if table in autorisees
    }


def sqlglot_schema(profile: str) -> dict[str, dict[str, str]]:
    """Le schéma tel que `qualify()` doit le voir : celui du profil, pas le complet.

    Restreint, `SELECT *` s'expanse sur les seules colonnes autorisées — la
    requête devient légale au lieu d'être refusée, et le refus reste réservé à
    une colonne nommée explicitement.
    """
    return {table: {c.nom: c.type for c in cols} for table, cols in _visibles(profile).items()}


def _contraintes_rendues(table: str, visibles: dict[str, list[Colonne]]) -> list[str]:
    """Les contraintes dont **toutes** les colonnes sont visibles par le profil.

    Une clé étrangère vers une table hors périmètre apprendrait son existence à
    qui n'y a pas droit : `ventes` est fermée au support, elle ne doit
    apparaître dans aucun `REFERENCES`.
    """
    noms = {c.nom for c in visibles.get(table, ())}
    rendues = []
    for contype, cols, ftable, fcols in _contraintes().get(table, ()):
        if not set(cols) <= noms:
            continue
        if contype == "p":
            rendues.append(f"  PRIMARY KEY ({', '.join(cols)})")
        elif ftable in visibles and set(fcols or ()) <= {c.nom for c in visibles[ftable]}:
            rendues.append(
                f"  FOREIGN KEY ({', '.join(cols)}) REFERENCES {ftable}({', '.join(fcols or ())})"
            )
    return rendues


def ddl(profile: str) -> str:
    """Le DDL commenté du profil — celui du prompt et celui que rend `get_schema`."""
    descriptions, _ = _introspection()
    visibles = _visibles(profile)

    blocs = []
    for table, cols in visibles.items():
        regle = "-- " + "-" * 75
        entete = [regle, f"-- {table} : {descriptions.get(table, '')}".rstrip(), regle]

        lignes = []
        for c in cols:
            declaration = f"  {c.nom.ljust(_LARGEUR_NOM)}{c.type}"
            if c.non_nul:
                declaration += " NOT NULL"
            lignes.append((declaration, c.commentaire))
        lignes += [(contrainte, "") for contrainte in _contraintes_rendues(table, visibles)]

        largeur = max(len(d) for d, _ in lignes)
        corps = []
        for i, (declaration, commentaire) in enumerate(lignes):
            virgule = "," if i < len(lignes) - 1 else ""
            corps.append(
                f"{declaration}{virgule}".ljust(largeur + 2)
                + (f"-- {commentaire}" if commentaire else "")
            )

        blocs.append(
            "\n".join(entete)
            + f"\nCREATE TABLE {table} (\n"
            + "\n".join(c.rstrip() for c in corps)
            + "\n);"
        )
    return "\n".join(blocs)
