"""The Context tab's one card (#542): a line for each zone or wiki that holds something, one queue for every kind, and no
count that adds two zones.

    cd tests && python3 -m unittest test_context_card

Invented names only: the zones are Work and Personal, the projects Acme and Birch.
"""

from __future__ import annotations

import datetime as dt
import html as htmllib
import json
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import write  # noqa: E402
from panel_case import commit_all  # noqa: E402
from test_decisions import RECORD, answer_record, decision  # noqa: E402
from test_questions_panel import ACME, BIRCH, ELSEWHERE, TODAY, Panel, fq, question, status  # noqa: E402

NOW = dt.datetime(2026, 11, 5, 9, 0)
RESUME = ("Zones/Work/Acme/Threads/Pricing/Pricing.md: its Resume here block has 520 words, over the 400 of `resume-max-words`; "
          "the next wrap or Nurture proposes a shorter one, and nothing changes without a yes")
THREAD = "Zones/Work/Acme/Threads/Pricing/Pricing.md"
KNOWLEDGE = "Knowledge: which year?"


class CardCase(Panel):
    def page(self, now=NOW):
        with mock.patch.object(status, "launch_agents", lambda: self.root / "LaunchAgents"):
            return status.build(self.root, now=now, folder=self.jobs)

    def card(self, html):
        start = html.index('<details class="card" id="checks"')
        ends = [i for i in (html.find('<details class="card" id="', start + 1), html.find("</section>", start)) if i > 0]
        return html[start:min(ends)]

    def queue(self, html):
        start = html.index('<dialog id="queue"')
        return html[start:html.index("</dialog>", start)]

    def scope(self, html, scope):
        q = self.queue(html)
        at = q.index('data-scope="%s"' % scope)
        return q[at:q.index("</section>", at)]

    def lines(self, card):
        return dict(re.findall(r'<span class="nsay"><b>([^<]*)</b>: ([^<]*)</span>', card))

    def record(self, standing=(), back=0):
        """A Nurture record, and a quick check that lists what it holds, so the queue keeps it."""
        day = NOW.date() - dt.timedelta(days=back)
        N = status.nurture_lib(self.root)[0]
        scopes = {}
        for f in standing:
            sc = N.debt_scope(f["path"])
            scopes.setdefault(sc, {})
            scopes[sc][f["kind"]] = scopes[sc].get(f["kind"], 0) + 1
        write(self.root / "System" / "generated" / "nurture" / ("%s.json" % day.isoformat()), json.dumps({
            "date": day.isoformat(), "standing": list(standing), "debt": {"total": len(standing), "kinds": {}, "scopes": scopes, "whole": True, "threshold": 40}}))
        listed = [{"check": f.get("check", ""), "severity": "warning", "path": f["path"], "message": f["line"].split(": ", 1)[-1]}
                  for f in standing if f["kind"] != "wall"]
        write(self.root / "System" / "tools" / "check.py", "import json\nprint(json.dumps(%r))\n" % {
            "errors": 0, "warnings": len(listed), "findings": listed})
        status._NURTURE.clear()
        self.addCleanup(status._NURTURE.clear)


