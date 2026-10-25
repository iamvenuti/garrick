#!/usr/bin/env python3
"""Whether a newer Garrick is out, and the update to it in one step.

    python3 System/tools/release.py latest              the newest release, asking GitHub at most once a day
    python3 System/tools/release.py latest --now        ask now, however recently it asked
    python3 System/tools/release.py update              download the newest release and say what an update would change
    python3 System/tools/release.py update --apply      ... and make the changes
    python3 System/tools/release.py update --tag v0.16.0 --apply --only System/tools/check.py
    python3 System/tools/release.py update --split      move your text out of Garrick's instruction files

The release notice is off until System/garrick-settings.json says
{"release-notice": true}. Then the status page runs `latest --background` as
it builds: it asks GitHub at most once a day, in a process of its own, and the
page shows the answer from the next build on. Run by hand, both commands ask
whatever the setting says: typing them is the request.

What goes over the wire. `latest` sends one HTTPS GET to
api.github.com/repos/<owner>/<name>/releases/latest, with a User-Agent that
names Garrick and the release the workspace runs ("Garrick/0.15.2"), and
nothing else: no file, name, path or setting of the workspace. The answer, the
newest release's tag, date and page, is kept in
System/generated/garrick-release.json, which is never committed. `update` also
downloads that release's source archive from github.com, the repository the
workspace came from, into a temporary folder outside the workspace, and runs
that release's own `install.py --update`, which reports first and writes
nothing without --apply. The folder is removed afterwards.
When this Python has no certificates (a python.org build before Install
Certificates.command has run), the same GET is made once more with curl,
which trusts the system's certificates, and the update says so.

A failed question is silent: the page shows nothing, and the next one comes a
day later. `check.py --version` never asks; it reads the kept answer.

Standard library only, Python 3.9 or later.
"""

import argparse
import datetime
import json
import os
import re
import shutil
import ssl
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import List, Optional

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from garrick_lib import (  # noqa: E402
    CHANGELOG_COPY,
    RELEASE_CACHE,
    release_asked_lately,
    release_due,
    release_key,
    release_repository,
    say_newer_release,
    workspace_release,
    workspace_root,
)

API = "https://api.github.com/repos/%s/releases/latest"
ARCHIVE = "https://github.com/%s/archive/refs/tags/%s.zip"
TIMEOUT = 10                    # seconds, for the question; the download gets longer
DOWNLOAD_TIMEOUT = 120
MAX_ARCHIVE = 100 * 1024 * 1024
TAG = re.compile(r"^v\d+(?:\.\d+)*(?:-[0-9A-Za-z.]+)?$")


class ReleaseError(Exception):
    """A refusal or failure, worded for the person updating."""


def user_agent(root: Path) -> str:
    return "Garrick/%s" % (workspace_release(root) or "unknown")


NO_CERTIFICATES = ("This Python has no certificates. Run it with /usr/bin/python3, or run Install "
                   "Certificates.command in its folder under /Applications.")


def no_certificates(exc: BaseException) -> bool:
    """Whether a failure is this Python not trusting any certificate: what a
    python.org build does until Install Certificates.command has been run."""
    return isinstance(getattr(exc, "reason", None), ssl.SSLCertVerificationError) or \
        isinstance(exc, ssl.SSLCertVerificationError)


