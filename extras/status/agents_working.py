#!/usr/bin/env python3
"""Which assistant sessions are working, idle or waiting on you, right now.
Garrick.app's *Keep awake › While an agent is working* runs this once a minute,
and the Overview's *Waiting on you now* card and the menu bar's count read the
same minute's result.

    python3 agents_working.py [--verbose]
    python3 agents_working.py --json [--workspace PATH [--notify]]

Exit 0 when at least one session is working, 1 when none is, 2 when it cannot
tell (no transcript folder can be read). It reads the transcripts Claude Code
and Codex write, never a socket or a model: Claude Code's in
~/.claude/projects/*/*.jsonl, Codex's in ~/.codex/sessions/**/*.jsonl. Only a
transcript written in the last 30 minutes counts, so a session that crashed
mid-turn stops counting; a single tool call that runs longer than that without
a word lets the Mac sleep. Each one is read from its last 256 KB: Claude Code's
turn is over once a turn_duration or local_command record follows the last
prompt or tool result, Codex's once task_complete or turn_aborted follows
task_started. --verbose prints each recent transcript's state.

A session is *waiting* when it has stopped on something only you can answer:

- Claude Code: its last record is a tool call to AskUserQuestion or
  ExitPlanMode with no result after it; or a permission prompt is open. The
  transcript does not record a permission prompt, so the Notification hook in
  extras/hooks/waiting_hook.py writes a small marker per session under
  ~/.garrick-waiting/ (kinds permission_prompt and idle_prompt), and the next
  prompt or tool result clears it. Only a permission_prompt makes a session
  wait; an idle_prompt is kept as the kind and the session stays idle.
- Codex: its rollout records an approval request (an event_msg whose type ends
  in `_approval_request`) with nothing after it. A Codex version that writes no
  such record shows its sessions as working or idle only.

--json prints one row per recent session: id, agent, folder, state (working,
idle, waiting or ?), what it waits for ("a question" or "an approval for
Bash") and since when, and with --workspace the thread the folder belongs to.
For a waiting session `where` says what it runs in: `cmux` (a tab the cmux
extra can bring forward), `desktop` (Claude's desktop app, which has no
documented way to bring one session forward) or `terminal` (any other).
It never carries the text of a question, a prompt or a message: a question can
name anything, so only the tool's name is read from the record. With --notify
(and --workspace) the waiting sessions are also handed to the workspace's
System/tools/notifications.py, which tells each wait once.
"""
import datetime
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

RECENT = 30 * 60
TAIL = 256 * 1024
MARKERS = ".garrick-waiting"                  # under the home folder, outside every workspace
MARKER_LIFE = 24 * 60 * 60
ASKING = {"AskUserQuestion": "a question", "ExitPlanMode": "an approval for the plan"}
SAFE = re.compile(r"[^A-Za-z0-9_.:-]")


def records(path: Path) -> Iterator[dict]:
    """The JSON records at the end of a transcript; a line cut by the tail is skipped."""
    with path.open("rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - TAIL))
        lines = f.read().split(b"\n")
    for line in lines[1:] if size > TAIL else lines:
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict):
            yield d


def tool_word(name: object) -> str:
    """A tool's name made safe to say: letters, digits and a few marks, 40 at most."""
    return SAFE.sub("", str(name or ""))[:40]


