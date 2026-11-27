#!/usr/bin/env python3
"""Create a zone, a party, a project or a thread in this workspace.

    python3 System/tools/scaffold.py zone "Garden" --holds "The house and the garden" [--open]
    python3 System/tools/scaffold.py zone --name Garden --walled | --open [--yes]
    python3 System/tools/scaffold.py party --name "Acme Corp" --zone Work --what "Supplier" [--check]
    python3 System/tools/scaffold.py project --zone Work --name "Acme" [--party acme] [--thread "Pricing"] [--separate]
    python3 System/tools/scaffold.py thread  --zone Work --project Acme --name "Pricing"
    python3 System/tools/scaffold.py thread  --zone Work --project Acme --name "Pricing" --check
    python3 System/tools/scaffold.py thread  --zone Work --project Acme --name "ISO 27001" --spoken "I S O twenty seven thousand one"
    python3 System/tools/scaffold.py park    --zone Work --project Acme [--thread Pricing]
    python3 System/tools/scaffold.py wake    --zone Work --project Acme [--thread Pricing]
    python3 System/tools/scaffold.py rename  --zone Work --project Acme [--thread Pricing] --to "Renewal"
    python3 System/tools/scaffold.py move    --zone Work --project Acme --thread Pricing --to Birch
    python3 System/tools/scaffold.py layout  --zone Work --project Acme --split [--check]
    python3 System/tools/scaffold.py layout  --zone Work --project Acme --join [--resume-from Pricing] [--check]
    python3 System/tools/scaffold.py delete  --zone Work --project Acme [--thread Pricing] [--confirm Pricing]
    python3 System/tools/scaffold.py undo    --zone Work --commit <the commit it reported>
    echo '{"verb":"checkpoint","zone":"Work","project":"Acme","thread":"Pricing", ...}' \
      | python3 System/tools/scaffold.py checkpoint

A name has to look like a name and store safely as a folder: letters and
digits, spaces, hyphens, apostrophes, `&`, and a full stop inside an acronym.
A name that does not say how it is said ("Q4 Planning") takes `--spoken`, the
form heard for it, which goes in the note as `spoken:` and is matched
alongside the name. Without it the script still makes the thing and asks for
one. A zone has no note, so a zone name must say how it is said.

A zone is made the way the installer makes one: its own folder and git repository
with a first commit, its inbox, the skill links and the wall check, and a row in
System/context.md, which is left for you to commit. A new zone is walled unless it
is made with `--open`. With `--walled` or `--open` on a zone that exists, the command
changes its flag, the one place a wall is set: open to walled writes, runs the
workspace's wall check and lists what now crosses; walled to open says how many files
it releases and writes only with `--yes`. Both are refused, writing nothing, while the
Zones table has no Walled column (the update to zone walls has not been accepted).
A project need not start with a thread: `--thread` is optional. Without `--separate` the
project is one job: its hub holds a `### Resume here` block, and it has `Sources/`
and `Deliverables/` and no `Threads/` until a thread is added. With `--separate` it is
separate jobs: the hub says `layout: thread-first`, holds no resume
point and no `Sources/` or `Deliverables/`, and may stay empty. A new thread in one job
uses the project's papers; in separate jobs it keeps `Sources/` and `Deliverables/` of
its own. The project decides, so a thread is asked nothing about papers, and `thread --papers` is refused. A thread inherits its
project's party, if it has one: `--party` is optional, an index and never a wall. `--check`
applies every refusal and makes nothing, so a form can check a name as it is typed.

`party` adds a row to the Parties table in System/context.md and offers the tag
itself, so nobody has to invent one. The row it adds carries a Learned cell,
`2026-10-16, user`, which says where it came from; the rows typed by hand are left
as they are. A party routes mail (its domains) and holds the names that are heard;
it is not walled, its zone is. It has to run, and its row be committed, before
`project` names it: a project is refused with a tag System/context.md does not
already carry, and that file is in the workspace's own repository while a project
is in the zone's, so the two are separate commits. Running it again for a party
already there changes nothing and says so. `party --check` answers one of two
things and writes nothing: that the party is new and what its tag would be, or that
it is already there, with its tag, its zone and any project whose hub note names
that tag. `--also` adds a second row for an organisation already in Parties, in
another zone: one company under two hats is two parties in two zones.

`park` sets a project or a thread aside and `wake` brings it back: `status:`,
`updated:` today and a dated entry, "Parked." or "Woken.", in the note the
names resolve to. A second park of a thread already set aside is refused,
and so is waking one that is active. Neither commits: the change is left for
you to commit, as a new project's files are, which is how the status page can
put the note back when the zone's wall check refuses the commit. Parking a
project parks every thread in it, whatever each thread's note says.

`rename` moves the folder and its note with git, renames the note's title and
heading, and points every link to it in the zone at the new name: the hub's
list, the Todo.md lines that open with it, `project:` frontmatter, the notes
between. One commit in the zone, with a dated entry "Renamed from <old>."; the
old name becomes a heard alias in names.md (context.md before the move), left for you to commit. The
Meetings wiki is listed, never edited. `move` takes a thread to another
project of its zone, by the same machinery: the folder, every link to it and to
the files inside it, its line in the hub (under the same heading), `project:`
and `parent:`, and its rows in the project's `Deliverables/published.md`, in one
commit that `undo` reverts. It refuses, and writes nothing, for another zone, a
thread of that name already there, a project that is parked or done, and files
of the thread that sit outside its folder. `delete` without `--confirm` only says
what would go; with it, the folder, the hub's line and the open Todo.md lines
naming it go in one commit, which `undo` reverts while it is still the zone's
last commit. Both refuse while what they
would change has changes not committed, or a cmux tab is mid-turn in it.

`layout` switches a whole project between one job and separate jobs. `--split` makes it separate jobs: it gives
each top-level file to the one thread that names it and sets `layout: thread-first`. `--join` makes it one job: it
moves each thread's `Sources/` and `Deliverables/` into the project's, and gives the hub a Resume here block back,
opening with the Next action of the thread named by `--resume-from` (the thread touched last when none is named).
A project that is one job but has a thread holding papers of its own is mended by the same `--join`, which moves those
papers up and changes no note but the links. A file moves only when it can go without a guess: on a split, when exactly
one thread note names it (and no other note of the project does); on a join, when its name is free in the project's
folder. Any other is listed for the owner to place, and a file is never renamed or overwritten. The ledger rows
of a moved file follow it, with their share destination unchanged, and the links to it are pointed at the new
place. `--check` says the plan and writes nothing (`--check --json` gives it as data for the status page); a real run
makes one commit through the zone's wall check, and a refused commit leaves every file and row where it was. Nothing
leaves the project. It is not run on an update: an existing project keeps its layout until the owner asks.

`checkpoint` writes the unconfirmed record of what a session has done into a
thread note, directly under its Resume here block, which it never touches, and
between two markers that are the block's whole extent. Its request is one JSON
object on standard input, because the fields are free text, and its reply is
one JSON object on standard output: what it wrote, or that the same state was
there already, or the name of the refusal and one line saying why. Every item
carries the source its kind needs, items are replaced by id and removed only
by `drop`, and `{"read": true, ...}` writes nothing and answers with what the
note holds. It never writes `Todo.md` and never commits: the wrap does those.

Where the status page is installed, `zone`, `project`, `thread`, `rename`, a
confirmed `delete`, `park`, `wake` and `undo` then start a build of it in the
background, with `--settle 10`, so a run of them makes one page, and with
`--same-flags`, so it keeps the flags the app or the plugin last built it
with. Nothing that only reads or refuses asks for one, nor a request from
the page, whose app builds it after the reply (GARRICK_CALLER_BUILDS_PAGE).

On success prints what it did in lines that can be read aloud; on refusal, one
line saying why, and exits 1. `checkpoint` prints JSON either way.
"""

import argparse
import datetime
import difflib
import hashlib
import json
import os
import re
import posixpath
import shutil
import subprocess
import sys
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True  # keep System/tools free of __pycache__
sys.path.insert(0, str(HERE))

from garrick_lib import (  # noqa: E402
    CALLER_BUILDS_PAGE,
    park_memory_pointer,
    CHECKPOINT_KINDS,
    CHECKPOINT_LABELS,
    CHECKPOINT_ONE,
    CHECKPOINT_STEMS,
    INBOX,
    RESUME_HEADING,
    TAG_RE,
    TAG_RULE,
    ZONE_TEMPLATE,
    GitError,
    checkpoint_item_line,
    detach,
    git,
    wall_hook_problem,
    hooks_path,
    init_repo,
    install_wall_hook,
    is_display_name,
    is_sayable,
    learned_cell,
    learned_row,
    load_context,
    table_files,
    machine_made,
    parse_frontmatter,
    place_checkpoint,
    read_checkpoint,
    record_written,
    render_checkpoint,
    resume_hash,
    said_time,
    same_action,
    skill_links,
    spoken_clash,
    spoken_of,
    tag_list,
    status_command,
    table_row,
    tag_for,
    live_files,
    workspace_root,
    walled as zone_flag,
    zone_of,
    write_if_unchanged,
)


class Refusal(Exception):
    pass


# The rule's own words for a wall that held something back (rules.md, Zones
# and walls); operations.py keeps the same sentence for the status page, and
# this is the one used where that module is not beside this script.
WALL_SENTENCE = "A wall holds some material back from this project, so I have not used it. Nothing was written."


# The verbs that change what the status page shows. After one, the page is
# asked for a build in the background, which waits PAGE_SETTLE seconds for
# another request first, so a run of commands makes one page (#243).
PAGE_VERBS = ("zone", "project", "thread", "rename", "move", "delete", "park", "wake", "undo", "layout")
PAGE_SETTLE = 10


def ask_for_page(root, args):
    """Start a build of the status page, and return without waiting on it, so
    a thread a session made is on the Threads card in seconds instead of at
    the next rebuild. Nothing for a verb that only reads (`--check`, a delete
    not confirmed), nothing where the status extra is not installed, and
    nothing under page_action.py, whose app builds the page after its reply."""
    if args.command not in PAGE_VERBS or getattr(args, "check", False):
        return
    if args.command == "delete" and args.confirm is None:
        return
    if os.environ.get(CALLER_BUILDS_PAGE):
        return
    cmd = status_command(root, settle=PAGE_SETTLE)
    if cmd:
        detach(cmd)


def ph(key):
    """A placeholder, spelled without writing the braces literally in this file."""
    return "{" * 2 + key + "}" * 2


def fill(text, values):
    for key, value in values.items():
        text = text.replace(ph(key), value)
    return text


def copy_filled(src, dst, values):
    """Copy a template folder, filling placeholders in file names and text."""
    dst.mkdir(parents=True)
    fill_into(src, dst, values)


def fill_into(src, dst, values):
    """Copy what a template folder holds into the folder `dst`, filling placeholders."""
    for item in sorted(src.iterdir()):
        if machine_made(item.name + ("/" if item.is_dir() else "")):
            continue
        out = dst / fill(item.name, values)
        if item.is_dir():
            copy_filled(item, out, values)
            continue
        try:
            text = item.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            shutil.copy2(item, out)
            continue
        out.write_text(fill(text, values), encoding="utf-8")


def children(folder):
    if not folder.is_dir():
        return []
    return [p.name for p in folder.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))]


def find_zone(root, zone):
    zones = children(root / "Zones")
    match = [z for z in zones if z.lower() == zone.strip().lower()]
    if not match:
        raise Refusal(f"There is no zone called {zone}. The zones are {', '.join(sorted(zones)) or 'none yet'}.")
    return root / "Zones" / match[0]


def find_child(folder, name, kind):
    match = [c for c in children(folder) if c.lower() == name.strip().lower()]
    if not match:
        raise Refusal(f"There is no {kind} called {name} in {folder.name}.")
    return folder / match[0]


def check_name(name, siblings, kind, where, spoken=None, parent=None, must_be_sayable=False):
    """Apply the three naming questions, and refuse with the one that fails.

    A name has to look like a name (`is_display_name`), and no sibling may be
    the same folder or sound the same, said as written or through its `spoken`
    form. A name that does not say how it is said is good as a name: it needs
    a `spoken` form, which only a zone cannot carry. Every refusal over a
    sibling ends in a question, because which of the two the user meant is
    theirs to answer, not the script's to decide.
    """
    ok, reason = is_display_name(name)
    if not ok:
        raise Refusal(f'"{name}" will not work as a {kind} name: {reason}')
    said, why = is_sayable(name)
    if must_be_sayable and not said:
        raise Refusal(f'"{name}" will not work as a {kind} name: {why}, '
                      f"and a {kind} has no note to carry a spoken form.")
    if spoken:
        ok, reason = is_sayable(spoken)        # which asks the other two first
        if not ok:
            raise Refusal(f'"{spoken}" will not work as the spoken form of {name}: {reason}.')
    for sibling in siblings:
        here = f"{where[:1].upper()}{where[1:]}"
        if sibling == name:
            raise Refusal(f"{here} already has a {kind} called {sibling}. Open it, or pick another name?")
        if sibling.lower() == name.lower():
            raise Refusal(f'{here} already has a {kind} stored as "{sibling}", and "{name}" would be the same '
                          f"folder. Open {sibling}, or pick another name?")
        clash = spoken_clash(name, sibling, spoken, spoken_of(parent / sibling) if parent else None)
        if clash:
            heard = "" if clash == (name, sibling) else f' ("{clash[0]}" and "{clash[1]}")'
            raise Refusal(f"{name} sounds too much like {sibling}{heard}, already in {where}. "
                          f"Open {sibling}, or pick a name that is easy to tell apart?")
    return said


def set_spoken(text, spoken):
    """Put `spoken:` in a note's frontmatter, under `title:`, or take it out."""
    text = re.sub(r"(?m)^spoken:.*\n", "", text, count=1)
    if not spoken:
        return text
    return re.sub(r"(?m)^title: .*$", lambda m: "%s\nspoken: %s" % (m.group(0), spoken), text, count=1)


def say_how(name, kind, spoken):
    """The line that asks for a spoken form, where the name needs one and was
    given none. A question: the form is the user's to choose."""
    if spoken or is_sayable(name)[0]:
        return []
    return [f"{name} does not say how it is said. What should be heard for it, so "
            f'"open {name}" finds the {kind}? It goes in the note as `spoken:`.']


def check_party(root, party, zone=None):
    """The party value for a note, if System/context.md holds every tag in it: one tag, or `[a, b]` for several
    (`a,b` on the command line); an empty value is no party, which a project may have. `party:` is an index of who
    a note is about, never a wall: the wall is the zone. For a new project, `zone` is the project's: a party that the
    table places in another zone is refused, since the index would point at a party of another zone."""
    ctx = load_context(root)
    parties = ctx.get("parties", {})
    tags = [t for t in tag_list([x for x in re.split(r"[,\s]+", str(party or "").strip("[] ")) if x])]
    if not tags:
        return ""
    for tag in tags:
        if tag not in parties:
            known = ", ".join(sorted(parties)) or "none yet"
            raise Refusal(f"{tag} is not a party tag in System/context.md. The tags are {known}.")
        there = parties[tag].get("zone") or ""
        if zone and there and there != zone:
            raise Refusal(f"{parties[tag].get('party') or tag} is a party of {there}, not of {zone}, so a project in {zone} "
                          "cannot be for it.")
    return tags[0] if len(tags) == 1 else "[%s]" % ", ".join(tags)


def drop_empty_party(note):
    """A note made with no party has no `party:` line: the index is optional."""
    if note.is_file():
        text = note.read_text(encoding="utf-8")
        new = re.sub(r"(?m)^party:[ \t]*\n", "", text, count=1)
        if new != text:
            note.write_text(new, encoding="utf-8")


def link_thread_in_hub(hub, thread, today):
    """Add the thread to the hub's Threads list, replacing the placeholder line on first use."""
    lines = hub.read_text(encoding="utf-8").splitlines()
    entry = f"- [[{hub.stem}/Threads/{thread}/{thread}|{thread}]]: <what it produces>"
    start = next((i for i, l in enumerate(lines) if l.strip().lower() == "## threads"), None)
    if start is None:
        lines += ["", "## Threads", "", entry]
    else:
        end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("#")), len(lines))
        placeholder = next((i for i in range(start + 1, end) if ph("THREAD") in lines[i]), None)
        if placeholder is not None:
            lines[placeholder] = fill(lines[placeholder], {"THREAD": thread})
        elif any(f"/Threads/{thread}/{thread}|" in lines[i] for i in range(start + 1, end)):
            pass  # already listed: the project template filled it in
        else:
            items = [i for i in range(start + 1, end) if lines[i].lstrip().startswith("- ")]
            at = items[-1] + 1 if items else start + 1
            if not items:
                lines[at:at] = ["", entry]
            else:
                lines.insert(at, entry)
    text = "\n".join(lines) + "\n"
    text = re.sub(r"(?m)^updated: .*$", f"updated: {today}", text, count=1)
    hub.write_text(text, encoding="utf-8")


PAPERS = ("Sources", "Deliverables")


def is_heading(project_dir):
    """Is the project a heading over separate pieces of work: `layout: thread-first` in its hub?"""
    hub = project_dir / f"{project_dir.name}.md"
    return hub.is_file() and str(parse_frontmatter(hub).get("layout") or "").strip().lower() == "thread-first"


SWITCH_SAID = ("A thread has no papers choice of its own: a project is one job or separate jobs, and every thread follows it. "
               "To change the project, use layout --split or layout --join.")


