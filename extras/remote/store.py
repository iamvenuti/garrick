#!/usr/bin/env python3
"""store.py: the sign-in records of remote access (preview): clients, grants, pairing codes, authorization codes, tokens.

One file, `auth.json` in the state folder, mode 0600, outside the workspace and outside git. Every token, every code and
the pairing code are kept as SHA-256 hashes: this file never holds a value that a caller could present. Two processes
write it, the service and the Settings action, so every change runs under one lock (a lock file, and a lock in the
process), reads the file, changes it and writes it whole.

Times are seconds since the epoch, passed in as `now` so a test sets the clock. Standard library only; runs on the
Python that macOS ships (3.9) as well as on the extra's own runtime.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import hashlib
import hmac
import json
import os
import secrets
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

sys.dont_write_bytecode = True


def _state():
    key = "garrick_remote_state"
    mod = sys.modules.get(key)
    if mod is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location(key, str(Path(__file__).resolve().parent / "state.py"))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[key] = mod
        spec.loader.exec_module(mod)
    return mod


AUTH_FILE = "auth.json"
LOCK_FILE = "auth.lock"
KEY_FILE = "handle.key"
CLASSES = ("read", "write")

ACCESS_SECONDS = 10 * 60                 # an access token lives ten minutes
REFRESH_SECONDS = 30 * 24 * 3600         # a refresh token thirty days, and rotates on every use
CODE_SECONDS = 5 * 60                    # a pairing code lives five minutes and works once
AUTHCODE_SECONDS = 2 * 60                # an authorization code, from consent to the token call
PENDING_SECONDS = 10 * 60                # a sign-in request waits for the owner this long
UNFINISHED_SECONDS = 60 * 60             # a registration that never completes is dropped after an hour
MAX_UNFINISHED = 200                     # and no more than this many wait at once
MAX_PENDING = 50                         # sign-in requests that wait for the owner at once; a new one pushes out the oldest
LOCK_AFTER = 5                           # wrong codes before the consent page locks
LOCK_SECONDS = 15 * 60

_THREAD_LOCK = threading.RLock()


def sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _empty() -> Dict[str, Any]:
    return {"clients": {}, "grants": {}, "pairing": {}, "authcodes": {}, "pending": {}, "access": {}, "refresh": {},
            "consent": {"wrong": 0, "locked_until": 0}}


@contextlib.contextmanager
def txn(now: Optional[float] = None) -> Iterator[Dict[str, Any]]:
    """The records, read under the lock; changes made inside are written when the block ends without an error. Entries
    that ran out are dropped first, so nothing lives past its time."""
    st = _state()
    now = time.time() if now is None else now
    folder = st.ensure_home()
    with _THREAD_LOCK:
        fd = os.open(str(folder / LOCK_FILE), os.O_RDWR | os.O_CREAT, st.MODE_FILE)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            data = st.read_json(AUTH_FILE, None)
            base = _empty()
            if isinstance(data, dict):
                for key in base:
                    if isinstance(data.get(key), type(base[key])):
                        base[key] = data[key]
            before = json.dumps(base, sort_keys=True)
            _expire(base, now)
            yield base
            if json.dumps(base, sort_keys=True) != before or not (folder / AUTH_FILE).exists():
                st.write_json(AUTH_FILE, base)
        finally:
            with contextlib.suppress(OSError):
                fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


def _expire(db: Dict[str, Any], now: float) -> None:
    for name in ("pairing", "authcodes", "pending", "access"):
        for key in [k for k, v in db[name].items() if not isinstance(v, dict) or v.get("expires", 0) <= now]:
            del db[name][key]
    for key in [k for k, v in db["refresh"].items() if not isinstance(v, dict) or v.get("expires", 0) <= now]:
        del db["refresh"][key]
    for key in [k for k, v in db["clients"].items()
                if isinstance(v, dict) and not v.get("done") and v.get("made", 0) + UNFINISHED_SECONDS <= now]:
        del db["clients"][key]


def peek(now: Optional[float] = None) -> Dict[str, Any]:
    """The records as they stand, read without a lock, without making the folder and without writing: what Settings reads. What ran out
    is left out of what comes back, and the file is left as it is."""
    now = time.time() if now is None else now
    base = _empty()
    data = _state().read_json(AUTH_FILE, None)
    if isinstance(data, dict):
        for key in base:
            if isinstance(data.get(key), type(base[key])):
                base[key] = data[key]
    _expire(base, now)
    return base


# --------------------------------------------------------------------------- the key behind a handle

def handle_key() -> bytes:
    """32 random bytes, made once and kept in the state folder, mode 0600. They sign a handle; nothing else uses them."""
    st = _state()
    folder = st.ensure_home()
    path = folder / KEY_FILE
    with _THREAD_LOCK:
        try:
            raw = path.read_bytes()
            if len(raw) == 32:
                return raw
        except OSError:
            pass
        raw = secrets.token_bytes(32)
        tmp = folder / (KEY_FILE + ".tmp")
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, st.MODE_FILE)
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
        os.replace(str(tmp), str(path))
        return raw


# --------------------------------------------------------------------------- the pairing code and the consent lock

def make_pairing_code(now: Optional[float] = None) -> Tuple[str, int]:
    """A new six-digit code, kept as a hash, good for five minutes and one use. A new code replaces the one before it.
    Returns the code, to be shown once, and its life in seconds."""
    now = time.time() if now is None else now
    code = "%06d" % secrets.randbelow(1000000)
    with txn(now) as db:
        db["pairing"] = {sha(code): {"expires": now + CODE_SECONDS}}
        db["consent"]["wrong"] = 0                       # a new code starts a new count
    return code, CODE_SECONDS


def pairing_state(now: Optional[float] = None) -> Dict[str, Any]:
    now = time.time() if now is None else now
    db = peek(now)
    left = max([int(v["expires"] - now) for v in db["pairing"].values()] or [0])
    locked = db["consent"].get("locked_until", 0) - now
    return {"waiting": left > 0, "seconds": left, "locked": int(locked) + 1 if locked > 0 else 0}


def consent_locked(now: Optional[float] = None) -> int:
    """Seconds left before the consent page takes a code again; 0 when it is open."""
    now = time.time() if now is None else now
    db = peek(now)
    left = db["consent"].get("locked_until", 0) - now
    return int(left) + 1 if left > 0 else 0


def check_pairing_code(code: str, now: Optional[float] = None) -> bool:
    """Try a code. The right one works once, and only while the page is open. A wrong one counts: the fifth in a row locks
    the page for 15 minutes, and a locked page takes no code at all, the right one included."""
    now = time.time() if now is None else now
    with txn(now) as db:
        consent = db["consent"]
        if consent.get("locked_until", 0) > now:
            return False
        if not db["pairing"]:
            return False                                 # no code waits: nothing to guess, so a wrong try is not counted
        text = str(code or "").strip()
        ok = False
        if len(text) == 6 and text.isdigit():
            for known in list(db["pairing"]):
                if hmac.compare_digest(known, sha(text)):
                    ok = True
                    del db["pairing"][known]
        if ok:
            consent["wrong"] = 0
            return True
        consent["wrong"] = int(consent.get("wrong", 0)) + 1
        if consent["wrong"] >= LOCK_AFTER:
            consent["wrong"] = 0
            consent["locked_until"] = now + LOCK_SECONDS
        return False


# --------------------------------------------------------------------------- clients

def put_client(client_id: str, info: Dict[str, Any], now: Optional[float] = None) -> bool:
    """Keep a registered client. False when too many registrations wait to be finished: a flood is refused, not stored."""
    now = time.time() if now is None else now
    with txn(now) as db:
        waiting = sum(1 for v in db["clients"].values() if not v.get("done"))
        if client_id not in db["clients"] and waiting >= MAX_UNFINISHED:
            return False
        db["clients"][client_id] = {"info": info, "made": now, "done": db["clients"].get(client_id, {}).get("done", False)}
        return True


def get_client(client_id: str) -> Optional[Dict[str, Any]]:
    db = peek()
    row = db["clients"].get(client_id)
    return dict(row["info"]) if row else None


# --------------------------------------------------------------------------- grants

def today(now: Optional[float] = None) -> str:
    return dt.datetime.fromtimestamp(time.time() if now is None else now).date().isoformat()


def create_grant(client_id: str, name: str, classes: List[str], now: Optional[float] = None) -> str:
    now = time.time() if now is None else now
    chosen = sorted({c for c in classes if c in CLASSES})
    gid = "g-" + secrets.token_hex(6)
    with txn(now) as db:
        db["grants"][gid] = {"client_id": client_id, "name": str(name or "An assistant")[:80], "classes": chosen,
                             "created": today(now), "last_used": "", "revoked": False, "zones": {}}
        if client_id in db["clients"]:
            db["clients"][client_id]["done"] = True
    return gid


def get_grant(gid: str) -> Optional[Dict[str, Any]]:
    """A live grant as stored (no hashes live in it); None when it is gone or revoked."""
    db = peek()
    g = db["grants"].get(gid)
    if not g or g.get("revoked"):
        return None
    return dict(g, id=gid)


def listing() -> List[Dict[str, Any]]:
    """The grants as Settings lists them: id, client name, classes, the day it connected, the day it was last used."""
    db = peek()
    return sorted(({"id": gid, "name": g["name"], "classes": list(g["classes"]), "created": g["created"],
                    "last_used": g.get("last_used", "")}
                   for gid, g in db["grants"].items() if not g.get("revoked")), key=lambda r: (r["created"], r["id"]))


def touch(gid: str, now: Optional[float] = None) -> None:
    now = time.time() if now is None else now
    with txn(now) as db:
        g = db["grants"].get(gid)
        if g and g.get("last_used") != today(now):
            g["last_used"] = today(now)


def revoke(gid: str, now: Optional[float] = None) -> bool:
    """Close a grant: its tokens go with it, so the next call is refused. False when there is no such live grant."""
    with txn(now) as db:
        g = db["grants"].get(gid)
        if not g or g.get("revoked"):
            return False
        g["revoked"] = True
        for name in ("access", "refresh", "authcodes"):
            for key in [k for k, v in db[name].items() if v.get("grant") == gid]:
                del db[name][key]
        return True


def set_zone(gid: str, zone: str, read: bool, write: bool, now: Optional[float] = None) -> bool:
    """Turn a zone's reads and writes on or off for a grant, with the day of the change. Both off takes the zone out."""
    with txn(now) as db:
        g = db["grants"].get(gid)
        if not g or g.get("revoked"):
            return False
        old = g["zones"].get(zone, {})
        day = today(now)
        entry = {"read": (old.get("read") or day) if read else "", "write": (old.get("write") or day) if write else ""}
        if entry["read"] or entry["write"]:
            g["zones"][zone] = entry
        else:
            g["zones"].pop(zone, None)
        return True


