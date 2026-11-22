#!/usr/bin/env python3
"""A scheduled job: file what arrived at an address kept for reading into
Knowledge, and skip what is too thin to keep.

    python3 reading_sweep.py --workspace /Users/<you>/Garrick --zone Work [--zone Personal]

The mail fetcher saves a mailbox configured with "reading": true as
`reading-<name>.eml` in a zone's Inbox. For each zone, this job lists those
items and sets aside any whose sender's domain names a party: the rules say
to ask before treating a party's mail as published, and nobody is here to
ask, so it waits in the Inbox for the next session. The rest go to one
assistant call per zone, which runs the knowledge skill's Ingest on each
(`intake.py file-reading`, then the source page, its concepts and entities,
the index and the log) or takes it out with `intake.py skip --reason`. Then
one commit in the Knowledge wiki's repository, of the files the call reported
it wrote (`WROTE <path>` lines), by name, through its hooks.

Run it through job.py:

    python3 job.py gr-reading-sweep --agent --cwd /Users/<you>/Garrick -- \\
        /usr/bin/python3 /Users/<you>/Garrick/System/jobs/reading_sweep.py \\
        --workspace /Users/<you>/Garrick --zone Work

It reports the items it filed and skipped, so a reading address that stopped
receiving mail is noticed within GARRICK_IDLE_DAYS. Exit codes: 0; the
assistant's own; 3 for an answer without its closing line; 1 for a refused
commit; 64 for an unknown zone or a workspace without the intake skill.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Set, Tuple

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import agent  # noqa: E402

SENTINEL = "END OF READING"
EXIT_INCOMPLETE = 3
COUNTS = re.compile(r"^FILED (\d+) SKIPPED (\d+)\s*$", re.M)
WROTE = re.compile(r"^WROTE (.+?)\s*$", re.M)
SHOWN = 5                       # the most paths a summary line names
INTAKE = ("System", "skills", "intake", "intake.py")


def intake(workspace: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(workspace.joinpath(*INTAKE)), "--root", str(workspace)] + list(args),
                          capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL)


def party_domain(workspace: Path, senders: List[str]) -> bool:
    """Whether any sender's domain names a party, as the workspace's own
    library reads the Parties table."""
    sys.path.insert(0, str(workspace / "System" / "tools"))
    try:
        import garrick_lib as lib
    finally:
        sys.path.pop(0)
    ctx = lib.load_context(workspace)
    for sender in senders:
        m = re.search(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)", sender or "")
        if m and lib.parties_for_domain(ctx, m.group(1).lower()):
            return True
    return False


def waiting(workspace: Path, zone: str) -> Tuple[List[str], List[str]]:
    """(items to read, items left for a person: from a party's domain, or
    not readable) in the zone's Inbox, among those the fetcher marked."""
    r = intake(workspace, "list", "--json")
    items = [i for i in json.loads(r.stdout or "[]") if i.get("zone") == zone and i.get("route") == "reading"]
    mine, theirs = [], []
    for item in items:
        p = intake(workspace, "parse", "--file", str(workspace / item["file"]))
        try:
            parsed = json.loads(p.stdout)
        except ValueError:
            theirs.append(item["file"])
            continue
        (theirs if party_domain(workspace, parsed.get("from") or []) else mine).append(item["file"])
    return mine, theirs


def prompt_for(zone: str, files: List[str]) -> str:
    listing = "\n".join("- %s" % f for f in files)
    return (
        "You are running unattended as a scheduled job, and nobody is watching. Each file below arrived at an "
        "address kept for reading, in the %s zone's Inbox, and nothing in it is anyone's confidence:\n\n%s\n\n"
        "For each one, follow the knowledge skill (System/skills/knowledge/SKILL.md), *Ingest*:\n"
        "- if it is worth keeping, file it with `python3 System/skills/intake/intake.py file-reading --file <it>` "
        "and finish what it drafted as the skill says from step 4: the source page, the concept and entity pages "
        "it touches, the index and the log;\n"
        "- if it is too thin to keep (a one-line promotion, an empty notice, a receipt), take it out with "
        "`python3 System/skills/intake/intake.py skip --file <it> --reason \"<a few words>\"`.\n"
        "Write only in Wikis/Knowledge/. Never file anything in Meetings or a project, never commit, never send.\n\n"
        "Then write one line for each file you wrote, changed or filed in Wikis/Knowledge/, exactly: WROTE <its path from "
        "the workspace root>. Only the files you list are committed; nothing else is.\n"
        "Then write one line exactly: FILED <n> SKIPPED <n>, and after it one line that says exactly %s"
        % (zone, listing, SENTINEL))


def counts(text: str) -> Optional[Tuple[int, int]]:
    lines = (text or "").rstrip().splitlines()
    if not lines or lines[-1].strip() != SENTINEL:
        return None
    found = COUNTS.findall(text)
    return (int(found[-1][0]), int(found[-1][1])) if found else None


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    # The Knowledge wiki has no wall hook by design (it crosses every wall): only the environment is cleaned.
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, timeout=300,
                          stdin=subprocess.DEVNULL, env=agent.own_repo_env())


def changes(repo: Path, rel: str) -> Set[str]:
    """The paths changed in the Knowledge wiki, as git names them, unquoted:
    `status -z` keeps a space or an accent in a name as it is."""
    out = git(repo, "status", "--porcelain", "-z", "--no-renames", "--untracked-files=all", "--", rel).stdout
    return {entry[3:] for entry in out.split("\0") if len(entry) > 3}


