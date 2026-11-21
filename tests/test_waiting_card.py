"""The Overview's Waiting on you now card (#474): rows, what they name, and never a question's text.

    cd tests && python3 -m unittest test_waiting_card

No real transcript, cmux or Mac notification is read: the rows are handed to the page.
"""
import datetime as dt
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import build_workspace  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "extras" / "status"))


def _load():
    spec = importlib.util.spec_from_file_location("garrick_status_waiting", REPO / "extras" / "status" / "status.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


status = _load()
SECRET = "Should we tell Birch & Co about the forty percent discount?"
NOW = dt.datetime(2026, 11, 10, 10, 0, tzinfo=dt.timezone.utc)


def row(sid, since, where="cmux", thread="Acme Review, Pricing", waits="a question", agent="claude", folder="/work/Pricing"):
    return {"id": sid, "agent": agent, "folder": folder, "thread": thread, "state": "waiting", "waiting_for": waits,
            "since": since, "where": where}


class Card(unittest.TestCase):
    def test_one_row_per_waiting_session_oldest_first(self):
        html = status.waiting_card([row("b", "2026-11-10T09:50:00Z", thread="Birch Entry"),
                                    row("a", "2026-11-10T09:00:00Z", waits="an approval for Bash")], NOW)
        self.assertEqual(["a", "b"], re.findall(r'class="wrow" data-id="([^"]*)"', html))
        self.assertIn("<h2>Two things need you.</h2>", html)                   # the heading is the lead sentence (#595)
        self.assertIn("an approval for Bash", html)
        self.assertIn("1 h", html)
        self.assertIn("10 min", html)

    def test_go_to_it_only_for_a_cmux_tab_and_the_others_name_the_app_and_the_folder(self):
        html = status.waiting_card([row("c", "2026-11-10T09:00:00Z", where="cmux"),
                                    row("d", "2026-11-10T09:01:00Z", where="desktop", folder="/work/Pricing"),
                                    row("t", "2026-11-10T09:02:00Z", where="terminal", agent="codex", folder="/work/Freight")], NOW)
        self.assertEqual(['data-wgo="c"'], re.findall(r'data-wgo="[^"]*"', html))
        self.assertIn("Claude&#x27;s desktop app, in Pricing", html)
        self.assertIn("Codex, in Freight", html)

    def test_with_no_session_waiting_the_card_is_built_calm_and_says_so_in_its_heading(self):
        html = status.waiting_card([], NOW)
        self.assertIn('class="card calm" id="waiting-now"', html)
        self.assertIn("<h2>Nothing needs you right now.</h2>", html)             # the heading says it; the body is folded away
        self.assertNotIn("No session is waiting on you.", html)
        self.assertIn('aria-live="polite"', html)                              # the region stays, so a new row is announced
        self.assertNotIn("calm", status.waiting_card([row("a", "2026-11-10T09:00:00Z")], NOW))
        self.assertIn("#waiting-now.calm>.body{display:none}", status.WAITING_CSS)

    def test_a_name_from_a_transcript_cannot_break_the_markup(self):
        html = status.waiting_card([row("a", "2026-11-10T09:00:00Z", thread='<img src=x onerror="1">')], NOW)
        self.assertNotIn("<img", html)

    def test_the_page_holds_the_card_and_its_script_and_hands_nothing_without_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "Workspace"
            build_workspace(root)
            jobs = Path(tmp) / "jobs"
            jobs.mkdir()
            with mock.patch.object(status, "launch_agents", lambda: Path(tmp) / "LA"), \
                    mock.patch.dict(os.environ, {"HOME": str(Path(tmp) / "home")}):
                bare = status.build(root, now=dt.datetime(2026, 11, 10, 10, 0), folder=jobs)
                full = status.build(root, now=dt.datetime(2026, 11, 10, 10, 0), folder=jobs,
                                    waiting_now=[row("a", "2026-11-10T09:00:00Z")])
        self.assertIn('id="waiting-now"', bare)
        self.assertNotIn("No session is waiting on you.", bare)
        self.assertIn("window.GarrickWaiting=", bare)
        self.assertIn('data-wgo="a"', full)
        self.assertLess(full.index('id="waiting-now"'), full.index('id="threads"'))      # first on the Overview

    def test_the_question_text_never_reaches_the_card_from_a_transcript(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            d = home / ".claude" / "projects" / "-x"
            d.mkdir(parents=True)
            rec = {"type": "assistant", "timestamp": "2026-11-10T09:00:00Z", "cwd": "/work/Pricing", "message": {"content": [
                {"type": "tool_use", "id": "t1", "name": "AskUserQuestion", "input": {"question": SECRET}}]}}
            (d / "a.jsonl").write_text(json.dumps({"type": "user", "message": {"content": "go"}}) + "\n" + json.dumps(rec) + "\n")
            with mock.patch.dict(os.environ, {"GARRICK_HOME": str(home)}):
                rows = status.waiting_rows(Path(tmp) / "ws")
        self.assertEqual(["a"], [r["id"] for r in rows])
        html = status.waiting_card(rows, NOW)
        self.assertNotIn("Birch", html)
        self.assertNotIn("discount", html)
        self.assertNotIn("discount", json.dumps(rows))

    def test_a_machine_with_no_transcripts_has_no_rows(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"GARRICK_HOME": tmp}):
            self.assertEqual([], status.waiting_rows(Path(tmp)))


HARNESS = r"""
const vm = require("vm");
const [js, data] = JSON.parse(process.argv[1]);
class El {
  constructor(tag) { this.tag = tag; this.children = []; this.dataset = {}; this.className = ""; this._text = ""; this.listeners = {}; }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(""); }
  appendChild(c) { this.children.push(c); return c; }
  addEventListener(k, f) { this.listeners[k] = f; }
  querySelector() { return null; }
  querySelectorAll() { return []; }
}
const box = new El("div");
const h2 = new El("h2");
const card = { dataset: { n: "0" }, querySelector: (q) => (q === "h2" ? h2 : null), classList: { on: null, toggle(c, on) { card.classList.on = on; } } };
const sent = [];
const ctx = { window: { webkit: { messageHandlers: { garrick: { postMessage: (m) => sent.push(m) } } } }, setInterval: () => 0, Date,
  document: { getElementById: (id) => (id === "wrows" ? box : id === "waiting-now" ? card : null), createElement: (t) => new El(t), querySelector: () => null } };
vm.createContext(ctx);
vm.runInContext(js, ctx);
ctx.window.GarrickWaiting(data);
const rows = box.children.map((r) => ({ id: r.dataset.id, text: r.textContent, go: r.children.filter((c) => c.dataset && c.dataset.wgo).map((c) => c.dataset.wgo) }));
const target = { closest: () => ({ dataset: { wgo: "c" } }) };
box.listeners.click({ target });
process.stdout.write(JSON.stringify({ rows, sent, calm: card.classList.on, lead: h2.textContent }));
"""


@unittest.skipUnless(shutil.which("node"), "Node is not installed")
class CardScript(unittest.TestCase):
    def run_js(self, data):
        done = subprocess.run(["node", "-e", HARNESS, json.dumps([status.WAITING_JS, data])], capture_output=True, text=True, timeout=60)
        self.assertEqual(0, done.returncode, done.stderr)
        return json.loads(done.stdout)

    def test_the_app_hands_a_minute_and_the_card_shows_only_the_waiting_oldest_first(self):
        rows = [row("b", "2026-11-10T09:30:00Z", thread="Birch Entry"), row("a", "2026-11-10T09:00:00Z"),
                dict(row("w", "2026-11-10T09:10:00Z"), state="working")]
        out = self.run_js({"ok": True, "sessions": rows})
        self.assertEqual(["a", "b"], [r["id"] for r in out["rows"]])
        self.assertIn("Go to it", out["rows"][0]["text"])
        self.assertEqual([{"waitingGo": "c"}], out["sent"])                  # the button's id goes to the app, nothing else

    def test_a_name_is_text_and_an_empty_minute_says_so(self):
        out = self.run_js([row("a", "2026-11-10T09:00:00Z", thread="<b>x</b>", where="terminal")])
        self.assertIn("<b>x</b>", out["rows"][0]["text"])                    # shown as text, never read as markup
        empty = self.run_js([])
        self.assertEqual([], empty["rows"])                                  # no line for an empty minute
        self.assertTrue(empty["calm"])                                       # the card goes calm with the last row
        self.assertEqual("Nothing needs you right now.", empty["lead"])
        one = self.run_js([row("a", "2026-11-10T09:00:00Z")])
        self.assertFalse(one["calm"])                                        # and leads with the first
        self.assertEqual("One thing needs you.", one["lead"])


class Tokens:
    """The colour tokens of status.CSS, per theme, and the contrast of two of them."""

    @staticmethod
    def block(css, opener):
        body = css[css.index(opener) + len(opener):]
        return dict(re.findall(r"--([\w-]+):(#[0-9a-fA-F]{6})\b", body[:body.index("}")]))

    @classmethod
    def themes(cls, css):
        return {"light": cls.block(css, ":root{"), "dark": cls.block(css, ':root[data-theme="dark"]{')}

    @staticmethod
    def luminance(hex_):
        r, g, b = (int(hex_[i:i + 2], 16) / 255 for i in (1, 3, 5))
        lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]

    @classmethod
    def contrast(cls, a, b):
        hi, lo = sorted((cls.luminance(a), cls.luminance(b)), reverse=True)
        return (hi + 0.05) / (lo + 0.05)


