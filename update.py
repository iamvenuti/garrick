#!/usr/bin/env python3
"""Bring a Garrick workspace up to this Garrick, without losing what you changed.

    python3 install.py --update ~/Garrick                    say what would change; changes nothing
    python3 install.py --update ~/Garrick --apply            do it
    python3 install.py --update ~/Garrick --apply --only System/tools/check.py,System/rules.md
    python3 install.py --update ~/Garrick --json             the same report, for a program
    python3 install.py --update ~/Garrick --split            move your text out of Garrick's instruction files

Run it from the newer Garrick: a fresh download, or a clone after `git pull`.
It compares every file Garrick would write today with the one in the
workspace, and with the fingerprint the workspace recorded when Garrick wrote
it (`System/garrick-version.json`), and sorts each into one of these:

- **replace**: a file still as some Garrick wrote it, with a newer version.
- **add**: a file new in this Garrick.
- **merge**: a file you changed that Garrick has changed too. Garrick's version
  goes beside it as `<name>.new`, and yours stays as it is. The `.new` is
  committed, so it survives a clean or a clone until you merge it. Once it is
  written the file counts as offered, and is offered again only when a later
  Garrick changes it again.
- **split**: one of Garrick's instruction files, `System/rules.md` or an
  `AGENTS.md`, that you changed. Those stay as Garrick ships them, and your
  own rules and routing go in the local file beside each, `rules.local.md` or
  `AGENTS.local.md`, which Garrick never ships or changes. The file is left as
  it is, with no `.new`; `--split` moves your text into the local file (see
  split.py) and puts Garrick's back.
- **yours**: a file Garrick only starts, such as a zone's `Todo.md` or a wiki's
  log, that you have since filled in. Never touched, not even with a `.new`.
- **restore**: a file Garrick ships that you deleted. Put back only when named
  with `--only`.
- **retired**: a file Garrick wrote that it no longer ships. Never deleted.

A `.gitignore` Garrick writes keeps Garrick's lines between two markers and
yours outside them. The update replaces only what is between the markers, and
adds them to a file that has none, keeping every line of yours; it never
offers a `.new` for one.

Two settings files are the workspace's own in the same way, and neither is
compared or replaced as a whole: `.claude/settings.json`, where the installer
writes the allow rules for Garrick's own commands, and
`System/garrick-settings.json`, which records which of those rules are
Garrick's. The update adds the rules it now writes and takes out those it no
longer writes, and leaves every other entry alone, the ones you added and the
ones of Garrick's you deleted among them. A workspace that declined the
question at install has nothing recorded, so neither file is touched.

The extras a workspace has installed are updated with the rest: the status
page in `System/status`, the scheduled jobs in `System/jobs`, and desk in
`System/cmux` with its skill in `System/skills/desk`. Their files are sorted as
the core's are, and the report names the extras it found. Once the files are
written, the update does what an extra needs next, and the report says so
first: it rebuilds Garrick.app with the flags it was built with, rebuilds the
status page with the same flags when anything in `System/status` changed, so
no page drawn by the replaced code stays up, refreshes the Obsidian plugin in
each vault that has it, and points a `desk` command linked
to another copy at the workspace's. What it cannot do, it prints: a merge to
make first, or the zone guard and the Garrick band, which run from a Garrick
kept outside the workspace.

Nothing is written without `--apply`, and nothing is ever deleted. Each
repository the update touches gets one commit of its own, holding only the
files the update wrote, `.new` files included, so `git revert` undoes it.
`System/context.md` is never read or written, but for one step: when its
Zones table has no Walled column, the update runs before it installs anything.
It prints the flag each zone would get, runs the workspace's own check (the
rule in force) and this Garrick's (the zone rule) over the workspace, and prints
every flow whose verdict changes, grouped by kind. It installs and writes only
with a yes (`--yes`, or typed at a terminal; a run without one never answers and
leaves the workspace as it was). On the yes it writes the Walled column, takes
out the Party and New parties columns and the Parties table's Walled column,
installs, and then proposes three clean-up lists, each on its own yes
(`--clean people`, `--clean ledger`, `--clean pages`). A local file beside an instruction file, such
as `System/rules.local.md`, is never read or written. The
version stamp changes last, once everything picked has applied and the
workspace's check finds no error in a file the update wrote. Running it twice
changes nothing the second time.

Garrick's scheduled jobs run under names that start with `gr-` since 0.49.0,
and one nightly job does what `nurture` and the evening status build did
(#275, #276). Your plists in `~/Library/LaunchAgents` are yours, so the update
never changes them: for each one that runs a job of Garrick's for this
workspace under its old name, the report names it and gives the commands that
unload it, rename it and load it again, for you to run. Until you do, it
keeps working as it is.

Python 3.9+, standard library only. Writes nothing outside the workspace but
the app it rebuilds and the desk link it points, both named in the report
first, and never through a symbolic link. `System/tools/release.py update`
downloads a release and runs this from it in one step.
"""

import argparse
import datetime
import fnmatch
import hashlib
import json
import os
import plistlib
import re
import shlex
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True

import install  # noqa: E402  (the installer beside this file, from the same Garrick)

REPO = install.REPO
TEMPLATE = install.TEMPLATE
RELEASE_HASHES = REPO / "release-hashes.json"

# Files Garrick writes once as a start, which become your record the moment you
# use them. While untouched they are replaced like any other; once changed they
# are yours, and an update never offers a .new for them.
SEEDS = ("Zones/*/Todo.md", "Wikis/*/wiki/index.md", "Wikis/*/wiki/log.md")
NEW_SUFFIX = ".new"

KINDS = ("replace", "add", "merge", "split", "yours", "restore", "retired")

# The extras that live in the workspace: the installer's table, which it reads
# to put the status page in place on the simple home. An extra counts as
# installed when one of its folders is in the workspace; its files are then
# updated as the core's are, and any it lacks are added.
EXTRAS = install.EXTRAS


class UpdateError(Exception):
    """A refusal or failure, worded for the person updating."""


def digest(data):
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------- what Garrick writes


def _tree(src, rel, out, fill=None, skip=()):
    """Mirror of the installer's Writer.copy_tree, into `out` instead of onto disk."""
    for item in sorted(src.iterdir()):
        if item.name in skip or item.name in install.IGNORED_FILES or item.name.startswith("._") \
                or item.name == "__pycache__":
            continue
        name = install.fill_text(item.name, fill) if fill else item.name
        path = "%s/%s" % (rel, name) if rel else name
        if item.is_dir():
            _tree(item, path, out, fill)
            continue
        data = item.read_bytes()
        if fill:
            try:
                data = install.fill_text(item.read_text(encoding="utf-8"), fill).encode("utf-8")
            except UnicodeDecodeError:
                pass
        out[path] = (data, item.stat().st_mode & 0o777)


def shipped(zones, simple=False):
    """Every file this Garrick's installer writes into a workspace with these
    zones, as {path from the top: (bytes, mode)}. Not System/context.md, which
    holds the user's answers, and not the version stamp. `simple`, for a
    workspace on the simple home: its zones' Todo.md has no example line."""
    out = {}
    _tree(TEMPLATE, "", out, skip=("System", "Wikis", "Zones"))
    _tree(TEMPLATE / "System", "System", out, skip=("context.md",))
    if (REPO / "CHANGELOG.md").is_file():
        out["System/garrick-changelog.md"] = ((REPO / "CHANGELOG.md").read_bytes(), 0o644)
    for rel in install.docs_files():
        source = REPO / "docs" / rel
        out["/".join(install.lib().DOCS_COPY + (rel,))] = (source.read_bytes(), source.stat().st_mode & 0o777)
    _tree(TEMPLATE / "Wikis", "Wikis", out)
    zone_template = TEMPLATE.joinpath(*install.lib().ZONE_TEMPLATE)
    for zone in zones:
        _tree(zone_template, "Zones/" + zone, out, fill={"ZONE": zone})
        todo = "Zones/%s/%s" % (zone, install.lib().ZONE_TODO)
        if simple and todo in out:
            data, mode = out[todo]
            out[todo] = (install.lib().zone_todo(data.decode("utf-8"), True).encode("utf-8"), mode)
    for path, text in install.ignore_files(zones).items():
        out[path] = (text.encode("utf-8"), 0o644)
    for path in list(out):
        if path in install.lib().UNLISTED:
            del out[path]
    return out


def installed_extras(root):
    """The names of the extras the workspace has: one of each one's folders is there."""
    return [name for name, _, places in EXTRAS
            if any((root / dest).is_dir() for _, dest, _ in places)]


def extras_shipped(names):
    """Every file this Garrick's extras of these names put in a workspace, as
    shipped() gives the core's."""
    out = {}
    for name, _, places in EXTRAS:
        if name not in names:
            continue
        for src, dest, skip in places:
            if (REPO / src).is_dir():
                _tree(REPO / src, dest, out, skip=skip)
    return out


def extra_place(path):
    """Where a file of this repository goes in a workspace with its extra
    installed, or None for a file no extra puts there."""
    for _, _, places in EXTRAS:
        for src, dest, skip in places:
            if path.startswith(src + "/"):
                rest = path[len(src) + 1:]
                if rest.split("/", 1)[0] not in skip:
                    return dest + "/" + rest
    return None


def allowlist(root, zones):
    """What this Garrick would change where the workspace already has the allow
    rules the installer writes: the two files to write, the rules to add and the
    rules to take out. A rule Garrick wrote and no longer writes goes; a rule
    Garrick now writes that it never recorded is added; everything else in the
    file stays, the rules the user added among them, and so does one of
    Garrick's own that the user has since deleted, which is how taking the
    allowance back holds. None where there is nothing to maintain: a workspace
    that declined the question, one whose assistant settings are gone, and one
    whose settings do not read.

    The two files are never compared or replaced as a whole (they are in
    garrick_lib.UNLISTED, so neither is fingerprinted and neither is ever
    offered as a `.new`): only the entries Garrick wrote are its own.
    """
    lib = install.lib()
    recorded = lib.allowed_commands(root)
    settings_file = root.joinpath(*lib.CLAUDE_SETTINGS)
    if not recorded or not settings_file.is_file():
        return None
    try:
        settings = install.read_json_file(settings_file, install.CLAUDE_SETTINGS)
        ours = install.read_json_file(root.joinpath(*lib.SETTINGS), "/".join(lib.SETTINGS))
    except install.InstallError as exc:
        return {"files": {}, "add": [], "remove": [], "record": False, "problem": str(exc)}
    allow = settings.get("permissions", {}).get("allow")
    if not isinstance(allow, list):
        return None
    writes = install.claude_allow_rules(zones)
    gone = [rule for rule in recorded if rule not in writes and rule in allow]
    added = [rule for rule in writes if rule not in recorded and rule not in allow]
    settings["permissions"]["allow"] = [rule for rule in allow if rule not in gone] + added
    ours[lib.ALLOWED_COMMANDS] = writes      # the order a zone was named in is not a change
    files = {install.CLAUDE_SETTINGS: ((json.dumps(settings, indent=2) + "\n").encode("utf-8"), 0o644),
             "/".join(lib.SETTINGS): ((json.dumps(ours, indent=2) + "\n").encode("utf-8"), 0o644)}
    return {"files": files, "add": added, "remove": gone, "record": sorted(recorded) != sorted(writes), "problem": ""}


def zones_of(root, stamp):
    """The zones to update: those the stamp lists files for that still have a
    folder, and every visible folder in Zones/ that is a repository of its own."""
    zones_dir = root / "Zones"
    names = {p.split("/")[1] for p in (stamp.get("files") or {}) if p.startswith("Zones/") and p.count("/") >= 2}
    names = {n for n in names if (zones_dir / n).is_dir()}     # a zone you removed is not put back
    if zones_dir.is_dir():
        names |= {d.name for d in zones_dir.iterdir()
                  if d.is_dir() and not d.name.startswith((".", "_")) and (d / ".git").exists()}
    return sorted(names)


def known_hashes(zones=()):
    """{path: [SHA-256, ...]} of every file each earlier release shipped, so a
    file still as any Garrick wrote it is known even when the stamp is older
    than the file, as after copying a fix in by hand, or has no list at all.
    A zone's files are rendered from each release's zone template with the
    zone's name, as the installer of the time did."""
    try:
        data = json.loads(RELEASE_HASHES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    known = {k: list(v) for k, v in (data.get("paths") or {}).items() if isinstance(v, list)}
    for name, texts in (data.get("zone") or {}).items():
        for zone in zones:
            known.setdefault("Zones/%s/%s" % (zone, install.fill_text(name, {"ZONE": zone})), []).extend(
                digest(install.fill_text(t, {"ZONE": zone}).encode("utf-8")) for t in texts)
    return known


# --------------------------------------------------------------------------- the plan


def is_seed(path):
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in SEEDS)


