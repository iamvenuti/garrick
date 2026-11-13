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


class Page(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        base = Path(cls._tmp.name).resolve()
        cls.root = base / "Workspace"
        build_workspace(cls.root)
        (base / "jobs").mkdir()
        (base / "home").mkdir()
        with mock.patch.object(status, "launch_agents", lambda: base / "LaunchAgents"), \
                mock.patch.dict(status.os.environ, {"HOME": str(base / "home")}):
            cls.html = status.build(cls.root, now=dt.datetime(2026, 11, 9, 9, 0), folder=base / "jobs")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def css(self):
        return "\n".join(re.findall(r"<style>(.*?)</style>", self.html, re.S))

    def test_no_font_size_under_12px(self):
        css = self.css()
        sizes = [float(n) for n in re.findall(r"font-size:\s*([0-9.]+)px", css)]
        sizes += [float(n) for n in re.findall(r"font:[^;}]*?\b([0-9.]+)px", css)]
        self.assertTrue(sizes)
        self.assertEqual([], [n for n in sizes if n < 12], "a font size under 12px")

    def test_other_modules_css_has_none_either(self):
        for name in ("finding_queue.py", "guide.py", "questions_panel.py", "your_work.py"):
            text = (HERE / name).read_text(encoding="utf-8")
            small = [n for n in re.findall(r"font-size:\s*([0-9.]+)px", text) if float(n) < 12]
            self.assertEqual([], small, name)

    def test_body_text_is_15px_on_1_55(self):
        self.assertIn("font:15px/1.55 var(--sans)", status.CSS)

    def test_the_font_is_embedded_and_nothing_is_fetched(self):
        css = self.css()
        self.assertEqual(3, len(re.findall(r"@font-face\{font-family:\"Plus Jakarta Sans\"", css)))
        self.assertEqual(3, len(re.findall(r"src:url\(data:font/woff2;base64,", css)))
        self.assertIn("system-ui", css)
        # no stylesheet, font, script or image is asked of the network: every http(s) address is a link the reader follows
        self.assertNotRegex(self.html, r"<link[^>]+(?:href|src)=[\"']https?:")
        self.assertNotRegex(self.html, r"<script[^>]+src=")
        self.assertNotRegex(css, r"url\(\s*[\"']?https?:")
        self.assertNotRegex(css, r"@import")
        self.assertNotIn("fonts.googleapis", self.html)

    def test_the_font_files_are_vendored_with_their_licence(self):
        fonts = HERE / "fonts"
        for name, _ in status.FONT_FILES:
            self.assertTrue((fonts / name).is_file(), name)
        self.assertIn("SIL OPEN FONT LICENSE", (fonts / "OFL.txt").read_text(encoding="utf-8"))
        self.assertLess(sum((fonts / n).stat().st_size for n, _ in status.FONT_FILES), 120 * 1024)

    def test_without_the_files_the_page_keeps_the_system_font(self):
        with tempfile.TemporaryDirectory() as empty:
            self.assertEqual("", status.font_css(Path(empty)))
        self.assertIn('--sans:"Plus Jakarta Sans",system-ui', status.CSS)

    def test_the_display_face_stays_for_big_numbers_only(self):
        css = self.css()
        users = [m.strip().split("}")[-1].strip() for m in re.findall(r"([^{}]*)\{[^{}]*var\(--display\)", css)]
        self.assertEqual([".hero .fig", ".hero .fig,.tile .val"], [u for u in users if u])

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
        html = Page.html
        rows = re.findall(r'<a class="item"[^>]*>.*?</a>', html, re.S)
        self.assertTrue(rows)
        for row in rows:
            self.assertRegex(row, r'class="st [a-z]+"><svg[^>]*>.*?</svg>(Fine|Look soon|Late|Act now|Waiting)</span>')

    def test_a_dot_is_never_the_only_sign_of_a_state_in_the_built_markup(self):
        # what the script draws later has its own title; every dot the build writes has words beside it or is a pill
        self.assertNotRegex(Page.html, r'<span class="dot (?:good|warning|critical)"')


if __name__ == "__main__":
    unittest.main()
