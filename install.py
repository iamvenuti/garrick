#!/usr/bin/env python3
"""Install a Garrick workspace.

    python3 install.py                                   asks, one question at a time
    python3 install.py --config FILE.json --target PATH  no questions (guided sessions, tests, demos)

Python 3.9+, standard library only. Writes nothing outside the target folder.
"""

import sys

if sys.version_info < (3, 9):
    sys.exit("Garrick needs Python 3.9 or later; this is %d.%d. "
             "Install the Command Line Tools (xcode-select --install) and run it with /usr/bin/python3."
             % sys.version_info[:2])

import argparse
import json
import os
import re
import shutil
import subprocess
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parent
TEMPLATE = REPO / "template"
TOOLS = TEMPLATE / "System" / "tools"

DEFAULT_TARGET = "~/Garrick"
# Offered instead when the default is Garrick's own folder: a Mac ignores capitals
# in folder names, so a clone at ~/garrick is also ~/Garrick.
OTHER_TARGET = "~/Garrick-workspace"
DEFAULT_ZONES = ["Work", "Personal"]
# macOS privacy protection stops scheduled jobs from reading these folders.
PROTECTED = ["Documents", "Desktop", "Downloads", "Library"]
IGNORED_FILES = {".DS_Store"}
TAG_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
TAG_RULE = "one lowercase word that starts with a letter, then letters, digits or hyphens"
# Wall examples the questions can show, never built from the user's own tags.
EXAMPLE_WALLS = (("acme", "birch"), ("cedar", "dune"))
# The one way to put your own address on the workspace's repositories when git had
# none. docs/getting-started.md gives the same command; a test keeps them alike.
OWN_ADDRESS = 'for repo in . Wikis Zones/*; do git -C "$repo" config user.email "you@example.com"; done'


class InstallError(Exception):
    """A refusal or failure, worded for the person installing."""


def ph(key):
    """A placeholder, spelled without writing the braces literally."""
    return "{" * 2 + key + "}" * 2


def lib():
    sys.dont_write_bytecode = True  # leave template/System/tools free of __pycache__
    sys.path.insert(0, str(TOOLS))
    try:
        import garrick_lib  # noqa: F401
    except ImportError as exc:
        raise InstallError(
            "The installer is missing a piece (template/System/tools/garrick_lib.py). "
            "Download Garrick again, then rerun."
        ) from exc
    return garrick_lib


# --------------------------------------------------------------------------- config


def normalise(raw):
    """Turn a config dict (from JSON or the questions) into one canonical shape."""
    owner = raw.get("owner") or {}
    if isinstance(owner, str):
        owner = {"name": owner}
    zones = []
    for z in raw.get("zones") or DEFAULT_ZONES:
        if isinstance(z, str):
            z = {"name": z}
        zones.append({"name": str(z.get("name", "")).strip(), "holds": str(z.get("holds", "")).strip()})
    parties = []
    for p in raw.get("parties") or []:
        parties.append({
            "name": str(p.get("name", "")).strip(),
            "what": str(p.get("what", "")).strip(),
            "zone": str(p.get("zone", "")).strip(),
            "tag": str(p.get("tag", "")).strip().strip("`"),
            "domains": domain_list(p.get("domains")),
        })
    walls = []
    for w in raw.get("walls") or []:
        if isinstance(w, (list, tuple)):
            w = {"between": w[0], "and": w[1], "why": w[2] if len(w) > 2 else ""}
        walls.append({
            "between": str(w.get("between", "")).strip().strip("`"),
            "and": str(w.get("and", "")).strip().strip("`"),
            "why": str(w.get("why", "")).strip(),
        })
    people = []
    for p in raw.get("people") or []:
        people.append({
            "name": str(p.get("name", "")).strip(),
            "party": str(p.get("party", "")).strip().strip("`"),
            "role": str(p.get("role", "")).strip(),
        })
    aliases = []
    for a in raw.get("aliases") or []:
        aliases.append({"heard": str(a.get("heard", "")).strip(), "means": str(a.get("means", "")).strip()})
    return {
        "owner": {"name": str(owner.get("name", "")).strip(),
                  "description": str(owner.get("description", "")).strip()},
        "zones": zones,
        "parties": parties,
        "walls": walls,
        "people": people,
        "aliases": aliases,
    }


