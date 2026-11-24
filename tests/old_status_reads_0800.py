"""The page's reads that 0.81.0 moved onto the core's readers (#650), frozen as v0.80.0 had them: the oracle the shadow tests
compare against, as `old_status_reads_0770.py` is for 0.77.0's sections.

Each area is `status.py`'s own code for one reader, copied word for word before it moved (`freeze.py`, by function name). They
read the workspace and this Mac by themselves, which the page no longer does; they stay here only so that a test can say the
core's readers and the old code agree. They borrow the page's small helpers (`HELPERS`) and its constants. Never edited: a
difference the reader should keep is written into the shadow test as a named rule, not changed here.

    old = old_reads(status, "JOBS")          # a namespace holding the area's old functions
"""
from __future__ import annotations

import datetime as dt
import json
import os
import plistlib
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def old_reads(status, *areas):
    """The old functions of the areas named, bound to the page module `status`, as a namespace."""
    g = {k: v for k, v in vars(status).items() if not k.startswith("__")}
    g["__file__"] = vars(status).get("__file__")          # find_workspace looks beside the page's own file
    g.update({"dt": dt, "re": re, "os": os, "json": json, "plistlib": plistlib, "subprocess": subprocess, "sys": sys, "Path": Path,
              "Dict": Dict, "List": List, "Optional": Optional, "Tuple": Tuple})
    for area in areas:
        exec(compile(AREAS[area], "old_status_reads_0800:" + area, "exec"), g)
    return g


AREAS = {}

