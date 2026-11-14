#!/usr/bin/env python3
"""finding_queue.py: the Context card's queue (#535, #542), one question at a time, as a plain question with answer buttons.

status.py builds the queue at page build, for every scope, from the one-pass forecast (the latest Nurture record's
standing findings), so the number on a scope's line on the card and the number in its queue are one list's. A kind
with plain wording says one short sentence and one line on why it matters, with no path, setting name or command in
either; those stay in *Details*, closed. Every other kind shows the check's own text under a plain label, with
*Something else* as its only answer. PLAIN_KINDS lists the kinds that have plain wording, and a test holds the list,
so a new kind cannot get one silently.

Each answer names the action it takes, from the fixed table in ANSWERS:

    handoff   the finding goes to the assistant at the workspace root, by the route Process the Inbox takes
              (data-request); the page writes nothing. A wall finding's request names the file and the two zones,
              never the repeated words.
    run       a tool the workspace already has: history.py applies. Through the page's
              verb `finding` (page_action.py), so the commit and its wall check are the page's own.
    preview   what a run would do, said as counts, the full output under Details; nothing is written.
    open      the file, or both files of a wall finding, opened in the note app by the page's own note-open; nothing
              is written.
    later     Not now: the finding is hidden for LATER_DAYS days in System/generated/status-later.json, a page-owned
              file that holds a key for each finding and the day it comes back, never a path or any text. No check
              and no Nurture record reads it, so what the checks report is the same with and without it.

A long note is asked from the plan, not from the kind alone (#539): while the page builds, `history.py dry-run --json` runs once for
each such finding (never a write subcommand), and when it would move nothing, or cannot be run, the question offers no Move and no
Show me; its recommended answer is the handoff in ANSWERS_NO_MOVE, and its why-line says in plain words which case applies.
A move refused when it runs (#540) disables that answer, offers Skip for now, and, when the refusal says nothing can move, the
kind's fallback handoff (FALLBACKS) in its place. Skip for now keeps nothing: it is the dialog's, and a reload brings the question back.

The queue holds three more kinds, the wiki's own questions (#542), built from questions_panel.py's data for the zone or wiki they
belong to and never for another: a wiki question (a field for the answer, Record as a decision, Later with its day, Close), a proposed
verdict (Accept, Answer it myself, Not now) and a decision to review (Open the decision, Not now). Each answer goes through the verb
the Questions panel's button used: `question-answer`, `question-later`, `question-close`, `question-decide`, `note-open` and, for Not
now, `finding` with the kind and the path of the question's file. No verb is new, so the wall check runs as before. A decision's status
is the user's alone: nothing here writes one.

Wall findings have no Not now. No wall answer is recommended (#548): when the question opens in the app, the page asks
page_action.py's read verb `walls-look` which file the finding is about; Show me both texts reads the shared words of both files into
the dialog, and drops them when it closes. Only after that does *The words are mine, keep them* show, in the app, and send
`walls-allow` (#550). Neither verb is for the ask box or a session; a browser has no bridge and shows neither.
A missing wall check is not asked at all (#550): the update and the nightly run install it. A hook of the user's own in its place is asked as hooks-blocked, with no Not now: hiding it would leave the walls unchecked on commit, which fails open, as for a wall.

This module only decides and says; it writes nothing but the Not now file, which page_action.py asks it to.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

LATER_DAYS = 7
LATER_FILE = ("System", "generated", "status-later.json")
HISTORY_TOOL = ("System", "tools", "history.py")
PLAN_TIMEOUT = 15         # seconds one history.py plan may take while the page builds
PLAN_BUDGET = 60          # seconds all the plans of one build may take together; the ones after count as "nothing moves"

# The kinds with plain wording, in the order a queue asks them (a wall first, always). The mechanical kind is not among them:
# the nightly run makes those fixes, and the card shows nothing for one (#550). One the run could not make is asked as fix-failed.
PLAIN_KINDS = ("wall", "note-long", "resume-long", "todo-long", "meeting-long", "hooks-blocked", "fix-failed")
HOOKS = "hooks-missing"     # the finding; Garrick installs the hook itself, and only a hook it must not touch is asked as hooks-blocked
MECHANICAL = "mechanical"
FREE = "Something else: tell Garrick what to do"
NO_FREE_FOR = ()          # every question keeps the free-text field, last

# The one table of finding kinds (#550). A kind is `automatic` (Garrick does it without asking; the user hears of it only when it
# fails) or `question` (a reasonable user could answer two ways and Garrick cannot tell which). The test for a kind: would a user
# ever say no? If not, it is not asked. A kind in neither class fails test_finding_queue, and so does a `question` kind whose
# only answer is *Something else*, except the kinds in FREE_ONLY, which have no plain wording yet and stay as they are today.
AUTOMATIC, QUESTION = "automatic", "question"
KIND_CLASS = {
    "wall": QUESTION, "note-long": QUESTION, "resume-long": QUESTION, "todo-long": QUESTION, "meeting-long": QUESTION,
    "hooks-missing": AUTOMATIC, "hooks-blocked": QUESTION, "mechanical": AUTOMATIC, "fix-failed": QUESTION,
    "wiki-question": QUESTION, "verdict": QUESTION, "decision-review": QUESTION, "answers-held": QUESTION,
    "other": QUESTION,
}
FREE_ONLY = ("other",)    # the check's own text under a plain label, *Something else* alone: no plain wording yet (listed in the release notes)


def A(id_: str, label: str, does: str, action: str) -> dict:
    return {"id": id_, "label": label, "does": does, "action": action}


# kind -> (tag, why, answers); the first answer is the recommended one.
ANSWERS: Dict[str, List[dict]] = {
    # No answer is recommended: the user sees the match first (#548). Show me both texts reads the two files and shows the words
    # they share, in the dialog only; Take it out waits for that check to name the file; The words are mine waits until both
    # texts were shown, and is the page's own button, in the Mac app (#550).
    "wall": [A("show-both", "Show me both texts", "Shows the words the two files share. Nothing changes.", "look"),
             A("take-out", "Take it out", "Your assistant removes it and shows you the change.", "handoff"),
             A("keep", "The words are mine, keep them", "Keeps this file as it is. Garrick stops flagging these words until the file changes.", "allow")],
    "note-long": [A("move-older", "Move older entries to history", "Nothing is deleted.", "run"),
                  A("preview", "Show me what would move", "A preview. No change until you say so.", "preview"),
                  A("later", "Not now", "Ask again in a week.", "later")],
    "resume-long": [A("shorten", "Shorten it", "Your assistant writes a shorter one for you to approve.", "handoff"),
                    A("later", "Not now", "Ask again in a week.", "later")],
    "todo-long": [A("shorten", "Shorten the line", "Your assistant shortens it and moves what came of it to the thread's notes.", "handoff"),
                  A("later", "Not now", "Ask again in a week.", "later")],
    "meeting-long": [A("shorten", "Shorten it", "Your assistant shortens the page. The recording's transcript stays as it is.", "handoff"),
                     A("open", "Let me open it", "Opens the page in your notes app. Nothing changes.", "open"),
                     A("later", "Not now", "Ask again in a week.", "later")],
    # A hook of the user's own stands where the wall check goes: Garrick never replaces it. The assistant adds one line to it (#550).
    # A small fix the nightly run could not make: the assistant makes it with the user watching, or it waits (#550).
    "fix-failed": [A("fix-now", "Fix it with my assistant", "Your assistant makes the fix and shows you the change.", "handoff"),
                   A("later", "Not now", "Ask again in a week.", "later")],
    "hooks-blocked": [A("add-check", "Add the wall check to my hook", "Your assistant adds one line to your hook and shows you the change.", "handoff")],
}
# What a long note is asked when its plan moves nothing: no Move and no Show me, the handoff first (#539).
ANSWERS_NO_MOVE: Dict[str, List[dict]] = {
    "note-long": [A("split", "Split the long sections into their own notes",
                    "Your assistant splits the long sections into their own notes in the thread's folder, links them, and shows you the change.", "handoff"),
                  A("later", "Not now", "Ask again in a week.", "later")],
}
# The answer a run that is refused for "nothing can move" is replaced by, by kind and by the answer refused (#540).
FALLBACKS: Dict[str, Dict[str, str]] = {"note-long": {"move-older": "split"}}
# Why nothing moves, by case: (the plain words under the sentence, what Details adds).
NO_MOVE = {
    "sections": ("Most of its words sit in long sections above the dated entries, and only dated entries move to history.",
                 "history.py moves only the dated entries below the rule under `## State of play`; none of the words here are in them."),
    "log-bullets": ("Its dated entries are bullets in a log above the line that opens the history, a shape the move does not read.",
                    "Dated bullets sit above the `---` rule under `## State of play`; history.py reads only dated paragraphs below it."),
    "few": ("It has five dated entries or fewer, and the newest five always stay.", "history.py always keeps the newest %d entries." % 5),
    "no-state": ("It has no state-of-play section, so there is nothing to move entries from.", "The note has no `## State of play` section, so history.py skips it."),
    "unreadable": ("The move cannot read this page's layout, so it cannot tell which entries are old.", "history.py skipped the note: %s"),
    "old-enough": ("No dated entry is old enough to leave the page.", "history.py plans no entry to move."),
    "unknown": ("Garrick could not ask what would move, so it does not offer a move.", "history.py did not answer in time, or is not in this workspace."),
}
TAGS = {"wall": "Private material", "note-long": "Tidy up", "resume-long": "Tidy up", "todo-long": "Tidy up",
        "meeting-long": "Tidy up", "hooks-blocked": "Safety check", "fix-failed": "Tidy up"}
HELD = re.compile(r"\(held: (.+)\)\s*$")
# The plain words for why the run held a fix back, by what Nurture said; the full reason stays in Details.
HELD_WORDS = (("mid-turn", "A session was working there when the fix came up."), ("mid-merge", "Its repository was in the middle of a merge."),
              ("not committed", "It has changes that are not committed yet."), ("could not be undone", "No single repository holds its files."),
              ("two repositories", "Its files are in two repositories."), ("refused", "The commit was refused by the wall check."),
              ("changed again", "The file changed again while the fix was being checked."))
WHY = {"fix-failed": "A fix this small is made on its own at night. This one was held back.",
       "note-long": "Long pages are slow to read and slow for the assistant. Older entries can move to a history page, where they stay linked.",
       "resume-long": "A resume point is what you read first when you come back, so a short one is quicker to take in.",
       "todo-long": "A line names one action. What came of it belongs in the thread's notes.",
       "meeting-long": "A meeting note is a short record: who was there, the key points, the actions.",
       "hooks-blocked": "Garrick installs this check on its own, but a hook of yours is in the way and Garrick never replaces one of yours. "
                        "Without the check, a commit can carry private material across a wall and nothing warns you."}
NEVER_LATER = ("wall", "hooks-blocked")     # no Not now: hiding either leaves the walls unchecked
ACTIONS = ("handoff", "run", "preview", "open", "later", "words", "day", "reveal", "look", "allow")
# The answers the verb `finding` takes (page_action.py), by kind: closed, so an unknown kind or answer is refused.
VERB_ANSWERS = {kind: tuple(a["id"] for a in answers if a["action"] in ("run", "preview", "later")) for kind, answers in ANSWERS.items()}
# The wiki's own kinds (#542) are put off, and nothing else, through the same verb: the question's file stays as it is.
ASKED_KINDS = ("wiki-question", "verdict", "decision-review", "answers-held")
VERB_ANSWERS.update({"verdict": ("later",), "decision-review": ("later",), "answers-held": ("later",)})

NOTE_RE = re.compile(r"has (\d+) words, over the \d+ of `note-max-words`")
RESUME_RE = re.compile(r"Resume here block has (\d+) words, over the \d+ of `resume-max-words`")
MEETING_RE = re.compile(r"body is (\d+) words, over the \d+ of `meeting-max-words`")
TODO_RE = re.compile(r"(\d+) lines? (?:is|are) longer than \d+ characters")
# The zone a wall finding names, from check.py's own texts: `links [[...]], a note of the <Z> zone; that zone is walled ...`,
# `repeats wording from ..., a meeting of the <Z> zone; that zone is walled ...`, `... in project P of the <Z> zone; ...`,
# `is a symbolic link into the <Z> zone; ...`, `is a copy, whole, of a file of the <Z> zone; ...`.
WALL_OTHER_RE = re.compile(r"\b(?:of|into) the ((?:(?!\b(?:of|into) the )[^;\[\]`])+?) zone; (?:that zone|a page with no zone) is walled")
NOTE_PATH_RE = re.compile(r"(?:Zones|Wikis)/[^\s;,`'\"()\[\]]+?\.md")


HOOK_LINE = re.compile(r"no pre-commit wall check|has the pre-commit wall check but not|no wall check before its commits")
HOOK_NAMES = ("pre-commit", "pre-merge-commit", "post-merge", "post-rewrite")
HOOK_MARK = "Garrick wall check"


def hooks_blocked(ws, path: str) -> bool:
    """Whether Garrick cannot install the wall check in the repository at `path` on its own: a hook that is not Garrick's, or
    a link or a folder, stands in a place of the four, or the repository has no .git folder of its own. Read only. Without a
    workspace the answer is yes, so the finding is asked rather than left out."""
    if ws is None:
        return True
    hooks = Path(str(ws)) / path / ".git" / "hooks"
    if not (Path(str(ws)) / path / ".git").is_dir():
        return True
    for name in HOOK_NAMES:
        slot = hooks / name
        if not os.path.lexists(str(slot)):
            continue
        try:
            ours = slot.is_file() and not slot.is_symlink() and HOOK_MARK in slot.read_text(encoding="utf-8", errors="replace")
        except OSError:
            ours = False
        if not ours:
            return True
    return False


def held_reason(item: dict) -> str:
    """The reason Nurture gave for holding a mechanical fix back, from its line in the record; "" when it gave none."""
    m = HELD.search(str(item.get("line") or item.get("message") or ""))
    return m.group(1) if m else ""


def plain_kind(item: dict) -> str:
    """The plain kind of a standing finding, from Nurture's kind and the check's name and text; "" for a kind with no
    plain wording, "mechanical" for one the nightly run fixes."""
    kind, check, line = str(item.get("kind") or ""), str(item.get("check") or ""), str(item.get("message") or item.get("line") or "")
    if kind == "wall":
        return "wall"
    if kind == MECHANICAL:
        return MECHANICAL
    if kind != "judgment":
        return ""
    if check in ("projects", "threads") and "`note-max-words`" in line and NOTE_RE.search(line):
        return "note-long"
    if check == "resume" and RESUME_RE.search(line):
        return "resume-long"
    if check == "todo" and TODO_RE.search(line):
        return "todo-long"
    if check == "meetings" and MEETING_RE.search(line):
        return "meeting-long"
    if check in ("zones", "hooks") and HOOK_LINE.search(line):
        return HOOKS
    return ""


def about(n: int) -> str:
    """A figure for the ear: to the nearest hundred, to the nearest thousand from ten thousand."""
    step = 1000 if n >= 10000 else 100
    return "about {:,}".format(int(round(n / step) * step))


def later_key(kind: str, path: str) -> str:
    """A finding's key in the Not now file: a hash of its plain kind and its path, so the file holds no path and no
    text of any zone."""
    return hashlib.sha1(("%s\0%s" % (kind, path)).encode("utf-8", "surrogatepass")).hexdigest()[:16]


def later_path(ws) -> Path:
    return Path(ws).joinpath(*LATER_FILE)


def later_hidden(ws, today: Optional[dt.date] = None) -> set:
    """The keys put off and not yet back. A file that is missing, unreadable or of another shape hides nothing."""
    today = today or dt.date.today()
    try:
        data = json.loads(later_path(ws).read_text(encoding="utf-8"))
        rows = data["later"]
    except (OSError, ValueError, KeyError, TypeError):
        return set()
    out = set()
    if isinstance(rows, dict):
        for key, until in rows.items():
            try:
                if isinstance(key, str) and re.fullmatch(r"[0-9a-f]{16}", key) and dt.date.fromisoformat(str(until)) > today:
                    out.add(key)
            except ValueError:
                continue
    return out


def later_put(ws, key: str, today: Optional[dt.date] = None) -> str:
    """Hide a finding for LATER_DAYS days; the day it comes back, ISO. Entries already back are dropped as it
    writes. The one write this module makes, in a file of its own that nothing but the page reads."""
    today = today or dt.date.today()
    until = (today + dt.timedelta(days=LATER_DAYS)).isoformat()
    path = later_path(ws)
    try:
        rows = json.loads(path.read_text(encoding="utf-8")).get("later") or {}
    except (OSError, ValueError, AttributeError):
        rows = {}
    rows = {k: v for k, v in rows.items() if isinstance(k, str) and isinstance(v, str) and v > today.isoformat()} if isinstance(rows, dict) else {}
    rows[key] = until
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "later": rows}, f, sort_keys=True)
        os.replace(tmp, str(path))
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return until


# ---- planning a long note (#539) ---------------------------------------------------------------------------------

STATE_RE = re.compile(r"^##[ \t]+State of play[ \t]*$", re.I)
RULE_RE = re.compile(r"^---[ \t]*$")
DATE_HEAD = r"\*\*(?:\d{1,2} [A-Za-z]+ \d{4}|\d{4}-\d{2}-\d{2})"
BULLET_RE = re.compile(r"^\s*[-*+]\s+" + DATE_HEAD)
ENTRY_RE = re.compile(r"^" + DATE_HEAD)
KEEP_NEWEST = 5           # history.py's own: the newest entries always stay


def no_move_case(text: str, skipped: str) -> str:
    """Why a plan moves nothing, as a key of NO_MOVE, from the note's own text: the four cases of #539."""
    if skipped:
        return "no-state" if "State of play" in skipped else "unreadable"
    lines = text.split("\n")
    state = next((i for i, l in enumerate(lines) if STATE_RE.match(l)), None)
    rule = next((i for i in range(state + 1, len(lines)) if RULE_RE.match(lines[i])), None) if state is not None else None
    if rule is None:
        return "no-state"
    if any(BULLET_RE.match(l) for l in lines[:rule]):
        return "log-bullets"
    entries, blank = 0, True
    for l in lines[rule + 1:]:
        if blank and l.strip() and ENTRY_RE.match(l):
            entries += 1
        blank = not l.strip()
    return "sections" if not entries else "few" if entries <= KEEP_NEWEST else "old-enough"


