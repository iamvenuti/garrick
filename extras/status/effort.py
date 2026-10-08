#!/usr/bin/env python3
"""Where the assistant's time and tokens went, thread by thread. Part of the status page.

    python3 effort.py [--workspace FOLDER] [--record] [--store FILE] [--also FOLDER ...] [--moved OLD=NEW ...] [--days N]

Claude Code keeps one transcript per session under ~/.claude/projects/, and
every assistant message in it carries its token usage, a timestamp and the
folder the session ran in. This reads them, with no model call, and adds up
each thread's active time and list-price cost by day.

**Which thread a session belongs to.** The folder it ran in gives the zone and
the project, since "open X" starts each session in its project folder; a
session started in a thread's own folder gives the thread too. Otherwise the
thread is the one whose `Threads/<X>/` files the session wrote or edited most.
A project that has no thread notes is its own thread. Whatever is left is the
project's *unassigned* share, never a guess. A session started above the
zones is placed by the files it wrote, and stays outside the zones when it
wrote none. A folder renamed or moved since (`--moved`, a project renamed, a
wiki moved) counts under its new name, and a folder the whole workspace used
to live in (`--also`) counts as the workspace.

**What is counted.** Interactive sessions only: a headless run (`claude -p`,
which is how the jobs extra calls the assistant) is already in the jobs
ledger, so it is left out here. A session's subagents count towards it.
Active time is the sum of the gaps between its messages, with any gap over
five minutes counted as idle. Cost is the list-price equivalent of the tokens,
the measure the jobs ledger uses: a little under Claude Code's own count,
which also prices small background calls the transcript does not record.

**History outlives the transcripts.** Claude Code deletes transcripts after
30 days by default (`cleanupPeriodDays`). `--record` writes each day's totals
per thread to a ledger file, `effort.jsonl` beside the jobs ledger; run it
nightly. The page reads that file and the transcripts and takes, for each day
and thread, the larger of the two, so a day survives its transcripts being
cleaned up and the page itself still stores nothing.

Only names, dates, durations and figures leave this file: never a line of a
transcript. Codex keeps its sessions elsewhere, in another format, and is not
read yet. Standard library only, Python 3.9 or later.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

sys.dont_write_bytecode = True

IDLE = 300                  # seconds: a longer gap between messages is idle time, not work
STORE = "effort.jsonl"

# List prices in dollars per million tokens: input, output, cache read. A cache
# write costs 1.25 times the input price for five minutes and twice for an
# hour. Fast mode costs twice the standard price. A model missing here still
# counts its tokens and time; its cost is left out and the card says so.
PRICES = {
    "fable-5-1": (10, 50, .25), "mythos-5-1": (10, 50, .25), "fable-5": (10, 50, 1), "mythos-5": (10, 50, 1),
    "opus-5-5": (4, 20, .2), "opus-5": (5, 25, .5), "opus-4-8": (5, 25, .5), "opus-4-7": (5, 25, .5),
    "opus-4-6": (5, 25, .5), "opus-4-5": (5, 25, .5), "opus-4-1": (15, 75, 1.5), "opus-4": (15, 75, 1.5),
    "sonnet-5-5": (2, 10, .2), "sonnet-5": (2, 10, .2), "sonnet-4-6": (3, 15, .3), "sonnet-4-5": (3, 15, .3),
    "sonnet-4": (3, 15, .3), "haiku-4-5": (1, 5, .1), "haiku-3-5": (.8, 4, .08),
}
TOKENS = ("input", "output", "cache_read", "cache_write")
TIMESTAMP = re.compile(r'"timestamp":\s*"([^"]+)"')
USER = re.compile(r'"type":\s*"user"')


def price(model: str) -> Optional[Tuple[float, float, float]]:
    m = re.sub(r"^claude-", "", model or "")
    m = re.sub(r"-\d{8}$", "", re.sub(r"\[.*\]$", "", m))
    return PRICES.get(m)


def usage_cost(model: str, u: dict) -> Optional[float]:
    p = price(model)
    if p is None:
        return None
    inp, out, read = p
    split = u.get("cache_creation") if isinstance(u.get("cache_creation"), dict) else None
    hour = int((split or {}).get("ephemeral_1h_input_tokens") or 0)
    five = int((split or {}).get("ephemeral_5m_input_tokens") or 0) if split else int(u.get("cache_creation_input_tokens") or 0)
    fast = 2 if u.get("speed") == "fast" else 1
    return fast * (int(u.get("input_tokens") or 0) * inp + int(u.get("output_tokens") or 0) * out
                   + int(u.get("cache_read_input_tokens") or 0) * read + five * inp * 1.25 + hour * inp * 2) / 1e6


def usage_tokens(u: dict) -> Dict[str, int]:
    return {"input": int(u.get("input_tokens") or 0), "output": int(u.get("output_tokens") or 0),
            "cache_read": int(u.get("cache_read_input_tokens") or 0),
            "cache_write": int(u.get("cache_creation_input_tokens") or 0)}


# --------------------------------------------------------------------------- where the transcripts are

def projects_dir() -> Path:
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(base).expanduser() if base else Path.home() / ".claude") / "projects"


def encoded(folder: Path) -> str:
    """The name Claude Code gives a working folder's transcript folder."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(folder))


