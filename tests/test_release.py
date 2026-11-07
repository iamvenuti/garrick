"""The release notice and the one-step update: System/tools/release.py, the
helpers in garrick_lib.py, `check.py --version` and the status page's line.

    python3 -m unittest discover -s tests

No test reaches the network: urllib's urlopen is replaced by a fake that
records each request and answers from the test.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import build_workspace, write  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "template" / "System" / "tools"
STATUS = REPO / "extras" / "status" / "status.py"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release = load("garrick_release", TOOLS / "release.py")
status = load("garrick_status_for_release", STATUS)

CHANGELOG = "# Changelog\n\n## [Unreleased]\n\n## [0.15.2] - 2026-10-10\n\nNotes.\n\n## [0.15.1] - 2026-10-09\n"


class Reply:
    def __init__(self, data):
        self.data = data

    def read(self, n=-1):
        return self.data if n < 0 else self.data[:n]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeNet:
    """Stands in for urllib.request.urlopen: answers by URL, records requests."""

    def __init__(self, answers=None, fail=None):
        self.answers = answers or {}
        self.fail = fail
        self.requests = []

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        if self.fail:
            raise self.fail
        for prefix, data in self.answers.items():
            if req.full_url.startswith(prefix):
                return Reply(data)
        raise urllib.error.URLError("no answer for %s" % req.full_url)


def latest(tag="v0.16.0"):
    return json.dumps({"tag_name": tag, "html_url": "https://github.com/iamvenuti/garrick/releases/tag/" + tag,
                       "published_at": "2026-11-02T10:00:00Z", "body": "notes"}).encode()


class ReleaseCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name).resolve()
        self.root = build_workspace(self.base / "Workspace")
        tools = self.root / "System" / "tools"
        tools.mkdir(parents=True, exist_ok=True)
        for name in ("garrick_lib.py", "check.py", "release.py"):
            shutil.copy(TOOLS / name, tools / name)
        write(self.root / "System" / "garrick-changelog.md", CHANGELOG)
        self.lib = load("garrick_lib_for_release", tools / "garrick_lib.py")
        agents = mock.patch.object(status, "launch_agents", lambda: self.base / "LaunchAgents")
        agents.start()
        self.addCleanup(agents.stop)
        self.addCleanup(self._tmp.cleanup)

    def setting(self, on=True, **more):
        write(self.root / "System" / "garrick-settings.json", json.dumps(dict({"release-notice": on}, **more)))

    def cache(self, latest_tag="v0.16.0", asked=None, repository="iamvenuti/garrick", **more):
        asked = asked or dt.datetime.now()
        data = dict({"repository": repository, "asked": asked.isoformat(timespec="seconds"), "latest": latest_tag,
                     "url": "https://github.com/iamvenuti/garrick/releases/tag/" + latest_tag}, **more)
        write(self.root / "System" / "generated" / "garrick-release.json", json.dumps(data))

    def read_cache(self):
        return json.loads((self.root / "System" / "generated" / "garrick-release.json").read_text())

    def net(self, **kw):
        fake = FakeNet(**kw)
        patch = mock.patch.object(release.urllib.request, "urlopen", fake)
        patch.start()
        self.addCleanup(patch.stop)
        return fake

    def run_release(self, *args):
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            code = release.main(["--root", str(self.root)] + list(args))
        return code, out.getvalue()

    def page(self):
        return status.build(self.root, now=dt.datetime.now(), folder=self.base / "jobs")

    def version(self):
        r = subprocess.run([sys.executable, str(self.root / "System" / "tools" / "check.py"), "--root", str(self.root),
                            "--version"], capture_output=True, text=True)
        self.assertEqual(0, r.returncode, r.stderr)
        return r.stdout


class TestTheSetting(ReleaseCase):
    def test_off_by_default_asks_nothing_and_shows_nothing(self):
        fake = self.net(answers={"https://api.github.com": latest()})
        self.assertFalse(self.lib.release_notice_on(self.root))
        self.assertEqual((0, ""), self.run_release("latest", "--background"))
        self.assertEqual([], fake.requests)
        self.assertFalse((self.root / "System" / "generated" / "garrick-release.json").exists())
        self.cache()                                   # an answer kept from before, with the notice switched off
        self.assertNotRegex(self.page(), r"Garrick \d[\d.]* is out")

    def test_only_true_switches_it_on(self):
        for value in ("yes", 1, "true", None):
            self.setting(value)
            self.assertFalse(self.lib.release_notice_on(self.root), value)
        self.setting(True)
        self.assertTrue(self.lib.release_notice_on(self.root))

    def test_a_fork_names_its_own_repository(self):
        self.setting(True, **{"release-repository": "birch-co/garrick"})
        self.assertEqual("birch-co/garrick", self.lib.release_repository(self.root))
        fake = self.net(answers={"https://api.github.com/repos/birch-co/garrick/releases/latest": latest()})
        self.run_release("latest", "--background")
        self.assertEqual(1, len(fake.requests))
        self.setting(True, **{"release-repository": "../../elsewhere"})
        self.assertEqual("iamvenuti/garrick", self.lib.release_repository(self.root))


class TestAsking(ReleaseCase):
    def test_on_and_due_asks_once_with_nothing_but_a_user_agent(self):
        self.setting()
        fake = self.net(answers={"https://api.github.com": latest()})
        self.assertEqual((0, ""), self.run_release("latest", "--background"))
        self.assertEqual(1, len(fake.requests))
        req = fake.requests[0]
        self.assertEqual("https://api.github.com/repos/iamvenuti/garrick/releases/latest", req.full_url)
        self.assertEqual("GET", req.get_method())
        self.assertIsNone(req.data)
        self.assertEqual({"User-agent": "Garrick/0.15.2", "Accept": "application/vnd.github+json"}, dict(req.header_items()))
        cache = self.read_cache()
        self.assertEqual("v0.16.0", cache["latest"])
        self.assertNotIn("failed", cache)
        self.run_release("latest", "--background")      # asked a moment ago: not again
        self.assertEqual(1, len(fake.requests))

    def test_an_answer_within_a_day_is_not_asked_again(self):
        self.setting()
        self.cache(asked=dt.datetime.now() - dt.timedelta(hours=20))
        fake = self.net(answers={"https://api.github.com": latest("v0.17.0")})
        self.run_release("latest", "--background")
        self.run_release("latest")                       # by hand, too, within the day
        self.assertEqual([], fake.requests)
        self.cache(asked=dt.datetime.now() - dt.timedelta(hours=25))
        self.run_release("latest", "--background")
        self.assertEqual(1, len(fake.requests))
        self.assertEqual("v0.17.0", self.read_cache()["latest"])

    def test_now_asks_whatever_the_cache_says(self):
        self.cache()
        fake = self.net(answers={"https://api.github.com": latest("v0.16.1")})
        code, out = self.run_release("latest", "--now")
        self.assertEqual(1, len(fake.requests))
        self.assertIn("Garrick 0.16.1 is out; this workspace runs 0.15.2.", out)

    def test_a_network_failure_is_silent_and_keeps_the_last_answer(self):
        self.setting()
        self.cache(latest_tag="v0.15.2", asked=dt.datetime.now() - dt.timedelta(days=3))
        fake = self.net(fail=urllib.error.URLError("offline"))
        self.assertEqual((0, ""), self.run_release("latest", "--background"))
        self.assertEqual(1, len(fake.requests))
        cache = self.read_cache()
        self.assertEqual("v0.15.2", cache["latest"])
        self.assertIn("offline", cache["failed"])
        html = self.page()
        self.assertNotRegex(html, r"Garrick \d[\d.]* is out")
        self.assertNotIn('id="attention"', html)          # nothing to attend to: no red, no amber
        self.run_release("latest", "--background")         # and not asked again the same day
        self.assertEqual(1, len(fake.requests))

    def test_a_garbled_answer_is_a_failure_too(self):
        self.setting()
        self.net(answers={"https://api.github.com": b"<html>rate limited</html>"})
        self.assertEqual((0, ""), self.run_release("latest", "--background"))
        self.assertIn("failed", self.read_cache())
        self.assertEqual("", self.lib.say_newer_release(self.root))


class TestWhereItShows(ReleaseCase):
    def test_a_newer_release_shows_on_the_page_and_in_version(self):
        self.setting()
        self.cache("v0.16.0")
        html = self.page()
        self.assertIn("Garrick 0.16.0 is out; this workspace runs 0.15.2. To update: "
                      "python3 System/tools/release.py update", html)
        self.assertIn('<a href="https://github.com/iamvenuti/garrick/releases/tag/v0.16.0" target="_blank" '
                      'rel="noopener">', html)
        self.assertIn('id="attention"', html)
        out = self.version()
        self.assertIn("Garrick 0.16.0 is out; this workspace runs 0.15.2.", out)
        self.assertIn("python3 System/tools/release.py update", out)

    def test_the_same_or_an_older_release_shows_nothing(self):
        self.setting()
        for tag in ("v0.15.2", "v0.15.1", "v0.15.2-rc1"):
            self.cache(tag)
            self.assertNotRegex(self.page(), r"Garrick \d[\d.]* is out", tag)
            self.assertNotIn("is out", self.version(), tag)

    def test_a_workspace_ahead_on_main_is_not_told_of_the_release_it_has(self):
        self.setting()
        write(self.root / "System" / "garrick-changelog.md",
              CHANGELOG.replace("## [Unreleased]\n", "## [Unreleased]\n\n### Added\n\n- Something new.\n"))
        self.cache("v0.15.2")
        self.assertEqual("", self.lib.say_newer_release(self.root))

    def test_an_answer_about_another_repository_is_ignored(self):
        self.setting()
        self.cache("v0.16.0", repository="birch-co/garrick")
        self.assertIsNone(self.lib.newer_release(self.root))
        self.assertTrue(self.lib.release_due(self.root))

    def test_version_never_asks(self):
        self.setting()
        for tool in ("check.py", "garrick_lib.py"):
            text = (TOOLS / tool).read_text()
            for word in ("urllib.request", "urlopen", "http.client", "socket"):
                self.assertNotIn(word, text, tool)
        self.assertNotIn("is out", self.version())


class TestThePageAsksInTheBackground(ReleaseCase):
    def detach(self):
        """Popen replaced for release.py alone, so git and the check still run."""
        real, calls = subprocess.Popen, mock.Mock()

        def popen(cmd, *args, **kw):
            if any(str(c).endswith("release.py") for c in cmd):
                return calls(cmd, *args, **kw)
            return real(cmd, *args, **kw)
        return mock.patch.object(status.subprocess, "Popen", popen), calls

    def started(self):
        patch, calls = self.detach()
        with patch:
            status.release_ask(self.root)
        return calls

    def test_off_starts_nothing(self):
        self.assertFalse(self.started().called)

    def test_on_and_due_starts_one_detached_question(self):
        self.setting()
        popen = self.started()
        self.assertEqual(1, popen.call_count)
        cmd, kw = popen.call_args[0][0], popen.call_args[1]
        self.assertEqual([str(self.root / "System" / "tools" / "release.py"), "--root", str(self.root), "latest",
                          "--background"], cmd[1:])
        self.assertTrue(kw["start_new_session"])
        self.assertEqual(subprocess.DEVNULL, kw["stdout"])

    def test_asked_within_a_day_starts_nothing(self):
        self.setting()
        self.cache(asked=dt.datetime.now() - dt.timedelta(hours=2))
        self.assertFalse(self.started().called)

    def test_a_workspace_without_release_py_starts_nothing(self):
        self.setting()
        (self.root / "System" / "tools" / "release.py").unlink()
        self.assertFalse(self.started().called)

    def test_main_builds_then_asks(self):
        self.setting()
        patch, calls = self.detach()
        with patch, mock.patch("sys.stdout", io.StringIO()), mock.patch.object(status, "launchers_installed", lambda: ()):
            status.main(["--workspace", str(self.root), "--no-graph", "--no-obsidian"])
        self.assertTrue((self.root / "System" / "generated" / "status.html").is_file())
        self.assertEqual(1, calls.call_count)


def archive(files, top="garrick-0.16.0", links=()):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(top + "/", "")
        for name, (text, mode) in files.items():
            info = zipfile.ZipInfo(top + "/" + name)
            info.external_attr = (stat.S_IFREG | mode) << 16
            z.writestr(info, text)
        for name in links:
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(info, "/etc/passwd")
    return buf.getvalue()


# A stand-in Garrick: its install.py records how it was run, where the test can read it.
FAKE_INSTALL = """import json, os, sys
open(os.environ["GARRICK_TEST_RECORD"], "w").write(json.dumps({"argv": sys.argv[1:], "here": os.path.dirname(os.path.abspath(__file__))}))
"""


class TestTheDownload(ReleaseCase):
    def setUp(self):
        super().setUp()
        self.record = self.base / "record.json"
        env = mock.patch.dict(os.environ, {"GARRICK_TEST_RECORD": str(self.record)})
        env.start()
        self.addCleanup(env.stop)
        self.zip = archive({"install.py": (FAKE_INSTALL, 0o644), "update.py": ("", 0o644),
                            "extras/status/app/make-app.sh": ("#!/bin/sh\n", 0o755)})

    def test_update_downloads_the_newest_release_and_runs_its_update_report_first(self):
        fake = self.net(answers={"https://api.github.com": latest(),
                                 "https://github.com/iamvenuti/garrick/archive/refs/tags/v0.16.0.zip": self.zip})
        with mock.patch("sys.stdout", io.StringIO()):
            self.assertEqual(0, release.update(self.root))
        self.assertEqual(["https://api.github.com/repos/iamvenuti/garrick/releases/latest",
                          "https://github.com/iamvenuti/garrick/archive/refs/tags/v0.16.0.zip"],
                         [r.full_url for r in fake.requests])
        ran = json.loads(self.record.read_text())
        self.assertEqual(["--update", str(self.root)], ran["argv"])          # a report: no --apply
        here = Path(ran["here"])
        self.assertNotIn(self.root, here.parents)
        self.assertFalse(here.exists())                                     # the download is removed afterwards

    def test_apply_and_only_reach_the_update(self):
        self.net(answers={"https://github.com/iamvenuti/garrick/archive/refs/tags/v0.15.9.zip": self.zip})
        with mock.patch("sys.stdout", io.StringIO()):
            release.update(self.root, tag="v0.15.9", apply=True, only="System/tools/check.py")
        self.assertEqual(["--update", str(self.root), "--apply", "--only", "System/tools/check.py"],
                         json.loads(self.record.read_text())["argv"])

    def test_split_reaches_the_update_even_on_the_release_the_workspace_runs(self):
        self.net(answers={"https://api.github.com": latest("v0.15.2"),
                          "https://github.com/iamvenuti/garrick/archive/refs/tags/v0.15.2.zip": self.zip})
        with mock.patch("sys.stdout", io.StringIO()):
            self.assertEqual(0, release.main(["--root", str(self.root), "update", "--split"]))
        self.assertEqual(["--update", str(self.root), "--split"], json.loads(self.record.read_text())["argv"])

    def test_the_release_the_workspace_runs_is_not_downloaded_again(self):
        fake = self.net(answers={"https://api.github.com": latest("v0.15.2")})
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            self.assertEqual(0, release.update(self.root))
        self.assertIn("Up to date", out.getvalue())
        self.assertEqual(1, len(fake.requests))                             # the question, no download
        self.assertFalse(self.record.exists())

    def test_an_older_release_is_refused(self):
        fake = self.net()
        with self.assertRaises(release.ReleaseError) as caught:
            release.update(self.root, tag="v0.15.1")
        self.assertIn("would take it back", str(caught.exception))
        write(self.root / "System" / "garrick-changelog.md",
              CHANGELOG.replace("## [Unreleased]\n", "## [Unreleased]\n\n### Added\n\n- Something new.\n"))
        with self.assertRaises(release.ReleaseError):
            release.update(self.root, tag="v0.15.2")                         # main after 0.15.2: 0.15.2 is older
        self.assertEqual([], fake.requests)

    def test_a_bad_tag_is_refused_before_anything_is_fetched(self):
        fake = self.net()
        with self.assertRaises(release.ReleaseError):
            release.update(self.root, tag="main; rm -rf ~")
        self.assertEqual([], fake.requests)

    def test_a_failed_question_stops_the_update(self):
        self.net(fail=urllib.error.URLError("offline"))
        code = None
        err = io.StringIO()
        with mock.patch("sys.stderr", err), mock.patch("sys.stdout", io.StringIO()):
            code = release.main(["--root", str(self.root), "update"])
        self.assertEqual(1, code)
        self.assertIn("could not be asked", err.getvalue())
        self.assertFalse(self.record.exists())

    def test_a_python_without_certificates_downloads_through_curl_and_says_so(self):
        import ssl
        self.net(fail=urllib.error.URLError(ssl.SSLCertVerificationError("unable to get local issuer certificate")))
        calls = []

        def curl(cmd, **kw):
            calls.append(cmd)
            url = cmd[-1]
            out = latest() if "api.github.com" in url else self.zip
            return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr=b"")

        real = subprocess.run
        with mock.patch.object(release.subprocess, "run",
                               side_effect=lambda cmd, **kw: curl(cmd, **kw) if "curl" in str(cmd[0]) else real(cmd, **kw)), \
                mock.patch.object(release.shutil, "which", return_value="/usr/bin/curl"):
            out = io.StringIO()
            with mock.patch("sys.stdout", out):
                self.assertEqual(0, release.update(self.root))
        self.assertEqual(2, len(calls))
        self.assertIn("-fsSL", calls[1])
        self.assertIn("User-Agent: Garrick/0.15.2", calls[1])
        self.assertIn("no certificates, so curl fetched", out.getvalue())
        self.assertEqual(["--update", str(self.root)], json.loads(self.record.read_text())["argv"])

    def test_without_certificates_or_curl_it_says_what_to_do(self):
        import ssl
        self.net(fail=urllib.error.URLError(ssl.SSLCertVerificationError("unable to get local issuer certificate")))
        err = io.StringIO()
        with mock.patch.object(release.shutil, "which", return_value=None), \
                mock.patch("sys.stderr", err), mock.patch("sys.stdout", io.StringIO()):
            self.assertEqual(1, release.main(["--root", str(self.root), "update", "--tag", "v0.16.0"]))
        self.assertIn("/usr/bin/python3", err.getvalue())
        self.assertIn("Install Certificates.command", err.getvalue())

    def test_unpack_keeps_modes_and_refuses_paths_and_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            top = release.unpack(self.zip, Path(tmp))
            self.assertEqual("garrick-0.16.0", top.name)
            self.assertTrue(os.access(top / "extras" / "status" / "app" / "make-app.sh", os.X_OK))
        for bad in (archive({"install.py": ("", 0o644)}, top="garrick/../.."),
                    archive({"install.py": ("", 0o644), "update.py": ("", 0o644)}, links=("garrick-0.16.0/x",)),
                    archive({"README.md": ("", 0o644)}),
                    b"not a zip"):
            with tempfile.TemporaryDirectory() as tmp, self.assertRaises(release.ReleaseError):
                release.unpack(bad, Path(tmp))


JOBS = REPO / "extras" / "jobs"
PAGE_ACTION = REPO / "extras" / "status" / "page_action.py"


class TestTheCadence(ReleaseCase):
    """#410: `release-notice-every` is 1 or 7 days, and a missing key is one."""

    def asked(self, days):
        self.cache(asked=dt.datetime.now() - dt.timedelta(days=days))

    def test_a_missing_or_odd_key_means_one_day(self):
        for more in ({}, {"release-notice-every": 3}, {"release-notice-every": "7"}, {"release-notice-every": True},
                     {"release-notice-every": None}):
            self.setting(**more)
            self.assertEqual(dt.timedelta(days=1), self.lib.release_every(self.root), more)

    def test_daily_asks_after_a_day_and_weekly_after_seven(self):
        self.setting()
        self.asked(0.5)
        self.assertFalse(self.lib.release_due(self.root))
        self.asked(2)
        self.assertTrue(self.lib.release_due(self.root))                  # no key: the day it always was
        self.setting(**{"release-notice-every": 7})
        self.asked(2)
        self.assertFalse(self.lib.release_due(self.root))
        self.asked(6.5)
        self.assertFalse(self.lib.release_due(self.root))
        self.asked(7.5)
        self.assertTrue(self.lib.release_due(self.root))
        self.setting(False, **{"release-notice-every": 7})
        self.assertFalse(self.lib.release_due(self.root))                 # off is off, whatever the cadence

    def test_the_two_keys_are_kept_choices(self):
        self.assertIn("release-notice", self.lib.PREFERENCES)
        self.assertIn("release-notice-every", self.lib.PREFERENCES)
        self.lib.save_preferences(self.root, {"release-notice": True, "release-notice-every": 7})
        self.assertEqual(7, self.lib.read_settings(self.root)["release-notice-every"])
        self.assertTrue(self.lib.release_notice_on(self.root))


