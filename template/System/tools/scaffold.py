#!/usr/bin/env python3
"""Create a zone, a project or a thread in this workspace.

    python3 System/tools/scaffold.py zone "Garden" --holds "The house and the garden"
    python3 System/tools/scaffold.py project --zone Work --name "Acme" --party acme --thread "Pricing"
    python3 System/tools/scaffold.py thread  --zone Work --project Acme --name "Pricing"
    python3 System/tools/scaffold.py thread  --zone Work --project Acme --name "Pricing" --check
    python3 System/tools/scaffold.py thread  --zone Work --project Acme --name "ISO 27001" --spoken "I S O twenty seven thousand one"
    python3 System/tools/scaffold.py park    --zone Work --project Acme [--thread Pricing]
    python3 System/tools/scaffold.py wake    --zone Work --project Acme [--thread Pricing]
    python3 System/tools/scaffold.py rename  --zone Work --project Acme [--thread Pricing] --to "Renewal"
    python3 System/tools/scaffold.py delete  --zone Work --project Acme [--thread Pricing] [--confirm Pricing]
    python3 System/tools/scaffold.py undo    --zone Work --commit <the commit it reported>

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

On success prints what it did in lines that can be read aloud; on refusal, one
line saying why, and exits 1.
"""

import argparse
import datetime
import os
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True  # keep System/tools free of __pycache__
sys.path.insert(0, str(HERE))

from garrick_lib import (  # noqa: E402
    INBOX,
    ZONE_TEMPLATE,
    GitError,
    git,
    hooks_path,
    init_repo,
    install_wall_hook,
    is_display_name,
    is_sayable,
    load_context,
    parse_frontmatter,
    record_written,
    skill_links,
    spoken_clash,
    spoken_of,
    table_row,
    workspace_root,
)

IGNORED = {".DS_Store", "__pycache__"}


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
        if item.name in IGNORED or item.name.startswith("._"):
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
    make_thread(root, project_dir, name, party, today, spoken)
    link_thread_in_hub(hub, name, today)
    return "\n".join([f"Created thread {name} in {project_dir.name}."] + asked)


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
    keeps in a repository of its own, which no revert brings back."""
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
    if loose:
        raise Refusal(f"{loose[0]}{' and %d more' % (len(loose) - 1) if len(loose) > 1 else ''} is in {folder.name} but "
                      f"not in the zone's history, so nothing could bring it back. Commit it or move it out, then {verb}.")


def remove_empty(folder):
    """The folders git left behind once it removed every file, deepest first."""
    for d, dirs, files in sorted(os.walk(folder), key=lambda t: -len(Path(t[0]).parts)):
        if not files and not os.listdir(d):
            os.rmdir(d)


def relink(text, swaps, prefixes, old_name, new_name, heads=("",)):
    """Every [[link]] to the renamed note pointed at its new name, in its
    bare, labelled, heading and path forms: `swaps` are whole targets (old,
    new, without .md), `prefixes` folders a target may run through, for the
    threads of a renamed project. A path counts only from the zone, written
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


def add_alias(root, heard, means):
    """The old name as a heard form of the new one, in context.md's Aliases
    table, so "Pricing" still finds "Renewal" for a while. False when the
    table is missing or already has it."""
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
    lines.insert(rows[-1] + 1, table_row([heard.lower(), means]))
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
    preflight(zone_dir, folder, "rename")
    dirty = uncommitted(zone_dir, [folder] + notes)
    if dirty:
        raise Refusal(f"{', '.join(dirty[:3])}{' and more' if len(dirty) > 3 else ''} has changes not committed. "
                      f"Commit or undo them, then rename.")
    if mid_turn(root, folder):
        raise Refusal(f"A session is mid-turn in {old}. Let it finish, then rename.")
    rel_old = folder.relative_to(zone_dir).as_posix()
    rel_new = (folder.parent / new).relative_to(zone_dir).as_posix()
    # Link targets, without .md: the note by its path, and by its name when no other note shares it.
    swaps = [(f"{rel_old}/{old}", f"{rel_new}/{new}")] + ([(old, new)] if not others else [])
    prefixes = [] if is_thread else [(rel_old, rel_new)]
    heads = ("", f"{zone_dir.name}/", f"Zones/{zone_dir.name}/")
    moved = zone_dir / rel_new
    touched = set()
    what = f"{project_dir.name}, {old}" if is_thread else old
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
    if add_alias(root, old, new):
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
    preflight(zone_dir, folder, "delete")
    dirty = uncommitted(zone_dir, [folder] + [p for p in (hub, todo) if p.is_file()])
    if dirty:
        raise Refusal(f"{', '.join(dirty[:3])} has changes not committed. Commit or undo them, then delete.")
    if mid_turn(root, folder):
        raise Refusal(f"A session is mid-turn in {name}. Let it finish, then delete.")
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


def main(argv=None):
    ap = argparse.ArgumentParser(description="Create a zone, a project or a thread.")
    ap.add_argument("--root", help="workspace folder (default: the one this script is in)")
    ap.add_argument("--today", help="YYYY-MM-DD to stamp instead of today")
    sub = ap.add_subparsers(dest="command", required=True)
    z = sub.add_parser("zone", help="a new zone, with its own git repository")
    z.add_argument("name", help="the zone's name, one that can be said aloud")
    z.add_argument("--holds", required=True, help="what the zone holds, in a few words, for System/context.md")
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
    u = sub.add_parser("undo", help="revert a rename or a deletion, while it is the zone's last commit")
    u.add_argument("--zone", required=True)
    u.add_argument("--commit", required=True, help="the commit the rename or deletion reported")
    for each in (p, t, r):
        each.add_argument("--check", action="store_true",
                          help="say whether the name would do, and make nothing")
    args = ap.parse_args(argv)

    try:
        try:
            root = Path(args.root).expanduser().resolve() if args.root else workspace_root(HERE)
        except FileNotFoundError:
            raise Refusal("This script is not inside a Garrick workspace.")
        if not (root / "System" / "templates").is_dir():
            raise Refusal(f"{root} is not an installed workspace: System/templates is missing.")
        today = args.today or datetime.date.today().isoformat()
        run = {"zone": cmd_zone, "project": cmd_project, "thread": cmd_thread, "rename": cmd_rename,
               "delete": cmd_delete, "undo": cmd_undo, "park": cmd_park, "wake": cmd_park}[args.command]
        print(run(root, args, today))
    except Refusal as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
