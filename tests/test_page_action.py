"""The status page's actions, extras/status/page_action.py, against a fictional workspace.

    python3 -m unittest discover -s tests

Each action changes one line or one status field and commits it in the zone's
repository; a stale line, a path outside the live notes, or a commit the wall
check refuses changes nothing.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

from fixtures import build_workspace, thread_note, write  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "extras" / "status" / "page_action.py"
TODAY = dt.date(2026, 10, 5)


def _load():
    spec = importlib.util.spec_from_file_location("garrick_page_action", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pa = _load()
tl = pa.todo_lines()


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd)] + list(args), capture_output=True, text=True, check=True).stdout


class ActionCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve() / "Workspace"
        build_workspace(self.root)
        self.work = self.root / "Zones" / "Work"
        shutil.rmtree(self.work / ".git")                 # a real repository for Work, with no hook
        git(self.work, "init", "-q")
        git(self.work, "config", "user.name", "Sam Rivera")
        git(self.work, "config", "user.email", "sam@example.com")
        write(self.work / "Todo.md", "# Work: open actions\n\n## Inbox\n\n"
              "- [ ] [[Pricing]]: Send the revised terms 📅 2026-10-09\n- [ ] Acme Corp: Invoice for September\n\n## Done\n")
        self.thread = self.work / "Acme Review" / "Threads" / "Pricing" / "Pricing.md"
        write(self.thread, thread_note("Acme Review", "Pricing") + "\n---\n\n<Dated entries, newest first. Never edit an old one.>\n\n"
              "**1 March 2026.** Started.\n")
        git(self.work, "add", "-A")
        git(self.work, "commit", "-q", "-m", "start")

    def tearDown(self):
        self._tmp.cleanup()

    def key(self, text):
        return next(t["key"] for t in tl.tasks(str(self.work)) if text in t["text"])

    def act(self, **req):
        return pa.act(self.root, req, today=TODAY)

    def last_commit(self):
        return git(self.work, "log", "-1", "--format=%s").strip(), git(self.work, "status", "--porcelain").strip()


class TestTodo(ActionCase):
    def test_tick_and_reopen(self):
        say = self.act(verb="todo-done", zone="Work", file="Todo.md", key=self.key("Send the revised"))
        self.assertEqual("Done: Send the revised terms", say)
        todo = (self.work / "Todo.md").read_text()
        self.assertRegex(todo, r"- \[x\] \[\[Pricing\]\]: Send the revised terms 📅 2026-10-09 ✅ \d{4}-\d\d-\d\d")
        self.assertEqual(("Work: done, Send the revised terms", ""), self.last_commit())
        ticked = tl.done_on(str(self.work), dt.date.today())[0]["key"]
        self.assertEqual("Reopened: Send the revised terms", self.act(verb="todo-undo", zone="Work", file="Todo.md", key=ticked))
        self.assertIn("- [ ] [[Pricing]]: Send the revised terms 📅 2026-10-09\n", (self.work / "Todo.md").read_text())

    def test_date_set_and_cleared(self):
        self.act(verb="todo-date", zone="Work", file="Todo.md", key=self.key("Invoice"), date="2026-10-12")
        self.assertIn("- [ ] Acme Corp: Invoice for September 📅 2026-10-12\n", (self.work / "Todo.md").read_text())
        self.assertEqual("Work: Mon 12 Oct, Acme Corp: Invoice for September", self.last_commit()[0])
        self.act(verb="todo-date", zone="Work", file="Todo.md", key=self.key("Invoice"), date="-")
        self.assertIn("- [ ] Acme Corp: Invoice for September\n", (self.work / "Todo.md").read_text())

    def test_a_stale_line_is_refused(self):
        key = self.key("Send the revised")
        before = (self.work / "Todo.md").read_text()
        write(self.work / "Todo.md", before.replace("revised terms", "final terms"))
        with self.assertRaisesRegex(pa.Refused, "changed since the page was built"):
            self.act(verb="todo-done", zone="Work", file="Todo.md", key=key)

    def test_only_live_notes_in_a_zone(self):
        write(self.work / "archive" / "Old.md", "- [ ] Old thing\n")
        for zone, rel in (("Work", "../Personal/Todo.md"), ("Work", "archive/Old.md"), ("Work", "Missing.md"),
                          ("../Zones/Work", "Todo.md"), ("_template", "Todo.md"), ("Work", "/etc/passwd")):
            with self.assertRaises(pa.Refused, msg=(zone, rel)):
                self.act(verb="todo-done", zone=zone, file=rel, key="0" * 16)
        for bad in ({"verb": "rm"}, ["todo-done"], {"verb": "todo-done", "zone": "Work", "file": "Todo.md", "key": "x"},
                    {"verb": "todo-date", "zone": "Work", "file": "Todo.md", "key": self.key("Invoice"), "date": "soon"}):
            with self.assertRaises(pa.Refused, msg=bad):
                pa.act(self.root, bad, today=TODAY)

    def test_a_refused_commit_changes_nothing(self):
        personal = self.root / "Zones" / "Personal"       # the fixture's stand-in repository: every commit fails
        write(personal / "Todo.md", "# Personal\n\n## Inbox\n\n- [ ] Renew the insurance\n\n## Done\n")
        before = (personal / "Todo.md").read_bytes()
        key = next(t["key"] for t in tl.tasks(str(personal)))
        with self.assertRaisesRegex(pa.Refused, "not committed, so nothing changed"):
            self.act(verb="todo-done", zone="Personal", file="Todo.md", key=key)
        self.assertEqual(before, (personal / "Todo.md").read_bytes())


class TestPark(ActionCase):
    def test_park_and_wake_as_the_skill_does(self):
        rel = "Acme Review/Threads/Pricing/Pricing.md"
        self.assertEqual("Acme Review, Pricing is parked", self.act(verb="park", zone="Work", file=rel))
        text = self.thread.read_text()
        self.assertIn("\nstatus: parked\n", text)
        self.assertIn("\nupdated: 2026-10-05\n", text)
        self.assertIn("<Dated entries, newest first. Never edit an old one.>\n\n**5 October 2026.** Parked.\n\n**1 March 2026.** Started.", text)
        self.assertIn("### Resume here\n\n**Where it stands, 1 March 2026.** Drafting.", text)     # left as it was
        self.assertEqual(("Acme Review, Pricing: parked", ""), self.last_commit())
        self.assertEqual("Acme Review, Pricing is awake again", self.act(verb="wake", zone="Work", file=rel))
        self.assertIn("\nstatus: active\n", self.thread.read_text())
        self.assertEqual("Acme Review, Pricing: woken", self.last_commit()[0])
        self.assertEqual("Pricing is already active", self.act(verb="wake", zone="Work", file=rel))

    def test_only_threads(self):
        for rel in ("Todo.md", "Acme Review/Acme Review.md", "Acme Review/Sources/x.md"):
            with self.assertRaises(pa.Refused, msg=rel):
                self.act(verb="park", zone="Work", file=rel)


class TestScript(ActionCase):
    def run_script(self, request, ws=None):
        return subprocess.run([sys.executable, str(SCRIPT), "--workspace", str(ws or self.root)], input=request,
                              capture_output=True, text=True)

    def test_one_line_of_json(self):
        done = self.run_script(json.dumps({"verb": "todo-done", "zone": "Work", "file": "Todo.md", "key": self.key("Invoice")}))
        self.assertEqual(0, done.returncode, done.stderr)
        self.assertEqual({"ok": True, "say": "Done: Acme Corp: Invoice for September"}, json.loads(done.stdout))
        refused = self.run_script("not json")
        self.assertEqual(1, refused.returncode)
        self.assertEqual({"ok": False, "say": "not a request"}, json.loads(refused.stdout))
        elsewhere = self.run_script("{}", ws=self.root.parent)
        self.assertEqual("not a Garrick workspace", json.loads(elsewhere.stdout)["say"])


if __name__ == "__main__":
    unittest.main()
