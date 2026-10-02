#!/usr/bin/env python3
"""A status page for a Garrick workspace. An optional extra.

    python3 status.py [--workspace FOLDER] [--out FILE] [--open] [--obsidian VAULT]

One self-contained HTML file that answers "is anything wrong, and where was I"
at a glance: every live thread by zone with how long since its resume point
moved, what the check found, open actions, what is waiting in the inboxes,
and, if you run scheduled jobs, how they ran and what the assistant spent.

**Show, don't store.** The page reads files the workspace and the jobs extra
already keep, and writes nothing but itself. It runs no server, loads nothing
from the network and carries no third-party script. Delete it and nothing is
lost: every fact on it lives in a file you own. Each panel says where its
numbers come from and how old they are.

**It lives in `System/generated/status.html`**, the folder for pages a tool
rebuilds. The page is the one place that shows every zone at once, so that
folder is kept out of two things: the workspace's git history (the root
`.gitignore` names it, and `check.py` reports it if not) and the wording the
wall check treats as shared by every side (`check.py` never reads it as such,
so whatever the page repeats can never be copied across a wall unnoticed).
It shows metadata only: names, party tags, dates and counts, never a line of
what a note says.

**Links open the files themselves**, in whatever app you use for Markdown.
Pass `--obsidian VAULT` if you opened the workspace root in Obsidian as a vault
called VAULT, and the links open there instead.

Copy this folder into your workspace as `System/status/`, next to
`System/jobs/` if you have it, and run it by hand or on a schedule through
job.py (see docs/extras/status-page.md). Standard library only, Python 3.9 or
later. Not installed by install.py.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import plistlib
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.dont_write_bytecode = True

E = html.escape
DAYS = 14
EXIT = {0: "ok", 3: "answer incomplete", 4: "could not sign in", 6: "missing connector", 8: "spending cap",
        64: "bad arguments", 75: "skipped, still running", 124: "timed out", 127: "command not found"}
OK_EXITS = (0, 75)
LOGLINE = re.compile(r"^===== (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)  (\S+)  (?:exit (-?\d+)  \((\d+)s\)|skipped)")
TODO_ITEM = re.compile(r"^\s*-\s\[ \]\s")


# --------------------------------------------------------------------------- where things are

def find_workspace(given: Optional[str]) -> Path:
    for cand in (given, os.environ.get("GARRICK_WORKSPACE")):
        if cand:
            return Path(cand).expanduser().resolve()
    here = Path.cwd().resolve()
    for folder in (here, *here.parents):
        if (folder / "System" / "rules.md").is_file() and (folder / "Zones").is_dir():
            return folder
    for folder in (Path(__file__).resolve().parent, *Path(__file__).resolve().parents):
        if (folder / "System" / "rules.md").is_file() and (folder / "Zones").is_dir():
            return folder
    raise SystemExit("status: no workspace found. Pass --workspace, set GARRICK_WORKSPACE, or run it from inside one.")


def load_agent(ws: Path):
    """The jobs extra's agent module, for the ledger and the caps, if it is installed."""
    here = Path(__file__).resolve().parent
    for folder in (ws / "System" / "jobs", here.parent / "jobs"):
        if (folder / "agent.py").is_file():
            sys.path.insert(0, str(folder))
            try:
                import agent  # noqa: F401
                return agent
            except Exception:
                return None
    return None


def jobs_dir(agent) -> Path:
    if agent is not None:
        return agent.jobs_dir()
    set_to = os.environ.get("GARRICK_JOBS_DIR")
    if set_to:
        return Path(set_to).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "garrick-jobs"
    return Path.home() / ".local" / "state" / "garrick-jobs"


def frontmatter(path: Path) -> dict:
    """The note's frontmatter: the workspace's own parser when it is there, a
    small one otherwise. Only frontmatter is ever read from a note."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    if not text.startswith("---"):
        return {}
    out = {}
    for line in text.split("\n")[1:]:
        if line.strip() == "---":
            break
        m = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", line)
        if m:
            out[m.group(1)] = m.group(2).strip().strip("\"'")
    return out


def visible_dirs(folder: Path) -> List[Path]:
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.is_dir() and not p.name.startswith((".", "_")))


def tags(value: str) -> List[str]:
    return [t.strip().lstrip("#") for t in re.split(r"[,\[\]]", value or "") if t.strip()]


def as_date(value: str) -> Optional[dt.date]:
    try:
        return dt.date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None


# --------------------------------------------------------------------------- what the page reads

def threads(ws: Path) -> Dict[str, dict]:
    """Per zone: every live thread's project, name, party and the date its
    note was last updated. Frontmatter only, like "what's open"."""
    out = {}
    for zone in visible_dirs(ws / "Zones"):
        rows, parked, done = [], [], 0
        for project in visible_dirs(zone):
            if project.name == "Inbox":
                continue
            pfm = frontmatter(project / (project.name + ".md"))
            for thread in visible_dirs(project / "Threads"):
                note = thread / (thread.name + ".md")
                fm = frontmatter(note)
                if str(fm.get("status", "")).lower() == "done":
                    done += 1
                    continue
                row = {"project": project.name, "thread": thread.name, "note": note,
                       "party": tags(fm.get("party") or pfm.get("party", "")),
                       "updated": as_date(fm.get("updated", "")), "status": fm.get("status", "")}
                (parked if str(fm.get("status", "")).lower() == "parked" else rows).append(row)
        rows.sort(key=lambda r: r["updated"] or dt.date.min)
        parked.sort(key=lambda r: r["updated"] or dt.date.min)
        out[zone.name] = {"rows": rows, "parked": parked, "done": done, "folder": zone}
    return out


def todo(ws: Path) -> Dict[str, dict]:
    out = {}
    for zone in visible_dirs(ws / "Zones"):
        f = zone / "Todo.md"
        if not f.is_file():
            continue
        counts, section = {}, None
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("## "):
                section = line[3:].strip()
            elif section and section.lower() != "done" and TODO_ITEM.match(line) and "<action>" not in line:
                counts[section] = counts.get(section, 0) + 1
        out[zone.name] = {"counts": counts, "file": f, "when": dt.datetime.fromtimestamp(f.stat().st_mtime)}
    return out


def inboxes(ws: Path) -> List[Tuple[str, Path, int]]:
    """Files waiting to be filed: each zone's Inbox and the Meetings inbox."""
    places = [(z.name, z / "Inbox") for z in visible_dirs(ws / "Zones")]
    places.append(("Meetings", ws / "Wikis" / "Meetings" / "raw" / "inbox"))
    out = []
    for name, folder in places:
        if folder.is_dir():
            n = sum(1 for p in folder.iterdir() if p.is_file() and not p.name.startswith("."))
            out.append((name, folder, n))
    return out