class Planner:
    """The plans of one build: `history.py dry-run --json` for a note, never a write subcommand, from the workspace's own
    System/tools. A missing tool, a non-zero exit, a reply that is not JSON of the shape, or a run past its time all
    count as "nothing moves". PLAN_BUDGET bounds the whole build: once it is spent, every plan after is "nothing moves"
    without running anything."""

    def __init__(self, ws, budget: float = PLAN_BUDGET, timeout: float = PLAN_TIMEOUT):
        self.ws, self.end, self.timeout = Path(ws), time.monotonic() + budget, timeout
        self.cache: Dict[str, dict] = {}

    def run(self, rel: str) -> Optional[dict]:
        tool = self.ws.joinpath(*HISTORY_TOOL)
        left = self.end - time.monotonic()
        if left <= 0 or not tool.is_file() or not rel or rel.startswith(("/", "~")) or ".." in rel.split("/"):
            return None
        try:
            r = subprocess.run([sys.executable, str(tool), "--root", str(self.ws), "dry-run", rel, "--json"], capture_output=True, text=True,
                               timeout=min(self.timeout, left), stdin=subprocess.DEVNULL, cwd=str(self.ws), env=dict(os.environ, GARRICK_HEADLESS="1"))
            data = json.loads(r.stdout)[0]
        except (OSError, ValueError, IndexError, TypeError, KeyError, subprocess.SubprocessError):
            return None
        return data if r.returncode == 0 and isinstance(data, dict) else None

    def plan(self, rel: str) -> dict:
        """{moves, before, after, still_over, case}: case is "" when entries would move, else a key of NO_MOVE."""
        if rel in self.cache:
            return self.cache[rel]
        data = self.run(rel)
        out = {"moves": 0, "before": 0, "after": 0, "still_over": False, "case": "unknown", "skipped": ""}
        if data is not None:
            skipped = str(data.get("skipped") or "")
            try:
                out.update(moves=int(data.get("entries_moved") or 0), before=int(data.get("words_before") or 0),
                           after=int(data.get("words_after") or 0), still_over=bool(data.get("still_over")), skipped=skipped)
            except (TypeError, ValueError):
                data = None
            if data is not None and (skipped or out["moves"] <= 0):
                out["moves"] = 0
                try:
                    text = self.ws.joinpath(rel).read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    text = ""
                out["case"] = no_move_case(text, skipped)
            elif data is not None:
                out["case"] = ""
        self.cache[rel] = out
        return out