AREAS['JOBS'] = r'''
def superseded(folder: Path, sched: Dict[str, dict]) -> Tuple[Dict[str, List[Tuple[str, float]]], set]:
    """Garrick's jobs that run under a new name now (#275): new name ->
    [(old name, cutoff)], the old names whose runs from before `cutoff`
    (epoch seconds) are read under the new one, and the old names no longer
    shown as a row of their own.

    Only what is Garrick's moves. The old name is folded in only when the
    new name's plist carries GARRICK_RENAMED_FROM naming it, which update.py's
    commands write into a plist it found running Garrick's own script under
    that name, or when a run under the new name recorded it (job.py's
    `renamed_from`), and only while no plist runs the old name. The cutoff is
    the first run under the new name (`renamed_at`), or before it the
    renamed plist's last change: a run under the old name after it is not
    Garrick's, and the old name keeps a row of its own while it has one. The
    retired evening build, `status`, is hidden once the nightly is there (a
    plist or a heartbeat), no plist runs `status`, and no `status` run has
    finished since the nightly's first run; its runs are never the
    nightly's. Nothing outside the jobs folder decides it, so deleting the
    plist set aside as .retired changes nothing."""
    earlier: Dict[str, List[Tuple[str, float]]] = {}
    hidden = set()

    def beat(name: str) -> dict:
        try:
            got = json.loads((folder / (name + ".heartbeat.json")).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return got if isinstance(got, dict) else {}

    def finished(name: str) -> Optional[float]:
        hb = beat(name)
        if isinstance(hb.get("finished_ts"), (int, float)):
            return float(hb["finished_ts"])
        try:
            return dt.datetime.strptime(str(hb.get("finished"))[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S").timestamp()
        except ValueError:
            return None

    for old, new in RENAMED_JOBS.items():
        if old in sched:
            continue
        hb = beat(new)
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
        last = finished(old)
        if last is None or last < cutoff:
            hidden.add(old)
    def first_run(name: str) -> Optional[float]:
        """When the job first ran, as far as its logs and heartbeat go back."""
        hb = beat(name)
        seen = [float(hb["renamed_at"])] if isinstance(hb.get("renamed_at"), (int, float)) else []
        if finished(name) is not None:
            seen.append(finished(name))
        for path in (folder / (name + ".log.1"), folder / (name + ".log")):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            m = next((LOGLINE.match(line) for line in text.splitlines() if LOGLINE.match(line)), None)
            if m:
                seen.append(dt.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").timestamp())
        return min(seen) if seen else None

    for old, new in RETIRED_JOBS.items():
        if old in sched or not (new in sched or (folder / (new + ".heartbeat.json")).is_file()):
            continue
        first, last = first_run(new), finished(old)
        if first is None or last is None or last < first:
            hidden.add(old)
    return earlier, hidden


def launchd_jobs(folder: Optional[Path] = None) -> Dict[str, dict]:
    """Job name -> what its launchd plist says: the schedule in words, how
    long before a missing run is late, whether it calls the assistant
    (--agent), the environment it runs with, its label, and the line its
    GARRICK_ABOUT gives, empty when it gives none. Only plists that run job.py;
    anything else in the folder, or a plist that does not read, is passed
    over. Elsewhere than macOS there are none, and schedules are unknown."""
    out: Dict[str, dict] = {}
    folder = folder or launch_agents()
    if not folder.is_dir():
        return out
    for plist in sorted(folder.glob("*.plist")):
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
        words, late = when(p)
        env = env if isinstance(env, dict) else {}
        out[args[at + 1]] = {"schedule": words, "late": late, "agent": "--agent" in flags, "env": env, "plist": plist,
                             "label": str(p.get("Label") or plist.stem), "about": env["GARRICK_ABOUT"].strip() if isinstance(env.get("GARRICK_ABOUT"), str) else ""}
    return out


def history(folder: Path, name: str, now: dt.datetime,
            earlier: Tuple[Tuple[str, float], ...] = ()) -> List[Tuple[dt.datetime, int, bool]]:
    """(when, exit, quiet) for each run the job's logs record in the last DAYS
    days, and those the logs of the names it ran under before record from
    before each one's cutoff (superseded())."""
    since = now - dt.timedelta(days=DAYS)
    runs = []
    for n, cutoff in (*earlier, (name, None)):
        for path in (folder / (n + ".log.1"), folder / (n + ".log")):
            if not path.is_file():
                continue
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                m = LOGLINE.match(line)
                if not m:
                    continue
                when = dt.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
                if when >= since and (cutoff is None or when.timestamp() < cutoff):
                    runs.append((when, int(m.group(3)) if m.group(3) else 75, bool(m.group(5))))
    return runs


def lock_held(lock: Path, now: dt.datetime) -> bool:
    """Whether a run holds the job's lock now. With the jobs extra loaded,
    job.py's own rule decides: a run whose job.py lives holds its lock
    whatever the time on it says, since that time runs on while a Mac
    sleeps. Without it, the record in `until`, "<until> <pid> [<started>]",
    holds until that time while its process lives, and a lock without a
    record counts for three hours."""
    if not lock.is_dir():
        return False
    job = sys.modules.get("job")
    if job is not None and hasattr(job, "holder"):
        try:
            return bool(job.holder(lock, 3 * 3600)[0])
        except Exception:
            pass
    try:
        words = (lock / "until").read_text(encoding="utf-8").split()
        if now.timestamp() >= float(words[0]):
            return False
        return pid_alive(int(words[1])) if len(words) > 1 and words[1].isdigit() else True
    except (OSError, ValueError, IndexError):
        try:
            return now.timestamp() - lock.stat().st_mtime < 3 * 3600
        except OSError:
            return False


def steps_now(folder: Path, name: str) -> Optional[List[dict]]:
    """The steps a run still going has reported so far (job.py's
    `<name>.steps.json`, which the nightly job writes after each step), or
    None. The nightly rebuilds this page as its last step, before its
    heartbeat is written, so this is how a step that failed tonight shows."""
    try:
        data = json.loads((folder / (name + ".steps.json")).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return [x for x in data if isinstance(x, dict)] if isinstance(data, list) else None


def job_log(folder: Path, name: str, earlier: Tuple[Tuple[str, float], ...] = ()) -> Path:
    """The job's log; before a renamed job's first run under its new name,
    the log it left under the newest of its old ones."""
    for n in (name, *(o for o, _ in reversed(earlier))):
        if (folder / (n + ".log")).is_file():
            return folder / (n + ".log")
    return folder / (name + ".log")


def log_tail(path: Path, lines: int = 30, width: int = 300) -> List[str]:
    """The last lines of a job's log, read from its end, each cut to `width`
    characters; none when there is no log. A read that starts mid-file drops
    its first line, which is likely a part of one."""
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


def jobs(folder: Path, now: dt.datetime, sched: Optional[Dict[str, dict]] = None) -> List[dict]:
    """One row per heartbeat in the jobs folder. A run whose exit job.py
    calls fine (the heartbeat's `ok` or `quiet`), or whose code the plist
    lists in GARRICK_QUIET_EXITS, is fine; a failure is said in the
    heartbeat's own `reason` when it has one. An idle job (the heartbeat's
    `idle`; from an older job.py, `idle_days` past the plist's
    GARRICK_IDLE_DAYS, 7) is a warning. A job whose lock is held is running now.
    A job whose plist runs job.py but which has no heartbeat yet, never run or
    not since its plist was added, gets a row too: neutral, "not run yet",
    with the schedule its plist gives. A heartbeat with no plist is a job a
    hook or a session starts: "started by a session", and the user's. Each
    row carries its plist's label, GARRICK_ABOUT and --agent, and whether it
    is Garrick's (garrick_job). A job of Garrick's that ran under an older
    name is one row under its new name, with the older runs in its strip
    (superseded())."""
    sched = launchd_jobs() if sched is None else sched
    earlier, hidden = superseded(folder, sched) if folder.is_dir() else ({}, set())
    beats: Dict[str, Tuple[dict, Optional[dt.datetime]]] = {}
    for beat in sorted(folder.glob("*.heartbeat.json")) if folder.is_dir() else []:
        try:
            hb = json.loads(beat.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(hb, dict):
            continue
        name = hb.get("job") or beat.name[:-len(".heartbeat.json")]
        when = None
        try:
            when = dt.datetime.strptime(str(hb.get("finished"))[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
        beats[name] = (hb, when)
    for new, olds in earlier.items():             # the newest heartbeat of a renamed job, under its new name
        got = ([beats[new]] if new in beats else []) + [beats[o] for o, cut in olds if o in beats and o in hidden]
        if got:
            beats[new] = max(got, key=lambda b: b[1] or dt.datetime.min)
    out = []
    for name, (hb, when) in sorted(beats.items()):
        if name in hidden:
            continue
        olds = tuple(earlier.get(name, ()))
        code = int(hb.get("exit", -1)) if str(hb.get("exit", "")).lstrip("-").isdigit() else -1
        env = sched[name].get("env", {}) if name in sched else {}
        # job.py says itself whether the exit was fine (`ok`, `quiet`); an older
        # heartbeat leaves it to the codes and the plist's GARRICK_QUIET_EXITS.
        quiet = set(quiet_exits(env)) | ({code} if hb.get("quiet") is True or (hb.get("ok") is True and code not in OK_EXITS) else set())
        words, limit = (sched[name]["schedule"], sched[name]["late"]) if name in sched else ("started by a session", None)
        try:
            idle = int(hb.get("idle_days") or 0)
        except (TypeError, ValueError):
            idle = 0
        if when and limit and now - when > limit:
            state, status = "critical", "late: last ran %s" % age(when, now)
        elif code not in OK_EXITS and code not in quiet:
            reason = hb.get("reason") if isinstance(hb.get("reason"), str) and hb.get("reason") else EXIT.get(code, "failed")
            state, status = "critical", "exit %d: %s" % (code, reason)
        elif (hb["idle"] is True) if isinstance(hb.get("idle"), bool) else (idle and idle >= idle_limit(env)):
            state, status = "warning", "idle %s" % counted(idle, "day")
        elif code in OK_EXITS and hb.get("agent") is True and isinstance(hb.get("reason"), str) and hb["reason"]:
            state, status = "warning", hb["reason"]               # exit 0, but the assistant was refused a tool (#567)
        elif code in quiet and code not in OK_EXITS:
            state, status = "good", "ok, exit %d is quiet" % code
        elif hb.get("no_call") is True:
            state, status = "good", "ok, called no assistant"   # fine when there was nothing to do
        else:
            state, status = "good", "ok"
        running = lock_held(folder / (name + ".lock"), now)
        steps = hb["steps"] if isinstance(hb.get("steps"), list) else None
        unrun = [x for x in steps or [] if isinstance(x, dict) and str(x.get("skipped") or "").startswith("not executable")]
        if unrun and state == "good":             # the job is fine, but a step of yours never runs (#276)
            state, status = "warning", "%s skipped: %s" % (unrun[0].get("step"), unrun[0]["skipped"])
        live = steps_now(folder, name) if running else None
        if live is not None:                      # the nightly building this page mid-run says what failed so far
            steps = live
            if failed_steps(live):
                state, status = "critical", "%s failed in the run under way" % failed_steps(live)
        say, tip = job_say(state, status, code)
        out.append({"name": name, "when": when, "seconds": hb.get("seconds"), "state": state, "status": status,
                    "say": say, "tip": tip,
                    "title": job_title(name, hb, env), "code": code, "since": failing_since(hb, when),
                    "reason": hb["reason"] if isinstance(hb.get("title"), str) and isinstance(hb.get("reason"), str) else "",
                    "schedule": words, "runs": history(folder, name, now, olds), "log": job_log(folder, name, olds),
                    "quiet": tuple(sorted(quiet)), "running": running,
                    "idle": state == "warning" and status.startswith("idle"), "steps": steps,
                    **plist_facts(sched.get(name), name)})
    beaten = {j["name"] for j in out}
    for name, plist in sched.items():
        if name not in beaten:
            olds = tuple(earlier.get(name, ()))
            running = lock_held(folder / (name + ".lock"), now)
            live = steps_now(folder, name) if running else None
            state, status = ("critical", "%s failed in the run under way" % failed_steps(live)) if failed_steps(live) \
                else ("none", "not run yet")
            out.append({"name": name, "when": None, "seconds": None, "state": state, "status": status,
                        "say": status, "tip": "",
                        "title": job_title(name, {}, plist.get("env", {})), "code": None, "since": None, "reason": "",
                        "schedule": plist["schedule"], "runs": history(folder, name, now, olds),
                        "log": job_log(folder, name, olds),
                        "quiet": quiet_exits(plist.get("env", {})), "running": running,
                        "idle": False, "steps": live, **plist_facts(plist, name)})
    return sorted(out, key=lambda j: j["name"].casefold())

'''

