#!/usr/bin/env python3
"""your_work.py: what the simple home and its actions share about the user's own work (#182).

The simple home's *Add your own work* points Garrick at a folder the user
already keeps, reads only its names and dates (System/tools/discover.py), and
proposes the pieces of work in it. A yes makes Garrick's record of one: a
project with one thread whose hub's `folder:` names the folder. *Start with
this one* reads that work's files for the first time and writes a first look.
*Stop using this* puts Garrick's record away; *Bring it back* returns it. The
folder itself is never written, by Garrick or by Claude.

status.py, which draws the page, and page_action.py, which does what its
buttons ask, both read what is here, so the two never disagree on a name, an
id or a rule:

- where a yes can go: the zones and parties a new piece of work may join
  (places()), the only one when there is one, and a one-line question when
  there are several;
- the id of a looked-at folder's view on the page (view_id());
- the first look: the instruction the read-only call is given
  (FIRST_LOOK_BRIEF, first_look_prompt()), and what of its answer is used
  (parse_first_look());
- the machine state of a first look, System/generated/first-look.json, never
  committed: the suggested request drawn from it, until Continue has asked it;
- the read-only rule for Claude: Edit denied on the folder, in the Claude
  settings of the folder each session on the work starts in, and given with
  `--settings` to every headless call (read_only(), settings_arg()). It
  covers Claude's file-editing tools, not a shell command the user approves;
- the pieces of work put away, under each zone's `archive/` (put_away()).

Standard library only, Python 3.9 or later.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

DISCOVERY = ("System", "generated", "discovery.json")
FIRST_LOOKS = ("System", "generated", "first-look.json")
EXTRACTS = ("System", "generated", "extracts")
CLAUDE_SETTINGS = (".claude", "settings.json")
ARCHIVE = "archive"
PUT_AWAY = "put-away"         # the hub's frontmatter key, with the day it was put away
FIRST_LOOK = "first-look"     # the thread note's, with the day its first look was made
DISCOVERED = "discovered"     # the hub's, with the id discover.py gave the proposal
OWN = "Change it"             # the answer to the first look's question given in the user's own words
RIGHT = "That's right"
EXAMPLE_MANIFEST = ".example.json"
FIELD_MAX = 400               # of any one field of a first look

# How the first look is to come back. The call only reads (handoff.READ_ONLY),
# so it cannot write the record itself: it answers in JSON, and Garrick writes
# the record from that, through the zone's wall check.
FIRST_LOOK_BRIEF = (
    "You are making Garrick's first record of a piece of work, from its own files, for someone who is not technical. "
    "Read the files; change nothing. Answer with one JSON object and nothing else, with these keys, each a string: "
    "\"what\", one sentence on what the work is; \"who\", who is involved, each name with their part in a few words, "
    "or \"\"; \"last\", what happened last and when, in one or two sentences; \"open\", what is still open, in one or two "
    "sentences; \"next\", the single next step for the user, small enough to start in two minutes; \"source\", where "
    "that next step comes from, named as a person would, such as \"the proof review call on 14 October\"; \"waiting\", "
    "who the work waits on, or \"nobody\"; \"deadline\", the nearest date that matters and what it is for, or "
    "\"not given\"; \"request\", one request the user could ask you to carry out now, drawn from the next step, in the "
    "user's own voice. Plain words: no file paths, no tables, no commands, nothing about tools.")
KEYS = ("what", "who", "last", "open", "next", "source", "waiting", "deadline", "request")
NEEDED = ("what", "next")


# --------------------------------------------------------------------------- small helpers

def read_json(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_json(path: Path, data: dict) -> None:
    """Written beside the file and renamed over it, so a reader sees one whole file or the other."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + path.stem + "-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True) + "\n")
        os.replace(tmp, str(path))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def view_id(real: str) -> str:
    """The page's id for the view of one looked-at folder: the same from status.py and page_action.py."""
    return "sd-" + hashlib.sha1(os.path.realpath(str(real)).encode("utf-8")).hexdigest()[:10]