def refuse_papers(args):
    """A thread's papers follow the project's switch, never a choice of the thread: a request that still names
    one is refused with the sentence that names the switch, never ignored."""
    if getattr(args, "papers", None) is not None:
        raise Refusal(SWITCH_SAID)


def make_thread(root, project_dir, name, party, today, spoken=None, papers=False):
    threads = project_dir / "Threads"
    check_name(name, children(threads), "thread", project_dir.name, spoken=spoken, parent=threads)
    target = threads / name
    if target.exists():
        raise Refusal(f"{target.relative_to(root)} already exists.")
    threads.mkdir(exist_ok=True)
    values = {"ZONE": project_dir.parent.name, "PROJECT": project_dir.name, "THREAD": name,
              "PARTY": party, "DATE": today}
    copy_filled(root / "System" / "templates" / "thread", target, values)
    note = target / f"{name}.md"
    if spoken and note.is_file():
        note.write_text(set_spoken(note.read_text(encoding="utf-8"), spoken), encoding="utf-8")
    if not party:
        drop_empty_party(note)
    if papers:
        for folder in PAPERS:
            (target / folder).mkdir(exist_ok=True)
            (target / folder / ".gitkeep").touch()
    return target


def git_value(args, cwd):
    try:
        return git(args, cwd)
    except (GitError, OSError):
        return ""


def zone_identity(root):
    """The git name and address a new zone commits with: the ones the workspace's own
    repository sets for itself, as the installer does when git has none. When git still
    has neither, the author of the workspace's last commit."""
    keys = ("user.name", "user.email")
    identity = {}
    for key in keys:
        value = git_value(["config", "--local", "--get", key], root)
        if value:
            identity[key] = value
    missing = [k for k in keys if k not in identity and not git_value(["config", "--get", k], root)]
    author = git_value(["log", "-1", "--format=%an%n%ae"], root).splitlines() if missing else []
    if missing and len(author) != 2:
        raise Refusal("git has no name or email to commit the new zone with. Set them in the workspace, "
                      'then try again: git config user.name "Your Name" and git config user.email "you@example.com".')
    identity.update({k: v for k, v in zip(keys, author) if k in missing})
    return identity


def walled_column(header):
    """The index of the Walled column of a table's header line, or None."""
    cells = [h.strip().lower() for h in header.strip().strip("|").split("|")]
    return next((i for i, h in enumerate(cells) if h.startswith("walled")), None)


def zones_table(lines):
    """(start, rows) of the Zones table: the index of its heading and the indexes of its table lines, header first."""
    start = next((i for i, l in enumerate(lines) if l.strip().lower() == "## zones"), None)
    if start is None:
        return None, []
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return start, [i for i in range(start + 1, end) if lines[i].lstrip().startswith("|")]


def list_zone(root, name, holds, walled=True):
    """Add the zone to the Zones table in System/context.md, as the installer would
    have. False when the table already lists it, which is then left as it is. A new zone is walled
    unless it is made open. A table still in the 0.62 shape (Party and New parties columns, no Walled
    column) gets a row in that shape, its New parties cell carrying the flag."""
    if name.lower() in (z.lower() for z in load_context(root)["zones"]):
        return False
    path = root / "System" / "context.md"
    lines = path.read_text(encoding="utf-8").splitlines()
    start, rows = zones_table(lines)
    flag = "yes" if walled else "no"
    if start is None:
        at = next((i for i, l in enumerate(lines) if l.strip().lower() == "## parties"), len(lines))
        block = ["## Zones", "", "| Zone | Holds | Walled |", "|---|---|---|", table_row([name, holds or f"<What {name} holds>", flag]), ""]
        if at == len(lines) and lines and lines[-1].strip():
            block = [""] + block[:-1]
        lines[at:at] = block
    else:
        header = lines[rows[0]] if rows else None
        cells = [name, holds or f"<What {name} holds>"]
        if header is None:
            lines[start + 1:start + 1] = ["", "| Zone | Holds | Walled |", "|---|---|---|", table_row(cells + [flag])]
        else:
            if walled_column(header) is not None:
                cells.append(flag)
            else:
                cells += ["", "walled" if walled else "open"]      # 0.62 shape: no zone party, and the new-parties default
            lines.insert(rows[-1] + 1, table_row(cells))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


def set_zone_flag(root, zone, walled):
    """Write the Walled cell of one zone's row. The commit is the caller's. Refused while the Zones table has no
    Walled column: the zone-walls migration has not run, and a flag written into a table that does not read it
    would decide nothing."""
    path = root / "System" / "context.md"
    lines = path.read_text(encoding="utf-8").splitlines()
    start, rows = zones_table(lines)
    want = walled_column(lines[rows[0]]) if rows else None
    if want is None:
        raise Refusal("The Zones table of System/context.md has no Walled column: the update to zone walls has not been "
                      "accepted yet, so no flag was changed.")
    for i in rows[2:]:
        cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
        if cells and cells[0].lower() == zone.lower() and len(cells) > want:
            cells[want] = "yes" if walled else "no"
            lines[i] = "| " + " | ".join(cells) + " |"
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return
    raise Refusal(f"{zone} is not in the Zones table of System/context.md.")


def files_in_zone(root, zone):
    """How many files belong to a zone today: its own folder's live files, and the Meetings pages and raw records whose
    `zone:` is this one. What making the zone open releases."""
    root = Path(root)
    n = 0
    for folder in (root / "Zones" / zone, root / "Wikis" / "Meetings" / "wiki", root / "Wikis" / "Meetings" / "raw"):
        for path in live_files(folder) if folder.is_dir() else []:
            n += zone_of(root, path) == zone
    return n


def walls_violations(root):
    """The files the whole-workspace walls check refuses now, as paths; None when the check could not run or finish."""
    check = Path(root) / "System" / "tools" / "check.py"
    try:
        run = subprocess.run([sys.executable, str(check), "--root", str(root), "--walls-only", "--json"],
                             capture_output=True, text=True, timeout=600)
        found = json.loads(run.stdout).get("findings", [])
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return sorted({f["path"] for f in found if f.get("severity") == "error" and f.get("path")})


def flip_zone(root, args):
    """`zone --name Z --walled | --open [--yes]` for a zone that exists. Walled to open releases history at once, so
    it says how many files it releases and writes only on --yes. Open to walled writes, runs the whole-workspace walls
    check and lists the files now in violation. System/context.md is changed and left for the caller to commit."""
    ctx = load_context(root)
    zone = next((z for z in ctx["zones"] if z.lower() == args.name.strip().lower()), None)
    if zone is None:
        raise Refusal(f"{args.name.strip()} is not a zone in System/context.md.")
    if ctx.get("pending"):
        raise Refusal("The Zones table of System/context.md has no Walled column: the update to zone walls has not been "
                      "accepted yet, so no flag was changed.")
    now = zone_flag(ctx, zone)
    if now == bool(args.walled):
        return f"{zone} is already {'walled' if args.walled else 'open'}. Nothing was changed."
    if args.open:
        n = files_in_zone(root, zone)
        if not args.yes:
            return (f"Opening {zone} releases {n} file{'s' if n != 1 else ''}: their material may go anywhere afterwards. "
                    "Nothing was written. To go on, run it again with --yes.")
        set_zone_flag(root, zone, False)
        return (f"{zone} is open. {n} file{'s' if n != 1 else ''} released. System/context.md is changed; commit it on its own, "
                "in the workspace's own repository.")
    set_zone_flag(root, zone, True)
    bad = walls_violations(root)
    said = [f"{zone} is walled. System/context.md is changed; commit it on its own, in the workspace's own repository."]
    if bad is None:
        raise Refusal(said[0] + " The check could not run, so the files now in violation are not known: run "
                      "`python3 System/tools/check.py --walls-only` before committing.")
    if bad:
        said.append("%d file%s now in violation:" % (len(bad), "s" if len(bad) != 1 else ""))
        said += ["  " + b for b in bad[:20]] + (["  and %d more" % (len(bad) - 20)] if len(bad) > 20 else [])
        said.append("Commits in their zones are refused until each is fixed.")
    else:
        said.append("No file is in violation.")
    return "\n".join(said)


def cmd_zone(root, args, today):
    given = args.name or args.zone_name
    if not given or not given.strip():
        raise Refusal("Say the zone's name.")
    args.name = given
    if args.walled or args.open:
        if any(z.lower() == given.strip().lower() for z in load_context(root)["zones"]):
            return flip_zone(root, args)
        if args.walled and args.open:
            raise Refusal("Say --walled or --open, not both.")
    if args.holds is None:
        raise Refusal(f"{given.strip()} is not a zone yet. To make it, say what it holds: --holds \"<what it holds>\".")
    name, holds = args.name.strip(), " ".join(args.holds.split())
    zones = root / "Zones"
    check_name(name, children(zones), "zone", "the workspace", parent=zones, must_be_sayable=True)
    target = zones / name
    if target.exists():
        raise Refusal(f"{target.relative_to(root)} already exists.")
    template = root.joinpath(*ZONE_TEMPLATE)
    if not all((template / f).is_file() for f in ("AGENTS.md", "Todo.md", ".gitignore")):
        raise Refusal("The zone template, System/templates/zone, is missing or has no .gitignore. "
                      "A workspace installed by an older Garrick has none.")
    if not (root / "System" / "context.md").is_file():
        raise Refusal("System/context.md is missing, so the new zone could not be listed there.")
    identity = zone_identity(root)
    zones.mkdir(exist_ok=True)
    try:
        target.mkdir()
    except FileExistsError:
        raise Refusal(f"{target.relative_to(root)} already exists.") from None
    try:
        fill_into(template, target, {"ZONE": name})
        for link, points_to in skill_links(root, target):
            link.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(points_to, link)
        init_repo(target, f"Garrick: {name} created", identity)
        install_wall_hook(target)
    except (GitError, OSError) as exc:
        shutil.rmtree(target, ignore_errors=True)  # only ever the folder made just above
        raise Refusal(f"The {name} zone could not be made, so nothing of it was kept: {' '.join(str(exc).split())}")
    said = [f"Created the {name} zone: its own folder and git history, an inbox, "
            "and the wall check before every commit."]
    to_commit = []
    if list_zone(root, name, holds, walled=not args.open):
        said.append(f"Added {name} to the Zones table in System/context.md, "
                    f"{'open: what is in it may go anywhere' if args.open else 'walled: what is in it stays in it'}.")
        to_commit.append("System/context.md")
    else:
        said.append(f"System/context.md already lists {name}, so its row is unchanged.")
    # The zone's files join the stamp's list, as the installer's zones did.
    made = []
    for folder, dirs, files in os.walk(target):
        dirs[:] = [d for d in dirs if d != ".git"]
        made += [Path(folder) / f for f in files]
    if record_written(root, made):
        said.append("Listed its files in System/garrick-version.json, so an update knows them as Garrick's.")
        to_commit.append("System/garrick-version.json")
    if to_commit:
        said.append("Commit %s in the workspace's own repository, at its top folder." % " and ".join(to_commit))
    elsewhere = hooks_path(target)
    if elsewhere:
        said.append(f"git takes its hooks from {elsewhere}, so the wall check will not run before commits "
                    f"in {name}. To turn it on, run in Zones/{name}: git config core.hooksPath .git/hooks")
    said.append(f'Next, say "new project <name> in {name}, first thread <name>". '
                f"A party new to the workspace goes into System/context.md first, with {name} as its zone.")
    return "\n".join(said)


# --------------------------------------------------------------------------- party


def party_words(name):
    """A party's name as the words it is made of, lower case, so that Acme Corp
    and "Acme  Corp." are the same name and the two-capacity case is found."""
    return " ".join(w for w in re.sub(r"[^\w\s]", " ", (name or "").lower()).split() if w)


def parties_called(root, name):
    """[(tag, entry)] for every row in Parties whose name is `name`, in the
    order the table has them. Two is one organisation in two capacities, which
    only the user can tell apart."""
    wanted = party_words(name)
    parties = load_context(root).get("parties", {})
    return [(tag, entry) for tag, entry in parties.items() if party_words(entry.get("party")) == wanted]


def projects_of(root, tag, zone=None):
    """Every project whose hub note names `tag` as its party, sorted, each
    named with its zone where that is not the party's own. This lists; it
    never picks one of them, which is what the user is asked."""
    found = []
    for zone_dir in sorted((root / "Zones").iterdir() if (root / "Zones").is_dir() else []):
        if not zone_dir.is_dir() or zone_dir.name.startswith((".", "_")) or zone_dir.name == INBOX:
            continue
        for project in sorted(zone_dir.iterdir()):
            if not project.is_dir() or project.name.startswith((".", "_")) or project.name == INBOX:
                continue
            hub = project / f"{project.name}.md"
            if hub.is_file() and tag in tag_list(parse_frontmatter(hub).get("party")):
                found.append(project.name if zone_dir.name == zone else f"{project.name} in {zone_dir.name}")
    return found


def say_projects(projects):
    if not projects:
        return "no project yet"
    if len(projects) == 1:
        return "the project %s" % projects[0]
    return "the projects %s and %s" % (", ".join(projects[:-1]), projects[-1])


def party_zone(root, args, name, required=True):
    """The zone the new party belongs to: the one named, or the only one there
    is. Never guessed between several, which is the user's to say. None where
    nothing settles it and nothing is being written yet."""
    if args.zone:
        return find_zone(root, args.zone).name
    zones = sorted(children(root / "Zones"))
    if len(zones) == 1:
        return zones[0]
    if not required:
        return None
    raise Refusal("Which zone is %s in? The zones are %s." % (name, ", ".join(zones) or "none yet"))


def add_party_row(root, name, what, zone, tag, today=None):
    """The row in context.md's Parties table, written where the installer wrote
    its own, each cell under its header. The commit is the caller's, as a new
    zone's row is. With `today`, the row is a learned one, added on the user's
    word, and its Learned cell says so; the rows typed by hand are left as
    they are."""
    path = root / "System" / "context.md"
    if not path.is_file():
        raise Refusal("System/context.md is missing, so the party could not be listed there.")
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next((i for i, l in enumerate(lines) if l.strip().lower() == "## parties"), None)
    if start is None:
        raise Refusal("System/context.md has no `## Parties` table to add the party to.")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    rows = [i for i in range(start + 1, end) if lines[i].lstrip().startswith("|")]
    if len(rows) < 2:
        lines[end:end] = ["| Party | What it is | Zone | Tag | Domains |", "|---|---|---|---|---|", ""]
        rows = [end, end + 1]
    # A table still in the 0.62 shape has a Walled column: a new row there is walled, until the update to zone walls drops it.
    given = {"party": name, "what": what, "zone": zone, "tag": "`%s`" % tag, "walled": "yes"}
    header = [h.lower() for h in lines[rows[0]].strip().strip("|").split("|")]
    cells = [next((v for k, v in given.items() if h.strip().startswith(k)), "") for h in header]
    row = learned_row(lines, rows, cells, learned_cell(today, "user")) if today else table_row(cells)
    lines.insert(rows[-1] + 1, row)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def cmd_party(root, args, today):
    if not args.name:
        raise Refusal("Say --name for a new party.")
    return cmd_new_party(root, args, today)


def cmd_new_party(root, args, today):
    """Add a party to System/context.md, or say what adding one would do.

    The one step of setting up a piece of work that reaches outside the zone
    it is for, and the one the user is asked about. It offers the tag itself,
    from `tag_for` in the library, so nobody has to invent one; it is
    idempotent, so an onboarding picked up again writes no second row; and it
    refuses, in a question, where two parties share the name, because which
    capacity a request means is the user's to answer.
    """
    name = " ".join(args.name.split())
    if not name:
        raise Refusal("A party needs a name.")
    same = parties_called(root, name)
    parties = load_context(root).get("parties", {})
    if same and not args.also:
        tag, entry = same[0]
        where = entry.get("zone") or "no zone"
        return "%s is already a party, `%s`, in %s, with %s." % (
            entry.get("party") or name, tag, where, say_projects(projects_of(root, tag, where)))
    if args.also and not same:
        raise Refusal("%s is not a party yet, so there is no first capacity for --also to stand beside. "
                      "Add it without --also." % name)
    zone = party_zone(root, args, name, required=not args.check)
    tag = tag_for(name, parties, zone)
    if not tag:
        raise Refusal('No tag can be made from "%s": a tag is %s. What should it be?' % (name, TAG_RULE))
    if tag == "none":
        raise Refusal("`none` is reserved: it says a page is nobody's, so it is never a party's tag. What should the tag be?")
    if not TAG_RE.match(tag):                     # the library offers only valid tags; belt and braces
        raise Refusal('"%s" will not work as a tag: it must be %s.' % (tag, TAG_RULE))
    if args.check:
        where = ", in %s" % zone if zone else ""
        return "%s is not a party yet, and the tag would be `%s`%s." % (name, tag, where)
    what = " ".join((args.what or "").split()) or f"<What {name} is>"
    add_party_row(root, name, what, zone, tag, today)
    said = [f"Added {name} to the Parties table in System/context.md, with the tag `{tag}`, in {zone}. "
            "A party routes mail and names what is said; the wall is its zone's."]
    said.append("Commit System/context.md on its own, in the workspace's own repository at its top folder: "
                "a project is in its zone's repository, and one commit never spans the two.")
    said.append('Next, once that row is committed: scaffold.py project --zone %s --name "<Project>" '
                '--party %s --thread "<Thread>" (the party is optional), which is refused while the row is not there.' % (zone, tag))
    return "\n".join(said)