def read(path: Path) -> dict:
    """What the transcript says: state (working, idle, waiting or ?), what it
    waits for, since when (an ISO time or ""), and the session's folder. Only
    the names of tools are taken from a record, never their input."""
    found, waits, since, folder, entry = "?", "", "", "", ""
    asked: Dict[str, Tuple[str, str]] = {}                           # tool_use id -> (what it waits for, when)
    codex: Optional[Tuple[str, str]] = None                          # an approval request not yet answered
    for d in records(path):
        kind = d.get("type")
        if isinstance(d.get("cwd"), str) and d["cwd"]:
            folder = d["cwd"]
        if isinstance(d.get("entrypoint"), str):
            entry = d["entrypoint"]
        if kind == "event_msg":                                       # Codex
            payload = d.get("payload") if isinstance(d.get("payload"), dict) else {}
            event = payload.get("type") if isinstance(payload.get("type"), str) else None
            if event == "task_started":
                found, codex = "working", None
            elif event in ("task_complete", "turn_aborted"):
                found, codex = "idle", None
            elif event and event.endswith("_approval_request"):
                what = "Bash" if event.startswith("exec") else "apply_patch" if "patch" in event else "a tool"
                codex = ("an approval for %s" % what, str(d.get("timestamp") or ""))
            elif event and event != "token_count":
                codex = None                                          # anything after the request answers it
        elif kind == "turn_context" and isinstance(d.get("payload"), dict):
            if isinstance(d["payload"].get("cwd"), str) and d["payload"]["cwd"]:
                folder = d["payload"]["cwd"]
        elif kind == "assistant":                                     # Claude Code: a tool call
            content = (d.get("message") or {}).get("content")
            for x in content if isinstance(content, list) else []:
                if isinstance(x, dict) and x.get("type") == "tool_use" and x.get("name") in ASKING:
                    asked[str(x.get("id") or "")] = (ASKING[x["name"]], str(d.get("timestamp") or ""))
        elif kind == "user" and not d.get("isMeta"):                  # Claude Code: a prompt or a tool result
            content = (d.get("message") or {}).get("content")
            parts = [x for x in content if isinstance(x, dict)] if isinstance(content, list) else []
            for x in parts:
                if x.get("type") == "tool_result":
                    asked.pop(str(x.get("tool_use_id") or ""), None)
            text = content if isinstance(content, str) else " ".join(
                x.get("text", "") for x in parts if isinstance(x.get("text", ""), str))
            found = "idle" if "[Request interrupted" in text else "working"
            if isinstance(content, str) or any(x.get("type") != "tool_result" for x in parts):
                asked.clear()                                         # a new prompt: nothing is open
        elif kind == "system" and d.get("subtype") in ("turn_duration", "local_command"):
            found = "idle"
            asked.clear()
    if codex and found == "working":
        found, waits, since = "waiting", codex[0], codex[1]
    elif asked and found == "working":
        waits, since = list(asked.values())[-1]
        found = "waiting"
    return {"state": found, "waits": waits, "since": since, "folder": folder, "desktop": "desktop" in entry}


def state(path: Path) -> str:
    """working, idle, waiting, or ? when the transcript says none of them."""
    return read(path)["state"]


def recent(home: Path, now: Optional[float] = None) -> Optional[List[Path]]:
    """Transcripts written in the last RECENT seconds, or None when neither folder exists."""
    now = time.time() if now is None else now
    folders = [(home / ".claude" / "projects", "*/*.jsonl"), (home / ".codex" / "sessions", "**/*.jsonl")]
    if not any(folder.is_dir() for folder, _ in folders):
        return None
    out = []
    for folder, pattern in folders:
        for path in folder.glob(pattern) if folder.is_dir() else []:
            try:
                if now - path.stat().st_mtime <= RECENT:
                    out.append(path)
            except OSError:
                continue
    return out


