"""Six faults of the wall check and the status page, found by the 0.58.0 review and the refusal of a
merge (0.59.0).

    cd tests && python3 -m unittest test_check_low_faults

Every name is invented; Acme Corp and Birch & Co have a wall between them.
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

import subprocess  # noqa: E402
from unittest import mock  # noqa: E402

from fixtures import HAVE_GIT, build_workspace, commit_all, git, git_init, meeting_page, project_hub, thread_note, write  # noqa: E402

import check  # noqa: E402

WALL_MESSAGE = "is walled and this project does not name it"


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "Workspace"
        build_workspace(self.root)
        self.work = self.root / "Zones" / "Work"
        self.note = self.work / "Birch Entry" / "Threads" / "Market Sizing" / "Notes.md"

    def says(self, text, note=None):
        note = note or self.note
        write(note, text)
        where = str(note.relative_to(self.root))
        return [(f.severity, f.message) for f in check.run_checks(self.root, walls_only=True) if f.path == where]

    def refused(self, found):
        return [m for s, m in found if s == "error"]


class OutsidePathTest(Base):
    """1. A path outside the workspace is read as a path into it."""

    def setUp(self):
        super().setUp()
        # An Acme project that holds folders named like the parts of a folder in a user's Library.
        write(self.work / "Harbour" / "Harbour.md", project_hub("Work", "Harbour", "acme"))
        write(self.work / "Harbour" / "Library" / "Application Scripts" / "com.apple.mail" / "x.scpt", "x\n")
        write(self.work / "Harbour" / "Deliverables" / "260301 - Plan.md", "# plan\n")

    def test_a_path_under_the_home_folder_that_ends_like_a_project_folder_is_not_a_path_into_it(self):
        for written in ("~/Library/Application Scripts/com.apple.mail/x.scpt",
                        "/Users/jo/Library/Application Scripts/com.apple.mail/x.scpt"):
            found = self.says("Put the script in `%s`.\n" % written)
            self.assertEqual([], self.refused(found), (written, found))





class RefusalTrailerTest(Base):
    """2. Each refusal ends with the fix of its own kind."""

    def line(self, text, note=None):
        note = note or self.note
        write(note, text)
        where = str(note.relative_to(self.root))
        found = [f for f in check.run_checks(self.root, walls_only=True) if f.path == where]
        return check.report_staged(found)

    def far_page(self):
        write(self.root / "Wikis" / "Meetings" / "wiki" / "sources" / "260399-home.md", meeting_page("Personal", "[acme]", "Home"))
        return "See `Wikis/Meetings/wiki/sources/260399-home.md`.\n"

    def test_a_wall_crossing_ends_with_take_it_out(self):
        with mock.patch("sys.stderr", io.StringIO()) as _:          # printing for an assistant: the clause is the user's, left out
            out = self.line(self.far_page())
        self.assertIn("Commit refused: ", out)
        self.assertTrue(out.splitlines()[-1].endswith("Take it out and commit again."), out)
        self.assertNotIn("--no-verify", out)
        tty = io.StringIO()
        tty.isatty = lambda: True
        with mock.patch("sys.stderr", tty):                         # a terminal: unchanged
            out = self.line(self.far_page())
        self.assertTrue(out.splitlines()[-1].endswith("Take it out and commit again; only if you mean it, git commit --no-verify."), out)

    def test_each_kind_has_a_fix_that_says_commit_again(self):
        kinds = {
            "links x, a note of the Personal zone; that zone is walled and this file is in the Work zone": "Take it out",
            "names different zones and walls on disk from the ones staged; stage that change or undo it": "Stage that change",
            "uses x, an unfinished source (no zone or parties)": "Finish or file it",
            "links x, a source that names no zone, so nothing says whose it is; give it a `zone:`": "Give it a",
            "uses x, a raw record that no page cites, so nothing says whose it is": "Give it a",
            "holds a path the system cannot read (Too long), so the file cannot be checked; shorten it": "Make that change",
        }
        for message, start in kinds.items():
            fix = check.staged_fix(message)
            self.assertTrue(fix.startswith(start), (message, fix))
            self.assertIn("commit again", fix)


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class StagedRunTest(Base):
    """3. A commit check asks git for each staged file once, and for a hub once."""

    def test_each_staged_file_is_read_from_git_once(self):
        git_init(self.work)
        write(self.work / "Northwind" / "Northwind.md", project_hub("Work", "Northwind", "acme", ["T0"]))
        write(self.work / "Northwind" / "Threads" / "T0" / "T0.md", thread_note("Northwind", "T0", "acme"))
        commit_all(self.work, "base")
        for i in range(6):
            write(self.work / "Northwind" / "Threads" / "T0" / ("Note %d.md" % i), "# Note %d\n\nFreight rates.\n" % i)
        git(self.work, "add", "-A")
        shown, real = [], subprocess.run

        def watching(cmd, *a, **kw):
            if list(cmd[:2]) == ["git", "show"]:
                shown.append(cmd[2])
            return real(cmd, *a, **kw)

        with mock.patch.object(check.subprocess, "run", watching):
            found = check.run_checks(self.root, walls_only=True, staged=self.work)
        self.assertEqual([], [f for f in found if f.severity == "error"])
        self.assertEqual(6, len(shown), shown)
        self.assertEqual(len(shown), len(set(shown)))


class CmuxResumeTest(unittest.TestCase):
    """#440: a warning, once, when cmux is set not to resume agent sessions. The config is built in a temporary HOME."""

    def run_with(self, config):
        import json
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as ws_root:
            if config is not None:
                path = Path(home) / ".config" / "cmux" / "cmux.json"
                path.parent.mkdir(parents=True)
                path.write_text(config if isinstance(config, str) else json.dumps(config), encoding="utf-8")
            (Path(ws_root) / "System" / "cmux").mkdir(parents=True)        # the cmux extra is installed
            with mock.patch.dict(os.environ, {"HOME": home}):
                return [(f.severity, f.check) for f in check.check_cmux(check.discover(Path(ws_root), light=True))]

    def test_it_warns_once_when_resuming_is_off(self):
        self.assertEqual([("warning", "cmux")], self.run_with({"terminal": {"autoResumeAgentSessions": False}}))
        self.assertEqual([("warning", "cmux")], self.run_with({"terminal.autoResumeAgentSessions": False}))

    def test_comments_in_the_file_do_not_hide_it(self):
        text = '// cmux\n{\n  /* resume */ "terminal": {"autoResumeAgentSessions": false, // off\n "url": "http://x//y"}\n}\n'
        self.assertEqual([("warning", "cmux")], self.run_with(text))

    def test_a_workspace_without_the_cmux_extra_reads_no_home_folder(self):
        with tempfile.TemporaryDirectory() as ws_root, mock.patch("os.path.expanduser", side_effect=AssertionError("read the home folder")):
            self.assertEqual([], check.check_cmux(check.discover(Path(ws_root), light=True)))

    def test_it_is_quiet_otherwise(self):
        for config in (None, {}, "not json", {"terminal": {"autoResumeAgentSessions": True}}, {"terminal": {}}, []):
            self.assertEqual([], self.run_with(config), config)


if __name__ == "__main__":
    unittest.main()