def local(stamp: str) -> Optional[dt.datetime]:
    try:
        return dt.datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
    except ValueError:
        return None


def read_session(path: Path) -> Optional[dict]:
    """One session: where it ran, how it was started, when each message came,
    what each assistant message used, and the files it wrote or edited. Its
    subagents' usage and writes are added; their times are not, as they run
    inside the session's own."""
    s = {"id": path.stem, "cwd": None, "entry": None, "times": [], "usage": [], "writes": []}
    if not _read(path, s, main=True):
        return None
    for sub in sorted((path.parent / path.stem / "subagents").glob("*.jsonl")):
        _read(sub, s, main=False)
    return s


def _read(path: Path, s: dict, main: bool) -> bool:
    msgs: Dict[str, Tuple[dt.datetime, str, dict]] = {}
    try:
        f = path.open(encoding="utf-8", errors="replace")
    except OSError:
        return False
    with f:
        for line in f:
            if main and s["entry"] is None and '"entrypoint"' in line:
                m = re.search(r'"entrypoint":\s*"([^"]*)"', line)
                s["entry"] = m.group(1) if m else ""
                if s["entry"].startswith("sdk"):
                    return False                      # headless: the jobs ledger has it
            if main and s["cwd"] is None and '"cwd"' in line:
                m = re.search(r'"cwd":\s*"((?:[^"\\]|\\.)*)"', line)
                if m:
                    s["cwd"] = json.loads('"%s"' % m.group(1))
            if '"assistant"' in line:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get("type") != "assistant":         # a user message that mentions the word
                    when = local(str(d.get("timestamp") or "")) if main and d.get("type") == "user" else None
                    if when:
                        s["times"].append(when)
                    continue
                m, when = d.get("message") or {}, local(str(d.get("timestamp") or ""))
                if when is None or not isinstance(m, dict):
                    continue
                if main:
                    s["times"].append(when)
                if isinstance(m.get("usage"), dict) and m.get("model") != "<synthetic>":
                    msgs[str(m.get("id") or len(msgs))] = (when, str(m.get("model") or ""), m["usage"])
                for c in m.get("content") or []:
                    if isinstance(c, dict) and c.get("type") == "tool_use" and isinstance(c.get("input"), dict):
                        target = c["input"].get("file_path") or c["input"].get("notebook_path")
                        if c.get("name") in ("Write", "Edit", "MultiEdit", "NotebookEdit") and target:
                            s["writes"].append(str(target))
            elif main and USER.search(line):
                m = TIMESTAMP.search(line)
                when = local(m.group(1)) if m else None
                if when:
                    s["times"].append(when)
    s["usage"].extend(msgs.values())          # one entry per message: Claude Code writes a line per content block
    return True


Roots = List[Tuple[Path, Tuple[str, ...]]]     # a folder, and where it sits in the workspace now


def sessions(roots: Roots, since: Optional[dt.datetime] = None, folder: Optional[Path] = None) -> Iterable[dict]:
    """Every interactive session that ran in one of `roots` or below,
    touched since `since`."""
    folder = folder or projects_dir()
    if not folder.is_dir():
        return
    prefixes = [encoded(r) for r, _ in roots]
    cutoff = since.timestamp() if since else 0
    for d in sorted(folder.iterdir()):
        if not d.is_dir() or not any(d.name == p or d.name.startswith(p + "-") for p in prefixes):
            continue
        for path in sorted(d.glob("*.jsonl")):
            try:
                if path.stat().st_mtime < cutoff:
                    continue
            except OSError:
                continue
            s = read_session(path)
            if s and s["cwd"]:
                yield s


# --------------------------------------------------------------------------- which thread

def inside(path: str, roots: Roots) -> Optional[Tuple[str, ...]]:
    """The path's parts in the workspace as it is now, through the deepest
    root that holds it, or None."""
    p = Path(path)
    for r, now in sorted(roots, key=lambda rn: -len(rn[0].parts)):
        try:
            return now + p.relative_to(r).parts
        except ValueError:
            continue
    return None


