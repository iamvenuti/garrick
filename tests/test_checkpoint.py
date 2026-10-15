"""The checkpoint a session writes as the work happens: `scaffold.py
checkpoint`, and the block it keeps in a thread note.

    python3 -m unittest discover -s tests

The rules these carry that no check can see: the same state written twice
writes once, at any interval; a write from a session that has not seen the
note is refused and changes nothing; every item names its source; and the
confirmed resume point and the zone's `Todo.md` come out byte for byte as they
went in, whatever the checkpoint does.

The workspace is the fictional one in fixtures.py. Nothing here reads this
machine: the time is given to the tool, never taken from the clock.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

import fixtures  # noqa: E402
from fixtures import build_workspace, write  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "template" / "System" / "tools"
SCAFFOLD = TOOLS / "scaffold.py"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module          # check.py's dataclasses look themselves up by module
    spec.loader.exec_module(module)
    return module


scaffold = load(SCAFFOLD, "garrick_scaffold_checkpoint")
lib = load(TOOLS / "garrick_lib.py", "garrick_lib_checkpoint")
ops = load(TOOLS / "operations.py", "garrick_operations_checkpoint")

PROJECT = "Acme Review"
THREAD = "Pricing"
NOW = "2026-03-15T14:32:10+01:00"
TEN_HOURS_LATER = "2026-03-16T00:32:10+01:00"

# A thread note as a real one looks by the time it is worked on: the resume
# table, the rule under it, and three dated entries, all inside State of play
# and none of them a heading. A block that ran "until the next heading" would
# swallow every one of them.
NOTE = """\
---
title: Pricing
type: thread
project: "[[Acme Review]]"
party: acme
status: active
created: 2026-03-01
updated: 2026-03-13
---

# Pricing

## The ask

Dana asked for a price sheet she can take to her board.

## State of play

### Resume here

**Where it stands, 13 March 2026.** Drafted; waiting on Dana's volumes.

| | |
|---|---|
| Live artifact | `Deliverables/260301 - Pricing memo.md` |
| Rebuild with | the memo, and the volumes when they come |
| Next action | chase Dana for the volumes |
| Keep in mind | the tier-three tab is a guess |
| Waiting on | Dana |
| Deadline | none |

---

<Dated entries, newest first. Never edit an old one.>

**13 March 2026.** Asked Dana for the volumes.

**8 March 2026.** Drafted the memo.

