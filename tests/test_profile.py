"""Résolution du profil — le seul endroit où un profil déclaré devient un profil su."""

from __future__ import annotations

import pytest

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
