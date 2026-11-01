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
(#294). A request of its own ending in one of those, in brackets, "Where
does Pricing stand? (Pricing in Work)", settles the same way: it is the
form the box puts back after a wall reset. scope() then takes the
session's `find`, the route and the place it proposed, checked against the
list as ask.py checks an action, and works out the parties it covers.

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
ROUTES = ("meetings", "knowledge", "thread", "docs", "actions")
ORDERS = ("recent",)        # a find's `order`: the newest first, for a question about the last or since (#315)
# A question about time, in the user's own words: the last, the latest, the
# most recent or newest, or what happened since. Read when the session's find
# leaves `order` out, so such a question is ranked by date all the same.
RECENT = re.compile(r"\b(?:last|latest|most\s+recent(?:ly)?|newest|since)\b", re.I)
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
                 heard: Optional[List[Tuple[int, int, str, List[Entry]]]] = None, option: Optional[str] = None):
        self.entries, self.question, self.heard = found, question, heard or []
        self.option = option        # the option, as which() offered it, the answer settled the name asked about to

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


# An answer that rules something out, or reaches past the options, settles
# nothing by a zone or an option: it is asked again (#294).
RULED_OUT = re.compile(r"\b(?:not|no|but|except|other|others|another|else|or|rather|instead|never|without|neither|nor|"
                       r"exclud\w*)\b|n't\b", re.I)


def _zone_said(answer: str, names: Dict[str, Dict[str, dict]]) -> Optional[Tuple[str, int, int]]:
    """The zone an answer names in one of the clear forms, and where: the
    zone alone ("Work"), "in Work", "from Work", "the one in Work", "the
    Work one", in any case, with a full stop or none. Anything else, "the one
    I work on" or "not the one in Work", names no zone."""
    body = answer.rstrip()
    body = body.rstrip(".!") if body else body
    lead = len(body) - len(body.lstrip())
    for zone in names:
        z = r"\s+".join(re.escape(w) for w in zone.split())
        for form in (r"(%s)", r"(?:the\s+one\s+)?(?:in|from)\s+(%s)", r"the\s+(%s)\s+one"):
            m = re.fullmatch(form % z, body.strip(), re.I)
            if m:
                return zone, lead + m.start(1), lead + m.end(1)
    return None


def _bracketed(request: str) -> Optional[Tuple[str, int]]:
    """A request that ends in brackets, "Where does Pricing stand? (Pricing
    in Work)", as a request and its answer: the brackets' words where an
    answer would stand, at the same place, and where they begin. None when
    it does not end so, or the brackets hold brackets or nothing."""
    body = str(request).rstrip()
    if not body.endswith(")"):
        return None
    at = body.rfind("(")
    inner = body[at + 1:-1]
    if at < 1 or not body[:at].strip() or not inner.strip() or ")" in inner:
        return None
    return body[:at] + "\n" + inner + " ", at + 1


def mentions(ws: Path, request: str, names: Dict[str, Dict[str, dict]], ctx: dict, lib_,
             answer: Optional[int] = None) -> Mentions:
    """The names in a request: _settle()'s, or, for a request of its own
    that _settle() asks about and that ends in brackets, the brackets read
    as the answer to that question, when that settles every name (#294).
    The box puts a question back in that form after a wall reset; read so,
    every rule an answer is held to holds for the brackets too, and they
    settle nothing that the question would not have settled."""
    got = _settle(ws, request, names, ctx, lib_, answer)
    if got.question and answer is None:
        split = _bracketed(request)
        if split is not None:
            again = _settle(ws, split[0], names, ctx, lib_, split[1])
            if not again.question:
                return Mentions(again.entries, heard=again.heard)
    return got


