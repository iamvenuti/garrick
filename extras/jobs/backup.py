#!/usr/bin/env python3
"""Commit and push every repository of the workspace, holding back only what
the wall check refuses. A scheduled job; it calls no assistant.

    python3 backup.py --workspace /Users/<you>/Garrick

Run it through job.py, twice a day, so it has a log, a lock and a watchdog:

    python3 job.py backup --cwd /Users/<you>/Garrick -- \\
        /usr/bin/python3 /Users/<you>/Garrick/System/jobs/backup.py --workspace /Users/<you>/Garrick

with GARRICK_QUIET_EXITS="5 6" in its environment, so the two quiet outcomes
below raise no failure notice.

For each repository with changes (the root, each zone, the wikis), it stages
everything, runs the workspace's own wall check on what is staged
(`check.py --staged --walls-only --json`), unstages each file the check
refuses, and commits the rest. The commit goes through the repository's own
pre-commit hook: never `--no-verify`. Then it pushes, when the repository
has a remote: never with force, and never after a rebase or a merge. A
remote that has moved ahead is left alone and reported.

Exit codes, the worst outcome deciding:

    0   every change committed and pushed
    5   quiet: some files held back by the wall check, the rest backed up
    6   quiet: offline; committed, every push held for the next run
    1   a commit or push failed, or a remote has moved ahead

Held files are named in one notice, sent again only when the list changes.
Offline for more than OFFLINE_DAYS days turns into a failure, so a push that
fails for another reason (a sign-in, a renamed remote) is not quiet forever.
The next run that pushes after an offline spell says so. The state lives in
`backup.state.json` in the jobs folder, outside the workspace.

Standard library only, Python 3.9 or later.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import agent  # noqa: E402
import job  # noqa: E402

OK, FAILED, HELD, OFFLINE = 0, 1, 5, 6
WORST = (FAILED, OFFLINE, HELD, OK)          # the worst first
OFFLINE_DAYS = 3
STATE = "backup.state.json"
TIMEOUT = 300


def git(repo: Path, *args: str, timeout: int = TIMEOUT) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, timeout=timeout,
                          stdin=subprocess.DEVNULL)


def repositories(ws: Path) -> List[Path]:
    """The workspace's own repositories: its root, each zone, and the wikis
    (one repository for both, or one each)."""
    out = [ws] if (ws / ".git").exists() else []
    zones = ws / "Zones"
    if zones.is_dir():
        out += [z for z in sorted(zones.iterdir()) if z.is_dir() and not z.name.startswith((".", "_"))
                and (z / ".git").exists()]
    wikis = ws / "Wikis"
    if (wikis / ".git").exists():
        out.append(wikis)
    elif wikis.is_dir():
        out += [w for w in sorted(wikis.iterdir()) if w.is_dir() and (w / ".git").exists()]
    return out


def refused(ws: Path, repo: Path) -> Tuple[List[Tuple[str, str]], Optional[str]]:
    """(file relative to the repository, why) for each staged file the wall
    check refuses, or an error when the check could not run."""
    check = ws / "System" / "tools" / "check.py"
    if not check.is_file():
        return [], "the wall check, System/tools/check.py, is missing"
    try:
        r = subprocess.run([sys.executable, str(check), "--root", str(ws), "--staged", "--walls-only", "--json"],
                           cwd=str(repo), capture_output=True, text=True, timeout=TIMEOUT, stdin=subprocess.DEVNULL)
        found = json.loads(r.stdout).get("findings", [])
    except (OSError, ValueError, AttributeError, subprocess.TimeoutExpired) as exc:
        return [], "the wall check did not run: %s" % exc
    out = []
    for f in found:
        if f.get("severity") != "error":
            continue
        try:
            name = (ws / f["path"]).resolve().relative_to(repo.resolve()).as_posix()
        except (KeyError, ValueError):
            return [], "the wall check refused %s, which is not in this repository" % f.get("path")
        out.append((name, f.get("message", "")))
    return out, None


def has_head(repo: Path) -> bool:
    return git(repo, "rev-parse", "-q", "--verify", "HEAD").returncode == 0


def unstage(repo: Path, name: str) -> bool:
    """Take one file out of the index, leaving it on disk as it is."""
    if has_head(repo):
        return git(repo, "reset", "-q", "--", name).returncode == 0
    return git(repo, "rm", "-q", "--cached", "--", name).returncode == 0      # nothing committed yet


def commit(ws: Path, repo: Path, when: str, say) -> Tuple[int, List[str]]:
    """Stage, hold back what the walls refuse, commit the rest. (outcome,
    held files relative to the workspace)."""
    if not git(repo, "status", "--porcelain").stdout.strip():
        return OK, []
    git(repo, "add", "-A")
    held: List[str] = []
    for _ in range(5):                     # a file held can be what made another refuse
        found, error = refused(ws, repo)
        if error:
            git(repo, "reset", "-q") if has_head(repo) else git(repo, "rm", "-r", "-q", "--cached", ".")
            say("%s: %s; nothing committed" % (rel(ws, repo), error))
            return FAILED, held
        if not found:
            break
        for name, why in found:
            if unstage(repo, name):
                held.append(rel(ws, repo / name))
                say("%s: held back %s: %s" % (rel(ws, repo), name, why))
    else:
        git(repo, "reset", "-q")
        say("%s: the wall check still refuses after holding files back; nothing committed" % rel(ws, repo))
        return FAILED, held
    if git(repo, "diff", "--cached", "--quiet").returncode == 0:
        return (HELD if held else OK), held
    r = git(repo, "commit", "-q", "-m", "Backup, %s" % when)
    if r.returncode != 0:
        git(repo, "reset", "-q")
        say("%s: the commit failed: %s" % (rel(ws, repo), (r.stderr or r.stdout).strip().splitlines()[-1:] or "?"))
        return FAILED, held
    say("%s: committed" % rel(ws, repo))
    return (HELD if held else OK), held


def push(ws: Path, repo: Path, say) -> int:
    """Push what is committed, when there is a remote. Never force, never
    rebase or merge: a remote that moved ahead is reported and left."""
    remotes = git(repo, "remote").stdout.split()
    if not remotes:
        return OK
    branch = git(repo, "symbolic-ref", "-q", "--short", "HEAD").stdout.strip()
    if not branch:
        say("%s: not on a branch; nothing pushed" % rel(ws, repo))
        return FAILED
    upstream = git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    remote = upstream.stdout.strip().split("/", 1)[0] if upstream.returncode == 0 else (
        "origin" if "origin" in remotes else remotes[0])
    if git(repo, "fetch", "-q", remote).returncode != 0:
        say("%s: could not reach %s; the push waits for the next run" % (rel(ws, repo), remote))
        return OFFLINE
    if upstream.returncode == 0:
        behind = git(repo, "rev-list", "--count", "HEAD..@{u}").stdout.strip()
        if behind and behind != "0":
            say("%s: %s has %s commit(s) this copy lacks; nothing pushed. Pull by hand." % (rel(ws, repo), remote, behind))
            return FAILED
        if git(repo, "rev-list", "--count", "@{u}..HEAD").stdout.strip() == "0":
            return OK
        r = git(repo, "push", "-q", remote, branch)
    else:
        r = git(repo, "push", "-q", "-u", remote, branch)
    if r.returncode != 0:
        say("%s: the push failed: %s" % (rel(ws, repo), " ".join((r.stderr or r.stdout).strip().splitlines()[-1:])))
        return FAILED
    say("%s: pushed to %s" % (rel(ws, repo), remote))
    return OK


def rel(ws: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(ws.resolve()).as_posix() or "."
    except ValueError:
        return str(path)


def worst(codes: List[int]) -> int:
    return next((c for c in WORST if c in codes), OK)


def read_state(folder: Path) -> dict:
    try:
        data = json.loads((folder / STATE).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_state(folder: Path, data: dict) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / (STATE + ".tmp")
    tmp.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, folder / STATE)


def run(ws: Path, now: Optional[datetime.datetime] = None, folder: Optional[Path] = None, say=print) -> int:
    now = now or datetime.datetime.now()
    folder = folder or agent.jobs_dir()
    state = read_state(folder)
    when = now.strftime("%Y-%m-%d %H:%M")
    codes, held = [], []
    repos = repositories(ws)
    for repo in repos:
        code, kept = commit(ws, repo, when, say)
        held += kept
        codes.append(code)
        if code != FAILED:
            codes.append(push(ws, repo, say))
    outcome = worst(codes)
    if sorted(held) != sorted(state.get("held", [])):
        if held:
            job.notify("message", "Backup held files back",
                       "The wall check refused %d file(s); the rest is backed up: %s" % (len(held), ", ".join(held)),
                       job="backup")
        state["held"] = sorted(held)
    if outcome == OFFLINE:
        since = state.setdefault("offline_since", now.isoformat(timespec="seconds"))
        days = (now - datetime.datetime.fromisoformat(since)).total_seconds() / 86400
        if days > OFFLINE_DAYS:
            say("no push has gone through for %d days; look at the remotes" % days)
            outcome = FAILED
    elif "offline_since" in state and FAILED not in codes and OFFLINE not in codes:
        since = state.pop("offline_since")
        say("pushed again, held since %s" % since)
        job.notify("recovered", "Backup pushed again", "Every push held since %s has gone through." % since,
                   job="backup")
    write_state(folder, state)
    agent.report_items(len(repos))            # the repositories looked at: none means a wrong --workspace
    return outcome


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Commit and push every repository of the workspace.")
    ap.add_argument("--workspace", required=True, help="the workspace's folder")
    a = ap.parse_args(argv)
    ws = Path(a.workspace).expanduser().resolve()
    if not (ws / "System" / "rules.md").is_file():
        print("backup: %s is not a Garrick workspace" % ws, file=sys.stderr)
        return 64
    return run(ws)


if __name__ == "__main__":
    sys.exit(main())
