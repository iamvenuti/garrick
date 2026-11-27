"""Remote access (preview): the pinned interpreter and the locked packages (#695).

    cd tests && python3 -m unittest test_remote_runtime

The runtime installs only from the lock. A download whose checksum differs is not unpacked; a package set that pip refuses leaves nothing
the service could start from. No test fetches anything: `fetch` copies a local file, and the interpreter in the fake download is a
shell script that records what it was asked.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "extras" / "remote" / "tests"))

from remote_fixture import EXTRA, RemoteCase, mod  # noqa: E402

FAKE_PYTHON = """#!/bin/sh
echo "$@" >> "$(dirname "$0")/../../calls.log"
case "$*" in
  *"-m pip"*) [ -f "$(dirname "$0")/../../refuse" ] && exit 1; exit 0;;
  *"import mcp"*) [ -f "$(dirname "$0")/../../broken" ] && exit 1; exit 0;;
esac
exit 0
"""


def make_archive(path: Path, refuse: bool = False, broken: bool = False, evil: str = "") -> str:
    """A tar.gz of a `python/bin/python3` that is a script; returns its sha256."""
    with tarfile.open(str(path), "w:gz") as tar:
        def add(name, data, mode=0o755):
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), mode
            tar.addfile(info, io.BytesIO(data))
        add("python/bin/python3", FAKE_PYTHON.encode())
        if refuse:
            add("refuse", b"")
        if broken:
            add("broken", b"")
        if evil:
            add(evil, b"x")
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Runtime(RemoteCase):
    def setUp(self):
        super().setUp()
        self.setup = mod("setup_runtime")
        self.archive = Path(self._tmp.name) / "a.tar.gz"
        self.spec = {"python": "3.12.0", "assets": {a: {"url": "https://example.test/p.tar.gz", "sha256": "0" * 64}
                                                      for a in ("arm64", "x86_64")}}
        self.fetched = []

    def fetch(self, url, dest):
        self.fetched.append(url)
        dest.write_bytes(self.archive.read_bytes())

    def run_setup(self, sha=None):
        digest = sha or hashlib.sha256(self.archive.read_bytes()).hexdigest()
        for a in self.spec["assets"].values():
            a["sha256"] = digest
        return self.setup.setup(self.state.home(), fetch=self.fetch, runtime=self.spec)

    def runtime_folder(self):
        return self.state.home() / "runtime"

    def test_installs_into_the_state_folder_and_writes_the_ready_note_last(self):
        make_archive(self.archive)
        py = self.run_setup()
        self.assertEqual(py, self.runtime_folder() / "python" / "bin" / "python3")
        self.assertTrue((self.runtime_folder() / "ready.json").is_file())
        self.assertIsNotNone(self.state.runtime_python())
        self.assertFalse((self.state.home() / "runtime.staging").exists())

    def test_pip_is_asked_for_hashes_and_wheels_only(self):
        make_archive(self.archive)
        self.run_setup()
        calls = (self.runtime_folder() / "calls.log").read_text()
        line = [l for l in calls.splitlines() if "-m pip" in l][0]
        for flag in ("--require-hashes", "--only-binary :all:", "--no-deps", "-r"):
            self.assertIn(flag, line)
        self.assertIn("requirements.lock", line)

    def test_a_checksum_that_differs_stops_before_anything_is_unpacked(self):
        make_archive(self.archive)
        with self.assertRaises(self.setup.SetupError):
            self.run_setup(sha="1" * 64)
        self.assertFalse(self.runtime_folder().exists())
        self.assertFalse((self.state.home() / "runtime.staging").exists())
        self.assertIsNone(self.state.runtime_python())

    def test_a_package_pip_refuses_leaves_nothing_to_start_from(self):
        make_archive(self.archive, refuse=True)
        with self.assertRaises(self.setup.SetupError):
            self.run_setup()
        self.assertIsNone(self.state.runtime_python())
        self.assertFalse(self.runtime_folder().exists())

    def test_a_failed_reinstall_keeps_the_runtime_that_worked(self):
        make_archive(self.archive)
        self.run_setup()
        make_archive(self.archive, broken=True)
        with self.assertRaises(self.setup.SetupError):
            self.run_setup()
        self.assertIsNotNone(self.state.runtime_python())

    def test_packages_that_do_not_load_stop_the_install(self):
        make_archive(self.archive, broken=True)
        with self.assertRaises(self.setup.SetupError):
            self.run_setup()
        self.assertIsNone(self.state.runtime_python())

    def test_an_archive_that_reaches_outside_its_folder_is_refused(self):
        make_archive(self.archive, evil="../escaped")
        with self.assertRaises(self.setup.SetupError):
            self.run_setup()
        self.assertFalse((self.state.home() / "escaped").exists())
        self.assertFalse((self.state.home().parent / "escaped").exists())

    def test_a_link_that_leaves_the_folder_is_refused(self):
        with tarfile.open(str(self.archive), "w:gz") as tar:
            info = tarfile.TarInfo("python/link")
            info.type, info.linkname = tarfile.SYMTYPE, "/etc/passwd"
            tar.addfile(info)
        with self.assertRaises(self.setup.SetupError):
            self.run_setup()

    def test_a_swap_that_fails_puts_the_old_runtime_back(self):
        make_archive(self.archive)
        self.run_setup()
        before = (self.runtime_folder() / "ready.json").read_text()
        real = os.replace
        calls = []

        def flaky(src, dst):
            calls.append((Path(src).name, Path(dst).name))
            if Path(src).name == "runtime.staging" and Path(dst).name == "runtime":
                raise OSError("killed")
            return real(src, dst)
        from unittest import mock
        with mock.patch.object(os, "replace", flaky), self.assertRaises(self.setup.SetupError):
            self.run_setup()
        self.assertEqual((self.runtime_folder() / "ready.json").read_text(), before)
        self.assertFalse((self.state.home() / "runtime.old").exists())

    def test_a_name_with_dots_or_a_path_through_a_link_is_refused(self):
        for evil in ("python/../x", "../x"):
            make_archive(self.archive, evil=evil)
            with self.assertRaises(self.setup.SetupError):
                self.run_setup()
        with tarfile.open(str(self.archive), "w:gz") as tar:
            link = tarfile.TarInfo("python/lib")
            link.type, link.linkname = tarfile.SYMTYPE, "inside"
            tar.addfile(link)
            inner = tarfile.TarInfo("python/lib/file")
            inner.size = 1
            tar.addfile(inner, io.BytesIO(b"x"))
        with self.assertRaises(self.setup.SetupError):
            self.run_setup()

    def test_the_data_filter_is_used_where_tarfile_has_it(self):
        src = (EXTRA / "setup_runtime.py").read_text()
        self.assertIn('filter="data"', src)

    def test_a_plain_http_address_is_never_fetched(self):
        with self.assertRaises(self.setup.SetupError):
            self.setup.download("http://example.test/x", Path(self._tmp.name) / "x")

    def test_a_lock_without_a_hash_is_refused_before_any_download(self):
        bad = Path(self._tmp.name) / "bad.lock"
        bad.write_text("mcp==2.3.0 \\\n    --hash=sha256:" + "a" * 64 + "\nanyio>=4\n", encoding="utf-8")
        make_archive(self.archive)
        with self.assertRaises(self.setup.SetupError):
            self.setup.setup(self.state.home(), fetch=self.fetch, runtime=self.spec, lock=bad)
        self.assertEqual(self.fetched, [])


class Pins(unittest.TestCase):
    """The files the install is made from."""

    def test_runtime_json_pins_both_processors_by_checksum(self):
        spec = json.loads((EXTRA / "runtime.json").read_text())
        for arch in ("arm64", "x86_64"):
            asset = spec["assets"][arch]
            self.assertTrue(asset["url"].startswith("https://"))
            self.assertRegex(asset["sha256"], r"^[0-9a-f]{64}$")
            self.assertIn("3.12.13", asset["url"])
        self.assertNotEqual(spec["assets"]["arm64"]["sha256"], spec["assets"]["x86_64"]["sha256"])

    def test_the_lock_pins_every_package_with_hashes(self):
        text = (EXTRA / "requirements.lock").read_text()
        self.assertTrue(mod("setup_runtime").lock_ok(text))
        self.assertIn("mcp==2.3.0", text)
        names = re.findall(r"^([a-z0-9_.-]+)==", text, re.M)
        self.assertGreaterEqual(len(names), 20)
        self.assertEqual((EXTRA / "requirements.in").read_text().split(), ["mcp==2.3.0"])

    def test_the_lock_check_catches_an_unpinned_or_unhashed_line(self):
        ok = mod("setup_runtime").lock_ok
        self.assertFalse(ok(""))
        self.assertFalse(ok("mcp>=2\n"))
        self.assertFalse(ok("mcp==2.3.0\n"))
        self.assertTrue(ok("mcp==2.3.0 \\\n    --hash=sha256:" + "a" * 64 + "\n"))

    def test_the_lock_is_for_wheels_alone(self):
        text = (EXTRA / "requirements.lock").read_text()
        self.assertNotIn("git+", text)
        self.assertNotRegex(text, r"\.tar\.gz|\.zip")


if __name__ == "__main__":
    unittest.main()