def read(path):
    try:
        return path.read_bytes()
    except OSError:
        return None


def plan(root, zones=None):
    """What an update would do, without doing any of it."""
    lib = install.lib()
    stamp = lib.read_version(root)
    listed = isinstance(stamp.get("files"), dict)
    recorded = stamp["files"] if listed else {}
    zones = zones if zones is not None else zones_of(root, stamp)
    known = known_hashes(zones)
    new = shipped(zones, simple=lib.simple_home(root))
    extras = installed_extras(root)
    new.update(extras_shipped(extras))
    actions = {kind: [] for kind in KINDS}
    current, kept = [], []
    history = {}        # repository: every path it ever committed, read once, for a stamp with no list
    ignores = lib.garrick_ignores(zones)
    for path in sorted(set(new) | set(recorded)):
        if path in lib.UNLISTED:
            continue
        on_disk = read(root / path)
        if path not in new:
            if on_disk is not None:
                actions["retired"].append(path)
            continue
        if path in ignores and on_disk is not None:
            # Garrick's block replaced, and every line outside it kept: never a .new.
            data = lib.with_ignore_block(on_disk.decode("utf-8", "replace"), ignores[path]).encode("utf-8")
            new[path] = (data, new[path][1])
            (current if data == on_disk else actions["replace"]).append(path)
            continue
        target = digest(new[path][0])
        if on_disk is None:
            removed = path in recorded or (not listed and ever_committed(root, path, history))
            actions["restore" if removed else "add"].append(path)
            continue
        have = digest(on_disk)
        if have == target:
            current.append(path)
            continue
        instruction = lib.is_instruction_file(path)
        if recorded.get(path) == target:
            # changed by you, and Garrick has nothing newer; but Garrick's instruction files stay as shipped
            (actions["split"] if instruction else kept).append(path)
            continue
        as_written = have == recorded.get(path) or have in known.get(path, ())
        if as_written:
            actions["replace"].append(path)
        elif instruction:
            actions["split"].append(path)
        elif is_seed(path):
            actions["yours"].append(path)
        else:
            actions["merge"].append(path)
    hooks = [z for z in zones if stale_hook(root / "Zones" / z)]
    return {"wiki_hook": wiki_hook_state(root), "workspace": str(root), "from": {k: stamp.get(k, "") for k in ("commit", "date")},
            "to": {k: v for k, v in install.source_version().items() if k in ("commit", "date", "from")},
            "actions": actions, "current": current, "kept": kept, "hooks": hooks, "files": new,
            "recorded": recorded, "listed": listed, "extras": extras,
            "allowlist": allowlist(root, zones),
            "renames": old_jobs(root) if "jobs" in extras and on_mac() else []}


def ever_committed(root, path, history):
    """Whether the repository holding `path` ever had it: a file missing now
    that was once committed was deleted, since an update never deletes. For a
    workspace whose stamp lists no files, installed before 0.4.0. `history`
    caches each repository's answer, so a repository costs two git commands
    however many files are missing."""
    repo = repo_of(root, path)
    if repo not in history:
        deleted = git(repo, "log", "--no-renames", "--diff-filter=D", "--name-only", "--format=", "-z",
                      check=False).stdout
        tracked = git(repo, "ls-files", "-z", check=False).stdout
        history[repo] = {x.strip("\n") for x in (deleted + "\0" + tracked).split("\0")} - {""}
    return path_in_repo(root, path) in history[repo]


def wiki_hook_state(root):
    """What the update does about the wikis' wall check (#340): "add" where
    Wikis has its own .git folder and no pre-commit hook, "refresh" where the
    hook is Garrick's and differs from what this Garrick writes, "foreign"
    where it is somebody else's (left alone, and said), else ""."""
    lib = install.lib()
    wikis = Path(root) / "Wikis"
    if not hasattr(lib, "wiki_hook_text") or not (wikis / ".git").is_dir() or (wikis / ".git").is_symlink():
        return ""
    hook = wikis / ".git" / "hooks" / "pre-commit"
    if not hook.exists():
        return "add"
    try:
        text = hook.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if lib.WALL_HOOK_MARK not in text:
        return "foreign"
    return "refresh" if text != lib.wiki_hook_text(root) else ""


def stale_hook(zone):
    """A zone whose pre-commit hook is Garrick's wall check, but an older one."""
    lib = install.lib()
    hook = zone / ".git" / "hooks" / "pre-commit"
    try:
        text = hook.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return lib.WALL_HOOK_MARK in text and text != lib.WALL_HOOK


# --------------------------------------------------------------------------- saying it


LABELS = {
    "replace": ("Replace", "file Garrick wrote that you have not changed, with a newer version",
                "files Garrick wrote that you have not changed, with a newer version"),
    "add": ("Add", "file new in this Garrick", "files new in this Garrick"),
    "merge": ("Merge", "file you changed that Garrick has changed too. Garrick's version goes beside it as .new",
              "files you changed that Garrick has changed too. Garrick's version goes beside each as .new"),
    "split": ("Split", "instruction file of Garrick's that you changed. Left as it is; your text belongs in the "
                       "local file beside it",
              "instruction files of Garrick's that you changed. Left as they are; your text belongs in the "
              "local file beside each"),
    "yours": ("Yours", "file Garrick started and you have filled in since. Left as it is",
              "files Garrick started and you have filled in since. Left as they are"),
    "restore": ("Removed by you", "file Garrick still ships. Put back only if you name it with --only",
                "files Garrick still ships. Put back only if you name them with --only"),
    "retired": ("Retired", "file Garrick no longer ships. Yours to keep or delete",
                "files Garrick no longer ships. Yours to keep or delete"),
}


def say_commit(v):
    commit = v.get("commit") or "unknown"
    return "%s of %s" % (commit, v["date"]) if v.get("date") else commit


def say_allowlist(allow, applied=None):
    """What the allow rules the installer wrote need, or what was done to them."""
    if not allow:
        return []
    if allow.get("problem"):
        return ["%s is left as it is: %s" % (install.CLAUDE_SETTINGS, allow["problem"])]
    counts = [n for n in ("%d added" % len(allow["add"]) if allow["add"] else "",
                          "%d taken out" % len(allow["remove"]) if allow["remove"] else "") if n]
    when = "" if applied else ", with --apply"
    if counts:
        return ["Allow rules Garrick wrote in %s: %s%s. Any you added are left alone." % (
            install.CLAUDE_SETTINGS, " and ".join(counts), when)]
    if allow.get("record"):
        return ["Which allow rules are Garrick's own: the record in %s is brought up to date%s, and %s is "
                "unchanged." % ("/".join(install.lib().SETTINGS), when, install.CLAUDE_SETTINGS)]
    return []


def report(p, applied=None):
    lines = ["Garrick update for %s: from %s to %s." % (p["workspace"], say_commit(p["from"]), say_commit(p["to"]))]
    if applied is None:
        lines.append("Nothing has been changed. To make these changes, run the same command with --apply.")
    for kind in KINDS:
        paths = p["actions"][kind]
        if paths:
            label, one, many = LABELS[kind]
            lines += ["", "%s, %d %s:" % (label, len(paths), one if len(paths) == 1 else many)]
            if kind == "split":
                lib = install.lib()
                lines += ["  %s: yours goes to %s" % (path, lib.local_file(path)) for path in paths]
                lines.append("  Run the update again with --split to see how your text would move there, "
                             "and what you would settle.")
                continue
            lines += ["  " + path for path in paths]
    if p["hooks"]:
        lines += ["", "Wall check: %d zone%s get%s the newer pre-commit check: %s." % (
            len(p["hooks"]), "" if len(p["hooks"]) == 1 else "s", "s" if len(p["hooks"]) == 1 else "",
            ", ".join(p["hooks"]))]
    wiki = p.get("wiki_hook")
    if wiki in ("add", "refresh"):
        lines += ["", "Wall check: the wikis get %s pre-commit check." % ("their" if wiki == "add" else "the newer")]
    elif wiki == "foreign":
        lines += ["", "Wall check: Wikis has a pre-commit hook that is not Garrick's, so it is left as it is and the wikis "
                  "do not check the walls before a commit. Add this line to it: "
                  "python3 System/tools/check.py --staged --walls-only"]
    if not any(p["actions"][k] for k in ("replace", "add", "merge", "split", "restore")) and not p["hooks"] \
            and wiki not in ("add", "refresh"):
        lines += ["", "Up to date: all %d files Garrick ships are as this Garrick writes them, "
                  "or yours by design." % len(p["files"])]
    else:
        lines += ["", "Already up to date: %d files." % len(p["current"])]
    if p["kept"]:
        lines.append("Changed by you, with nothing newer from Garrick: %d file%s, left as %s." % (
            len(p["kept"]), "" if len(p["kept"]) == 1 else "s", "it is" if len(p["kept"]) == 1 else "they are"))
    if p.get("extras"):
        names = {name: (what, places) for name, what, places in EXTRAS}
        lines.append("Extras updated with the rest: %s." % "; ".join(
            "%s (%s)" % (names[n][0], ", ".join(dest for _, dest, _ in names[n][1])) for n in p["extras"]))
    lines += say_allowlist(p.get("allowlist"))
    steps = p.get("then") or []
    if steps:
        lines += ["", "Then%s:" % (", with --apply" if applied is None else "")]
        lines += ["  - " + what + "." for what in steps]
    lines += say_renames(p.get("renames"))
    return "\n".join(lines)


# --------------------------------------------------------------------------- doing it


def git(repo, *args, check=True):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise UpdateError("git %s failed in %s: %s" % (" ".join(args), repo, (r.stderr or r.stdout).strip()))
    return r


def repo_of(root, path):
    """The repository that holds `path`: the nearest folder above it with a .git."""
    folder = (root / path).parent
    while True:
        if (folder / ".git").exists():
            return folder
        if folder == root or root not in folder.parents:
            return root
        folder = folder.parent


def status(repo, rel):
    """git's two-letter status of one path: "" when committed as it is, "??" when untracked."""
    return git(repo, "status", "--porcelain", "--", rel, check=False).stdout[:2].strip()


def uncommitted(repo, rel):
    return bool(status(repo, rel))


def write_bytes(path, data, mode):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".garrick-tmp")
    if tmp.exists() or tmp.is_symlink():
        tmp.unlink()                       # left by an update that stopped halfway
    try:
        with open(tmp, "xb") as f:
            f.write(data)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def first_missing(root, path):
    """The topmost folder that writing `path` would create, or None when its
    folder is there already, so that putting it back can remove what it made."""
    folder, top = path.parent, None
    while folder != root and root in folder.parents and not folder.exists():
        top, folder = folder, folder.parent
    return top


# System/rules.md keeps what every session needs and points to the skills for
# the procedures. These are the skills that carry what it moved out (#366), so
# an update writes them in the same step as the rules, and holds the rules back
# when it cannot: a rule must never stand in neither place.
RULES = "System/rules.md"
RULE_SKILLS = tuple("System/skills/%s/SKILL.md" % name for name in ("threads", "intake", "nurture", "desk"))