STATE_OF_PLAY = "## State of play"


def hub_resume_section(root):
    """The thread template's `## State of play` section, which is what a hub that keeps its own
    resume point holds too: one block, one shape."""
    template = root / "System" / "templates" / "thread"
    note = next((p for p in sorted(template.glob("*.md"))), None)
    text = note.read_text(encoding="utf-8") if note else ""
    at = text.find(STATE_OF_PLAY)
    if at < 0:
        raise Refusal("System/templates/thread has no State of play section to start a hub's resume point from.")
    return text[at:].rstrip("\n") + "\n"


def shape_hub(hub, root, heading, with_thread):
    """A hub made from the project template, shaped for what the project is. One job with
    no thread yet gets a resume point and no Threads list entry; separate jobs get `layout: thread-first`
    and no Sources or Deliverables rows; a project made with its first thread is as it has always been."""
    text = hub.read_text(encoding="utf-8")
    if not with_thread:
        text = re.sub(r"(?m)^- \[\[[^\n]*<what it produces>\n", "", text, count=1)
    if heading:
        text = re.sub(r"(?m)^(status: .*)$", r"\1\nlayout: thread-first", text, count=1)
        text = re.sub(r"(?m)^\| `(Sources|Deliverables)/` \|.*\n", "", text)
        text = text.replace("| `Threads/` | One folder per thread, each with its resume point |",
                            "| `Threads/` | One folder per thread, each with its resume point and its own `Sources/` and `Deliverables/` |")
    elif not with_thread:
        section = hub_resume_section(root)
        text = re.sub(r"(?m)^## Threads$", lambda m: section + "\n## Threads", text, count=1)
    hub.write_text(text, encoding="utf-8")


def cmd_project(root, args, today):
    zone_dir = find_zone(root, args.zone)
    name = args.name.strip()
    thread = (args.thread or "").strip()
    heading = bool(getattr(args, "heading", False))
    if name.lower() == INBOX.lower():
        raise Refusal(f"{INBOX} is where {zone_dir.name}'s mail and files wait to be filed. Pick another name for the project.")
    spoken = (args.spoken or "").strip()
    thread_spoken = (args.thread_spoken or "").strip()
    if thread_spoken and not thread:
        raise Refusal("--thread-spoken says how the first thread's name is said, and no first thread is named.")
    check_name(name, children(zone_dir), "project", zone_dir.name, spoken=spoken, parent=zone_dir)
    if thread:
        check_name(thread, [], "thread", name, spoken=thread_spoken)
    party = check_party(root, args.party, zone_dir.name)
    target = zone_dir / name
    if target.exists():
        raise Refusal(f"{target.relative_to(root)} already exists.")
    asked = say_how(name, "project", spoken) + (say_how(thread, "thread", thread_spoken) if thread else [])
    kind = "separate jobs" if heading else "one job"
    if getattr(args, "check", False):
        first = f", and {thread} as its first thread" if thread else ""
        if thread and not heading:                  # as it has always said it
            return "\n".join([f"{name} will do as a project in {zone_dir.name}, and {thread} as its first thread."] + asked)
        return "\n".join([f"{name} will do as a project in {zone_dir.name}, as {kind}{first}."] + asked)
    values = {"ZONE": zone_dir.name, "PROJECT": name, "THREAD": thread, "PARTY": party, "DATE": today}
    copy_filled(root / "System" / "templates" / "project", target, values)
    hub = target / f"{name}.md"
    if spoken and hub.is_file():
        hub.write_text(set_spoken(hub.read_text(encoding="utf-8"), spoken), encoding="utf-8")
    if hub.is_file():
        shape_hub(hub, root, heading, bool(thread))
    if heading:
        for papers in ("Sources", "Deliverables"):       # just copied from the template: nothing of anyone's in them
            shutil.rmtree(target / papers, ignore_errors=True)
    if thread:
        make_thread(root, target, thread, party, today, thread_spoken, papers=heading)
    if not party:
        drop_empty_party(hub)
    if thread:
        link_thread_in_hub(hub, thread, today)
    if thread and not heading:                      # as it has always said it
        return "\n".join([f"Created project {name} in {zone_dir.name}, with its first thread, {thread}."] + asked)
    made = f"Created project {name} in {zone_dir.name}, as {kind}"
    return "\n".join([made + (f", with its first thread, {thread}." if thread else ".")] + asked)


def cmd_thread(root, args, today):
    zone_dir = find_zone(root, args.zone)
    project_dir = find_child(zone_dir, args.project, "project")
    hub = project_dir / f"{project_dir.name}.md"
    if not hub.is_file():
        raise Refusal(f"{project_dir.name} has no hub note, {hub.name}.")
    party = check_party(root, ",".join(tag_list(parse_frontmatter(hub).get("party"))))      # none: the thread has none either
    name = args.name.strip()
    spoken = (args.spoken or "").strip()
    asked = say_how(name, "thread", spoken)
    refuse_papers(args)
    own = is_heading(project_dir)                 # separate jobs: each thread keeps its own papers; one job: the project's
    keeps = " It keeps its own papers." if own else ""
    if getattr(args, "check", False):
        threads = project_dir / "Threads"
        check_name(name, children(threads), "thread", project_dir.name, spoken=spoken, parent=threads)
        if (threads / name).exists():
            raise Refusal(f"{(threads / name).relative_to(root)} already exists.")
        return "\n".join([f"{name} will do as a thread in {project_dir.name}." + keeps] + asked)
    target = make_thread(root, project_dir, name, party, today, spoken, papers=own)
    link_thread_in_hub(hub, name, today)
    said = [f"Created thread {name} in {project_dir.name}." + keeps] + asked
    if getattr(args, "touched", False):
        # What it wrote, from the zone, for a caller that commits it by name and nothing else (#183).
        said.append("Touched: " + json.dumps([target.relative_to(zone_dir).as_posix(),
                                              hub.relative_to(zone_dir).as_posix()], ensure_ascii=False))
    return "\n".join(said)


# --------------------------------------------------------------------------- rename and delete

MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")


def commit_trailers():
    """`-m <trailers>` for a commit made on behalf of a recorded action: the operation's id and payload hash, which
    the status page's page_action.py hands over in GARRICK_COMMIT_TRAILERS (#716), so that the commit names the
    action as the page's own commits do. Nothing else is taken from the environment, and a value of another shape
    is left out."""
    text = os.environ.get("GARRICK_COMMIT_TRAILERS", "")
    if re.fullmatch(r"Garrick-Op: [0-9a-f]{8,32}\nGarrick-Payload: [0-9a-f]{64}", text):
        return ["-m", text]
    return []


def git_ok(args, cwd):
    try:
        return git(args, cwd)
    except GitError as exc:
        raise Refusal(" ".join(str(exc).split()))


def target_of(root, args):
    """(zone folder, project folder, thread folder or None, the note) for the
    project or thread the arguments name."""
    zone_dir = find_zone(root, args.zone)
    if not (zone_dir / ".git").exists():
        raise Refusal(f"{zone_dir.name} is not a git repository, so the change could not be committed or undone.")
    project_dir = find_child(zone_dir, args.project, "project")
    if args.thread:
        thread_dir = find_child(project_dir / "Threads", args.thread, "thread")
        note = thread_dir / f"{thread_dir.name}.md"
    else:
        thread_dir, note = None, project_dir / f"{project_dir.name}.md"
    if not note.is_file():
        raise Refusal(f"{note.relative_to(root)} is missing, so {note.stem} is not a project or thread scaffold made.")
    return zone_dir, project_dir, thread_dir, note


def uncommitted(zone_dir, paths):
    """The paths, relative to the zone, among `paths` that git reports as changed."""
    rels = [str(p.relative_to(zone_dir)) for p in paths]
    out = git_value(["status", "--porcelain", "--untracked-files=all", "--"] + rels, zone_dir)
    return [line[3:].strip().strip('"') for line in out.splitlines() if line.strip()]


def mid_turn(root, folder):
    """Whether a cmux tab is mid-turn in the folder, when the cmux extra is
    installed beside the workspace's tools; False when nobody can say."""
    lib = root / "System" / "cmux" / "cmuxlib.py"
    if not lib.is_file():
        return False
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("garrick_scaffold_cmuxlib", str(lib))
        cx = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cx)
        folder = folder.resolve()
        return any(state == "working" and (Path(f) == folder or folder in Path(f).parents)
                   for f, state in cx.sessions_by_folder(root).items())
    except Exception:
        return False


def zone_notes(zone_dir):
    """Every note git tracks in the zone: nothing ignored, nothing in a
    repository of its own inside a project, nothing waiting in the inbox."""
    listing = git_value(["ls-files", "-z", "--", "*.md"], zone_dir)
    for name in sorted(n for n in listing.split("\0") if n and not n.startswith(INBOX + "/")):
        if not (zone_dir / name).is_symlink():          # a link may lead out of the zone: never write through one
            yield zone_dir / name


def preflight(zone_dir, folder, verb):
    """Refuse a rename or a deletion that git could not put back exactly:
    a merge or rebase under way, anything already staged (it would go into
    this commit), or a folder holding files git does not track, ignores, or
    keeps in a repository of its own, which no revert brings back. The files
    a machine makes on its own (MACHINE_IGNORES: Finder's .DS_Store and the
    like) hold nothing to bring back and refuse nothing: their paths, from the
    zone's top, are what it returns, for clear_machine_made()."""
    gitdir = zone_dir / ".git"
    if any((gitdir / m).exists() for m in ("MERGE_HEAD", "rebase-merge", "rebase-apply", "CHERRY_PICK_HEAD", "REVERT_HEAD")):
        raise Refusal(f"{zone_dir.name} is in the middle of a merge or rebase. Finish it, then {verb}.")
    if git_value(["diff", "--cached", "--name-only"], zone_dir).strip():
        raise Refusal(f"Something is staged in {zone_dir.name}, and it would go into this commit. Commit or unstage it, then {verb}.")
    rel = folder.relative_to(zone_dir).as_posix()
    nested = [Path(d).relative_to(zone_dir).as_posix() for d, dirs, _ in os.walk(folder) if ".git" in dirs or (Path(d) / ".git").is_file()]
    if nested:
        raise Refusal(f"{nested[0]} is a repository of its own, which the zone's history cannot bring back. "
                      f"Move it out of {folder.name} first, then {verb}.")
    status = git_value(["status", "--porcelain", "--ignored", "--untracked-files=all", "--", rel], zone_dir)
    loose = [l[3:].strip().strip('"') for l in status.splitlines() if l[:2] in ("!!", "??")]
    made = [p for p in loose if machine_made(p)]
    loose = [p for p in loose if p not in made]
    if loose:
        raise Refusal(f"{loose[0]}{' and %d more' % (len(loose) - 1) if len(loose) > 1 else ''} is in {folder.name} but "
                      f"not in the zone's history, so nothing could bring it back. Commit it or move it out, then {verb}.")
    return made


def clear_machine_made(zone_dir, folder, made):
    """The files preflight() let through, removed before git moves or removes
    the folder, so the new folder starts without them and the old one goes
    once git has taken the rest. A folder they leave empty goes with them.
    Finder writes a new .DS_Store the next time the folder is opened."""
    for rel in made:
        path = zone_dir / rel
        try:
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink()
        except FileNotFoundError:
            pass
        up = path.parent
        while up != folder and folder in up.parents and up.is_dir() and not os.listdir(up):
            up.rmdir()
            up = up.parent


def remove_empty(folder):
    """The folders git left behind once it removed every file, deepest first."""
    for d, dirs, files in sorted(os.walk(folder), key=lambda t: -len(Path(t[0]).parts)):
        if not files and not os.listdir(d):
            os.rmdir(d)


def relink(text, swaps, prefixes, old_name, new_name, heads=("",)):
    """Every [[link]] to the renamed note pointed at its new name, in its
    bare, labelled, heading and path forms: `swaps` are whole targets (old,
    new, without .md), `prefixes` folders a target may run through, for the
    files inside a renamed folder. A path counts only from the zone, written
    from its top or with one of `heads` before it (`Work/`, `Zones/Work/`):
    a thread elsewhere that shares a name is another note. A label that was
    the old name follows it."""
    def one(m):
        target, rest = m.group(1), m.group(2) or ""
        md = target.endswith(".md")
        key = target[:-3] if md else target
        found = None
        for old, new in swaps:
            for head in (heads if "/" in old else ("",)):     # a bare name is only ever itself
                if key == head + old:
                    found = head + new
                    break
            if found:
                break
        for old, new in prefixes if found is None else ():
            for head in heads:
                if key.startswith(head + old + "/"):
                    found = head + new + key[len(head + old):]
                    break
            if found:
                break
        if found is None:
            return m.group(0)
        itself = not any(found.startswith(h + new + "/") for _, new in prefixes for h in heads) or \
            any(found == h + new for _, new in swaps for h in heads)
        if itself and rest.endswith("|" + old_name):
            rest = rest[: -len(old_name)] + new_name
        return "[[" + found + (".md" if md else "") + rest + "]]"
    return re.sub(r"\[\[([^\]|#]+)((?:#[^\]|]*)?(?:\|[^\]]*)?)\]\]", one, text)


def dated_entry(text, line, today, append=True):
    """`line` as today's dated entry, newest first, below the Resume here
    block's rule, as the threads skill writes one. A note with no block of
    either kind takes it at the end, unless `append` is off, when the note is
    left as it is: that is what park did while its own copy of this lived in
    page_action.py, which keeps one for `answer`."""
    d = datetime.date.fromisoformat(today)
    entry = f"**{d.day} {MONTHS[d.month - 1]} {d.year}.** {line}"
    resume = text.find("### Resume here")
    rule = text.find("\n---\n", resume) if resume >= 0 else -1
    play = re.search(r"(?m)^## State of play[ \t]*\n", text) if rule < 0 else None
    at = rule + 5 if rule >= 0 else play.end() if play else -1
    if at < 0:
        return text.rstrip("\n") + "\n\n" + entry + "\n" if append else text
    lead = re.match(r"\n*(?:<Dated entries[^\n]*>\n)?\n*", text[at:])
    at += lead.end()
    return text[:at] + entry + "\n\n" + text[at:]


def add_alias(root, heard, means, today=None):
    """The old name as a heard form of the new one, in the Aliases table, so
    "Pricing" still finds "Renewal" for a while: in System/names.md, or in
    context.md while the workspace has not moved its tables (#653). False when
    there is no table or the table already has it, else the file it went into. With `today`, the row's
    Learned cell says it came from the user, who asked for the rename."""
    if heard.lower() in load_context(root).get("aliases", {}):
        return False
    for path in table_files(root, "aliases"):
        if not path.is_file():
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        start = next((i for i, l in enumerate(lines) if l.strip().lower() == "## aliases"), None)
        if start is None:
            continue
        end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
        rows = [i for i in range(start + 1, end) if lines[i].lstrip().startswith("|")]
        if len(rows) < 2:
            continue
        cells = [heard.lower(), means]
        lines.insert(rows[-1] + 1, learned_row(lines, rows, cells, learned_cell(today, "user")) if today else table_row(cells))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return "System/" + path.name
    return False


# --------------------------------------------------------------------------- park and wake


def operations():
    """operations.py, beside this file: the table every operation is declared
    in, and the words for refusing one. None where System/tools is older than
    this script, and then the refusal below is this file's own."""
    try:
        import operations as ops
    except ImportError:
        return None
    return ops if callable(getattr(ops, "stale", None)) and callable(getattr(ops, "say", None)) else None


def refuse_stale(verb, request, status):
    """operations.py's precheck for park and wake: the note's `status:` as it
    stands now. A second park of a thread already set aside is refused in the
    words that module keeps, which are the words the status page reads for it
    too, so the two cannot drift apart."""
    ops = operations()
    if ops is None:
        if status == ("parked" if verb == "park" else "active"):
            raise Refusal(f"Nothing was changed: {request.get('thread') or request.get('project')} is not for "
                          f"{verb} to do anything about now.")
        return
    why = ops.stale(verb, request, status)
    if why:
        raise Refusal(ops.say("refused", verb, request, why=why))