def work_id(name: str, key: str) -> str:
    """The page's id for a piece of work's own page, from the name the home
    gives it and its note's key, "<Zone>/<note from the zone>"."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40]
    return "pw-%s-%s" % (slug, hashlib.sha1(key.encode("utf-8")).hexdigest()[:6])


def discovery(ws: Path) -> dict:
    """discover.py's state, {"folders": {real path: entry}}; empty when there is none."""
    data = read_json(Path(ws).joinpath(*DISCOVERY))
    return data if isinstance(data.get("folders"), dict) else {"folders": {}}


def said_folder(path: str) -> str:
    """A folder as the page names it: its name and the folder it is in, never a path."""
    p = Path(path)
    return "%s, in %s" % (p.name, p.parent.name) if p.parent.name else p.name


def folder_value(path: str) -> str:
    """A folder as a hub's `folder:` keeps it: from `~/` when it is under the home folder."""
    real = os.path.realpath(path)
    home = os.path.realpath(os.path.expanduser("~"))
    return "~/" + os.path.relpath(real, home) if real.startswith(home + os.sep) else real


# --------------------------------------------------------------------------- where a yes goes

def example_zone(ws: Path) -> Optional[str]:
    """The zone the worked example is in, read as status.py's example_zone() does."""
    zones = Path(ws) / "Zones"
    for zone in sorted(zones.iterdir()) if zones.is_dir() else []:
        data = read_json(zone / EXAMPLE_MANIFEST) if zone.is_dir() else {}
        if data.get("zone") == zone.name:
            return zone.name
    return None


def places(ws: Path, ctx: dict) -> List[dict]:
    """Where a new piece of work may go: one entry for each zone and party,
    {"zone", "party", "label"}. Every zone of the user's, never the example's,
    with the parties System/context.md puts in it; a zone with one party is
    named alone, one with several once for each, "Work (Acme Corp)". A zone
    with no party cannot hold a project, so it is not offered."""
    zones = Path(ws) / "Zones"
    example = example_zone(ws)
    out = []
    for zone in sorted(zones.iterdir()) if zones.is_dir() else []:
        if not zone.is_dir() or zone.name.startswith((".", "_")) or zone.name == example:
            continue
        parties = [(tag, p) for tag, p in sorted((ctx.get("parties") or {}).items())
                   if str(p.get("zone") or "").strip().casefold() == zone.name.casefold()]
        for tag, p in parties:
            label = zone.name if len(parties) == 1 else "%s (%s)" % (zone.name, p.get("party") or tag)
            out.append({"zone": zone.name, "party": tag, "label": label})
    return out


def which_place(options: List[dict]) -> str:
    """The one-line question that asks where a piece of work goes."""
    names = [o["label"] for o in options]
    listed = ", ".join(names[:-1]) + " or " + names[-1] if len(names) > 1 else "".join(names)
    return "Which part of your workspace is this work for: %s?" % listed


# --------------------------------------------------------------------------- the first look

def first_look_prompt(name: str, folder: str, extracts: Optional[str], members: Optional[List[str]] = None) -> str:
    """What the read-only call is asked: the work, where its files are, and where the text of its Office files is."""
    said = ["Make Garrick's first record of %s. Its files are in %s; read them where they are." % (name, folder)]
    if members:
        shown = members[:60]
        said.append("Only these files of that folder belong to it: %s%s." % (
            "; ".join(shown), " and %d more" % (len(members) - len(shown)) if len(members) > len(shown) else ""))
    if extracts:
        said.append("The text of its Word, PowerPoint and Excel files is in %s, one .txt file beside each." % extracts)
    said.append("Answer with the JSON object only.")
    return " ".join(said)


def one_line(value) -> str:
    """A field of a first look as the record can hold it: one line, no table bars, at most FIELD_MAX characters."""
    text = " ".join(str(value or "").split()).replace("|", "/")
    return text[:FIELD_MAX].rstrip() if len(text) > FIELD_MAX else text


def parse_first_look(answer: str) -> Optional[Dict[str, str]]:
    """The first look from the call's answer: its JSON object, the first one in
    it, fenced or not. None when there is none, or it lacks what it is for: what
    the work is and its next step."""
    text = answer or ""
    for start in [m.start() for m in re.finditer(r"\{", text)]:
        try:
            data, _ = json.JSONDecoder().raw_decode(text[start:])
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        look = {k: one_line(data.get(k)) for k in KEYS}
        if all(look[k] for k in NEEDED):
            look["waiting"] = look["waiting"] or "nobody"
            look["deadline"] = look["deadline"] or "not given"
            return look
        return None
    return None