def reported(text: str, workspace: Path, top: Path, rel: str) -> List[str]:
    """The paths the run says it wrote (`WROTE <path>` lines), as git names them from the top of the repository. A path
    that is not under the Knowledge wiki is not taken."""
    out: List[str] = []
    for raw in WROTE.findall(text or ""):
        full = Path(os.path.normpath(str(workspace / raw.strip().strip("`")))) if not raw.strip().startswith("/") else Path(os.path.normpath(raw.strip()))
        try:
            got = full.resolve().relative_to(top.resolve()).as_posix()
        except (ValueError, OSError):
            continue
        if (rel in (".", "") or got == rel or got.startswith(rel.rstrip("/") + "/")) and got not in out:
            out.append(got)
    return out


def digest(top: Path, paths) -> dict:
    out = {}
    for p in paths:
        try:
            out[p] = hashlib.sha1((top / p).read_bytes()).hexdigest()
        except OSError:
            out[p] = ""
    return out


def named(paths: List[str]) -> str:
    shown = ", ".join(paths[:SHOWN])
    return shown + (" and %d more" % (len(paths) - SHOWN) if len(paths) > SHOWN else "")


def commit(workspace: Path, before: Set[str], top: Path, rel: str, filed: int, skipped: int, wrote: Optional[List[str]] = None,
           seen: Optional[dict] = None) -> Tuple[Optional[str], str]:
    """Commit what the call reported it wrote in Knowledge, by name. Returns (None when done or nothing to commit, else why
    not; a note for the summary line). Only a reported path that changed during the call is committed: a path the wiki holds
    changed that the run did not report (another writer's edit) is left as it is and named, and a reported path that was
    already changed before the call is committed only if the call changed it (#640). A run that reports none commits nothing."""
    now = changes(top, rel)
    before_hash = seen or {}
    after = digest(top, now & before)
    wrote = wrote or []
    paths = sorted(p for p in wrote if p in now and (p not in before or after.get(p) != before_hash.get(p)))
    notes = []
    stale = sorted(p for p in wrote if p in now and p in before and p not in paths)
    other = sorted(p for p in now if p not in paths and p not in stale and p not in before)
    if not wrote:
        notes.append("nothing was reported as filed, so nothing was committed")
    if stale:
        notes.append("%s was already changed before the call, so it was left as it is" % named(stale))
    if other:
        notes.append("%s changed during the call and was left as %s" % (named(other), "it is" if len(other) == 1 else "they are"))
    note = "; ".join(notes)
    if not paths:
        return None, note
    git(top, "add", "-A", "--", *paths)
    c = git(top, "commit", "-q", "-m", "Knowledge: reading swept; %d filed, %d skipped" % (filed, skipped), "--", *paths)
    if c.returncode != 0:
        git(top, "reset", "-q", "--", *paths)
        why = (c.stderr or c.stdout).strip().splitlines()
        return (why[-1] if why else "git refused"), note
    return None, note


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="File what reached an address kept for reading into Knowledge.")
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--zone", action="append", required=True)
    ap.add_argument("--tier", default="sonnet", choices=agent.TIERS)
    args = ap.parse_args(argv)
    workspace = Path(args.workspace).expanduser().resolve()
    if not workspace.joinpath(*INTAKE).is_file():
        print("reading_sweep: %s has no intake skill; update Garrick first" % workspace, file=sys.stderr)
        return agent.EXIT_USAGE
    knowledge = workspace / "Wikis" / "Knowledge"
    top = Path(git(knowledge, "rev-parse", "--show-toplevel").stdout.strip() or knowledge)
    rel = knowledge.resolve().relative_to(top.resolve()).as_posix() or "."
    worst, total = 0, 0
    for name in args.zone:
        zone = next((z for z in (workspace / "Zones").iterdir() if z.is_dir() and z.name.lower() == name.lower()), None)
        if zone is None:
            print("reading_sweep: there is no zone called %s" % name, file=sys.stderr)
            return agent.EXIT_USAGE
        mine, theirs = waiting(workspace, zone.name)
        for f in theirs:
            print("%s: left for you, from a party's domain: %s" % (zone.name, f))
        if not mine:
            print("%s: nothing to read" % zone.name)
            continue
        before = changes(top, rel)
        seen = digest(top, before)
        code, text = agent.run(args.tier, prompt_for(zone.name, mine), cwd=workspace,
                               allow=["Read", "Grep", "Glob", "Edit", "Write",
                                      "Bash(python3 System/skills/intake/intake.py:*)"])
        found = counts(text) if code == 0 else None
        if found is None:
            code = code or EXIT_INCOMPLETE
            print("%s: no complete answer (exit %d); what it wrote is left uncommitted for you to look at" % (zone.name, code))
            worst = worst or code
            continue
        filed, skipped = found
        why, note = commit(workspace, before, top, rel, filed, skipped, reported(text, workspace, top, rel), seen)
        print("%s: %d filed, %d skipped%s%s" % (zone.name, filed, skipped, "; not committed: " + why if why else "",
                                                " (%s)" % note if note else ""))
        if why:
            worst = worst or 1
        total += filed + skipped
    if worst == 0:
        agent.report_items(total)
    return worst


if __name__ == "__main__":
    sys.exit(main())
