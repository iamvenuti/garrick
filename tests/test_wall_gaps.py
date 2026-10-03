"""What the check promises and now holds: the gaps between the rules and the
check, each closed with a case that must be caught and one that must pass.

Invented parties only: Acme Corp (`acme`) and Birch & Co (`birch`), walled
from each other, as in fixtures.py.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fixtures import HAVE_GIT, build_workspace, commit_all, git, write

import check  # noqa: E402  (fixtures puts the tools folder on sys.path)
from garrick_lib import WALL_HOOK, install_wall_hook  # noqa: E402

# The checker runs git as the user would; these keep the user's own config out.
NO_USER_GIT = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def real_repo(folder: Path) -> None:
    shutil.rmtree(folder / ".git", ignore_errors=True)
    git(folder, "init", "-q")


class GapCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve() / "Workspace"
        build_workspace(self.root)
        self.work = self.root / "Zones" / "Work"
        self.acme = self.work / "Acme Review"
        self.birch = self.work / "Birch Entry"
        self.meetings = self.root / "Wikis" / "Meetings"
        self.knowledge = self.root / "Wikis" / "Knowledge"

    def tearDown(self):
        self._tmp.cleanup()

    def findings(self, name=None, severity=None):
        return [f for f in check.run_checks(self.root)
                if (name is None or f.check == name) and (severity is None or f.severity == severity)]

    def assertClean(self, name):
        self.assertEqual([], [(f.severity, f.path, f.message) for f in self.findings(name)])


class TestLinkIndex(GapCase):
    """Each link is matched against an index built once, not against every file."""

    def test_links_resolve_as_before(self):
        ws = check.discover(self.root)
        files = check.PathIndex(ws, check.walk_files(self.root))
        note = self.acme / "Threads" / "Pricing" / "Pricing.md"
        kickoff = self.meetings / "wiki" / "sources" / "260310-acme-kickoff.md"
        for target in ("260310-acme-kickoff", "Sources/260310-ACME-Kickoff.md", "Meetings/wiki/sources/260310-acme-kickoff",
                       "obsidian:Wikis:Meetings/wiki/sources/260310-acme-kickoff",
                       "../../../../../Wikis/Meetings/wiki/sources/260310-acme-kickoff.md",
                       "../../../../../Wikis/Meetings/wiki/sources/260310-acme-kickoff",
                       str(kickoff)):
            with self.subTest(target):
                self.assertEqual([kickoff], check.resolve(ws, note, target, files))
                self.assertEqual([kickoff], check.resolve(ws, note, target, list(check.walk_files(self.root))))
        for target in ("260310-acme", "wiki/260310-acme-kickoff", "../260310-acme-kickoff", "./", ""):
            with self.subTest(target):
                self.assertEqual([], check.resolve(ws, note, target, files))

    def test_knowledge_links_cost_one_lookup_each(self):
        concepts = self.knowledge / "wiki" / "concepts"
        n = 300
        for i in range(n):
            write(concepts / ("idea-%d.md" % i), "# Idea\n\nSee [[idea-%d]] and [[wiki/sources/supply-chain-report]].\n"
                  % ((i + 1) % n))
        write(concepts / "leak.md", "As heard in [[260310-acme-kickoff]].\n")
        calls = []
        real = check.rel
        check.rel = lambda ws, path: calls.append(path) or real(ws, path)
        try:
            found = check.check_knowledge(check.discover(self.root))
        finally:
            check.rel = real
        self.assertEqual(["Wikis/Knowledge/wiki/concepts/leak.md"], [f.path for f in found])
        # Once per file to index it, and a few per finding: never once per file per link.
        self.assertLess(len(calls), 4 * n, len(calls))


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class TestHooksPath(GapCase):
    """core.hooksPath set anywhere but a repository's own hooks folder means
    its wall check never runs: from the repository's config, the user's or the
    system's."""

    def setUp(self):
        super().setUp()
        env = mock.patch.dict(os.environ, NO_USER_GIT)
        env.start()
        self.addCleanup(env.stop)
        real_repo(self.work)
        install_wall_hook(self.work)
        real_repo(self.root / "Wikis")

    def test_own_hooks_are_clean(self):
        self.assertClean("hooks")
        git(self.work, "config", "core.hooksPath", ".git/hooks")
        self.assertClean("hooks")
        git(self.work, "config", "core.hooksPath", str(self.work / ".git" / "hooks"))
        self.assertClean("hooks")

    def test_repository_setting(self):
        git(self.work, "config", "core.hooksPath", "/nowhere/hooks")
        found = self.findings("hooks", "warning")
        self.assertEqual(["Zones/Work"], [f.path for f in found])
        self.assertIn("/nowhere/hooks", found[0].message)
        self.assertIn("wall check", found[0].message)
        self.assertIn("git config core.hooksPath .git/hooks", found[0].message)
        self.assertEqual("Git skips the wall check in the Work zone", found[0].ear)

    def test_user_setting_reaches_every_repository(self):
        config = write(self.root.parent / "user.gitconfig", "[core]\n\thooksPath = ~/.githooks\n")
        with mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": str(config)}):
            found = self.findings("hooks", "warning")
            self.assertEqual(["Wikis", "Zones/Work"], sorted(f.path for f in found))  # Personal is not a repository here
            git(self.work, "config", "core.hooksPath", ".git/hooks")  # the fix the message gives
            self.assertEqual(["Wikis"], [f.path for f in self.findings("hooks")])

    def test_a_folder_that_runs_the_wall_check_is_fine(self):
        shared = self.root.parent / "hooks"
        write(shared / "pre-commit", WALL_HOOK).chmod(0o755)
        git(self.work, "config", "core.hooksPath", str(shared))
        self.assertClean("hooks")
        (shared / "pre-commit").write_text("#!/bin/sh\nexit 0\n")
        self.assertEqual(["Zones/Work"], [f.path for f in self.findings("hooks")])


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class TestMeetingsInbox(GapCase):
    """Transcripts wait in Wikis/Meetings/raw/inbox/ and, like a zone's Inbox,
    never enter any history."""

    def setUp(self):
        super().setUp()
        self.wikis = self.root / "Wikis"
        self.inbox = self.meetings / "raw" / "inbox"
        real_repo(self.wikis)
        write(self.wikis / ".gitignore", "Meetings/raw/inbox/*\n!Meetings/raw/inbox/.gitkeep\n")  # as installed
        commit_all(self.wikis, "start")

    def test_a_transcript_waiting_is_untracked_and_clean(self):
        write(self.inbox / "Theo call 2026-03-20.vtt", "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHello.\n")
        self.assertEqual("", git(self.wikis, "status", "--porcelain"))
        commit_all(self.wikis, "nothing to add")
        self.assertEqual("Meetings/raw/inbox/.gitkeep\n", git(self.wikis, "ls-files", "Meetings/raw/inbox"))
        self.assertClean("inbox")

    def test_something_committed_there_is_an_error(self):
        write(self.inbox / "call.vtt", "WEBVTT\n")
        git(self.wikis, "add", "-f", "Meetings/raw/inbox/call.vtt")
        commit_all(self.wikis, "forced in")
        found = self.findings("inbox", "error")
        self.assertEqual(["Wikis/Meetings/raw/inbox/call.vtt"], [f.path for f in found])
        self.assertIn("never committed", found[0].message)
        self.assertEqual("Something in the Meetings inbox was committed", found[0].ear)

    def test_a_recording_instead_of_its_transcript(self):
        write(self.inbox / "call.m4a", "")
        found = self.findings("inbox")
        self.assertEqual([("warning", "Wikis/Meetings/raw/inbox/call.m4a")], [(f.severity, f.path) for f in found])
        self.assertIn("transcript", found[0].message)

    def test_staged_transcript_is_refused(self):
        write(self.inbox / "call.vtt", "WEBVTT\n")
        git(self.wikis, "add", "-f", "Meetings/raw/inbox/call.vtt")
        found = check.run_checks(self.root, staged=self.wikis)
        self.assertEqual([("error", "inbox", "Wikis/Meetings/raw/inbox/call.vtt")],
                         [(f.severity, f.check, f.path) for f in found])


if __name__ == "__main__":
    unittest.main()
