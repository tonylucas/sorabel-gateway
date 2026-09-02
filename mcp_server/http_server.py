"""Canal Streamable HTTP — route unique `/mcp`, tous profils dans un process.

Le profil est déclaré par le host à chaque requête, dans `X-Sorabel-Profile` ;
un middleware ASGI le pose avant que le tool ne s'exécute.

Lancement : ``make serve-http`` (ou ``uv run python -m mcp_server.http_server``).
"""

from __future__ import annotations

import os

from gateway.access import set_profile
from mcp_server.app import build_server
from mcp_server.profile import resolve_profile

mcp = build_server(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))


class ProfileMiddleware:
    """Pose le profil de la requête courante avant d'entrer dans le serveur MCP.

    Le profil voyage dans une `ContextVar`, donc par tâche asyncio. Vérifié sur
    30 appels concurrents entrelacés (support refusé / commercial autorisé sur
    `get_schema`) : aucune fuite d'un profil vers un autre.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = {
                k.decode("latin-1").lower(): v.decode("latin-1")
                for k, v in scope.get("headers", [])
            }
            set_profile(resolve_profile(headers))
        await self.app(scope, receive, send)


def main() -> None:
    import uvicorn

    app = ProfileMiddleware(mcp.streamable_http_app())
    uvicorn.run(
        app,
        host=mcp.settings.host,
        port=mcp.settings.port,
        log_level=mcp.settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
