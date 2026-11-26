"""reads.py: the five read tools, over Ask's own readers.

`places`, `thread_state`, `search`, `read` and `owed` add no reader of their own. Each call runs Ask's read server
(`System/status/ask_tools.py` of the workspace) as a child process of its own, as the Ask window starts it, with the
grant's reach as the scope. It is a child, not an import, because ask.py loads page_action.py when it is imported,
and the service never holds that module (the writes run as processes of their own, too):

* A reach of several zones is asked one zone at a time and the answers are joined. One scope is never widened, and
  one conversation never holds two walled zones, which is the rule Ask keeps.
* A zone, project, thread or record id in a request is checked against the Session first, and the check fails
  closed. A walled zone named outright outside the reach gets `new_context_required`. A project, thread or id
  outside the reach gets the words Ask uses for a place that is not there, and nothing about it changes any count.
* `note-read` and Ask's `propose` are not here.
* Each answer carries a handle that the Session mints, and each request that carries one is checked.

Ask's limits stay Ask's: the length of a record part, of a snippet and of the Todo list. Standard library only.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from . import common

sys.dont_write_bytecode = True

KNOWLEDGE, DOCS = "Knowledge", "docs"
NOT_ZONES = (KNOWLEDGE, DOCS)
MOST_SEARCH, MOST_OWED = 50, 40
_LOCKS: dict = {}
_LOCKS_GUARD = threading.Lock()
# The words of Ask's read server, which a test holds to extras/status/ask_tools.py.
STOPPED = "This conversation has been stopped. Do not answer. Reply with the single word: stopped."
NO_PROJECTS = "No projects."
INDEX_DOWN = "The search index was not available, so this is a plain keyword find."
LIMIT = 10
CALL_TIMEOUT = 120
ENV_KEPT = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "USER", "GARRICK_JOBS_DIR")


def read_server(workspace) -> Path:
    path = Path(workspace) / "System" / "status" / "ask_tools.py"
    if not path.is_file():
        raise FileNotFoundError("the workspace has no Ask read server")
    return path


def python_for_tools() -> str:
    """The Python the Ask window runs the read server with: the one macOS ships, else this one."""
    return "/usr/bin/python3" if os.access("/usr/bin/python3", os.X_OK) else sys.executable


def _lock_for(folder: Path) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(str(folder), threading.Lock())


def zone_tag(zone: str) -> str:
    """The name of a zone in an id and in a folder: 12 hex characters, so that two zones never share one."""
    return common.short(zone)


class Reads:
    """The read tools for one call: a Session and the folder the service keeps Ask's per-zone state in."""

    def __init__(self, session, state=None):
        self.session = session
        self.ws = Path(session.workspace)
        self.state = Path(state) if state else common.state_root()
        self.script = read_server(self.ws)
        self._names = None
        self.clear_old_reaches()

    # ------------------------------------------------------------ the reach

    def reach_zones(self) -> list:
        """The zones of the grant's reach that exist in the workspace, sorted. Zones the grant lists and the workspace lacks are dropped."""
        known = self.all_zones()
        zones = sorted(z for z in known if z not in NOT_ZONES and self.session.zone_allowed(z, False))
        if len({zone_tag(z) for z in zones}) != len(zones):
            raise RuntimeError("two zones of the reach have one tag")      # fails closed: nothing is answered
        return zones

    def reach_name(self) -> str:
        """A name that changes when the grant's reach does: the classes and the two zone sets."""
        body = [sorted(self.session.classes), sorted(z.casefold() for z in self.session.readable),
                sorted(z.casefold() for z in self.session.writable)]
        return common.short(json.dumps(body))

    def grant_folder(self) -> Path:
        return common.private_dir(common.private_dir(self.state / "reads") / common.short(self.session.grant_id))

    def clear_old_reaches(self) -> None:
        """The ids Ask handed out under an earlier reach go with it: only the folder of the present reach is kept."""
        here = self.reach_name()
        for child in self.grant_folder().iterdir():
            if child.name != here:
                shutil.rmtree(str(child), ignore_errors=True)

    def folder(self, zone: str) -> Path:
        """The state of one grant, one reach and one zone: out.json holds the ids Ask handed out to this grant for this zone."""
        return common.private_dir(common.private_dir(self.grant_folder() / self.reach_name()) / zone_tag(zone))

    def all_zones(self) -> list:
        """Every zone the workspace has, by name. Zone names are not secret."""
        if self._names is None:
            zones = [p.name for p in sorted((self.ws / "Zones").iterdir()) if p.is_dir() and not p.name.startswith(".")] \
                if (self.ws / "Zones").is_dir() else []
            self._names = zones
        return self._names

    def zone_named(self, text):
        """The canonical zone a word names, or None. Compared as Ask compares, ignoring case and spacing."""
        want = common.clean_zone_name(text).casefold()
        return next((z for z in self.all_zones() if z.casefold() == want), None)

    def conv_call(self, zone: str, name: str, args: dict):
        """One Ask tool in one zone's read server: (the text, whether Ask called it a failure). The server is a child
        of its own for this call, started on the grant's state for that zone, so that an id it handed out earlier can
        be read now. A server that Ask latched is cleared, and the call answers as nothing found: one odd record never
        shuts a zone for the grant."""
        folder = self.folder(zone)
        lines = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
                 {"jsonrpc": "2.0", "method": "notifications/initialized"},
                 {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": name, "arguments": args}}]
        env = {k: os.environ[k] for k in ENV_KEPT if k in os.environ}
        with _lock_for(folder):
            try:
                done = subprocess.run([python_for_tools(), "-B", str(self.script), "serve", "--workspace", str(self.ws),
                                       "--state", str(folder), "--zone", zone],
                                      input="\n".join(json.dumps(m) for m in lines) + "\n", capture_output=True, text=True,
                                      timeout=CALL_TIMEOUT, cwd=str(folder), env=env)
                got = {}
                for line in done.stdout.splitlines():
                    try:
                        msg = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(msg, dict) and msg.get("id") == 2:
                        got = msg
                result = got.get("result") or {}
                text = str((result.get("content") or [{}])[0].get("text") or "")
                bad = bool(result.get("isError")) or "error" in got
            except (OSError, subprocess.SubprocessError, ValueError, IndexError, AttributeError):
                return "That did not work.", True
            if not text:
                return "That did not work.", True
            if text == STOPPED:
                shutil.rmtree(str(folder), ignore_errors=True)
                return "Nothing was found.", False
            return text, bad

    # ------------------------------------------------------------ places named in a request

    def projects(self, zone: str) -> list:
        """[(project, [threads])] of one zone, read from Ask's own `places` answer for that zone."""
        text, bad = self.conv_call(zone, "places", {"zone": zone})
        out = []
        for line in text.splitlines():
            m = re.match(r"^- (.+) \[([^\]]*)\](?: threads: (.*))?$", line)
            if not m:
                continue
            threads = []
            for t in (m.group(3) or "").split("; "):
                t = re.sub(r" \((?:parked|done|[a-z-]+)\)$", "", t.strip())
                if t:
                    threads.append(t)
            out.append((m.group(1), threads))
        return out

    def find_place(self, place):
        """(zone, the full name of the place, "") for the one place in the reach that a name stands for, else
        (None, None, a refusal dict, or the words for a place that is not there). A walled zone named outright
        outside the reach is `new_context_required`. A project or a thread outside the reach is a place that is not
        there, whatever the zone: only the zones of the reach are ever asked."""
        bits = [b.strip() for b in str(place or "").split("/") if b.strip()]
        if not bits:
            return None, None, "Name a zone, a project or a thread, such as Work, Acme Review or Acme Review/Pricing."
        if len(bits) > 3:
            return None, None, common.NOT_THERE
        low = lambda t: " ".join(str(t).split()).casefold()
        first = self.zone_named(bits[0])
        if first is not None and not self.session.zone_allowed(first, False):
            return None, None, common.reach_refusal()
        found = set()
        for z in self.reach_zones():
            rows = self.projects(z)
            if len(bits) == 3:
                if low(bits[0]) == low(z):
                    found |= {(z, p, t) for p, ts in rows if low(p) == low(bits[1]) for t in ts if low(t) == low(bits[2])}
            elif len(bits) == 2:
                if low(bits[0]) == low(z):
                    found |= {(z, p, None) for p, _ in rows if low(p) == low(bits[1])}
                found |= {(z, p, t) for p, ts in rows if low(p) == low(bits[0]) for t in ts if low(t) == low(bits[1])}
            else:
                if low(bits[0]) == low(z):
                    found.add((z, None, None))
                for p, ts in rows:
                    if low(p) == low(bits[0]):
                        found.add((z, p, None))
                    found |= {(z, p, t) for t in ts if low(t) == low(bits[0])}
        if not found:
            return None, None, common.NOT_THERE
        found = sorted(found, key=lambda f: tuple(str(x) for x in f))
        if len(found) > 1:
            return None, None, "More than one place has that name: %s. Say it as Zone/Project/Thread." % "; ".join(
                "/".join(x for x in f if x) for f in found[:6])
        zone, project, thread = found[0]
        return zone, "/".join(x for x in (zone, project, thread) if x), ""

    # ------------------------------------------------------------ the five

    def places(self, zone=None):
        if zone:
            z = self.zone_named(zone)
            if z is None:
                return {"text": common.NO_ZONE}
            if z in NOT_ZONES or not self.session.zone_allowed(z, False):
                return common.reach_refusal()
            zones = [z]
        else:
            zones = self.reach_zones()
        parts = []
        for z in zones:
            text, _ = self.conv_call(z, "places", {"zone": z})
            if text and text != NO_PROJECTS:
                parts.append(text)
        return {"text": "\n".join(parts) or NO_PROJECTS}

    def thread_state(self, place, offset=None):
        zone, full, why = self.find_place(place)
        if zone is None:
            return why if isinstance(why, dict) else {"text": why}
        args = {"place": full}
        if offset is not None:
            args["offset"] = offset
        text, bad = self.conv_call(zone, "thread_state", args)
        return {"text": self.tag_ids(zone, text)}

    def kinds(self, kind):
        """The kinds a search may take, by what the grant may read: Knowledge and Garrick's docs only when the reach holds them."""
        every = ["meetings", "threads"] + (["library"] if KNOWLEDGE in self.session.readable else []) \
            + (["docs"] if DOCS in self.session.readable else [])
        if kind in (None, "", "all"):
            return None if len(every) == 4 else every
        if kind == "library" and KNOWLEDGE not in self.session.readable:
            return []
        if kind == "docs" and DOCS not in self.session.readable:
            return []
        return [kind]

    def search(self, words, place=None, kind="all", order=None, limit=None, after=None, raw=None):
        args = {"words": words}
        for k, v in (("kind", kind), ("order", order), ("limit", limit), ("after", after), ("raw", raw)):
            if v not in (None, ""):
                args[k] = v
        zones = self.reach_zones()
        if place:
            zone, full, why = self.find_place(place)
            if zone is None:
                return why if isinstance(why, dict) else {"text": why}
            zones, args["place"] = [zone], full
        want = self.kinds(args.get("kind"))
        if want == []:
            return {"text": "0 records returned."}
        try:
            most = max(1, min(MOST_SEARCH, int(limit or LIMIT)))
        except (TypeError, ValueError):
            most = LIMIT
        blocks, notes, seen = [], [], set()
        for z in zones:
            for k in ([None] if want is None else want):
                a = dict(args)
                if k is not None:
                    a["kind"] = k
                text, bad = self.conv_call(z, "search", a)
                if not re.match(r"\d+ records? returned", text):
                    notes.append(text)                  # a refusal of Ask's own words: say it once
                    continue
                if INDEX_DOWN in text:
                    notes.append(INDEX_DOWN)
                for block in self.blocks(text):
                    key = re.sub(r"^\[[^\]]*\]\s*", "", block[0])
                    if key not in seen:
                        seen.add(key)
                        blocks.append((z, block))
        picked = self.interleave(blocks)[:most]
        head = "%d record%s returned." % (len(picked), "" if len(picked) == 1 else "s")
        if len(picked) == most:
            head += " There may be more: ask for a larger limit, or narrow the words."
        if not picked and notes:
            return {"text": notes[0]}
        lines = []
        for z, block in picked:
            lines += [self.tag_ids(z, block[0])] + block[1:]
        extra = " " + INDEX_DOWN if INDEX_DOWN in notes else ""
        return {"text": head + extra + ("\n" + "\n".join(lines) if lines else "")}

    def read(self, id, offset=None):
        tag, _, rid = str(id or "").partition("~")
        zone = next((z for z in self.reach_zones() if zone_tag(z) == tag), None)
        if zone is None or not rid:
            return {"text": common.NOT_GIVEN}
        args = {"id": rid}
        if offset is not None:
            args["offset"] = offset
        text, _ = self.conv_call(zone, "read", args)
        return {"text": self.tag_ids(zone, text)}

    def owed(self, period=None, party=None, waiting=None):
        args = {}
        if period:
            args["period"] = period
        if party:
            args["party"] = party
        if waiting:
            args["waiting"] = True
        lines, total, words = [], 0, None
        for z in self.reach_zones():
            text, bad = self.conv_call(z, "owed", args)
            m = re.match(r"(\d+) items?\.", text)
            if not m:
                words = words or text
                continue
            total += int(m.group(1))
            lines += [self.tag_ids(z, ln) for ln in text.splitlines()[1:]]
        if total == 0 and words:
            return {"text": words}
        lines = lines[:MOST_OWED]
        return {"text": ("%d item%s." % (len(lines), "" if len(lines) == 1 else "s")) + ("\n" + "\n".join(lines) if lines else "")}

    # ------------------------------------------------------------ small helpers

    @staticmethod
    def blocks(text: str) -> list:
        """The records of an Ask answer: each a head line and its indented lines."""
        out = []
        for line in text.splitlines()[1:]:
            if line.startswith("["):
                out.append([line])
            elif out and line.startswith("    "):
                out[-1].append(line)
        return out

    @staticmethod
    def interleave(blocks: list) -> list:
        """One record from each zone in turn, so that no zone's ranking crowds out another's."""
        groups: dict = {}
        for z, b in blocks:
            groups.setdefault(z, []).append((z, b))
        out = []
        while any(groups.values()):
            for z in sorted(groups):
                if groups[z]:
                    out.append(groups[z].pop(0))
        return out

    @staticmethod
    def tag_ids(zone: str, text: str) -> str:
        """An Ask id `[r3-ab12]` as `[<zone tag>~r3-ab12]`, so that read() knows which zone's conversation handed it out."""
        return re.sub(r"(?m)^\[(r\d+-[0-9a-f]+)\]", lambda m: "[%s~%s]" % (zone_tag(zone), m.group(1)), text)