# ---- saying a finding -------------------------------------------------------------------------------------------

def place(path: str) -> str:
    """A zone, a wiki or System as a sentence says it."""
    parts = path.split("/")
    if parts[0] == "Zones" and len(parts) > 1:
        return parts[1]
    if parts[0] == "Wikis" and len(parts) > 1:
        return "the %s wiki" % parts[1]
    return "System"


def stem(path: str) -> str:
    return re.sub(r"\.md$", "", path.rsplit("/", 1)[-1])


def note_name(path: str) -> Tuple[str, bool]:
    """(the project's or the thread's name, whether it is a thread) for a hub or a thread note's path."""
    parts = path.split("/")
    return stem(path), "Threads" in parts


def wall_other(item: dict) -> str:
    """The other zone of a wall finding, from the quick check's text or Nurture's line; "" when neither names it."""
    for text in (item.get("message"), item.get("line")):
        m = WALL_OTHER_RE.search(str(text or ""))
        if m:
            return m.group(1)
    return ""


def said(plain: str, item: dict) -> Tuple[str, str]:
    """(the sentence, the line on why) for a plain kind, with the figures from the finding. No path, setting name or
    command in either."""
    path, text = str(item["path"]), str(item.get("message") or item.get("line") or "")
    if plain == "wall":
        other = wall_other(item) or "another zone"
        here = place(path)
        return ("“%s” in %s points into private material from %s." % (stem(path), here, other),
                "%s stays out of %s. Take it out before anyone else sees the file." % (other[:1].upper() + other[1:], here))
    if plain == "note-long":
        name, thread = note_name(path)
        n = int(NOTE_RE.search(text).group(1))
        return ("The %s %s is getting long: %s words." % (name, "thread note" if thread else "project page", about(n)), WHY[plain])
    if plain == "resume-long":
        name, _ = note_name(path)
        n = int(RESUME_RE.search(text).group(1))
        return ("The resume point of %s is getting long: %s words." % (name, about(n)), WHY[plain])
    if plain == "todo-long":
        n = int(TODO_RE.search(text).group(1))
        return ("%s in the %s to-do list %s longer than an action should be." % (
            "One line" if n == 1 else "%d lines" % n, place(path), "is" if n == 1 else "are"), WHY[plain])
    if plain == "meeting-long":
        n = int(MEETING_RE.search(text).group(1))
        return ("A meeting note is longer than usual: %s words." % about(n), WHY[plain])
    if plain == "fix-failed":
        reason = held_reason(item)
        words = next((w for k, w in HELD_WORDS if k in reason), "Garrick could not make the change safely.")
        return ("A small fix to “%s” in %s could not be made." % (stem(path), place(path)), "%s %s" % (words, WHY[plain]))
    if plain == "hooks-blocked":
        where = place(path)
        return ("%s does not check the walls before a commit." % ("The %s zone" % where if path.startswith("Zones/") else where[:1].upper() + where[1:]),
                WHY[plain])
    raise KeyError(plain)


def handoff_phrase(plain: str, answer: str, item: dict) -> str:
    """The request an answer that needs judgment hands to the assistant. It carries the finding's kind, its path and
    its zones, and never the check's wording: a wall finding's request names the file and the two zones and nothing
    the check repeated."""
    path = str(item["path"])
    if plain == "wall":
        other = wall_other(item) or "another zone"
        return ("Take the private material from %s out of %s. The file is in %s, which is walled from it. "
                "Show me the change before anything is committed." % (other, path, place(path)))
    if plain == "note-long":
        return ("Split the long sections of %s into their own notes in the %s's folder, link them from it, and show me the change "
                "before anything is committed." % (path, "thread" if "/Threads/" in path else "project"))
    if plain == "resume-long":
        return "Shorten the Resume here block of %s so it fits its word limit. Show me the shorter one and change nothing until I say yes." % path
    if plain == "todo-long":
        return ("Shorten the long lines of %s to one action each, and move what came of each into its thread's dated entry. "
                "Show me the change before anything is committed." % path)
    if plain == "fix-failed":
        return "Make the small fix that Nurture holds back for %s, and show me the change before anything is committed." % path
    if plain == "hooks-blocked":
        return ("The repository %s has a commit hook of mine, so Garrick's wall check could not be installed. Add the line "
                "python3 <workspace>/System/tools/check.py --staged --walls-only to my hook, keep the rest of it as it is, "
                "and show me the change before anything is committed." % path)
    if plain == "meeting-long":
        return ("Shorten the meeting page %s to who was there, the key points and the actions. Leave the transcript as it is. "
                "Show me the change before anything is committed." % path)
    raise KeyError(plain)


def free_prefix(plain: str, item: dict) -> str:
    """What goes before the user's own words when the free-text answer is sent: the kind, the path and the zones."""
    path = str(item["path"])
    label = {"wall": "a private-material finding", "note-long": "a note that is too long", "resume-long": "a resume point that is too long",
             "todo-long": "a to-do line that is too long", "meeting-long": "a meeting page that is too long",
             "hooks-blocked": "a commit hook of yours that is in the way", "fix-failed": "a small fix that was held back"}.get(plain, "a check finding")
    if plain == "wall":
        return "About %s in %s (%s, from %s): " % (path, place(path), label, wall_other(item) or "another zone")
    return "About %s (%s): " % (path, label)


