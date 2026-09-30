#!/usr/bin/env python3
"""Create a project or a thread in this workspace.

    python3 System/tools/scaffold.py project --zone Work --name "Acme" --party acme --thread "Pricing"
    python3 System/tools/scaffold.py thread  --zone Work --project Acme --name "Pricing"

A project always starts with its first thread. A thread inherits its project's party.
On success prints one line that can be read aloud; on refusal, one line saying why, and exits 1.
"""

import argparse
import datetime
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True  # keep System/tools free of __pycache__
sys.path.insert(0, str(HERE))

from garrick_lib import INBOX, is_speakable, load_context, parse_frontmatter, sounds_alike, workspace_root  # noqa: E402

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
            raise Refusal(f"{where} already has a {kind} called {sibling}.")
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
    ap = argparse.ArgumentParser(description="Create a project or a thread.")
    ap.add_argument("--root", help="workspace folder (default: the one this script is in)")
    ap.add_argument("--today", help="YYYY-MM-DD to stamp instead of today")
    sub = ap.add_subparsers(dest="command", required=True)
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
        run = cmd_project if args.command == "project" else cmd_thread
        print(run(root, args, today))
    except Refusal as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
