#!/usr/bin/env python3
"""Install a Garrick workspace.

    python3 install.py                                   asks, one question at a time
    python3 install.py --config FILE.json --target PATH  no questions (guided sessions, tests, demos)
    python3 install.py --update ~/Garrick [--apply]      bring an installed workspace up to this Garrick
    python3 install.py --allowlist ~/Garrick             allow Garrick's own commands there, and nothing else

Python 3.9+, standard library only. Writes nothing outside the target folder.
"""

import sys

if sys.version_info < (3, 9):
    sys.exit("Garrick needs Python 3.9 or later; this is %d.%d. "
             "Install the Command Line Tools (xcode-select --install) and run it with /usr/bin/python3."
             % sys.version_info[:2])

import argparse
import importlib.util
import json
import os
import posixpath
import re
import shutil
import subprocess
import urllib.parse
from pathlib import Path

REPO = Path(__file__).resolve().parent
TEMPLATE = REPO / "template"
TOOLS = TEMPLATE / "System" / "tools"
# Git fills in this file's lines when GitHub serves a download (export-subst in
# .gitattributes); in a clone they stay as written, and git is asked instead.
VERSION_FILE = REPO / "VERSION"

DEFAULT_TARGET = "~/Garrick"
# Offered instead when the default is Garrick's own folder: a Mac ignores capitals
# in folder names, so a clone at ~/garrick is also ~/Garrick.
OTHER_TARGET = "~/Garrick-workspace"
DEFAULT_ZONES = ["Work", "Personal"]
# macOS privacy protection stops scheduled jobs from reading these folders.
PROTECTED = ["Documents", "Desktop", "Downloads", "Library"]
IGNORED_FILES = {".DS_Store"}

# What of docs/ a workspace gets, in System/garrick-docs/: every page outside
# docs/assets/, and the images those pages show. A file a page only links to
# stays on GitHub, where the Guide sends that link.
DOC_IMAGE = re.compile(r"!\[[^\]]*\]\(\s*<?([^)\s>]+)")
DOC_CODE = re.compile(r"```.*?```|~~~.*?~~~|`[^`\n]*`", re.S)


def shipped_docs(names, read):
    """The files of docs/ a workspace gets, by their paths from docs/, given
    every file there (`names`) and a way to read a page's text (`read`). The
    installer, update.py's shipped() and its release_hashes() all ask this,
    so the three agree on what Garrick writes."""
    names = set(names)
    pages = sorted(n for n in names if n.endswith(".md") and not n.startswith("assets/"))
    out = set(pages)
    for page in pages:
        for target in DOC_IMAGE.findall(DOC_CODE.sub("", read(page))):
            if target.startswith("/") or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target):
                continue                                  # a web address, or none of the docs' own
            image = posixpath.normpath(posixpath.join(posixpath.dirname(page),
                                                      urllib.parse.unquote(target.split("#", 1)[0])))
            if image in names:
                out.add(image)
    return sorted(out)


def docs_files(docs=None):
    """shipped_docs() for a docs folder on disk, by default this Garrick's."""
    docs = Path(docs) if docs is not None else REPO / "docs"
    if not docs.is_dir():
        return []
    names = [p.relative_to(docs).as_posix() for p in docs.rglob("*")
             if p.is_file() and p.name not in IGNORED_FILES and not any(part.startswith(".") for part in p.relative_to(docs).parts)]
    return shipped_docs(names, lambda n: (docs / n).read_text(encoding="utf-8"))
# The tag rule and the tag the questions offer live in the library, beside the
# naming layer: `garrick_lib.TAG_RE`, `TAG_RULE` and `tag_for`. This file is not
# shipped into a workspace, so a copy here could not be reached by the workspace's
# own tools, and `scaffold.py party` offers a tag long after the install.
# The one way to put your own address on the workspace's repositories when git had
# none. docs/commands.md gives the same command; a test keeps them alike.
OWN_ADDRESS = 'for repo in . Wikis Zones/*; do git -C "$repo" config user.email "you@example.com"; done'

