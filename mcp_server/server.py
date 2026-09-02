"""Canal stdio — un process par profil, lu dans `SORABEL_PROFILE`.

C'est ce que lancent la suite d'acceptance et `scripts/mcp_client.py`.

Lancement : ``make serve`` (ou ``uv run python -m mcp_server.server``).
"""

from __future__ import annotations

from gateway.access import set_profile
from mcp_server.app import build_server
from mcp_server.profile import resolve_profile

mcp = build_server()


def main() -> None:
    # Un process, un profil : résolu une fois, pour toute la session.
    set_profile(resolve_profile())
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