class TestWhatMayBeUpdated(ReleaseCase):
    """Only a workspace whose release is older than the newest, by semantic comparison, may be updated."""

    def state(self, tag, **more):
        self.cache(tag, **more)
        return release.state(self.root)

    def test_older_is_updatable(self):
        st = self.state("v0.16.0")
        self.assertTrue(st["update"] and st["newer"])
        self.assertEqual(("0.15.2", "0.16.0", "v0.16.0"), (st["running"], st["latest"], st["tag"]))

    def test_semantic_not_textual(self):
        write(self.root / "System" / "garrick-changelog.md", CHANGELOG.replace("0.15.2", "0.9.0"))
        self.assertTrue(self.state("v0.10.0")["update"])                 # 0.10.0 is newer than 0.9.0
        write(self.root / "System" / "garrick-changelog.md", CHANGELOG.replace("0.15.2", "0.10.0"))
        self.assertFalse(self.state("v0.9.0")["update"])

    def test_the_same_newer_or_a_pre_release_of_it_is_not(self):
        write(self.root / "System" / "garrick-changelog.md", CHANGELOG.replace("0.15.2", "0.17.0"))
        for tag in ("v0.17.0", "v0.16.0", "v0.17.0-rc1"):
            st = self.state(tag)
            self.assertFalse(st["update"], tag)
            self.assertIn("is the newest release, and this workspace runs 0.17.0", st["why"], tag)

    def test_a_running_version_that_cannot_be_read_fails_closed(self):
        write(self.root / "System" / "garrick-changelog.md", "# Changelog\n\n## [Unreleased]\n")
        st = self.state("v0.16.0")
        self.assertFalse(st["update"])
        self.assertIn("does not record", st["why"])
        (self.root / "System" / "garrick-changelog.md").unlink()
        self.assertFalse(release.state(self.root)["update"])

    def test_a_failed_or_missing_answer_is_not_updated(self):
        self.assertFalse(self.state("v0.16.0", failed="offline")["update"])
        self.assertTrue(self.state("v0.16.0", failed="offline")["failed"])
        (self.root / "System" / "generated" / "garrick-release.json").unlink()
        st = release.state(self.root)
        self.assertFalse(st["update"])
        self.assertTrue(st["failed"])

    def test_another_repositorys_answer_is_not(self):
        self.assertFalse(self.state("v0.16.0", repository="birch-co/garrick")["update"])

    def test_latest_json_prints_the_comparison(self):
        self.net(answers={"https://api.github.com": latest("v0.16.0")})
        code, out = self.run_release("latest", "--now", "--json")
        self.assertEqual(0, code)
        found = json.loads(out)
        self.assertTrue(found["update"])
        self.assertEqual("0.15.2", found["running"])


