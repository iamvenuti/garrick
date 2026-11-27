#!/usr/bin/env python3
"""state.py: what the remote access extra keeps on this Mac, and what Settings shows of it (preview).

Remote access lets an assistant on a phone work with the workspace over a remote connection. Nothing runs until the
owner turns it on in Settings. This module is the one reader of the extra's own state. Settings (`view_settings.py`)
reads it through `view()`, the service reads it on every call, and `settings_actions.py` changes it.

The state lives in one folder outside the workspace and outside git: `~/Library/Application Support/Garrick/remote/`,
mode 0700, or the folder that GARRICK_REMOTE_HOME names (tests, and the tools' operation store, which keeps its files
in `<state folder>/operations/`). Files that hold a token hash, a code hash or the key behind a handle are mode 0600.
Nothing here is ever written to the workspace.

Runs on the Python that macOS ships (3.9) as well as on the extra's own runtime: standard library only.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import importlib.util
import json
import os
import stat
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.dont_write_bytecode = True

HOME_ENV = "GARRICK_REMOTE_HOME"
DEFAULT_PORT = 8781
LOOPBACK = "127.0.0.1"
STATUSES = ("off", "on", "paused")
SETTINGS_FILE = "settings.json"
LOG_FILE = "service.log"
RUNTIME_DIR = "runtime"
READY_FILE = "ready.json"
SETUP_FILE = "setup.json"
MODE_DIR = 0o700
MODE_FILE = 0o600
NAME = "Remote access"
PREVIEW = "Preview"


def sibling(name: str):
    """A module of this extra, by its file, under a name of its own: the extra's names (store, context, address) are
    common ones, and Settings runs in a process that may know others by them."""
    key = "garrick_remote_" + name
    mod = sys.modules.get(key)
    if mod is None:
        path = Path(__file__).resolve().parent / (name + ".py")
        spec = importlib.util.spec_from_file_location(key, str(path))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[key] = mod
        try:
            spec.loader.exec_module(mod)
        except BaseException:
            sys.modules.pop(key, None)
            raise
    return mod


# --------------------------------------------------------------------------- the folder

def home() -> Path:
    """The state folder, read now: GARRICK_REMOTE_HOME, else Application Support under HOME."""
    given = os.environ.get(HOME_ENV)
    if given:
        return Path(given).expanduser()
    base = os.environ.get("HOME") or os.path.expanduser("~")
    return Path(base) / "Library" / "Application Support" / "Garrick" / "remote"


def ensure_home() -> Path:
    """The state folder, made with mode 0700 when it is not there, and set to 0700 when it is."""
    folder = home()
    folder.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(str(folder), MODE_DIR)
    except OSError:
        pass
    return folder


def read_json(name: str, default: Any = None) -> Any:
    """A JSON file of the state folder; `default` when it is missing or does not read."""
    try:
        return json.loads((home() / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(name: str, data: Any, mode: int = MODE_FILE) -> Path:
    """A JSON file of the state folder, written whole and replaced in one step, with the mode set before the name
    exists, so a secret is never readable by another user, not even for a moment."""
    folder = ensure_home()
    target = folder / name
    fd, tmp = tempfile.mkstemp(prefix=name + ".", suffix=".tmp", dir=str(folder))
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(data, indent=2, sort_keys=True) + "\n")
        os.replace(tmp, str(target))
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    return target


def mode_of(path: Path) -> int:
    return stat.S_IMODE(os.stat(str(path)).st_mode)


# --------------------------------------------------------------------------- the switch and the address

def settings() -> Dict[str, Any]:
    """The switch, the port and the address, as kept. A file that does not read, or a value that is not one of the
    known ones, reads as off: nothing is served."""
    data = read_json(SETTINGS_FILE, {})
    data = data if isinstance(data, dict) else {}
    status = data.get("status") if data.get("status") in STATUSES else "off"
    port = data.get("port")
    port = port if isinstance(port, int) and not isinstance(port, bool) and 1 <= port <= 65535 else DEFAULT_PORT
    address = data.get("address") if isinstance(data.get("address"), dict) else {}
    url = address.get("url") if isinstance(address.get("url"), str) else ""
    adapter = address.get("adapter") if address.get("adapter") in ("relay", "own") else ""
    return {"status": status, "port": port,
            "address": {"url": url if adapter else "", "adapter": adapter if url else "",
                        "trust_forwarded": address.get("trust_forwarded") is True,
                        "set": str(address.get("set") or "")}}


def _save(data: Dict[str, Any]) -> None:
    write_json(SETTINGS_FILE, data)


def status() -> str:
    return settings()["status"]


def port() -> int:
    return settings()["port"]


def set_status(value: str) -> None:
    if value not in STATUSES:
        raise ValueError("The state is off, on or paused.")
    data = settings()
    data["status"] = value
    _save(data)


def set_port(value: int) -> None:
    if not (isinstance(value, int) and not isinstance(value, bool) and 1024 <= value <= 65535):
        raise ValueError("The port is a number from 1024 to 65535.")
    data = settings()
    data["port"] = value
    _save(data)


def address() -> Dict[str, Any]:
    return settings()["address"]


def set_address(url: str, adapter: str, trust_forwarded: bool = False, today: Optional[str] = None) -> Dict[str, Any]:
    """Keep the address, once. Returns {"changed": bool, "previous": the old address or ""}. The address is the issuer and
    the resource of the sign-in, so a change is reported and never silent."""
    if adapter not in ("relay", "own"):
        raise ValueError("The address comes from a relay or is your own.")
    data = settings()
    previous = data["address"]["url"]
    data["address"] = {"url": url, "adapter": adapter, "trust_forwarded": bool(trust_forwarded),
                       "set": today or dt.date.today().isoformat()}
    _save(data)
    return {"changed": bool(previous) and previous != url, "previous": previous}


def clear_address() -> None:
    data = settings()
    data["address"] = {}
    _save(data)


# --------------------------------------------------------------------------- the runtime

def runtime_dir() -> Path:
    return home() / RUNTIME_DIR


def runtime_python() -> Optional[Path]:
    """The extra's own interpreter, once the install finished and left its ready note; None before."""
    ready = read_json(RUNTIME_DIR + "/" + READY_FILE) if (runtime_dir() / READY_FILE).is_file() else None
    py = runtime_dir() / "python" / "bin" / "python3"
    if isinstance(ready, dict) and ready.get("ok") is True and py.is_file():
        return py
    return None