def other_files(item: dict) -> List[str]:
    """The files a wall finding names in the other zone, from the check's text, for Show me both texts."""
    other = wall_other(item)
    text = str(item.get("message") or "")
    found = []
    for p in NOTE_PATH_RE.findall(text):
        if p != item["path"] and (not other or p.startswith("Zones/%s/" % other)) and p not in found:
            found.append(p)
    return found[:1]


def question(item: dict, scope: str, plan: Optional[dict] = None) -> dict:
    """One finding as a question. `item` holds kind (Nurture's), path, line and check from the record, and message,
    the quick check's own text, where the card has it. `plan` is the note's plan for a long note (Planner.plan), None
    when none was asked for: the kind's own answers, as before."""
    plain = plain_kind(item)
    if plain == HOOKS:
        plain = "hooks-blocked"      # only a finding Garrick could not fix itself is ever made a question
    elif plain == MECHANICAL and held_reason(item):
        plain = "fix-failed"
    path = str(item["path"])
    details = str(item.get("message") or item.get("line") or "")
    if plain == "wall" and not item.get("listed"):
        return unlisted_wall(item, scope)
    q = {"id": plain or "other", "scope": scope, "path": path, "key": later_key(plain or "other", path), "details": details,
         "recommended": "", "other": wall_other(item) if plain == "wall" else ""}
    if plain not in PLAIN_KINDS:
        q.update(tag=str(item.get("title") or "Check finding"), sentence=re.sub(r"^%s: " % re.escape(path), "", details), why="", answers=[],
                 free=free_prefix("", item))
        return q
    sentence, why = said(plain, item)
    table = ANSWERS[plain]
    if plain == "note-long" and plan is not None:
        if plan["moves"] > 0:
            n = plan["moves"]
            why = "%d older entr%s would move, taking the page from %s words to %s words.%s %s" % (
                n, "y" if n == 1 else "ies", about(plan["before"]), about(plan["after"]),
                " The move alone will not bring it under its limit." if plan["still_over"] else "", why)
        else:
            table = ANSWERS_NO_MOVE[plain]
            plain_why, technical = NO_MOVE[plan["case"]]
            why = plain_why
            q["details"] = "%s\n%s" % (details, technical % plan["skipped"] if "%s" in technical else technical)
    answers = []
    for a in (wall_answers(scope) if plain == "wall" else table):
        a = dict(a)
        if a["action"] == "handoff":
            a["phrase"] = handoff_phrase(plain, a["id"], item)
        elif a["action"] == "open":
            a["reqs"] = [{"verb": "note-open", "path": path}]
        elif a["action"] in ("look", "allow"):
            pass
        else:
            a["req"] = {"verb": "finding", "kind": plain, "path": path, "answer": a["id"]}
        answers.append(a)
    for a in answers:
        fb = FALLBACKS.get(plain, {}).get(a["id"])
        if fb:
            f = dict(next(x for x in ANSWERS_NO_MOVE[plain] if x["id"] == fb))
            f["phrase"] = handoff_phrase(plain, fb, item)
            a["fallback"] = f
    q.update(tag=TAGS[plain], sentence=sentence, why=why, answers=answers, free=free_prefix(plain, item), recommended="" if plain == "wall" else answers[0]["id"])
    if plain == "wall":
        q["wallfile"] = path
    return q


def unlisted_wall(item: dict, scope: str) -> dict:
    """A wall finding that the last Nurture run holds and this page's quick check does not list. The page build runs no check,
    so the question says where the finding is, and the page's own look (`walls-look`, in the app) names the file when the
    question opens. The file is not in the page's markup: the page showed only a count of these (#525). Until then, and in a browser, the one answer hands Nurture's request for that scope
    to the assistant."""
    place_ = place(str(item["path"]))
    ask = str(item.get("ask") or "nurture the context")
    answers = wall_answers(scope)
    for a in answers:
        if a["id"] == "take-out":
            a["phrase"] = ask
            a["does"] = "Your assistant goes through the wall findings of this place with you."
    return {"id": "wall", "scope": scope, "path": "", "key": later_key("wall", str(item["path"])), "other": "",
            "tag": TAGS["wall"], "sentence": "A file in %s points into private material from another zone." % place_,
            "why": "Another zone stays out of %s. The last Nurture run found it; this page's quick check does not list it." % place_,
            "details": "From the last Nurture run. The app checks the file when this question opens.",
            "answers": answers, "free": "About a private-material finding in %s: " % place_, "recommended": ""}


def wall_answers(scope: str) -> List[dict]:
    """The three answers of a wall question, in order, each with what the page needs to ask it (#548, #550)."""
    out = []
    for a in ANSWERS["wall"]:
        a = dict(a)
        if a["action"] == "look":
            a["req"] = {"verb": "walls-look", "place": scope}       # the page adds the file and the finding it was told of
        elif a["action"] == "allow":
            a["req"] = {"verb": "walls-allow"}                      # and the finding and the file's blob that it was shown
        out.append(a)
    return out


def forecast_questions(items: List[dict], hidden: set, ws=None, planner=None) -> Dict[str, List[dict]]:
    """The queue of each scope, from the forecast's findings: the list the scope's line on the card counts, less
    what Not now has put off (a wall finding and missing commit hooks are never put off, whatever a file says). The mechanical ones are not
    asked: the nightly run makes them, and one it held back is asked as fix-failed (#550). With `ws`, a long note is asked from its plan (#539); without it, from its kind. A `planner` shared by several calls spends one budget for all of them."""
    out: Dict[str, List[dict]] = {}
    if planner is None and ws is not None:
        planner = Planner(ws)
    for item in items:
        plain = plain_kind(item)
        if plain == MECHANICAL and not held_reason(item):
            continue                # the nightly run makes it, and the card shows nothing (#550)
        if plain == MECHANICAL:
            plain = "fix-failed"
        if plain == HOOKS:
            if not hooks_blocked(ws, str(item["path"])):
                continue            # automatic: the update and the nightly run install it; it is never asked
            plain = "hooks-blocked"
        if plain not in NEVER_LATER and plain in PLAIN_KINDS and later_key(plain, str(item["path"])) in hidden:
            continue
        plan = planner.plan(str(item["path"])) if planner is not None and plain == "note-long" else None
        out.setdefault(str(item["scope"]), []).append(question(item, str(item["scope"]), plan))
    settle(out)
    return out


def settle(out: Dict[str, List[dict]]) -> None:
    """The order of each scope's queue and the page's own key for each question: a wall finding first, always, then the
    oldest first by the day the question was asked or the decision made (#542); what has no day (a finding of the last
    Nurture run) follows, by kind and path. Two questions with one kind and path stay two."""
    rank = {k: i for i, k in enumerate(PLAIN_KINDS)}
    for qs in out.values():
        qs.sort(key=lambda q: (q["id"] != "wall", 0 if q.get("age") else 1, q.get("age") or "", rank.get(q["id"], len(rank)), q["path"]))
        taken: Dict[str, int] = {}
        for q in qs:
            base = q["key"] + ("-" + hashlib.sha1(q["other"].encode("utf-8", "surrogatepass")).hexdigest()[:6] if q.get("other") else "")
            taken[base] = taken.get(base, 0) + 1
            q["gk"] = base if taken[base] == 1 else "%s.%d" % (base, taken[base])


# ---- the wiki's own questions (#542) ------------------------------------------------------------------------------

def wiki_path(wiki: str, rel: str) -> str:
    return "Wikis/%s/%s" % (wiki, rel)


def asked_base(kind: str, tag: str, path: str, sentence: str, why: str, age: str, answers: List[dict]) -> dict:
    return {"id": kind, "scope": "", "path": path, "key": later_key(kind, path), "details": "", "recommended": "", "other": "", "tag": tag,
            "sentence": sentence, "why": why, "answers": answers, "free": "", "age": age, "field": None, "details_label": "Details"}


def not_now(kind: str, path: str) -> dict:
    return dict(A("later", "Not now", "Ask again in a week.", "later"), req={"verb": "finding", "kind": kind, "path": path, "answer": "later"})