class TestTheReleaseNotice(ReleaseCase):
    """#410: `release` is sent once for each tag, by the background check alone."""

    def setUp(self):
        super().setUp()
        sys.path.insert(0, str(TOOLS))
        self.addCleanup(sys.path.remove, str(TOOLS))
        import notifications
        self.n = notifications
        self.sent = []
        patch = mock.patch.object(notifications, "send", side_effect=lambda *a, **k: self.sent.append((a, k)) or True)
        patch.start()
        self.addCleanup(patch.stop)

    def background(self, tag):
        self.setting()
        kept = {"notified": self.read_cache()["notified"]} if "notified" in (self.read_cache() if (
            self.root / "System" / "generated" / "garrick-release.json").exists() else {}) else {}
        self.cache(tag, asked=dt.datetime.now() - dt.timedelta(days=3), **kept)
        self.net(answers={"https://api.github.com": latest(tag)})
        self.assertEqual((0, ""), self.run_release("latest", "--background"))

    def test_the_event_is_known_and_held_at_night(self):
        self.assertIn("release", self.n.EVENT_NAMES)
        self.assertEqual("hold", self.n.QUIET["release"])
        self.assertIn(("release", "a newer Garrick is out"), self.n.TELL)

    def test_one_notice_for_one_release(self):
        self.background("v0.16.0")
        self.assertEqual(1, len(self.sent))
        (event, title, message), kw = self.sent[0]
        self.assertEqual(("release", "A newer Garrick is out", "Garrick 0.16.0 is out; this workspace runs 0.15.2"),
                         (event, title, message))
        self.assertEqual("v0.16.0", self.read_cache()["notified"])
        self.background("v0.16.0")                                         # the next check of the same release
        self.assertEqual(1, len(self.sent))
        self.background("v0.17.0")                                         # a newer one is news again
        self.assertEqual(2, len(self.sent))

    def test_a_notice_that_could_not_go_is_tried_again(self):
        self.n.send.side_effect = lambda *a, **k: False                   # the event is off
        self.background("v0.16.0")
        self.assertNotIn("notified", self.read_cache())
        self.n.send.side_effect = lambda *a, **k: True
        self.background("v0.16.0")
        self.assertEqual("v0.16.0", self.read_cache()["notified"])

    def test_nothing_newer_sends_nothing(self):
        self.background("v0.15.2")
        self.assertEqual([], self.sent)

    def test_the_background_check_never_updates(self):
        with mock.patch.object(release, "update", side_effect=AssertionError("a scheduled check updated")), \
                mock.patch.object(release, "fetch_with_curl", side_effect=AssertionError("downloaded")):
            self.background("v0.16.0")
        self.assertEqual(1, len(self.sent))


