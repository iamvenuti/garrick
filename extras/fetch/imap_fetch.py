#!/usr/bin/env python3
"""Fetch mail from one IMAP mailbox into one zone's Inbox. An optional extra.

A fetcher writes files into `Zones/<Zone>/Inbox/` and decides nothing. This one
saves each new message in one mailbox (a folder, or a Gmail label) as a `.eml`
file in the zone Inbox the config names, remembers which messages it has saved
so a rerun never duplicates one, and can then mark each one read or copy it to
another mailbox. Where a message goes after that is for the intake skill to
decide, when you say "process the inbox".

    python3 imap_fetch.py --config ~/.config/garrick/work-mail.json

The config is a small JSON file:

    {
      "server": "imap.example.com",
      "user": "sam@example.com",
      "mailbox": "Garrick/Work",
      "inbox": "/Users/sam/Garrick/Zones/Work/Inbox"
    }

Optional keys: "port" (993), "search" (an IMAP search, default "ALL"),
"mark_read" (false), "copy_to" (a mailbox to copy each saved message to; on
Gmail that adds a label), "keychain_service" ("garrick-imap"), and "state"
(where the list of saved messages is kept; default: beside the config, as
<config name>.state.json).

The password comes from the macOS Keychain, and nowhere else: never from an
argument, the config or a file. Store it once:

    security add-generic-password -s garrick-imap -a sam@example.com -w

and type it when asked. Works with any IMAP server that accepts a password
(Gmail app passwords, iCloud Mail, Fastmail); not with Microsoft 365 or
Outlook.com, which accept only OAuth. Standard library only, Python 3.9 or
later. Not installed by install.py and not part of a Garrick workspace.
"""

from __future__ import annotations

import argparse
import datetime
import email
import email.policy
import imaplib
import json
import os
import re
import subprocess
import sys
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable, List, Optional

DEFAULTS = {"port": 993, "search": "ALL", "mark_read": False, "copy_to": "", "keychain_service": "garrick-imap"}
REQUIRED = ("server", "user", "mailbox", "inbox")
KNOWN = set(REQUIRED) | set(DEFAULTS) | {"state"}
SECRET_KEYS = {"password", "pass", "passwd", "secret", "token", "app_password"}


class FetchError(Exception):
    """A refusal or failure, in one line for whoever runs the fetcher."""


# --------------------------------------------------------------------------- config and state


def load_config(path: Path) -> dict:
    """Read and check the config. Refuses a password in it, an unknown key, and
    an inbox that is not an existing `Zones/<Zone>/Inbox` folder."""
    try:
        raw = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FetchError("Could not read %s: %s" % (path, exc))
    if not isinstance(raw, dict):
        raise FetchError("%s must hold one JSON object." % path)
    secret = sorted(SECRET_KEYS & {k.lower() for k in raw})
    if secret:
        raise FetchError("%s has a %s in it. Take it out: the password lives in the macOS Keychain only."
                         % (path, secret[0]))
    unknown = sorted(set(raw) - KNOWN)
    if unknown:
        raise FetchError("%s has keys this fetcher does not know: %s." % (path, ", ".join(unknown)))
    missing = [k for k in REQUIRED if not str(raw.get(k, "")).strip()]
    if missing:
        raise FetchError("%s is missing %s." % (path, ", ".join(missing)))
    cfg = dict(DEFAULTS, **raw)
    inbox = Path(str(cfg["inbox"])).expanduser()
    if inbox.name != "Inbox" or inbox.parent.parent.name != "Zones" or not inbox.is_dir():
        raise FetchError("%s is not a zone's Inbox folder, Zones/<Zone>/Inbox, that exists." % inbox)
    cfg["inbox"] = inbox
    cfg["state"] = Path(str(cfg.get("state") or Path(path).expanduser().with_suffix(".state.json"))).expanduser()
    return cfg


def load_state(path: Path) -> dict:
    try:
        state = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        raise FetchError("Could not read the state file %s: %s. Fix or remove it; removing it means every "
                         "message is fetched again." % (path, exc))
    return state if isinstance(state, dict) else {}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("." + path.name + ".part")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(str(tmp), str(path))


# --------------------------------------------------------------------------- the password


def keychain_password(service: str, account: str, run: Callable = subprocess.run) -> str:
    """The password stored in the macOS Keychain for `service` and `account`.
    The value never appears in a command line, a file or the output."""
    try:
        res = run(["security", "find-generic-password", "-s", service, "-a", account, "-w"],
                  capture_output=True, text=True)
    except FileNotFoundError:
        raise FetchError("The macOS `security` command is not here; this fetcher reads its password from the Keychain.")
    if res.returncode != 0 or not res.stdout.strip():
        raise FetchError("No Keychain password for service %s and account %s. Store it with: "
                         "security add-generic-password -s %s -a %s -w" % (service, account, service, account))
    return res.stdout.rstrip("\n")


