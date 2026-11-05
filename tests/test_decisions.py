"""Record as a decision (#224, point 5): page_action.py's question-decide, the decision
page kind, the panel's list of decisions to review, and check.py's warning for a
`status:` changed with no raw answer the same day. Walls first: a decision carries its
question's zone and parties, copied exactly, and is never listed across a wall.

    cd tests && python3 -m unittest test_decisions
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import write  # noqa: E402
from test_nurture_panel_actions import SENTENCE, PanelCase, commit_all, snap  # noqa: E402
from test_page_action import TODAY, git, pa  # noqa: E402
from test_questions_panel import ACME, BIRCH, qp, question, status  # noqa: E402

TOOLS = Path(__file__).resolve().parent.parent / "template" / "System" / "tools"
spec = importlib.util.spec_from_file_location("garrick_check_decisions_test", str(TOOLS / "check.py"))
check = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = check
spec.loader.exec_module(check)

Q = "questions/261001 - acme.md"
DECISION = "wiki/decisions/261005 - acme.md"
RECORD = "raw/answers/261005 - acme.md"
WORDS = "We hold the 500 pallet floor from March.\n## Assumptions\nnot a section"


def decision(parties="[acme]", status="valid", extra="", zone="Work", source=RECORD[:-3]):
    head = ["type: decision", "title: \"Acme: which volume floor holds?\"", "status: %s" % status, "decided: 2026-10-05"]
    if zone:
        head.append("zone: %s" % zone)
    if parties:
        head.append("parties: %s" % parties)
    head += ["source: \"[[%s]]\"" % source, "question: questions/261001 - acme", "created: 2026-10-05", "updated: 2026-10-05"]
    return ("---\n%s\n%s---\n\n# Acme: which volume floor holds?\n\n## Decision\n\n```\n500 pallets.\n```\n\n"
            "## Assumptions\n\nNone yet.\n\n## Options turned down\n\nNone yet.\n\n## Revisit when\n\nNot set.\n"
            % ("\n".join(head), extra))


def answer_record(parties="[acme]", answered="2026-10-05"):
    return ("---\ntype: answer\nanswered: %s\nzone: Work\nparties: %s\nquestion: \"[[questions/261001 - acme]]\"\n---\n\n"
            "Question: Acme: which volume floor holds?\n\nAnswered on %s, in the user's own words:\n\n```\n500\n```\n"
            % (answered, parties, answered))


class DecisionCase(PanelCase):
    def setUp(self):
        super().setUp()
        write(self.meetings / Q, question(ACME, pages="[[wiki/sources/260310-acme-kickoff]]"))
        write(self.meetings / "questions/261001 - birch.md", question(BIRCH, parties="[birch]", pages="[[wiki/sources/260312-birch-kickoff]]"))
        commit_all(self.meetings, "questions")

    def decide(self, file=Q, words=WORDS, wiki="Meetings"):
        return pa.act(self.root, dict(verb="question-decide", wiki=wiki, file=file, words=words), today=TODAY)

    def changed(self, before):
        after = snap(self.root)
        return sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))

    def findings(self, code="decisions"):
        return [f for f in check.run_checks(self.root) if f.check == code]


class TestRecordAsADecision(DecisionCase):
    def test_one_transaction_writes_the_raw_answer_the_decision_and_the_question(self):
        before = snap(self.root)
        with mock.patch.object(pa, "transaction", wraps=pa.transaction) as tx:
            say = self.decide()
        self.assertEqual(1, tx.call_count)
        self.assertIn("Recorded as a decision", say)
        self.assertEqual(sorted(["Wikis/Meetings/" + Q, "Wikis/Meetings/" + RECORD, "Wikis/Meetings/" + DECISION]), self.changed(before))
        page = (self.meetings / DECISION).read_text()
        self.assertIn("type: decision\n", page)
        self.assertIn("status: valid\n", page)
        self.assertIn("zone: Work\nparties: [acme]\n", page)
        self.assertIn('source: "[[raw/answers/261005 - acme]]"', page)
        self.assertIn("## Decision\n\n```\n%s\n```" % WORDS, page)                # the words, whole and fenced
        self.assertEqual({"Decision", "Assumptions", "Options turned down", "Revisit when"}, check.decision_sections(page))
        record = (self.meetings / RECORD).read_text()
        self.assertIn("zone: Work\nparties: [acme]", record)
        self.assertIn("```\n%s\n```" % WORDS, record)
        question_text = (self.meetings / Q).read_text()
        self.assertIn("status: answered", question_text)
        self.assertIn('answer: "[[raw/answers/261005 - acme]]"', question_text)
        self.assertIn('decision: "[[wiki/decisions/261005 - acme]]"', question_text)

    def test_the_decision_carries_the_questions_zone_and_parties_exactly(self):
        write(self.meetings / Q, question(ACME, zone="Work", parties="[acme, cedar]"))
        git(self.meetings, "add", "-A")
        self.decide()
        page = (self.meetings / DECISION).read_text()
        self.assertIn("zone: Work\nparties: [acme, cedar]\n", page)
        self.assertIn("parties: [acme, cedar]", (self.meetings / RECORD).read_text())

    def test_a_failure_anywhere_puts_every_file_back(self):
        before = snap(self.root)
        with mock.patch.object(pa, "write_question", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.decide()
        self.assertEqual([], self.changed(before))
        self.assertFalse((self.meetings / "wiki" / "decisions").exists())
        self.assertFalse((self.meetings / "raw" / "answers").exists())

    def test_a_check_that_gets_worse_puts_every_file_back(self):
        before = snap(self.root)
        with mock.patch.object(pa, "walls_on_written", return_value=["Wikis/Meetings/wiki/decisions/261005 - acme.md"]):
            with self.assertRaisesRegex(pa.Refused, "Nothing was written"):
                self.decide()
        self.assertEqual([], self.changed(before))

    def test_the_words_are_needed_and_the_question_must_be_open(self):
        before = snap(self.root)
        for words in (None, "", "  \n"):
            with self.assertRaises(pa.Refused):
                pa.act(self.root, dict(verb="question-decide", wiki="Meetings", file=Q, **({} if words is None else {"words": words})), today=TODAY)
        self.assertEqual([], self.changed(before))
        self.decide()
        with self.assertRaisesRegex(pa.Refused, "answered, not open"):
            self.decide()

    def test_a_name_already_taken_is_never_written_over(self):
        write(self.meetings / DECISION, "kept\n")
        self.decide()
        self.assertEqual("kept\n", (self.meetings / DECISION).read_text())
        self.assertIn("type: decision", (self.meetings / "wiki/decisions/261005 - acme-2.md").read_text())

    def test_a_question_with_no_zone_or_parties_is_refused_and_writes_nothing(self):
        for name, text in (("nozone", question("Nozone: where?", zone="")), ("noparties", question("Noparties: whose?", parties="")),
                           ("unknown", question("Unknown: who?", parties="[zzz]")), ("neither", question("Neither: what?", zone="", parties=""))):
            write(self.meetings / ("questions/261001 - %s.md" % name), text)
        commit_all(self.meetings, "unfinished")
        before = snap(self.root)
        for name in ("nozone", "noparties", "unknown", "neither"):
            with self.assertRaisesRegex(pa.Refused, "unfinished|nothing was written", msg=name):
                self.decide(file="questions/261001 - %s.md" % name)
        self.assertEqual([], self.changed(before))

    def test_a_question_that_names_both_sides_of_a_wall_is_refused_with_the_sentence(self):
        write(self.meetings / "questions/261001 - mixed.md", question("Mixed: whose figure?", parties="[acme, birch]"))
        before = snap(self.root)
        with self.assertRaises(pa.Refused) as caught:
            self.decide(file="questions/261001 - mixed.md")
        self.assertEqual(SENTENCE, str(caught.exception))
        self.assertEqual([], self.changed(before))

    def test_a_zone_that_does_not_own_the_parties_is_refused_with_the_sentence(self):
        write(self.meetings / "questions/261001 - strayed.md", question("Strayed: where?", zone="Personal"))
        before = snap(self.root)
        with self.assertRaises(pa.Refused) as caught:
            self.decide(file="questions/261001 - strayed.md")
        self.assertEqual(SENTENCE, str(caught.exception))
        self.assertEqual([], self.changed(before))

    def test_a_question_naming_its_parties_two_ways_is_refused(self):
        for name, extra in (("both", "party: birch\n"), ("caps", "PARTIES: [birch]\n")):
            write(self.meetings / ("questions/261001 - %s.md" % name), question("Two: which?", extra=extra))
        before = snap(self.root)
        for name in ("both", "caps"):
            with self.assertRaisesRegex(pa.Refused, "two ways|nothing was written", msg=name):
                self.decide(file="questions/261001 - %s.md" % name)
        self.assertEqual([], self.changed(before))

    def test_a_knowledge_question_is_refused_plainly(self):
        k = self.root / "Wikis" / "Knowledge" / "questions" / "260901 - year.md"
        write(k, "---\ntype: question\nasked: 2026-09-01\nstatus: open\n---\n\n**Knowledge: which year?**\n\nThe report differs.\n")
        before = snap(self.root)
        with self.assertRaisesRegex(pa.Refused, "no zone and no parties"):
            self.decide(file="questions/260901 - year.md", wiki="Knowledge")
        self.assertEqual([], self.changed(before))

    def test_the_words_are_not_logged(self):
        self.assertNotIn("words", pa.LOGGED)


class TestWorkingItIn(DecisionCase):
    def test_the_work_in_step_leaves_the_status_as_it_is(self):
        self.decide()
        page = self.meetings / DECISION
        was = page.read_bytes()
        said = pa.act(self.root, dict(verb="question-work", wiki="Meetings", file=Q), today=TODAY)
        self.assertIn("Cite [[raw/answers/261005 - acme]]", said)
        pa.act(self.root, dict(verb="question-done", wiki="Meetings", file=Q), today=TODAY)
        self.assertIn("status: done", (self.meetings / Q).read_text())
        self.assertEqual(was, page.read_bytes())
        self.assertIn("status: valid\n", page.read_text())


class TestWhatTheCheckSays(DecisionCase):
    def test_a_decision_made_through_the_panel_is_clean(self):
        self.decide()
        commit_all(self.meetings, "decide")
        self.assertEqual([], [f.message for f in self.findings()])
        self.assertEqual([], [f.message for f in self.findings("questions")])

    def test_a_hand_edit_of_status_is_warned_about(self):
        self.decide()
        commit_all(self.meetings, "decide")
        page = self.meetings / DECISION
        page.write_text(page.read_text().replace("status: valid", "status: superseded"))
        got = [f.message for f in self.findings() if "`status:` changed" in f.message]
        self.assertEqual(1, len(got), got)
        self.assertIn("valid to superseded", got[0])

    def test_a_committed_hand_edit_is_warned_about_too(self):
        self.decide()
        commit_all(self.meetings, "decide")
        page = self.meetings / DECISION
        page.write_text(page.read_text().replace("status: valid", "status: withdrawn"))
        commit_all(self.meetings, "withdraw")
        self.assertEqual(1, len([f for f in self.findings() if "`status:` changed" in f.message]))

    def test_the_same_edit_with_a_raw_answer_dated_that_day_is_not(self):
        self.decide()
        commit_all(self.meetings, "decide")
        today = dt.date.today()
        write(self.meetings / ("raw/answers/%s - acme-again.md" % today.strftime("%y%m%d")), answer_record(answered=today.isoformat()))
        page = self.meetings / DECISION
        page.write_text(page.read_text().replace("status: valid", "status: superseded"))
        self.assertEqual([], [f for f in self.findings() if "`status:` changed" in f.message])

    def test_a_record_of_another_question_the_same_day_does_not_count(self):
        self.decide()
        commit_all(self.meetings, "decide")
        today = dt.date.today()
        other = answer_record(answered=today.isoformat()).replace("questions/261001 - acme", "questions/261001 - birch")
        write(self.meetings / ("raw/answers/%s - other.md" % today.strftime("%y%m%d")), other)
        page = self.meetings / DECISION
        page.write_text(page.read_text().replace("status: valid", "status: superseded"))
        self.assertEqual(1, len([f for f in self.findings() if "`status:` changed" in f.message]))

    def test_a_rename_with_a_status_edit_in_one_commit_is_warned_about(self):
        self.decide()
        commit_all(self.meetings, "decide")
        old, new = self.meetings / DECISION, self.meetings / "wiki/decisions/261006 - acme-renamed.md"
        new.write_text(old.read_text().replace("status: valid", "status: withdrawn"))
        old.unlink()
        commit_all(self.meetings, "rename and withdraw")
        self.assertEqual(1, len([f for f in self.findings() if "`status:` changed" in f.message]))

    def test_a_plain_rename_is_not(self):
        self.decide()
        commit_all(self.meetings, "decide")
        old, new = self.meetings / DECISION, self.meetings / "wiki/decisions/261006 - acme-renamed.md"
        new.write_text(old.read_text())
        old.unlink()
        commit_all(self.meetings, "rename")
        self.assertEqual([], [f.message for f in self.findings() if "`status:` changed" in f.message])

    def test_a_new_decision_that_does_not_start_valid_is_warned_about(self):
        write(self.meetings / RECORD, answer_record())
        write(self.meetings / DECISION, decision(status="superseded"))
        self.assertTrue([f for f in self.findings() if "is new with `status: superseded`" in f.message])
        commit_all(self.meetings, "hand made")
        self.assertTrue([f for f in self.findings() if "is new with `status: superseded`" in f.message])

    def test_a_new_decision_whose_day_has_no_record_of_its_own_question_is_warned_about(self):
        write(self.meetings / RECORD, answer_record().replace("questions/261001 - acme", "questions/261001 - birch"))
        write(self.meetings / DECISION, decision())
        self.assertTrue([f for f in self.findings() if "no raw answer dated 2026-10-05 for its own question" in f.message])
        write(self.meetings / RECORD, answer_record())
        self.assertEqual([], [f for f in self.findings() if "for its own question" in f.message])

    def test_both_party_keys_on_a_decision_or_a_question_are_warned_about(self):
        write(self.meetings / RECORD, answer_record())
        write(self.meetings / DECISION, decision(extra="party: birch\n"))
        write(self.meetings / "questions/261001 - two.md", question("Two: which?", extra="PARTY: birch\n"))
        messages = [f.message for f in self.findings("decisions") + self.findings("questions")]
        self.assertEqual(2, len([m for m in messages if "both `party` and `parties`" in m]), messages)

    def test_a_decision_with_other_parties_than_its_raw_answer_is_warned_about(self):
        write(self.meetings / RECORD, answer_record())
        write(self.meetings / DECISION, decision(parties="[acme, cedar]"))
        self.assertTrue([f for f in self.findings() if "not its raw answer's" in f.message])

    def test_an_unfinished_decision_and_one_missing_a_section_are_warned_about(self):
        write(self.meetings / RECORD, answer_record())
        write(self.meetings / "wiki/decisions/261005 - nozone.md", decision(zone="", parties=""))
        write(self.meetings / "wiki/decisions/261005 - short.md", decision().replace("## Revisit when\n\nNot set.\n", ""))
        messages = " | ".join(f.message for f in self.findings())
        self.assertIn("unfinished: no zone or parties", messages)
        self.assertIn("no `## Revisit when` section", messages)

    def test_a_decision_citing_a_meeting_across_a_wall_is_warned_about(self):
        write(self.meetings / RECORD, answer_record())
        write(self.meetings / DECISION, decision().replace("None yet.", "See [[wiki/sources/260312-birch-kickoff]].", 1))
        self.assertTrue([f for f in self.findings() if "across a wall" in f.message])

    def test_the_lint_counts_a_decision_as_no_orphan(self):
        self.decide()
        spec_ = importlib.util.spec_from_file_location("garrick_wiki_lint_test", str(TOOLS / "wiki_lint.py"))
        lint = importlib.util.module_from_spec(spec_)
        sys.modules[spec_.name] = lint
        spec_.loader.exec_module(lint)
        found = lint.lint(self.meetings)
        self.assertNotIn("wiki/decisions/261005 - acme", found["orphans"])
        self.assertEqual({}, found["missing"] if isinstance(found.get("missing"), dict) else {})


class TestWhatThePanelLists(DecisionCase):
    def setUp(self):
        super().setUp()
        d = self.meetings / "wiki" / "decisions"
        flagged = "revisit: \"The volume floor changed in the March call.\"\n"
        write(self.meetings / RECORD, answer_record())
        write(d / "261005 - acme.md", decision(extra=flagged))
        write(d / "261005 - birch.md", decision(parties="[birch]", extra=flagged).replace("Acme: which", "Birch: which"))
        write(d / "261005 - mixed.md", decision(parties="[acme, birch]", extra=flagged).replace("Acme: which", "Mixed: which"))
        write(d / "261005 - plain.md", decision(extra="").replace("Acme: which", "Plain: which"))
        write(d / "261005 - old.md", decision(status="superseded", extra=flagged).replace("Acme: which", "Old: which"))
        write(d / "261005 - nobody.md", decision(zone="", parties="", extra=flagged).replace("Acme: which", "Nobody: which"))
        write(d / "261005 - elsewhere.md", decision(zone="Personal", extra=flagged).replace("Acme: which", "Elsewhere: which"))
        commit_all(self.meetings, "decisions")

    def data(self):
        return qp.build(self.root, None, status.nurture_lib(self.root), TODAY, status.Links(self.root))

    def titles(self, bucket):
        return sorted(d["title"] for d in bucket["decisions"])

    def test_each_bucket_lists_only_decisions_on_its_own_side(self):
        d = self.data()
        self.assertEqual(["Acme: which volume floor holds?"], self.titles(d["buckets"]["Work|acme"]))
        self.assertEqual(["Birch: which volume floor holds?"], self.titles(d["buckets"]["Work|birch"]))
        self.assertEqual([], self.titles(d["buckets"]["Work|cedar"]))

    def test_no_view_of_all_lists_a_walled_decision(self):
        d = self.data()
        sel = d["select"]
        self.assertTrue(sel["*|*"]["views"])
        for choice, entry in sel.items():
            for view in entry["views"]:
                held = d["buckets"][view["key"]]["decisions"]
                for item in held:
                    self.assertEqual(view["zone"], item["zone"], choice)
                    if view["party"]:
                        self.assertIn(view["party"], item["parties"], choice)
                        self.assertEqual(sorted(set(item["parties"])), item["parties"])
                        self.assertNotIn("birch" if view["party"] == "acme" else "acme", item["parties"], choice)
        for view in qp.group_views(d["zones"], qp.ALL, qp.ALL):
            blob = json.dumps(d["buckets"][view["key"]]["decisions"])
            for hidden in ("Mixed:", "Plain:", "Old:", "Nobody:", "Elsewhere:"):
                self.assertNotIn(hidden, blob, (view["key"], hidden))
        self.assertNotIn("Birch:", json.dumps(d["buckets"]["Work|acme"]["decisions"]))
        self.assertNotIn("Acme:", json.dumps(d["buckets"]["Work|birch"]["decisions"]))

    def test_a_decision_naming_its_parties_two_ways_is_not_listed(self):
        d = self.meetings / "wiki" / "decisions"
        write(d / "261005 - twoway.md", decision(extra="party: birch\n").replace("Acme: which", "Twoway: which").replace(
            "revisit", "revisit").replace("---\n\n#", "revisit: \"x\"\n---\n\n#", 1))
        write(d / "261005 - caps.md", decision(extra="PARTIES: [birch]\nrevisit: \"x\"\n").replace("Acme: which", "Caps: which"))
        commit_all(self.meetings, "two ways")
        blob = json.dumps(self.data()["buckets"])
        self.assertNotIn("Twoway:", blob)
        self.assertNotIn("Caps:", blob)

    def test_a_decision_with_a_wall_finding_is_not_listed(self):
        write(self.meetings / "wiki/decisions/261005 - acme.md",
              decision(extra="revisit: \"x\"\n").replace("None yet.", "See [[wiki/sources/260312-birch-kickoff]].", 1))
        commit_all(self.meetings, "wall")
        C = status.check(self.root)
        self.assertTrue(any("decisions/261005 - acme" in f["path"] for f in C["findings"]), "the fixture must carry the finding")
        self.assertEqual([], self.titles(qp.build(self.root, C, status.nurture_lib(self.root), TODAY, status.Links(self.root))["buckets"]["Work|acme"]))

    def test_the_page_data_holds_no_decision_from_the_far_side_of_a_view(self):
        d = self.data()
        for key, far in (("Work|acme", "Birch: which"), ("Work|birch", "Acme: which")):
            self.assertNotIn(far, json.dumps(d["buckets"][key]))
        for hidden in ("Mixed: which", "Plain: which", "Old: which", "Nobody: which", "Elsewhere: which"):
            self.assertNotIn(hidden, json.dumps(d["buckets"]))

    def test_the_not_built_yet_texts_are_gone(self):
        self.assertNotIn("not built yet", qp.JS)
        self.assertIn("go('decide'", qp.JS)
        self.assertIn("decisions to review", qp.JS)


if __name__ == "__main__":
    unittest.main()