def cmd_park(root, args, today):
    """Park a project or a thread, or wake it: `status:`, `updated:` today and
    a dated entry, which is steps 3 and 4 of the threads skill's Park.

    The change is left uncommitted, as a new project's files are. The caller
    commits it: the skill as its own next step, and the status page through
    page_action.py, whose commit puts the note back as it was when the zone's
    wall check refuses. So one script makes the edit however it was asked
    for, and the page keeps the one path that can undo it."""
    zone_dir, project_dir, thread_dir, note = target_of(root, args)
    status = "parked" if args.command == "park" else "active"
    name = f"{project_dir.name}, {thread_dir.name}" if thread_dir else project_dir.name
    request = {"verb": args.command, "zone": zone_dir.name, "project": project_dir.name,
               "thread": thread_dir.name if thread_dir else None}
    try:
        text = note.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise Refusal("the note is not UTF-8 text")
    m = re.match(r"\A---\n(.*?)\n---\n", text, re.S)
    if not m:
        raise Refusal("the note has no frontmatter to set its status in")
    fm = m.group(1)
    was = re.search(r"(?m)^status:[ \t]*(\S*)", fm)
    refuse_stale(args.command, request, was.group(1).lower() if was else "")
    when = today if isinstance(today, datetime.date) else datetime.date.fromisoformat(today)
    fm = re.sub(r"(?m)^status:.*$", "status: " + status, fm) if was else fm + "\nstatus: " + status
    fm = re.sub(r"(?m)^updated:.*$", "updated: " + when.isoformat(), fm) if re.search(r"(?m)^updated:", fm) \
        else fm + "\nupdated: " + when.isoformat()
    body = dated_entry(text[m.end():], "Parked." if status == "parked" else "Woken.", when.isoformat(),
                       append=False)                           # as the page's own copy left such a note
    note.write_text("---\n%s\n---\n%s" % (fm, body), encoding="utf-8")
    said = "%s is %s" % (name, "parked" if status == "parked" else "awake again")
    if not os.environ.get(CALLER_BUILDS_PAGE):      # the status page's executor moves the pointer after its commit (#664)
        try:
            pointer = park_memory_pointer(root, note.resolve().relative_to(Path(root).resolve()).as_posix(), status != "parked")
        except Exception:
            pointer = ""
        said = "%s. %s" % (said, pointer) if pointer else said
    return said


def rename_history(zone_dir, moved, old, new):
    """The history files beside a renamed note (history.py) go by its new name: each file, its `parent:` and its
    heading. The note's own link line is rewritten with the note. The files of a thread moved to another project
    need nothing: the whole folder goes with it. Returns the files it changed, in their new places."""
    folder = moved / "history"
    out = []
    if not folder.is_dir():
        return out
    for path in sorted(folder.glob("*.md")):
        m = re.fullmatch(re.escape(old) + r" history (\d{4}-Q[1-4])\.md", path.name)
        if not m:
            continue
        target = folder / f"{new} history {m.group(1)}.md"
        step = folder / f".rename-{m.group(1)}.md"
        git_ok(["mv", path.relative_to(zone_dir).as_posix(), step.relative_to(zone_dir).as_posix()], zone_dir)
        git_ok(["mv", step.relative_to(zone_dir).as_posix(), target.relative_to(zone_dir).as_posix()], zone_dir)
        text = target.read_text(encoding="utf-8")
        text = re.sub(r"(?m)^# %s: history, " % re.escape(old), lambda _: f"# {new}: history, ", text, count=1)
        target.write_text(text, encoding="utf-8")
        out.append(target)
    return out


PLAN_FILES = 40         # notes a plan lists: the count is the whole, the list is cut here
PLAN_EDITS = 3          # edited lines shown for each note


def plan_of(zone_dir, paths, notes, after, rewritten, extra=None, texts=None):
    """What a rename or a move would write, as JSON, and nothing written: the paths that change, and for each note
    its lines that change. `rewritten(path, text)` is the very function the change itself writes with, asked for each
    note at the place it will have, `after(path)`, so a plan is never a second guess at what the change does."""
    files, whole = [], hashlib.sha256()
    for path in notes:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        there = after(path)
        changed = rewritten(there, (texts or {}).get(path, text))        # a hub's line is taken out or put in first
        if changed == text:
            continue
        whole.update(("\0" + there.relative_to(zone_dir).as_posix() + "\0" + changed).encode("utf-8"))
        was, now = text.split("\n"), changed.split("\n")
        edits, lines = [], 0
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, was, now, autojunk=False).get_opcodes():
            if tag != "equal":
                lines += max(i2 - i1, j2 - j1)
                edits.append({"was": " ".join(was[i1:i2])[:160], "now": " ".join(now[j1:j2])[:160]})
        files.append({"path": there.relative_to(zone_dir).as_posix(), "lines": lines, "edits": edits})
    # The digest is of every note as it would be written, not only the lines the plan lists, so that a caller can tell a plan has changed.
    whole.update(json.dumps([paths, extra or {}], ensure_ascii=False, sort_keys=True).encode("utf-8"))
    shown = [dict(f, edits=f["edits"][:PLAN_EDITS]) for f in files[:PLAN_FILES]]
    plan = {"paths": paths, "count": len(files), "files": shown,
            "digest": whole.hexdigest()}
    plan.update(extra or {})
    return json.dumps(plan, ensure_ascii=False, sort_keys=True)


def cmd_rename(root, args, today):
    zone_dir, project_dir, thread_dir, note = target_of(root, args)
    new = args.to.strip()
    is_thread = thread_dir is not None
    folder = thread_dir if is_thread else project_dir
    old = folder.name
    kind = "thread" if is_thread else "project"
    siblings = [c for c in children(folder.parent) if c != old]
    if new == old:
        raise Refusal(f"{old} is already called {new}.")
    if new.lower() == old.lower():
        siblings = [c for c in siblings if c.lower() != new.lower()]
    spoken = (args.spoken or "").strip()
    check_name(new, siblings, kind, project_dir.name if is_thread else zone_dir.name,
               spoken=spoken, parent=folder.parent)
    if not is_thread and new.lower() == INBOX.lower():
        raise Refusal(f"{INBOX} is where {zone_dir.name}'s mail and files wait to be filed. Pick another name.")
    asked = say_how(new, kind, spoken)
    if getattr(args, "check", False):
        return "\n".join([f"{new} will do as the {kind}'s new name."] + asked)
    notes = list(zone_notes(zone_dir))
    others = [n for n in notes if n.stem.lower() == old.lower() and n != note]
    if folder.parent / new != folder and (folder.parent / new).exists() and new.lower() != old.lower():
        raise Refusal(f"{(folder.parent / new).relative_to(root)} already exists.")
    made = preflight(zone_dir, folder, "rename")
    dirty = uncommitted(zone_dir, [folder] + notes)
    if dirty:
        raise Refusal(f"{', '.join(dirty[:3])}{' and more' if len(dirty) > 3 else ''} has changes not committed. "
                      f"Commit or undo them, then rename.")
    if mid_turn(root, folder):
        raise Refusal(f"A session is mid-turn in {old}. Let it finish, then rename.")
    rel_old = folder.relative_to(zone_dir).as_posix()
    rel_new = (folder.parent / new).relative_to(zone_dir).as_posix()
    # Link targets, without .md: the note by its path, and by its name when no other note shares it;
    # and every file inside its folder, a thread's Deliverables as much as a project's threads.
    swaps = [(f"{rel_old}/{old}", f"{rel_new}/{new}")] + ([(old, new)] if not others else [])
    prefixes = [(rel_old, rel_new)]
    heads = ("", f"{zone_dir.name}/", f"Zones/{zone_dir.name}/")
    moved = zone_dir / rel_new
    touched = set()
    what = f"{project_dir.name}, {old}" if is_thread else old
    new_note = moved / f"{new}.md"

    def rewritten(path, text):
        """One note as the rename leaves it: `path` is where the note is once the folder has moved. The write below
        and the plan (--plan) both ask this, so what a plan lists is what the rename writes."""
        changed = relink(text, swaps, prefixes, old, new, heads)
        if not is_thread and moved in path.parents:
            # `parent:` names the project only in a thread's own note and a note at the project's
            # top; a thread's working note names its thread, which may share the project's name.
            own = path.parent == moved or (path.parent.parent == moved / "Threads"
                                           and path.name == path.parent.name + ".md")
            changed = re.sub(r'(?m)^(%s): "?\[\[%s\]\]"?$' % ("project|parent" if own else "project", re.escape(old)),
                             lambda m: f'{m.group(1)}: "[[{new}]]"', changed)
        if path == new_note:
            changed = re.sub(r"(?m)^title: .*$", f"title: {new}", changed, count=1)
            # The old spoken form goes with the old name, which becomes a heard alias below.
            if spoken or is_sayable(new)[0]:
                changed = set_spoken(changed, spoken)
            changed = re.sub(r"(?m)^# %s\s*$" % re.escape(old), f"# {new}", changed, count=1)
            # the link line: relink moved each path with the folder; the file name and its label follow the note
            changed = re.sub(r"\[\[([^\]|]*/history/)%s history (\d{4}-Q[1-4])\]\]" % re.escape(old),
                             lambda m: f"[[{m.group(1)}{new} history {m.group(2)}]]", changed)
            changed = re.sub(r"(?m)^updated: .*$", f"updated: {today}", changed, count=1)
            changed = dated_entry(changed, f"Renamed from {old}.", today)
        return changed

    if getattr(args, "plan", False):
        def after(path):                                    # where a tracked file is once the folder has moved
            try:
                rel = path.relative_to(folder)
            except ValueError:
                return path
            return moved / (f"{new}.md" if rel.as_posix() == f"{old}.md" else rel.as_posix())
        kept = sorted(os.listdir(folder / "history")) if (folder / "history").is_dir() else []
        history = [{"from": (folder / "history" / n).relative_to(zone_dir).as_posix(),
                    "to": (moved / "history" / f"{new} history {m.group(1)}.md").relative_to(zone_dir).as_posix()}
                   for n in kept for m in [re.fullmatch(re.escape(old) + r" history (\d{4}-Q[1-4])\.md", n)] if m]
        paths = [{"from": rel_old, "to": rel_new},
                 {"from": f"{rel_old}/{old}.md", "to": f"{rel_new}/{new}.md"}] + history
        return plan_of(zone_dir, paths, notes, after, rewritten)
    clear_machine_made(zone_dir, folder, made)
    try:
        # The folder and its note, through git, so history follows.
        tmp = folder.parent / f".rename-{new}"
        if new.lower() == old.lower():                     # a change of case alone needs a step between
            git_ok(["mv", rel_old, tmp.relative_to(zone_dir).as_posix()], zone_dir)
            git_ok(["mv", tmp.relative_to(zone_dir).as_posix(), rel_new], zone_dir)
        else:
            git_ok(["mv", rel_old, rel_new], zone_dir)
        git_ok(["mv", f"{rel_new}/{old}.md", f"{rel_new}/{new}.md"], zone_dir)
        touched.add(new_note)
        touched.update(rename_history(zone_dir, moved, old, new))
        for path in zone_notes(zone_dir):
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue                                    # not text it can rewrite; its links, if any, stay
            changed = rewritten(path, text)
            if changed != text:
                touched.add(path)
                path.write_text(changed, encoding="utf-8")
        git_ok(["add", "-A", "--", rel_new] + [str(t.relative_to(zone_dir)) for t in touched], zone_dir)
        problem = wall_hook_problem(zone_dir)
        if problem:
            raise Refusal(f"{problem}, so nothing was committed.")
        git(["commit", "-q", "-m", f"{what}: renamed {new}", *commit_trailers()], zone_dir)
    except (GitError, Refusal, OSError) as exc:
        # Everything here was tracked and clean, and nothing was staged before: put back what HEAD holds.
        git_value(["reset", "-q"], zone_dir)
        if moved.exists() and moved != folder:
            shutil.rmtree(moved, ignore_errors=True)        # only files git moved: the folder held nothing else
        git_value(["checkout", "HEAD", "--", rel_old] + [str(t.relative_to(zone_dir)) for t in touched
                                                       if moved not in t.parents and t.exists()], zone_dir)
        raise Refusal(f"The rename was not committed, so nothing changed: {' '.join(str(exc).split())}")
    said = [f"Renamed the {kind} {old} to {new} in {zone_dir.name}, and every link to it in the zone, in one commit."]
    said += asked
    if others:
        said.append(f"Links written [[{old}]] were left alone: another note in {zone_dir.name} has that name too.")
    alias_file = add_alias(root, old, new, today)
    if alias_file:
        said.append(f'Added "{old}" as a heard name for {new} in {alias_file}; commit it in the workspace root.')
    meetings = root / "Wikis" / "Meetings" / "wiki"
    mentions = sorted(p.relative_to(root).as_posix() for p in meetings.rglob("*.md")
                      if re.search(r"\[\[[^\]]*\b%s\b" % re.escape(old), p.read_text(encoding="utf-8", errors="replace"))) \
        if meetings.is_dir() else []
    if mentions:
        said.append(f"Left as they are, in the Meetings wiki: {', '.join(mentions[:5])}"
                    f"{' and %d more' % (len(mentions) - 5) if len(mentions) > 5 else ''}.")
    said.append("If your assistant keeps a memory pointer to it, point it at the new name. For the status page's "
                f'effort history, build it with --moved "Zones/{zone_dir.name}/{rel_old}=Zones/{zone_dir.name}/{rel_new}".')
    return "\n".join(said)


def hub_status(hub):
    """The `status:` of a hub or thread note: active where it says none."""
    value = parse_frontmatter(hub).get("status")
    return str(value).strip().lower() if isinstance(value, str) and value.strip() else "active"


def item_end(lines, i):
    """The index after a list item and the indented lines that continue it."""
    indent = len(lines[i]) - len(lines[i].lstrip())
    j = i + 1
    while j < len(lines) and lines[j].strip() and len(lines[j]) - len(lines[j].lstrip()) > indent:
        j += 1
    return j


def heading_of(line):
    m = re.match(r"(#{1,6})\s+(.*?)\s*#*\s*$", line)
    return (len(m.group(1)), m.group(2)) if m else None


def cut_hub_line(hub, zone, rel, name):
    """The hub's list item for a thread, taken out of the hub's text with its
    continuation lines: (text without it, the `##` heading it stands under, the
    deeper heading directly above it or None, the item's lines). The item is
    the one whose first link leads to the thread, written as a bare name, a
    path from the zone's top or with the zone before it, labelled or with a
    heading. None where there is not exactly one such item: the move then
    refuses, since the hub cannot be told apart from another thread's."""
    forms = {name.lower()} | {(h + f"{rel}/Threads/{name}/{name}").lower() for h in ("", f"{zone}/", f"Zones/{zone}/")}
    first = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
    text = hub.read_text(encoding="utf-8")
    lines = text.split("\n")
    hits = []
    for i, line in enumerate(lines):
        if re.match(r"\s*[-*+]\s", line):
            m = first.search(line)
            if m and re.sub(r"\.md$", "", m.group(1).strip()).lower() in forms:
                hits.append(i)
    if len(hits) != 1:
        return text, None, None, None
    i = hits[0]
    block = lines[i:item_end(lines, i)]
    h2 = sub = None
    at = None
    for k in range(i):
        h = heading_of(lines[k])
        if h and h[0] == 2:
            h2, sub, at = h[1], None, k
        elif h and h[0] > 2 and h2 is not None:
            sub, at = h[1], k
    rest = lines[:i] + lines[i + len(block):]
    if sub is not None:                                      # no sub-heading is left standing empty
        j = at + 1
        while j < len(rest) and heading_of(rest[j]) is None:
            j += 1
        if not any(l.strip() for l in rest[at + 1:j]):
            del rest[at:j]
            if at < len(rest) and not rest[at].strip() and at > 0 and not rest[at - 1].strip():
                del rest[at]
    return "\n".join(rest), h2, sub, block


def put_hub_line(hub, h2, sub, block):
    """`block`, a list item with its continuation lines, as the last item under
    `## h2` of the hub, or under the same deeper heading when the hub has one;
    the section made at the end of the note where it has none."""
    lines = hub.read_text(encoding="utf-8").rstrip("\n").split("\n")
    heads = [(i, heading_of(l)) for i, l in enumerate(lines) if heading_of(l)]
    start = next((i for i, h in heads if h[0] == 2 and h[1].lower() == h2.lower()), None)
    if start is None:
        lines += ["", f"## {h2}", ""] + block
        return "\n".join(lines) + "\n"
    stop = next((i for i, h in heads if i > start and h[0] <= 2), len(lines))
    at = start
    if sub is not None:
        at = next((i for i, h in heads if start < i < stop and h[0] > 2 and h[1].lower() == sub.lower()), start)
    end = next((i for i, h in heads if i > at), len(lines))
    items = [i for i in range(at + 1, min(end, stop)) if re.match(r"[-*+]\s", lines[i])]
    if items:
        pos = item_end(lines, items[-1])
        lines[pos:pos] = block
    else:
        lines[at + 1:at + 1] = [""] + block
    return "\n".join(lines) + "\n"


MD_LINK = re.compile(r"(!?\[[^\]\n]*\]\()([^)\s]+)(\))")


def md_relink(text, p_old, p_new, rel_old, rel_new, zone_dir, zone, name, unresolved):
    """Markdown links, `[t](path)`, that a move changes the meaning of: one
    that leads into the thread's folder, and one from a note that moved with
    it to anything else. A path counts as written from the note's folder, or
    from the zone's top (with the zone's name before it, or not). A link both
    readings lead somewhere through, or one that names the thread and leads
    nowhere, is left as it is and added to `unresolved`, as (note, link)."""
    def inside(r):
        return r == rel_old or r.startswith(rel_old + "/")

    def now(r):
        return rel_new + r[len(rel_old):] if inside(r) else r

    def exists(r):
        return not r.startswith("..") and r != "." and (zone_dir / now(r)).exists()
    old_dir, new_dir = posixpath.dirname(p_old), posixpath.dirname(p_new)

    def one(m):
        raw = m.group(2)
        if re.match(r"[A-Za-z][A-Za-z0-9+.-]*:", raw) or raw.startswith(("#", "/", "<")):
            return m.group(0)
        path, _, frag = raw.partition("#")
        dec = urllib.parse.unquote(path)
        if not dec:
            return m.group(0)
        a = posixpath.normpath(posixpath.join(old_dir, dec))
        head = next((h for h in (f"Zones/{zone}/", f"{zone}/") if dec.startswith(h)), "")
        b = posixpath.normpath(dec[len(head):])
        found = [("a", a)] if exists(a) else []
        if b != a and exists(b):
            found.append(("b", b))
        moved_note = p_old != p_new
        if len(found) == 2:
            if inside(a) or inside(b) or moved_note:
                unresolved.append((p_new, raw))
            return m.group(0)
        if not found:
            if re.search(r"(^|/)%s(/|\.md$|$)" % re.escape(name), dec):
                unresolved.append((p_new, raw))
            return m.group(0)
        kind, r = found[0]
        if kind == "a":
            if not (inside(a) or moved_note):
                return m.group(0)
            new = posixpath.relpath(now(a), new_dir or ".")
        else:
            if not inside(b):
                return m.group(0)
            new = head + now(b)
        if dec.endswith("/") and not new.endswith("/"):
            new += "/"
        if new == dec:
            return m.group(0)
        if "%" in path:
            new = urllib.parse.quote(new, safe="/")
        return m.group(1) + new + ("#" + frag if frag else "") + m.group(3)
    return MD_LINK.sub(one, text)