def fetch(url: str, root: Path, timeout: int, accept: str = "", limit: int = 1024 * 1024, say=None) -> bytes:
    """One GET, with Garrick's User-Agent and nothing about the workspace.
    When this Python has no certificates, the GET is made once more with curl,
    which trusts the system's own, and `say` is told so."""
    headers = {"User-Agent": user_agent(root)}
    if accept:
        headers["Accept"] = accept
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
            data = r.read(limit + 1)
    except (OSError, urllib.error.URLError) as exc:
        if not no_certificates(exc):
            raise
        data = fetch_with_curl(url, headers, timeout, limit)
        if say:
            say("This Python has no certificates, so curl fetched %s instead." % url)
    if len(data) > limit:
        raise ReleaseError("%s sent more than %d MB; stopped." % (url, limit // (1024 * 1024)))
    return data


def fetch_with_curl(url: str, headers: dict, timeout: int, limit: int) -> bytes:
    """The same GET through curl. Fails with the one line that says what to do."""
    curl = shutil.which("curl")
    if not curl:
        raise ReleaseError(NO_CERTIFICATES)
    cmd = [curl, "-fsSL", "--proto", "=https", "--max-time", str(timeout), "--max-filesize", str(limit + 1)]
    for key, value in headers.items():
        cmd += ["-H", "%s: %s" % (key, value)]
    try:
        r = subprocess.run(cmd + [url], capture_output=True, timeout=timeout + 5)
    except (OSError, subprocess.TimeoutExpired):
        raise ReleaseError(NO_CERTIFICATES)
    if r.returncode != 0:
        raise ReleaseError(NO_CERTIFICATES)
    return r.stdout


def write_cache(root: Path, data: dict) -> None:
    path = root.joinpath(*RELEASE_CACHE)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".")      # its own: two builds asking at once share none
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, indent=1) + "\n")
        os.replace(tmp, str(path))
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def read_cache(root: Path) -> dict:
    try:
        data = json.loads(root.joinpath(*RELEASE_CACHE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def ask(root: Path, now: Optional[datetime.datetime] = None) -> dict:
    """Ask GitHub for the newest release and keep the answer. The time of
    asking is written first, so two builds at once ask once. A failure keeps
    the last answer and says why under "failed"; it raises nothing."""
    now = now or datetime.datetime.now()
    repo = release_repository(root)
    old = read_cache(root)
    cache = {k: v for k, v in old.items() if k in ("latest", "url", "published")} if old.get("repository") == repo else {}
    cache.update({"repository": repo, "asked": now.isoformat(timespec="seconds")})
    write_cache(root, dict(cache, failed="still asking"))
    try:
        data = json.loads(fetch(API % repo, root, TIMEOUT, accept="application/vnd.github+json").decode("utf-8"))
        tag = data.get("tag_name") if isinstance(data, dict) else None
        if not release_key(tag):
            raise ValueError("the answer names no release")
        cache.update({"latest": tag, "url": str(data.get("html_url") or ""), "published": str(data.get("published_at") or "")})
    except Exception as exc:            # offline, refused, slow or garbled: silent, and asked again tomorrow
        cache["failed"] = str(getattr(exc, "reason", None) or exc)[:200]
    write_cache(root, cache)
    return cache


# --------------------------------------------------------------------------- the download


def unpack(data: bytes, into: Path) -> Path:
    """Unpack a release archive into `into` and return the Garrick folder in
    it. Refuses a member that would land outside, and links of any kind;
    keeps each file's mode, so a script stays runnable."""
    import io
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ReleaseError("The download is not a ZIP archive: %s." % exc)
    base = into.resolve()
    with archive:
        for info in archive.infolist():
            name = info.filename
            parts = Path(name).parts
            if name.startswith(("/", "\\")) or ".." in parts or ":" in name or not parts:
                raise ReleaseError("The archive holds a path that leads outside it: %s." % name)
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ReleaseError("The archive holds a link, %s; a Garrick release has none." % name)
            target = base.joinpath(*parts)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            os.chmod(target, (mode & 0o777) or 0o644)
    tops = [p for p in base.iterdir() if p.is_dir()]
    if len(tops) != 1 or not ((tops[0] / "install.py").is_file() and (tops[0] / "update.py").is_file()):
        raise ReleaseError("The download does not hold a Garrick: no install.py and update.py in one folder.")
    return tops[0]


def latest_tag(root: Path) -> str:
    cache = ask(root)
    if cache.get("failed") or not cache.get("latest"):
        raise ReleaseError("GitHub could not be asked for the newest release (%s). Try again later, or name one "
                           "with --tag." % (cache.get("failed") or "no answer"))
    return cache["latest"]


def ahead_of_release(root: Path) -> bool:
    """Whether the workspace came from main after its release: its copy of
    the release notes has lines waiting under Unreleased."""
    try:
        text = root.joinpath(*CHANGELOG_COPY).read_text(encoding="utf-8")
    except OSError:
        return False
    waiting = re.split(r"(?m)^## ", text)
    return any(part.lower().startswith("[unreleased]") and re.search(r"(?m)^- ", part) for part in waiting)


def update(root: Path, tag: str = "", apply: bool = False, only: str = "", as_json: bool = False,
           split: bool = False) -> int:
    """Download the release `tag`, the newest when empty, and run its update
    on this workspace, or with `split` its split of the instruction files.
    Returns the update's exit code. Never a release older than the workspace
    runs, which would take its files back."""
    named = bool(tag)
    tag = tag or latest_tag(root)
    if not TAG.match(tag):
        raise ReleaseError("%s is not a release tag, such as v0.16.0." % tag)
    current = workspace_release(root)
    if current and release_key(tag) is not None:
        older, same = release_key(tag) < release_key(current), release_key(tag) == release_key(current)
        if older or (same and ahead_of_release(root)):
            raise ReleaseError("This workspace runs %s%s, so %s would take it back. Update from a newer Garrick." % (
                current, " and changes from main after it" if same else "", tag))
        if same and not named and not split:
            print("Up to date: Garrick %s is the newest release, and this workspace runs it." % current)
            return 0
    repo = release_repository(root)
    url = ARCHIVE % (repo, tag)
    tmp = Path(tempfile.mkdtemp(prefix="garrick-%s-" % tag)).resolve()
    try:
        if tmp == root or root in tmp.parents:
            raise ReleaseError("The temporary folder, %s, is inside the workspace; set TMPDIR to a folder "
                               "outside it." % tmp)
        if not as_json:
            print("Downloading Garrick %s from %s ..." % (tag, url), flush=True)
        try:
            data = fetch(url, root, DOWNLOAD_TIMEOUT, limit=MAX_ARCHIVE, say=None if as_json else print)
        except (OSError, urllib.error.URLError) as exc:
            raise ReleaseError("The download failed: %s." % (getattr(exc, "reason", None) or exc))
        source = unpack(data, tmp)
        cmd = [sys.executable, str(source / "install.py"), "--update", str(root)]
        cmd += ["--apply"] if apply else []
        cmd += ["--only", only] if only else []
        cmd += ["--json"] if as_json else []
        cmd += ["--split"] if split else []
        return subprocess.run(cmd, cwd=str(tmp)).returncode
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------- main


def say_latest(root: Path) -> str:
    cache = read_cache(root)
    newer = say_newer_release(root)
    if newer:
        return newer
    if cache.get("latest") and cache.get("repository") == release_repository(root):
        return "Up to date: the newest Garrick is %s, and this workspace runs %s." % (
            str(cache["latest"]).lstrip("v"), workspace_release(root) or "a release it does not record")
    if cache.get("failed"):
        return "GitHub could not be asked: %s." % cache["failed"]
    return "Not asked yet."


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Whether a newer Garrick is out, and the update to it.")
    ap.add_argument("--root", help="the workspace (default: the one this script sits in)")
    sub = ap.add_subparsers(dest="command")
    lt = sub.add_parser("latest", help="the newest release, asking GitHub at most once a day")
    lt.add_argument("--now", action="store_true", help="ask now, however recently it asked")
    lt.add_argument("--background", action="store_true",
                    help="for the status page: only with the release notice switched on and due, and silent")
    up = sub.add_parser("update", help="download a release and run its update on this workspace")
    up.add_argument("--tag", default="", help="the release, such as v0.16.0 (default: the newest)")
    up.add_argument("--apply", action="store_true", help="make the changes; without it, only say what they would be")
    up.add_argument("--only", default="", help="comma-separated paths, as the report lists them")
    up.add_argument("--json", action="store_true", help="the update's report as JSON")
    up.add_argument("--split", action="store_true",
                    help="move your own text out of Garrick's instruction files, into the local file beside each")
    args = ap.parse_args(argv)
    try:
        root = workspace_root(Path(args.root).expanduser() if args.root else HERE)
    except FileNotFoundError as exc:
        print("release: %s" % exc, file=sys.stderr)
        return 2
    root = root.resolve()
    if args.command == "latest":
        if args.background:
            if release_due(root):
                ask(root)
            return 0
        if args.now or not release_asked_lately(root):
            ask(root)
        print(say_latest(root))
        return 0
    if args.command == "update":
        try:
            return update(root, args.tag, args.apply, args.only, args.json, args.split)
        except ReleaseError as exc:
            print(exc, file=sys.stderr)
            return 1
    ap.print_help()
    return 64


if __name__ == "__main__":
    sys.exit(main())
