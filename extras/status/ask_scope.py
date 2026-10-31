#!/usr/bin/env python3
"""ask_scope.py: what an answer from the Ask box may read, for ask.py. Part
of the preview `ask` (#261, slice C).

Two things, both settled before the session sees a record.

**The scope.** mentions() reads the request for the names in it: a party or
its tag, a person, an alias (the Parties, People and Aliases of
System/context.md, as garrick_lib.load_context() reads them), a project or
a thread (ask.py's list of names). Each stands for a party, and a project
or a thread for a place as well. A name that fits two entries whose parties
or places differ, and that the other names in the request do not settle,
is unclear: the box asks which, and nothing is read. scope() then takes the
session's `find`, the route and the place it proposed, checked against the
list as ask.py checks an action, and works out the parties it covers.

**The records.** search() reads files inside the scope and nowhere else:

    meetings   Wikis/Meetings/wiki/, each page with its parties; a page with
               no parties, or a meeting page with no zone, is unfinished and
               never read
    knowledge  Wikis/Knowledge/wiki/: published material, of no party
    thread     the project's folder, or the thread's with its hub: notes, and
               the documents in a Sources/ folder, Word, PowerPoint and Excel
               through extract.py; all of the hub's party
    docs       System/garrick-docs/: Garrick's own pages, of no party

It returns passages, each with the parties it carries, and never writes a
prompt: Asker.admit() in ask.py is the only way a passage reaches one.
pick() chooses the passages a process may be given: none whose party is
walled from one it holds already, or from one picked with it, and says
whether a wall held any back. Nothing here writes a file.

Standard library only, Python 3.9 or later.
"""

from __future__ import annotations

import collections
import importlib.util
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

HERE = Path(__file__).resolve().parent
ROUTES = ("meetings", "knowledge", "thread", "docs")
MAX_WORDS = 8               # words a find may look for
MAX_RECORDS = 8             # records one answer is given
PASSAGE = 1500              # characters of one record an answer is given
MAX_FILE = 2 * 1024 * 1024  # bytes: a larger file is not read
NOTES = (".md", ".txt")
SHORTEST = 3                # a name shorter than this is never looked for
MOST_NAMED = 5              # candidates a clarification names


class Refused(Exception):
    """A find that does not hold: ask.py says why, and nothing is read."""


class Unclear(Exception):
    """A name or a place the box must ask about. The message is the question."""


_TOOLS: Dict[Tuple[Path, str], object] = {}


def _tool(ws: Path, name: str, fits):
    """System/tools/<name>, found as prefs.py finds garrick_lib: the
    workspace's own copy first, then the one beside this folder (an extra
    sits in System/, a step from System/tools/), then a Garrick clone's
    template/, which is what the tests run against. None when none fits."""
    key = (Path(ws), name)
    if key not in _TOOLS:
        found = None
        for src in (Path(ws) / "System" / "tools" / name, HERE.parent / "tools" / name,
                    HERE.parent.parent / "template" / "System" / "tools" / name):
            if not src.is_file():
                continue
            try:
                spec = importlib.util.spec_from_file_location("garrick_ask_" + src.stem, str(src))
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
            except Exception:
                continue
            if fits(mod):
                found = mod
                break
        _TOOLS[key] = found
    return _TOOLS[key]


def lib(ws: Path):
    """garrick_lib.py: the context, the walls, the frontmatter and the live files, read as the checks read them."""
    return _tool(ws, "garrick_lib.py", lambda m: all(callable(getattr(m, f, None)) for f in
                                                     ("load_context", "walled", "parse_frontmatter_text", "live_files")))


def extractor(ws: Path):
    """extract.py: the text of a Word, PowerPoint or Excel file, read and never written anywhere."""
    return _tool(ws, "extract.py", lambda m: callable(getattr(m, "text_of", None)) and isinstance(getattr(m, "KINDS", None), dict))


def any_wall(ctx: dict, these: Iterable[str], those: Iterable[str], lib_) -> bool:
    those = list(those)
    return any(lib_.walled(ctx, a, b) for a in these for b in those)


# ---------------------------------------------------------------- the names in a request


# One thing a name can stand for. `parties` is a frozenset of tags; a place
# (a project or a thread) has its zone and project, and a thread its name.
Entry = collections.namedtuple("Entry", "kind label parties zone project thread")


def _norm(text: str) -> str:
    return " ".join(str(text).replace("’", "'").split()).lower()


def hub_parties(ws: Path, zone: str, project: str, lib_) -> frozenset:
    """The `party:` of a project's hub, the tag the walls are checked against."""
    fm = lib_.parse_frontmatter(Path(ws) / "Zones" / zone / project / (project + ".md"))
    value = fm.get("party")
    values = value if isinstance(value, list) else [value] if value else []
    return frozenset(t for t in (lib_.strip_tag(str(v)) for v in values) if t)


