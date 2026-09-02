"""Le garde : ce qui se tient entre le SQL généré et la base.

Trois refus possibles, dans cet ordre — le premier qui tombe arrête tout, et la
sécurité tranche **avant** qu'on parle à la base : un `EXPLAIN` sur une requête
touchant une table interdite serait déjà une interrogation de trop.

1. un seul `SELECT`, rien qui écrive          → `write_attempt`
2. tables et colonnes dans le périmètre       → `forbidden_column`
3. `LIMIT` injecté s'il manque, puis `EXPLAIN`

Le message de refus ne nomme jamais ce qu'il protège : dire « la colonne
`marge_ht` est interdite » apprend au demandeur la colonne qu'on lui cache.
"""

from __future__ import annotations

import sqlite3
from typing import cast

import sqlglot
from sqlglot import exp
from sqlglot.errors import OptimizeError, ParseError
from sqlglot.optimizer.qualify import qualify

from gateway.access import sql_scope
from sql import db
from sql.schema import DIALECT, columns, sqlglot_schema

#: Plafond de lignes injecté quand la requête n'en porte pas.
LIMIT_DEFAUT = 200

#: Tout ce qui n'est pas une lecture. `Command` couvre les verbes que sqlglot ne
#: modélise pas (PRAGMA, ATTACH, VACUUM…) — les refuser en bloc est plus sûr que
#: les énumérer.
ECRITURES = (
    exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter,
    exp.TruncateTable, exp.Command, exp.Into,
)


class Refus(Exception):
    """Un refus : code applicatif, message lisible, et statut de l'enveloppe.

    `status` vaut `refused` sauf pour une question ambiguë, qui appelle une
    précision de l'utilisateur et non un rejet — le contrat d'intégration a un
    statut pour ça.
    """

    def __init__(self, code: str, message: str, status: str = "refused") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


REFUS_ECRITURE = (
    "La gateway n'accède à la base qu'en lecture. Aucune requête de "
    "modification n'est exécutée, même formulée autrement."
)
REFUS_PERIMETRE = (
    "Ce profil n'a pas accès aux informations nécessaires pour répondre à "
    "cette question."
)
REFUS_SCHEMA = (
    "Cette question porte sur des données que la base Sorabel ne contient pas."
)


def valide(sql: str, profile: str) -> str:
    """Rend la requête exécutable, ou lève `Refus`."""
    try:
        statements = sqlglot.parse(sql, read=DIALECT)
    except ParseError as exc:
        raise Refus("invalid_sql", "La requête produite est invalide.") from exc

    arbres = [s for s in statements if s is not None]
    if len(arbres) != 1 or not isinstance(arbres[0], exp.Select):
        raise Refus("write_attempt", REFUS_ECRITURE)
    arbre = arbres[0]
    if any(arbre.find_all(*ECRITURES)):
        raise Refus("write_attempt", REFUS_ECRITURE)

    autorisees, interdites = sql_scope(profile)
    lues = {t.name for t in arbre.find_all(exp.Table) if t.name}
    if lues - set(columns()):
        raise Refus("out_of_schema", REFUS_SCHEMA)
    if lues - autorisees:
        raise Refus("forbidden_column", REFUS_PERIMETRE)

    try:
        # Résolu contre le schéma **du profil** : `SELECT *` s'expanse alors sur
        # les seules colonnes autorisées, au lieu d'être refusé en bloc.
        resolue = cast(
            exp.Select,
            qualify(arbre, schema=sqlglot_schema(profile), dialect=DIALECT, identify=False),
        )
    except OptimizeError as exc:
        raise _classe(arbre, profile) from exc

    # Le contrôle de sécurité, explicite : `qualify` résout, il ne garde rien.
    for colonne in resolue.find_all(exp.Column):
        if f"{colonne.table}.{colonne.name}" in interdites:
            raise Refus("forbidden_column", REFUS_PERIMETRE)

    if not resolue.args.get("limit"):
        resolue = resolue.limit(LIMIT_DEFAUT)
    final = resolue.sql(dialect=DIALECT)

    try:
        db.explain(final)
    except sqlite3.Error as exc:
        raise Refus("invalid_sql", f"La requête produite est invalide : {exc}") from exc
    return final


def _classe(arbre: exp.Expression, profile: str) -> Refus:
    """Colonne non résolue : existe-t-elle ailleurs dans le schéma, ou nulle part ?"""
    complet = {t: {c: "TEXT" for c in cols} for t, cols in columns().items()}
    try:
        qualify(arbre.copy(), schema=complet, dialect=DIALECT)
    except OptimizeError:
        return Refus("out_of_schema", REFUS_SCHEMA)
    return Refus("forbidden_column", REFUS_PERIMETRE)
