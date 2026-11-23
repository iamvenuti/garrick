"""A held history move retries instead of asking (#661).

    cd tests && python3 -m unittest test_history_hold

Invented names only: the project is Acme Review, the thread Freight.
"""

from __future__ import annotations

import datetime
import json
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import write  # noqa: E402
from test_nurture import Base, JOBS, TOOLS, load, nurture  # noqa: E402
from test_nurture_history import entries, TODAY  # noqa: E402

sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(JOBS))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "extras" / "status"))
import finding_queue as fq  # noqa: E402
import history  # noqa: E402

FREIGHT = "Zones/Work/Acme Review/Threads/Freight/Freight.md"


class Held(Base):
    def setUp(self):
        super().setUp()
        self.freight = self.acme / "Threads" / "Freight" / "Freight.md"
        text = self.freight.read_text(encoding="utf-8")
        write(self.freight, text.rstrip("\n") + "\n\n---\n\n" + entries(30))
        self.commit(self.work, "2026-10-01T10:00:00")

    def records(self):
        path = self.root / "System" / "generated" / "nurture" / "2026-10-17.json"
        rec = json.loads(path.read_text(encoding="utf-8"))
        return [dict(f, scope=nurture.debt_scope(f["path"])) for f in rec["standing"]]

    def questions(self):
        got = fq.forecast_questions(self.records(), set(), ws=self.root)
        return [q for qs in got.values() for q in qs if q["path"] == FREIGHT and q["id"] in ("note-long",) + fq.HISTORY_KINDS + ("fix-failed",)]

    def item(self):
        return next(f for f in self.records() if f["path"] == FREIGHT)


class TestATransientHold(Held):
    def test_a_note_held_because_a_session_is_mid_turn_makes_no_question_and_is_tried_again(self):
        before = self.freight.read_text(encoding="utf-8")
        with mock.patch.object(nurture, "busy", return_value=True):
            code, out = self.run_tool("nightly")
        self.assertEqual(before, self.freight.read_text(encoding="utf-8"))       # a held note's file is unchanged
        self.assertFalse((self.freight.parent / "history").exists())
        f = self.item()
        self.assertEqual("mechanical", f["kind"])
        self.assertIn("(held: a session is mid-turn there)", f["line"])
        self.assertEqual([], self.questions())
        self.assertEqual("mechanical", fq.plain_kind(f))
        code, out = self.run_tool("nightly")                                          # no session there now
        self.assertIn("history", {i["fix"]["op"] for i in out["fixed"]})
        self.assertLessEqual(len(self.freight.read_text(encoding="utf-8").split()), 4000)
        self.assertEqual([], [f for f in self.records() if f["path"] == FREIGHT])

    def test_the_morning_line_does_not_say_somebody_is_waited_on(self):
        with mock.patch.object(nurture, "busy", return_value=True):
            _, out = self.run_tool("nightly")
        mine = nurture.Item("check", "threads", FREIGHT, "has 9000 words, over the 4000 of `note-max-words`", kind="mechanical",
                            held="a session is mid-turn there", fix={"op": "history"})
        self.assertTrue(nurture.waits_for_tonight(mine))
        done = {"fixed": []}
        self.assertEqual({}, nurture.waiting(done, [mine]))
        self.assertEqual({"mechanical": 1}, nurture.waiting(done, [nurture.Item("check", "links", FREIGHT, "x", kind="mechanical", held="y")]))

    def test_a_hold_that_has_no_fix_to_carry_stays_mechanical_and_names_its_reason(self):
        with mock.patch.object(history, "compute", return_value=(mock.Mock(moves=[1]), {}, "a history file is being written")):
            _, out = self.run_tool("list")
        (i,) = [i for i in out["items"] if i["path"] == FREIGHT and i["check"] == "threads"]
        self.assertEqual("mechanical", i["kind"])
        self.assertIn("(held: a history file is being written)", i["line"] if "line" in i else json.dumps(i))
        self.assertIsNone(i["fix"])
        self.assertEqual("", i["said"])
        self.assertTrue(nurture.waits_for_tonight(nurture.Item("check", "threads", FREIGHT, i["message"], kind="mechanical",
                                                                held=i["held"])))

    def test_the_attended_move_still_applies_on_a_yes(self):
        with mock.patch.object(nurture, "busy", return_value=True):
            self.run_tool("nightly")
        code, out = self.run_tool("fix", "--yes")
        self.assertIn("history", {i["fix"]["op"] for i in out["fixed"]})


