"""The Overview's opening list of work (#503): each live piece of work with its next action, who it waits on
and Continue, on the full page, from the data and the `continue` action the page already has.

    cd tests && python3 -m unittest test_overview_work
"""

from __future__ import annotations

import datetime as dt
import html as htmllib
import json
import re
import shutil
import subprocess
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

    def test_the_overview_opens_on_the_work_with_its_next_action_what_it_waits_on_and_a_way_to_open_it(self):
        html = self.page()
        card = self.card(html)
        self.assertLess(html.index('id="your-work"'), html.index('<details class="card" id="threads"'))
        for name, nxt in (("Acme Review", "Send Dana the price sheet"), ("Market Sizing", "Theo to send the volumes"),
                          ("Interviews", "Write up the interviews")):
            self.assertIn(name, card)
            self.assertIn(nxt, card)
        self.assertIn("Waiting on Theo Marsh", card)                    # who the thread waits on
        self.assertNotIn(">Continue<", card)                            # the way to open is the Threads card's (#523)
        self.assertEqual(3, card.count('class="yopen apponly" data-card='))

    def test_the_name_is_two_lines_zone_and_project_in_grey_above_the_thread(self):
        """#523: a thread of several: `Zone / Project` small, the thread in bold. A project of one thread: the zone
        alone above, the project in bold."""
        card = self.card(self.page())
        names = re.findall(r'<span class="yname"><small class="yzone">([^<]*)</small><span class="yline"><b>([^<]*)</b>', card)
        self.assertEqual({("Work", "Acme Review"), ("Work / Birch Entry", "Market Sizing"), ("Work / Birch Entry", "Interviews")},
                         set(names))
        css = status.YOURWORK_CSS
        self.assertIn(".yzone{font-size:12px;font-weight:400;color:var(--muted)}", css)
        self.assertIn(".yline{font-weight:600;color:var(--ink)}", css)
        self.assertIn("grid-template-columns:minmax(140px,.8fr) minmax(200px,2.6fr) minmax(110px,1fr) auto", css)
        self.assertIn("@media(max-width:720px){.yrow{grid-template-columns:1fr auto}.ynext,.ywhy{grid-column:1/-1}}", css)

    def test_the_examples_tag_stays_on_the_bold_line(self):
        with mock.patch.object(status, "example_zone", lambda ws: "Work"):
            card = self.card(self.page())
        self.assertEqual(3, len(re.findall(r'<span class="yline"><b>[^<]*</b><span class="ytag">Example</span></span>', card)))

    def test_the_waiting_badge_is_rendered_and_its_title_stays_plain(self):
        write(self.work / "Birch Entry" / "Threads" / "Market Sizing" / "Market Sizing.md",
              thread("Birch Entry", "Market Sizing", "birch", "Theo to send the volumes", waiting="**Theo Marsh**: the volumes"))
        card = self.card(self.page())
        self.assertIn('Waiting on <b>Theo Marsh</b>', card)
        self.assertIn('title="Waiting on **Theo Marsh**: the volumes"', card)
        self.assertNotIn(">Waiting on **", card)

    def test_an_owner_is_removed_from_the_head_of_a_next_action_as_from_its_tail(self):
        for said, wanted in (("Robin's: send the sheet", "send the sheet"),
                             ("Robin\u2019s: send the sheet", "send the sheet"), ("The assistant's: draft it", "draft it"),
                             ("Send the sheet; Robin's", "Send the sheet"), ("Robin: send the sheet, Dana's", "Robin: send the sheet"),
                             ("Note: send the sheet", "Note: send the sheet"), ("Q3: review pricing", "Q3: review pricing"),
                             ("Draft: v2 to Tyson", "Draft: v2 to Tyson"), ("Decide: A or B", "Decide: A or B"),
                             ("Next: 12:30 call", "Next: 12:30 call"),
                             ("Send Robin the sheet: it is late", "Send Robin the sheet: it is late"),   # not a name before the colon
                             ("send the sheet: the long one", "send the sheet: the long one"),
                             ("Robin:", "Robin:")):
            self.assertEqual(wanted, status.without_owner(said), said)
        self.assertIsNone(status.without_owner(None))

    def test_a_bare_name_head_goes_only_for_a_known_person_or_party(self):
        owners = status.known_owners({"people": [{"name": "Jo Example"}], "parties": {"acme": {"party": "Acme Corp"}}}, "Dana Lee")
        for said, wanted in (("Jo: send it", "send it"), ("Jo Example: send it", "send it"), ("Acme Corp: reply", "reply"),
                             ("Dana: call", "call"), ("Note: send it", "Note: send it"), ("Sam: send it", "Sam: send it")):
            self.assertEqual(wanted, status.without_owner(said, owners), said)

    def test_the_waiting_badge_keeps_a_bold_pair_whole(self):
        for said, wanted in (("**Theo: Marsh**: volumes", "**Theo: Marsh**"), ("**Theo Marsh**: the volumes", "**Theo Marsh**"),
                             ("Theo: volumes", "Theo"), ("**Theo: Marsh", "Theo"), ("Theo; later", "Theo")):
            self.assertEqual(wanted, status.waiting_badge(said), said)

    def test_a_next_action_that_starts_with_an_owner_shows_without_it(self):
        write(self.work / "Acme Review" / "Threads" / "Pricing" / "Pricing.md",
              thread("Acme Review", "Pricing", next_="Dana's: send the price sheet"))
        card = self.card(self.page())
        self.assertIn("send the price sheet", card)
        self.assertNotIn("Dana&#x27;s:", card)
        self.assertNotIn("Dana's:", card)

    def todo(self, zone, *lines):
        write(self.root / "Zones" / zone / "Todo.md", "# %s: open actions\n\n## Inbox\n\n" % zone
              + "".join("- [ ] %s\n" % l for l in lines) + "\n## Done\n")

    def threads_pop(self, html, pop_id):
        start = html.index('<div class="tpop" id="%s"' % pop_id)
        ends = [html.find(m, start + 1) for m in ('<div class="tpop"', '<div class="thread', '<div class="yrow"', "</details>")]
        return html[start:min(e for e in ends if e > 0)]

    def test_a_row_with_open_actions_has_the_threads_cards_chip_and_list_and_one_without_has_none(self):
        self.todo("Work", "[[Pricing]]: send the floor to Dana", "[[Pricing]]: send the renewal")
        html = self.page()
        card = self.card(html)
        rows = dict(re.findall(r'<div class="yrow" data-w="([^"]*)">(.*?)(?=<div class="yrow"|$)', card, re.S))
        mine = next(v for v in rows.values() if "Acme Review" in v and "yline" in v)
        chip = re.search(r'<button type="button" class="chip tchip todo ok"[^>]*aria-controls="(tp-[0-9a-f]+)"[^>]*>todo 2</button>', mine)
        self.assertTrue(chip, mine)
        pop = self.threads_pop(card, chip.group(1))
        self.assertEqual(2, len(re.findall(r'class="trow[ "]', pop)))
        for line in ("send the floor to Dana", "send the renewal"):
            self.assertIn(line, pop)
        others = [v for v in rows.values() if "Acme Review" not in v]
        self.assertTrue(others)
        for v in others:
            self.assertNotIn("tchip", v)                                # no open lines: no chip
            self.assertNotIn("tpop", v)
        # the Threads card has the same two lines, under the same keys, under an id of its own
        threads = self.card_threads(html)
        theirs = re.search(r'<div class="tpop" id="(tp-[0-9a-f]+)"', threads).group(1)
        self.assertNotEqual(theirs, chip.group(1))
        self.assertEqual(sorted(re.findall(r'data-k="([0-9a-f]{16})"', self.threads_pop(threads, theirs))),
                         sorted(re.findall(r'data-k="([0-9a-f]{16})"', pop)))
        self.assertEqual(2, len(set(re.findall(r'data-k="([0-9a-f]{16})"', pop))))
        ids = re.findall(r'<div class="tpop" id="([^"]+)"', html)
        self.assertEqual(2, len(ids))
        self.assertEqual(len(ids), len(set(ids)))                       # no two lists under one id

    def card_threads(self, html):
        start = html.index('<details class="card" id="threads"')
        return html[start:html.index("</section>", start)]

    def test_a_ticks_scripts_reach_the_list_and_the_chip_on_a_work_row(self):
        html = self.page()
        self.assertIn("document.querySelectorAll('.tview,.yrows').forEach(function(v){v.addEventListener('click'", html)
        self.assertIn("var places=[todo].concat([].slice.call(document.querySelectorAll('.tview,.yrows')));", html)

    def test_a_rows_list_holds_only_its_own_threads_lines_when_two_walled_zones_share_a_thread_name(self):
        """The wall: Personal has a thread called Pricing too. Its lines never reach the Work row's list, and the
        other way round; every line a row lists is one the Threads card lists for the same thread."""
        write(self.root / "Zones" / "Personal" / "House" / "House.md", project_hub("Personal", "House", "", ["Pricing"]))
        write(self.root / "Zones" / "Personal" / "House" / "Threads" / "Pricing" / "Pricing.md",
              thread("House", "Pricing", "", next_="Ring the plumber"))
        self.todo("Work", "[[Pricing]]: work line one for Dana")
        self.todo("Personal", "[[Pricing]]: house line about the boiler", "[[Pricing]]: house line about the roof")
        html = self.page()
        card = self.card(html)
        rows = re.findall(r'<div class="yrow" data-w="[^"]*">.*?(?=<div class="yrow"|$)', card, re.S)
        by = {}
        for r in rows:
            zone = re.search(r'class="yzone">([^<]*)<', r).group(1)
            by.setdefault(zone.split(" / ")[0], []).append(r)
        work = next(r for r in by["Work"] if "Acme Review" in r)
        house = next(r for r in by["Personal"])
        self.assertIn("work line one", work)
        self.assertNotIn("house line", work)
        self.assertIn("todo 1", work)
        self.assertIn("house line about the boiler", house)
        self.assertIn("house line about the roof", house)
        self.assertNotIn("work line", house)
        self.assertIn("todo 2", house)
        threads = self.card_threads(html)
        for line in ("work line one", "house line about the boiler", "house line about the roof"):
            self.assertIn(line, threads)                                # nothing the Threads card does not show

    def test_the_way_to_open_is_the_threads_cards_data_and_a_browser_gets_a_phrase_to_copy(self):
        html = self.page()
        card = self.card(html)
        data = [json.loads(htmllib.unescape(d)) for d in re.findall(r'class="yopen apponly" data-card="([^"]+)"', card)]
        self.assertEqual(3, len(data))
        threads = self.card_threads(html)
        for o in data:
            self.assertEqual("thread", o["kl"])
            self.assertIn(htmllib.escape(json.dumps(o, separators=(",", ":"), ensure_ascii=False), quote=True), threads)   # the same card
        self.assertNotIn("data-act=", card)
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


