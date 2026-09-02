"""Canal Streamable HTTP de la gateway — route unique ``/mcp``.

Étape 1 de la roadmap : le circuit vide. Un seul tool, ``ping``, dont le seul
rôle est de prouver que la chaîne front → runtime CopilotKit → client MCP →
serveur répond, et que le header de profil traverse bien le host.

Lancement : ``make serve-http`` (ou ``uv run python -m mcp_server.http_server``).
"""

from __future__ import annotations

import json
import os

from mcp.server.fastmcp import Context, FastMCP

from mcp_server.profile import PROFILE_HEADER, resolve_profile

mcp = FastMCP("sorabel-gateway", host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))


def _headers(ctx: Context) -> dict[str, str]:
    """Headers HTTP de l'appel courant, ou {} hors transport HTTP."""
    request = getattr(ctx.request_context, "request", None)
    return dict(getattr(request, "headers", {}) or {})


@mcp.tool()
def ping(ctx: Context) -> str:
    """Vérifie que la gateway répond. Renvoie le profil vu par le serveur.

    À utiliser uniquement pour un diagnostic de connexion, jamais pour répondre
    à une question métier.
    """
    headers = _headers(ctx)
    return json.dumps(
        {
            "status": "ok",
            "payload": {
                "profile": resolve_profile(headers),
                "profile_header_recu": PROFILE_HEADER in headers,
            },
            "message": "gateway joignable",
        },
        ensure_ascii=False,
    )


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