class TestAHoldTheUserSettles(Held):
    def run_hold(self):
        _, out = self.run_tool("nightly")
        return out

    def quarter_file(self):
        found = history.plan(self.root, self.freight, TODAY)
        return sorted(found.quarters)[0]

    def test_a_foreign_history_file_is_one_question_naming_it_without_the_move(self):
        name = "Freight history %s.md" % self.quarter_file()
        folder = self.freight.parent / "history"
        write(folder / name, "---\ntype: note\n---\n\n# Something else\n")
        self.commit(self.work, "2026-10-02T10:00:00")
        before = (folder / name).read_text(encoding="utf-8")
        self.run_hold()
        self.assertEqual(before, (folder / name).read_text(encoding="utf-8"))
        f = self.item()
        self.assertEqual("judgment", f["kind"])
        (q,) = self.questions()
        self.assertEqual("history-foreign", q["id"])
        self.assertIn(name, q["sentence"])
        self.assertIn("Freight", q["sentence"])
        self.assertNotIn("move-older", [a["id"] for a in q["answers"]])
        self.assertNotIn("Move older entries", " ".join(a["label"] for a in q["answers"]))
        self.assertIn("Rename it", q["why"])
        self.assertIn("next free name", q["why"])

    def test_a_history_file_with_another_heading_is_one_question_naming_it(self):
        name = "Freight history %s.md" % self.quarter_file()
        write(self.freight.parent / "history" / name,
              '---\ntype: history\nparent: "%s"\ncreated: 2026-10-01\n---\n\n# Freight, the old record\n\n**1 July 2026.** x.\n'
              % history.note_link(self.freight))
        self.commit(self.work, "2026-10-02T10:00:00")
        self.run_hold()
        (q,) = self.questions()
        self.assertEqual("history-heading", q["id"])
        self.assertIn(name, q["sentence"])
        self.assertNotIn("move-older", [a["id"] for a in q["answers"]])

    def test_a_note_with_no_rule_under_state_of_play_is_one_question(self):
        text = self.freight.read_text(encoding="utf-8").replace("\n---\n\n**", "\n\n**", 1)
        write(self.freight, text)
        self.commit(self.work, "2026-10-02T10:00:00")
        self.run_hold()
        (q,) = self.questions()
        self.assertEqual("history-rule", q["id"])
        self.assertIn("Freight", q["sentence"])
        self.assertNotIn("move-older", [a["id"] for a in q["answers"]])
        self.assertEqual(text, self.freight.read_text(encoding="utf-8"))

    def test_the_three_answers_change_no_file_and_hand_over_to_a_visible_assistant(self):
        for kind in fq.HISTORY_KINDS:
            for a in fq.ANSWERS[kind]:
                self.assertIn(a["action"], ("handoff", "open", "later"))
            q = fq.question({"kind": "judgment", "check": "threads", "path": FREIGHT, "scope": "Zones/Work",
                             "line": "%s: has 9000 words, over the 4000 of `note-max-words`; move (held: %s)" % (FREIGHT, {
                                 "history-foreign": "Freight history 2026-Q3.md exists and is not a history file of this note",
                                 "history-heading": "Freight history 2026-Q3.md exists and its heading differs from the one this tool writes",
                                 "history-rule": history.NO_RULE}[kind])}, "Zones/Work")
            self.assertEqual(kind, q["id"])
            self.assertTrue(all("req" not in a or a["action"] == "later" for a in q["answers"]), kind)
            self.assertTrue(next(a for a in q["answers"] if a["action"] == "handoff")["phrase"])

    def test_the_questions_are_made_from_history_pys_own_sentences(self):
        self.assertTrue(fq.HOLD_FOREIGN.match(history.NOT_HISTORY % "A history 2026-Q1.md"))
        self.assertTrue(fq.HOLD_HEADING.match(history.HEADING_DIFFERS % "A history 2026-Q1.md"))
        self.assertEqual(fq.HOLD_RULE, history.NO_RULE)
        self.assertEqual(("foreign", "A history 2026-Q1.md"), history.hold_kind(history.NOT_HISTORY % "A history 2026-Q1.md"))
        self.assertEqual(("heading", "A history 2026-Q1.md"), history.hold_kind(history.HEADING_DIFFERS % "A history 2026-Q1.md"))
        self.assertEqual(("rule", ""), history.hold_kind(history.NO_RULE))
        self.assertEqual("later", history.hold_kind("a session is mid-turn there")[0])
        self.assertEqual("later", history.hold_kind("")[0])

    def test_a_note_no_move_can_read_keeps_its_old_question_with_split_first(self):
        text = self.freight.read_text(encoding="utf-8").replace("## State of play", "## Where it stands", 1)
        write(self.freight, text)
        self.commit(self.work, "2026-10-02T10:00:00")
        self.run_hold()
        f = self.item()
        self.assertEqual("judgment", f["kind"])
        (q,) = self.questions()
        self.assertEqual("note-long", q["id"])
        self.assertEqual("split", q["answers"][0]["id"])