def roots_for(ws: Path, also: Iterable[Path] = (), moved: Optional[Dict[str, str]] = None) -> Roots:
    """The workspace, the folders it used to live in, and each moved folder.
    A moved folder named relatively is taken under each of the others."""
    bases = [ws.resolve()] + [Path(a).expanduser().resolve() for a in also]
    out: Roots = [(b, ()) for b in bases]
    for old, new in (moved or {}).items():
        now = tuple(Path(new).parts)
        old_p = Path(old).expanduser()
        for o in ([old_p] if old_p.is_absolute() else [b / old_p for b in bases]):
            out.append((Path(os.path.abspath(o)), now))
    return out


def attribute(s: dict, roots: Roots, single: Dict[Tuple[str, str], str]) -> Optional[Tuple[str, str, str]]:
    """(zone, project, thread) for a session. Outside the zones the zone is ''
    and the project names the place, such as System. An empty thread is the
    project's unassigned share. `single` maps (zone, project) to the thread a
    project without thread notes is. None: the session ran elsewhere."""
    parts = inside(s["cwd"], roots)
    if parts is None:
        return None
    writes = [w for w in (inside(x, roots) for x in s["writes"]) if w and len(w) >= 4 and w[0] == "Zones"]
    zone = project = thread = ""
    if len(parts) >= 3 and parts[0] == "Zones" and not parts[2].startswith((".", "_")):
        zone, project = parts[1], parts[2]
        if len(parts) >= 5 and parts[3] == "Threads":
            thread = parts[4]
    else:
        here = [w for w in writes if len(parts) < 2 or parts[0] != "Zones" or w[1] == parts[1]]
        here = [w for w in here if not w[2].startswith((".", "_"))]
        if here:
            zone, project = most([(w[1], w[2]) for w in here])
        elif len(parts) >= 2 and parts[0] == "Zones":
            return (parts[1], "", "")                 # the zone, but no project in it
        else:
            return ("", "/".join(parts[:2]) if parts and parts[0] in ("System", "Wikis") else "Workspace", "")
    if not thread:
        mine = [w[4] for w in writes if w[1] == zone and w[2] == project and len(w) >= 6 and w[3] == "Threads"]
        thread = most(mine) if mine else single.get((zone, project), "")
    return (zone, project, thread)


def most(items: list):
    """The commonest item; on a tie, the first to appear."""
    counts: Dict[object, int] = {}
    for i in items:
        counts[i] = counts.get(i, 0) + 1
    return max(counts, key=lambda k: (counts[k], -items.index(k)))


# --------------------------------------------------------------------------- by day

def tally(found: Iterable[dict], roots: Roots, single: Dict[Tuple[str, str], str]) -> Dict[tuple, dict]:
    """(day, zone, project, thread) -> seconds, cost, tokens, sessions."""
    out: Dict[tuple, dict] = {}

    def row(day: dt.date, key: tuple) -> dict:
        return out.setdefault((day.isoformat(),) + key, dict({"seconds": 0, "cost": 0.0, "unpriced": 0, "sessions": []},
                                                             **{t: 0 for t in TOKENS}))
    for s in found:
        key = attribute(s, roots, single)
        if key is None:
            continue
        times = sorted(s["times"])
        for a, b in zip(times, times[1:]):
            gap = (b - a).total_seconds()
            if 0 < gap <= IDLE:
                row(b.date(), key)["seconds"] += gap
        for when, model, u in s["usage"]:
            r = row(when.date(), key)
            c = usage_cost(model, u)
            r["cost"] += c or 0.0
            r["unpriced"] += c is None
            for t, n in usage_tokens(u).items():
                r[t] += n
        for when in times[:1] + [w for w, _, _ in s["usage"]]:
            r = row(when.date(), key)
            if s["id"] not in r["sessions"]:
                r["sessions"].append(s["id"])
    for r in out.values():
        r["seconds"] = round(r["seconds"])
        r["cost"] = round(r["cost"], 4)
        r["sessions"] = len(r["sessions"])
    return out


def read_store(path: Optional[Path]) -> Dict[tuple, dict]:
    out: Dict[tuple, dict] = {}
    if path is None or not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            e = json.loads(line)
            out[(str(e["day"]), str(e["zone"]), str(e["project"]), str(e["thread"]))] = e
        except (ValueError, KeyError, TypeError):
            continue
    return out


def merged(fresh: Dict[tuple, dict], stored: Dict[tuple, dict]) -> Dict[tuple, dict]:
    """Per day and thread, the fuller of the two counts. A day's count only
    grows while its transcripts are there, so the larger is the one that has
    not lost a session to the clean-up."""
    out = dict(stored)
    for k, r in fresh.items():
        old = out.get(k)
        if old is None or (float(r.get("cost") or 0), r.get("seconds") or 0) >= (float(old.get("cost") or 0), old.get("seconds") or 0):
            out[k] = r
    return out


