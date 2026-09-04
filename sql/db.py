"""La connexion à la base métier — un pool par profil, en lecture seule.

**Barrière 1 des trois qu'exige E3**, et la seule qui tienne encore si les deux
autres tombent : chaque profil emprunte une connexion ouverte sous *son* rôle
PostgreSQL, créé par `scripts/roles.py` avec ses `GRANT SELECT` colonne par
colonne et `default_transaction_read_only`. Une requête hors périmètre échoue
dans la base, pas seulement dans le garde.

C'est ce qui distingue ce module de son ancêtre SQLite : la lecture seule était
une propriété du fichier, elle devient une propriété de l'identité. Le contrat
de `run()` n'a pas changé pour autant.

**Un pool par rôle, pas une connexion par appel.** La base est chez Azure et le
service chez Google : une poignée de main TLS par requête coûterait plus que la
requête. `check` teste la connexion avant de la prêter — Cloud Run endort ses
instances et Azure coupe les connexions inactives, sans quoi le premier appel
après une pause échouerait sur une connexion morte.
"""

from __future__ import annotations

import atexit
import os
from collections.abc import Sequence
from typing import Any

import psycopg
from psycopg_pool import ConnectionPool

from gateway.access import current_profile

#: Plafond de lignes rendues, appliqué en plus du `LIMIT` injecté dans la requête.
MAX_ROWS = 200

#: Au repos une seule connexion reste ouverte ; deux appels simultanés du même
#: profil ne se bloquent pas. Le tier Burstable du serveur Azure plafonne à une
#: cinquantaine de connexions, **partagées avec l'autre base du serveur** : c'est
#: ce plafond-là, et non la charge attendue, qui fixe `max_size`.
POOL_MIN, POOL_MAX = 1, 3

#: Au-delà, l'appelant préfère un refus lisible à une attente. La suite
#: d'acceptance coupe à 30 s, et la génération du SQL a déjà consommé sa part.
TIMEOUT_EMPRUNT_S = 10.0

_pools: dict[str, ConnectionPool] = {}


def role(profile: str) -> str:
    """Le rôle PostgreSQL du profil. `scripts/roles.py` applique la même règle."""
    return f"sorabel_{profile}"


def conninfo(profile: str) -> str:
    """L'adresse commune, l'identité du profil.

    `DATABASE_URL` porte le serveur, la base et le mode TLS — déclarée une seule
    fois, et c'est la même que celle des scripts de migration. Seuls `user` et
    `password` en sont remplacés : le FQDN Azure n'a pas à être recopié une fois
    par rôle, avec une occasion de diverger à chaque copie.

    Le mot de passe vient de l'environnement — d'un secret monté sur Cloud Run,
    du `.env` en local. Aucun identifiant de rôle n'est écrit dans le dépôt.
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL absente : la gateway n'a pas de base à interroger.")
    variable = f"PG_{profile.upper()}"
    mot_de_passe = os.environ.get(variable)
    if not mot_de_passe:
        raise RuntimeError(
            f"{variable} absent : le profil {profile!r} n'a pas de mot de passe de rôle."
        )
    return psycopg.conninfo.make_conninfo(url, user=role(profile), password=mot_de_passe)


def pool(profile: str) -> ConnectionPool:
    """Le pool du profil, ouvert au premier appel.

    Paresseux, et non créé au démarrage : la suite d'acceptance relance un
    process par session et coupe à 30 s — ouvrir trois pools vers Azure pour
    répondre à une question documentaire serait payé par tout le monde.
    """
    if profile not in _pools:
        _pools[profile] = ConnectionPool(
            conninfo(profile),
            min_size=POOL_MIN,
            max_size=POOL_MAX,
            timeout=TIMEOUT_EMPRUNT_S,
            check=ConnectionPool.check_connection,
            # Une lecture seule n'a rien à valider : `autocommit` évite d'ouvrir
            # une transaction par requête, et surtout d'avoir à la défaire quand
            # un `EXPLAIN` échoue.
            kwargs={"autocommit": True},
            open=True,
        )
    return _pools[profile]


@atexit.register
def _ferme_les_pools() -> None:
    for p in _pools.values():
        p.close()
    _pools.clear()


def run(
    sql: str, params: Sequence[Any] = (), profile: str | None = None
) -> tuple[list[str], list[list[Any]]]:
    """Exécute sous le rôle du profil et rend `(colonnes, lignes)`, lignes en listes.

    Le contrat d'intégration veut `payload.rows` en liste de listes — la suite
    d'acceptance lit `rows[0][0]`.

    `params` sert aux tools figés (`check_stock`, `order_status`) : leur SQL est
    écrit ici, seule la valeur vient du client, et elle passe par un paramètre lié.
    """
    with pool(profile or current_profile()).connection() as con:
        # `params or None` et non `params` : psycopg n'interprète les `%` du SQL
        # comme des marqueurs que si on lui passe une séquence, fût-elle vide.
        # Une requête générée contenant `ILIKE '%…%'` échouerait sinon.
        cur = con.execute(sql, params or None)
        colonnes = [d.name for d in cur.description or []]
        return colonnes, [list(ligne) for ligne in cur.fetchmany(MAX_ROWS)]


def explain(sql: str, profile: str | None = None) -> None:
    """Valide syntaxe, noms de colonnes **et droits** sans exécuter.

    Sur PostgreSQL, `EXPLAIN` planifie : il rejette donc aussi une colonne que
    le rôle n'a pas le droit de lire. Le garde y gagne une vérification de
    périmètre faite par la base elle-même, avant toute lecture de données.
    """
    with pool(profile or current_profile()).connection() as con:
        con.execute("EXPLAIN " + sql)
