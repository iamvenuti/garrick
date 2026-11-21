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
        self.assertIn("margin-left:24px", rule(status.CSS, ".zone .tunit>.thread"))
        self.assertIn("margin-left:46px", rule(status.CSS, ".zone .thread.sub"))     # 24 + 22
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


if __name__ == "__main__":
    unittest.main()
