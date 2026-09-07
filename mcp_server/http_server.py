"""Canal Streamable HTTP — route unique `/mcp`, tous profils dans un process.

Deux middlewares ASGI encadrent le serveur MCP, dans cet ordre : le premier
vérifie que l'appelant connaît le secret partagé, le second pose le profil qu'il
déclare. Refuser avant de résoudre : un appelant inconnu n'a pas de profil.

Lancement : ``make serve-http`` (ou ``uv run python -m mcp_server.http_server``).
"""

from __future__ import annotations

import hmac
import os

from starlette.responses import JSONResponse

from gateway.access import refused, set_profile
from mcp_server.app import build_server
from mcp_server.profile import resolve_profile

mcp = build_server(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))


SHARED_KEY_HEADER = "x-sorabel-key"

REFUS_CLIENT = (
    "Client non reconnu par la gateway. Vérifiez la clé partagée de votre "
    "application avant de réessayer."
)


def entetes(scope) -> dict[str, str]:
    """Les en-têtes de la requête, en minuscules — l'ASGI les livre en octets."""
    return {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}


class SharedKeyMiddleware:
    """Barrière 2 du modèle de confiance : le secret partagé avec l'app bot.

    Cloud Run IAM vérifie qu'un jeton `run.invoker` accompagne la requête, pas
    lequel : tout compte de service à qui ce rôle serait accordé — un autre
    service du projet, un poste de développement — parlerait à la gateway. Le
    brief exige une défense multiple, pas une barrière unique.

    Sans `SORABEL_KEY` dans l'environnement, aucun contrôle : `make serve-http`
    et la suite d'acceptance tournent en local, où il n'y a pas de secret à
    distribuer. C'est le déploiement qui arme la barrière, en montant le secret.
    """

    def __init__(self, app, key: str | None = None):
        self.app = app
        self.key = os.environ.get("SORABEL_KEY", "") if key is None else key

    def autorise(self, scope) -> bool:
        # `compare_digest` et non `==` : la comparaison naïve s'arrête au premier
        # octet qui diffère, et sa durée renseigne sur le préfixe correct.
        return hmac.compare_digest(entetes(scope).get(SHARED_KEY_HEADER, ""), self.key)

    async def __call__(self, scope, receive, send):
        if self.key and scope["type"] == "http" and not self.autorise(scope):
            # Journalisé sur `stdout` et non dans le journal des appels : celui-ci
            # compte une entrée par appel de tool, et un client refusé à la porte
            # n'a pas encore nommé de tool.
            print(
                f"refus client : clé partagée absente ou invalide ({scope.get('path')})", flush=True
            )
            await JSONResponse(refused("unauthorized_client", REFUS_CLIENT), status_code=403)(
                scope, receive, send
            )
            return
        await self.app(scope, receive, send)


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
            set_profile(resolve_profile(entetes(scope)))
        await self.app(scope, receive, send)


def main() -> None:
    import uvicorn

    app = SharedKeyMiddleware(ProfileMiddleware(mcp.streamable_http_app()))
    uvicorn.run(
        app,
        host=mcp.settings.host,
        port=mcp.settings.port,
        log_level=mcp.settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
