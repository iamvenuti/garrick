"""The commit record against real handlers (#716): park and a tick through page_action's own git, and rename through
scaffold.py's own commit, in a workspace with the real tools.

    python3 -m unittest discover -s tests
"""

from __future__ import annotations

import json
import sys
import unittest

sys.dont_write_bytecode = True

import test_page_action as base       # noqa: E402

pa = base.pa
git = base.git


class TestRealHandlers(base.ActionCase):
    def setUp(self):
        super().setUp()
        self.ops = pa.ops_lib(self.root)
        self.assertIsNotNone(self.ops)
        self._ask = pa.ask_for_page
        pa.ask_for_page = lambda ws: False

    def tearDown(self):
        pa.ask_for_page = self._ask
        super().tearDown()

    def commits(self):
        return int(git(self.work, "rev-list", "--count", "HEAD"))

    def record(self, op):
        return json.loads((self.work / ".git" / "garrick-ops" / (op + ".json")).read_text())

    def test_a_tick_through_the_pages_own_git_carries_the_trailers(self):
        req = {"verb": "todo-done", "zone": "Work", "file": "Todo.md", "key": self.key("Send the revised"), "op": "1234123412341234"}
        out, _, _ = pa.perform(self.root, dict(req), self.ops, via="page")
        self.assertTrue(out["ok"], out)
        self.assertIn("Garrick-Op: 1234123412341234", git(self.work, "log", "-1", "--format=%B"))
        self.assertEqual(self.record("1234123412341234")["result"], "done")

    def test_c3_rename_through_scaffold_carries_the_trailers_and_a_retry_answers_done(self):
        req = {"verb": "rename", "zone": "Work", "project": "Acme Review", "thread": "Pricing", "to": "Cost", "op": "5678567856785678"}
        out, _, _ = pa.perform(self.root, dict(req), self.ops, via="page")
        self.assertTrue(out["ok"], out)
        body = git(self.work, "log", "-1", "--format=%B")
        self.assertIn("Garrick-Op: 5678567856785678", body)
        self.assertIn("Garrick-Payload: " + self.ops.payload_hash("rename", req), body)
        rec = self.record("5678567856785678")
        self.assertEqual((rec["result"], rec["by_head"]), ("done", False))
        n = self.commits()
        again, _, _ = pa.perform(self.root, dict(req), self.ops, via="page")
        self.assertTrue(again["ok"], again)
        self.assertEqual(self.commits(), n)
        self.assertEqual(again["commit"], git(self.work, "rev-parse", "HEAD").strip())

    def test_the_trailers_variable_takes_only_its_own_shape(self):
        import os
        import importlib.util
        spec = importlib.util.spec_from_file_location("garrick_scaffold_t", base.REPO / "template" / "System" / "tools" / "scaffold.py")
        sc = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(base.REPO / "template" / "System" / "tools"))
        try:
            spec.loader.exec_module(sc)
        finally:
            sys.path.pop(0)
        old = os.environ.get("GARRICK_COMMIT_TRAILERS")
        try:
            for bad in ("", "Garrick-Op: x", "Garrick-Op: 1234123412341234\nGarrick-Payload: zz\nFoo: bar"):
                os.environ["GARRICK_COMMIT_TRAILERS"] = bad
                self.assertEqual(sc.commit_trailers(), [])
            good = "Garrick-Op: 1234123412341234\nGarrick-Payload: " + "a" * 64
            os.environ["GARRICK_COMMIT_TRAILERS"] = good
            self.assertEqual(sc.commit_trailers(), ["-m", good])
        finally:
            if old is None:
                os.environ.pop("GARRICK_COMMIT_TRAILERS", None)
            else:
                os.environ["GARRICK_COMMIT_TRAILERS"] = old


if __name__ == "__main__":
    unittest.main()
