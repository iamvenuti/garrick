#!/usr/bin/env python3
"""Bring a Garrick workspace up to this Garrick, without losing what you changed.

    python3 install.py --update ~/Garrick                    say what would change; changes nothing
    python3 install.py --update ~/Garrick --apply            do it
    python3 install.py --update ~/Garrick --apply --only System/tools/check.py,System/rules.md
    python3 install.py --update ~/Garrick --json             the same report, for a program

Run it from the newer Garrick: a fresh download, or a clone after `git pull`.
It compares every file Garrick would write today with the one in the
workspace, and with the fingerprint the workspace recorded when Garrick wrote
it (`System/garrick-version.json`), and sorts each into one of these:

- **replace**: a file still as some Garrick wrote it, with a newer version.
- **add**: a file new in this Garrick.
- **merge**: a file you changed that Garrick has changed too. Garrick's version
  goes beside it as `<name>.new`, and yours stays as it is. `System/rules.md` is
  always merged, never replaced: it is yours to amend. The `.new` is
  committed, so it survives a clean or a clone until you merge it. Once it is
  written the file counts as offered, and is offered again only when a later
  Garrick changes it again.
- **yours**: a file Garrick only starts, such as a zone's `Todo.md` or a wiki's
  log, that you have since filled in. Never touched, not even with a `.new`.
- **restore**: a file Garrick ships that you deleted. Put back only when named
  with `--only`.
- **retired**: a file Garrick wrote that it no longer ships. Never deleted.

Nothing is written without `--apply`, and nothing is ever deleted. Each
repository the update touches gets one commit of its own, holding only the
files the update wrote, `.new` files included, so `git revert` undoes it.
`System/context.md` is never read or written. The
version stamp changes last, once everything picked has applied and the
workspace's check finds no error in a file the update wrote. Running it twice
changes nothing the second time.

Python 3.9+, standard library only. Writes nothing outside the workspace, and
never through a symbolic link.
"""

import argparse
import datetime
import fnmatch
import hashlib
import json
import os
import re
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
# Files that are yours to amend even when Garrick wrote them: always merged, never replaced.
NEVER_REPLACE = ("System/rules.md",)
NEW_SUFFIX = ".new"

KINDS = ("replace", "add", "merge", "yours", "restore", "retired")


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


def shipped(zones):
    """Every file this Garrick's installer writes into a workspace with these
    zones, as {path from the top: (bytes, mode)}. Not System/context.md, which
    holds the user's answers, and not the version stamp."""
    out = {}
    _tree(TEMPLATE, "", out, skip=("System", "Wikis", "Zones"))
    _tree(TEMPLATE / "System", "System", out, skip=("context.md",))
    if (REPO / "CHANGELOG.md").is_file():
        out["System/garrick-changelog.md"] = ((REPO / "CHANGELOG.md").read_bytes(), 0o644)
    _tree(TEMPLATE / "Wikis", "Wikis", out)
    zone_template = TEMPLATE.joinpath(*install.lib().ZONE_TEMPLATE)
    for zone in zones:
        _tree(zone_template, "Zones/" + zone, out, fill={"ZONE": zone})
    for path, text in install.ignore_files(zones).items():
        out[path] = (text.encode("utf-8"), 0o644)
    for path in list(out):
        if path in install.lib().UNLISTED:
            del out[path]
    return out


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
    new = shipped(zones)
    actions = {kind: [] for kind in KINDS}
    current, kept = [], []
    history = {}        # repository: every path it ever committed, read once, for a stamp with no list
    for path in sorted(set(new) | set(recorded)):
        if path in lib.UNLISTED:
            continue
        on_disk = read(root / path)
        if path not in new:
            if on_disk is not None:
                actions["retired"].append(path)
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
        if recorded.get(path) == target:
            kept.append(path)               # changed by you, and Garrick has nothing newer
            continue
        as_written = have == recorded.get(path) or have in known.get(path, ())
        if path in NEVER_REPLACE:
            actions["merge"].append(path)
        elif as_written:
            actions["replace"].append(path)
        elif is_seed(path):
            actions["yours"].append(path)
        else:
            actions["merge"].append(path)
    hooks = [z for z in zones if stale_hook(root / "Zones" / z)]
    return {"workspace": str(root), "from": {k: stamp.get(k, "") for k in ("commit", "date")},
            "to": {k: v for k, v in install.source_version().items() if k in ("commit", "date", "from")},
            "actions": actions, "current": current, "kept": kept, "hooks": hooks, "files": new,
            "recorded": recorded, "listed": listed}


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


def report(p, applied=None):
    lines = ["Garrick update for %s: from %s to %s." % (p["workspace"], say_commit(p["from"]), say_commit(p["to"]))]
    if applied is None:
        lines.append("Nothing has been changed. To make these changes, run the same command with --apply.")
    for kind in KINDS:
        paths = p["actions"][kind]
        if paths:
            label, one, many = LABELS[kind]
            lines += ["", "%s, %d %s:" % (label, len(paths), one if len(paths) == 1 else many)]
            lines += ["  " + path for path in paths]
    if p["hooks"]:
        lines += ["", "Wall check: %d zone%s get%s the newer pre-commit check: %s." % (
            len(p["hooks"]), "" if len(p["hooks"]) == 1 else "s", "s" if len(p["hooks"]) == 1 else "",
            ", ".join(p["hooks"]))]
    if not any(p["actions"][k] for k in ("replace", "add", "merge", "restore")) and not p["hooks"]:
        lines += ["", "Up to date: all %d files Garrick ships are as this Garrick writes them, "
                  "or yours by design." % len(p["files"])]
    else:
        lines += ["", "Already up to date: %d files." % len(p["current"])]
    if p["kept"]:
        lines.append("Changed by you, with nothing newer from Garrick: %d file%s, left as %s." % (
            len(p["kept"]), "" if len(p["kept"]) == 1 else "s", "it is" if len(p["kept"]) == 1 else "they are"))
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
    return {"done": done, "skipped": skipped, "commits": commits, "hooks": hooks,
            "problems": problems, "stamped": stamped, "unstamped": unstamped}


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
    if not lines:
        lines.append("Nothing to do: the workspace is up to date.")
    return "\n".join(lines)


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
    shipped, for release-hashes.json, and the texts of each release's zone
    template, since a zone's own files hold the zone's name and can only be
    recognised once it is filled in."""
    def run(*args):
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True).stdout
    tags = sorted((t for t in run("tag", "-l", "v*").decode().split() if version_key(t)), key=version_key)
    zone = "template/" + "/".join(install.lib().ZONE_TEMPLATE) + "/"
    paths, zone_texts = {}, {}
    for tag in tags:
        for line in run("ls-tree", "-r", "--name-only", tag).decode().splitlines():
            in_zone = line.startswith((zone, OLD_ZONE_TEMPLATE))
            if line == "CHANGELOG.md":
                rel = "System/garrick-changelog.md"
            elif line.startswith(OLD_ZONE_TEMPLATE):
                rel = None                  # copied into each zone, never to a path of its own
            elif line.startswith("template/") and line != "template/System/context.md":
                rel = line[len("template/"):]
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
        if not args.apply:
            if args.json:
                print(json.dumps({k: v for k, v in p.items() if k not in ("files", "recorded")}, indent=2))
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