def domain_list(value):
    """Domains from a config value: a list, or one comma-separated string."""
    if isinstance(value, (list, tuple)):
        value = ",".join(str(v) for v in value)
    out = []
    for part in str(value or "").replace(";", ",").split(","):
        d = part.strip().strip("`").strip().lstrip("@").lower().rstrip(".")
        if d and d not in out:
            out.append(d)
    return out


def domain_problems(label, domains, taken, pl):
    """What is wrong with one party's domains; `taken` maps domain -> party already using it."""
    problems = []
    for d in domains:
        if not pl.is_domain(d):
            problems.append(f'"{d}" for {label} is not a mail domain, such as acmecorp.example.')
        elif pl.is_webmail(d):
            problems.append(f"{d} for {label} is personal webmail, which never names a party. Leave it out.")
        elif d in taken:
            problems.append(f"{d} is given for both {taken[d]} and {label}.")
    return problems


def check_zone_name(name, others, pl):
    ok, reason = pl.is_speakable(name)
    if not ok:
        return f'"{name}" will not work as a zone name: {reason}'
    for other in others:
        if other.lower() == name.lower():
            return f'There is already a zone called {other}.'
        if pl.sounds_alike(name, other):
            return f'"{name}" sounds too much like {other}; pick names that are easy to tell apart.'
    return None


def validate(cfg, pl):
    """Return a list of problems; empty means the config can be installed."""
    problems = []
    if not cfg["owner"]["name"]:
        problems.append("The owner's name is missing.")
    if not cfg["owner"]["description"]:
        problems.append("The one-line description of what the owner does is missing.")
    if not cfg["zones"]:
        problems.append("At least one zone is needed.")
    seen = []
    for z in cfg["zones"]:
        err = check_zone_name(z["name"], seen, pl)
        if err:
            problems.append(err)
        seen.append(z["name"])
    zone_names = {z["name"] for z in cfg["zones"]}
    tags = []
    domains = {}
    for p in cfg["parties"]:
        label = p["name"] or "a party"
        problems += domain_problems(label, p["domains"], domains, pl)
        domains.update({d: label for d in p["domains"]})
        if not p["name"]:
            problems.append("A party has no name.")
        if p["zone"] not in zone_names:
            problems.append(f'{label} is in zone "{p["zone"]}", which is not one of: {", ".join(sorted(zone_names))}.')
        if not TAG_RE.match(p["tag"]):
            problems.append(f'The tag for {label} ("{p["tag"]}") must be {TAG_RULE}.')
        elif p["tag"] in tags:
            problems.append(f'The tag "{p["tag"]}" is used twice.')
        tags.append(p["tag"])
    for w in cfg["walls"]:
        for t in (w["between"], w["and"]):
            if t not in tags:
                problems.append(f'The wall between "{w["between"]}" and "{w["and"]}" names "{t}", which is not a party tag.')
        if w["between"] == w["and"]:
            problems.append(f'A wall needs two different parties, not "{w["between"]}" twice.')
    for p in cfg["people"]:
        if not p["name"]:
            problems.append("A person has no name.")
        if p["party"] and p["party"] not in tags:
            problems.append(f'{p["name"] or "A person"} belongs to "{p["party"]}", which is not a party tag.')
    for a in cfg["aliases"]:
        if not a["heard"] or not a["means"]:
            problems.append("Each alias needs both what is heard and what it means.")
    return problems


# --------------------------------------------------------------------------- target