def entries(ws: Path, names: Dict[str, Dict[str, dict]], ctx: dict, lib_) -> List[Tuple[str, bool, Entry]]:
    """(form, capital, entry) for every name the request may hold: `capital`
    when the form counts only written with a capital, as a first name alone."""
    out: List[Tuple[str, bool, Entry]] = []
    for tag, row in ctx.get("parties", {}).items():
        e = Entry("party", row.get("party") or tag, frozenset([tag]), row.get("zone") or None, None, None)
        out += [(row.get("party") or "", False, e), (tag, False, e)]
    for person in ctx.get("people", []):
        party = person.get("party") or ""
        zone = ctx.get("parties", {}).get(party, {}).get("zone") or None
        e = Entry("person", person["name"], frozenset([party]) if party else frozenset(), zone, None, None)
        out.append((person["name"], False, e))
        words = person["name"].split()
        if len(words) > 1:
            out.append((words[0], True, e))
    for zone, projects in names.items():
        for project, r in projects.items():
            parties = hub_parties(ws, zone, project, lib_)
            folder = Path(ws) / "Zones" / zone / project
            e = Entry("project", project, parties, zone, project, None)
            out += [(project, False, e), (_spoken(lib_, folder), False, e)]
            for thread in r["threads"]:
                t = Entry("thread", "%s, %s" % (project, thread), parties, zone, project, thread)
                out += [(thread, False, t), (_spoken(lib_, folder / "Threads" / thread), False, t)]
    by_form: Dict[str, List[Entry]] = {}
    for form, _, e in out:
        by_form.setdefault(_norm(form), []).append(e)
    for heard, means in ctx.get("aliases", {}).items():
        for e in by_form.get(_norm(means), []):
            out.append((heard, False, e))
    return [(f, cap, e) for f, cap, e in out if len(_norm(f)) >= SHORTEST]


def _spoken(lib_, folder: Path) -> str:
    """A name's `spoken:` form, what is heard for it, or nothing."""
    try:
        return lib_.spoken_of(folder) or ""
    except Exception:
        return ""


def _order(e: Entry) -> tuple:
    return (e.kind, e.label, sorted(e.parties), e.zone or "", e.project or "", e.thread or "")


def _unclear(cands: Iterable[Entry]) -> bool:
    cands = list(cands)
    places = {(e.zone, e.project, e.thread) for e in cands if e.kind in ("project", "thread")}
    return len({e.parties for e in cands}) > 1 or len(places) > 1


class Mentions:
    """The names a request holds: what each stands for, or the question to ask."""

    def __init__(self, found: List[Entry], question: Optional[str] = None):
        self.entries, self.question = found, question

    @property
    def parties(self) -> Set[str]:
        return set().union(*(e.parties for e in self.entries)) if self.entries else set()

    @property
    def places(self) -> List[Tuple[str, str, Optional[str]]]:
        seen = []
        for e in self.entries:
            if e.kind in ("project", "thread") and (e.zone, e.project, e.thread) not in seen:
                seen.append((e.zone, e.project, e.thread))
        return seen


def mentions(ws: Path, request: str, names: Dict[str, Dict[str, dict]], ctx: dict, lib_) -> Mentions:
    """The names in a request, each settled to one party or place, or the one
    question that settles the first that is not. A longer name holds the
    shorter ones inside it ("Acme Review" holds "Acme"); a name that fits
    two entries is narrowed by the other names in the request ("Pricing" in
    two projects, with "Acme" beside it), and asked about when it is not."""
    text = str(request).replace("’", "'")
    spans: Dict[Tuple[int, int], Set[Entry]] = {}
    for form, capital, e in entries(ws, names, ctx, lib_):
        pattern = r"(?<!\w)%s(?!\w)" % r"\s+".join(re.escape(w) for w in _norm(form).split())
        for m in re.finditer(pattern, text, re.I):
            if capital and not text[m.start()].isupper():
                continue
            spans.setdefault((m.start(), m.end()), set()).add(e)
    kept: List[Tuple[int, int]] = []
    for span in sorted(spans, key=lambda s: (s[0] - s[1], s[0])):     # the longest first
        if not any(span[0] < k[1] and k[0] < span[1] for k in kept):
            kept.append(span)
    kept.sort()
    settled: Dict[Tuple[int, int], Entry] = {}
    for _ in range(2):                          # a name settled in the first pass can settle another
        parties = set().union(*(e.parties for e in settled.values())) if settled else set()
        places = {(e.zone, e.project) for e in settled.values() if e.project}
        for span in kept:
            if span in settled:
                continue
            cands = sorted(spans[span], key=_order)
            if not _unclear(cands):
                settled[span] = cands[0]
                continue
            narrowed = ([e for e in cands if e.project and (e.zone, e.project) in places]
                        or [e for e in cands if e.parties & parties])
            if narrowed and not _unclear(narrowed):
                settled[span] = narrowed[0]
    for span in kept:
        if span not in settled:
            return Mentions([], which(sorted(spans[span], key=_order), ctx))
    return Mentions([settled[s] for s in kept])


