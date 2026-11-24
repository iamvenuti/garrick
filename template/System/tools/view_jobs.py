#!/usr/bin/env python3
"""view_jobs.py: what the scheduled jobs left on this Mac, as plain records (#650).

The App's Scheduled jobs card reads the jobs folder (a heartbeat, a log, a lock and a list of steps for each job) and the
launchd agents folder. Until 0.81.0 the page (`extras/status/status.py`) read each file for itself while it worked out
what each job's state is. This module is the one reader: it reads the same files, writes nothing, starts no process and
opens no socket, and `status.py` keeps only what a state means (late, idle, failed), how a row is worded and how it is drawn.

It is not part of `view.build()`. The jobs folder and the launch agents folder are this Mac's, never a workspace's, and a
document built for one zone must hold nothing from them. `view.jobs_reader()` is the way the page reaches it. Each reader
takes the folder it reads as its first argument, as the page's own functions did, and works nothing out more widely: it
follows no link and no `..` the page's reader did not.

A file that is missing or does not read gives the empty value of its shape (`{}`, `[]`, `None`, `False`), never an
exception and never a path or the text of an error. Standard library only; it never imports the jobs extra. The jobs
extra's own lock rule (`job.holder`) stays with the page, which has it loaded or not.

    AGENT   {"agent": true,                    # the plist calls the assistant (`--agent`)
             "env": {"GARRICK_ABOUT": "..."},  # its environment variables, as text or numbers
             "label": "garrick.brief", "about": "the line GARRICK_ABOUT gives" | "",
             "plist": "/Users/jo/Library/LaunchAgents/garrick.brief.plist",
             "mtime": 1763000000.0 | null,     # when the plist last changed
             "timing": {"StartCalendarInterval": [{"Hour": 6}]}}   # the keys the schedule is read from, as the plist gave them

    BEAT    {"name": "brief", "heartbeat": {...}}      # one heartbeat file, as job.py wrote it

    RUN     ["2026-11-20 05:00:00", 0, false]          # when it finished, its exit, whether it was a quiet exit

    LOCK    {"dir": true, "until": "1763000600 4242 1763000000" | null, "mtime": 1763000000.0 | null}
"""
from __future__ import annotations

import datetime as dt
import json
import os
import plistlib
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.dont_write_bytecode = True

API = 1
# job.py's end-of-run line; a quiet exit ends with "  quiet" before the rule.
LOGLINE = re.compile(r"^===== (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)  (\S+)  (?:exit (-?\d+)  \((\d+)s\)(  quiet)?|skipped)")
# Garrick's jobs by the names they ran under before #275 and #276, and the names they run under now (agent.py's RENAMED
# and RETIRED, kept here too so the page reads the jobs folder without the jobs extra; a test holds them equal).
RENAMED_JOBS = {"backup": "gr-backup", "nurture": "gr-nightly", "reading-sweep": "gr-reading-sweep",
                "todo-sweep": "gr-todo-sweep", "whats-open": "gr-whats-open"}
RETIRED_JOBS = {"status": "gr-nightly"}
RENAMED_FROM = "GARRICK_RENAMED_FROM"     # set in a renamed plist by update.py's commands: the old name
TIMING_KEYS = ("StartInterval", "StartCalendarInterval")