class TheStatusDot(unittest.TestCase):
    """The dot that marks a state (class `dot`, with `good`, `warning` or `critical` for a state) reads against the card
    it sits on in both themes: 3:1 or more for its fill, and its words stay, so it is never the only sign."""

    def fills(self):
        css = status.CSS
        base = re.search(r"\.dot\{[^}]*background:var\(--(\w+)\)\}", css).group(1)
        fills = {"none": base}
        for state in ("good", "warning", "critical"):
            fills[state] = re.search(r"\.dot\.%s\{background:var\(--(\w+)\)\}" % state, css).group(1)
        return fills

    def test_every_dot_fill_has_three_to_one_against_the_card_in_both_themes(self):
        themes = Tokens.themes(status.CSS)
        for theme, tokens in themes.items():
            for state, name in self.fills().items():
                for ground in ("surface", "page"):
                    ratio = Tokens.contrast(tokens[name], tokens[ground])
                    self.assertGreaterEqual(ratio, 3.0, "%s dot (%s) on %s in the %s theme: %.2f:1" % (state, name, ground, theme, ratio))

    def test_the_stateless_dot_is_not_the_empty_track_colour(self):
        self.assertNotEqual("none", self.fills()["none"])

    def test_the_dot_on_the_context_tab_carries_its_words_in_a_title(self):
        qp = importlib.util.spec_from_file_location("garrick_qp_dot", REPO / "extras" / "status" / "questions_panel.py")
        mod = importlib.util.module_from_spec(qp)
        qp.loader.exec_module(mod)
        self.assertIn('title="Something needs a look"', mod.tab_button("Something needs a look"))


