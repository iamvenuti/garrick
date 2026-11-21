"""The page's own route (#618 leftover): a page-only verb is done only when Garrick.app's bridge asks.

    cd tests && python3 -m unittest test_page_route

`--via page` is a word on a command line, so a session's shell can type it. page_action.py believes it only when the
process that started it is the app's own executable (page_route()). Tests replace that one function in this process,
never through an argument, a variable or a file.
"""

from __future__ import annotations

import json
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

import test_page_action as base  # noqa: E402

pa = base.pa
SCRIPT = base.SCRIPT

# One request for each verb only the page's own button sends.
PAGE_ONLY_REQUESTS = [{"verb": v} for v in sorted(set(pa.PAGE_ONLY) | {"walls-look", "walls-allow", "new-project-party"})]
PAGE_ONLY_REQUESTS += [{"verb": "finding", "answer": "%s-0a1b2c" % a} for a in pa.PAGE_ONLY_ANSWERS]


class RouteCase(base.ActionCase):
    def run_script(self, request, via="page"):
        argv = [sys.executable, str(SCRIPT), "--workspace", str(self.root)] + (["--via", via] if via else [])
        done = subprocess.run(argv, input=json.dumps(request), capture_output=True, text=True,
                              env=dict(os.environ, GARRICK_JOBS_DIR=str(self.jobs)))
        return json.loads(done.stdout)

    def log(self):
        return (self.jobs / "page-actions.log").read_text(encoding="utf-8").splitlines()


class TestNoRouteNoPage(RouteCase):
    def test_every_page_only_verb_is_refused_when_the_command_line_says_page(self):
        for req in PAGE_ONLY_REQUESTS:
            with self.subTest(verb=req["verb"], answer=req.get("answer")):
                out = self.run_script(req)
                self.assertFalse(out["ok"], out)
                said = "a party is added only from the New project dialog on the page" if req["verb"] == "new-project-party" \
                    else pa.PAGE_REFUSED
                self.assertEqual(said, out["say"])

    def test_walls_allow_is_one_of_them(self):
        self.assertIn("walls-allow", [r["verb"] for r in PAGE_ONLY_REQUESTS])
        self.assertIn("new-project-party", [r["verb"] for r in PAGE_ONLY_REQUESTS])
        self.assertEqual(len(pa.PAGE_ONLY_ANSWERS), len([r for r in PAGE_ONLY_REQUESTS if r["verb"] == "finding"]))

    def test_the_log_names_the_caller_it_was_treated_as(self):
        self.run_script({"verb": "walls-allow"})
        self.assertTrue(self.log()[-1].endswith("(session; --via page did not come from the app)"), self.log()[-1])

    def test_a_verb_that_is_not_page_only_does_what_it_did(self):
        out = self.run_script({"verb": "todo-add", "zone": "Work", "text": "Book the room"})
        self.assertTrue(out["ok"], out)
        self.assertIn("Book the room", (self.work / "Todo.md").read_text(encoding="utf-8"))

    def test_a_session_and_no_flag_are_refused_as_before(self):
        for via in ("session", None):
            with self.subTest(via=via):
                self.assertFalse(self.run_script({"verb": "walls-allow"}, via=via)["ok"])

    def test_ask_and_outbox_are_in_process_callers_and_never_a_command_line(self):
        for declared in ("ask", "outbox", None, "session"):
            self.assertEqual("session", pa.caller(declared, self.root))

    def test_the_environment_and_the_workspace_cannot_make_a_page(self):
        env = dict(os.environ, GARRICK_JOBS_DIR=str(self.jobs), GARRICK_VIA="page", GARRICK_PAGE="1", GARRICK_FROM_APP="1")
        done = subprocess.run([sys.executable, str(SCRIPT), "--workspace", str(self.root), "--via", "page"],
                              input=json.dumps({"verb": "walls-allow"}), capture_output=True, text=True, env=env)
        self.assertFalse(json.loads(done.stdout)["ok"])