STATE_MOVED = ("System", "generated", "moved.json")


def write_json_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("." + path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(str(tmp), str(path))


def move_state(root, zone, name, was, now):
    """What a thread's move changes outside the zone, where this script owns
    it: the effort history's record of the move (System/generated, never
    committed). `was` and `now` are the thread's folder from the zone's top.
    Best effort: a file that is not there or cannot be read is left alone."""
    path = root.joinpath(*STATE_MOVED)
    old, new = f"Zones/{zone}/{was}", f"Zones/{zone}/{now}"
    try:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        data = data if isinstance(data, dict) else {}
        data = {o: (new if n == old else n) for o, n in data.items() if isinstance(o, str) and isinstance(n, str)}
        if old != new:
            data[old] = new
        data.pop(new, None)
        write_json_atomic(path, data)
    except OSError:
        pass


def whole_word(name, text):
    return re.search(r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])" % re.escape(name), text, re.I) is not None


MOVE_ACTION = "Garrick-Action: move"
MOVE_PATHS = "Garrick-Moved:"


def undo_failed_move(zone_dir, rel_old, rel_new, moved, touched, created, threads, made_threads):
    """Put a move that failed back whole: unstage, remove what the move made,
    restore from HEAD only the paths HEAD holds, and report what git still
    shows changed (the paths, from the zone's top), empty when all is as it was."""
    git_value(["reset", "-q"], zone_dir)
    if moved.exists():
        shutil.rmtree(moved, ignore_errors=True)
    for path in sorted(created, key=lambda p: -len(p.parts)):
        try:
            if path.is_dir():
                if not os.listdir(path):
                    path.rmdir()
            else:
                path.unlink()
        except OSError:
            pass
    if made_threads and threads.is_dir() and not os.listdir(threads):
        threads.rmdir()
    rels = [str(t.relative_to(zone_dir)) for t in touched if moved not in t.parents and t != moved]
    held = set(git_value(["ls-tree", "-r", "--name-only", "-z", "HEAD", "--", rel_old] + rels, zone_dir).split("\0"))
    restore = [r for r in [rel_old] + rels if r == rel_old or r in held]
    try:
        git_ok(["checkout", "HEAD", "--"] + restore, zone_dir)
    except Refusal:
        pass
    out = git_value(["status", "--porcelain", "--untracked-files=all", "--", rel_old, rel_new] + rels, zone_dir)
    return [l[3:].strip().strip('"') for l in out.splitlines() if l.strip()]


def cmd_move(root, args, today):
    """Move a thread to another project of its zone: the folder with git, every
    link to it and to the files inside it, the hub lines, `project:` and
    `parent:`, and the ledger rows, in one commit. A move is a rename of the
    path, not of the name, so it is rename's machinery. Everything it cannot
    check is a refusal that writes nothing."""
    if not args.thread:
        raise Refusal("Say which thread to move: a project moves nowhere.")
    zone_dir, project_dir, thread_dir, note = target_of(root, args)
    name = thread_dir.name
    to_name = args.to.strip()
    # A project of another zone is refused as a missing one, naming no other zone: that it exists
    # elsewhere is not for this zone's session to say.
    target = find_child(zone_dir, to_name, "project")
    if target.name == INBOX or target == project_dir:
        raise Refusal(f"{name} is in {project_dir.name} already.")
    hub, target_hub = project_dir / f"{project_dir.name}.md", target / f"{target.name}.md"
    if not target_hub.is_file():
        raise Refusal(f"{target_hub.relative_to(root)} is missing, so {target.name} is not a project scaffold made.")
    # A move stays inside one zone, and a zone is the whole wall: nothing crosses one here.
    if not hub.is_file():
        raise Refusal(f"{hub.relative_to(root)} is missing, so the thread's line in its hub could not be moved.")
    if hub_status(target_hub) != "active":
        raise Refusal(f"{target.name} is {hub_status(target_hub)}, and a thread moved into it would take that status. "
                      "Wake it first, or pick another project.")
    if hub.is_file() and hub_status(hub) != "active":
        raise Refusal(f"{project_dir.name} is {hub_status(hub)}. Wake it before moving a thread out of it.")
    threads = target / "Threads"
    check_name(name, children(threads), "thread", target.name, spoken=spoken_of(thread_dir), parent=threads)
    if (threads / name).exists():
        raise Refusal(f"{(threads / name).relative_to(root)} already exists.")
    # Files of the thread that sit at the project's top, outside its folder, would be left behind.
    tracked = git_value(["ls-files", "-z", "--", project_dir.relative_to(zone_dir).as_posix()], zone_dir).split("\0")
    inside = f"{project_dir.relative_to(zone_dir).as_posix()}/Threads/"
    left = [t for t in tracked if t and not t.startswith(inside) and t != f"{project_dir.relative_to(zone_dir).as_posix()}/{project_dir.name}.md"
            and whole_word(name, Path(t).stem) and Path(t).name != "published.md"]
    if left:
        raise Refusal(f"{left[0]}{' and %d more' % (len(left) - 1) if len(left) > 1 else ''} sits in {project_dir.name} "
                      f"outside the {name} folder and would stay behind. Move it into the thread's folder first, then move the thread.")
    if getattr(args, "check", False):
        return f"{name} can move from {project_dir.name} to {target.name}."
    notes = list(zone_notes(zone_dir))
    ledger, target_ledger = project_dir / "Deliverables" / "published.md", target / "Deliverables" / "published.md"
    made = preflight(zone_dir, thread_dir, "move")
    dirty = uncommitted(zone_dir, [thread_dir, hub, target_hub, ledger, target_ledger] + notes)
    if dirty:
        raise Refusal(f"{', '.join(dirty[:3])}{' and more' if len(dirty) > 3 else ''} has changes not committed. "
                      "Commit or undo them, then move.")
    if mid_turn(root, thread_dir):
        raise Refusal(f"A session is mid-turn in {name}. Let it finish, then move.")
    rel_old = thread_dir.relative_to(zone_dir).as_posix()
    rel_new = (threads / name).relative_to(zone_dir).as_posix()
    swaps = [(f"{rel_old}/{name}", f"{rel_new}/{name}")]
    prefixes = [(rel_old, rel_new)]
    heads = ("", f"{zone_dir.name}/", f"Zones/{zone_dir.name}/")
    moved = zone_dir / rel_new
    new_note = moved / f"{name}.md"
    touched = {new_note, hub, target_hub}
    made_threads = not threads.exists()
    created = []
    unresolved = []

    def rewritten(path, text):
        """One note as the move leaves it: `path` is where the note is once the thread has moved. The write below and
        the plan (--plan) both ask this, so what a plan lists is what the move writes."""
        changed = relink(text, swaps, prefixes, name, name, heads)
        p_new = path.relative_to(zone_dir).as_posix()
        p_old = rel_old + p_new[len(rel_new):] if p_new == rel_new or p_new.startswith(rel_new + "/") else p_new
        changed = md_relink(changed, p_old, p_new, rel_old, rel_new, zone_dir, zone_dir.name, name, unresolved)
        if moved in path.parents or path.parent == moved:
            own = path == new_note
            changed = re.sub(r'(?m)^(%s): "?\[\[%s\]\]"?$' % ("project|parent" if own else "project", re.escape(project_dir.name)),
                             lambda m: f'{m.group(1)}: "[[{target.name}]]"', changed)
        if path == new_note:
            changed = re.sub(r"(?m)^updated: .*$", f"updated: {today}", changed, count=1)
            changed = dated_entry(changed, f"Moved from {project_dir.name} to {target.name}.", today)
        return changed

    if getattr(args, "plan", False):
        def after(path):                                    # where a tracked file is once the thread has moved
            try:
                return moved / path.relative_to(thread_dir).as_posix()
            except ValueError:
                return path
        cut, h2, subhead, block = cut_hub_line(hub, zone_dir.name, project_dir.name, name)
        if block is None or h2 is None:
            raise Refusal(f"The thread's line in {hub.name} cannot be told apart from the others, so it is not moved. "
                          "Make that line the only one that starts with a link to the thread, under a ## heading, then move it.")
        block = [relink(l, swaps, prefixes, name, name, heads) for l in block]
        texts = {hub: re.sub(r"(?m)^updated: .*$", f"updated: {today}", cut, count=1),
                 target_hub: re.sub(r"(?m)^updated: .*$", f"updated: {today}", put_hub_line(target_hub, h2, subhead, block), count=1)}
        rows = []
        if ledger.is_file():
            rows = [r for r in ledger.read_text(encoding="utf-8").split("\n") if r.startswith("|") and f"Threads/{name}/" in r]
        paths = [{"from": rel_old, "to": rel_new}]
        return plan_of(zone_dir, paths, notes, after, rewritten, texts=texts,
                       extra={"hubs": {"leaves": hub.relative_to(zone_dir).as_posix(), "enters": target_hub.relative_to(zone_dir).as_posix()},
                              "ledger_rows": len(rows)})
    clear_machine_made(zone_dir, thread_dir, made)
    try:
        threads.mkdir(exist_ok=True)
        git_ok(["mv", rel_old, rel_new], zone_dir)
        # The hub lines first, in memory: the old hub gives its line up, the new one takes it under the same heading.
        cut, h2, subhead, block = cut_hub_line(hub, zone_dir.name, project_dir.name, name)
        if block is None or h2 is None:
            raise Refusal(f"The thread's line in {hub.name} cannot be told apart from the others, so it is not moved. "
                          "Make that line the only one that starts with a link to the thread, under a ## heading, then move it.")
        block = [relink(l, swaps, prefixes, name, name, heads) for l in block]
        hub.write_text(re.sub(r"(?m)^updated: .*$", f"updated: {today}", cut, count=1), encoding="utf-8")
        target_hub.write_text(re.sub(r"(?m)^updated: .*$", f"updated: {today}",
                                     put_hub_line(target_hub, h2, subhead, block), count=1), encoding="utf-8")
        # The ledger rows for files inside the thread's folder go to the new project's ledger.
        if ledger.is_file():
            rows = ledger.read_text(encoding="utf-8").split("\n")
            mine_rows = [r for r in rows if r.startswith("|") and f"Threads/{name}/" in r]
            if mine_rows:
                ledger.write_text("\n".join(r for r in rows if r not in mine_rows), encoding="utf-8")
                touched.add(ledger)
                if not target_ledger.is_file():
                    if not target_ledger.parent.exists():
                        created.append(target_ledger.parent)
                    created.append(target_ledger)
                    target_ledger.parent.mkdir(exist_ok=True)
                    base = ledger.read_text(encoding="utf-8").split("\n")
                    first_row = next((i for i, r in enumerate(base) if r.startswith("|---")), len(base) - 1)
                    target_ledger.write_text("\n".join(base[:first_row + 1] + mine_rows) + "\n", encoding="utf-8")
                else:
                    body = target_ledger.read_text(encoding="utf-8").rstrip("\n")
                    target_ledger.write_text(body + "\n" + "\n".join(mine_rows) + "\n", encoding="utf-8")
                touched.add(target_ledger)
        for path in zone_notes(zone_dir):
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            changed = rewritten(path, text)
            if changed != text:
                touched.add(path)
                path.write_text(changed, encoding="utf-8")
        git_ok(["add", "-A", "--", rel_new] + [str(t.relative_to(zone_dir)) for t in touched if t.exists()], zone_dir)
        problem = wall_hook_problem(zone_dir)
        if problem:
            raise Refusal(f"{problem}, so nothing was committed.")
        # The trailers are what `undo` knows a move by, and where it finds the paths to put back.
        git(["commit", "-q", "-m", f"{name}: moved to {target.name}", "-m",
             f"{MOVE_ACTION}\n{MOVE_PATHS} {rel_old}={rel_new}", *commit_trailers()], zone_dir)
    except (GitError, Refusal, OSError) as exc:
        left = undo_failed_move(zone_dir, rel_old, rel_new, moved, touched, created, threads, made_threads)
        why = " ".join(str(exc).split())
        if left:
            raise Refusal(f"The move was not committed, and the folder could not be put back whole: {why} "
                          f"Left as they are: {', '.join(left[:5])}{' and %d more' % (len(left) - 5) if len(left) > 5 else ''}. "
                          "Look at git status in the zone.")
        raise Refusal(f"The move was not committed, so nothing changed: {why}")
    if not getattr(args, "no_state", False):
        move_state(root, zone_dir.name, name, rel_old, rel_new)
    said = [f"Moved the thread {name} from {project_dir.name} to {target.name} in {zone_dir.name}, and every link to it "
            "in the zone, in one commit."]
    meetings = root / "Wikis" / "Meetings" / "wiki"
    mentions = sorted(p.relative_to(root).as_posix() for p in meetings.rglob("*.md")
                      if re.search(r"\[\[[^\]]*\b%s\b" % re.escape(name), p.read_text(encoding="utf-8", errors="replace"))) \
        if meetings.is_dir() else []
    if mentions:
        said.append(f"Left as they are, in the Meetings wiki: {', '.join(mentions[:5])}"
                    f"{' and %d more' % (len(mentions) - 5) if len(mentions) > 5 else ''}.")
    if unresolved:
        said.append("Markdown links left as they are, because they could not be resolved plainly: "
                    + ", ".join(f"{n} ({l})" for n, l in unresolved[:5]) + (f" and {len(unresolved) - 5} more" if len(unresolved) > 5 else "") + ".")
    said.append("The status page's effort history follows it. If your assistant "
                f"keeps a memory pointer to it, or a cmux tab is open on it, point them at {rel_new}/{name}.md.")
    return "\n".join(said)


# --------------------------------------------------------------------------- layout

LAYOUT_ACTION = "Garrick-Action: layout"
LAYOUT_SAID_MOST = 8


def tracked_under(zone_dir, folder):
    """The files git tracks under `folder`, from the zone's top, as paths: never a link, which a move would follow."""
    rel = folder.relative_to(zone_dir).as_posix()
    listing = git_value(["ls-files", "-z", "--", rel], zone_dir)
    out = []
    for name in sorted(n for n in listing.split("\0") if n):
        path = zone_dir / name
        if path.is_symlink() or not path.is_file():
            continue
        out.append(name)
    return out


def names_file(text, rel, name):
    """Does a note name a file: by its path from the project, or by its name (a note also without the extension),
    as a whole word, written plainly or as a URL writes it."""
    forms = {rel, urllib.parse.quote(rel)}
    bare = {name, urllib.parse.quote(name)}
    if name.endswith(".md"):
        forms |= {rel[:-3]}
        bare |= {name[:-3]}
    # A bare name is not a path: a "/" before it is another folder's file of the same name.
    return any(re.search(r"(?<![\w.-])%s(?![\w])" % re.escape(f), text) for f in forms if f) or \
        any(re.search(r"(?<![\w./-])%s(?![\w])" % re.escape(f), text) for f in bare if f)


def ledger_rows_of(ledger, folder):
    """The rows of a ledger with the file each one names, resolved as drift.py does: under the ledger's own
    Deliverables folder, else from that folder's parent. A list of (row line, path)."""
    try:
        lines = ledger.read_text(encoding="utf-8").split("\n")
    except OSError:
        return []
    out = []
    for line in lines:
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip().strip("`") for c in line.strip().strip("|").split("|")]
        if len(cells) < 2 or not cells[1] or set(cells[0]) <= set("-: ") or cells[0].lower() == "date":
            continue
        first = folder / cells[1]
        out.append((line, first if first.exists() else folder.parent / cells[1]))
    return out


def thread_dirs_of(project_dir):
    """The project's threads that have a note, as folders. A thread folder that is a link is no thread of the project:
    the layout change would make or remove folders through it, in whatever the link points at."""
    found = [project_dir / "Threads" / n for n in children(project_dir / "Threads")]
    return [t for t in found if not t.is_symlink() and (t / f"{t.name}.md").is_file()]


def next_action_of(text):
    """The Next action cell of a thread note's Resume here block, or "" when it holds none or only the template's placeholder."""
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")] if line.strip().startswith("|") else []
        if len(cells) >= 2 and cells[0].lower() == "next action":
            value = " | ".join(cells[1:]).strip()
            return "" if not value or (value.startswith("<") and value.endswith(">")) else value
    return ""