def apply(root, p, only=None, today=None):
    """Make the changes `p` lists: every replace, add and merge, or only the
    paths in `only`, which may also name a file to restore. Returns what was
    done, by kind, with what was skipped and why."""
    lib = install.lib()
    picked = set(only) if only else None
    if picked is not None:
        listed = {path for kind in KINDS for path in p["actions"][kind]}
        unknown = sorted(picked - listed)
        if unknown:
            raise UpdateError("Not in the update: %s. Name files as the report lists them." % ", ".join(unknown))
        held = sorted(picked & set(p["actions"]["split"]))
        if held:
            raise UpdateError("%s: Garrick's instruction file, changed by you. Move your text out with --split; "
                              "it puts Garrick's back as shipped." % ", ".join(held))
    if picked is not None and RULES in picked:
        # The rules go with the skills that now carry their procedures.
        picked |= {path for path in RULE_SKILLS
                   for kind in ("replace", "add", "restore") if path in p["actions"][kind]}
    todo = []          # (kind, path, where it is written, bytes, mode)
    skipped = []       # (path, reason)
    done = {kind: [] for kind in ("replace", "add", "restore", "merge")}
    for kind in ("replace", "add", "restore", "merge"):
        for path in p["actions"][kind]:
            if picked is not None and path not in picked:
                continue
            if kind == "restore" and picked is None:
                continue
            data, mode = p["files"][path]
            dest = path + NEW_SUFFIX if kind == "merge" else path
            if lib.link_on_the_way(root, root / dest) is not None:
                skipped.append((path, "a symbolic link stands on the way to it"))
                continue
            state = status(repo_of(root, dest), path_in_repo(root, dest))
            if kind == "merge":
                if not state and read(root / dest) == data:
                    done["merge"].append(path)      # its .new is there and committed, from a run that stopped
                    continue
                if state not in ("", "??") and (root / dest).exists():
                    skipped.append((path, "its .new has changes not committed; commit or discard them, "
                                          "then run again"))
                    continue
            elif state:
                skipped.append((path, "it has changes not committed; commit or discard them, then run again"))
                continue
            if kind in ("add", "restore") and (root / path).exists():
                skipped.append((path, "a file is there now"))
                continue
            todo.append((kind, path, dest, data, mode))

    if any(path == RULES and kind == "replace" for kind, path, _, _, _ in todo):
        written_now = {path for kind, path, _, _, _ in todo if kind != "merge"}
        behind = [path for path in RULE_SKILLS if path in p["files"] and path not in written_now
                  and (path in p["actions"]["merge"] or path in p["actions"]["split"]
                       or path in {s for s, _ in skipped}
                       or path in p["actions"]["replace"] or path in p["actions"]["add"]
                       or path in p["actions"]["restore"])]
        if behind:
            todo = [item for item in todo if item[1] != RULES]
            skipped.append((RULES, "the skills that carry the procedures it points to are not updated yet (%s); "
                                   "merge or commit them, then run again" % ", ".join(behind)))

    by_repo = {}
    for kind, path, dest, data, mode in todo:
        by_repo.setdefault(repo_of(root, dest), []).append((kind, path, dest, data, mode))
    commits = []
    to = p["to"].get("commit") or "unknown"
    for repo, items in sorted(by_repo.items()):
        before = {}        # where it is written: (bytes, mode, folder made), bytes None where there was no file
        rels = [path_in_repo(root, dest) for _, _, dest, _, _ in items]
        try:
            for _, _, dest, _, _ in items:
                target = root / dest
                if target.exists() or target.is_symlink():
                    before[dest] = (target.read_bytes(), target.stat().st_mode & 0o777, None)
                else:
                    before[dest] = (None, None, first_missing(root, target))
            for _, _, dest, data, mode in items:
                write_bytes(root / dest, data, mode)
            git(repo, "add", "--", *rels)
            git(repo, "commit", "-q", "-m", "Garrick: update to %s, %d file%s" % (
                to, len(rels), "" if len(rels) == 1 else "s"), "--", *rels)
        except (UpdateError, OSError) as exc:
            git(repo, "reset", "-q", "--", *rels, check=False)
            stuck = put_back(root, before)
            why = "the commit was refused" if isinstance(exc, UpdateError) else "a file could not be read or written"
            skipped += [(path, "%s, so it was put back: %s" % (why, exc) if dest not in stuck else
                         "%s, and it could not be put back (%s): restore it with git checkout" % (why, stuck[dest]))
                        for _, path, dest, _, _ in items]
            continue
        commits.append(git(repo, "rev-parse", "--short", "HEAD").stdout.strip() + " in " + (
            os.path.relpath(repo, root) if repo != root else "the workspace"))
        for kind, path, _, _, _ in items:
            done[kind].append(path)

    # The allow rules the installer wrote: Garrick's own entries brought up to
    # date, in the user's own settings file, which it never replaces as a whole.
    allow = p.get("allowlist") or {}
    allowed = {"add": [], "remove": [], "record": False}
    if picked is None and (allow.get("add") or allow.get("remove") or allow.get("record")):
        why = commit_files(root, allow["files"], "Garrick: allow rules, %d added, %d taken out" % (
            len(allow["add"]), len(allow["remove"])))
        if why:
            skipped.append((install.CLAUDE_SETTINGS, why))
        else:
            allowed = {"add": allow["add"], "remove": allow["remove"], "record": allow["record"]}
            commits.append(git(root, "rev-parse", "--short", "HEAD").stdout.strip() + " in the workspace")

    hooks, added = [], []
    for zone in p["hooks"]:
        lib.install_wall_hook(root / "Zones" / zone)
        hooks.append(zone)
    if p.get("wiki_hook") in ("add", "refresh"):
        try:
            lib.install_wall_hook(root / "Wikis", wiki=True, root=root)
            hooks.append("Wikis")
            if p.get("wiki_hook") == "add":
                added.append("Wikis")
        except (FileExistsError, FileNotFoundError) as exc:
            skipped.append(("Wikis/.git/hooks/pre-commit", "the wikis' wall check was not installed: %s" % exc))

    tidied = clear_retired_state(root) if picked is None else []
    written = [path for kind in ("replace", "add", "restore") for path in done[kind]]
    problems = check_errors(root, written)
    stamped, unstamped = False, ""
    if not problems:
        try:
            stamped = stamp(root, p, done, today)
        except (UpdateError, OSError) as exc:
            unstamped = str(exc)
    then = []
    for what, do in next_steps(root, p, done):
        then.append(do() if do else "To do: %s." % what)
    return {"done": done, "skipped": skipped, "commits": commits, "hooks": hooks,
            "hooks_added": added, "tidied": tidied,
            "problems": problems, "stamped": stamped, "unstamped": unstamped, "then": then,
            "allowlist": allowed}


# State Garrick once kept in System/generated/, which belongs to the tools and is
# never committed. An update takes these out: nothing reads them any more (#367).
RETIRED_STATE = ("System/generated/interrupted.json",)


def clear_retired_state(root):
    """Remove the retired state files a workspace still has. Returns the ones
    removed. A file that is not a plain file, or a link, is left alone."""
    gone = []
    for rel in RETIRED_STATE:
        path = root / rel
        if path.is_symlink() or not path.is_file():
            continue
        try:
            path.unlink()
        except OSError:
            continue
        gone.append(rel)
    return gone


def commit_files(root, files, message):
    """Write `files`, {path from the top: (bytes, mode)}, and commit them in the
    workspace's own repository. "" when it went, or why it did not, with
    whatever was written put back."""
    rels = sorted(files)
    for rel in rels:
        if install.lib().link_on_the_way(root, root / rel) is not None:
            return "a symbolic link stands on the way to it"
        if uncommitted(root, rel):
            return "it has changes not committed; commit or discard them, then run again"
    before = {}
    for rel in rels:
        target = root / rel
        before[rel] = ((target.read_bytes(), target.stat().st_mode & 0o777, None) if target.is_file()
                       else (None, None, first_missing(root, target)))
    try:
        for rel in rels:
            write_bytes(root / rel, *files[rel])
        git(root, "add", "--", *rels)
        git(root, "commit", "-q", "-m", message, "--", *rels)
    except (UpdateError, OSError) as exc:
        git(root, "reset", "-q", "--", *rels, check=False)
        stuck = put_back(root, before)
        if stuck:
            return "the commit was refused and it could not be put back (%s): restore it with git checkout" % exc
        return "the commit was refused, so it was put back: %s" % exc
    return ""


def put_back(root, before):
    """Return each file in `before` to what it held, {path: (bytes or None,
    mode, the folder writing it made)}, and remove any temporary file a stopped
    write left, and any folder made for a file that was not there. Returns the
    files that could not be put back, with why."""
    stuck = {}
    for path, (data, mode, made) in before.items():
        target = root / path
        tmp = target.with_name(target.name + ".garrick-tmp")
        try:
            if tmp.exists() or tmp.is_symlink():
                tmp.unlink()
            if data is None:
                if target.exists() or target.is_symlink():
                    target.unlink()
                folder = target.parent
                while made is not None and (folder == made or made in folder.parents):
                    if folder.is_dir() and not any(folder.iterdir()):
                        folder.rmdir()
                    folder = folder.parent
            elif read(target) != data:
                write_bytes(target, data, mode)
        except OSError as exc:
            stuck[path] = exc
    return stuck


def path_in_repo(root, path):
    return os.path.relpath(root / path, repo_of(root, path))


def check_errors(root, paths):
    """Errors the workspace's own check now finds in the files just written.
    Only those files are checked (`check.py --paths`), not the whole workspace,
    which on a large one is most of an update's time (#412). A workspace whose
    check.py predates `--paths`, or one that cannot be run, falls back to the
    whole check, as before: the answer is never left out."""
    if not paths:
        return []
    tool = root / "System" / "tools" / "check.py"
    try:
        scoped = "--paths" in tool.read_text(encoding="utf-8")
    except OSError:
        scoped = False
    cmd = [sys.executable, str(tool), "--root", str(root), "--json"]
    if scoped:
        cmd += ["--paths"] + sorted(paths)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        findings = json.loads(r.stdout).get("findings", [])
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return ["the check could not run: %s" % exc]
    touched = set(paths)
    return ["%s: %s" % (f.get("path"), f.get("message")) for f in findings
            if f.get("severity") == "error" and f.get("path") in touched]


def stamp(root, p, done, today=None):
    """Record the newer Garrick in System/garrick-version.json and commit it.
    The list of files keeps, for each, the fingerprint of what Garrick last
    gave it: the new one where the update wrote it, wrote its .new or found it
    current, the old one where it left a file behind or as yours. A merged file
    is then changed by you with nothing newer from Garrick, and is not offered
    again until Garrick changes it again. A stamp that had no list gets one
    holding every file Garrick ships that is there, those it left with no
    fingerprint, so that one you delete later counts as removed by you. Nothing
    is written when nothing would change, and if the commit is refused the
    stamp is put back as it was. `from` says how the newer Garrick came, except
    in a workspace adopted rather than installed, which keeps "adopted"; each
    entry in `updates` says how its Garrick came, as `via`."""
    lib = install.lib()
    old = lib.read_version(root)
    files = dict(p["recorded"])
    written = {path for paths in done.values() for path in paths}
    for path, (data, _) in p["files"].items():
        if path in written or path in p["current"]:
            files[path] = digest(data)
        elif path in p["actions"]["restore"] and path not in files:
            files[path] = digest(data)      # listed, so it stays removed by you rather than new
        elif not p["listed"] and path not in files and os.path.lexists(root / path):
            files[path] = None              # there, as yours or left behind; what Garrick gave it is unknown
    for path in p["actions"]["retired"]:
        files.pop(path, None)
    offered = [path for kind in ("replace", "add") for path in p["actions"][kind]]
    left = sorted(path for path in offered if path not in written)
    new = {k: v for k, v in install.source_version().items()}
    via = new.get("from", "")
    if old.get("from") == "adopted":
        new["from"] = "adopted"     # laid out by hand, not installed: an update does not change how it began
    if (new.get("commit") == old.get("commit") and files == p["recorded"]
            and left == sorted(old.get("left") or [])):
        return False
    history = list(old.get("updates") or [])
    entry = {"from": old.get("commit", ""), "to": new.get("commit", ""),
             "on": today or datetime.date.today().isoformat(), "via": via}
    if (new.get("commit") != old.get("commit") or written) and history[-1:] != [entry]:
        history.append(entry)       # an update between two copies with no commit to tell them apart counts too
    new["files"] = dict(sorted(files.items()))
    new["updates"] = history
    if left:
        new["left"] = left
    rel = "/".join(lib.VERSION_STAMP)
    target = root / rel
    before = {rel: (target.read_bytes(), target.stat().st_mode & 0o777, None) if target.is_file()
              else (None, None, first_missing(root, target))}
    try:
        write_bytes(target, (json.dumps(new, indent=2) + "\n").encode("utf-8"), 0o644)
        git(root, "add", "--", rel)
        git(root, "commit", "-q", "-m", "Garrick: version stamp %s" % new.get("commit", "unknown"), "--", rel)
    except (UpdateError, OSError) as exc:
        git(root, "reset", "-q", "--", rel, check=False)
        stuck = put_back(root, before)
        raise UpdateError("the version stamp could not be committed, so it %s: %s" % (
            "was put back as it was" if not stuck else "could not be put back; restore it with git checkout", exc))
    return True


def say_applied(p, result):
    done = result["done"]
    lines = []
    if done["replace"] or done["add"] or done["restore"]:
        n = len(done["replace"]) + len(done["add"]) + len(done["restore"])
        lines.append("Updated %d file%s." % (n, "" if n == 1 else "s"))
    if done["merge"]:
        lines.append("Wrote %d .new file%s beside the file%s you changed: %s. Merge each, then remove the .new "
                     "with git rm in the same commit." % (
                         len(done["merge"]), "" if len(done["merge"]) == 1 else "s",
                         "" if len(done["merge"]) == 1 else "s",
                         ", ".join(path + NEW_SUFFIX for path in done["merge"])))
    if result["commits"]:
        lines.append("Committed as %s." % ", ".join(result["commits"]))
    added = result.get("hooks_added", [])
    if added:
        lines.append("Added the wall check in: %s." % ", ".join(added))
    refreshed = [h for h in result["hooks"] if h not in added]
    if refreshed:
        lines.append("Refreshed the wall check in: %s." % ", ".join(refreshed))
    lines += say_allowlist(result.get("allowlist"), applied=True)
    for rel in result.get("tidied", []):
        lines.append("Removed %s: Back now reads the thread notes, and nothing keeps that file." % rel)
    for path, why in result["skipped"]:
        lines.append("Skipped %s: %s." % (path, why))
    if result.get("unstamped"):
        lines.append("System/garrick-version.json is unchanged: %s. Run the update again to record it." % (
            result["unstamped"]))
    if result["problems"]:
        lines.append("The check finds errors in files the update wrote, so the version stamp is unchanged:")
        lines += ["  " + x for x in result["problems"]]
        lines.append("To undo, run git revert on the commits above.")
    elif result["stamped"]:
        lines.append("System/garrick-version.json now records %s." % say_commit(p["to"]))
    lines += result.get("then") or []
    lines += say_renames(p.get("renames"))
    if not lines:
        lines.append("Nothing to do: the workspace is up to date.")
    return "\n".join(lines)