def wiki_question(q: dict) -> dict:
    """A question of a wiki as a queue question: the field for the answer first, then Record as a decision (a Meetings
    question only, as the panel offered it), Later with its day, Close. *From* shows the raw record and the pages the
    answer changes, by name. `q` is questions_panel.read_question's dict."""
    wiki, rel = q["wiki"], q["file"]
    base = {"wiki": wiki, "file": rel}
    one = "the %s question" % wiki
    out = asked_base("wiki-question", "%s question" % wiki, wiki_path(wiki, rel), q["title"], q.get("why") or "", q.get("asked") or "", [])
    answers = []
    if "decide" in (q.get("writes") or {}):
        answers.append(dict(A("decide", "Record as a decision", "Your words become a decision page that stands as valid.", "words"),
                            req=dict(base, verb="question-decide")))
    answers.append(dict(A("later", "Later", "Ask again on a day you pick.", "day"), req=dict(base, verb="question-later")))
    answers.append(dict(A("close", "Close", "Nothing to work in.", "run"), req=dict(base, verb="question-close")))
    out.update(answers=answers, wiki=wiki, file=rel, field={"req": dict(base, verb="question-answer"), "placeholder": "Type the answer",
                                                              "prefix": "Answer %s “%s” with: " % (one, q["title"]), "first": True, "hidden": False})
    origin = (q.get("origin") or {}).get("name")
    pages = [p["name"] for p in q.get("pages") or []]
    out["details"] = " · ".join(x for x in ("raw: %s" % origin if origin else "", "pages: %s" % ", ".join(pages) if pages else "") if x) or "No raw record or page named."
    out["details_label"] = "From"
    return out


def verdict_question(q: dict) -> dict:
    """A proposed verdict: Accept (recommended) closes the question as the panel's Accept did, Answer it myself shows the
    field, Not now puts it off in the page's own file. The verdict and its reason are the why-line."""
    wiki, rel = q["wiki"], q["file"]
    path = wiki_path(wiki, rel)
    reason = q.get("reason") or ""
    why = "Proposed as %s%s." % (q["verdict"], ": %s" % reason.rstrip(".") if reason else "")
    out = asked_base("verdict", "Proposed verdict", path, q["title"], why, q.get("asked") or "", [
        dict(A("accept", "Accept", "Closes the question with this answer.", "run"), req={"verb": "question-close", "wiki": wiki, "file": rel}),
        A("answer-myself", "Answer it myself", "Opens the field.", "reveal"), not_now("verdict", path)])
    out.update(wiki=wiki, file=rel, recommended="accept", field={"req": {"verb": "question-answer", "wiki": wiki, "file": rel},
                                                                 "placeholder": "Type the answer", "first": False, "hidden": True,
                                                                 "prefix": "Answer the %s question “%s” with: " % (wiki, q["title"])})
    return out


def decision_question(d: dict) -> dict:
    """A decision to review: open it, or put it off. Only the user changes a decision's status, so nothing here does."""
    path = wiki_path("Meetings", d["file"])
    out = asked_base("decision-review", "Decision to review", path, "“%s” may no longer hold." % d["title"],
                     "Flagged: %s. Only you change a decision." % d["revisit"].rstrip("."), d.get("decided") or "", [
        dict(A("open", "Open the decision", "Change its status there.", "open"), reqs=[{"verb": "note-open", "path": path}]), not_now("decision-review", path)])
    return out


def asked_questions(data: Optional[dict], hidden: set) -> Dict[str, List[dict]]:
    """The wiki's own questions by scope, from questions_panel.build()'s data: each zone's questions, verdicts and decisions in
    `Zones/<zone>`, and the Knowledge wiki's questions, which carry no zone, in `Wikis/Knowledge`. An item is in the queue of the zone
    it belongs to and no other (the panel's buckets are placed by the walls' own view, and one that is not the item's own zone is passed
    over here too); one put off with Not now is left out until it is back. {} without data."""
    out: Dict[str, List[dict]] = {}
    if not data:
        return out

    def add(scope: str, item: dict) -> None:
        if not (item["id"] in ("verdict", "decision-review") and item["key"] in hidden):
            item["scope"] = scope
            out.setdefault(scope, []).append(item)
    for zone, bucket in sorted((data.get("buckets") or {}).items()):
        for q in bucket.get("questions") or []:
            if q.get("zone") == zone and q.get("shown", True):
                add("Zones/" + zone, verdict_question(q) if q.get("verdict") else wiki_question(q))
        for d in bucket.get("decisions") or []:
            if d.get("zone") == zone:
                add("Zones/" + zone, decision_question(d))
    for q in data.get("knowledge") or []:
        add("Wikis/Knowledge", verdict_question(q) if q.get("verdict") else wiki_question(q))
    return out


def with_asked(queues: Dict[str, List[dict]], asked: Dict[str, List[dict]]) -> Dict[str, List[dict]]:
    """The findings' queues and the wiki's own questions, one queue for each scope, in the order settle() gives."""
    out = {scope: list(qs) for scope, qs in queues.items()}
    for scope, qs in asked.items():
        out.setdefault(scope, []).extend(qs)
    settle(out)
    return out


# ---- answers the night could not work in (#550) ------------------------------------------------------------------

HELD_FILE = ("System", "generated", "status-answers.json")
# Why a place's answers were left, by the code work_in.py keeps: the plain words. The file holds a code and a day, never a path or a title.
ANSWERS_HELD = {"cap": "The assistant's limit for scheduled calls was reached.", "assistant": "The assistant could not be reached tonight.",
                "incomplete": "The assistant did not finish.", "held": "Some of the answers were unclear, so the assistant left them.",
                "commit": "The wall check refused the change, so nothing was kept."}


def held_answers(ws, places: Dict[str, str], waiting: Dict[str, int], hidden: set) -> Dict[str, List[dict]]:
    """A question for each place whose answers the nightly run could not work in and that still holds some: the reason in plain
    words, *Work them in with my assistant* and *Not now*. From System/generated/status-answers.json, which work_in.py keeps. A
    place with no answer waiting has no question, so a stale entry is never shown, and an entry only ever names its own place."""
    try:
        data = json.loads(Path(str(ws)).joinpath(*HELD_FILE).read_text(encoding="utf-8"))
        held = data.get("held") if isinstance(data, dict) else None
    except (OSError, ValueError):
        return {}
    out: Dict[str, List[dict]] = {}
    for scope, entry in sorted((held or {}).items() if isinstance(held, dict) else []):
        if not isinstance(entry, dict) or entry.get("why") not in ANSWERS_HELD or not waiting.get(scope) or scope not in places:
            continue
        key = later_key("answers-held", scope)
        if key in hidden:
            continue
        phrase = "work in the answers in %s" % places[scope]
        sentence = "Your answers in %s could not be worked in." % (scope.split("/", 1)[1] if scope.startswith("Zones/") else places[scope])
        q = asked_base("answers-held", "Answers", scope, sentence, "%s Nothing is lost: the answers are kept as you gave them." % ANSWERS_HELD[entry["why"]], "",
                       [dict(A("work-in", "Work them in with my assistant", "Your assistant works them in and shows you the change.", "handoff"), phrase=phrase),
                        not_now("answers-held", scope)])
        q.update(scope=scope, recommended="work-in", free=free_prefix("", {"path": scope}), details="Left on %s." % str(entry.get("day") or "an earlier night"))
        out[scope] = [q]
    return out


# ---- the page ------------------------------------------------------------------------------------------------------

def E(s) -> str:
    return html.escape(str(s), quote=True)


