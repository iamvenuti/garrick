#!/usr/bin/env python3
"""Create a zone, a party, a project or a thread in this workspace.

    python3 System/tools/scaffold.py zone "Garden" --holds "The house and the garden"
    python3 System/tools/scaffold.py party --name "Acme Corp" --zone Work --what "Supplier" [--check]
    python3 System/tools/scaffold.py project --zone Work --name "Acme" --party acme --thread "Pricing"
    python3 System/tools/scaffold.py thread  --zone Work --project Acme --name "Pricing"
    python3 System/tools/scaffold.py thread  --zone Work --project Acme --name "Pricing" --check
    python3 System/tools/scaffold.py thread  --zone Work --project Acme --name "ISO 27001" --spoken "I S O twenty seven thousand one"
    python3 System/tools/scaffold.py park    --zone Work --project Acme [--thread Pricing]
    python3 System/tools/scaffold.py wake    --zone Work --project Acme [--thread Pricing]
    python3 System/tools/scaffold.py rename  --zone Work --project Acme [--thread Pricing] --to "Renewal"
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
System/context.md, which is left for you to commit. A project always starts with its
first thread. A thread inherits its project's party. `--check` applies every refusal
and makes nothing, so a form can check a name as it is typed.

`party` adds a row to the Parties table in System/context.md and offers the tag
itself, so nobody has to invent one. The row it adds, and a Walls row, carry a
Learned cell, `2026-10-16, user`, which says where they came from; the rows
typed by hand are left as they are. It has to run, and its row be committed,
before `project`: a project is refused with a tag System/context.md does not
already carry, and that file is in the workspace's own repository while a project
is in the zone's, so the two are separate commits. Running it again for a party
already there changes nothing and says so. `party --check` answers one of three
things and writes nothing: that the party is new and what its tag would be; that
it is already there, with its tag, its zone and any project whose hub note names
that tag; or, where two parties share the name, a refusal naming both and asking
which is meant. `--also` adds a second row for an organisation already in Parties,
in another capacity, with the wider tag that keeps the two apart, and
`--walled-from` writes the Walls row that keeps their material apart.

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
old name becomes a heard alias in context.md, left for you to commit. The
Meetings wiki is listed, never edited. `delete` without `--confirm` only says
what would go; with it, the folder, the hub's line and the open Todo.md lines
naming it go in one commit, which `undo` reverts while it is still the zone's
last commit. Both refuse while what they
would change has changes not committed, or a cmux tab is mid-turn in it.

`checkpoint` writes the unconfirmed record of what a session has done into a
thread note, directly under its Resume here block, which it never touches, and
between two markers that are the block's whole extent. Its request is one JSON
object on standard input, because the fields are free text, and its reply is
one JSON object on standard output: what it wrote, or that the same state was
there already, or the name of the refusal and one line saying why. Every item
carries the source its kind needs, items are replaced by id and removed only
by `drop`, and `{"read": true, ...}` writes nothing and answers with what the
note holds. It never writes `Todo.md` and never commits: the wrap does those.

On success prints what it did in lines that can be read aloud; on refusal, one
line saying why, and exits 1. `checkpoint` prints JSON either way.
"""

import argparse
import datetime
import json
import os
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True  # keep System/tools free of __pycache__
sys.path.insert(0, str(HERE))

from garrick_lib import (  # noqa: E402
    CHECKPOINT_KINDS,
    CHECKPOINT_LABELS,
    CHECKPOINT_ONE,
    CHECKPOINT_STEMS,
    INBOX,
    RESUME_HEADING,
    TAG_RE,
    TAG_RULE,
    ZONE_TEMPLATE,
    ZONE_TODO,
    GitError,
    checkpoint_item_line,
    git,
    hooks_path,
    init_repo,
    install_wall_hook,
    is_display_name,
    is_sayable,
    learned_cell,
    learned_row,
    load_context,
    machine_made,
    parse_frontmatter,
    place_checkpoint,
    read_checkpoint,
    record_written,
    render_checkpoint,
    resume_hash,
    said_time,
    same_action,
    simple_home,
    skill_links,
    spoken_clash,
    spoken_of,
    strip_tag,
    table_row,
    tag_for,
    workspace_root,
    write_if_unchanged,
    zone_todo,
)


