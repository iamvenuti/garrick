#!/usr/bin/env python3
"""address.py: the one stable HTTPS address of remote access (preview), from a relay or from an address of your own.

Two adapters. They differ in who carries the traffic, and nothing else downstream knows which one is in use.

**The relay.** A relay is a service that gives this Mac a public address and carries the traffic to it while TLS ends on the Mac,
so the relay cannot read a record. This adapter drives Tailscale Funnel through the client's own command line: the one inside the
app (`/Applications/Tailscale.app/Contents/MacOS/Tailscale`), else `tailscale` on the PATH. It publishes the service's local
port (`funnel --bg <port>`) and reads the address back from `status --json` (`Self.DNSName`). Tests drive a fake command line:
nothing here opens a public address by itself.

**An address you already have.** A public `https://` origin that forwards to the local port, such as a reverse proxy on a rented
server. The owner types it; the adapter checks only that it is a plain public origin. Whether the proxy hands on the caller's
address is the owner's to say.

The address is kept once (state.set_address) and is the issuer and the resource of the sign-in. A restart or an update keeps it. A
change is shown with what it breaks: the connector must be added again.

Every refusal is a plain sentence with one next step. Standard library only; runs on the Python that macOS ships (3.9).
"""
from __future__ import annotations

import ipaddress
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlsplit

sys.dont_write_bytecode = True

APP_CLI = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"
CLI_ENV = "GARRICK_REMOTE_RELAY_CLI"          # a test points it at a fake command line
TIMEOUT = 40

# The missing steps, in the order the owner meets them: the relay's app, its sign-in, its publishing setting, the address itself.
NO_APP = "The relay's app is not installed on this Mac. Install it, then choose Check again."
NO_SIGN_IN = "The relay's app is not signed in. Open it and sign in, then choose Check again."
NO_PUBLISH = ("Publishing is not switched on in your relay account. Turn it on in the relay's settings, then choose Check again.")
NO_ADDRESS = "The relay has not given this Mac an address yet. Wait a minute, then choose Check again."
NOT_AN_ORIGIN = "Type your address as a secure web address: the name of your server with https in front of it, and no page after the name."
LOST = "The relay no longer publishes this Mac. Open the relay's app, then choose Check again."
CHANGED = "The address changed. Add the connector in your assistant again, because the old one points at the old address."


def find_cli(env: Optional[Dict[str, str]] = None, app: str = APP_CLI, which: Callable = shutil.which) -> Optional[str]:
    """The relay's command line: the one named for a test, else the one inside the app, else one on the PATH. `app` and `which` are
    passed in so a test never reads this Mac."""
    env = os.environ if env is None else env
    named = env.get(CLI_ENV)
    if named:
        return named if Path(named).is_file() else None
    if Path(app).is_file():
        return app
    return which("tailscale")


def _run(cli: str, *args: str, runner: Callable = subprocess.run) -> Any:
    return runner([cli, *args], capture_output=True, text=True, timeout=TIMEOUT, stdin=subprocess.DEVNULL)


def _status(cli: str, runner: Callable) -> Dict[str, Any]:
    r = _run(cli, "status", "--json", runner=runner)
    if r.returncode != 0:
        raise ValueError("status")
    data = json.loads(r.stdout or "{}")
    return data if isinstance(data, dict) else {}


def read_back(cli: str, runner: Callable = subprocess.run) -> Dict[str, Any]:
    """What the relay says now: {"ok": True, "url": "https://name"} when it is signed in and has an address, else {"ok": False,
    "say": the missing step}."""
    try:
        data = _status(cli, runner)
    except (OSError, ValueError, subprocess.SubprocessError):
        return {"ok": False, "say": NO_SIGN_IN}
    if str(data.get("BackendState") or "") not in ("Running", "Starting"):
        return {"ok": False, "say": NO_SIGN_IN}
    name = str((data.get("Self") or {}).get("DNSName") or "").strip().rstrip(".")
    if not name:
        return {"ok": False, "say": NO_ADDRESS}
    return {"ok": True, "url": "https://" + name.lower()}


def relay_setup(port: int, runner: Callable = subprocess.run, env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Turn publishing on for the local port and read the address back. {"ok": True, "url": ...}, or {"ok": False, "say": the
    one missing step}."""
    cli = find_cli(env)
    if not cli:
        return {"ok": False, "say": NO_APP}
    first = read_back(cli, runner)
    if not first["ok"]:
        return first
    try:
        r = _run(cli, "funnel", "--bg", str(int(port)), runner=runner)
    except (OSError, subprocess.SubprocessError):
        return {"ok": False, "say": NO_PUBLISH}
    if r.returncode != 0:
        return {"ok": False, "say": NO_PUBLISH}
    return read_back(cli, runner)


def relay_stop(port: int, runner: Callable = subprocess.run, env: Optional[Dict[str, str]] = None) -> bool:
    """Stop publishing. False when the relay's command line is not there or refused."""
    cli = find_cli(env)
    if not cli:
        return False
    try:
        return _run(cli, "funnel", "--https=443", "off", runner=runner).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def check_relay(kept: str, runner: Callable = subprocess.run, env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Is the relay still publishing at the address kept? {"ok": True} when it is; {"ok": False, "say": ...} when it is lost;
    {"ok": True, "changed": True, "url": new, "say": CHANGED} when it now answers at another address."""
    cli = find_cli(env)
    if not cli:
        return {"ok": False, "say": NO_APP}
    now = read_back(cli, runner)
    if not now["ok"]:
        return {"ok": False, "say": now["say"] if now["say"] != NO_ADDRESS else LOST}
    if kept and now["url"] != kept:
        return {"ok": True, "changed": True, "url": now["url"], "say": CHANGED}
    return {"ok": True, "url": now["url"]}


def own_address(text: str) -> Dict[str, Any]:
    """An address the owner types: a public https origin with a name and no page. {"ok": True, "url": origin} or {"ok": False,
    "say": ...}. A bare IP address, a name without a dot, a local name, a password in the address, a path, a query and a
    fragment are all refused."""
    raw = str(text or "").strip()
    try:
        parts = urlsplit(raw)
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        return {"ok": False, "say": NOT_AN_ORIGIN}
    if (parts.scheme != "https" or not host or parts.username is not None or parts.password is not None
            or parts.path not in ("", "/") or parts.query or parts.fragment or "." not in host
            or host.endswith((".local", ".localhost", ".internal", ".lan", ".home.arpa")) or host == "localhost"):
        return {"ok": False, "say": NOT_AN_ORIGIN}
    try:
        ipaddress.ip_address(host.strip("[]"))
        return {"ok": False, "say": NOT_AN_ORIGIN}
    except ValueError:
        pass
    if any(not label or len(label) > 63 or label.startswith("-") or label.endswith("-") for label in host.split(".")):
        return {"ok": False, "say": NOT_AN_ORIGIN}
    origin = "https://" + host + (":%d" % port if port and port != 443 else "")
    return {"ok": True, "url": origin}


def caller(peer: str, headers: Dict[str, str], trust_forwarded: bool) -> str:
    """The address a sign-in request counts against. Where the owner's proxy passes the caller's address on, the one it appended
    last; otherwise the peer, which for a relay is the relay's own: all callers then share one count, the stricter way."""
    if trust_forwarded:
        chain = [p.strip() for p in (headers.get("x-forwarded-for") or "").split(",") if p.strip()]
        if chain:
            try:
                return str(ipaddress.ip_address(chain[-1]))
            except ValueError:
                pass
    return peer or "unknown"