AREAS['APP'] = r'''
def drifted(ws: Path) -> List[dict]:
    """What drift.py last found worth a look, from System/generated/drift.json,
    which it writes when run from a session or the app: a launchd job may
    not read a cloud folder, so the page never compares anything itself.
    Each with the sentence its Needs attention row says, which copy changed
    and when for one that drifted, and where its row leads: the thread's row
    on the Threads card for a file in a thread, else the project's (#323).
    `both` says drift.json names the two copies, for Show both."""
    try:
        data = json.loads(ws.joinpath(*DRIFT).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for f in data.get("files", []) if isinstance(data, dict) else []:
        if not (isinstance(f, dict) and f.get("state") in DRIFT_SAY):
            continue
        project, name = str(f.get("project") or "?"), str(f.get("file") or "")
        thread = str(f.get("thread") or "")
        parts = name.split("/")
        if not thread and len(parts) > 2 and parts[0] == "Threads":
            thread = parts[1]                       # kept in a thread's folder, named from the project's
        where = project + (", " + thread if thread else "")
        here, shared = drift_day(f.get("here_changed")), drift_day(f.get("shared_changed"))
        if f["state"] == "drifted" and here and shared and f.get("newer") in ("here", "shared"):
            first, then = ("the shared copy", "the copy here") if f["newer"] == "shared" else ("the copy here", "the shared copy")
            said = "%s: %s: %s changed on %s, after %s (%s)" % (
                where, parts[-1], first, shared if f["newer"] == "shared" else here, then, here if f["newer"] == "shared" else shared)
        else:
            said = "%s: %s %s" % (where, name or "published.md", DRIFT_SAY[f["state"]])
        out.append({"text": said, "zone": str(f.get("zone") or ""), "project": project, "thread": thread,
                    "ledger": str(f.get("thread") or ""), "file": name,
                    "both": f["state"] == "drifted" and bool(f.get("here")) and bool(f.get("shared"))})
    return out


def workspace_stamp(ws: Path) -> dict:
    """The installer's stamp, System/garrick-version.json, or {}."""
    try:
        stamp = json.loads(ws.joinpath("System", "garrick-version.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return stamp if isinstance(stamp, dict) else {}


def inbox_state(ws: Path, now: dt.datetime, folder: Optional[Path] = None) -> Optional[dict]:
    """What the last background run of Process the Inbox left for the page (#634): `running`, `done` or `failed`, with its one
    sentence and its figures for each place, never over two. None for none, for one over a day old, and for a `running` that no
    process holds the run's lock for any more (a run that died)."""
    try:
        data = json.loads(ws.joinpath(*INBOX_STATE).read_text(encoding="utf-8"))
        at = dt.datetime.fromisoformat(str(data.get("at")))
    except (OSError, ValueError, AttributeError, TypeError):
        return None
    if not isinstance(data, dict) or data.get("state") not in ("running", "done", "failed") or abs((now - at).total_seconds()) > 86400:
        return None
    if data["state"] == "running":
        try:
            import fcntl
            fd = os.open(str((folder or jobs_dir(None)) / "inbox-run.lock"), os.O_RDWR)
        except (OSError, ImportError):
            return None
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return None                 # nobody holds it: the run is not going
        except OSError:
            pass
        finally:
            os.close(fd)
    return data


def kept_check(store: Path, ws: Path, now: dt.datetime) -> Optional[dict]:
    """The result a build kept in `store` for this workspace, of whatever age,
    marked `kept` and carrying `at`, when the check ran; None when there is
    none, or it cannot be read (#382)."""
    try:
        data = json.loads(store.read_text(encoding="utf-8"))
        at, result = float(data["at"]), data["result"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if data.get("workspace") != str(ws) or not isinstance(result, dict) or result.get("failed"):
        return None
    if now.timestamp() < at:
        return None                           # from the future: not a result to trust
    return dict(result, at=at, kept=True)


def check(ws: Path, store: Optional[Path] = None, reuse: Optional[float] = None,
          now: Optional[dt.datetime] = None) -> Optional[dict]:
    """check.py's findings, run as the page is built. With `--quick`, where the
    workspace's check.py has it: every check but the comparison of wording
    with the meetings, which on a large workspace is most of a full run's
    time, and which the commit hook and a scheduled full check still make.

    With `store`, a result is kept there for the next build, and with `reuse`
    as well, the one kept there is shown, whatever its age, and the check is
    never run: what scaffold.py's and correct.py's rebuilds ask for (#260,
    #382), so a thread a session made reaches the page in seconds. The
    builds that run the check keep it fresh. With no result kept, such a
    build says there is none yet (`pending`) rather than claim a pass. A
    check that did not run is never kept."""
    tool = ws / "System" / "tools" / "check.py"
    if not tool.is_file():
        return None
    now = now or dt.datetime.now()
    if store is not None and reuse:
        kept = kept_check(store, ws, now)
        return kept if kept is not None else {"failed": True, "pending": True}
    try:
        quick = ["--quick"] if "--quick" in tool.read_text(encoding="utf-8") else []
    except OSError:
        quick = []
    try:
        proc = subprocess.run([sys.executable, str(tool), "--root", str(ws), "--json"] + quick,
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
    if store is not None:
        try:
            write_page(store, json.dumps({"workspace": str(ws), "at": now.timestamp(), "result": data}, ensure_ascii=False) + "\n")
        except OSError:
            pass                              # the next build runs the check again
    return data


def forecast_items(ws: Path, day: dt.date) -> List[dict]:
    """The standing findings of the Nurture record of `day` that weigh anything, each with its scope: the one-pass
    forecast, as nurture.py's day_outcome() counts it. The list the card's lines and the queue are both made from, so
    a line's number and its queue's are one. [] without a record or a nurture.py that keeps them."""
    lib = nurture_lib(ws)
    N = lib[0] if lib is not None else None
    if N is None or not getattr(N, "REPORTS", None) or not callable(getattr(N, "debt_settings", None)) or not callable(getattr(N, "debt_scope", None)):
        return []
    try:
        rec = json.loads(Path(ws).joinpath(*N.REPORTS, "%s.json" % day.isoformat()).read_text(encoding="utf-8"))
        weights, _ = N.debt_settings(Path(ws))
    except (OSError, ValueError):
        return []
    out = []
    for f in rec.get("standing") or [] if isinstance(rec, dict) else []:
        kind = str(f.get("kind", "")) if isinstance(f, dict) else ""
        # a wall is on the card whatever its weight: the weight sets the debt figure, not whether a wall shows
        if kind and (kind == "wall" or weights.get(kind, getattr(N, "UNKNOWN_WEIGHT", 1))):
            path = re.sub(r":\d+$", "", str(f.get("path", "")))
            out.append({"kind": kind, "path": path, "line": str(f.get("line") or ""), "check": str(f.get("check") or ""),
                        "scope": N.debt_scope(path)})
    return out


def chase_days_of(ws: Path, zone: str) -> int:
    """Days *Still waiting* and *Give it a week* move a chase day on: `todo-chase-days` of the check settings, a week
    when it is 0 or not set, so a button always moves the day."""
    try:
        value = json.loads((ws / "System" / "garrick-checks.json").read_text(encoding="utf-8")).get("todo-chase-days")
    except (OSError, ValueError, AttributeError):
        return 7
    value = value.get(zone) if isinstance(value, dict) else value
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 7


def followup_records(z: dict) -> Dict[str, dict]:
    """The zone's follow-up records by line key; {} when there are none or the file does not read."""
    folder = Path(z["file"]).parent if z.get("file") else None
    try:
        found = json.loads((folder / ".todo-followups.json").read_text(encoding="utf-8")) if folder else {}
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in found.items() if isinstance(v, dict)} if isinstance(found, dict) else {}


def guide_tab(ws: Path) -> Tuple[str, str]:
    """The Guide tab: the docs this workspace was installed with, in System/garrick-docs/,
    its links to Garrick's own files pointing at the release it runs. (The tab's body,
    the pages that wait at the end of the page until it opens.)"""
    gd = guide_mod()
    try:
        text = ws.joinpath(*CHANGELOG).read_text(encoding="utf-8")
    except OSError:
        text = None
    ref = gd.release_ref(text, edge=workspace_stamp(ws).get("from") in ("clone", "adopted"))
    body, held = gd.guide(ws.joinpath(*gd.DOCS), ref)
    return body, held

'''

