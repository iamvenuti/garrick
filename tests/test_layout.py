"""#604: a project need not start with a thread, and each thread chooses whether it keeps its own papers.

Part 1, making a project. Run from the tests folder: `python3 -m unittest test_layout`.
"""

from __future__ import annotations

import sys
import unittest

sys.dont_write_bytecode = True

from test_setup import Installed  # noqa: E402

import check  # noqa: E402


class LayoutCase(Installed):
    def setUp(self):
        super().setUp()
        self.work = self.root / "Zones" / "Work"

    def scaffold(self, *args):
        return self.run_tool("scaffold.py", *args)

    def make(self, *args):
        r = self.scaffold(*args)
        self.assertEqual(0, r.returncode, r.stderr)
        return r

    def hub_text(self, project):
        return (self.work / project / (project + ".md")).read_text(encoding="utf-8")

    def findings(self, name=None):
        return [f for f in check.run_checks(self.root) if name is None or f.check == name]


class TestMakingAProject(LayoutCase):
    def test_no_thread_makes_one_piece_of_work(self):
        self.make("project", "--zone", "Work", "--name", "Acme")
        folder = self.work / "Acme"
        text = self.hub_text("Acme")
        self.assertIn("### Resume here", text)
        self.assertNotIn("layout:", text)
        self.assertTrue((folder / "Sources").is_dir())
        self.assertTrue((folder / "Deliverables").is_dir())
        self.assertFalse((folder / "Threads").exists())
        self.assertNotIn("<what it produces>", text)
        self.assertEqual([], [f for f in self.findings("projects") if f.path.endswith("Acme")])

    def test_a_heading_has_no_resume_point_and_no_papers(self):
        self.make("project", "--zone", "Work", "--name", "Birch", "--heading")
        folder = self.work / "Birch"
        text = self.hub_text("Birch")
        self.assertIn("layout: thread-first", text)
        self.assertNotIn("### Resume here", text)
        self.assertFalse((folder / "Sources").exists())
        self.assertFalse((folder / "Deliverables").exists())
        self.assertFalse((folder / "Threads").exists())
        self.assertEqual([], [f for f in self.findings() if "Birch" in f.path and f.check in ("projects", "threads")])

    def test_a_piece_of_work_with_no_resume_point_still_warns(self):
        self.make("project", "--zone", "Work", "--name", "Acme")
        hub = self.work / "Acme" / "Acme.md"
        hub.write_text(hub.read_text().replace("### Resume here", "### Notes"))
        self.assertTrue([f for f in self.findings("projects") if "no threads" in f.message])

    def test_with_a_thread_it_is_as_it_was(self):
        self.make("project", "--zone", "Work", "--name", "Cedar", "--thread", "Pricing")
        text = self.hub_text("Cedar")
        self.assertNotIn("### Resume here", text)
        self.assertIn("[[Cedar/Threads/Pricing/Pricing|Pricing]]", text)
        self.assertTrue((self.work / "Cedar" / "Threads" / "Pricing" / "Pricing.md").is_file())
        self.assertTrue((self.work / "Cedar" / "Sources").is_dir())
        self.assertTrue((self.work / "Cedar" / "Deliverables").is_dir())

    def test_a_heading_may_start_with_a_thread(self):
        self.make("project", "--zone", "Work", "--name", "Maple", "--heading", "--thread", "Pricing")
        self.assertIn("layout: thread-first", self.hub_text("Maple"))
        self.assertTrue((self.work / "Maple" / "Threads" / "Pricing" / "Pricing.md").is_file())

    def test_check_writes_nothing(self):
        r = self.make("project", "--zone", "Work", "--name", "Harbour", "--heading", "--check")
        self.assertIn("a heading over separate pieces of work", r.stdout)
        self.assertFalse((self.work / "Harbour").exists())

    def test_a_first_thread_name_alone_is_refused_when_it_is_not_given(self):
        r = self.scaffold("project", "--zone", "Work", "--name", "Dana", "--thread-spoken", "pricing")
        self.assertEqual(1, r.returncode)


if __name__ == "__main__":
    unittest.main()