# What the assistant may run without asking, when the last question is answered
# yes. Garrick's own tools, named one at a time, as the skills run them: never
# one blanket rule for everything under System/, which would also cover
# whatever the user puts there later. System/tools/release.py and
# notifications.py are not here: they are the two tools that reach the network.
ALLOWED_TOOLS = (
    "System/tools/check.py",
    "System/tools/probe.py",
    "System/tools/scaffold.py",
    "System/tools/wiki_lint.py",
    "System/tools/drift.py",
    "System/tools/next_up.py",
    "System/tools/nurture.py",
    "System/tools/discover.py",
    "System/tools/extract.py",
    "System/skills/intake/intake.py",
    "System/skills/meetings/ingest.py",
    "System/skills/todo/todo.py",
)
# git's words that only look at history, or save it on this Mac.
ALLOWED_GIT = ("status", "diff", "log", "add", "commit")
# The words no rule may carry: the first five reach the internet, the rest can
# throw work away. Nor may a rule stop at a folder, `git -C Zones/Work`, which
# would let every git command run there, push included.
REFUSED_GIT = ("push", "pull", "fetch", "clone", "remote",
               "reset", "checkout", "restore", "clean", "rm", "--force")
# Claude Code is the only host with a per-workspace setting, so it is the only
# one that gets rules; Codex's approval setting belongs to the user's account,
# and the installer says which to choose instead. The rules live here, on the
# installer's side, and not in template/, which depends on no one assistant.
CLAUDE_SETTINGS = ".claude/settings.json"
# A path a command line can carry without quotes, so both spellings are worth a rule.
PLAIN_PATH = re.compile(r"^[A-Za-z0-9/._-]+$")
# The page a workspace made now opens on (#175), "simple" or "full": written as
# its "home" setting, and on the simple home its zones' lists start without the
# zone template's example line.
NEW_HOME = "simple"


class InstallError(Exception):
    """A refusal or failure, worded for the person installing."""


def ph(key):
    """A placeholder, spelled without writing the braces literally."""
    return "{" * 2 + key + "}" * 2


def lib():
    sys.dont_write_bytecode = True  # leave template/System/tools free of __pycache__
    if str(TOOLS) not in sys.path:
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
    # Allowing Garrick's own commands is the last question, and its default is yes;
    # a config file left silent gets the same answer, so a --config run asks nothing.
    allow = raw.get("allow-commands")
    return {
        "owner": {"name": str(owner.get("name", "")).strip(),
                  "description": str(owner.get("description", "")).strip()},
        "zones": zones,
        "parties": parties,
        "walls": walls,
        "people": people,
        "aliases": aliases,
        "allow_commands": True if allow is None else bool(allow),
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
    """A zone has no note to carry a spoken form, so its name has to say how it
    is said: the strictest of the three naming questions, not just the folder's."""
    ok, reason = pl.is_sayable(name)      # which asks the other two first
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
        if not pl.TAG_RE.match(p["tag"]):
            problems.append(f'The tag for {label} ("{p["tag"]}") must be {pl.TAG_RULE}.')
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
        self.written = []       # every file, in order, for the stamp's fingerprints

    def _wrote(self, p):
        if p not in self.written:
            self.written.append(p)

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
        self._wrote(p)

    def copy_file(self, src, dst):
        p = self._inside(dst)
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, p)
        self._wrote(p)

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
                        self._wrote(p)
                        continue
                    p.write_text(fill_text(text, fill), encoding="utf-8")
                    shutil.copymode(item, p)
                else:
                    shutil.copy2(item, p)
                self._wrote(p)

    def symlink(self, link, target_rel):
        p = self._inside(link)
        self._inside(p.parent / target_rel)  # the link must point inside too
        p.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(target_rel, p)


def fill_text(text, values):
    for key, value in values.items():
        text = text.replace(ph(key), value)
    return text


def table(header_lines, rows):
    return header_lines + [lib().table_row(row) for row in rows]


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


def ignore_files(zones):
    """The .gitignore of every repository the installer makes, and the zone
    template's, which a zone added later copies: {path from the top: text}.
    Garrick's lines sit between two markers, so that your own can go anywhere
    outside them; an update replaces only what is between (see update.py)."""
    lib_ = lib()
    return {path: lib_.ignore_block(lines) for path, lines in lib_.garrick_ignores(zones).items()}