AREAS['FIND'] = r'''
def is_workspace(folder: Path) -> bool:
    return (folder / "System" / "rules.md").is_file() and (folder / "Zones").is_dir()


def find_workspace(given: Optional[str]) -> Path:
    """The folder named, or the one this runs in. A named folder must hold
    System/rules.md and Zones/, so a mistyped path stops here instead of
    gaining a System/generated/ of its own."""
    for how, cand in (("--workspace", given), ("GARRICK_WORKSPACE", os.environ.get("GARRICK_WORKSPACE"))):
        if cand:
            folder = Path(cand).expanduser().resolve()
            if not is_workspace(folder):
                raise SystemExit("status: %s (from %s) is not a Garrick workspace: it has no System/rules.md "
                                 "and Zones/ folder. Check the path." % (folder, how))
            return folder
    here = Path.cwd().resolve()
    for folder in (here, *here.parents):
        if is_workspace(folder):
            return folder
    for folder in (Path(__file__).resolve().parent, *Path(__file__).resolve().parents):
        if is_workspace(folder):
            return folder
    raise SystemExit("status: no workspace found. Pass --workspace, set GARRICK_WORKSPACE, or run it from inside one.")


def visible_dirs(folder: Path) -> List[Path]:
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.is_dir() and not p.name.startswith((".", "_")))


def threads(ws: Path, model: Optional[dict] = None) -> Dict[str, dict]:
    """Per zone, what the Threads card and Your work draw: every live thread's project, name, party and the date its
    note was last updated; whether the note has a Resume here block, with that block's own date, and its unwrapped
    checkpoint, with `touched`, the later of `updated:` and that checkpoint's day (#650: all of it decided by the
    view model, System/tools/view.py, which reads the notes; this page only draws it). A project with no thread note
    is its own single thread, read from its hub. A project whose hub says parked holds every live thread in it
    parked too, each marked `held`; `held` per zone names those projects.

    For the Threads card's search (#140), names only: `finished` per zone, the threads `done` counts, and
    `projects`, each project by name with its hub's status (live, parked or done), its spoken form and whether it is
    its own single thread (`own`). Nothing of a note's body is read here."""
    model = model or view_model(ws, ("work",))
    if model is None:
        # A half-finished update: this page is new and System/tools has no view.py or work.py yet. The page builds and says so.
        return {zone.name: {"rows": [], "parked": [], "done": 0, "folder": zone, "held": [], "finished": [], "projects": {},
                            "hubs": [], "needs_update": True} for zone in visible_dirs(ws / "Zones")}
    out = {}
    for z in model["zones"]:
        work = z["work"]
        out[z["name"]] = {"rows": [piece_row(ws, p) for p in work if p["shown"] == "row"],
                          "parked": [piece_row(ws, p) for p in work if p["shown"] == "parked"],
                          "done": z["done"], "folder": ws / "Zones" / z["name"], "held": list(z["held"]),
                          "finished": [piece_row(ws, p) for p in work if p["shown"] == "done"],
                          "projects": {name: dict(v, hub=ws / v["hub"] if v["hub"] else None, party=list(v["party"]))
                                       for name, v in z["projects"].items()},
                          "open_links": [list(x) for x in z["open_links"]],
                          "hubs": [piece_row(ws, p) for p in work if p["shown"] == "hub"]}
    return out

'''

