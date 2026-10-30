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
to live in (`--also`) counts as the workspace. A project or thread renamed
from the status page is kept in System/generated/moved.json (MOVED), never
committed, and counts as if it had been given with `--moved`.

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
cleaned up.

**A transcript unchanged is not read again.** Given a file to keep its
reading in (`ledger(kept=...)`; the status page keeps it beside itself, as
status.effort.json), each transcript's size and modification time, and its
subagents', are kept with what the ledger needs of the session: where it ran,
the files it wrote and its figures by day. A later reading takes those
figures again for a transcript whose size and times are the same, so a build
with nothing changed reads no transcript in full (#260). A change to this
file or to the machine's time zone starts the record afresh.

Only names, dates, durations and figures leave this file: never a line of a
transcript. Codex keeps its sessions elsewhere, in another format, and is not
read yet. Standard library only, Python 3.9 or later.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

sys.dont_write_bytecode = True

IDLE = 300                  # seconds: a longer gap between messages is idle time, not work
STORE = "effort.jsonl"
# The folders renamed from the status page (#184): {"<old>": "<new>"}, each from
# the workspace's root, written by page_action.py. A `--moved` given for the
# same old folder wins.
MOVED = ("System", "generated", "moved.json")

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


def summary(s: dict) -> dict:
    """What the ledger needs of one session, and all a later reading keeps of
    it: where it ran, each file it wrote with how often, in the order first
    written, and its figures by day. Never a line of the transcript."""
    days: Dict[str, dict] = {}

    def row(day: dt.date) -> dict:
        return days.setdefault(day.isoformat(), dict({"seconds": 0.0, "cost": 0.0, "unpriced": 0, "session": 0},
                                                     **{t: 0 for t in TOKENS}))
    times = sorted(s["times"])
    for a, b in zip(times, times[1:]):
        gap = (b - a).total_seconds()
        if 0 < gap <= IDLE:
            row(b.date())["seconds"] += gap
    for when, model, u in s["usage"]:
        r = row(when.date())
        c = usage_cost(model, u)
        r["cost"] += c or 0.0
        r["unpriced"] += c is None
        for t, n in usage_tokens(u).items():
            r[t] += n
    for when in times[:1] + [w for w, _, _ in s["usage"]]:
        row(when.date())["session"] = 1
    writes: Dict[str, int] = {}
    for w in s["writes"]:
        writes[w] = writes.get(w, 0) + 1
    return {"id": s["id"], "cwd": s["cwd"], "writes": [[w, n] for w, n in writes.items()], "days": days}


def stamp(path: Path) -> Optional[list]:
    """A transcript as it is on disk: its size and modification time, and
    each of its subagents' by name. The same stamp, the same session."""
    try:
        st = path.stat()
    except OSError:
        return None
    subs = []
    for sub in sorted((path.parent / path.stem / "subagents").glob("*.jsonl")):
        try:
            ss = sub.stat()
        except OSError:
            continue
        subs.append([sub.name, ss.st_size, ss.st_mtime_ns])
    return [st.st_size, st.st_mtime_ns, subs]


def sessions(roots: Roots, since: Optional[dt.datetime] = None, folder: Optional[Path] = None,
             kept: Optional[Dict[str, list]] = None) -> Iterable[dict]:
    """Every interactive session that ran in one of `roots` or below,
    touched since `since`, as summary() gives it. `kept` maps a transcript's
    path to [its stamp, its summary or None] as an earlier reading found
    them: a transcript whose stamp is the same is not read again, and once
    every session has been given, `kept` holds what this reading found, for
    the transcripts it looked at and no others. The stamp is taken before
    the read, so a transcript written meanwhile is read again next time."""
    seen: Dict[str, list] = {}
    folder = folder or projects_dir()
    prefixes = [encoded(r) for r, _ in roots]
    cutoff = since.timestamp() if since else 0
    for d in (sorted(folder.iterdir()) if folder.is_dir() else []):
        if not d.is_dir() or not any(d.name == p or d.name.startswith(p + "-") for p in prefixes):
            continue
        for path in sorted(d.glob("*.jsonl")):
            try:
                if path.stat().st_mtime < cutoff:
                    continue
            except OSError:
                continue
            now = stamp(path) if kept is not None else None
            was = (kept or {}).get(str(path))
            if now is not None and isinstance(was, list) and len(was) == 2 and was[0] == now:
                one = was[1]
            else:
                s = read_session(path)
                one = summary(s) if s and s["cwd"] else None     # a headless run or no folder: kept as nothing
            if now is not None:
                seen[str(path)] = [now, one]
            if one:
                yield one
    if kept is not None:
        kept.clear()
        kept.update(seen)


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


def kept_moves(ws: Path) -> Dict[str, str]:
    """The folders renamed from the status page, as `--moved` would give them."""
    try:
        data = json.loads(Path(ws).joinpath(*MOVED).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {o: n for o, n in data.items() if isinstance(o, str) and isinstance(n, str)} if isinstance(data, dict) else {}


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
    writes = [w for w in (inside(x, roots) for x, n in s["writes"] for _ in range(n)) if w and len(w) >= 4 and w[0] == "Zones"]
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
    """(day, zone, project, thread) -> seconds, cost, tokens, sessions, from
    sessions as summary() gives them."""
    out: Dict[tuple, dict] = {}
    for s in found:
        key = attribute(s, roots, single)
        if key is None:
            continue
        for day, fig in s["days"].items():
            r = out.setdefault((day,) + key, dict({"seconds": 0, "cost": 0.0, "unpriced": 0, "sessions": []},
                                                  **{t: 0 for t in TOKENS}))
            for k in ("seconds", "cost", "unpriced") + TOKENS:
                r[k] += fig.get(k) or 0
            if fig.get("session") and s["id"] not in r["sessions"]:
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


def reader() -> str:
    """This reader and the time zone it puts days in: a reading kept by
    another is not taken again, since its figures may not be what this one
    would find."""
    try:
        me = Path(__file__).read_bytes()
    except OSError:
        me = b""
    zone = "%s %s %s %s" % (time.tzname, time.timezone, time.altzone, os.environ.get("TZ", ""))
    return hashlib.sha1(me + zone.encode("utf-8")).hexdigest()


def read_kept(path: Path) -> Dict[str, list]:
    """The transcripts an earlier reading kept in `path`, or {} where it kept
    none, or another reader did, or the file does not read."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("reader") != reader() or not isinstance(data.get("transcripts"), dict):
        return {}
    return data["transcripts"]


def write_kept(path: Path, transcripts: Dict[str, list]) -> None:
    """Keep what this reading found, whole or not at all: a write that fails
    leaves the next reading to read everything once."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".")
    except OSError:
        return
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"reader": reader(), "transcripts": transcripts}, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, str(path))
    except (OSError, TypeError, ValueError):
        if os.path.exists(tmp):
            os.unlink(tmp)


