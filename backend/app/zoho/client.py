"""Client for the official Zoho CRM MCP server.

The backend calls the server's tools by name, exactly like any MCP client. No AI
is involved. Only the tools in ALLOWED can ever be called, so a bug here cannot
delete records or touch users, even though the server may expose more tools.

The server URL contains a secret token: it is never logged, and is scrubbed from
every error message.
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Protocol

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

log = logging.getLogger("zoho")

PREFIX = "ZohoCRM_"  # this server prefixes every tool name with the service name

ALLOWED = frozenset(
    {
        "createRecords",
        "updateRecord",
        "updateRecords",
        "searchRecords",
        "getRecord",
        "getFields",
        "getModules",
        "executeCOQLQuery",
    }
)


class ZohoError(Exception):
    """Zoho (or the MCP server) refused the request. `code` is Zoho's error code if known."""

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.code = code


class ZohoUnavailable(ZohoError):
    """Network problem, timeout or server error: worth retrying later."""


class ToolNotAllowed(Exception):
    pass


class Zoho(Protocol):
    """What the sync logic needs. Tests use a fake implementing this."""

    async def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


def records_from(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull the list of records / per-record results out of a Zoho response."""
    d = payload.get("data")
    if isinstance(d, dict):
        d = d.get("data")
    return d if isinstance(d, list) else []


def first_id(payload: dict[str, Any]) -> str:
    """The id of the record Zoho just created or updated. Raises ZohoError if it failed."""
    for item in records_from(payload):
        if item.get("code") not in (None, "SUCCESS"):
            raise ZohoError(f"{item.get('code')}: {item.get('message')}", item.get("code"))
        zid = (item.get("details") or {}).get("id")
        if zid:
            return str(zid)
    raise ZohoError("Zoho did not return a record id")


class McpZoho:
    """A live connection to the Zoho MCP server (use as `async with McpZoho(url, timeout) as z`)."""

    def __init__(self, url: str, timeout_seconds: int = 60):
        self._url = url
        self._timeout = timeout_seconds
        self._session: ClientSession | None = None
        self._hidden = {url, *(p for p in url.split("/") if len(p) > 16)}

    def _scrub(self, text: str) -> str:
        for s in self._hidden:
            text = text.replace(s, "<hidden>")
        return text

    @asynccontextmanager
    async def _open(self) -> AsyncIterator[ClientSession]:
        async with streamable_http_client(self._url) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                yield session

    async def __aenter__(self) -> McpZoho:
        self._cm = self._open()
        try:
            self._session = await asyncio.wait_for(self._cm.__aenter__(), self._timeout)
        except BaseException as e:  # noqa: BLE001
            raise ZohoUnavailable(self._scrub(f"cannot connect to Zoho: {_describe(e)}")) from None
        return self

    async def __aexit__(self, *exc: Any) -> None:
        try:
            await self._cm.__aexit__(*exc)
        except BaseException:  # noqa: BLE001 - closing must never hide the real result
            pass

    async def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool not in ALLOWED:
            raise ToolNotAllowed(tool)
        assert self._session is not None
        try:
            result = await asyncio.wait_for(self._session.call_tool(PREFIX + tool, arguments), self._timeout)
        except asyncio.TimeoutError:
            raise ZohoUnavailable(f"Zoho did not answer within {self._timeout}s ({tool})") from None
        except BaseException as e:  # noqa: BLE001
            raise ZohoUnavailable(self._scrub(f"Zoho call failed ({tool}): {_describe(e)}")) from None

        text = "".join(getattr(c, "text", "") for c in (result.content or []))
        try:
            payload = json.loads(text) if text.strip() else {}
        except json.JSONDecodeError:
            payload = {"raw": text}
        if not isinstance(payload, dict):
            payload = {"data": payload}
        if set(payload) == {"raw"}:
            # Zoho answered with plain text instead of data: that is an error message, e.g.
            # "You cannot perform this operation. Connection not authorised".
            raw = payload["raw"].strip()
            code = "NOT_AUTHORISED" if "not authori" in raw.lower() else None
            raise ZohoError(self._scrub(f"{tool}: {raw}")[:600], code)
        is_error = getattr(result, "is_error", getattr(result, "isError", False))
        if is_error or payload.get("status") == "error" or ("code" in payload and "data" not in payload):
            code = payload.get("code")
            msg = payload.get("message") or payload.get("raw") or text or "unknown error"
            raise ZohoError(self._scrub(f"{tool}: {code or ''} {msg}".strip())[:600], code)
        return payload


def _describe(e: BaseException) -> str:
    """Flatten (nested) exception groups; include HTTP status codes so '400' is visible."""
    sub = getattr(e, "exceptions", None)
    if sub:
        return "; ".join(_describe(x) for x in sub)
    response = getattr(e, "response", None)
    status = getattr(response, "status_code", None)
    return f"{type(e).__name__}: {e}" + (f" (HTTP {status})" if status else "")