def check(ws: Path) -> Optional[dict]:
    tool = ws / "System" / "tools" / "check.py"
    if not tool.is_file():
        return None
    try:
        proc = subprocess.run([sys.executable, str(tool), "--root", str(ws), "--json"],
                              capture_output=True, text=True, timeout=300)
        data = json.loads(proc.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {"failed": True}
    titles = {}
    try:
        src = tool.read_text(encoding="utf-8")
        titles = dict(re.findall(r'\(\s*"([a-z-]+)",\s*"([^"]+)"\s*\)', src.split("EAR_GROUP")[0]))
    except OSError:
        pass
    data["titles"] = titles
    return data


def repos(ws: Path) -> List[dict]:
    places = [("Workspace", ws)] + [(z.name, z) for z in visible_dirs(ws / "Zones")] + \
             [(w.name, w) for w in visible_dirs(ws / "Wikis")]
    out = []
    for name, folder in places:
        if not (folder / ".git").exists():
            continue
        def git(*args):
            try:
                return subprocess.run(["git", "-C", str(folder), *args], capture_output=True, text=True, timeout=30).stdout
            except (OSError, subprocess.TimeoutExpired):
                return ""
        dirty = len(git("status", "--porcelain").splitlines())
        ct = git("log", "-1", "--format=%ct").strip()
        out.append({"name": name, "dirty": dirty, "last": dt.datetime.fromtimestamp(int(ct)) if ct.isdigit() else None})
    return out


def wikis(ws: Path) -> List[Tuple[str, Path, str]]:
    out = []
    for w in visible_dirs(ws / "Wikis"):
        log = w / "wiki" / "log.md"
        if not log.is_file():
            continue
        heads = [l[3:].strip() for l in log.read_text(encoding="utf-8", errors="replace").splitlines() if l.startswith("## ")]
        dated = sorted((h for h in heads if re.match(r"\d{4}-\d{2}-\d{2}", h)), reverse=True)
        top = (dated or heads or ["nothing logged yet"])[0]
        out.append((w.name, log, top[:100] + ("…" if len(top) > 100 else "")))
    return out


def schedules() -> Dict[str, Tuple[str, dt.timedelta]]:
    """Job name -> (schedule in words, how long before a missing run is late),
    from launchd jobs that run job.py. Elsewhere schedules are unknown."""
    out = {}
    folder = Path.home() / "Library" / "LaunchAgents"
    if not folder.is_dir():
        return out
    for plist in folder.glob("*.plist"):
        try:
            p = plistlib.loads(plist.read_bytes())
        except Exception:
            continue
        args = [str(a) for a in p.get("ProgramArguments", [])]
        at = next((i for i, a in enumerate(args) if a.endswith("job.py")), None)
        if at is None or at + 1 >= len(args):
            continue
        name = args[at + 1]
        if "StartInterval" in p:
            m = int(p["StartInterval"]) // 60
            out[name] = ("every %d min" % m if m < 120 else "every %d h" % (m // 60), dt.timedelta(seconds=3 * int(p["StartInterval"])))
            continue
        cal = p.get("StartCalendarInterval", {})
        cal = cal if isinstance(cal, list) else [cal]
        days = "Sun Mon Tue Wed Thu Fri Sat".split()
        words = ", ".join((days[c["Weekday"] % 7] + " " if "Weekday" in c else "") + "%02d:%02d" % (c.get("Hour", 0), c.get("Minute", 0)) for c in cal)
        weekly = bool(cal) and all("Weekday" in c for c in cal)
        out[name] = (("weekly " if weekly else "daily ") + words, dt.timedelta(days=8 if weekly else 2))
    return out


def history(folder: Path, name: str, now: dt.datetime) -> List[Tuple[dt.datetime, int]]:
    since = now - dt.timedelta(days=DAYS)
    runs = []
    for path in (folder / (name + ".log.1"), folder / (name + ".log")):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            m = LOGLINE.match(line)
            if not m:
                continue
            when = dt.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
            if when >= since:
                runs.append((when, int(m.group(3)) if m.group(3) else 75))
    return runs


def jobs(folder: Path, now: dt.datetime) -> List[dict]:
    if not folder.is_dir():
        return []
    sched = schedules()
    out = []
    for beat in sorted(folder.glob("*.heartbeat.json")):
        try:
            hb = json.loads(beat.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        name = hb.get("job") or beat.name[:-len(".heartbeat.json")]
        when = None
        try:
            when = dt.datetime.strptime(str(hb.get("finished"))[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
        code = int(hb.get("exit", -1)) if str(hb.get("exit", "")).lstrip("-").isdigit() else -1
        words, limit = sched.get(name, ("schedule not found", None))
        if when and limit and now - when > limit:
            state, status = "critical", "late: last ran %s" % age(when, now)
        elif code not in OK_EXITS:
            state, status = "critical", "exit %d: %s" % (code, EXIT.get(code, "failed"))
        elif hb.get("idle_days"):
            state, status = "warning", "idle %s days" % hb["idle_days"]
        else:
            state, status = "good", "ok"
        out.append({"name": name, "when": when, "seconds": hb.get("seconds"), "state": state, "status": status,
                    "schedule": words, "runs": history(folder, name, now), "log": folder / (name + ".log")})
    return out


def ledger(agent, folder: Path, now: dt.datetime) -> Optional[dict]:
    path = folder / "ledger.jsonl"
    if agent is None or not path.is_file():
        return None
    entries = agent.read_ledger(path, now.timestamp(), DAYS * 24)
    caps = agent.caps()
    calls = [e for e in entries if not e.get("refused")]
    day = [e for e in calls if now.timestamp() - e["ts"] < 86400]
    hour = [e for e in calls if now.timestamp() - e["ts"] < 3600]
    by = {}
    for e in entries:
        j = by.setdefault(e.get("job", "?"), {"calls": 0, "cost": 0.0, "failed": 0, "refused": 0, "denied": set()})
        if e.get("refused"):
            j["refused"] += 1
            continue
        j["calls"] += 1
        j["cost"] += float(e.get("cost_usd") or 0)
        j["failed"] += 1 if e.get("exit") else 0
        j["denied"] |= set(e.get("denied") or [])
    return {"caps": caps, "day": len(day), "hour": len(hour), "cost_day": sum(float(e.get("cost_usd") or 0) for e in day),
            "by": by, "refused_today": [e for e in entries if e.get("refused") and now.timestamp() - e["ts"] < 86400]}


# --------------------------------------------------------------------------- small helpers

def age(t: dt.datetime, now: dt.datetime) -> str:
    s = (now - t).total_seconds()
    if s < 3600:
        return "%d min ago" % max(1, s // 60)
    if s < 86400 * 2:
        return "%d h ago" % round(s / 3600)
    return "%d days ago" % round(s / 86400)


class Links:
    def __init__(self, ws: Path, vault: Optional[str]):
        self.ws, self.vault = ws, vault

    def __call__(self, path: Path) -> str:
        if self.vault:
            rel = path.resolve().relative_to(self.ws).as_posix()
            rel = rel[:-3] if rel.endswith(".md") else rel
            return "obsidian://open?vault=%s&file=%s" % (urllib.parse.quote(self.vault), urllib.parse.quote(rel))
        return path.resolve().as_uri()


def day_cells(runs: List[Tuple[dt.datetime, int]], now: dt.datetime) -> List[Tuple[str, str]]:
    """One cell per day, oldest first, coloured by how the day ended: red when
    its last run failed or most runs did, amber when it failed and recovered."""
    out = []
    for i in range(DAYS - 1, -1, -1):
        day = (now - dt.timedelta(days=i)).date()
        rs = sorted(r for r in runs if r[0].date() == day)
        bad = [r for r in rs if r[1] not in OK_EXITS]
        if not rs:
            out.append(("none", "%s · no run" % day.strftime("%a %d %b")))
            continue
        ended_bad = rs[-1][1] not in OK_EXITS
        state = "critical" if ended_bad or len(bad) * 2 > len(rs) else "warning" if bad else "good"
        tip = "%s · %d run%s" % (day.strftime("%a %d %b"), len(rs), "" if len(rs) == 1 else "s")
        if bad:
            codes = sorted({r[1] for r in bad})
            tip += " · %d failed (exit %s)%s" % (len(bad), ", ".join(map(str, codes)), "" if ended_bad else " · recovered")
        else:
            tip += " · all ok"
        out.append((state, tip))
    return out


ICON = {
    "good": '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="7" fill="var(--good)"/><path d="M4.8 8.2l2.1 2.1 4.3-4.6" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    "warning": '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1.5l7 12.5H1z" fill="var(--warning)" stroke="var(--warning)" stroke-width="1.5" stroke-linejoin="round"/><path d="M8 6v3.6" stroke="#0b0b0b" stroke-width="1.7" stroke-linecap="round"/><circle cx="8" cy="11.9" r="1" fill="#0b0b0b"/></svg>',
    "critical": '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="7" fill="var(--critical)"/><path d="M5.4 5.4l5.2 5.2M10.6 5.4l-5.2 5.2" stroke="#fff" stroke-width="1.8" stroke-linecap="round"/></svg>',
    "none": '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6" fill="none" stroke="var(--muted)" stroke-width="1.6"/></svg>',
}
CHEV = '<svg class="chev" viewBox="0 0 16 16" aria-hidden="true"><path d="M6 3.5L10.5 8 6 12.5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>'


def short_names(T: Dict[str, dict]) -> Dict[Tuple[str, str], str]:
    """The name to say for each thread, as the threads skill says it: the
    thread alone when no other thread has that name, else "project, thread"."""
    every = [(r["project"], r["thread"]) for z in T.values() for r in z["rows"] + z["parked"]]
    count: Dict[str, int] = {}
    for _, thread in every:
        count[thread.lower()] = count.get(thread.lower(), 0) + 1
    return {(p, t): (t if count[t.lower()] == 1 else "%s, %s" % (p, t)) for p, t in every}


def copy(label: str, text: str, say: str) -> str:
    """A button that copies a phrase for your assistant, or a command for your
    terminal. The page acts on nothing itself."""
    return '<button class="act" type="button" data-copy="%s" data-say="%s">%s</button>' % (E(text), E(say), E(label))


def card(id_: str, title: str, meta: str, body: str, open_: bool = True) -> str:
    return ('<details class="card" id="%s"%s><summary class="head">%s<h2>%s</h2><span class="meta">%s</span></summary>'
            '<div class="body">%s</div></details>' % (id_, " open" if open_ else "", CHEV, E(title), E(meta), body))


def meter(value: float, cap: float, label: str, right: str) -> str:
    pct = 0 if not cap else min(100.0, value / cap * 100)
    kind = "critical" if pct >= 90 else "warning" if pct >= 70 else ""
    return ('<div class="m"><span class="ink2">%s</span><span class="num">%s</span><div class="meter %s"><i style="width:%.1f%%"></i></div></div>'
            % (E(label), E(right), kind, pct))


# --------------------------------------------------------------------------- the page

CSS = r"""
:root{color-scheme:light;--page:#f4f3f0;--side:#ecebe6;--surface:#fcfcfb;--raise:#fff;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
--line:rgba(11,11,11,.10);--grid:#e1e0d9;--base:#c3c2b7;--accent:#2a78d6;--track:#cde2fb;--wash:rgba(42,120,214,.10);
--good:#0ca30c;--warning:#fab219;--critical:#d03b3b;--none:#e6e5df;--shadow:0 1px 2px rgba(11,11,11,.04),0 4px 16px rgba(11,11,11,.04)}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){color-scheme:dark;--page:#0d0d0d;--side:#131312;--surface:#1a1a19;--raise:#211f1e;
--ink:#fff;--ink2:#c3c2b7;--line:rgba(255,255,255,.10);--grid:#2c2c2a;--base:#383835;--accent:#3987e5;--track:#0d366b;--wash:rgba(57,135,229,.14);--none:#2a2a28;--shadow:none}}
:root[data-theme="dark"]{color-scheme:dark;--page:#0d0d0d;--side:#131312;--surface:#1a1a19;--raise:#211f1e;
--ink:#fff;--ink2:#c3c2b7;--line:rgba(255,255,255,.10);--grid:#2c2c2a;--base:#383835;--accent:#3987e5;--track:#0d366b;--wash:rgba(57,135,229,.14);--none:#2a2a28;--shadow:none}
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;background:var(--page);color:var(--ink);font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif;-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}a:hover{text-decoration:underline;text-underline-offset:2px}
.app{display:grid;grid-template-columns:240px minmax(0,1fr);min-height:100vh}
aside{position:sticky;top:0;height:100vh;overflow:auto;background:var(--side);border-right:1px solid var(--line);padding:22px 14px;display:flex;flex-direction:column;gap:18px}
.brand{padding:0 8px}.brand h1{font-size:15px;margin:0}.brand p{margin:2px 0 0;color:var(--muted);font-size:12px}
.overall{display:flex;align-items:center;gap:10px;padding:10px;border-radius:10px;background:var(--surface);border:1px solid var(--line)}
.overall svg{width:22px;height:22px;flex:none}.overall b{display:block;font-size:13px}.overall span{color:var(--ink2);font-size:12px}
nav{display:flex;flex-direction:column;gap:1px}
nav a{display:flex;align-items:center;gap:9px;padding:7px 10px;border-radius:8px;color:var(--ink2);font-size:13px}
nav a:hover{background:var(--wash);text-decoration:none;color:var(--ink)}nav a.on{background:var(--surface);color:var(--ink);box-shadow:inset 0 0 0 1px var(--line)}
nav a .n{margin-left:auto;font-size:11px;color:var(--muted)}nav .sub{padding-left:28px;font-size:12px}
.dot{width:8px;height:8px;border-radius:50%;flex:none;background:var(--none)}.dot.good{background:var(--good)}.dot.warning{background:var(--warning)}.dot.critical{background:var(--critical)}
.controls{margin-top:auto;display:flex;flex-direction:column;gap:10px;padding:0 6px}
.switch{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--ink2);cursor:pointer}
.switch input{appearance:none;width:30px;height:18px;border-radius:9px;background:var(--base);position:relative;cursor:pointer;margin:0}
.switch input::after{content:"";position:absolute;top:2px;left:2px;width:14px;height:14px;border-radius:50%;background:#fff;transition:left .15s}
.switch input:checked{background:var(--accent)}.switch input:checked::after{left:14px}
.seg{display:flex;background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:2px}
.seg button{flex:1;border:0;background:none;color:var(--ink2);font:inherit;font-size:12px;padding:4px 0;border-radius:6px;cursor:pointer}.seg button.on{background:var(--wash);color:var(--ink)}
main{padding:26px 30px 80px;min-width:0}
.stale{display:none;margin:0 0 16px;padding:10px 14px;border-radius:10px;background:var(--surface);border:1px solid var(--critical);font-weight:600}
.top{display:grid;grid-template-columns:minmax(220px,1.1fr) repeat(4,minmax(140px,1fr));gap:14px;margin-bottom:18px}
.hero,.tile{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:16px;box-shadow:var(--shadow);min-width:0}
.hero{display:flex;flex-direction:column;justify-content:space-between}
.hero .fig{font-size:48px;font-weight:650;line-height:1;letter-spacing:-.03em;display:flex;align-items:center;gap:12px}.hero .fig svg{width:28px;height:28px}
.hero .lbl,.tile .lbl{color:var(--ink2);font-size:12px}.hero .lbl{font-size:14px;margin-top:6px}
.tile .val{font-size:26px;font-weight:620;letter-spacing:-.02em;margin:4px 0 8px;display:flex;align-items:baseline;gap:8px}
.tile .val small{font-size:12px;font-weight:500;color:var(--muted)}.tile .sub{font-size:12px;color:var(--muted);margin-top:6px}
.meter{height:6px;border-radius:3px;background:var(--track);overflow:hidden}.meter i{display:block;height:100%;border-radius:3px;background:var(--accent)}
.meter.warning i{background:var(--warning)}.meter.critical i{background:var(--critical)}
.grid{display:grid;grid-template-columns:repeat(12,minmax(0,1fr));gap:16px;align-items:start}
.full{grid-column:span 12}.stack{grid-column:span 5;display:flex;flex-direction:column;gap:16px;min-width:0}.stack.l{grid-column:span 7}
.card{background:var(--surface);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow);min-width:0;scroll-margin-top:16px}
summary{list-style:none;cursor:pointer}summary::-webkit-details-marker{display:none}
.head{display:flex;align-items:center;gap:10px;padding:14px 16px}.head h2{font-size:14px;margin:0;font-weight:640}
.head .meta{color:var(--muted);font-size:12px;margin-left:auto;text-align:right}
.chev{width:16px;height:16px;flex:none;color:var(--muted);transition:transform .15s}details[open]>summary .chev{transform:rotate(90deg)}
.body{padding:0 16px 16px}.muted{color:var(--muted)}.ink2{color:var(--ink2)}.num{font-variant-numeric:tabular-nums}
.row{display:grid;align-items:center;gap:12px;padding:8px 2px;border-top:1px solid var(--grid)}.rows>.row:first-child{border-top:0}
.jobs .row{grid-template-columns:18px minmax(0,1fr) 180px 86px 140px}.jobs .row .status{overflow:hidden;text-overflow:ellipsis}
.row>svg,.item>svg{width:16px;height:16px}
.name{font-weight:560;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.name small{display:block;font-weight:400;color:var(--muted);font-size:12px}
.strip{display:flex;gap:2px}.strip i{width:11px;height:18px;border-radius:3px;background:var(--none);flex:none}
.strip i.good{background:var(--good)}.strip i.warning{background:var(--warning)}.strip i.critical{background:var(--critical)}.strip i:hover,.strip i:focus{outline:2px solid var(--ink)}
.status{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--ink2);white-space:nowrap}.status svg{width:14px;height:14px;flex:none}
.legend{display:flex;flex-wrap:wrap;gap:14px;margin-top:10px;color:var(--muted);font-size:12px}.legend span{display:inline-flex;align-items:center;gap:6px}
.legend i{width:10px;height:10px;border-radius:2px;background:var(--none)}.legend i.good{background:var(--good)}.legend i.warning{background:var(--warning)}.legend i.critical{background:var(--critical)}
.attn{display:flex;flex-direction:column;gap:6px}.attn a{display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:10px;background:var(--raise);border:1px solid var(--line)}
.attn a:hover{text-decoration:none;border-color:var(--base)}.attn svg{width:16px;height:16px;flex:none}
.zones{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:0 22px}
.zone>summary{display:flex;align-items:baseline;gap:8px;padding:10px 0 8px}
.zone>summary h3{margin:0;font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--ink2)}.zone>summary .meta{margin-left:auto;font-size:12px;color:var(--muted)}
.thread{display:grid;grid-template-columns:minmax(0,1fr) 80px 34px;align-items:center;gap:10px;padding:6px 0;border-top:1px solid var(--grid);font-size:13px}
.thread .t{min-width:0}.thread .t a{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.thread .t small{display:block;color:var(--muted);font-size:11.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.chip{display:inline-flex;align-items:center;font-size:11px;padding:0 6px;border-radius:999px;border:1px solid var(--line);color:var(--ink2);margin-left:4px}
.fresh{height:6px;border-radius:3px;background:var(--grid);position:relative}.fresh i{position:absolute;left:0;top:0;bottom:0;border-radius:3px;background:var(--good)}
.fresh.warning i{background:var(--warning)}.fresh.critical i{background:var(--critical)}
.group>summary{display:flex;align-items:center;gap:8px;padding:8px 10px;border-radius:8px;font-size:13px}.group>summary:hover{background:var(--wash)}
.group>summary .counts{margin-left:auto;display:flex;gap:6px}
.group ul{list-style:none;margin:2px 0 8px;padding:0 0 0 32px}.group li{display:flex;gap:8px;padding:5px 0;color:var(--ink2);font-size:12.5px;border-top:1px solid var(--grid)}
.group li:first-child{border-top:0}.group li svg{width:14px;height:14px;flex:none;margin-top:2px}
.clean{display:flex;align-items:center;gap:8px;color:var(--ink2);padding:8px 2px}.clean svg{width:16px;height:16px}
.bullet{display:grid;grid-template-columns:110px minmax(0,1fr) 40px;align-items:center;gap:10px;font-size:12.5px;padding:5px 0}
.bar{position:relative;height:10px;background:var(--track);border-radius:3px}.bar i{position:absolute;left:0;top:0;bottom:0;background:var(--accent);border-radius:3px}
.tiles{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
.item{display:flex;align-items:center;gap:9px;padding:8px 10px;border-radius:10px;background:var(--raise);border:1px solid var(--line);min-width:0}
.meters{display:flex;flex-direction:column;gap:12px}.meters .m{display:grid;grid-template-columns:1fr auto;gap:4px 10px;font-size:12px}.meters .m .meter{grid-column:1/-1}
table{border-collapse:collapse;width:100%;font-size:12.5px}th{text-align:left;color:var(--muted);font-weight:500;font-size:11.5px;padding:6px;border-bottom:1px solid var(--grid)}
td{padding:6px;border-bottom:1px solid var(--grid)}tr:last-child td{border-bottom:0}.r{text-align:right;font-variant-numeric:tabular-nums}.scroll{overflow-x:auto}
.acts{display:inline-flex;gap:4px;opacity:0;transition:opacity .12s}
.thread:hover .acts,.acts:focus-within,.acts.show{opacity:1}
.thread .t{position:relative}.thread .t .acts{position:absolute;right:0;top:50%;transform:translateY(-50%);background:var(--surface);padding-left:6px}
.act{font:inherit;font-size:11px;font-weight:560;line-height:1;padding:5px 8px;border-radius:7px;border:1px solid var(--line);background:var(--raise);color:var(--ink2);white-space:nowrap;cursor:pointer}
.act:hover{color:var(--ink);border-color:var(--base)}.act.wide{display:block;width:100%;padding:8px;font-size:12px}
.parked>summary{display:flex;align-items:center;gap:6px;padding:8px 0 4px;font-size:12px;color:var(--muted)}.parked>summary .n{margin-left:auto}
.parked .chev{width:13px;height:13px}.parked .thread{opacity:.8}
#toast{position:fixed;left:50%;bottom:22px;transform:translateX(-50%);background:var(--ink);color:var(--surface);font-size:13px;padding:9px 14px;border-radius:10px;opacity:0;transition:opacity .15s;pointer-events:none;z-index:10;max-width:90vw}
@media (hover:none){.acts{opacity:1}}
#tip{position:fixed;pointer-events:none;z-index:9;background:var(--ink);color:var(--surface);font-size:12px;padding:6px 9px;border-radius:7px;max-width:280px;opacity:0}
.only [data-ok="1"]{display:none}
.only .rows:not(:has([data-ok="0"]))::after,.only .zone:not(:has([data-ok="0"]))::after,.only .tiles:not(:has([data-ok="0"]))::after{content:"Nothing wrong here.";display:block;color:var(--muted);font-size:12px;padding:8px 2px}
@media (max-width:1180px){.top{grid-template-columns:repeat(2,minmax(0,1fr))}.hero{grid-column:span 2}.stack,.stack.l{grid-column:span 12}}
@media (max-width:820px){.app{grid-template-columns:1fr}aside{position:static;height:auto;border-right:0;border-bottom:1px solid var(--line)}nav{flex-direction:row;flex-wrap:wrap}nav .sub{display:none}.controls{margin-top:0}main{padding:16px}
.jobs .row{grid-template-columns:18px minmax(0,1fr) auto}.jobs .row>:nth-child(4){display:none}.jobs .row .strip{grid-column:2/-1;grid-row:2}.tiles{grid-template-columns:1fr}}
"""

JS = r"""
(function(){var root=document.documentElement,st={get:function(k){try{return localStorage.getItem(k)}catch(e){return null}},set:function(k,v){try{localStorage.setItem(k,v)}catch(e){}}};
function theme(t){if(t==='auto')root.removeAttribute('data-theme');else root.setAttribute('data-theme',t);document.querySelectorAll('.seg button').forEach(function(b){b.classList.toggle('on',b.dataset.t===t)});st.set('garrick-status-theme',t)}
theme(st.get('garrick-status-theme')||'auto');document.querySelectorAll('.seg button').forEach(function(b){b.onclick=function(){theme(b.dataset.t)}});
var only=document.getElementById('only');only.checked=st.get('garrick-status-only')==='1';function apply(){document.body.classList.toggle('only',only.checked);st.set('garrick-status-only',only.checked?'1':'0')}only.onchange=apply;apply();
document.querySelectorAll('details[id]').forEach(function(d){var s=st.get('garrick-fold-'+d.id);if(s==='0')d.open=false;if(s==='1')d.open=true;d.addEventListener('toggle',function(){st.set('garrick-fold-'+d.id,d.open?'1':'0')})});
var h=(Date.now()-new Date(document.body.dataset.built))/36e5,el=document.getElementById('age');if(el)el.textContent=h<1?Math.max(1,Math.round(h*60))+' min ago':h<48?Math.round(h)+' h ago':Math.round(h/24)+' days ago';
if(h>36){var s=document.getElementById('stale');s.style.display='block';s.textContent='Built '+Math.round(h)+' hours ago, so it may be out of date. Run status.py again to refresh it.'}
var tip=document.getElementById('tip');function show(e){var t=e.target.closest&&e.target.closest('[data-tip]');if(!t){tip.style.opacity=0;return}tip.textContent=t.dataset.tip;tip.style.opacity=1;
var r=t.getBoundingClientRect(),x=e.type==='focusin'?r.left+r.width/2:e.clientX,y=e.type==='focusin'?r.top:e.clientY,w=tip.offsetWidth;tip.style.left=Math.min(innerWidth-w-8,Math.max(8,x-w/2))+'px';tip.style.top=(y-tip.offsetHeight-12)+'px'}
document.addEventListener('mousemove',show);document.addEventListener('focusin',show);document.addEventListener('scroll',function(){tip.style.opacity=0},true);
var toast=document.getElementById('toast');function say(s){toast.textContent=s;toast.style.opacity=1;clearTimeout(say.t);say.t=setTimeout(function(){toast.style.opacity=0},2600)}
function put(text){if(navigator.clipboard&&window.isSecureContext){return navigator.clipboard.writeText(text)}var a=document.createElement('textarea');a.value=text;a.style.position='fixed';a.style.opacity=0;document.body.appendChild(a);a.select();try{document.execCommand('copy')}finally{document.body.removeChild(a)}return Promise.resolve()}
document.querySelectorAll('button[data-copy]').forEach(function(b){b.addEventListener('click',function(){put(b.dataset.copy).then(function(){say(b.dataset.say)},function(){say(b.dataset.copy)})})});
var links={};document.querySelectorAll('nav a[href^="#"]').forEach(function(a){links[a.getAttribute('href').slice(1)]=a});
if('IntersectionObserver' in window){var io=new IntersectionObserver(function(es){es.forEach(function(x){if(x.isIntersecting&&links[x.target.id]){Object.keys(links).forEach(function(k){links[k].classList.remove('on')});links[x.target.id].classList.add('on')}})},{rootMargin:'-20% 0px -70% 0px'});Object.keys(links).forEach(function(id){var t=document.getElementById(id);if(t)io.observe(t)})}
})();
"""


def build(ws: Path, vault: Optional[str] = None, now: Optional[dt.datetime] = None, folder: Optional[Path] = None) -> str:
    now = now or dt.datetime.now()
    agent = load_agent(ws)
    folder = folder or jobs_dir(agent)
    link = Links(ws, vault)
    T, TD, IB, C, R, W = threads(ws), todo(ws), inboxes(ws), check(ws), repos(ws), wikis(ws)
    J, L = jobs(folder, now), ledger(agent, folder, now)

    # ---- what needs attention, worst first
    attn = []
    if C and C.get("failed"):
        attn.append(("critical", "The check did not run", "#checks"))
    elif C and C.get("errors"):
        attn.append(("critical", "The check found %d error%s" % (C["errors"], "" if C["errors"] == 1 else "s"), "#checks"))
    for j in J:
        if j["state"] == "critical":
            attn.append(("critical", "%s: %s" % (j["name"], j["status"]), "#jobs"))
    if L:
        for e in L["refused_today"][-3:]:
            attn.append(("critical", "The spending cap stopped %s" % e.get("job", "a job"), "#calls"))
    waiting = sum(n for _, _, n in IB)
    if waiting:
        attn.append(("warning", "%d item%s waiting in the inboxes" % (waiting, "" if waiting == 1 else "s"), "#inboxes"))
    if C and C.get("warnings"):
        attn.append(("warning", "The check found %d warning%s" % (C["warnings"], "" if C["warnings"] == 1 else "s"), "#checks"))
    attn.sort(key=lambda a: a[0] != "critical")
    worst = "critical" if any(a[0] == "critical" for a in attn) else "warning" if attn else "good"

    live = sum(len(z["rows"]) for z in T.values())
    parked_n = sum(len(z["parked"]) for z in T.values())
    names = short_names(T)
    aging = sum(1 for z in T.values() for r in z["rows"] if r["updated"] and (now.date() - r["updated"]).days > 14)
    week = sum(1 for z in T.values() for r in z["rows"] if r["updated"] and (now.date() - r["updated"]).days <= 7)
    open_actions = sum(sum(t["counts"].values()) for t in TD.values())

    # ---- sidebar
    nav = [("overview", "Overview", worst, len(attn) or ""), ("threads", "Threads", "warning" if aging else "good", live)]
    navh = "".join('<a href="#%s"><span class="dot %s"></span>%s<span class="n">%s</span></a>' % (i, s, E(t), E(str(n))) for i, t, s, n in nav)
    navh += "".join('<a class="sub" href="#zone-%s">%s<span class="n">%d</span></a>' % (re.sub(r"\W+", "-", z.lower()), E(z), len(T[z]["rows"])) for z in T)
    more = [("checks", "Checks", "critical" if C and (C.get("errors") or C.get("failed")) else "warning" if C and C.get("warnings") else "good",
             (C.get("errors", 0) + C.get("warnings", 0)) if C and not C.get("failed") else ""),
            ("todo", "Open actions", "good", open_actions), ("inboxes", "Inboxes", "warning" if waiting else "good", waiting or "")]
    if J:
        more.append(("jobs", "Scheduled jobs", "critical" if any(j["state"] == "critical" for j in J) else "good", len(J)))
    if L:
        more.append(("calls", "Assistant calls", "critical" if L["refused_today"] else "good", L["day"]))
    more += [("repos", "Repositories", "good", ""), ("wikis", "Wikis", "good", "")]
    navh += "".join('<a href="#%s"><span class="dot %s"></span>%s<span class="n">%s</span></a>' % (i, s, E(t), E(str(n))) for i, t, s, n in more)
    overall = "All clear" if not attn else "%d need%s attention" % (len(attn), "s" if len(attn) == 1 else "")
    aside = ('<aside><div class="brand"><h1>Workspace status</h1><p>Built %s · <span id="age">just now</span></p></div>'
             '<div class="overall">%s<div><b>%s</b><span>%d live thread%s, %d touched this week</span></div></div><nav>%s</nav>'
             '<div class="controls">%s<label class="switch"><input type="checkbox" id="only"> Problems only</label>'
             '<div class="seg" role="group" aria-label="Theme"><button data-t="auto">Auto</button><button data-t="light">Light</button><button data-t="dark">Dark</button></div></div></aside>'
             % (now.strftime("%a %d %b, %H:%M"), ICON[worst], E(overall), live, "" if live == 1 else "s", week, navh,
                copy("Copy the rebuild command", "python3 System/status/status.py --workspace %s --open" % ws,
                     "Copied. Run it in a terminal to rebuild the page.").replace('class="act"', 'class="act wide"')))

    # ---- hero and tiles
    if attn:
        hero = '<div class="hero" id="overview"><div class="fig">%s%d</div><div class="lbl">%s attention</div></div>' % (
            ICON[worst], len(attn), "thing needs" if len(attn) == 1 else "things need")
    else:
        hero = '<div class="hero" id="overview"><div class="fig" style="font-size:38px">%sAll clear</div><div class="lbl">Nothing failing, waiting or broken.</div></div>' % ICON["good"]
    tiles = [("Live threads", "%d" % live, "%d touched this week, %d untouched for 14+ days" % (week, aging)),
             ("Open actions", "%d" % open_actions, "across %d zone%s" % (len(TD), "" if len(TD) == 1 else "s")),
             ("Waiting to be filed", "%d" % waiting, "in the zone and meeting inboxes"),
             ("Check", ("%d<small>errors</small>%d<small>warnings</small>" % (C.get("errors", 0), C.get("warnings", 0)))
              if C and not C.get("failed") else "—", "run just now" if C else "check.py not found")]
    if L:
        tiles[3] = ("Assistant calls, 24 h", "%d<small>of %g</small>" % (L["day"], L["caps"]["calls_day"]),
                    "$%.2f at list price" % L["cost_day"])
    top = '<div class="top">%s%s</div>' % (hero, "".join(
        '<div class="tile"><div class="lbl">%s</div><div class="val">%s</div><div class="sub">%s</div></div>' % (E(a), b, E(c)) for a, b, c in tiles))

    # ---- attention
    attn_card = ""
    if attn:
        attn_card = '<div class="full">%s</div>' % card("attention", "Needs attention", "%d item%s" % (len(attn), "" if len(attn) == 1 else "s"),
                                                       '<div class="attn">%s</div>' % "".join('<a href="%s">%s<span>%s</span></a>' % (h, ICON[k], E(t)) for k, t, h in attn))

    # ---- threads, one column per zone
    cols = ""
    for z, data in T.items():
        rows, na, nb = [], 0, 0
        for r in data["rows"]:
            days = (now.date() - r["updated"]).days if r["updated"] else None
            k = "good" if days is not None and days <= 14 else "warning" if days is not None and days <= 45 else "critical"
            na += k == "warning"
            nb += k == "critical"
            chips = "".join('<span class="chip">%s</span>' % E(p) for p in r["party"])
            tip = "%s, %s: updated %s" % (r["project"], r["thread"], r["updated"].strftime("%d %b %Y") if r["updated"] else "never")
            say = names[(r["project"], r["thread"])]
            acts = ('<span class="acts">%s%s</span>' % (copy("Open", "open " + say, "Copied “open %s”. Paste it to your assistant." % say),
                                                      copy("Park", "park " + say, "Copied “park %s”. Paste it to your assistant." % say)))
            rows.append('<div class="thread" data-ok="%d" data-tip="%s"><div class="t"><a href="%s">%s</a><small>%s%s</small>%s</div>'
                        '<div class="fresh %s"><i style="width:%.1f%%"></i></div><span class="num muted" style="text-align:right">%s</span></div>'
                        % (k == "good", E(tip), E(link(r["note"])), E(r["thread"]), E(r["project"]), chips, acts,
                           k, max(3.0, min(100.0, (days if days is not None else 60) / 60 * 100)), "%dd" % days if days is not None else "—"))
        held = []
        for r in data["parked"]:
            say = names[(r["project"], r["thread"])]
            days = (now.date() - r["updated"]).days if r["updated"] else None
            held.append('<div class="thread" data-ok="1"><div class="t"><a href="%s">%s</a><small>%s</small><span class="acts show">%s</span></div>'
                        '<span></span><span class="num muted" style="text-align:right">%s</span></div>'
                        % (E(link(r["note"])), E(r["thread"]), E(r["project"]),
                           copy("Wake", "wake " + say, "Copied “wake %s”. Paste it to your assistant." % say),
                           "%dd" % days if days is not None else "—"))
        slug = re.sub(r"\W+", "-", z.lower())
        parked_block = ('<details class="parked" id="parked-%s"><summary>%sParked<span class="n">%d</span></summary>%s</details>'
                        % (slug, CHEV, len(held), "".join(held))) if held else ""
        meta = "%d live" % len(data["rows"]) + (" · %d aging" % na if na else "") + (" · %d stale" % nb if nb else "") + (" · %d done" % data["done"] if data["done"] else "")
        cols += ('<details class="zone" id="zone-%s" open><summary>%s<h3>%s</h3><span class="meta">%s</span></summary>%s%s</details>'
                 % (slug, CHEV, E(z), E(meta), "".join(rows) or '<p class="muted">No live threads.</p>', parked_block))
    legend = ('<div class="legend"><span><i class="good"></i>updated in the last 14 days</span><span><i class="warning"></i>15 to 45 days</span>'
              '<span><i class="critical"></i>over 45 days</span><span>· the bar is days since the thread note was updated, full at 60</span></div>')
    threads_card = '<div class="full">%s</div>' % card("threads", "Threads", "%d live · %d parked · names, parties and dates only" % (live, parked_n),
                                                       '<div class="zones">%s</div>%s' % (cols, legend))

    # ---- checks
    if C is None:
        body = '<p class="muted">No <code>System/tools/check.py</code> in this workspace.</p>'
    elif C.get("failed"):
        body = '<div class="clean">%sThe check did not run. Run <code>python3 System/tools/check.py</code> to see why.</div>' % ICON["critical"]
    else:
        groups = {}
        for f in C.get("findings", []):
            groups.setdefault(f.get("check", "?"), []).append(f)
        body = "" if groups else '<div class="clean">%sNo problems found.</div>' % ICON["good"]
        for name, fs in groups.items():
            errs = sum(1 for f in fs if f.get("severity") == "error")
            counts = "".join('<span class="chip">%s %d</span>' % (ICON[k].replace("<svg ", '<svg width="12" height="12" '), n)
                             for k, n in (("critical", errs), ("warning", len(fs) - errs)) if n)
            lis = "".join('<li>%s<span>%s: %s</span></li>' % (ICON["critical" if f.get("severity") == "error" else "warning"], E(f.get("path", "")), E(f.get("message", ""))) for f in fs)
            body += ('<details class="group" data-ok="0"%s><summary>%s<b>%s</b><span class="counts">%s</span></summary><ul>%s</ul></details>'
                     % (" open" if errs else "", CHEV, E(C["titles"].get(name, name)), counts, lis))
    checks_card = card("checks", "Checks", "check.py, run as the page was built", body)

    # ---- open actions and inboxes
    tb = ""
    for z, t in TD.items():
        scale = max(list(t["counts"].values()) + [1]) * 1.08
        tb += '<div style="margin:8px 0 2px"><b><a href="%s">%s</a></b> <span class="muted" style="font-size:12px">changed %s</span></div>' % (
            E(link(t["file"])), E(z), age(t["when"], now))
        if not t["counts"]:
            tb += '<p class="muted" style="font-size:12px;margin:2px 0">Nothing open.</p>'
        for sec, n in t["counts"].items():
            tb += '<div class="bullet"><span class="ink2">%s</span><div class="bar"><i style="width:%.1f%%"></i></div><span class="num">%d</span></div>' % (E(sec), n / scale * 100, n)
    todo_card = card("todo", "Open actions", "unticked items in each zone's Todo.md", tb or '<p class="muted">No Todo.md found.</p>')
    ib = "".join('<a class="item" data-ok="%d" href="%s">%s<div class="name">%s<small>%s</small></div></a>' % (
        0 if n else 1, E(link(f)), ICON["warning" if n else "good"], E(name), "%d waiting" % n if n else "empty") for name, f, n in IB)
    inbox_card = card("inboxes", "Inboxes", "files waiting to be filed; say \"process the inbox\"", '<div class="tiles">%s</div>' % ib)

    # ---- jobs and calls, only when the jobs extra is in use
    jobs_card = calls_card = ""
    if J:
        rows = []
        for j in J:
            strip = "".join('<i class="%s" tabindex="0" data-tip="%s"></i>' % (s, E(t)) for s, t in day_cells(j["runs"], now))
            last = age(j["when"], now) if j["when"] else "never"
            rows.append('<div class="row" data-ok="%d">%s<div class="name"><a href="%s">%s</a><small>%s</small></div><div class="strip">%s</div>'
                        '<div class="ink2 num" data-tip="took %ss">%s</div><span class="status">%s%s</span></div>'
                        % (j["state"] == "good", ICON[j["state"]], E(link(j["log"])), E(j["name"]), E(j["schedule"]), strip,
                           E(str(j["seconds"])), E(last), ICON[j["state"]], E(j["status"])))
        legend = ('<div class="legend"><span><i class="good"></i>every run ok</span><span><i class="warning"></i>some failed, then recovered</span>'
                  '<span><i class="critical"></i>ended the day failed, or most runs failed</span><span><i></i>no run</span><span>· one cell per day, last %d days</span></div>' % DAYS)
        jobs_card = card("jobs", "Scheduled jobs", "heartbeats and logs in %s" % folder.name, '<div class="rows jobs">%s</div>%s' % ("".join(rows), legend))
    if L:
        c = L["caps"]
        m = (meter(L["day"], c["calls_day"], "Calls, last 24 h", "%d / %g" % (L["day"], c["calls_day"]))
             + meter(L["hour"], c["calls_hour"], "Calls, last hour", "%d / %g" % (L["hour"], c["calls_hour"]))
             + meter(L["cost_day"], c["cost_day"], "Cost, last 24 h", "$%.2f / $%g" % (L["cost_day"], c["cost_day"])))
        trs = "".join('<tr><td>%s</td><td class="r">%d</td><td class="r">$%.2f</td><td>%s</td><td class="r">%d</td><td class="r">%d</td></tr>'
                      % (E(job), d["calls"], d["cost"], E(", ".join(sorted(d["denied"]))) or '<span class="muted">none</span>', d["failed"], d["refused"])
                      for job, d in sorted(L["by"].items()))
        table = ('<div class="scroll"><table><thead><tr><th>Job</th><th class="r">Calls</th><th class="r">Cost</th><th>Refused tools</th>'
                 '<th class="r">Failed</th><th class="r">Capped</th></tr></thead><tbody>%s</tbody></table></div>' % trs) if trs else '<p class="muted">No calls yet.</p>'
        calls_card = card("calls", "Assistant calls", "ledger.jsonl, last %d days, list-price cost" % DAYS,
                          '<div class="meters">%s</div><div style="margin-top:14px">%s</div>' % (m, table))

    # ---- repositories and wikis
    rr = "".join('<div class="item" data-ok="1" data-tip="last commit %s">%s<div class="name">%s<small>%s</small></div></div>' % (
        E(age(r["last"], now)) if r["last"] else "never", ICON["good" if not r["dirty"] else "none"], E(r["name"]),
        "%d uncommitted" % r["dirty"] if r["dirty"] else "all committed") for r in R)
    repos_card = card("repos", "Repositories", "a ring means work not yet committed", '<div class="tiles">%s</div>' % rr if rr else '<p class="muted">No git repositories found.</p>')
    wr = "".join('<div class="row" style="grid-template-columns:1fr"><div class="name"><a href="%s">%s</a><small style="white-space:normal">%s</small></div></div>' % (
        E(link(log)), E(name), E(head)) for name, log, head in W)
    wikis_card = card("wikis", "Wikis", "newest entry in each log", '<div class="rows">%s</div>' % wr if wr else '<p class="muted">No wiki logs found.</p>')

    left = checks_card + jobs_card + wikis_card
    right = todo_card + inbox_card + calls_card + repos_card
    main = ('<main><div class="stale" id="stale"></div>%s<div class="grid">%s%s<div class="stack l">%s</div><div class="stack">%s</div></div></main>'
            % (top, attn_card, threads_card, left, right))
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Workspace status</title><style>%s</style></head><body data-built="%s"><div class="app">%s%s</div>'
            '<div id="tip" role="tooltip"></div><div id="toast" role="status"></div><script>%s</script></body></html>' % (CSS, now.isoformat(timespec="seconds"), aside, main, JS))


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Build the status page for a Garrick workspace.")
    ap.add_argument("--workspace", help="the workspace folder (default: GARRICK_WORKSPACE, or the folder this runs in)")
    ap.add_argument("--out", help="where to write the page (default: System/generated/status.html)")
    ap.add_argument("--obsidian", metavar="VAULT", help="link into Obsidian, with the workspace root opened as this vault")
    ap.add_argument("--open", action="store_true", help="open the page when it is built")
    args = ap.parse_args(argv)
    ws = find_workspace(args.workspace)
    generated = ws / "System" / "generated"
    out = Path(args.out).expanduser() if args.out else generated / "status.html"
    inside = str(out.resolve()).startswith(str(ws) + os.sep)
    if inside and not str(out.resolve()).startswith(str(generated.resolve()) + os.sep):
        print("status: %s is inside the workspace but not in System/generated/; this page shows every zone, "
              "so keep it where git and the wall check leave it alone." % out, file=sys.stderr)
    if inside and (ws / ".git").exists():
        probe = subprocess.run(["git", "-C", str(ws), "check-ignore", "-q", "--no-index", "System/generated/status.html"],
                               capture_output=True, text=True)
        if probe.returncode == 1:
            print("status: the workspace's .gitignore does not name System/generated/; add that line so the page "
                  "is never committed.", file=sys.stderr)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text(build(ws, args.obsidian), encoding="utf-8")
    os.replace(tmp, out)
    print(out)
    if args.open:
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        try:
            subprocess.run([opener, str(out)], check=False)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