# --------------------------------------------------------------------------- fetching


def quote_mailbox(name: str) -> str:
    return '"%s"' % name.replace("\\", "\\\\").replace('"', '\\"')


def _ok(typ, what: str) -> None:
    if typ != "OK":
        raise FetchError("The server refused %s." % what)


def _message_bytes(data) -> Optional[bytes]:
    for part in data or []:
        if isinstance(part, tuple) and len(part) >= 2 and isinstance(part[1], (bytes, bytearray)):
            return bytes(part[1])
    return None


def file_name(data: bytes, uid: int) -> str:
    """`YYMMDD-<subject words>-<uid>.eml`: sortable, unique, safe on any disk."""
    msg = email.message_from_bytes(data, policy=email.policy.default)
    try:
        day = parsedate_to_datetime(str(msg.get("Date", ""))).strftime("%y%m%d")
    except (TypeError, ValueError, IndexError):
        day = "000000"
    words = re.sub(r"[^a-z0-9]+", "-", str(msg.get("Subject", "") or "").lower()).strip("-")[:60].strip("-")
    return "%s-%s-%d.eml" % (day, words or "mail", uid)


def fetch(cfg: dict, imap_factory: Callable = imaplib.IMAP4_SSL, password: Optional[Callable[[], str]] = None,
          log: Callable[[str], None] = print) -> List[Path]:
    """Save every message in the mailbox not saved before. Returns the new files."""
    get_password = password or (lambda: keychain_password(cfg["keychain_service"], cfg["user"]))
    state_path: Path = cfg["state"]
    state = load_state(state_path)
    box = state.setdefault(cfg["mailbox"], {"uidvalidity": "", "uids": [], "message_ids": []})
    try:
        imap = imap_factory(cfg["server"], int(cfg["port"]))
    except (OSError, imaplib.IMAP4.error) as exc:
        raise FetchError("Could not reach %s: %s" % (cfg["server"], exc))
    saved: List[Path] = []
    try:
        try:
            typ, _ = imap.login(cfg["user"], get_password())
        except imaplib.IMAP4.error:
            raise FetchError("The server refused the login for %s." % cfg["user"])
        _ok(typ, "the login")
        typ, _ = imap.select(quote_mailbox(cfg["mailbox"]), readonly=not cfg["mark_read"])
        _ok(typ, "to open %s" % cfg["mailbox"])
        _, validity = imap.response("UIDVALIDITY")
        validity = (validity or [b""])[0]
        validity = validity.decode() if isinstance(validity, bytes) else str(validity or "")
        if box["uidvalidity"] != validity:
            box["uidvalidity"], box["uids"] = validity, []  # UIDs were renumbered; Message-IDs still guard
        seen, ids = set(box["uids"]), set(box["message_ids"])
        typ, data = imap.uid("SEARCH", None, cfg["search"])
        _ok(typ, "the search %s" % cfg["search"])
        uids = sorted(int(u) for u in (data[0] or b"").split())
        for uid in (u for u in uids if u not in seen):
            typ, data = imap.uid("FETCH", str(uid), "(BODY.PEEK[])")
            message = _message_bytes(data) if typ == "OK" else None
            if message is None:
                log("Skipped message %d: the server sent nothing to save." % uid)
                continue
            msg_id = str(email.message_from_bytes(message, policy=email.policy.default).get("Message-ID", "") or "").strip()
            if not (msg_id and msg_id in ids):
                dest = cfg["inbox"] / file_name(message, uid)
                tmp = dest.with_name("." + dest.name + ".part")  # hidden until whole
                tmp.write_bytes(message)
                os.replace(str(tmp), str(dest))
                saved.append(dest)
            if cfg["copy_to"]:
                _ok(imap.uid("COPY", str(uid), quote_mailbox(cfg["copy_to"]))[0], "to copy to %s" % cfg["copy_to"])
            if cfg["mark_read"]:
                _ok(imap.uid("STORE", str(uid), "+FLAGS", "(\\Seen)")[0], "to mark a message read")
            box["uids"].append(uid)
            if msg_id:
                box["message_ids"].append(msg_id)
                ids.add(msg_id)
            save_state(state_path, state)  # after each one, so an interrupted run never saves twice
    finally:
        try:
            imap.logout()
        except Exception:
            pass
    return saved


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Save new mail from one IMAP mailbox into one zone's Inbox. "
                                             "The password comes from the macOS Keychain.")
    ap.add_argument("--config", required=True, help="the JSON config file")
    args = ap.parse_args(argv)
    try:
        cfg = load_config(Path(args.config))
        saved = fetch(cfg)
    except FetchError as exc:
        print(exc, file=sys.stderr)
        return 1
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    print("%s: %d new message%s saved to %s" % (stamp, len(saved), "" if len(saved) == 1 else "s", cfg["inbox"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
