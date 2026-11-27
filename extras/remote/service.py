#!/usr/bin/env python3
"""service.py: the remote access service (preview): a remote MCP server for one owner's workspace.

    <the extra's python> service.py --workspace PATH         serve, on this computer's loopback only
    <the extra's python> service.py --workspace PATH --check say why it would not start, or "ok"

It runs in the extra's own runtime and starts at login (`launchagent.py`) while remote access is on. It listens on 127.0.0.1 only; the
address the assistant uses (`address.py`) is a relay or a proxy that forwards to this port. It is its own authorization server
(`provider.py`): there is no tool without a token, no token without the owner's pairing code, and no reach the owner did not set at the
Mac (`context.py`). It refuses to start when remote access is off or paused, when this computer is a roaming one, and when no address is
set; and a pause or an off closes every route at once, without a restart.

The tools are the extra's own (`tools/`, `register(server, session_for)`). Where that folder is not there the service serves none and says
so in its log. It changes no reach, no grant and no setting: those change in Settings at the Mac only.

Logs hold the time, the tool, the grant id, the outcome and the duration, and nothing else (`logs.py`).
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True


def _sib(name: str):
    key = "garrick_remote_" + name
    mod = sys.modules.get(key)
    if mod is None:
        spec = importlib.util.spec_from_file_location(key, str(HERE / (name + ".py")))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[key] = mod
        try:
            spec.loader.exec_module(mod)
        except BaseException:
            sys.modules.pop(key, None)
            raise
    return mod


HOST = "127.0.0.1"                       # the only address this service listens on
MCP_PATH = "/mcp"
MAX_BODY = 64 * 1024                     # a sign-in request is small
SIGN_IN_PATHS = ("/register", "/token", "/consent", "/authorize", "/revoke")


def quiet() -> None:
    """Nothing the libraries log may leave this process: a traceback can hold the arguments of a call, and a call can hold a record. The
    service's own log (logs.py) is the only one, and it has no field for text."""
    import logging
    logging.disable(logging.CRITICAL)


def refusal(ws: Path) -> str:
    """Why the service must not start: "" when it may."""
    st = _sib("state")
    cfg = st.settings()
    if cfg["status"] == "paused":
        return "Remote access is paused."
    if cfg["status"] != "on":
        return "Remote access is off."
    reason = st.host_refusal(ws)
    if reason:
        return reason
    url = cfg["address"]["url"]
    if not url:
        return "Remote access has no address yet."
    from urllib.parse import urlsplit
    p = urlsplit(url)
    if p.scheme != "https" and (p.hostname or "") not in ("127.0.0.1", "localhost"):
        return "The address is not a secure one."
    return ""


class Guard:
    """The outermost layer: while remote access is not on, every route answers 503 and nothing else runs; the sign-in routes are counted
    and slowed or refused when one caller knocks too often; a sign-in request that is too big is refused before it is read."""

    SLOW_SECONDS = 1.5

    def __init__(self, app, active: Callable[[], bool], trust_forwarded: Callable[[], bool], clock: Callable[[], float] = time.time):
        self.app, self.active, self.trust, self.clock = app, active, trust_forwarded, clock
        self.limits = _sib("limits").routes()
        self.address = _sib("address")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        if not self.active():
            return await self._say(send, 503, b'{"error":"unavailable"}')
        path, method = scope.get("path", ""), scope.get("method", "GET")
        if path in SIGN_IN_PATHS and method != "OPTIONS":
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
            try:
                size = int(headers.get("content-length") or 0)
            except ValueError:
                size = MAX_BODY + 1
            if size > MAX_BODY:
                return await self._say(send, 413, b'{"error":"too_large"}')
            if method in ("POST", "PUT", "PATCH"):
                body, more = b"", True
                while more:                                  # no Content-Length can be trusted: count what really arrives
                    msg = await receive()
                    if msg["type"] != "http.request":
                        return await self._say(send, 400, b'{"error":"bad_request"}')
                    body += msg.get("body", b"")
                    more = msg.get("more_body", False)
                    if len(body) > MAX_BODY:
                        return await self._say(send, 413, b'{"error":"too_large"}')
                sent = [False]

                async def replay():
                    if not sent[0]:
                        sent[0] = True
                        return {"type": "http.request", "body": body, "more_body": False}
                    return await receive()
                receive_for_app = replay
            else:
                receive_for_app = receive
            caller = self.address.caller((scope.get("client") or ("", 0))[0], headers, self.trust())
            verdict, wait = self.limits[path].hit(caller, self.clock())
            receive = receive_for_app
            if verdict == "refuse":
                return await self._say(send, 429, b'{"error":"slow_down"}', [(b"retry-after", str(int(wait) + 1).encode())])
            if verdict == "slow":
                await asyncio.sleep(self.SLOW_SECONDS)
        return await self.app(scope, receive, send)

    @staticmethod
    async def _say(send, status: int, body: bytes, more=()):
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json"), (b"cache-control", b"no-store"), *more]})
        await send({"type": "http.response.body", "body": body})


class Built:
    """What `build` makes: the ASGI app, the pieces a test drives, and the address it was built for."""

    def __init__(self, **kw: Any):
        self.__dict__.update(kw)


