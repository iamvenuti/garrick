"""Open sections as questions (#224, point 8): wiki_lint.py lists each line under
an *Open* or *Open issues* heading, and page_action.py's question-open-sections
writes one question file per line on a yes, never changes a page, and carries
the page's own zone and parties.

    python3 -m unittest test_open_sections
"""

from __future__ import annotations

import sys
import unittest

sys.dont_write_bytecode = True

from fixtures import meeting_page, write  # noqa: E402
import wiki_lint  # noqa: E402  (fixtures puts the tools folder on sys.path)
from test_page_action import pa  # noqa: E402
from test_wiki_answers import SENTENCE, WikiAnswerCase, snapshot  # noqa: E402

ACME = "wiki/sources/260310-acme-kickoff"
BIRCH = "wiki/sources/260312-birch-kickoff"
OPEN = "\n## Open\n\n- Who signs the volume floor?\n- Which version of the price list is live?\n\n## Next\n\nDone.\n"


class OpenCase(WikiAnswerCase):
    def page(self, key, zone="Work", parties="[acme]", title="Acme kick-off", tail=OPEN):
        write(self.meetings / (key + ".md"), meeting_page(zone, parties, title) + tail)

    def run_verb(self, wiki="Meetings", **kw):
        return pa.act(self.root, dict(verb="question-open-sections", wiki=wiki, **kw), today=pa.dt.date(2026, 10, 5))

    def files(self, wiki="Meetings"):
        folder = self.root / "Wikis" / wiki / "questions"
        return sorted(p for p in folder.glob("*.md")) if folder.is_dir() else []


class TestLint(OpenCase):
    def test_each_line_of_each_open_section_is_listed(self):
        self.page(ACME)
        write(self.meetings / (BIRCH + ".md"), meeting_page("Work", "[birch]", "Birch kick-off")
              + "\n### Open issues\n1. Is the pilot paid?\n   Nobody has said.\n\n## Other\n\n- not this\n")
        rows = wiki_lint.open_sections(self.meetings)
        self.assertEqual([(ACME, "Who signs the volume floor?"), (ACME, "Which version of the price list is live?"),
                          (BIRCH, "Is the pilot paid? Nobody has said.")], [(r["page"], r["line"]) for r in rows])
        self.assertTrue(all(r["state"] == "propose" for r in rows))

    def test_none_and_fenced_lines_are_not_questions(self):
        self.page(ACME, tail="\n## Open\n\nNone\n\n```\n- code\n```\n")
        self.assertEqual([], wiki_lint.open_sections(self.meetings))

    def test_the_lint_says_it_and_writes_nothing(self):
        self.page(ACME)
        before = snapshot(self.root)
        text = wiki_lint.say(wiki_lint.lint(self.meetings))
        self.assertIn("Open sections: 2 lines, 2 to propose", text)
        self.assertIn("[[%s]]: Who signs the volume floor?" % ACME, text)
        self.assertEqual(before, snapshot(self.root))

    def test_a_page_with_no_zone_or_two_zones_gets_none_and_the_reason(self):
        self.page(ACME, zone=None)
        self.page(BIRCH, zone="[Work, Personal]", title="Birch kick-off")
        rows = wiki_lint.open_sections(self.meetings)
        self.assertTrue(rows and all(r["state"] == "skipped" for r in rows))
        reasons = {r["page"]: r["reason"] for r in rows}
        self.assertIn("no zone", reasons[ACME])
        self.assertIn("more than one zone", reasons[BIRCH])
        text = wiki_lint.say(wiki_lint.lint(self.meetings))
        self.assertIn("no question for [[%s]]: it has no zone" % ACME, text)

    def test_a_page_with_no_parties_still_gets_its_question_for_parties_are_an_index(self):
        self.page(ACME, parties=None)
        rows = wiki_lint.open_sections(self.meetings)
        self.assertTrue(rows and all(r["state"] == "propose" for r in rows))