class TestOneLineForEachPlace(CardCase):
    def test_a_line_names_a_places_questions_and_answers_and_a_place_with_nothing_has_none(self):
        self.record()
        card = self.card(self.page())
        self.assertEqual({"Work": "2 questions · 1 answer to work in · about 5 minutes",
                          "Personal": "1 question · about 5 minutes",
                          "The Knowledge wiki": "1 question · about 5 minutes"}, self.lines(card))
        for q in (self.meetings / "questions" / "261001 - elsewhere.md", ):
            q.unlink()
        card = self.card(self.page())
        self.assertNotIn("Personal", self.lines(card))                              # a zone with nothing has no line
        self.assertEqual(["Work", "The Knowledge wiki"], list(self.lines(card)))     # zones first, then the wikis

    def test_a_failing_findings_read_still_shows_the_wikis_questions(self):
        self.record()
        with mock.patch.object(status, "finding_queues", return_value=None):
            html = self.page()
        card = self.card(html)
        self.assertIn("question", self.lines(card).get("Work", ""))                # the zone's wiki question line is still there
        self.assertIn('data-qopen="Zones/Work"', card)
        self.assertIn('data-scope="Zones/Work"', self.queue(html))

    def test_nothing_anywhere_says_so_once_a_record_exists(self):
        for f in list((self.meetings / "questions").glob("*.md")) + [self.knowledge_q]:
            f.unlink()
        self.record()
        card = self.card(self.page())
        self.assertIn("Nothing needs you.", card)
        self.assertEqual({}, self.lines(card))
        self.assertNotIn("data-qopen", card)

    def test_without_a_record_the_card_does_not_claim_nothing_needs_you(self):
        for f in list((self.meetings / "questions").glob("*.md")) + [self.knowledge_q]:
            f.unlink()
        card = self.card(self.page())
        self.assertNotIn("Nothing needs you.", card)

    def test_a_work_line_counts_works_questions_verdicts_decisions_and_findings_together_and_nothing_else(self):
        write(self.meetings / "questions" / "261001 - birch.md", question(BIRCH, parties="[birch]", extra="verdict: done\nverdict_reason: the call settled it\n"))
        write(self.meetings / RECORD, answer_record())
        write(self.meetings / "wiki" / "decisions" / "261005 - acme.md", decision(extra='revisit: "A later meeting named another vendor."\n'))
        commit_all(self.meetings, "kinds")
        self.record([{"kind": "judgment", "check": "resume", "path": THREAD, "line": RESUME}])
        html = self.page()
        card = self.card(html)
        lines = self.lines(card)
        self.assertEqual("4 questions · 1 answer to work in · about 5 minutes", lines["Work"])   # one question, one verdict, one decision, one finding
        self.assertEqual("1 question · about 5 minutes", lines["Personal"])
        self.assertIn("3 places need you.", card)                                    # places, and never a figure that adds two zones
        for added in ("5 questions", "6 questions", "in all", "7 questions"):
            self.assertNotIn(added, card)
        work = self.scope(html, "Zones/Work")
        self.assertEqual(4, work.count("data-q "))
        self.assertEqual(1, self.scope(html, "Zones/Personal").count("data-q "))
        for other in (ELSEWHERE, KNOWLEDGE):
            self.assertNotIn(other, work)                                            # an item is in the queue of its own zone only
        self.assertNotIn(ACME, self.scope(html, "Zones/Personal"))

    def test_no_element_adds_two_zones(self):
        self.record()
        html = self.page()
        card = self.card(html)
        counts = [int(n) for n in re.findall(r'data-n="(\d+)"', card)]
        self.assertEqual([1, 2, 1], counts)                                          # one place's own number on each line
        self.assertEqual(["*", "Zones/Personal", "Zones/Work", "Wikis/Knowledge"],
                         re.findall(r'<option value="([^"]+)">', card))              # the Zone menu: All, then each place
        self.assertNotIn("4 questions", card)                                        # 2 + 1 + 1: never shown
        self.assertEqual(["", ], re.findall(r'id="qp-tab-n">([^<]*)<', html))        # the tab's number is set for one place only, by the script


class TestWorkThemIn(CardCase):
    def test_it_shows_on_a_line_only_when_that_zone_has_answers_waiting(self):
        self.record()
        card = self.card(self.page())
        personal = card[card.index('data-scope="Zones/Personal"'):card.index('data-scope="Zones/Work"')]
        work = card[card.index('data-scope="Zones/Work"'):]
        self.assertIn('data-request="work in the answers in Work"', work)             # the request names its own line's place
        self.assertIn(">Work them in</button>", work)
        self.assertNotIn("Work them in", personal)
        self.assertEqual(1, card.count(">Work them in</button>"))
        for req in re.findall(r'data-request="(work in the answers[^"]*)"', card):         # never another zone's name on a line
            self.assertNotIn("Personal", req)
            self.assertTrue(req.startswith("work in the answers in "), req)


