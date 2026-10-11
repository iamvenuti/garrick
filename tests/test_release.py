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
        self.assertNotIn("is out", self.page())

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
        self.assertNotIn("is out", html)
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
            self.assertNotIn("is out", self.page(), tag)
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


if __name__ == "__main__":
    unittest.main()
