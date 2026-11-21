#!/usr/bin/env python3
"""The role of this machine: `solo`, `server` or `roaming`.

    python3 System/tools/machine.py            say the role, one line
    python3 System/tools/machine.py --json     the whole record, for a program
    python3 System/tools/machine.py set --role roaming --name laptop --server mini [--workspace PATH]

A workspace that lives on one machine needs none of this: with no file the role
is `solo`, and nothing changes. A workspace on more than one machine (a server
that holds it and runs the sessions and the jobs, and a laptop that keeps a
copy) says which machine is which in one small file outside the workspace,
`~/.config/garrick/machine.json`:

    {"role": "roaming", "name": "laptop", "server": "mini", "workspace": "/Users/jo/Garrick"}

`peers` may list the names of the other machines that sync with this one, so that a conflict copy a shared library
names after a machine is known (`Plan-laptop.docx`). `workspace` is where the workspace sits on this machine.

The file is outside the workspace on purpose: the workspace is what a sync tool
copies to the other machine, and the role belongs to the machine. The
zone guard refuses a file-editing tool's write to it, a guard against a mistaken edit and no lock (a shell
command can still change the file); the person runs `set` themselves.

A missing file, one that cannot be read, or a role this file does not know all
mean `solo`. Everything else calls `role()`, which reads HOME when it is called,
so a test points it at a temporary folder. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, Optional

sys.dont_write_bytecode = True

ROLES = ("solo", "server", "roaming")
SOLO = "solo"
FILE = "machine.json"
FIELDS = ("role", "name", "server", "workspace")


def folder() -> Path:
    """~/.config/garrick, with HOME read now."""
    home = os.environ.get("HOME") or os.path.expanduser("~")
    return Path(home) / ".config" / "garrick"


def path() -> Path:
    return folder() / FILE


def read() -> Dict[str, object]:
    """The record: the four fields as text, the role always one of ROLES, and `peers`, a list of names."""
    out: Dict[str, object] = {"role": SOLO, "name": "", "server": "", "workspace": "", "peers": []}
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return out
    if not isinstance(data, dict):
        return out
    for key in FIELDS[1:]:
        value = data.get(key)
        if isinstance(value, str):
            out[key] = value.strip()
    peers = data.get("peers")
    if isinstance(peers, list):
        out["peers"] = [p.strip() for p in peers if isinstance(p, str) and p.strip()]
    role = data.get("role")
    out["role"] = role.strip().lower() if isinstance(role, str) and role.strip().lower() in ROLES else SOLO
    return out


def role() -> str:
    return read()["role"]


def name() -> str:
    return read()["name"]


def is_roaming() -> bool:
    return role() == "roaming"


def is_server() -> bool:
    return role() == "server"


def known_names() -> set:
    """The machine names the file knows: this machine's, its server's and its peers', lower case."""
    rec = read()
    return {n.casefold() for n in [rec["name"], rec["server"]] + list(rec["peers"]) if n}


def write(role_: str, name_: str = "", server_: str = "", workspace_: str = "", peers_=()) -> Path:
    if role_ not in ROLES:
        raise ValueError("The role is solo, server or roaming.")
    record = {"role": role_}
    for key, value in (("name", name_), ("server", server_), ("workspace", workspace_)):
        if value:
            record[key] = value
    if peers_:
        record["peers"] = list(peers_)
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    os.replace(str(tmp), str(target))
    return target


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Say or set this machine's role.")
    sub = parser.add_subparsers(dest="command")
    parser.add_argument("--json", action="store_true", help="the whole record, for a program")
    setter = sub.add_parser("set", help="write ~/.config/garrick/machine.json")
    setter.add_argument("--role", required=True, choices=ROLES)
    setter.add_argument("--name", default="", help="this machine's name, such as laptop")
    setter.add_argument("--server", default="", help="the server's name, such as mini")
    setter.add_argument("--peer", action="append", default=[], help="another machine that syncs with this one (repeat for more)")
    setter.add_argument("--workspace", default="", help="the workspace's absolute path on this machine")
    args = parser.parse_args(argv)
    if args.command == "set":
        target = write(args.role, args.name.strip(), args.server.strip(), args.workspace.strip(),
                       [p.strip() for p in args.peer if p.strip()])
        print("Wrote the role %s to %s." % (args.role, target))
        return 0
    rec = read()
    if args.json:
        print(json.dumps(rec))
    else:
        print(rec["role"] + (" (%s)" % rec["name"] if rec["name"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
