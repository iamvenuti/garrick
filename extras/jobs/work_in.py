#!/usr/bin/env python3
"""work_in.py: the nightly run's step that works in the answers still waiting (#550).

    python3 work_in.py --workspace /Users/<you>/Garrick [--tier sonnet]

A question the user answered on the Context card waits as `status: answered` until the `meetings` or `knowledge` skill
works it into the pages it changes. Closing the queue asks for that at once; this step is what is left, so a user who
never presses anything still has them worked in. It makes one assistant call for each answer, the oldest first, that
names that one question and its place only ("work in the answer in Work"), so no call ever holds two zones' answers, and
the skills themselves leave out every page that is not in the question's own zone. Each answer is committed when its own
call ends, so a call stopped at the step's limit loses only its own question's changes and every answer worked in before
it stays; what is left waits for the next night, in the same order (#629). A place with no answer waiting costs no call.

The call is made through agent.py, so the scheduled jobs' own caps and deny profile hold it: nothing is added. The call
writes pages and commits nothing. This script commits what changed in that wiki's repository, by name, through the
repository's hooks, and puts the files back if a hook refuses.

What it could not work in is kept for the Context card, which asks about it: `System/generated/status-answers.json` holds,
for each place, the day and a reason from a short fixed list (never a path, a title or an answer), and nothing else.
A place that works in cleanly is taken out of the file.

Exit codes: 0 (an answer left unworked is no fault of the night: the card asks about it, and the last line says
"<place>: N worked in, M left" for each place, and each count is of that one place, also when the step's limit was reached
between two answers); 124 when an assistant call
was stopped while it ran, so that the nightly summary says `answers exit 124` and the step is not read as ok (#566); the
assistant's own for a hard failure to start (2 usage, 127 missing); 64 for a workspace without the status page's panel.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import importlib.util
import itertools
import json
import os
import re
import shutil
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
STOPPED: List[str] = []      # the places whose call was stopped at its time limit, in this run
LEFT_DIRTY: Dict[str, int] = {}       # how many listed pages were already changed before the call and not by it, by place (#640)
LEFT_ALONE: Dict[str, int] = {}      # how many other changed paths in the wiki the commits left as they were, by place (W6)
KNOWLEDGE = "Wikis/Knowledge"
# The reasons a place was left, by code: the words the card says are in finding_queue.ANSWERS_HELD.
REASONS = ("cap", "assistant", "incomplete", "held", "commit", "long")
STOP_LIMIT = 2       # a question whose call was stopped at the limit on this many runs is held as too long, and the night skips it (#629)
# What the call may run. page_action.py only by the two CLI verbs it needs: a CLI verb runs as `via: session`, which refuses
# the page-only verbs, while JSON on stdin would run as `via: page`.
ALLOW = ["Read", "Grep", "Glob", "Edit", "Write",
         "Bash(python3 System/status/page_action.py question-work:*)",
         "Bash(python3 System/status/page_action.py question-done:*)"]
MIN_LEFT = 60        # seconds: start no place with less than this left of the step's limit
MARGIN = 20          # seconds kept back from the limit for the commit and the restore


_PA = None


def page_action():
    """page_action.py of the status page extra, or None where there is none: it knows which pages a question may change."""
    global _PA
    if _PA is None:
        path = STATUS / "page_action.py"
        if not path.is_file():
            return None
        sys.path.insert(0, str(STATUS))
        spec = importlib.util.spec_from_file_location("garrick_work_in_page_action", str(path))
        _PA = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_PA)
    return _PA


def listed_paths(ws: Path, wiki: str, rel: str, top: Path) -> Optional[Set[str]]:
    """The paths this one answer may change, from the repository's top: the pages `question-work` lists for it, the question's own
    file (which `question-done` marks) and the raw answer it cites. None when they cannot be listed: then nothing is kept (W6)."""
    pa = page_action()
    if pa is None:
        return None
    try:
        q = pa.WikiQuestion(ws, {"wiki": wiki, "file": rel})
        wall = pa.wall_sentence(ws)
        record = pa.own_record(q, wall)
        pages, _, _ = pa.question_pages(q, wall)
        files = list(pages) + [q.path]
        for name in (record, record + ".md"):
            if (q.dir / name).is_file():
                files.append((q.dir / name).resolve())
        return {os.path.relpath(str(f), str(top.resolve())).replace(os.sep, "/") for f in files}
    except Exception:
        return None


def panel():
    """questions_panel.py of the status page extra, or None where there is none."""
    path = STATUS / "questions_panel.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("garrick_work_in_panel", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def answers(ws: Path, today: datetime.date) -> Optional[List[Tuple[str, str, str, str]]]:
    """(scope, how the request names the place, the wiki, the question's file) for each answer waiting, zones by name and
    then the Knowledge wiki, the oldest question first within a place. None when the panel cannot read the workspace. The
    panel places each answer by the walls' own view, so a zone's answers are that zone's and no other's."""
    mod = panel()
    if mod is None:
        return None
    found: list = []
    try:
        data = mod.build(ws, {"findings": [], "at": time.time()}, today, lambda p: "", found)
    except Exception:
        return None
    if not data:
        return None
    seen, out = set(), []
    for key, wiki, rel, asked in sorted(found, key=lambda x: (x[0] == "Knowledge", x[0], str(x[3] or ""), x[2])):
        if (key, wiki, rel) in seen:
            continue
        seen.add((key, wiki, rel))
        out.append((KNOWLEDGE, "the Knowledge wiki", wiki, rel) if key == "Knowledge" else ("Zones/" + key, key, wiki, rel))
    return out


def prompt_for(scope: str, place: str, wiki: str = "", rel: str = "") -> str:
    """The request, naming one question and its own place only: the meetings skill's step for a zone, the knowledge skill's
    for the Knowledge wiki."""
    skill = "knowledge" if scope == KNOWLEDGE else "meetings"
    return ("work in the answer in %s.\n"
            "The question is `%s` in the %s wiki. Follow the %s skill's \"Answers, and working them in\" for that one question "
            "only. Change only the pages `question-work` lists, cite the raw answer, and mark the question done. Never commit, "
            "never send, and never ask a question: where the answer is unclear, or `question-work` refuses, leave the question as "
            "it is and count it as held.\n"
            "Look with Read, Grep and Glob. The shell runs only `python3 System/status/page_action.py question-work` and "
            "`python3 System/status/page_action.py question-done`: no other shell command, never wait for a file to change, and "
            "never run the lint, since the nightly run's own steps do that.\n"
            "Then write one line exactly: WORKED <n> HELD <n>, and after it one line that says exactly %s" % (place, rel, wiki, skill, SENTINEL))


def counts(text: str) -> Optional[Tuple[int, int]]:
    lines = (text or "").rstrip().splitlines()
    if not lines or lines[-1].strip() != SENTINEL:
        return None
    found = COUNTS.findall(text)
    return (int(found[-1][0]), int(found[-1][1])) if found else None


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "--literal-pathspecs", *args], cwd=str(repo), capture_output=True, text=True, timeout=300,
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


def digest(repo: Path, paths) -> Dict[str, str]:
    """A short hash of what each path holds now, '' for a path that is not a file: how a page that was changed before the call
    is told from one the call changed (#640)."""
    out = {}
    for p in paths:
        try:
            out[p] = hashlib.sha1((repo / p).read_bytes()).hexdigest()
        except OSError:
            out[p] = ""
    return out


def own_changes(repo: Path, before: Set[str], rel: str, listed, seen: Optional[Dict[str, str]] = None) -> List[str]:
    """The paths this call changed that its list allows, sorted. A path in the list that was changed before the call counts only
    when what it holds differs from `seen`, its hash from before the call. `listed` None means the list could not be made: then
    it is every path that changed during the call and was clean before (today's reading, for the put-back only)."""
    now = changes(repo, rel)
    fresh = now - before
    if listed is None:
        return sorted(fresh)
    mine = {p for p in fresh if p in listed}
    dirty = {p for p in now & before if p in listed}
    if dirty and seen is not None:
        after = digest(repo, dirty)
        mine |= {p for p in dirty if after[p] != seen.get(p)}
    return sorted(mine)


def restore(repo: Path, before: Set[str], rel: str, listed=None) -> None:
    """Put back what a call changed, and only its own: the pages `question-work` listed for it. Tracked paths as the last commit
    has them, files it created moved out. Another writer's edit made while the call ran (the user, a mail fetch) is neither put
    back nor committed, and a path that was already changed before the call is never put back. With no list at all, every path
    that changed during the call and was clean before is put back, as before.
    Nothing is lost: each path is first copied, as it is now, into the repository's own `.git`
    (`.git/garrick-put-back/<time>/`), which no commit carries and which stays in that repository's place."""
    paths = own_changes(repo, before, rel, listed)
    if not paths:
        return
    keep = repo / ".git" / "garrick-put-back" / time.strftime("%Y%m%d-%H%M%S")
    for p in paths:
        src = repo / p
        try:
            if src.is_file() and not src.is_symlink():
                (keep / p).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src), str(keep / p))
        except OSError:
            return              # a copy that cannot be made: put nothing back, so nothing is lost
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