class TestConversion(OpenCase):
    def test_a_read_writes_nothing(self):
        self.page(ACME)
        before = snapshot(self.root)
        say = self.run_verb()
        self.assertIn("2 open lines would become a question, in 1 group.", say)
        self.assertIn("Who signs the volume floor?", say)
        self.assertEqual(before, snapshot(self.root))
        self.assertEqual(before, snapshot(self.root))

    def test_no_yes_means_no_question_file(self):
        self.page(ACME)
        self.run_verb(confirm=False)
        self.assertEqual([], self.files())

    def test_a_yes_writes_one_file_per_line_and_the_page_is_unchanged(self):
        self.page(ACME)
        before = snapshot(self.root)
        say = self.run_verb(confirm=True)
        self.assertIn("2 questions written in Meetings/questions. No page was changed", say)
        self.assertEqual(2, len(self.files()))
        after = snapshot(self.root)
        new = sorted(set(after) - set(before))
        self.assertEqual(2, len(new))
        self.assertTrue(all(k.startswith("Wikis/Meetings/questions/261005 - ") for k in new))
        self.assertTrue(all(before[k] == after[k] for k in before))                   # the page and everything else
        text = self.files()[0].read_text()
        self.assertIn("type: question\nasked: 2026-10-05\nstatus: open\nzone: Work\nparties: [acme]\n", text)
        self.assertIn('origin: "[[%s]]"' % ACME, text)
        self.assertIn('pages: ["[[%s]]"]' % ACME, text)
        self.assertRegex(text, r"(?m)^\*\*Open on Acme kick-off: .+\*\*$")

    def test_the_question_files_pass_the_workspace_check(self):
        self.page(ACME)
        self.run_verb(confirm=True)
        for q in self.files():
            rel = q.relative_to(self.meetings).as_posix()
            self.assertEqual("", self.do("question-close", file=rel) and "")            # a file the panel can act on

    def test_a_second_run_proposes_nothing_already_converted(self):
        self.page(ACME)
        self.run_verb(confirm=True)
        say = self.run_verb()
        self.assertIn("0 open lines would become a question, in 0 groups.", say)
        self.assertIn("2 already asked.", say)
        before = snapshot(self.root)
        self.assertIn("Nothing to write", self.run_verb(confirm=True))
        self.assertEqual(before, snapshot(self.root))

    def test_a_question_closed_or_answered_still_counts_as_asked(self):
        self.page(ACME)
        self.run_verb(confirm=True)
        for q in self.files():
            self.do("question-close", file=q.relative_to(self.meetings).as_posix())
        self.assertEqual(0, len([r for r in wiki_lint.open_sections(self.meetings) if r["state"] == "propose"]))

    def test_a_page_with_no_zone_gives_no_question_and_only_the_sentence(self):
        self.page(ACME, zone=None)
        before = snapshot(self.root)
        say = self.run_verb(confirm=True)
        self.assertIn("Nothing to write", say)
        self.assertEqual([], self.files())
        self.assertEqual(before, snapshot(self.root))
        say = self.run_verb()
        self.assertIn(SENTENCE, say)             # only the rule's sentence, never why
        self.assertNotIn("No question for", say)

    def test_a_knowledge_question_has_no_zone_and_no_parties(self):
        write(self.knowledge / "wiki" / "concepts" / "resilience.md", "# Resilience\n\n## Open issues\n\n- Is the 80% figure independent?\n")
        self.run_verb("Knowledge", confirm=True)
        (q,) = self.files("Knowledge")
        text = q.read_text()
        self.assertNotIn("zone:", text)
        self.assertNotIn("parties:", text)
        self.assertIn('origin: "[[wiki/concepts/resilience]]"', text)
        self.assertEqual("# Resilience\n\n## Open issues\n\n- Is the 80% figure independent?\n",
                         (self.knowledge / "wiki" / "concepts" / "resilience.md").read_text())

    def test_a_knowledge_page_that_carries_parties_gets_none(self):
        write(self.knowledge / "wiki" / "concepts" / "odd.md", "---\ntype: concept\nparties: [acme]\n---\n\n## Open\n\n- A thing?\n")
        self.assertIn("Nothing to write", self.run_verb("Knowledge", confirm=True))
        self.assertEqual([], self.files("Knowledge"))

    def test_a_failed_check_leaves_nothing(self):
        self.page(ACME)
        before = snapshot(self.root)
        from unittest import mock
        with mock.patch.object(pa, "check_counts", side_effect=[{"check:error": 0}, {"check:error": 1}]):
            with self.assertRaises(pa.Refused):
                self.run_verb(confirm=True)
        self.assertEqual(before, snapshot(self.root))

    def test_it_runs_from_the_command_line_too(self):
        self.page(ACME)
        args = pa.command_parser().parse_args(["question-open-sections", "--wiki", "Meetings", "--confirm", "true"])
        req = pa.session_request(self.root, args)
        self.assertEqual(dict(verb="question-open-sections", wiki="Meetings", confirm="true"), req)
        pa.act(self.root, req, today=pa.dt.date(2026, 10, 5))
        self.assertEqual(2, len(self.files()))