def _settle(ws: Path, request: str, names: Dict[str, Dict[str, dict]], ctx: dict, lib_,
            answer: Optional[int] = None) -> Mentions:
    """The names in a request, each settled to one party or place, or the one
    question that settles the first that is not. A longer name holds the
    shorter ones inside it ("Acme Review" holds "Acme"); a name that fits
    two entries is narrowed by the other names in the request ("Pricing" in
    two projects, with "Acme" beside it), and asked about when it is not.

    `answer` is where, in a request the box asked about, the answer to its
    question begins (#294). The answer may also settle a name by one of the
    options exactly as which() offered it, and the name the question asked
    about by a zone, said in one of the clear forms _zone_said() takes. An
    answer that rules anything out ("not the one in Work", "the other
    one", "Work or Personal") settles nothing, by a name in it either, and
    the question is asked again. Every way
    the request narrows a name must agree: an answer that names both
    options, or none, is asked again."""
    text = str(request).replace("’", "'")
    spans: Dict[Tuple[int, int], Set[Entry]] = {}
    for form, capital, e in entries(ws, names, ctx, lib_):
        for m in re.finditer(_pattern(form), text, re.I):
            if capital and not text[m.start()].isupper():
                continue
            spans.setdefault((m.start(), m.end()), set()).add(e)
    kept = _longest(spans)
    said = text[answer:] if answer is not None else ""
    plain = answer is not None and not RULED_OUT.search(said)
    zone = _zone_said(said, names) if plain else None
    if zone is not None:
        at = (answer + zone[1], answer + zone[2])
        for k in kept:                          # a zone's word that is also a name: only when that name is all of the zone
            if at[0] < k[1] and k[0] < at[1] and not _all_of(spans[k], zone[0], ctx):
                zone = None
                break

    def settle(within, asked=None, answered=False):
        settled: Dict[Tuple[int, int], Entry] = {}
        means: Dict[Tuple[int, int], List[Entry]] = {}     # every entry a settled name stands for, all of one party and place
        for _ in range(2):                      # a name settled in the first pass can settle another
            parties = set().union(*(e.parties for e in settled.values())) if settled else set()
            places = {(e.zone, e.project) for e in settled.values() if e.project}
            for span in within:
                if span in settled:
                    continue
                cands = sorted(spans[span], key=_order)
                if not _unclear(cands):
                    settled[span], means[span] = cands[0], cands
                    continue
                by_zone = [e for e in cands if e.zone == zone[0]] if span == asked else []
                by_label = offered(cands, ctx, text, answer) if answered else []
                narrowed = None
                for way in ([e for e in cands if e.project and (e.zone, e.project) in places]
                            or [e for e in cands if e.parties & parties], by_zone, by_label):
                    if way:                     # each way that narrows at all, and all of them together
                        narrowed = [e for e in (cands if narrowed is None else narrowed) if e in way]
                if narrowed and not _unclear(narrowed):
                    settled[span], means[span] = narrowed[0], narrowed
        return settled, means

    asked = None
    if answer is not None:                      # the name the question asked about: the first the request before it left open
        before = [k for k in kept if k[1] < answer]
        first, _ = settle(before)
        asked = next((k for k in before if k not in first), None)
        if asked is not None and not plain:     # an answer that rules something out settles nothing: asked again
            return Mentions([], which(sorted(spans[asked], key=_order), ctx))
    settled, means = settle(kept, asked if zone is not None else None, plain)
    for span in kept:
        if span not in settled:
            return Mentions([], which(sorted(spans[span], key=_order), ctx))
    option = None
    if asked is not None:                       # what the answer settled it to, as the question offered it
        option = next((label for label, e in _labels(sorted(spans[asked], key=_order), ctx) if e == settled[asked]), None)
    return Mentions([settled[s] for s in kept], heard=[(s[0], s[1], text[s[0]:s[1]], means[s]) for s in kept],
                    option=option)


def _all_of(cands: Iterable[Entry], zone: str, ctx: dict) -> bool:
    """Whether every entry a name stands for is of this zone, and so is every
    party it stands for: a party tagged like its zone, or named like it."""
    rows = ctx.get("parties", {})
    return all(e.zone == zone and all(rows.get(p, {}).get("zone") == zone for p in e.parties) for e in cands)