def joined(words, last="and"):
    """"status, diff, log, add and commit", for a sentence."""
    words = list(words)
    return "%s %s %s" % (", ".join(words[:-1]), last, words[-1]) if len(words) > 1 else "".join(words)


def claude_allow_rules(zones):
    """The commands Garrick asks to have allowed in a workspace with these
    zones: one prefix rule per tool, and five per repository the installer
    makes, in the shape extras/jobs/headless-settings.json uses. A prefix rule
    matches the start of the command string, so each repository is spelled as
    the skills spell it: a zone's path in quotes, since a zone name may hold a
    space, and plain as well, for the names that need no quotes."""
    rules = ["Bash(python3 %s:*)" % tool for tool in ALLOWED_TOOLS]
    for repo in [".", "Wikis"] + ["Zones/%s" % z for z in zones]:
        spellings = ['"%s"' % repo] if repo.startswith("Zones/") else []
        if PLAIN_PATH.match(repo):
            spellings.append(repo)          # a name with a space is only ever written in quotes
        rules += ["Bash(git -C %s %s:*)" % (spelling, word)
                  for spelling in spellings for word in ALLOWED_GIT]
    return rules


def read_json_file(path, what):
    """The JSON object in `path`, or {} where there is no file. A file that
    does not read is a refusal, not something to overwrite."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise InstallError(f"{what} could not be read: {exc}") from None
    try:
        data = json.loads(text) if text.strip() else {}
    except ValueError as exc:
        raise InstallError(f"{what} is not JSON Garrick can add to ({exc}). It is left as it is; "
                           "allow the commands yourself, as the first-steps page describes.") from None
    if not isinstance(data, dict):
        raise InstallError(f"{what} does not hold a JSON object, so Garrick cannot add to it.")
    return data


def with_allow_rules(settings, rules):
    """`settings`, read from the assistant's own settings file, with `rules`
    added to permissions.allow. Everything already there stays, in its own
    order, and a rule already there is not added twice: nothing is overwritten.
    Returns (the settings, the rules it added)."""
    perms = settings.setdefault("permissions", {})
    if not isinstance(perms, dict):
        raise InstallError(f'{CLAUDE_SETTINGS} has a "permissions" that is not an object, '
                           "so Garrick cannot add to it.")
    allow = perms.setdefault("allow", [])
    if not isinstance(allow, list):
        raise InstallError(f'{CLAUDE_SETTINGS} has a "permissions.allow" that is not a list, '
                           "so Garrick cannot add to it.")
    added = [rule for rule in rules if rule not in allow]
    allow.extend(added)
    return settings, added


def allowlist_files(root, zones):
    """The two files to write when the commands are allowed: the assistant's
    own settings with Garrick's rules in them, and the workspace's settings
    recording which rules are Garrick's, so an update can replace its own and
    leave the user's. ({path from the top: text}, the rules, those it added)."""
    pl = lib()
    rules = claude_allow_rules(zones)
    settings, added = with_allow_rules(read_json_file(Path(root) / CLAUDE_SETTINGS, CLAUDE_SETTINGS), rules)
    recorded = "/".join(pl.SETTINGS)
    ours = read_json_file(Path(root) / recorded, recorded)
    ours[pl.ALLOWED_COMMANDS] = rules
    return ({CLAUDE_SETTINGS: json.dumps(settings, indent=2) + "\n",
             recorded: json.dumps(ours, indent=2) + "\n"}, rules, added)


def allowed_lines(rules):
    """What to say about the rules just written, for either route in."""
    return [
        f"Your assistant may run Garrick's own tools, and git's {joined(ALLOWED_GIT)} inside the workspace, "
        f"without asking each time: {len(rules)} rules in {CLAUDE_SETTINGS}, for Claude Code.",
        f"Nothing else: no {joined(REFUSED_GIT, 'or')}, and nothing outside the workspace.",
        "Codex has one approval setting for your whole account rather than one per workspace, so there is "
        "nothing to write for it: choose the setting that lets Codex work inside the workspace on its own "
        "and ask before it runs commands outside the workspace or reaches the internet.",
    ]


