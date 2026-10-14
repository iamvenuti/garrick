"""template/System/tools/operations.py: the durable record of a page action.

    python3 -m unittest discover -s tests

The identity key, the one mapping from outcome to sentence, and the journal:
what a worker writes, what a reader finds, and what stops a refusal from
reading as saved.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("garrick_operations_t", REPO / "template" / "System" / "tools" / "operations.py")
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)

pa_spec = importlib.util.spec_from_file_location("garrick_page_action_for_ops", REPO / "extras" / "status" / "page_action.py")
pa = importlib.util.module_from_spec(pa_spec)
pa_spec.loader.exec_module(pa)

# One request of each declared verb, as the status page sends it.
REQUESTS = {
    "park": {"verb": "park", "zone": "Work", "project": "Acme Review", "thread": "Pricing"},
    "wake": {"verb": "wake", "zone": "Work", "file": "Acme Review/Threads/Pricing/Pricing.md"},
    "todo-done": {"verb": "todo-done", "zone": "Work", "file": "Todo.md", "key": "0123456789abcdef"},
    "todo-undo": {"verb": "todo-undo", "zone": "Work", "file": "Todo.md", "key": "0123456789abcdef"},
    "todo-date": {"verb": "todo-date", "zone": "Work", "file": "Todo.md", "key": "0123456789abcdef", "date": "2026-10-12"},
    "todo-add": {"verb": "todo-add", "zone": "Work", "text": "Book the room", "target": "-", "date": "-"},
}
# What the code says when a check refuses or the worker falls over, and what a
# careless one might: every one of them must come out without a success.
REASONS = [
    "not committed, so nothing changed: the wall check refused: Acme Review/Acme Review.md names birch",
    "not committed: the wall check was still running after 5 minutes and was stopped, so the note was put back as it was. "
    "Make the change again and commit it by hand: that commit waits for the check and goes through",
    "not committed: x. The note was edited meanwhile, so it was left as it is, uncommitted; commit it by hand",
    "that line has changed since the page was built; it rebuilds now, try again",
    "another action in Work is still running; try again in a moment",
    "OSError: the disk went away",
    # said carelessly: the guard must replace these rather than pass them on
    "Saved elsewhere", "made, but not committed: the files are there", "it was parked already", "Ticked and added",
]
SUCCESS = re.compile(r"\b(%s)\b" % "|".join(ops.SUCCESS_VERBS), re.I)


def only_in_the_negative(sentence):
    """A stricter reading than the module's own: any success verb at all is a
    failure, except straight after "not " or "no "."""
    return all(re.search(r"\b(not|no)\s+$", sentence[:m.start()], re.I) for m in SUCCESS.finditer(sentence))


class TestDeclared(unittest.TestCase):
    def test_every_verb_it_declares_is_one_the_page_sends(self):
        self.assertEqual(sorted(REQUESTS), sorted(ops.OPS))
        for verb in ops.OPS:
            self.assertIn(verb, pa.VERBS, verb)
        for verb, spec in ops.OPS.items():
            self.assertTrue(set(spec.identity) <= set(spec.fields), verb)
            self.assertIn("zone", spec.fields, verb)
            self.assertNotIn("zone", spec.identity, verb)                 # the zone is always in the key, apart from them
            self.assertTrue(set(REQUESTS[verb]) - {"verb"} <= set(spec.fields), verb)   # nothing a real request carries is undeclared

    def test_the_page_script_zones_cover_them(self):
        sys.path.insert(0, str(REPO / "extras" / "status"))
        try:
            import status
        finally:
            sys.path.pop(0)
        self.assertTrue(set(ops.OPS) <= set(status.ZONE_VERBS))

    def test_a_worker_and_a_reader_agree_on_the_words(self):
        self.assertEqual(("saved", "refused", "crashed", "unknown", "lost"), ops.OUTCOMES)
        self.assertEqual(("queued", "running", "completed", "failed"), ops.STATES)


class TestIdentityKey(unittest.TestCase):
    def test_the_same_request_has_the_same_key(self):
        for verb, req in REQUESTS.items():
            key = ops.identity_key(verb, req)
            self.assertRegex(key, r"^[0-9a-f]{64}$")
            self.assertEqual(key, ops.identity_key(verb, dict(reversed(list(req.items())))), verb)    # order
            self.assertEqual(key, ops.identity_key(verb, dict(req, op="a19f3c80", retry_of="x", host="app", junk=1)), verb)

    def test_a_missing_field_and_an_empty_one_say_the_same(self):
        bare = {"verb": "todo-add", "zone": "Work", "text": "Book the room"}
        self.assertEqual(ops.identity_key("todo-add", bare), ops.identity_key("todo-add", REQUESTS["todo-add"]))
        self.assertEqual(ops.identity_key("todo-add", bare), ops.identity_key("todo-add", dict(bare, target=None, date="")))
        self.assertEqual(ops.identity_key("todo-add", bare), ops.identity_key("todo-add", dict(bare, text="  Book the room ")))
        park = {"verb": "park", "zone": "Work", "project": "Acme Review"}
        self.assertEqual(ops.identity_key("park", park), ops.identity_key("park", dict(park, thread=None, file="")))

    def test_a_meaningful_change_is_a_different_key(self):
        for verb, req in REQUESTS.items():
            base = ops.identity_key(verb, req)
            self.assertNotEqual(base, ops.identity_key(verb, dict(req, zone="Personal")), verb)
            for field in ops.OPS[verb].identity:
                changed = dict(req, **{field: "something else"})
                self.assertNotEqual(base, ops.identity_key(verb, changed), (verb, field))
        self.assertNotEqual(ops.identity_key("park", REQUESTS["park"]), ops.identity_key("wake", REQUESTS["park"]))

    def test_a_client_cannot_choose_it(self):
        req = dict(REQUESTS["park"], key="deadbeefdeadbeef", identity="x")
        self.assertEqual(ops.identity_key("park", REQUESTS["park"]), ops.identity_key("park", req))

    def test_the_op_is_checked_for_its_shape_only(self):
        for good in ("a19f3c80", "0" * 32, ops.mint_op()):
            self.assertTrue(ops.valid_op(good), good)
        for bad in ("", "A19F3C80", "a19f3c8", "g" * 8, "0" * 33, None, 12345678, "a19f3c80\n", "../a19f3c80"):
            self.assertFalse(ops.valid_op(bad), bad)


class TestWording(unittest.TestCase):
    """What stops a refusal reading as saved: one mapping, and a test that asserts the negative."""

    def test_only_saved_may_say_what_the_handler_said(self):
        for verb, req in REQUESTS.items():
            self.assertEqual("Acme Review is parked", ops.say("saved", verb, req, said="Acme Review is parked"))
            for outcome in ops.OUTCOMES[1:]:
                self.assertNotIn("Acme Review is parked", ops.say(outcome, verb, req, why="x", said="Acme Review is parked"))

    def test_no_failure_for_any_verb_reads_as_a_success(self):
        for verb, req in REQUESTS.items():
            for outcome in ops.OUTCOMES:
                if outcome == "saved":
                    continue
                for why in REASONS:
                    sentence = ops.say(outcome, verb, req, why=why, said="Everything was saved, parked, ticked and added")
                    self.assertTrue(only_in_the_negative(sentence), (verb, outcome, why, sentence))
                    self.assertFalse(ops.affirms(sentence), (verb, outcome, why, sentence))

    def test_the_templates_hold_no_success_verb_at_all(self):
        for outcome, template in ops.SAYINGS.items():
            self.assertIsNone(SUCCESS.search(template), outcome)
            self.assertIsNone(SUCCESS.search(ops.FALLBACK_WHY.get(outcome, "")), outcome)
        for verb, req in REQUESTS.items():
            for already in (False, True):                       # a join says a request is under way, never that it is done
                self.assertIsNone(SUCCESS.search(ops.label(verb, req, already=already)), verb)
            for outcome in ("unknown", "lost"):
                self.assertIsNone(SUCCESS.search(ops.say(outcome, verb, req)), (verb, outcome))

    def test_an_unknown_one_says_what_to_check_and_that_trying_again_is_safe(self):
        said = ops.say("unknown", "park", REQUESTS["park"])
        self.assertIn("We do not know whether the change to Pricing went through", said)
        self.assertIn("git log -1 in Work", said)
        self.assertIn("Trying again is safe", said)

    def test_the_guard_reads_negatives_and_affirmatives(self):
        for fine in ("Not committed, so nothing changed", "left as it is, uncommitted", "was not saved", "Make the change again",
                     "nothing was parked", "never ticked"):
            self.assertFalse(ops.affirms(fine), fine)
        for bad in ("Saved", "made, but not committed", "It was added to Inbox", "committed", "Parked."):
            self.assertTrue(ops.affirms(bad), bad)

    def test_a_terminal_record_without_a_valid_outcome_is_a_programming_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            j = ops.Journal(tmp)
            base = {"op": "a19f3c80", "verb": "park", "zone": "Work", "at": 1.0}
            for rec in (dict(base, state="failed"), dict(base, state="failed", outcome="nope"), dict(base, state="completed"),
                        dict(base, state="completed", outcome="refused"), dict(base, state="failed", outcome="saved"),
                        dict(base, state="finished", outcome="saved")):
                with self.assertRaises(ValueError, msg=rec):
                    j.append(rec)
            self.assertEqual([], j.records())
        with self.assertRaises(ValueError):
            ops.say("fine", "park", REQUESTS["park"])


class JournalCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self._tmp.name) / "jobs"
        self.j = ops.Journal(self.folder)
        self.runs = []

    def tearDown(self):
        for run in self.runs:
            run.close(REQUESTS["park"])
        self._tmp.cleanup()

    def start(self, verb="park", now=None, **extra):
        run, reply = ops.start(self.folder, dict(REQUESTS[verb], **extra), now=now)
        if run is not None:
            self.runs.append(run)
        return run, reply


class TestJournal(JournalCase):
    def test_a_record_runs_from_queued_to_a_terminal_state(self):
        run, reply = self.start(op="a19f3c80")
        self.assertIsNone(reply)
        run.running()
        run.phase("checking")
        said = run.finish("saved", REQUESTS["park"], said="Pricing is parked")
        run.close(REQUESTS["park"])
        self.assertEqual({"ok": True, "say": "Pricing is parked", "op": "a19f3c80", "state": "completed", "outcome": "saved"}, said)
        records = self.j.records()
        self.assertEqual([("queued", ""), ("running", ""), ("running", "checking"), ("completed", "")],
                         [(r["state"], r["phase"]) for r in records])
        self.assertEqual({"a19f3c80"}, {r["op"] for r in records})
        self.assertEqual("saved", records[-1]["outcome"])
        self.assertEqual({"zone": "Work", "project": "Acme Review", "thread": "Pricing"}, records[0]["request"])
        self.assertEqual(ops.identity_key("park", REQUESTS["park"]), records[0]["key"])
        self.assertEqual("Parking Pricing…", records[0]["label"])
        self.assertFalse(self.j.run_path("a19f3c80").exists())                 # the lock file goes with the run

    def test_the_request_holds_only_what_the_verb_declares_and_a_line_cut_short(self):
        run, _ = self.start("todo-add", text="x" * 200, password="hunter2", op="a19f3c80")
        text = self.j.path.read_text()
        self.assertNotIn("hunter2", text)
        self.assertLess(len(json.loads(text.splitlines()[0])["request"]["text"]), 70)

    def test_a_refusal_is_failed_and_refused_and_never_completed(self):
        run, _ = self.start(op="a19f3c80")
        said = run.finish("refused", REQUESTS["park"], why="not committed, so nothing changed: the wall check refused")
        self.assertEqual((False, "failed", "refused"), (said["ok"], said["state"], said["outcome"]))
        self.assertTrue(only_in_the_negative(said["say"]), said["say"])
        self.assertEqual("failed", self.j.records()[-1]["state"])

    def test_closing_without_a_terminal_record_leaves_a_crashed_one(self):
        run, _ = self.start(op="a19f3c80")
        run.close(REQUESTS["park"])
        last = self.j.records()[-1]
        self.assertEqual(("failed", "crashed"), (last["state"], last["outcome"]))
        self.assertIsNone(SUCCESS.search(last["say"]))

    def test_the_last_line_for_an_op_wins_and_a_torn_line_is_skipped(self):
        run, _ = self.start(op="a19f3c80")
        with open(self.j.path, "a") as f:
            f.write("{not json\n\n[1]\n")
        run.running()
        self.assertEqual("running", self.j.latest()["a19f3c80"]["state"])
        self.assertEqual(1, len(self.j.latest()))

    def test_a_bad_op_is_refused_for_its_shape(self):
        with self.assertRaises(ops.BadOp):
            ops.start(self.folder, dict(REQUESTS["park"], op="../../etc"))
        self.assertFalse(self.j.path.exists() and self.j.path.read_text())

    def test_an_op_left_out_is_minted(self):
        run, _ = self.start()
        self.assertTrue(ops.valid_op(run.op))

    def test_the_folder_nobody_can_write_gives_nothing_to_do(self):
        (self.folder).mkdir(parents=True)
        self.j.path.mkdir()                                                    # a folder where the journal should be
        self.assertEqual((None, None), ops.start(self.folder, REQUESTS["park"]))
        reply = ops.read(self.folder)
        self.assertEqual((True, False, []), (reply["ok"], reply["durable"], reply["ops"]))


class TestJoin(JournalCase):
    def test_an_identical_request_under_way_joins_and_executes_nothing(self):
        first, _ = self.start(op="a19f3c80", now=1000.0)
        first.running()
        run, reply = self.start(op="b29f3c80", now=1030.0)
        self.assertIsNone(run)
        self.assertEqual({"ok": True, "say": "Already parking Pricing…", "op": "a19f3c80", "state": "running"}, reply)
        self.assertNotIn("outcome", reply)                                    # a join is ok, and is not a save
        self.assertIsNone(SUCCESS.search(reply["say"]))
        self.assertEqual({"a19f3c80"}, {r["op"] for r in self.j.records()})   # the second left no record of its own
        self.assertFalse(self.j.run_path("b29f3c80").exists())

    def test_the_same_op_twice_is_one_run(self):
        self.start(op="a19f3c80")
        run, reply = self.start(op="a19f3c80")
        self.assertIsNone(run)
        self.assertEqual(("a19f3c80", "running"), (reply["op"], reply["state"]))

    def test_a_different_request_does_not_join(self):
        self.start(op="a19f3c80", now=1000.0)
        run, reply = self.start(op="b29f3c80", now=1001.0, thread="Other")
        self.assertIsNotNone(run)
        self.assertIsNone(reply)

    def test_outside_the_window_it_does_not(self):
        self.start(op="a19f3c80", now=1000.0)
        run, reply = self.start(op="b29f3c80", now=1000.0 + ops.IDEM_WINDOW + 1)
        self.assertIsNotNone(run)

    def test_a_dead_worker_is_not_joined(self):
        self.start(op="a19f3c80", now=1000.0)[0]
        os.close(self.runs[0].fd)                                              # the worker is gone, its lock with it
        self.runs[0].fd = os.open(os.devnull, os.O_RDONLY)
        run, reply = self.start(op="b29f3c80", now=1010.0)
        self.assertIsNotNone(run)
        self.assertEqual("unknown", self.j.latest()["a19f3c80"]["outcome"])

    def test_a_save_just_made_is_returned_and_nothing_runs(self):
        first, _ = self.start(op="a19f3c80", now=1000.0)
        first.finish("saved", REQUESTS["park"], said="Acme Review, Pricing is parked")
        first.close(REQUESTS["park"])
        run, reply = self.start(op="b29f3c80", now=1010.0)
        self.assertIsNone(run)
        self.assertEqual({"ok": True, "say": "Acme Review, Pricing is parked", "op": "a19f3c80", "state": "completed",
                          "outcome": "saved"}, reply)

    def test_a_refusal_is_not_cached(self):
        first, _ = self.start(op="a19f3c80", now=1000.0)
        first.finish("refused", REQUESTS["park"], why="a wall")
        first.close(REQUESTS["park"])
        run, reply = self.start(op="b29f3c80", now=1010.0)
        self.assertIsNotNone(run)
        self.assertIsNone(reply)

    def test_a_crash_is_not_cached_either(self):
        first, _ = self.start(op="a19f3c80", now=1000.0)
        first.close(REQUESTS["park"])
        run, reply = self.start(op="b29f3c80", now=1010.0)
        self.assertIsNotNone(run)

    def test_park_then_wake_then_park_is_three_edits(self):
        """The same park, asked again after a wake in between, is a new request."""
        for i, verb in enumerate(("park", "wake", "park")):
            req = dict(REQUESTS["park"], verb=verb)
            run, reply = ops.start(self.folder, dict(req, op="a19f3c8%d" % i), now=1000.0 + 10 * i)
            self.assertIsNone(reply, verb)
            run.finish("saved", req, said="done")
            run.close(req)

    def test_a_save_in_another_zone_does_not_hide_the_replay(self):
        first, _ = self.start(op="a19f3c80", now=1000.0)
        first.finish("saved", REQUESTS["park"], said="Acme Review, Pricing is parked")
        first.close(REQUESTS["park"])
        other = dict(REQUESTS["todo-add"], zone="Personal", op="c39f3c80")
        run, _ = ops.start(self.folder, other, now=1005.0)
        run.finish("saved", other, said="Added")
        run.close(other)
        _, reply = self.start(op="b29f3c80", now=1010.0)
        self.assertEqual("a19f3c80", reply["op"])


class TestReader(JournalCase):
    def test_it_lists_what_is_open_and_what_ended_recently(self):
        now = time.time()
        a, _ = self.start(op="a19f3c80", now=now - 5)
        a.running()
        b, _ = self.start("wake", op="b29f3c80", now=now - 50)
        b.finish("saved", REQUESTS["wake"], said="awake")
        b.close(REQUESTS["wake"])
        old = {"op": "c39f3c80", "key": "k", "verb": "park", "zone": "Work", "state": "completed", "phase": "", "at": now - 5000,
               "done": now - 4000, "outcome": "saved", "say": "old", "label": "x", "request": {}}
        self.j.append(old)
        listed = self.j.open_set(now)
        self.assertEqual(["a19f3c80", "b29f3c80"], [r["op"] for r in listed])
        self.assertEqual(("running", None), (listed[0]["state"], listed[0]["outcome"]))
        self.assertEqual(("completed", "saved", "awake"), (listed[1]["state"], listed[1]["outcome"], listed[1]["say"]))
        self.assertTrue(all(set(r) == {"op", "verb", "zone", "state", "phase", "at", "done", "outcome", "say", "label"} for r in listed))

    def test_the_reply_says_what_the_page_needs(self):
        self.start(op="a19f3c80")
        reply = ops.read(self.folder)
        self.assertEqual(True, reply["durable"])
        self.assertEqual(sorted(REQUESTS), reply["verbs"])
        self.assertEqual(["a19f3c80"], [r["op"] for r in reply["ops"]])
        self.assertIn("{zone}", reply["lost"])
        self.assertIsNone(SUCCESS.search(reply["lost"]))

    def test_a_record_with_no_worker_reads_back_unknown_and_stays_that_way(self):
        self.j.folder.mkdir(parents=True)
        queued = {"op": "a19f3c80", "key": "k", "verb": "park", "zone": "Work", "state": "running", "phase": "checking", "at": time.time(),
                  "done": None, "outcome": None, "say": None, "label": "Parking Pricing…",
                  "request": {"zone": "Work", "project": "Acme Review", "thread": "Pricing"}}
        self.j.append(queued)                                                  # and no .run file: the worker is gone
        listed = self.j.open_set()
        self.assertEqual(("failed", "unknown"), (listed[0]["state"], listed[0]["outcome"]))
        self.assertIsNone(SUCCESS.search(listed[0]["say"]))
        self.assertIn("git log -1 in Work", listed[0]["say"])
        self.assertIn("Trying again is safe", listed[0]["say"])
        self.j.open_set()                                                      # a second read does not write a second one
        self.assertEqual(2, len(self.j.records()))

    def test_a_worker_that_is_alive_is_left_alone(self):
        run, _ = self.start(op="a19f3c80")
        run.running()
        self.assertEqual("running", self.j.open_set()[0]["state"])
        self.assertEqual(2, len(self.j.records()))

    def test_a_worker_that_finished_between_the_read_and_the_check_keeps_its_own_record(self):
        run, _ = self.start(op="a19f3c80")
        run.finish("saved", REQUESTS["park"], said="parked")
        os.close(run.fd)                                                       # the lock is free, the record is terminal
        run.fd = os.open(os.devnull, os.O_RDONLY)
        self.assertEqual("saved", self.j.open_set()[0]["outcome"])
        self.assertEqual(2, len(self.j.records()))                             # queued, saved: nothing written for it

    def test_a_long_file_is_compacted_to_the_last_record_of_each_op(self):
        now = time.time()
        self.assertTrue(self.j.usable())
        for i in range(30):
            self.j.append({"op": "%08x" % i, "key": "k", "verb": "park", "zone": "Work", "state": "completed", "phase": "", "at": now,
                           "done": now, "outcome": "saved", "say": "x" * 30000, "request": {}, "label": "x"})
        self.assertGreater(self.j.path.stat().st_size, ops.COMPACT_BYTES)
        self.j.compact(now)
        self.assertEqual(30, len(self.j.records()))
        self.j.append({"op": "00000000", "key": "k", "verb": "park", "zone": "Work", "state": "failed", "phase": "", "at": now,
                       "done": now - 3 * ops.KEEP, "outcome": "refused", "say": "x" * 600000, "request": {}, "label": "x"})
        self.j.compact(now)
        self.assertNotIn("00000000", self.j.latest())                          # an ended op older than a day goes


if __name__ == "__main__":
    unittest.main()
