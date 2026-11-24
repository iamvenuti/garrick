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
