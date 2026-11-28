"""`--plan` of scaffold.py's rename and move (#724): what the change would write, as JSON, with nothing written.

    cd tests && python3 -m unittest test_scaffold_plan

The plan asks the same function the change writes with, so the notes it lists are the files the commit then changes.
"""

from __future__ import annotations

import json
import sys
import unittest

sys.dont_write_bytecode = True

from test_scaffold_manage import ManageCase, pa  # noqa: E402


class PlanCase(ManageCase):
    def plan(self, *args):
        r = self.scaffold("--today", "2027-01-01", *args, "--plan")
        self.assertEqual(0, r.returncode, r.stderr)
        return json.loads(r.stdout)

    def changed(self):
        return set(self.git("show", "--name-only", "--format=", "HEAD").stdout.split())

    def snapshot(self):
        return (self.git("rev-parse", "HEAD").stdout, self.git("status", "--porcelain", "--ignored").stdout)


class TestRenamePlan(PlanCase):
    def test_a_plan_writes_nothing(self):
        before = self.snapshot()
        got = self.plan("rename", "--zone", "Work", "--project", "Acme", "--thread", "Pricing", "--to", "Rates")
        self.assertEqual(before, self.snapshot())
        self.assertEqual({"from": "Acme/Threads/Pricing", "to": "Acme/Threads/Rates"}, got["paths"][0])
        self.assertTrue(got["count"] >= 1)

    def test_the_plan_lists_the_notes_and_lines_the_rename_then_changes(self):
        got = self.plan("rename", "--zone", "Work", "--project", "Acme", "--thread", "Pricing", "--to", "Rates")
        listed = {f["path"] for f in got["files"]}
        r = self.scaffold("--today", "2027-01-01", "rename", "--zone", "Work", "--project", "Acme", "--thread", "Pricing",
                          "--to", "Rates")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual(listed, {p for p in self.changed() if p.endswith(".md")})
        self.assertIn("Acme/Threads/Freight/Freight.md", listed)
        freight = next(f for f in got["files"] if f["path"].endswith("Freight/Freight.md"))
        self.assertIn("[[Pricing]]", json.dumps(freight["edits"]))

    def test_a_project_plan_lists_its_threads(self):
        got = self.plan("rename", "--zone", "Work", "--project", "Acme", "--to", "Acme Freight")
        self.assertEqual({"from": "Acme", "to": "Acme Freight"}, got["paths"][0])
        self.assertTrue(any("Acme Freight/Threads/Freight/Freight.md" == f["path"] for f in got["files"]))

    def test_the_refusals_of_the_rename_are_the_plans_too(self):
        (self.work / "Acme" / "Threads" / "Pricing" / "Pricing.md").write_text("changed\n")
        r = self.scaffold("rename", "--zone", "Work", "--project", "Acme", "--thread", "Pricing", "--to", "Rates", "--plan")
        self.assertEqual(1, r.returncode)
        self.assertIn("has changes not committed", r.stderr)
        r = self.scaffold("rename", "--zone", "Work", "--project", "Acme", "--thread", "Freight", "--to", "Pricing", "--plan")
        self.assertEqual(1, r.returncode)


class TestMovePlan(PlanCase):
    def setUp(self):
        super().setUp()
        r = self.scaffold("project", "--zone", "Work", "--name", "Apex", "--party", "acme", "--thread", "Kickoff")
        self.assertEqual(0, r.returncode, r.stderr)
        self.commit("Apex")

    def test_a_plan_writes_nothing_and_names_the_hubs(self):
        before = self.snapshot()
        got = self.plan("move", "--zone", "Work", "--project", "Acme", "--thread", "Freight", "--to", "Apex")
        self.assertEqual(before, self.snapshot())
        self.assertEqual({"from": "Acme/Threads/Freight", "to": "Apex/Threads/Freight"}, got["paths"][0])
        self.assertEqual({"leaves": "Acme/Acme.md", "enters": "Apex/Apex.md"}, got["hubs"])

    def test_the_plan_lists_the_notes_the_move_then_changes(self):
        got = self.plan("move", "--zone", "Work", "--project", "Acme", "--thread", "Freight", "--to", "Apex")
        listed = {f["path"] for f in got["files"]}
        r = self.scaffold("--today", "2027-01-01", "move", "--zone", "Work", "--project", "Acme", "--thread", "Freight",
                          "--to", "Apex")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual(listed, {p for p in self.changed() if p.endswith(".md")})

    def test_the_refusals_of_the_move_are_the_plans_too(self):
        r = self.scaffold("move", "--zone", "Work", "--project", "Acme", "--thread", "Freight", "--to", "Nowhere", "--plan")
        self.assertEqual(1, r.returncode)
        self.assertIn("There is no project called Nowhere", r.stderr)


class TestTheHeardName(PlanCase):
    """A rename adds the old name as a heard name, which changes how a spoken name is read in every zone. The App does; a remote
    assistant never does (#724)."""

    def tables(self):
        return {n: (self.root / "System" / n).read_text(encoding="utf-8") for n in ("context.md", "names.md")
                if (self.root / "System" / n).is_file()}

    def test_scaffold_adds_it_and_the_flag_leaves_it_out(self):
        before = self.tables()
        r = self.scaffold("rename", "--zone", "Work", "--project", "Acme", "--thread", "Pricing", "--to", "Rates", "--no-alias")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual(before, self.tables())
        self.assertNotIn("heard name", r.stdout)
        r = self.scaffold("rename", "--zone", "Work", "--project", "Acme", "--thread", "Freight", "--to", "Lanes")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertNotEqual(before, self.tables())
        self.assertIn("freight", "".join(self.tables().values()).lower())

    def test_the_page_action_writes_it_for_the_page_and_not_for_a_remote_caller(self):
        before = self.tables()
        out, _, _ = pa.perform(self.root, dict(verb="rename", zone="Work", project="Acme", thread="Pricing", to="Rates"),
                               pa.ops_lib(self.root), via="remote")
        self.assertTrue(out["ok"], out)
        self.assertEqual(before, self.tables())
        self.assertEqual(self.git("rev-parse", "HEAD").stdout.strip(), out["commit"])
        out, _, _ = pa.perform(self.root, dict(verb="rename", zone="Work", project="Acme", thread="Freight", to="Lanes"),
                               pa.ops_lib(self.root), via="page")
        self.assertTrue(out["ok"], out)
        self.assertNotEqual(before, self.tables())


if __name__ == "__main__":
    unittest.main()
