#!/usr/bin/env python3
"""engine_cmd.py: the only commands an Act session runs, each checked against the zone the exchange is bound to (#571).

    GARRICK_ENGINE_WS=<workspace> GARRICK_ENGINE_ZONE=<zone> python3 engine_cmd.py <tool> <sub> [arguments]

`tool` is `git`, `intake`, `scaffold`, `check` or `todo`. A permission pattern such as `Bash(git commit:*)` takes any
argument, and an argument can name another zone, a file anywhere, or a flag that skips a hook. So the session is given
no pattern for those tools: it is given this script, which checks every argument and then runs the real command.
It fails closed: a flag it does not list, a path that does not resolve inside the zone's place, or a failure to
judge, refuses the command (exit 2) and runs nothing.

What stays, and how each is bound:

- `git add|commit|status|diff|log`, in the zone's repository only. `add` takes paths inside it and no flag. `commit`
  takes `-m` or `--message` and `-q`: no `-a`, `-n`, `--no-verify`, `--amend`, `-F`, `-c` or `--author`, so the hook
  runs and only what was added is committed. `status`, `diff` and `log` take a list of read flags and paths or
  revisions; none writes (`--output`, `--no-index` and `--ext-diff` are not listed).
- `intake` file, project and zone arguments must resolve inside the zone (its `Inbox/`, `Zones/<zone>/`). `list` and
  `process-notes` are not offered: the first returns every zone's inbox, the second runs the job's own pass.
  `learn` is not offered. An item in the workspace's own `Inbox/` can be read (`parse`) or moved into the zone
  (`move-to-zone`), not filed from.
- `scaffold project|thread|checkpoint` take the zone only as the exchange's own.
- `check --quick` and `todo digest --zone <the zone>`.

Standard library only, Python 3.9 or later.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

sys.dont_write_bytecode = True

TOOLS = ("git", "intake", "scaffold", "check", "todo")
GIT_SUBS = ("add", "commit", "status", "diff", "log")
INTAKE_SUBS = ("parse", "file-conversation", "file-reading", "file-to-project", "extract-attachment", "move-to-zone", "skip",
               "file-note", "notes")
SCAFFOLD_SUBS = ("project", "thread", "checkpoint")

# flag -> kind. "flag" takes no value; "value" is free text; "file", "project" and "zone" are bound to the exchange.
SPECS: Dict[str, Dict[str, str]] = {
    "intake parse": {"--file": "file"},
    "intake file-conversation": {"--file": "file", "--parties": "value", "--title": "value", "--date": "value"},
    "intake file-reading": {"--file": "file", "--title": "value", "--slug": "value", "--kind": "value"},
    "intake file-to-project": {"--file": "file", "--project": "project", "--parties": "value", "--name": "name",
                               "--as-material": "flag"},
    "intake extract-attachment": {"--mail": "value", "--project": "project", "--name": "value", "--index": "value",
                                  "--save-as": "value"},
    "intake move-to-zone": {"--file": "file", "--zone": "zone"},
    "intake skip": {"--file": "file", "--reason": "value"},
    "intake file-note": {"--file": "file", "--destination": "value", "--title": "value"},
    "intake notes": {"--project": "project", "--thread": "name"},
    "scaffold project": {"--zone": "zone", "--name": "name", "--party": "name", "--thread": "name", "--spoken": "value",
                         "--thread-spoken": "value"},
    "scaffold thread": {"--zone": "zone", "--project": "name", "--name": "name", "--spoken": "value", "--touched": "flag"},
    "scaffold checkpoint": {"--json": "json"},
    "check": {"--quick": "flag"},
    "todo digest": {"--zone": "zone", "--json": "flag", "--count": "value"},
}
# Where a `--file` may sit, by subcommand: the zone's own Inbox, and for a few the workspace's.
WS_INBOX_OK = ("intake parse", "intake move-to-zone")
# git flags that stand alone, by subcommand. `-n <N>`, `-<N>`, `-U<N>`, `--max-count=`, `--since=`, `--until=`,
# `--author=`, `--grep=`, `--format=` and `--pretty=` are read by pattern below, for log and diff where they apply.
GIT_FLAGS = {
    "status": {"-s", "--short", "-b", "--branch", "--porcelain", "--porcelain=v1", "--porcelain=v2", "-uno", "-unormal",
               "-uall", "--untracked-files=no", "--untracked-files=normal", "--untracked-files=all"},
    "diff": {"--stat", "--shortstat", "--numstat", "--name-only", "--name-status", "--cached", "--staged", "-p", "--patch",
             "--no-color", "--color=never", "-w", "--ignore-all-space", "--summary"},
    "log": {"--oneline", "--stat", "--name-only", "--name-status", "-p", "--patch", "--no-color", "--color=never", "--graph",
            "--decorate", "--all", "--reverse", "--summary"},
    "add": set(),
    "commit": {"-q", "--quiet"},
}
GIT_PATTERNS = {
    "diff": (re.compile(r"-U\d{1,3}$"),),
    "log": (re.compile(r"-\d{1,4}$"), re.compile(r"--max-count=\d{1,4}$"), re.compile(r"--(?:since|until|author|grep)=[^\n]{1,200}$"),
            re.compile(r"--(?:format|pretty)=[^\n]{1,200}$"), re.compile(r"-U\d{1,3}$")),
}


class Refused(Exception):
    pass


def real(path: str) -> str:
    return os.path.realpath(os.path.expanduser(path))


def inside(path: str, folder: str) -> bool:
    a, b = path.casefold(), folder.casefold().rstrip(os.sep)
    return a == b or a.startswith(b + os.sep)


def git_part(path: str) -> bool:
    return ".git" in [p.casefold() for p in re.split(r"[\\/]", path) if p]


class Bound:
    """The workspace and the zone the exchange is bound to."""

    def __init__(self, ws: str, zone: str):
        if not ws or not zone or "/" in zone or zone.startswith("."):
            raise Refused("this command runs only inside an exchange bound to a zone")
        self.ws = real(ws)
        self.zone = zone
        self.home = os.path.join(self.ws, "Zones", zone)
        if not os.path.isdir(os.path.join(self.home)):
            raise Refused("the zone is not there")
        self.home = real(self.home)

    def file(self, value: str, where_ws_inbox: bool) -> str:
        path = real(value if os.path.isabs(value) else os.path.join(self.ws, value))
        places = [os.path.join(self.home, "Inbox")]
        if where_ws_inbox:
            places.append(os.path.join(self.ws, "Inbox"))
        if not any(inside(path, p) and path.casefold() != p.casefold() for p in places) or git_part(path):
            raise Refused("a file is read from this zone's Inbox only (%s)" % self.zone)
        return path

    def project(self, value: str) -> str:
        """`Zones/<zone>/<Project>` as intake takes it, or the project's name inside the zone; refused anywhere else."""
        text = value.strip()
        if os.path.isabs(text):
            path = real(text)
        elif text.split("/")[0] == "Zones":
            path = real(os.path.join(self.ws, text))
        else:
            path = real(os.path.join(self.home, text))
        if not inside(path, self.home) or path.casefold() == self.home.casefold() or git_part(path):
            raise Refused("a project is named inside the %s zone only" % self.zone)
        return os.path.relpath(path, self.ws)

    def zone_arg(self, value: str) -> str:
        if value.strip().casefold() != self.zone.casefold():
            raise Refused("this exchange is bound to the %s zone, not %s" % (self.zone, value.strip()))
        return self.zone