def workspace_zones(root):
    """The zones of a workspace already installed."""
    zones = Path(root) / "Zones"
    return sorted(d.name for d in zones.iterdir()
                  if d.is_dir() and not d.name.startswith((".", "_"))) if zones.is_dir() else []


def allow_commands(root):
    """--allowlist: write the rules into a workspace already installed, for
    someone who declined the question or installed before it existed. Writes
    the same two files and nothing else, and overwrites neither."""
    root = Path(root).expanduser().resolve()
    if not (root / "AGENTS.md").is_file() or not (root / "System").is_dir():
        raise InstallError(f"{root} does not look like a Garrick workspace.")
    files, rules, added = allowlist_files(root, workspace_zones(root))
    w = Writer(root)
    for rel, text in files.items():
        w.write(root / rel, text)
    print(f"Allowed in {root}: {len(added)} of {len(rules)} rules added to {CLAUDE_SETTINGS}.")
    for line in allowed_lines(rules):
        print("  " + line)
    print("  To save it: git add -- %s %s && git commit -m \"Settings: Garrick's own commands allowed\""
          % (CLAUDE_SETTINGS, "/".join(lib().SETTINGS)))
    return 0


def count(items, one, many):
    return f"{len(items)} {one if len(items) == 1 else many}"


def git_identity_missing(cwd):
    for key in ("user.name", "user.email"):
        r = subprocess.run(["git", "config", "--get", key], cwd=cwd, capture_output=True, text=True)
        if r.returncode != 0 or not r.stdout.strip():
            return True
    return False


def init_repo(path, message, owner_name, local_identity, paths=None):
    """garrick_lib makes the repository, as it does for a zone scaffold.py adds later."""
    pl = lib()
    identity = {"user.name": owner_name, "user.email": pl.LOCAL_EMAIL} if local_identity else None
    try:
        pl.init_repo(path, message, identity, paths)
    except pl.GitError as exc:
        raise InstallError(str(exc)) from None