def offered(cands: List[Entry], ctx: dict, text: str, answer: int) -> List[Entry]:
    """The candidates of the option, as which() says it, that the answer is
    word for word, a full stop aside: "Dana Whitlock of Acme Corp in Work".
    An answer that holds anything more names none."""
    body = _norm(text[answer:].strip().rstrip(".!"))
    return [e for label, e in _labels(cands, ctx) if _norm(label) == body]


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
    parties no wall divides. `order` is "recent" for a question about the
    last or since (#315), else None; `groups` are the words in groups, two
    spellings of one name in one group (groups())."""

    def __init__(self, route: str, zone: Optional[str], project: Optional[str], thread: Optional[str],
                 words: List[str], parties: Set[str], every: bool = False, order: Optional[str] = None,
                 groups: Optional[List[List[str]]] = None, until: Optional[str] = None, waiting: bool = False):
        self.route, self.zone, self.project, self.thread = route, zone, project, thread
        self.words, self.parties, self.every = words, parties, every
        self.order = order
        self.groups = groups if groups is not None else [[w] for w in words]
        self.until, self.waiting = until, waiting           # an actions find's period and kind (#316)


def wants_recent(text: str) -> bool:
    """Whether a request asks about the last, the latest or since (#315)."""
    return bool(RECENT.search(str(text or "")))


def groups(ws: Path, words: List[str], names: Dict[str, Dict[str, dict]], ctx: dict, lib_) -> List[List[str]]:
    """The words of a find in groups, each group one thing (#315): words that
    settle to the same party, place or person are one group, whichever
    spelling each is ("acme", "acme corp", "acmecorp"), and any other word a
    group of its own. A page is ranked by the groups it holds, not by how
    many spellings of one name it uses."""
    known: Dict[str, Set[Entry]] = {}
    for form, _, e in entries(ws, names, ctx, lib_):
        n = _norm(form)
        for k in (n, n.replace(" ", "")):
            known.setdefault(k, set()).add(e)
    out: List[List[str]] = []
    keys: List[object] = []
    for w in words:
        found = known.get(w, set()) | known.get(w.replace(" ", ""), set())
        key = frozenset(found) if found else ("word", w)
        if key in keys:
            out[keys.index(key)].append(w)
        else:
            keys.append(key)
            out.append([w])
    return out


def no_zone(zone, names: Dict[str, Dict[str, dict]]) -> str:
    """Why a zone the session named is refused: a project's name, when it is
    exactly one project's, said as such so the user can act on it (#308);
    else that there is no such zone. Never guessed into a place."""
    holds = [z for z, ps in names.items() if isinstance(zone, str) and zone in ps]
    if len(holds) == 1:
        return "%s is a project, not a zone" % zone
    return "no zone %r" % (zone,)


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
        raise Refused(no_zone(zone, names))
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
    if project is None and route in ("thread", "meetings", "actions") and len(said.places) == 1:
        zone, project, thread = said.places[0]          # the place the request named, when the find left it out
    if route == "thread" and project is None:
        raise Unclear("Which project or thread do you mean?")
    order = find.get("order")
    if order is not None and order not in ORDERS:
        raise Refused("not an order: %r" % (order,))
    if route == "actions":
        until = find.get("until")
        if until is not None and not (isinstance(until, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", until)):
            raise Refused("not a date: %r" % (until,))
        waiting = find.get("waiting")
        if waiting is not None and not isinstance(waiting, bool):
            raise Refused("not a yes or no: %r" % (waiting,))
        # Garrick lists these itself and no session is told them (#316): the
        # parties a request names narrow the list, and a wall does not, since
        # nothing crosses one into a session.
        return Scope(route, zone, project, thread, [], set() if project is not None else set(said.parties),
                     every=zone is None and project is None and not said.parties, until=until, waiting=bool(waiting))
    raw = find.get("words") if isinstance(find.get("words"), list) else []
    words = []
    for w in raw:
        w = _norm(w) if isinstance(w, str) else ""
        if len(w) >= SHORTEST and w not in words:
            words.append(w)
    words = words[:MAX_WORDS]
    kept = dict(order=order, groups=groups(ws, words, names, ctx, lib_))
    if route in ("knowledge", "docs"):
        return Scope(route, None, None, None, words, set(), **kept)
    if project is not None:
        hub = hub_parties(ws, zone, project, lib_)
        if not hub or not hub <= set(ctx.get("parties", {})):
            # Nothing can say which side of a wall its files are on.
            raise Refused("%s names no party %s, so nothing in it is read"
                          % (project, "the Parties table holds" if hub else "in its hub"))
        return Scope(route, zone, project, thread, words, set(place_parties(ws, zone, project, thread, lib_)), **kept)
    if said.parties:
        return Scope(route, zone, None, None, words, said.parties, **kept)
    if zone is not None:                        # every party of one zone
        return Scope(route, zone, None, None, words,
                     {t for t, row in ctx.get("parties", {}).items() if row.get("zone") == zone}, **kept)
    return Scope(route, None, None, None, words, set(), every=True, **kept)


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
    """When what a record holds happened (#261, slice D): a meeting's
    `date`, a published work's `published` (a month or a year where that is
    all it gives), else the date its name starts with."""
    value = fm.get("date")
    if isinstance(value, str) and re.match(r"\d{4}-\d{2}-\d{2}", value):
        return value[:10]
    value = fm.get("published")
    m = re.match(r"\d{4}(?:-\d{2}){0,2}(?!\d)", value) if isinstance(value, str) else None
    if m:
        return m.group(0)
    m = re.match(r"(\d{2})(\d{2})(\d{2})(?:\D|$)", path.name)
    return "20%s-%s-%s" % m.groups() if m else ""


def _imported(fm: dict, path: Path) -> str:
    """When a record was filed: the page's `created`, or nothing. A file's
    own date is the last edit, a clone or a sync, never a filing date, so it
    is not guessed from. Never what "last time" or "how long ago" is told
    from."""
    value = fm.get("created")
    return value[:10] if isinstance(value, str) and re.match(r"\d{4}-\d{2}-\d{2}", value) else ""


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
    {"path", "date", "imported", "title", "parties", "text"}: the whole of it
    a prompt or a citation may hold. `date` is when it happened, `imported`
    when it was filed.

    Best first is by the groups of words a record holds (groups()), each
    counted once however it is spelled, then how often, then the date. With
    `order` "recent" (#315) it is the newest first: by `date`, then
    `imported`, and the words only break ties, so a question about the last
    meeting with a party reads the newest pages that name it, not the ones
    that name it most. A thread's own note comes first either way.
    Nothing outside the scope is opened."""
    ws = Path(ws)
    found: List[Tuple[tuple, dict]] = []

    def consider(path: Path, root: Path, parties: List[str], text: str, first: bool = False) -> None:
        fm = lib_.parse_frontmatter_text(text) if path.suffix.lower() == ".md" else {}
        body = _body(text) if fm else text
        low = body.lower()
        hits = [max(low.count(w) for w in group) for group in sc.groups]
        if sc.words and not any(hits) and not first:
            return
        date, imported = _date(fm, path), _imported(fm, path)
        words = (sum(1 for h in hits if h), sum(hits))
        lead = 1 if first else 0
        rank = (lead, date, imported) + words if sc.order == "recent" else (lead,) + words + (date,)
        title = fm.get("title") if isinstance(fm.get("title"), str) and fm.get("title").strip() else path.stem
        found.append((rank, {"path": path.relative_to(ws).as_posix(), "date": date, "imported": imported,
                             "title": title.strip(), "parties": sorted(parties), "text": passage(body, sc.words)}))

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
    most `most`, and whether a wall held any back: choose() without its count."""
    chosen, back, _ = choose(records, held, ctx, lib_, most)
    return chosen, back


def choose(records: List[dict], held: Set[str], ctx: dict, lib_, most: int = MAX_RECORDS) -> Tuple[List[dict], bool, int]:
    """The records a process that holds `held` may be given, best first, at
    most `most`; whether a wall held any back: one whose parties are walled
    from each other, from a party held already, or from one picked before
    it; and how many it could have been given with no `most` (#315), the
    `matched` the answer session is told beside how many it was given. A
    record a wall held back is never counted, so the count says nothing of
    what is on the far side. A question across every zone reads within one
    group of parties no wall divides, the one its best record starts."""
    group, chosen, back, matched = set(held), [], False, 0
    known = set(ctx.get("parties", {}))
    for r in records:
        parties = set(r["parties"])
        if not parties <= known:
            continue                            # a tag no wall can be checked against: never read
        if any_wall(ctx, parties, parties | group, lib_):
            back = True
            continue
        matched += 1
        if len(chosen) < most:
            chosen.append(r)
            group |= parties
    return chosen, back, matched


# ---------------------------------------------------------------- the actions (#316)


MOST_ACTIONS = 5            # items one actions reply lists
NOBODY = {"", "nobody", "no one", "noone", "none", "nothing", "-", "—", "n/a", "no"}
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")
_RESUME = re.compile(r"^#{1,6}\s+Resume here\b", re.I)
_ROW = re.compile(r"^\|\s*([^|]*?)\s*\|\s*(.*?)\s*\|\s*$")
_ISO = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_SPOKEN = re.compile(r"\b(\d{1,2})\s+([A-Za-z]{3,9})\.?\s+(\d{4})\b")
_LINK = re.compile(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]")
_TODO: Dict[Path, object] = {}


def todo_lib(ws: Path):
    """The todo skill's todo.py, whose reading of a Todo.md is the only one:
    the digest's and next_up.py's. The workspace's own copy first, then the
    one an installed extra sits beside, then a Garrick clone's template/."""
    ws = Path(ws)
    if ws not in _TODO:
        found = None
        for src in (ws / "System" / "skills" / "todo" / "todo.py", HERE.parent / "skills" / "todo" / "todo.py",
                    HERE.parent.parent / "template" / "System" / "skills" / "todo" / "todo.py"):
            if not src.is_file():
                continue
            try:
                spec = importlib.util.spec_from_file_location("garrick_ask_todo", str(src))
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
            except Exception:
                continue
            if all(callable(getattr(mod, f, None)) for f in ("read", "classify", "plain", "link_of")):
                found = mod
                break
        _TODO[ws] = found
    return _TODO[ws]


def _day(text: str):
    """The first date in a cell, ISO or spoken ("14 November 2026"), or None."""
    import datetime as _dt
    m = _ISO.search(text or "")
    try:
        if m:
            return _dt.date.fromisoformat(m.group(1))
    except ValueError:
        pass
    for day, month, year in _SPOKEN.findall(text or ""):
        n = next((i + 1 for i, name in enumerate(MONTHS) if name[:3].lower() == month[:3].lower()), None)
        try:
            if n:
                return _dt.date(int(year), n, int(day))
        except ValueError:
            continue
    return None


def resume_rows(note: Path) -> Dict[str, str]:
    """A note's Resume here table, by row name, each as written and "" where
    it is still the template's `<placeholder>`. Nothing else of the note."""
    try:
        lines = note.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {}
    out: Dict[str, str] = {}
    start = next((i for i, l in enumerate(lines) if _RESUME.match(l)), None)
    if start is None:
        return out
    for line in lines[start + 1:]:
        if line.startswith("#") or line.strip() == "---":
            break
        m = _ROW.match(line)
        if m and m.group(1) and not set(m.group(1)) <= set("-: "):
            value = m.group(2).replace("\\|", "|").strip()
            out[m.group(1)] = "" if re.fullmatch(r"<[^>]*>", value) else value
    return out


def said_day(day, today) -> str:
    """A date for the ear: today, tomorrow, 14 November, 14 November 2027."""
    n = (day - today).days
    if n == 0:
        return "today"
    if n == 1:
        return "tomorrow"
    if n == -1:
        return "yesterday"
    return "%d %s%s" % (day.day, MONTHS[day.month - 1], "" if day.year == today.year else " %d" % day.year)


def _place_of(link: str, zone: str, names: Dict[str, Dict[str, dict]]) -> Optional[Tuple[str, Optional[str]]]:
    """The project and thread a Todo line's link names inside its zone, or None
    when it names none, or two."""
    parts = [p for p in link.strip().split("/") if p]
    projects = names.get(zone, {})
    if "Threads" in parts:
        at = parts.index("Threads")
        project = parts[at - 1] if at >= 1 else None
        thread = parts[at + 1] if at + 1 < len(parts) else None
        if project in projects and thread in projects[project]["threads"]:
            return project, thread
        return None
    name = parts[-1] if parts else ""
    hits = [(p, name) for p, r in projects.items() if name in r["threads"]]
    if len(hits) == 1:
        return hits[0]
    if not hits and name in projects:
        return name, None
    return None


def _named(text: str, forms: List[Tuple[str, bool, Entry]]) -> Set[str]:
    """Every party a line's own words name: a party, its tag, a person, an alias."""
    out: Set[str] = set()
    for form, capital, e in forms:
        if e.kind not in ("party", "person"):
            continue
        for m in re.finditer(_pattern(form), text, re.I):
            if capital and not text[m.start()].isupper():
                continue
            out |= set(e.parties)
            break
    return out


def actions(ws: Path, sc: Scope, names: Dict[str, Dict[str, dict]], ctx: dict, lib_, today) -> List[dict]:
    """What the user owes, or waits on, inside an actions scope (#316), in
    the digest's order: the open Todo lines, read through todo.py's own
    reading, and each live thread's Next action, Waiting on and Deadline
    rows. Garrick says these itself and no session is told them, so the list
    may hold both sides of a wall, each item labelled with its zone.

    Owed, in this order: lines overdue, the most late first; lines due in
    the period (today to `until`, every later line when there is no
    period), by date; chases that have come due, or come due in the period;
    Next actions whose Deadline falls in the period, by date. With no period,
    then the lines with no date, and the Next actions with no deadline.
    Waited on (`waiting`): chases that have come due, the waiting lines by
    chase date, then each thread's Waiting on row.

    Each item: {"zone", "project", "thread", "text", "date", "kind", "note",
    "parties"}, `note` the thread's note, the project's hub or the zone's
    Todo.md, from the workspace. Meeting pages are never read."""
    import datetime as _dt
    ws = Path(ws)
    todo = todo_lib(ws)
    until = _dt.date.fromisoformat(sc.until) if sc.until else None
    forms = entries(ws, names, ctx, lib_)
    zones = [sc.zone] if sc.zone else list(names)
    first: List[Tuple[tuple, dict]] = []

    def inside(zone: str, project: Optional[str], thread: Optional[str], parties: Set[str]) -> bool:
        if sc.zone and zone != sc.zone:
            return False
        if sc.project is not None:
            return project == sc.project and (sc.thread is None or thread == sc.thread)
        return not sc.parties or bool(parties & sc.parties)

    def note_of(zone: str, project: Optional[str], thread: Optional[str]) -> str:
        if project is None:
            return "Zones/%s/Todo.md" % zone
        if thread is None:
            return "Zones/%s/%s/%s.md" % (zone, project, project)
        return "Zones/%s/%s/Threads/%s/%s.md" % (zone, project, thread, thread)

    def item(rank, zone, project, thread, text, date, kind, parties):
        first.append((rank, {"zone": zone, "project": project, "thread": thread, "text": text,
                             "date": date.isoformat() if date else "", "kind": kind,
                             "note": note_of(zone, project, thread), "parties": sorted(parties)}))

    in_period = (lambda d: until is None or d <= until)
    for zone in zones:
        folder = ws / "Zones" / zone
        if todo is None or not (folder / "Todo.md").is_file():
            continue
        try:
            found = todo.classify(todo.read(folder), today)
        except (OSError, ValueError):
            continue

        def place(line):
            link = todo.link_of(line)
            where = _place_of(link, zone, names) if link else None
            project, thread = where if where else (None, None)
            parties = set(_named(line, forms))
            if project is not None:
                parties |= set(place_parties(ws, zone, project, thread, lib_))
            words = todo.plain(line)
            if link and ": " in words:
                words = words.split(": ", 1)[1]
            return project, thread, parties, words

        def add(rank, line, date, kind):
            project, thread, parties, words = place(line)
            if inside(zone, project, thread, parties):
                item(rank, zone, project, thread, words, date, kind, parties)

        def on(line, rx):
            m = getattr(todo, rx).search(line)
            try:
                return _dt.date.fromisoformat(m.group(1)) if m else None
            except ValueError:
                return None
        if sc.waiting:
            for line in found["chase"]:
                d = on(line, "CHASE_ON")
                add((0, d.isoformat() if d else ""), line, d, "chase")
            for when, line in found.get("waiting", []):
                d = _dt.date.fromisoformat(when) if when else None
                add((1, when or "9999"), line, d, "waiting")
            continue
        for late, line in found["overdue"]:
            add((0, -late), line, on(line, "DUE"), "overdue")
        for line in found["due"]:
            add((1, today.isoformat()), line, today, "due")
        for when, line in found.get("later", []):
            d = _dt.date.fromisoformat(when)
            if in_period(d):
                add((1, when), line, d, "due")
        for line in found["chase"]:
            d = on(line, "CHASE_ON")
            add((2, d.isoformat() if d else ""), line, d, "chase")
        for when, line in found.get("waiting", []):
            d = _dt.date.fromisoformat(when) if when else None
            if d is not None and until is not None and d <= until:
                add((2, when), line, d, "chase")
        if until is None:
            for line in found.get("open", []):
                add((4, ""), line, None, "open")

    # Each live thread's own rows: a project with no thread is its own one.
    for zone in zones:
        for project, r in names.get(zone, {}).items():
            if r["status"] != "active":
                continue
            threads = [t for t, st in r["threads"].items() if st == "active"] or ([None] if not r["threads"] else [])
            for thread in threads:
                parties = set(place_parties(ws, zone, project, thread, lib_))
                if not inside(zone, project, thread, parties):
                    continue
                rows = resume_rows(ws / note_of(zone, project, thread))
                if sc.waiting:
                    who = _LINK.sub(r"\1", rows.get("Waiting on", "")).strip().rstrip(".")
                    if who.casefold() not in NOBODY and not re.match(r"(?i)^(nobody|no one|none)\b", who):
                        item((3, ""), zone, project, thread, who, None, "waits", parties)
                    continue
                step = _LINK.sub(r"\1", rows.get("Next action", "")).strip()
                if not step:
                    continue
                deadline = _day(rows.get("Deadline", ""))
                if deadline is not None and in_period(deadline):
                    item((3, deadline.isoformat()), zone, project, thread, step, deadline, "next", parties)
                elif deadline is None and until is None:
                    item((5, ""), zone, project, thread, step, None, "next", parties)
    first.sort(key=lambda t: (t[0], t[1]["zone"], t[1]["note"], t[1]["text"]))
    return [i for _, i in first]


def action_said(it: dict, names: Dict[str, Dict[str, dict]], today) -> str:
    """One item of an actions list, for the ear: when, what, and where, with
    its zone: "3 days late: Send the revised terms (Pricing, in Work)."."""
    import datetime as _dt
    d = _dt.date.fromisoformat(it["date"]) if it["date"] else None
    kind = it["kind"]
    if kind == "overdue" and d is not None:
        n = (today - d).days
        when = "%d day%s late" % (n, "" if n == 1 else "s")
    elif kind == "due" and d is not None:
        when = "Due " + said_day(d, today) if (d - today).days in (0, 1) else "Due on " + said_day(d, today)
    elif kind == "chase":
        when = "Chase" + ("" if d is None else " " + said_day(d, today) if (d - today).days in (-1, 0, 1)
                          else " since " + said_day(d, today) if d < today else " on " + said_day(d, today))
    elif kind == "waiting":
        when = "Waiting" + ("" if d is None else ", chase on " + said_day(d, today))
    elif kind == "waits":
        when = "Waiting on"
    elif kind == "next":
        when = "Next" + ("" if d is None else ", deadline " + ("" if (d - today).days in (-1, 0, 1) else "on ")
                         + said_day(d, today))
    else:
        when = "Open"
    where = it["thread"] or it["project"]
    place = "%s, in %s" % (where, it["zone"]) if where else "in %s" % it["zone"]
    text = it["text"].rstrip(" .")
    return "%s: %s (%s)." % (when, text, place)


def user_name(ws: Path) -> str:
    """The user's own name, as System/context.md's *Me* section opens: "Jo
    Example. Independent advisor." gives "Jo Example". Two to four words
    with capitals, before the first full stop or comma; "" otherwise. The
    answer session is told it, so a record that names the user is "you"."""
    try:
        text = (Path(ws) / "System" / "context.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    m = re.search(r"(?m)^##\s+Me\s*$\n+\s*(\S[^\n]*)", text)
    if not m:
        return ""
    name = re.match(r"([A-Z][\w'’-]+(?:\s+[A-Z][\w'’-]+){1,3})\s*[.,]", m.group(1).replace("**", ""))
    return name.group(1) if name else ""

