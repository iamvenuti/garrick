"""A running service on a loopback port the test chose by binding port 0, a fake relay in front of nothing, and the SDK's own client.

Runs only in the extra's runtime (it imports the locked packages). Invented names only. Nothing here reaches this Mac's network but the
loopback address, and nothing is published.
"""
from __future__ import annotations

import asyncio
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from urllib.parse import parse_qs, urlsplit

import httpx2
from mcp.client import Client
from mcp.client.auth import OAuthClientProvider
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import AuthorizationCodeResult, OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

from remote_fixture import RemoteCase, mod

sys.dont_write_bytecode = True

import base64
import hashlib
import logging
import secrets

for noisy in ("httpx2", "httpx", "mcp", "uvicorn", "uvicorn.error", "asyncio"):
    logging.getLogger(noisy).setLevel(logging.ERROR)


class Memory:
    """Token storage for the SDK client, in memory."""

    def __init__(self):
        self.tokens: Optional[OAuthToken] = None
        self.info: Optional[OAuthClientInformationFull] = None

    async def get_tokens(self):
        return self.tokens

    async def set_tokens(self, tokens):
        self.tokens = tokens

    async def get_client_info(self):
        return self.info

    async def set_client_info(self, info):
        self.info = info


class Served:
    """Build the service for the fixture workspace and run it on a socket this test bound to port 0."""

    def __init__(self, case: "ServiceCase", tools=None, fetch=None, port: int = 0):
        self.case, self.tools, self.fetch = case, tools, fetch
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", port))
        self.sock.listen(64)
        self.port = self.sock.getsockname()[1]
        self.url = "http://127.0.0.1:%d" % self.port
        self.thread: Optional[threading.Thread] = None

    def __enter__(self):
        import uvicorn
        case = self.case
        case.state.set_address(self.url, "own")
        case.state.set_status("on")
        self.built = mod("service").build(case.ws, fetch=self.fetch, tools=self.tools)
        config = uvicorn.Config(self.built.app, log_level="warning", access_log=False, proxy_headers=False, lifespan="on")
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=lambda: asyncio.run(self.server.serve(sockets=[self.sock])), daemon=True)
        self.thread.start()
        for _ in range(200):
            if self.server.started:
                break
            time.sleep(0.05)
        else:
            raise RuntimeError("the service did not start")
        return self

    def __exit__(self, *exc):
        self.server.should_exit = True
        if self.thread:
            self.thread.join(10)
        self.sock.close()

    @property
    def mcp_url(self) -> str:
        return self.url + "/mcp"


def request_of(pid: str) -> str:
    """The short id Settings names a waiting sign-in request by, from the id in its link: what the owner picks to make a code for it."""
    return mod("store").peek()["pending"][pid]["rid"]


def sign_in_by_hand(base: str, ws, act, scope="read", writes=False, client_name="Test phone", follow_code=True):
    """What the owner does on the consent page: returns a function the SDK client's redirect handler calls with the authorization address."""
    result: Dict[str, Any] = {}

    async def redirect(url: str):
        async with httpx2.AsyncClient(follow_redirects=False) as http:
            r = await http.get(url)
            page = r.headers["location"]
            result["page"] = page
            await http.get(page)
            pid = parse_qs(urlsplit(page).query)["p"][0]
            code = act.run(ws, {"action": "pair", "request": request_of(pid)})["code"]
            data = {"p": pid, "code": code, "read": "1"}
            if writes:
                data["write"] = "1"
            done = await http.post(base + "/consent", data=data)
            result["done"] = done
            loc = done.headers.get("location", "")
            result["location"] = loc

    async def callback():
        q = parse_qs(urlsplit(result["location"]).query)
        return AuthorizationCodeResult(code=q["code"][0], state=(q.get("state") or [None])[0])

    return redirect, callback, result


def sdk_client(served: "Served", ws, act, storage: Memory, writes=False, mode="legacy", port=19999):
    """The SDK's own OAuth client against the service, signed in the way the owner would."""
    redirect, callback, result = sign_in_by_hand(served.url, ws, act, writes=writes)
    meta = OAuthClientMetadata(redirect_uris=["http://127.0.0.1:%d/callback" % port], client_name="Test phone",
                               grant_types=["authorization_code", "refresh_token"], response_types=["code"], scope="read write",
                               token_endpoint_auth_method="none")
    oauth = OAuthClientProvider(served.mcp_url, meta, storage, redirect_handler=redirect, callback_handler=callback)
    http = httpx2.AsyncClient(auth=oauth, timeout=30)
    return Client(streamable_http_client(served.mcp_url, http_client=http), mode=mode), result


class ServiceCase(RemoteCase):
    def serve(self, tools=None, fetch=None, port: int = 0) -> Served:
        return Served(self, tools, fetch, port)


class Raw:
    """The sign-in by hand, one step at a time, over plain requests: for the tests that attack it."""

    def __init__(self, served: "Served", case: "ServiceCase", redirect="http://127.0.0.1:19999/callback"):
        self.served, self.case, self.redirect = served, case, redirect
        self.http = httpx2.Client(base_url=served.url, follow_redirects=False, timeout=20)
        case.addCleanup(self.http.close)
        self.verifier = secrets.token_urlsafe(48)
        self.challenge = base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode()).digest()).decode().rstrip("=")
        self.client_id = ""

    def register(self, **over):
        body = {"redirect_uris": [self.redirect], "client_name": "Test phone", "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"], "scope": "read write", "token_endpoint_auth_method": "none"}
        body.update(over)
        r = self.http.post("/register", json=body)
        if r.status_code == 201:
            self.client_id = r.json()["client_id"]
        return r

    def authorize(self, redirect=None, scope="read write", resource="", client_id=None):
        q = {"response_type": "code", "client_id": client_id or self.client_id, "redirect_uri": redirect or self.redirect,
             "state": "st1", "code_challenge": self.challenge, "code_challenge_method": "S256", "scope": scope,
             "resource": resource or self.served.mcp_url}
        return self.http.get("/authorize", params=q)

    def consent(self, authorize_response, code=None, read=True, write=False):
        page = authorize_response.headers["location"]
        pid = parse_qs(urlsplit(page).query)["p"][0]
        if code is None:
            code = mod("settings_actions").run(self.case.ws, {"action": "pair", "request": request_of(pid)})["code"]
        data = {"p": pid, "code": code}
        if read:
            data["read"] = "1"
        if write:
            data["write"] = "1"
        return self.http.post("/consent", data=data)

    def token(self, code=None, **over):
        data = {"grant_type": "authorization_code", "client_id": self.client_id, "code_verifier": self.verifier,
                "redirect_uri": self.redirect, "code": code}
        data.update(over)
        return self.http.post("/token", data=data)

    def refresh(self, token, **over):
        data = {"grant_type": "refresh_token", "client_id": self.client_id, "refresh_token": token}
        data.update(over)
        return self.http.post("/token", data=data)

    def sign_in(self, write=False, scope="read write"):
        """The whole thing; returns the token response's JSON."""
        self.register()
        a = self.authorize(scope=scope)
        c = self.consent(a, write=write)
        code = parse_qs(urlsplit(c.headers["location"]).query)["code"][0]
        r = self.token(code)
        assert r.status_code == 200, r.text
        return r.json()

    def mcp(self, token=None, headers=None, body=None):
        h = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
        if token:
            h["Authorization"] = "Bearer " + token
        h.update(headers or {})
        body = body or {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        return self.http.post("/mcp", json=body, headers=h)
