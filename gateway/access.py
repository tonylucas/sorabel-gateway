"""Matrice d'accès, profil courant et journal — le passage obligé de tout appel.

La matrice elle-même vit dans `access.yaml`, à la racine : c'est un document de
gouvernance, relu et amendé sans toucher au code. Ce module en est la seule
lecture — `can()`, `tools_of()`, `collections()`, `sql_scope()`. Aucun tool
n'ouvre le fichier lui-même, et rien d'autre ne décide d'une autorisation.

Un seul décorateur, `@tool_access`, posé sur chacune des fonctions de
`gateway.tools` : il résout le profil, autorise ou refuse, et journalise dans
les deux cas. Aucun appel ne le contourne, quel que soit le canal.
"""

from __future__ import annotations

import functools
import json
import os
import time
from collections.abc import Callable
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, NamedTuple

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_PROFILE = "support"

ALL_TOOLS = (
    "answer_question",
    "search_docs",
    "get_document",
    "list_sources",
    "ask_database",
    "get_schema",
    "check_stock",
    "order_status",
)

#: Les quatre types du corpus. Ni `ingest` ni Chroma n'en tiennent la liste — un
#: document déclare son type, il ne le choisit pas dans une énumération. Elle
#: n'existe donc qu'ici, pour rattraper une faute de frappe dans `access.yaml`.
DOC_TYPES = frozenset({"fiche_technique", "notice", "procedure_sav", "note_interne"})


class Perimetre(NamedTuple):
    """Ce qu'un profil peut atteindre, sur les trois dimensions de la matrice."""

    tools: frozenset[str]
    collections: frozenset[str]
    sql_tables: frozenset[str]
    sql_colonnes_interdites: frozenset[str]


def access_path() -> Path:
    return Path(os.environ.get("GATEWAY_ACCESS") or REPO_ROOT / "access.yaml")


def _charge(path: Path) -> dict[str, Perimetre]:
    """Lit et valide `access.yaml`.

    La validation n'est pas décorative : ce fichier est la frontière de
    confiance de l'autorisation, et un nom mal orthographié y ouvre ou y ferme
    un accès sans rien signaler. `get_shema` mal tapé, et le profil se voit
    refuser un tool qu'il devrait avoir ; `note_intern`, et le support hérite
    des notes internes puisque le filtre ne correspond plus à rien.
    """
    brut = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    profils = brut.get("profils") or {}
    if not profils:
        raise ValueError(f"{path} : aucun profil déclaré")

    matrice: dict[str, Perimetre] = {}
    for nom, bloc in profils.items():
        bloc = bloc or {}
        sql = bloc.get("sql") or {}
        perimetre = Perimetre(
            tools=frozenset(bloc.get("tools") or ()),
            collections=frozenset(bloc.get("collections") or ()),
            sql_tables=frozenset(sql.get("tables") or ()),
            sql_colonnes_interdites=frozenset(sql.get("colonnes_interdites") or ()),
        )
        if inconnus := perimetre.tools - set(ALL_TOOLS):
            raise ValueError(f"{path} : profil {nom}, tools inconnus {sorted(inconnus)}")
        if inconnues := perimetre.collections - DOC_TYPES:
            raise ValueError(f"{path} : profil {nom}, collections inconnues {sorted(inconnues)}")
        for colonne in perimetre.sql_colonnes_interdites:
            table, _, reste = colonne.partition(".")
            if not reste or table not in perimetre.sql_tables:
                # Une colonne interdite sur une table hors périmètre est morte :
                # la table est déjà refusée. Le plus souvent, c'est la table qui
                # a été retirée du périmètre sans nettoyer la ligne.
                raise ValueError(
                    f"{path} : profil {nom}, colonne interdite {colonne!r} — attendu "
                    f"`table.colonne` sur une table du périmètre"
                )
        matrice[nom] = perimetre

    if DEFAULT_PROFILE not in matrice:
        raise ValueError(f"{path} : le profil de repli {DEFAULT_PROFILE!r} doit être déclaré")
    return matrice


@lru_cache(maxsize=1)
def matrice() -> dict[str, Perimetre]:
    """La matrice, chargée une fois par process — un fichier statique, relu à chaud
    par personne : la modifier demande un redéploiement, comme le code qu'elle régit."""
    return _charge(access_path())


def profiles() -> tuple[str, ...]:
    return tuple(matrice())


_profile: ContextVar[str] = ContextVar("sorabel_profile", default=DEFAULT_PROFILE)


def set_profile(profile: str) -> None:
    """Posé par le canal, une fois par requête (HTTP) ou au démarrage (stdio)."""
    _profile.set(profile if profile in matrice() else DEFAULT_PROFILE)


