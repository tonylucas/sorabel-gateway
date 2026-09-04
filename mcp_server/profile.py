"""Résolution du profil client, commune aux deux canaux (stdio et HTTP).

En stdio, un process par profil : la variable ``SORABEL_PROFILE`` fait foi.
En HTTP, un seul process sert tous les profils : le header ``X-Sorabel-Profile``
posé par le host prend le pas. Le profil est *déclaré*, pas prouvé — la gateway
authentifie le client, pas l'utilisateur final.
"""

from __future__ import annotations

import os

from gateway.access import DEFAULT_PROFILE, profiles

PROFILE_HEADER = "x-sorabel-profile"


def resolve_profile(headers: dict[str, str] | None = None) -> str:
    """Les profils connus viennent d'`access.yaml` : un profil ajouté à la matrice
    est accepté ici sans retouche, et le résolveur ne peut pas en connaître un
    que la matrice ignore."""
    declared = (headers or {}).get(PROFILE_HEADER) or os.environ.get("SORABEL_PROFILE")
    declared = (declared or "").strip().lower()
    return declared if declared in profiles() else DEFAULT_PROFILE