def source_version():
    """Which Garrick is installing: its commit and that commit's date, and
    whether it came as a download or a clone. A clone with edits not committed
    says so, since its commit no longer tells the whole story."""
    fields = {}
    try:
        for line in VERSION_FILE.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition(":")
            if sep and not line.startswith("#"):
                fields[key.strip()] = value.strip()
    except OSError:
        pass
    if fields.get("commit") and "$" not in fields["commit"]:
        return {"commit": fields["commit"], "date": fields.get("date", ""), "from": "download"}

    def git(*args):
        try:
            return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return None

    top = git("rev-parse", "--show-toplevel")
    if top is not None and top.returncode == 0 and same_folder(Path(top.stdout.strip()), REPO):
        head = git("log", "-1", "--format=%h %cs")
        status = git("status", "--porcelain", "--untracked-files=no")
        if head is not None and head.returncode == 0 and len(head.stdout.split()) == 2:
            commit, date = head.stdout.split()
            return {"commit": commit, "date": date, "from": "clone",
                    "modified": bool(status is not None and status.stdout.strip())}
    return {"commit": "unknown", "date": "", "from": "copy"}


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
    w.copy_file(TEMPLATE / "AGENTS.md", root / "AGENTS.md")
    w.mkdir(root / "System")
    w.copy_tree(TEMPLATE / "System", root / "System", skip=("context.md",))
    w.write(root / "System" / "context.md",
            render_context((TEMPLATE / "System" / "context.md").read_text(encoding="utf-8"), cfg))
    # The release notes of this Garrick, which the status page shows without fetching anything.
    if (REPO / "CHANGELOG.md").is_file():
        w.copy_file(REPO / "CHANGELOG.md", root / "System" / "garrick-changelog.md")
    # Its docs, which the assistant answers from and the Garrick App's Guide tab shows.
    for rel in docs_files():
        w.copy_file(REPO / "docs" / rel, root.joinpath(*pl.DOCS_COPY, *rel.split("/")))

    # The wikis: one repository for both.
    w.mkdir(root / "Wikis")
    w.copy_tree(TEMPLATE / "Wikis", root / "Wikis")

    # One folder per zone, from the template that System/tools/scaffold.py uses for a zone added later.
    # A workspace that will open on the simple home (below) starts each list without its example line.
    simple = NEW_HOME == "simple"
    for z in cfg["zones"]:
        zdir = root / "Zones" / z["name"]
        w.mkdir(zdir)
        w.copy_tree(TEMPLATE.joinpath(*pl.ZONE_TEMPLATE), zdir, fill={"ZONE": z["name"]})
        if simple:
            todo = zdir / pl.ZONE_TODO
            w.write(todo, pl.zone_todo(todo.read_text(encoding="utf-8"), True))

    # Skill discovery. Claude Code reads .claude/skills and Codex reads .agents/skills
    # from the session's folder up to its git repository root. Zones and Wikis are
    # their own repositories, so each gets its own pointer at the one skills folder.
    repos = [root, root / "Wikis"] + [root / "Zones" / z["name"] for z in cfg["zones"]]
    for repo in repos:
        for link, points_to in pl.skill_links(root, repo):
            w.symlink(link, points_to)

    for rel, text in ignore_files([z["name"] for z in cfg["zones"]]).items():
        if not rel.startswith("System/"):          # the zone template's comes after the repositories exist
            w.write(root / rel, text)

    local_identity = git_identity_missing(root)
    for repo in repos[1:]:
        init_repo(repo, f"Garrick: {repo.name} created", cfg["owner"]["name"], local_identity)
    # A zone added later is copied from the zone template, so the template keeps the
    # ignore file every zone was just given: its inbox stays out of that zone's history too.
    zone_ignore = "/".join(pl.ZONE_TEMPLATE + (".gitignore",))
    w.write(root / zone_ignore, ignore_files([])[zone_ignore])
    # The commands the assistant may run without asking, on a yes. The two files
    # are the workspace's own from the start, so neither is fingerprinted below:
    # what Garrick wrote is recorded in System/garrick-settings.json instead.
    allowed = []
    if cfg["allow_commands"]:
        files, allowed, _ = allowlist_files(root, [z["name"] for z in cfg["zones"]])
        for rel, text in files.items():
            w.write(root / rel, text)

    # The status page opens a workspace made now on the simple home (#175). One
    # installed before it has no "home" and keeps the page it had; Settings ›
    # Home switches either way. The file is the workspace's own, never fingerprinted.
    recorded = "/".join(pl.SETTINGS)
    ours = read_json_file(root / recorded, recorded)
    ours.setdefault("home", NEW_HOME)
    w.write(root / recorded, json.dumps(ours, indent=2) + "\n")

    # Which Garrick this is, and a fingerprint of every file it just wrote, so an
    # update can tell a file still as installed from one the user has changed.
    stamp = source_version()
    stamp["files"] = pl.fingerprints(root, w.written)
    w.write(root.joinpath(*pl.VERSION_STAMP), json.dumps(stamp, indent=2) + "\n")
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
    hooks_path = pl.hooks_path(root)

    say("")
    say(f"Your workspace is ready at {root}")
    say(f"  Zones: {', '.join(z['name'] for z in cfg['zones'])}, each its own folder and history.")
    say("  Two memories, Meetings and Knowledge, under Wikis, both empty for now.")
    say("  Each zone has an Inbox folder: drop mail or any file there, and say \"process the inbox\".")
    say(f"  {count(cfg['parties'], 'party', 'parties')}, {count(cfg['walls'], 'wall', 'walls')} "
        f"and {count(cfg['people'], 'person', 'people')} in System/context.md.")
    if hooks_path:
        say(f"  git is set to take its hooks from {hooks_path}, so the wall check will not run before commits.")
        say("  To turn it on, run in each zone: git config core.hooksPath .git/hooks")
    else:
        say("  Each zone checks the walls before every commit.")
    if allowed:
        for line in allowed_lines(allowed):
            say("  " + line)
    else:
        say("  No command is allowed in advance, so your assistant asks before each one.")
    say("  More zones and parties can come later: ask your assistant.")
    if local_identity:
        say("  git had no name or email set, so commits here carry your name and the address garrick@localhost. "
            "Nothing needs changing.")
        say(f"  To use your own address instead, run this in {root}:")
        say(f"    {OWN_ADDRESS}")
    say("")
    say(f"Next: open {root} in your Claude or ChatGPT app, or start claude or codex there, and say \"set up Garrick\".")
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

    # One round for parties, which Enter skips. Each name becomes a party with a tag
    # taken from the name; its zone is asked only when there is more than one.
    # Domains, walls, people and aliases are not asked: the first session adds
    # them when something needs them, and a --config file can still carry them.
    raw = ask("Who do you work for or with? Names, separated by commas. Enter to skip.")
    parties = []
    for pname in [n.strip() for n in raw.split(",") if n.strip()]:
        if any(p["name"].lower() == pname.lower() for p in parties):
            continue
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
        tag = pl.tag_for(pname, taken, zone)
        while not tag:  # only a name with no letter to start a tag from, such as 4Birch
            tag = ask(f"A short tag for {pname}, used in notes: one lowercase word that starts with a letter.").strip("`")
            if tag in taken:
                print(f"{tag} is already the tag for {taken[tag]}. Pick another.\n")
                tag = ""
            elif not pl.TAG_RE.match(tag):
                print(f"A tag is {pl.TAG_RULE}, such as acme or acme-uk.\n")
                tag = ""
        parties.append({"name": pname, "what": "", "zone": zone, "tag": tag, "domains": []})

    allow = ask("May your assistant run Garrick's own tools, and git's %s inside the workspace, without "
                "asking each time? None of them sends anything off your Mac. (y/n)" % joined(ALLOWED_GIT),
                "y").lower() in ("y", "yes")

    cfg = {"owner": {"name": name, "description": desc}, "zones": zones, "parties": parties,
           "allow-commands": allow}
    print(f"Ready to install in {root}: {count(zones, 'zone', 'zones')}, {count(parties, 'party', 'parties')}.")
    if ask("Go ahead? (y/n)", "y").lower() not in ("y", "yes"):
        print("Nothing was written.")
        sys.exit(1)
    return cfg, root


