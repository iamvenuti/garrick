#!/usr/bin/env python3
"""history.py: keep a hub or thread note short by moving its old dated entries to history files.

    python3 System/tools/history.py dry-run                       every note it would trim, before and after
    python3 System/tools/history.py dry-run --scope Zones/Work/Acme
    python3 System/tools/history.py apply Zones/Work/Acme/Threads/Pricing/Pricing.md
    python3 System/tools/history.py apply --scope Zones/Work --json
    python3 System/tools/history.py apply <note> --commit "Acme, Pricing: older entries moved to history"
    python3 System/tools/history.py resume <note>                 the Resume here block's words and its limit

A note's dated entries sit under `## State of play`, below the first `---`
rule, newest first. An entry is a paragraph that opens with a bold date, such
as `**10 November 2026.**`, and every paragraph after it up to the next entry
belongs to it. This tool moves entries, unchanged, to
`history/<Note> history <YYYY>-Q<n>.md` in the note's own folder, one file for
each calendar quarter of the entry's own date, and leaves one line under the
last entry that links them: `*Older entries: [[<Note> history 2026-Q4]], ...*`.

**What moves.** Step 1: every entry older than `history-months` (6). Step 2:
if the note is still longer than `note-max-words` (4,000), the oldest entries,
until it fits. The newest five entries always stay, whatever their age, and
there is no time floor. The three settings are `history-months`,
`note-max-words` and `resume-max-words` (400) in System/garrick-settings.json.
The Resume here block is never touched: when it is longer than its limit the
tool says so and a person decides what shrinks (the threads skill's Wrap).

**A history file** holds its frontmatter (`type: history`, `parent:`, the
note's own `project:`, `party:` and `zone:` where it has them, `created:`), its
heading and the entries, and nothing else: no sentence two history files could
share. It has no `status:`, so no tool reads it as a thread. A relative
Markdown link inside a moved entry is rewritten so it still leads where it led
from `history/`; every other character of an entry is kept.

**Fail closed.** A note is skipped, reported, and nothing of it moved when it
has no `## State of play` or no `---` rule under it, when an entry's date does
not parse, when it has carriage returns, or when a history file it would add
to is not one this tool wrote. After the move, every line that left the note
must be found in a history file; if one is not, the note and the files are put
back exactly as they were, and the run fails. A second run on the same note
changes nothing.

`dry-run` writes nothing. `apply` writes files and commits nothing, unless
`--commit MESSAGE` is given, which stages the files it wrote by name, runs the
walls check on them as staged and commits them in the note's own repository,
or refuses and leaves them staged-out and changed. Standard library only.
Exit codes: 0 done (a skipped note is reported, not an error), 1 a move that
was put back or a commit that was refused, 2 a usage error.
"""

from __future__ import annotations

import argparse
import calendar
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import garrick_lib as gl  # noqa: E402

DEFAULTS = {"history-months": 6, "note-max-words": 4000, "resume-max-words": 400}
KEEP_NEWEST = 5                 # the entries a note always keeps
FOLDER = "history"
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december"]
_MONTH_NUMBER = {name: i + 1 for i, name in enumerate(MONTHS)}
_MONTH_NUMBER.update({name[:3]: i + 1 for i, name in enumerate(MONTHS)})
_MONTH_NUMBER["sept"] = 9
# A paragraph that opens with a bold date, in the two forms a wrap writes, and a paragraph that looks like one.
DATED_RE = re.compile(r"^\*\*(?:(\d{1,2}) ([A-Za-z]+) (\d{4})|(\d{4})-(\d{2})-(\d{2}))(?![0-9A-Za-z])")
DATE_SHAPE_RE = re.compile(r"^\*\*(?:\d{1,2} [A-Za-z]+ \d{4}|\d{4}-\d{2}-\d{2})")
LINK_LINE_RE = re.compile(r"^\*Older entries: .*\*[ \t]*$")
STATE_RE = re.compile(r"^##[ \t]+State of play[ \t]*$", re.I)
H2_RE = re.compile(r"^##[ \t]")
RESUME_RE = re.compile(r"^###[ \t]+Resume here[ \t]*$", re.I)
HEADING_RE = re.compile(r"^ {0,3}#{1,6}[ \t]")
RULE_RE = re.compile(r"^---[ \t]*$")
FENCE_RE = re.compile(r"^ {0,3}(```|~~~)")
MDLINK_RE = re.compile(r"(\]\()(<[^>\n]*>|[^)\s]+)((?:\s+\"[^\"]*\")?\))")