class TestNothingToMove(Held):
    def test_a_note_over_its_limit_with_no_entries_to_move_says_so_and_asks_split_first(self):
        text = self.freight.read_text(encoding="utf-8")
        write(self.freight, text[:text.index("\n\n---\n\n**")] + "\n\n---\n\n" + entries(3, words=2000))
        self.commit(self.work, "2026-10-02T10:00:00")
        import io, contextlib
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            history.main(["--root", str(self.root), "dry-run", FREIGHT, "--today", "2026-10-17"])
        said = out.getvalue()
        self.assertIn("is over its limit, but none of its dated entries is old enough to move", said)
        self.assertNotIn("no note is over its limits", said)
        self.run_tool("nightly")
        (q,) = self.questions()
        self.assertEqual("note-long", q["id"])
        self.assertEqual("split", q["answers"][0]["id"])
        self.assertNotIn("move-older", [a["id"] for a in q["answers"]])

    def test_no_note_over_its_limit_still_says_nothing_to_move(self):
        import io, contextlib
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            history.main(["--root", str(self.root), "dry-run", "Zones/Work/Acme Review/Acme Review.md"])
        self.assertIn("Nothing to move: no note is over its limits.", out.getvalue())


class TestSevenNights(Held):
    def day(self, n, held=True, path=FREIGHT):
        d = datetime.date(2026, 10, 17) - datetime.timedelta(days=n)
        standing = [{"kind": "mechanical", "path": path, "check": "threads",
                     "line": "%s: has 9000 words, over the 4000 of `note-max-words`; move its older dated entries to history files (held: a session is mid-turn there)" % path}] if held else []
        write(self.root / "System" / "generated" / "nurture" / ("%s.json" % d.isoformat()),
              json.dumps({"date": d.isoformat(), "runs": [], "standing": standing}))

    def line(self):
        return nurture.hold_line(nurture.Ctx(self.root, headless=True, today=datetime.date(2026, 10, 17)))

    def test_a_note_held_seven_nights_in_a_row_is_named_once_in_one_line(self):
        for n in range(7):
            self.day(n)
        self.assertEqual("The note Freight has waited at least a week for its older entries to move.", self.line())
        self.assertNotIn("Zones", self.line())

    def test_six_nights_name_nothing_and_a_missing_day_breaks_the_run(self):
        for n in range(6):
            self.day(n)
        self.assertEqual("", self.line())
        for n in range(8):
            self.day(n)
        (self.root / "System" / "generated" / "nurture" / "2026-10-14.json").unlink()
        self.assertEqual("", self.line())

    def test_the_eighth_night_does_not_name_it_again_and_the_fourteenth_does(self):
        for n in range(8):
            self.day(n)
        self.assertEqual("", self.line())
        for n in range(14):
            self.day(n)
        self.assertIn("Freight", self.line())

    def test_a_night_without_the_hold_ends_the_run(self):
        for n in range(7):
            self.day(n)
        self.day(3, held=False)
        self.assertEqual("", self.line())

    def test_the_morning_digest_carries_the_line_and_never_a_question(self):
        sweep = load("garrick_nurture_sweep", JOBS / "nurture_sweep.py")
        out = {"digest": "Nothing needed fixing overnight.", "hold_line": "The note Freight has waited at least a week for its older entries to move.",
               "code": 0, "waiting": 0, "items": []}
        write(self.root / "System" / "tools" / "nurture.py", "# a stand-in\n")
        sent = []
        with mock.patch.object(sweep, "run", return_value=out), mock.patch.object(sweep, "send_digest", side_effect=sent.append):
            sweep.main(["--workspace", str(self.root), "--digest"])
        self.assertEqual(["Nothing needed fixing overnight.\nThe note Freight has waited at least a week for its older entries to move."], sent)


if __name__ == "__main__":
    unittest.main()
