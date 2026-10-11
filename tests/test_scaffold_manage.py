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


if __name__ == "__main__":
    unittest.main()
