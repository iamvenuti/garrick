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
`System/context.md` is never read or written, and neither is a local file
beside an instruction file, such as `System/rules.local.md`. The
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
    return {"workspace": str(root), "from": {k: stamp.get(k, "") for k in ("commit", "date")},
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
    if not any(p["actions"][k] for k in ("replace", "add", "merge", "split", "restore")) and not p["hooks"]:
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

    hooks = []
    for zone in p["hooks"]:
        lib.install_wall_hook(root / "Zones" / zone)
        hooks.append(zone)

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
            "problems": problems, "stamped": stamped, "unstamped": unstamped, "then": then,
            "allowlist": allowed}


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
    """Errors the workspace's own check now finds in the files just written."""
    if not paths:
        return []
    tool = root / "System" / "tools" / "check.py"
    try:
        r = subprocess.run([sys.executable, str(tool), "--root", str(root), "--json"],
                           capture_output=True, text=True, timeout=600)
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
    if result["hooks"]:
        lines.append("Refreshed the wall check in: %s." % ", ".join(result["hooks"]))
    lines += say_allowlist(result.get("allowlist"), applied=True)
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
    this workspace under the name it had before 0.49.0, with the commands
    that rename it: [{plist, label, job, new, retired, commands}]. Reads the
    folder and nothing else; never writes there, and runs none of them."""
    folder = launch_agents()
    if not folder.is_dir():
        return []
    renamed, retired = job_names()
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
        if name not in renamed and name not in retired or not any(Path(a).name == OLD_SCRIPTS[name] for a in cmd):
            continue
        found.append(rename_commands(plist, data, args, at, name, renamed.get(name) or retired[name],
                                     name in retired))
    return found


def rename_commands(plist, data, args, at, name, new, retired):
    """The commands, in order, that take one plist from its old name to its
    new one, kept as the user edited it otherwise: unload it, set its label,
    its job name, its log paths and its line of description with plutil,
    rename the file, load it. For the nightly job, its script and a time
    limit for four steps too. A retired job is unloaded and put in the Trash."""
    label = str(data.get("Label") or plist.stem)

    def q(path):                                # a path under the home folder as ~/..., as the docs write it
        try:
            return "~/" + shlex.quote(str(Path(path).relative_to(Path.home())))
        except ValueError:
            return shlex.quote(str(path))
    out = {"plist": str(plist), "label": label, "job": name, "new": new, "retired": retired, "commands": []}
    cmds = out["commands"]
    cmds.append("launchctl bootout gui/$(id -u)/%s" % shlex.quote(label))
    target = plist.with_name("garrick.%s.plist" % new)
    if retired or (target.exists() and not same_place(target, plist)):
        cmds.append("mv %s %s" % (q(str(plist)), q(str(Path.home() / ".Trash") + "/")))
        return out
    def edit(key, value):                       # a key of a dictionary: replaced, or added
        cmds.append("plutil -replace %s -string %s %s" % (key, (q if key.endswith("Path") else shlex.quote)(str(value)),
                                                          q(str(plist))))

    def put(index, value, replace=True):        # an item of ProgramArguments: plutil's -replace inserts there
        if replace:
            cmds.append("plutil -remove ProgramArguments.%d %s" % (index, q(str(plist))))
        cmds.append("plutil -insert ProgramArguments.%d -string %s %s" % (
            index, (q if "/" in str(value) else shlex.quote)(str(value)), q(str(plist))))

    edit("Label", "garrick." + new)
    put(at + 1, new)
    if name == "nurture":
        flags = args[at + 2:args.index("--", at)] if "--" in args[at:] else []
        script = next(i for i, a in enumerate(args) if i > at and Path(a).name == OLD_SCRIPTS[name])
        put(script, str(Path(args[script]).with_name("nightly.py")))
        if "--timeout" not in flags:            # four steps need more than the 25 minutes nurture had
            put(at + 2, "3600", replace=False)
            put(at + 2, "--timeout", replace=False)
    for key in ("StandardOutPath", "StandardErrorPath"):
        value = data.get(key)
        if isinstance(value, str) and value.endswith("/%s.launchd.log" % name):
            edit(key, value[:-len("%s.launchd.log" % name)] + "%s.launchd.log" % new)
    about = shipped_about(new)
    env = data.get("EnvironmentVariables")
    if about and not (isinstance(env, dict) and env.get("GARRICK_ABOUT") == about):
        if not isinstance(env, dict):
            cmds.append("plutil -insert EnvironmentVariables -dictionary %s" % q(str(plist)))
        edit("EnvironmentVariables.GARRICK_ABOUT", about)
    cmds.append("mv %s %s" % (q(str(plist)), q(str(target))))
    cmds.append("launchctl bootstrap gui/$(id -u) %s" % q(str(target)))
    return out


def say_renames(renames):
    """The report's lines for the plists still running Garrick's jobs under
    their old names: one message, then each plist and its commands."""
    if not renames:
        return []
    folder = str(Path(renames[0]["plist"]).parent)
    n = len(renames)
    lines = ["", "Garrick's scheduled jobs have new names, which start with gr-, so they read apart from yours "
             "(#275). %d plist%s in %s still run%s them under the old names. Each keeps working as it is until you "
             "rename it: this update changes nothing in that folder and runs none of these commands. To rename "
             "one, run its lines in Terminal, in order; leave out the last line of one you keep unloaded." % (
                 n, "" if n == 1 else "s", folder, "s" if n == 1 else "")]
    for r in renames:
        name = Path(r["plist"]).name
        if r["retired"]:
            lines.append("  %s runs %s, which the nightly job gr-nightly now does. Once garrick.gr-nightly is loaded, "
                         "unload this one and put it in the Trash:" % (name, r["job"]))
        elif r["commands"][1].startswith("mv "):
            lines.append("  %s runs %s, and garrick.%s.plist is already there. Unload the old one and put it in "
                         "the Trash:" % (name, r["job"], r["new"]))
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


def garrick_apps(root):
    """Each Garrick.app built for this workspace, with the flags make-app.sh
    stored in it: [(app, [flags])]. macOS only."""
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
            out.append((app, [str(a) for a in args] if isinstance(args, list) else []))
    return out


def make_app(cmd):
    """Run make-app.sh; (exit code, its last line)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    lines = (r.stdout + r.stderr).strip().splitlines()
    return r.returncode, lines[-1] if lines else ""


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

    for what, path in outside_copies(root):
        steps.append(("%s runs from %s, which differs from this Garrick's. Point your assistant's settings at a newer "
                      "Garrick you keep outside the workspace" % (what[0].upper() + what[1:], path), None))
    return steps


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
            if args.json:
                shown = {k: v for k, v in p.items() if k not in ("files", "recorded")}
                if shown.get("allowlist"):      # its files hold bytes, as p["files"] does
                    shown["allowlist"] = {k: v for k, v in shown["allowlist"].items() if k != "files"}
                print(json.dumps(shown, indent=2))
            else:
                print(report(p))
            return 0
        result = apply(root, p, only, args.today)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(say_applied(p, result))
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