def commit(repo: Path, before: Set[str], rel: str, place: str, worked: int, listed=None, seen: Optional[Dict[str, str]] = None) -> Optional[str]:
    """Commit what the call wrote, by name, through the repository's hooks. None when done or nothing changed, else why. With
    `listed` (the paths `question-work` named for this answer), only those are committed; any other path the wiki holds changed
    is left exactly as it is, and counted for the step's summary line (W6). A listed page that was already changed before the
    call is committed only when the call changed it (`seen` holds what it held before); otherwise it is left as it is and counted
    for the summary line (#640)."""
    now = changes(repo, rel)
    paths = own_changes(repo, before, rel, listed, seen)
    if listed is not None:
        others = [p for p in sorted(now - before) if p not in listed]
        if others:
            LEFT_ALONE[place] = LEFT_ALONE.get(place, 0) + len(others)
        untouched = [p for p in sorted(now & before) if p in listed and p not in paths]
        if untouched:
            LEFT_DIRTY[place] = LEFT_DIRTY.get(place, 0) + len(untouched)
    if not paths:
        return None
    git(repo, "add", "-A", "--", *paths)
    c = git(repo, "commit", "-q", "-m", "Answers worked in for %s: %d question%s" % (place, worked, "" if worked == 1 else "s"), "--", *paths)
    if c.returncode != 0:
        restore(repo, before, rel, listed)
        return "commit"
    return None


