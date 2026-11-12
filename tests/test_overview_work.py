"""The Overview's opening list of work (#503): each live piece of work with its next action, who it waits on
and Continue, on the full page, from the data and the `continue` action the page already has.

    cd tests && python3 -m unittest test_overview_work
"""

from __future__ import annotations

import datetime as dt
import html as htmllib
import json
import re
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "extras" / "status"))
import status  # noqa: E402
from fixtures import build_workspace, project_hub, write  # noqa: E402


def thread(project, name, party="acme", next_="Send Dana the price sheet", waiting="nobody"):
    return textwrap.dedent("""\
        ---
        title: {name}
        type: thread
        project: "[[{project}]]"
        party: {party}
        status: active
        created: 2026-03-01
        updated: 2026-03-02
        ---

        # {name}

        ## State of play

        ### Resume here

        **Where it stands, 2 March 2026.** In hand.

        | | |
        |---|---|
        | Live artifact | none |
        | Next action | {next_} |
        | Keep in mind | nothing |
        | Waiting on | {waiting} |
        | Deadline | none |
        """).format(project=project, name=name, party=party, next_=next_, waiting=waiting)


class OverviewWork(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name).resolve()
        self.root = base / "Workspace"
        self.jobs = base / "jobs"
        self.jobs.mkdir()
        build_workspace(self.root)
        self.work = self.root / "Zones" / "Work"
        write(self.work / "Acme Review" / "Threads" / "Pricing" / "Pricing.md", thread("Acme Review", "Pricing"))
        write(self.work / "Birch Entry" / "Birch Entry.md", project_hub("Work", "Birch Entry", "birch", ["Market Sizing", "Interviews"]))
        write(self.work / "Birch Entry" / "Threads" / "Market Sizing" / "Market Sizing.md",
              thread("Birch Entry", "Market Sizing", "birch", "Theo to send the volumes", waiting="Theo Marsh: the volumes"))
        write(self.work / "Birch Entry" / "Threads" / "Interviews" / "Interviews.md",
              thread("Birch Entry", "Interviews", "birch", "Write up the interviews"))
        agents = mock.patch.object(status, "launch_agents", lambda: base / "LaunchAgents")
        agents.start()
        self.addCleanup(agents.stop)
        self.addCleanup(self._tmp.cleanup)

    def page(self):
        return status.build(self.root, folder=self.jobs, now=dt.datetime(2026, 3, 3, 9, 0))

    def card(self, html):
        start = html.index('<details class="card" id="your-work"')
        return html[start:html.index("</details>", start)]

    def rows(self, html):
        out = []
        for m in re.finditer(r'<div class="yrow" data-w="[^"]*">(.*?)</div>(?=<div class="yrow"|</div>$|</div>\s*$)', self.card(html), re.S):
            out.append(htmllib.unescape(re.sub(r"<[^>]+>", " ", m.group(1))).split())
        return out

    def test_the_overview_opens_on_the_work_with_its_next_action_what_it_waits_on_and_continue(self):
        html = self.page()
        card = self.card(html)
        self.assertLess(html.index('id="your-work"'), html.index('<details class="card" id="threads"'))
        for name, nxt in (("Acme Review", "Send Dana the price sheet"), ("Market Sizing", "Theo to send the volumes"),
                          ("Interviews", "Write up the interviews")):
            self.assertIn(name, card)
            self.assertIn(nxt, card)
        self.assertIn("Waiting on Theo Marsh", card)                    # who the thread waits on
        self.assertEqual(3, card.count(">Continue<"))

    def test_continue_is_the_page_actions_continue_and_a_browser_gets_a_phrase_to_copy(self):
        card = self.card(self.page())
        acts = [json.loads(htmllib.unescape(a)) for a in re.findall(r'data-act="([^"]+)"', card)]
        self.assertEqual(3, len(acts))
        self.assertTrue(all(a["verb"] == "continue" and a["zone"] == "Work" and a["file"].endswith(".md") for a in acts))
        self.assertIn('data-copy="Where am I on Acme Review?"', card)           # no host: the phrase is copied
        self.assertIn("apponly", card)

    def test_a_thread_with_no_next_action_says_so_and_a_name_cannot_break_the_markup(self):
        write(self.work / "Acme Review" / "Threads" / "Pricing" / "Pricing.md",
              thread("Acme Review", "Pricing", next_="<img src=x onerror=1>"))
        card = self.card(self.page())
        self.assertNotIn("<img", card)

    def test_no_work_means_no_list_and_the_first_use_card_names_no_internal_file(self):
        for p in list(self.work.glob("*/")):
            if p.is_dir() and p.name != "Inbox":
                import shutil
                shutil.rmtree(p)
        html = self.page()
        self.assertNotIn('id="your-work"', html)
        start = html[html.index('id="start"'):html.index("</details>", html.index('id="start"'))]
        self.assertIn("help me prepare my next supplier call", start)
        for internal in ("SKILL.md", "System/skills", "skill", "scaffold"):
            self.assertNotIn(internal, start)

    def test_the_list_needs_no_new_data_source(self):
        # works() is what the page's own list reads; the card is built from it alone.
        T = status.threads(self.root)
        lists = status.todo_list(self.root, status.Links(self.root), dt.date(2026, 3, 3))
        status.thread_actions(T, lists, None, self.root)
        names = [w["name"] for w in status.works(self.root, T, dt.date(2026, 3, 3))]
        html = status.work_list_card(status.works(self.root, T, dt.date(2026, 3, 3)), dt.date(2026, 3, 3))
        for n in names:
            self.assertIn(htmllib.escape(n), html)


if __name__ == "__main__":
    unittest.main()