def first_looks(ws: Path) -> dict:
    """{note key: {"request", "question", "made", "used"}}: each first look's suggested request, kept on this Mac."""
    data = read_json(Path(ws).joinpath(*FIRST_LOOKS))
    return data if isinstance(data, dict) else {}


def keep_first_look(ws: Path, key: str, **values) -> None:
    data = first_looks(ws)
    entry = data.get(key) if isinstance(data.get(key), dict) else {}
    entry.update(values)
    data[key] = entry
    write_json(Path(ws).joinpath(*FIRST_LOOKS), data)


# --------------------------------------------------------------------------- read-only for Claude

def read_only_rules(folder: str) -> List[str]:
    """The deny rule that keeps Claude's file-editing tools out of `folder`.
    Claude Code matches one kind of rule for this, Edit, which covers every
    tool that edits or writes a file; it does not match Write rules. An
    absolute path in a permission rule starts with `//`. A shell command the
    user approves is not a file-editing tool, and no rule here covers it."""
    real = os.path.realpath(str(folder)).rstrip("/")
    return ["Edit(/%s/**)" % real]


def settings_arg(folder: str) -> str:
    """The same rule as the JSON `--settings` takes, for a headless call: a
    second guard beside the settings file."""
    return json.dumps({"permissions": {"deny": read_only_rules(folder)}}, ensure_ascii=False)


def read_only(session: Path, folder: str) -> Optional[bytes]:
    """The Claude settings of the folder a session starts in, `session`, with
    Edit denied in `folder`. Claude Code reads a project's settings only from
    the session's own working folder, never from a folder above it, so the
    rule sits there: for a piece of work that is one thread, the project's
    own folder, which is committed with the project and moves with it.
    Everything already in the file stays. Returns the bytes the file held
    before, None for a file that was not there, or False when it already said
    it. Refuses with ValueError a file that is not JSON Garrick can add to."""
    path = Path(session).joinpath(*CLAUDE_SETTINGS)
    try:
        before = path.read_bytes()
    except FileNotFoundError:
        before = None
    try:
        data = json.loads(before.decode("utf-8")) if before and before.strip() else {}
    except ValueError:
        raise ValueError("this work's Claude settings are not JSON Garrick can add to")
    if not isinstance(data, dict):
        raise ValueError("this work's Claude settings are not JSON Garrick can add to")
    perms = data.setdefault("permissions", {})
    if not isinstance(perms, dict):
        raise ValueError("this work's Claude settings have permissions Garrick cannot add to")
    deny = perms.setdefault("deny", [])
    if not isinstance(deny, list):
        raise ValueError("this work's Claude settings have a deny list Garrick cannot add to")
    added = [r for r in read_only_rules(folder) if r not in deny]
    if not added:
        return False
    deny.extend(added)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return before


# --------------------------------------------------------------------------- put away

def front_value(note: Path, key: str) -> str:
    try:
        text = Path(note).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    m = re.match(r"\A---\n(.*?)\n---", text, re.S)
    found = re.search(r"(?m)^%s:[ \t]*(.*?)[ \t]*$" % re.escape(key), m.group(1)) if m else None
    return found.group(1).strip().strip("\"'") if found else ""


def put_away(ws: Path) -> List[dict]:
    """The pieces of work put away by Stop using this, most recent first:
    {"zone", "project", "since"}, from each zone's archive/ folder, where a
    hub says when it was put away."""
    out = []
    zones = Path(ws) / "Zones"
    for zone in sorted(zones.iterdir()) if zones.is_dir() else []:
        box = zone / ARCHIVE
        if not box.is_dir():
            continue
        for p in sorted(box.iterdir()):
            hub = p / (p.name + ".md")
            since = front_value(hub, PUT_AWAY) if p.is_dir() else ""
            if since:
                out.append({"zone": zone.name, "project": p.name, "since": since})
    out.sort(key=lambda w: (w["since"], w["project"]), reverse=True)
    return out


MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")


def today_said(day: dt.date) -> str:
    """A date as said aloud: 19 October 2026."""
    return "%d %s %d" % (day.day, MONTHS[day.month - 1], day.year)
