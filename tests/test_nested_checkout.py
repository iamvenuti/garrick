"""A Garrick checkout kept inside a workspace, committing its own files.

The checkout's shipped tree holds the originals of the files every side reads,
so a template or a line of the rules it adds may carry wording the workspace's
own notes already use, and the commit must go through. Everything else it
holds is ordinary project text, and a quotation of real material into one is
refused as before.

Invented parties only: Acme Corp (`acme`), which keeps the checkout, and
Birch & Co (`birch`) on the far side of the wall, as in fixtures.py.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fixtures import HAVE_GIT, build_workspace, commit_all, git, meeting_page, thread_note, write

import check  # noqa: E402  (fixtures puts the tools folder on sys.path)

# The explanation a shipped ledger template carries, written in each project
# before it was shipped: common wording, on both sides of every wall.
LEDGER = ("A row stays here once it is written, so the ledger is the record of what left the building. "
          "Mark a copy that no longer counts rather than striking the row out.")

# New wording for the rules, of the same shape: a shipped line whose words a
# project's notes already use.
RULE = ("Note where the work stands and what the next move is, so a thread can be taken up cold "
        "by whoever opens it next.")

# Wording only Birch's side ever saw. A finding may never repeat it.
BRIEF = ("The partners have agreed to fund the Harlow depot from the spring and to hold the southern "
         "lanes until the freight tender closes")
BRIEF_WORDS = ("harlow", "depot", "tender")

# The checker runs git as the user would; these keep the user's own config out.
NO_USER_GIT = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def build_checkout(top: Path) -> Path:
    """A Garrick checkout: the installer, the VERSION file it stamps into a
    workspace, the tree it copies, and the rest of the source beside them."""
    write(top / "VERSION", "# Which Garrick this is.\ncommit: 0000000\ndate: 2026-03-01\n")
    write(top / "install.py", "# The installer.\n")
    write(top / "update.py", "# The updater.\n")
    write(top / "README.md", "# Garrick\n\nA workspace for an assistant.\n")
    write(top / "CHANGELOG.md", "# Changelog\n\n## [Unreleased]\n")
    write(top / "docs" / "principles.md", "# Principles\n\nWhat the check promises.\n")
    write(top / "tests" / "test_walls.py", "# The suite.\n")
    write(top / "template" / "AGENTS.md", "# Workspace\n")
    write(top / "template" / "System" / "rules.md", "# Rules\n\n## Threads\n\nOne resume point each.\n")
    write(top / "template" / "System" / "templates" / "thread.md", "# A thread\n\n## State of play\n")
    write(top / "template" / "System" / "skills" / "threads" / "SKILL.md", "# Threads\n")
    return top


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class CheckoutCase(unittest.TestCase):
    """Acme keeps a Garrick checkout in its project; Birch's own files, on the
    far side of the wall, already hold the wording the checkout ships."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve() / "Workspace"
        build_workspace(self.root)
        self.work = self.root / "Zones" / "Work"
        self.acme = self.work / "Acme Review"
        self.birch = self.work / "Birch Entry"
        self.meetings = self.root / "Wikis" / "Meetings"
        # Birch's ledger and its notes: the wording the shipped files repeat,
        # and wording that is Birch's alone.
        write(self.birch / "Deliverables" / "published.md", "# Published\n\n" + LEDGER + "\n")
        write(self.birch / "Threads" / "Market Sizing" / "Market Sizing.md",
              thread_note("Birch Entry", "Market Sizing", "birch", RULE + "\n\n" + BRIEF + "."))
        self.checkout = build_checkout(self.acme / "Repo")
        env = mock.patch.dict(os.environ, NO_USER_GIT)
        env.start()
        self.addCleanup(env.stop)
        git(self.checkout, "init", "-q")
        commit_all(self.checkout, "Garrick")

    def tearDown(self):
        check._committing(None)
        self._tmp.cleanup()

    def staged(self):
        """What the commit hook would say about what the checkout has staged."""
        git(self.checkout, "add", "-A")
        return check.run_checks(self.root, staged=self.checkout)

    def refused(self):
        found = self.staged()
        for f in found:
            for word in BRIEF_WORDS:
                self.assertNotIn(word, f.message.lower(), f.message)
                self.assertNotIn(word, f.ear.lower(), f.ear)
        return [(f.severity, f.path) for f in found]

    def allowed(self):
        return [(f.severity, f.path, f.message) for f in self.staged()]


class TestShippedFilesCommit(CheckoutCase):
    """The false positive: a shipped file may carry wording already in use."""

    def test_a_new_template_whose_wording_is_already_used(self):
        write(self.checkout / "template" / "System" / "templates" / "published.md", "# Published\n\n" + LEDGER + "\n")
        self.assertEqual([], self.allowed())

    def test_a_line_added_to_the_shipped_rules(self):
        rules = self.checkout / "template" / "System" / "rules.md"
        rules.write_text(rules.read_text(encoding="utf-8") + "\n" + RULE + "\n", encoding="utf-8")
        self.assertEqual([], self.allowed())

    def test_the_shipped_changelog(self):
        log = self.checkout / "CHANGELOG.md"
        log.write_text(log.read_text(encoding="utf-8") + "\n### Fixed\n\n- " + RULE + "\n", encoding="utf-8")
        self.assertEqual([], self.allowed())

    def test_a_shipped_skill(self):
        write(self.checkout / "template" / "System" / "skills" / "threads" / "SKILL.md", "# Threads\n\n" + RULE + "\n")
        self.assertEqual([], self.allowed())


