"""#711: empty states and counts that explain themselves, on the built page.

    cd tests && python3 -m unittest test_empty_states

Each of the issue's four parts is read from the page itself: the Context card before the first Nurture run, the Threads
card with no thread, the Status tab's badge against the cards the Status tab holds, and a waiting reason that the line cuts.
Invented names only.
"""

from __future__ import annotations

import html as htmllib
import json
import re
import shutil
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

from fixtures import write  # noqa: E402
from fixtures import project_hub  # noqa: E402
from test_overview_work import thread  # noqa: E402
from test_status import StatusCase, status  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
CLEAN = "import json\nprint(json.dumps({'errors': 0, 'warnings': 0, 'findings': []}))\n"


class Never(StatusCase):
    """A workspace whose check ran and found nothing, and that has never run Nurture."""

    def setUp(self):
        super().setUp()
        shutil.copytree(REPO / "template" / "System" / "tools", self.root / "System" / "tools",
                        ignore=shutil.ignore_patterns("__pycache__"))
        (self.root / "System" / "tools" / "check.py").write_text(CLEAN, encoding="utf-8")
        status._NURTURE.clear()
        self.addCleanup(status._NURTURE.clear)

    def card(self, html, id_="checks"):
        start = html.index('<details class="card" id="%s"' % id_)
        ends = [i for i in (html.find('<details class="card" id="', start + 1), html.find("</section>", start)) if i > 0]
        return html[start:min(ends)]


class TestTheContextTabBeforeTheFirstNurtureRun(Never):
    def test_it_says_that_nothing_needs_you_yet(self):
        card = self.card(self.page())
        self.assertIn('<p class="hint nonee" id="nsum">Nothing needs you yet.</p>', card)
        self.assertNotIn("Last nurture", card)

    def test_it_does_not_say_so_while_the_check_lists_something_or_did_not_run(self):
        (self.root / "System" / "tools" / "check.py").write_text(
            "import json\nprint(json.dumps({'errors': 0, 'warnings': 1, 'findings': [{'check': 'x', 'severity': 'warning', 'path': 'a.md', 'message': 'm'}]}))\n",
            encoding="utf-8")
        self.assertNotIn("Nothing needs you", self.card(self.page()))
        (self.root / "System" / "tools" / "check.py").unlink()
        self.assertNotIn("Nothing needs you", self.card(self.page()))

    def test_after_a_nurture_run_it_keeps_its_old_words(self):
        day = self.now.date()
        write(self.root / "System" / "generated" / "nurture" / ("%s.json" % day.isoformat()), json.dumps(
            {"date": day.isoformat(), "standing": [], "debt": {"total": 0, "kinds": {}, "scopes": {}, "whole": True, "threshold": 40}}))
        card = self.card(self.page())
        self.assertIn('<p class="hint nonee" id="nsum">Nothing needs you.</p>', card)
        self.assertNotIn("Nothing needs you yet", card)


class TestAnEmptyThreadsCardDropsItsLegend(Never):
    LEGEND = "hover one for what to do"

    def line(self, html):
        return re.search(r'<p class="hint gsum mu">(.*?)</p>', self.card(html, "threads"), re.S).group(1)

    def test_a_card_with_threads_keeps_the_legend(self):
        line = self.line(self.page())
        self.assertIn(self.LEGEND, line)
        self.assertIn("Bar and number", line)
        self.assertIn("Dot: a session is open in it", line)

    def test_a_card_with_no_thread_says_the_count_and_nothing_to_explain(self):
        for project in ("Acme Review", "Birch Entry"):
            shutil.rmtree(self.root / "Zones" / "Work" / project)
        line = self.line(self.page())
        self.assertEqual("0 live · 0 parked", line)
        self.assertNotIn(self.LEGEND, line)