class Refusal(Exception):
    pass


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


def check_party(root, party):
    parties = load_context(root).get("parties", {})
    tag = party.strip().strip("`")
    if tag not in parties:
        known = ", ".join(sorted(parties)) or "none yet"
        raise Refusal(f"{party} is not a party tag in System/context.md. The tags are {known}.")
    return tag


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


def make_thread(root, project_dir, name, party, today, spoken=None):
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


def list_zone(root, name, holds):
    """Add the zone to the Zones table in System/context.md, as the installer would
    have. False when the table already lists it, which is then left as it is."""
    if name.lower() in (z.lower() for z in load_context(root)["zones"]):
        return False
    path = root / "System" / "context.md"
    lines = path.read_text(encoding="utf-8").splitlines()
    row = table_row([name, holds or f"<What {name} holds>"])
    start = next((i for i, l in enumerate(lines) if l.strip().lower() == "## zones"), None)
    if start is None:
        at = next((i for i, l in enumerate(lines) if l.strip().lower() == "## parties"), len(lines))
        block = ["## Zones", "", "| Zone | Holds |", "|---|---|", row, ""]
        if at == len(lines) and lines and lines[-1].strip():
            block = [""] + block[:-1]
        lines[at:at] = block
    else:
        end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
        rows = [i for i in range(start + 1, end) if lines[i].lstrip().startswith("|")]
        if rows:
            lines.insert(rows[-1] + 1, row)
        else:
            lines[start + 1:start + 1] = ["", "| Zone | Holds |", "|---|---|", row]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