def build(ws: Path, fetch=None, tools=None, clock: Callable[[], float] = time.time) -> Built:
    """Make the service for a workspace. `tools` is the module whose `register(server, session_for)` adds the tools; where it is None the
    extra's own `tools/` is used, and where that is not there either, none are served. `fetch` gets a client's metadata document."""
    from mcp.server.auth.handlers.metadata import MetadataHandler
    from mcp.server.auth.middleware.auth_context import get_access_token
    from mcp.server.auth.routes import build_metadata, cors_middleware
    from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
    from mcp.server.mcpserver import MCPServer
    from mcp.server.transport_security import TransportSecuritySettings
    from pydantic import AnyHttpUrl
    from starlette.requests import Request
    from starlette.responses import JSONResponse, Response
    from starlette.routing import Route
    from urllib.parse import urlsplit

    ws = Path(ws)
    st, store, ctx, logs = _sib("state"), _sib("store"), _sib("context"), _sib("logs")
    provider_mod, consent = _sib("provider"), _sib("consent")
    why = refusal(ws)
    if why:
        raise RuntimeError(why)
    cfg = st.settings()
    issuer = cfg["address"]["url"]
    resource = issuer + MCP_PATH
    seen_role = {"at": 0.0, "ok": True}

    def active() -> bool:
        """On now, at the address the service was built for, on a computer that may serve. The role is looked at every few seconds, the switch on every call."""
        now = time.monotonic()
        if now - seen_role["at"] > 5:
            seen_role["ok"] = not st.host_refusal(ws)
            seen_role["at"] = now
        now_cfg = st.settings()
        return now_cfg["status"] == "on" and now_cfg["address"]["url"] == issuer and seen_role["ok"]

    provider = provider_mod.Provider(store, issuer, resource, active, fetch or provider_mod.fetch_document, clock)
    options = ClientRegistrationOptions(enabled=True, valid_scopes=list(provider_mod.SCOPES), default_scopes=["read"])
    server = MCPServer(
        "garrick", instructions="Garrick's workspace, read and written for its owner. It answers only inside what the owner allowed.",
        auth_server_provider=provider,
        auth=AuthSettings(issuer_url=AnyHttpUrl(issuer), resource_server_url=AnyHttpUrl(resource), validate_token_resource=True,
                          client_registration_options=options, revocation_options=RevocationOptions(enabled=True)))

    def session_for(request: Any = None):
        """The Session of the grant that made this call, from the token the call came with. Raises where there is no token, where remote access is not on,
        where the grant is gone or where it cannot read."""
        tok = get_access_token()
        if tok is None or not active() or str(tok.resource or "").rstrip("/") != resource.rstrip("/"):
            raise PermissionError("Sign in again.")
        try:
            session = ctx.session_for(ws, tok.subject or "", tok.scopes)
        except ValueError:
            raise PermissionError("Sign in again.") from None
        if "read" not in session.classes:
            raise PermissionError("Sign in again.")
        store.touch(session.grant_id, clock())
        return session

    show, answer = consent.routes(provider, store, clock, issuer)
    server.custom_route("/consent", ["GET"])(show)
    server.custom_route("/consent", ["POST"])(answer)

    @server.custom_route("/health", ["GET"])
    async def health(request: Request) -> Response:
        return JSONResponse({"status": "ok"})

    async def log_calls(call_ctx, call_next):
        if getattr(call_ctx, "method", "") != "tools/call":
            return await call_next(call_ctx)
        began = time.monotonic()
        name = (getattr(call_ctx, "params", None) or {}).get("name", "")
        tok = get_access_token()
        outcome = "error"
        try:
            result = await call_next(call_ctx)
            outcome = "error" if getattr(result, "is_error", False) or (isinstance(result, dict) and result.get("isError")) else "ok"
            return result
        finally:
            logs.write(name, tok.subject if tok else "-", outcome, int((time.monotonic() - began) * 1000))

    server.middleware.append(log_calls)

    served = tools
    if served is None:
        path = HERE / "tools" / "__init__.py"
        if path.is_file():
            spec = importlib.util.spec_from_file_location("garrick_remote_tools", str(path), submodule_search_locations=[str(HERE / "tools")])
            served = importlib.util.module_from_spec(spec)
            sys.modules["garrick_remote_tools"] = served
            spec.loader.exec_module(served)
    if served is not None and hasattr(served, "register"):
        served.register(server, session_for)
        tools_note = "tools"
    else:
        tools_note = "no-tools"
    logs.write(tools_note, "-", "started", 0)

    host = urlsplit(issuer).netloc
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["127.0.0.1:*", "localhost:*", host],
        allowed_origins=["http://127.0.0.1:*", "http://localhost:*", issuer])
    app = server.streamable_http_app(streamable_http_path=MCP_PATH, json_response=True, stateless_http=True, transport_security=security,
                                     host=HOST)
    metadata = build_metadata(server.settings.auth.issuer_url, None, options, RevocationOptions(enabled=True)).model_copy(update={
        "client_id_metadata_document_supported": True, "token_endpoint_auth_methods_supported": ["none"]})
    app.router.routes.insert(0, Route("/.well-known/oauth-authorization-server",
                                      endpoint=cors_middleware(MetadataHandler(metadata).handle, ["GET", "OPTIONS"]),
                                      methods=["GET", "OPTIONS"]))
    app.add_middleware(Guard, active=active, trust_forwarded=lambda: st.address()["trust_forwarded"], clock=clock)
    return Built(app=app, server=server, provider=provider, session_for=session_for, issuer=issuer, resource=resource, active=active,
                 port=cfg["port"])


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Serve the workspace to a remote assistant, on this computer's loopback only.")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--check", action="store_true", help="say why it would not start, or ok")
    args = parser.parse_args(argv)
    ws = Path(args.workspace)
    why = refusal(ws)
    if args.check:
        print(why or "ok")
        return 0
    logs = _sib("logs")
    if why:
        logs.write("service", "-", "stopped", 0)
        print(why)
        return 0                                            # a clean stop: launchd does not start it again in a loop
    quiet()
    import uvicorn
    built = build(ws)
    logs.write("service", "-", "started", 0)
    uvicorn.run(built.app, host=HOST, port=built.port, log_level="critical", log_config=None, access_log=False, server_header=False,
                date_header=False, proxy_headers=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