def same_folder(a, b):
    """True when two paths name one folder, however they are spelt. Compared by
    device and inode, not by name: a Mac's disk ignores capitals, so ~/garrick is
    ~/Garrick, and a symlink is the folder it points to."""
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def within(path, folder):
    """True when `path`, which need not exist yet, is `folder` or sits inside it."""
    p = Path(os.path.abspath(path))
    while not os.path.exists(p) and p != p.parent:
        p = p.parent
    real = p.resolve()
    return any(same_folder(q, folder) for q in (p, *p.parents, real, *real.parents))


def source_overlap(target):
    """How a target meets the folder this installer runs from: "is", "inside", "holds" or None."""
    if within(target, REPO):
        return "is" if same_folder(target, REPO) else "inside"
    if within(REPO, target):
        return "holds"
    return None


def suggestion():
    """The folder a refusal offers: the default, unless the default is Garrick's own folder."""
    return OTHER_TARGET if source_overlap(Path(DEFAULT_TARGET).expanduser()) else DEFAULT_TARGET


def check_target(target, force=False):
    """Refuse a target that would break scheduled jobs, touch home config, mix the
    workspace into Garrick's own folder, or clobber files. Returns it as an absolute path."""
    home = Path.home().resolve()
    t = Path(os.path.abspath(target.expanduser()))
    resolved = t.resolve()
    if resolved == home or resolved in home.parents or within(home, t):
        raise InstallError(f"{t} is your home folder or above it. Pick a folder of its own, such as {suggestion()}.")
    for name in PROTECTED:
        guarded = {home / name, (home / name).resolve()}
        if any(c == g or g in c.parents for c in (t, resolved) for g in guarded) or within(t, home / name):
            raise InstallError(
                    f"Not inside ~/{name}: macOS privacy protection blocks scheduled jobs there. "
                    f"Pick a folder such as {suggestion()}."
                )
    overlap = source_overlap(t)
    if overlap:
        source = "the Garrick folder this installer runs from"
        if overlap == "is" and str(t) == str(REPO):
            problem = f"{t} is {source}."
        elif overlap == "is":
            problem = f"{t} is the same folder as {REPO}, {source}."
        elif overlap == "inside":
            problem = f"{t} is inside {REPO}, {source}."
        else:
            problem = f"{t} holds {REPO}, {source}."
        instead = "of its own" if overlap == "holds" else "outside it"
        raise InstallError(f"{problem} Pick a new folder {instead}, such as {suggestion()}.")
    if t.exists() and not t.is_dir():
        raise InstallError(f"{t} is a file, not a folder.")
    if t.is_dir():
        contents = [p for p in t.iterdir() if p.name not in IGNORED_FILES]
        if contents and not force:
            raise InstallError(f"{t} is not empty. Pick an empty or new folder, or rerun with --force.")
        clashes = [p.name for p in contents if p.name in {"AGENTS.md", "System", "Zones", "Wikis", ".git", ".gitignore", ".claude", ".agents"}]
        if clashes:
            raise InstallError(f"{t} already has {', '.join(sorted(clashes))}; Garrick will not overwrite them.")
    return resolved


def check_git():
    try:
        r = subprocess.run(["git", "--version"], capture_output=True, text=True)
    except FileNotFoundError:
        r = None
    if r is None or r.returncode != 0:
        raise InstallError("git is not installed. Run `xcode-select --install`, let it finish, then rerun.")


# --------------------------------------------------------------------------- writing


