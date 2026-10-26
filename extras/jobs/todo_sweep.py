#!/usr/bin/env python3
"""A scheduled job: keep each zone's Todo.md complete and short, one zone at
a time, as the todo skill's Sweep does.

    python3 todo_sweep.py --workspace /Users/<you>/Garrick --zone Work [--zone Personal] [--digest]

For each zone: one assistant call that sweeps that zone's Meetings pages of
the last 30 days and its live threads' Next action rows into Todo.md,
appending under Inbox and Waiting on and folding repeats into the line
already there; then the skill's script, which expires, archives and tidies
with no assistant; then one commit in the zone, through its wall check, of
Todo.md and archive/ by name. Nothing else is written. A zone whose call
fails is left as it was, and its script and commit do not run.

Each zone that swept then sends a "Todo refreshed" notice, its counts and
nothing of its lines, and with --digest its morning summary (`todo.py
digest`) as the "Todo summary" notice: both through System/tools/
notifications.py, to this Mac when Settings › Notifications has them on
(a GARRICK_NOTIFY_CMD command runs in the zone's folder with GARRICK_ZONE set).
The summary goes also when the zone's call failed, opening with a line that
says so, since a silent morning reads like a clear one. A Waiting on line
gets a ⏳ day `todo-chase-days` ahead when its source gives none (7, or 0
for none).

Run it through job.py, so it has a log, a lock and a watchdog:

    python3 job.py todo-sweep --agent --cwd /Users/<you>/Garrick -- \\
        /usr/bin/python3 /Users/<you>/Garrick/System/jobs/todo_sweep.py \\
        --workspace /Users/<you>/Garrick --zone Work

The count it reports for the idle alarm is the lines it added, folded,
expired and archived. Exit codes: 0; the assistant's own; 3 when an answer
came back without its closing line (the zone's file is put back); 1 when a
commit was refused; 64 for an unknown zone or a workspace without the skill.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import agent  # noqa: E402

SENTINEL = "END OF SWEEP"
EXIT_INCOMPLETE = 3
COUNTS = re.compile(r"^ADDED (\d+) FOLDED (\d+)\s*$", re.M)


def chase_rule(days: int) -> str:
    if days == 0:
        return "with #waiting, and a ⏳ day to chase only when the source gives one: never one of your own"
    return "with #waiting and a ⏳ day to chase, %d days from today when the source gives none" % days


def prompt_for(zone: str, today: str, chase_days: int = 7) -> str:
    return (
        "You are running unattended as a scheduled job, and nobody is watching. Follow the todo skill's "
        "*Sweep* in System/skills/todo/SKILL.md, steps 2 to 6, for the %s zone only, today %s:\n\n"
        "- read Zones/%s/Todo.md first;\n"
        "- read the Meetings pages in Wikis/Meetings/wiki/sources/ whose `zone` is %s and whose date is in the "
        "last 30 days, each one's actions table, and the `Next action` row of each live thread note in Zones/%s/; "
        "never a page whose zone is another, and nothing else;\n"
        "- keep only rows with one named owner and a concrete verb; the user's go under `## Inbox`, what a named "
        "person owes the user under `## Waiting on` %s;\n"
        "- before adding a line, compare it with every open line, the lines ticked in the last 14 days and the "
        "rest of this batch; a match is not added, and its source goes on the line already there as "
        "`(also in [[<slug>]])`, the only change you may make to an existing line;\n"
        "- edit Zones/%s/Todo.md and no other file; never reword, move, tick or delete a line; do not commit.\n\n"
        "Then write one line exactly: ADDED <n> FOLDED <n>, with the numbers of lines you added and folded, "
        "and after it one line that says exactly %s"
        % (zone, today, zone, zone, zone, chase_rule(chase_days), zone, SENTINEL))


def counts(text: str) -> Optional[Tuple[int, int]]:
    """(added, folded) from a complete answer, or None when it is not."""
    lines = (text or "").rstrip().splitlines()
    if not lines or lines[-1].strip() != SENTINEL:
        return None
    found = COUNTS.findall(text)
    return (int(found[-1][0]), int(found[-1][1])) if found else None


def git(zone: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(zone), capture_output=True, text=True, timeout=300,
                          stdin=subprocess.DEVNULL)


def find_zone(workspace: Path, name: str) -> Optional[Path]:
    zones = workspace / "Zones"
    match = [z for z in (zones.iterdir() if zones.is_dir() else []) if z.is_dir() and z.name.lower() == name.lower()
             and not z.name.startswith(("_", ".")) and (z / "Todo.md").is_file()]
    return match[0] if match else None


def skill(workspace: Path):
    """The workspace's own todo.py, for the settings it reads."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("garrick_todo_skill", str(workspace / "System" / "skills" / "todo" / "todo.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def send_digest(workspace: Path, zone: Path, failed: bool) -> None:
    """The zone's morning summary, the "Todo summary" notice."""
    import job
    script = workspace / "System" / "skills" / "todo" / "todo.py"
    r = subprocess.run([sys.executable, str(script), "digest", "--zone", zone.name, "--root", str(workspace)],
                       capture_output=True, text=True, timeout=300)
    text = r.stdout.strip() if r.returncode == 0 else "The digest could not be built: %s" % (r.stderr.strip()[-200:])
    if failed:
        text = "The sweep did not finish this morning; this is the list as it stood.\n\n" + text
    job.notify("digest", "Todo", text, zone=zone, event="todo-summary")