def question_html(q: dict) -> str:
    rec = q["recommended"]
    field = q.get("field")
    opts, n = "", 0

    def field_row() -> str:
        nonlocal n
        n += 1
        data = {"req": field["req"], "prefix": field["prefix"]}
        return ('<label class="opt other" data-ansrow%s><span class="n">%d</span><input type="text" maxlength="2000" autocomplete="off" '
                'data-ans="%s" placeholder="%s" aria-label="%s"></label>'
                % (" hidden" if field["hidden"] else "", n, E(json.dumps(data, sort_keys=True)), E(field["placeholder"]), E(field["placeholder"])))
    if field and field["first"]:
        opts += field_row()
    for a in q["answers"]:
        n += 1
        data = {"a": a["action"], "id": a["id"]}
        if a["action"] == "handoff":
            data["phrase"] = a["phrase"]
        elif a["action"] == "open":
            data["reqs"] = a["reqs"]
        elif a["action"] != "reveal":
            data["req"] = a["req"]
        wall = q["id"] == "wall"
        hosted = a["action"] != "handoff"
        # a wall's Take it out waits for the page's look to name the file, and The words are mine for the texts (#548, #550)
        gate = (" data-needlook" if wall and a["id"] == "take-out" else " data-needseen hidden" if a["action"] == "allow" else "")
        text = "%s<small>%s%s</small>" % (E(a["label"]), '<b class="recd">Recommended.</b> ' if a["id"] == rec else "", E(a["does"]))
        if a["action"] == "day":      # Later with its day: the day is picked in the answer itself, the button puts it off
            opts += ('<div class="opt later tacts" data-id="%s"><span class="n">%d</span><span>%s<span class="lrow"><input type="date" data-day '
                     'aria-label="Come back on"><button class="act" type="button" data-id="%s" data-fa="%s">Put off</button></span></span></div>'
                     % (E(a["id"]), n, text, E(a["id"]), E(json.dumps(data, sort_keys=True))))
            continue
        opts += ('<button class="opt%s%s" type="button" data-id="%s" data-fa="%s"%s><span class="n">%d</span><span>%s</span></button>'
                 % (" rec" if rec and a["id"] == rec else "", " tacts" if hosted and a["action"] != "reveal" else "", E(a["id"]),
                    E(json.dumps(data, sort_keys=True)), gate, n, text))
        fb = a.get("fallback")
        if fb:        # shown in its place when this answer is refused for "nothing can move" (#540); a handoff, so it needs no host
            opts += ('<button class="opt" type="button" data-id="%s" data-for="%s" data-fa="%s" hidden><span class="n">%d</span><span>%s'
                     '<small><b class="recd">Recommended.</b> %s</small></span></button>'
                     % (E(fb["id"]), E(a["id"]), E(json.dumps({"a": "handoff", "id": fb["id"], "phrase": fb["phrase"]}, sort_keys=True)), n, E(fb["label"]), E(fb["does"])))
    if field and not field["first"]:
        opts += field_row()
    typed = bool(q.get("free") or field)
    web = ""
    if q["answers"] and all(a["action"] != "handoff" for a in q["answers"]):
        web = ('<p class="hint qweb">%s</p>' % ("The other answers need the Garrick app. Here you can send your own words to your assistant." if typed
                                                else "These answers need the Garrick app."))
    if q.get("free"):
        n += 1
        opts += ('<label class="opt other"><span class="n">%d</span><input type="text" maxlength="500" autocomplete="off" '
                 'data-free="%s" placeholder="%s" aria-label="%s"></label>' % (n, E(q["free"]), E(FREE), E(FREE)))
    where = ' data-wiki="%s" data-file="%s"' % (E(q["wiki"]), E(q["file"])) if q.get("wiki") else ""
    if q.get("wallfile"):
        where += ' data-wallfile="%s"' % E(q["wallfile"])
    return ('<div class="q" data-q data-key="%s" data-kind="%s" data-path="%s" data-gk="%s"%s hidden><span class="tag%s">%s</span><p class="qs">%s</p>%s'
            '<div class="opts">%s</div><div class="qtexts" hidden></div>%s<p class="hint qsay" role="status"></p>'
            '<button class="act qskip" type="button" data-qskip hidden>Skip for now</button>'
            '<details class="qdet"><summary>%s</summary><code>%s</code><pre class="qout" hidden></pre></details></div>'
            % (q["key"], E(q["id"]), E(q["path"]), E(q.get("gk") or q["key"]), where, " private" if q["id"] == "wall" else "", E(q["tag"]), E(q["sentence"]),
               '<div class="why">%s</div>' % E(q["why"]) if q["why"] else "", opts, web, E(q.get("details_label") or "Details"), E(q["details"])))


def dialog(root: str, queues: Dict[str, List[dict]], names: Dict[str, str], today: str = "", places: Optional[Dict[str, str]] = None) -> str:
    """The queue's dialog: every scope's questions, hidden until the card's line opens that scope. `places` says each scope as the
    request "work in the answers in <place>" names it: closing a queue that took answers sends that request for its own scope (#550)."""
    if not queues:
        return ""
    body = ""
    for scope, qs in queues.items():
        phrase = (places or {}).get(scope, "")
        body += ('<section class="qscope" data-scope="%s" data-name="%s"%s hidden><div class="prog"><span>%s</span><div class="bar"><i></i></div>'
                 '<span class="qn"></span></div>%s</section>' % (E(scope), E(names.get(scope, scope)),
                                                                  ' data-work="%s"' % E("work in the answers in %s" % phrase) if phrase else "",
                                                                  E(names.get(scope, scope)), "".join(question_html(q) for q in qs)))
    body += ('<section class="qdone" hidden><div class="done"><b></b><span class="qsum"></span><div class="qnext">'
             '<button class="act primary" type="button" data-qnext hidden></button> '
             '<button class="act" type="button" data-qclose>Back to the overview</button></div></div></section>')
    return ('<dialog id="queue" class="findings queue" aria-labelledby="queue-h" data-folder="%s" data-today="%s"><div class="fhead"><h3 id="queue-h">Context</h3>'
            '<button class="act" type="button" data-qclose>Close</button></div><div id="qbody">%s</div></dialog>' % (E(root), E(today), body))


QUEUE_CSS = r"""
/* The queue: one finding at a time, in the page's own tokens */
dialog.queue{width:min(620px,calc(100vw - 32px))}
.queue .prog{display:flex;justify-content:space-between;align-items:center;color:var(--muted);font-size:var(--fs-meta);margin:0 0 12px}
.queue .bar{height:4px;background:var(--line);border-radius:4px;flex:1;margin:0 12px}.queue .bar i{display:block;height:100%;width:0;background:var(--accent);border-radius:4px}
.queue .q{padding:4px 0}.queue .tag{display:inline-block;font-size:var(--fs-meta);font-weight:600;letter-spacing:.03em;text-transform:uppercase;color:var(--muted);margin-bottom:4px}
.queue .tag.private{color:var(--critical)}.queue .qs{margin:0 0 4px;font-weight:600}.queue .why{color:var(--muted);font-size:var(--fs-sub);margin:0 0 12px}
.queue .opts{display:flex;flex-direction:column;gap:7px}
.queue .opt{display:flex;gap:10px;align-items:flex-start;text-align:left;padding:10px 12px;border-radius:10px;width:100%;font:inherit;font-size:var(--fs-sub);color:var(--ink);background:var(--surface);border:1px solid var(--line);cursor:pointer}
.queue .opt .n{flex:none;width:22px;height:22px;border-radius:6px;background:var(--raise);color:var(--muted);font-size:var(--fs-meta);display:grid;place-items:center;font-weight:600}
.queue .opt small{display:block;color:var(--muted);font-size:var(--fs-meta)}.queue .opt.rec{border-color:var(--accent);background:var(--wash)}
.queue .opt.rec .n{background:var(--accent);color:#fff}.queue .recd{font-weight:600;color:var(--ink2)}
.queue .opt.other{cursor:text}.queue .opt.other input{flex:1;border:0;background:transparent;color:var(--ink);font:inherit;outline:none}
.queue .opt:focus-visible,.queue .opt.other:focus-within{outline:2px solid var(--accent);outline-offset:1px}
.queue .qsay{margin:8px 0 0}.queue .qsay.bad{color:var(--critical)}.queue .qdet{margin-top:10px;font-size:var(--fs-meta);color:var(--muted)}
.queue .qdet code,.queue .qdet pre{display:block;white-space:pre-wrap;margin:6px 0 0;font-size:var(--fs-meta);background:var(--raise);padding:8px;border-radius:6px}
.queue .done{text-align:center;padding:24px 8px}.queue .done b{display:block;font-size:var(--fs-h3);margin-bottom:4px}.queue .qnext{margin-top:14px}
.nohost .queue .opt.tacts{display:none}.queue .qweb{display:none;margin:8px 0 0}.nohost .queue .qweb{display:block}
.queue .opt:disabled{opacity:.55;cursor:not-allowed}.queue .opt:not(.rec) .recd{display:none}.queue .qskip{margin-top:8px}
.queue .opt.later{cursor:default}.queue .lrow{display:flex;gap:8px;align-items:center;margin-top:6px}
.queue .lrow input{font:inherit;font-size:var(--fs-meta);color:var(--ink);background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:3px 8px}
.queue .q[data-kind="wall"]:not(.looked) .opt[data-needlook]{display:none}.nohost .queue .q[data-kind="wall"] .opt[data-needlook]{display:flex}
.queue .qtexts{margin:10px 0 0}.queue .qtext{background:var(--raise);border:1px solid var(--line);border-radius:8px;padding:8px 10px;margin:0 0 8px;font-size:var(--fs-meta);overflow-wrap:anywhere}
.queue .qtext small{display:block;color:var(--muted);margin-bottom:3px}.queue .qtext mark{background:var(--wash);color:var(--ink);font-weight:600;border-radius:3px}
.queue .opt[hidden],.queue .qskip[hidden],.queue .q[hidden],.queue .qscope[hidden],.queue .qdone[hidden]{display:none}
"""

