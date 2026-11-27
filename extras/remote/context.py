#!/usr/bin/env python3
"""context.py: what a grant may reach, and the handle that keeps a chat to it (preview).

A grant's reach is the zones it may read and the zones it may write, set at the Mac. The default reach is every zone whose
walled flag is off, as the workspace's own zone function reads it (`garrick_lib.load_context`, never a parse of
`System/context.md` here), with Knowledge and Garrick's docs for reading. A walled zone joins a grant only through
`settings_actions`, by name, reads and writes as separate choices, with the day it was turned on.

No tool changes a reach, a grant or a setting. The tools have no argument that names a zone outside the reach; a zone, a path
or an id in a request is checked against the `Session`, and the check fails closed.

A handle is a signed note that says which grant and which reach an answer came from. It carries no secret and proves nothing
about the chat: it keeps record ids and retries apart, and it stops working the moment the reach changes, so an old chat
that carries on after the owner changed the reach is refused with the words "start a new chat".

Standard library only; runs on the Python that macOS ships (3.9) as well as on the extra's own runtime.
"""
from __future__ import annotations

import base64
import dataclasses
import hashlib
import hmac
import importlib.util
import json
import os
import secrets
import stat
import sys
import time
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional

sys.dont_write_bytecode = True

KNOWLEDGE = "Knowledge"
DOCS = "docs"
HANDLE_SECONDS = 12 * 3600
HANDLE_WORDS = "That chat belongs to an earlier setting. Start a new chat."
NEW_CONTEXT_REQUIRED = "new_context_required"          # the machine code a client may match; its spoken sentence says reach
NEW_CONTEXT_SAY = "That is outside what this connection may reach. The owner sets that at the Mac."


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


def _clock() -> float:
    return time.time()


class HandleRefused(Exception):
    """A handle that is made up, out of date, for another grant, or from before the reach changed."""


# --------------------------------------------------------------------------- the zones of the workspace

_LIBS: Dict[str, Any] = {}


