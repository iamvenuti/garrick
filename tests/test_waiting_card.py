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
import time
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import build_workspace  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "extras" / "status"))
import agents_working as aw  # noqa: E402


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
        self.assertIn("Waiting on you now", html)
        self.assertIn("2 sessions", html)
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

    def test_the_simple_homes_needs_you_gets_a_live_row_for_a_waiting_session_and_none_without(self):
        today = dt.date(2026, 11, 10)
        none = status.home_section([], today, None, None, {})
        self.assertIn("Nothing needs you.", none)
        html = status.home_section([], today, None, None, {}, [row("a", "2026-11-10T09:00:00Z", thread="Acme Review, Pricing")], NOW)
        self.assertIn('data-live="a"', html)
        self.assertIn("Live</span> waiting on you for a question, 1 h", html)
        self.assertIn("1 question", html)
        self.assertNotIn("Nothing needs you.", html)
        self.assertNotIn("Birch", html)

    def test_an_empty_card_says_so(self):
        self.assertIn("No session is waiting on you.", status.waiting_card([], NOW))

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
        self.assertIn("No session is waiting on you.", bare)
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
const sent = [];
const ctx = { window: { webkit: { messageHandlers: { garrick: { postMessage: (m) => sent.push(m) } } } }, setInterval: () => 0, Date,
  document: { getElementById: (id) => (id === "wrows" ? box : null), createElement: (t) => new El(t), querySelector: () => null } };
vm.createContext(ctx);
vm.runInContext(js, ctx);
ctx.window.GarrickWaiting(data);
const rows = box.children.map((r) => ({ id: r.dataset.id, text: r.textContent, go: r.children.filter((c) => c.dataset && c.dataset.wgo).map((c) => c.dataset.wgo) }));
const target = { closest: () => ({ dataset: { wgo: "c" } }) };
box.listeners.click({ target });
process.stdout.write(JSON.stringify({ rows, sent }));
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
        self.assertEqual(["No session is waiting on you."], [r["text"] for r in self.run_js([])["rows"]])


if __name__ == "__main__":
    unittest.main()