class TestLater(CardCase):
    def test_a_later_with_a_day_after_today_hides_the_question_until_that_day_and_no_due_count_exists(self):
        write(self.meetings / "questions" / "261001 - acme.md", question(ACME, status="later", extra="later: 2026-11-10\n"))
        commit_all(self.meetings, "later")
        self.record()
        before = self.page()
        self.assertNotIn(ACME, before)
        self.assertEqual("1 question · 1 answer to work in · about 5 minutes", self.lines(self.card(before))["Work"])
        on_the_day = self.page(now=dt.datetime(2026, 11, 10, 9, 0))
        self.assertIn(ACME, self.scope(on_the_day, "Zones/Work"))                    # the day has come: a question again
        self.assertEqual("2 questions · 1 answer to work in · about 5 minutes", self.lines(self.card(on_the_day))["Work"])
        for page in (before, on_the_day):
            self.assertNotIn("due today", page)


class TestTheQueueAsksEveryKind(CardCase):
    def setUp(self):
        super().setUp()
        write(self.meetings / "questions" / "261001 - birch.md", question(BIRCH, parties="[birch]", extra="verdict: done\nverdict_reason: the call settled it\n"))
        write(self.meetings / RECORD, answer_record())
        write(self.meetings / "wiki" / "decisions" / "261005 - acme.md", decision(extra='revisit: "A later meeting named another vendor."\n'))
        commit_all(self.meetings, "kinds")
        self.record([{"kind": "judgment", "check": "resume", "path": THREAD, "line": RESUME}])

    def test_a_wiki_question_a_verdict_and_a_decision_each_with_its_answers_and_the_kinds_label(self):
        work = self.scope(self.page(), "Zones/Work")
        for tag in ("Meetings question", "Proposed verdict", "Decision to review", "Tidy up"):
            self.assertIn('<span class="tag">%s</span>' % tag, work)
        self.assertIn('placeholder="Type the answer"', work)                         # the field of a wiki question
        self.assertIn("Record as a decision", work)
        self.assertIn(">Accept<", work)                                              # a verdict
        self.assertIn("Open the decision", work)
        self.assertNotIn("It still holds", work)                                     # left out: only the user changes a decision
        verbs = set(re.findall(r'&quot;verb&quot;: &quot;([a-z-]+)&quot;', work))
        self.assertEqual({"question-answer", "question-decide", "question-later", "question-close", "note-open", "finding"}, verbs)

    def test_the_order_is_walls_first_then_oldest_first(self):
        work = self.scope(self.page(), "Zones/Work")
        tags = re.findall(r'<span class="tag[^"]*">([^<]+)</span>', work)
        self.assertEqual(["Meetings question", "Proposed verdict", "Decision to review", "Tidy up"], tags)   # asked 1 Oct, 1 Oct, decided 5 Oct, no day

    def test_a_not_now_hides_a_verdict_from_the_next_build(self):
        key = fq.later_key("verdict", "Wikis/Meetings/questions/261001 - birch.md")
        write(self.root / "System" / "generated" / "status-later.json", json.dumps({"version": 1, "later": {key: "2026-11-12"}}))
        work = self.scope(self.page(), "Zones/Work")
        self.assertNotIn("Proposed verdict", work)
        self.assertEqual("3 questions · 1 answer to work in · about 5 minutes", self.lines(self.card(self.page()))["Work"])


class TestTheLineBelow(CardCase):
    def test_the_debt_and_the_last_nurture_are_one_line_and_there_is_one_card(self):
        self.record()
        html = self.page()
        card = self.card(html)
        self.assertIn('<p class="hint ndebt"><span>Context debt 0, under 40</span> · Last nurture Thu 05 Nov</p>', card)
        self.assertEqual(1, html.count('<details class="card" id="checks"'))
        self.assertEqual(1, html.count("Context debt"))


if __name__ == "__main__":
    unittest.main()