# --------------------------------------------------------------------------- what an extra needs next


APP_ID = "local.garrick.status"                 # make-app.sh's bundle identifier
APP_SOURCES = ("System/status/app/", "System/status/status.py")     # the app's code, and the page that draws its icon
PLUGIN = (".obsidian", "plugins", "garrick-status")
PLUGIN_SOURCE = "System/status/obsidian/"
DESK = "System/cmux/desk.py"
STATUS_FOLDER = "System/status/"
STATUS_PY = "System/status/status.py"
PAGE = "System/generated/status.html"


def on_mac():
    return sys.platform == "darwin"


# --------------------------------------------------------------------------- jobs renamed (#275, #276)

JOBS_SOURCE = REPO / "extras" / "jobs"
# The script each of Garrick's jobs ran under its old name: a plist that runs
# job.py under that name and this script is Garrick's, whatever its label.
OLD_SCRIPTS = {"backup": "backup.py", "nurture": "nurture_sweep.py", "reading-sweep": "reading_sweep.py",
               "todo-sweep": "todo_sweep.py", "whats-open": "whats_open.py", "status": "status.py"}
NEW_SCRIPTS = {"gr-nightly": "nightly.py"}      # the job whose script changed with its name
NEW_FROM = {"nurture"}                           # its old name: its old script in a gr- plist shows the rename


def launch_agents():
    return Path.home() / "Library" / "LaunchAgents"


def job_names():
    """(RENAMED, RETIRED) from this Garrick's agent.py: each old name of a job
    of Garrick's, and the name it runs under now."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("garrick_update_agent", str(JOBS_SOURCE / "agent.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.RENAMED, mod.RETIRED


def shipped_about(job):
    """The GARRICK_ABOUT line this Garrick's plist for `job` gives, or ""."""
    try:
        with (JOBS_SOURCE / "launchd" / ("garrick.%s.plist" % job)).open("rb") as f:
            return str(plistlib.load(f).get("EnvironmentVariables", {}).get("GARRICK_ABOUT", ""))
    except (OSError, ValueError, AttributeError):
        return ""


def old_jobs(root):
    """Each plist in ~/Library/LaunchAgents that runs one of Garrick's jobs for
    this workspace under the name it had before 0.49.0, or part way through
    its rename, with the commands that finish it: [{plist, label, job, new,
    retired, state, commands}]. A plist counts only when it runs this
    workspace's System/jobs/job.py under an old or new name of Garrick's with
    Garrick's own script for it. Reads the folder and nothing else; never
    writes there, and runs none of the commands."""
    folder = launch_agents()
    if not folder.is_dir():
        return []
    renamed, retired = job_names()
    back = {new: old for old, new in renamed.items()}
    jobs_dir = root / "System" / "jobs"
    found = []
    for plist in sorted(folder.glob("*.plist")):
        try:
            with plist.open("rb") as f:
                data = plistlib.load(f)
        except Exception:
            continue
        args = data.get("ProgramArguments") if isinstance(data, dict) else None
        if not isinstance(args, list):
            continue
        args = [str(a) for a in args]
        at = next((i for i, a in enumerate(args) if a.endswith("job.py")), None)
        if at is None or at + 1 >= len(args) or not same_place(Path(args[at]).parent, jobs_dir):
            continue
        name = args[at + 1]
        cmd = args[args.index("--", at) + 1:] if "--" in args[at:] else []
        old = name if name in renamed or name in retired else back.get(name)
        if old is None:
            continue
        new = renamed.get(old) or retired[old]
        scripts = {OLD_SCRIPTS[old], NEW_SCRIPTS.get(new, OLD_SCRIPTS[old])} if old in renamed else {OLD_SCRIPTS[old]}
        if not any(Path(a).name in scripts for a in cmd):
            continue
        if name == new and not came_from(plist, data, cmd, old):
            continue                               # a gr- plist with no old name behind it: as shipped, nothing to do
        block = rename_commands(plist, data, args, at, old, new, old in retired)
        if block["commands"] or block["state"] == "manual":
            found.append(block)
    return found


def jobs_folder(env):
    """The jobs folder a launchd job writes to: GARRICK_JOBS_DIR in its own
    plist's environment, or agent.py's default. Never this process's
    environment, which is the Terminal's the update runs in, not the job's."""
    set_to = env.get("GARRICK_JOBS_DIR") if isinstance(env, dict) else None
    if isinstance(set_to, str) and set_to.strip():
        return Path(set_to).expanduser()
    return Path.home() / "Library" / "Logs" / "garrick-jobs"


def came_from(plist, data, cmd, old):
    """Whether a plist that already runs a job under its gr- name was once
    the job under its old name, part way through its rename: an old label or
    marker in it, the old script or the old log in it, the old plist set
    aside as .retired beside it, or the old name's heartbeat in the jobs
    folder. A gr- plist copied as shipped has none of these, and is left
    alone. An old plist still beside it is not counted: its own block, set
    aside as a duplicate, marks this one."""
    env = data.get("EnvironmentVariables") if isinstance(data.get("EnvironmentVariables"), dict) else {}
    logs = [data.get(k) for k in ("StandardOutPath", "StandardErrorPath")]
    return (str(data.get("Label")) == "garrick." + old or env.get("GARRICK_RENAMED_FROM") == old
            or any(Path(a).name == OLD_SCRIPTS[old] for a in cmd) and old in NEW_FROM
            or any(isinstance(v, str) and Path(v).name == "%s.launchd.log" % old for v in logs)
            or plist.with_name("garrick.%s.plist.retired" % old).exists()
            or (jobs_folder(env) / ("%s.heartbeat.json" % old)).is_file())


def rename_commands(plist, data, args, at, old, new, retired):
    """The commands that take one plist to its new name, kept as the user
    edited it otherwise, each safe to run again: unload it, move the file
    first, then set on the moved file its label, its whole ProgramArguments,
    its log paths and its environment (the job's line of description, and
    GARRICK_RENAMED_FROM, the old name, so the jobs card reads the runs from
    before as this job's), then load it. For the nightly job, its script and
    `--timeout 3600` too. Only what is still to do: a plist part way through
    gets the rest, and one already done gets none. A retired job is unloaded
    and set aside as `.plist.retired`, which launchd does not load."""
    label = str(data.get("Label") or plist.stem)
    out = {"plist": str(plist), "label": label, "job": old, "new": new, "retired": retired, "state": "old",
           "commands": []}
    cmds = out["commands"]

    def q(path):                                # a path under the home folder as ~/..., as the docs write it
        try:
            return "~/" + shlex.quote(str(Path(path).relative_to(Path.home())))
        except ValueError:
            return shlex.quote(str(path))

    target = plist.with_name("garrick.%s.plist" % new)
    if retired or (target.exists() and not same_place(target, plist)):
        out["state"] = "retire" if retired else "duplicate"
        mark = None
        if not retired:                            # the copy already there learns the old name, its other keys kept
            try:
                with target.open("rb") as f:
                    there = plistlib.load(f).get("EnvironmentVariables")
                there = dict(there) if isinstance(there, dict) else {}
                if there.get("GARRICK_RENAMED_FROM") != old:
                    mark = "plutil -replace EnvironmentVariables -json %s %s" % (
                        shlex.quote(json.dumps(dict(there, GARRICK_RENAMED_FROM=old), ensure_ascii=False)), q(target))
            except (OSError, ValueError, AttributeError, plistlib.InvalidFileException):
                pass
            except TypeError:
                out["state"] = "manual"
                return out
        cmds.append("launchctl bootout gui/$(id -u)/%s" % shlex.quote(label))
        cmds.append("mv -n %s %s" % (q(plist), q(str(plist) + ".retired")))
        if mark:
            cmds.append(mark)
        return out

    want = list(args)
    want[at + 1] = new
    if new == "gr-nightly":
        for i, a in enumerate(want):
            if i > at and Path(a).name == OLD_SCRIPTS[old]:
                want[i] = str(Path(a).with_name(NEW_SCRIPTS[new]))
        stop = want.index("--", at) if "--" in want[at:] else len(want)
        flags = want[at + 2:stop]
        while "--timeout" in flags:                # four steps need the hour, whatever was set for nurture alone
            i = flags.index("--timeout")
            del flags[i:i + 2]
        want[at + 2:stop] = ["--timeout", "3600"] + flags
    env = data.get("EnvironmentVariables")
    env = dict(env) if isinstance(env, dict) else {}
    want_env = dict(env)
    about = shipped_about(new)
    if about:
        want_env["GARRICK_ABOUT"] = about
    want_env["GARRICK_RENAMED_FROM"] = old
    edits = []
    if label != "garrick." + new:
        edits.append("plutil -replace Label -string %s %s" % (shlex.quote("garrick." + new), q(target)))
    if want != args:
        edits.append("plutil -replace ProgramArguments -json %s %s" % (shlex.quote(json.dumps(want)), q(target)))
    for key in ("StandardOutPath", "StandardErrorPath"):
        value = data.get(key)
        if isinstance(value, str) and Path(value).name == "%s.launchd.log" % old:
            edits.append("plutil -replace %s -string %s %s" % (
                key, q(value[:-len("%s.launchd.log" % old)] + "%s.launchd.log" % new), q(target)))
    if want_env != env:
        try:
            edits.append("plutil -replace EnvironmentVariables -json %s %s" % (
                shlex.quote(json.dumps(want_env, ensure_ascii=False)), q(target)))
        except TypeError:                          # a <date> or <data> value, which JSON cannot carry
            out["state"] = "manual"
            return out
    moved = same_place(target, plist)
    if moved and not edits:
        return out                                 # done
    out["state"] = "part" if moved or args[at + 1] == new or label == "garrick." + new else "old"
    for name in dict.fromkeys([label] + (["garrick." + old, "garrick." + new] if out["state"] == "part" else [])):
        cmds.append("launchctl bootout gui/$(id -u)/%s" % shlex.quote(name))
    if not moved:
        cmds.append("mv -n %s %s" % (q(plist), q(target)))
    cmds += edits
    cmds.append("launchctl bootstrap gui/$(id -u) %s" % q(target))
    return out


def say_renames(renames):
    """The report's lines for the plists still running Garrick's jobs under
    their old names, or part way through a rename: one message, then each
    plist and its commands."""
    if not renames:
        return []
    folder = str(Path(renames[0]["plist"]).parent)
    n = len(renames)
    lines = ["", "Garrick's scheduled jobs have new names, which start with gr-, so they read apart from yours "
             "(#275). %d plist%s in %s still need%s the change. Each keeps working as it is until you make it: this "
             "update changes nothing in that folder and runs none of these commands. To make it, run a plist's lines "
             "in Terminal, in order. Each line is safe to run again; launchctl may say a job is not loaded, and mv "
             "that a file is already moved, which is fine. Leave out the last line of a job you keep unloaded." % (
                 n, "" if n == 1 else "s", folder, "s" if n == 1 else "")]
    for r in renames:
        name = Path(r["plist"]).name
        if r["state"] == "retire":
            lines.append("  %s runs %s, which the nightly job gr-nightly now does. Once garrick.gr-nightly is loaded, "
                         "unload this one and set it aside as %s.retired, which launchd does not load. You may delete "
                         "that file afterwards:" % (name, r["job"], name))
        elif r["state"] == "duplicate":
            lines.append("  %s runs %s, and garrick.%s.plist is already there. Unload the old one and set it aside as "
                         "%s.retired, which launchd does not load; you may delete that file afterwards. The last line, "
                         "when there is one, marks garrick.%s.plist with the old name, so the runs from before count "
                         "as its own:" % (name, r["job"], r["new"], name, r["new"]))
        elif r["state"] == "manual":
            lines.append("  %s runs %s, which is now %s, but has a value plutil -json cannot write, a date or data; "
                         "rename it by hand, as docs/extras/scheduled-jobs.md says." % (name, r["job"], r["new"]))
        elif r["state"] == "part":
            lines.append("  %s is part way through its rename from %s to %s. The lines still to run:" % (
                name, r["job"], r["new"]))
        else:
            lines.append("  %s runs %s, which is now %s:" % (name, r["job"], r["new"]))
        lines += ["    " + c for c in r["commands"]]
    if any(r["new"] == "gr-nightly" for r in renames):
        lines.append("  The nightly job now also records effort for the Effort view and rebuilds the status page "
                     "(#276). A job of your own that did either can go: put the checks it ran in "
                     "System/jobs/nightly.local, make that file executable, and unload your job. "
                     "The update does not touch your own jobs.")
    return lines