class TestNoScheduledPathUpdates(unittest.TestCase):
    """#410: only a click, or a request to the assistant, runs downloaded code."""

    def test_nothing_under_the_jobs_calls_release_update(self):
        for path in sorted(JOBS.rglob("*")):
            if not path.is_file() or path.suffix not in (".py", ".plist", ".sh", ".json", ""):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for m in re.finditer(r"release(?:\.py)?\b", text):
                near = text[m.start():m.start() + 160]
                self.assertNotRegex(near, r"[\"' ]update[\"' ]", "%s runs release.py update: %s" % (path.name, near))
            self.assertNotIn("--apply", text.replace("--apply-", "") if "release.py" in text else "", path.name)

    def test_the_nightly_job_runs_latest_background_and_nothing_else_of_release_py(self):
        text = (JOBS / "nightly.py").read_text(encoding="utf-8")
        self.assertIn('"latest", "--background"', text)
        calls = re.findall(r"RELEASE_TOOL|release\.py", text)
        self.assertTrue(calls)
        self.assertNotRegex(text, r"RELEASE_TOOL[^\n]*update")
        self.assertNotIn("update --apply", text)

    def test_the_launchd_templates_run_no_update(self):
        for plist in sorted((JOBS / "launchd").glob("*.plist")):
            text = plist.read_text(encoding="utf-8")
            self.assertNotIn("release.py", text, plist.name)

    def test_the_page_build_asks_and_never_updates(self):
        text = STATUS.read_text(encoding="utf-8")
        body = text[text.index("def release_ask("):text.index("def _value(")]
        self.assertIn('"latest", "--background"', body)
        self.assertNotIn("update", body.replace("updat", "", 0).split('"""', 2)[2])

    def test_only_the_buttons_verb_runs_release_py_update(self):
        text = PAGE_ACTION.read_text(encoding="utf-8")
        users = [m.start() for m in re.finditer(r'release_run\(ws, "update"', text)]
        self.assertEqual(2, len(users))                                     # the plan and the apply, both in release_update
        start, end = text.index("def release_update("), text.index("def save_settings(")
        self.assertTrue(all(start < at < end for at in users))
        self.assertEqual(1, len(re.findall(r"release_update\(ws\)", text[:start] + text[end:])))   # one caller: act()
        self.assertIn('if not state.get("update")', text[start:end])        # the guard, before any download