class Live(HTMLParser):
    """Every aria-live element of a page, with the classes of the elements around it."""

    VOID = {"br", "img", "input", "hr", "meta", "link"}

    def __init__(self):
        super().__init__()
        self.stack, self.found = [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "aria-live" in a:
            self.found.append((a.get("id"), list(self.stack) + [(tag, a)]))
        if tag not in self.VOID:
            self.stack.append((tag, a))

    def handle_endtag(self, tag):
        while self.stack and self.stack[-1][0] != tag:
            self.stack.pop()
        if self.stack:
            self.stack.pop()


class TheLiveRegion(unittest.TestCase):
    """The region a screen reader listens to is not inside the calm card's hidden body (#600): it says the lead
    sentence whether the card is calm or not."""

    def regions(self, html):
        p = Live()
        p.feed(html)
        return p.found

    def test_no_live_region_sits_inside_the_body_the_calm_rule_hides(self):
        for rows in ([], [row("a", "2026-11-10T09:00:00Z")]):
            html = status.waiting_card(rows, NOW)
            found = self.regions(html)
            self.assertTrue(found)
            for ident, chain in found:
                for tag, a in chain:
                    self.assertNotIn("body", (a.get("class") or "").split(), ident)
                    self.assertIsNone(a.get("hidden"), ident)
            self.assertIn("wlive", [i for i, _ in found])
        self.assertIn("#waiting-now.calm>.body{display:none}", status.WAITING_CSS)
        css = re.search(r"\.srsay\{[^}]*\}", status.WAITING_CSS).group(0)
        self.assertNotIn("display:none", css)                                # visually hidden, not removed from the tree
        self.assertIn("clip", css)

    def test_the_region_says_the_lead_sentence_and_the_ids_stay(self):
        html = status.waiting_card([], NOW)
        self.assertRegex(html, r'<div class="srsay" id="wlive" role="status" aria-live="polite" aria-atomic="true">Nothing needs you right now\.</div>')
        for kept in ('id="waiting-now"', 'id="wneeds"', 'id="wrows"', 'data-n="0"'):
            self.assertIn(kept, html)
        self.assertNotRegex(html, r'id="wrows"[^>]*aria-live')

    def test_the_script_writes_to_it_when_the_count_changes_and_not_when_it_does_not(self):
        harness = """
const vm = require("vm");
const [js, steps] = JSON.parse(process.argv[1]);
class El { constructor() { this.children = []; this.dataset = {}; this.className = ""; this._t = ""; this.writes = []; }
  set textContent(v) { this._t = String(v); this.children = []; this.writes.push(String(v)); } get textContent() { return this._t; }
  appendChild(c) { this.children.push(c); return c; } addEventListener() {} querySelector() { return null; } querySelectorAll() { return []; } }
const box = new El(), h2 = new El(), live = new El();
live._t = "Nothing needs you right now."; live.writes = [];
const card = { dataset: { n: "0" }, querySelector: (q) => (q === "h2" ? h2 : null), classList: { toggle() {} } };
const ctx = { window: { webkit: { messageHandlers: { garrick: { postMessage() {} } } } }, setInterval: () => 0, Date,
  document: { getElementById: (id) => (id === "wrows" ? box : id === "waiting-now" ? card : id === "wlive" ? live : null),
              createElement: () => new El(), querySelector: () => null } };
vm.createContext(ctx); vm.runInContext(js, ctx);
const out = [];
for (const n of steps) { ctx.window.GarrickWaiting(Array.from({ length: n }, (_, i) => ({ id: "s" + i, state: "waiting", since: "2026-11-10T09:00:00Z", where: "cmux", thread: "T" + i }))); out.push([live.writes.slice(), live.textContent]); }
process.stdout.write(JSON.stringify(out));
"""
        if not shutil.which("node"):
            self.skipTest("Node is not installed")
        done = subprocess.run(["node", "-e", harness, json.dumps([status.WAITING_JS, [0, 0, 1, 1, 2, 0]])], capture_output=True, text=True, timeout=60)
        self.assertEqual(0, done.returncode, done.stderr)
        out = json.loads(done.stdout)
        self.assertEqual([], out[0][0])                                      # the build's own sentence stands: nothing announced
        self.assertEqual([], out[1][0])                                      # still none waiting: not said again
        self.assertEqual(["One thing needs you."], out[2][0])                # the first row arrives: said
        self.assertEqual(["One thing needs you."], out[3][0])                # the same count: not said again
        self.assertEqual("Two things need you.", out[4][1])
        self.assertEqual("Nothing needs you right now.", out[5][1])          # and the last row going is said too


if __name__ == "__main__":
    unittest.main()