def app_folders():
    return [Path.home() / "Applications", Path("/Applications")]


def kept_flags(args):
    """An app's stored flags, less the ones status.py no longer takes: --obsidian
    VAULT and --no-obsidian went in 0.51.0 (#318), and make-app.sh drops them too."""
    out, i = [], 0
    while i < len(args):
        if args[i] == "--obsidian":
            i += 2
            continue
        if args[i] != "--no-obsidian" and not args[i].startswith("--obsidian="):
            out.append(args[i])
        i += 1
    return out


def garrick_apps(root):
    """Each Garrick.app built for this workspace, with the flags make-app.sh
    stored in it, as a rebuild keeps them (kept_flags()): [(app, [flags])].
    macOS only."""
    if not on_mac():
        return []
    out = []
    for folder in app_folders():
        app = folder / "Garrick.app"
        try:
            with (app / "Contents" / "Info.plist").open("rb") as f:
                info = plistlib.load(f)
            same = bool(info.get("GarrickWorkspace")) and Path(str(info["GarrickWorkspace"])).resolve() == root.resolve()
        except (OSError, ValueError, plistlib.InvalidFileException):
            continue
        if info.get("CFBundleIdentifier") == APP_ID and same:
            args = info.get("GarrickStatusArgs")
            out.append((app, kept_flags([str(a) for a in args]) if isinstance(args, list) else []))
    return out


def make_app(cmd):
    """Run make-app.sh; (exit code, its last line)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    if r.returncode:
        lines = (r.stdout + r.stderr).strip().splitlines()
        return r.returncode, lines[-1] if lines else ""
    # The app's place is the last line on stdout. What make-app.sh has to say (an Accessibility reset, a
    # Finder extension that did not build) is on stderr behind `make-app: `, and follows the place as sentences
    # of its own. Any other stderr line is build output, which stays out of the message.
    out = r.stdout.strip().splitlines()
    notes = [n.strip()[len("make-app: "):] for n in r.stderr.splitlines() if n.strip().startswith("make-app: ")]
    notes = [n.rstrip(".:") for n in notes]
    return 0, ". ".join([out[-1] if out else ""] + notes)


def plugin_copies(root):
    """The Obsidian plugin's folder in each vault inside the workspace: its
    top, or a folder one or two down, such as a zone or a wiki."""
    level, vaults = [root], [root]
    for _ in range(2):
        nxt = []
        for folder in level:
            try:
                nxt += [d for d in sorted(folder.iterdir())
                        if d.is_dir() and not d.is_symlink() and not d.name.startswith(".")]
            except OSError:
                pass
        vaults += nxt
        level = nxt
    return [v.joinpath(*PLUGIN) for v in vaults if v.joinpath(*PLUGIN).is_dir()]


def desk_links():
    """Every `desk` on the PATH, and in ~/.local/bin, that is a link to a desk.py: [(link, target)]."""
    seen, out = set(), []
    for folder in os.environ.get("PATH", "").split(os.pathsep) + [str(Path.home() / ".local" / "bin")]:
        link = Path(folder or ".") / "desk"
        if not link.is_symlink() or str(link) in seen:
            continue
        seen.add(str(link))
        target = Path(os.path.join(str(link.parent), os.readlink(str(link))))
        if target.name == "desk.py":
            out.append((link, Path(os.path.abspath(str(target)))))
    return out


def outside_copies(root):
    """The extras that run from a Garrick kept outside the workspace, the zone
    guard and the Garrick band, where the assistants' settings point at a copy
    that differs from this Garrick's: [(what, path)]. Reads the settings for
    those paths only."""
    found = []
    guard = REPO / "extras" / "hooks" / "zone_guard.py"
    band = REPO / "extras" / "mods" / "garrick-band"
    texts = []
    for settings in (Path.home() / ".claude" / "settings.json", Path.home() / ".codex" / "hooks.json"):
        try:
            texts.append(settings.read_text(encoding="utf-8"))
        except OSError:
            pass
    paths = set()
    for text in texts:
        paths |= set(re.findall(r"[^\s\"']*zone_guard\.py", text))
    for path in sorted(paths):
        there = Path(os.path.expanduser(path))
        if there.is_file() and guard.is_file() and read(there) != read(guard) and not same_place(there, guard):
            found.append(("the zone guard", str(there)))
    dirs = set()
    for text in texts:
        try:
            env = (json.loads(text).get("env") or {})
        except (ValueError, AttributeError):
            continue
        value = env.get("CLAUDE_CODE_PLUGIN_DIRS") if isinstance(env, dict) else None
        if isinstance(value, str):
            dirs |= {d for d in re.split(r"[:,]", value) if d.rstrip("/").endswith("garrick-band")}
    for d in sorted(dirs):
        there = Path(os.path.expanduser(d))
        if there.is_dir() and band.is_dir() and not same_place(there, band) and any(
                read(there / f.relative_to(band)) != read(f) for f in band.rglob("*") if f.is_file()):
            found.append(("the Garrick band", str(there)))
    return found


def same_place(a, b):
    try:
        return Path(a).resolve() == Path(b).resolve()
    except OSError:
        return False


def next_steps(root, p, done=None):
    """What the extras need once their files are written: rebuild the Mac
    app, then the status page with the app's flags, refresh the Obsidian
    plugin in each vault, point the desk command at the workspace's copy,
    and say which extras run from a copy outside it.
    `done` is apply()'s record; without it, what the plan would write. Returns
    [(what it is, a function that does it, or None when it is for you)]."""
    if done is None:
        written = set(p["actions"]["replace"]) | set(p["actions"]["add"])
        merged = set(p["actions"]["merge"])
    else:
        written = {path for kind in ("replace", "add", "restore") for path in done[kind]}
        merged = set(done["merge"])
    ours = written | set(p["current"])          # files that are, or will be, as this Garrick ships them
    steps = []
    apps = garrick_apps(root) if any(path.startswith(STATUS_FOLDER) for path in written) else []

    if any(path.startswith(APP_SOURCES) for path in written):
        for app, args in apps:
            if any(path.startswith(APP_SOURCES) for path in merged):
                steps.append(("Garrick.app in %s: merge the .new files under System/status first, then rebuild it "
                              "with System/status/app/make-app.sh" % app.parent, None))
                continue
            cmd = ["/bin/bash", str(root / "System" / "status" / "app" / "make-app.sh"), "--workspace", str(root),
                   "--dest", str(app.parent), "--"] + args
            steps.append(("Rebuild Garrick.app in %s, with the flags it was built with%s" % (
                app.parent, ": " + " ".join(args) if args else " (none)"), lambda cmd=cmd: say_make_app(cmd)))

    # The page a build left is the replaced code's, and the app shows it as
    # current until it is old enough to rebuild, so it is built again here,
    # once every file is in place, with the flags the app builds it with.
    # Without an app it builds with the flags the last build stored, which may
    # be the Obsidian plugin's: nobody chose flags here, so it stores none (#246).
    if any(path.startswith(STATUS_FOLDER) for path in written) and (root / STATUS_PY).is_file() \
            and (apps or (root / PAGE).is_file()):
        if any(path.startswith(STATUS_FOLDER) for path in merged):
            steps.append(("The status page: merge the .new files under System/status first, then rebuild it "
                          "with python3 %s" % STATUS_PY, None))
        else:
            args = apps[0][1] if apps else ["--same-flags"]
            cmd = [sys.executable or "python3", str(root / STATUS_PY), "--workspace", str(root)] + args
            steps.append(("Rebuild the status page, %s, %s" % (
                PAGE, "with the flags Garrick.app was built with" + (": " + " ".join(args) if args else " (none)")
                if apps else "with the flags its last build used, as no Garrick.app is built for this workspace"),
                lambda cmd=cmd: say_page(cmd)))

    sources = sorted(path for path in p["files"] if path.startswith(PLUGIN_SOURCE))
    known = known_hashes()
    refreshed = False
    for copy in plugin_copies(root) if sources else []:
        vault = os.path.relpath(copy.parent.parent.parent, root)
        vault = "the workspace's top" if vault == "." else vault
        stale, foreign = [], []
        for path in sources:
            data = p["files"][path][0]
            have = read(copy / path[len(PLUGIN_SOURCE):])
            if have == data:
                continue
            if path not in ours:
                foreign.append(path)                        # the workspace's copy is not this Garrick's yet
            elif have is None or digest(have) in known.get(path, ()) or digest(have) == p["recorded"].get(path):
                stale.append(path)
            else:
                foreign.append(path)
        if stale:
            refreshed = True
            steps.append(("Refresh the Obsidian plugin in %s: %s" % (vault, ", ".join(x[len(PLUGIN_SOURCE):] for x in stale)),
                          lambda copy=copy, stale=stale: refresh_plugin(root, copy, stale, p)))
        if foreign:
            steps.append(("The Obsidian plugin in %s has %s unlike any Garrick's, so it is left as it is; copy them "
                          "from System/status/obsidian/ to refresh it" % (
                              vault, ", ".join(x[len(PLUGIN_SOURCE):] for x in foreign)), None))
    if refreshed:
        steps.append(("In Obsidian, switch Garrick off and on in Settings > Community plugins, or restart Obsidian, "
                      "to load the refreshed plugin", None))

    if "cmux" in p.get("extras", ()) and DESK in ours:
        mine = (root / DESK).resolve() if (root / DESK).exists() else root / DESK
        for link, target in desk_links():
            if not same_place(target, mine):
                steps.append(("Point the desk command, %s, at the workspace's %s, in place of %s" % (link, DESK, target),
                              lambda link=link: relink(link, mine)))

    steps.extend(before_quit_steps(root))

    for what, path in outside_copies(root):
        steps.append(("%s runs from %s, which differs from this Garrick's. Point your assistant's settings at a newer "
                      "Garrick you keep outside the workspace" % (what[0].upper() + what[1:], path), None))
    return steps


# The commands `desk shutdown` ran before quitting cmux (the `before_quit` setting in
# System/desk.json) have no desk to run them: "close for the day" quits nothing. They go
# into System/jobs/nightly.local, which the jobs extra's nightly run executes from the
# workspace root, or the update says why they could not (#442).
DESK_JSON = "System/desk.json"
NIGHTLY_LOCAL = "System/jobs/nightly.local"


def before_quit_commands(root):
    """[(command line)] from before_quit in System/desk.json; None when there are none or the file does not read."""
    try:
        given = json.loads((root / DESK_JSON).read_text(encoding="utf-8")).get("before_quit")
    except (OSError, ValueError, AttributeError):
        return None
    if not isinstance(given, list):
        return None
    out = []
    for c in given:
        if isinstance(c, str) and c.strip():
            out.append(c.strip())
        elif isinstance(c, list) and c and all(isinstance(a, str) for a in c):
            out.append(shlex.join(c))
    return out or None


def before_quit_steps(root):
    lines = before_quit_commands(root)
    if not lines:
        return []
    where = "before_quit in %s" % DESK_JSON
    if not (root / "System" / "jobs" / "nightly.py").is_file():
        return [("desk no longer runs %s, and the jobs extra is not installed: run %s yourself, or install the jobs "
                 "extra and put them in %s" % (where, "; ".join(lines), NIGHTLY_LOCAL), None)]
    if (root / NIGHTLY_LOCAL).exists():
        return [("desk no longer runs %s. %s is yours and is left as it is: add %s to it, then delete the setting" % (
            where, NIGHTLY_LOCAL, "; ".join(lines)), None)]
    return [("Move %s into %s, which the jobs extra's nightly run executes, and delete the setting" % (where, NIGHTLY_LOCAL),
             lambda: move_before_quit(root, lines))]


def move_before_quit(root, lines):
    target, config = root / NIGHTLY_LOCAL, root / DESK_JSON
    try:
        given = json.loads(config.read_text(encoding="utf-8"))
        body = ("#!/bin/sh\n# Moved from before_quit in System/desk.json: the commands \"close for the day\" used to run\n"
                "# before quitting cmux. The jobs extra's nightly run executes this file from the workspace root.\n"
                + "\n".join(lines) + "\n")
        target.write_text(body, encoding="utf-8")
        os.chmod(str(target), 0o755)
        del given["before_quit"]
        config.write_text(json.dumps(given, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, KeyError) as exc:
        return "The before_quit commands were not moved: %s. Put them in %s by hand." % (exc, NIGHTLY_LOCAL)
    return "Moved the before_quit commands into %s; commit it with %s." % (NIGHTLY_LOCAL, DESK_JSON)


def say_make_app(cmd):
    code, last = make_app(cmd)
    return "Rebuilt Garrick.app: %s." % last if code == 0 else "Garrick.app was not rebuilt: %s. Run %s by hand." % (
        last or "make-app.sh failed", " ".join(cmd[1:2]))


def build_page(cmd):
    """Run status.py; (exit code, the page it wrote, or why it did not)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    lines = (r.stdout if r.returncode == 0 else r.stderr + r.stdout).strip().splitlines()
    return r.returncode, lines[-1] if lines else ""