class TestTheNightlyCheck(ReleaseCase):
    """The nightly job's release step: the tool's own due-check decides; it is called once and passes `latest --background`."""

    def setUp(self):
        super().setUp()
        self.nightly = load("garrick_nightly_for_release", JOBS / "nightly.py")

    def test_it_runs_the_background_check_and_nothing_more(self):
        seen = []

        def fake(cmd, **kw):
            seen.append(cmd)
            return subprocess.CompletedProcess(cmd, 0)

        with mock.patch.object(self.nightly.subprocess, "run", fake):
            self.assertEqual(0, self.nightly.release_check(self.root))
        self.assertEqual(1, len(seen))
        self.assertEqual(["latest", "--background"], seen[0][-2:])
        self.assertNotIn("update", seen[0])
        self.assertEqual(str(self.root / "System" / "tools" / "release.py"), seen[0][1])

    def test_without_the_tool_it_is_skipped(self):
        (self.root / "System" / "tools" / "release.py").unlink()
        self.assertIsNone(self.nightly.release_check(self.root))

    def test_a_failure_is_silent(self):
        with mock.patch.object(self.nightly.subprocess, "run", side_effect=subprocess.TimeoutExpired("x", 1)):
            self.assertIsNone(self.nightly.release_check(self.root))

    def test_it_asks_when_due_and_not_otherwise(self):
        """The real tool, with the network replaced: off asks nothing; on with no key asks after a day;
        weekly asks after seven."""
        fake = self.net(answers={"https://api.github.com": latest("v0.16.0")})
        for on, key, days, asks in ((False, {}, 9, 0), (True, {}, 0.5, 0), (True, {}, 2, 1),
                                    (True, {"release-notice-every": 7}, 3, 0), (True, {"release-notice-every": 7}, 8, 1)):
            del fake.requests[:]
            self.setting(on, **key)
            self.cache(asked=dt.datetime.now() - dt.timedelta(days=days))
            release.main(["--root", str(self.root), "latest", "--background"])
            self.assertEqual(asks, len(fake.requests), (on, key, days))


