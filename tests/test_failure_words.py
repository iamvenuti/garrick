"""#511: a failure in plain words. The table in page_action.py (FAILURES), the reply that carries a row of it, and the
rule that "saved" is the operation record's word. The page and the notification line read the same table."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

import test_page_action as tpa  # noqa: E402

pa = tpa.pa
REPO = tpa.REPO
_spec = importlib.util.spec_from_file_location("garrick_operations_fw", str(REPO / "template" / "System" / "tools" / "operations.py"))
ops = importlib.util.module_from_spec(_spec)
sys.modules["garrick_operations_fw"] = ops
_spec.loader.exec_module(ops)

# Words that would make a card read as a success; "not saved" and "no change" are the only ways they may appear.
SUCCESS = re.compile(r"(?i)\b(saved|done|committed|parked|woke|ticked|reopened|made)\b")
# What only a person who built Garrick can read: a command, a path, a stack trace, a flag.
RAW = re.compile(r"(?i)(/\w|\.py\b|\bgit\b|traceback|\bexit \d|--\w)")
WALL = ops.WALL_REFUSAL


class TestTheTable(unittest.TestCase):
    def test_each_row_has_one_sentence_one_button_and_ends_on_other(self):
        codes = [row[0] for row in pa.FAILURES]
        self.assertEqual(len(codes), len(set(codes)))
        self.assertEqual("other", codes[-1])
        for code, say, button, act, hint in pa.FAILURES:
            if code == "wall":
                self.assertEqual(("", "", "", ""), (say, button, act, hint))      # the rules' sentence stands alone
                continue
            self.assertTrue(say.endswith("."), code)
            self.assertIn(act, ("why", "retry", "refresh"), code)                # buttons the page already has
            self.assertTrue(button, code)
            self.assertNotRegex(say + " " + hint, RAW, code)                      # no command, path or trace

    def test_the_list_in_the_docs_names_every_sentence(self):
        docs = (REPO / "docs" / "extras" / "status-page.md").read_text(encoding="utf-8")
        section = docs[docs.index("## When something fails"):docs.index("## What the actions keep")]
        for code, say, *_ in pa.FAILURES:
            if say:
                self.assertIn(say, section, code)

    def test_a_failure_the_table_does_not_name_is_the_fallback(self):
        self.assertEqual("This did not finish.", pa.plain_failure("no-such-code")["say"])
        self.assertEqual("other", pa.plain_failure("no-such-code")["code"])
        self.assertEqual("other", pa.failure_code({"ok": False, "say": "x", "outcome": "weird"}, {"verb": "park"}))
        self.assertEqual("other", pa.failure_code({"ok": False, "say": "x"}, {"verb": "park"}))

    def test_each_failure_code_is_picked_for_its_reply(self):
        for outcome in ("refused", "crashed", "unknown", "lost"):
            self.assertEqual(outcome, pa.failure_code({"ok": False, "say": "x", "outcome": outcome}, {"verb": "park"}))
        self.assertEqual("handoff", pa.failure_code({"ok": False, "say": "Claude did not open"}, {"verb": "continue"}))
        self.assertEqual("wall", pa.failure_code({"ok": False, "say": WALL, "outcome": "refused"}, {"verb": "park"}))

    def test_a_row_is_the_reply_with_its_hint_and_never_the_tools_text(self):
        for code in pa.FAILURE_CODES:
            row = pa.plain_failure(code, WALL if code == "wall" else "")
            self.assertEqual({"code", "say", "next", "band"}, set(row))
            self.assertTrue(row["band"].startswith(row["say"]))
        self.assertEqual(WALL, pa.plain_failure("wall", WALL)["band"])         # said alone, word for word

    def test_no_failure_reads_as_saved(self):
        for code in pa.FAILURE_CODES:
            text = pa.plain_failure(code)["band"]
            for m in SUCCESS.finditer(text):
                self.assertRegex(text[:m.start()], r"(?i)\b(not|no)\s+$", "%s: %s" % (code, text))


class TestTheReply(tpa.ActionCase):
    def run_main(self, request):
        env = dict(os.environ, GARRICK_JOBS_DIR=str(self.jobs))
        r = subprocess.run([sys.executable, str(tpa.SCRIPT), "--workspace", str(self.root)], input=json.dumps(request),
                           capture_output=True, text=True, env=env)
        return json.loads(r.stdout)

    def test_a_stale_line_is_refused_and_says_so_plainly(self):
        out = self.run_main({"verb": "todo-done", "zone": "Work", "file": "Todo.md", "key": "0" * 16, "op": "a19f3c80"})
        self.assertFalse(out["ok"])
        self.assertEqual("refused", out["outcome"])
        self.assertEqual("This was not saved: the check refused it.", out["plain"]["say"])
        self.assertEqual("Show why", out["plain"]["next"])
        self.assertIn("changed since the page was built", out["say"])          # the tool's text stays, for Details
        self.assertNotIn("changed since", out["plain"]["band"])

    def test_a_reply_with_no_record_of_it_is_left_as_it_was(self):
        out = self.run_main({"verb": "frobnicate"})
        self.assertEqual({"ok": False, "say": "unknown action"}, out)           # the app says "This did not finish." for it

    def test_an_outcome_the_table_does_not_name_is_the_fallback(self):
        out = pa.with_plain({"ok": False, "say": "x", "outcome": "weird"}, {"verb": "park"}, ops)
        self.assertEqual(("other", "This did not finish."), (out["plain"]["code"], out["plain"]["say"]))

    def test_a_layout_look_keeps_no_record_and_is_not_called_unconfirmed(self):
        # The layout dialog's plan (#604) writes nothing and keeps no record on purpose: it is not "could not confirm".
        look = {"verb": "layout", "zone": "Work", "project": "Acme", "check": True, "plan": True}
        self.assertTrue(pa.only_looks(look))
        out = pa.with_plain({"ok": True, "say": "The plan.", "plan": {"moves": []}}, look, ops)
        self.assertNotIn("plain", out)
        real = pa.with_plain({"ok": True, "say": "Moved."}, dict(look, check=False), ops)
        if "layout" in ops.OPS:                                            # the real run is one the record keeps
            self.assertEqual("unrecorded", real["plain"]["code"])

    def test_a_save_is_saved_when_the_record_says_so_and_carries_no_plain_words(self):
        out = self.run_main({"verb": "todo-done", "zone": "Work", "file": "Todo.md", "key": self.key("Invoice"), "op": "b19f3c80"})
        self.assertTrue(out["ok"])
        self.assertEqual("saved", out["outcome"])
        self.assertNotIn("plain", out)

    def test_a_save_the_record_cannot_hold_never_says_saved(self):
        (self.jobs / "operations.jsonl").mkdir(parents=True)               # the record cannot be written; the action can
        out = self.run_main({"verb": "todo-done", "zone": "Work", "file": "Todo.md", "key": self.key("Invoice"), "op": "c19f3c80"})
        self.assertTrue(out["ok"])
        self.assertNotIn("outcome", out)
        self.assertEqual("unrecorded", out["plain"]["code"])
        self.assertNotRegex(out["plain"]["band"], r"(?i)\bsaved\b")

SWIFT = REPO / "extras" / "status" / "app" / "Garrick.swift"


@unittest.skipUnless(sys.platform == "darwin" and shutil.which("xcrun"), "needs the Swift compiler")
class TestTheNotificationLine(unittest.TestCase):
    """The Mac app's toast and notification line say the row page_action.py sent, never the tool's text, and never
    "saved" for a reply the record did not hold. bandLine() itself, compiled on its own and run on real replies."""

    def test_the_line_is_the_plain_sentence_and_the_tools_text_is_the_detail(self):
        swift = SWIFT.read_text(encoding="utf-8")
        fn = swift[swift.index("\tfunc bandLine("):swift.index("\t// Only a folder inside this workspace")]
        fall = re.search(r'^let didNotFinish = .*$', swift, re.M).group(0)
        work = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, work, True)
        (work / "main.swift").write_text(
            "import Foundation\n" + fall + "\n" + "struct T {\n" + fn + "\n}\n"
            "let raw = CommandLine.arguments[1]\n"
            "let said = (try! JSONSerialization.jsonObject(with: raw.data(using: .utf8)!)) as! [String: Any]\n"
            "let r = T().bandLine(said)\nprint(r.sentence + \"|\" + r.detail)\n", encoding="utf-8")
        built = subprocess.run(["xcrun", "swiftc", "-o", str(work / "run"), str(work / "main.swift")], capture_output=True, text=True)
        self.assertEqual(0, built.returncode, built.stderr)

        def line(reply):
            done = subprocess.run([str(work / "run"), json.dumps(reply)], capture_output=True, text=True)
            self.assertEqual(0, done.returncode, done.stderr)
            return done.stdout.rstrip("\n").split("|", 1)

        tool = "Not done. Commit refused in /Users/sam/Zones/Work: 2 errors; commit again once they are fixed."
        for outcome in ("refused", "crashed", "unknown", "lost"):
            row = pa.plain_failure(outcome)
            sentence, detail = line({"ok": False, "say": tool, "outcome": outcome, "plain": row})
            self.assertEqual(row["band"], sentence)
            self.assertEqual(tool, detail)                                            # nothing dropped
            self.assertNotRegex(sentence, RAW)
        # a failure with no row says the fallback, never the tool's text
        self.assertEqual(["This did not finish.", "Cannot run /usr/bin/python3"], line({"ok": False, "say": "Cannot run /usr/bin/python3"}))
        # the rules' sentence is said alone
        wall = pa.plain_failure("wall", WALL)
        self.assertEqual([WALL, ""], line({"ok": False, "say": WALL, "outcome": "refused", "plain": wall}))
        # a reply that is a question, or under way, is not a failure
        self.assertEqual(["Asked.", ""], line({"ok": False, "say": "Asked.", "state": "asked", "again": "a19f3c80"}))
        self.assertEqual(["Parking it\u2026", ""], line({"ok": True, "say": "Parking it\u2026", "state": "running"}))
        # saved is the record's word: a reply with no outcome for an action it keeps says it could not confirm
        sentence, _ = line({"ok": True, "say": "Parked Birch Entry", "plain": pa.plain_failure("unrecorded")})
        self.assertNotRegex(sentence, r"(?i)\b(saved|parked|done)\b")
        # and one the record held keeps the handler's own words
        self.assertEqual(["Parked Birch Entry", ""], line({"ok": True, "say": "Parked Birch Entry", "outcome": "saved", "state": "completed"}))

    def test_the_toast_keeps_the_detail_as_its_title_and_the_notification_the_sentence_alone(self):
        swift = SWIFT.read_text(encoding="utf-8")
        toast = swift[swift.index("func toast("):swift.index("func notify(")]
        self.assertIn("t.title=a[1]", toast)
        self.assertIn("!window.isVisible || !NSApp.isActive { notify(text) }", toast)
        acted = swift[swift.index("\tfunc acted("):swift.index("\t// What the toast and the notification line say")]
        self.assertIn("toast(line.sentence, detail: line.detail)", acted)
        self.assertNotIn('toast(said["say"]', acted)


if __name__ == "__main__":
    unittest.main()
