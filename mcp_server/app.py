"""Construction du serveur MCP — le catalogue, commun aux deux canaux.

`mcp_server/` est un canal : il traduit du JSON-RPC en appels Python et rien
de plus. L'autorisation et le journal vivent dans `gateway/`, sur les fonctions
elles-mêmes, donc un appel direct en Python y passe aussi.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.types import Tool as MCPTool

from gateway.access import current_profile, tools_of
from gateway.tools import CATALOGUE


class GatewayMCP(FastMCP):
    """FastMCP dont `tools/list` est filtré par la matrice.

    Un client ne découvre que les tools que son profil lui accorde — c'est la
    dimension « catalogue » de E4, et le seul moyen d'éviter qu'un LLM de host
    tente un tool qu'on lui refusera.

    `tools/call` n'est pas filtré, et c'est délibéré : les huit fonctions
    restent enregistrées pour qu'un appel hors matrice revienne en refus métier
    — `{status: "refused"}`, journalisé, explicable par le host — et non en
    erreur de protocole « unknown tool », qu'un host présenterait comme une
    panne et que le journal ne verrait jamais passer.
    """

    async def list_tools(self) -> list[MCPTool]:
        # Pas de journalisation ici : la suite d'acceptance compte une entrée
        # par *appel de tool*, et une ligne de découverte casserait l'égalité.
        autorises = tools_of(current_profile())
        return [tool for tool in await super().list_tools() if tool.name in autorises]


def build_server(**settings) -> FastMCP:
    mcp = GatewayMCP("sorabel-gateway", **settings)
    for tool in CATALOGUE:
        mcp.tool()(tool)
    return mcp