class Skip(Exception):
    """A note this tool does not touch, and why."""


# ---------------------------------------------------------------------------
# Settings


def limits(root) -> Dict[str, int]:
    """The three settings, from System/garrick-settings.json over the defaults. A value that is not a whole
    number above zero is left out, so the default stands."""
    found = gl.read_settings(root)
    out = dict(DEFAULTS)
    for key in DEFAULTS:
        value = found.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            out[key] = value
    return out


# ---------------------------------------------------------------------------
# Reading a note


def count_words(text: str) -> int:
    return len(text.split())


def body_start(lines: List[str]) -> int:
    """The index of the first line after the frontmatter, 0 when there is none."""
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i] in ("---", "..."):
                return i + 1
    return 0


def _fenced(lines: List[str]) -> List[bool]:
    """For each line, whether it sits inside a fenced code block (the fence lines included)."""
    out, mark = [], ""
    for line in lines:
        m = FENCE_RE.match(line)
        if mark:
            out.append(True)
            if m and m.group(1) == mark and set(line.strip()) <= set(mark):
                mark = ""
        elif m:
            mark = m.group(1)
            out.append(True)
        else:
            out.append(False)
    return out


class Entry:
    def __init__(self, lines: List[str], date: datetime.date, index: int):
        self.lines = lines
        self.date = date
        self.index = index

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    @property
    def quarter(self) -> str:
        return "%d-Q%d" % (self.date.year, (self.date.month - 1) // 3 + 1)

    @property
    def words(self) -> int:
        return count_words(self.text)


def _date_of(line: str) -> Optional[datetime.date]:
    m = DATED_RE.match(line)
    if not m:
        return None
    try:
        if m.group(1):
            month = _MONTH_NUMBER.get(m.group(2).lower())
            return datetime.date(int(m.group(3)), month, int(m.group(1))) if month else None
        return datetime.date(int(m.group(4)), int(m.group(5)), int(m.group(6)))
    except ValueError:
        return None


class Parsed:
    """A note cut at the places that matter: `head` (everything up to and including the rule, then the lines
    before the first entry), `entries`, and `tail` (what follows the entries: the next `##` section, if any)."""

    def __init__(self, head: List[str], entries: List[Entry], tail: List[str], had_link_line: bool):
        self.head, self.entries, self.tail, self.had_link_line = head, entries, tail, had_link_line


def parse(text: str) -> Parsed:
    """Cut `text`. Raises Skip, with the reason, when the note cannot be read for certain."""
    if "\r" in text:
        raise Skip("the note has carriage returns, so its lines cannot be told apart for certain")
    lines = text.split("\n")
    fenced = _fenced(lines)
    start = body_start(lines)
    state = next((i for i in range(start, len(lines)) if not fenced[i] and STATE_RE.match(lines[i])), None)
    if state is None:
        raise Skip("it has no `## State of play` section")
    end = next((i for i in range(state + 1, len(lines)) if not fenced[i] and H2_RE.match(lines[i])), len(lines))
    rule = next((i for i in range(state + 1, end) if not fenced[i] and RULE_RE.match(lines[i])), None)
    if rule is None:
        raise Skip("it has no `---` rule under `## State of play`")
    region = list(range(rule + 1, end))
    had_link_line = False
    keep: List[int] = []
    for i in region:
        if not fenced[i] and LINK_LINE_RE.match(lines[i]):
            had_link_line = True
        else:
            keep.append(i)
    # paragraphs of the region: runs of lines between blank lines, a fenced block never split
    starts: List[int] = []           # indexes into `keep` where an entry opens
    dates: List[datetime.date] = []
    previous_blank = True
    for k, i in enumerate(keep):
        line = lines[i]
        blank = not line.strip() and not fenced[i]
        if previous_blank and not blank and not fenced[i]:
            if DATE_SHAPE_RE.match(line):
                when = _date_of(line)
                if when is None:
                    raise Skip("an entry's date does not parse: %s" % line[:40].replace("\n", " "))
                starts.append(k)
                dates.append(when)
        previous_blank = blank
    if not starts:
        head = lines[:end]
        return Parsed(head, [], lines[end:], had_link_line)
    entries = []
    for n, k in enumerate(starts):
        stop = starts[n + 1] if n + 1 < len(starts) else len(keep)
        block = [lines[i] for i in keep[k:stop]]
        while block and not block[-1].strip():
            block.pop()
        entries.append(Entry(block, dates[n], n))
    head = lines[:rule + 1] + [lines[i] for i in keep[:starts[0]]]
    return Parsed(head, entries, lines[end:], had_link_line)


def render(parsed: Parsed, kept: List[Entry], link_line: str) -> str:
    """The note with only `kept` entries, in their order, a blank line between them, then the link line."""
    head = list(parsed.head)
    while head and not head[-1].strip():
        head.pop()
    out = head + [""]
    for entry in kept:
        out += entry.lines + [""]
    if link_line:
        out += [link_line, ""]
    tail = list(parsed.tail)
    if tail:
        out += tail
    else:
        while out and not out[-1].strip():
            out.pop()
        out.append("")
    return "\n".join(out)


def resume_block(text: str) -> Optional[str]:
    """The Resume here block: from its heading to the rule that ends it (or the next heading), or None."""
    lines = text.split("\n")
    fenced = _fenced(lines)
    start = next((i for i in range(body_start(lines), len(lines)) if not fenced[i] and RESUME_RE.match(lines[i])), None)
    if start is None:
        return None
    for j in range(start + 1, len(lines)):
        if not fenced[j] and (RULE_RE.match(lines[j]) or HEADING_RE.match(lines[j])):
            return "\n".join(lines[start + 1:j])
    return "\n".join(lines[start + 1:])


def note_words(text: str) -> int:
    lines = text.split("\n")
    return count_words("\n".join(lines[body_start(lines):]))


def resume_words(text: str) -> int:
    block = resume_block(text)
    return count_words(block) if block is not None else 0


# ---------------------------------------------------------------------------
# What to move


def months_ago(today: datetime.date, months: int) -> datetime.date:
    index = today.year * 12 + today.month - 1 - months
    year, month = divmod(index, 12)
    month += 1
    return datetime.date(year, month, min(today.day, calendar.monthrange(year, month)[1]))


def note_over(words: int, limit: int) -> str:
    """What check.py says of a note over its limit; nurture.py's HISTORY_RE reads its opening words."""
    return ("has %d words, over the %d of `note-max-words`; move its older dated entries to history files "
            "(`python3 System/tools/history.py dry-run` lists what would move)" % (words, limit))


def resume_over(words: int, limit: int) -> str:
    return ("its Resume here block has %d words, over the %d of `resume-max-words`; the next wrap or Nurture "
            "proposes a shorter one, and nothing changes without a yes" % (words, limit))


def link_target_of(note: Path, quarter: str) -> str:
    return "%s history %s" % (note.stem, quarter)


def link_line(note: Path, quarters) -> str:
    """The one line under the last kept entry, the newest quarter first."""
    names = sorted(set(quarters), key=lambda q: (int(q[:4]), int(q[-1])), reverse=True)
    if not names:
        return ""
    return "*Older entries: %s.*" % ", ".join("[[%s]]" % link_target_of(note, q) for q in names)


def existing_quarters(note: Path) -> List[str]:
    folder = note.parent / FOLDER
    prefix = "%s history " % note.stem
    out = []
    if folder.is_dir():
        for path in folder.glob("*.md"):
            m = re.fullmatch(r"%s(\d{4}-Q[1-4])\.md" % re.escape(prefix), path.name)
            if m:
                out.append(m.group(1))
    return out


class Plan:
    """What one note would do: the entries it moves (by quarter), its counts before and after, or why it is skipped."""

    def __init__(self, note: Path):
        self.note = note
        self.skipped = ""
        self.moves: List[Entry] = []
        self.before = self.after = 0
        self.resume = 0
        self.resume_over = False
        self.still_over = False
        self.parsed: Optional[Parsed] = None
        self.text = ""
        self.new_text = ""
        self.quarters: Dict[str, List[Entry]] = {}

    def as_dict(self, root: Path) -> dict:
        return {"note": self.note.relative_to(root).as_posix(), "skipped": self.skipped,
                "entries_moved": len(self.moves), "words_before": self.before, "words_after": self.after,
                "quarters": sorted(self.quarters), "resume_words": self.resume, "resume_over": self.resume_over,
                "still_over": self.still_over}


def plan(root, note: Path, today: Optional[datetime.date] = None) -> Plan:
    """The plan for `note`: no file is written."""
    root, note = Path(root), Path(note)
    today = today or datetime.date.today()
    cap = limits(root)
    p = Plan(note)
    try:
        p.text = note.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as why:
        p.skipped = "it cannot be read (%s)" % type(why).__name__
        return p
    p.before = note_words(p.text)
    p.resume = resume_words(p.text)
    p.resume_over = p.resume > cap["resume-max-words"]
    try:
        p.parsed = parse(p.text)
    except Skip as why:
        p.skipped = str(why)
        return p
    entries = p.parsed.entries
    protected = {e.index for e in sorted(entries, key=lambda e: (-e.date.toordinal(), e.index))[:KEEP_NEWEST]}
    cutoff = months_ago(today, cap["history-months"])
    moving = {e.index for e in entries if e.index not in protected and e.date < cutoff}
    quarters = set(existing_quarters(note)) | {e.quarter for e in entries if e.index in moving}

    def words_with(moved: set) -> int:
        kept = [e for e in entries if e.index not in moved]
        return note_words(render(p.parsed, kept, link_line(note, quarters | {e.quarter for e in entries if e.index in moved})))

    if moving or p.before > cap["note-max-words"]:
        movable = sorted((e for e in entries if e.index not in protected and e.index not in moving),
                         key=lambda e: (e.date.toordinal(), -e.index))
        while words_with(moving) > cap["note-max-words"] and movable:
            moving.add(movable.pop(0).index)
        p.still_over = words_with(moving) > cap["note-max-words"]
    p.moves = [e for e in entries if e.index in moving]
    for e in p.moves:
        p.quarters.setdefault(e.quarter, []).append(e)
    if p.moves:
        quarters = set(existing_quarters(note)) | set(p.quarters)
        kept = [e for e in entries if e.index not in moving]
        p.new_text = render(p.parsed, kept, link_line(note, quarters))
        p.after = note_words(p.new_text)
    else:
        p.after = p.before
        p.still_over = p.before > cap["note-max-words"] and bool(entries)
    return p


# ---------------------------------------------------------------------------
# The history files


def rewrite_links(text: str) -> str:
    """`text` with each relative Markdown link given one more `../`, so it leads where it led before the entry
    moved into `history/`. A wikilink, an address, a link to an anchor and a rooted path stay as they are."""
    def one(m) -> str:
        target = m.group(2)
        inner = target[1:-1] if target.startswith("<") else target
        if not inner or inner.startswith(("#", "/", "~")) or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", inner):
            return m.group(0)
        shown = "<../%s>" % inner if target.startswith("<") else "../%s" % inner
        return m.group(1) + shown + m.group(3)
    return MDLINK_RE.sub(one, text)


def _fm_lines(text: str, keys: Tuple[str, ...]) -> List[str]:
    """The frontmatter lines of `keys` in `text`, each with the lines that continue it, as written."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return []
    out, take = [], False
    for line in lines[1:]:
        if line in ("---", "..."):
            break
        m = re.match(r"([A-Za-z_][\w -]*?)\s*:", line)
        if m and not line[:1].isspace():
            take = m.group(1).strip() in keys
        if take:
            out.append(line)
    return out


def header(note: Path, note_text: str, today: datetime.date, quarter: str) -> List[str]:
    kept = _fm_lines(note_text, ("project", "party", "zone"))
    return (["---", "type: history", 'parent: "[[%s]]"' % note.stem] + kept + ["created: %s" % today.isoformat(), "---", "",
             "# %s: history, %s" % (note.stem, quarter), ""])


def read_history(path: Path, note: Path, quarter: str) -> Tuple[List[str], List[Entry]]:
    """(header lines, entries) of an existing history file, or Skip when this tool did not write it."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as why:
        raise Skip("%s cannot be read (%s)" % (path.name, type(why).__name__))
    if "\r" in text:
        raise Skip("%s has carriage returns" % path.name)
    lines = text.split("\n")
    shut = body_start(lines)
    fm = lines[:shut]
    if (not fm or "type: history" not in fm or 'parent: "[[%s]]"' % note.stem not in fm
            or any(l.startswith("status:") for l in fm)):
        raise Skip("%s exists and is not a history file of this note" % path.name)
    title = "# %s: history, %s" % (note.stem, quarter)
    at = next((i for i in range(shut, len(lines)) if lines[i].strip()), None)
    if at is None or lines[at] != title:
        raise Skip("%s exists and its heading differs from the one this tool writes" % path.name)
    entries: List[Entry] = []
    previous_blank, fenced = True, _fenced(lines)
    starts: List[int] = []
    for i in range(at + 1, len(lines)):
        blank = not lines[i].strip() and not fenced[i]
        if previous_blank and not blank and not fenced[i]:
            if not DATE_SHAPE_RE.match(lines[i]):
                if not starts:
                    raise Skip("%s holds text that is not an entry" % path.name)
            else:
                when = _date_of(lines[i])
                if when is None:
                    raise Skip("%s holds an entry whose date does not parse" % path.name)
                starts.append(i)
                entries.append(Entry([], when, len(entries)))
        previous_blank = blank
    for n, i in enumerate(starts):
        stop = starts[n + 1] if n + 1 < len(starts) else len(lines)
        block = lines[i:stop]
        while block and not block[-1].strip():
            block.pop()
        entries[n].lines = block
    return lines[:shut] + [""] + [title, ""], entries


def history_text(head: List[str], entries: List[Entry]) -> str:
    out = list(head)
    for e in entries:
        out += e.lines + [""]
    return "\n".join(out)


def build_files(p: Plan, today: datetime.date) -> Dict[Path, str]:
    """The text of each history file this plan writes, merged with the file already there. Raises Skip."""
    files: Dict[Path, str] = {}
    folder = p.note.parent / FOLDER
    for quarter, moved in sorted(p.quarters.items()):
        path = folder / ("%s history %s.md" % (p.note.stem, quarter))
        if path.exists():
            head, held = read_history(path, p.note, quarter)
            # keep the file's own header, including its created date
        else:
            head, held = header(p.note, p.text, today, quarter), []
        have = {e.text for e in held}
        for e in reversed(moved):                      # oldest position first, so equal dates keep their order
            body = Entry(rewrite_links(e.text).split("\n"), e.date, 0)
            if body.text in have:
                continue
            at = next((i for i, h in enumerate(held) if h.date <= body.date), len(held))
            held.insert(at, body)
            have.add(body.text)
        files[path] = history_text(head, held)
    return files


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp-history")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


class Result:
    def __init__(self, plan_: Plan):
        self.plan = plan_
        self.done = False
        self.skipped = plan_.skipped
        self.error = ""
        self.files: List[Path] = []
        self.commit = ""


def compute(root, note: Path, today: Optional[datetime.date] = None) -> Tuple[Plan, Dict[Path, str], str]:
    """(plan, the text of each history file, why not): everything a move would write, in memory, and the
    reason it cannot be done for certain, "" when it can. Nothing is written."""
    p = plan(root, note, today or datetime.date.today())
    if p.skipped:
        return p, {}, p.skipped
    if not p.moves:
        return p, {}, ""
    try:
        files = build_files(p, today or datetime.date.today())
    except Skip as why:
        return p, {}, str(why)
    bad = unconfirmed(p.text, p.new_text, files.values())
    return p, files, bad


def apply(root, note: Path, today: Optional[datetime.date] = None, commit: str = "") -> Result:
    """Move what `plan` says to history files, confirm every removed line is in one, and put everything back
    when it is not. With `commit`, commit the files this wrote."""
    root, note = Path(root), Path(note)
    today = today or datetime.date.today()
    p, files, why = compute(root, note, today)
    res = Result(p)
    if not p.moves:
        return res
    if why:
        # a move that cannot be confirmed is an error; one that cannot be read for certain is a skip
        if p.skipped or not why.startswith(UNCONFIRMED):
            res.skipped = why
        else:
            res.error = why
        return res
    # the note as it is now, once more: another session may have written it since it was read
    try:
        if note.read_text(encoding="utf-8") != p.text:
            res.skipped = "the note changed while it was being read; run it again"
            return res
    except OSError:
        res.skipped = "the note cannot be read"
        return res
    before: Dict[Path, Optional[str]] = {}
    for path in [note] + list(files):
        before[path] = path.read_text(encoding="utf-8") if path.exists() else None
    try:
        for path, text in files.items():
            _write(path, text)
        _write(note, p.new_text)
        missing = verify(p, files)
    except OSError as why:
        missing = "a file could not be written (%s)" % type(why).__name__
    if missing:
        for path, text in before.items():
            if text is None:
                if path.exists():
                    path.unlink()
            else:
                _write(path, text)
        folder = note.parent / FOLDER
        if folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
        res.error = missing
        return res
    res.done = True
    res.files = [note] + sorted(files)
    if commit:
        res.commit, res.error = commit_files(root, res.files, commit)
        if res.error:
            res.done = False
    return res


UNCONFIRMED = "a line that left"


def unconfirmed(old: str, new: str, histories) -> str:
    """"" when every line that left `old` to make `new` is in one of the history texts `histories`, else why not."""
    held = set()
    for text in histories:
        held.update(text.split("\n"))
    left: Dict[str, int] = {}
    for line in old.split("\n"):
        left[line] = left.get(line, 0) + 1
    for line in new.split("\n"):
        if line in left:
            left[line] -= 1
    for line, count in left.items():
        if count > 0 and line.strip() and not LINK_LINE_RE.match(line) and rewrite_links(line) not in held:
            return "%s the note is in no history file, so nothing was moved" % UNCONFIRMED
    return ""


def verify(p: Plan, files: Dict[Path, str]) -> str:
    """"" when every line that left the note is in a history file as written to disk, else why not."""
    return unconfirmed(p.text, p.note.read_text(encoding="utf-8"),
                       [path.read_text(encoding="utf-8") for path in files])


# ---------------------------------------------------------------------------
# Committing


def _git(args: List[str], repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git"] + args, cwd=str(repo), env=gl.own_repo_env(), capture_output=True, text=True)


def repo_of(root: Path, note: Path) -> Optional[Path]:
    """The zone's repository: the folder under Zones/ the note sits in, or the workspace root."""
    parts = note.resolve().relative_to(Path(root).resolve()).parts
    if len(parts) > 1 and parts[0] == "Zones":
        return Path(root).resolve() / "Zones" / parts[1]
    return Path(root).resolve()


def commit_files(root: Path, files: List[Path], message: str) -> Tuple[str, str]:
    """(commit, error): the files committed by name in their repository, after the walls check on what is staged."""
    repo = repo_of(root, files[0])
    names = [f.resolve().relative_to(repo).as_posix() for f in files]
    added = _git(["add", "--"] + names, repo)
    if added.returncode != 0:
        return "", " ".join((added.stderr or added.stdout).split()) or "git add failed"
    refused = gl.staged_walls_refusal(root, repo, names)
    if refused:
        _git(["reset", "-q", "--"] + names, repo)
        return "", refused
    done = _git(["commit", "-q", "-m", message, "--"] + names, repo)
    if done.returncode != 0:
        _git(["reset", "-q", "--"] + names, repo)
        return "", " ".join((done.stderr or done.stdout).split()) or "git commit failed"
    return _git(["rev-parse", "--short", "HEAD"], repo).stdout.strip(), ""


# ---------------------------------------------------------------------------
# Which notes


def notes_in(root: Path, scope: Optional[str] = None) -> List[Path]:
    """The hub and thread notes under `scope` (a path from the workspace root: a zone, a project, a thread or a
    note), or under every zone: `Zones/<Zone>/<Project>/<Project>.md` and `.../Threads/<Thread>/<Thread>.md`."""
    root = Path(root).resolve()
    base = (root / scope) if scope else root / "Zones"
    out: List[Path] = []
    if base.is_file():
        return [base]
    if not base.is_dir():
        return out
    for path in sorted(base.rglob("*.md")):
        rel = path.relative_to(root).parts
        if any(part.startswith((".", "_")) or part in (FOLDER, "archive") for part in rel[:-1]):
            continue
        hub = len(rel) == 4 and rel[0] == "Zones" and path.stem == rel[2]
        thread = len(rel) == 6 and rel[0] == "Zones" and rel[3] == "Threads" and path.stem == rel[4]
        if hub or thread:
            out.append(path)
    return out


# ---------------------------------------------------------------------------
# Command line


def say(root: Path, results: List[Result], dry: bool) -> str:
    cap = limits(root)["note-max-words"]
    # A note it cannot read for certain is named only when it is long: a hub with no State of play is no finding.
    rows = [r for r in results if r.plan.moves or r.error or (r.skipped and r.plan.before > cap)]
    if not rows:
        return "Nothing to move: no note is over its limits.\n"
    out = []
    for r in rows:
        name = r.plan.note.relative_to(root).as_posix()
        if r.skipped:
            out.append("skipped  %s: %s" % (name, r.skipped))
        elif r.error:
            out.append("FAILED   %s: %s" % (name, r.error))
        else:
            tag = "would move" if dry else "moved"
            more = "  (still over its limit: the newest entries stay)" if r.plan.still_over else ""
            out.append("%s %d entries from %s: %d words -> %d words%s"
                       % (tag, len(r.plan.moves), name, r.plan.before, r.plan.after, more))
    return "\n".join(out) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="history.py", description=__doc__.split("\n")[0])
    ap.add_argument("--root", help="the workspace (default: the one this script sits in)")
    sub = ap.add_subparsers(dest="command", required=True)
    for name in ("dry-run", "apply"):
        s = sub.add_parser(name)
        s.add_argument("notes", nargs="*", help="note paths from the workspace root")
        s.add_argument("--scope", action="append", default=[], help="a zone, project or thread, from the workspace root")
        s.add_argument("--json", action="store_true")
        s.add_argument("--today", help=argparse.SUPPRESS)
        if name == "apply":
            s.add_argument("--commit", default="", metavar="MESSAGE", help="commit what was written, by name")
    r = sub.add_parser("resume")
    r.add_argument("note")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[2]
    if args.command == "resume":
        text = (root / args.note).read_text(encoding="utf-8")
        words, cap = resume_words(text), limits(root)["resume-max-words"]
        print(json.dumps({"resume_words": words, "limit": cap, "over": words > cap}))
        return 0
    notes = [root / n for n in args.notes]
    if not notes:
        for scope in (args.scope or [None]):
            notes += notes_in(root, scope)
    if not notes:
        print("No hub or thread note found there.", file=sys.stderr)
        return 2
    today = datetime.date.fromisoformat(args.today) if args.today else None
    dry = args.command == "dry-run"
    results = []
    for note in notes:
        if dry:
            results.append(Result(plan(root, note, today)))
        else:
            results.append(apply(root, note, today, getattr(args, "commit", "")))
    if args.json:
        print(json.dumps([dict(r.plan.as_dict(root), done=r.done, error=r.error, commit=r.commit,
                               skipped=r.skipped) for r in results], indent=2))
    else:
        sys.stdout.write(say(root, results, dry))
    return 1 if any(r.error for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
