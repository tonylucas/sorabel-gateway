"""Matrice d'accès, profil courant et journal — le passage obligé de tout appel.

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
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

PROFILES = ("support", "commercial", "dev")
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

#: Tools autorisés par profil. Reprend la matrice de `tests/acceptance/conftest.py`,
#: qui fait foi : `support` n'a pas `get_schema`, `commercial` a tout. `dev` est
#: le profil technique de l'IDE, sans restriction.
TOOLS_BY_PROFILE: dict[str, frozenset[str]] = {
    "support": frozenset(set(ALL_TOOLS) - {"get_schema"}),
    "commercial": frozenset(ALL_TOOLS),
    "dev": frozenset(ALL_TOOLS),
}

#: Collections documentaires par profil. Les notes internes portent des
#: négociations fournisseurs et des alertes qualité : un bot support ne doit pas
#: pouvoir les ressortir à un client.
COLLECTIONS_BY_PROFILE: dict[str, frozenset[str]] = {
    "support": frozenset({"fiche_technique", "notice", "procedure_sav"}),
    "commercial": frozenset({"fiche_technique", "notice", "procedure_sav", "note_interne"}),
    "dev": frozenset({"fiche_technique", "notice", "procedure_sav", "note_interne"}),
}

_profile: ContextVar[str] = ContextVar("sorabel_profile", default=DEFAULT_PROFILE)


def set_profile(profile: str) -> None:
    """Posé par le canal, une fois par requête (HTTP) ou au démarrage (stdio)."""
    _profile.set(profile if profile in PROFILES else DEFAULT_PROFILE)


def current_profile() -> str:
    return _profile.get()


def can(profile: str, tool: str) -> bool:
    return tool in TOOLS_BY_PROFILE.get(profile, frozenset())


def collections(profile: str) -> frozenset[str]:
    return COLLECTIONS_BY_PROFILE.get(profile, frozenset())


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
