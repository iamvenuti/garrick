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

    def test_the_big_number_is_the_h1_token(self):
        self.assertIn("font:600 var(--fs-h1)/1 var(--sans)", status.CSS)

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
        self.assertIn(".thread.sub{padding-left:20px;border-top:1px dashed var(--grid);font-size:var(--fs-sub)}", css)
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
            self.assertEqual("var(--sans)", family.strip())
        guide = status.guide_mod().GUIDE_CSS
        self.assertEqual(1, guide.count("ui-monospace"))
        self.assertEqual(1, css.count("ui-monospace"))                                          # and nowhere else on the page
        self.assertEqual(1, len(re.findall(r"\.gd-page code\{[^}]*monospace", css)))
        self.assertNotRegex(re.sub(r"sans-serif", "", css), r"(?i)\bserif\b|Georgia|Baskerville")   # no serif

    def test_big_numbers_are_the_sans_at_600_with_tabular_figures(self):
        css = self.css()
        self.assertNotIn("--display", css)
        self.assertIn(".hero .fig,.tile .val{font-family:var(--sans);font-weight:600;font-variant-numeric:tabular-nums}", css)

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
        rows = re.findall(r'<a class="item"[^>]*>.*?</a>', html, re.S)
        self.assertTrue(rows)
        for row in rows:
            self.assertRegex(row, r'class="st [a-z]+"><svg[^>]*>.*?</svg>(Fine|Look soon|Late|Act now|Waiting)</span>')

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
    """The Overview opens on one sentence that says how many things wait, and it agrees with the card (#551)."""

    def test_the_sentence_in_three_cases(self):
        self.assertEqual("Three things need you.", status.lead_said(3))      # several waiting
        self.assertEqual("One thing needs you.", status.lead_said(1))        # one
        self.assertEqual("Nothing needs you right now.", status.lead_said(0))  # none
        self.assertEqual("Twelve things need you.".replace("Twelve", "12"), status.lead_said(12))

    def test_several_waiting_gives_counts_by_kind_and_leads_to_the_first(self):
        items = [status.attn_need("critical", "The check did not run", "#checks", label="See the check"),
                 status.late_need(zone("Work", [todo_row("a", dt.date(2026, 11, 2), True), todo_row("b", dt.date(2026, 11, 5), True)]), TODAY),
                 status.attn_need("warning", "3 items waiting in the inboxes", "#inboxes", kind="inbox", count=3, label="Open the inbox")]
        html = status.lead_block(items, 0)
        self.assertIn("Three things need you.", html)
        self.assertIn("1 problem · 2 late actions · 3 in the inboxes", html)
        self.assertNotIn("The check did not run ·", html)                    # counts only: the card lists the rows
        self.assertRegex(html, r'<a class="btn primary" id="lead-go" href="#checks">See the check')
        self.assertNotIn(" hidden", html.split('<a class="btn')[1])

    def test_the_lead_line_is_one_line_in_a_fixed_order(self):
        items = [status.attn_need("warning", "w", "#checks", kind="warnings", count=20),
                 status.attn_need("warning", "f", "#repos", kind="files", count=12),
                 status.attn_need("warning", "i", "#inboxes", kind="inbox", count=2),
                 status.late_need(zone("Work", [todo_row("a", dt.date(2026, 11, 2), True)] * 5), TODAY),
                 status.attn_need("critical", "j1", "#jobs", kind="job"), status.attn_need("critical", "j2", "#jobs", kind="job")]
        html = status.lead_block(items, 0)
        self.assertIn("2 jobs failed · 5 late actions · 2 in the inboxes · 12 files not committed · 20 warnings", html)

    def test_one_waiting(self):
        html = status.lead_block([status.late_need(zone("Home", [todo_row("a", dt.date(2026, 11, 8), True)]), TODAY)], 0)
        self.assertIn("One thing needs you.", html)
        self.assertIn("1 late action", html)
        self.assertNotIn("in Home", html)
        self.assertIn('href="#todolist" data-tz-go="Home"', html)

    def test_none_waiting_says_so_and_has_no_button(self):
        html = status.lead_block([], 0)
        self.assertIn("Nothing needs you right now.", html)
        self.assertRegex(html, r'<a class="btn primary" id="lead-go" href="#" hidden></a>')

    def test_a_waiting_session_counts_and_leads_to_the_card_when_nothing_else_waits(self):
        html = status.lead_block([], 2)
        self.assertIn("Two things need you.", html)
        self.assertIn("2 sessions are waiting for you", html)
        self.assertIn('href="#waiting-now"', html)

    def test_no_count_is_cut_with_and_more(self):
        items = [status.attn_need("warning", "reason %d" % i, "#jobs", kind=k, count=2) for i, k in enumerate(("warnings", "files", "inbox", "other"))]
        html = status.lead_block(items, 0)
        self.assertNotIn("more", html)
        self.assertIn("2 in the inboxes · 2 files not committed · 2 warnings · 2 other things to look at", html)

    def test_the_card_lists_what_waits_with_a_button_and_stays_hidden_only_when_nothing_does(self):
        needs = [status.attn_need("critical", "A job failed", "#jobs"),
                 status.late_need(zone("Work", [todo_row("a", dt.date(2026, 11, 2), True)]), TODAY)]
        now = dt.datetime(2026, 11, 9, 9, 0, tzinfo=dt.timezone.utc)
        html = status.waiting_card([], now, needs)
        self.assertNotIn("nowait", html)
        self.assertIn("2 items", html)
        self.assertEqual(2, html.count('class="wrow wneed"'))
        self.assertIn('<a class="act" href="#jobs">See the details</a>', html)
        self.assertIn('data-tz-go="Work">Open the list</a>', html)
        self.assertIn("oldest was due Mon 2 Nov", html)
        self.assertIn("nowait", status.waiting_card([], now, []))
        self.assertIn("nowait", status.waiting_card([], now))

    def test_the_script_redraws_the_lead_from_the_same_figures(self):
        js = status.WAITING_JS
        for needle in ("function lead(sess)", "Nothing needs you right now.", "One thing needs you.", "explore-go"):
            self.assertIn(needle, js)
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

    def test_the_page_lead_and_the_card_count_the_same_things(self):
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
            fixed = len(re.findall(r'<div class="wrow wneed">', html))
            said = re.search(r'<h2 id="lead-h">([^<]*)</h2>', html).group(1)
            self.assertEqual(status.lead_said(fixed + n_sessions), said)
            self.assertEqual(n_sessions, len(re.findall(r'<div class="wrow" data-id=', html)))
            self.assertIn('data-n="%d"' % fixed, html)
            self.assertNotIn("tabn-overview", html)
        self.assertGreater(len(re.findall(r'<div class="wrow wneed">', none)) + 2, 0)


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
        return [(re.sub(r"<[^>]+>", "|", m).replace("||", "|").strip("|")) for m in re.findall(r'<div class="wrow wneed">(.*?)</div>', block, re.S)]

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

    def test_the_lead_line_holds_counts_only(self):
        html = build_with_beats({"gr-nightly": {"title": "Nightly check", "reason": "Recall timed out"}})
        why = re.search(r'<p id="lead-why">([^<]*)</p>', html).group(1)
        self.assertTrue(why.startswith("1 job failed"), why)
        self.assertNotIn("Nightly", why)

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
        for row in re.findall(r'<div class="wrow wneed">(.*?)</div>', block, re.S):
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


if __name__ == "__main__":
    unittest.main()