def touched_key(zone_dir, tdir):
    """How recently a thread was touched, to sort on: its note's `updated:` day, then its last commit's time."""
    note = tdir / f"{tdir.name}.md"
    day = str(parse_frontmatter(note).get("updated") or "")
    stamp = git_value(["log", "-1", "--format=%ct", "--", tdir.relative_to(zone_dir).as_posix()], zone_dir).strip()
    return (day, int(stamp) if stamp.isdigit() else 0, tdir.name)


def resume_choices(zone_dir, project_dir):
    """The threads' Next actions, as (thread, text), most recently touched first: what a Join offers to open the hub's
    Resume here block with. The first is the one chosen when nothing else is said."""
    found = sorted(thread_dirs_of(project_dir), key=lambda t: touched_key(zone_dir, t), reverse=True)
    return [(t.name, next_action_of((t / f"{t.name}.md").read_text(encoding="utf-8", errors="replace"))) for t in found]


def through_a_link(project_dir, path):
    """Does a path go through a link, or out of the project? True when any part of it below the project folder is a
    symlink, or when its real place is not inside the project folder's real place. A path that is not there yet is
    read as far as it exists."""
    try:
        parts = Path(path).relative_to(project_dir).parts
    except ValueError:
        return True
    here = Path(project_dir)
    for part in parts:
        here = here / part
        if here.is_symlink():
            return True
    base = os.path.realpath(project_dir)
    real = os.path.realpath(path)
    return not (real == base or real.startswith(base + os.sep))


def refuse_linked_moves(zone_dir, project_dir, moves):
    """Refuse, moving nothing, when a source or a destination of a move goes through a link or out of the project:
    a file moved there would land in whatever the link points at, which may be another zone."""
    bad = [p for a, b in moves for p in (a, b) if through_a_link(project_dir, zone_dir / p)]
    if bad:
        raise Refusal(f"{say_files(dict.fromkeys(bad))} goes through a link or out of the project, so nothing was moved. "
                      "Replace the link with the folder itself, then change the layout.")


def plan_layout(zone_dir, project_dir, split=False, join=False):
    """(moves, left, what): the files to move as (from, to) paths from the zone's top, the files listed for the
    owner to place with why, and what the change is. Reads, writes nothing. A Split gives a file to a thread only
    when exactly one thread note names it, and no other note of the project does; a file that no thread names, or
    that two notes name, is listed, and Garrick does not guess a thread for it. A Join moves each thread's `Sources/`
    and `Deliverables/` into the project's: a name already taken there, in the project or by another thread's file
    going the same way, moves nothing for that file and lists it. Nothing is ever renamed or overwritten, and every
    target lies in the project's own folder."""
    rel = lambda p: p.relative_to(zone_dir).as_posix()                # noqa: E731
    pname = project_dir.name
    hub = project_dir / f"{pname}.md"
    threads = thread_dirs_of(project_dir)
    notes = {t.name: (t / f"{t.name}.md").read_text(encoding="utf-8", errors="replace") for t in threads}
    hub_text = hub.read_text(encoding="utf-8", errors="replace") if hub.is_file() else ""
    moves, left = [], []

    if join:
        taken = set()
        for t in threads:
            for name in tracked_under(zone_dir, t):
                inside = Path(name).relative_to(rel(t)).as_posix()
                if Path(inside).parts[0] not in PAPERS or Path(inside).name == ".gitkeep" or inside == "Deliverables/published.md":
                    continue
                target = f"{rel(project_dir)}/{inside}"
                if (zone_dir / target).exists() or target.casefold() in taken:
                    left.append((name, "the project has a file of that name already"))
                else:
                    taken.add(target.casefold())
                    moves.append((name, target))
        refuse_linked_moves(zone_dir, project_dir, moves)
        return moves, left, f"{pname} becomes one job"

    if is_heading(project_dir):
        raise Refusal(f"{pname} is separate jobs already.")
    for inside in top_files_of(zone_dir, project_dir):
        namers = [t.name for t in threads if names_file(notes[t.name], inside, Path(inside).name)]
        hub_names = names_file(hub_text, inside, Path(inside).name)
        target = f"{rel(project_dir)}/Threads/{namers[0]}/{inside}" if namers else ""
        if len(namers) == 1 and not hub_names and (zone_dir / target).exists():
            left.append((f"{rel(project_dir)}/{inside}", "the thread has a file of that name already"))
        elif len(namers) == 1 and not hub_names:
            moves.append((f"{rel(project_dir)}/{inside}", target))
        else:
            left.append((f"{rel(project_dir)}/{inside}", "no thread names it" if not namers else
                         "more than one note names it" if len(namers) > 1 or hub_names else ""))
    refuse_linked_moves(zone_dir, project_dir, moves)
    return moves, left, f"{pname} becomes separate jobs"


def top_files_of(zone_dir, project_dir):
    """The project's own files, as paths from the project: not its hub, its ledger, its threads or its archive."""
    pname = project_dir.name
    out = []
    for name in tracked_under(zone_dir, project_dir):
        inside = Path(name).relative_to(project_dir.relative_to(zone_dir).as_posix()).as_posix()
        if Path(inside).parts[0] in ("Threads", "archive") or inside in (f"{pname}.md", "Deliverables/published.md") \
                or Path(inside).name == ".gitkeep":
            continue
        out.append(inside)
    return out


def say_files(names):
    names = list(names)
    return ", ".join(names[:LAYOUT_SAID_MOST]) + (f" and {len(names) - LAYOUT_SAID_MOST} more" if len(names) > LAYOUT_SAID_MOST else "")


def text_keeps_resume_block(text):
    return any(l.strip().lower() == RESUME_HEADING.lower() for l in text.splitlines())


def hub_keeps_resume_block(hub):
    try:
        return text_keeps_resume_block(hub.read_text(encoding="utf-8"))
    except OSError:
        return False


def hub_as_one_job(root, text, today, next_action):
    """The hub text of a project joined into one job: no `layout: thread-first`, the Sources and Deliverables rows back
    in its contents table, and a Resume here block that opens with `next_action`, unless the hub holds one already."""
    front = re.match(r"---\n.*?\n---\n", text, re.S)
    if front:
        head = re.sub(r"(?m)^layout:[ \t]*thread-first[ \t]*\n", "", front.group(0))
        head = re.sub(r"(?m)^updated: .*$", f"updated: {today}", head, count=1)
        text = head + text[front.end():]
    if not re.search(r"(?m)^\| `Sources/` \|", text):
        text = text.replace("| `Threads/` | One folder per thread, each with its resume point and its own `Sources/` and `Deliverables/` |",
                            "| `Sources/` | Material received |\n| `Threads/` | One folder per thread, each with its resume point |\n"
                            "| `Deliverables/` | What is made for the project, `YYMMDD - <name>.<ext>` |")
    if not text_keeps_resume_block(text):
        section = hub_resume_section(root)
        if next_action:
            section = re.sub(r"(?m)^\| Next action \|.*$", lambda m: f"| Next action | {next_action} |", section, count=1)
        text = re.sub(r"(?m)^## Threads$", lambda m: section + "\n## Threads", text, count=1) \
            if re.search(r"(?m)^## Threads$", text) else text.rstrip("\n") + "\n\n" + section
    return text


def cmd_layout(root, args, today):
    """Split a project into separate jobs, or join it into one job, and carry the files with their ledger rows and
    links, in one commit. `--check` says the plan and writes nothing. A Split gives a file to a thread only when
    exactly one thread note names it; a Join moves each thread's papers into the project's, and a name already taken
    there is listed, never renamed or overwritten. A Join on a project that is one job already moves the papers its
    threads kept apart, and changes no note but the links. Nothing leaves the project, so nothing leaves the zone. A
    commit that is refused leaves every file and ledger row where it was."""
    refuse_papers(args)
    if args.thread:
        raise Refusal(SWITCH_SAID)
    split, join = bool(getattr(args, "heading", False)), bool(getattr(args, "join", False))
    if split == join:
        raise Refusal("Say what changes: --split for separate jobs, or --join for one job.")
    zone_dir, project_dir, _thread_dir, note = target_of(root, args)
    pname = project_dir.name
    hub = project_dir / f"{pname}.md"
    rel = lambda p: p.relative_to(zone_dir).as_posix()                # noqa: E731
    prefix = rel(project_dir) + "/"
    was_split = is_heading(project_dir)
    threads = thread_dirs_of(project_dir)
    if join and not was_split and not any((t / k).is_dir() for t in threads for k in PAPERS):
        raise Refusal(f"{pname} is one job already.")
    if args.resume_from and not join:
        raise Refusal("--resume-from is for --join: it names the thread whose Next action opens the hub's Resume here block.")
    choices = resume_choices(zone_dir, project_dir) if join else []
    if join and args.resume_from and args.resume_from.casefold() not in [n.casefold() for n, _ in choices]:
        raise Refusal(f"{args.resume_from} is not a thread of {pname}.")
    chosen = next((n for n, _ in choices if n.casefold() == (args.resume_from or "").casefold()), choices[0][0] if choices else "")
    next_action = dict(choices).get(chosen, "")
    opens = join and was_split and not hub_keeps_resume_block(hub)
    moves, left, what = plan_layout(zone_dir, project_dir, split=split, join=join)
    if any(not (a.startswith(prefix) and b.startswith(prefix)) for a, b in moves):
        raise Refusal("A move would leave the project, so nothing is changed.")
    lines = [f"{what}: {len(moves)} file{'' if len(moves) == 1 else 's'} to move, {len(left)} left for you to place."]
    if moves:
        lines.append("Moves: " + say_files(f"{a[len(prefix):]} to {b[len(prefix):]}" for a, b in moves) + ".")
    if left:
        lines.append("Left for you to place: " + say_files(f"{n[len(prefix):]} ({why})" for n, why in left) + ".")
    if split and hub_keeps_resume_block(hub):
        lines.append("The hub still holds a Resume here block, and separate jobs hold none: move it into a thread, or close it as an Outcome.")
    if opens:
        lines.append(f"The hub gets a Resume here block back, opening with the Next action of {chosen}." if chosen
                     else "The hub gets a Resume here block back.")
    if getattr(args, "check", False):
        if getattr(args, "json", False):                              # the plan as data, for the page's dialog: still writes nothing
            return json.dumps({"what": what, "heading": split, "join": join, "thread": "", "papers": "",
                               "moves": [[a[len(prefix):], b[len(prefix):]] for a, b in moves],
                               "left": [[n[len(prefix):], why] for n, why in left],
                               "resume_block": bool(split and hub_keeps_resume_block(hub)),
                               "opens_resume": bool(opens), "resume_from": chosen,
                               "next_actions": [[n, a] for n, a in choices],
                               "threads": [t.name for t in threads]}, ensure_ascii=False)
        return "\n".join(lines + ["Nothing was changed."])
    if not moves and not split and not (join and was_split):
        return "\n".join(lines + ["Nothing was changed."])
    made = preflight(zone_dir, project_dir, "change the layout")
    moved_abs = {zone_dir / a: zone_dir / b for a, b in moves}
    changes = {}                                                      # where a file is to be written -> its new text
    # The ledger rows follow their files, to the ledger of the folder the file moved into. A row's share
    # destination is never touched: only the ledger it sits in changes.
    new_rows = {}
    for base in [project_dir] + (threads if join else []):
        ledger = base / "Deliverables" / "published.md"
        if not ledger.is_file():
            continue
        text = ledger.read_text(encoding="utf-8")
        keep = text.split("\n")
        for row, path in ledger_rows_of(ledger, base / "Deliverables"):
            dst = moved_abs.get(path)
            if dst is None:
                continue
            under = dst.relative_to(project_dir).parts
            dest = project_dir / "Threads" / under[1] if under[0] == "Threads" else project_dir
            if dest != base:
                keep.remove(row)
                new_rows.setdefault(dest / "Deliverables" / "published.md", []).append((ledger, row))
        if "\n".join(keep) != text:
            changes[ledger] = "\n".join(keep)
    for dest, rows in new_rows.items():
        if dest in changes:
            body = changes[dest]
        elif dest.is_file():
            body = dest.read_text(encoding="utf-8")
        else:
            src = rows[0][0].read_text(encoding="utf-8").split("\n")
            first = next((i for i, r in enumerate(src) if r.startswith("|---")), len(src) - 1)
            body = "\n".join(src[:first + 1]) + "\n"
        changes[dest] = body.rstrip("\n") + "\n" + "\n".join(r for _, r in rows) + "\n"
    # The notes as they are now, read before anything moves: the links in them are pointed at the new places once the files are there.
    notes_text = {}
    for path in zone_notes(zone_dir):
        try:
            notes_text[path] = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
    dirty = uncommitted(zone_dir, [project_dir])
    if dirty:
        raise Refusal(f"{', '.join(dirty[:3])}{' and more' if len(dirty) > 3 else ''} has changes not committed. "
                      "Commit or undo them, then change the layout.")
    if mid_turn(root, project_dir):
        raise Refusal(f"A session is mid-turn in {pname}. Let it finish, then change the layout.")
    clear_machine_made(zone_dir, project_dir, made)
    unresolved = []
    heads = ("", f"{zone_dir.name}/", f"Zones/{zone_dir.name}/")
    outside = []
    try:
        refuse_linked_moves(zone_dir, project_dir, moves)             # again, now the work starts
        for a, b in moves:
            refuse_linked_moves(zone_dir, project_dir, [(a, b)])      # and before each one
            (zone_dir / b).parent.mkdir(parents=True, exist_ok=True)
            git_ok(["mv", "--", a, b], zone_dir)
        for folder in (threads if split else []):                     # separate jobs: each thread keeps both folders
            for kind in PAPERS:
                (folder / kind).mkdir(parents=True, exist_ok=True)
                if not any((folder / kind).iterdir()):
                    (folder / kind / ".gitkeep").touch()
        # The links, as they were written, pointed at the new places, in every note of the zone.
        for path, text in notes_text.items():
            changed = changes.pop(path, text)
            for a, b in moves:
                noext = lambda x: x[:-3] if x.endswith(".md") else x     # noqa: E731
                swaps = [(a, b), (noext(a), noext(b))]
                if path == hub or project_dir in path.parents:
                    swaps += [(a[len(prefix):], b[len(prefix):]), (noext(a[len(prefix):]), noext(b[len(prefix):]))]
                changed = relink(changed, swaps, [], Path(a).name, Path(b).name, heads)
                changed = md_relink(changed, rel(path), rel(moved_abs.get(path, path)), a, b, zone_dir, zone_dir.name,
                                    Path(a).stem, unresolved)
            here = moved_abs.get(path, path)
            if changed != text or here in changes:
                changes[here] = changed
        if split:
            text = changes.get(hub) or hub.read_text(encoding="utf-8")
            text = re.sub(r"(?m)^(status: .*)$", r"\1\nlayout: thread-first", text, count=1)
            changes[hub] = re.sub(r"(?m)^updated: .*$", f"updated: {today}", text, count=1)
        elif join and was_split:
            changes[hub] = hub_as_one_job(root, changes.get(hub) or hub.read_text(encoding="utf-8"), today, next_action)
        outside = [p for p in changes if project_dir not in p.parents and p != hub]
        present = [p for p in outside if p.exists()]
        dirty = uncommitted(zone_dir, present) if present else []       # a note elsewhere in the zone that a link change would touch
        if dirty:
            raise Refusal(f"{', '.join(dirty[:3])}{' and more' if len(dirty) > 3 else ''} has changes not committed. "
                          "Commit or undo them, then change the layout.")
        linked = [p for p in changes if p.is_symlink() or any(q.is_symlink() for q in p.parents if zone_dir in q.parents)]
        if linked:                                                     # never write through a link, inside or out of the zone
            raise Refusal(f"{', '.join(rel(p) for p in linked[:3])} is a link, so the layout was not changed. "
                          "Replace the link with the file itself, then change the layout.")
        for path, text in changes.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        if join:
            # Each thread's papers go once they hold nothing; what was left stays. A ledger goes once it has no row.
            for tdir in threads:
                ledger = tdir / "Deliverables" / "published.md"
                if ledger.is_file() and not ledger_rows_of(ledger, tdir / "Deliverables"):
                    git_ok(["rm", "-q", "-f", "--", rel(ledger)], zone_dir)
                for kind in PAPERS:
                    folder = tdir / kind
                    if folder.is_dir() and not [n for n in tracked_under(zone_dir, folder) if Path(n).name != ".gitkeep"] \
                            and not any(f.name != ".gitkeep" for f in folder.rglob("*") if f.is_file()):
                        shutil.rmtree(folder, ignore_errors=True)
            for kind in PAPERS:                                        # the project keeps both folders, as one job always has
                (project_dir / kind).mkdir(exist_ok=True)
                if not any((project_dir / kind).iterdir()):
                    (project_dir / kind / ".gitkeep").touch()
        git_ok(["add", "-A", "--", rel(project_dir)] + [rel(p) for p in outside], zone_dir)
        problem = wall_hook_problem(zone_dir)
        if problem:
            raise Refusal(f"{problem}, so nothing was committed.")
        git(["commit", "-q", "-m", f"{pname}: layout, {what}", "-m", f"{LAYOUT_ACTION}\nGarrick-Moved-Files: {len(moves)}", *commit_trailers()], zone_dir)
    except (GitError, Refusal, OSError) as exc:
        git_value(["reset", "-q"], zone_dir)
        git_value(["checkout", "HEAD", "--", rel(project_dir)] + [rel(p) for p in outside], zone_dir)
        git_value(["clean", "-fdq", "--", rel(project_dir)], zone_dir)
        raise Refusal("The change was not committed, so every file and ledger row is where it was: " + " ".join(str(exc).split()))
    commit = git_value(["rev-parse", "--short", "HEAD"], zone_dir).strip()
    lines[0] = lines[0].replace(" to move,", " moved,")
    lines.append(f"Changed in commit {commit}. To take it back: scaffold.py undo --zone {zone_dir.name} --commit {commit}.")
    if unresolved:
        lines.append("Markdown links left as they are, because they could not be resolved plainly: "
                     + ", ".join(f"{n} ({l})" for n, l in unresolved[:5]) + ".")
    return "\n".join(lines)