class TestTheButtonsVerbs(ReleaseCase):
    """page_action.py's `release-check` and `release-update`."""

    def setUp(self):
        super().setUp()
        self.pa = load("garrick_page_action_for_release", PAGE_ACTION)
        self.calls = []

    def runner(self, answers):
        def run(ws, *args, timeout):
            self.calls.append(args)
            for key, (code, out, err) in answers.items():
                if all(k in args for k in key):
                    return subprocess.CompletedProcess(args, code, out, err)
            raise AssertionError("unexpected release.py call: %r" % (args,))
        return mock.patch.object(self.pa, "release_run", run)

    def state(self, **more):
        base = {"running": "0.15.2", "latest": "0.16.0", "tag": "v0.16.0", "url": "https://github.com/x/y/releases/tag/v0.16.0",
                "asked": "2026-11-07T10:00:00", "failed": "", "newer": True, "update": True}
        return json.dumps(dict(base, **more))

    def test_check_says_the_newest_release_when_there_is_nothing_newer(self):
        out = self.state(running="0.16.0", newer=False, update=False, why="Garrick 0.16.0 is the newest release, and this workspace runs 0.16.0")
        with self.runner({("latest", "--now", "--json"): (0, out, "")}):
            reply = self.pa.act(self.root, {"verb": "release-check"})
        self.assertEqual("current", reply["release"]["state"])
        self.assertIn("Garrick 0.16.0 is the newest release", reply["say"])
        self.assertEqual([("latest", "--now", "--json")], self.calls)          # asked once, changed nothing

    def test_check_with_a_newer_release_only_asks(self):
        with self.runner({("latest", "--now", "--json"): (0, self.state(), "")}):
            reply = self.pa.act(self.root, {"verb": "release-check"})
        self.assertEqual("newer", reply["release"]["state"])
        self.assertEqual([("latest", "--now", "--json")], self.calls)

    def test_a_failed_question_is_one_line_and_changes_nothing(self):
        out = self.state(failed="offline", newer=False, update=False)
        with self.runner({("latest", "--now", "--json"): (0, out, "")}):
            reply = self.pa.act(self.root, {"verb": "release-check"})
        self.assertEqual("failed", reply["release"]["state"])
        self.assertIn("Could not ask GitHub (offline). Nothing was changed.", reply["say"])

    def test_update_refuses_when_the_running_release_is_not_older(self):
        for more in ({"running": "0.16.0", "newer": False, "update": False,
                      "why": "Garrick 0.16.0 is the newest release, and this workspace runs 0.16.0"},
                     {"running": "", "update": False, "newer": False, "why": "this workspace does not record which release it runs"},
                     {"failed": "offline", "update": False, "newer": False}):
            del self.calls[:]
            with self.runner({("latest", "--json"): (0, self.state(**more), "")}):
                reply = self.pa.act(self.root, {"verb": "release-update"})
            self.assertNotEqual("updated", reply["release"]["state"], more)
            self.assertEqual([("latest", "--json")], self.calls, more)          # nothing was downloaded

    def test_update_applies_and_reports_in_the_updates_words(self):
        plan = json.dumps({"actions": {"split": ["System/rules.md"], "replace": [], "add": [], "merge": []}})
        applied = json.dumps({"done": {"replace": ["a.md", "b.md"], "add": ["c.md"], "restore": [], "merge": ["System/x.md"]},
                              "skipped": [["System/y.md", "it has changes not committed; commit or discard them, then run again"]],
                              "commits": ["abc123 in the workspace"], "problems": [], "stamped": True, "unstamped": "",
                              "then": ["The zone guard runs from a copy outside the workspace"]})
        with self.runner({("latest", "--json"): (0, self.state(), ""),
                          ("update", "--apply"): (0, applied, ""),
                          ("update", "--tag", "v0.16.0", "--json"): (0, plan, "")}):
            reply = self.pa.act(self.root, {"verb": "release-update"})
        r = reply["release"]
        self.assertEqual("updated", r["state"])
        self.assertEqual("Updated to 0.16.0 from 0.15.2.", reply["say"])
        self.assertEqual((3 - 1, 1), (r["replaced"], r["added"]))
        self.assertEqual(["System/x.md"], r["new"])
        self.assertEqual(["System/rules.md"], r["split"])
        self.assertEqual("System/y.md", r["skipped"][0][0])
        self.assertEqual(["The zone guard runs from a copy outside the workspace"], r["then"])
        self.assertTrue(r["url"].startswith("https://github.com/"))
        self.assertIn("--apply", self.calls[-1])

    def test_an_update_the_check_stops_keeps_the_stamp_and_says_how_to_undo(self):
        plan = json.dumps({"actions": {"split": []}})
        applied = json.dumps({"done": {"replace": ["a.md"], "add": [], "restore": [], "merge": []}, "skipped": [], "commits": [],
                              "problems": ["System/a.md: error"], "stamped": False, "unstamped": "", "then": []})
        with self.runner({("latest", "--json"): (0, self.state(), ""), ("update", "--apply"): (1, applied, ""),
                          ("update", "--json"): (0, plan, "")}):
            reply = self.pa.act(self.root, {"verb": "release-update"})
        self.assertEqual("stopped", reply["release"]["state"])
        self.assertIn("version stamp is not moved", reply["say"])
        self.assertIn("git revert", reply["say"])

    def test_a_plan_that_fails_starts_nothing(self):
        with self.runner({("latest", "--json"): (0, self.state(), ""),
                          ("update", "--json"): (1, "", "The download failed: offline.\n")}):
            reply = self.pa.act(self.root, {"verb": "release-update"})
        self.assertEqual("failed", reply["release"]["state"])
        self.assertFalse(any("--apply" in c for c in self.calls))

    def test_settings_keep_the_switch_and_the_cadence(self):
        self.assertEqual("Settings saved", self.pa.act(self.root, {"verb": "settings", "release-notice": True, "release-notice-every": 7}))
        self.assertTrue(self.lib.release_notice_on(self.root))
        self.assertEqual(dt.timedelta(days=7), self.lib.release_every(self.root))
        for bad in ({"release-notice": "yes"}, {"release-notice-every": 3}, {"release-notice-every": True}):
            with self.assertRaises(self.pa.Refused):
                self.pa.act(self.root, dict(bad, verb="settings"))

    def test_the_section_shows_the_button_the_switch_and_the_cadence(self):
        self.setting(**{"release-notice-every": 7})
        html = status.build(self.root, now=dt.datetime.now(), folder=self.base / "jobs")
        start = html.index('id="about-settings"')
        sec = html[start:html.index("</section>", start)]
        self.assertIn('id="rel-check">Check for updates</button>', sec)
        self.assertIn("Check for a newer Garrick", sec)
        self.assertIn('<option value="7" selected>Weekly</option>', sec)
        self.assertIn('id="rel-on" checked', sec)
        self.assertIn("window.GarrickRelease", status.RELEASE_JS)
        self.assertIn("q['release-notice']=rq.on;q['release-notice-every']=rq.every", html)


if __name__ == "__main__":
    unittest.main()
