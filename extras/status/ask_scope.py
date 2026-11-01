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
is unclear: the box asks which, and nothing is read. The answer settles it
by another name, by the zone it names, or by an option exactly as the
question offered it; an answer that names two options is asked again
(#294). scope() then takes the session's `find`, the route and the place it
proposed, checked against the list as ask.py checks an action, and works
out the parties it covers.

**The records.** search() reads files inside the scope and nowhere else:

    meetings   Wikis/Meetings/wiki/, each page with its parties: a list of
               tags, and a zone, as check.py's finished() asks; a person or
               entity page with its `party:` alone. Anything else is
               unfinished and never read
    knowledge  Wikis/Knowledge/wiki/: published material, of no party; a page
               that carries a party or a zone is not published, and is skipped
    thread     the project's folder, or the thread's with its hub: notes, and
               the documents in a Sources/ folder, Word, PowerPoint and Excel
               through extract.py. Each file is of its hub's party and, inside
               a thread, its thread's too, as check.py reads them; a project
               whose hub names no party is refused, and nothing in it is read
    docs       System/garrick-docs/: Garrick's own pages, of no party

**It fails closed.** A record whose parties cannot all be stated, a tag the
Parties table does not hold, a `parties:` that is not a list, is never read,
even where check.py only warns about it.

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


def note_tags(note: Path, lib_) -> frozenset:
    """The `party:` tags a hub or thread note declares, read as check.py's party_tags() reads them."""
    return frozenset(_tags(lib_.parse_frontmatter(note).get("party"), lib_))


def hub_parties(ws: Path, zone: str, project: str, lib_) -> frozenset:
    """The `party:` of a project's hub, the tag the walls are checked against."""
    return note_tags(Path(ws) / "Zones" / zone / project / (project + ".md"), lib_)


def place_parties(ws: Path, zone: str, project: str, thread: Optional[str], lib_) -> frozenset:
    """The parties a place is written for: its hub's, and a thread's own as
    well; for a whole project, every thread's in it, live or not."""
    folder = Path(ws) / "Zones" / zone / project
    tags = set(hub_parties(ws, zone, project, lib_))
    threads = [thread] if thread is not None else sorted(p.name for p in (folder / "Threads").glob("*/"))
    for t in threads:
        tags |= note_tags(folder / "Threads" / t / (t + ".md"), lib_)
    return frozenset(tags)


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
                t = Entry("thread", "%s, %s" % (project, thread), place_parties(ws, zone, project, thread, lib_),
                          zone, project, thread)
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
    """The names a request holds: what each stands for, or the question to
    ask. `heard` keeps each name as the request wrote it: (start, end, the
    words, every entry it was settled to), for the command session's
    `<names>` block (ask.heard_names())."""

    def __init__(self, found: List[Entry], question: Optional[str] = None,
                 heard: Optional[List[Tuple[int, int, str, List[Entry]]]] = None):
        self.entries, self.question, self.heard = found, question, heard or []

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

    def since(self, start: int) -> "Mentions":
        """The names heard from `start` on: what is left when the words
        before it are dropped."""
        keep = [i for i, h in enumerate(self.heard) if h[0] >= start]
        return Mentions([self.entries[i] for i in keep], self.question, [self.heard[i] for i in keep])


def _pattern(form: str) -> str:
    """A name as a whole word or words, however the spaces between them fall."""
    return r"(?<!\w)%s(?!\w)" % r"\s+".join(re.escape(w) for w in _norm(form).split())


def _longest(spans: Iterable[Tuple[int, int]]) -> List[Tuple[int, int]]:
    """The spans no longer one overlaps, the longest first, in order."""
    kept: List[Tuple[int, int]] = []
    for span in sorted(set(spans), key=lambda s: (s[0] - s[1], s[0])):
        if not any(span[0] < k[1] and k[0] < span[1] for k in kept):
            kept.append(span)
    return sorted(kept)


def mentions(ws: Path, request: str, names: Dict[str, Dict[str, dict]], ctx: dict, lib_,
             answer: Optional[int] = None) -> Mentions:
    """The names in a request, each settled to one party or place, or the one
    question that settles the first that is not. A longer name holds the
    shorter ones inside it ("Acme Review" holds "Acme"); a name that fits
    two entries is narrowed by the other names in the request ("Pricing" in
    two projects, with "Acme" beside it), and asked about when it is not.

    `answer` is where, in a request the box asked about, the answer to its
    question begins (#294). The answer may also settle a name by a zone it
    names ("the one in Work") or by one of the options exactly as which()
    offered it. Every way the request narrows a name must agree: an answer
    that names both options, or none, is asked again."""
    text = str(request).replace("’", "'")
    spans: Dict[Tuple[int, int], Set[Entry]] = {}
    for form, capital, e in entries(ws, names, ctx, lib_):
        for m in re.finditer(_pattern(form), text, re.I):
            if capital and not text[m.start()].isupper():
                continue
            spans.setdefault((m.start(), m.end()), set()).add(e)
    kept = _longest(spans)
    zones: Set[str] = set()
    if answer is not None:
        for zone in names:
            for m in re.finditer(_pattern(zone), text[answer:], re.I):
                at = (m.start() + answer, m.end() + answer)
                if not any(at[0] < k[1] and k[0] < at[1] for k in kept):    # a word of a longer name is that name's
                    zones.add(zone)
    settled: Dict[Tuple[int, int], Entry] = {}
    means: Dict[Tuple[int, int], List[Entry]] = {}     # every entry a settled name stands for, all of one party and place
    for _ in range(2):                          # a name settled in the first pass can settle another
        parties = set().union(*(e.parties for e in settled.values())) if settled else set()
        places = {(e.zone, e.project) for e in settled.values() if e.project}
        for span in kept:
            if span in settled:
                continue
            cands = sorted(spans[span], key=_order)
            if not _unclear(cands):
                settled[span], means[span] = cands[0], cands
                continue
            by_zone = [e for e in cands if e.zone in zones]
            by_label, labels = offered(cands, ctx, text, answer) if answer is not None else ([], 0)
            if len({e.zone for e in by_zone}) > 1 or labels > 1:
                continue                        # the answer names two of the options: asked again
            narrowed = None
            for way in ([e for e in cands if e.project and (e.zone, e.project) in places]
                        or [e for e in cands if e.parties & parties], by_zone, by_label):
                if way:                         # each way that narrows at all, and all of them together
                    narrowed = [e for e in (cands if narrowed is None else narrowed) if e in way]
            if narrowed and not _unclear(narrowed):
                settled[span], means[span] = narrowed[0], narrowed
    for span in kept:
        if span not in settled:
            return Mentions([], which(sorted(spans[span], key=_order), ctx))
    return Mentions([settled[s] for s in kept], heard=[(s[0], s[1], text[s[0]:s[1]], means[s]) for s in kept])


def offered(cands: List[Entry], ctx: dict, text: str, answer: int) -> Tuple[List[Entry], int]:
    """The candidates whose option, as which() says it, the answer holds
    word for word, the longest where one option holds another ("Acme Corp"
    and "Acme Corp in Work"), and how many options it holds."""
    by_label: Dict[str, List[Entry]] = {}
    for label, e in _labels(cands, ctx):
        by_label.setdefault(label, []).append(e)
    found: Dict[Tuple[int, int], str] = {}
    for label in by_label:
        for m in re.finditer(_pattern(label), text[answer:], re.I):
            found.setdefault((m.start(), m.end()), label)
    named = [found[span] for span in _longest(found)]
    return [e for label in dict.fromkeys(named) for e in by_label[label]], len(set(named))


def _labels(cands: List[Entry], ctx: dict) -> List[Tuple[str, Entry]]:
    """Each candidate as a question names it, with its zone where two would
    otherwise be said alike."""
    def said(e: Entry) -> str:
        if e.kind == "person":
            of = ", ".join(sorted(ctx.get("parties", {}).get(p, {}).get("party") or p for p in e.parties))
            return "%s of %s" % (e.label, of) if of else e.label
        return e.label
    out = []
    for e in cands:
        label = said(e)
        if sum(said(o) == label for o in cands) > 1 and e.zone:
            label += " in %s" % e.zone
        out.append((label, e))
    return out


def which(cands: List[Entry], ctx: dict) -> str:
    """One question for the ear, naming the candidates as they are said."""
    labels: List[str] = []
    for label, _ in _labels(cands, ctx):
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
        hub = hub_parties(ws, zone, project, lib_)
        if not hub or not hub <= set(ctx.get("parties", {})):
            # Nothing can say which side of a wall its files are on.
            raise Refused("%s names no party %s, so nothing in it is read"
                          % (project, "the Parties table holds" if hub else "in its hub"))
        return Scope(route, zone, project, thread, words, set(place_parties(ws, zone, project, thread, lib_)))
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
            if text is None:
                continue
            fm = lib_.parse_frontmatter_text(text) if path.suffix.lower() == ".md" else {}
            if any(fm.get(k) for k in ("parties", "party", "zone")):
                continue                        # a page of someone's, not published: never read as published
            consider(path, root, [], text)
    elif sc.route == "meetings":
        root = ws / "Wikis" / "Meetings" / "wiki"
        for path in _files(lib_, root):
            text = _text(ws, path, False)
            if text is None:
                continue
            fm = lib_.parse_frontmatter_text(text)
            parties = page_parties(fm, ctx, lib_)
            if not parties:
                continue                        # unfinished, or its parties cannot all be stated: never used
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
        hub_tags, thread_tags = note_tags(hub, lib_), {}
        for path in _files(lib_, root, only):
            parts = path.relative_to(root).parts
            tags = set(hub_tags)
            if len(parts) > 2 and parts[0] == "Threads":     # a thread's file: its party too, as check.py has it
                if parts[1] not in thread_tags:
                    thread_tags[parts[1]] = note_tags(root / "Threads" / parts[1] / (parts[1] + ".md"), lib_)
                tags |= thread_tags[parts[1]]
            text = _text(ws, path, "Sources" in parts)
            if text is not None:
                consider(path, root, sorted(tags), text, first=path == note)
    found.sort(key=lambda r: (r[0], r[1]["path"]), reverse=True)
    return [r for _, r in found]


def _tags(value, lib_) -> List[str]:
    values = value if isinstance(value, list) else [value] if value else []
    return sorted({t for t in (lib_.strip_tag(str(v)) for v in values) if t})


PARTY_ALONE = ("person", "entity")       # the pages one `party:` may stand for: read on every side of a wall


def page_parties(fm: dict, ctx: dict, lib_) -> List[str]:
    """A Meetings page's parties, or none when they cannot all be stated: a
    finished page has a zone and a list of tags (check.py's finished()); a
    person or entity page may have its `party:` alone. Every tag must be in
    the Parties table, since walled() never matches one it does not hold."""
    if str(fm.get("type") or "").strip().lower() in PARTY_ALONE and fm.get("parties") is None:
        tags = _tags(fm.get("party"), lib_)
    elif fm.get("zone") and isinstance(fm.get("parties"), list):
        tags = _tags(fm.get("parties"), lib_)
    else:
        return []
    return tags if tags and set(tags) <= set(ctx.get("parties", {})) else []


def pick(records: List[dict], held: Set[str], ctx: dict, lib_, most: int = MAX_RECORDS) -> Tuple[List[dict], bool]:
    """The records a process that holds `held` may be given, best first, at
    most `most`, and whether a wall held any back: one whose parties are
    walled from each other, from a party held already, or from one picked
    before it. So a question across every zone reads within one group of
    parties no wall divides, the one its best record starts."""
    group, chosen, back = set(held), [], False
    known = set(ctx.get("parties", {}))
    for r in records:
        parties = set(r["parties"])
        if not parties <= known:
            continue                            # a tag no wall can be checked against: never read
        if any_wall(ctx, parties, parties | group, lib_):
            back = True
            continue
        if len(chosen) < most:
            chosen.append(r)
            group |= parties
    return chosen, back