**1 March 2026.** Opened the thread.
"""


class CheckpointCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = build_workspace(Path(self.tmp.name) / "ws")
        (self.root / "System" / "templates").mkdir(parents=True, exist_ok=True)
        self.project = self.root / "Zones" / "Work" / PROJECT
        self.note = self.project / "Threads" / THREAD / (THREAD + ".md")
        write(self.note, NOTE)
        self.sheet = "Deliverables/260315 - Price sheet.md"
        write(self.project / self.sheet, "# Price sheet\n")
        self.todo = self.root / "Zones" / "Work" / "Todo.md"

    def tearDown(self):
        self.tmp.cleanup()

    # -- running it ---------------------------------------------------------

    def send(self, now=NOW, **fields):
        """The tool, run as the command line runs it: one JSON object in, one
        out, and the exit code with it."""
        req = {"verb": "checkpoint", "zone": "Work", "project": PROJECT, "thread": THREAD}
        req.update(fields)
        req = {k: v for k, v in req.items() if v is not None}
        out = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(req))), contextlib.redirect_stdout(out):
            code = scaffold.main(["--root", str(self.root), "checkpoint", "--now", now])
        return code, json.loads(out.getvalue())

    def state(self):
        """What a session reads before it writes: the resume point's hash and
        the key of the checkpoint that is there."""
        _, reply = self.send(read=True)
        return reply["base"], reply["key"]

    def made(self, **more):
        item = {"kind": "made", "path": self.sheet, "at": "14:20"}
        item.update(more)
        return item

    def first(self, now=NOW):
        """One checkpoint in the note, and the state after it."""
        base, prev = self.state()
        code, reply = self.send(now=now, base=base, prev=prev, items=[
            self.made(),
            {"kind": "decided", "said": "Go with the tier-two rate as drafted", "by": "user", "at": "14:25"},
            {"kind": "considering", "text": "dropping tier three"},
            {"kind": "next", "text": "fill in the tier-two volume on row 14", "by": "user"},
            {"kind": "action", "text": "send Dana the price sheet", "said": "I'll send Dana the sheet"},
            {"kind": "incomplete", "text": "the tier-three tab is half filled"},
        ])
        self.assertEqual(0, code, reply)
        self.assertTrue(reply["wrote"], reply)
        return reply

    # -- what is outside the markers ---------------------------------------

    def outside(self):
        """Every byte of the note that is not between the two markers, with
        the heading the first write adds taken out too: what a wrap gives back
        when it folds the checkpoint away."""
        text = self.note.read_text(encoding="utf-8")
        found = lib.checkpoint_span(text)
        if found is None:
            return text
        start, end = found
        head = text.rfind("\n" + lib.CHECKPOINT_HEADING + "\n\n", 0, start)
        self.assertGreaterEqual(head, 0, "the heading is written with the block")
        return text[:head] + text[end + 1:]

    def resume(self):
        return "\n".join(lib.resume_lines(self.note.read_text(encoding="utf-8")))


class TestTheBlock(CheckpointCase):
    def test_it_goes_under_resume_here_above_the_rule_and_between_its_markers(self):
        reply = self.first()
        text = self.note.read_text(encoding="utf-8")
        self.assertLess(text.index("### Resume here"), text.index("### Checkpoint"))
        self.assertLess(text.index("### Checkpoint"), text.index("\n---\n\n<Dated entries"))
        self.assertIn("<!-- garrick-checkpoint at=%s base=%s key=%s -->" % (NOW, reply["base"], reply["key"]), text)
        self.assertIn("**Unconfirmed, 14:32 on 15 March 2026.** Recorded since the resume point above", text)
        self.assertIn(lib.CHECKPOINT_CLOSE, text)
        self.assertEqual([
            "- **Made** `Deliverables/260315 - Price sheet.md`, saved 14:20 <!-- m1 -->",
            '- **Decided** "Go with the tier-two rate as drafted", the user at 14:25 <!-- d1 -->',
            "- **Considering** dropping tier three; not decided <!-- c1 -->",
            "- **Next action** fill in the tier-two volume on row 14, the user's <!-- n -->",
            "- **To file** send Dana the price sheet, no date given <!-- a1 -->",
            "- **Incomplete** the tier-three tab is half filled <!-- i -->",
        ], [item["line"] for item in reply["items"]])

    def test_an_action_nobody_dated_says_so_rather_than_claiming_a_date(self):
        reply = self.first()
        line = next(i["line"] for i in reply["items"] if i["kind"] == "action")
        self.assertIn("no date given", line)
        self.assertNotIn("📅", line)
        self.assertNotIn("Deadline", self.note.read_text(encoding="utf-8").split("### Checkpoint")[1])

    def test_the_key_covers_the_items_and_the_base_but_not_the_time(self):
        base, _ = self.state()
        one = lib.render_checkpoint(NOW, base, [{"line": "- **Incomplete** half done <!-- i -->"}])
        two = lib.render_checkpoint(TEN_HOURS_LATER, base, [{"line": "- **Incomplete** half done <!-- i -->"}])
        self.assertEqual(one[1], two[1])
        self.assertNotEqual(one[1], lib.render_checkpoint(NOW, base, [
            {"line": "- **Incomplete** all done <!-- i -->"}])[1])
        self.assertNotEqual(one[1], lib.render_checkpoint(NOW, "0" * 12, [
            {"line": "- **Incomplete** half done <!-- i -->"}])[1])

    def test_a_read_writes_nothing_and_answers_with_the_base_the_key_and_the_items(self):
        before = self.note.read_bytes()
        code, reply = self.send(read=True)
        self.assertEqual((0, True, False), (code, reply["ok"], reply["wrote"]))
        self.assertEqual(before, self.note.read_bytes())
        self.assertEqual("No checkpoint in Acme Review, Pricing.", reply["say"])
        written = self.first()
        with_block = self.note.read_bytes()
        code, reply = self.send(read=True)
        self.assertEqual(with_block, self.note.read_bytes())          # a read is a read
        self.assertEqual((written["base"], written["key"]), (reply["base"], reply["key"]))
        self.assertEqual([i["id"] for i in written["items"]], [i["id"] for i in reply["items"]])
        self.assertTrue(reply["valid"])
        self.assertFalse(reply["stale"])
        self.assertIn("unwrapped checkpoint", reply["say"])

    def test_a_read_says_so_when_the_resume_point_has_moved_on_since(self):
        self.first()
        text = self.note.read_text(encoding="utf-8")
        self.note.write_text(text.replace("| Waiting on | Dana |", "| Waiting on | nobody |"), encoding="utf-8")
        _, reply = self.send(read=True)
        self.assertTrue(reply["valid"])
        self.assertTrue(reply["stale"])
        self.assertIn("predates the last confirmed resume point", reply["say"])


class TestRepeats(CheckpointCase):
    def test_the_same_request_twice_writes_once_ten_hours_apart(self):
        base, prev = self.state()
        items = [self.made(), {"kind": "action", "text": "send Dana the price sheet",
                               "said": "I'll send Dana the sheet"}]
        code, one = self.send(now=NOW, base=base, prev=prev, items=items)
        self.assertEqual((0, True), (code, one["wrote"]))
        after = self.note.read_bytes()
        # The same request again, with the same `prev` it was sent with: a
        # retry that never saw the first reply, ten hours later.
        code, two = self.send(now=TEN_HOURS_LATER, base=base, prev=prev, items=items)
        self.assertEqual(0, code)
        self.assertEqual({"ok": True, "wrote": False, "say": "Nothing new since the last checkpoint."}, two)
        self.assertEqual(after, self.note.read_bytes())
        # And again from a session that did read the first one.
        code, three = self.send(now=TEN_HOURS_LATER, base=base, prev=one["key"], items=items)
        self.assertEqual((0, False), (code, three["wrote"]))
        self.assertEqual(after, self.note.read_bytes())
        self.assertEqual(1, self.note.read_text(encoding="utf-8").count("send Dana the price sheet"))

    def test_a_reworded_action_sent_with_its_id_makes_one_item(self):
        first = self.first()
        base, prev = self.state()
        code, reply = self.send(base=base, prev=prev, items=[
            {"kind": "action", "id": "a1", "text": "Send  DANA the price sheet.",
             "said": "I'll send Dana the sheet", "date": "2026-03-20"}])
        self.assertEqual((0, True), (code, reply["wrote"]))
        actions = [i for i in reply["items"] if i["kind"] == "action"]
        self.assertEqual(1, len(actions))
        self.assertEqual("- **To file** Send DANA the price sheet., by 2026-03-20 <!-- a1 -->", actions[0]["line"])
        self.assertEqual(len(first["items"]), len(reply["items"]))

    def test_a_reworded_item_sent_without_its_id_merges_on_its_text(self):
        """The backstop: the same words in another case and spacing are the
        same item, read as the Todo list reads two lines."""
        self.first()
        base, prev = self.state()
        code, reply = self.send(base=base, prev=prev, items=[
            {"kind": "incomplete", "text": "The  tier-three tab is half filled."}])
        self.assertEqual(0, code)
        self.assertEqual(1, len([i for i in reply["items"] if i["kind"] == "incomplete"]))
        self.assertEqual("i", next(i["id"] for i in reply["items"] if i["kind"] == "incomplete"))

    def test_an_item_goes_only_when_its_id_is_dropped(self):
        self.first()
        base, prev = self.state()
        code, reply = self.send(base=base, prev=prev, drop=["c1"], items=[
            {"kind": "considering", "text": "keeping tier three after all"}])
        self.assertEqual(0, code)
        considering = [i["line"] for i in reply["items"] if i["kind"] == "considering"]
        self.assertEqual(["- **Considering** keeping tier three after all; not decided <!-- c1 -->"], considering)
        # Dropping an id that is not there changes nothing, so a retry is safe.
        base, prev = self.state()
        code, again = self.send(base=base, prev=prev, drop=["c9"])
        self.assertEqual(0, code)
        self.assertFalse(again["wrote"])


class TestTwoWriters(CheckpointCase):
    def test_a_base_that_has_moved_is_refused_and_returns_what_is_there(self):
        written = self.first()
        before = self.note.read_bytes()
        code, reply = self.send(base="0" * 12, prev=written["key"],
                                items=[{"kind": "incomplete", "text": "something else"}])
        self.assertEqual(1, code)
        self.assertEqual("moved", reply["refused"])
        self.assertIn("moved on since it was read", reply["say"])
        self.assertEqual(before, self.note.read_bytes())
        self.assertEqual(written["key"], reply["key"])
        self.assertEqual([i["line"] for i in written["items"]], [i["line"] for i in reply["items"]])

    def test_a_prev_the_other_session_has_overwritten_is_refused(self):
        self.first()
        base, prev = self.state()
        code, reply = self.send(base=base, prev="0" * 12,
                                items=[{"kind": "incomplete", "text": "something else"}])
        self.assertEqual((1, "moved"), (code, reply["refused"]))
        self.assertEqual(prev, reply["key"])
        self.assertNotIn("something else", self.note.read_text(encoding="utf-8"))

    def test_a_first_write_that_claims_no_block_is_refused_once_one_is_there(self):
        self.first()
        base, _ = self.state()
        code, reply = self.send(base=base, items=[{"kind": "incomplete", "text": "something else"}])
        self.assertEqual((1, "moved"), (code, reply["refused"]))


class TestRefusals(CheckpointCase):
    def refuse(self, name, **fields):
        before = self.note.read_bytes()
        base, prev = self.state()
        fields.setdefault("base", base)
        fields.setdefault("prev", prev)
        code, reply = self.send(**fields)
        self.assertEqual(1, code, reply)
        self.assertEqual(name, reply["refused"], reply["say"])
        self.assertFalse(reply["wrote"])
        self.assertEqual(before, self.note.read_bytes())
        return reply["say"]

    def test_a_considering_item_sent_as_decided_is_refused(self):
        self.first()
        said = self.refuse("considering", items=[
            {"kind": "decided", "id": "c1", "said": "we drop tier three", "by": "user"}])
        self.assertIn("c1 is a Considering item", said)
        self.assertIn("a decision carries its own words", said)

    def test_a_made_path_that_is_not_there_is_refused(self):
        said = self.refuse("made", items=[{"kind": "made", "path": "Deliverables/260315 - Nothing.md"}])
        self.assertIn("Deliverables/260315 - Nothing.md` is not there", said)

    def test_a_link_that_resolves_into_the_meetings_wiki_is_refused(self):
        said = self.refuse("meetings", items=[
            {"kind": "considering", "text": "as Dana put it in [[260310-acme-kickoff]]"}])
        self.assertIn("carries no meeting material", said)
        self.assertIn("waits for the wrap", said)
        self.refuse("meetings", items=[{"kind": "considering",
                                        "text": "see [[Wikis/Meetings/wiki/sources/260310-acme-kickoff]]"}])

    def test_a_finished_thread_is_refused(self):
        self.note.write_text(NOTE.replace("status: active", "status: done"), encoding="utf-8")
        said = self.refuse("done", items=[{"kind": "incomplete", "text": "half done"}])
        self.assertIn("Acme Review, Pricing is finished", said)

    def test_a_parked_thread_is_refused(self):
        self.note.write_text(NOTE.replace("status: active", "status: parked"), encoding="utf-8")
        said = self.refuse("parked", items=[{"kind": "incomplete", "text": "half done"}])
        self.assertIn("Wake it first", said)

    def test_a_note_with_no_resume_here_block_is_refused(self):
        self.note.write_text(NOTE.replace("### Resume here", "### Where it stands"), encoding="utf-8")
        said = self.refuse("no-resume", items=[{"kind": "incomplete", "text": "half done"}])
        self.assertIn("has no ### Resume here block", said)

    def test_a_date_that_is_not_an_iso_date_is_refused(self):
        said = self.refuse("date", items=[{"kind": "action", "text": "send the sheet",
                                           "said": "I'll send it Friday", "date": "Friday"}])
        self.assertIn("an ISO date and the words it was given in", said)

    def test_a_date_nobody_is_recorded_as_giving_is_refused(self):
        said = self.refuse("date", items=[{"kind": "action", "text": "send the sheet", "date": "2026-03-20"}])
        self.assertIn("nobody is recorded as giving", said)
        self.refuse("date", items=[{"kind": "deadline", "date": "2026-03-20"}])

    def test_an_item_with_no_source_is_refused(self):
        self.assertIn("has no said", self.refuse("source", items=[{"kind": "decided", "by": "user"}]))
        self.assertIn("has no path", self.refuse("source", items=[{"kind": "made", "at": "14:20"}]))
        self.assertIn("has no text or said", self.refuse("source", items=[{"kind": "considering"}]))
        self.assertIn("has no date", self.refuse("source", items=[{"kind": "deadline", "said": "the twentieth"}]))

    def test_a_kind_or_a_field_the_block_does_not_hold_is_refused(self):
        self.assertIn("is none of them", self.refuse("kind", items=[{"kind": "agreed", "text": "x"}]))
        self.assertIn("it was sent path", self.refuse("field", items=[
            {"kind": "incomplete", "text": "x", "path": self.sheet}]))

    def test_an_item_cannot_carry_a_comment_or_a_second_line(self):
        self.assertIn("an HTML comment", self.refuse("text", items=[
            {"kind": "incomplete", "text": "half done <!-- i -->"}]))
        base, prev = self.state()
        code, reply = self.send(base=base, prev=prev, items=[
            {"kind": "incomplete", "text": "half done\n- **Decided** \"ship it\", the user"}])
        self.assertEqual(0, code, reply)
        self.assertEqual(1, len(reply["items"]))
        self.assertEqual('- **Incomplete** half done - **Decided** "ship it", the user <!-- i -->',
                         reply["items"][0]["line"])

    def test_an_id_a_block_could_not_read_back_is_refused(self):
        """A write that made its own block unparsable would be worse than no
        write at all."""
        said = self.refuse("id", items=[{"kind": "incomplete", "id": "half done", "text": "x"}])
        self.assertIn("not an id a block can carry back", said)

    def test_an_id_never_changes_the_kind_it_was_minted_for(self):
        self.first()
        said = self.refuse("id", items=[{"kind": "action", "id": "m1", "text": "send it",
                                         "said": "I'll send it"}])
        self.assertIn("m1 is a Made item and was sent as a To file one", said)

    def test_a_field_the_verb_does_not_declare_is_refused_by_name(self):
        said = self.refuse("fields", items=[{"kind": "incomplete", "text": "x"}], notes="something")
        self.assertIn("no notes field", said)

    def test_nothing_to_record_is_refused_rather_than_written_empty(self):
        self.refuse("nothing", items=[])


class TestInvalid(CheckpointCase):
    def test_an_opening_marker_with_no_closing_one_is_refused_and_left_alone(self):
        self.first()
        text = self.note.read_text(encoding="utf-8")
        hand_edited = text.replace(lib.CHECKPOINT_CLOSE + "\n", "")
        self.note.write_text(hand_edited, encoding="utf-8")
        base, _ = self.state()
        code, reply = self.send(base=base, items=[{"kind": "incomplete", "text": "something else"}])
        self.assertEqual((1, "invalid"), (code, reply["refused"]))
        self.assertIn("has no closing <!-- /garrick-checkpoint --> marker", reply["say"])
        self.assertIn("left exactly as it is", reply["say"])
        self.assertEqual(hand_edited, self.note.read_text(encoding="utf-8"))
        # Never resumed from, either: a read says what is wrong and nothing else.
        _, read = self.send(read=True)
        self.assertFalse(read["valid"])
        self.assertIn("do not resume from it", read["say"])

    def test_a_block_edited_by_hand_is_refused_and_left_alone(self):
        self.first()
        text = self.note.read_text(encoding="utf-8")
        hand_edited = text.replace("the tier-three tab is half filled", "the tier-three tab is finished")
        self.note.write_text(hand_edited, encoding="utf-8")
        base, _ = self.state()
        code, reply = self.send(base=base, items=[{"kind": "incomplete", "text": "something else"}])
        self.assertEqual((1, "invalid"), (code, reply["refused"]))
        self.assertIn("edited since it was written", reply["say"])
        self.assertEqual(hand_edited, self.note.read_text(encoding="utf-8"))


class TestTheWrite(CheckpointCase):
    def test_a_kill_between_the_temporary_file_and_the_rename_leaves_the_earlier_block(self):
        written = self.first()
        before = self.note.read_bytes()
        base, prev = self.state()
        with mock.patch.object(lib.os, "replace", side_effect=OSError(5, "killed")):
            with self.assertRaises(OSError):
                self.send(base=base, prev=prev, items=[{"kind": "incomplete", "text": "something else"}])
        self.assertEqual(before, self.note.read_bytes())
        self.assertNotIn("something else", self.note.read_text(encoding="utf-8"))
        _, reply = self.send(read=True)
        self.assertEqual(written["key"], reply["key"])
        self.assertTrue(reply["valid"])
        self.assertEqual([], [p for p in self.note.parent.iterdir() if p.name.startswith(".")])

    def test_a_note_that_changed_while_it_was_read_is_not_written_over(self):
        """The compare between the temporary file and the rename: another
        writer got there first, so nothing is written and nothing is lost."""
        base, prev = self.state()
        text = self.note.read_text(encoding="utf-8")
        mine = text.replace("| Waiting on | Dana |", "| Waiting on | Theo |")

        def meanwhile(*args, **kwargs):
            self.note.write_text(text.replace("Drafted;", "Drafted and sent;"), encoding="utf-8")
            return original(*args, **kwargs)

        original = lib.Path.write_bytes
        with mock.patch.object(lib.Path, "write_bytes", meanwhile):
            self.assertFalse(lib.write_if_unchanged(self.note, mine, text.encode("utf-8")))
        self.assertIn("Drafted and sent;", self.note.read_text(encoding="utf-8"))
        self.assertNotIn("Theo", self.note.read_text(encoding="utf-8"))
        self.assertEqual([], [p for p in self.note.parent.iterdir() if p.name.startswith(".")])


class TestEverythingOutsideTheMarkers(CheckpointCase):
    def test_written_rewritten_and_folded_leaves_every_other_byte_alone(self):
        original = self.note.read_bytes()
        resume = self.resume()
        todo = self.todo.read_bytes()

        self.first()
        self.assertEqual(original.decode("utf-8"), self.outside())
        self.assertEqual(resume, self.resume())

        base, prev = self.state()
        code, _ = self.send(base=base, prev=prev, items=[
            {"kind": "next", "text": "send the sheet to Dana", "by": "user"},
            {"kind": "deadline", "date": "2026-03-20", "said": "Dana needs it by the twentieth"}])
        self.assertEqual(0, code)
        self.assertEqual(original.decode("utf-8"), self.outside())

        base, prev = self.state()
        code, _ = self.send(base=base, prev=prev, drop=["m1", "d1", "c1"], items=[
            {"kind": "incomplete", "text": "nothing left"}])
        self.assertEqual(0, code)
        # Folding is the wrap's: take the block and its heading out, and the
        # note is byte for byte the one the session started with.
        self.assertEqual(original, self.outside().encode("utf-8"))
        self.assertEqual(resume, self.resume())
        self.assertEqual(todo, self.todo.read_bytes())

    def test_the_dated_entries_and_the_rule_are_never_touched(self):
        self.first()
        text = self.note.read_text(encoding="utf-8")
        for entry in ("**13 March 2026.** Asked Dana for the volumes.",
                      "**8 March 2026.** Drafted the memo.",
                      "**1 March 2026.** Opened the thread.",
                      "<Dated entries, newest first. Never edit an old one.>"):
            self.assertEqual(1, text.count(entry), entry)
        self.assertEqual(1, text.count("\n---\n\n<Dated entries"))
        block = lib.read_checkpoint(text)
        self.assertTrue(block["valid"])
        self.assertEqual(6, len(block["items"]))
        self.assertLess(block["span"][1], text.index("\n---\n\n<Dated entries"))

    def test_todo_md_is_never_written(self):
        before = self.todo.read_bytes()
        self.first()
        base, prev = self.state()
        self.send(base=base, prev=prev, items=[
            {"kind": "action", "text": "chase the volumes", "said": "I'll chase her", "date": "2026-03-20"}])
        self.assertEqual(before, self.todo.read_bytes())
        self.assertNotIn("chase the volumes", self.todo.read_text(encoding="utf-8"))


class TestOneReadingOfEach(CheckpointCase):
    """The checkpoint reuses what the workspace already has: the resume
    block's extent, and what makes two lines the same action. Both live in one
    place, and these hold that place against the other reader of it."""

    def test_resume_lines_reads_a_block_as_check_py_reads_it(self):
        check = load(TOOLS / "check.py", "garrick_check_checkpoint")
        self.first()
        for text in (NOTE, self.note.read_text(encoding="utf-8"), "no block here\n",
                     "### Resume here\n\n| a | b |\n\n### Checkpoint\n\nx\n"):
            self.assertEqual(check.resume_block(text), lib.resume_lines(text))

    def test_same_action_reads_a_line_as_the_todo_list_reads_it(self):
        todo_lines = load(REPO / "extras" / "status" / "todo_lines.py", "garrick_todo_lines_checkpoint")
        for line in ("- [ ] [[Pricing]]: send Dana the sheet 📅 2026-03-20",
                     "send  Dana the sheet.", "Send DANA the sheet",
                     "- [ ] chase the volumes · [src](x.md) (also in [[a]](b.md)) ⏫ 📅 2026-03-20",
                     "- **Incomplete** half done"):
            self.assertEqual(todo_lines.same_action(line), lib.same_action(line))


class TestTheCommandLine(CheckpointCase):
    def test_it_takes_json_on_stdin_and_prints_json_whatever_happens(self):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        req = json.dumps({"verb": "checkpoint", "zone": "Work", "project": PROJECT, "thread": THREAD,
                          "read": True})
        done = subprocess.run([sys.executable, str(SCAFFOLD), "--root", str(self.root), "checkpoint"],
                              input=req, capture_output=True, text=True, env=env)
        self.assertEqual(0, done.returncode, done.stderr)
        self.assertIsNone(json.loads(done.stdout)["key"])
        done = subprocess.run([sys.executable, str(SCAFFOLD), "--root", str(self.root), "checkpoint"],
                              input="not json at all", capture_output=True, text=True, env=env)
        self.assertEqual(1, done.returncode)
        self.assertEqual("request", json.loads(done.stdout)["refused"])

    def test_the_verb_is_declared_and_keeps_no_journal_entry(self):
        self.assertIn("checkpoint", ops.DECLARED)
        self.assertNotIn("checkpoint", ops.RECORDED)
        self.assertNotIn("checkpoint", ops.OPS)
        self.assertEqual("checkpoint", ops.DECLARED["checkpoint"].precheck)
        self.assertFalse(ops.DECLARED["checkpoint"].commits)
        self.assertIsNotNone(ops.validate("checkpoint", {"verb": "checkpoint", "nope": 1}))


if __name__ == "__main__":
    unittest.main()
