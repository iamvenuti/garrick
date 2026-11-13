#!/usr/bin/env python3
"""work_in.py: the nightly run's step that works in the answers still waiting (#550).

    python3 work_in.py --workspace /Users/<you>/Garrick [--tier sonnet]

A question the user answered on the Context card waits as `status: answered` until the `meetings` or `knowledge` skill
works it into the pages it changes. Closing the queue asks for that at once; this step is what is left, so a user who
never presses anything still has them worked in. For each zone, and for the Knowledge wiki, that holds an answer, it
makes one assistant call that names only that place ("work in the answers in Work"), so no call ever holds two zones'
answers, and the skills themselves leave out every page that is not in the question's own zone. A place with no answer
waiting costs no call.

The call is made through agent.py, so the scheduled jobs' own caps and deny profile hold it: nothing is added. The call
writes pages and commits nothing. This script commits what changed in that wiki's repository, by name, through the
repository's hooks, and puts the files back if a hook refuses.

What it could not work in is kept for the Context card, which asks about it: `System/generated/status-answers.json` holds,
for each place, the day and a reason from a short fixed list (never a path, a title or an answer), and nothing else.
A place that works in cleanly is taken out of the file.

Exit codes: 0 (a place left unworked is no fault of the night: the card asks about it); the assistant's own for a hard
failure to start (2 usage, 127 missing); 64 for a workspace without the status page's panel.
"""

from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import agent  # noqa: E402

STATUS = HERE.parent / "status"            # System/status beside System/jobs, as extras/status is beside extras/jobs
HELD_FILE = ("System", "generated", "status-answers.json")
SENTINEL = "END OF WORK-IN"
COUNTS = re.compile(r"^WORKED (\d+) HELD (\d+)\s*$", re.M)
EXIT_NO_PANEL = 64
KNOWLEDGE = "Wikis/Knowledge"
# The reasons a place was left, by code: the words the card says are in finding_queue.ANSWERS_HELD.
REASONS = ("cap", "assistant", "incomplete", "held", "commit")
# What the call may run. page_action.py only by the two CLI verbs it needs: a CLI verb runs as `via: session`, which refuses
# the page-only verbs, while JSON on stdin would run as `via: page`.
ALLOW = ["Read", "Grep", "Glob", "Edit", "Write",
         "Bash(python3 System/status/page_action.py question-work:*)",
         "Bash(python3 System/status/page_action.py question-done:*)"]
MIN_LEFT = 60        # seconds: start no place with less than this left of the step's limit
MARGIN = 20          # seconds kept back from the limit for the commit and the restore


def panel():
    """questions_panel.py of the status page extra, or None where there is none."""
    path = STATUS / "questions_panel.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("garrick_work_in_panel", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def waiting(ws: Path, today: datetime.date) -> Optional[List[Tuple[str, str, int]]]:
    """(scope, how the request names the place, how many answers) for each place that holds an answer, zones by name and
    then the Knowledge wiki. None when the panel cannot read the workspace. The panel places each answer by the walls'
    own view, so a zone's count holds that zone's answers and no other's."""
    mod = panel()
    if mod is None:
        return None
    try:
        data = mod.build(ws, {"findings": [], "at": time.time()}, today, lambda p: "")
    except Exception:
        return None
    if not data:
        return None
    out = [("Zones/" + zone, zone, int(b.get("answered") or 0)) for zone, b in sorted((data.get("buckets") or {}).items())]
    out.append((KNOWLEDGE, "the Knowledge wiki", int(data.get("knowledge_answered") or 0)))
    return [x for x in out if x[2] > 0]


def prompt_for(scope: str, place: str) -> str:
    """The request, naming its own place only: the meetings skill's step for a zone, the knowledge skill's for the Knowledge wiki."""
    skill = "knowledge" if scope == KNOWLEDGE else "meetings"
    return ("work in the answers in %s.\n"
            "Follow the %s skill's \"Answers, and working them in\" for the questions of %s only. Change only the pages "
            "`question-work` lists, cite the raw answer, and mark each question done. Never commit, never send, and never ask a "
            "question: where an answer is unclear, or `question-work` refuses, leave that question as it is and count it as held.\n"
            "Then write one line exactly: WORKED <n> HELD <n>, and after it one line that says exactly %s" % (place, skill, place, SENTINEL))


def counts(text: str) -> Optional[Tuple[int, int]]:
    lines = (text or "").rstrip().splitlines()
    if not lines or lines[-1].strip() != SENTINEL:
        return None
    found = COUNTS.findall(text)
    return (int(found[-1][0]), int(found[-1][1])) if found else None


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, timeout=300,
                          stdin=subprocess.DEVNULL, env=agent.own_repo_env())


