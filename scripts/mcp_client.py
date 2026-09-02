"""Client MCP de test de la gateway.

Lance le serveur en sous-processus (stdio) sous un profil donné, liste le
catalogue de tools, puis appelle un tool si demandé.

Exemples :
    uv run python scripts/mcp_client.py --profile support
    uv run python scripts/mcp_client.py --http --tool ping
    uv run python scripts/mcp_client.py --profile commercial \
        --tool ask_database --args '{"question": "combien de commandes en avril ?"}'
    uv run python scripts/mcp_client.py --profile support \
        --tool search_docs --args '{"query": "REF-8842"}'
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

HTTP_URL = os.environ.get("MCP_URL", "http://127.0.0.1:8000/mcp")


@asynccontextmanager
async def _transport(profile: str, http: bool):
    """stdio (un process par profil) ou Streamable HTTP (profil dans le header)."""
    if http:
        async with streamablehttp_client(
            HTTP_URL, headers={"X-Sorabel-Profile": profile}
        ) as (read, write, _):
            yield read, write
        return
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_server.server"],
        env={**os.environ, "SORABEL_PROFILE": profile},
    )
    async with stdio_client(params) as (read, write):
        yield read, write


async def run(profile: str, tool: str | None, args: dict, http: bool = False) -> None:
    async with _transport(profile, http) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            listed = await session.list_tools()
            print(f"— Catalogue ({profile}) —")
            for t in listed.tools:
                print(f"  {t.name}: {(t.description or '').strip().splitlines()[0]}")

            if tool:
                print(f"\n— Appel {tool} {json.dumps(args, ensure_ascii=False)} —")
                result = await session.call_tool(tool, args)
                for block in result.content:
                    text = getattr(block, "text", None)
                    if text:
                        try:
                            print(json.dumps(json.loads(text), ensure_ascii=False, indent=2))
                        except json.JSONDecodeError:
                            print(text)


def main() -> None:
    parser = argparse.ArgumentParser(description="Client de test de la Sorabel Data Gateway")
    parser.add_argument("--profile", default="support", choices=["support", "commercial", "dev"])
    parser.add_argument("--tool", default=None, help="Nom du tool à appeler")
    parser.add_argument("--args", default="{}", help="Arguments du tool (JSON)")
    parser.add_argument("--http", action="store_true",
                        help=f"Passer par le canal Streamable HTTP ({HTTP_URL}) au lieu de stdio")
    ns = parser.parse_args()
    asyncio.run(run(ns.profile, ns.tool, json.loads(ns.args), ns.http))


if __name__ == "__main__":
    main()