class TestTheStatusTabsCountIsWhatItShows(unittest.TestCase):
    def trouble(self, html):
        return json.loads(re.search(r'id="trouble-data">(.*?)</script>', html, re.S).group(1))

    def badge(self, html):
        m = re.search(r'<span class="n (?:crit|warn)" id="tabn-status"[^>]*>(?:<svg.*?</svg>)?(\d+)</span>', html, re.S)
        return int(m.group(1)) if m else 0

    def shown(self, html):
        """The troubles whose card the Status tab holds, read from the page."""
        tab = html[html.index('<section class="tab" id="tab-status"'):]
        tab = tab[:tab.index("</section>")]
        held = set(re.findall(r'<details class="card" id="([^"]+)"', tab))
        return [t for t in self.trouble(html) if t[1] in held]

    def build(self, beats, inbox):
        from test_status_look import build_with_beats
        return build_with_beats(beats, (lambda root: write(root / "Zones" / "Work" / "Inbox" / "a note.md", "A note.\n")) if inbox else None)

    def test_a_trouble_on_the_overview_is_not_counted_on_the_status_tab(self):
        html = self.build({}, inbox=True)
        self.assertEqual(["waiting-now"], [t[1] for t in self.trouble(html)])         # the inboxes: a row of the Overview
        self.assertEqual([], self.shown(html))
        self.assertEqual(0, self.badge(html))
        self.assertNotIn('id="tabn-status"', html)

    def test_the_badge_equals_the_troubles_on_the_cards_the_tab_holds_beside_one_it_does_not(self):
        html = self.build({"gr-nightly": {"title": "Nightly check", "reason": "Recall timed out"}}, inbox=True)
        self.assertEqual(2, len(self.trouble(html)))                  # the failed job, and the inboxes
        shown = self.shown(html)
        self.assertEqual(["jobs"], [t[1] for t in shown])
        self.assertEqual(len(shown), self.badge(html))
        self.assertRegex(html, r'<span class="n crit" id="tabn-status" aria-label="1 thing needs attention"')


class TestAReasonTheLineCutsReadsInFull(StatusCase):
    LONG = "Theo Marsh: a very long wait for the volumes from the Birch finance team, which the board needs before the March review"

    def setUp(self):
        super().setUp()
        work = self.root / "Zones" / "Work"
        write(work / "Birch Entry" / "Birch Entry.md", project_hub("Work", "Birch Entry", "birch", ["Market Sizing", "Interviews"]))
        write(work / "Birch Entry" / "Threads" / "Market Sizing" / "Market Sizing.md",
              thread("Birch Entry", "Market Sizing", "birch", "Theo to send the volumes", waiting="Theo Marsh: the volumes"))
        write(work / "Birch Entry" / "Threads" / "Interviews" / "Interviews.md",
              thread("Birch Entry", "Interviews", "birch", "Write up the interviews", waiting=self.LONG))

    def card(self, html):
        start = html.index('<details class="card" id="your-work"')
        return html[start:html.index("</details>", start)]

    def wait(self, html, name):
        row = next(r for r in re.findall(r'<div class="yrow".*?(?=<div class="yrow"|</details>)', self.card(html), re.S) if name in r)
        return re.search(r'<span class="ywait".*?</span></span>|<span class="ywait"[^>]*>[^<]*</span>', row, re.S).group(0)

    def test_the_rest_of_the_reason_is_in_the_line_for_a_tap_and_not_only_in_the_hover(self):
        w = self.wait(self.page(), "Interviews")
        self.assertIn('tabindex="0"', w)                                       # a tap or the keyboard focuses it: no new control
        self.assertIn('data-tip="Waiting on %s' % self.LONG.split(":")[0], htmllib.unescape(w))
        self.assertRegex(htmllib.unescape(w), r'Waiting on Theo Marsh<span class="yrest">: a very long wait for the volumes')
        self.assertIn("before the March review</span>", w)
        self.assertNotRegex(w, r"<(details|summary|button|a)\b")

    def test_a_focused_reason_wraps_and_shows_its_rest_at_every_width(self):
        css = status.YOURWORK_CSS
        self.assertIn("display:none", css.split(".yrest{")[1].split("}")[0])
        focus = css.split(".ywait:focus{")[1].split("}")[0]
        for word in ("white-space:normal", "overflow:visible", "overflow-wrap:anywhere"):
            self.assertIn(word, focus)
        self.assertIn("display:inline", css.split(".ywait:focus .yrest{")[1].split("}")[0])
        self.assertIn("white-space:nowrap", css.split(".ywait{")[1].split("}")[0])           # closed, the line is as tall as before

    def test_a_short_reason_is_as_it_was(self):
        card = self.card(self.page())
        self.assertRegex(htmllib.unescape(card), r'<span class="ywait" tabindex="0" data-tip="Waiting on Theo Marsh: the volumes">Waiting on Theo Marsh<span class="yrest">: the volumes</span></span>')
        self.assertEqual("", status.waiting_rest("Theo Marsh"))
        self.assertEqual("", status.waiting_rest("Theo Marsh:"))
        self.assertEqual(": the volumes", status.waiting_rest("Theo Marsh: the volumes"))
        self.assertEqual("; the volumes: late", status.waiting_rest("**Theo Marsh**; the volumes: late"))


if __name__ == "__main__":
    unittest.main()