class Writer:
    """Every write goes through here, and nothing lands outside the target."""

    def __init__(self, root):
        self.root = root

    def _inside(self, path):
        p = Path(os.path.abspath(path))
        if p != self.root and self.root not in p.parents:
            raise InstallError(f"Refusing to write outside the workspace: {p}")
        return p

    def mkdir(self, path):
        self._inside(path).mkdir(parents=True, exist_ok=True)

    def write(self, path, text):
        p = self._inside(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def copy_tree(self, src, dst, skip=(), fill=None):
        """Copy src into dst, skipping names in `skip`, filling placeholders from `fill`."""
        for item in sorted(src.iterdir()):
            if item.name in skip or item.name in IGNORED_FILES or item.name.startswith("._") or item.name == "__pycache__":
                continue
            name = fill_text(item.name, fill) if fill else item.name
            out = dst / name
            if item.is_dir():
                self.mkdir(out)
                self.copy_tree(item, out, skip=(), fill=fill)
            else:
                p = self._inside(out)
                p.parent.mkdir(parents=True, exist_ok=True)
                if fill:
                    try:
                        text = item.read_text(encoding="utf-8")
                    except UnicodeDecodeError:
                        shutil.copy2(item, p)
                        continue
                    p.write_text(fill_text(text, fill), encoding="utf-8")
                    shutil.copymode(item, p)
                else:
                    shutil.copy2(item, p)

    def symlink(self, link, target_rel):
        p = self._inside(link)
        self._inside(p.parent / target_rel)  # the link must point inside too
        p.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(target_rel, p)


def fill_text(text, values):
    for key, value in values.items():
        text = text.replace(ph(key), value)
    return text


def cell(text):
    return text.replace("|", "\\|").replace("\n", " ")


def table(header_lines, rows):
    return header_lines + ["| " + " | ".join(cell(c) for c in row) + " |" for row in rows]


def render_context(template_text, cfg):
    """Replace the example rows of the template's context.md with the owner's own."""
    owner = cfg["owner"]
    rows = {
        "Zones": [[z["name"], z["holds"] or f"<What {z['name']} holds>"] for z in cfg["zones"]],
        "Parties": [[p["name"], p["what"] or "<What it is>", p["zone"], f"`{p['tag']}`", ", ".join(p["domains"])]
                    for p in cfg["parties"]],
        "Walls": [[f"`{w['between']}`", f"`{w['and']}`", w["why"] or "<Why they never meet>"] for w in cfg["walls"]],
        "People": [[p["name"], f"`{p['party']}`" if p["party"] else "", p["role"]] for p in cfg["people"]],
        "Aliases": [[a["heard"], a["means"]] for a in cfg["aliases"]],
    }
    out, section, i = [], None, 0
    lines = template_text.splitlines()
    while i < len(lines):
        line = lines[i]
        if line.startswith("## "):
            section = line[3:].strip()
        if line.strip().startswith("The rows below are examples"):
            i += 1
            if i < len(lines) and not lines[i].strip() and out and not out[-1].strip():
                i += 1  # drop the blank line that followed it
            continue
        if section == "Me" and line.startswith("<"):
            desc = owner["description"]
            if not desc.endswith((".", "!", "?")):
                desc += "."
            out.append(f"{owner['name']}. {desc}")
            i += 1
            continue
        if section in rows and line.startswith("|"):
            header = []
            while i < len(lines) and lines[i].startswith("|"):
                if len(header) < 2:
                    header.append(lines[i])
                i += 1
            out.extend(table(header, rows[section]))
            continue
        out.append(line)
        i += 1
    return "\n".join(out) + "\n"


def count(items, one, many):
    return f"{len(items)} {one if len(items) == 1 else many}"


def git(args, cwd, env=None):
    r = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise InstallError(f"git {' '.join(args)} failed in {cwd}: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout.strip()


def git_identity_missing(cwd):
    for key in ("user.name", "user.email"):
        r = subprocess.run(["git", "config", "--get", key], cwd=cwd, capture_output=True, text=True)
        if r.returncode != 0 or not r.stdout.strip():
            return True
    return False


def init_repo(path, message, owner_name, local_identity, paths=("-A",)):
    git(["init", "-q"], path)
    git(["symbolic-ref", "HEAD", "refs/heads/main"], path)
    if local_identity:
        git(["config", "user.name", owner_name], path)
        git(["config", "user.email", "garrick@localhost"], path)
    git(["add", "--"] + list(paths) if paths != ("-A",) else ["add", "-A"], path)
    git(["commit", "-q", "-m", message], path)


def install(cfg, target, force=False, quiet=False):
    pl = lib()
    cfg = normalise(cfg)
    problems = validate(cfg, pl)
    if problems:
        raise InstallError("The setup has problems:\n  - " + "\n  - ".join(problems))
    check_git()
    root = check_target(Path(target), force=force)
    w = Writer(root)
    w.mkdir(root)

    say = (lambda *a: None) if quiet else print

    # The root: entry point and system folder.
    shutil.copy2(TEMPLATE / "AGENTS.md", w._inside(root / "AGENTS.md"))
    w.mkdir(root / "System")
    w.copy_tree(TEMPLATE / "System", root / "System", skip=("context.md",))
    w.write(root / "System" / "context.md",
            render_context((TEMPLATE / "System" / "context.md").read_text(encoding="utf-8"), cfg))

    # The wikis: one repository for both.
    w.mkdir(root / "Wikis")
    w.copy_tree(TEMPLATE / "Wikis", root / "Wikis")

    # One folder per zone.
    for z in cfg["zones"]:
        zdir = root / "Zones" / z["name"]
        w.mkdir(zdir)
        w.copy_tree(TEMPLATE / "Zones" / "_zone", zdir, fill={"ZONE": z["name"]})

    # Skill discovery. Claude Code reads .claude/skills and Codex reads .agents/skills
    # from the session's folder up to its git repository root. Zones and Wikis are
    # their own repositories, so each gets its own pointer at the one skills folder.
    repos = [root, root / "Wikis"] + [root / "Zones" / z["name"] for z in cfg["zones"]]
    for repo in repos:
        rel = os.path.relpath(root / "System" / "skills", repo / ".claude")
        for harness in (".claude", ".agents"):
            w.symlink(repo / harness / "skills", rel)

    ignore = (".DS_Store\n._*\n__pycache__/\n"
              "# Obsidian rewrites these on every pan, zoom and click, in whichever folder is opened as a vault.\n"
              "**/.obsidian/workspace*.json\n**/.obsidian/graph.json\n")
    inbox = "# Mail and files wait in Inbox/ until they are filed where they belong; they never enter this history.\nInbox/*\n!Inbox/.gitkeep\n"
    generated = "# Pages tools write for you, such as the status page: rebuilt, never committed.\nSystem/generated/\n"
    w.write(root / ".gitignore", "# Zones and wikis are their own repositories.\nZones/\nWikis/\n" + generated + ignore)
    for repo in repos[1:]:
        w.write(repo / ".gitignore", ignore + (inbox if repo.parent == root / "Zones" else ""))

    local_identity = git_identity_missing(root)
    for repo in repos[1:]:
        init_repo(repo, f"Garrick: {repo.name} created", cfg["owner"]["name"], local_identity)
    # Only what Garrick wrote: with --force the folder may hold the user's own files.
    init_repo(root, "Garrick: workspace created", cfg["owner"]["name"], local_identity,
              paths=("AGENTS.md", "System", ".gitignore", ".claude", ".agents"))

    # Each zone refuses a commit that would carry walled material into its history.
    for z in cfg["zones"]:
        zdir = root / "Zones" / z["name"]
        w._inside(zdir / ".git" / "hooks" / "pre-commit")
        try:
            pl.install_wall_hook(zdir)
        except (FileExistsError, FileNotFoundError) as exc:
            raise InstallError(f"Could not install the wall check: {exc}")
    hooks_path = subprocess.run(["git", "config", "--get", "core.hooksPath"], cwd=root, capture_output=True, text=True)

    say("")
    say(f"Your workspace is ready at {root}")
    say(f"  Zones: {', '.join(z['name'] for z in cfg['zones'])}, each its own folder and history.")
    say("  Two memories, Meetings and Knowledge, under Wikis, both empty for now.")
    say("  Each zone has an Inbox folder: drop mail or any file there, and say \"process the inbox\".")
    say(f"  {count(cfg['parties'], 'party', 'parties')}, {count(cfg['walls'], 'wall', 'walls')} "
        f"and {count(cfg['people'], 'person', 'people')} in System/context.md.")
    if hooks_path.returncode == 0 and hooks_path.stdout.strip():
        say(f"  git is set to take its hooks from {hooks_path.stdout.strip()}, so the wall check will not run before commits.")
        say("  To turn it on, run in each zone: git config core.hooksPath .git/hooks")
    else:
        say("  Each zone checks the walls before every commit.")
    if local_identity:
        say("  git had no name or email set, so commits here carry your name and the address garrick@localhost. "
            "Nothing needs changing.")
        say(f"  To use your own address instead, run this in {root}:")
        say(f"    {OWN_ADDRESS}")
    say("")
    say(f"Next: open {root} in your Claude or ChatGPT app, or start claude or codex there.")
    return root


# --------------------------------------------------------------------------- questions


def ask(prompt, default=None):
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"{prompt}{suffix}\n> ").strip()
    except EOFError:
        # Out of answers: stop, rather than ask forever or take "y" as the answer to "Go ahead?".
        print()
        raise InstallError("The input ended before the last question, so nothing was written.") from None
    print()
    return answer or (default or "")


def home_relative(answer):
    """A folder typed at the question. A relative one goes in the home folder, not in
    the folder the installer was started from, which is usually Garrick's own."""
    p = Path(answer).expanduser()
    return p if p.is_absolute() else Path.home() / p


def tag_guess(name, taken=()):
    """The tag the question offers for a party: its first word, or its first words
    joined by hyphens, in lowercase. Only one the question would accept: valid and
    not taken. "" when there is none, such as for 4Birch, whose tag cannot start with 4."""
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    words = [w for w in (re.sub(r"[^a-z0-9]", "", w) for w in plain.split()) if w]
    for n in range(1, len(words) + 1):
        guess = "-".join(words[:n])
        if TAG_RE.match(guess) and guess not in taken:
            return guess
    return ""


def example_wall(tags):
    """A pair of example tags for the walls question that is not the user's own."""
    return next((pair for pair in EXAMPLE_WALLS if not set(pair) & set(tags)), EXAMPLE_WALLS[-1])


def interview(pl, target=None, force=False):
    check_git()  # before the first question, not after the last
    print("Garrick setup. A few questions, one at a time. Press Enter to accept what is in [brackets].\n")

    while True:
        # --target keeps its usual meaning, relative to the current folder.
        folder = Path(target).expanduser() if target else home_relative(
            ask("Where should the workspace go?", suggestion()))
        try:
            root = check_target(folder, force=force)
            break
        except InstallError as exc:
            print(exc, "\n")
            target = None

    name = ""
    while not name:
        name = ask("What is your name?")
    desc = ""
    while not desc:
        desc = ask("In one line: what do you do, and for whom?")

    while True:
        raw = ask("Zones are the separate sides of your life, each kept apart. Type their names separated by commas.",
                  ", ".join(DEFAULT_ZONES))
        names = [n.strip() for n in raw.split(",") if n.strip()]
        errors, seen = [], []
        for n in names:
            err = check_zone_name(n, seen, pl)
            if err:
                errors.append(err)
            seen.append(n)
        if names and not errors:
            break
        print("\n".join(errors or ["Name at least one zone."]), "\n")
    zones = [{"name": n, "holds": ask(f"What goes in {n}, in a few words? (Enter to skip)")} for n in names]

    print("Now the parties: every organisation or person whose confidences you hold. You can add more later.\n")
    parties = []
    while True:
        pname = ask("Name of a party (Enter when done):")
        if not pname:
            break
        what = ask(f"What is {pname}, in a few words?")
        zone = names[0]
        if len(names) > 1:
            while True:
                zone = ask(f"Which zone is {pname} in? ({', '.join(names)})", names[0])
                match = [n for n in names if n.lower() == zone.lower()]
                if match:
                    zone = match[0]
                    break
                print(f"That is not one of your zones: {', '.join(names)}.\n")
        taken = {p["tag"]: p["name"] for p in parties}
        guess = tag_guess(pname, taken)
        while True:
            tag = ask(f"A short tag for {pname}, used in notes: one lowercase word that starts with a letter.",
                      guess).strip("`")
            if tag in taken:
                print(f"{tag} is already the tag for {taken[tag]}. Pick another.\n")
            elif TAG_RE.match(tag):
                break
            else:
                print(f"A tag is {TAG_RULE}, such as acme or acme-uk.\n")
        taken_domains = {d: p["name"] for p in parties for d in p["domains"]}
        while True:
            domains = domain_list(ask(f"Mail domains for {pname}: the part after the @ in their addresses, "
                                      "separated by commas. Optional; press Enter to skip."))
            problems = domain_problems(pname, domains, taken_domains, pl)
            if not problems:
                break
            print("\n".join(problems), "\n")
        parties.append({"name": pname, "what": what, "zone": zone, "tag": tag, "domains": domains})

    tags = [p["tag"] for p in parties]
    walls = []
    if len(tags) >= 2:
        print(f"Walls: pairs of parties whose material must never meet. None is assumed. "
              f"Your tags: {', '.join(tags)}.\n")
        a, b = example_wall(tags)
        while True:
            pair = ask(f"Two of your tags with a wall between them, separated by a space. For example, "
                       f"two clients tagged {a} and {b} would be \"{a} {b}\". (Enter when done)")
            if not pair:
                break
            bits = pair.replace(",", " ").split()
            if len(bits) != 2 or bits[0] == bits[1] or any(b not in tags for b in bits):
                print(f"Type two different tags from: {', '.join(tags)}.\n")
                continue
            walls.append({"between": bits[0], "and": bits[1], "why": ask("Why? (Enter to skip)")})

    people = []
    while True:
        person = ask("People you deal with, so names are recognised. A name (Enter to skip):")
        if not person:
            break
        party = ""
        if tags:
            while True:
                party = ask(f"Which party is {person} with? ({', '.join(tags)}, or Enter for none)")
                if not party or party in tags:
                    break
                print(f"Use one of: {', '.join(tags)}.\n")
        people.append({"name": person, "party": party, "role": ask(f"{person}'s role, in a few words?")})

    print("Aliases: names that dictation writes wrongly, and what they mean. Most people skip this now, "
          "before they have dictated anything. Your assistant adds one to the Aliases table in "
          "System/context.md whenever it has to ask what a name meant, and you can add them there yourself.\n")
    aliases = []
    while True:
        heard = ask("A name as dictation wrote it (Enter to skip):")
        if not heard:
            break
        means = ask(f'What does "{heard}" mean?')
        if means:
            aliases.append({"heard": heard, "means": means})
        else:
            print(f'Skipped "{heard}": an alias needs what it means.\n')

    cfg = {"owner": {"name": name, "description": desc}, "zones": zones, "parties": parties,
           "walls": walls, "people": people, "aliases": aliases}
    print(f"Ready to install in {root}: {count(zones, 'zone', 'zones')}, "
          f"{count(parties, 'party', 'parties')}, {count(walls, 'wall', 'walls')}.")
    if ask("Go ahead? (y/n)", "y").lower() not in ("y", "yes"):
        print("Nothing was written.")
        sys.exit(1)
    return cfg, root


# --------------------------------------------------------------------------- main


def main(argv=None):
    ap = argparse.ArgumentParser(description="Install a Garrick workspace.")
    ap.add_argument("--config", help="JSON file with the answers; skips the questions")
    ap.add_argument("--target", help=f"folder to install into (default {DEFAULT_TARGET})")
    ap.add_argument("--force", action="store_true", help="allow a folder that already has other files in it")
    args = ap.parse_args(argv)
    try:
        if args.config:
            try:
                cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise InstallError(f"Could not read {args.config}: {exc}")
            target = args.target or cfg.get("target") or DEFAULT_TARGET
        else:
            cfg, target = interview(lib(), args.target, args.force)
        install(cfg, Path(target).expanduser(), force=args.force)
    except InstallError as exc:
        print(exc, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
