"""One-time "Connect Zoho": get the backend its own MCP credentials.

What it does (standard MCP OAuth: dynamic client registration + PKCE):
  1. reads ZOHO_MCP_URL from backend/.env and discovers the server's sign-in settings
  2. registers this app with the Zoho MCP server (gets a client id, and a secret only if Zoho issues one)
  3. opens your browser at Zoho's sign-in page; YOU sign in and click Allow
  4. exchanges the result for tokens and saves them into backend/.env:
       ZOHO_MCP_CLIENT_ID, ZOHO_MCP_CLIENT_SECRET (if any), ZOHO_MCP_REFRESH_TOKEN
  5. checks the connection by listing the available tools (READ-ONLY)

Nothing secret is printed. Usage (from backend/):  uv run python scripts/zoho_mcp_authorize.py
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import http.server
import json
import re
import secrets
import sys
import threading
import time
import urllib.parse
import webbrowser
from pathlib import Path

import httpx
from dotenv import dotenv_values

ENV = Path(__file__).resolve().parents[1] / ".env"
URL = (dotenv_values(ENV).get("ZOHO_MCP_URL") or "").strip().strip("\"'")
PORT = 8765
REDIRECT = f"http://127.0.0.1:{PORT}/callback"
SCOPE = "ZohoMCP.tool.execute"

_hidden: set[str] = set()


def hide(*values: str | None) -> None:
    for v in values:
        if v and len(v) > 8:
            _hidden.add(v)


def scrub(text: str) -> str:
    for s in sorted(_hidden, key=len, reverse=True):
        text = text.replace(s, "<hidden>")
    return text


def set_env(key: str, value: str) -> None:
    text = ENV.read_text(encoding="utf-8-sig")
    line = f"{key}={value}"
    if re.search(rf"^{key}=.*$", text, flags=re.M):
        text = re.sub(rf"^{key}=.*$", lambda _m: line, text, flags=re.M)
    else:
        text = text.rstrip("\n") + f"\n{line}\n"
    ENV.write_text(text, encoding="utf-8")


def fail(msg: str) -> None:
    print(f"\nSTOPPED: {scrub(msg)}")
    sys.exit(1)


def discover(client: httpx.Client) -> dict:
    u = urllib.parse.urlparse(URL)
    base = f"{u.scheme}://{u.netloc}"
    pr = client.get(f"{base}/.well-known/oauth-protected-resource").json()
    issuer = pr["authorization_servers"][0].rstrip("/")
    md = client.get(f"{issuer}/.well-known/oauth-authorization-server").json()
    for k in ("authorization_endpoint", "token_endpoint", "registration_endpoint"):
        if k not in md:
            fail(f"server settings are missing {k}")
    return md


def register(client: httpx.Client, md: dict) -> tuple[str, str | None]:
    body = {
        "client_name": "Field Meeting CRM backend",
        "redirect_uris": [REDIRECT],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "scope": SCOPE,
    }
    r = client.post(md["registration_endpoint"], json=body)
    if r.status_code >= 300:
        fail(f"registration refused (HTTP {r.status_code}): {r.text[:400]}")
    reg = r.json()
    cid, secret = reg.get("client_id"), reg.get("client_secret")
    if not cid:
        fail("registration returned no client id")
    hide(cid, secret)
    print(f"  registered: client id received, client secret issued: {bool(secret)}")
    return cid, secret


class _Handler(http.server.BaseHTTPRequestHandler):
    result: dict[str, str] = {}

    def do_GET(self):  # noqa: N802
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
        if "code" in q or "error" in q:
            type(self).result = q
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        ok = "code" in q
        self.wfile.write(
            (
                "<h2>Zoho connected. You can close this tab.</h2>"
                if ok
                else "<h2>Sign-in did not complete. Go back to the terminal.</h2>"
            ).encode()
        )

    def log_message(self, *_):  # silence
        pass


def wait_for_callback(timeout: int = 300) -> dict[str, str]:
    server = http.server.HTTPServer(("127.0.0.1", PORT), _Handler)
    server.timeout = 1
    deadline = time.time() + timeout
    while time.time() < deadline and not _Handler.result:
        server.handle_request()
    server.server_close()
    return _Handler.result


def main() -> None:
    if not URL:
        fail("ZOHO_MCP_URL is empty in backend/.env")
    hide(URL, *(p for p in URL.split("/") if len(p) > 16))

    with httpx.Client(timeout=30) as client:
        print("1/5 reading the server's sign-in settings…")
        md = discover(client)
        hide(*(p for p in md["token_endpoint"].split("/") if len(p) > 16))
        print("2/5 registering this app with the Zoho MCP server…")
        client_id, client_secret = register(client, md)

        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = secrets.token_urlsafe(16)
        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "scope": SCOPE,
            "state": state,
            "resource": URL,
        }
        auth_url = md["authorization_endpoint"] + "?" + urllib.parse.urlencode(params)

        print("3/5 opening your browser: sign in to Zoho and click Allow (waiting up to 5 minutes)…")
        threading.Thread(target=lambda: (time.sleep(0.5), webbrowser.open(auth_url)), daemon=True).start()
        result = wait_for_callback()
        if not result:
            fail("timed out waiting for the sign-in")
        if "error" in result:
            fail(f"Zoho returned an error: {result.get('error')} {result.get('error_description', '')}")
        if result.get("state") != state:
            fail("sign-in response did not match (state mismatch); nothing was saved")

        print("4/5 exchanging the sign-in for tokens…")
        data = {
            "grant_type": "authorization_code",
            "code": result["code"],
            "redirect_uri": REDIRECT,
            "client_id": client_id,
            "code_verifier": verifier,
            "resource": URL,
        }
        if client_secret:
            data["client_secret"] = client_secret
        r = client.post(md["token_endpoint"], data=data)
        if r.status_code >= 300:
            fail(f"token request refused (HTTP {r.status_code}): {r.text[:400]}")
        tok = r.json()
        hide(tok.get("access_token"), tok.get("refresh_token"))
        if not tok.get("refresh_token"):
            fail("Zoho gave an access token but no refresh token, so the backend could not stay connected")

        set_env("ZOHO_MCP_CLIENT_ID", client_id)
        if client_secret:
            set_env("ZOHO_MCP_CLIENT_SECRET", client_secret)
        set_env("ZOHO_MCP_REFRESH_TOKEN", tok["refresh_token"])
        print(f"  saved to backend/.env (access token valid for {tok.get('expires_in', '?')} s)")

    print("5/5 checking the connection (read-only: listing tools)…")
    asyncio.run(check(tok["access_token"]))


async def check(access_token: str) -> None:
    import httpx2
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    http = httpx2.AsyncClient(headers={"Authorization": f"Bearer {access_token}"}, timeout=30)
    try:
        async with http, streamable_http_client(URL, http_client=http) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                names = sorted(t.name for t in (await session.list_tools()).tools)
                print(f"  CONNECTED. {len(names)} tools available, e.g. {names[:4]}")
    except BaseException as e:  # noqa: BLE001
        sub = getattr(e, "exceptions", None)
        detail = "; ".join(f"{type(x).__name__}: {x}" for x in sub) if sub else f"{type(e).__name__}: {e}"
        print(f"  tokens were saved, but the tool check failed: {scrub(detail)[:500]}")


if __name__ == "__main__":
    main()