QUEUE_JS = r"""
(function(){var dlg=document.getElementById('queue');
var host=window.webkit&&window.webkit.messageHandlers&&window.webkit.messageHandlers.garrick;
var KEY='garrick-queue',st={get:function(k){try{return sessionStorage.getItem(k)}catch(e){return null}},set:function(k,x){try{sessionStorage.setItem(k,x)}catch(e){}},del:function(k){try{sessionStorage.removeItem(k)}catch(e){}}};
function say(t){var s=document.getElementById('toast');if(s){s.textContent=t;s.classList.add('on');setTimeout(function(){s.classList.remove('on')},3500)}}
if(!dlg)return;
/* the tally's lines, in the order the summary says them: one row to add for a new way of answering */
var LINES=[['done','done'],['handed','handed to your assistant'],['opened','opened'],['later','put off to next week'],['skipped','skipped']],UNSAVED=['skipped'];
function fresh(){var t={};LINES.forEach(function(l){t[l[0]]=0});return t}
var tally=fresh(),notes={},gone={},skip={},refused={},pend=null,cur=null,taken={};
function all(){return[].slice.call(dlg.querySelectorAll('.qscope'))}
function qs(s){return[].slice.call(s.querySelectorAll('[data-q]'))}
function pending(s){return qs(s).filter(function(q){return!gone[q.dataset.gk]&&!skip[q.dataset.gk]})}
/* what a reload keeps: the answers given, never a refusal, a disabled answer or a skip (Skip for now is the dialog's, not the disk's) */
function kept(){var t={},n={};for(var k in tally)if(UNSAVED.indexOf(k)<0)t[k]=tally[k];for(var g in notes)if(!notes[g].bad)n[g]=notes[g];return{tally:t,notes:n}}
function save(){if(cur){var k=kept();st.set(KEY,JSON.stringify({scope:cur.dataset.scope,gone:gone,tally:k.tally,notes:k.notes,pend:pend,taken:taken,t:Date.now()}))}}
function sum(){var p=[];LINES.forEach(function(l){if(tally[l[0]])p.push(tally[l[0]]+' '+l[1])});return p.join(', ')||'Nothing answered.'}
function next(){var o=all().filter(function(s){return s!==cur&&pending(s).length});return o[0]||null}
function out(q,text,bad,detail){var s=q.querySelector('.qsay');s.textContent=text||'';s.classList.toggle('bad',!!bad);
var p=q.querySelector('.qout');if(detail){p.textContent=detail;p.hidden=false}else p.hidden=true}
var RECS='.opt.rec:not([hidden]):not(:disabled)';
function foc(q){var c=[q.querySelector(RECS),q.querySelector('.opts>[data-ansrow]:first-child input'),q.querySelector('button.opt'),q.querySelector('.opt.other input')];
for(var i=0;i<c.length;i++)if(c[i]&&c[i].getClientRects().length){c[i].focus();return}}
/* A browser has no host, so a hosted answer is hidden there: a question left with no answer to see (the reveal of a field is not one) can only be skipped, so Skip for now shows at once */
function bare(q){var seen=[].slice.call(q.querySelectorAll('.opts button.opt,.opts input[data-free]')).some(function(x){
var d={};try{d=JSON.parse(x.dataset.fa||'{}')}catch(e){}return d.a!=='reveal'&&x.getClientRects().length});
if(!seen)q.querySelector('[data-qskip]').hidden=false}
/* A wall question, in the app (#548, #550): when it opens the page asks which file it is about (walls-look); Show me both texts reads the
   words the two files share into the dialog; only then does The words are mine show. The texts live in the dialog's own elements and
   nowhere else: not the session store, not the tally. They go when the question changes and when the dialog closes. */
var seen={},placed={};
function clearTexts(){seen={};[].forEach.call(dlg.querySelectorAll('.qtexts'),function(t){t.textContent='';t.hidden=true});
[].forEach.call(dlg.querySelectorAll('[data-needseen]'),function(b){b.hidden=true})}
function lookup(q){if(!host||q.dataset.kind!=='wall'||q.dataset.checked)return;q.dataset.checked='1';out(q,'Checking the file…');
var req={verb:'walls-look',place:cur.dataset.scope};if(q.dataset.wallfile)req.path=q.dataset.wallfile;
else{if(placed[cur.dataset.scope]){looked(req,placed[cur.dataset.scope]);return}if(cur.dataset.checking)return;cur.dataset.checking='1'}host.postMessage({act:req})}
function wallq(path){return cur?qs(cur).filter(function(x){return x.dataset.kind==='wall'&&x.dataset.wallfile===path})[0]:null}
function textBlock(t){var d=document.createElement('div');d.className='qtext';var h=document.createElement('small');h.textContent=t.where;d.appendChild(h);
d.appendChild(document.createTextNode(t.before));var m=document.createElement('mark');m.textContent=t.run;d.appendChild(m);d.appendChild(document.createTextNode(t.after));return d}
function nothing(el,res){var sb=el.querySelector('[data-id="show-both"]');if(sb)sb.hidden=true;out(el,res&&res.ok?res.say||'The check finds nothing to take out in this file now.':(res&&res.say)||'The check could not run, so nothing can be taken out from here.',!(res&&res.ok))}
function named(el,f,res){el.dataset.wallfile=f.path;el.dataset.lookid=f.id;
if(f.sentence)el.querySelector('.qs').textContent=f.sentence;if(f.why){var wy=el.querySelector('.why');if(wy)wy.textContent=f.why}
var dc=el.querySelector('.qdet code');if(dc&&f.details)dc.textContent=f.details;el.classList.add('looked');out(el,'')}
function looked(req,res){
if(!req.path){delete cur.dataset.checking;placed[cur.dataset.scope]=res;var by={};((res&&res.ok&&res.findings)||[]).forEach(function(f){if(!by[f.key]||f.rule==='wording'&&by[f.key].rule!=='wording')by[f.key]=f});
qs(cur).filter(function(x){return x.dataset.kind==='wall'&&x.dataset.checked&&!x.dataset.wallfile&&!x.dataset.lookid}).forEach(function(el){var wk=el.getAttribute('data-key');if(by[wk])named(el,by[wk],res);else nothing(el,res)});return}
var el=wallq(req.path);if(!el)return;
if(!res||!res.ok){out(el,(res&&res.say)||'That could not be shown.',true);return}
if(!req.id){var f=res.findings||[];if(!f.length){nothing(el,res);return}
named(el,f.filter(function(x){return x.rule==='wording'})[0]||f[0],res);return}
if(!res.a||!res.b){out(el,res.say||'Nothing to show for this one.',true);return}
var box=el.querySelector('.qtexts');box.textContent='';box.appendChild(textBlock(res.a));box.appendChild(textBlock(res.b));box.hidden=false;
seen[el.dataset.gk]={id:req.id,blob:res.blob};[].forEach.call(el.querySelectorAll('[data-needseen]'),function(b){b.hidden=false});out(el,'')}
function allowed(req,res){var el=wallq(req.path);pend=null;if(!el)return;if(res&&res.ok){finish(el,'done');return}out(el,(res&&res.say)||'That did not work.',true)}
function show(done0){if(!cur)return;clearTexts();var every=qs(cur),left=done0?[]:pending(cur),n=every.length;every.forEach(function(q){q.hidden=true});
var done=dlg.querySelector('.qdone');
if(!left.length){cur.hidden=true;done.hidden=false;done.querySelector('b').textContent=cur.dataset.name+' is done.';
done.querySelector('.qsum').textContent=sum();var nx=next(),b=done.querySelector('[data-qnext]');b.hidden=!nx;
if(nx){b.textContent='Go on to '+nx.dataset.name;b.dataset.qnext=nx.dataset.scope}
if(every.some(function(q){return skip[q.dataset.gk]}))save();else st.set(KEY,JSON.stringify({scope:cur.dataset.scope,done:true,tally:tally,taken:taken,t:Date.now()}));return}
done.hidden=true;cur.hidden=false;var k=n-left.length+1,q=left[0];q.hidden=false;
cur.querySelector('.qn').textContent=k+' of '+n;cur.querySelector('.bar i').style.width=(k/n*100)+'%';
var m=notes[q.dataset.gk],f=refused[q.dataset.gk];if(m)out(q,m.say,m.bad,m.detail);if(f)refuse(q,f);lookup(q);bare(q);save();foc(q)}
/* A refused answer stays open by design. It is disabled, with the refusal under the answers, and Skip for now shows. When the refusal says
   nothing can move, the handoff that stands in for the move takes its place, with its number. */
function refuse(q,f){out(q,f.say,true);var b=q.querySelector('button.opt[data-id="'+f.id+'"]')||q.querySelector('.opt[data-id="'+f.id+'"] button[data-fa]');if(b){b.disabled=true;b.classList.remove('rec')}
if(f.cant){var fb=q.querySelector('button.opt[data-for]');if(fb){var r=q.querySelector('button.opt[data-id="'+fb.dataset.for+'"]');
if(r){r.hidden=true;r.classList.remove('rec')}fb.hidden=false;fb.classList.add('rec')}}
q.querySelector('[data-qskip]').hidden=false}
function open(scope){var s=all().filter(function(x){return x.dataset.scope===scope})[0];if(!s)return;all().forEach(function(x){x.hidden=true});
cur=s;tally=fresh();gone={};notes={};skip={};refused={};pend=null;if(!dlg.open)dlg.showModal();show()}
/* The app rebuilds the page after an answer that changed something and reloads it: the queue comes back where it was, and an
   answer sent just before the reload is counted from what the new page shows */
function restore(){var r=null;try{r=JSON.parse(st.get(KEY)||'null')}catch(e){}if(!r||Date.now()-r.t>9e5){st.del(KEY);return}
taken=r.taken||{};var s=r.scope&&all().filter(function(x){return x.dataset.scope===r.scope})[0];
if(!s){if(Object.keys(taken).length)st.set(KEY,JSON.stringify({taken:taken,t:Date.now()}));else st.del(KEY);return}
cur=s;gone=r.gone||{};tally=Object.assign(fresh(),r.tally||{});notes=r.notes||{};skip={};refused={};pend=null;
if(r.done){dlg.showModal();show(true);return}
if(r.pend&&r.pend.key){var here=qs(s).some(function(q){return q.dataset.gk===r.pend.key});
if(!here){gone[r.pend.key]=1;tally[r.pend.id==='later'?'later':'done']++}
else notes[r.pend.key]={say:'It is still open. The change was not made, or was refused.',bad:true}}
dlg.showModal();show()}
function finish(q,kind){gone[q.dataset.gk]=1;tally[kind]++;pend=null;show()}
function handoff(phrase){var b=document.createElement('button');b.type='button';b.setAttribute('data-request',phrase);
b.setAttribute('data-folder',dlg.dataset.folder||'');b.hidden=true;dlg.appendChild(b);b.click();b.remove()}
document.addEventListener('click',function(e){var t=e.target&&e.target.closest?e.target:null;if(!t)return;
var o=t.closest('[data-qopen]');if(o){e.preventDefault();open(o.dataset.qopen);return}
if(t.closest('[data-qclose]')){st.del(KEY);if(dlg.open)dlg.close();return}
var nx=t.closest('[data-qnext]');if(nx&&nx.dataset.qnext){tally=fresh();cur=all().filter(function(x){return x.dataset.scope===nx.dataset.qnext})[0];gone={};notes={};skip={};refused={};pend=null;show();return}
var sk=t.closest('#queue [data-qskip]');if(sk){var sq=sk.closest('[data-q]');skip[sq.dataset.gk]=1;tally.skipped++;pend=null;show();return}
var b=t.closest('#queue button[data-fa]');if(!b)return;var q=b.closest('[data-q]'),d;try{d=JSON.parse(b.dataset.fa)}catch(err){return}
if(d.a==='handoff'){handoff(d.phrase);finish(q,'handed');return}
if(d.a==='reveal'){var rw=q.querySelector('[data-ansrow]');if(rw){rw.hidden=false;var ri=rw.querySelector('input');if(ri)ri.focus()}return}
if(!host)return;
if(d.a==='look'){if(!q.dataset.lookid){out(q,'Garrick has not found the file yet.',true);return}out(q,'Reading both files…');host.postMessage({act:Object.assign({},d.req,{path:q.dataset.wallfile,id:q.dataset.lookid})});return}
if(d.a==='allow'){var sn=seen[q.dataset.gk];if(!sn||!sn.blob)return;pend={key:q.dataset.gk,id:'keep'};host.postMessage({act:Object.assign({},d.req,{path:q.dataset.wallfile,id:sn.id,blob:sn.blob})});return}
if(d.a==='open'){d.reqs.forEach(function(r){host.postMessage({act:r})});finish(q,'opened');return}
/* an answer that takes the user's words or a day reads them from the question's own field, and the request is the verb the Questions panel used */
var extra={};
if(d.a==='words'){var wi=q.querySelector('input[data-ans]'),w=wi?wi.value.trim():'';if(!w){if(wi)wi.focus();out(q,'Say it in your own words first.',true);return}extra={words:w}}
if(d.a==='day'){var di=q.querySelector('input[data-day]'),v=di?di.value:'';if(!v){if(di)di.focus();out(q,'Pick the day to come back on.',true);return}
if(v<=(dlg.dataset.today||'')){di.focus();out(q,'Pick a day after today.',true);return}extra={until:v}}
pend={key:q.dataset.gk,id:d.id};save();host.postMessage({act:Object.assign({},d.req,extra)})});
/* the field of a wiki question, or of a verdict the user answers himself: Return sends the words as question-answer, or, in a browser, as a request to the assistant */
function answerWords(q,input,w){var d;try{d=JSON.parse(input.dataset.ans)}catch(err){return}
if(!host){handoff(d.prefix+w);finish(q,'handed');return}
pend={key:q.dataset.gk,id:'answer'};save();host.postMessage({act:Object.assign({},d.req,{words:w})})}
/* keys: 1 to 4 answer, the last number is the free-text field, Return takes the recommended one, Esc closes (the dialog's own) */
dlg.addEventListener('keydown',function(e){if(e.metaKey||e.ctrlKey||e.altKey)return;var q=cur&&pending(cur)[0];if(!q||q.hidden)return;
var typing=e.target&&e.target.tagName==='INPUT';
if(typing){if(e.key==='Enter'){if(e.isComposing||e.keyCode===229)return;
if(e.target.type==='date'){var db=e.target.closest('.opt').querySelector('button[data-fa]');if(db){e.preventDefault();db.click()}return}
var w=e.target.value.trim();if(w){e.preventDefault();if(e.target.dataset.ans)answerWords(q,e.target,w);else{handoff(e.target.dataset.free+w);finish(q,'handed')}}}return}
if(e.key==='Enter'){if(e.target.closest&&e.target.closest('summary,a,input,textarea,select,button'))return;var r=q.querySelector(RECS);if(r){e.preventDefault();r.click()}return}
if(/^[1-4]$/.test(e.key)){var opts=[].filter.call(q.querySelectorAll('.opt'),function(x){return!x.hidden&&x.getClientRects().length}),o=opts[+e.key-1];if(!o)return;e.preventDefault();
if(o.classList.contains('other')||o.classList.contains('later')){o.querySelector('input').focus()}else o.click()}});
/* Closing the queue works in the answers it took (#550): one request that names the place, to the default assistant, for each place that took
   an answer since the last close. The count is cleared as the request goes, so a second close sends none, and a queue that took none sends none. */
dlg.addEventListener('close',function(){var sent=taken;taken={};st.del(KEY);
Object.keys(sent).forEach(function(sc){var t=sent[sc];if(!t||!t.n||!t.work)return;handoff(t.work)})});
dlg.addEventListener('close',function(){clearTexts();placed={}});
var prev=window.GarrickActed;window.GarrickActed=function(q,res){
if(q&&q.verb==='walls-look'){looked(q,res);return}
if(q&&q.verb==='walls-allow'){allowed(q,res);return}
var ask=q&&/^question-/.test(q.verb||'');
if(q&&(q.verb==='finding'||ask)&&cur){var p=pend,el=qs(cur).filter(function(x){return p&&p.key?x.dataset.gk===p.key:ask?x.dataset.wiki===q.wiki&&x.dataset.file===q.file:x.dataset.kind===q.kind&&x.dataset.path===q.path})[0];pend=null;
if(el){if(res&&res.ok){if(q.verb==='question-answer'||q.verb==='question-decide')(taken[cur.dataset.scope]=taken[cur.dataset.scope]||{n:0,work:cur.dataset.work||''}).n++;if(q.answer==='preview'){notes[el.dataset.gk]={say:res.say,detail:res.detail||'',bad:false};out(el,res.say,false,res.detail);save();foc(el)}
else if(q.answer==='later'||q.verb==='question-later')finish(el,'later');else finish(el,'done')}
else{var say=(res&&res.say)||'That did not work.';delete notes[el.dataset.gk];
refused[el.dataset.gk]={say:say,id:(p&&p.id)||q.answer,cant:/^nothing (can move|is old enough)/i.test(say)};refuse(el,refused[el.dataset.gk]);save();foc(el)}}}
if(prev)return prev(q,res)};
restore()})();
"""