# --------------------------------------------------------------------------- the example

EXAMPLE_BUILD = REPO / "examples" / "example-work" / "build.py"


def add_example(root):
    """--example: Robin Hale's work at Quillfield Furniture, added to the
    workspace just installed, as examples/example-work/build.py --add does."""
    if not EXAMPLE_BUILD.is_file():
        raise InstallError(f"{EXAMPLE_BUILD} is missing, so the example could not be added.")
    spec = importlib.util.spec_from_file_location("garrick_example_build", EXAMPLE_BUILD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        module.add(root)
    except module.BuildError as exc:
        raise InstallError(f"The workspace is installed, but the example could not be added: {exc}") from None


# --------------------------------------------------------------------------- main


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--update" in argv:                     # bring an installed workspace up to this Garrick
        argv.remove("--update")
        import update
        return update.main(argv)
    ap = argparse.ArgumentParser(description="Install a Garrick workspace.")
    ap.add_argument("--config", help="JSON file with the answers; skips the questions")
    ap.add_argument("--target", help=f"folder to install into (default {DEFAULT_TARGET})")
    ap.add_argument("--force", action="store_true", help="allow a folder that already has other files in it")
    ap.add_argument("--allowlist", metavar="WORKSPACE",
                    help="allow Garrick's own commands in a workspace already installed, and change nothing else")
    ap.add_argument("--example", action="store_true",
                    help="add the worked example, Robin Hale's work at Quillfield Furniture, as a zone of its own "
                         "that System/tools/example.py removes again")
    args = ap.parse_args(argv)
    try:
        if args.allowlist:
            return allow_commands(args.allowlist)
        if args.config:
            try:
                cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise InstallError(f"Could not read {args.config}: {exc}")
            target = args.target or cfg.get("target") or DEFAULT_TARGET
        else:
            cfg, target = interview(lib(), args.target, args.force)
        root = install(cfg, Path(target).expanduser(), force=args.force)
        if args.example:
            add_example(root)
    except InstallError as exc:
        print(exc, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