class TestWalls(OpenCase):
    def test_the_question_carries_the_pages_zone_and_parties_exactly(self):
        self.page(ACME)
        write(self.meetings / (BIRCH + ".md"), meeting_page("Work", "[birch]", "Birch kick-off") + "\n## Open\n\n- Is the pilot paid?\n")
        self.run_verb(confirm=True)
        seen = {}
        for q in self.files():
            text = q.read_text()
            origin = pa.re.search(r'origin: "\[\[(.+?)\]\]"', text).group(1)
            seen.setdefault(origin, set()).add(pa.re.search(r"parties: (.+)", text).group(1))
            self.assertIn("zone: Work\n", text)
        self.assertEqual({ACME: {"[acme]"}, BIRCH: {"[birch]"}}, seen)

    def test_a_page_in_two_walled_zones_gets_none_and_only_the_sentence(self):
        self.page(ACME, zone="[Work, Personal]")
        say = self.run_verb()
        self.assertIn(SENTENCE, say)
        self.assertNotIn("personal", say.lower())
        self.assertNotIn("No question for", say)
        self.assertIn("Nothing to write", self.run_verb(confirm=True))
        self.assertEqual([], self.files())

    def test_an_unknown_zone_gets_none_and_only_the_sentence(self):
        self.page(ACME, zone="Nowhere", parties="[acme]")
        say = self.run_verb()
        self.assertIn(SENTENCE, say)
        self.assertNotIn("nowhere", say.lower())
        self.assertIn("Nothing to write", self.run_verb(confirm=True))
        self.assertEqual([], self.files())

    def test_a_page_filter_limits_what_is_written(self):
        self.page(ACME)
        write(self.meetings / (BIRCH + ".md"), meeting_page("Personal", "[birch]", "Birch kick-off") + "\n## Open\n\n- Is the pilot paid?\n")
        self.run_verb(confirm=True, pages=[BIRCH])
        (q,) = self.files()
        self.assertIn("zone: Personal", q.read_text())


class TestGroups(OpenCase):
    def two(self):
        self.page(ACME)
        write(self.meetings / (BIRCH + ".md"), meeting_page("Personal", "[birch]", "Home visit") + "\n## Open\n\n- Is the pilot paid?\n")

    def test_the_read_groups_by_zone_and_asks_once_per_group(self):
        self.two()
        say = self.run_verb()
        self.assertIn("in 2 groups. Ask once per group, never for two together.", say)
        self.assertEqual(["Group (Personal):", "Group (Work):"], [l for l in say.splitlines() if l.startswith("Group")])
        lines = say.splitlines()
        home, work = lines.index("Group (Personal):"), lines.index("Group (Work):")
        self.assertIn("Is the pilot paid?", "\n".join(lines[home:work]))
        self.assertNotIn("Is the pilot paid?", "\n".join(lines[work:]))

    def test_a_confirm_over_two_groups_is_refused_and_writes_nothing(self):
        self.two()
        before = snapshot(self.root)
        for kw in ({}, {"pages": [ACME, BIRCH]}, {"pages": "%s,%s" % (ACME, BIRCH)}):
            with self.assertRaisesRegex(pa.Refused, "more than one zone"):
                self.run_verb(confirm=True, **kw)
        self.assertEqual(before, snapshot(self.root))

    def test_a_confirm_takes_one_group_at_a_time(self):
        self.two()
        self.run_verb(confirm=True, pages=[ACME])
        self.assertEqual(2, len(self.files()))
        self.run_verb(confirm=True, pages=[BIRCH])
        self.assertEqual(3, len(self.files()))

    def test_two_pages_of_one_zone_are_one_group_whatever_their_parties(self):
        self.page(ACME)
        self.page("wiki/sources/260311-acme-second", parties="[birch]", title="Acme second")
        self.assertIn("in 1 group.", self.run_verb())
        self.run_verb(confirm=True)
        self.assertEqual(4, len(self.files()))


class TestRefusals(OpenCase):
    def test_a_wrong_wiki_or_pages_is_refused(self):
        for kw in ({"wiki": "Nowhere"}, {"pages": 3}, {"confirm": "yes"}):
            with self.assertRaises(pa.Refused):
                self.run_verb(**dict({"wiki": "Meetings"}, **kw))


if __name__ == "__main__":
    unittest.main()