def lock_hash() -> str:
    """The SHA-256 of the extra's own package lock. The runtime records the lock it was made from; a newer lock (a security fix shipped between
    releases) makes the runtime out of date."""
    import hashlib
    try:
        return hashlib.sha256((Path(__file__).resolve().parent / "requirements.lock").read_bytes()).hexdigest()
    except OSError:
        return ""


def runtime_current() -> bool:
    """Is the runtime the one this extra's lock describes?"""
    ready = read_json(RUNTIME_DIR + "/" + READY_FILE) if (runtime_dir() / READY_FILE).is_file() else None
    return runtime_python() is not None and isinstance(ready, dict) and ready.get("lock") == lock_hash() != ""


def setup_progress() -> Dict[str, Any]:
    """What the background setup of the runtime says: {"state": "idle"|"running"|"failed"|"done", "say": text}."""
    data = read_json(SETUP_FILE, {})
    data = data if isinstance(data, dict) else {}
    state = data.get("state") if data.get("state") in ("running", "failed", "done") else "idle"
    return {"state": state, "say": str(data.get("say") or "")}


# --------------------------------------------------------------------------- the grants, as Settings lists them

def grants(ws: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Each connected assistant: its id, its name, its classes, the day it connected and the day it was last used. Never a
    token, a code or a hash. Revoked grants are not listed."""
    try:
        return sibling("store").listing()
    except Exception:
        return []


# --------------------------------------------------------------------------- the host

def _machine(ws: Path):
    """machine.py of the workspace: this computer's role."""
    import importlib.util
    path = Path(ws) / "System" / "tools" / "machine.py"
    spec = importlib.util.spec_from_file_location("garrick_remote_machine", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def role(ws: Path) -> str:
    """solo, server or roaming. A machine file that cannot be read means solo, as machine.py says; machine.py that cannot be
    loaded means roaming: nothing is offered where the host cannot be told."""
    try:
        return str(_machine(ws).role())
    except Exception:
        return "roaming"


def host_refusal(ws: Path) -> str:
    """"" when this computer may serve remote access; otherwise the plain reason it may not."""
    if role(ws) == "roaming":
        return ("This computer is set up as a roaming computer, so it cannot serve remote access. "
                "Turn it on at the Mac that holds your workspace.")
    return ""


def installed(ws: Path) -> bool:
    return (Path(ws) / "System" / "remote" / "service.py").is_file()


# --------------------------------------------------------------------------- what Settings shows

def steps(ws: Path, cfg: Dict[str, Any], host: str) -> List[Dict[str, Any]]:
    """Each setup step and whether it is done, in the order the owner meets them."""
    prog = setup_progress()
    ready = runtime_current()
    out = [{"key": "on", "text": "Remote access is turned on", "done": cfg["status"] == "on"},
           {"key": "software", "text": "The service software is installed",
            "done": ready, "note": prog["say"] if prog["state"] in ("running", "failed") else
            ("The service software has a newer version to install." if runtime_python() is not None and not ready else "")},
           {"key": "address", "text": "Your address is set", "done": bool(cfg["address"]["url"])},
           {"key": "service", "text": "The service starts when you log in", "done": _agent_loaded()},
           {"key": "assistant", "text": "An assistant is connected", "done": bool(grants(ws))}]
    return out


def _agent_loaded() -> bool:
    try:
        return sibling("launchagent").written()
    except Exception:
        return False


def zone_rows(ws: Path) -> List[Dict[str, Any]]:
    """Each zone and whether it is walled, as the workspace's own zone function reads it."""
    try:
        return sibling("context").zones(ws)
    except Exception:
        return []


def view(ws: Path) -> Dict[str, Any]:
    """The whole of what Settings shows for remote access: one JSON-serialisable record. Reads; writes nothing."""
    ws = Path(ws)
    if not installed(ws):
        return {"installed": False, "name": NAME, "label": PREVIEW}
    cfg = settings()
    refusal = host_refusal(ws)
    notice = ""
    try:
        notice = (Path(__file__).resolve().parent / "notice.md").read_text(encoding="utf-8").strip()
    except OSError:
        notice = ""
    rows = []
    try:
        for g in grants(ws):
            sibling("context").prune_absent(ws, g["id"])
    except Exception:
        pass
    for g in grants(ws):
        reach = []
        try:
            reach = sibling("context").reach_rows(ws, g["id"])
        except Exception:
            reach = []
        note = ""
        try:
            sib = sibling("context")
            note = sib.reach_note(ws, sibling("store").get_grant(g["id"]) or {})
        except Exception:
            note = ""
        rows.append(dict(g, reach=reach, reach_note=note))
    return {"installed": True, "name": NAME, "label": PREVIEW, "status": cfg["status"], "port": cfg["port"],
            "address": cfg["address"], "role": role(ws), "refusal": refusal, "can_enable": not refusal,
            "steps": steps(ws, cfg, refusal), "grants": rows, "notice": notice,
            "pairing": pairing_state(), "requests": waiting_requests()}


def _ago(seconds: float) -> str:
    n = max(0, int(seconds)) // 60
    return "less than a minute ago" if n < 1 else ("%d minute%s ago" % (n, "" if n == 1 else "s"))


def waiting_requests() -> List[Dict[str, Any]]:
    """The sign-in requests that wait for the owner, oldest first, as Settings lists them: a short id, the name the client gave and when
    the request started. No link, no state and no code. Empty where they cannot be read."""
    try:
        now = time.time()
        return [{"id": r["id"], "name": r["name"], "started": _ago(now - r["made"])} for r in sibling("store").waiting_requests(now)]
    except Exception:
        return []


def pairing_state() -> Dict[str, Any]:
    """Whether a pairing code waits, and for how many more seconds; never the code."""
    try:
        return sibling("store").pairing_state()
    except Exception:
        return {"waiting": False, "seconds": 0}
