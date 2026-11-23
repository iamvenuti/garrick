"""The status page's look (#551): readable text, status in words, a font that is embedded.

    python3 -m unittest discover -s tests -p test_status_look.py

Colours are computed from the page's own tokens, so a change to a token that
fails the 4.5:1 text contrast fails here, in both themes and for every zone
colour. The built page is read as text: nothing here asks the network or a
browser.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import html as htmllib
import json
import os
import shutil
import subprocess
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import build_workspace  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
HERE = REPO / "extras" / "status"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


status = _load("garrick_status_look", HERE / "status.py")


def rgba(value):
    """(r, g, b, a) from #rgb, #rrggbb or rgba(r,g,b,a)."""
    value = value.strip()
    if value.startswith("#"):
        h = value[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) + (1.0,)
    m = re.match(r"rgba?\(([^)]*)\)", value)
    parts = [p.strip() for p in m.group(1).split(",")]
    return (int(parts[0]), int(parts[1]), int(parts[2]), float(parts[3]) if len(parts) > 3 else 1.0)


def over(top, under):
    """`top` laid over the opaque colour `under`."""
    a = top[3]
    return tuple(round(top[i] * a + under[i] * (1 - a)) for i in range(3)) + (1.0,)


def luminance(c):
    def lin(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(c[0]) + 0.7152 * lin(c[1]) + 0.0722 * lin(c[2])


def contrast(a, b):
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def tokens(css, theme):
    """The custom properties the page sets for a theme: the root block, or the one a dark switch sets."""
    head = ':root{color-scheme:light;' if theme == "light" else ':root[data-theme="dark"]{'
    start = css.index(head) + len(head)
    block = css[start:css.index("}", start)]
    return dict(re.findall(r"(--[a-z0-9-]+):([^;]+)", block))


# Every text colour against every ground it is drawn on.
TEXT = ("--ink", "--ink2", "--muted", "--accent", "--good", "--warning", "--critical")
GROUNDS = ("--page", "--surface", "--raise")


class Contrast(unittest.TestCase):
    def test_text_tokens_pass_in_both_themes(self):
        for theme in ("light", "dark"):
            t = tokens(status.CSS, theme)
            for name in TEXT:
                for ground in GROUNDS:
                    ratio = contrast(rgba(t[name]), rgba(t[ground]))
                    self.assertGreaterEqual(ratio, 4.5, "%s %s on %s: %.2f" % (theme, name, ground, ratio))

    def test_status_text_passes_on_its_own_wash(self):
        for theme in ("light", "dark"):
            t = tokens(status.CSS, theme)
            surface = rgba(t["--surface"])
            for name in ("good", "warning", "critical"):
                wash = over(rgba(t["--%s-wash" % name]), surface)
                ratio = contrast(rgba(t["--" + name]), wash)
                self.assertGreaterEqual(ratio, 4.5, "%s %s on its wash: %.2f" % (theme, name, ratio))

    def test_ink_on_accent_button(self):
        for theme in ("light", "dark"):
            t = tokens(status.CSS, theme)
            ratio = contrast(rgba(t["--accent-ink"]), rgba(t["--accent"]))
            self.assertGreaterEqual(ratio, 4.5, "%s: %.2f" % (theme, ratio))

    def test_zone_colours_pass_on_the_card(self):
        light, dark = tokens(status.CSS, "light"), tokens(status.CSS, "dark")
        for name, (on_light, on_dark) in status.ZONE_COLOURS.items():
            for theme, colour, ground in (("light", on_light, light), ("dark", on_dark, dark)):
                ratio = contrast(rgba(colour), rgba(ground["--surface"]))
                self.assertGreaterEqual(ratio, 4.5, "%s in %s: %.2f" % (name, theme, ratio))

    def test_the_tokens_are_the_issue_s(self):
        light, dark = tokens(status.CSS, "light"), tokens(status.CSS, "dark")
        for k, v in {"--page": "#f4f2ed", "--surface": "#fbfaf7", "--raise": "#fff", "--sunk": "#efede7", "--ink": "#16150f",
                     "--ink2": "#45443f", "--muted": "#6b6963", "--accent": "#2f5fc4", "--good": "#1d7a3a",
                     "--warning": "#9a5b00", "--critical": "#b42f2f"}.items():
            self.assertEqual(v, light[k], k)
        for k, v in {"--page": "#0f0f0e", "--surface": "#1a1a19", "--raise": "#222120", "--ink": "#f3f1ec", "--ink2": "#cfccc4",
                     "--muted": "#a29f97", "--accent": "#7ea3ee", "--good": "#6fcf8a", "--warning": "#e8a93a",
                     "--critical": "#f08a8a"}.items():
            self.assertEqual(v, dark[k], k)
        auto = status.CSS[status.CSS.index("@media (prefers-color-scheme:dark)"):]
        self.assertIn("--accent:#7ea3ee", auto)        # the system's dark follows the same tokens as the switch's


_BUILT = []


def page_html():
    """The page built once for the module, from a clean workspace; nothing of this Mac is read."""
    if not _BUILT:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            root = base / "Workspace"
            build_workspace(root)
            (base / "jobs").mkdir()
            (base / "home").mkdir()
            with mock.patch.object(status, "launch_agents", lambda: base / "LaunchAgents"), \
                    mock.patch.dict(status.os.environ, {"HOME": str(base / "home")}):
                _BUILT.append(status.build(root, now=dt.datetime(2026, 11, 9, 9, 0), folder=base / "jobs"))
    return _BUILT[0]


class Page(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = page_html()

    def css(self):
        return "\n".join(re.findall(r"<style>(.*?)</style>", self.html, re.S))

    def test_form_controls_take_the_pages_font_family(self):
        self.assertIn("button,input,select,textarea{font-family:inherit}", self.css())

    SCALE = {"meta": 13, "sub": 14, "body": 15, "h3": 17, "h2": 20, "h1": 38}

    def sizes(self, css):
        """Every size the CSS sets, as written: in `font-size:` and in the `font:` shorthand."""
        out = re.findall(r"font-size:\s*([^;}\"']+)", css)
        out += re.findall(r"(?<![-\w])font:\s*(?:(?:italic|bold|normal|\d{3})\s+)*([^\s/;}\"']+)", css)
        return [x.strip() for x in out if x.strip() not in ("inherit", "0")]

    def test_the_scale_is_on_root_and_nothing_is_under_13px(self):
        css = self.css()
        root = css[css.index(":root{color-scheme:light;"):]
        root = root[:root.index("}")]
        got = dict(re.findall(r"--fs-([a-z0-9]+):(\d+)px", root))
        self.assertEqual({k: str(v) for k, v in self.SCALE.items()}, got)
        self.assertGreaterEqual(min(int(v) for v in got.values()), 13)

    def test_no_font_size_under_13px(self):
        css = self.css()
        literal = [float(n) for n in re.findall(r"font-size:\s*([0-9.]+)px", css) + re.findall(r"(?<![-\w])font:[^;}]*?\b([0-9.]+)px", css)]
        self.assertEqual([], [n for n in literal if n < 13], "a font size under 13px")
        used = {m for m in re.findall(r"var\(--fs-([a-z0-9]+)\)", css)}
        self.assertTrue(used <= set(self.SCALE), used)

    def test_every_font_size_is_a_scale_token_outside_the_token_block(self):
        css = self.css()
        css = css.replace(css[css.index(":root{color-scheme:light;"):css.index("}", css.index(":root{color-scheme:light;"))], "")
        sizes = self.sizes(css)
        self.assertTrue(sizes)
        self.assertEqual([], [x for x in sizes if not re.fullmatch(r"var\(--fs-(meta|sub|body|h3|h2|h1)\)", x)])

    def test_the_module_css_strings_hold_no_px_size_either(self):
        for name in ("finding_queue.py", "guide.py", "status.py"):
            text = (HERE / name).read_text(encoding="utf-8")
            left = [m for m in re.findall(r"font-size:\s*([0-9.]+px)", text)]
            left += re.findall(r"(?<![-\w])font:\s*(?:(?:italic|bold|normal|\d{3})\s+)*([0-9.]+px)", text)
            left = [x for x in left if x not in ("13px", "14px", "15px", "17px", "20px", "38px") or name != "status.py"]
            self.assertEqual([], left, name)
        # the one block this file does not own is mapped when the page is built
        self.assertEqual("font-size:var(--fs-meta)", status.fs_scale("font-size:12.5px"))
        self.assertEqual("font:600 var(--fs-body)/1.2 x", status.fs_scale("font:600 14.5px/1.2 x"))
        self.assertEqual("font-size:var(--fs-h3)", status.fs_scale("font-size:16px"))        # a tie goes to the larger
        self.assertNotIn("px", status.fs_scale(status.questions_mod().CX_CSS).split("font-size:")[1].split(";")[0])

    def test_other_modules_css_has_none_under_13_either(self):
        for name in ("finding_queue.py", "guide.py", "questions_panel.py", "your_work.py"):
            text = (HERE / name).read_text(encoding="utf-8")
            small = [n for n in re.findall(r"font-size:\s*([0-9.]+)px", text) if float(n) < 13]
            self.assertEqual([], small, name)

    def test_body_text_is_the_body_token_on_1_55(self):
        self.assertIn("font:var(--fs-body)/1.55 var(--sans)", status.CSS)

    def test_threads_names_are_body_sub_threads_sub_and_the_rest_meta(self):
        css = status.CSS
        self.assertRegex(css, r"\.thread\{display:grid;grid-template-columns:minmax\(0,1fr\) 70px 34px;[^}]*font-size:var\(--fs-body\)\}")
        self.assertIn(".thread.sub{padding-left:0;border-top:1px dashed var(--grid);font-size:var(--fs-sub)}", css)
        self.assertIn(".thread .num,.thread .chip,.thread .tchips,.thread .thr{font-size:var(--fs-meta)}", css)
        self.assertIn(".thread .t small{display:block;color:var(--muted);font-size:var(--fs-meta)", css)

    def test_the_todo_tab_reads_at_body_with_meta_around_it(self):
        css = status.TODO_CSS
        self.assertIn(".ttext{font-size:var(--fs-body);", css)
        for rule in (".tsum{display:flex;flex-wrap:wrap;align-items:center;gap:6px;color:var(--ink2);font-size:var(--fs-meta)",
                     ".thr{display:inline-block;font-size:var(--fs-meta)", ".tdate{", ".todotab .tbar .seg button{flex:none;padding:5px 12px;font-size:var(--fs-meta)"):
            self.assertIn(rule, css)
        self.assertIn("font-weight:640;font-size:var(--fs-h3)", css)               # the group headings

    def test_the_todo_tab_has_no_open_todo_md_and_add_stays_alone(self):
        html = status.todo_list_card([{"zone": "Work", "file": Path("/x/Work/Todo.md"), "groups": [("Inbox", [])], "done": [], "open": 0,
                                       "late": 0, "undated": 0}], TODAY, True, {}, lambda f: "file:///x/Work/Todo.md", {})
        self.assertNotIn("Open Todo.md", html)
        self.assertRegex(html, r'<span class="tsum-acts"><button type="button" class="act primary tadd-open"[^>]*>＋ Add</button></span>')
        self.assertNotIn("Open Todo.md", page_html())

    def test_no_font_travels_with_the_page_and_nothing_is_fetched(self):
        css = self.css()
        self.assertNotIn("@font-face", css)
        self.assertNotIn("data:font", self.html)
        self.assertNotIn("woff", self.html)
        self.assertIn("system-ui", css)
        # no stylesheet, font, script or image is asked of the network: every http(s) address is a link the reader follows
        self.assertNotRegex(self.html, r"<link[^>]+(?:href|src)=[\"']https?:")
        self.assertNotRegex(self.html, r"<script[^>]+src=")
        self.assertNotRegex(css, r"url\(\s*[\"']?https?:")
        self.assertNotRegex(css, r"@import")
        self.assertNotIn("fonts.googleapis", self.html)

    def test_the_font_files_and_their_builder_are_gone(self):
        self.assertFalse((HERE / "fonts").exists())
        self.assertFalse(hasattr(status, "font_css"))
        self.assertFalse(hasattr(status, "FONT_FILES"))
        self.assertNotIn("Jakarta", self.html)

    def test_one_family_in_the_built_page_besides_the_guides_code(self):
        css = self.css()
        self.assertEqual('system-ui,-apple-system,"Segoe UI",Roboto,sans-serif', tokens(css, "light")["--sans"])
        families = re.findall(r"(?<![-\w])font-family:\s*([^;}\"']+)", css)
        families += re.findall(r"(?<![-\w])font:[^;}\"']*?var\(--fs-[a-z0-9]+\)(?:/[0-9.]+)?\s+([^;}\"']+)", css)
        self.assertTrue(families)
        for family in families:
            if "monospace" in family:
                continue                                                                        # the Guide's code, checked below
            self.assertIn(family.strip(), ("var(--sans)", "inherit"))                   # inherit: the base rule for form controls
        guide = status.guide_mod().GUIDE_CSS
        self.assertEqual(1, guide.count("ui-monospace"))
        self.assertEqual(1, css.count("ui-monospace"))                                          # and nowhere else on the page
        self.assertEqual(1, len(re.findall(r"\.gd-page code\{[^}]*monospace", css)))
        self.assertNotRegex(re.sub(r"sans-serif", "", css), r"(?i)\bserif\b|Georgia|Baskerville")   # no serif

    def test_the_figures_row_has_left_no_css_behind(self):
        css = self.css()
        self.assertNotIn("--display", css)
        for gone in (".hero", ".tile .val", ".top{", ".lead{", ".lead h2"):
            self.assertNotIn(gone, css, gone)                                  # #595

    def test_every_control_has_a_visible_focus_ring_and_a_40px_target(self):
        look = status.LOOK_CSS
        self.assertIn(":focus-visible{outline:2px solid var(--accent)", look)
        self.assertRegex(look, r"button\.act,a\.act[^{]*\{min-height:40px\}")

    def test_motion_stops_under_reduced_motion(self):
        look = status.LOOK_CSS
        self.assertRegex(look, r"@media \(prefers-reduced-motion:reduce\)\{\*[^}]*transition:none!important")
        for m in re.findall(r"transition:[^;}]*?([0-9.]+)s", look):
            self.assertTrue(.15 <= float(m) <= .2, m)


class Words(unittest.TestCase):
    """Status in words (#551): every health state is a pill with an icon and a word, so colour never carries it alone."""

    def test_each_state_renders_a_word_and_an_icon(self):
        said = {"good": "Fine", "warning": "Look soon", "critical": "Act now", "none": "Waiting", "late": "Late",
                "look": "Look soon", "act": "Act now", "wait": "Waiting"}
        for state, word in said.items():
            html = status.pill(state)
            self.assertRegex(html, r">%s</span>$" % word, state)
            self.assertIn("<svg", html, state)
            self.assertIn('aria-hidden="true"', html, state)
        self.assertEqual({"Fine", "Look soon", "Late", "Act now", "Waiting"}, {w for _, w, _ in status.PILLS.values()})

    def test_no_emoji_in_the_icons(self):
        for body in status._PILL_PATHS.values():
            self.assertTrue(body.isascii())

    def test_a_row_with_a_state_has_its_word_beside_it(self):
        html = page_html()
        pills = re.findall(r'<span class="st [a-z]+">.*?</span>', html, re.S)
        self.assertTrue(pills)
        for pill in pills:
            self.assertRegex(pill, r'class="st [a-z]+"><svg[^>]*>.*?</svg>(Fine|Look soon|Late|Act now|Waiting)</span>')

    def test_a_dot_is_never_the_only_sign_of_a_state_in_the_built_markup(self):
        # what the script draws later has its own title; every dot the build writes has words beside it or is a pill
        self.assertNotRegex(page_html(), r'<span class="dot (?:good|warning|critical)"')


TODAY = dt.date(2026, 11, 9)


def todo_row(text, when=None, late=False):
    return {"text": text, "when": when, "late": late, "waiting": False}


def zone(name, rows):
    return {"zone": name, "groups": [("Inbox", rows)], "late": sum(1 for r in rows if r["late"]), "open": len(rows),
            "undated": sum(1 for r in rows if r["when"] is None)}


class Lead(unittest.TestCase):
    """The sentence that says how many things wait is the heading of Waiting on you now, and it agrees with the card (#551, #595)."""

    def test_the_sentence_in_three_cases(self):
        self.assertEqual("Three things need you.", status.lead_said(3))      # several waiting
        self.assertEqual("One thing needs you.", status.lead_said(1))        # one
        self.assertEqual("Nothing needs you right now.", status.lead_said(0))  # none
        self.assertEqual("Twelve things need you.".replace("Twelve", "12"), status.lead_said(12))

    def test_there_is_no_lead_block_and_no_line_of_counts(self):
        for gone in ("lead_block", "lead_counts", "LEAD_KINDS"):
            self.assertFalse(hasattr(status, gone), gone)
        html = page_html()
        for gone in ('id="lead"', 'id="lead-h"', 'id="lead-why"', 'id="lead-go"', 'class="lead"'):
            self.assertNotIn(gone, html, gone)

    def test_the_card_lists_what_waits_and_is_one_line_when_nothing_does(self):
        needs = [status.attn_need("critical", "A job failed", "#jobs"),
                 status.late_need(zone("Work", [todo_row("a", dt.date(2026, 11, 2), True)]), TODAY)]
        now = dt.datetime(2026, 11, 9, 9, 0, tzinfo=dt.timezone.utc)
        html = status.waiting_card([], now, needs)
        self.assertNotIn("nowait", html)
        self.assertNotIn(" calm", html)
        self.assertIn("<h2>Two things need you.</h2>", html)                 # the sentence is the heading (#595)
        self.assertIn('id="waiting-now" data-n="2"', html)
        self.assertEqual(2, html.count('class="wrow wneed"'))
        self.assertIn('<a class="act" href="#jobs">See the details</a>', html)
        self.assertIn('data-tz-go="Work">Open the list</a>', html)
        self.assertIn("oldest was due Mon 2 Nov", html)
        for empty in (status.waiting_card([], now, []), status.waiting_card([], now)):
            self.assertIn("<h2>Nothing needs you right now.</h2>", empty)
            self.assertIn('class="card calm" id="waiting-now"', empty)      # one line: its body is not shown
            self.assertNotIn('class="wrow wneed"', empty)
        self.assertIn("#waiting-now.calm>.body{display:none}", status.WAITING_CSS)

    def test_the_script_says_the_sentence_again_for_the_sessions_now(self):
        js = status.WAITING_JS
        for needle in ("function lead(sess)", "Nothing needs you right now.", "One thing needs you.", "explore-go",
                       "document.getElementById('waiting-now')", "c.classList.toggle('calm',t<1)"):
            self.assertIn(needle, js)
        for gone in ("lead-go", "lead-why", "nowait"):
            self.assertNotIn(gone, js)
        self.assertNotIn("tabn-overview", js)                                # the Overview tab carries no badge (#560)

    def test_each_zones_late_actions_stay_that_zones_own(self):
        lists = [zone("Work", [todo_row("a", dt.date(2026, 11, 2), True)]), zone("Home", [todo_row("b", dt.date(2026, 11, 3), True),
                                                                                       todo_row("c", dt.date(2026, 11, 4), True)])]
        items = status.needs_you([], lists, TODAY)
        self.assertEqual([("Work", "1 late action"), ("Home", "2 late actions")], [(i["zone"], i["text"]) for i in items])
        self.assertEqual(["Work", "Home"], [i["tz"] for i in items])

    def test_what_failed_comes_before_late_actions_and_warnings_after(self):
        attn = [("warning", "w", "#jobs"), ("critical", "c", "#checks")]
        items = status.needs_you(attn, [zone("Work", [todo_row("a", dt.date(2026, 11, 2), True)])], TODAY)
        self.assertEqual(["c", "1 late action", "w"], [i["text"] for i in items])

    def test_the_check_s_warnings_are_no_row_and_its_error_stays_under_broken(self):
        attn = [("critical", "The check found 2 errors", "#checks"), ("warning", "The check found 27 warnings", "#checks")]
        detail = {"The check found 2 errors": {"kind": "errors", "count": 2, "label": "See the errors"},
                  "The check found 27 warnings": {"kind": "warnings", "count": 27, "label": "See the warnings"}}
        items = status.needs_you(attn, [], TODAY, detail)
        self.assertEqual(["The check found 2 errors"], [i["text"] for i in items])
        self.assertEqual(["broken"], [i["group"] for i in items])
        self.assertIn("<h2>One thing needs you.</h2>", status.waiting_card([], dt.datetime(2026, 11, 9, 9, 0), items))

    def test_the_page_heading_and_the_card_count_the_same_things(self):
        sessions = [{"id": "s%d" % i, "agent": "claude", "folder": "/x/Pricing", "thread": "Pricing", "state": "waiting",
                     "waiting_for": "an answer", "since": "2026-11-09T08:00:00Z", "where": "cmux"} for i in range(2)]
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            root = base / "Workspace"
            build_workspace(root)
            (base / "jobs").mkdir()
            (base / "home").mkdir()
            with mock.patch.object(status, "launch_agents", lambda: base / "LaunchAgents"), \
                    mock.patch.dict(status.os.environ, {"HOME": str(base / "home")}):
                none = status.build(root, now=dt.datetime(2026, 11, 9, 9, 0), folder=base / "jobs")
                two = status.build(root, now=dt.datetime(2026, 11, 9, 9, 0), folder=base / "jobs", waiting_now=sessions)
        for html, n_sessions in ((none, 0), (two, 2)):
            fixed = len(re.findall(r'<div class="wrow wneed"[^>]*>', html))
            said = re.search(r'id="waiting-now"[^>]*><summary class="head">.*?<h2>([^<]*)</h2>', html, re.S).group(1)
            self.assertEqual(status.lead_said(fixed + n_sessions), said)
            self.assertEqual(n_sessions, len(re.findall(r'<div class="wrow" data-id=', html)))
            self.assertIn('data-n="%d"' % fixed, html)
            self.assertNotIn("tabn-overview", html)
        self.assertIn('class="card calm" id="waiting-now"', none)
        self.assertNotIn(" calm", two[two.index('id="waiting-now"') - 30:two.index('id="waiting-now"')])


class Overview(unittest.TestCase):
    """The Overview is the lead line and Waiting on you now (#559): no At a glance card, and Explore the graph in the header."""

    def test_the_overview_holds_no_at_a_glance_card(self):
        html = page_html()
        self.assertNotIn("At a glance", html)
        self.assertNotIn('id="summary-col"', html)
        self.assertFalse(hasattr(status, "summary_card"))

    def test_the_header_has_the_graph_button_when_the_graph_is_built(self):
        html = page_html()
        self.assertRegex(html, r'<button class="cog" type="button" id="explore-go" aria-label="Explore the graph" title="Explore the graph">')
        head = html[html.index('<div class="bacts">'):html.index('id="open-settings"')]
        self.assertIn('id="explore-go"', head)                            # beside Settings
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            build_workspace(base / "ws")
            (base / "jobs").mkdir()
            with mock.patch.object(status, "launch_agents", lambda: base / "LaunchAgents"):
                plain = status.build(base / "ws", now=dt.datetime(2026, 11, 9, 9, 0), folder=base / "jobs", show_graph=False)
        self.assertNotIn('id="explore-go"', plain)


def build_with_beats(beats, extra=None):
    """The page built over a jobs folder holding these heartbeats (name -> fields)."""
    import json as _json
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp).resolve()
        root = base / "Workspace"
        build_workspace(root)
        (base / "jobs").mkdir()
        (base / "home").mkdir()
        for name, hb in beats.items():
            body = {"job": name, "started": "2026-11-13 02:00:00", "finished": "2026-11-13 02:20:00", "finished_ts": 1, "exit": 1,
                    "seconds": 1151, "ok": False, "quiet": False}
            body.update(hb)
            (base / "jobs" / ("%s.heartbeat.json" % name)).write_text(_json.dumps(body), encoding="utf-8")
        if extra:
            extra(root)
        with mock.patch.object(status, "launch_agents", lambda: base / "LaunchAgents"), \
                mock.patch.dict(status.os.environ, {"HOME": str(base / "home")}):
            return status.build(root, now=dt.datetime(2026, 11, 14, 9, 0), folder=base / "jobs")


class PlainRows(unittest.TestCase):
    """The Overview says what failed in plain words (#559)."""

    def rows(self, html):
        start = html.index('id="wneeds"')
        block = html[start:html.index('id="wrows"', start)]
        return [(re.sub(r"<[^>]+>", "|", m).replace("||", "|").strip("|")) for m in re.findall(r'<div class="wrow wneed"[^>]*>(.*?)</div>', block, re.S)]

    def test_a_failed_job_reads_title_failed_reason_with_the_day_and_see_the_log(self):
        html = build_with_beats({"gr-nightly": {"title": "Nightly check", "reason": "Recall timed out", "failing_since": "2026-11-13 02:20:00"}})
        row = next(r for r in self.rows(html) if "Nightly check" in r)
        self.assertIn("Nightly check failed: Recall timed out", row)
        self.assertIn("since Fri 13 Nov", row)
        self.assertTrue(row.endswith("See the log"), row)
        self.assertNotRegex(html, r"exit \d+: exited \d+")
        self.assertNotIn("exited 1 after", html.split('id="wneeds"')[1].split('id="wrows"')[0])

    def test_a_heartbeat_with_no_title_uses_the_name_and_no_reason_says_the_code(self):
        html = build_with_beats({"app-update": {"exit": 1}})
        row = next(r for r in self.rows(html) if "App update" in r)
        self.assertIn("App update failed: it exited with code 1", row)

    def test_no_row_has_a_button_that_says_open_it(self):
        html = build_with_beats({"gr-nightly": {"title": "Nightly check", "reason": "Recall timed out"}})
        self.assertNotIn(">Open it<", html.split('id="wneeds"')[1].split('id="wrows"')[0])
        self.assertNotIn('"label": "Open it"', html)

    def test_broken_is_listed_before_to_do_and_to_do_starts_folded_with_its_count(self):
        def todo(root):
            (root / "Zones" / "Work" / "Todo.md").write_text("# Work: open actions\n\n## Inbox\n\n- [ ] Send it 📅 2026-11-02\n\n## Done\n", encoding="utf-8")
        html = build_with_beats({"gr-nightly": {"title": "Nightly check", "reason": "Recall timed out"}}, todo)
        block = html.split('id="wneeds"')[1].split('id="wrows"')[0]
        self.assertLess(block.index('data-g="broken"'), block.index('data-g="todo"'))
        self.assertRegex(block, r'<details class="wgroup" data-g="todo"><summary class="wgh">To do <span class="wgn">\d+</span></summary>')
        self.assertNotIn("<details class=\"wgroup\" data-g=\"todo\" open", block)

    def test_with_nothing_broken_to_do_is_open(self):
        html = build_with_beats({})
        block = html.split('id="wneeds"')[1].split('id="wrows"')[0]
        self.assertNotIn('data-g="broken"', block)

    def test_the_zone_is_in_its_column_never_in_the_sentence(self):
        def todo(root):
            (root / "Zones" / "Work" / "Todo.md").write_text("# Work: open actions\n\n## Inbox\n\n- [ ] Send it 📅 2026-11-02\n\n## Done\n", encoding="utf-8")
        html = build_with_beats({}, todo)
        block = html.split('id="wneeds"')[1].split('id="wrows"')[0]
        for row in re.findall(r'<div class="wrow wneed"[^>]*>(.*?)</div>', block, re.S):
            name = re.search(r'<span class="wname">([^<]*)</span>', row).group(1)
            self.assertNotRegex(name, r"^(Work|Personal|Home):|\bin Work\b", name)

    def test_a_job_title_is_the_name_without_gr_and_hyphens(self):
        self.assertEqual("Nightly", status.job_title("gr-nightly", {}))
        self.assertEqual("App update", status.job_title("app-update", {}))
        self.assertEqual("Updates", status.job_title("app-update", {}, {"GARRICK_JOB_TITLE": "Updates"}))

    def test_a_failed_step_of_a_run_under_way_is_named(self):
        self.assertEqual("Recall timed out", status.step_reason([{"step": "recall", "exit": 124}]))
        self.assertEqual("Effort failed", status.step_reason([{"step": "effort", "exit": 1}, {"step": "recall", "exit": 124}]))
        self.assertEqual("", status.step_reason([{"step": "effort", "exit": 0}]))


def dirty_zone(root, days_old, files=("Notes.md",)):
    """Work as a repository with uncommitted files, each last changed `days_old` days before the page's clock (2026-11-14)."""
    zone_dir = root / "Zones" / "Work"
    subprocess.run(["git", "init", "-q", str(zone_dir)], check=True)
    when = dt.datetime(2026, 11, 14, 9, 0) - dt.timedelta(days=days_old)
    for name in files:
        (zone_dir / name).parent.mkdir(parents=True, exist_ok=True)
        (zone_dir / name).write_text("# note\n", encoding="utf-8")
        os.utime(zone_dir / name, (when.timestamp(), when.timestamp()))


class WaitingActs(unittest.TestCase):
    """Waiting on you now is the one place for what needs you, and a row acts where it is (#595)."""

    NOW = dt.datetime(2026, 11, 14, 9, 0)

    def card(self, html):
        start = html.index('id="waiting-now"')
        return html[start:html.index("</details>", start)]

    def need_rows(self, html):
        return re.findall(r'<div class="wrow wneed"[^>]*>.*?(?=<div class="wrow wneed"[^>]*>|</div></section>|</details>)', self.card(html), re.S)

    def test_the_status_tab_has_no_hero_and_no_tiles_and_keeps_its_badge(self):
        html = build_with_beats({"gr-nightly": {"title": "Nightly check", "reason": "Recall timed out"}})
        for gone in ('class="top"', 'id="summary"', 'class="hero', 'class="tile go"', "All clear", "things need attention</div>"):
            self.assertNotIn(gone, html, gone)
        self.assertRegex(html, r'data-tab="status">Status<span class="n crit"')           # the tab's badge is as it was
        status_tab = html[html.index('id="tab-status"'):]
        self.assertTrue(status_tab.startswith('id="tab-status" hidden><div class="onlybar">'), status_tab[:80])
        self.assertIn('id="jobs"', status_tab)                                          # and each card still shows its own trouble

    def test_the_card_is_first_on_the_overview_and_opens_on_the_sentence(self):
        html = build_with_beats({"gr-nightly": {"title": "Nightly check", "reason": "Recall timed out"}})
        overview = html[html.index('id="tab-overview"'):html.index('id="tab-status"')]
        self.assertLess(overview.index('id="waiting-now"'), overview.index('id="your-work"'))
        self.assertLess(overview.index('id="waiting-now"'), overview.index('id="threads"'))
        self.assertNotIn('class="lead', overview)
        self.assertRegex(overview[overview.index('id="waiting-now"'):], r"<h2>One thing needs you\.</h2>")

    def test_a_row_with_an_action_has_it_as_the_main_button_and_its_link_secondary(self):
        need = status.attn_need("warning", "x", "#repos", label="See the changes", act='<button class="act" type="button">Do it</button>')
        html = status.need_row(need)
        self.assertIn('<span class="wacts"><button class="act" type="button">Do it</button><a class="alt" href="#repos">See the changes</a></span>', html)
        plain = status.need_row(status.attn_need("warning", "x", "#repos", label="See the changes"))
        self.assertIn('<a class="act" href="#repos">See the changes</a>', plain)         # a row with no action keeps its link as its button
        self.assertNotIn("wacts", plain)

    def test_late_actions_are_the_late_lines_with_a_tick_and_a_date(self):
        html = build_with_beats({}, late_todo)
        row = self.need_rows(html)[0]
        self.assertIn("1 late action", row)
        late = row[row.index('<div class="wlate">'):]
        self.assertIn('<button class="tick"', late)
        self.assertIn('<button class="tdate late"', late)
        self.assertIn("Send it", late)
        self.assertRegex(row, r'<a class="alt" href="#todolist" data-tz-go="Work">Open the list</a>')       # the link is secondary
        self.assertIn(".querySelectorAll('.tview,.yrows,.wlate')", status.TODO_JS)         # the tick and the date menu work there too

    def test_no_check_warnings_row_and_the_check_error_stays(self):
        warn = {"warnings": 27, "errors": 0}
        err = {"warnings": 27, "errors": 2}
        for result, rows in ((warn, 0), (err, 1)):
            with mock.patch.object(status, "check", return_value=dict(result, groups=[], pending=False, failed=False)):
                html = build_with_beats({})
            texts = [r for r in self.need_rows(html) if "The check found" in r]
            self.assertEqual(rows, len(texts), result)
            self.assertNotIn("warnings</span>", "".join(texts))
        self.assertIn("The check found 2 errors", self.card(html))
        self.assertIn('data-g="broken"', self.card(html))

    def test_files_not_committed_offers_commit_them_for_a_young_zone_repository(self):
        with mock.patch.object(status, "bounded_ready", return_value=True):
            html = build_with_beats({}, lambda root: dirty_zone(root, 4, ("Notes.md", "Acme/Draft.md")))
        row = next(r for r in self.need_rows(html) if "not committed" in r)
        self.assertRegex(row, r"\d+ files not committed")
        self.assertIn("oldest changed 4 days ago", row)
        m = re.search(r'<button class="act apponly" type="button" data-commit="Work" data-files="([^"]*)"[^>]*>Commit them</button>', row)
        self.assertTrue(m, row)
        listed = json.loads(htmllib.unescape(m.group(1)))
        self.assertTrue({"Zones/Work/Acme/Draft.md", "Zones/Work/Notes.md"} <= set(listed), listed)      # workspace-relative, as `commit-files` takes them
        self.assertIn('<a class="alt" href="#repos">See the changes</a>', row)           # the link is secondary

    def test_commit_them_is_not_offered_for_old_changes_and_the_row_says_where_they_may_belong(self):
        with mock.patch.object(status, "bounded_ready", return_value=True):
            html = build_with_beats({}, lambda root: dirty_zone(root, 45))
        row = next(r for r in self.need_rows(html) if "not committed" in r)
        self.assertNotIn("Commit them", row)
        self.assertIn("they may belong in .gitignore", row)
        self.assertIn('<a class="act" href="#repos">Show me</a>', row)                   # Show me first, as the only button

    def test_without_a_bounded_run_the_row_keeps_its_link_alone(self):
        with mock.patch.object(status, "bounded_ready", return_value=False):
            html = build_with_beats({}, lambda root: dirty_zone(root, 4))
        row = next(r for r in self.need_rows(html) if "not committed" in r)
        self.assertNotIn("Commit them", row)
        self.assertIn('<a class="act" href="#repos">See the changes</a>', row)

    def test_commit_row_is_for_one_zone_only(self):
        ws = Path("/w")
        base = {"name": "Work", "folder": ws / "Zones" / "Work", "dirty": 1, "changes": [("a.md", ("unstaged",))],
                "since": self.NOW - dt.timedelta(days=3)}
        with mock.patch.object(status, "bounded_ready", return_value=True):
            self.assertIn("data-commit=\"Work\"", status.commit_row(ws, base, self.NOW)["act"])
            for other in (dict(base, name="Workspace", folder=ws), dict(base, name="Wikis", folder=ws / "Wikis"),
                          dict(base, name="Meetings", folder=ws / "Wikis" / "Meetings"),
                          dict(base, changes=[("a.md", ("conflicted",))]),
                          dict(base, changes=[("f%d.md" % i, ("unstaged",)) for i in range(status.COMMIT_MOST + 1)], dirty=status.COMMIT_MOST + 1)):
                self.assertEqual({}, status.commit_row(ws, other, self.NOW))
        with mock.patch.object(status, "bounded_ready", return_value=False):
            self.assertEqual({}, status.commit_row(ws, base, self.NOW))

    def test_try_again_is_for_garricks_own_update_job_only(self):
        job = {"title": "Garrick update", "status": "failed", "code": 1, "reason": "no network", "name": "gr-update", "garrick": True}
        need = status.job_need(job)
        self.assertIn('data-try-update="1"', need["act"])
        self.assertIn(">Try again<", need["act"])
        self.assertEqual("See the log", need["label"])                                    # the log is the secondary link
        for other in (dict(job, garrick=False), dict(job, name="gr-nightly"), dict(job, name="update-wiki", garrick=False)):
            self.assertNotIn("act", status.job_need(other))

    def test_the_buttons_that_act_are_for_the_app_and_a_browser_keeps_each_link(self):
        for needle in (".nohost .wacts .act,.nohost .wlate{display:none}", ".nohost .wacts .alt{"):
            self.assertIn(needle, status.WAITING_CSS)
        js = status.COMMIT_JS
        self.assertIn("if(!host)return;", js)
        self.assertIn("verb:'commit-files',zone:c.dataset.commit,files:files", js)
        self.assertIn("verb:'commit-files',undo:u.dataset.undoCommit,repo:u.dataset.repo", js)
        self.assertIn("var r=window.GarrickRelease;if(r&&r.update)r.update()", js)         # Try again runs the update's own code
        self.assertIn("update:function(){if(!busy)go()}", status.RELEASE_JS)
        self.assertNotIn("innerHTML", js)                                                  # drawn with textContent only

    def test_the_page_loads_with_no_app_host_and_every_row_keeps_a_link(self):
        with mock.patch.object(status, "bounded_ready", return_value=True):
            html = build_with_beats({"gr-nightly": {"title": "Nightly check", "reason": "Recall timed out"}},
                                    lambda root: (late_todo(root), dirty_zone(root, 4)))
        for row in self.need_rows(html):
            self.assertRegex(row, r'<a class="(act|alt)" href="[^"]+"', row)


class Badges(unittest.TestCase):
    """The tab bar (#560): at most one badge on a tab, and it is a number."""

    def tabs(self, html):
        bar = html[html.index('<div class="tabs" role="tablist">'):]
        bar = bar[:bar.index("</div>")]
        return {m.group(1): m.group(2) for m in re.finditer(r'<button[^>]*data-tab="([a-z]+)">(.*?)</button>', bar, re.S)}

    def test_a_critical_badge_has_the_icon_and_the_words_in_its_label_and_title_only(self):
        html = status.tab_badge("x", 3, " action is late", " actions are late", True)
        self.assertIn('class="n crit"', html)
        self.assertIn('aria-label="3 actions are late"', html)
        self.assertIn('title="3 actions are late"', html)
        self.assertIn("<svg", html)
        self.assertRegex(re.sub(r"<[^>]+>", "", html), r"^3$")

    def test_a_warning_badge_has_no_icon(self):
        html = status.tab_badge("x", 1, " thing needs attention", " things need attention", False)
        self.assertIn('class="n warn"', html)
        self.assertNotIn("<svg", html)
        self.assertIn('aria-label="1 thing needs attention"', html)

    def test_no_badge_at_zero(self):
        self.assertEqual("", status.tab_badge("x", 0, " a", " b", True))

    def test_the_overview_and_the_guide_carry_nothing(self):
        tabs = self.tabs(page_html())
        self.assertEqual("Overview", tabs["overview"])
        self.assertEqual("Guide", tabs["guide"])

    def test_no_tab_renders_more_than_one_badge_and_no_badge_holds_a_word(self):
        html = build_with_beats({"gr-nightly": {"title": "Nightly check", "reason": "Recall timed out"}}, late_todo)
        tabs = self.tabs(html)
        self.assertTrue(tabs)
        for name, inner in tabs.items():
            self.assertLessEqual(len(re.findall(r'<span class="n ', inner)), 1, name)
            self.assertNotIn('class="dot', inner, name)
            for badge in re.findall(r'<span class="n [^"]*"[^>]*>(.*?)</span>', inner, re.S):
                self.assertRegex(re.sub(r"<svg.*?</svg>", "", badge, flags=re.S), r"^\d*$", name)

    def test_todo_shows_its_late_count_critical_with_the_icon_and_no_total(self):
        html = build_with_beats({}, late_todo)
        todo = self.tabs(html)["todo"]
        self.assertRegex(todo, r'<span class="n crit" id="tabn-late" aria-label="1 action is late" title="1 action is late"><svg[^>]*>.*?</svg>1</span>')
        self.assertNotIn('<span class="n">', todo)
        self.assertNotRegex(todo, r"\d+ late")

    def test_todo_has_no_badge_when_nothing_is_late(self):
        self.assertEqual("Todo", self.tabs(build_with_beats({}))["todo"])

    def test_status_is_critical_when_something_failed_and_warning_otherwise(self):
        failed = self.tabs(build_with_beats({"gr-nightly": {"title": "Nightly check", "reason": "Recall timed out"}}))["status"]
        self.assertRegex(failed, r'<span class="n crit" id="tabn-status" aria-label="\d+ things? needs? attention"')
        self.assertIn("<svg", failed)
        self.assertNotIn("Act now", failed)
        warn = self.tabs(page_html())["status"]
        if warn != "Status":
            self.assertIn('class="n warn"', warn)
            self.assertNotIn("<svg", warn)

    def test_the_tab_dots_with_words_are_gone(self):
        css = status.LOOK_CSS
        self.assertNotIn(".tabs .dot.tr", css)
        self.assertNotIn(".tabs .dot.tr", status.CSS)
        self.assertNotIn("'.tabs [data-tab]').forEach(function(b){var d=b.querySelector('.dot.tr')", status.LAYOUT_JS)

    def test_context_shows_the_open_questions_of_one_place_as_a_warning_number_and_none_at_zero(self):
        button = status.questions_mod().tab_button()
        self.assertIn('<span class="n warn" id="qp-tab-n" hidden></span>', button)
        js = status.CONTEXT_JS
        self.assertIn("tn.hidden=!c", js)
        self.assertIn("tn.setAttribute('aria-label',c?w:'')", js)
        self.assertIn("questions to answer", js)


def late_todo(root):
    (root / "Zones" / "Work" / "Todo.md").write_text("# Work: open actions\n\n## Inbox\n\n- [ ] Send it 📅 2026-11-02\n\n## Done\n", encoding="utf-8")


class Work(unittest.TestCase):
    def w(self, **kw):
        base = {"row": {}, "actions": [], "waiting": None, "mine": False, "next": "Send it", "moved": TODAY}
        base.update(kw)
        return base

    def test_state_is_one_word(self):
        self.assertEqual("late", status.work_state(self.w(row={"late": 1}), TODAY))
        self.assertEqual("late", status.work_state(self.w(actions=[{"late": True}]), TODAY))
        self.assertEqual("act", status.work_state(self.w(waiting="Marco: the call", mine=True), TODAY))
        self.assertEqual("wait", status.work_state(self.w(waiting="Theo: the volumes"), TODAY))
        self.assertEqual("look", status.work_state(self.w(next=None), TODAY))
        self.assertEqual("look", status.work_state(self.w(moved=TODAY - dt.timedelta(days=15)), TODAY))
        self.assertEqual("good", status.work_state(self.w(), TODAY))

    def test_touched_in_words(self):
        self.assertEqual("Touched today", status.touched_said(TODAY, TODAY))
        self.assertEqual("Touched yesterday", status.touched_said(TODAY - dt.timedelta(days=1), TODAY))
        self.assertEqual("Touched 6 days ago", status.touched_said(TODAY - dt.timedelta(days=6), TODAY))


class JobRows(unittest.TestCase):
    """A job's row keeps its name, and its status cell says each thing once (#565)."""

    LONG = "exited 1 after 1498s; recall (exit 124) failed; " + "x" * 30

    def rows(self, html):
        block = html[html.index('<div class="rows jobs">'):]
        return re.findall(r'<div class="row" data-ok="\d">.*?</span></div>', block, re.S)

    def cells(self, html):
        return [re.search(r'<span class="status[^"]*"[^>]*>(.*?)</span></div>', r, re.S) for r in self.rows(html)]

    def test_an_eighty_character_reason_leaves_the_name_column_a_floor_and_the_status_column_a_fixed_width(self):
        reason = "r" * 80
        html = build_with_beats({"gr-nightly": {"title": "Nightly check", "reason": reason}})
        css = html[html.index(".jobs .row{grid-template-columns:"):]
        wide = re.findall(r"\.jobs \.row\{grid-template-columns:(18px [^}]*86px[^}]*)\}", html)
        self.assertTrue(wide)
        for cols in wide:
            self.assertIn("minmax(160px,1fr)", cols)            # the name never shrinks to nothing
            self.assertNotIn("auto", cols)                      # the last column has no open end: every row has the same tracks
            self.assertTrue(cols.endswith("minmax(0,300px)"))   # the status column gives way in a narrow card, up to 300px in a wide one
        row = next(r for r in self.rows(html) if "gr-nightly" in r)
        self.assertIn(">gr-nightly</button>", row)
        self.assertIn('<span class="say">%s</span>' % reason, row)   # the whole reason is in the page, clipped by the style
        self.assertIn(".jobs .status .say{min-width:0;overflow:hidden;text-overflow:ellipsis", css)

    def test_a_fine_job_shows_the_pill_alone_and_no_row_says_ok_beside_fine(self):
        html = build_with_beats({"gr-ok": {"exit": 0, "ok": True},
                                 "gr-quiet": {"exit": 6, "ok": True, "quiet": True},
                                 "gr-idle": {"exit": 0, "ok": True, "no_call": True}})
        for r in self.rows(html):
            self.assertIn("Fine", r)
            self.assertNotRegex(r, r">\s*ok[,<\s]")
            self.assertNotIn("is quiet", re.sub(r'data-tip="[^"]*"', "", r))
            self.assertNotIn("called no assistant", re.sub(r'data-tip="[^"]*"', "", r))
        quiet = next(r for r in self.rows(html) if "gr-quiet" in r)
        self.assertIn('data-tip="Exit 6 counts as fine for this job."', quiet)

    def test_a_failure_says_its_reason_once_and_the_code_goes_to_the_tooltip(self):
        html = build_with_beats({"gr-a": {"exit": 1}, "gr-b": {"exit": 124, "reason": "Recall timed out"},
                                 "gr-c": {"exit": 1, "reason": "it exited with code 1"}})
        cells = dict(zip(("gr-a", "gr-b", "gr-c"), [c.group(1) for c in self.cells(html)]))
        for name, cell in cells.items():
            text = re.sub(r"<[^>]+>", " ", cell)
            self.assertLessEqual(len(re.findall(r"\b(?:exit )?1\b" if name != "gr-b" else r"\b124\b", text)), 1, text)
            self.assertNotRegex(text, r"exit \d+:")
        self.assertIn('<span class="say">exit 1</span>', cells["gr-a"])
        self.assertIn('<span class="say">exit 1</span>', cells["gr-c"])
        self.assertIn('<span class="say">Recall timed out</span>', cells["gr-b"])
        row = next(r for r in self.rows(html) if "gr-b" in r)
        self.assertIn('data-tip="Exit 124"', row)

    def test_no_empty_tooltip_is_written_and_the_script_skips_one(self):
        html = build_with_beats({"gr-ok": {"exit": 0, "ok": True}, "gr-bad": {"exit": 1}})
        self.assertNotIn('data-tip=""', html)
        self.assertIn("if(!t||!t.dataset.tip){tip.style.opacity=0;return}", html)


class OpeningAThread(unittest.TestCase):
    """Settings > Opening a thread: no path, the cmux setting under its row, a Default only where it can apply (#577)."""

    def card(self):
        return status.launcher_choices(("finder", "claude", "cmux"), why={}, agent="claude")

    def test_the_card_holds_no_system_path(self):
        self.assertNotIn("System/", re.sub(r"<[^>]+>", " ", self.card()))
        self.assertNotIn("desk.json", self.card())

    def test_the_agent_row_sits_under_cmux_indented_and_hides_with_its_box(self):
        card = self.card()
        self.assertLess(card.index('data-launcher="cmux"'), card.index('id="desk-agent-row"'))
        self.assertRegex(card, r'class="launcher-row srow apponly launcher-sub" id="desk-agent-row"')
        self.assertRegex(status.SETTINGS_CSS, r"\.launcher-sub\{padding-left:\d+px\}")
        # shown and hidden in the script as the box is ticked, with no rebuild
        self.assertIn("r.style.display=!c||c.disabled||!c.checked?'none':''", status.JS)
        self.assertIn("daRow()", status.JS[status.JS.index("c.onchange=function(){var p=lprefs()"):][:600])

    def test_a_default_is_drawn_only_on_a_row_that_is_on(self):
        self.assertIn("r.parentNode.classList.toggle('nodefault',r.disabled)", status.JS)
        self.assertIn(".launcher-default.nodefault{visibility:hidden}", status.SETTINGS_CSS)
        self.assertIn("r.disabled=!c||c.disabled||!c.checked", status.JS)          # unticked, uninstalled: no radio
        card = self.card()
        self.assertNotIn('data-launcher="preview"></label><label class="launcher-default"', card)   # Preview never had one
        self.assertEqual(7, card.count('name="garrick-default"'))      # one for each way but Preview, the two new sessions included

    def test_switching_off_the_default_row_moves_it_and_says_so(self):
        self.assertIn("GarrickPrefs.set(p,moved?'note':dpref())", status.JS)
        self.assertIn("Clicking a thread now opens the note.", status.JS)


class ChannelsCard(unittest.TestCase):
    """Settings > Ask: Telegram's state first, only when something is wrong (#682), its menus greyed while it is off, the held
    list in its own part, only when something waits (#581, #682)."""

    def card(self, state=None, held=None):
        import json as _json
        import os as _os
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            root = base / "Workspace"
            build_workspace(root)
            jobs = base / "jobs"
            jobs.mkdir()
            if state:
                (jobs / "telegram-status.json").write_text(_json.dumps(state), encoding="utf-8")
            with mock.patch.dict(_os.environ, {"GARRICK_JOBS_DIR": str(jobs), "HOME": str(base)}):
                data = status._data(root, None, "channels")
                if held is not None and data.get("channels"):
                    data["channels"]["held"] = held
                return status.channels_settings(root, data)

    def telegram_block(self, html):
        start = html.index('<div class="setpart chblock" id="channels-telegram">')
        return html[start:html.index('id="channels-held"') if 'id="channels-held"' in html else len(html)]

    def test_off_the_state_line_comes_first_and_the_menus_are_greyed_with_a_button(self):
        block = self.telegram_block(self.card())
        self.assertTrue(block.index(status.TELEGRAM_DOWN) < block.index("<select"))
        self.assertEqual(3, len(re.findall(r"<select[^>]* disabled ", block)))
        self.assertIn(status.NOT_SET_UP, block)
        self.assertRegex(block, r'<button class="act sm" type="button" data-request="set up Telegram"[^>]*>Set up Telegram</button>')
        self.assertLess(block.index("Set up Telegram"), block.index("<select"))

    def test_running_the_menus_are_live_and_there_is_no_button(self):
        import time as _time
        block = self.telegram_block(self.card({"state": "running", "beat": _time.time(), "pid": 1, "last_received": None}))
        self.assertNotIn(" disabled", block)
        self.assertNotIn("Set up Telegram", block)
        self.assertNotIn('id="telegram-service"', block)                    # all is well: no status line (#682)
        self.assertNotIn("receiver is running", block)

    def test_a_receiver_that_is_not_connected_says_one_plain_sentence_first(self):
        why = "Another program is already reading this bot's messages."
        for state in ({"state": "conflict", "why": why, "beat": 1, "pid": 1}, {"state": "running", "beat": 1, "pid": 1}):
            block = self.telegram_block(self.card(state))
            import html as _h
            text = _h.unescape(block)
            self.assertIn(status.TELEGRAM_DOWN, text)
            self.assertLess(text.index(status.TELEGRAM_DOWN), text.index("<select"))
            self.assertNotIn(why, text)

    def test_the_held_list_shows_only_when_something_waits_after_telegram(self):
        html = self.card()
        self.assertNotIn("Waiting for your yes", html)                     # nothing waits: no heading, no sentence (#682)
        self.assertNotIn("Nothing is waiting for your yes", html)
        row = {"id": "h1", "what": "Send Dana the price sheet", "where": "dana@acme.example", "channel": "telegram", "zone": "Work",
               "kind": "send", "detail": "", "hours_left": 5}
        html = self.card(held=[row])
        self.assertIn('<div class="setpart" id="channels-held"><h4 class="setsubh">Waiting for your yes</h4><div id="held-actions">', html)
        self.assertIn("Send Dana the price sheet", html)
        self.assertLess(html.index('<h4 class="setsubh">Telegram</h4>'), html.index("Waiting for your yes"))
        self.assertGreater(html.index("Waiting for your yes"), html.rindex('data-key="autonomy"'))

    def test_no_path_and_no_model_code_name_in_the_visible_text(self):
        html = self.card()
        text = re.sub(r"<[^>]+>", " ", html)
        for word in ("System/", "garrick-settings", "haiku", "sonnet", "opus", "git "):
            self.assertNotIn(word, text.lower() if word != "System/" else text)
        tiers = re.findall(r'data-key="tier"[^>]*>(.*?)</select>', html)
        self.assertEqual(2, len(tiers))
        for t in tiers:
            self.assertEqual(["Small", "Medium", "Large"], re.findall(r"<option[^>]*>([^<]*)</option>", t))
        self.assertIn("changes that can be undone", status.CHANNELS_HELP)       # the Ask section's "?" (#682)


def two_zones_one_late_each(root):
    """Work has one late action and Personal two: a sum would read 3."""
    (root / "Zones" / "Work" / "Todo.md").write_text("# Work: open actions\n\n## Inbox\n\n- [ ] Send it \U0001F4C5 2026-11-02\n\n## Done\n", encoding="utf-8")
    personal = root / "Zones" / "Personal"
    personal.mkdir(parents=True, exist_ok=True)
    (personal / "Todo.md").write_text("# Personal: open actions\n\n## Inbox\n\n- [ ] Pay it \U0001F4C5 2026-11-01\n- [ ] Book it \U0001F4C5 2026-11-03\n\n## Done\n", encoding="utf-8")


class LookItems(unittest.TestCase):
    """The look items of the 0.68.0 review: plural agreement, the Todo badge, the State reason, hit targets, the Guide's commands."""

    def test_a_count_and_its_noun_agree_in_one_helper(self):
        self.assertEqual(["1 error", "2 errors", "0 errors"], [status.counted(n, "error") for n in (1, 2, 0)])
        self.assertEqual("1 project or thread", status.counted(1, "project or thread", "projects and threads"))
        self.assertEqual("idle 1 day", "idle %s" % status.counted(1, "day"))
        self.assertEqual("about 1 minute", "about %s" % status.counted(1, "minute"))
        self.assertIn("(V.length===1?' note, ':' notes, ')+E.length+(E.length===1?' link':' links')", page_html())

    def test_the_context_tile_and_caption_say_1_error_not_1_errors(self):
        def check(errors, warnings):
            def extra(root):
                tools = root / "System" / "tools"
                tools.mkdir(parents=True, exist_ok=True)
                found = [{"check": "walls", "severity": "error", "path": "Zones/Work/Acme/Memo.md", "message": "links a file of zone Personal"}] * errors \
                    + [{"check": "threads", "severity": "warning", "path": "Zones/Work/Acme/Pricing.md", "message": "no resume block"}] * warnings
                (tools / "check.py").write_text("import json\nprint(json.dumps(%r))\n" % {"errors": errors, "warnings": warnings, "findings": found})
            return build_with_beats({}, extra)
        one = check(1, 1)
        wait = lambda page: page[page.index('id="waiting-now"'):page.index('id="wrows"')]
        self.assertIn("The check found 1 error", wait(one))                  # the row that stays under Broken (#595); the tile is gone
        self.assertNotRegex(one, r"\b1 (errors|warnings)\b")
        two = check(2, 3)
        self.assertIn("The check found 2 errors", wait(two))
        self.assertNotIn("warning", wait(two))                               # the warnings are the Context queue's, no row

    def test_the_todo_badge_counts_the_zone_shown_and_the_script_follows_the_zone(self):
        html = build_with_beats({}, two_zones_one_late_each)
        bar = html[html.index('<div class="tabs" role="tablist">'):]
        todo = bar[bar.index('data-tab="todo"'):bar.index("</button>", bar.index('data-tab="todo"'))]
        self.assertRegex(todo, r'<span class="n crit" id="tabn-late" aria-label="1 action is late" title="1 action is late">')   # Work, the first zone: 1, not 3
        state = html[html.index('id="state-data">'):]
        data = json.loads(state[len('id="state-data">'):state.index("</script>")])
        self.assertEqual({"Work": 1, "Personal": 2}, data["late"])                                    # each zone's own, for the script
        self.assertIn("function lateBadge(z)", html)
        self.assertIn("st.set('garrick-todo-zone',z);empties();lateBadge(z)", html)               # every change of zone sets it again
        self.assertIn("b.hidden=!n", html)

    def test_the_state_reason_shows_on_focus_as_well_as_hover(self):
        # the row's markup is pinned in test_overview_work: a focusable span carrying the page's own tip, which listens for focus
        self.assertIn("document.addEventListener('focusin',show)", status.JS)
        self.assertIn("t.closest('[data-tip]')", status.JS)
        self.assertIn(".ywait:focus-visible{outline", page_html())

    def test_small_carets_and_help_marks_reach_24_pixels(self):
        html = page_html()
        self.assertIn('.tchev::after{content:"";position:absolute;inset:-2px}', html)             # 20px and 2px either side: 24
        self.assertIn(".qhelp{position:relative;flex:none;width:17px;height:17px", html)
        self.assertIn('.qhelp::after{content:"";position:absolute;inset:-4px}', html)             # 17px and 4px either side: 25
        self.assertIn(".grip::after,.hide::after,.totab::after,.tick::after,.pchev::after", html)  # the rest were already padded out

    def test_the_help_mark_hit_area_stays_inside_its_section_so_no_section_scrolls_sideways(self):
        # The 4px hit area of a "?" at the end of a row reached past the section's box and made it scroll by 3px (1280px and
        # 375px). The mark keeps 4px of margin on that side, and a wall row may wrap at 375px instead of pushing its edge.
        html = page_html()
        self.assertIn('dialog.settings .setsec .qhelp{margin-right:4px}', html)
        self.assertIn(".wallrow{display:flex;flex-wrap:wrap;", html)

    def test_the_guide_shows_a_zone_command_only_behind_details(self):
        gd = status.guide_mod()
        text = "# Zones\n\nChange a flag:\n\n```\npython3 System/tools/scaffold.py zone --name Garden --walled\n```\n\nList them:\n\n```\nls Zones\n```\n"
        html = gd.Renderer().render(text) if hasattr(gd, "Renderer") else ""
        self.assertTrue(html)
        shown = re.sub(r"<details class=\"gd-cmd\">.*?</details>", "", html, flags=re.S)
        self.assertNotIn("scaffold.py", shown)
        self.assertIn('<details class="gd-cmd"><summary>Details</summary><pre><code>python3 System/tools/scaffold.py zone', html)
        self.assertIn("<pre><code>ls Zones</code></pre>", shown)                      # any other block stays as it was


DANA_LINE = "- [ ] Dana: send the price sheet #waiting \u23f3 2026-11-11"
THEO_LINE = "- [ ] Theo: send the letter #waiting \u23f3 2026-11-12"


def followup_key(line):
    import hashlib
    return hashlib.sha1(line.rstrip().encode("utf-8")).hexdigest()[:16]


def followups_workspace(records=None, personal=False):
    """Work holds Dana's due line, a late line of its own and one that is not due yet; with `personal`, Personal holds a due line too."""
    def extra(root):
        work = root / "Zones" / "Work"
        (work / "Todo.md").write_text("# Work: open actions\n\n## Inbox\n\n- [ ] Send it \U0001F4C5 2026-11-02\n\n## Waiting on\n\n%s\n"
                                      "- [ ] Alex: later one #waiting \u23f3 2026-11-30\n\n## Done\n" % DANA_LINE, encoding="utf-8")
        if records is not None:
            (work / ".todo-followups.json").write_text(json.dumps(records), encoding="utf-8")
        if personal:
            home = root / "Zones" / "Personal"
            home.mkdir(parents=True, exist_ok=True)
            (home / "Todo.md").write_text("# Personal: open actions\n\n## Waiting on\n\n%s\n\n## Done\n" % THEO_LINE, encoding="utf-8")
    return extra


class FollowUps(unittest.TestCase):
    """#603: the Follow-ups row of Waiting on you now, one for each zone with a Waiting on line whose chase day has come."""

    def rows(self, html):
        start = html.index('id="wneeds"')
        return re.findall(r'<div class="wrow wneed"[^>]*>.*?(?=<div class="wrow wneed"[^>]*>|</div></section>|</details>)', html[start:], re.S)

    def follow(self, html):
        return [r for r in self.rows(html) if "follow-up" in r]

    def test_the_waiting_line_leaves_late_actions_and_shows_once(self):
        html = build_with_beats({}, followups_workspace())
        late = [r for r in self.rows(html) if "late action" in r]
        self.assertEqual(1, len(late))
        self.assertIn("1 late action", late[0])
        self.assertIn("Send it", late[0])
        self.assertNotIn("price sheet", late[0])
        fu = self.follow(html)
        self.assertEqual(1, len(fu))
        self.assertIn("1 follow-up", fu[0])
        self.assertEqual(1, html.count("price sheet</span>") + html.count("price sheet\u201d.</span>") + html.count("price sheet\u201d: chase day"))
        self.assertNotIn("later one", fu[0])                      # a line not due is no follow-up

    def test_a_zone_with_only_a_due_waiting_line_has_no_late_actions_row(self):
        html = build_with_beats({}, followups_workspace(personal=True))
        home = [r for r in self.rows(html) if "Personal" in r]
        self.assertEqual(["follow-up"], [("follow-up" if "follow-up" in r else "late") for r in home])

    def test_a_line_not_looked_at_is_still_shown_with_its_words_and_day_and_two_buttons(self):
        fu = self.follow(build_with_beats({}, followups_workspace()))[0]
        self.assertIn("price sheet", fu)
        self.assertIn("chase day 11 Nov", fu)
        self.assertEqual(["todo-done", "todo-date"], re.findall(r'data-fu="([a-z-]+)"', fu))
        self.assertRegex(fu, r'<button class="act" type="button" data-fu="todo-done">Tick it</button>')
        self.assertRegex(fu, r'<button class="alt" type="button" data-fu="todo-date" data-date="2026-11-21">Give it a week</button>')

    def test_no_sign_offers_chase_as_the_main_button(self):
        rec = {followup_key(DANA_LINE): {"line": DANA_LINE, "person": "Dana Whitlock", "result": "no sign", "since": "2026-11-11", "source": "", "title": "", "date": ""}}
        fu = self.follow(build_with_beats({}, followups_workspace(rec)))[0]
        self.assertIn("No reply from Dana since 11 Nov", fu)
        self.assertEqual(["chase", "todo-date", "todo-done"], re.findall(r'data-fu="([a-z-]+)"', fu))
        self.assertRegex(fu, r'<button class="act" type="button" data-fu="chase">Chase</button>')
        self.assertIn(">Give it a week<", fu)

    def test_a_reply_found_offers_tick_it_with_its_source_and_a_link_to_the_page(self):
        def extra(root):
            followups_workspace({followup_key(DANA_LINE): {"line": DANA_LINE, "person": "Dana Whitlock", "result": "delivered", "since": "2026-11-11",
                                                          "source": "Wikis/Meetings/wiki/sources/261112-acme-pricing.md", "title": "Acme pricing call", "date": "2026-11-12"}})(root)
        fu = self.follow(build_with_beats({}, extra))[0]
        self.assertIn("Dana sent it", fu)
        self.assertIn("Acme pricing call, 12 Nov", fu)
        self.assertEqual(["todo-done", "todo-date"], re.findall(r'data-fu="([a-z-]+)"', fu))
        self.assertRegex(fu, r'<button class="act" type="button" data-fu="todo-done">Tick it</button>')
        self.assertIn(">Still waiting<", fu)
        self.assertRegex(fu, r'<a class="alt" href="file://[^"]*/Wikis/Meetings/wiki/sources/261112-acme-pricing.md">Show me</a>')

    def test_a_source_that_leaves_the_workspace_has_no_link(self):
        rec = {followup_key(DANA_LINE): {"line": DANA_LINE, "person": "Dana", "result": "delivered", "source": "../../etc/passwd", "title": "X", "date": "2026-11-12"}}
        self.assertNotIn("Show me", self.follow(build_with_beats({}, followups_workspace(rec)))[0])

    def test_each_zone_has_its_own_row_with_its_own_lines(self):
        html = build_with_beats({}, followups_workspace(personal=True))
        fu = self.follow(html)
        self.assertEqual(2, len(fu))
        work = next(r for r in fu if "Work" in r)
        home = next(r for r in fu if "Personal" in r)
        self.assertIn("price sheet", work)
        self.assertNotIn("letter", work)
        self.assertIn("letter", home)
        self.assertNotIn("price sheet", home)
        self.assertIn("1 follow-up", work)
        self.assertIn("1 follow-up", home)

    def test_the_lead_sentence_counts_the_row_once(self):
        html = build_with_beats({}, followups_workspace())
        self.assertIn("<h2>Two things need you.</h2>", html)          # the late action, and the follow-up

    def test_the_buttons_send_their_verb_and_the_script_names_them(self):
        offered = {v for buttons in status.FOLLOW_BUTTONS.values() for v, _, _ in buttons}
        self.assertEqual({"todo-done", "todo-date", "chase", "show"}, offered)
        self.assertIn("'chase'", status.FOLLOWUP_JS)
        self.assertIn("{verb:b.dataset.fu,zone:row.dataset.z,file:row.dataset.f,key:row.dataset.k}", status.FOLLOWUP_JS)
        self.assertIn("host.postMessage({act:q})", status.FOLLOWUP_JS)
        self.assertIn("GarrickAct(q,said)", status.FOLLOWUP_JS)
        html = build_with_beats({}, followups_workspace())
        self.assertIn("function go(row,b)", html)

    def test_the_row_in_a_browser_is_hidden_like_the_late_lines_and_keeps_its_link(self):
        self.assertIn(".nohost .wacts .act,.nohost .wlate{display:none}", status.WAITING_CSS)
        fu = self.follow(build_with_beats({}, followups_workspace()))[0]
        self.assertIn('<div class="wlate">', fu)
        self.assertRegex(fu, r'<a class="alt" href="#todolist" data-tz-go="Work">Open the list</a>')


if __name__ == "__main__":
    unittest.main()


MEMORY_HARNESS = r"""
const js=require('fs').readFileSync(process.argv[2],'utf8');
const listeners={};
const field=(o)=>Object.assign({value:'',checked:false,defaultValue:'',min:'0',max:'99',dataset:{},matches:()=>false,querySelector:()=>null,querySelectorAll:()=>[]},o||{});
const els={'m-wake':field({checked:true}),'m-reach':field({value:'mid'}),'m-night':field({checked:true}),'m-min':field({value:'30',max:'600'}),'m-prevsaid':field({hidden:true}),'m-prev':field()};
const review=field({hidden:false});
const sec={querySelector:(q)=>q==='#m-prev'?els['m-prev']:null,querySelectorAll:(q)=>q==='.mcount [data-request]'?[review]:[],addEventListener:(t,f)=>{listeners[t]=f}};
global.document={getElementById:(id)=>id==='memory-settings'?sec:els[id]||null};
global.window={};
new Function(js)();
const edit=(v)=>{els['m-min'].value=v;listeners.change({target:els['m-min']})};
const out=[];
edit('45');out.push(review.hidden);       // edited: Review waits
edit('30');out.push(review.hidden);       // put back: Review shows again
edit('45');out.push(review.hidden);
window.GarrickMemory.saved();out.push(review.hidden);   // saved: Review shows again
edit('45');out.push(review.hidden);       // the saved value again, not a change
console.log(JSON.stringify(out));
"""


class MemoryReview(unittest.TestCase):
    """The Review button waits while a Memory edit is unsaved and shows again once it is saved or put back, with no reload."""

    def test_review_shows_again_when_the_edit_is_saved_or_undone(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("no node")
        with tempfile.TemporaryDirectory() as tmp:
            script, js = Path(tmp) / "h.js", Path(tmp) / "m.js"
            script.write_text(MEMORY_HARNESS, encoding="utf-8")
            js.write_text(status.MEMORY_JS, encoding="utf-8")
            out = subprocess.run([node, str(script), str(js)], capture_output=True, text=True, timeout=60)
        self.assertEqual(0, out.returncode, out.stderr)
        self.assertEqual([True, False, True, False, False], json.loads(out.stdout.strip().splitlines()[-1]))