def which(cands: List[Entry], ctx: dict) -> str:
    """One question for the ear, naming the candidates as they are said."""
    def said(e: Entry) -> str:
        if e.kind == "person":
            of = ", ".join(sorted(ctx.get("parties", {}).get(p, {}).get("party") or p for p in e.parties))
            return "%s of %s" % (e.label, of) if of else e.label
        return e.label
    labels: List[str] = []
    for e in cands:
        label = said(e)
        if sum(said(o) == label for o in cands) > 1 and e.zone:
            label += " in %s" % e.zone
        if label not in labels:
            labels.append(label)
    labels = labels[:MOST_NAMED]
    return "Which do you mean: %s?" % (", ".join(labels[:-1]) + " or " + labels[-1] if len(labels) > 1 else labels[0])


# ---------------------------------------------------------------- the scope


class Scope:
    """Where an answer reads. `parties` are the tags it may read for; `every`
    is a question across every zone, which reads within one group of
    parties no wall divides."""

    def __init__(self, route: str, zone: Optional[str], project: Optional[str], thread: Optional[str],
                 words: List[str], parties: Set[str], every: bool = False):
        self.route, self.zone, self.project, self.thread = route, zone, project, thread
        self.words, self.parties, self.every = words, parties, every


def scope(ws: Path, find, said: Mentions, names: Dict[str, Dict[str, dict]], ctx: dict, lib_) -> Scope:
    """The session's find, checked against the list as an action is, with the
    names the request holds. Raises Refused, or Unclear with the question."""
    if not isinstance(find, dict):
        raise Refused("a find that is not an object")
    route = find.get("route")
    if route not in ROUTES:
        raise Refused("not somewhere an answer reads: %r" % (route,))
    zone, project, thread = find.get("zone"), find.get("project"), find.get("thread")
    if zone is not None and (not isinstance(zone, str) or zone not in names):
        raise Refused("no zone %r" % (zone,))
    if project is not None:
        if not isinstance(project, str):
            raise Refused("no project %r" % (project,))
        if zone is None:
            holds = [z for z, ps in names.items() if project in ps]
            if len(holds) > 1:
                raise Unclear("Which do you mean: %s?" % " or ".join("%s in %s" % (project, z) for z in holds))
            zone = holds[0] if holds else None
        if zone is None or project not in names[zone]:
            raise Refused("no project %r" % (project,))
    if thread is not None and (project is None or not isinstance(thread, str) or thread not in names[zone][project]["threads"]):
        raise Refused("no thread %r in %s" % (thread, project or zone))
    if project is None and route in ("thread", "meetings") and len(said.places) == 1:
        zone, project, thread = said.places[0]          # the place the request named, when the find left it out
    if route == "thread" and project is None:
        raise Unclear("Which project or thread do you mean?")
    raw = find.get("words") if isinstance(find.get("words"), list) else []
    words = []
    for w in raw:
        w = _norm(w) if isinstance(w, str) else ""
        if len(w) >= SHORTEST and w not in words:
            words.append(w)
    words = words[:MAX_WORDS]
    if route in ("knowledge", "docs"):
        return Scope(route, None, None, None, words, set())
    if project is not None:
        return Scope(route, zone, project, thread, words, set(hub_parties(ws, zone, project, lib_)))
    if said.parties:
        return Scope(route, zone, None, None, words, said.parties)
    if zone is not None:                        # every party of one zone
        return Scope(route, zone, None, None, words,
                     {t for t, row in ctx.get("parties", {}).items() if row.get("zone") == zone})
    return Scope(route, None, None, None, words, set(), every=True)


# ---------------------------------------------------------------- the records


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (ValueError, OSError):
        return False
    return True


def _files(lib_, root: Path, only: Optional[Iterable[Path]] = None) -> Iterable[Path]:
    """The live files under `root` (garrick_lib.live_files()), or those of
    `only`, never a link and never anything that resolves outside `root`."""
    if not root.is_dir():
        return
    for folder in (only if only is not None else [root]):
        if folder.is_file():
            listed: Iterable[Path] = [folder]
        elif folder.is_dir():
            listed = lib_.live_files(folder)
        else:
            continue
        for path in listed:
            if path.is_symlink() or not path.is_file() or not _inside(path, root):
                continue
            try:
                if path.stat().st_size > MAX_FILE:
                    continue
            except OSError:
                continue
            yield path


def _body(text: str) -> str:
    """A note without its frontmatter."""
    m = re.match(r"﻿?---\n.*?\n(?:---|\.\.\.)[ \t]*\n", text, re.S)
    return text[m.end():] if m else text