def parse_flags(spec: Dict[str, str], args: List[str], bound: Bound, key: str) -> List[str]:
    out, i = [], 0
    seen = set()
    while i < len(args):
        tok = args[i]
        if not tok.startswith("--"):
            raise Refused("unexpected argument %r" % tok[:40])
        flag, eq, value = tok.partition("=")
        kind = spec.get(flag)
        if kind is None or flag in seen:
            raise Refused("the flag %s is not offered here" % flag[:40])
        seen.add(flag)
        i += 1
        if kind == "flag":
            if eq:
                raise Refused("%s takes no value" % flag)
            out.append(flag)
            continue
        if not eq:
            if i >= len(args):
                raise Refused("%s needs a value" % flag)
            value, i = args[i], i + 1
        if kind == "file":
            value = bound.file(value, key in WS_INBOX_OK)
        elif kind == "project":
            value = bound.project(value)
        elif kind == "zone":
            value = bound.zone_arg(value)
        elif kind == "name":                          # a project named inside the zone: scaffold looks it up there
            if "/" in value or "\\" in value or value.startswith(".") or not value.strip():
                raise Refused("%s takes a name, not a path" % flag)
        elif kind == "json":
            try:
                req = json.loads(value)
            except ValueError:
                raise Refused("the checkpoint request is not JSON")
            if not isinstance(req, dict) or str(req.get("zone") or "").casefold() != bound.zone.casefold():
                raise Refused("a checkpoint is written in the exchange's own zone (%s)" % bound.zone)
        out += [flag, value]
    required = {"intake file-to-project": ("--file", "--project"), "scaffold project": ("--zone",), "scaffold thread": ("--zone",),
                "intake move-to-zone": ("--file", "--zone"), "todo digest": ("--zone",)}.get(key, ())
    missing = [f for f in required if f not in seen]
    if missing:
        raise Refused("%s must be given" % ", ".join(missing))
    return out


