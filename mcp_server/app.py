"""Construction du serveur MCP — le catalogue, commun aux deux canaux.

`mcp_server/` est un canal : il traduit du JSON-RPC en appels Python et rien
de plus. L'autorisation et le journal vivent dans `gateway/`, sur les fonctions
elles-mêmes, donc un appel direct en Python y passe aussi.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from gateway.tools import CATALOGUE


def build_server(**settings) -> FastMCP:
    mcp = FastMCP("sorabel-gateway", **settings)
    for tool in CATALOGUE:
        mcp.tool()(tool)
    return mcp