def _date(fm: dict, path: Path) -> str:
    value = fm.get("date")
    if isinstance(value, str) and re.match(r"\d{4}-\d{2}-\d{2}", value):
        return value[:10]
    m = re.match(r"(\d{2})(\d{2})(\d{2})(?:\D|$)", path.name)
    return "20%s-%s-%s" % m.groups() if m else ""


def passage(body: str, words: List[str], most: int = PASSAGE) -> str:
    """The paragraphs of a body that hold a word looked for, or its opening
    when none do or none was asked for, cut to `most` characters."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    hits = [p for p in paras if any(w in p.lower() for w in words)] if words else []
    out, size = [], 0
    for p in hits or paras:
        if out and size + len(p) > most:
            break
        out.append(p[:most])
        size += len(p)
    return "\n\n".join(out)


def _text(ws: Path, path: Path, sources: bool) -> Optional[str]:
    """A note's text, or a Sources/ document's through extract.py; None for anything else."""
    suffix = path.suffix.lower()
    if suffix in NOTES:
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
    ex = extractor(ws) if sources else None
    if ex is not None and suffix in ex.KINDS:
        try:
            return ex.text_of(str(path), ex.KINDS[suffix])
        except Exception:               # extract.Unreadable, or anything a damaged file raises
            return None
    return None


def search(ws: Path, sc: Scope, ctx: dict, lib_) -> List[dict]:
    """Every record inside the scope that the words find, best first, as
    {"path", "date", "parties", "text"}: the whole of it a prompt may hold.
    Nothing outside the scope is opened."""
    ws = Path(ws)
    found: List[Tuple[tuple, dict]] = []

    def consider(path: Path, root: Path, parties: List[str], text: str, first: bool = False) -> None:
        fm = lib_.parse_frontmatter_text(text) if path.suffix.lower() == ".md" else {}
        body = _body(text) if fm else text
        low = body.lower()
        hits = [low.count(w) for w in sc.words]
        if sc.words and not any(hits) and not first:
            return
        date = _date(fm, path)
        rank = (1 if first else 0, sum(1 for h in hits if h), sum(hits), date)
        found.append((rank, {"path": path.relative_to(ws).as_posix(), "date": date, "parties": sorted(parties),
                             "text": passage(body, sc.words)}))

    if sc.route in ("knowledge", "docs"):
        root = ws / ("Wikis/Knowledge/wiki" if sc.route == "knowledge" else "System/garrick-docs")
        for path in _files(lib_, root):
            text = _text(ws, path, False)
            if text is not None:
                consider(path, root, [], text)
    elif sc.route == "meetings":
        root = ws / "Wikis" / "Meetings" / "wiki"
        for path in _files(lib_, root):
            text = _text(ws, path, False)
            if text is None:
                continue
            fm = lib_.parse_frontmatter_text(text)
            parties = _tags(fm.get("parties"), lib_) or _tags(fm.get("party"), lib_)
            if not parties or (fm.get("parties") is not None and not fm.get("zone")):
                continue                        # unfinished: nothing on it may be used
            if sc.zone and fm.get("zone") and fm.get("zone") != sc.zone:
                continue
            if not sc.every and not set(parties) & sc.parties:
                continue
            consider(path, root, parties, text)
    else:
        root = ws / "Zones" / sc.zone / sc.project
        hub = root / (sc.project + ".md")
        if sc.thread is not None:
            folder = root / "Threads" / sc.thread
            note = folder / (sc.thread + ".md")
            only = [folder, hub, root / "Sources"]
        else:
            note, only = hub, None
        parties = sorted(sc.parties)
        for path in _files(lib_, root, only):
            text = _text(ws, path, "Sources" in path.relative_to(root).parts)
            if text is not None:
                consider(path, root, parties, text, first=path == note)
    found.sort(key=lambda r: (r[0], r[1]["path"]), reverse=True)
    return [r for _, r in found]


def _tags(value, lib_) -> List[str]:
    values = value if isinstance(value, list) else [value] if value else []
    return sorted({t for t in (lib_.strip_tag(str(v)) for v in values) if t})


def pick(records: List[dict], held: Set[str], ctx: dict, lib_, most: int = MAX_RECORDS) -> Tuple[List[dict], bool]:
    """The records a process that holds `held` may be given, best first, at
    most `most`, and whether a wall held any back: one whose parties are
    walled from each other, from a party held already, or from one picked
    before it. So a question across every zone reads within one group of
    parties no wall divides, the one its best record starts."""
    group, chosen, back = set(held), [], False
    for r in records:
        parties = set(r["parties"])
        if any_wall(ctx, parties, parties | group, lib_):
            back = True
            continue
        if len(chosen) < most:
            chosen.append(r)
            group |= parties
    return chosen, back