def prune_zones(gid: str, known) -> None:
    """Drop the walled-zone entries of a grant whose zone is not among `known` any more, so a later zone of the same name starts with nothing."""
    names = set(known)
    with txn() as db:
        g = db["grants"].get(gid)
        if g:
            for zone in [z for z in g["zones"] if z not in names]:
                del g["zones"][zone]


# --------------------------------------------------------------------------- sign-in requests and codes

def put_pending(data: Dict[str, Any], now: Optional[float] = None) -> Optional[str]:
    """Keep a sign-in request while the owner decides, and give it a short random id of its own (`rid`) for Settings to name it by. When 50
    already wait, the oldest goes and this one stays, so a flood of new sign-ins cannot shut the owner out. The request that a live pairing
    code was made for is never the one that goes."""
    now = time.time() if now is None else now
    pid = secrets.token_urlsafe(32)
    with txn(now) as db:
        held = {v.get("request") for v in db["pairing"].values() if isinstance(v, dict)}
        while len(db["pending"]) >= MAX_PENDING:
            order = sorted(((float(v.get("made", 0)) if isinstance(v, dict) else 0.0), k) for k, v in db["pending"].items()
                           if not (isinstance(v, dict) and v.get("rid") in held))
            if not order:
                return None                                  # nothing may go: refuse the new one, as before
            del db["pending"][order[0][1]]
        db["pending"][pid] = dict(data, expires=now + PENDING_SECONDS, made=now, rid=secrets.token_hex(4))
    return pid


