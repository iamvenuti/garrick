#!/usr/bin/env python3
"""setup_runtime.py: make the interpreter and the packages that the remote access service runs on (preview).

The service needs a newer Python and third-party packages than the Python that macOS ships and the standard library the rest of
Garrick keeps to. So the extra carries its own, pinned twice:

* the interpreter: one python-build-standalone build, its address and its SHA-256 in `runtime.json`. The download is hashed
  **before** it is unpacked. A hash that does not match stops here and nothing is unpacked.
* the packages: `requirements.lock`, with a hash for every file, installed with `--require-hashes --only-binary :all: --no-deps`.
  A package whose hash is not in the lock, or is not a wheel, is refused by pip, and the install stops.

It builds in a staging folder and moves the result into place only when the packages import. A stop at any point removes the staging
folder and leaves what was there before: the service starts only from a runtime that holds `ready.json`, which is written last.

    /usr/bin/python3 setup_runtime.py [--workspace PATH]   make the runtime in the state folder

Runs on the Python that macOS ships (3.9). Standard library only. A test passes a local file for `fetch` and a fake interpreter,
and never uses the network.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, Optional

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
STAGING = "runtime.staging"
PIP_FLAGS = ("--require-hashes", "--only-binary", ":all:", "--no-deps", "--disable-pip-version-check", "--no-input")
MAX_DOWNLOAD = 200 * 1024 * 1024


class SetupError(Exception):
    """A stop, worded for the owner."""


def _state():
    import importlib.util
    key = "garrick_remote_state"
    mod = sys.modules.get(key)
    if mod is None:
        spec = importlib.util.spec_from_file_location(key, str(HERE / "state.py"))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[key] = mod
        spec.loader.exec_module(mod)
    return mod


def arch() -> str:
    return "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x86_64"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(str(path), "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def download(url: str, dest: Path) -> None:
    """Fetch an address into a file. Only https; at most 200 MB."""
    if not url.startswith("https://"):
        raise SetupError("The download address is not a secure one, so nothing was fetched.")
    total = 0
    req = urllib.request.Request(url, headers={"User-Agent": "garrick-remote-setup"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(str(dest), "wb") as out:      # noqa: S310 (https only, above)
        for block in iter(lambda: resp.read(1 << 20), b""):
            total += len(block)
            if total > MAX_DOWNLOAD:
                raise SetupError("The download was larger than expected, so it was stopped.")
            out.write(block)


def safe_unpack(archive: Path, into: Path) -> None:
    """Unpack a tar file, refusing any member that would land outside `into`, any link that points outside it, and any special file."""
    root = os.path.realpath(str(into))
    with tarfile.open(str(archive), "r:*") as tar:
        members = tar.getmembers()
        links = []
        for m in members:
            name = os.path.normpath(m.name)
            if ".." in m.name.split("/") or ".." in (m.linkname or "").split("/") and m.islnk():
                raise SetupError("The download holds a name with .. in it, so nothing was unpacked.")
            if any(name == l or name.startswith(l + os.sep) for l in links):
                raise SetupError("The download holds a file that goes through a link, so nothing was unpacked.")
            if m.issym() or m.islnk():
                links.append(name)
            target = os.path.realpath(os.path.join(root, m.name))
            if not (target == root or target.startswith(root + os.sep)):
                raise SetupError("The download holds a file outside its folder, so nothing was unpacked.")
            if m.issym() or m.islnk():
                base = os.path.dirname(target) if m.issym() else root
                link = os.path.realpath(os.path.join(base, m.linkname))
                if not (link == root or link.startswith(root + os.sep)):
                    raise SetupError("The download holds a link that leaves its folder, so nothing was unpacked.")
            elif not (m.isfile() or m.isdir()):
                raise SetupError("The download holds a file of a kind that is not allowed, so nothing was unpacked.")
        if hasattr(tarfile, "data_filter"):
            tar.extractall(str(into), members=members, filter="data")
        else:
            tar.extractall(str(into), members=members)


def lock_text() -> str:
    return (HERE / "requirements.lock").read_text(encoding="utf-8")


def lock_ok(text: str) -> bool:
    """Every requirement in the lock is pinned with `==` and carries at least one hash."""
    blocks = []
    for line in text.splitlines():
        if line and not line[0].isspace() and not line.startswith("#"):
            blocks.append(line)
        elif line.strip().startswith("--hash=") and blocks:
            blocks[-1] += " " + line.strip()
    return bool(blocks) and all("==" in b.split()[0] and "--hash=sha256:" in b for b in blocks)


def setup(home: Path, fetch: Callable[[str, Path], None] = download, runner: Callable = subprocess.run,
          runtime: Optional[Dict[str, Any]] = None, lock: Optional[Path] = None, say: Callable[[str], None] = lambda s: None) -> Path:
    """Make `<home>/runtime/` from the pinned interpreter and the lock. Returns its interpreter. Raises SetupError."""
    spec = runtime if runtime is not None else json.loads((HERE / "runtime.json").read_text(encoding="utf-8"))
    asset = (spec.get("assets") or {}).get(arch())
    lockfile = lock or (HERE / "requirements.lock")
    if not asset or not asset.get("url") or len(str(asset.get("sha256") or "")) != 64:
        raise SetupError("This Mac's kind of processor has no pinned runtime, so nothing was installed.")
    if not lock_ok(lockfile.read_text(encoding="utf-8")):
        raise SetupError("The package list is not fully pinned with hashes, so nothing was installed.")
    st = _state()
    folder = st.ensure_home()
    staging = folder / STAGING
    if staging.exists():
        shutil.rmtree(str(staging))
    staging.mkdir(mode=0o700)
    try:
        archive = staging / "python.tar.gz"
        say("Downloading the service's interpreter.")
        fetch(asset["url"], archive)
        if sha256_of(archive) != str(asset["sha256"]).lower():
            raise SetupError("The download does not match its pinned checksum, so it was not unpacked and nothing was installed.")
        say("Unpacking it.")
        safe_unpack(archive, staging)
        archive.unlink()
        python = staging / "python" / "bin" / "python3"
        if not python.is_file():
            raise SetupError("The download did not hold an interpreter, so nothing was installed.")
        say("Installing the packages from the pinned list.")
        r = runner([str(python), "-m", "pip", "install", *PIP_FLAGS, "-r", str(lockfile)],
                   capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=900)
        if r.returncode != 0:
            raise SetupError("A package did not match its pinned checksum or could not be fetched, so nothing was installed.")
        check = runner([str(python), "-c", "import mcp, uvicorn, starlette"], capture_output=True, text=True,
                       stdin=subprocess.DEVNULL, timeout=120)
        if check.returncode != 0:
            raise SetupError("The packages did not load, so nothing was installed.")
        (staging / "ready.json").write_text(json.dumps({"ok": True, "python": spec.get("python"), "lock": sha256_of(lockfile)}) + "\n",
                                            encoding="utf-8")
        final = folder / st.RUNTIME_DIR
        old = folder / (st.RUNTIME_DIR + ".old")
        if old.exists():
            shutil.rmtree(str(old))
        if final.exists():
            os.replace(str(final), str(old))
        try:
            os.replace(str(staging), str(final))
        except OSError:
            if old.exists() and not final.exists():
                os.replace(str(old), str(final))                     # put the runtime that worked back
            raise SetupError("The new software could not be put in place, so the old one was kept.") from None
        if old.exists():
            shutil.rmtree(str(old), ignore_errors=True)
        return final / "python" / "bin" / "python3"
    except BaseException:
        shutil.rmtree(str(staging), ignore_errors=True)
        raise


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Make the runtime of the remote access service.")
    parser.add_argument("--workspace", default="")
    parser.add_argument("--then-start", action="store_true", help="start the service at login once the runtime is ready")
    args = parser.parse_args(argv)
    st = _state()

    def note(state: str, text: str) -> None:
        st.write_json(st.SETUP_FILE, {"state": state, "say": text})

    try:
        note("running", "Setting up the service software. This takes a few minutes.")
        python = setup(st.home(), say=lambda s: note("running", s))
    except SetupError as exc:
        note("failed", str(exc))
        print(str(exc))
        return 1
    except Exception:
        note("failed", "The service software could not be set up. Turn remote access off and on to try again.")
        print("Setup stopped.")
        return 1
    note("done", "The service software is installed.")
    if args.then_start and args.workspace:
        try:
            act = _state().sibling("settings_actions")
            act.start_if_on(Path(args.workspace))
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
