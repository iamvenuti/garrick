"""`--expect-plan` of scaffold.py's rename and move, and `plan_digest` of the page action's (C5): the plan is made again under the
zone's lock, just before the first write, and a note saved since the plan was shown refuses the change and writes nothing.

    cd tests && python3 -m unittest test_scaffold_expect_plan
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import unittest
from unittest import mock

sys.dont_write_bytecode = True

from test_scaffold_manage import ManageCase, pa  # noqa: E402

SAID = "Not changed: a note was saved after the plan was made. Check it again."


class Expect(ManageCase):
    def setUp(self):
        super().setUp()
        spec = importlib.util.spec_from_file_location("scaffold_expect", str(self.root / "System" / "tools" / "scaffold.py"))
        self.sc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.sc)
        r = self.scaffold("project", "--zone", "Work", "--name", "Apex", "--party", "acme", "--thread", "Kickoff")
        self.assertEqual(0, r.returncode, r.stderr)
        self.commit("Apex")

    def digest(self, *args):
        r = self.scaffold("--today", "2027-01-01", *args, "--plan")
        self.assertEqual(0, r.returncode, r.stderr)
        return json.loads(r.stdout)["digest"]

    def shown(self, verb, **fields):
        """The digest the page action's own check gives, as the extra reads it: the plan of today's date."""
        out, _, _ = pa.perform(self.root, dict(verb="check-name", kind=verb, zone="Work", project="Acme", plan=True, **fields),
                               pa.ops_lib(self.root), via="remote")
        self.assertTrue(out["ok"], out)
        return out["plan"]["digest"]

    def snapshot(self):
        return (self.git("rev-parse", "HEAD").stdout, self.git("status", "--porcelain").stdout)

    def run_in_process(self, argv, save):
        """The command run in this process, with `save` called where a note could be saved: after the checks, before the write."""
        err = io.StringIO()
        with mock.patch.object(self.sc, "mid_turn", lambda root, folder: save() and False), contextlib.redirect_stderr(err), \
                contextlib.redirect_stdout(io.StringIO()):
            try:
                code = self.sc.main(["--root", str(self.root), "--today", "2027-01-01", *argv])
            except SystemExit as e:
                code = e.code
        return code, err.getvalue()

    def save_a_note(self):
        self.freight.write_text(self.freight.read_text() + "\nAlso see [[Pricing]] for the lanes.\n")
        return True


RENAME = ["rename", "--zone", "Work", "--project", "Acme", "--thread", "Pricing", "--to", "Rates"]
MOVE = ["move", "--zone", "Work", "--project", "Acme", "--thread", "Freight", "--to", "Apex"]


class TestTheRecheck(Expect):
    def test_a_note_saved_after_the_plan_refuses_a_rename_and_writes_nothing(self):
        digest = self.digest(*RENAME)
        before = self.snapshot()
        code, err = self.run_in_process([*RENAME, "--expect-plan", digest], self.save_a_note)
        self.assertNotEqual(0, code)
        self.assertIn(SAID, err)
        head, status = self.snapshot()
        self.assertEqual(before[0], head)
        self.assertEqual(["Acme/Threads/Freight/Freight.md"], [l[3:] for l in status.splitlines()])        # only the saved note
        self.assertTrue((self.work / "Acme" / "Threads" / "Pricing").is_dir())
        self.assertFalse((self.work / "Acme" / "Threads" / "Rates").exists())

    def test_a_note_saved_after_the_plan_refuses_a_move_and_writes_nothing(self):
        digest = self.digest(*MOVE)
        head = self.git("rev-parse", "HEAD").stdout
        code, err = self.run_in_process([*MOVE, "--expect-plan", digest], self.save_a_note)
        self.assertNotEqual(0, code)
        self.assertIn(SAID, err)
        self.assertEqual(head, self.git("rev-parse", "HEAD").stdout)
        self.assertTrue((self.work / "Acme" / "Threads" / "Freight").is_dir())
        self.assertFalse((self.work / "Apex" / "Threads" / "Freight").exists())

    def test_the_same_rename_with_an_unchanged_plan_goes_through(self):
        digest = self.digest(*RENAME)
        r = self.scaffold("--today", "2027-01-01", *RENAME, "--expect-plan", digest)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertTrue((self.work / "Acme" / "Threads" / "Rates").is_dir())

    def test_the_same_move_with_an_unchanged_plan_goes_through(self):
        digest = self.digest(*MOVE)
        r = self.scaffold("--today", "2027-01-01", *MOVE, "--expect-plan", digest)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertTrue((self.work / "Apex" / "Threads" / "Freight").is_dir())

    def test_a_move_with_a_digest_lists_each_unresolved_link_once_as_without(self):
        self.freight.write_text(self.freight.read_text() + "\nSee [gone](../Gone/Freight/x.md).\n")
        self.commit("A link that leads nowhere")
        digest = self.digest(*MOVE)
        twin = self.scaffold("--today", "2027-01-01", *MOVE, "--expect-plan", digest)
        self.assertEqual(0, twin.returncode, twin.stderr)
        line = next(l for l in twin.stdout.splitlines() if l.startswith("Markdown links left as they are"))
        self.assertEqual(1, line.count("../Gone/Freight/x.md"), line)
        self.assertNotIn("more", line)

    def test_with_no_digest_a_note_saved_late_is_carried_along_as_before(self):
        code, err = self.run_in_process(MOVE, lambda: False)
        self.assertEqual(0, code or 0, err)

    def test_a_digest_that_is_not_one_is_refused_before_anything_is_read(self):
        r = self.scaffold(*RENAME, "--expect-plan", "abc")
        self.assertNotEqual(0, r.returncode)
        self.assertIn("64 hexadecimal", r.stderr)
        self.assertTrue((self.work / "Acme" / "Threads" / "Pricing").is_dir())


class TestThePageAction(Expect):
    def test_a_request_with_a_stale_digest_is_refused_in_the_fixed_sentence(self):
        digest = self.shown("rename", thread="Pricing", to="Rates")
        self.freight.write_text(self.freight.read_text() + "\nAlso see [[Pricing]] for the lanes.\n")
        self.commit("A note saved and committed")
        head = self.git("rev-parse", "HEAD").stdout
        out, _, _ = pa.perform(self.root, dict(verb="rename", zone="Work", project="Acme", thread="Pricing", to="Rates",
                                               plan_digest=digest), pa.ops_lib(self.root), via="remote")
        self.assertFalse(out["ok"], out)
        self.assertEqual(SAID, out["say"])
        self.assertEqual(head, self.git("rev-parse", "HEAD").stdout)
        self.assertTrue((self.work / "Acme" / "Threads" / "Pricing").is_dir())

    def test_a_request_with_the_digest_of_the_plan_goes_through_and_one_without_is_as_before(self):
        digest = self.shown("move", thread="Freight", to="Apex")
        out, _, _ = pa.perform(self.root, dict(verb="move", zone="Work", project="Acme", thread="Freight", to="Apex",
                                               plan_digest=digest), pa.ops_lib(self.root), via="remote")
        self.assertTrue(out["ok"], out)
        out, _, _ = pa.perform(self.root, dict(verb="rename", zone="Work", project="Acme", thread="Pricing", to="Rates"),
                               pa.ops_lib(self.root), via="remote")
        self.assertTrue(out["ok"], out)

    def test_a_digest_that_is_not_one_is_refused(self):
        out, _, _ = pa.perform(self.root, dict(verb="rename", zone="Work", project="Acme", thread="Pricing", to="Rates",
                                               plan_digest="x"), pa.ops_lib(self.root), via="remote")
        self.assertFalse(out["ok"], out)
        self.assertTrue((self.work / "Acme" / "Threads" / "Pricing").is_dir())


if __name__ == "__main__":
    unittest.main()