def single_threads(ws: Path) -> Dict[Tuple[str, str], str]:
    """Projects with no thread note, each its own thread, as the page reads them."""
    out = {}
    zones = ws / "Zones"
    for zone in (sorted(p for p in zones.iterdir() if p.is_dir()) if zones.is_dir() else []):
        for project in sorted(p for p in zone.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))):
            notes = [t for t in (project / "Threads").glob("*/*.md") if t.stem == t.parent.name] if (project / "Threads").is_dir() else []
            if not notes and (project / (project.name + ".md")).is_file():
                out[(zone.name, project.name)] = project.name
    return out


def ledger(ws: Path, store: Optional[Path] = None, also: Iterable[Path] = (), days: Optional[int] = None,
           now: Optional[dt.datetime] = None, folder: Optional[Path] = None,
           moved: Optional[Dict[str, str]] = None) -> Dict[tuple, dict]:
    """Every day and thread on record: the transcripts there are now, merged
    with the stored ledger. `also` names folders the workspace used to live in,
    read as if they were it; `moved` maps an old folder, absolute or relative
    to the workspace, to where it is now, relative to the workspace."""
    now = now or dt.datetime.now()
    roots = roots_for(ws, also, moved)
    since = now - dt.timedelta(days=days) if days else None
    fresh = tally(sessions(roots, since, folder), roots, single_threads(ws))
    return merged(fresh, read_store(store))


def record(ws: Path, store: Path, also: Iterable[Path] = (), folder: Optional[Path] = None,
           moved: Optional[Dict[str, str]] = None) -> int:
    """Write the merged ledger to `store`, one line per day and thread, oldest
    first. Returns the number of lines."""
    rows = ledger(ws, store, also, folder=folder, moved=moved)
    store.parent.mkdir(parents=True, exist_ok=True)
    tmp = store.with_name(store.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for k in sorted(rows):
            day, zone, project, thread = k
            f.write(json.dumps(dict(rows[k], day=day, zone=zone, project=project, thread=thread), sort_keys=True) + "\n")
    os.replace(tmp, store)
    return len(rows)


def default_store() -> Path:
    """Beside the jobs extra's ledger: GARRICK_JOBS_DIR, or the folder job.py uses."""
    set_to = os.environ.get("GARRICK_JOBS_DIR")
    if set_to:
        base = Path(set_to).expanduser()
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Logs" / "garrick-jobs"
    else:
        base = Path.home() / ".local" / "state" / "garrick-jobs"
    return base / STORE


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Time and tokens per thread, from Claude Code's transcripts.")
    ap.add_argument("--workspace", default=os.environ.get("GARRICK_WORKSPACE") or ".", help="the workspace folder")
    ap.add_argument("--store", help="the ledger file (default: effort.jsonl beside the jobs ledger)")
    ap.add_argument("--record", action="store_true", help="write each day's totals to the ledger file")
    ap.add_argument("--also", action="append", default=[], help="a folder the workspace used to live in")
    ap.add_argument("--moved", action="append", default=[], metavar="OLD=NEW",
                    help="a folder renamed or moved: its old path, absolute or in the workspace, and its path in the workspace now")
    ap.add_argument("--days", type=int, default=30, help="without --record, the days to print (default 30)")
    args = ap.parse_args(argv)
    ws = Path(args.workspace).expanduser().resolve()
    if not (ws / "Zones").is_dir():
        raise SystemExit("effort: %s has no Zones/ folder; pass --workspace." % ws)
    store = Path(args.store).expanduser() if args.store else default_store()
    moved = dict(m.split("=", 1) for m in args.moved if "=" in m)
    if args.record:
        print("effort: %d day-and-thread lines in %s" % (record(ws, store, [Path(a) for a in args.also], moved=moved), store))
        return 0
    rows = ledger(ws, store, [Path(a) for a in args.also], moved=moved)
    since = (dt.date.today() - dt.timedelta(days=args.days - 1)).isoformat()
    total: Dict[tuple, list] = {}
    for (day, zone, project, thread), r in rows.items():
        if day >= since:
            t = total.setdefault((zone, project, thread), [0, 0.0])
            t[0] += r.get("seconds") or 0
            t[1] += float(r.get("cost") or 0)
    for (zone, project, thread), (secs, cost) in sorted(total.items(), key=lambda kv: -kv[1][1]):
        print("%-10s %-30s %-30s %6.1f h  $%8.2f" % (zone or "-", project[:30], (thread or "unassigned")[:30], secs / 3600, cost))
    return 0


if __name__ == "__main__":
    sys.exit(main())