OPENER = textwrap.dedent("""
    const vm = require("vm");
    const [js, launchers, installed, def, card, host] = JSON.parse(process.argv[1]);
    const store = { "garrick-launchers": JSON.stringify(launchers), "garrick-default": def };
    const ctx = { JSON, String, Object, Array,
      document: { getElementById: () => null, body: { dataset: { launchers: installed.join(","), cli: "1" } }, addEventListener() {} },
      localStorage: { getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = v; } } };
    ctx.window = ctx;
    if (host) ctx.webkit = { messageHandlers: { garrick: { postMessage() {} } } };
    vm.createContext(ctx);
    vm.runInContext(js + "; this.out = Panel.opener(" + JSON.stringify(card) + ");", ctx);
    process.stdout.write(ctx.out);
""")
CARD = {"n": "Pricing", "kl": "thread", "z": "Work", "p": "Acme Review", "w": "Pricing", "u": "file:///x/Pricing.md",
        "f": "/x/Acme Review/Threads/Pricing", "oc": ["Work", "Acme Review/Threads/Pricing/Pricing.md"], "dk": ["Work", "Acme Review", "Pricing"]}


@unittest.skipUnless(shutil.which("node"), "Node is not installed")
class TestTheWayToOpen(unittest.TestCase):
    """#523: a Your work row opens as the Threads card does: the main button runs Settings' Default, a list offers the
    other ways that are on and installed."""

    def opener(self, default, on, installed=("finder", "cmux", "codex", "claude"), host=True, note=True):
        chosen = {k: True for k in on}
        chosen.update({k: False for k in ("finder", "cmux", "codex", "claude") if k not in on})
        chosen["note"] = note
        done = subprocess.run(["node", "-e", OPENER, json.dumps([status.PANEL_JS, chosen, list(installed), default, CARD, host])],
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(0, done.returncode, done.stderr)
        return done.stdout

    def kinds(self, html):
        return re.findall(r'data-k="([a-z]+)"', html)

    def test_the_main_button_runs_the_default_and_the_list_offers_the_others_that_are_on_and_installed(self):
        for default in ("cmux", "finder", "codex"):
            html = self.opener(default, ("finder", "cmux", "codex", "claude"))
            main, rest = html.split("<details")
            self.assertEqual([default], self.kinds(main), default)
            self.assertIn("data-d", main)
            self.assertEqual({"note", "finder", "cmux", "codex", "claude"} - {default}, set(self.kinds(rest)), default)

    def test_with_codex_turned_off_or_not_installed_the_list_does_not_offer_it(self):
        html = self.opener("cmux", ("finder", "cmux", "claude"))
        self.assertNotIn('data-k="codex"', html)
        html = self.opener("cmux", ("finder", "cmux", "codex", "claude"), installed=("finder", "cmux", "claude"))
        self.assertNotIn('data-k="codex"', html)

    def test_with_the_default_claude_the_request_is_the_continue_hand_off(self):
        html = self.opener("claude", ("finder", "cmux", "claude"))
        main = html.split("<details")[0]
        act = json.loads(htmllib.unescape(re.search(r'data-act="([^"]+)"', main).group(1)))
        self.assertEqual({"verb": "continue", "zone": "Work", "file": "Acme Review/Threads/Pricing/Pricing.md"}, act)
        self.assertIn("Open in Claude", main)

    def test_the_cmux_button_is_the_desks(self):
        main = self.opener("cmux", ("cmux", "claude")).split("<details")[0]
        act = json.loads(htmllib.unescape(re.search(r'data-act="([^"]+)"', main).group(1)))
        self.assertEqual({"verb": "open", "zone": "Work", "project": "Acme Review", "thread": "Pricing"}, act)

    def test_one_way_on_is_one_plain_button(self):
        html = self.opener("claude", ("claude",), note=False)
        self.assertNotIn("<details", html)
        self.assertEqual(["claude"], self.kinds(html))
        html = self.opener("note", (), note=True)
        self.assertNotIn("<details", html)
        self.assertEqual(["note"], self.kinds(html))
        self.assertIn('href="file:///x/Pricing.md"', html)

    def test_a_default_that_is_off_falls_back_to_the_first_way_on(self):
        html = self.opener("codex", ("finder", "claude"))
        self.assertEqual(["note"], self.kinds(html.split("<details")[0]))
        self.assertNotIn('data-k="codex"', html)


if __name__ == "__main__":
    unittest.main()