def open_lines(zone_dir, paths, bare):
    """The open lines of the zone's Todo.md that link to one of `paths` (from
    the zone's top, without .md), or to one of `bare`, names that no other
    note in the zone has."""
    todo = zone_dir / "Todo.md"
    if not todo.is_file():
        return []
    heads = ("", f"{zone_dir.name}/", f"Zones/{zone_dir.name}/")
    out = []
    for line in todo.read_text(encoding="utf-8").splitlines():
        if not re.match(r"\s*- \[ \]", line):
            continue
        targets = [t.split("|")[0].split("#")[0].strip().removesuffix(".md")
                   for t in re.findall(r"\[\[([^\]]+)\]\]", line)]
        if any(t in bare or any(t == h + p for h in heads for p in paths) for t in targets):
            out.append(line)
    return out


def cmd_delete(root, args, today):
    zone_dir, project_dir, thread_dir, note = target_of(root, args)
    is_thread = thread_dir is not None
    folder = thread_dir if is_thread else project_dir
    name = folder.name
    files = [Path(d) / f for d, _, fs in os.walk(folder) for f in fs if ".git" not in Path(d).parts]
    threads = children(project_dir / "Threads") if not is_thread else []
    rel = folder.relative_to(zone_dir).as_posix()
    paths = {f"{rel}/{name}"} | {f"{rel}/Threads/{t}/{t}" for t in threads}
    stems = [n.stem.lower() for n in zone_notes(zone_dir)]
    bare = {n for n in {name} | set(threads) if stems.count(n.lower()) <= 1}
    lines = open_lines(zone_dir, paths, bare)
    hub = project_dir / f"{project_dir.name}.md"
    hub_line = None
    if is_thread and hub.is_file():
        hub_line = next((l for l in hub.read_text(encoding="utf-8").splitlines()
                         if re.search(r"\[\[%s/Threads/%s/%s(\|[^\]]*)?\]\]" % tuple(map(re.escape, (project_dir.name, name, name))), l)), None)
    what = f"{project_dir.name}, {name}" if is_thread else name
    plan = [f"Deleting {what} would remove {rel}/ ({len(files)} file{'s' if len(files) != 1 else ''})"
            + (f", with its threads {', '.join(threads)}" if threads else "")
            + (", its line in the hub" if hub_line else "")
            + (f", and {len(lines)} open line{'s' if len(lines) != 1 else ''} in Todo.md" if lines else "") + "."]
    plan += [f"  {l.strip()}" for l in lines]
    plan.append("Meetings pages stay, and the zone's history keeps it all: a revert brings it back. "
                "To set it aside instead, park it; to close it with a record, finish it.")
    if args.confirm is None:
        plan.append(f'Nothing was deleted. To delete it, run again with --confirm "{name}".')
        return "\n".join(plan)
    if args.confirm != name:
        raise Refusal(f'--confirm must name it exactly: "{name}". Nothing was deleted.')
    todo = zone_dir / "Todo.md"
    made = preflight(zone_dir, folder, "delete")
    dirty = uncommitted(zone_dir, [folder] + [p for p in (hub, todo) if p.is_file()])
    if dirty:
        raise Refusal(f"{', '.join(dirty[:3])} has changes not committed. Commit or undo them, then delete.")
    if mid_turn(root, folder):
        raise Refusal(f"A session is mid-turn in {name}. Let it finish, then delete.")
    clear_machine_made(zone_dir, folder, made)
    git_ok(["rm", "-r", "-q", "--", rel], zone_dir)
    if folder.exists():
        remove_empty(folder)                                       # git took every file; only empty folders stay
    touched = []
    if hub_line:
        text = hub.read_text(encoding="utf-8")
        hub.write_text(text.replace(hub_line + "\n", "", 1), encoding="utf-8")
        touched.append(hub)
    if lines:
        text = todo.read_text(encoding="utf-8").splitlines(keepends=True)
        gone = set(lines)
        todo.write_text("".join(l for l in text if l.rstrip("\n") not in gone), encoding="utf-8")
        touched.append(todo)
    if touched:
        git_ok(["add", "--"] + [str(t.relative_to(zone_dir)) for t in touched], zone_dir)
    body = "\n".join(["Removed:"] + [f"- {rel}/ ({len(files)} files)"] + (["- the hub's line"] if hub_line else [])
                     + [f"- {l.strip()}" for l in lines])
    try:
        problem = wall_hook_problem(zone_dir)
        if problem:
            raise Refusal(f"{problem}, so nothing was committed.")
        git(["commit", "-q", "-m", f"{what}: deleted\n\n{body}", *commit_trailers()], zone_dir)
    except (GitError, Refusal) as exc:
        git_value(["reset", "-q"], zone_dir)
        git_value(["checkout", "HEAD", "--", rel] + [str(t.relative_to(zone_dir)) for t in touched], zone_dir)
        raise Refusal(f"The deletion was not committed, so nothing changed: {' '.join(str(exc).split())}")
    commit = git_value(["rev-parse", "--short", "HEAD"], zone_dir).strip()
    said = [f"Deleted {what} in commit {commit}."]
    said += [f"  removed: {l.strip()}" for l in lines]
    said.append(f"To bring it back: scaffold.py undo --zone {zone_dir.name} --commit {commit}. If your assistant "
                "keeps a memory pointer to it, delete that too.")
    return "\n".join(said)


def cmd_undo(root, args, today):
    """Revert a rename, a move, a deletion or a creation this script committed, while it
    is still the zone's last commit: anything committed since might depend on it."""
    zone_dir = find_zone(root, args.zone)
    head = git_value(["rev-parse", "HEAD"], zone_dir).strip()
    wanted = git_value(["rev-parse", "--verify", "-q", args.commit + "^{commit}"], zone_dir).strip()
    if not wanted:
        raise Refusal(f"{zone_dir.name} has no commit {args.commit}.")
    if wanted != head:
        raise Refusal(f"{args.commit} is no longer the last commit in {zone_dir.name}, so it is not undone here. "
                      "Ask for it to be reverted by hand.")
    subject = git_value(["log", "-1", "--format=%s"], zone_dir).strip()
    body = git_value(["log", "-1", "--format=%B"], zone_dir)
    is_move = MOVE_ACTION in body.splitlines()                 # a move is known by its trailer, never by its subject
    if not (is_move or re.search(r": (deleted|renamed .+|new thread .+)$|^New project .+$|: layout, .+$", subject)):
        raise Refusal(f"{args.commit} is not a rename, a move, a deletion or a new project or thread: {subject}")
    if git_value(["status", "--porcelain", "--untracked-files=no"], zone_dir).strip():
        raise Refusal(f"{zone_dir.name} has changes not committed. Commit or undo them first.")
    git_ok(["revert", "--no-edit", head], zone_dir)
    if is_move and not getattr(args, "no_state", False):
        paths = next((l.split(":", 1)[1].strip() for l in body.splitlines() if l.startswith(MOVE_PATHS)), "")
        was, _, now = paths.partition("=")
        if was and now:
            move_state(root, zone_dir.name, was.rsplit("/", 1)[-1], now, was)
    return f"Undone: {subject}."


# --------------------------------------------------------------------------- checkpoint


# What each kind of item may carry, and what it must. A field the kind does
# not take is refused by name, as operations.py refuses one the verb does not
# declare: an item that holds something nobody reads has no source for it.
CHECKPOINT_ITEM_FIELDS = {
    "made": ("path", "at"),
    "decided": ("said", "by", "at"),
    "considering": ("text", "said", "at"),
    "next": ("text", "said", "by", "at"),
    "action": ("text", "said", "date", "at"),
    "deadline": ("date", "said", "at"),
    "incomplete": ("text", "at"),
}
# The source each kind needs: a name for a field it must carry, a tuple for
# one of several. Nothing in a checkpoint stands without one.
CHECKPOINT_NEEDS = {
    "made": ("path",),
    "decided": ("said",),
    "considering": (("text", "said"),),
    "next": ("text",),
    "action": ("text",),
    "deadline": ("date",),
    "incomplete": ("text",),
}
# A date is an ISO date and nothing else, and it is only ever written because
# somebody said it: the kinds that may carry one, and the field that sources it.
CHECKPOINT_DATED = {"action": "said", "deadline": "said"}
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
# An item id goes into an HTML comment and is read back out of it, so it is
# letters, digits and hyphens and nothing else: an id with a space in it would
# make the block unparsable the next time it was read.
ITEM_ID = re.compile(r"[A-Za-z][A-Za-z0-9-]{0,15}\Z")
MEETINGS_WIKI = ("Wikis", "Meetings")
CHECKPOINT_TEXT_MAX = 400
_WIKILINK_RE = re.compile(r"\[\[([^\]|#\n]+)")
_MDLINK_RE = re.compile(r"\[[^\]\n]*\]\(([^)\s]+)\)")
_TICKED_RE = re.compile(r"`([^`\n]+)`")
_GLOB_RE = re.compile(r"[*?\[\]]")
_LIST_RE = re.compile(r"^(?:[-*+]\s*(?:\[[ xX]\]\s*)?|#{1,6}\s+|>\s*)+")

# One line for each way a checkpoint is refused, by the name the reply carries
# in `refused`. The precheck's words are operations.py's, so that a writer
# reads the same sentence for a block that has moved as for a Todo line that
# has: nothing here composes a second version of them.
CHECKPOINT_WHY = {
    "request": "A checkpoint is one JSON object on standard input, and {why}.",
    "nothing": "There is nothing to checkpoint: no items, and nothing to drop.",
    "id": "{id} {why}, and an item keeps the id and the kind it was written with: "
          "drop it, or send the new one on its own.",
    "kind": "A checkpoint item is one of {kinds}, and {kind} is none of them.",
    "field": "A {label} item takes {takes}, and it was sent {names}.",
    "source": "Every checkpoint item names its source, and this {label} item has no {needs}.",
    "text": "A checkpoint item is one line of its own, and its {name} holds {what}.",
    "date": "A date in a checkpoint is an ISO date and the words it was given in, and this {label} item {why}.",
    "made": "`{path}` is not there, so there is nothing to record.",
    "meetings": "A checkpoint carries no meeting material, and {link} leads into the Meetings wiki. "
                "A decision that rests on a meeting waits for the wrap.",
    "considering": "{id} is a Considering item, and nothing promotes one: a decision carries its own words, "
                   "so send what was said rather than that item's id.",
    "done": "{name} is finished, so there is nothing to checkpoint: its outcome is the record now.",
    "parked": "{name} is parked, so there is nothing to checkpoint. Wake it first.",
    "no-resume": "{note} has no {heading} block, so there is nothing to checkpoint under.",
    "invalid": "The checkpoint in {note} {why}. It is left exactly as it is: read it, "
               "and wrap the thread to settle it.",
}


class CheckpointRefusal(Refusal):
    """A refusal with a name, so that a caller can tell them apart without
    reading the sentence."""

    def __init__(self, name, said):
        super().__init__(said)
        self.name = name


def checkpoint_request(text):
    """The one JSON object a checkpoint arrives as."""
    try:
        req = json.loads(text or "")
    except ValueError:
        raise CheckpointRefusal("request", CHECKPOINT_WHY["request"].format(why="this is not JSON"))
    if not isinstance(req, dict):
        raise CheckpointRefusal("request", CHECKPOINT_WHY["request"].format(why="this is not an object"))
    if req.get("verb") not in (None, "checkpoint"):
        raise CheckpointRefusal("request", CHECKPOINT_WHY["request"].format(
            why="its verb is %s" % str(req.get("verb"))[:40]))
    for name in ("items", "drop"):
        if not isinstance(req.get(name, []), list):
            raise CheckpointRefusal("request", CHECKPOINT_WHY["request"].format(why="its %s is not a list" % name))
    if any(not isinstance(item, dict) for item in req.get("items") or []):
        raise CheckpointRefusal("request", CHECKPOINT_WHY["request"].format(why="an item is not an object"))
    return req


def one_line(value):
    """A field as a block may carry it: one line, no list or heading marker in
    front of it, so an item can never become a task line or a heading."""
    return _LIST_RE.sub("", " ".join(str(value).split())).strip()


def meetings_link(root, value):
    """The link or path in `value` that leads into the Meetings wiki, or None.
    A path that names the wiki, and a bare `[[name]]` a page in it answers to:
    the checkpoint carries no meeting material, so neither goes in."""
    wiki = root.joinpath(*MEETINGS_WIKI)
    for target in _WIKILINK_RE.findall(value) + _MDLINK_RE.findall(value) + _TICKED_RE.findall(value):
        bare = target.strip().split("|")[0].split("#")[0].strip().rstrip("/")
        if not bare or "://" in bare:
            continue
        parts = [p for p in re.split(r"[\\/]+", bare) if p not in ("", ".")]
        if not parts:
            continue
        lower = [p.lower() for p in parts]
        if any(lower[i:i + 2] == [m.lower() for m in MEETINGS_WIKI] for i in range(len(lower) - 1)):
            return target.strip()
        if lower[0] == MEETINGS_WIKI[1].lower():
            return target.strip()
        if len(parts) == 1 and wiki.is_dir() and not _GLOB_RE.search(parts[0]):
            name = parts[0] if parts[0].lower().endswith(".md") else parts[0] + ".md"
            if next(wiki.rglob(name), None) is not None:
                return target.strip()
    return None


def checkpoint_who(by):
    return "the user" if one_line(by).lower() in ("user", "the user", "me") else one_line(by)


def checkpoint_whose(by):
    who = checkpoint_who(by)
    return who + ("'" if who.endswith("s") else "'s")


def checkpoint_text(item):
    """What one item's line holds, after its kind and before its id: the file,
    the words, the date, each with the source the kind needs."""
    kind = item["kind"]
    at = one_line(item.get("at") or "")
    said = one_line(item.get("said") or "")
    text = one_line(item.get("text") or "")
    by = one_line(item.get("by") or "")
    if kind == "made":
        line = "`%s`" % one_line(item["path"])
        return line + (", saved %s" % at if at else "")
    if kind == "decided":
        line = '"%s"' % said
        if by:
            line += ", %s" % checkpoint_who(by)
        if at:
            line += "%s at %s" % ("" if by else ",", at)
        return line
    if kind == "considering":
        line = text or '"%s"' % said
        line += "; not decided"
        if text and said:
            line += ', in their words "%s"' % said
        return line
    if kind == "next":
        return text + (", %s" % checkpoint_whose(by) if by else "")
    if kind == "action":
        return "%s, %s" % (text, "by " + item["date"] if item.get("date") else "no date given")
    if kind == "deadline":
        return '%s, "%s"' % (item["date"], said)
    return text                                                     # incomplete


def checkpoint_shape(req):
    """Every item of the request read as a kind with its fields, refused by
    name where a kind, a field, a source or a date is wrong. Nothing outside
    the request is read here."""
    kinds = ", ".join(k for k, _, _ in CHECKPOINT_KINDS)
    out = []
    for item in req.get("items") or []:
        kind = str(item.get("kind") or "").strip().lower()
        if kind not in CHECKPOINT_ITEM_FIELDS:
            raise CheckpointRefusal("kind", CHECKPOINT_WHY["kind"].format(
                kinds=kinds, kind="`%s`" % str(item.get("kind"))[:40] if item.get("kind") else "nothing"))
        label = CHECKPOINT_LABELS[kind]
        takes = CHECKPOINT_ITEM_FIELDS[kind]
        given = one_line(item.get("id") or "")
        if given and not ITEM_ID.fullmatch(given):
            raise CheckpointRefusal("id", CHECKPOINT_WHY["id"].format(
                id="`%s`" % given[:40], why="is not an id a block can carry back"))
        extra = sorted(k for k in item if k not in takes and k not in ("kind", "id"))
        if extra:
            raise CheckpointRefusal("field", CHECKPOINT_WHY["field"].format(
                label=label, takes=" and ".join(takes), names=" and ".join(extra)))
        for need in CHECKPOINT_NEEDS[kind]:
            names = (need,) if isinstance(need, str) else need
            if not any(one_line(item.get(n) or "") for n in names):
                raise CheckpointRefusal("source", CHECKPOINT_WHY["source"].format(
                    label=label, needs=" or ".join(names)))
        for name in takes:
            value = item.get(name)
            if value is None:
                continue
            if not isinstance(value, str):
                raise CheckpointRefusal("text", CHECKPOINT_WHY["text"].format(
                    name=name, what="something that is not text"))
            if "<!--" in value or "-->" in value:
                raise CheckpointRefusal("text", CHECKPOINT_WHY["text"].format(
                    name=name, what="an HTML comment, which is where an item keeps its id"))
            if len(one_line(value)) > CHECKPOINT_TEXT_MAX:
                raise CheckpointRefusal("text", CHECKPOINT_WHY["text"].format(
                    name=name, what="more than %d characters" % CHECKPOINT_TEXT_MAX))
        date = one_line(item.get("date") or "")
        if kind in CHECKPOINT_DATED and (date or kind == "deadline"):
            if not ISO_DATE.match(date):
                raise CheckpointRefusal("date", CHECKPOINT_WHY["date"].format(
                    label=label, why="gives %s" % ("`%s`" % date[:40] if date else "none")))
            try:
                datetime.date.fromisoformat(date)
            except ValueError:
                raise CheckpointRefusal("date", CHECKPOINT_WHY["date"].format(
                    label=label, why="gives `%s`, which is not a day" % date[:40]))
            if not one_line(item.get(CHECKPOINT_DATED[kind]) or ""):
                raise CheckpointRefusal("date", CHECKPOINT_WHY["date"].format(
                    label=label, why="has a date nobody is recorded as giving"))
        clean = {"kind": kind, "id": given or None}
        clean.update({name: one_line(item[name]) for name in takes if item.get(name) is not None})
        clean["body"] = checkpoint_text(clean)
        out.append(clean)
    return out