def _lib(ws: Path):
    """The workspace's own garrick_lib, loaded from its file and kept while the file stays as it is."""
    path = Path(ws) / "System" / "tools" / "garrick_lib.py"
    try:
        stamp = (str(path), path.stat().st_mtime_ns)
    except OSError:
        return None
    hit = _LIBS.get(stamp[0])
    if hit and hit[0] == stamp:
        return hit[1]
    key = "garrick_remote_lib_%d" % (abs(hash(stamp[0])) % 10 ** 8)
    spec = importlib.util.spec_from_file_location(key, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(key, None)
        return None
    _LIBS[stamp[0]] = (stamp, mod)
    return mod


def zones(ws: Path) -> List[Dict[str, Any]]:
    """Each zone the workspace names and whether it is walled, as `load_context` reads it. A zone with no flag is walled.
    Empty where the zone function cannot be read: nothing is then open."""
    lib = _lib(ws)
    if lib is None:
        return []
    try:
        ctx = lib.load_context(Path(ws))
        names = sorted((ctx.get("zone_walled") or {}).keys(), key=str.casefold)
        return [{"zone": str(z), "walled": bool(lib.walled(ctx, z))} for z in names]
    except Exception:
        return []


def open_zones(ws: Path) -> List[str]:
    return [z["zone"] for z in zones(ws) if not z["walled"]]


def zone_marker(ws: Path, zone: str) -> str:
    """A marker of one zone's folder: it changes when the folder is removed and made again, and not when something inside it is edited.
    It is made of the folder's device, its inode and its birth time. "" when the folder cannot be read or the system gives no birth time:
    a caller treats that as no zone."""
    try:
        base = Path(ws) / "Zones"
        folder = base / str(zone)
        if str(zone) in ("", ".", "..") or not str(zone).strip() or folder.parent != base or folder.name != str(zone):
            return ""
        st = os.stat(str(folder))
        if not stat.S_ISDIR(st.st_mode):
            return ""
        born = getattr(st, "st_birthtime_ns", None)
        if born is None:
            born = int((getattr(st, "st_birthtime", 0) or 0) * 1000000000)
        if not born:
            return ""                                                 # no birth time: an inode can come back, so the zone cannot be marked
        text = "zone1:%d:%d:%d" % (st.st_dev, st.st_ino, born)
        return hashlib.sha256(text.encode("ascii")).hexdigest()[:32]
    except (OSError, ValueError):
        return ""


def entry_holds(ws: Path, zone: str, entry: Any) -> bool:
    """Is this stored entry for this zone good now: it has a marker, the zone folder can be read, and the two are the same folder?
    An entry from before markers has none, so it is not good until the owner turns the zone on again in Settings."""
    if not isinstance(entry, dict):
        return False
    stored = entry.get("marker")
    if not isinstance(stored, str) or not stored:
        return False
    now = zone_marker(ws, zone)
    return bool(now) and hmac.compare_digest(stored, now)


# --------------------------------------------------------------------------- reach

def _grant(gid: str) -> Optional[Dict[str, Any]]:
    return _sib("store").get_grant(gid)


def _live(ws: Path, grant: Dict[str, Any], known: Dict[str, bool]) -> Dict[str, Dict[str, Any]]:
    """The walled zones a grant holds that count now: still in the workspace, still walled, turned on (read or write), and the same folder
    that was turned on. An entry for a zone that is open now adds nothing here: an open zone is in every reach anyway."""
    out = {}
    for zone, entry in (grant.get("zones") or {}).items():
        if known.get(zone) and isinstance(entry, dict) and (entry.get("read") or entry.get("write")) and entry_holds(ws, zone, entry):
            out[zone] = entry
    return out


def live_zones(ws: Path, grant: Dict[str, Any]) -> List[str]:
    """The names of the walled zones that count in a grant's reach now."""
    return sorted(_live(ws, grant, {z["zone"]: z["walled"] for z in zones(ws)}))


def reach_of(ws: Path, grant: Dict[str, Any]) -> Dict[str, FrozenSet[str]]:
    """The zones a grant may read and write now: the zones that are open today, plus the walled zones the owner turned on for
    it, by name, that the workspace still has and that are still walled or open as named. A walled zone the owner turned on
    stays in only while it exists."""
    known = {z["zone"]: z["walled"] for z in zones(ws)}
    classes = frozenset(c for c in grant.get("classes", ()) if c in ("read", "write"))
    readable = {z for z, walled in known.items() if not walled}
    writable = set(readable)
    live = _live(ws, grant, known)
    for zone, entry in live.items():
        if entry.get("read"):
            readable.add(zone)
        if entry.get("write"):
            writable.add(zone)
    if len(live) > 1:                                                  # one connection reaches one walled zone: with two stored, none
        readable = {z for z, walled in known.items() if not walled}
        writable = set(readable)
    readable |= {KNOWLEDGE, DOCS}
    return {"readable": frozenset(readable), "writable": frozenset(writable), "classes": classes}


ONE_WALLED = "One connection reaches one walled zone. Use another connection for the second zone."
TOO_MANY = "This connection holds more than one walled zone, so it reaches none of them. Turn all but one off."


def reach_note(ws: Path, grant: Dict[str, Any]) -> str:
    """Why a grant's walled zones are all out of reach, or "" when they are not."""
    known = {z["zone"]: z["walled"] for z in zones(ws)}
    return TOO_MANY if len(_live(ws, grant, known)) > 1 else ""


def prune_absent(ws: Path, gid: str) -> None:
    """Drop the walled-zone entries of a grant for zones the workspace no longer has. Nothing is dropped when the zone list cannot be read."""
    known = [z["zone"] for z in zones(ws)]
    grant = _grant(gid)
    if known and grant and any(z not in known for z in (grant.get("zones") or {})):
        _sib("store").prune_zones(gid, known)


def reach_rows(ws: Path, gid: str) -> List[Dict[str, Any]]:
    """What Settings shows of a grant's reach: each zone, whether it is walled, whether the grant reads it and writes it, and
    the day the owner turned a walled zone on. Open zones are in the reach of every grant; the owner cannot take them out
    here, so the row says so."""
    prune_absent(ws, gid)
    grant = _grant(gid)
    if grant is None:
        return []
    out = []
    for z in zones(ws):
        entry = (grant.get("zones") or {}).get(z["zone"], {}) if z["walled"] else {}
        if z["walled"] and not entry_holds(ws, z["zone"], entry):
            entry = {}                                                    # an old entry, or another folder of that name: off until turned on again
        out.append({"zone": z["zone"], "walled": z["walled"],
                    "read": (not z["walled"]) or bool(entry.get("read")),
                    "write": ((not z["walled"]) and "write" in grant["classes"]) or bool(entry.get("write")),
                    "since": str(entry.get("read") or entry.get("write") or "")})
    return out


@dataclasses.dataclass(frozen=True)
class Session:
    """What one grant may do, as the service holds it. The tools take it as it is: they never build one and never change one."""
    grant_id: str
    workspace: Path
    classes: FrozenSet[str]
    readable: FrozenSet[str]
    writable: FrozenSet[str]
    secret: bytes = dataclasses.field(default=b"", repr=False, compare=False)

    def reach_id(self) -> str:
        """A short fingerprint of the reach: the classes and the two zone sets. It changes when any of them does."""
        text = json.dumps([sorted(self.classes), sorted(z.casefold() for z in self.readable),
                           sorted(z.casefold() for z in self.writable)])
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    def zone_allowed(self, zone: Any, write: bool = False) -> bool:
        """May this grant read (or write) this zone? Anything that is not a plain zone name, a zone the grant does not hold and a
        class the grant lacks all say no."""
        if not isinstance(zone, str) or not zone.strip():
            return False
        if ("write" if write else "read") not in self.classes:
            return False
        names = self.writable if write else self.readable
        return zone.strip().casefold() in {n.casefold() for n in names}

    def _key(self) -> bytes:
        return self.secret or _sib("store").handle_key()

    def new_handle(self) -> str:
        """A handle for an answer, good for twelve hours and for as long as the reach stays as it is."""
        body = {"g": self.grant_id, "f": self.reach_id(), "e": int(_clock()) + HANDLE_SECONDS, "n": secrets.token_hex(4)}
        raw = base64.urlsafe_b64encode(json.dumps(body, sort_keys=True).encode("utf-8")).decode("ascii").rstrip("=")
        sig = hmac.new(self._key(), raw.encode("ascii"), hashlib.sha256).hexdigest()[:32]
        return "h1.%s.%s" % (raw, sig)

    def check_handle(self, handle: Any) -> None:
        """Pass for a handle this grant made under this reach; otherwise raise HandleRefused with the words to start a new chat.
        Made-up, out of date and changed-reach handles all say the same thing."""
        try:
            tag, raw, sig = str(handle).split(".")
            if tag != "h1" or len(sig) != 32:
                raise ValueError("form")
            good = hmac.new(self._key(), raw.encode("ascii"), hashlib.sha256).hexdigest()[:32]
            if not hmac.compare_digest(good, sig):
                raise ValueError("signature")
            body = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8"))
            if body.get("g") != self.grant_id or body.get("f") != self.reach_id() or int(body.get("e", 0)) <= _clock():
                raise ValueError("stale")
        except Exception:
            raise HandleRefused(HANDLE_WORDS) from None


def session_for(ws: Path, gid: str, scopes=None) -> Session:
    """The Session of a live grant, from the reach as it stands now. Raises HandleRefused-free ValueError for a grant that is
    gone or revoked: the caller turns that into a refusal."""
    grant = _grant(gid)
    if grant is None:
        raise ValueError("That connection is not active.")
    known = [z["zone"] for z in zones(ws)]
    if known and any(z not in known for z in (grant.get("zones") or {})):
        _sib("store").prune_zones(gid, known)                          # a zone that left the workspace takes its entry with it
        grant = _grant(gid) or grant
    reach = reach_of(ws, grant)
    classes = reach["classes"] if scopes is None else reach["classes"] & frozenset(scopes)   # never wider than the token's own scopes
    return Session(grant_id=gid, workspace=Path(ws), classes=classes, readable=reach["readable"],
                   writable=reach["writable"])