def say_page(cmd):
    code, last = build_page(cmd)
    return "Rebuilt the status page: %s." % last if code == 0 else "The status page was not rebuilt: %s. Run python3 %s by hand." % (
        last or "status.py failed", cmd[1])


def refresh_plugin(root, copy, paths, p):
    """Copy this Garrick's plugin files into one vault's plugin folder. Where
    git tracks them, the change is committed as the update's own are."""
    targets = [copy / path[len(PLUGIN_SOURCE):] for path in paths]
    if lib_link(root, copy):
        return "Skipped the Obsidian plugin in %s: a symbolic link stands on the way to it." % copy
    repo = repo_of(root, os.path.relpath(copy, root))
    rels = [os.path.relpath(t, repo) for t in targets]
    tracked = [rel for rel in rels if git(repo, "ls-files", "--error-unmatch", "--", rel, check=False).returncode == 0]
    if any(status(repo, rel) for rel in tracked):
        return "Skipped the Obsidian plugin in %s: it has changes not committed." % copy
    try:
        for path, target in zip(paths, targets):
            data, mode = p["files"][path]
            write_bytes(target, data, mode)
        if tracked:
            git(repo, "add", "--", *tracked)
            git(repo, "commit", "-q", "-m", "Garrick: refresh the Obsidian plugin", "--", *tracked)
    except (OSError, UpdateError) as exc:
        return "The Obsidian plugin in %s could not be refreshed: %s." % (copy, exc)
    return "Refreshed the Obsidian plugin in %s." % copy


def lib_link(root, path):
    return install.lib().link_on_the_way(root, path) is not None


def relink(link, target):
    tmp = link.with_name(link.name + ".garrick-tmp")
    try:
        if tmp.is_symlink() or tmp.exists():
            tmp.unlink()
        os.symlink(str(target), str(tmp))
        os.replace(str(tmp), str(link))
    except OSError as exc:
        return "The desk command was not re-linked: %s. Run: ln -sf %s %s" % (exc, target, link)
    return "The desk command, %s, now runs %s." % (link, target)


# --------------------------------------------------------------------------- releases


# Where 0.1.0 kept the zone template, before it moved under System/templates.
OLD_ZONE_TEMPLATE = "template/Zones/_zone/"


def version_key(tag):
    """Sort key for a release tag: v0.7.0-rc2 before v0.7.0-rc10 before v0.7.0
    before v0.10.0.
    None for a tag that is not a version."""
    m = re.match(r"^v(\d+(?:\.\d+)*)(?:-(.+))?$", tag)
    if not m:
        return None
    pre = m.group(2)
    parts = tuple((0, int(x), "") if x.isdigit() else (1, 0, x) for x in re.findall(r"\d+|\D+", pre or ""))
    return tuple(int(x) for x in m.group(1).split(".")), pre is None, parts


def release_hashes(repo=REPO):
    """{path: [SHA-256, ...]} of the files every tagged release's template
    shipped, and its docs and extras where a workspace keeps them
    (System/garrick-docs for docs, System/status for extras/status), for
    release-hashes.json, and the texts of each release's zone
    template, since a zone's own files hold the zone's name and can only be
    recognised once it is filled in."""
    def run(*args):
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True).stdout
    tags = sorted((t for t in run("tag", "-l", "v*").decode().split() if version_key(t)), key=version_key)
    zone = "template/" + "/".join(install.lib().ZONE_TEMPLATE) + "/"
    paths, zone_texts = {}, {}
    for tag in tags:
        listed = run("ls-tree", "-r", "--name-only", tag).decode().splitlines()
        docs = set(install.shipped_docs([l[len("docs/"):] for l in listed if l.startswith("docs/")],
                                        lambda n: run("show", "%s:docs/%s" % (tag, n)).decode("utf-8", "replace")))
        for line in listed:
            in_zone = line.startswith((zone, OLD_ZONE_TEMPLATE))
            if line == "CHANGELOG.md":
                rel = "System/garrick-changelog.md"
            elif line.startswith("docs/") and line[len("docs/"):] in docs:
                rel = "/".join(install.lib().DOCS_COPY) + line[len("docs"):]
            elif line.startswith(OLD_ZONE_TEMPLATE):
                rel = None                  # copied into each zone, never to a path of its own
            elif line.startswith("template/") and line[len("template/"):] not in install.lib().UNLISTED:
                rel = line[len("template/"):]
            elif extra_place(line):
                rel = extra_place(line)
            else:
                continue
            data = run("show", "%s:%s" % (tag, line))
            if rel is not None:
                h = digest(data)
                paths.setdefault(rel, [])
                if h not in paths[rel]:
                    paths[rel].append(h)
            if in_zone:
                zone_prefix = zone if line.startswith(zone) else OLD_ZONE_TEMPLATE
                try:
                    text = data.decode("utf-8")
                except UnicodeDecodeError:
                    continue
                texts = zone_texts.setdefault(line[len(zone_prefix):], [])
                if text not in texts:
                    texts.append(text)
    return {"releases": tags, "paths": dict(sorted(paths.items())), "zone": dict(sorted(zone_texts.items()))}


# --------------------------------------------------------------------------- main


# --------------------------------------------------------------------------- the walls step (#485)

# From 0.63.0 a zone is walled or open and nothing below a zone is. A workspace that took 0.60.0 to 0.62.0 holds a
# flag on each party and a party and a default on each zone. This is the one step that turns them into a flag on
# each zone. It runs before the update installs anything: it runs the workspace's own check (the 0.62 rule) and this
# Garrick's check (the zone rule, read only against the workspace), prints every flow whose verdict changes, and
# asks. A no, or nobody to answer, stops the update with the workspace as it was. This module keeps no copy of the
# 0.62 rule: the old verdicts are the workspace's own check.py, run as it is.

WALL_TIMEOUT = 1800                 # seconds one check may take on a large workspace
SHOWN = 12                          # findings printed for each kind
WALL_KINDS = (("inside", "Inside one zone: the file and what it points at or names are in one zone"),
              ("name", "Name only: a name, with no link, embed, path or copy"),
              ("other", "Other: neither of the two above"))
CLEAN_KINDS = ("people", "ledger", "pages")


def _cells(line):
    """The cells of a table line, outer bars off, an escaped bar kept."""
    inner = line.strip()
    inner = inner[1:] if inner.startswith("|") else inner
    inner = inner[:-1] if inner.endswith("|") and not inner.endswith("\\|") else inner
    return [c.strip() for c in re.split(r"(?<!\\)\|", inner)]


def _row(cells):
    return "|" + "|".join(" %s " % c if c else " " for c in cells) + "|" if cells else ""


def _is_rule(line):
    return bool(line.strip()) and set(line.replace("|", "").strip()) <= set("-: ")


def _table_at(lines, title):
    """(first, last + 1) of the first table under `## <title>`, or None."""
    start = next((i for i, l in enumerate(lines) if l.startswith("## ") and l[3:].strip().lower() == title), None)
    if start is None:
        return None
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    first = next((i for i in range(start + 1, end) if lines[i].lstrip().startswith("|")), None)
    if first is None:
        return None
    last = first
    while last < end and lines[last].lstrip().startswith("|"):
        last += 1
    return first, last


def _plain(cell):
    return cell.replace("*", "").strip().strip("`").strip()


def _table_rows(lines, title):
    """(header names lower case, [cells of each row]) of a table, or (None, [])."""
    span = _table_at(lines, title)
    if span is None:
        return None, []
    first, last = span
    header = [c.lower() for c in _cells(lines[first])]
    rows = [_cells(l) for l in lines[first + 1:last] if not _is_rule(l)]
    return header, rows


def _column(header, *names):
    return next((i for i, h in enumerate(header or []) if any(h.startswith(n) for n in names)), None)


def zone_flags(text):
    """What the 0.62 tables propose for each zone: {zone: (walled, why)}, in the order of the Zones table; None
    when the Zones table already has its Walled column, or there is no Zones table to read. A zone is walled when
    its party is walled or its default for new parties is walled, and open otherwise; a zone whose cells say
    neither is walled (#485)."""
    lines = text.splitlines()
    zh, zrows = _table_rows(lines, "zones")
    if not zrows or zh is None or _column(zh, "walled") is not None:
        return None
    ph, prows = _table_rows(lines, "parties")
    tag_at, walled_at = _column(ph, "tag"), _column(ph, "walled")
    flag = {}
    for row in prows:
        if tag_at is not None and len(row) > tag_at:
            tag = _plain(row[tag_at]).lstrip("#").lower()
            flag[tag] = (_plain(row[walled_at]).lower() != "no") if walled_at is not None and len(row) > walled_at else True
    zone_at, party_at, default_at = _column(zh, "zone"), _column(zh, "party"), _column(zh, "new parties")
    out = {}
    for row in zrows:
        name = _plain(row[zone_at]) if zone_at is not None and len(row) > zone_at else ""
        if not name:
            continue
        party = _plain(row[party_at]).lstrip("#").lower() if party_at is not None and len(row) > party_at else ""
        default = _plain(row[default_at]).lower() if default_at is not None and len(row) > default_at else ""
        if party and flag.get(party, True):
            out[name] = (True, "its party `%s` is walled" % party)
        elif default == "open" and (not party or party in flag):
            out[name] = (False, "its party and its default for new parties are open" if party else "its default for new parties is open")
        elif default == "open":
            out[name] = (True, "its party `%s` has no row in the Parties table" % party)
        else:
            out[name] = (True, "its default for new parties is walled" if default == "walled" else "nothing says it is open")
    return out


def has_walls_table(text):
    return any(l.startswith("## ") and l[3:].strip().lower() == "walls" for l in text.splitlines())