AREAS['FM'] = r'''
def _value(raw: str):
    """One frontmatter value for the fallback parser: a trailing comment
    dropped, quotes taken off, [a, b] read as a list."""
    quote = None
    for i, ch in enumerate(raw):
        if quote:
            quote = None if ch == quote else quote
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or raw[i - 1].isspace()):
            raw = raw[:i]
            break
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]") and not raw.startswith("[["):
        return [v.strip().strip("\"'") for v in raw[1:-1].split(",") if v.strip()]
    return raw.strip("\"'")


def frontmatter(path: Path, ws: Optional[Path] = None) -> dict:
    """The note's frontmatter: the workspace's own parser (garrick_lib in
    System/tools) when it is there, a small one otherwise that also drops
    trailing comments and reads block lists. Only frontmatter is ever read
    from a note here."""
    lib = workspace_lib(ws)
    if lib is not None:
        try:
            return lib.parse_frontmatter(path) or {}
        except Exception:
            pass
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    # Lines end where garrick_lib's parse_frontmatter_text ends them, as YAML
    # does: at \n, \r\n or a lone \r, never at U+2028 and the like (#330).
    lines = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        return {}
    out: dict = {}
    key = None
    for line in lines[1:]:
        if line in ("---", "..."):             # a `---` alone at the margin closes it, as for YAML
            break
        item = re.match(r"^\s*-\s+(.*)$", line)
        if item and key is not None:
            out[key] = (out[key] if isinstance(out.get(key), list) else []) + [_value(item.group(1))]
            continue
        m = re.match(r"^([A-Za-z_][\w-]*)\s*:(.*)$", line)
        key = m.group(1) if m else None
        if m:
            out[key] = _value(m.group(2))
    return out

'''
