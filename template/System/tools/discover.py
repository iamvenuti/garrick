#!/usr/bin/env python3
"""discover.py: find the pieces of work in a folder you already keep, read-only.

    python3 System/tools/discover.py scan <folder>              propose three to five pieces of work
    python3 System/tools/discover.py answer <id> yes            that one is a piece of work
    python3 System/tools/discover.py answer <id> rename <name>  it is, under another name
    python3 System/tools/discover.py answer <id> not            it is not; never propose it again
    python3 System/tools/discover.py list                       every folder scanned, and the answers

`--json` prints one JSON object instead of plain words, for the page.
`--root` names the workspace (default: the one this script is in), and
`--today YYYY-MM-DD` scores as of that day instead of now.

Discovery reads names, folders, sizes and dates, and nothing else: it lists
the folder without opening a single file under it, so a cloud drive's
online-only files are never downloaded, and it writes nothing there. An audit
hook (`guard`) refuses both for the whole run, so a slip fails loudly instead
of touching somebody's files.

The rules, each from the stage 2 trial:

- Recency dominates the score, with a two-week half-life; the number of files
  and the days they were saved on add a little. Nothing older than 60 days is
  among the first five, unless fewer than three are newer; a proposal needs at
  least two files. Proposals that score alike, at three decimals, are ordered
  by last activity, newest first.
- Folders that never hold a piece of work are left out by name, in English,
  Italian and Dutch, without case or accents: archives, templates, personal
  folders, the desktop, chat exports, recordings, "old" and "do not use",
  shared assets, and odds and ends.
- Stage, part and media folders (Draft, Final, Working, Proofs, Page drafts,
  Research, Photos) count toward the folder above them. Year folders and
  grouping folders such as `Clients` are walked through, never proposed.
- A routine is a folder of one document made again and again, such as a
  weekly report: one name, its dates and versions taken out, covers at least
  two thirds of the folder's files on at least four dates, and the folder holds
  at most two other files. It is listed, never proposed. A folder that holds a
  weekly status report beside three or more other files is a piece of work
  that reports on itself, and is proposed with the series noted.
- A copy a download leaves, `Final_v3 (1)` beside `Final_v3`, counts once.
  Junk (`.DS_Store`, `~$` lock files, `desktop.ini`) is ignored.
- In a tree, the picked folder's own loose files are listed, never proposed.
- A flat folder, at least half its files loose, is said to be flat, and its
  loose files are offered as groups of names that share words instead.

Proposals and answers are machine state, in the workspace's
`System/generated/discovery.json`, never committed and never under the
picked folder. A rescan keeps every answer: a "not" keeps that folder out of
later proposals, and what was not answered is proposed again. A yes is only
recorded here; Garrick's own record of the work is made later, from it.

Standard library only, Python 3.9 or later. Exits 1 when it refuses, and says why.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import hashlib
import json
import math
import os
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import garrick_lib as gl  # noqa: E402

STATE = ("System", "generated", "discovery.json")
GENERATED = ("System", "generated")
VERSION = 1


class Refusal(Exception):
    """Something the tool will not do, said for the person who asked."""


# ---------------------------------------------------------------- the guard

# Audit events that change the file system. `open` is handled apart, by its mode.
WRITE_EVENTS = frozenset({
    "os.mkdir", "os.rename", "os.remove", "os.rmdir", "os.utime", "os.chmod", "os.chown", "os.symlink", "os.link",
    "os.truncate", "os.chflags", "os.lchflags", "os.setxattr", "os.removexattr", "shutil.copyfile", "shutil.copymode",
    "shutil.copystat", "shutil.copytree", "shutil.move", "shutil.rmtree", "shutil.chown",
})
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
_ARMED: List[Tuple[str, Tuple[str, ...], bool]] = []   # (folder, exempt folders, refuse reads too)
_HOOKED = False


def _real(path) -> Optional[str]:
    try:
        return os.path.realpath(os.fsdecode(path))
    except (TypeError, ValueError):
        return None


def _within(path: str, folder: str) -> bool:
    return path == folder or path.startswith(folder.rstrip(os.sep) + os.sep)


def _writes(event: str, args) -> bool:
    if event in WRITE_EVENTS:
        return True
    mode = args[1] if len(args) > 1 else None
    flags = args[2] if len(args) > 2 else 0
    if isinstance(mode, str):
        return any(c in mode for c in "wax+")
    return isinstance(flags, int) and bool(flags & _WRITE_FLAGS)


def _hook(event: str, args) -> None:
    if not _ARMED or not (event == "open" or event in WRITE_EVENTS):
        return
    if not args or not isinstance(args[0], (str, bytes, os.PathLike)):
        return                      # an open by descriptor: no path to check
    paths = [args[0]]
    if event in ("os.rename", "os.link", "os.symlink", "shutil.copyfile", "shutil.copytree", "shutil.move") \
            and len(args) > 1 and isinstance(args[1], (str, bytes, os.PathLike)):
        paths.append(args[1])
    writes = _writes(event, args)
    for raw in paths:
        path = _real(raw)
        if path is None:
            continue
        for folder, exempt, reads in _ARMED:
            if not _within(path, folder) or any(_within(path, e) for e in exempt):
                continue
            if writes:
                raise PermissionError("Garrick must not change anything in %s (%s %s)" % (folder, event, path))
            if reads:
                raise PermissionError("discovery must not open %s" % path)


@contextlib.contextmanager
def guard(folder, exempt=(), reads: bool = True) -> Iterator[None]:
    """While inside, refuse every write under `folder`, and with `reads`
    every open as well, except under the `exempt` folders. An audit hook
    cannot be removed, so one is added once per process and disarmed here."""
    global _HOOKED
    if not _HOOKED:
        sys.addaudithook(_hook)
        _HOOKED = True
    entry = (os.path.realpath(str(folder)), tuple(os.path.realpath(str(e)) for e in exempt), reads)
    _ARMED.append(entry)
    try:
        yield
    finally:
        _ARMED.remove(entry)


# ---------------------------------------------------------------- vocabulary

JUNK_FILES = {"desktop.ini", "thumbs.db", "icon\r"}
YEAR = re.compile(r"^(19|20)\d\d$")

# Folders that never hold a piece of work, each with why: skipped with everything under them.
# Every name is compared after norm(), so case and accents never matter: "PRIVÉ", "Privé" and "prive" are one.
# (why, whole names, words anywhere in the name, patterns), checked in this order.
SKIPS = (
    ("chat", set(), set(), (
        # Chat Files, Teams Chat Files, Microsoft Teams Chat Files, Microsoft Teams-chatbestanden (Dutch),
        # File della chat di Microsoft Teams (Italian)
        r"^((microsoft )?teams[ -]?)?chat ?files?$", r"^((microsoft )?teams[ -]?)?chatbestanden$",
        r"^files? (della|delle|di) chat( di (microsoft )?teams)?$")),
    ("desktop", {"desktop"}, set(), ()),
    ("personal", {"personal", "private", "privato", "prive"}, set(), ()),
    ("templates", {"templates", "template", "modelli", "sjablonen"}, {"templates"}, ()),
    ("recordings", {"recordings"}, set(), ()),
    ("archive", {"archive", "archived", "archives", "archivio", "archief"},
     {"archive", "archived", "archivio", "archief"}, (r"\barchive\b",)),
    ("old", {"old", "vecchio", "oud"}, set(), (
        r"\bdo not use\b", r"^old\b", r"\bold$",
        # the same shapes in Italian and Dutch: "Vecchio - non usare", "Listini vecchi", "Oude versies"
        r"\b(da )?non usare\b", r"^vecchi[oae]?\b", r"\bvecchi[oae]?$", r"\bniet gebruiken\b", r"^oude?\b", r"\boude?$")),
    ("assets", set(), {"assets", "resources", "library"}, ()),
    ("copy", set(), set(), (r"^copy of\b",)),
    ("odds", {"misc", "miscellaneous", "other", "stuff", "temp", "tmp", "unsorted", "new folder", "downloads", "trash",
              "backup", "backups", "attachments", "shared with me"}, set(), (r"^_", r"^zz")),
)
SKIPS = tuple((why, names, words, tuple(re.compile(p) for p in patterns)) for why, names, words, patterns in SKIPS)

# Why a folder was left out, in the words the line under the proposals uses.
WHY = {
    "chat": "chat files", "desktop": "the desktop", "personal": "personal files", "templates": "templates",
    "recordings": "recordings", "archive": "archives", "old": "old material", "assets": "shared assets",
    "copy": "copies of other folders", "odds": "odds and ends", "declined": "not a piece of work, as you said",
    "unlisted": "could not be listed", "garrick": "Garrick's own folder",
}
# Folders that group work but are not work: walked through, never proposed.
CONTAINERS = {"clients", "customers", "projects", "engagements", "internal", "work", "shared", "documents", "team"}
# Folders that are a stage or part of the work above them: their files count for the parent.
# A word qualifies as a stage when a folder so named only ever holds rounds of the deliverable above it
# (an earlier draft, a proof, a signed copy), never work of its own. Words that are also subjects
# ("review", "working", "copy") stay whole-name only, or out.
STAGES = {"draft", "drafts", "final", "finals", "working", "wip", "work in progress", "review", "in review", "sent",
          "signed", "versions", "old versions", "superseded", "for review", "approved", "submitted",
          "proof", "proofs", "proofing", "revisions", "redlines"}
# Stage words that also count when they end a longer name, optionally numbered: "Page drafts", "Printer proofs",
# "Proof 2", "Draft 3". Only words that cannot head a piece of work of their own are here.
STAGE_HEADS = {"draft", "drafts", "proof", "proofs", "versions", "revisions", "redlines"}
PARTS = {"research", "notes", "data", "analysis", "sources", "inputs", "outputs", "deliverables", "correspondence",
         "emails", "minutes", "meetings", "admin", "docs", "background", "references", "exports", "figures"}
MEDIA = {"photo", "photos", "images", "pictures", "screenshots", "scans", "renders", "video", "videos", "selects"}


def norm(name: str) -> str:
    """Lower case, accents dropped, spaces collapsed: what every vocabulary match compares."""
    n = unicodedata.normalize("NFKD", name.strip().casefold())
    n = "".join(c for c in n if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", n)


def skip_reason(name: str) -> Optional[str]:
    """Why a folder of this name is left out, or None when it is not."""
    n = norm(name)
    words = set(re.findall(r"[a-z0-9]+", n))
    for why, names, skip_words, patterns in SKIPS:
        if n in names or words & skip_words or any(p.search(n) for p in patterns):
            return why
    return None


def is_stage(n: str) -> bool:
    if n in STAGES or re.fullmatch(r"v\d+", n):
        return True
    words = re.findall(r"[a-z0-9]+", n)
    while words and re.fullmatch(r"\d+|v\d+", words[-1]):     # "Proof 2", "Draft v3"
        words.pop()
    return bool(words) and words[-1] in STAGE_HEADS


def is_junk(name: str) -> bool:
    n = name.lower()
    return name.startswith(".") or name.startswith("~$") or n in JUNK_FILES or n.endswith(".tmp")


def classify(name: str) -> str:
    """skip, container (walked through), part (counts for its parent) or unit (may be a piece of work)."""
    if skip_reason(name):
        return "skip"
    n = norm(name)
    words = set(re.findall(r"[a-z0-9]+", n))
    if YEAR.match(n) or n in CONTAINERS:
        return "container"
    if is_stage(n) or n in PARTS or words & MEDIA:
        return "part"
    return "unit"


# ---------------------------------------------------------------- copies and routines (names only)

# A copy a download or a sync leaves beside the original: "Final_v3 (1).docx" next to "Final_v3.docx".
# It counts once, dated by whichever of the two was saved last. Only the " (n)" mark is folded, and only when
# the original sits in the same folder: "Copy" and "copy" also mean marketing text, so they are left alone.
COPY_MARK = re.compile(r"^(?P<base>.+?) \(\d+\)$")


class F:
    """One file, as listed: its path from the picked folder, its name, when it was saved and its size."""
    __slots__ = ("rel", "name", "mtime", "size")

    def __init__(self, rel: str, name: str, st):
        self.rel, self.name, self.mtime, self.size = rel, name, st.st_mtime, st.st_size


def fold_copies(files: List[F]) -> Tuple[List[F], int]:
    """One entry per file, with each ' (n)' copy folded into the original beside it. Returns (files, folded)."""
    by_key = {}
    for f in files:
        stem, ext = os.path.splitext(f.rel)
        by_key[(stem.casefold(), ext.casefold())] = f
    out, folded = [], 0
    for f in files:
        stem, ext = os.path.splitext(f.rel)
        m = COPY_MARK.match(stem)
        orig = by_key.get((m.group("base").casefold(), ext.casefold())) if m else None
        if orig is not None and orig is not f:
            orig.mtime = max(orig.mtime, f.mtime)
            folded += 1
            continue
        out.append(f)
    return out, folded


# A routine is a folder of the same document made again and again: a weekly or monthly report.
# Take each file's name, drop dates and periods (2026-10-16, 20261016, 16.10.2026, W41, week 41, 2026-09,
# October, Q3 2026), version marks and numbers; what is left is its stem. A folder is a routine when one stem
# covers at least two thirds of its files, those files carry at least four different dates or periods in their
# names, and the folder holds at most two other files. Drafts of one thing (v1, v2, FINAL) differ by version,
# not by date, so they never qualify; nor does a folder where the reports are a minority beside other work.
# The last condition is the build's: a piece of work with a weekly status report beside its plan, its risk
# log and its test results passes the first two, and is still a piece of work.
ROUTINE_SHARE = 2 / 3
ROUTINE_DATES = 4
ROUTINE_OTHERS = 2
MONTHS = ("january|february|march|april|may|june|july|august|september|october|november|december|"
          "jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec|"
          "gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre|"
          "januari|februari|maart|mei|juni|juli|augustus|oktober")
MM, DD = r"(?:0[1-9]|1[0-2])", r"(?:0[1-9]|[12]\d|3[01])"         # a real month, a real day
M1, D1 = r"(?:0?[1-9]|1[0-2])", r"(?:0?[1-9]|[12]\d|3[01])"
PERIOD = re.compile(
    r"(?<![a-z0-9])(?:"
    r"(?:19|20)\d\d[-_. ]?" + MM + r"[-_. ]?" + DD +       # 2026-10-16, 20261016
    r"|" + D1 + r"[-_.]" + M1 + r"[-_.](?:19|20)?\d\d"         # 16-10-2026, 16.10.26
    r"|(?:(?:19|20)\d\d[-_ ]?)?w(?:k|eek)?[-_ ]?[0-5]?\d"    # 2026-W41, W41, wk 41, week 41
    r"|(?:19|20)\d\d[-_ ]" + MM +                            # 2026-09
    r"|(?:(?:19|20)\d\d[-_ ]?)?q[1-4][-_ ](?:19|20)\d\d|(?:19|20)\d\d[-_ ]?q[1-4]"   # Q3 2026, 2026 Q3
    r"|(?:" + MONTHS + r")(?:[-_ ]?(?:19|20)\d\d)?"          # October, Oct 2026
    r")(?![a-z0-9])")


def routine_key(name: str) -> Tuple[str, Tuple[str, ...]]:
    """(stem, periods) for one file name: the stem without dates, versions or numbers, and the dates it carried."""
    n = norm(os.path.splitext(name)[0])
    periods = tuple(re.sub(r"[-_. ]", "", m.group(0)) for m in re.finditer(PERIOD, n))
    stem = re.sub(PERIOD, " ", n)
    stem = re.sub(r"\(\d+\)|\bv\d+\b|\b(final|draft|copy|rev)\b|\d+", " ", stem)
    return " ".join(re.findall(r"[a-z]+", stem)), periods


def series(files: List[F]) -> Optional[Tuple[str, int]]:
    """(stem, files) of the largest name that recurs on at least four dates and covers two thirds of the files."""
    groups: Dict[str, List[Tuple[str, ...]]] = defaultdict(list)
    for f in files:
        stem, periods = routine_key(f.name)
        if stem:
            groups[stem].append(periods)
    best = None
    for stem, seen in sorted(groups.items()):
        dates = {p for ps in seen for p in ps}
        if len(seen) >= ROUTINE_SHARE * len(files) and len(dates) >= ROUTINE_DATES:
            if best is None or len(seen) > best[1]:
                best = (stem, len(seen))
    return best


def is_routine(files: List[F]) -> Optional[str]:
    """The stem of the report a folder holds again and again, when the folder is a routine; otherwise None."""
    found = series(files)
    if found and len(files) - found[1] <= ROUTINE_OTHERS:
        return found[0]
    return None


def recurring(files: List[F]) -> Dict[str, List[F]]:
    """In a flat folder: each name that recurs on at least four dates in at least four files, with those files."""
    groups: Dict[str, List[Tuple[F, Tuple[str, ...]]]] = defaultdict(list)
    for f in files:
        stem, periods = routine_key(f.name)
        if stem and periods:
            groups[stem].append((f, periods))
    out = {}
    for stem, seen in groups.items():
        if len(seen) >= ROUTINE_DATES and len({p for _, ps in seen for p in ps}) >= ROUTINE_DATES:
            out[stem] = [f for f, _ in seen]
    return out


# ---------------------------------------------------------------- listing (names and dates only)

def entries(path: str) -> list:
    with os.scandir(path) as it:  # lists names; opens no file
        return sorted(it, key=lambda e: e.name)


class Walk:
    """One pass over a picked folder: what it found, and what it left out."""

    def __init__(self, root: str, avoid: Tuple[str, ...] = ()):
        self.root = root
        self.avoid = avoid                      # folders never walked: Garrick's own, when it sits inside
        self.units: List[dict] = []
        self.left: List[Tuple[str, str]] = []   # (folder, why)

    def rel(self, path: str) -> str:
        return os.path.relpath(path, self.root).replace(os.sep, "/")

    def listing(self, path: str) -> list:
        try:
            return entries(path)
        except OSError:
            self.left.append((self.rel(path), "unlisted"))
            return []

    def folder_left(self, e) -> bool:
        """True when the folder `e` is left out, recording why."""
        if os.path.realpath(e.path) in self.avoid:
            self.left.append((self.rel(e.path), "garrick"))
            return True
        why = skip_reason(e.name)
        if why:
            self.left.append((self.rel(e.path), why))
            return True
        return False

    def file(self, e) -> Optional[F]:
        try:
            return F(self.rel(e.path), e.name, e.stat(follow_symlinks=False))
        except OSError:
            return None

    def collect(self, path: str) -> List[F]:
        """Every file under `path` that is not junk, leaving out skipped folders."""
        out = []
        for e in self.listing(path):
            if e.is_symlink() or is_junk(e.name):
                continue
            if e.is_dir(follow_symlinks=False):
                if not self.folder_left(e):
                    out += self.collect(e.path)
            elif e.is_file(follow_symlinks=False):
                f = self.file(e)
                if f:
                    out.append(f)
        return out

    def walk(self, path: str, depth: int = 0, kind: str = "unit") -> None:
        files = []
        for e in self.listing(path):
            if e.is_symlink() or is_junk(e.name):
                continue
            if e.is_dir(follow_symlinks=False):
                if self.folder_left(e):
                    continue
                k = classify(e.name)
                if k == "part" and kind == "unit" and depth > 0:
                    files += self.collect(e.path)       # stage and part folders count for their parent
                else:
                    self.walk(e.path, depth + 1, "unit" if k == "part" else k)
            elif e.is_file(follow_symlinks=False):
                f = self.file(e)
                if f:
                    files.append(f)
        if kind == "unit" and len(files) >= 2:
            self.units.append({"path": self.rel(path), "depth": depth, "files": files})


def work_files(folder) -> List[F]:
    """The files that belong to the piece of work in `folder`, as discovery counts them: its own, and those of
    its stage and part folders, with nothing under a folder that is left out or that holds work of its own."""
    w = Walk(os.path.realpath(str(folder)))
    files = []
    for e in w.listing(w.root):
        if e.is_symlink() or is_junk(e.name):
            continue
        if e.is_dir(follow_symlinks=False):
            if not w.folder_left(e) and classify(e.name) == "part":
                files += w.collect(e.path)
        elif e.is_file(follow_symlinks=False):
            f = w.file(e)
            if f:
                files.append(f)
    return files


# ---------------------------------------------------------------- scoring

def score(files: List[F], today: datetime.datetime, depth: int = 1) -> Tuple[float, float, int]:
    """(score, last saved as a timestamp, whole days since)."""
    last = max(f.mtime for f in files)
    days = max(0.0, (today - datetime.datetime.fromtimestamp(last)).total_seconds() / 86400)
    window = today - datetime.timedelta(days=45)
    active_days = len({datetime.datetime.fromtimestamp(f.mtime).date() for f in files
                       if datetime.datetime.fromtimestamp(f.mtime) >= window})
    s = 0.5 ** (days / 14)                                  # recency, two-week half-life: dominant
    s *= 1 + 0.4 * math.log2(1 + min(len(files), 30))       # size, saturating
    s *= 1 + 0.25 * min(active_days, 6)                     # touched on several days, not dumped once
    s *= 0.9 ** max(0, depth - 4)                           # very deep folders slightly down
    return s, last, int(days)


def order(props: List[dict]) -> List[dict]:
    """Best first: by score at three decimals, then by last activity, newest first, then by name."""
    return sorted(props, key=lambda p: (-p["score"], -p["_last"], p["label"]))


def pick(props: List[dict]) -> Tuple[List[dict], List[dict]]:
    """Three to five to propose; the rest wait under 'more'. Precision first: nothing older than 60 days in the
    top, unless fewer than three are newer."""
    top = [p for p in props if p["days"] <= 60][:5]
    if len(top) < 3:
        top = props[:3]
    return top, [p for p in props if p not in top]


def ago(days: int) -> str:
    return ("today" if days == 0 else "yesterday" if days == 1 else "%d days ago" % days if days < 60
            else "%d months ago" % (days // 30))


def proposal_id(folder: str, kind: str, key: str) -> str:
    """A short id that stays the same for the same piece of work in the same folder, scan after scan."""
    return hashlib.sha256(("%s\0%s\0%s" % (folder, kind, key)).encode("utf-8")).hexdigest()[:8]


def folder_key(folder) -> str:
    """A stable name for a folder, readable and unique: its own name and a short fingerprint of where it is."""
    real = os.path.realpath(str(folder))
    base = re.sub(r"[^\w .&'-]+", " ", os.path.basename(real) or "folder").strip() or "folder"
    return "%s-%s" % (base[:48].strip(), hashlib.sha256(real.encode("utf-8")).hexdigest()[:8])


def proposal(root: str, kind: str, key: str, label: str, name: str, folder: Optional[str], files: List[F],
             today: datetime.datetime, depth: int = 1) -> dict:
    s, last, days = score(files, today, depth)
    latest = sorted(files, key=lambda f: (-f.mtime, f.name))
    p = {"id": proposal_id(root, kind, key), "kind": kind, "name": name, "label": label,
         "folder": folder, "path": os.path.join(root, folder) if folder not in (None, ".") else root,
         "files": len(files), "last": datetime.datetime.fromtimestamp(last).date().isoformat(), "days": days,
         "score": round(s, 3), "latest": [f.name for f in latest[:3]], "_last": last}
    if kind == "names":
        p["members"] = sorted(f.rel for f in files)
    return p


# ---------------------------------------------------------------- folders, then names when flat

def by_folders(root: str, today: datetime.datetime, avoid: Tuple[str, ...] = ()) -> Tuple[List[dict], dict]:
    w = Walk(root, avoid)
    w.walk(root)
    folded, routines = 0, []
    for u in w.units:
        u["files"], n = fold_copies(u["files"])
        folded += n
    units = [u for u in w.units if len(u["files"]) >= 2]
    total = sum(len(u["files"]) for u in units)
    props = []
    for u in units:
        if u["path"] != ".":
            stem = is_routine(u["files"])
            if stem:                               # a weekly or monthly report: a routine, not a piece of work
                routines.append({"folder": u["path"], "label": u["path"].replace("/", " › "), "name": stem,
                                 "files": len(u["files"])})
                continue
        if u["path"] == ".":
            label, name = os.path.basename(root) + " (loose files)", os.path.basename(root)
        else:
            label, name = u["path"].replace("/", " › "), u["path"].rsplit("/", 1)[-1]
        p = proposal(root, "folder", u["path"], label, name, u["path"], u["files"], today, u["depth"])
        reports = series(u["files"]) if u["path"] != "." else None
        if reports:                                # proposed, and the report it makes again and again noted
            p["series"] = {"name": reports[0], "files": reports[1]}
        props.append(p)
    loose = next((u for u in units if u["path"] == "."), None)
    flat = loose is not None and (len(loose["files"]) >= 0.5 * max(total, 1) or len(units) < 3)
    # In a tree, the picked folder's own loose files are what sits on top of the work, not a piece of it
    # (a holiday rota, an untitled note): never proposed, only listed. A flat folder keeps them: they are its work.
    loose_top = []
    if loose is not None and not flat:
        props = [p for p in props if p["folder"] != "."]
        loose_top = [f.name for f in sorted(loose["files"], key=lambda f: (-f.mtime, f.name))]
    return props, {"left": w.left, "flat": flat, "loose_files": len(loose["files"]) if loose else 0,
                   "loose": loose_top, "total_files": total, "routines": routines, "copies": folded}


# Names a camera, a scanner, a chat or an app gives a file: never a sign of what the work is.
MACHINE = re.compile(r"^(screenshot|screen shot|img[_ ]|dsc|pxl_|scan\b|document\d|book\d|presentation\d|untitled|invoice\b|"
                     r"receipt|image \(|export \(|file \(|meeting in |recording)", re.I)
STOP = {"and", "the", "of", "for", "to", "a", "in", "at", "with", "on", "from", "by", "an", "is",
        "final", "really", "draft", "copy", "new", "latest", "updated", "rev", "version", "old", "signed", "v",
        "notes", "note", "slides", "deck", "doc", "docs", "document", "report", "review", "plan", "meeting", "minutes",
        "summary", "numbers", "actions", "checklist", "template", "comments", "feedback", "brief", "list", "options",
        "data", "ideas", "call", "agenda", "pdf", "docx", "xlsx", "pptx", "jpg", "png", "zip", "txt"}


def sig_words(stem: str) -> List[str]:
    s = re.sub(r"\(\d+\)", " ", stem.lower().lstrip("~$"))
    words = re.findall(r"[a-z0-9]+", s)
    return [w for w in words if len(w) > 1 and w not in STOP and not w.isdigit()
            and not re.fullmatch(r"v\d+|w\d+|\d+[a-z]{0,2}|[a-z]\d{3,}", w)]


def group_label(key: Tuple[str, ...]) -> str:
    return " ".join(key).title() if len(key) == 2 else key[0].upper() if len(key[0]) <= 3 else key[0].title()


def by_names(root: str, today: datetime.datetime, files: List[F]) -> Tuple[List[dict], dict]:
    """Groups of loose files whose names share a word or a pair of words, for a flat folder."""
    files, folded = fold_copies(files)
    pool = [f for f in files if not MACHINE.match(f.name)]
    machine = len(files) - len(pool)
    # A name that recurs on many dates, a weekly report, is a routine here too: listed, never grouped.
    routines = []
    for stem, fs in sorted(recurring(pool).items()):
        routines.append({"folder": None, "label": stem, "name": stem, "files": len(fs)})
        taken = set(id(f) for f in fs)
        pool = [f for f in pool if id(f) not in taken]
    words = {f.rel: sig_words(os.path.splitext(f.name)[0]) for f in pool}
    index: Dict[Tuple[str, ...], set] = defaultdict(set)
    for f in pool:
        w = words[f.rel]
        for t in set(w):
            index[(t,)].add(f.rel)
        for a, b in zip(w, w[1:]):
            index[(a, b)].add(f.rel)
    cap = max(6, int(0.2 * len(pool)))
    byrel = {f.rel: f for f in pool}
    keys = []
    for k, rels in index.items():
        if 3 <= len(rels) <= cap:
            s, _, _ = score([byrel[r] for r in rels], today)
            keys.append((s * (1.15 if len(k) == 2 else 1), k, rels))
    keys.sort(key=lambda x: (-x[0], x[1]))
    taken_by: Dict[str, Tuple[str, ...]] = {}
    clusters = []
    for _, k, rels in keys:
        free = rels - taken_by.keys()
        if len(free) < 3 or len(free) < 0.5 * len(rels):
            continue
        for r in free:
            taken_by[r] = k
        clusters.append((k, free))
    props = []
    for k, rels in clusters:
        fs = [byrel[r] for r in rels]
        span = (max(f.mtime for f in fs) - min(f.mtime for f in fs)) / 86400
        same = len({tuple(words[r]) for r in rels}) == 1
        label = group_label(k)
        if same and span > 60:                    # one name on many dates: a routine
            routines.append({"folder": None, "label": label, "name": label, "files": len(fs)})
            continue
        props.append(proposal(root, "names", " ".join(k), "names with “%s”" % label, label, None, fs, today))
    return props, {"routines": routines, "machine_named": machine, "unclustered": len(pool) - len(taken_by),
                   "copies": folded}


def discover(root: str, today: datetime.datetime, avoid: Tuple[str, ...] = ()) -> Tuple[List[dict], dict]:
    """Every proposal for the folder, best first, and what the scan found besides: by folders, and by names
    when the folder is flat."""
    props, info = by_folders(root, today, avoid)
    if info["flat"]:
        w = Walk(root, avoid)
        loose = []
        for e in w.listing(root):
            if e.is_file(follow_symlinks=False) and not e.is_symlink() and not is_junk(e.name):
                f = w.file(e)
                if f:
                    loose.append(f)
        named, ninfo = by_names(root, today, loose)
        props = named + [p for p in props if p["folder"] != "."]
        info["routines"] = info["routines"] + ninfo["routines"]
        info["machine_named"] = ninfo["machine_named"]
        info["unclustered"] = ninfo["unclustered"]
    return order(props), info


# ---------------------------------------------------------------- the state

def state_path(root: Path) -> Path:
    return root.joinpath(*STATE)


def load(root: Path) -> dict:
    path = state_path(root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = None
    except (OSError, ValueError):
        # Unreadable machine state is put aside, not lost, and the scan starts again from nothing.
        aside = path.with_name(path.name + ".unreadable")
        try:
            os.replace(str(path), str(aside))
        except OSError:
            pass
        data = None
    if not isinstance(data, dict) or not isinstance(data.get("folders"), dict):
        data = {"version": VERSION, "folders": {}}
    return data


def save(root: Path, data: dict) -> None:
    path = state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(".%s.%d.tmp" % (path.name, os.getpid()))
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(str(tmp), str(path))


def public(p: dict) -> dict:
    return {k: v for k, v in p.items() if not k.startswith("_")}


# ---------------------------------------------------------------- commands

def check_folder(folder: str, root: Path) -> Tuple[str, Tuple[str, ...]]:
    """The picked folder as it really is, and the folders under it never walked. Refuses a folder that is not
    there, the whole Mac, the whole home folder, or a part of Garrick itself."""
    real = os.path.realpath(os.path.expanduser(folder))
    if not os.path.isdir(real):
        raise Refusal("There is no folder at %s." % folder)
    home = os.path.realpath(os.path.expanduser("~"))
    if real == os.path.realpath(os.sep) or real == home:
        raise Refusal("That is the whole %s. Pick the folder your work is in." %
                      ("Mac" if real == os.path.realpath(os.sep) else "home folder"))
    ws = os.path.realpath(str(root))
    if real == ws or any(_within(real, os.path.join(ws, part)) for part in ("System", "Zones", "Wikis")):
        raise Refusal("That folder is part of Garrick itself. Pick the folder your work is in.")
    avoid = (ws,) if _within(ws, real) else ()
    return real, avoid


def scan(folder: str, root: Path, today: datetime.datetime, day: str) -> dict:
    real, avoid = check_folder(folder, root)
    with guard(real, exempt=(str(root.joinpath(*GENERATED)),)):
        return _scan(real, avoid, root, today, day)


def _scan(real: str, avoid: Tuple[str, ...], root: Path, today: datetime.datetime, day: str) -> dict:
    data = load(root)
    entry = data["folders"].get(real, {})
    answers = entry.get("answers", {}) if isinstance(entry.get("answers"), dict) else {}
    props, info = discover(real, today, avoid)
    confirmed, declined, open_ = [], [], []
    for p in props:
        a = answers.get(p["id"])
        if a and a.get("answer") == "yes":
            confirmed.append(dict(public(p), name=a.get("name") or p["name"], suggested=p["name"]))
            a.update({k: p[k] for k in ("label", "folder", "path")})
            if "members" in p:
                a["members"] = p["members"]
        elif a and a.get("answer") == "not":
            declined.append(p)
        else:
            open_.append(p)
    top, more = pick(open_)
    left = [{"folder": f, "why": why, "said": WHY[why]} for f, why in sorted(set(info["left"]))]
    left += [{"folder": p["folder"] or p["label"], "why": "declined", "said": WHY["declined"]} for p in declined]
    found = {p["id"] for p in props}
    entry = {
        "name": os.path.basename(real), "key": folder_key(real), "today": day,
        "scanned": datetime.datetime.now().replace(microsecond=0).isoformat(),
        "flat": info["flat"], "files": info["total_files"], "copies": info["copies"],
        "top": [public(p) for p in top], "more": [public(p) for p in more], "confirmed": confirmed,
        "left_out": left, "routines": info["routines"], "loose": info["loose"],
        "answers": answers,
    }
    for k in ("machine_named", "unclustered"):
        if k in info:
            entry[k] = info[k]
    data["folders"][real] = entry
    save(root, data)
    out = dict(entry, folder=real, missing=sorted(i for i, a in answers.items()
                                                  if a.get("answer") == "yes" and i not in found))
    out["left_out_said"] = say_left(out)
    out["said"] = say_scan(out)
    return out


def find(data: dict, pid: str) -> Tuple[str, dict, Optional[dict]]:
    """(folder, its entry, the proposal) for an id, from the latest scans and the answers kept."""
    for real, entry in data["folders"].items():
        for p in entry.get("top", []) + entry.get("more", []) + entry.get("confirmed", []):
            if p.get("id") == pid:
                return real, entry, p
        if pid in entry.get("answers", {}):
            return real, entry, None
    raise Refusal("No proposal has the id %s. discover.py list shows them." % pid)


def answer(root: Path, pid: str, verb: str, words: List[str], day: str) -> dict:
    data = load(root)
    real, entry, p = find(data, pid)
    answers = entry.setdefault("answers", {})
    known = answers.get(pid, {})
    base = dict(known)
    if p is not None:
        base.update({"label": p["label"], "kind": p["kind"], "folder": p["folder"], "path": p["path"],
                     "suggested": p.get("suggested") or known.get("suggested") or p["name"]})
        if "members" in p:
            base["members"] = p["members"]
    base.pop("name_problem", None)
    suggested = base.get("suggested") or base.get("name") or ""
    if verb == "rename":
        name = " ".join(words).strip()
        ok, why = gl.is_display_name(name)
        if not ok:
            raise Refusal("“%s” cannot be the name of a piece of work: %s." % (name, why))
        record = dict(base, answer="yes", name=name)
    elif verb == "yes":
        if words:
            raise Refusal("A yes takes no name. To give it another name: answer %s rename <name>." % pid)
        record = dict(base, answer="yes", name=suggested)
        ok, why = gl.is_display_name(suggested)
        if not ok:
            record["name_problem"] = why
    else:
        if words:
            raise Refusal("A not takes no name.")
        record = dict(base, answer="not")
        record.pop("name", None)
    record["at"] = day
    answers[pid] = record
    # The answer moves the proposal out of the open list at once, so the page need not scan again.
    for place in ("top", "more"):
        entry[place] = [q for q in entry.get(place, []) if q.get("id") != pid]
    entry["confirmed"] = [q for q in entry.get("confirmed", []) if q.get("id") != pid]
    if record["answer"] == "yes" and p is not None:
        entry["confirmed"].append(dict(p, name=record["name"], suggested=suggested))
    elif record["answer"] == "not":
        what = base.get("folder") or base.get("label") or pid
        if not any(l.get("folder") == what and l.get("why") == "declined" for l in entry.get("left_out", [])):
            entry.setdefault("left_out", []).append({"folder": what, "why": "declined", "said": WHY["declined"]})
    save(root, data)
    out = dict(record, id=pid, picked=real)
    out["said"] = say_answer(out)
    return out


def listing(root: Path) -> dict:
    data = load(root)
    folders = []
    for real, entry in sorted(data["folders"].items()):
        folders.append(dict(entry, folder=real))
    out = {"folders": folders}
    out["said"] = say_list(out)
    return out


# ---------------------------------------------------------------- plain words

NUMBERS = ("no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")


def count(n: int, what: str) -> str:
    word = NUMBERS[n] if n < len(NUMBERS) else str(n)
    return "%s %s%s" % (word, what, "" if n == 1 else "s")


def say_left(out: dict) -> str:
    """The one line under the proposals: what was left out, and why, three names at most for each reason."""
    by: Dict[str, List[str]] = defaultdict(list)
    for l in out["left_out"]:
        by[l["said"]].append(l["folder"].replace("/", " › "))
    for r in out["routines"]:
        by["a report made again and again"].append(r["label"])
    parts = []
    for said, names in by.items():
        shown = ", ".join(names[:3]) + (" and %d more" % (len(names) - 3) if len(names) > 3 else "")
        parts.append("%s (%s)" % (said, shown))
    return ("Left out: " + "; ".join(parts) + ".") if parts else ""


def say_proposal(i: int, p: dict) -> List[str]:
    if p["kind"] == "names":
        lines = ["%d. %s: last activity %s, these %d files. [%s]" % (i, p["label"], ago(p["days"]), p["files"], p["id"])]
    else:
        lines = ["%d. %s: last activity %s, %d files. [%s]" % (i, p["label"], ago(p["days"]), p["files"], p["id"])]
    lines.append("   Latest: " + "; ".join(p["latest"]))
    if p.get("series"):
        lines.append("   It also holds a report made again and again: %s, %d files." %
                     (p["series"]["name"], p["series"]["files"]))
    return lines


def say_scan(out: dict) -> str:
    lines = []
    if out["flat"]:
        lines.append("%s is a flat folder: most of its files sit loose in it, so these groups come from words "
                     "their names share." % out["name"])
    top = out["top"]
    if top:
        lines.append("%s: %s, most recently active first." % (out["name"], count(len(top), "piece") + " of work"))
        for i, p in enumerate(top, 1):
            lines += say_proposal(i, p)
    else:
        lines.append("Nothing new in %s looks like a piece of work." % out["name"])
    if out["more"]:
        lines.append("More (%d): " % len(out["more"]) + "; ".join(
            "%s (%s, %d files) [%s]" % (p["label"], ago(p["days"]), p["files"], p["id"]) for p in out["more"]))
    if out["confirmed"]:
        lines.append("Already yours: " + "; ".join(p["name"] for p in out["confirmed"]) + ".")
    if out["left_out_said"]:
        lines.append(out["left_out_said"])
    if out["loose"]:
        lines.append("Loose files at the top, not proposed: " + "; ".join(out["loose"]) + ".")
    if out["copies"]:
        lines.append("Copies a download left, counted once: %d." % out["copies"])
    if top or out["more"]:
        lines.append("To answer: discover.py answer <id> yes, rename <name>, or not.")
    return "\n".join(lines)


def say_answer(out: dict) -> str:
    what = out.get("label") or out["id"]
    if out["answer"] == "not":
        return "Recorded: %s is not a piece of work. It will not be proposed again." % what
    said = "Recorded: %s is a piece of work, called %s." % (what, out["name"])
    if out.get("name_problem"):
        said += " That name cannot stand as it is (%s), so give it another: answer %s rename <name>." % (
            out["name_problem"], out["id"])
    return said


def say_list(out: dict) -> str:
    if not out["folders"]:
        return "No folder has been looked at yet. To start: discover.py scan <folder>."
    lines = []
    for f in out["folders"]:
        answers = f.get("answers", {})
        yes = [a.get("name", "") for a in answers.values() if a.get("answer") == "yes"]
        not_ = [a.get("label", "") for a in answers.values() if a.get("answer") == "not"]
        lines.append("%s, looked at as of %s: %s proposed, %d more waiting." % (
            f["name"], f.get("today", "an earlier day"), count(len(f.get("top", [])), "piece") + " of work",
            len(f.get("more", []))))
        for p in f.get("top", []):
            lines.append("   %s [%s]" % (p["label"], p["id"]))
        if yes:
            lines.append("   Yours: " + "; ".join(yes) + ".")
        if not_:
            lines.append("   Not a piece of work: " + "; ".join(not_) + ".")
    return "\n".join(lines)


# ---------------------------------------------------------------- main

def default_root() -> Path:
    return Path(__file__).resolve().parents[2]


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Find the pieces of work in a folder you already keep, read-only.")
    ap.add_argument("--root", help="the workspace folder (default: the one this script is in)")
    ap.add_argument("--json", action="store_true", help="print the result as JSON")
    ap.add_argument("--today", help="YYYY-MM-DD to score as of, instead of now")
    sub = ap.add_subparsers(dest="command")
    s = sub.add_parser("scan", help="propose the pieces of work in a folder")
    s.add_argument("folder")
    a = sub.add_parser("answer", help="answer a proposal: yes, rename <name>, or not")
    a.add_argument("id")
    a.add_argument("verb", choices=("yes", "rename", "not"))
    a.add_argument("words", nargs="*")
    sub.add_parser("list", help="every folder looked at, and the answers")
    args = ap.parse_args(argv)
    if not args.command:
        ap.print_help()
        return 2
    root = Path(args.root).expanduser().resolve() if args.root else default_root()
    try:
        if args.today:
            try:
                day = datetime.date.fromisoformat(args.today)
            except ValueError:
                raise Refusal("--today takes a date as YYYY-MM-DD, not %s." % args.today)
            today = datetime.datetime(day.year, day.month, day.day, 23, 59)
        else:
            today = datetime.datetime.now()
        day_s = today.date().isoformat()
        if args.command == "scan":
            out = scan(args.folder, root, today, day_s)
        elif args.command == "answer":
            if args.verb == "rename" and not args.words:
                raise Refusal("A rename needs the name: answer %s rename <name>." % args.id)
            # Every folder already looked at is guarded too: an answer never touches one.
            data = load(root)
            with contextlib.ExitStack() as stack:
                for real in data["folders"]:
                    stack.enter_context(guard(real, exempt=(str(root.joinpath(*GENERATED)),)))
                out = answer(root, args.id, args.verb, args.words, day_s)
        else:
            out = listing(root)
    except Refusal as exc:
        if args.json:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        else:
            print(exc, file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        print(out["said"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
