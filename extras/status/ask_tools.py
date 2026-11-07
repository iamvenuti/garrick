#!/usr/bin/env python3
"""ask_tools.py: Garrick's read server for the Ask window (#358).

An MCP server over stdio (JSON-RPC 2.0, one message to a line), started by the
Ask session's `--mcp-config` and holding the only tools that session has:

    search(words, place?, kind?, order?, limit?, after?)   ids, titles and dates
    read(id)                                               the text of a record the server handed out
    places(zone?)                                          projects and threads, with status
    thread_state(place)                                    a thread's Resume here block
    owed(period?, party?, waiting?)                        the Todo lines and Next actions Garrick builds
    propose(action)                                        a proposal, never a result

    python3 ask_tools.py serve --workspace DIR --state DIR [--zone Z]

Python standard library only, 3.9 or later.

**The walls live here.** Every result passes through `Conversation.admit()`,
which asks ask_scope.admits(): the one wall test Asker.admit() uses too. A
result whose parties are walled from what the conversation holds is not
returned. The server latches (`wall`), says nothing of what it withheld and
refuses every call after, and the Ask server that started the session (ask.py)
reads the latch from the state folder after the turn, stops the session and
says the rules' sentence. What the conversation holds is the server's own:
its `seen` parties (what it has admitted) and the parties ask.py wrote to
`in.json` (what the user's requests named), never anything the model says.

**Ids are the server's.** `read` takes only an id that this server handed
out in an admitted result of this conversation. An id made up, one from
before a reset, or one for a record that is gone gets the same words, which
say nothing of whether the record exists.

**Search is the scope index's, with a fallback.** The wall stands at the store
(#358, #341): `search` and `read` open only the scope index of the conversation
(recall.py), which holds the rows that scope may read and no others. Nothing is
filtered after the search, because nothing walled is in the file to rank, count
or order. With no `kind` a search reads every store the scope holds: the zone's
notes, Meetings and Knowledge. The names in the words are expanded and a near
spelling is found through the trigram table (recall.py does both), and a result
that is a thread or hub note carries its Resume here block. `read` is a lookup of
the id in the scope index. Only when the index cannot be opened does `search`
fall back to the keyword find the window used before (ask_scope.search()), and
it says so.

The state folder holds `in.json` (ask.py's: the zone and the parties the
requests named), `out.json` (this server's: its nonce, the parties admitted,
the records handed out, the latch) and `proposals.jsonl` (one line for each
propose call).
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
import re
import secrets
import sys
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
SERVER = "garrick"
TOOLS = ("search", "read", "places", "thread_state", "owed", "propose")
KINDS = ("all", "meetings", "library", "threads", "docs")
ORDERS = ("relevance", "recent")
PROPOSED = ("open", "park", "wake", "todo-add")     # what propose() takes: the verbs a click can carry out
LIMIT = 10                  # records one search returns, unless it asks for more
MOST = 50                   # the most it may ask for
OVERSAMPLE = 5              # rows asked of the index for each one returned, since the zone and kind are cut after
MOST_TEXT = 6000            # characters of one record read() returns
MOST_TODO = 200             # characters of a Todo line a proposal may carry: the button shows all of it
MOST_OWED = 40              # items owed() returns
STATE_TEXT = 1500           # characters of a thread's Resume here block a search result carries
SNIPPET = 300               # characters of a record a search result shows

STOPPED = "This conversation has been stopped. Do not answer. Reply with the single word: stopped."
NOT_GIVEN = "That id was not given in this conversation."
NO_PLACE = "No such place. places() lists the projects and threads."
INDEX_DOWN = "The search index was not available, so this is a plain keyword find."

# The tags a message is built from: a record's own text never opens or closes one.
_TAGS = re.compile(r"<\s*(?=/?\s*(?:records?|request|earlier-request|workspace|names|today|last-results|correction"
                   r"|refreshed|you|zone|tool|system)\b)", re.I)
_UNSEEN = re.compile("[­͏᠎​-‏⁠-⁤﻿]")


def inert(text: str) -> str:
    """A record's text, unable to open or close a tag of the message: folded
    first (NFKC), with the characters that show nothing taken out, then every
    "<" that starts a tag's name written as "&lt;"."""
    return _TAGS.sub("&lt;", _UNSEEN.sub("", unicodedata.normalize("NFKC", str(text))))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_MODS: Dict[str, object] = {}


def scope_mod():
    """ask_scope.py, beside this file: the reading of records and the wall test."""
    if "scope" not in _MODS:
        _MODS["scope"] = _load("garrick_ask_tools_scope", HERE / "ask_scope.py")
    return _MODS["scope"]


def ask_mod():
    """ask.py, beside this file, for the workspace list and the checks of an action. Loaded when a tool needs them."""
    if "ask" not in _MODS:
        _MODS["ask"] = _load("garrick_ask_tools_ask", HERE / "ask.py")
    return _MODS["ask"]


def recall_for(ws: Path):
    """recall.py (#341): the workspace's own copy, else the one in Garrick's template. None when there is none."""
    sc = scope_mod()
    return sc._tool(ws, "recall.py", lambda m: callable(getattr(m, "search", None)))


def sc_body(conv, text: str) -> str:
    return conv.world()[0]._body(text)


def tidy(text: str, most: int) -> str:
    return inert(" ".join(str(text).split()))[:most]


NAME_A_PLACE = "Name the project or thread you mean."
NO_PROJECTS = "No projects."