class TestTheRestOfTheCheckoutIsChecked(CheckoutCase):
    """The true positive: only what a checkout ships is shared wording."""

    def test_documentation_that_quotes_a_project_on_the_far_side(self):
        write(self.checkout / "docs" / "ledgers.md", "# Ledgers\n\n" + BRIEF + ".\n")
        self.assertEqual([("error", "Zones/Work/Acme Review/Repo/docs/ledgers.md")], self.refused())

    def test_documentation_that_quotes_a_meeting_on_the_far_side(self):
        write(self.meetings / "wiki" / "sources" / "260314-birch-call.md",
              meeting_page("Work", "[birch]", "Birch call").replace("Decisions.", BRIEF + "."))
        write(self.checkout / "docs" / "notes.md", "# Notes\n\n" + BRIEF + ".\n")
        found = self.staged()
        self.assertEqual([("error", "Zones/Work/Acme Review/Repo/docs/notes.md")],
                         [(f.severity, f.path) for f in found])
        self.assertIn("meeting 260314-birch-call", found[0].message)

    def test_the_readme_and_the_tests_are_ordinary_files_too(self):
        write(self.checkout / "README.md", "# Garrick\n\n" + BRIEF + ".\n")
        write(self.checkout / "examples" / "demo.md", "# Demo\n\n" + BRIEF + ".\n")
        self.assertEqual([("error", "Zones/Work/Acme Review/Repo/README.md"),
                          ("error", "Zones/Work/Acme Review/Repo/examples/demo.md")], sorted(self.refused()))

    def test_a_repository_that_is_not_a_checkout_ships_nothing(self):
        """The same path in a repository with no installer beside it: an
        ordinary folder that happens to be called `template`."""
        shutil.rmtree(self.checkout / ".git")
        (self.checkout / "install.py").unlink()
        git(self.checkout, "init", "-q")
        commit_all(self.checkout, "Code")
        write(self.checkout / "template" / "System" / "templates" / "published.md", "# Published\n\n" + LEDGER + "\n")
        self.assertEqual([("error", "Zones/Work/Acme Review/Repo/template/System/templates/published.md")],
                         self.refused())

    def test_an_unstaged_edit_to_a_shipped_file_makes_nothing_common(self):
        """Wording is common when the commit holds it, not when the working
        copy does: the shipped file counts as git has it."""
        rules = self.checkout / "template" / "System" / "rules.md"
        write(self.checkout / "docs" / "quoted.md", "# Quoted\n\n" + BRIEF + ".\n")
        git(self.checkout, "add", "--", "docs/quoted.md")
        rules.write_text(rules.read_text(encoding="utf-8") + "\n" + BRIEF + ".\n", encoding="utf-8")
        found = check.run_checks(self.root, staged=self.checkout)
        self.assertEqual([("error", "Zones/Work/Acme Review/Repo/docs/quoted.md")],
                         [(f.severity, f.path) for f in found])


class TestWhatCountsAsACheckout(CheckoutCase):
    """What is found, and what of it is shared."""

    def shared(self):
        ws = check.discover(self.root)
        return {p.relative_to(self.checkout).as_posix() for p in check.shared_files(ws)
                if self.checkout in p.parents}

    def test_a_checkout_is_found_at_its_top(self):
        ws = check.discover(self.root)
        self.assertEqual([self.checkout], check.checkouts(ws))

    def test_a_worktree_of_one_is_a_checkout_too(self):
        other = build_checkout(self.acme / ".worktrees" / "a-branch")
        ws = check.discover(self.root)
        self.assertEqual(sorted([self.checkout, other]), sorted(check.checkouts(ws)))

    def test_what_a_checkout_shares_is_what_it_ships(self):
        found = self.shared()
        self.assertIn("template/System/rules.md", found)
        self.assertIn("template/AGENTS.md", found)
        self.assertIn("template/System/templates/thread.md", found)
        self.assertIn("template/System/skills/threads/SKILL.md", found)
        self.assertIn("CHANGELOG.md", found)
        for name in ("README.md", "docs/principles.md", "tests/test_walls.py", "VERSION", "install.py"):
            self.assertNotIn(name, found)

    def test_a_folder_with_no_installer_is_not_one(self):
        (self.checkout / "install.py").unlink()
        ws = check.discover(self.root)
        self.assertEqual([], check.checkouts(ws))
        self.assertEqual(set(), self.shared())


if __name__ == "__main__":
    unittest.main()