def ledger(ws: Path, store: Optional[Path] = None, also: Iterable[Path] = (), days: Optional[int] = None,
           now: Optional[dt.datetime] = None, folder: Optional[Path] = None,
           moved: Optional[Dict[str, str]] = None, kept: Optional[Path] = None) -> Dict[tuple, dict]:
    """Every day and thread on record: the transcripts there are now, merged
    with the stored ledger. `also` names folders the workspace used to live in,
    read as if they were it; `moved` maps an old folder, absolute or relative
    to the workspace, to where it is now, relative to the workspace. With
    `kept`, a file this reading is kept in, a transcript unchanged since the
    last reading kept there is not read again (#260)."""
    now = now or dt.datetime.now()
    roots = roots_for(ws, also, dict(kept_moves(ws), **(moved or {})))
    since = now - dt.timedelta(days=days) if days else None
    reads = read_kept(kept) if kept is not None else None
    before = dict(reads) if reads is not None else None
    fresh = tally(sessions(roots, since, folder, reads), roots, single_threads(ws))
    if kept is not None and reads != before:
        write_kept(kept, reads)
    return merged(fresh, read_store(store))


def record(ws: Path, store: Path, also: Iterable[Path] = (), folder: Optional[Path] = None,
           moved: Optional[Dict[str, str]] = None) -> int:
    """Write the merged ledger to `store`, one line per day and thread, oldest
    first. Returns the number of lines."""
    rows = ledger(ws, store, also, folder=folder, moved=moved)
    store.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(store.parent), prefix=store.name + ".")     # its own: two records at once share none
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for k in sorted(rows):
                day, zone, project, thread = k
                f.write(json.dumps(dict(rows[k], day=day, zone=zone, project=project, thread=thread), sort_keys=True) + "\n")
        os.replace(tmp, str(store))
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
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