def current_profile() -> str:
    return _profile.get()


def _perimetre(profile: str) -> Perimetre:
    """Un profil inconnu n'a droit à rien — jamais au périmètre du profil de repli."""
    return matrice().get(profile, Perimetre(frozenset(), frozenset(), frozenset(), frozenset()))


def can(profile: str, tool: str) -> bool:
    return tool in _perimetre(profile).tools


def tools_of(profile: str) -> frozenset[str]:
    """Le catalogue visible par ce profil — ce que `tools/list` doit renvoyer."""
    return _perimetre(profile).tools


def collections(profile: str) -> frozenset[str]:
    return _perimetre(profile).collections


def sql_scope(profile: str) -> tuple[frozenset[str], frozenset[str]]:
    """Tables autorisées et colonnes interdites (`table.colonne`) du profil."""
    p = _perimetre(profile)
    return p.sql_tables, p.sql_colonnes_interdites


# ── Enveloppe du contrat d'intégration ───────────────────────────────────────
# `status` ∈ ok | refused | hors_corpus | clarification. Le code applicatif
# précis vit dans `payload.code`, le texte lisible dans `message`.


def ok(**payload: Any) -> dict[str, Any]:
    return {"status": "ok", "payload": payload, "message": ""}


def refused(code: str, message: str, **payload: Any) -> dict[str, Any]:
    return {"status": "refused", "payload": {"code": code, **payload}, "message": message}


def hors_corpus(message: str, **payload: Any) -> dict[str, Any]:
    return {
        "status": "hors_corpus",
        "payload": {"code": "hors_corpus", **payload},
        "message": message,
    }


def clarification(code: str, message: str, **payload: Any) -> dict[str, Any]:
    return {"status": "clarification", "payload": {"code": code, **payload}, "message": message}


# ── Journal ──────────────────────────────────────────────────────────────────


def journal_path() -> Path:
    """Relu à chaque appel : les tests réassignent GATEWAY_JOURNAL par session."""
    return Path(os.environ.get("GATEWAY_JOURNAL") or REPO_ROOT / "logs" / "journal.jsonl")


def journalise(entry: dict[str, Any]) -> None:
    path = journal_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


REFUS_TOOL = (
    "Ce profil n'a pas accès à cet outil. Adressez-vous à un profil "
    "habilité si vous en avez besoin."
)
REFUS_INTERNE = (
    "La gateway n'a pas pu traiter cet appel. L'incident est journalisé ; "
    "réessayez ou signalez-le à l'équipe."
)


def tool_access(name: str) -> Callable[[Callable[..., dict]], Callable[..., str]]:
    """Autorise, exécute, journalise — dans cet ordre, et une seule fois.

    La suite d'acceptance compare le nombre d'entrées du journal au nombre
    d'appels : **une entrée par appel**, ni plus ni moins. Rien d'autre dans le
    code ne doit écrire dans ce fichier.

    Renvoie l'enveloppe sérialisée : c'est le texte que lit le client MCP.
    """

    def decorate(fn: Callable[..., dict]) -> Callable[..., str]:
        @functools.wraps(fn)
        def wrapper(**kwargs: Any) -> str:
            profile = current_profile()
            started = time.perf_counter()

            erreur = None
            if not can(profile, name):
                envelope = refused("unauthorized_tool", REFUS_TOOL)
            else:
                try:
                    envelope = fn(**kwargs)
                except Exception as exc:  # noqa: BLE001 — dernier filet avant le canal
                    # Sans ce filet, l'exception ressortirait en erreur de
                    # protocole MCP : sans enveloppe, et sans entrée au journal.
                    # Le détail technique reste au journal, pas chez le client.
                    erreur = f"{type(exc).__name__}: {exc}"
                    envelope = refused("erreur_interne", REFUS_INTERNE)

            journalise(
                {
                    "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                    "profile": profile,
                    "tool": name,
                    "arguments": kwargs,
                    "status": envelope["status"],
                    "code": envelope.get("payload", {}).get("code"),
                    "sql": envelope.get("payload", {}).get("sql"),
                    "latence_ms": round((time.perf_counter() - started) * 1000, 1),
                    "erreur": erreur,
                }
            )
            return json.dumps(envelope, ensure_ascii=False)

        # `functools.wraps` recopie les annotations de la fonction enveloppée,
        # dont `-> dict` : le canal MCP en déduirait un schéma de sortie faux.
        wrapper.__annotations__ = {**fn.__annotations__, "return": str}
        return wrapper

    return decorate