class TestThePageRoute(RouteCase):
    """What a request through the app's bridge does: the check says yes, and the request is the page's."""

    def main(self, req, via="page"):
        import contextlib
        import io
        out = io.StringIO()
        with mock.patch.object(pa, "page_route", return_value=True), mock.patch.object(sys, "stdin", io.StringIO(json.dumps(req))), \
                contextlib.redirect_stdout(out):
            pa.main(["--workspace", str(self.root), "--via", via])
        return json.loads(out.getvalue())

    def test_the_check_is_asked_of_this_workspace(self):
        with mock.patch.object(pa, "page_route", return_value=True) as route:
            self.assertEqual("page", pa.caller("page", self.root))
        route.assert_called_once_with(self.root)

    def test_a_page_only_verb_gets_past_the_page_check(self):
        out = self.main({"verb": "walls-allow"})
        self.assertNotEqual(pa.PAGE_REFUSED, out["say"])

    def test_the_log_says_page(self):
        self.main({"verb": "todo-add", "zone": "Work", "text": "Book the room"})
        self.assertTrue(self.log()[-1].endswith("(page)"), self.log()[-1])

    def test_the_same_verb_through_a_session_is_still_refused(self):
        self.assertEqual(pa.PAGE_REFUSED, self.main({"verb": "walls-allow"}, via="session")["say"])


class TestWhatCountsAsTheApp(RouteCase):
    """page_route() reads the kernel's word about the parent process, and says no when anything is unclear."""

    def setUp(self):
        super().setUp()
        self.home = Path(self._tmp.name).resolve() / "home"
        (self.home / "Applications").mkdir(parents=True)
        self.exe = self.bundle(self.home / "Applications" / "Garrick.app")
        patch = mock.patch("pathlib.Path.home", return_value=self.home)
        patch.start()
        self.addCleanup(patch.stop)

    def bundle(self, app, ident=None, ws=None, exe="Garrick"):
        macos = app / "Contents" / "MacOS"
        macos.mkdir(parents=True)
        (macos / exe).write_text("binary")
        with (app / "Contents" / "Info.plist").open("wb") as f:
            plistlib.dump({"CFBundleIdentifier": ident or pa.APP_BUNDLE_ID,
                           "GarrickWorkspace": str(ws or self.root)}, f)
        return macos / exe

    def route(self, path):
        with mock.patch.object(pa, "_parent_executable", return_value=path):
            return pa.page_route(self.root)

    def test_the_apps_own_executable_in_the_users_applications_folder_is_the_page(self):
        self.assertTrue(self.route(self.exe))

    def test_the_bundle_identifier_decides(self):
        other = self.bundle(self.home / "Applications" / "Other.app", ident="local.other.app", exe="Garrick")
        self.assertFalse(self.route(other))
        scratch = self.bundle(self.home / "Applications" / "Scratch.app", ident=pa.APP_BUNDLE_ID + ".scratch")
        self.assertFalse(self.route(scratch))

    def test_the_app_must_name_this_workspace(self):
        other = self.bundle(self.home / "Applications" / "Else.app", ws=Path(self._tmp.name) / "Elsewhere")
        self.assertFalse(self.route(other))

    def test_the_executable_has_the_apps_name_and_place(self):
        self.assertFalse(self.route(self.bundle(self.home / "Applications" / "Name.app", exe="python3")))
        loose = self.home / "Applications" / "Garrick"
        loose.write_text("binary")
        self.assertFalse(self.route(loose))

    def test_a_bundle_outside_an_applications_folder_is_not_the_app(self):
        elsewhere = self.home / "Downloads"
        elsewhere.mkdir()
        self.assertFalse(self.route(self.bundle(elsewhere / "Garrick.app")))

    def test_a_link_to_the_executable_is_not_the_executable(self):
        link = self.home / "Applications" / "Link.app" / "Contents" / "MacOS"
        link.mkdir(parents=True)
        (link / "Garrick").symlink_to(self.exe)
        self.assertFalse(self.route(link / "Garrick"))

    def test_a_lookup_that_fails_says_no(self):
        self.assertFalse(self.route(None))
        self.assertFalse(self.route(Path("relative/Garrick")))
        with mock.patch.object(pa, "_parent_executable", side_effect=OSError("no lookup")):
            self.assertFalse(pa.page_route(self.root))
        (self.exe.parent.parent / "Info.plist").write_bytes(b"not a plist")
        self.assertFalse(self.route(self.exe))

    def test_the_parent_of_a_test_run_is_not_the_app(self):
        # Nothing patched: the process that started this one is the test runner.
        self.assertFalse(pa.page_route(self.root))


class TestTheDocsSayWhoCannotPress(unittest.TestCase):
    def test_a_scratch_build_a_build_elsewhere_and_a_translocated_app_are_named(self):
        text = (Path(__file__).resolve().parent.parent / "docs" / "enforced.md").read_text(encoding="utf-8")
        for words in ("outside `~/Applications` or `/Applications`", "scratch build", "translocated", "cannot press the page-only buttons"):
            self.assertIn(words, text)