def get_pending(pid: str, now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    db = peek(now)
    row = db["pending"].get(pid)
    return dict(row) if row else None


def pop_pending(pid: str, now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    with txn(now) as db:
        row = db["pending"].pop(pid, None)
        return dict(row) if row else None


def put_authcode(data: Dict[str, Any], now: Optional[float] = None) -> str:
    """An authorization code for the token call, kept as a hash, good for two minutes and one use."""
    now = time.time() if now is None else now
    code = secrets.token_urlsafe(32)
    with txn(now) as db:
        db["authcodes"][sha(code)] = dict(data, expires=now + AUTHCODE_SECONDS, used=False)
    return code


def load_authcode(code: str, now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    db = peek(now)
    row = db["authcodes"].get(sha(code))
    return dict(row) if row else None


def spend_authcode(code: str, now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Take an authorization code once. A second use of the same code closes the grant it made: it was copied."""
    with txn(now) as db:
        row = db["authcodes"].get(sha(code))
        if row is None:
            return None
        if row.get("used"):
            gid = row.get("grant")
            g = db["grants"].get(gid)
            if g:
                g["revoked"] = True
                for name in ("access", "refresh"):
                    for key in [k for k, v in db[name].items() if v.get("grant") == gid]:
                        del db[name][key]
            return None
        row["used"] = True
        return dict(row)


# --------------------------------------------------------------------------- tokens

def _issue(db: Dict[str, Any], gid: str, client_id: str, scopes: List[str], resource: str, now: float) -> Dict[str, Any]:
    access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    db["access"][sha(access)] = {"grant": gid, "client": client_id, "scopes": list(scopes), "resource": resource,
                                 "expires": now + ACCESS_SECONDS}
    db["refresh"][sha(refresh)] = {"grant": gid, "client": client_id, "scopes": list(scopes), "resource": resource,
                                   "expires": now + REFRESH_SECONDS, "used": False}
    return {"access": access, "refresh": refresh, "expires_in": ACCESS_SECONDS}


def issue(gid: str, client_id: str, scopes: List[str], resource: str, now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    now = time.time() if now is None else now
    with txn(now) as db:
        g = db["grants"].get(gid)
        if not g or g.get("revoked"):
            return None
        return _issue(db, gid, client_id, scopes, resource, now)


def lookup_access(token: str, now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """What an access token stands for, or None: unknown, expired, or its grant revoked."""
    now = time.time() if now is None else now
    db = peek(now)
    row = db["access"].get(sha(token))
    if not row:
        return None
    g = db["grants"].get(row["grant"])
    if not g or g.get("revoked"):
        return None
    return dict(row, expires=int(row["expires"]))


def lookup_refresh(token: str, now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    now = time.time() if now is None else now
    db = peek(now)
    row = db["refresh"].get(sha(token))
    if not row:
        return None
    g = db["grants"].get(row["grant"])
    if not g or g.get("revoked"):
        return None
    return dict(row, expires=int(row["expires"]))


def rotate(token: str, scopes: List[str], now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Use a refresh token once. It answers with a new pair and is marked used. Used a second time, it closes the grant:
    two parties held it. Returns the new pair, or None."""
    now = time.time() if now is None else now
    with txn(now) as db:
        row = db["refresh"].get(sha(token))
        if row is None:
            return None
        gid = row["grant"]
        g = db["grants"].get(gid)
        if not g or g.get("revoked"):
            return None
        if row.get("used"):
            g["revoked"] = True
            for name in ("access", "refresh"):
                for key in [k for k, v in db[name].items() if v.get("grant") == gid]:
                    del db[name][key]
            return None
        row["used"] = True
        narrowed = [s for s in scopes if s in row["scopes"]] or list(row["scopes"])
        return _issue(db, gid, row["client"], narrowed, row["resource"], now)


def drop_token(token: str) -> None:
    """Revoke one token and its partner: the grant stays, the pair goes."""
    with txn() as db:
        h = sha(token)
        row = db["access"].pop(h, None) or db["refresh"].pop(h, None)
        if row:
            for name in ("access", "refresh"):
                for key in [k for k, v in db[name].items() if v.get("grant") == row["grant"] and v.get("client") == row["client"]]:
                    del db[name][key]