def checkpoint_world(root, project_dir, items):
    """The checks a request cannot answer on its own: a Made file that is
    there, and no link into the Meetings wiki."""
    for item in items:
        if item["kind"] == "made":
            path = item["path"]
            where = Path(path).expanduser() if path.startswith(("~", "/")) else project_dir / path
            if not where.exists():
                raise CheckpointRefusal("made", CHECKPOINT_WHY["made"].format(path=path))
        for name, value in item.items():
            if name in ("kind", "id", "body") or not isinstance(value, str):
                continue
            link = meetings_link(root, value)
            if link:
                raise CheckpointRefusal("meetings", CHECKPOINT_WHY["meetings"].format(link="`%s`" % link))


def checkpoint_merge(items, sent, drop):
    """The items a block holds once the request is applied.

    An item is replaced by its id; one that says the same thing as an item
    already there, read as `same_action` reads a Todo line, is merged into it,
    which is the backstop for a reworded duplicate; anything else is added
    with an id of its own. Only an id under `drop` removes an item, so a
    second writer cannot lose the first one's work."""
    kept = [dict(item) for item in items if item["id"] not in drop]
    for item in sent:
        where = next((i for i, k in enumerate(kept) if k["id"] == item["id"]), -1) if item["id"] else -1
        if where < 0 and item["kind"] in CHECKPOINT_ONE:
            where = next((i for i, k in enumerate(kept) if k["kind"] == item["kind"]), -1)
        if where < 0:
            mark = same_action(item["body"])
            where = next((i for i, k in enumerate(kept)
                          if k["kind"] == item["kind"] and same_action(k["text"]) == mark), -1)
        if where >= 0:
            item_id = kept[where]["id"]
            kept[where] = {"id": item_id, "kind": item["kind"], "text": item["body"],
                           "line": checkpoint_item_line(item["kind"], item["body"], item_id)}
        else:
            item_id = checkpoint_id(kept, item["kind"])
            kept.append({"id": item_id, "kind": item["kind"], "text": item["body"],
                         "line": checkpoint_item_line(item["kind"], item["body"], item_id)})
    order = {kind: i for i, (kind, _, _) in enumerate(CHECKPOINT_KINDS)}
    return sorted(kept, key=lambda k: order.get(k["kind"], len(order)))


def checkpoint_id(items, kind):
    """The id a new item takes: the kind's stem for the kinds a block holds one
    of, and the stem with the lowest number nobody else has for the rest."""
    stem = CHECKPOINT_STEMS[kind]
    if kind in CHECKPOINT_ONE:
        return stem
    taken = {item["id"] for item in items}
    n = 1
    while "%s%d" % (stem, n) in taken:
        n += 1
    return "%s%d" % (stem, n)


def checkpoint_state(text):
    """What a reply says is in the note now: the resume point's hash, the
    block's key and time, and its items with their ids."""
    block = read_checkpoint(text) or {}
    return {"base": resume_hash(text), "key": block.get("key"), "at": block.get("at"),
            "items": [{"id": i["id"], "kind": i["kind"], "line": i["line"]} for i in block.get("items", [])]}


def checkpoint_read(name, text, state):
    """The reply to `read: true`: what is there, whether it can be resumed
    from, and one line saying so. It never refuses, because Open calls it on
    whatever the note holds."""
    block = read_checkpoint(text)
    reply = {"ok": True, "wrote": False, "read": True, "valid": False, "stale": False, "why": ""}
    reply.update(state)
    if block is None:
        reply["say"] = "No checkpoint in %s." % name
        return reply
    reply["valid"] = bool(block["valid"])
    reply["why"] = block["why"]
    if not block["valid"]:
        reply["say"] = "The checkpoint in %s %s. Read it; do not resume from it." % (name, block["why"])
        return reply
    reply["stale"] = block["base"] != state["base"]
    when = said_time(block["at"]).split(" on ")[0]
    if reply["stale"]:
        reply["say"] = ("A checkpoint from %s predates the last confirmed resume point in %s; "
                        "read it, do not resume from it." % (when, name))
    else:
        reply["say"] = "An unwrapped checkpoint in %s from %s, with %d item%s." % (
            name, when, len(block["items"]), "" if len(block["items"]) == 1 else "s")
    return reply


def checkpoint_now(args):
    """The time to stamp: `--now`, or this moment with the machine's offset."""
    if not getattr(args, "now", None):
        return datetime.datetime.now().astimezone().replace(microsecond=0).isoformat()
    try:
        return datetime.datetime.fromisoformat(args.now).replace(microsecond=0).isoformat()
    except ValueError:
        raise Refusal("--now takes an ISO date and time, such as 2026-10-15T14:32:10+02:00.")


def cmd_checkpoint(root, args, today):
    """Write the unconfirmed record of what a session has done into a thread
    note, or read what is there.

    The request is one JSON object on standard input, because the fields are
    free text, and the reply is one JSON object on standard output, whether it
    wrote, wrote nothing, or refused. It never writes Resume here, never
    writes `Todo.md`, and never commits: the wrap does those, and a commit
    here would run the zone's wall check in the middle of the work."""
    state = {"base": None, "key": None, "at": None, "items": []}
    try:
        return checkpoint_run(root, args, state)
    except Refusal as exc:
        reply = {"ok": False, "wrote": False, "refused": getattr(exc, "name", "where"), "say": str(exc)}
        reply.update(state)
        return reply


def checkpoint_run(root, args, state):
    req = checkpoint_request(args.stdin if getattr(args, "stdin", None) is not None else sys.stdin.read())
    ops = operations()
    if ops is not None and "checkpoint" in getattr(ops, "DECLARED", {}):
        why = ops.validate("checkpoint", req)
        if why:
            raise CheckpointRefusal("fields", ops.say("refused", "checkpoint", req, why=why))
    names = argparse.Namespace(zone=str(req.get("zone") or ""), project=str(req.get("project") or ""),
                               thread=str(req.get("thread") or "") or None)
    if not names.zone or not names.project:
        raise CheckpointRefusal("request", CHECKPOINT_WHY["request"].format(why="it names no zone or project"))
    zone_dir, project_dir, thread_dir, note = target_of(root, names)
    name = "%s, %s" % (project_dir.name, thread_dir.name) if thread_dir else project_dir.name
    raw = note.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise CheckpointRefusal("request", CHECKPOINT_WHY["request"].format(why="the note is not UTF-8 text"))
    state.update(checkpoint_state(text))
    if req.get("read"):
        return checkpoint_read(name, text, state)

    block = read_checkpoint(text)
    if block is not None and not block["valid"]:
        raise CheckpointRefusal("invalid", CHECKPOINT_WHY["invalid"].format(
            note=note.name, why=block["why"]))
    status = str(parse_frontmatter(note).get("status") or "").strip().lower()
    if status in ("done", "parked"):
        raise CheckpointRefusal(status, CHECKPOINT_WHY[status].format(name=name))
    if state["base"] is None:
        raise CheckpointRefusal("no-resume", CHECKPOINT_WHY["no-resume"].format(
            note=note.name, heading=RESUME_HEADING))

    sent = checkpoint_shape(req)
    drop = [one_line(d) for d in (req.get("drop") or [])]
    if not sent and not drop:
        raise CheckpointRefusal("nothing", CHECKPOINT_WHY["nothing"])
    held = (block or {}).get("items", [])
    items = checkpoint_merge(held, sent, drop)
    at = checkpoint_now(args)
    body, key = render_checkpoint(at, state["base"], items)
    # The repeat test comes first, and against the note rather than a clock:
    # the same state sent again at any interval is already there, so there is
    # nothing to write and nothing to refuse, however long ago the first went
    # in and whatever key the sender last read.
    if block is not None and key == block["key"]:
        return {"ok": True, "wrote": False, "say": "Nothing new since the last checkpoint."}
    if ops is not None and "checkpoint" in getattr(ops, "DECLARED", {}):
        why = ops.stale("checkpoint", req, (state["base"], state["key"]))
        if why:
            raise CheckpointRefusal("moved", ops.say("refused", "checkpoint", req, why=why))
    for item in sent:
        was = next((k for k in held if k["id"] == item["id"]), None) if item["id"] else None
        if was and was["kind"] == "considering" and item["kind"] == "decided":
            raise CheckpointRefusal("considering", CHECKPOINT_WHY["considering"].format(id=item["id"]))
        if was and was["kind"] != item["kind"]:
            raise CheckpointRefusal("id", CHECKPOINT_WHY["id"].format(
                id=item["id"], why="is a %s item and was sent as a %s one"
                % (CHECKPOINT_LABELS[was["kind"]], CHECKPOINT_LABELS[item["kind"]])))
    checkpoint_world(root, project_dir, sent)
    text_new = place_checkpoint(text, body)
    if text_new is None:
        raise CheckpointRefusal("no-resume", CHECKPOINT_WHY["no-resume"].format(
            note=note.name, heading=RESUME_HEADING))
    if not write_if_unchanged(note, text_new, raw):
        state.update(checkpoint_state(note.read_text(encoding="utf-8")))
        raise CheckpointRefusal("moved", ops.say("refused", "checkpoint", req, why=ops.STALE_WHY[("checkpoint", None)])
                                if ops is not None else "Nothing was written: the note changed while it was read.")
    reply = {"ok": True, "wrote": True, "say": "Checkpoint: %s, %s." % (name, said_time(at).split(" on ")[0])}
    reply.update(checkpoint_state(text_new))
    return reply


def main(argv=None):
    ap = argparse.ArgumentParser(description="Create a zone, a party, a project or a thread.")
    ap.add_argument("--root", help="workspace folder (default: the one this script is in)")
    ap.add_argument("--today", help="YYYY-MM-DD to stamp instead of today")
    sub = ap.add_subparsers(dest="command", required=True)
    z = sub.add_parser("zone", help="a new zone with its own git repository, or the wall of one that exists")
    z.add_argument("zone_name", nargs="?", help="the zone's name, one that can be said aloud (or --name)")
    z.add_argument("--name", help="the zone's name")
    z.add_argument("--holds", help="what a new zone holds, in a few words, for System/context.md")
    zflag = z.add_mutually_exclusive_group()
    zflag.add_argument("--walled", action="store_true", help="walled: what is in the zone stays in it (the default for a new zone)")
    zflag.add_argument("--open", action="store_true", help="open: what is in the zone may go anywhere")
    z.add_argument("--yes", action="store_true", help="go on where opening a zone releases its files")
    y = sub.add_parser("party", help="a new party in System/context.md; commit it before the project")
    y.add_argument("--name", help="the party's name, as a person would say it")
    y.add_argument("--zone", help="the zone it belongs to; needed where the workspace has more than one")
    y.add_argument("--what", help="what it is, in a few words, for the table")
    y.add_argument("--also", action="store_true",
                   help="a second row for an organisation already in Parties, in another capacity")
    p = sub.add_parser("project", help="a new project: one job, or separate jobs; the first thread is optional")
    p.add_argument("--zone", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--party", help="tag from Parties in System/context.md, or several separated by commas; optional, an index")
    p.add_argument("--thread", help="name of the first thread; optional")
    p.add_argument("--separate", dest="heading", action="store_true",
                   help="separate jobs, each thread with its own resume point and papers, not one job (the default)")
    p.add_argument("--heading", dest="heading", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--spoken", help="how the name is said, for a name that does not say it: heard alongside the name itself")
    p.add_argument("--thread-spoken", dest="thread_spoken",
                   help="how the first thread's name is said, where it does not say it")
    t = sub.add_parser("thread", help="a new thread in an existing project")
    t.add_argument("--zone", required=True)
    t.add_argument("--project", required=True)
    t.add_argument("--name", required=True)
    t.add_argument("--spoken", help="how the name is said, for a name that does not say it: heard alongside the name itself")
    t.add_argument("--papers", help=argparse.SUPPRESS)          # refused, with the sentence that names the project's switch
    t.add_argument("--touched", action="store_true",
                   help="end with a line `Touched: [...]`, the paths from the zone it wrote, for a caller that commits them")
    r = sub.add_parser("rename", help="rename a project or a thread, and every link to it in the zone")
    r.add_argument("--zone", required=True)
    r.add_argument("--project", required=True)
    r.add_argument("--thread", help="the thread to rename; without it, the project")
    r.add_argument("--to", required=True, help="the new name")
    r.add_argument("--spoken", help="how the name is said, for a name that does not say it: heard alongside the name itself")
    mv = sub.add_parser("move", help="move a thread to another project of its zone, and every link to it")
    mv.add_argument("--zone", required=True)
    mv.add_argument("--project", required=True, help="the project the thread is in now")
    mv.add_argument("--thread", required=True, help="the thread to move")
    mv.add_argument("--to", required=True, help="the project it goes to, in the same zone")
    mv.add_argument("--no-state", dest="no_state", action="store_true", help=argparse.SUPPRESS)
    for each in (r, mv):
        each.add_argument("--plan", action="store_true",
                          help="say what the change would write, as JSON, and make nothing")
    ly = sub.add_parser("layout", help="split a project into separate jobs, or join it into one job, and carry the files")
    ly.add_argument("--zone", required=True)
    ly.add_argument("--project", required=True)
    ly.add_argument("--thread", help=argparse.SUPPRESS)         # refused: the layout is the whole project's
    ly.add_argument("--papers", help=argparse.SUPPRESS)         # refused, with the sentence that names the project's switch
    ly.add_argument("--split", dest="heading", action="store_true",
                    help="separate jobs: each file goes to the one thread that names it")
    ly.add_argument("--heading", dest="heading", action="store_true", help=argparse.SUPPRESS)
    ly.add_argument("--join", action="store_true",
                    help="one job: each thread's Sources/ and Deliverables/ move into the project's")
    ly.add_argument("--resume-from", dest="resume_from",
                    help="with --join: the thread whose Next action opens the hub's Resume here block "
                         "(the one touched last when not said)")
    ly.add_argument("--json", action="store_true", help="with --check: the plan as JSON, for the status page's dialog")
    d = sub.add_parser("delete", help="delete a project or a thread; without --confirm, only say what would go")
    d.add_argument("--zone", required=True)
    d.add_argument("--project", required=True)
    d.add_argument("--thread", help="the thread to delete; without it, the whole project")
    d.add_argument("--confirm", help="the name of what is deleted, typed again")
    for verb, what in (("park", "set a project or a thread aside, without finishing it"),
                       ("wake", "bring a parked project or thread back")):
        k = sub.add_parser(verb, help=what + "; commit it afterwards")
        k.add_argument("--zone", required=True)
        k.add_argument("--project", required=True)
        k.add_argument("--thread", help="the thread; without it, the project, and every thread in it with it")
    c = sub.add_parser("checkpoint", help="write or read a thread note's checkpoint; the request is JSON on stdin")
    c.add_argument("--now", help="the time to stamp instead of now, as 2026-10-15T14:32:10+02:00")
    u = sub.add_parser("undo", help="revert a rename, a move, a deletion or a new project or thread, while it is the zone's last commit")
    u.add_argument("--zone", required=True)
    u.add_argument("--commit", required=True, help="the commit the rename or deletion reported")
    for each in (y, p, t, r, mv, ly):
        each.add_argument("--check", action="store_true",
                          help="say what this would do, and make nothing")
    args = ap.parse_args(argv)

    try:
        try:
            root = Path(args.root).expanduser().resolve() if args.root else workspace_root(HERE)
        except FileNotFoundError:
            raise Refusal("This script is not inside a Garrick workspace.")
        if not (root / "System" / "templates").is_dir():
            raise Refusal(f"{root} is not an installed workspace: System/templates is missing.")
        today = args.today or datetime.date.today().isoformat()
        if args.command == "checkpoint":
            # One JSON object out, whether it wrote, wrote nothing or refused,
            # because the caller is a script and reads the reply, not a line.
            reply = cmd_checkpoint(root, args, today)
            print(json.dumps(reply, ensure_ascii=False, sort_keys=True))
            return 0 if reply.get("ok") else 1
        run = {"zone": cmd_zone, "party": cmd_party, "project": cmd_project, "thread": cmd_thread,
               "rename": cmd_rename, "move": cmd_move, "layout": cmd_layout, "delete": cmd_delete, "undo": cmd_undo, "park": cmd_park,
               "wake": cmd_park}[args.command]
        print(run(root, args, today))
        ask_for_page(root, args)
    except Refusal as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