def walls_pending(root):
    """The flags the update proposes, {zone: (walled, why)}, while System/context.md has no Walled column on its
    Zones table; None when nothing waits. A 0.59 workspace (a Walls table, no flags) is told to take 0.62 first."""
    try:
        text = (root / "System" / "context.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    flags = zone_flags(text)
    if flags is None:
        return None
    lines = text.splitlines()
    ph, _ = _table_rows(lines, "parties")
    if has_walls_table(text) and _column(ph, "walled") is None:
        raise UpdateError("This workspace still holds the Walls table of Garrick 0.59, and this Garrick no longer "
                          "reads it. Update to Garrick 0.62.0 first: run the update from that release "
                          "(https://github.com/iamvenuti/garrick/releases/tag/v0.62.0), answer the walls question "
                          "it asks, then run this update again. Nothing was changed.")
    return flags


def rewrite_tables(text, flags):
    """`text` with the Zones table as `| Zone | Holds | Walled |` (other columns kept, Party and New parties gone)
    and the Walled column off the Parties table. A table already in that shape is left as it is."""
    lines = text.splitlines()
    zones = _table_at(lines, "zones")
    if zones is not None:
        first, last = zones
        header = _cells(lines[first])
        low = [h.lower() for h in header]
        keep = [i for i, h in enumerate(low) if not h.startswith(("party", "new parties"))]
        zone_at = _column(low, "zone")
        walled_at = _column(low, "walled")
        holds_at = _column(low, "holds")
        new = [[header[i] for i in keep]]
        if walled_at is None:
            new[0].insert((keep.index(holds_at) + 1) if holds_at in keep else len(keep), "Walled")
        rows = [_cells(l) for l in lines[first + 2:last]]
        for cells in rows:
            cells += [""] * (len(header) - len(cells))
            out = [cells[i] for i in keep]
            if walled_at is None:
                name = _plain(cells[zone_at]) if zone_at is not None else ""
                walled = flags.get(name, flags.get(next((z for z in flags if z.casefold() == name.casefold()), ""), (True, "")))[0]
                out.insert((keep.index(holds_at) + 1) if holds_at in keep else len(keep), "yes" if walled else "no")
            new.append(out)
        block = [_row(new[0]), "|" + "---|" * len(new[0])] + [_row(c) for c in new[1:]]
        lines[first:last] = block
    parties = _table_at(lines, "parties")
    if parties is not None:
        first, last = parties
        header = _cells(lines[first])
        at = _column([h.lower() for h in header], "walled")
        if at is not None:
            block = [_row([c for i, c in enumerate(header) if i != at]), "|" + "---|" * (len(header) - 1)]
            for line in lines[first + 2:last]:
                cells = _cells(line)
                cells += [""] * (len(header) - len(cells))
                block.append(_row([c for i, c in enumerate(cells) if i != at]))
            lines[first:last] = block
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def duplicate_people(text):
    """(the text without them, the rows taken out): a People row that repeats a name already listed above it. The
    first row of a person stays; the Party cell was a wall's and is context now."""
    lines = text.splitlines()
    span = _table_at(lines, "people")
    if span is None:
        return text, []
    first, last = span
    name_at = _column([h.lower() for h in _cells(lines[first])], "name")
    if name_at is None:
        return text, []
    seen, gone, keep = set(), [], []
    for i in range(first, last):
        cells = _cells(lines[i])
        if i >= first + 2 and len(cells) > name_at:
            key = _plain(cells[name_at]).casefold()
            if key in seen:
                gone.append(lines[i])
                continue
            seen.add(key)
        keep.append(lines[i])
    lines[first:last] = keep
    return "\n".join(lines) + ("\n" if text.endswith("\n") else ""), gone


# ---- the two checks and their diff

def run_wall_check(check, root, final=False):
    """The walls findings of one check.py over `root`, each as its --json gives it. Raises UpdateError when it
    does not run: a diff made of half its parts would say nothing was released."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    if final:       # the zone flags the tables would hold count as written: what the zone rule refuses after the yes
        env["GARRICK_ZONE_FLAGS_FINAL"] = "1"
    else:
        env.pop("GARRICK_ZONE_FLAGS_FINAL", None)
    try:
        r = subprocess.run([sys.executable, "-B", str(check), "--root", str(root), "--walls-only", "--json"],
                           capture_output=True, text=True, timeout=WALL_TIMEOUT, env=env, cwd=str(root))
        data = json.loads(r.stdout)
        found = data["findings"]
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError) as exc:
        raise UpdateError("The walls check %s could not be run (%s), so the update cannot say what it would change. "
                          "Nothing was changed." % (check, exc.__class__.__name__))
    return [f for f in found if isinstance(f, dict) and f.get("check") == "walls" and f.get("severity") == "error"]


_SUBJECT = (re.compile(r"\[\[([^\]|#]+)"), re.compile(r"\]\(([^)#\s]+)"), re.compile(r"the path (\S+)"),
            re.compile(r"<([^<>\s]+)>"))


def _subject(finding):
    """What a finding is about, apart from how the check words it: its first link, path or tag."""
    message = finding.get("message") or ""
    for pattern in _SUBJECT:
        hit = pattern.search(message)
        if hit:
            return hit.group(1).strip("`").lower()
    return finding.get("fid") or finding.get("token") or message


def _keys(finding):
    path = finding.get("path") or ""
    return {(path, finding.get("fid") or ""), (path, _subject(finding))} - {(path, "")}


def diff_findings(old, new):
    """(released, newly refused): the findings only the old check has, and those only the new one has. A finding is
    the same in both when its path and id agree, or its path and what it is about."""
    seen_new = set().union(*[_keys(f) for f in new]) if new else set()
    seen_old = set().union(*[_keys(f) for f in old]) if old else set()
    released = [f for f in old if not (_keys(f) & seen_new)]
    refused = [f for f in new if not (_keys(f) & seen_old)]
    return released, refused


def _meeting_stems(root):
    """{stem: [paths]} of every page of the Meetings wiki."""
    base = root / "Wikis" / "Meetings"
    stems = {}
    if base.is_dir():
        for path in base.rglob("*.md"):
            stems.setdefault(path.stem.casefold(), []).append(path)
    return stems


def _party_zones(text):
    """{tag: zone name} from the Parties table."""
    header, rows = _table_rows(text.splitlines(), "parties")
    tag_at, zone_at = _column(header, "tag"), _column(header, "zone")
    out = {}
    if tag_at is None or zone_at is None:
        return out
    for row in rows:
        if len(row) > max(tag_at, zone_at):
            out[_plain(row[tag_at]).lstrip("#").lower()] = _plain(row[zone_at])
    return out


def _target_zone(root, lib, finding, stems, parties, zones):
    """The zone of what a finding points at or names: the file a link or path resolves to, else the zone of the
    party it names. None when neither says."""
    message = finding.get("message") or ""
    found = set()
    for pattern in _SUBJECT[:3]:
        for target in pattern.findall(message):
            target = target.strip("`").strip()
            options = []
            if target.startswith(("Zones/", "Wikis/")):
                options += [root / target, root / (target + ".md")]
            else:
                options += [root / "Wikis" / "Meetings" / (target + ".md")]
                stem = Path(target).name.casefold()
                stem = stem[:-3] if stem.endswith(".md") else stem
                if len(stems.get(stem, [])) == 1:
                    options += stems[stem]
            hit = next((p for p in options if p.is_file()), None)
            if hit is not None:
                found.add(lib.zone_of(root, hit))
    if found:
        return found.pop() if len(found) == 1 else None
    tags = set(re.findall(r"<([^<>\s]+)>", message)) | set(re.findall(r"; (\S+) is walled", message))
    known = {parties[t.lower()] for t in tags if t.lower() in parties}
    if len(known) == 1:
        zone = known.pop()
        return next((z for z in zones if z.casefold() == zone.casefold()), zone)
    return None


def classify(root, lib, finding, stems, parties, zones):
    """"inside", "name" or "other" for a finding the zone rule releases."""
    src = lib.zone_of(root, finding.get("path") or "")
    target = _target_zone(root, lib, finding, stems, parties, zones)
    if src is not None and target == src:
        return "inside"
    if re.match(r"\s*names\b", finding.get("message") or "") or "one of its people" in (finding.get("message") or ""):
        return "name"
    return "other"


def mixed_pages(root, lib, flags):
    """The Meetings entity and people pages whose sources sit in two walled zones, as [(path, [zones])]."""
    base = root / "Wikis" / "Meetings"
    stems = _meeting_stems(root)
    out = []
    walled = {z.casefold() for z, (w, _) in flags.items() if w}
    for kind in ("entities", "people"):
        for page in sorted((base / "wiki" / kind).glob("*.md")) if (base / "wiki" / kind).is_dir() else []:
            zones = page_source_zones(root, lib, page, stems)
            hit = sorted({z for z in zones if z is not None and (z == lib.UNZONED or z.casefold() in walled)})
            if len(hit) > 1:
                out.append((page.relative_to(root).as_posix(), hit))
    return out


def page_source_zones(root, lib, page, stems):
    try:
        text = page.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    zones = set()
    for target in re.findall(r"\[\[([^\]|#]+)", text) + re.findall(r"\]\(([^)#\s]+)", text):
        stem = Path(target.strip()).name.casefold()
        stem = stem[:-3] if stem.endswith(".md") else stem
        paths = stems.get(stem, [])
        if len(paths) == 1 and paths[0] != page and "sources" in paths[0].parts:
            zones.add(lib.zone_of(root, paths[0]))
    return zones


def walls_study(root, flags, old_check=None, new_check=None):
    """Everything the yes would change, read only: the proposed flags, the two checks' findings and their diff,
    the mixed Meetings pages, and the text that says so."""
    lib = install.lib()
    old_check = old_check or root / "System" / "tools" / "check.py"
    new_check = new_check or TEMPLATE / "System" / "tools" / "check.py"
    old = run_wall_check(old_check, root)
    new = run_wall_check(new_check, root, final=True)
    released, refused = diff_findings(old, new)
    text = (root / "System" / "context.md").read_text(encoding="utf-8", errors="replace")
    stems, parties, zones = _meeting_stems(root), _party_zones(text), list(flags)
    kinds = {k: [] for k, _ in WALL_KINDS}
    for f in released:
        kinds[classify(root, lib, f, stems, parties, zones)].append(f)
    mixed = mixed_pages(root, lib, flags)
    study = {"flags": {z: w for z, (w, _) in flags.items()}, "released": {k: len(v) for k, v in kinds.items()},
             "newly_refused": len(refused), "mixed_pages": [p for p, _ in mixed], "old": len(old), "new": len(new)}
    return study, say_study(flags, kinds, refused, mixed)


def say_finding(f):
    return "  %s: %s" % (f.get("path"), (f.get("message") or "").strip())


def say_study(flags, kinds, refused, mixed):
    out = ["Garrick 0.63 walls each zone, not each party. Each zone is either walled or open: what is in a walled zone "
           "stays in that zone; what is in an open zone may go anywhere.", "",
           "The flag each zone would get, from its party and its default for new parties:"]
    out += ["  %-14s %-7s because %s" % (z, "walled" if w else "open", why) for z, (w, why) in flags.items()]
    if refused:
        out += ["", "NEWLY REFUSED: %d thing%s the zone rule refuses and the rule in force passes. Read these first; "
                    "the release is meant to refuse nothing new." % (len(refused), "" if len(refused) == 1 else "s")]
        out += [say_finding(f) for f in refused[:50]]
        if len(refused) > 50:
            out.append("  ... and %d more." % (len(refused) - 50))
    total = sum(len(v) for v in kinds.values())
    out += ["", "%d refusal%s of the rule in force %s released by the zone rule:" % (
        total, "" if total == 1 else "s", "is" if total == 1 else "are")]
    for key, title in WALL_KINDS:
        found = kinds[key]
        out.append("")
        out.append("%s (%d)" % (title, len(found)))
        out += [say_finding(f) for f in found[:SHOWN]]
        if len(found) > SHOWN:
            out.append("  ... and %d more." % (len(found) - SHOWN))
    out += ["", "Meetings entity and people pages whose sources sit in two walled zones (%d):" % len(mixed)]
    out += ["  %s: %s" % (p, ", ".join(z)) for p, z in mixed] or ["  none"]
    return "\n".join(out)


# ---- the clean-up lists

def stale_allowances(root):
    """The ledger entries that no longer hold a finding, as [entry]: the file is gone or has changed since, or the
    zone rule's check, run with the ledger left out, has no finding of that id for it. Empty when that check cannot
    be run: an entry that cannot be shown stale stays."""
    path = root / "System" / "walls-allowed.json"
    try:
        entries = [e for e in json.loads(path.read_text(encoding="utf-8")).get("allowed", []) if isinstance(e, dict)]
    except (OSError, ValueError, AttributeError):
        return []
    if not entries:
        return []
    program = ("import sys, json; from pathlib import Path; sys.path.insert(0, sys.argv[1]); import check; "
               "root = Path(sys.argv[2]); found = check.run_checks(root, walls_only=True, use_ledger=False); "
               "print(json.dumps([[f.path, check.finding_id(f)] for f in found if f.check == 'walls']))")
    try:
        r = subprocess.run([sys.executable, "-B", "-c", program, str(TEMPLATE / "System" / "tools"), str(root)],
                           capture_output=True, text=True, timeout=WALL_TIMEOUT, cwd=str(root),
                           env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        live = {tuple(x) for x in json.loads(r.stdout)}
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        return []
    stale = []
    for e in entries:
        if not (root / str(e.get("path", ""))).is_file() or (str(e.get("path")), str(e.get("id"))) not in live:
            stale.append(e)
    return stale


def page_blocks(body):
    """The blocks of a page body: each heading, each paragraph and each top-level list item with what continues it."""
    blocks, current = [], []

    def close():
        if current:
            blocks.append("\n".join(current))
            current.clear()
    for line in body.strip("\n").splitlines():
        if not line.strip():
            close()
        elif line.lstrip().startswith("#") and not line.startswith((" ", "\t")):
            close()
            blocks.append(line)
        elif re.match(r"^ {0,2}([-*]|\d+\.)\s", line):
            close()
            current.append(line)
        else:
            current.append(line)
    close()
    return blocks


def split_page(root, lib, page, stems):
    """The page cut per zone, {zone: text}, or None when a block of it cannot be placed in one walled zone: a
    block that cites no source or sources of two zones is not guessed at. Each block is a run of lines up to a
    blank line; the front matter goes with each zone's page, with `zone:` set and only that zone's sources."""
    text = page.read_text(encoding="utf-8", errors="replace")
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
    front, body = (m.group(1), m.group(2)) if m else ("", text)
    order, placed = [], {}
    for block in page_blocks(body):
        zones = set()
        for target in re.findall(r"\[\[([^\]|#]+)", block) + re.findall(r"\]\(([^)#\s]+)", block):
            stem = Path(target.strip()).name.casefold()
            stem = stem[:-3] if stem.endswith(".md") else stem
            hit = stems.get(stem, [])
            if len(hit) == 1 and "sources" in hit[0].parts:
                zones.add(lib.zone_of(root, hit[0]))
        if block.lstrip().startswith("#") and not zones:
            order.append((None, block))
            continue
        if len(zones) != 1 or None in zones:
            return None
        zone = zones.pop()
        placed.setdefault(zone, []).append(block)
        order.append((zone, block))
    if len(placed) < 2:
        return None
    out = {}
    for zone in placed:
        mine = [b for z, b in order if z in (None, zone)]
        while mine and mine[-1].lstrip().startswith("#"):
            mine.pop()
        mine = [b for i, b in enumerate(mine) if not (b.lstrip().startswith("#") and i + 1 < len(mine) and mine[i + 1].lstrip().startswith("#"))]
        lines = [l for l in front.splitlines() if not l.startswith("zone:")]
        lines.append("zone: %s" % zone)
        kept, skip = [], False
        for line in lines:
            if line.startswith("sources:"):
                skip = True
                kept.append(line)
                continue
            if skip and line.startswith((" ", "-")):
                target = re.search(r"\[\[([^\]|#]+)", line)
                stem = Path(target.group(1)).name.casefold() if target else ""
                hit = stems.get(stem, [])
                if len(hit) == 1 and lib.zone_of(root, hit[0]) == zone:
                    kept.append(line)
                continue
            skip = False
            kept.append(line)
        text = ""
        for i, b in enumerate(mine):
            if i:
                text += "\n" if re.match(r"^ {0,2}([-*]|\d+\.)\s", b) and re.match(r"^ {0,2}([-*]|\d+\.)\s", mine[i - 1]) else "\n\n"
            text += b
        out[zone] = "---\n" + "\n".join(kept) + "\n---\n\n" + text + "\n"
    return out


def apply_page_split(root, lib, page, parts):
    """Write one page per zone beside `page`, take `page` out, commit in the Meetings repository. "" or why not."""
    repo = root / "Wikis"
    written = []
    try:
        for zone, text in parts.items():
            slug = re.sub(r"[^a-z0-9]+", "-", zone.lower()).strip("-")
            target = page.with_name("%s-%s.md" % (page.stem, slug))
            if target.exists():
                return "%s is already there" % target.name
            target.write_text(text, encoding="utf-8")
            written.append(target)
        rels = [p.relative_to(repo).as_posix() for p in written] + [page.relative_to(repo).as_posix()]
        git(repo, "rm", "-q", "--", page.relative_to(repo).as_posix())
        git(repo, "add", "--", *rels[:-1])
        git(repo, "commit", "-q", "-m", "Garrick: %s split per zone" % page.stem, "--", *rels)
    except (OSError, UpdateError) as exc:
        for p in written:
            try:
                p.unlink()
            except OSError:
                pass
        git(repo, "reset", "-q", "HEAD", "--", page.relative_to(repo).as_posix(), check=False)
        git(repo, "checkout", "--", page.relative_to(repo).as_posix(), check=False)
        return str(exc)
    return ""


def ask(question, answers, tty):
    """True on a yes: `answers` is True when the flag said so; a terminal is asked; no one to ask is a no."""
    if answers:
        return True
    if not tty:
        return False
    return input(question + " [y/N] ").strip().lower() in ("y", "yes")


def cleanups(root, clean, tty, as_json=False):
    """The three lists, each on its own yes: `clean` names the lists answered yes with `--clean`, a terminal asks.
    Returns (lines to print, data)."""
    lib = install.lib()
    out, data = [], {}
    context = root / "System" / "context.md"
    text = context.read_text(encoding="utf-8", errors="replace")
    shown, gone = duplicate_people(text)
    data["people"] = len(gone)
    if gone:
        out += ["", "People rows that repeat a person under a second party (%d):" % len(gone)] + ["  " + g for g in gone]
        if ask("Take these rows out of the People table?", "people" in clean, tty and not as_json):
            why = commit_files(root, {"System/context.md": (shown.encode("utf-8"), context.stat().st_mode & 0o777)},
                               "Garrick: one People row for each person")
            out.append("Took them out." if not why else "Nothing was written: System/context.md: %s." % why)
        else:
            out.append("Left as they are. To take them out: python3 System/tools/release.py update --apply --clean people")
    stale = stale_allowances(root)
    data["ledger"] = len(stale)
    if stale:
        out += ["", "Allowances whose finding no longer exists (%d):" % len(stale)] + ["  %s (%s)" % (e.get("path"), e.get("rule")) for e in stale]
        if ask("Take these allowances out of the ledger?", "ledger" in clean, tty and not as_json):
            ledger = root / "System" / "walls-allowed.json"
            current = json.loads(ledger.read_text(encoding="utf-8"))
            drop = {(e.get("path"), e.get("id"), e.get("blob")) for e in stale}
            current["allowed"] = [e for e in current.get("allowed", []) if (e.get("path"), e.get("id"), e.get("blob")) not in drop]
            why = commit_files(root, {"System/walls-allowed.json": ((json.dumps(current, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
                                                                    ledger.stat().st_mode & 0o777)},
                               "Garrick: take out the allowances that hold no finding")
            out.append("Took them out." if not why else "Nothing was written: System/walls-allowed.json: %s." % why)
        else:
            out.append("Left as they are. To take them out: python3 System/tools/release.py update --apply --clean ledger")
    flags = zone_flags_after(root)
    stems = _meeting_stems(root)
    pages = [(root / p, z) for p, z in mixed_pages(root, lib, flags)] if flags else []
    data["pages"] = len(pages)
    if pages:
        out += ["", "Mixed Meetings pages, to split per zone, page by page (%d):" % len(pages)]
        for page, zones in pages:
            rel = page.relative_to(root).as_posix()
            parts = split_page(root, lib, page, stems)
            if parts is None:
                out.append("  %s (%s): a block of it cites no source or sources of two zones, so it is split by hand "
                           "or through the meetings skill" % (rel, ", ".join(zones)))
                continue
            out.append("  %s -> %s" % (rel, ", ".join("%s-%s.md" % (page.stem, re.sub(r"[^a-z0-9]+", "-", z.lower()).strip("-")) for z in parts)))
            if ask("Split %s per zone?" % page.name, "pages" in clean, tty and not as_json):
                why = apply_page_split(root, lib, page, parts)
                out.append("    Split." if not why else "    Not split: %s." % why)
            else:
                out.append("    Left as it is. To split it: python3 System/tools/release.py update --apply --clean pages")
    return out, data


def zone_flags_after(root):
    """{zone: (walled, why)} of a context with its Walled column, read from the table."""
    try:
        text = (root / "System" / "context.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    header, rows = _table_rows(text.splitlines(), "zones")
    zone_at, walled_at = _column(header, "zone"), _column(header, "walled")
    if zone_at is None or walled_at is None:
        return {}
    return {_plain(r[zone_at]): (_plain(r[walled_at]).lower() != "no", "the Zones table") for r in rows if len(r) > max(zone_at, walled_at)}


def walls_step(root, answer, apply_changes, as_json=False, only=False):
    """The walls step, before the update installs anything. Returns (go, text, data): `go` is True when the update
    may go on (nothing waits, or the yes was given and the tables were written), `text` what to print first, `data`
    for --json. A no, and nobody to answer, stop it with the workspace as it was."""
    flags = walls_pending(root)
    if flags is None:
        return True, "", None
    study, said = walls_study(root, flags)
    data = {"pending": True, **study}
    if not apply_changes:
        return False, said + "\n\nNothing is written. Run python3 System/tools/release.py update --apply, and answer at the " \
                            "terminal or add --yes. Until you say yes the update installs nothing.", data
    if only:
        return False, "The walls step waits, so nothing is installed, not even the files named with --only. Run the " \
                      "update again without --only to read it.", data
    tty = sys.stdin.isatty() and sys.stdout.isatty() and not as_json
    if not answer and tty:
        print(said)
        said = ""
        answer = input("Write the zone flags, install this Garrick and take out what nothing reads? [y/N] ").strip().lower() in ("y", "yes")
    if not answer:
        return False, (said + "\n\n" if said else "") + "Nothing was installed and nothing was written. The 0.62 rule " \
            "keeps deciding every flow, as it did. Once you have read the changes above, run " \
            "python3 System/tools/release.py update --apply --yes (or answer yes at the terminal).", data
    context = root / "System" / "context.md"
    text = rewrite_tables(context.read_text(encoding="utf-8"), flags)
    why = commit_files(root, {"System/context.md": (text.encode("utf-8"), context.stat().st_mode & 0o777)},
                       "Garrick: a Walled flag on each zone, in System/context.md")
    if why:
        return False, (said + "\n\n" if said else "") + "Nothing was installed and nothing was written: System/context.md: %s." % why, data
    data["written"] = True
    return True, (said + "\n\n" if said else "") + "Wrote the Walled column of the Zones table, and took the Party and New parties " \
                                                    "columns and the Parties table's Walled column out.", data


def find_workspace(path):
    root = Path(path).expanduser()
    root = Path(os.path.abspath(root))
    if not (root / "System" / "rules.md").is_file():
        raise UpdateError("%s is not a Garrick workspace: it has no System/rules.md." % root)
    overlap = install.source_overlap(root)
    if overlap == "holds":
        raise UpdateError("The Garrick this update runs from, %s, is inside the workspace it would update. "
                          "Unzip the newer Garrick outside it (your Downloads folder will do), or export a release "
                          "from your clone with `git archive vX.Y.Z | tar -x -C <folder>`, and run install.py "
                          "from there." % REPO)
    if overlap:
        raise UpdateError("%s is the Garrick folder this update runs from, or inside it. "
                          "Name your workspace, such as ~/Garrick." % root)
    return root.resolve()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Update a Garrick workspace to this Garrick.")
    ap.add_argument("workspace", nargs="?", help="the workspace folder, such as ~/Garrick")
    ap.add_argument("--apply", action="store_true", help="make the changes; without it, only say what they would be")
    ap.add_argument("--only", default="", help="comma-separated paths, as the report lists them")
    ap.add_argument("--json", action="store_true", help="the report as JSON")
    ap.add_argument("--yes", action="store_true",
                    help="answer yes to the walls step: write the zone flags, then install (needs --apply)")
    ap.add_argument("--clean", action="append", default=[], choices=CLEAN_KINDS, metavar="LIST",
                    help="answer yes to one clean-up list after the walls step: %s (needs --apply; repeat for more)"
                         % ", ".join(CLEAN_KINDS))
    ap.add_argument("--split", action="store_true",
                    help="move your own text out of Garrick's instruction files, into the local file beside each")
    ap.add_argument("--today", help=argparse.SUPPRESS)
    ap.add_argument("--release-hashes", action="store_true",
                    help="maintainers: rewrite release-hashes.json from this clone's tags")
    args = ap.parse_args(argv)
    try:
        if args.release_hashes:
            RELEASE_HASHES.write_text(json.dumps(release_hashes(), indent=1) + "\n", encoding="utf-8")
            print("Wrote %s." % RELEASE_HASHES.name)
            return 0
        if not args.workspace:
            ap.error("name the workspace to update, such as ~/Garrick")
        install.check_git()
        root = find_workspace(args.workspace)
        p = plan(root)
        only = [x.strip() for x in args.only.split(",") if x.strip()] or None
        if args.split:
            import split        # beside this file, from the same Garrick
            return split.main(root, p, args.apply, only, args.json)
        if not args.apply:
            p["then"] = [what for what, _ in next_steps(root, p)]
            _, said, walls = walls_step(root, False, False)
            if args.json:
                shown = {k: v for k, v in p.items() if k not in ("files", "recorded")}
                if shown.get("allowlist"):      # its files hold bytes, as p["files"] does
                    shown["allowlist"] = {k: v for k, v in shown["allowlist"].items() if k != "files"}
                if walls is not None:
                    shown["walls"] = walls
                print(json.dumps(shown, indent=2))
            else:
                print(report(p))
                if said:
                    print("\n" + said)
            return 0
        go, said, walls = walls_step(root, args.yes, True, as_json=args.json, only=only is not None)
        if not go:
            if args.json:
                print(json.dumps({"walls": walls, "installed": False, "message": said}, indent=2))
            else:
                print(said)
            return 0
        result = apply(root, p, only, args.today)
        migrated = walls is not None
        tidy, tidy_data = ([], {})
        if migrated or args.clean:
            tidy, tidy_data = cleanups(root, set(args.clean), sys.stdin.isatty() and sys.stdout.isatty() and not args.json, args.json)
            if args.json:
                result["cleanup"] = tidy_data
        if walls is not None:
            result["walls"] = walls
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(say_applied(p, result))
            if said:
                print("\n" + said)
            if tidy:
                print("\n".join(tidy))
        return 1 if result["problems"] or result["unstamped"] else 0
    except (UpdateError, install.InstallError) as exc:
        print(exc, file=sys.stderr)
        return 1
    except OSError as exc:
        print("The update stopped: %s. Run it again without --apply to see where the workspace stands." % exc,
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