def _plain(value):
    """A plist value as JSON can hold it: text, numbers and booleans as they are, lists and dicts of them, else None."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    return None


def agents(folder: Path) -> Dict[str, dict]:
    """Job name -> AGENT, for each plist in `folder` that runs job.py: the job's own name is the word after job.py. A plist
    that does not read, or runs anything else, is passed over; two plists for one job leave the later one by file name."""
    out: Dict[str, dict] = {}
    try:
        if not folder.is_dir():
            return out
        plists = sorted(folder.glob("*.plist"))
    except OSError:
        return out
    for plist in plists:
        try:
            p = plistlib.loads(plist.read_bytes())
        except Exception:
            continue
        args = p.get("ProgramArguments") if isinstance(p, dict) else None
        if not isinstance(args, list):
            continue
        args = [str(a) for a in args]
        at = next((i for i, a in enumerate(args) if a.endswith("job.py")), None)
        if at is None or at + 1 >= len(args):
            continue
        flags = args[at + 2:]
        flags = flags[:flags.index("--")] if "--" in flags else flags
        env = p.get("EnvironmentVariables")
        env = env if isinstance(env, dict) else {}
        try:
            mtime: Optional[float] = plist.stat().st_mtime
        except OSError:
            mtime = None
        out[args[at + 1]] = {"agent": "--agent" in flags, "env": {str(k): _plain(v) for k, v in env.items()},
                             "label": str(p.get("Label") or plist.stem),
                             "about": env["GARRICK_ABOUT"].strip() if isinstance(env.get("GARRICK_ABOUT"), str) else "",
                             "plist": str(plist), "mtime": mtime,
                             "timing": {k: _plain(p[k]) for k in TIMING_KEYS if k in p}}
    return out


def heartbeat(folder: Path, name: str) -> dict:
    """The heartbeat `<name>.heartbeat.json`, or {} where there is none or it is not an object."""
    try:
        got = json.loads((folder / (name + ".heartbeat.json")).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def heartbeats(folder: Path) -> List[dict]:
    """Every heartbeat in `folder`, by file name: BEAT. A job's name is the one its heartbeat gives, else its file's."""
    out: List[dict] = []
    try:
        beats = sorted(folder.glob("*.heartbeat.json")) if folder.is_dir() else []
    except OSError:
        return out
    for beat in beats:
        try:
            hb = json.loads(beat.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(hb, dict):
            continue
        out.append({"name": hb.get("job") or beat.name[:-len(".heartbeat.json")], "heartbeat": hb})
    return out


def _finished(folder: Path, name: str) -> Optional[float]:
    hb = heartbeat(folder, name)
    if isinstance(hb.get("finished_ts"), (int, float)):
        return float(hb["finished_ts"])
    try:
        return dt.datetime.strptime(str(hb.get("finished"))[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S").timestamp()
    except ValueError:
        return None


def _first_run(folder: Path, name: str) -> Optional[float]:
    """When the job first ran, as far as its logs and heartbeat go back."""
    hb = heartbeat(folder, name)
    seen = [float(hb["renamed_at"])] if isinstance(hb.get("renamed_at"), (int, float)) else []
    if _finished(folder, name) is not None:
        seen.append(_finished(folder, name))
    for path in (folder / (name + ".log.1"), folder / (name + ".log")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        m = next((LOGLINE.match(line) for line in text.splitlines() if LOGLINE.match(line)), None)
        if m:
            seen.append(dt.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").timestamp())
    return min(seen) if seen else None


def superseded(folder: Path, sched: Dict[str, dict]) -> Tuple[Dict[str, List[Tuple[str, float]]], set]:
    """Garrick's jobs that run under a new name now (#275): new name -> [(old name, cutoff)], the old names whose runs from
    before `cutoff` (epoch seconds) are read under the new one, and the old names no longer shown as a row of their own.
    `sched` is `agents()`, by job name, for the plists that exist.

    Only what is Garrick's moves. The old name is folded in only when the new name's plist carries GARRICK_RENAMED_FROM
    naming it, which update.py's commands write into a plist it found running Garrick's own script under that name, or when
    a run under the new name recorded it (job.py's `renamed_from`), and only while no plist runs the old name. The cutoff is
    the first run under the new name (`renamed_at`), or before it the renamed plist's last change: a run under the old name
    after it is not Garrick's, and the old name keeps a row of its own while it has one. The retired evening build,
    `status`, is hidden once the nightly is there (a plist or a heartbeat), no plist runs `status`, and no `status` run has
    finished since the nightly's first run; its runs are never the nightly's. Nothing outside the jobs folder decides it,
    so deleting the plist set aside as .retired changes nothing."""
    earlier: Dict[str, List[Tuple[str, float]]] = {}
    hidden = set()
    for old, new in RENAMED_JOBS.items():
        if old in sched:
            continue
        hb = heartbeat(folder, new)
        plist = sched.get(new) or {}
        cutoff = None
        if hb.get("renamed_from") == old and isinstance(hb.get("renamed_at"), (int, float)):
            cutoff = float(hb["renamed_at"])
        elif (plist.get("env") or {}).get(RENAMED_FROM) == old and plist.get("plist"):
            try:
                cutoff = Path(plist["plist"]).stat().st_mtime
            except OSError:
                cutoff = None
        if cutoff is None:
            continue
        earlier.setdefault(new, []).append((old, cutoff))
        last = _finished(folder, old)
        if last is None or last < cutoff:
            hidden.add(old)
    for old, new in RETIRED_JOBS.items():
        if old in sched or not (new in sched or (folder / (new + ".heartbeat.json")).is_file()):
            continue
        first, last = _first_run(folder, new), _finished(folder, old)
        if first is None or last is None or last < first:
            hidden.add(old)
    return earlier, hidden


def runs(folder: Path, name: str, since: str, earlier: Tuple[Tuple[str, float], ...] = ()) -> List[list]:
    """RUN for each run the job's logs record from `since` on (a local time, as `isoformat()` writes it), and those the logs of
    the names it ran under before record from before each one's cutoff (`superseded()`)."""
    start = dt.datetime.fromisoformat(since)
    found = []
    for n, cutoff in (*earlier, (name, None)):
        for path in (folder / (n + ".log.1"), folder / (n + ".log")):
            try:
                if not path.is_file():
                    continue
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for line in lines:
                m = LOGLINE.match(line)
                if not m:
                    continue
                when = dt.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
                if when >= start and (cutoff is None or when.timestamp() < cutoff):
                    found.append([m.group(1), int(m.group(3)) if m.group(3) else 75, bool(m.group(5))])
    return found


def steps_now(folder: Path, name: str) -> Optional[List[dict]]:
    """The steps a run still going has reported so far (job.py's `<name>.steps.json`, which the nightly job writes after each
    step), or None."""
    try:
        data = json.loads((folder / (name + ".steps.json")).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return [x for x in data if isinstance(x, dict)] if isinstance(data, list) else None


def lock(path: Path) -> dict:
    """LOCK for the job's lock folder: whether it is a folder, the record `until` it holds ("<until> <pid> [<started>]"),
    and when the folder last changed. What a lock means is the page's to say."""
    out = {"dir": False, "until": None, "mtime": None}
    try:
        if not path.is_dir():
            return out
        out["dir"] = True
    except OSError:
        return out
    try:
        out["until"] = (path / "until").read_text(encoding="utf-8")
    except (OSError, ValueError):
        pass
    try:
        out["mtime"] = path.stat().st_mtime
    except OSError:
        pass
    return out


def log_name(folder: Path, name: str, earlier: Tuple[Tuple[str, float], ...] = ()) -> str:
    """The file name of the job's log; before a renamed job's first run under its new name, the log it left under the newest
    of its old ones."""
    for n in (name, *(o for o, _ in reversed(earlier))):
        if (folder / (n + ".log")).is_file():
            return n + ".log"
    return name + ".log"


def log_tail(path: Path, lines: int = 30, width: int = 300) -> List[str]:
    """The last lines of a job's log, read from its end, each cut to `width` characters; none when there is no log. A read
    that starts mid-file drops its first line, which is likely a part of one."""
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            start = max(0, f.tell() - 64 * 1024)
            f.seek(start)
            text = f.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    got = text.splitlines()[1 if start else 0:]
    return [line[:width] for line in got[-lines:]]