def marker_for(home: Path, session: str) -> Optional[dict]:
    """The hook's marker for a session: {kind, tool, since (epoch seconds)}, or None."""
    safe = SAFE.sub("", session)
    if not safe or safe != session:
        return None
    try:
        m = json.loads((home / MARKERS / (safe + ".json")).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(m, dict) or not isinstance(m.get("since"), (int, float)) or isinstance(m.get("since"), bool):
        return None
    return {"kind": str(m.get("kind") or ""), "tool": tool_word(m.get("tool")), "since": float(m["since"])}


def iso(epoch: float) -> str:
    return datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sessions(home: Path, now: Optional[float] = None) -> Optional[List[dict]]:
    """One row per recent session: id, agent, folder, state, waits, since (ISO).
    None when no transcript folder exists."""
    now = time.time() if now is None else now
    paths = recent(home, now)
    if paths is None:
        return None
    rows = []
    for path in paths:
        try:
            got = read(path)
            mtime = path.stat().st_mtime
        except OSError:
            continue
        agent = "codex" if ".codex" in path.parts else "claude"
        row = {"id": path.stem, "agent": agent, "folder": got["folder"], "state": got["state"],
               "waits": got["waits"], "since": got["since"], "desktop": got["desktop"]}
        if agent == "claude":
            mark = marker_for(home, path.stem)
            # The transcript is written again once a tool's answer comes back, so a later record clears the marker.
            if mark and mark["kind"] == "permission_prompt" and now - mark["since"] < MARKER_LIFE \
                    and mtime <= mark["since"] + 2:
                row.update(state="waiting", waits="an approval for %s" % (mark["tool"] or "a tool"),
                           since=iso(mark["since"]))
        if row["state"] == "waiting" and not row["since"]:
            row["since"] = iso(mtime)
        rows.append(row)
    return rows


def thread_of(folder: str, workspace: Optional[Path]) -> str:
    """The thread (or project) a folder belongs to, as "Project, Thread" or
    "Project"; the folder's own name when it is neither."""
    if not folder:
        return ""
    try:
        if workspace is not None:
            parts = Path(folder).resolve().relative_to((Path(workspace) / "Zones").resolve()).parts
            if len(parts) >= 4 and parts[2] == "Threads":
                return "%s, %s" % (parts[1], parts[3])
            if len(parts) >= 2:
                return parts[1]
    except (OSError, ValueError):
        pass
    return Path(folder).name or folder


def cmux_sessions(extra: Optional[Path] = None) -> set:
    """The ids of the sessions cmux runs in a tab, from the cmux extra beside
    this folder; empty without the extra or cmux, or when cmux does not answer."""
    try:
        import importlib.util
        lib = (extra or Path(__file__).resolve().parent.parent / "cmux") / "cmuxlib.py"
        if not lib.is_file():
            return set()
        spec = importlib.util.spec_from_file_location("garrick_cmuxlib_waiting", str(lib))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return {s["session_id"] for s in mod.roster(running_only=True, titles={}, timeout=3)
                if s.get("session_id") and s.get("surface")}
    except Exception:
        return set()


def check(home: Path, now: Optional[float] = None) -> Tuple[int, List[Tuple[str, Path]]]:
    paths = recent(home, now)
    if paths is None:
        return 2, []
    seen = []
    for path in paths:
        try:
            seen.append((state(path), path))
        except OSError:
            continue
    return (0 if any(s == "working" for s, _ in seen) else 1), seen


def rows_json(home: Path, workspace: Optional[Path] = None, now: Optional[float] = None,
              in_cmux: Optional[set] = None) -> List[dict]:
    """What --json prints: the sessions, the waiting ones first, longest waiting first.
    `in_cmux` is the ids of the sessions cmux runs, asked for only when one waits."""
    found = sessions(home, now) or []
    if in_cmux is None:
        in_cmux = cmux_sessions() if any(r["state"] == "waiting" for r in found) else set()
    out = []
    for r in found:
        where = "cmux" if r["id"] in in_cmux else "desktop" if r["desktop"] else "terminal"
        out.append({"id": r["id"], "agent": r["agent"], "folder": r["folder"],
                    "thread": thread_of(r["folder"], workspace), "state": r["state"],
                    "waiting_for": r["waits"], "since": r["since"], "where": where if r["state"] == "waiting" else ""})
    order = {"waiting": 0, "working": 1, "idle": 2}
    return sorted(out, key=lambda r: (order.get(r["state"], 3), r["since"] if r["state"] == "waiting" else "", r["id"]))


def main(argv: List[str]) -> int:
    home = Path(os.environ.get("GARRICK_HOME") or Path.home())
    if "--json" in argv:
        ws = None
        if "--workspace" in argv and argv.index("--workspace") + 1 < len(argv):
            ws = Path(argv[argv.index("--workspace") + 1])
        paths = recent(home)
        data = json.dumps({"ok": paths is not None, "sessions": rows_json(home, ws)}, indent=1)
        print(data)
        if "--notify" in argv and ws is not None:
            notifier = ws / "System" / "tools" / "notifications.py"
            if notifier.is_file():
                try:
                    subprocess.run([sys.executable, str(notifier), "waiting", "--root", str(ws)], input=data,
                                   text=True, capture_output=True, timeout=30)
                except (OSError, subprocess.SubprocessError):
                    pass
        return 2 if paths is None else 0
    code, seen = check(home)
    if "--verbose" in argv:
        if code == 2:
            print("cannot tell: no Claude Code or Codex transcripts on this Mac")
        for s, path in seen:
            print("%-8s %s" % (s, path))
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