def wiki_repo(ws: Path, scope: str) -> Tuple[Optional[Path], str]:
    """(the repository that holds the wiki, the wiki's folder from its top) for a place: the Meetings wiki for a zone, the
    Knowledge wiki for itself."""
    wiki = ws / "Wikis" / ("Knowledge" if scope == KNOWLEDGE else "Meetings")
    top = git(wiki, "rev-parse", "--show-toplevel").stdout.strip() if wiki.is_dir() else ""
    if not top:
        return None, ""
    return Path(top), os.path.relpath(str(wiki.resolve()), str(Path(top).resolve())).replace(os.sep, "/")


def changes(repo: Path, rel: str) -> Set[str]:
    out = git(repo, "status", "--porcelain", "-z", "--no-renames", "--untracked-files=all", "--", rel).stdout
    return {entry[3:] for entry in out.split("\0") if len(entry) > 3}


def restore(repo: Path, before: Set[str], rel: str) -> None:
    """Put back what a call changed: tracked paths as the last commit has them, files it created deleted. A path that was
    already changed before the call is never touched."""
    paths = sorted(changes(repo, rel) - before)
    if not paths:
        return
    git(repo, "reset", "-q", "--", *paths)
    tracked = set(git(repo, "ls-files", "-z", "--", *paths).stdout.split("\0"))
    back = [p for p in paths if p in tracked]
    if back:
        git(repo, "checkout", "-q", "--", *back)
    for p in paths:
        if p not in tracked:
            try:
                (repo / p).unlink()
            except OSError:
                pass


def commit(repo: Path, before: Set[str], rel: str, place: str, worked: int) -> Optional[str]:
    """Commit what the call wrote, by name, through the repository's hooks. None when done or nothing changed, else why."""
    paths = sorted(changes(repo, rel) - before)
    if not paths:
        return None
    git(repo, "add", "-A", "--", *paths)
    c = git(repo, "commit", "-q", "-m", "Answers worked in for %s: %d question%s" % (place, worked, "" if worked == 1 else "s"), "--", *paths)
    if c.returncode != 0:
        restore(repo, before, rel)
        return "commit"
    return None


def read_held(ws: Path) -> Dict[str, dict]:
    try:
        data = json.loads(ws.joinpath(*HELD_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    held = data.get("held") if isinstance(data, dict) else None
    return {k: v for k, v in (held or {}).items() if isinstance(v, dict) and v.get("why") in REASONS} if isinstance(held, dict) else {}


def write_held(ws: Path, held: Dict[str, dict]) -> None:
    path = ws.joinpath(*HELD_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".status-answers-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"held": held}, f, indent=1, sort_keys=True)
        f.write("\n")
    os.replace(tmp, str(path))


def work_place(ws: Path, scope: str, place: str, n: int, tier: str, deadline: Optional[float] = None) -> Optional[str]:
    """Work in one place's answers. None when they were worked in, else the reason code."""
    repo, rel = wiki_repo(ws, scope)
    if repo is None:
        return "assistant"
    before = changes(repo, rel)
    extra = {} if deadline is None else {"timeout": max(1.0, deadline - time.time() - MARGIN)}
    code, text = agent.run(tier, prompt_for(scope, place), cwd=ws, allow=ALLOW, **extra)
    if code == agent.EXIT_CAP:
        restore(repo, before, rel)
        return "cap"
    found = counts(text) if code == 0 else None
    if found is None:
        restore(repo, before, rel)
        return "assistant" if code else "incomplete"
    worked, held = found
    why = commit(repo, before, rel, place, worked)
    if why:
        return why
    return "held" if held else None


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Work in the answers still waiting, one place at a time.")
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--tier", default="sonnet", choices=agent.TIERS)
    ap.add_argument("--limit", type=float, help="seconds the whole step may take; no place is started near the end of it")
    ap.add_argument("--today", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    ws = Path(args.workspace).expanduser().resolve()
    today = datetime.date.fromisoformat(args.today) if args.today else datetime.date.today()
    places = waiting(ws, today)
    if places is None:
        print("work_in: no System/status/questions_panel.py, or it cannot read this workspace", file=sys.stderr)
        return EXIT_NO_PANEL
    held = read_held(ws)
    for scope in [s for s in held if s not in {p[0] for p in places}]:
        del held[scope]                               # nothing waits there any more
    total = 0
    deadline = time.time() + args.limit if args.limit else None
    for scope, place, n in places:
        if deadline is not None and deadline - time.time() < MIN_LEFT:
            why = "cap"
        else:
            why = work_place(ws, scope, place, n, args.tier, deadline)
        print("work_in: %s: %s" % (place, "worked in" if why is None else "left (%s)" % why))
        if why is None:
            held.pop(scope, None)
            total += n
        else:
            held[scope] = {"why": why, "day": today.isoformat()}
        write_held(ws, held)
    if not places:
        print("work_in: no answer is waiting")
        if ws.joinpath(*HELD_FILE).exists():
            write_held(ws, held)
    agent.report_items(total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
