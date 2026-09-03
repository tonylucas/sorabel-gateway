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
    uv run python scripts/mcp_client.py --compare --tool get_schema
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
        async with streamablehttp_client(HTTP_URL, headers={"X-Sorabel-Profile": profile}) as (
            read,
            write,
            _,
        ):
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


async def compare(tool: str, args: dict, http: bool = False) -> None:
    """Le même appel sous deux profils, l'un à côté de l'autre.

    C'est la démonstration de la matrice : un catalogue plus court pour le
    support, et le même appel qui passe pour l'un et se voit refuser à l'autre.
    """
    print(f"— {tool} {json.dumps(args, ensure_ascii=False)} —\n")
    for profile in ("support", "commercial"):
        async with _transport(profile, http) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                catalogue = sorted(t.name for t in (await session.list_tools()).tools)
                result = await session.call_tool(tool, args)
                texts = [t for t in (getattr(b, "text", None) for b in result.content) if t]
                envelope = json.loads(texts[0]) if texts else {}

        print(f"{profile:<11} {len(catalogue)} tools annoncés : {', '.join(catalogue)}")
        print(
            f"{'':<11} → {envelope.get('status', '?')}"
            f"{' · ' + envelope['payload']['code'] if envelope.get('payload', {}).get('code') else ''}"
        )
        if message := envelope.get("message", "").strip():
            print(f"{'':<11}   {message}")
        if sql := envelope.get("payload", {}).get("sql"):
            print(f"{'':<11}   {sql}")
        if rows := envelope.get("payload", {}).get("rows"):
            print(f"{'':<11}   {rows[:3]}")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Client de test de la Sorabel Data Gateway")
    parser.add_argument("--profile", default="support", choices=["support", "commercial", "dev"])
    parser.add_argument("--tool", default=None, help="Nom du tool à appeler")
    parser.add_argument("--args", default="{}", help="Arguments du tool (JSON)")
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Rejouer le même appel en support puis en commercial (démonstration de la matrice)",
    )
    parser.add_argument(
        "--http",
        action="store_true",
        help=f"Passer par le canal Streamable HTTP ({HTTP_URL}) au lieu de stdio",
    )
    ns = parser.parse_args()
    args = json.loads(ns.args)
    if ns.compare:
        if not ns.tool:
            parser.error("--compare demande un --tool à rejouer")
        asyncio.run(compare(ns.tool, args, ns.http))
    else:
        asyncio.run(run(ns.profile, ns.tool, args, ns.http))


if __name__ == "__main__":
    main()
