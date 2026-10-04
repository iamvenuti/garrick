#!/usr/bin/env python3
"""An example scheduled job: a "what's open" brief, one zone at a time.

    python3 whats_open.py --workspace /Users/<you>/Garrick --zone Work [--zone Personal] [--out FOLDER]

For each zone named, the script lists the live threads itself, with no
assistant involved, then asks the assistant to read only those threads'
Resume here blocks and write a short brief: what is open, the next action,
any deadline. One assistant call per zone, so no single turn ever holds two
zones, and one file per zone. Nothing in the workspace is written: the brief
goes to `briefs/` in the jobs folder (or `--out`), outside every zone, to be
read and thrown away. A zone with nothing open costs no call.

It needs no connector, so it runs the same under Claude or Codex. The number
of live threads goes to job.py's idle alarm. Run it through job.py, so it has
a log, a lock and a watchdog:

    python3 job.py whats-open --agent --cwd /Users/<you>/Garrick -- \\
        /usr/bin/python3 /Users/<you>/Garrick/System/jobs/whats_open.py \\
        --workspace /Users/<you>/Garrick --zone Work

Exit codes: 0, or the assistant's own, or 3 when an answer came back without
its closing line (nothing is written then), or 64 for an unknown zone.
"""

from __future__ import annotations

import argparse
import datetime
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import agent  # noqa: E402

# The workspace's own frontmatter parser, so a status reads here as it reads
# everywhere else: installed, System/jobs/ sits beside System/tools/; in
# Garrick's source, extras/jobs/ reaches template/System/tools/. Failing both,
# main() looks in the workspace it is given.
for _tools in (HERE.parent / "tools", HERE.parent.parent / "template" / "System" / "tools"):
    if (_tools / "garrick_lib.py").is_file():
        sys.path.insert(1, str(_tools))
        break
try:
    from garrick_lib import parse_frontmatter  # noqa: E402
except ImportError:
    parse_frontmatter = None

SENTINEL = "END OF BRIEF"
EXIT_INCOMPLETE = 3


def load_parser(workspace: Path) -> bool:
    """Make sure the workspace's frontmatter parser is loaded."""
    global parse_frontmatter
    if parse_frontmatter is None and (workspace / "System" / "tools" / "garrick_lib.py").is_file():
        sys.path.insert(1, str(workspace / "System" / "tools"))
        from garrick_lib import parse_frontmatter as found
        parse_frontmatter = found
    return parse_frontmatter is not None


NOT_LIVE = ("done", "parked")  # finished, or set aside until it is woken


def live_threads(zone: Path) -> List[Tuple[str, Path]]:
    """(short label, note) for every live thread in the zone, newest first. A
    thread note is the .md file named after its folder; a path part starting
    with `_` is a template; `done` means finished and `parked` set aside, and
    neither is live."""
    found = []
    for note in zone.glob("*/Threads/*/*.md"):
        project, thread = note.parts[-4], note.parent.name
        if note.stem != thread or project.startswith(("_", ".")) or thread.startswith(("_", ".")):
            continue
        fm = parse_frontmatter(note)
        if str(fm.get("status") or "").strip().lower() in NOT_LIVE:
            continue
        found.append((str(fm.get("updated") or ""), "%s, %s" % (project, thread), note))
    found.sort(key=lambda row: row[0], reverse=True)
    return [(label, note) for _, label, note in found]


def find_zone(workspace: Path, name: str) -> Optional[Path]:
    zones = workspace / "Zones"
    if not zones.is_dir():
        return None
    match = [z for z in zones.iterdir() if z.is_dir() and z.name.lower() == name.strip().lower()
             and not z.name.startswith(("_", "."))]
    return match[0] if match else None


def prompt_for(zone: str, workspace: Path, threads: List[Tuple[str, Path]], today: str) -> str:
    listing = "\n".join("- %s: %s" % (label, note.relative_to(workspace)) for label, note in threads)
    return (
        "You are running unattended as a scheduled job, and nobody is watching. "
        "Read the `### Resume here` block of each thread note listed below, and nothing else: "
        "not the hubs, not the meetings, not any other zone. All of them are in the %s zone.\n\n"
        "%s\n\n"
        "Write a brief in Markdown, for the owner to read first thing:\n\n"
        "- a first line: # What's open in %s, %s\n"
        "- one line per thread, most urgent first: its short name, its next action, and its deadline "
        "if the block gives one;\n"
        "- a last line starting \"Waiting on others:\" that names the threads blocked on someone, "
        "or says none.\n\n"
        "Use only what the blocks say. Where a block is missing or unclear, say so on that thread's "
        "line instead of guessing. Do not edit, create or delete any file. "
        "After the brief, write one line that says exactly %s"
        % (zone, listing, zone, today, SENTINEL)
    )


def finish(text: str) -> Optional[str]:
    """The brief without its closing line, or None when the line is missing."""
    lines = text.rstrip().splitlines()
    if not lines or lines[-1].strip() != SENTINEL:
        return None
    return "\n".join(lines[:-1]).rstrip() + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="A what's-open brief per zone, written outside the workspace.")
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--zone", action="append", required=True, help="a zone to brief; repeat for more")
    ap.add_argument("--out", help="folder for the briefs (default: briefs/ in the jobs folder)")
    ap.add_argument("--tier", default="sonnet", choices=agent.TIERS)
    args = ap.parse_args(argv)

    workspace = Path(args.workspace).expanduser().resolve()
    out = Path(args.out).expanduser() if args.out else agent.jobs_dir() / "briefs"
    today = datetime.date.today().isoformat()
    if not load_parser(workspace):
        print("whats_open: no System/tools/garrick_lib.py in %s; is it a Garrick workspace?" % workspace,
              file=sys.stderr)
        return agent.EXIT_USAGE
    zones = []
    for name in args.zone:
        zone = find_zone(workspace, name)
        if zone is None:
            print("whats_open: there is no zone called %s in %s" % (name, workspace), file=sys.stderr)
            return agent.EXIT_USAGE
        zones.append(zone)

    worst, total = 0, 0
    for zone in zones:
        threads = live_threads(zone)
        total += len(threads)
        target = out / ("whats-open-%s-%s.md" % (re.sub(r"[^a-z0-9]+", "-", zone.name.lower()).strip("-"), today))
        if not threads:
            out.mkdir(parents=True, exist_ok=True)
            target.write_text("# What's open in %s, %s\n\nNothing open.\n" % (zone.name, today), encoding="utf-8")
            print("%s: nothing open, no call made" % zone.name)
            continue
        code, text = agent.run(args.tier, prompt_for(zone.name, workspace, threads, today),
                               allow=["Read"], cwd=workspace)
        brief = finish(text) if code == 0 else None
        if brief is None:
            code = code or EXIT_INCOMPLETE
            print("whats_open: %s: no complete brief (exit %d); nothing written" % (zone.name, code))
            worst = worst or code
            continue
        out.mkdir(parents=True, exist_ok=True)
        target.write_text(brief, encoding="utf-8")
        print("%s: %d open, brief in %s" % (zone.name, len(threads), target))
    if worst == 0:
        agent.report_items(total)
    return worst


if __name__ == "__main__":
    sys.exit(main())