def cmd_zone(root, args, today):
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
        if simple_home(root):           # as the installer's zones: no example line on the simple home
            todo = target / ZONE_TODO
            todo.write_text(zone_todo(todo.read_text(encoding="utf-8"), True), encoding="utf-8")
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
    if list_zone(root, name, holds):
        said.append(f"Added {name} to the Zones table in System/context.md.")
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
    said.append(f'Next, say "new project <name> for <party> in {name}, first thread <name>". '
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
            if hub.is_file() and strip_tag(str(parse_frontmatter(hub).get("party") or "")) == tag:
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
    its own. The commit is the caller's, as a new zone's row is. With `today`,
    the row is a learned one, added on the user's word, and its Learned cell
    says so; the rows typed by hand are left as they are."""
    path = root / "System" / "context.md"
    if not path.is_file():
        raise Refusal("System/context.md is missing, so the party could not be listed there.")
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next((i for i, l in enumerate(lines) if l.strip().lower() == "## parties"), None)
    if start is None:
        raise Refusal("System/context.md has no `## Parties` table to add the party to.")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    rows = [i for i in range(start + 1, end) if lines[i].lstrip().startswith("|")]
    cells = [name, what, zone, "`%s`" % tag, ""]
    if len(rows) < 2:
        lines[end:end] = ["| Party | What it is | Zone | Tag | Domains |", "|---|---|---|---|---|", ""]
        rows = [end, end + 1]
    row = learned_row(lines, rows, cells, learned_cell(today, "user")) if today else table_row(cells)
    lines.insert(rows[-1] + 1, row)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def add_wall_row(root, tag, other, why, today=None):
    """The row in context.md's Walls table between two tags, with a Learned
    cell, as a party's row has, when `today` is given."""
    path = root / "System" / "context.md"
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next((i for i, l in enumerate(lines) if l.strip().lower() == "## walls"), None)
    if start is None:
        raise Refusal("System/context.md has no `## Walls` table, so the wall could not be written. "
                      "The party's row is there; add the wall by hand.")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    rows = [i for i in range(start + 1, end) if lines[i].lstrip().startswith("|")]
    cells = ["`%s`" % tag, "`%s`" % other, why]
    if len(rows) < 2:
        lines[end:end] = ["| Between | And | Why |", "|---|---|---|", ""]
        rows = [end, end + 1]
    row = learned_row(lines, rows, cells, learned_cell(today, "user")) if today else table_row(cells)
    lines.insert(rows[-1] + 1, row)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def cmd_party(root, args, today):
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
    if len(same) > 1:
        each = ["`%s` in %s" % (tag, entry.get("zone") or "no zone") for tag, entry in same]
        counts = {2: "Two", 3: "Three", 4: "Four"}
        raise Refusal("%s of your parties are called %s: %s, and %s. Which one is this?"
                      % (counts.get(len(same), str(len(same))), name,
                         ", ".join(each[:-1]), each[-1]))
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
    if not TAG_RE.match(tag):                     # the library offers only valid tags; belt and braces
        raise Refusal('"%s" will not work as a tag: it must be %s.' % (tag, TAG_RULE))
    other = strip_tag(args.walled_from or "")
    if other:
        if other == tag:
            raise Refusal("A wall needs two parties, not `%s` twice." % tag)
        if other not in parties:
            raise Refusal("`%s` is not a party tag in System/context.md, so no wall can name it. "
                          "The tags are %s." % (other, ", ".join(sorted(parties)) or "none yet"))
    if args.check:
        where = ", in %s" % zone if zone else ""
        return "%s is not a party yet, and the tag would be `%s`%s." % (name, tag, where)
    what = " ".join((args.what or "").split()) or f"<What {name} is>"
    add_party_row(root, name, what, zone, tag, today)
    said = [f"Added {name} to the Parties table in System/context.md, with the tag `{tag}`, in {zone}."]
    if other:
        add_wall_row(root, tag, other, args.why or "<Why their material never meets>", today)
        said.append(f"Added a wall between `{tag}` and `{other}`, so neither ever informs the other in writing.")
    elif same:
        said.append("`%s` and `%s` are both %s with no wall between them, which the workspace check warns "
                    "about until one is added." % (same[0][0], tag, name))
    said.append("Commit System/context.md on its own, in the workspace's own repository at its top folder: "
                "a project is in its zone's repository, and one commit never spans the two.")
    said.append('Next, once that row is committed: scaffold.py project --zone %s --name "<Project>" '
                '--party %s --thread "<Thread>", which is refused while the row is not there.' % (zone, tag))
    return "\n".join(said)


def cmd_project(root, args, today):
    zone_dir = find_zone(root, args.zone)
    name, thread = args.name.strip(), args.thread.strip()
    if name.lower() == INBOX.lower():
        raise Refusal(f"{INBOX} is where {zone_dir.name}'s mail and files wait to be filed. Pick another name for the project.")
    spoken = (args.spoken or "").strip()
    thread_spoken = (args.thread_spoken or "").strip()
    check_name(name, children(zone_dir), "project", zone_dir.name, spoken=spoken, parent=zone_dir)
    check_name(thread, [], "thread", name, spoken=thread_spoken)
    party = check_party(root, args.party)
    target = zone_dir / name
    if target.exists():
        raise Refusal(f"{target.relative_to(root)} already exists.")
    asked = say_how(name, "project", spoken) + say_how(thread, "thread", thread_spoken)
    if getattr(args, "check", False):
        return "\n".join([f"{name} will do as a project in {zone_dir.name}, and {thread} as its first thread."] + asked)
    values = {"ZONE": zone_dir.name, "PROJECT": name, "THREAD": thread, "PARTY": party, "DATE": today}
    copy_filled(root / "System" / "templates" / "project", target, values)
    hub = target / f"{name}.md"
    if spoken and hub.is_file():
        hub.write_text(set_spoken(hub.read_text(encoding="utf-8"), spoken), encoding="utf-8")
    make_thread(root, target, thread, party, today, thread_spoken)
    link_thread_in_hub(hub, thread, today)
    return "\n".join([f"Created project {name} in {zone_dir.name}, with its first thread, {thread}."] + asked)


def cmd_thread(root, args, today):
    zone_dir = find_zone(root, args.zone)
    project_dir = find_child(zone_dir, args.project, "project")
    hub = project_dir / f"{project_dir.name}.md"
    if not hub.is_file():
        raise Refusal(f"{project_dir.name} has no hub note, {hub.name}.")
    party = str(parse_frontmatter(hub).get("party") or "").strip()
    if not party:
        raise Refusal(f"{project_dir.name} has no party in its hub note, so a thread cannot inherit one.")
    party = check_party(root, party)
    name = args.name.strip()
    spoken = (args.spoken or "").strip()
    asked = say_how(name, "thread", spoken)
    if getattr(args, "check", False):
        threads = project_dir / "Threads"
        check_name(name, children(threads), "thread", project_dir.name, spoken=spoken, parent=threads)
        if (threads / name).exists():
            raise Refusal(f"{(threads / name).relative_to(root)} already exists.")
        return "\n".join([f"{name} will do as a thread in {project_dir.name}."] + asked)
    target = make_thread(root, project_dir, name, party, today, spoken)
    link_thread_in_hub(hub, name, today)
    said = [f"Created thread {name} in {project_dir.name}."] + asked
    if getattr(args, "touched", False):
        # What it wrote, from the zone, for a caller that commits it by name and nothing else (#183).
        said.append("Touched: " + json.dumps([target.relative_to(zone_dir).as_posix(),
                                              hub.relative_to(zone_dir).as_posix()], ensure_ascii=False))
    return "\n".join(said)


# --------------------------------------------------------------------------- rename and delete

MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")


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
    page_action.py, which keeps one for `interrupt`."""
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
    """The old name as a heard form of the new one, in context.md's Aliases
    table, so "Pricing" still finds "Renewal" for a while. False when the
    table is missing or already has it. With `today`, the row's Learned cell
    says it came from the user, who asked for the rename."""
    path = root / "System" / "context.md"
    if not path.is_file() or heard.lower() in load_context(root).get("aliases", {}):
        return False
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next((i for i, l in enumerate(lines) if l.strip().lower() == "## aliases"), None)
    if start is None:
        return False
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    rows = [i for i in range(start + 1, end) if lines[i].lstrip().startswith("|")]
    if len(rows) < 2:
        return False
    cells = [heard.lower(), means]
    lines.insert(rows[-1] + 1, learned_row(lines, rows, cells, learned_cell(today, "user")) if today else table_row(cells))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


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
    return "%s is %s" % (name, "parked" if status == "parked" else "awake again")


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
        new_note = moved / f"{new}.md"
        touched.add(new_note)
        for path in zone_notes(zone_dir):
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue                                    # not text it can rewrite; its links, if any, stay
            changed = relink(text, swaps, prefixes, old, new, heads)
            if not is_thread and moved in path.parents:
                changed = re.sub(r'(?m)^project: "?\[\[%s\]\]"?$' % re.escape(old), f'project: "[[{new}]]"', changed)
            if path == new_note:
                changed = re.sub(r"(?m)^title: .*$", f"title: {new}", changed, count=1)
                # The old spoken form goes with the old name, which becomes a heard alias below.
                if spoken or is_sayable(new)[0]:
                    changed = set_spoken(changed, spoken)
                changed = re.sub(r"(?m)^# %s\s*$" % re.escape(old), f"# {new}", changed, count=1)
                changed = re.sub(r"(?m)^updated: .*$", f"updated: {today}", changed, count=1)
                changed = dated_entry(changed, f"Renamed from {old}.", today)
            if changed != text:
                touched.add(path)
                path.write_text(changed, encoding="utf-8")
        git_ok(["add", "-A", "--", rel_new] + [str(t.relative_to(zone_dir)) for t in touched], zone_dir)
        git(["commit", "-q", "-m", f"{what}: renamed {new}"], zone_dir)
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
    if add_alias(root, old, new, today):
        said.append(f'Added "{old}" as a heard name for {new} in System/context.md; commit it in the workspace root.')
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
        git(["commit", "-q", "-m", f"{what}: deleted\n\n{body}"], zone_dir)
    except GitError as exc:
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
    """Revert a rename or a deletion this script committed, while it is still
    the zone's last commit: anything committed since might depend on it."""
    zone_dir = find_zone(root, args.zone)
    head = git_value(["rev-parse", "HEAD"], zone_dir).strip()
    wanted = git_value(["rev-parse", "--verify", "-q", args.commit + "^{commit}"], zone_dir).strip()
    if not wanted:
        raise Refusal(f"{zone_dir.name} has no commit {args.commit}.")
    if wanted != head:
        raise Refusal(f"{args.commit} is no longer the last commit in {zone_dir.name}, so it is not undone here. "
                      "Ask for it to be reverted by hand.")
    subject = git_value(["log", "-1", "--format=%s"], zone_dir).strip()
    if not re.search(r": (deleted|renamed .+)$", subject):
        raise Refusal(f"{args.commit} is not a rename or a deletion: {subject}")
    if git_value(["status", "--porcelain", "--untracked-files=no"], zone_dir).strip():
        raise Refusal(f"{zone_dir.name} has changes not committed. Commit or undo them first.")
    git_ok(["revert", "--no-edit", head], zone_dir)
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
    z = sub.add_parser("zone", help="a new zone, with its own git repository")
    z.add_argument("name", help="the zone's name, one that can be said aloud")
    z.add_argument("--holds", required=True, help="what the zone holds, in a few words, for System/context.md")
    y = sub.add_parser("party", help="a new party in System/context.md; commit it before the project")
    y.add_argument("--name", required=True, help="the party's name, as a person would say it")
    y.add_argument("--zone", help="the zone it belongs to; needed where the workspace has more than one")
    y.add_argument("--what", help="what it is, in a few words, for the table")
    y.add_argument("--also", action="store_true",
                   help="a second row for an organisation already in Parties, in another capacity")
    y.add_argument("--walled-from", dest="walled_from",
                   help="a party tag whose material must never meet this one's: writes the Walls row")
    y.add_argument("--why", help="why the wall stands, for the Walls table")
    p = sub.add_parser("project", help="a new project, with its first thread")
    p.add_argument("--zone", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--party", required=True, help="tag from Parties in System/context.md")
    p.add_argument("--thread", required=True, help="name of the first thread")
    p.add_argument("--spoken", help="how the name is said, for a name that does not say it: heard alongside the name itself")
    p.add_argument("--thread-spoken", dest="thread_spoken",
                   help="how the first thread's name is said, where it does not say it")
    t = sub.add_parser("thread", help="a new thread in an existing project")
    t.add_argument("--zone", required=True)
    t.add_argument("--project", required=True)
    t.add_argument("--name", required=True)
    t.add_argument("--spoken", help="how the name is said, for a name that does not say it: heard alongside the name itself")
    t.add_argument("--touched", action="store_true",
                   help="end with a line `Touched: [...]`, the paths from the zone it wrote, for a caller that commits them")
    r = sub.add_parser("rename", help="rename a project or a thread, and every link to it in the zone")
    r.add_argument("--zone", required=True)
    r.add_argument("--project", required=True)
    r.add_argument("--thread", help="the thread to rename; without it, the project")
    r.add_argument("--to", required=True, help="the new name")
    r.add_argument("--spoken", help="how the name is said, for a name that does not say it: heard alongside the name itself")
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
    u = sub.add_parser("undo", help="revert a rename or a deletion, while it is the zone's last commit")
    u.add_argument("--zone", required=True)
    u.add_argument("--commit", required=True, help="the commit the rename or deletion reported")
    for each in (y, p, t, r):
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
               "rename": cmd_rename, "delete": cmd_delete, "undo": cmd_undo, "park": cmd_park,
               "wake": cmd_park}[args.command]
        print(run(root, args, today))
    except Refusal as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
