"""The durable record of a note, a reworded line and a retired one (#701).

    cd tests && python3 -m unittest test_remote_record

A remote assistant cannot see the first answer when its call times out, so it asks again. The record is what stops a
second note or a second reworded line: a retry joins the first one, also after a restart (a fresh load of the module,
with only the jobs folder carried over), and the same operation id with other words is refused.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest

sys.dont_write_bytecode = True

import test_notes as notes  # noqa: E402
import test_page_action as base  # noqa: E402

REPO = base.REPO
NEW = ("note-add", "todo-edit", "todo-retire")


class RecordCase(notes.NoteCase):
    def setUp(self):
        super().setUp()
        # A save asks for a build of the status page: a detached process that waits ten seconds (`--settle`) and then writes into the
        # workspace. It outlives the test and writes while tearDown removes the folder (Errno 66, Directory not empty). Nothing here
        # reads the page, so the request is not made; the reply is then the one a caller gets where the page cannot be asked for.
        self.pa.ask_for_page = lambda ws: False
        base.write(self.work / "Todo.md", "# Work: open actions\n\n## Inbox\n\n"
                   "- [ ] [[Pricing]]: Send the revised terms 📅 2026-10-09\n- [ ] Acme Corp: Invoice for September\n\n## Done\n")
        notes.git(self.work, "add", "-A")
        notes.git(self.work, "commit", "-q", "-m", "todo")
        self.invoice = self.key("Invoice")      # taken once: a reworded or retired line has another key afterwards
        self.terms = self.key("Send the revised")

    def key(self, text):
        return next(t["key"] for t in base.tl.tasks(str(self.work)) if text in t["text"])

    def ops(self, fresh=False):
        if not fresh:
            return self.pa.ops_lib(self.root)
        spec = importlib.util.spec_from_file_location("operations_restarted", str(REPO / "template" / "System" / "tools" / "operations.py"))
        mod = importlib.util.module_from_spec(spec)
        sys.modules["operations_restarted"] = mod
        spec.loader.exec_module(mod)
        return mod

    def send(self, req, via="remote", fresh=False):
        return self.pa.perform(self.root, req, self.ops(fresh), via=via)[0]

    def request(self, verb, op, text="Dana hinted the floor could move"):
        if verb == "note-add":
            return {"verb": verb, "op": op, "zone": "Work", "project": "Acme Review", "thread": "Pricing", "text": text}
        if verb == "todo-edit":
            return {"verb": verb, "op": op, "zone": "Work", "file": "Todo.md", "key": self.invoice, "text": text}
        return {"verb": verb, "op": op, "zone": "Work", "file": "Todo.md", "key": self.terms, "reason": text}

    def commits(self):
        return int(notes.git(self.work, "rev-list", "--count", "HEAD").strip())

    def rows(self):
        path = self.pa.jobs_dir() / "operations.jsonl"
        return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


class TestTheThreeKeepARecord(RecordCase):
    def test_they_are_recorded_through_start(self):
        ops = self.ops()
        for verb in NEW:
            self.assertIn(verb, ops.RECORDED)
            self.assertIn(verb, ops.OPS)

    def test_a_save_leaves_a_record_that_names_remote(self):
        for verb, op in zip(NEW, ("a1a1a1a1a1a1a1a1", "b2b2b2b2b2b2b2b2", "c3c3c3c3c3c3c3c3")):
            with self.subTest(verb=verb):
                out = self.send(self.request(verb, op))
                self.assertTrue(out["ok"], out)
                row = [r for r in self.rows() if r["op"] == op][-1]
                self.assertEqual(("saved", "remote", verb), (row["outcome"], row["via"], row["verb"]))


class TestARetryJoinsTheFirst(RecordCase):
    def test_after_success_the_first_answer_comes_back_and_nothing_is_written_twice(self):
        for verb, op in zip(NEW, ("a1a1a1a1a1a1a1a1", "b2b2b2b2b2b2b2b2", "c3c3c3c3c3c3c3c3")):
            with self.subTest(verb=verb):
                first = self.send(self.request(verb, op))
                self.assertTrue(first["ok"], first)
                before = (self.commits(), (self.work / "Todo.md").read_bytes(), sorted(p.name for p in self.work.rglob("*.md")))
                again = self.send(self.request(verb, op))
                self.assertTrue(again["ok"], again)
                self.assertEqual(first["say"], again["say"])
                self.assertEqual(before, (self.commits(), (self.work / "Todo.md").read_bytes(), sorted(p.name for p in self.work.rglob("*.md"))))

    def test_a_retry_with_a_new_operation_id_is_joined_too(self):
        first = self.send(self.request("note-add", "a1a1a1a1a1a1a1a1"))
        count = self.commits()
        again = self.send(self.request("note-add", "d4d4d4d4d4d4d4d4"))
        self.assertEqual(first["say"], again["say"])
        self.assertEqual(count, self.commits())
        notes = [p for p in (self.work / "Acme Review" / "Threads" / "Pricing").rglob("*.md") if p.parent.name == "Notes"]
        self.assertEqual(1, len(notes))

    def test_across_a_restart(self):
        for verb, op in zip(NEW, ("a1a1a1a1a1a1a1a1", "b2b2b2b2b2b2b2b2", "c3c3c3c3c3c3c3c3")):
            with self.subTest(verb=verb):
                first = self.send(self.request(verb, op))
                count = self.commits()
                again = self.send(self.request(verb, op), fresh=True)
                self.assertTrue(again["ok"], again)
                self.assertEqual(first["say"], again["say"])
                self.assertEqual(count, self.commits())

    def test_a_retry_that_arrives_while_the_first_is_running_joins_it(self):
        ops = self.ops()
        run, joined = ops.start(self.pa.jobs_dir(), self.request("note-add", "a1a1a1a1a1a1a1a1"), via="remote", workspace=str(self.root))
        self.assertIsNone(joined)
        try:
            out = self.send(self.request("note-add", "e5e5e5e5e5e5e5e5"))
            self.assertTrue(out["ok"], out)
            self.assertEqual("running", out.get("state"))
        finally:
            run.close(self.request("note-add", "a1a1a1a1a1a1a1a1"))
        self.assertEqual([], [p for p in (self.work / "Acme Review").rglob("*.md") if p.parent.name == "Notes"])


class TestAConflictingPayloadIsRefused(RecordCase):
    def test_the_same_id_with_other_words(self):
        for verb, op in zip(NEW, ("a1a1a1a1a1a1a1a1", "b2b2b2b2b2b2b2b2", "c3c3c3c3c3c3c3c3")):
            with self.subTest(verb=verb):
                self.assertTrue(self.send(self.request(verb, op, "First words"))["ok"])
                count = self.commits()
                other = self.send(self.request(verb, op, "Other words entirely"))
                self.assertFalse(other["ok"], other)
                self.assertEqual(count, self.commits())

    def test_also_after_a_restart(self):
        self.assertTrue(self.send(self.request("note-add", "a1a1a1a1a1a1a1a1", "First words"))["ok"])
        count = self.commits()
        self.assertFalse(self.send(self.request("note-add", "a1a1a1a1a1a1a1a1", "Other words entirely"), fresh=True)["ok"])
        self.assertEqual(count, self.commits())

    def test_the_six_it_always_had_keep_their_ways(self):
        first = self.send({"verb": "todo-add", "op": "f6f6f6f6f6f6f6f6", "zone": "Work", "text": "Call the carrier"}, via="page")
        self.assertTrue(first["ok"], first)
        other = self.send({"verb": "todo-add", "op": "f6f6f6f6f6f6f6f6", "zone": "Work", "text": "Something else"}, via="page")
        self.assertFalse(other["ok"], other)


if __name__ == "__main__":
    unittest.main()
