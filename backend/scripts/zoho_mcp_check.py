"""Check that the backend can reach the official Zoho CRM MCP server on its own.

READ-ONLY: connects, lists the available tools, and (optionally) runs one
harmless read. Writes nothing to Zoho. The server URL contains a secret token,
so it is never printed (it is scrubbed from any error text too).

Usage (from backend/):  uv run python scripts/zoho_mcp_check.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from dotenv import dotenv_values
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client

URL = (dotenv_values(Path(__file__).resolve().parents[1] / ".env").get("ZOHO_MCP_URL") or "").strip().strip("\"'")

# The only tools the backend is allowed to call (everything else is blocked).
ALLOWED = {
    "createRecords",
    "updateRecord",
    "updateRecords",
    "searchRecords",
    "getRecord",
    "getFields",
    "getModules",
    "executeCOQLQuery",
}


PREFIX = "ZohoCRM_"  # this server prefixes every tool name with the service name


def short(name: str) -> str:
    return name[len(PREFIX) :] if name.startswith(PREFIX) else name


def scrub(text: str) -> str:
    out = text
    for part in {URL, *(p for p in URL.split("/") if len(p) > 16)}:
        out = out.replace(part, "<hidden>")
    return out


async def try_transport(name: str, factory) -> bool:
    print(f"\n[{name}] connecting…")
    try:
        async with asyncio.timeout(30):
            async with factory() as streams:
                read, write = streams[0], streams[1]
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = (await session.list_tools()).tools
                    names = sorted(short(t.name) for t in tools)
                    print(f"[{name}] CONNECTED with no interactive login. {len(names)} tools available.")
                    print("  needed and present :", sorted(ALLOWED & set(names)))
                    print("  needed but MISSING :", sorted(ALLOWED - set(names)))
                    print("  present but blocked in our code:", len(set(names) - ALLOWED))
                    return True
    except BaseException as e:  # noqa: BLE001 - report any failure, scrubbed
        sub = getattr(e, "exceptions", None)
        detail = "; ".join(f"{type(x).__name__}: {x}" for x in sub) if sub else f"{type(e).__name__}: {e}"
        print(f"[{name}] FAILED -> {scrub(detail)[:600]}")
        return False


async def main() -> int:
    if not URL:
        print("ZOHO_MCP_URL is empty in backend/.env")
        return 2
    if await try_transport("streamable-http", lambda: streamable_http_client(URL)):
        return 0
    if await try_transport("sse", lambda: sse_client(URL)):
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