def read_held(ws: Path) -> Dict[str, dict]:
    try:
        data = json.loads(ws.joinpath(*HELD_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    held = data.get("held") if isinstance(data, dict) else None
    return {k: v for k, v in (held or {}).items() if isinstance(v, dict) and v.get("why") in REASONS} if isinstance(held, dict) else {}


def question_key(scope: str, wiki: str, rel: str) -> str:
    """Twelve hex digits that name one question in the file below: never its path, its title or its answer."""
    return hashlib.sha1(("%s\0%s\0%s" % (scope, wiki, rel)).encode("utf-8", "surrogatepass")).hexdigest()[:12]


STOP_DAYS = 7        # a held question is tried again after this many days, whatever its file holds (C8)


def question_hash(ws: Path, wiki: str, rel: str) -> str:
    """A short hash of what a question file holds now, so that a question changed since it was held is tried again (C8)."""
    try:
        return hashlib.sha1((ws / "Wikis" / wiki / rel).read_bytes()).hexdigest()[:12]
    except OSError:
        return ""


def read_stopped(ws: Path) -> Dict[str, dict]:
    """For each question whose call was stopped at the step's limit, how many runs stopped it and the day of the last (#629)."""
    try:
        data = json.loads(ws.joinpath(*HELD_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    found = data.get("stopped") if isinstance(data, dict) else None
    return {k: {"n": int(v["n"]), "day": str(v.get("day") or ""), "h": str(v.get("h") or "")} for k, v in (found or {}).items()
            if isinstance(v, dict) and re.fullmatch(r"[0-9a-f]{12}", str(k)) and isinstance(v.get("n"), int) and v["n"] > 0} \
        if isinstance(found, dict) else {}


def write_held(ws: Path, held: Dict[str, dict], stopped: Optional[Dict[str, dict]] = None) -> None:
    path = ws.joinpath(*HELD_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".status-answers-")
    body = {"held": held}
    if stopped:
        body["stopped"] = stopped
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(body, f, indent=1, sort_keys=True)
        f.write("\n")
    os.replace(tmp, str(path))


def work_place(ws: Path, scope: str, place: str, wiki: str, rel: str, tier: str, deadline: Optional[float] = None) -> Tuple[Optional[str], int]:
    """Work in one answer. (None, the number worked in) when it was worked in, else (the reason code, 0). The call's changes
    are committed, or put back, before the next answer starts: only this call's own."""
    repo, folder = wiki_repo(ws, scope)
    if repo is None:
        return "assistant", 0
    before = changes(repo, folder)
    listed = listed_paths(ws, wiki, rel, repo)
    seen = digest(repo, [p for p in before if listed is not None and p in listed])      # what the listed pages that were dirty held
    extra = {} if deadline is None else {"timeout": max(1.0, deadline - time.time() - MARGIN)}
    code, text = agent.run(tier, prompt_for(scope, place, wiki, rel), cwd=ws, allow=ALLOW, **extra)
    if code == agent.EXIT_TIMEOUT:
        STOPPED.append(place)
    if listed is None:
        restore(repo, before, folder, None)           # which pages this answer may change cannot be told: nothing is kept (W6)
        return "incomplete", 0
    if code == agent.EXIT_CAP:
        restore(repo, before, folder, listed)
        return "cap", 0
    found = counts(text) if code == 0 else None
    if found is None:
        restore(repo, before, folder, listed)
        return ("assistant" if code else "incomplete"), 0
    worked, held = found
    if worked + held == 0:
        restore(repo, before, folder, listed)         # a call that worked nothing in and held nothing back did not finish (#629)
        return "incomplete", 0
    why = commit(repo, before, folder, place, worked, listed, seen)
    if why:
        return why, 0
    return ("held" if held else None), worked


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Work in the answers still waiting, one answer at a time.")
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--tier", default="sonnet", choices=agent.TIERS)
    ap.add_argument("--limit", type=float, help="seconds the whole step may take; no answer is started near the end of it")
    ap.add_argument("--today", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    ws = Path(args.workspace).expanduser().resolve()
    today = datetime.date.fromisoformat(args.today) if args.today else datetime.date.today()
    items = answers(ws, today)
    if items is None:
        print("work_in: no System/status/questions_panel.py, or it cannot read this workspace", file=sys.stderr)
        return EXIT_NO_PANEL
    held = read_held(ws)
    for scope in [s for s in held if s not in {i[0] for i in items}]:
        del held[scope]                               # nothing waits there any more
    stops = read_stopped(ws)
    now_hash = {question_key(i[0], i[2], i[3]): question_hash(ws, i[2], i[3]) for i in items}
    for key in [k for k in stops if k not in now_hash]:
        del stops[key]                                # answered or gone: no longer counted
    for key in list(stops):
        try:
            old = (today - datetime.date.fromisoformat(stops[key]["day"])).days > STOP_DAYS
        except ValueError:
            old = True
        if old or (stops[key].get("h") and stops[key]["h"] != now_hash[key]):
            del stops[key]                            # held a week, or the question changed since: tried again (C8)
    total = 0
    del STOPPED[:]
    LEFT_ALONE.clear()
    LEFT_DIRTY.clear()
    deadline = time.time() + args.limit if args.limit else None
    for scope, group in itertools.groupby(items, key=lambda i: i[0]):
        group = list(group)
        place = group[0][1]
        worked_in, reason, cut = 0, None, False
        for _, _, wiki, rel in group:
            key = question_key(scope, wiki, rel)
            if stops.get(key, {}).get("n", 0) >= STOP_LIMIT:
                why, worked = "long", 0                # stopped at the limit on two runs: held for the card, the others go on (#629)
            elif cut or (deadline is not None and deadline - time.time() < MIN_LEFT):
                cut = True                            # the limit is reached between answers: what is left waits for the night after
                why, worked = "cap", 0
            else:
                stopped_before = len(STOPPED)
                why, worked = work_place(ws, scope, place, wiki, rel, args.tier, deadline)
                if len(STOPPED) > stopped_before:     # this question's call was stopped while it ran
                    stops[key] = {"n": stops.get(key, {}).get("n", 0) + 1, "day": today.isoformat(), "h": now_hash.get(key, "")}
                    if stops[key]["n"] >= STOP_LIMIT:
                        why = "long"
                elif why in (None, "held"):
                    stops.pop(key, None)              # it ran to its end: the count starts again
            total += worked
            if why is None:
                worked_in += 1
            else:
                reason = reason or why
        n_left = len(group) - worked_in
        print("work_in: %s: %d worked in, %d left%s%s%s%s" % (
            place, worked_in, n_left, " (%s)" % reason if reason else "", ", a call was stopped at its time limit" if place in STOPPED else "",
            ", %d other changed path%s in the wiki left as %s" % (LEFT_ALONE[place], "" if LEFT_ALONE[place] == 1 else "s",
                                                              "it is" if LEFT_ALONE[place] == 1 else "they are") if LEFT_ALONE.get(place) else "",
            ", %d listed page%s already changed before the call left as %s" % (LEFT_DIRTY[place], "" if LEFT_DIRTY[place] == 1 else "s",
                                                                           "it is" if LEFT_DIRTY[place] == 1 else "they are") if LEFT_DIRTY.get(place) else ""))
        if reason is None:
            held.pop(scope, None)
        else:
            held[scope] = {"why": reason, "day": today.isoformat()}
        write_held(ws, held, stops)
    if not items:
        print("work_in: no answer is waiting")
        if ws.joinpath(*HELD_FILE).exists():
            write_held(ws, held, stops)
    agent.report_items(total)
    return agent.EXIT_TIMEOUT if STOPPED else 0


if __name__ == "__main__":
    sys.exit(main())
