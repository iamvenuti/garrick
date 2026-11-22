"""The Threads card reads as three levels (#619), and the row card as a menu (#620).

    cd tests && python3 -m unittest test_threads_card

The page is built in a temporary folder and read as text; layout at 1280px and 390px is the page gate's, in a browser.
"""
import datetime as dt
import importlib.util
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import build_workspace  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "extras" / "status"))


def _load():
    spec = importlib.util.spec_from_file_location("garrick_status_threads_card", REPO / "extras" / "status" / "status.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


status = _load()


def rule(css, selector):
    """The declarations of the first rule whose selector is exactly `selector`."""
    m = re.search(r"(?:^|\})\s*" + re.escape(selector) + r"\{([^}]*)\}", css, re.M)
    return m.group(1) if m else None


class Card(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        root = Path(cls._tmp.name).resolve() / "Workspace"
        build_workspace(root)
        jobs = Path(cls._tmp.name) / "jobs"
        jobs.mkdir()
        with mock.patch.object(status, "launch_agents", lambda: Path(cls._tmp.name) / "LA"), \
                mock.patch.dict(os.environ, {"HOME": str(Path(cls._tmp.name) / "home")}):
            cls.page = status.build(root, now=dt.datetime(2026, 11, 10, 10, 0), folder=jobs)
        start = cls.page.index('<div class="zones">')
        cls.zones = cls.page[start:cls.page.index("</div></div>", cls.page.index('class="hint gsum'))]

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_a_zone_header_is_ink_at_weight_600_and_never_uppercase(self):
        h3 = rule(status.CSS, ".zone>summary h3")
        self.assertIn("font-size:var(--fs-body)", h3)
        self.assertIn("font-weight:600", h3)
        self.assertIn("color:var(--ink)", h3)
        self.assertIn("text-transform:none", h3)
        self.assertIn("letter-spacing:0", h3)
        self.assertNotIn("uppercase", h3)
        self.assertNotRegex(self.zones, r'<h3 class="zc')              # the colour is not on the name

    def test_the_zone_colour_is_on_the_icon_alone(self):
        icon = next(iter(status.ZONE_ICONS))
        self.assertTrue(status.zone_label("Work", {"Work": {"color": "Teal", "icon": icon}}).startswith('<span class="zic zc zc-teal"><svg'))
        self.assertEqual("Work", status.zone_label("Work", {"Work": {"color": "Teal"}}))      # no icon: the name alone
        self.assertEqual("Work", status.zone_label("Work", {}))

    def test_the_zone_meta_says_late_in_the_critical_colour(self):
        self.assertIn(".zone>summary .meta .late{color:var(--critical)}", status.CSS)
        self.assertIn("var(--muted)", rule(status.CSS, ".zone>summary .meta") or "")
        self.assertIn('<span class="late">', status.TVIEW_JS + status.CSS + self.page)   # the build and the page's recount write it
        self.assertIn("meta.innerHTML=", self.page)
        self.assertNotRegex(self.page, r"meta\.textContent=l\+' live'")

    def test_a_rule_above_every_zone_but_the_first_and_one_column(self):
        self.assertIn("border-top:1px solid var(--line)", rule(status.CSS, ".zone+.zone>summary"))
        self.assertIn("grid-template-columns:minmax(0,1fr)", rule(status.CSS, ".zones"))

    def test_projects_start_24px_in_and_threads_22px_further(self):
        # the names step in; the chevrons stay in one column, so the project row takes no margin of its own (#619)
        self.assertNotIn("margin-left", rule(status.CSS, ".zone .tunit>.thread") or "")
        self.assertIn("left:24px", status.CSS[status.CSS.index(".zone .tunit>.thread::before"):][:120])        # the project's rule starts 24px in
        self.assertIn("margin-right:30px", rule(status.CSS, ".zone .tunit>.thread.proj .pchev"))             # 16 + 30 = 46: zone name + 24
        self.assertIn("padding-left:46px", rule(status.CSS, ".zone .tunit>.thread:not(.proj)>.t"))
        self.assertIn("margin-left:68px", rule(status.CSS, ".zone .thread.sub"))                             # 46 + 22
        self.assertIn("padding-left:0", rule(status.CSS, ".thread.sub") or status.CSS[status.CSS.index(".thread.sub{padding"):][:80])

    def test_one_chevron_size_for_zone_and_project(self):
        self.assertIn("width:14px;height:14px", rule(status.CSS, ".zone>summary .chev"))
        self.assertIn("width:14px;height:14px", rule(status.CSS, ".pchev .chev"))
        self.assertIn("color:var(--muted)", rule(status.CSS, ".zone>summary .chev"))
        self.assertIn("color:var(--muted)", rule(status.CSS, ".pchev"))

    def test_the_thread_count_is_a_cell_of_its_own_before_the_bar_and_goes_with_it(self):
        head = re.search(r'<div class="thread proj".*?</div><span class="cnt[^"]*">[^<]*</span>(.*?)</div>', self.zones, re.S)
        self.assertTrue(head, self.zones[:400])
        self.assertRegex(self.zones, r'<div class="t"><button type="button" class="pchev"[^>]*>.*?</button><a href="[^"]*">[^<]*</a></div><span class="cnt muted subn mu">\d+ threads?')
        self.assertTrue(head.group(1).lstrip().startswith(('<div class="fresh age mu"', '<span class="mu"')))      # then the bar
        self.assertIn("grid-template-columns:minmax(0,1fr) auto 70px 34px", rule(status.CSS, ".thread.proj"))
        self.assertIn("text-align:right", rule(status.CSS, ".thread .cnt"))
        self.assertIn("font-size:var(--fs-meta)", rule(status.CSS, ".thread .cnt"))
        self.assertIn('.tview:not([data-tm="updated"]) .mu{display:none!important}', status.TVIEW_CSS)     # hidden in Time and Cost, as the bar is

    def test_the_count_wraps_before_the_name_is_clipped_at_390(self):
        self.assertIn("@media (max-width:520px){.thread .cnt{white-space:normal", status.CSS)
        self.assertIn("text-overflow:ellipsis", rule(status.CSS, ".thread .t a") or status.CSS[status.CSS.index(".thread .t a{"):][:140])

    def test_the_live_dot_is_6px_with_no_ring_until_it_works(self):
        idle = rule(status.CSS, ".live")
        self.assertIn("width:6px;height:6px", idle)
        self.assertNotIn("box-shadow", idle)
        self.assertIn("animation:livepulse", rule(status.CSS, ".live.working"))

    def test_the_legend_is_part_of_the_hint_line(self):
        self.assertEqual(1, self.page.count('class="hint gsum mu"'))
        hint = re.search(r'<p class="hint gsum mu">([^<]*)</p>', self.page).group(1)
        self.assertIn("Bar and number: days since the newest thread moved, toward sixty", hint)
        self.assertIn("Dot: a session is open in it", hint)

    def test_no_text_on_the_card_is_uppercase(self):
        card = status.CSS[status.CSS.index(".zones{"):status.CSS.index(".thread{display:grid")]
        self.assertNotIn("uppercase", card)


HARNESS = r"""
const vm = require("vm");
const [panel, manage, card, hosted] = JSON.parse(process.argv[1]);
const added = [];
const ctx = { JSON, String, Array, Date, Math, setTimeout: () => 0, clearTimeout: () => 0,
  localStorage: { getItem: () => null, setItem: () => {} },
  document: { readyState: "complete", getElementById: (id) => id === "manage-data" ? { textContent: '{"zones":{},"acting":true}' } : null,
              addEventListener: () => {}, createElement: () => ({}), body: { dataset: { launchers: "claude,cmux,finder", cli: "1" }, appendChild: () => 0 } } };
ctx.window = hosted ? { webkit: { messageHandlers: { garrick: { postMessage: () => {} } } } } : {};
vm.createContext(ctx);
vm.runInContext(manage, ctx);
ctx.GarrickManage = ctx.window.GarrickManage;
vm.runInContext(panel + ";this.out=[Panel.card(" + JSON.stringify(card) + ",1), Panel.card(" + JSON.stringify(card) + ",0)]", ctx);
process.stdout.write(JSON.stringify(ctx.out));
"""

PROJECT = {"n": "Harbour", "kl": "project", "z": "Work", "p": "", "t": ["acme"], "d": 1, "s": 0, "h": 1, "hp": 0, "tn": 3, "pp": ["Work", "Harbour"],
           "mg": ["Work", "Harbour", "", [], [], ["Quay"], ["split"]], "dk": ["Work", "Harbour", ""], "live": "idle", "f": "/w/Harbour",
           "u": "file:///w/Harbour/Harbour.md", "w": "Harbour"}
THREAD = {"n": "Quay", "kl": "thread", "z": "Work", "p": "Harbour", "t": ["acme"], "d": 3, "s": 0, "r": 1, "rd": 3, "pa": ["Work", "Harbour/Threads/Quay/Quay.md"],
          "mg": ["Work", "Harbour", "Quay", [], [], [], []], "u": "file:///w/Quay.md", "w": "Quay"}


class RowCard(unittest.TestCase):
    """#620: header, Open in, a plain menu, Delete last."""

    def run_card(self, card, hosted=True):
        import json, shutil, subprocess
        if not shutil.which("node"):
            self.skipTest("Node is not installed")
        done = subprocess.run(["node", "-e", HARNESS, json.dumps([status.PANEL_JS, status.MANAGE_JS, card, hosted])],
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(0, done.returncode, done.stderr)
        import html
        return [html.unescape(x) for x in json.loads(done.stdout)]

    def order(self, html, *needles):
        at = [html.index(n) for n in needles]
        self.assertEqual(sorted(at), at, needles)

    def test_a_project_reads_header_open_in_actions_then_delete(self):
        row, graph = self.run_card(PROJECT)
        self.order(row, 'class="phead"', 'class="pl pl1"', 'class="pl pl2"', 'class="gacts popen"', 'class="pmenu"', 'class="psep"', "Delete…")
        self.assertEqual(0, row[row.index('class="pmenu"'):].count('"verb":"park"'))               # no Park row in the menu (#633)
        self.order(row, "Open in", 'data-manage="new-thread"', 'data-manage="rename"', 'data-manage="layout-split"', "Close session", 'class="psep"', 'data-manage="delete"')
        self.assertTrue(row.rstrip().endswith("Delete…</button></div>"))                      # Delete is the last row
        self.assertEqual(1, row.count('data-manage="delete"'))
        self.assertIn("project · Work", graph)                                               # the graph's panel keeps kind, zone and project
        self.assertNotIn("project · Work", row)

    def test_line_one_is_the_party_and_the_state_and_line_two_when_it_was_touched(self):
        row, _ = self.run_card(PROJECT)
        self.assertIn('<div class="pl pl1"><span class="chip">acme</span><button class="ctl pflip" type="button" data-act=', row)
        self.assertIn('>Active</button></div>', row)
        self.assertNotIn("3 threads", row)                                                    # the row has the count (#633)
        self.assertIn('<div class="pl pl2">Touched yesterday</div>', row)
        self.assertIn('<span class="live idle"></span>Session open in cmux, idle', row)
        thread, _ = self.run_card(THREAD)
        self.assertIn('<div class="pl pl2">Touched 3 days ago · Resume point dated 3 days ago</div>', thread)
        self.assertNotIn("threads", thread.split('class="gacts')[0].split('pl1')[1])         # a thread has no count
        parked, _ = self.run_card(dict(THREAD, s=1))
        self.assertIn('class="ctl parked pflip"', parked)
        self.assertIn('>Parked</button>', parked)

    def test_no_action_has_a_border_and_the_chip_is_the_only_bordered_element(self):
        row, _ = self.run_card(PROJECT)
        menu = row[row.index('class="pmenu"'):]
        self.assertNotIn('class="act', menu)                                                 # plain rows
        self.assertEqual(menu.count("<button"), menu.count('class="pmi'))
        css = status.CSS
        self.assertIn("border:0", css[css.index(".pmi{"):][:200])
        self.assertEqual(1, row.count("chip"))
        self.assertIn("border-color:transparent", css[css.index(".popen .act{"):][:80])

    def test_delete_is_critical_icon_included_and_set_apart(self):
        row, _ = self.run_card(PROJECT)
        self.assertIn('<button class="pmi del" type="button" data-manage="delete"', row)
        self.assertIn(".pmi.del,.pmi.del svg{color:var(--critical)}", status.CSS)
        self.assertIn('<div class="psep" role="separator"></div><button class="pmi del"', row)

    def test_every_verb_and_handler_is_kept(self):
        row, _ = self.run_card(PROJECT)
        for need in ('data-manage="new-thread"', 'data-manage="rename"', 'data-manage="layout-split"', 'data-manage="delete"', 'data-mg="',
                     '"verb":"close"' if False else 'data-act=', 'data-expect="none:/w/Harbour"', 'data-expect="parked:Work/Harbour/Harbour.md"'):
            self.assertIn(need, row)
        thread, _ = self.run_card(THREAD)
        self.assertIn('data-manage="move"', thread)
        self.assertNotIn('data-manage="layout', thread)               # a thread has no layout of its own (#632)
        self.assertNotIn('data-manage="new-thread"', thread)
        self.assertNotIn("Close session", self.run_card(dict(PROJECT, live=None, dk=None))[0])      # only with a session open

    def test_a_parked_with_its_project_thread_has_no_menu_of_its_own(self):
        row, _ = self.run_card(dict(THREAD, held=1, s=1, pa=None))
        self.assertNotIn("pmenu", row)

    def test_open_in_comes_first_and_the_default_is_a_dot_not_a_tint(self):
        row, _ = self.run_card(PROJECT)
        self.assertIn('<span class="plbl">Open in</span>', row)
        self.assertLess(row.index("Open in"), row.index('class="pmenu"'))
        css = status.CSS
        self.assertIn('.appicons .act[data-k][data-d]::after{content:"";position:absolute;left:50%;bottom:-3px;width:4px;height:4px', css)
        self.assertIn("background:var(--accent)", css[css.index("[data-d]::after"):][:200])
        self.assertNotIn("22%,transparent)}\n.appicons .act[data-k]:hover", css)
        self.assertIn("center/22px no-repeat", css[css.index(".appicons .act[data-k]{"):][:220])

    def test_the_card_is_264_wide_and_the_rows_have_a_hover_and_a_focus_ring(self):
        css = status.CSS
        self.assertIn("width:264px", css[css.index(".gpop{position:absolute"):][:90])
        self.assertIn("width:264px", css[css.index(".tcard{position:fixed"):][:90])
        self.assertIn(".pmi:hover{background:var(--wash)}", css)
        self.assertIn(":focus-visible{outline:2px solid var(--accent);outline-offset:2px}", status.LOOK_CSS)

    def test_a_browser_keeps_the_words(self):
        row, _ = self.run_card(THREAD, hosted=False)
        self.assertIn("Open</a>", row)
        self.assertIn('data-copy="park Quay"', row)

    def test_one_component_for_row_search_result_and_graph_panel(self):
        self.assertIn("tc.innerHTML=Panel.card(o,1);", status.JS)             # a project row, a thread row and a search result
        self.assertIn("Panel.card(o,0,window.GarrickNote", status.GRAPH_JS)    # the graph panel
        self.assertNotIn("Panel.head(o,1)+", status.JS)


if __name__ == "__main__":
    unittest.main()
