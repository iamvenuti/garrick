"""Making, renaming and deleting projects and threads: scaffold.py's
`--check`, `rename` and `delete`, in a workspace the installer made.

    python3 -m unittest discover -s tests
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest

sys.dont_write_bytecode = True

from test_setup import Installed  # noqa: E402

import importlib.util  # noqa: E402
import os  # noqa: E402
from pathlib import Path  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("garrick_page_action_manage", str(REPO / "extras" / "status" / "page_action.py"))
pa = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pa)


class ManageCase(Installed):
    def setUp(self):
        super().setUp()
        self.work = self.root / "Zones" / "Work"
        r = self.run_tool("scaffold.py", "project", "--zone", "Work", "--name", "Acme", "--party", "acme",
                          "--thread", "Pricing")
        self.assertEqual(0, r.returncode, r.stderr)
        r = self.run_tool("scaffold.py", "thread", "--zone", "Work", "--project", "Acme", "--name", "Freight")
        self.assertEqual(0, r.returncode, r.stderr)
        self.freight = self.work / "Acme" / "Threads" / "Freight" / "Freight.md"
        self.freight.write_text(self.freight.read_text() + "\nSee [[Pricing]] and [[Acme/Threads/Pricing/Pricing|Pricing]].\n")
        todo = self.work / "Todo.md"
        todo.write_text(todo.read_text().replace("## Inbox\n", "## Inbox\n\n- [ ] [[Pricing]]: call Dana 📅 2026-10-20\n"
                                                 "- [ ] [[Freight]]: send the lanes\n- [x] [[Freight]]: old one ✅ 2026-10-01\n", 1))
        self.commit("Acme set up")

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=str(self.work), capture_output=True, text=True, env=self.env)

    def commit(self, message):
        self.git("add", "-A")
        r = self.git("commit", "-q", "-m", message)
        self.assertEqual(0, r.returncode, r.stderr + r.stdout)

    def scaffold(self, *args):
        return self.run_tool("scaffold.py", *args)


class TestCheck(ManageCase):
    def test_check_says_whether_a_name_would_do_and_makes_nothing(self):
        r = self.scaffold("thread", "--zone", "Work", "--project", "Acme", "--name", "Renewal", "--check")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("will do", r.stdout)
        self.assertFalse((self.work / "Acme" / "Threads" / "Renewal").exists())
        r = self.scaffold("thread", "--zone", "Work", "--project", "Acme", "--name", "Prising", "--check")
        self.assertEqual(1, r.returncode)
        self.assertIn("sounds too much like Pricing", r.stderr)
        r = self.scaffold("project", "--zone", "Work", "--name", "Birch", "--party", "birch", "--thread", "Q3",
                          "--check")
        self.assertEqual(1, r.returncode)
        self.assertFalse((self.work / "Birch").exists())
        self.assertEqual("", self.git("status", "--porcelain").stdout)


class TestRename(ManageCase):
    def test_a_thread_and_every_link_to_it(self):
        r = self.scaffold("rename", "--zone", "Work", "--project", "Acme", "--thread", "Pricing", "--to", "Renewal")
        self.assertEqual(0, r.returncode, r.stderr)
        note = self.work / "Acme" / "Threads" / "Renewal" / "Renewal.md"
        self.assertTrue(note.is_file())
        self.assertFalse((self.work / "Acme" / "Threads" / "Pricing").exists())
        text = note.read_text()
        self.assertIn("title: Renewal", text)
        self.assertIn("\n# Renewal\n", text)
        self.assertIn("Renamed from Pricing.", text)
        self.assertIn("[[Acme/Threads/Renewal/Renewal|Renewal]]", (self.work / "Acme" / "Acme.md").read_text())
        self.assertIn("- [ ] [[Renewal]]: call Dana", (self.work / "Todo.md").read_text())
        self.assertIn("See [[Renewal]] and [[Acme/Threads/Renewal/Renewal|Renewal]].", self.freight.read_text())
        self.assertEqual("", self.git("status", "--porcelain").stdout)                   # one commit, all of it
        self.assertIn("Acme, Pricing: renamed Renewal", self.git("log", "-1", "--format=%s").stdout)
        self.assertIn("Renamed from Pricing.", self.git("log", "-1", "--follow", "-p", "--format=", "--",
                                                        "Acme/Threads/Renewal/Renewal.md").stdout)
        self.assertIn("| pricing | Renewal |", (self.root / "System" / "context.md").read_text())
        found = json.loads(self.run_tool("check.py", "--json").stdout)["findings"]
        self.assertEqual([], [f for f in found if f["severity"] == "error" and "Work" in f["path"]])

    def test_a_project_and_its_threads(self):
        r = self.scaffold("rename", "--zone", "Work", "--project", "Acme", "--to", "Apex")
        self.assertEqual(0, r.returncode, r.stderr)
        hub = self.work / "Apex" / "Apex.md"
        self.assertTrue(hub.is_file())
        self.assertIn("[[Apex/Threads/Pricing/Pricing|Pricing]]", hub.read_text())
        self.assertIn('project: "[[Apex]]"', self.freight.parent.parent.parent.parent.joinpath(
            "Apex", "Threads", "Freight", "Freight.md").read_text())
        self.assertIn("[[Apex/Threads/Pricing/Pricing|Pricing]]",
                      (self.work / "Apex" / "Threads" / "Freight" / "Freight.md").read_text())
        self.assertEqual("", self.git("status", "--porcelain").stdout)

    def test_refusals_change_nothing(self):
        cases = [
            (["--thread", "Pricing", "--to", "Freight"], "already has a thread called Freight"),
            (["--thread", "Pricing", "--to", "Q3 2026"], "will not work"),
            (["--thread", "Pricing", "--to", "Fraight"], "sounds too much like Freight"),
        ]
        for extra, said in cases:
            r = self.scaffold("rename", "--zone", "Work", "--project", "Acme", *extra)
            self.assertEqual(1, r.returncode, extra)
            self.assertIn(said, r.stderr)
        self.freight.write_text(self.freight.read_text() + "An edit not committed.\n")
        r = self.scaffold("rename", "--zone", "Work", "--project", "Acme", "--thread", "Pricing", "--to", "Renewal")
        self.assertEqual(1, r.returncode)
        self.assertIn("not committed", r.stderr)
        self.assertTrue((self.work / "Acme" / "Threads" / "Pricing" / "Pricing.md").is_file())

    def test_a_refused_commit_puts_everything_back(self):
        hook = self.work / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\necho refused >&2\nexit 1\n")
        hook.chmod(0o755)
        before = self.git("ls-files", "-s").stdout
        r = self.scaffold("rename", "--zone", "Work", "--project", "Acme", "--thread", "Pricing", "--to", "Renewal")
        self.assertEqual(1, r.returncode)
        self.assertIn("nothing changed", r.stderr)
        self.assertEqual(before, self.git("ls-files", "-s").stdout)
        self.assertEqual("", self.git("status", "--porcelain").stdout)
        self.assertFalse((self.work / "Acme" / "Threads" / "Renewal").exists())


class TestDelete(ManageCase):
    def test_without_confirm_it_only_says_what_would_go(self):
        r = self.scaffold("delete", "--zone", "Work", "--project", "Acme", "--thread", "Freight")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("its line in the hub", r.stdout)
        self.assertIn("1 open line in Todo.md", r.stdout)
        self.assertIn("[[Freight]]: send the lanes", r.stdout)
        self.assertIn('--confirm "Freight"', r.stdout)
        self.assertTrue(self.freight.is_file())
        r = self.scaffold("delete", "--zone", "Work", "--project", "Acme", "--thread", "Freight", "--confirm", "freight")
        self.assertEqual(1, r.returncode)
        self.assertTrue(self.freight.is_file())

    def test_confirmed_it_goes_in_one_commit_and_a_revert_brings_it_back(self):
        before = self.git("ls-files", "-s").stdout
        r = self.scaffold("delete", "--zone", "Work", "--project", "Acme", "--thread", "Freight", "--confirm", "Freight")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertFalse(self.freight.parent.exists())
        self.assertNotIn("Threads/Freight/", (self.work / "Acme" / "Acme.md").read_text())
        todo = (self.work / "Todo.md").read_text()
        self.assertNotIn("send the lanes", todo)
        self.assertIn("[x] [[Freight]]: old one", todo)                  # a done line is the record: it stays
        self.assertIn("removed: - [ ] [[Freight]]: send the lanes", r.stdout)
        self.assertIn("- [ ] [[Freight]]: send the lanes", self.git("log", "-1", "--format=%b").stdout)
        self.assertEqual("", self.git("status", "--porcelain").stdout)
        commit = self.git("rev-parse", "--short", "HEAD").stdout.strip()
        self.assertIn("scaffold.py undo --zone Work --commit " + commit, r.stdout)
        r = self.scaffold("undo", "--zone", "Work", "--commit", commit)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual(before, self.git("ls-files", "-s").stdout)
        r = self.scaffold("undo", "--zone", "Work", "--commit", commit)             # no longer the last commit
        self.assertEqual(1, r.returncode)
        self.assertIn("no longer the last commit", r.stderr)

    def test_a_whole_project(self):
        r = self.scaffold("delete", "--zone", "Work", "--project", "Acme")
        self.assertIn("with its threads", r.stdout)
        self.assertIn("2 open lines in Todo.md", r.stdout)
        r = self.scaffold("delete", "--zone", "Work", "--project", "Acme", "--confirm", "Acme")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertFalse((self.work / "Acme").exists())
        self.assertNotIn("- [ ] [[Pricing]]", (self.work / "Todo.md").read_text())


class TestWhatCannotBeBroughtBack(ManageCase):
    """A rename or deletion refuses whatever a revert could not restore."""

    def test_ignored_files_and_a_nested_repository_are_refused_and_kept(self):
        acme = self.work / "Acme"
        (self.work / ".gitignore").write_text((self.work / ".gitignore").read_text() + "Acme/build/\n")
        self.commit("ignore build")
        (acme / "build").mkdir()
        (acme / "build" / "out.bin").write_bytes(b"x")
        for args in (["delete", "--zone", "Work", "--project", "Acme", "--confirm", "Acme"],
                     ["rename", "--zone", "Work", "--project", "Acme", "--to", "Apex"]):
            r = self.scaffold(*args)
            self.assertEqual(1, r.returncode, args)
            self.assertIn("not in the zone's history", r.stderr)
        self.assertTrue((acme / "build" / "out.bin").exists())
        (acme / "build" / "out.bin").unlink()
        (acme / "build").rmdir()
        repo = acme / "Site"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=str(repo), env=self.env, check=True)
        r = self.scaffold("delete", "--zone", "Work", "--project", "Acme", "--confirm", "Acme")
        self.assertEqual(1, r.returncode)
        self.assertIn("repository of its own", r.stderr)
        self.assertTrue((repo / ".git").is_dir())

    def test_something_staged_elsewhere_is_never_swept_in(self):
        (self.work / "Birch Sources").mkdir()
        (self.work / "Birch Sources" / "contract.pdf").write_bytes(b"%PDF staged by hand")
        self.git("add", "Birch Sources/contract.pdf")
        r = self.scaffold("rename", "--zone", "Work", "--project", "Acme", "--thread", "Pricing", "--to", "Renewal")
        self.assertEqual(1, r.returncode)
        self.assertIn("staged", r.stderr)

    def test_a_thread_of_the_same_name_in_another_project_is_left_alone(self):
        r = self.scaffold("project", "--zone", "Work", "--name", "Birch", "--party", "birch", "--thread", "Pricing")
        self.assertEqual(0, r.returncode, r.stderr)
        todo = self.work / "Todo.md"
        todo.write_text(todo.read_text().replace("## Inbox\n", "## Inbox\n\n- [ ] [[Birch/Threads/Pricing/Pricing|Pricing]]: Birch's\n", 1))
        self.commit("Birch")
        r = self.scaffold("delete", "--zone", "Work", "--project", "Acme", "--thread", "Pricing", "--confirm", "Pricing")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("Birch's", todo.read_text())                              # another thread's line stays
        self.assertIn("[[Pricing]]: call Dana", todo.read_text())               # ambiguous now: left, not guessed

    def test_renaming_a_project_leaves_a_thread_that_shares_its_name(self):
        for project in ("Pallets", "Ledger"):
            r = self.scaffold("project", "--zone", "Work", "--name", project, "--party", "acme", "--thread", "Pallets")
            self.assertEqual(0, r.returncode, r.stderr)
        self.commit("two projects with a Pallets thread")
        r = self.scaffold("rename", "--zone", "Work", "--project", "Pallets", "--to", "Crates")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("[[Ledger/Threads/Pallets/Pallets|Pallets]]", (self.work / "Ledger" / "Ledger.md").read_text())
        self.assertIn("[[Crates/Threads/Pallets/Pallets|Pallets]]", (self.work / "Crates" / "Crates.md").read_text())


class TestFromThePage(ManageCase):
    """The page's buttons run scaffold.py and nothing else."""

    def setUp(self):
        super().setUp()
        os.environ["GARRICK_JOBS_DIR"] = str(self.base / "jobs")

    def act(self, **req):
        return pa.act(self.root, req)

    def test_new_project_and_thread_match_the_script_and_are_committed(self):
        said = self.act(verb="check-name", kind="thread", zone="Work", project="Acme", name="Renewal")
        self.assertIn("will do", said)
        with self.assertRaisesRegex(pa.Refused, "sounds too much like Pricing"):
            self.act(verb="check-name", kind="thread", zone="Work", project="Acme", name="Prising")
        self.assertIn("Created thread Renewal", self.act(verb="new-thread", zone="Work", project="Acme", name="Renewal"))
        self.assertIn("Created project Birch", self.act(verb="new-project", zone="Work", name="Birch", party="birch",
                                                         thread="Launch Plan"))
        self.assertEqual("", self.git("status", "--porcelain").stdout)
        self.assertIn("New project Birch (birch), first thread Launch Plan", self.git("log", "-1", "--format=%s").stdout)
        self.assertTrue((self.work / "Birch" / "Threads" / "Launch Plan" / "Launch Plan.md").is_file())
        found = json.loads(self.run_tool("check.py", "--json").stdout)["findings"]
        self.assertEqual([], [f for f in found if f["severity"] == "error" and "Work" in f["path"]])

    def slow_hook(self, seconds):
        """The zone's own wall check, after `seconds` of sleep: a workspace whose check takes that long."""
        hook = Path(self.git("rev-parse", "--git-path", "hooks/pre-commit").stdout.strip())
        hook = hook if hook.is_absolute() else self.work / hook
        shipped = hook.read_text()
        hook.write_text(shipped.replace("\n", "\nsleep %s\n" % seconds, 1))
        return hook, shipped

    def test_a_wall_check_slower_than_a_git_command_still_commits(self):
        self.slow_hook(4)
        real = pa.GIT_TIMEOUT, pa.COMMIT_TIMEOUT
        pa.GIT_TIMEOUT, pa.COMMIT_TIMEOUT = 2, 60
        try:
            self.assertIn("Created project Birch", self.act(verb="new-project", zone="Work", name="Birch", party="birch",
                                                             thread="Launch Plan"))
        finally:
            pa.GIT_TIMEOUT, pa.COMMIT_TIMEOUT = real
        self.assertEqual("", self.git("status", "--porcelain").stdout)
        self.assertIn("New project Birch (birch), first thread Launch Plan", self.git("log", "-1", "--format=%s").stdout)

    def test_a_wall_check_stopped_leaves_the_files_for_a_commit_by_hand(self):
        hook, shipped = self.slow_hook(30)
        real, pa.COMMIT_TIMEOUT = pa.COMMIT_TIMEOUT, 2
        try:
            with self.assertRaisesRegex(pa.Refused, "^made, but not committed: the wall check was still running after "
                                        "2 s and was stopped. The files are there, unstaged; commit them by hand: that "
                                        "commit waits for the check and goes through$"):
                self.act(verb="new-project", zone="Work", name="Birch", party="birch", thread="Launch Plan")
        finally:
            pa.COMMIT_TIMEOUT = real
        self.assertTrue((self.work / "Birch" / "Threads" / "Launch Plan" / "Launch Plan.md").is_file())
        self.assertEqual("?? Birch/\n", self.git("status", "--porcelain").stdout)
        self.assertFalse((self.work / ".git" / "index.lock").exists())
        hook.write_text(shipped.replace("\n", "\nsleep 3\n", 1))     # by hand, git waits as long as the check takes
        self.commit("New project Birch")
        self.assertEqual("", self.git("status", "--porcelain").stdout)

    def test_rename_delete_and_undo(self):
        self.assertIn("Renamed the thread Pricing to Renewal",
                      self.act(verb="rename", zone="Work", project="Acme", thread="Pricing", to="Renewal"))
        listed = self.act(verb="delete", zone="Work", project="Acme", thread="Freight")
        self.assertIn("Nothing was deleted", listed)
        said = self.act(verb="delete", zone="Work", project="Acme", thread="Freight", confirm="Freight")
        commit = self.git("rev-parse", "--short", "HEAD").stdout.strip()
        self.assertIn(commit, said)
        self.assertIn("Undone", self.act(verb="undo", zone="Work", commit=commit))
        self.assertTrue(self.freight.is_file())
        for bad in ({"verb": "undo", "zone": "Work", "commit": "HEAD~1"},
                    {"verb": "rename", "zone": "Work", "project": "Acme", "to": "--root=/"},
                    {"verb": "new-thread", "zone": "../Personal", "project": "Acme", "name": "X"}):
            with self.assertRaises(pa.Refused):
                pa.act(self.root, bad)


if __name__ == "__main__":
    unittest.main()
