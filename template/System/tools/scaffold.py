#!/usr/bin/env python3
"""Create a zone, a project or a thread in this workspace.

    python3 System/tools/scaffold.py zone "Garden" --holds "The house and the garden"
    python3 System/tools/scaffold.py project --zone Work --name "Acme" --party acme --thread "Pricing"
    python3 System/tools/scaffold.py thread  --zone Work --project Acme --name "Pricing"

A zone is made the way the installer makes one: its own folder and git repository
with a first commit, its inbox, the skill links and the wall check, and a row in
System/context.md, which is left for you to commit. A project always starts with its
first thread. A thread inherits its project's party. On success prints what it made in
lines that can be read aloud; on refusal, one line saying why, and exits 1.
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
    is_speakable,
    load_context,
    parse_frontmatter,
    record_written,
    skill_links,
    sounds_alike,
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


def check_name(name, siblings, kind, where):
    ok, reason = is_speakable(name)
    if not ok:
        raise Refusal(f'"{name}" will not work as a {kind} name: {reason}')
    for sibling in siblings:
        if sibling.lower() == name.lower():
            raise Refusal(f"{where[:1].upper()}{where[1:]} already has a {kind} called {sibling}.")
        if sounds_alike(name, sibling):
            raise Refusal(f"{name} sounds too much like {sibling}, already in {where}. Pick a name that is easy to tell apart.")


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


def make_thread(root, project_dir, name, party, today):
    threads = project_dir / "Threads"
    check_name(name, children(threads), "thread", project_dir.name)
    target = threads / name
    if target.exists():
        raise Refusal(f"{target.relative_to(root)} already exists.")
    threads.mkdir(exist_ok=True)
    values = {"ZONE": project_dir.parent.name, "PROJECT": project_dir.name, "THREAD": name,
              "PARTY": party, "DATE": today}
    copy_filled(root / "System" / "templates" / "thread", target, values)
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
    check_name(name, children(zones), "zone", "the workspace")
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
    check_name(name, children(zone_dir), "project", zone_dir.name)
    ok, reason = is_speakable(thread)
    if not ok:
        raise Refusal(f'"{thread}" will not work as a thread name: {reason}')
    party = check_party(root, args.party)
    target = zone_dir / name
    if target.exists():
        raise Refusal(f"{target.relative_to(root)} already exists.")
    values = {"ZONE": zone_dir.name, "PROJECT": name, "THREAD": thread, "PARTY": party, "DATE": today}
    copy_filled(root / "System" / "templates" / "project", target, values)
    make_thread(root, target, thread, party, today)
    link_thread_in_hub(target / f"{name}.md", thread, today)
    return f"Created project {name} in {zone_dir.name}, with its first thread, {thread}."


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
    make_thread(root, project_dir, name, party, today)
    link_thread_in_hub(hub, name, today)
    return f"Created thread {name} in {project_dir.name}."


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
    t = sub.add_parser("thread", help="a new thread in an existing project")
    t.add_argument("--zone", required=True)
    t.add_argument("--project", required=True)
    t.add_argument("--name", required=True)
    args = ap.parse_args(argv)

    try:
        try:
            root = Path(args.root).expanduser().resolve() if args.root else workspace_root(HERE)
        except FileNotFoundError:
            raise Refusal("This script is not inside a Garrick workspace.")
        if not (root / "System" / "templates").is_dir():
            raise Refusal(f"{root} is not an installed workspace: System/templates is missing.")
        today = args.today or datetime.date.today().isoformat()
        run = {"zone": cmd_zone, "project": cmd_project, "thread": cmd_thread}[args.command]
        print(run(root, args, today))
    except Refusal as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
