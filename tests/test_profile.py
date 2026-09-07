"""Résolution du profil — le seul endroit où un profil déclaré devient un profil su."""

from __future__ import annotations

import pytest

from mcp_server.http_server import SharedKeyMiddleware
from mcp_server.profile import PROFILE_HEADER, resolve_profile


@pytest.mark.parametrize(
    ("headers", "env", "attendu"),
    [
        ({PROFILE_HEADER: "commercial"}, None, "commercial"),
        ({PROFILE_HEADER: " Commercial "}, None, "commercial"),
        ({PROFILE_HEADER: "commercial"}, "support", "commercial"),  # le header prime
        ({}, "commercial", "commercial"),  # stdio : un process par profil
        ({PROFILE_HEADER: "root"}, "commercial", "support"),  # profil inconnu → repli
        ({}, None, "support"),
    ],
)
def test_resolve_profile(monkeypatch, headers, env, attendu):
    monkeypatch.delenv("SORABEL_PROFILE", raising=False)
    if env:
        monkeypatch.setenv("SORABEL_PROFILE", env)
    assert resolve_profile(headers) == attendu


# ── La barrière du secret partagé ────────────────────────────────────────────


async def _appelle(middleware, cle_envoyee: str | None) -> tuple[int, bytes]:
    """Joue une requête HTTP minimale au travers du middleware."""
    entetes = [(b"content-type", b"application/json")]
    if cle_envoyee is not None:
        entetes.append((b"x-sorabel-key", cle_envoyee.encode()))
    scope = {"type": "http", "method": "POST", "path": "/mcp", "headers": entetes}

    statut, corps = 0, b""

    async def send(message):
        nonlocal statut, corps
        if message["type"] == "http.response.start":
            statut = message["status"]
        elif message["type"] == "http.response.body":
            corps += message.get("body", b"")

    async def receive():
        return {"type": "http.request", "body": b"{}", "more_body": False}

    await middleware(scope, receive, send)
    return statut, corps


async def _passe_tout(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"servi"})


@pytest.mark.parametrize("cle_envoyee", [None, "", "mauvaise-cle"])
async def test_sans_la_bonne_cle_la_gateway_refuse(cle_envoyee):
    middleware = SharedKeyMiddleware(_passe_tout, key="la-bonne")
    statut, corps = await _appelle(middleware, cle_envoyee)
    assert statut == 403
    assert b"unauthorized_client" in corps
    assert b"servi" not in corps


async def test_avec_la_bonne_cle_l_appel_passe():
    middleware = SharedKeyMiddleware(_passe_tout, key="la-bonne")
    assert await _appelle(middleware, "la-bonne") == (200, b"servi")


@pytest.mark.parametrize("cle_envoyee", [None, "n-importe-quoi"])
async def test_sans_secret_configure_aucun_controle(cle_envoyee):
    """En local il n'y a pas de secret à distribuer : la barrière reste ouverte."""
    middleware = SharedKeyMiddleware(_passe_tout, key="")
    assert await _appelle(middleware, cle_envoyee) == (200, b"servi")