class Conversation:
    """One Ask conversation, as the read server holds it. Its state is saved to
    `out.json` after every call, for ask.py to read; it reads `in.json` before
    every call, for the zone and the parties ask.py says the requests named."""

    def __init__(self, ws: Path, state: Path, zone: Optional[str] = None):
        self.ws, self.dir, self.zone = Path(ws), Path(state), zone
        self.nonce = secrets.token_hex(2)
        self.seen: set = set()
        self.handed: Dict[str, dict] = {}
        self.count = 0
        self.wall = False           # a result crossed a wall: nothing more is returned
        self.held_back = 0          # how many times a wall held records back from a first reading, which nothing crossed
        self.told: set = set()      # the parties ask.py wrote to in.json: what the requests named
        self.proposed = 0
        self.text_seen = False      # any text out of the workspace has been handed to the session (names too)
        self._world = None          # world(), read once for each tool call
        self.dir.mkdir(parents=True, exist_ok=True)
        try:
            data = json.loads((self.dir / "out.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if isinstance(data, dict) and isinstance(data.get("nonce"), str):
            self.nonce = data["nonce"]
            self.seen = set(data.get("seen") or [])
            self.handed = dict(data.get("handed") or {})
            self.count = int(data.get("count") or 0)
            self.wall = bool(data.get("wall"))
            self.held_back = int(data.get("held_back") or 0)
            self.proposed = int(data.get("proposed") or 0)
            self.text_seen = bool(data.get("text_seen"))
        self.save()

    # ------------------------------------------------------------ state

    def save(self) -> None:
        data = {"nonce": self.nonce, "seen": sorted(self.seen), "handed": self.handed, "count": self.count,
                "wall": self.wall, "held_back": self.held_back, "proposed": self.proposed,
                "read": bool(self.handed), "text_seen": self.text_seen}
        tmp = self.dir / "out.json.tmp"
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(str(tmp), str(self.dir / "out.json"))

    def refresh(self) -> None:
        """What ask.py says: the zone the window answers in and the parties the requests named."""
        try:
            data = json.loads((self.dir / "in.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(data, dict):
            if isinstance(data.get("zone"), str) and data["zone"]:
                self.zone = data["zone"]
            if isinstance(data.get("parties"), list):
                self.told = {str(p) for p in data["parties"]}

    def held(self) -> set:
        return self.seen | self.told

    def world(self):
        """The scope module, garrick_lib, the context and the workspace list: read once for each tool call."""
        if self._world is None:
            sc = scope_mod()
            lib = sc.lib(self.ws)
            if lib is None:
                raise RuntimeError("garrick_lib.py is not in System/tools")
            self._world = (sc, lib, lib.load_context(self.ws), ask_mod().scan(self.ws))
        return self._world

    def admit(self, parties) -> bool:
        """The wall test (ask_scope.admits()) for records of these parties,
        which are then held. A crossing latches the conversation and returns False."""
        if self.wall:
            return False
        sc, lib, ctx, _ = self.world()
        parties = set(parties)
        if not sc.admits(ctx, self.held(), parties, lib):
            self.wall = True
            self.save()
            return False
        self.seen |= parties
        return True

    def hand(self, d: dict) -> str:
        """An id for an admitted record: only an id handed out here can be read."""
        self.count += 1
        rid = "r%d-%s" % (self.count, self.nonce)
        self.handed[rid] = {k: d.get(k) or "" for k in ("path", "title", "date", "imported", "rid", "scope", "kind", "zone")}
        self.handed[rid]["parties"] = sorted(d.get("parties") or [])
        return rid

    def latch(self) -> None:
        self.wall = True
        self.save()

    def fair(self, rows: List[dict], most: int, ctx: dict, lib, sc) -> Optional[List[dict]]:
        """The rows of a result that the conversation may hold, best first, at most `most`: none whose parties are
        walled from what it holds or from a row taken before it (ask_scope.choose()). Rows that a wall holds back are
        left out and counted, never named, so the answer ends with the rules' sentence. When a wall held back every
        row there was, the search reached across it: the conversation is stopped, and None is returned."""
        # A conversation that holds nothing begins its group with the first record, among the parties of the window's
        # zone (all of the table's when it has none): the release's choose() takes that as `start`.
        names = self.world()[3]
        start = set(ctx.get("parties", {})) if not self.zone else set().union(
            *[set(sc.place_parties(self.ws, self.zone, pr, None, lib)) for pr in names.get(self.zone, {})], set())
        chosen, back, _ = sc.choose(rows, self.held(), ctx, lib, most=most, start=start)
        if back and not chosen:
            self.latch()
            return None
        if back:
            self.held_back += 1
        if not self.admit({p for r in chosen for p in r["parties"]}):
            return None
        return chosen

    # ------------------------------------------------------------ records

    def describe(self, rel: str, words: Optional[List[str]] = None) -> Optional[dict]:
        """A record as it is on disk now: its kind, parties, dates and text. None
        for anything that is not a record Ask may read: a path outside the
        places records live, a link, a file too large, a Meetings page with no
        zone or parties, a page of someone's in the library, a project whose hub
        names no party the Parties table holds. Fails closed."""
        sc, lib, ctx, _ = self.world()
        rel = str(rel).replace("\\", "/")
        parts = tuple(Path(rel).parts)
        if not parts or rel.startswith("/") or ".." in parts:
            return None
        p = self.ws / rel
        if p.is_symlink() or not p.is_file():
            return None
        zone = project = thread = None
        if parts[:3] == ("Wikis", "Meetings", "wiki"):
            kind, root = "meetings", self.ws / "Wikis" / "Meetings" / "wiki"
        elif parts[:3] == ("Wikis", "Knowledge", "wiki"):
            kind, root = "library", self.ws / "Wikis" / "Knowledge" / "wiki"
        elif parts[:2] == ("System", "garrick-docs"):
            kind, root = "docs", self.ws / "System" / "garrick-docs"
        elif len(parts) == 3 and parts[0] == "Zones" and parts[2] == "Todo.md":
            # A zone's Todo list holds lines for every project in it, the far side of a wall too, and has no
            # party of its own: it is not a record. owed() serves it line by line, each line with its own wall test.
            return None
        elif len(parts) >= 4 and parts[0] == "Zones":
            kind, root, zone, project = "threads", self.ws / "Zones" / parts[1] / parts[2], parts[1], parts[2]
            if len(parts) > 5 and parts[3] == "Threads":
                thread = parts[4]
        else:
            return None
        if not sc._inside(p, root):
            return None
        try:
            if p.stat().st_size > sc.MAX_FILE:
                return None
        except OSError:
            return None
        text = sc._text(self.ws, p, "Sources" in parts)
        if text is None:
            return None
        fm = lib.parse_frontmatter_text(text) if p.suffix.lower() == ".md" else {}
        body = sc._body(text) if fm else text
        if kind == "meetings":
            parties = sc.page_parties(fm, ctx, lib)
            if not parties:
                return None
            zone = fm.get("zone")
            if isinstance(zone, list) and len(zone) == 1:
                zone = zone[0]
            if not isinstance(zone, str) or not zone.strip():
                return None             # a list of zones cannot be placed: fail closed
            zone = zone.strip()
        elif kind in ("library", "docs"):
            if any(fm.get(k) for k in ("parties", "party", "zone")):
                return None
            parties = []
        else:
            hub = sc.hub_parties(self.ws, zone, project, lib)
            if not hub or not hub <= set(ctx.get("parties", {})):
                return None
            own = set(sc._tags(fm.get("party"), lib)) | set(sc._tags(fm.get("parties"), lib))
            if not own <= set(ctx.get("parties", {})):
                return None             # a tag the Parties table lacks cannot be walled: drop the row
            parties = sorted(set(sc.place_parties(self.ws, zone, project, thread, lib)) | own)
        title = fm.get("title") if isinstance(fm.get("title"), str) and fm.get("title").strip() else p.stem
        return {"path": rel, "kind": kind, "zone": zone, "project": project, "thread": thread,
                "title": title.strip(), "date": sc._date(fm, p), "imported": sc._imported(fm, p),
                "parties": list(parties), "public": kind in ("library", "docs"), "body": body, "text": sc.passage(body, words or [])}

    def line(self, rid: str, d: dict, snippet: str = "") -> str:
        when = [d["date"]] if d.get("date") else ["no date"]
        if d.get("imported"):
            when.append("filed " + d["imported"])
        label = {"meetings": "Meetings", "library": "Library", "docs": "Garrick docs", "todo": "Todo list"}.get(
            d["kind"], d.get("zone") or "Thread")
        head = '[%s] %s · %s · "%s" · %s' % (rid, " · ".join(when), label, tidy(d["title"], 120), d["path"])
        return head + ("\n    " + tidy(snippet, SNIPPET) if snippet else "")

    # ------------------------------------------------------------ places

    def resolve(self, place: str, names) -> Tuple[list, str]:
        """The places a name stands for: [(zone, project, thread or None)], and
        an empty message, else [] and why. Inside the conversation's zone first;
        a zone, a project, a thread, or `Zone/Project`, `Project/Thread`,
        `Zone/Project/Thread`."""
        bits = [b.strip() for b in str(place).split("/") if b.strip()]
        if not bits or len(bits) > 3:
            return [], "Name a zone, a project or a thread, such as Work, Acme Review or Acme Review/Pricing."
        low = lambda s: " ".join(str(s).split()).casefold()
        zones = {low(z): z for z in names}
        found = set()
        if len(bits) == 3:
            z = zones.get(low(bits[0]))
            for pr, r in names.get(z, {}).items():
                if low(pr) == low(bits[1]):
                    found |= {(z, pr, t) for t in r["threads"] if low(t) == low(bits[2])}
        elif len(bits) == 2:
            z = zones.get(low(bits[0]))
            for zz, ps in names.items():
                for pr, r in ps.items():
                    if z == zz and low(pr) == low(bits[1]):
                        found.add((zz, pr, None))
                    if low(pr) == low(bits[0]):
                        found |= {(zz, pr, t) for t in r["threads"] if low(t) == low(bits[1])}
        else:
            if low(bits[0]) in zones:
                found.add((zones[low(bits[0])], None, None))
            for zz, ps in names.items():
                for pr, r in ps.items():
                    if low(pr) == low(bits[0]):
                        found.add((zz, pr, None))
                    found |= {(zz, pr, t) for t in r["threads"] if low(t) == low(bits[0])}
        if not found:
            return [], NO_PLACE
        mine = {f for f in found if f[0] == self.zone}
        found = mine or found
        return sorted(found, key=lambda f: tuple(str(x) for x in f)), ""

    def zone_fits(self, zone: str, lib, ctx: dict) -> bool:
        """Whether a zone as a place may be held with what is held: some scope of the zone has no wall between its
        parties and anything held. A zone with no scope, or no way to list its scopes, does not fit."""
        rc = recall_for(self.ws)
        try:
            scopes = [s for s in rc.scopes_of(self.ws, ctx) if s.kind == "zone" and s.zone.lower() == zone.lower()]
        except Exception:
            return False
        return any(not self.crosses(s.tags, lib, ctx) for s in scopes)

    def one_place(self, place: str, names):
        """The one place a name stands for, or (None, a message that names only candidates the conversation may hold)."""
        found, why = self.resolve(place, names)
        if not found:
            return None, why
        # One test for one match or many: a place the conversation may not hold is left out, and when none is
        # left the answer is the words for a place that does not exist, so a name on the far side cannot be told
        # from one that is not there. The wall is noted (held_back) for the user's answer, never for the session.
        sc, lib, ctx, _ = self.world()
        fair = [f for f in found if (self.zone_fits(f[0], lib, ctx) if f[1] is None else
                                     sc.admits(ctx, self.held(), sc.place_parties(self.ws, f[0], f[1], f[2], lib), lib))]
        if len(fair) < len(found):
            self.held_back += 1
            self.save()
        if not fair:
            return None, NO_PLACE
        if len(fair) > 1:
            return None, "More than one place has that name: %s. Say it as Zone/Project/Thread." % "; ".join(
                "/".join(x for x in f if x) for f in fair[:6])
        return fair[0], ""

    # ------------------------------------------------------------ search

    def keyword(self, words: str, zone: Optional[str], place, kind: str, order: Optional[str], names) -> List[str]:
        """The keyword find the window used before the index (#261): paths, best first."""
        sc, lib, ctx, _ = self.world()
        toks = []
        for w in re.split(r"\s+", words):
            w = sc._norm(w)
            if len(w) >= sc.SHORTEST and w not in toks:
                toks.append(w)
        toks = toks[:sc.MAX_WORDS]
        if not toks:
            return []
        kept = dict(order="recent" if order == "recent" else None, groups=sc.groups(self.ws, toks, names, ctx, lib))
        zones = [zone] if zone else list(names)
        routes = {"meetings": ["meetings"], "library": ["knowledge"], "docs": ["docs"], "threads": ["thread"],
                  "all": ["meetings", "knowledge", "docs"] + (["thread"] if place and place[1] else [])}[kind]
        out: List[str] = []
        for route in routes:
            scopes = []
            if route in ("knowledge", "docs"):
                scopes.append(sc.Scope(route, None, None, None, toks, set(), **kept))
            elif route == "meetings":
                for z in zones:
                    mine = {t for t, row in ctx.get("parties", {}).items() if row.get("zone") == z}
                    scopes.append(sc.Scope(route, z, None, None, toks, mine, **kept))
            elif place and place[1]:
                scopes.append(sc.Scope(route, place[0], place[1], place[2], toks,
                                       set(sc.place_parties(self.ws, place[0], place[1], place[2], lib)), **kept))
            else:
                for z in zones:
                    for pr in names.get(z, {}):
                        scopes.append(sc.Scope(route, z, pr, None, toks, set(sc.place_parties(self.ws, z, pr, None, lib)), **kept))
            for s in scopes:
                try:
                    out += [r["path"] for r in sc.search(self.ws, s, ctx, lib)]
                except Exception:
                    continue
        return list(dict.fromkeys(out))

    def held_tags(self, lib) -> set:
        """Every party the conversation holds, seen or told, in any zone."""
        return {lib.strip_tag(t) for t in self.held()} - {lib.PUBLIC}

    def crosses(self, tags, lib, ctx: dict, extra=()) -> bool:
        """Whether a wall stands between a scope's tags and anything held (or `extra`), or inside what is held."""
        held = self.held_tags(lib) | {lib.strip_tag(t) for t in extra}
        held -= {lib.PUBLIC}
        return bool(held and (lib.crossings(ctx, set(tags), held) or lib.crossings(ctx, held)))

    def scope_for(self, rc, ctx: dict, place, kind: str = "all"):
        """The one scope index this conversation opens: the scope of the zone the window answers in (or the place's
        zone), on the side that holds what is held. (scope, "") or (None, why). Several sides and nothing to choose
        by: the user names the project. What is held spread over two sides: the conversation is stopped."""
        sc, lib, _, _ = self.world()
        zone = place[0] if place else self.zone
        if not zone:
            return None, NAME_A_PLACE
        scopes = [s for s in rc.scopes_of(self.ws, ctx) if s.kind == "zone" and s.zone.lower() == zone.lower()]
        if not scopes:
            return None, NO_PLACE
        every = set().union(*[set(s.tags) for s in scopes])
        need = {lib.strip_tag(t) for t in self.held()} & every
        if place and place[1]:
            need |= {lib.strip_tag(t) for t in sc.place_parties(self.ws, place[0], place[1], place[2], lib)} & every
        extra = {lib.strip_tag(t) for t in sc.place_parties(self.ws, place[0], place[1], place[2], lib)} \
            if place and place[1] else set()
        # A scope fits when what is held on its side is in it and no held party, of any zone, is walled from it.
        fits = [s for s in scopes if need <= set(s.tags) and not self.crosses(s.tags, lib, ctx, extra)]
        if not fits:
            self.latch()
            return None, STOPPED
        if len(fits) > 1:
            if kind == "library":
                return fits[0], ""              # published pages name no party: every side holds the same ones
            return None, NAME_A_PLACE
        return fits[0], ""

    def indexed(self, words: str, limit: int, place, wiki: Optional[str], after: Optional[str], kind: str = "all"):
        """(rows, scope, why): the scope index's results for the words, best first. rows is None when the index
        cannot be used (no recall, a recall without scopes, an error); scope is None with `why` when no scope fits."""
        rc = recall_for(self.ws)
        if rc is None or not all(callable(getattr(rc, n, None)) for n in ("scopes_of", "read", "search")):
            return None, None, ""
        _, _, ctx, _ = self.world()
        try:
            scope, why = self.scope_for(rc, ctx, place, kind)
            if scope is None:
                return [], None, why
            rows = rc.search(words, project=None, root=self.ws, scope=scope, limit=limit, wiki=wiki, after=after)
        except Exception:
            return None, None, ""
        return list(rows or []), scope, ""

    def state_of(self, rc, scope, rid: str, path: str) -> str:
        """The Resume here block of a hub or thread note a result names, as the scope index reads it."""
        parts = path.split("/")
        hub = len(parts) == 4 and parts[0] == "Zones" and parts[3] == parts[2] + ".md"
        note = len(parts) == 6 and parts[0] == "Zones" and parts[3] == "Threads" and parts[5] == parts[4] + ".md"
        if not (hub or note):
            return ""
        try:
            text = rc.read(rid, project=None, root=self.ws, scope=scope)
        except Exception:
            return ""
        return self.resume(text or "")

    @staticmethod
    def wanted(d: dict, kind: str, zone: Optional[str], place) -> bool:
        if kind != "all" and d["kind"] != kind:
            return False
        if d["kind"] in ("meetings", "threads", "todo") and zone and d.get("zone") and d["zone"] != zone:
            return False
        if place and place[1] and d["kind"] == "threads":
            if d["project"] != place[1]:
                return False
            if place[2] and d["thread"] not in (None, place[2]) and "Sources" not in d["path"].split("/"):
                return False
        return True

    def search(self, a: dict) -> str:
        sc, lib, ctx, names = self.world()
        words = " ".join(str(a.get("words") or "").split())
        if not words:
            return "Give the words to look for."
        kind = a.get("kind") or "all"
        order = a.get("order") or "relevance"
        if kind not in KINDS:
            return "kind is one of: %s." % ", ".join(KINDS)
        if order not in ORDERS:
            return "order is one of: %s." % ", ".join(ORDERS)
        try:
            limit = max(1, min(MOST, int(a.get("limit") or LIMIT)))
        except (TypeError, ValueError):
            limit = LIMIT
        after = a.get("after")
        if after is not None and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(after)):
            return "after is a date, YYYY-MM-DD."
        place, zone = None, self.zone
        if a.get("place"):
            place, why = self.one_place(str(a["place"]), names)
            if place is None:
                return why
            zone = place[0]
        wiki = {"meetings": "Meetings", "library": "Knowledge"}.get(kind)
        wide = 200 if order == "recent" else limit * OVERSAMPLE
        rows, scope, why = (None, None, "") if kind == "docs" else self.indexed(words, wide, place, wiki, after, kind)
        if scope is None and rows == []:
            return why                          # no scope fits: the words of a place that is not there, or the question
        terms = [sc._norm(w) for w in words.split() if len(w) >= sc.SHORTEST]
        if rows is None:
            return self.found_by_keyword(words, zone, place, kind, order, names, terms, after, limit)
        recs: List[dict] = []
        rc = recall_for(self.ws)
        for r in rows:
            d = self.shape(r, scope, zone, place)
            if d is None or (kind != "all" and d["kind"] != kind) or not self.in_place(d, place):
                continue
            recs.append(d)
        if kind == "all":
            # The docs are Garrick's own pages: not in the index, so searched by keyword whatever the index says.
            for rel in self.keyword(words, zone, place, "docs", order, names):
                d = self.describe(rel, terms)
                if d is not None and d["kind"] == "docs" and not (after and (not d["date"] or d["date"] < str(after))):
                    recs.append(dict(d, snippet=d["text"]))
        if order == "recent":
            recs.sort(key=lambda d: (d["date"], d["imported"]), reverse=True)
        recs = recs[:limit]
        # What the session now holds: the parties of the records it was given, for the reset between requests.
        # It decides nothing about what is returned.
        cache: dict = {}
        for d in recs:
            lab = lib.labels(self.ws, d["path"], ctx, cache) if d["kind"] != "docs" else None
            self.seen |= {lib.strip_tag(t) for t in (lab or ())} - {"public"}
        lines = []
        for d in recs:
            rid = self.hand(d)
            line = self.line(rid, d, d.get("snippet") or "")
            state = self.state_of(rc, scope, d["rid"], d["path"]) if d.get("rid") and d["kind"] == "threads" else ""
            if state:
                line += "\n    State of play: " + tidy(state, STATE_TEXT)
            lines.append(line)
        self.save()
        head = "%d record%s returned (from the search index)." % (len(recs), "" if len(recs) == 1 else "s")
        if len(recs) == limit:
            head += " There may be more: ask for a larger limit, or narrow the words."
        return head + ("\n" + "\n".join(lines) if lines else "")

    def shape(self, r, scope, zone, place) -> Optional[dict]:
        """A record from one result of the scope index: its kind from where it lives, no judgement of its parties."""
        path = str(getattr(r, "path", "") or "")
        source = str(getattr(r, "source", "") or "")
        parts = path.split("/")
        if parts[:3] == ["Wikis", "Meetings", "wiki"]:
            kind, zn = "meetings", None
        elif parts[:3] == ["Wikis", "Knowledge", "wiki"]:
            kind, zn = "library", None
        elif len(parts) >= 4 and parts[0] == "Zones" and parts[2] != "Todo.md" and not parts[2].startswith("."):
            kind, zn = "threads", parts[1]
        else:
            return None                         # raw records, sessions, a zone's Todo list: not records Ask hands out
        proj = parts[2] if kind == "threads" else None
        thread = parts[4] if kind == "threads" and len(parts) > 5 and parts[3] == "Threads" else None
        title = str(getattr(r, "title", "") or "") or Path(path).stem
        return {"path": path, "kind": kind, "zone": zn, "project": proj, "thread": thread, "title": title,
                "date": str(getattr(r, "date", "") or ""), "imported": "", "snippet": str(getattr(r, "snippet", "") or ""),
                "rid": str(getattr(r, "id", "") or ""), "scope": scope.key, "parties": []}

    @staticmethod
    def in_place(d: dict, place) -> bool:
        """A place narrows the notes of its own project or thread; Meetings and Knowledge are read whatever the place."""
        if d["kind"] != "threads" or not (place and place[1]):
            return True
        if d["zone"] != place[0] or d["project"] != place[1]:
            return False
        return not place[2] or d["thread"] in (None, place[2]) or "Sources" in d["path"].split("/")

    def found_by_keyword(self, words, zone, place, kind, order, names, terms, after, limit) -> str:
        """The keyword find, when the index cannot be opened. It cannot open a scope, so its rows are chosen
        against what is held after the search (ask_scope.choose()), as before the index."""
        sc, lib, ctx, _ = self.world()
        recs: List[dict] = []
        for rel in self.keyword(words, zone, place, kind, order, names):
            d = self.describe(rel, terms)
            if d is None or not set(d["parties"]) <= set(ctx.get("parties", {})) or not self.wanted(d, kind, zone, place):
                continue
            if after and (not d["date"] or d["date"] < str(after)):
                continue
            recs.append(d)
        if order == "recent":
            recs.sort(key=lambda d: (d["date"], d["imported"]), reverse=True)
        recs = self.fair(recs, limit, ctx, lib, sc)
        if recs is None:
            return STOPPED
        lines = [self.line(self.hand(d), d, d["text"]) for d in recs]
        self.save()
        head = "%d record%s returned (from %s)." % (len(recs), "" if len(recs) == 1 else "s",
                                                    "Garrick's docs" if kind == "docs" else "a keyword find")
        if len(recs) == limit:
            head += " There may be more: ask for a larger limit, or narrow the words."
        return head + ("" if kind == "docs" else " " + INDEX_DOWN) + ("\n" + "\n".join(lines) if lines else "")

    def read(self, a: dict) -> str:
        rid = a.get("id")
        rec = self.handed.get(rid) if isinstance(rid, str) else None
        if rec is None:
            return NOT_GIVEN
        if rec.get("rid"):
            # A record of the scope index: a lookup of its id in that index. An id the scope does not hold, because the
            # page moved across a wall or is gone, answers as an id that was never given.
            rc = recall_for(self.ws)
            _, lib, ctx, _ = self.world()
            try:
                scope = rc.scope_named(self.ws, ctx, rec["scope"]) if rc is not None else None
                if scope is None:
                    return NOT_GIVEN
                if self.crosses(scope.tags, lib, ctx):
                    self.latch()                # what is held is walled from this scope: nothing is read
                    return STOPPED
                text = rc.read(rec["rid"], project=None, root=self.ws, scope=scope)
            except Exception:
                return NOT_GIVEN
            if text is None:
                return NOT_GIVEN
            d = dict(rec, kind=rec.get("kind") or "threads")
            body = text
            if text.startswith("---"):
                body = sc_body(self, text)
            self.save()
            return "%s\n\n%s" % (self.line(rid, d), inert(body.strip())[:MOST_TEXT])
        d = self.describe(rec["path"])
        if d is None:
            return NOT_GIVEN
        if not self.admit(set(d["parties"]) | set(rec.get("parties") or [])):
            return STOPPED
        self.save()
        return "%s\n\n%s" % (self.line(rid, d), inert(d["body"].strip())[:MOST_TEXT])

    # ------------------------------------------------------------ places, threads, what is owed

    def places(self, a: dict) -> str:
        sc, lib, ctx, names = self.world()
        zone = self.zone
        if a.get("zone"):
            z = next((n for n in names if n.casefold() == str(a["zone"]).strip().casefold()), None)
            if z is None:
                return "No such zone."
            zone = z
        held, listing = self.held(), []
        if not held and not zone:
            return NAME_A_PLACE             # nothing held and no zone to list: the user names the place
        for z in ([zone] if zone else list(names)):
            rows = []
            for pr, r in names.get(z, {}).items():
                parties = set(sc.place_parties(self.ws, z, pr, None, lib))
                if not parties or not parties <= set(ctx.get("parties", {})):
                    continue            # a place no party can be stated for is not named
                if held and not sc.admits(ctx, held, parties, lib):
                    continue            # names of the far side are left out, not refused
                ts = "; ".join(t + ("" if s == "active" else " (%s)" % s) for t, s in r["threads"].items())
                rows.append((parties, "- %s [%s]%s" % (inert(pr), r["status"], " threads: " + inert(ts) if ts else "")))
            if rows:
                listing.append((z, rows))
        listed = {p for _, rows in listing for ps, _ in rows for p in ps}
        if bool(lib.crossings(ctx, listed)):
            return NO_PROJECTS          # the list would span a wall: the words of an empty zone, so the text says nothing
        if listed and not self.admit(listed):      # the names are material: what is listed is held
            return STOPPED
        self.save()
        lines = []
        for z, rows in listing:
            lines.append("%s:" % z)
            lines += [t for _, t in rows]
        return "\n".join(lines) or NO_PROJECTS

    @staticmethod
    def resume(text: str) -> str:
        """The thread note's Resume here block: from its heading to the next heading of the same level."""
        m = re.search(r"(?m)^(#{1,6})\s+(?:Resume here|State of play)\b.*$", text)
        if not m:
            return ""
        level = len(m.group(1))
        rest = text[m.end():]
        end = re.search(r"(?m)^#{1,%d}\s" % level, rest)
        return (m.group(0) + rest[:end.start()] if end else m.group(0) + rest).strip()

    def thread_state(self, a: dict) -> str:
        sc, lib, ctx, names = self.world()
        place, why = self.one_place(str(a.get("place") or ""), names)
        if place is None:
            return why or "Name a project or a thread."
        zone, project, thread = place
        if project is None:
            return "Name a project or a thread, not a zone."
        note = "Zones/%s/%s/Threads/%s/%s.md" % (zone, project, thread, thread) if thread else \
            "Zones/%s/%s/%s.md" % (zone, project, project)
        d = self.describe(note)
        if d is None:
            if not self.admit(set(sc.place_parties(self.ws, zone, project, thread, lib))):
                return STOPPED
            return "That note cannot be read."
        if not self.admit(set(d["parties"])):
            return STOPPED
        rid = self.hand(d)
        self.save()
        block = self.resume(d["body"]) or "(no Resume here block)"
        return "%s\n\n%s" % (self.line(rid, d), inert(block)[:MOST_TEXT])

    def period_end(self, text) -> Tuple[Optional[dt.date], str]:
        if text in (None, ""):
            return None, ""
        today = dt.date.today()
        t = str(text).strip().lower()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", t):
            try:
                return dt.date.fromisoformat(t), ""
            except ValueError:
                return None, "not a date"
        if t == "today":
            return today, ""
        if t == "tomorrow":
            return today + dt.timedelta(days=1), ""
        if t in ("this week", "week"):
            return today + dt.timedelta(days=6 - today.weekday()), ""
        if t in ("this month", "month"):
            nxt = (today.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
            return nxt - dt.timedelta(days=1), ""
        return None, "period is a date (YYYY-MM-DD), today, tomorrow, this week or this month"

    def zone_parties(self, zone: str, names, ctx: dict, sc, lib) -> Optional[set]:
        """Every party of a zone's projects, or None when a wall stands between any two of them (an unplaceable
        project counts as one)."""
        every = set()
        for pr in names.get(zone, {}):
            ps = set(sc.place_parties(self.ws, zone, pr, None, lib))
            if not ps or not ps <= set(ctx.get("parties", {})):
                return None
            every |= ps
        return None if bool(lib.crossings(ctx, every)) else every

    @staticmethod
    def surnamed(text: str, ctx: dict) -> set:
        """The parties of the people a line names by surname alone: the last word of a name the People table holds,
        written with a capital. A surname two people share names both parties."""
        out = set()
        for person in ctx.get("people", []):
            words = str(person.get("name") or "").split()
            if len(words) > 1 and person.get("party") and len(words[-1]) >= 3 \
                    and re.search(r"(?<!\w)%s(?!\w)" % re.escape(words[-1]), text):
                out.add(person["party"])
        return out

    def owed(self, a: dict) -> str:
        sc, lib, ctx, names = self.world()
        until, bad = self.period_end(a.get("period"))
        if bad:
            return "Give the period as a date, YYYY-MM-DD, or: today, tomorrow, this week, this month."
        tags: set = set()
        if a.get("party"):
            want = " ".join(str(a["party"]).split()).casefold()
            tags = {t for t, row in ctx.get("parties", {}).items()
                    if want in (t.casefold(), str(row.get("party") or "").casefold())}
            if not tags:
                return "No such party."
            if not self.admit(tags):             # a party from the far side goes through the same test
                return STOPPED
        zone = self.zone
        scope = sc.Scope("actions", zone, None, None, [], tags, every=zone is None and not tags,
                         until=until.isoformat() if until else None, waiting=bool(a.get("waiting")))
        found = sc.actions(self.ws, scope, names, ctx, lib, dt.date.today())[:MOST_OWED]
        known = set(ctx.get("parties", {}))
        for i in found:
            i["parties"] = sorted(set(i["parties"]) | self.surnamed(i["text"], ctx))
        found = [i for i in found if set(i["parties"]) <= known]
        # A line that names no party is material of its zone, and it passes every wall test by itself. It is served
        # only in a zone with no wall inside it and a conversation that holds nothing yet, and it counts as every
        # party of its zone, so what the conversation holds afterwards is walled against all of them.
        held = self.held()
        kept = []
        for i in found:
            if i["parties"]:
                kept.append(i)
                continue
            zp = None if held else self.zone_parties(i["zone"], names, ctx, sc, lib)
            if zp is not None:
                kept.append(dict(i, parties=sorted(zp)))
        found = kept
        found = self.fair(found, MOST_OWED, ctx, lib, sc)
        if found is None:
            return STOPPED
        lines = []
        for it in found:
            where = " / ".join(x for x in (it["zone"], it["project"], it["thread"]) if x)
            rid = self.hand({"path": it["note"], "title": it["thread"] or it["project"] or "%s Todo list" % it["zone"],
                             "date": it["date"], "imported": "", "parties": it["parties"]})
            lines.append("[%s] %s%s (%s, %s)" % (rid, tidy(it["text"], 200), " — " + it["date"] if it["date"] else "",
                                                 where, it["kind"]))
        self.save()
        return ("%d item%s." % (len(lines), "" if len(lines) == 1 else "s")) + ("\n" + "\n".join(lines) if lines else "")

    # ------------------------------------------------------------ proposals

    def propose(self, a: dict) -> str:
        act = a.get("action") if isinstance(a.get("action"), dict) else None
        if act is None:
            return "propose takes an action: an object with a verb."
        if act.get("verb") not in PROPOSED:
            return "Not something the box does: %r. It proposes %s." % (act.get("verb"), ", ".join(PROPOSED))
        sc, lib, ctx, names = self.world()
        ask = ask_mod()
        zn, pj = act.get("zone"), act.get("project")
        if isinstance(zn, str) and isinstance(pj, str) and pj in names.get(zn, {}):
            # Before anything else about the place is said: a project on the far side of a wall looks like one that
            # is not there, whatever else the action gets wrong (its thread, its app).
            if not sc.admits(ctx, self.held(), set(sc.place_parties(self.ws, zn, pj, None, lib)), lib):
                self.held_back += 1
                self.save()
                return "Refused: no project %r in %s." % (pj, zn)
        try:
            ask.proposal(act, names, self.ws)
        except ask.Bad as e:
            return "Refused: %s." % e
        if act.get("project"):
            parties = sc.place_parties(self.ws, act["zone"], act["project"], act.get("thread"), lib)
            if not sc.admits(ctx, self.held(), set(parties), lib):
                # A place on the far side of a wall looks like one that is not there: the same words as proposal() uses.
                self.held_back += 1
                self.save()
                return "Refused: no project %r in %s." % (act["project"], act["zone"])
            if not self.admit(set(parties)):
                return STOPPED
        elif act.get("verb") == "todo-add":
            # A Todo line with no project is the zone's own: no party to test. Only the window's zone, and only
            # while the conversation holds no party.
            if self.zone and act.get("zone") != self.zone:
                return "Refused: a Todo line goes in the window's zone, %s, or in a project." % self.zone
            if self.held():
                return "Refused: name the project the Todo line is for."
            if len(str(act.get("text") or "")) > MOST_TODO:
                return "Refused: a Todo line of at most %d characters." % MOST_TODO
        self.proposed += 1
        with (self.dir / "proposals.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"n": self.proposed, "action": act}, ensure_ascii=False) + "\n")
        self.save()
        return "Proposed. Nothing has been done: the user decides, and Garrick checks the action first."

    # ------------------------------------------------------------ calls

    def call(self, name: str, args: dict) -> Tuple[str, bool]:
        """(the text, whether it is an error). Every tool answers STOPPED once the latch is set."""
        self.refresh()
        self._world = None
        if self.wall:
            return STOPPED, True
        if name in ("search", "read", "places", "thread_state", "owed"):
            # Any text out of the workspace, names included, whatever the call finds: from here a proposal is only
            # ever a button, never run by itself (#358).
            self.text_seen = True
            self.save()
        fn = {"search": self.search, "read": self.read, "places": self.places, "thread_state": self.thread_state,
              "owed": self.owed, "propose": self.propose}.get(name)
        if fn is None:
            raise KeyError(name)
        try:
            text = fn(args if isinstance(args, dict) else {})
        except Exception as e:           # nothing of the fault's text: it could name a path on the far side
            self.save()
            return "That did not work (%s)." % type(e).__name__, True
        return text, text == STOPPED


def schemas() -> List[dict]:
    def obj(props, required=()):
        return {"type": "object", "properties": props, "required": list(required)}
    s = {"type": "string"}
    return [
        {"name": "search", "description": "Look for records: meetings, the library, threads (their notes and documents) and Garrick's docs. "
                                          "Returns ids, dates and titles with a snippet. Searches the window's zone first; name another zone or a project in `place` to reach it.",
         "inputSchema": obj({"words": dict(s, description="the words to look for"),
                             "place": dict(s, description="a zone, a project, or a thread: Work, Acme Review, Acme Review/Pricing"),
                             "kind": {"type": "string", "enum": list(KINDS)},
                             "order": {"type": "string", "enum": list(ORDERS)},
                             "limit": {"type": "integer"}, "after": dict(s, description="YYYY-MM-DD")}, ["words"])},
        {"name": "read", "description": "The text of a record, by an id that search, thread_state or owed returned in this conversation.",
         "inputSchema": obj({"id": s}, ["id"])},
        {"name": "places", "description": "The projects and threads, with their status.",
         "inputSchema": obj({"zone": s})},
        {"name": "thread_state", "description": "A thread's or a project's Resume here block: where it stands, the next action, who it waits on.",
         "inputSchema": obj({"place": s}, ["place"])},
        {"name": "owed", "description": "What the user owes or waits on: the Todo lines and the threads' next actions, as Garrick builds the list.",
         "inputSchema": obj({"period": dict(s, description="a date YYYY-MM-DD, today, tomorrow, this week or this month"),
                             "party": s, "waiting": {"type": "boolean"}})},
        {"name": "propose", "description": "Propose an action: open, park or wake a project or thread, or add a Todo line. It is a proposal: "
                                            "nothing happens until Garrick has checked it and, where needed, the user has clicked it.",
         "inputSchema": obj({"action": {"type": "object", "properties": {
             "verb": {"type": "string", "enum": list(PROPOSED)}, "zone": s, "project": s, "thread": s,
             "text": s, "date": s, "app": s, "again": {"type": "boolean"}}, "required": ["verb", "zone"]}}, ["action"])},
    ]


def handle(conv: Conversation, msg: dict) -> Optional[dict]:
    """One JSON-RPC message: the reply, or None for a notification."""
    mid, method = msg.get("id"), msg.get("method")
    params = msg.get("params") if isinstance(msg.get("params"), dict) else {}

    def ok(result):
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def err(code, message):
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}
    if mid is None:
        return None                      # a notification, such as notifications/initialized
    if method == "initialize":
        return ok({"protocolVersion": params.get("protocolVersion") or "2024-11-05",
                   "capabilities": {"tools": {}}, "serverInfo": {"name": SERVER, "version": "1"}})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": schemas()})
    if method == "tools/call":
        name = params.get("name")
        if name not in TOOLS:
            return err(-32602, "unknown tool")
        text, bad = conv.call(name, params.get("arguments") or {})
        return ok({"content": [{"type": "text", "text": text}], "isError": bad})
    return err(-32601, "method not found")


def serve(conv: Conversation, stdin=None, stdout=None) -> None:
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            stdout.write(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}) + "\n")
            stdout.flush()
            continue
        out = handle(conv, msg) if isinstance(msg, dict) else None
        if out is not None:
            stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
            stdout.flush()


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Garrick's read server for the Ask window.")
    ap.add_argument("op", choices=("serve",))
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--state", required=True, help="the folder in.json, out.json and proposals.jsonl live in")
    ap.add_argument("--zone", help="the zone the window answers in")
    args = ap.parse_args(argv)
    serve(Conversation(Path(args.workspace).expanduser().resolve(), Path(args.state), args.zone))
    return 0


if __name__ == "__main__":
    sys.exit(main())
