"""Answering a wiki question from the command line (#224, points 2 to 4):
page_action.py's question-answer, question-later, question-close, the refused
decision, and the read of what an answered question may change. The answer is
a raw record first; a page across a wall is never changed.

    python3 -m unittest test_wiki_answers
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import write  # noqa: E402
from test_page_action import ActionCase, TODAY, pa  # noqa: E402

SENTENCE = "A wall holds some material back from this project, so I have not used it. Nothing was written."
ACME = "[[wiki/sources/260310-acme-kickoff]]"
BIRCH = "[[wiki/sources/260312-birch-kickoff]]"


def question(fields="zone: Work\nparties: [acme]\n", pages=ACME, status="open", extra=""):
    return ("---\ntype: question\nasked: 2026-03-12\nstatus: %s\n%s%sorigin: \"[[raw/260310-acme-kickoff]]\"\n"
            "pages: [\"%s\"]\n---\n\n**Acme: which volume floor holds, 400 pallets or 500?**\n\nThe call and the mail differ.\n"
            % (status, fields, extra, pages))


def snapshot(root: Path) -> dict:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted((root).rglob("*")) if p.is_file() and ".git" not in p.parts}


class WikiAnswerCase(ActionCase):
    def setUp(self):
        super().setUp()
        self.meetings = self.root / "Wikis" / "Meetings"
        self.knowledge = self.root / "Wikis" / "Knowledge"
        self.q = "questions/260312 - volume-floor.md"

    def ask(self, text=None, wiki="Meetings", name=None):
        base = self.meetings if wiki == "Meetings" else self.knowledge
        write(base / (name or self.q), text if text is not None else question())
        return name or self.q

    def do(self, verb, wiki="Meetings", **kw):
        return pa.act(self.root, dict(verb=verb, wiki=wiki, file=kw.pop("file", self.q), **kw), today=TODAY)

    def changed(self, before):
        after = snapshot(self.root)
        return sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))


class TestOutcomes(WikiAnswerCase):
    def test_answer_writes_the_record_and_the_question_and_nothing_else(self):
        self.ask()
        before = snapshot(self.root)
        say = self.do("question-answer", words="It is 500 pallets, from March.")
        self.assertIn("raw/answers/261005 - volume-floor", say)
        self.assertEqual(["Wikis/Meetings/questions/260312 - volume-floor.md",
                          "Wikis/Meetings/raw/answers/261005 - volume-floor.md"], self.changed(before))
        record = (self.meetings / "raw" / "answers" / "261005 - volume-floor.md").read_text()
        self.assertIn("```\nIt is 500 pallets, from March.\n```", record)
        self.assertIn("Question: Acme: which volume floor holds, 400 pallets or 500?", record)
        self.assertIn("answered: 2026-10-05", record)
        self.assertIn("zone: Work\nparties: [acme]", record)
        text = (self.meetings / self.q).read_text()
        self.assertIn("status: answered", text)
        self.assertIn('answer: "[[raw/answers/261005 - volume-floor]]"', text)

    def test_the_words_are_kept_word_for_word_even_with_fences(self):
        self.ask()
        words = "Use ```500``` and\n  keep   the spacing."
        self.do("question-answer", words=words)
        record = (self.meetings / "raw" / "answers" / "261005 - volume-floor.md").read_text()
        self.assertIn("````\n%s\n````" % words, record)

    def test_the_record_is_filed_before_the_question_changes(self):
        self.ask()
        seen = []
        real = pa.write_question

        def spy(path, text):
            seen.append((self.meetings / "raw" / "answers" / "261005 - volume-floor.md").is_file())
            return real(path, text)
        with mock.patch.object(pa, "write_question", spy):
            self.do("question-answer", words="500")
        self.assertEqual([True], seen)

    def test_a_question_that_cannot_be_written_keeps_the_record_and_says_so(self):
        self.ask()
        with mock.patch.object(pa, "write_question", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(pa.Refused, "filed as raw/answers/261005 - volume-floor.*stays"):
                self.do("question-answer", words="500")
        self.assertTrue((self.meetings / "raw" / "answers" / "261005 - volume-floor.md").is_file())
        self.assertIn("status: open", (self.meetings / self.q).read_text())

    def test_a_record_already_there_is_never_touched(self):
        self.ask()
        write(self.meetings / "raw" / "answers" / "261005 - volume-floor.md", "kept\n")
        self.do("question-answer", words="500")
        self.assertEqual("kept\n", (self.meetings / "raw" / "answers" / "261005 - volume-floor.md").read_text())
        self.assertIn("500", (self.meetings / "raw" / "answers" / "261005 - volume-floor-2.md").read_text())

    def test_nine_names_taken_refuses(self):
        self.ask()
        write(self.meetings / "raw" / "answers" / "261005 - volume-floor.md", "x\n")
        for n in range(2, 10):
            write(self.meetings / "raw" / "answers" / ("261005 - volume-floor-%d.md" % n), "x\n")
        before = snapshot(self.root)
        with self.assertRaisesRegex(pa.Refused, "nothing was written"):
            self.do("question-answer", words="500")
        self.assertEqual([], self.changed(before))

    def test_answer_needs_words_and_an_open_question(self):
        self.ask()
        before = snapshot(self.root)
        for words in (None, "", "  \n"):
            with self.assertRaises(pa.Refused):
                self.do("question-answer", **({} if words is None else {"words": words}))
        self.do("question-answer", words="500")
        after = snapshot(self.root)
        with self.assertRaisesRegex(pa.Refused, "answered, not open"):
            self.do("question-answer", words="400")
        self.assertEqual(after, snapshot(self.root))
        self.assertNotEqual(before, after)

    def test_later_writes_only_the_question(self):
        self.ask()
        before = snapshot(self.root)
        self.do("question-later", until="2026-11-01")
        self.assertEqual(["Wikis/Meetings/questions/260312 - volume-floor.md"], self.changed(before))
        text = (self.meetings / self.q).read_text()
        self.assertIn("status: later", text)
        self.assertIn("later: 2026-11-01", text)

    def test_later_needs_a_day_to_come(self):
        self.ask()
        before = snapshot(self.root)
        for until in (None, "", "tomorrow", "2026-10-05", "2026-09-01", 5):
            with self.assertRaises(pa.Refused, msg=until):
                self.do("question-later", **({} if until is None else {"until": until}))
        self.assertEqual([], self.changed(before))

    def test_close_writes_only_the_question(self):
        self.ask(question(status="later", extra="later: 2026-11-01\n"))
        before = snapshot(self.root)
        self.do("question-close")
        self.assertEqual(["Wikis/Meetings/questions/260312 - volume-floor.md"], self.changed(before))
        text = (self.meetings / self.q).read_text()
        self.assertIn("status: closed", text)
        self.assertNotIn("later:", text)
        self.assertFalse((self.meetings / "raw" / "answers").exists())

    def test_a_decision_is_refused_and_writes_nothing(self):
        self.ask()
        before = snapshot(self.root)
        with self.assertRaisesRegex(pa.Refused, "Record as a decision is not built yet, so nothing was written"):
            self.do("question-decide")
        self.assertEqual([], self.changed(before))

    def test_an_unknown_field_or_a_path_outside_questions_is_refused(self):
        self.ask()
        write(self.meetings / "wiki" / "sources" / "x.md", question())
        before = snapshot(self.root)
        for bad in ({"file": "wiki/sources/x.md"}, {"file": "../questions/260312 - volume-floor.md"},
                    {"file": "/etc/passwd"}, {"wiki": "Other"}):
            with self.assertRaises(pa.Refused, msg=bad):
                self.do("question-close", **bad)
        with self.assertRaises(pa.Refused):
            pa.act(self.root, dict(verb="question-close", wiki="Meetings", file=self.q, zone="Work"), today=TODAY)
        self.assertEqual([], self.changed(before))

    def test_the_words_are_not_logged(self):
        self.assertNotIn("words", pa.LOGGED)


class TestWalls(WikiAnswerCase):
    def test_a_page_across_the_wall_is_left_out_and_the_sentence_said(self):
        self.ask(question(pages=BIRCH))
        before = snapshot(self.root)
        self.do("question-answer", words="500")
        self.changed(before)
        say = self.do("question-work")
        self.assertIn(SENTENCE, say)
        self.assertNotIn("birch", say.lower())
        self.assertIn("No page may be changed.", say)

    def test_pages_on_the_questions_side_are_listed(self):
        self.ask()
        self.do("question-answer", words="500")
        say = self.do("question-work")
        self.assertIn("Change wiki/sources/260310-acme-kickoff.md", say)
        self.assertIn("Cite [[raw/answers/261005 - volume-floor]].", say)
        self.assertNotIn(SENTENCE, say)

    def test_a_page_that_cannot_be_read_plainly_is_left_out(self):
        write(self.meetings / "wiki" / "sources" / "260401-unfinished.md", "---\ntitle: x\ntype: meeting\n---\n\nbody\n")
        self.ask(question(pages="[[wiki/sources/260401-unfinished]]"))
        self.do("question-answer", words="500")
        say = self.do("question-work")
        self.assertIn(SENTENCE, say)
        self.assertNotIn("260401", say)

    def test_pages_on_both_sides_are_refused_with_the_sentence_and_nothing_named(self):
        self.ask(question(pages="%s\", \"%s" % (ACME, BIRCH)))
        before = snapshot(self.root)
        for verb, kw in (("question-answer", {"words": "500"}), ("question-later", {"until": "2026-11-01"}),
                         ("question-close", {})):
            with self.assertRaises(pa.Refused) as caught:
                self.do(verb, **kw)
            self.assertEqual(SENTENCE, str(caught.exception))
        self.assertEqual([], self.changed(before))

    def test_a_question_naming_both_sides_is_refused(self):
        self.ask(question("zone: Work\nparties: [acme, birch]\n"))
        before = snapshot(self.root)
        with self.assertRaises(pa.Refused) as caught:
            self.do("question-answer", words="500")
        self.assertEqual(SENTENCE, str(caught.exception))
        self.assertEqual([], self.changed(before))

    def test_a_question_with_no_zone_or_parties_is_refused(self):
        for fields in ("", "parties: [acme]\n", "zone: Work\n", "zone: Work\nparties: [nobody]\n", "zone: Nowhere\nparties: [acme]\n"):
            self.ask(question(fields))
            before = snapshot(self.root)
            with self.assertRaisesRegex(pa.Refused, "unfinished"):
                self.do("question-close")
            self.assertEqual([], self.changed(before), fields)

    def test_a_frontmatter_a_reader_could_take_two_ways_is_refused(self):
        self.ask(question("zone: Work\nparties: [acme]\nparties: [birch]\n"))
        before = snapshot(self.root)
        with self.assertRaisesRegex(pa.Refused, "cannot be read plainly"):
            self.do("question-answer", words="500")
        self.assertEqual([], self.changed(before))

    def test_a_knowledge_question_with_no_parties_works_normally(self):
        name = "questions/260312 - source-date.md"
        self.ask("---\ntype: question\nasked: 2026-03-12\nstatus: open\norigin: \"[[raw/supply-chain-report]]\"\n"
                 "pages: [\"[[wiki/sources/supply-chain-report]]\", \"[[wiki/concepts/resilience]]\"]\n---\n\n"
                 "**Which year is the report from?**\n\nIt says two.\n", wiki="Knowledge", name=name)
        before = snapshot(self.root)
        self.do("question-answer", wiki="Knowledge", file=name, words="2025.")
        self.assertEqual(["Wikis/Knowledge/questions/260312 - source-date.md",
                          "Wikis/Knowledge/raw/answers/261005 - source-date.md"], self.changed(before))
        record = (self.knowledge / "raw" / "answers" / "261005 - source-date.md").read_text()
        self.assertNotIn("zone:", record)
        self.assertNotIn("parties:", record)
        say = self.do("question-work", wiki="Knowledge", file=name)
        self.assertIn("Change wiki/sources/supply-chain-report.md", say)
        self.assertIn("Change wiki/concepts/resilience.md", say)
        self.assertEqual("Done. The question is worked in", self.do("question-done", wiki="Knowledge", file=name))
        self.assertIn("status: done", (self.knowledge / name).read_text())

    def test_a_knowledge_question_with_parties_is_refused(self):
        name = "questions/260312 - source-date.md"
        self.ask(question(pages="[[wiki/sources/supply-chain-report]]"), wiki="Knowledge", name=name)
        with self.assertRaisesRegex(pa.Refused, "no zone and no parties"):
            self.do("question-close", wiki="Knowledge", file=name)


class TestOwnRecord(WikiAnswerCase):
    """F1: the record an answered question cites is its own, or nothing is printed."""

    def planted(self, record_parties="[birch]", name="260312 - volume-floor"):
        write(self.meetings / "raw" / "answers" / "261005 - birch-secret-lease.md",
              "---\ntype: answer\nanswered: 2026-10-05\nzone: Work\nparties: %s\nquestion: \"[[questions/%s]]\"\n---\n\n"
              "Question: x\n\n```\nthe lease ends in spring\n```\n" % (record_parties, "260312 - birch-lease"))
        self.ask(question(status="answered", extra='answer: "[[raw/answers/261005 - birch-secret-lease]]"\n'))

    def test_another_partys_record_is_never_cited_or_named(self):
        self.planted()
        before = snapshot(self.root)
        for verb in ("question-work", "question-done"):
            with self.assertRaises(pa.Refused) as caught:
                self.do(verb)
            self.assertEqual(SENTENCE, str(caught.exception))
            self.assertNotIn("birch", str(caught.exception).lower())
        self.assertEqual([], self.changed(before))

    def test_a_record_of_another_question_with_the_same_parties_is_refused_too(self):
        self.planted("[acme]")           # its question: link lands on another file
        with self.assertRaises(pa.Refused) as caught:
            self.do("question-work")
        self.assertEqual(SENTENCE, str(caught.exception))

    def test_a_knowledge_record_of_another_question_is_refused_plainly(self):
        name = "questions/260312 - source-date.md"
        write(self.knowledge / "raw" / "answers" / "261005 - other.md",
              "---\ntype: answer\nanswered: 2026-10-05\nquestion: \"[[questions/260312 - elsewhere]]\"\n---\n\nx\n")
        self.ask("---\ntype: question\nasked: 2026-03-12\nstatus: answered\nanswer: \"[[raw/answers/261005 - other]]\"\n"
                 "pages: []\n---\n\n**Which year?**\n", wiki="Knowledge", name=name)
        with self.assertRaisesRegex(pa.Refused, "not a record of this question"):
            self.do("question-work", wiki="Knowledge", file=name)

    def test_its_own_record_still_works_straight_after_the_answer(self):
        self.ask()
        self.do("question-answer", words="500")
        self.assertIn("Cite [[raw/answers/261005 - volume-floor]].", self.do("question-work"))
        self.assertEqual("Done. The question is worked in", self.do("question-done"))


class TestPagesToChange(WikiAnswerCase):
    """F2: only a page of wiki/ is ever offered for change."""

    def test_raw_records_questions_and_the_answer_are_not_pages(self):
        self.ask()
        write(self.meetings / "questions" / "260313 - other.md", question())
        pages = ['[[raw/260310-acme-kickoff]]', '[[questions/260313 - other]]', '[[questions/260312 - volume-floor]]',
                 '[[raw/answers/261005 - volume-floor]]', ACME]
        self.ask(question(pages='", "'.join(pages)))
        self.do("question-answer", words="500")
        say = self.do("question-work")
        self.assertIn("Change wiki/sources/260310-acme-kickoff.md", say)
        self.assertEqual(1, say.count("Change "))
        self.assertIn("4 pages are not there.", say)


class TestWorkIn(WikiAnswerCase):
    def test_work_and_done_need_an_answered_question_with_a_record(self):
        self.ask()
        for verb in ("question-work", "question-done"):
            with self.assertRaisesRegex(pa.Refused, "not answered"):
                self.do(verb)
        self.ask(question(status="answered", extra='answer: "[[raw/answers/261005 - volume-floor]]"\n'))
        for verb in ("question-work", "question-done"):
            with self.assertRaisesRegex(pa.Refused, "no raw answer"):
                self.do(verb)

    def test_done_writes_only_the_status(self):
        self.ask()
        self.do("question-answer", words="500")
        before = snapshot(self.root)
        self.do("question-done")
        self.assertEqual(["Wikis/Meetings/questions/260312 - volume-floor.md"], self.changed(before))
        self.assertIn("status: done", (self.meetings / self.q).read_text())

    def test_work_reads_and_writes_nothing(self):
        self.ask()
        self.do("question-answer", words="500")
        before = snapshot(self.root)
        self.do("question-work")
        self.assertEqual([], self.changed(before))


class TestCommandLine(WikiAnswerCase):
    def test_the_session_form_names_a_wiki_not_a_zone(self):
        self.ask()
        args = pa.command_parser().parse_args(["question-answer", "--wiki", "Meetings", "--file", self.q, "--words", "500"])
        self.assertEqual({"verb": "question-answer", "wiki": "Meetings", "file": self.q, "words": "500"},
                         pa.session_request(self.root, args))
        args = pa.command_parser().parse_args(["question-close", "--file", self.q])
        with self.assertRaisesRegex(pa.Refused, "no wiki given"):
            pa.session_request(self.root, args)

    def test_every_verb_is_declared(self):
        ops = pa.ops_lib(self.root)
        for verb in ("question-answer", "question-later", "question-close", "question-decide", "question-work", "question-done"):
            self.assertIn(verb, ops.DECLARED)
            self.assertIn(verb, pa.VERBS)


if __name__ == "__main__":
    unittest.main()
