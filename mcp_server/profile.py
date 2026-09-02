"""Résolution du profil client, commune aux deux canaux (stdio et HTTP).

En stdio, un process par profil : la variable ``SORABEL_PROFILE`` fait foi.
En HTTP, un seul process sert tous les profils : le header ``X-Sorabel-Profile``
posé par le host prend le pas. Le profil est *déclaré*, pas prouvé — la gateway
authentifie le client, pas l'utilisateur final.
"""

from __future__ import annotations

import os

PROFILE_HEADER = "x-sorabel-profile"
PROFILES = ("support", "commercial", "dev")
DEFAULT_PROFILE = "support"


def resolve_profile(headers: dict[str, str] | None = None) -> str:
    declared = (headers or {}).get(PROFILE_HEADER) or os.environ.get("SORABEL_PROFILE")
    declared = (declared or "").strip().lower()
    return declared if declared in PROFILES else DEFAULT_PROFILE