def git_path(tok: str, repo: str) -> str:
    if tok.startswith(":") or tok.startswith("-"):
        raise Refused("a pathspec with magic is not offered")
    if tok.startswith("/") or tok.startswith("~"):
        if not inside(real(tok), repo):
            raise Refused("a path is inside the zone's repository only")
    elif tok.startswith("..") or "/../" in tok or tok.endswith("/..") or "\\" in tok:
        raise Refused("a path is inside the zone's repository only")
    if git_part(tok) or git_part(real(os.path.join(repo, tok))):
        raise Refused("the .git folder is not for a session")
    return tok


def git_args(sub: str, args: List[str], repo: str) -> List[str]:
    flags, pats = GIT_FLAGS[sub], GIT_PATTERNS.get(sub, ())
    out, i, rest, messages = [], 0, False, 0
    while i < len(args):
        tok = args[i]
        i += 1
        if rest or not tok.startswith("-"):
            out.append(git_path(tok, repo))
            continue
        if tok == "--":
            rest = True
            out.append(tok)
        elif tok in flags or any(p.match(tok) for p in pats):
            out.append(tok)
        elif sub == "commit" and (tok == "-m" or tok.startswith("--message=")):
            if tok == "-m":
                if i >= len(args):
                    raise Refused("-m needs a message")
                msg, i = args[i], i + 1
                out += ["-m", msg]
            else:
                out.append(tok)
                msg = tok.partition("=")[2]
            if not msg.strip():
                raise Refused("a commit needs a message")
            messages += 1
        elif sub == "log" and tok in ("-n", "--max-count"):
            if i >= len(args) or not re.match(r"\d{1,4}$", args[i]):
                raise Refused("%s needs a number" % tok)
            out += [tok, args[i]]
            i += 1
        else:
            raise Refused("the flag %s is not offered for git %s" % (tok[:40], sub))
    if sub == "commit" and not messages:
        raise Refused("a commit needs a message (-m)")
    if sub == "add" and not [o for o in out if o != "--"]:
        raise Refused("name the files to add: no -A, no .")
    if sub == "add" and any(o in (".", "./", "*") for o in out):
        raise Refused("name the files to add: no -A, no .")
    return out


def script(ws: str, tool: str) -> str:
    return {"intake": os.path.join(ws, "System", "skills", "intake", "intake.py"),
            "scaffold": os.path.join(ws, "System", "tools", "scaffold.py"),
            "check": os.path.join(ws, "System", "tools", "check.py"),
            "todo": os.path.join(ws, "System", "skills", "todo", "todo.py")}[tool]


def plan(argv: List[str], ws: str, zone: str) -> tuple:
    """(the command to run, the text for its stdin or None). Raises Refused."""
    if len(argv) < 1 or argv[0] not in TOOLS:
        raise Refused("tools are %s" % ", ".join(TOOLS))
    bound = Bound(ws, zone)
    tool, rest = argv[0], argv[1:]
    if tool == "check":
        return [sys.executable, script(bound.ws, "check")] + parse_flags(SPECS["check"], rest, bound, "check"), None
    if not rest:
        raise Refused("name a subcommand")
    sub, args = rest[0], rest[1:]
    if tool == "git":
        if sub not in GIT_SUBS:
            raise Refused("git %s is not offered" % sub[:30])
        return (["git", "-C", bound.home, "--no-pager"] + [sub] + (["--no-ext-diff", "--no-textconv"] if sub in ("diff", "log") else [])
                + git_args(sub, args, bound.home)), None
    allowed = {"intake": INTAKE_SUBS, "scaffold": SCAFFOLD_SUBS, "todo": ("digest",)}[tool]
    if sub not in allowed:
        raise Refused("%s %s is not offered here" % (tool, sub[:30]))
    key = "%s %s" % (tool, sub)
    got = parse_flags(SPECS[key], args, bound, key)
    stdin = None
    if key == "scaffold checkpoint":
        stdin, got = got[1], []
    return [sys.executable, script(bound.ws, tool), sub] + got, stdin


def clean_env() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_TERMINAL_PROMPT="0", GIT_PAGER="cat")
    return env


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        cmd, stdin = plan(argv, os.environ.get("GARRICK_ENGINE_WS", ""), os.environ.get("GARRICK_ENGINE_ZONE", ""))
    except Refused as e:
        print("Refused: %s" % e, file=sys.stderr)
        return 2
    except BaseException:
        print("Refused: the engine could not judge this command.", file=sys.stderr)
        return 2
    run = subprocess.run(cmd, input=stdin, text=True if stdin is not None else None, env=clean_env())
    return run.returncode


def prefix(tool: str, sub: str = "") -> str:
    """The permission pattern's text for a command of this script, as a session would type it."""
    here = shlex.quote(str(Path(__file__).resolve()))
    return ("python3 %s %s %s" % (here, tool, sub)).rstrip()


if __name__ == "__main__":
    sys.exit(main())