def send_refreshed(zone: Path, said: str) -> None:
    """The "Todo refreshed" notice: what the sweep did to the zone's list, in counts."""
    import job
    job.notify("refreshed", "Todo refreshed", said, zone=zone, event="todo-refreshed")


def sweep_zone(workspace: Path, zone: Path, tier: str, today: str) -> Tuple[int, int, str]:
    """(exit code, lines changed, what to log) for one zone."""
    todo = zone / "Todo.md"
    before = todo.read_bytes()
    days = skill(workspace).chase_days(workspace, zone.name)
    code, text = agent.run(tier, prompt_for(zone.name, today, days), allow=["Read", "Grep", "Glob", "Edit"], cwd=workspace)
    found = counts(text) if code == 0 else None
    if found is None:
        now = todo.read_bytes()
        kept = set(now.splitlines())
        if now != before and all(line in kept for line in before.splitlines()):
            # Half a sweep only adds lines. Put the list back only when nothing it held was changed
            # meanwhile, by this call or another session; otherwise leave it for a person to look at.
            todo.write_bytes(before)
        return code or EXIT_INCOMPLETE, 0, "%s: no complete sweep (exit %d); Todo.md left as it was" % (zone.name, code or EXIT_INCOMPLETE)
    added, folded = found
    script = workspace / "System" / "skills" / "todo" / "todo.py"
    r = subprocess.run([sys.executable, str(script), "all", "--zone", zone.name, "--root", str(workspace), "--json"],
                       capture_output=True, text=True, timeout=300)
    try:
        done = json.loads(r.stdout)
    except ValueError:
        return 1, 0, "%s: todo.py failed: %s" % (zone.name, (r.stderr or r.stdout).strip()[-200:])
    changed = added + folded + done.get("expired", 0) + done.get("archived", 0)
    said = "%s: %d added, %d folded, %d expired, %d archived" % (
        zone.name, added, folded, done.get("expired", 0), done.get("archived", 0))
    paths = ["Todo.md"] + (["archive"] if (zone / "archive").is_dir() else [])
    if not git(zone, "status", "--porcelain", "--", *paths).stdout.strip():
        return 0, changed, said + "; nothing to commit"
    git(zone, "add", "-A", "--", *paths)
    c = git(zone, "commit", "-q", "-m", "%s: actions swept; %d added, %d folded, %d expired, %d archived" % (
        zone.name, added, folded, done.get("expired", 0), done.get("archived", 0)), "--", *paths)   # these alone
    if c.returncode != 0:
        git(zone, "reset", "-q", "--", *paths)
        why = (c.stderr or c.stdout).strip().splitlines()
        return 1, changed, said + "; not committed: %s" % (why[-1] if why else "git refused")
    return 0, changed, said + "; committed"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Sweep each zone's actions into its Todo.md, then tidy it.")
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--zone", action="append", required=True, help="a zone to sweep; repeat for more")
    ap.add_argument("--tier", default="sonnet", choices=agent.TIERS)
    ap.add_argument("--digest", action="store_true", help="then send each zone's morning summary as the Todo summary notice")
    args = ap.parse_args(argv)
    workspace = Path(args.workspace).expanduser().resolve()
    if not (workspace / "System" / "skills" / "todo" / "todo.py").is_file():
        print("todo_sweep: %s has no System/skills/todo/todo.py; update Garrick first" % workspace, file=sys.stderr)
        return agent.EXIT_USAGE
    zones = []
    for name in args.zone:
        zone = find_zone(workspace, name)
        if zone is None:
            print("todo_sweep: there is no zone %s with a Todo.md in %s" % (name, workspace), file=sys.stderr)
            return agent.EXIT_USAGE
        zones.append(zone)
    today = datetime.date.today().isoformat()
    worst, total = 0, 0
    for zone in zones:
        code, changed, said = sweep_zone(workspace, zone, args.tier, today)
        print(said)
        if code == 0:
            send_refreshed(zone, said)
        if args.digest:
            send_digest(workspace, zone, failed=code != 0)
        total += changed
        worst = worst or code
    if worst == 0:
        agent.report_items(total)
    return worst


if __name__ == "__main__":
    sys.exit(main())
