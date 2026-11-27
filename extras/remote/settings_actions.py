#!/usr/bin/env python3
"""settings_actions.py: the changes Settings makes to remote access, at the Mac (preview).

`run(ws, req)` is the one door. The page-only verb `remote` sends its `action` here: `enable`, `pause`, `resume`, `off`, `pair`,
`zone` and `revoke`. Nothing else changes a switch, a grant or a reach: no tool of the service calls this module, and the verb is
page-only, so a request that came from a chat or a remote client never reaches it.

Each answer is a dict: {"ok": bool, "say": one plain sentence, ...}. `pair` also returns `code` and `seconds`: the code is shown once
and kept only as a hash. A refusal changes nothing.

Runs on the Python that macOS ships (3.9). Standard library only. HOME and GARRICK_REMOTE_HOME are read when called.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional

sys.dont_write_bytecode = True

ACTIONS = ("enable", "pause", "resume", "off", "pair", "zone", "revoke")


def _sib(name: str):
    key = "garrick_remote_" + name
    mod = sys.modules.get(key)
    if mod is None:
        spec = importlib.util.spec_from_file_location(key, str(Path(__file__).resolve().parent / (name + ".py")))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[key] = mod
        try:
            spec.loader.exec_module(mod)
        except BaseException:
            sys.modules.pop(key, None)
            raise
    return mod


def spawn(args, **kw):
    """Start the background setup. A test replaces this."""
    return subprocess.Popen(args, **kw)


def _flag(value: Any) -> bool:
    return value is True or (isinstance(value, str) and value.strip().lower() in ("1", "true", "yes", "on"))


def _no(say: str) -> Dict[str, Any]:
    return {"ok": False, "say": say}


# --------------------------------------------------------------------------- starting the service

def start_if_on(ws: Path) -> Dict[str, Any]:
    """Load the start-up agent when remote access is on, the software is installed and an address is set. Otherwise nothing."""
    st, la = _sib("state"), _sib("launchagent")
    if st.status() != "on":
        return {"ok": False, "say": "Remote access is not on."}
    python = st.runtime_python()
    if python is None:
        return {"ok": False, "say": "The service software is not installed yet."}
    if not st.address()["url"]:
        return {"ok": False, "say": "Remote access has no address yet."}
    return la.install(Path(ws), python, Path(ws) / "System" / "remote" / "service.py", st.home() / "logs")


def _setup_started(ws: Path) -> bool:
    """Start the background setup of the software; True when it was started."""
    st = _sib("state")
    if st.setup_progress()["state"] == "running":
        return True
    try:
        spawn([sys.executable, str(Path(__file__).resolve().parent / "setup_runtime.py"), "--workspace", str(ws), "--then-start"],
              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        st.write_json(st.SETUP_FILE, {"state": "running", "say": "Setting up the service software. This takes a few minutes."})
        return True
    except OSError:
        return False


# --------------------------------------------------------------------------- the actions

def _enable(ws: Path, req: Dict[str, Any]) -> Dict[str, Any]:
    st, ad = _sib("state"), _sib("address")
    refusal = st.host_refusal(ws)
    if refusal:
        return _no(refusal)
    cfg = st.settings()
    adapter = str(req.get("adapter") or cfg["address"]["adapter"] or "relay")
    if adapter not in ("relay", "own"):
        return _no("Choose a relay or an address of your own.")
    result: Optional[Dict[str, Any]] = None
    if adapter == "own":
        typed = req.get("address") or cfg["address"]["url"]
        result = ad.own_address(typed)
    else:
        result = ad.relay_setup(cfg["port"])
    said = []
    if result["ok"]:
        change = st.set_address(result["url"], adapter, trust_forwarded=_flag(req.get("trust_forwarded")))
        if change["changed"]:
            said.append(ad.CHANGED)
    else:
        return _no(result["say"])                      # no address, or a relay that cannot publish: nothing is turned on
    st.set_status("on")
    if not st.runtime_current():
        said.append("Setting up the service software. This takes a few minutes." if _setup_started(ws)
                    else "The service software could not be set up here.")
    else:
        started = start_if_on(ws)
        if not started["ok"] and result["ok"]:
            said.append(started["say"])
    if not said:
        said.append("Remote access is on.")
    return {"ok": True, "say": " ".join(said)}


def _pause(ws: Path, req: Dict[str, Any]) -> Dict[str, Any]:
    st = _sib("state")
    if st.status() == "off":
        return _no("Remote access is off, so there is nothing to pause.")
    st.set_status("paused")
    return {"ok": True, "say": "Remote access is paused. Nothing gets in until you resume it."}


def _resume(ws: Path, req: Dict[str, Any]) -> Dict[str, Any]:
    st = _sib("state")
    if st.status() != "paused":
        return _no("Remote access is not paused.")
    refusal = st.host_refusal(ws)
    if refusal:
        return _no(refusal)
    st.set_status("on")
    if not st.runtime_current():                       # missing, or older than this release's lock: set it up first
        return {"ok": True, "say": "Remote access is on again. Setting up the service software first. This takes a few minutes."
                if _setup_started(ws) else "Remote access is on again. The service software could not be set up here."}
    started = start_if_on(ws)
    return {"ok": True, "say": "Remote access is on again." if started["ok"] else "Remote access is on again. " + started["say"]}


def _off(ws: Path, req: Dict[str, Any]) -> Dict[str, Any]:
    st, la, ad, store = _sib("state"), _sib("launchagent"), _sib("address"), _sib("store")
    cfg = st.settings()
    st.set_status("off")
    la.remove()
    if cfg["address"]["adapter"] == "relay":
        ad.relay_stop(cfg["port"])
    with store.txn() as db:
        db["pairing"] = {}
    return {"ok": True, "say": "Remote access is off. Your connected assistants stay listed, and none of them can get in."}


def _pair(ws: Path, req: Dict[str, Any]) -> Dict[str, Any]:
    st, store = _sib("state"), _sib("store")
    state = st.status()
    if state == "paused":
        return _no("Remote access is paused. Resume it first.")
    if state != "on":
        return _no("Turn remote access on first.")
    if not st.address()["url"]:
        return _no("Remote access has no address yet. Set it up first.")
    if store.consent_locked():
        return _no("Too many wrong codes were tried. The sign-in page opens again in a few minutes.")
    waiting = store.waiting_requests()
    asked = str(req.get("request") or "").strip()
    if asked:
        picked = [r for r in waiting if r["id"] == asked]
        if not picked:
            return _no("That sign-in is not waiting any more. Start it again in your assistant, then choose Show a code.")
    elif len(waiting) == 1:
        picked = waiting
    elif not waiting:
        return _no("No sign-in is waiting. Start one in your assistant, then choose Show a code.")
    else:
        return _no("More than one sign-in is waiting. Pick the one you started, then choose Show a code.")
    made = store.make_pairing_code(request=picked[0]["id"])
    if made is None:
        return _no("That sign-in is not waiting any more. Start it again in your assistant, then choose Show a code.")
    code, seconds = made
    return {"ok": True, "say": "Type this code on the page of the sign-in you picked, within five minutes. It works once, for that sign-in only.",
            "code": code, "seconds": seconds}


def _zone(ws: Path, req: Dict[str, Any]) -> Dict[str, Any]:
    ctx, store = _sib("context"), _sib("store")
    gid, name = str(req.get("grant") or ""), str(req.get("zone") or "").strip()
    grant = store.get_grant(gid)
    if grant is None:
        return _no("That connection is not active.")
    known = ctx.zones(ws)
    if known:
        store.prune_zones(gid, [z["zone"] for z in known])
        grant = store.get_grant(gid) or grant
    found = [z for z in known if z["zone"].casefold() == name.casefold()]
    if not found:
        return _no("That zone is not in this workspace.")
    zone = found[0]
    if not zone["walled"] and not (_flag(req.get("read")) or _flag(req.get("write"))) and (grant.get("zones") or {}).get(zone["zone"]):
        store.set_zone(gid, zone["zone"], False, False)                      # an old entry for a zone that is open now: clear it
        return {"ok": True, "say": "%s is open, and its old setting for this connection is cleared." % zone["zone"]}
    if not zone["walled"]:
        return _no("%s is open, so every connection already reaches it." % zone["zone"])
    read, write = _flag(req.get("read")), _flag(req.get("write"))
    marker = ctx.zone_marker(ws, zone["zone"])
    stored = (grant.get("zones") or {}).get(zone["zone"], {})
    now = stored if ctx.entry_holds(ws, zone["zone"], stored) else {}       # an entry from another folder, or from before markers, is off
    turning_on = (read and not now.get("read")) or (write and not now.get("write"))
    others = [z for z in ctx.live_zones(ws, grant) if z != zone["zone"]]
    if turning_on and others:
        return _no(ctx.ONE_WALLED)
    if turning_on and not _flag(req.get("acknowledged")):
        return _no("Read the notice first. Nothing was changed.")
    if write and "write" not in grant["classes"]:
        return _no("This connection was not allowed to write, so it cannot write in %s." % zone["zone"])
    if (read or write) and not marker:
        return _no("%s could not be read, so it was not turned on." % zone["zone"])
    if not store.set_zone(gid, zone["zone"], read, write, marker=marker):
        return _no("That connection is not active.")
    if not (read or write):
        return {"ok": True, "say": "%s is out of reach for this connection." % zone["zone"]}
    return {"ok": True, "say": "%s is now in reach for this connection. Chats that started before this need a new chat." % zone["zone"]}


def _revoke(ws: Path, req: Dict[str, Any]) -> Dict[str, Any]:
    store = _sib("store")
    if not store.revoke(str(req.get("grant") or "")):
        return _no("That connection is not active.")
    return {"ok": True, "say": "That connection is revoked. Its next call is refused."}


_DO: Dict[str, Callable[[Path, Dict[str, Any]], Dict[str, Any]]] = {
    "enable": _enable, "pause": _pause, "resume": _resume, "off": _off, "pair": _pair, "zone": _zone, "revoke": _revoke}


def run(ws, req) -> Dict[str, Any]:
    """Do one action of remote access. Never raises: a stop is {"ok": False, "say": a plain sentence} and changes nothing it did not say."""
    try:
        ws = Path(ws)
        req = req if isinstance(req, dict) else {}
        action = str(req.get("action") or "")
        if action not in ACTIONS:
            return _no("Remote access has no such action.")
        if not _sib("state").installed(ws):
            return _no("Remote access is not installed in this workspace.")
        return _DO[action](ws, req)
    except Exception:
        return _no("Remote access could not do that. Nothing was changed that you were not told about.")
