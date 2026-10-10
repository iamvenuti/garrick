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
import os
import re
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
        self.jobs = Path(self._tmp.name).resolve() / "jobs"         # never the real jobs folder
        self._env = os.environ.get("GARRICK_JOBS_DIR")
        os.environ["GARRICK_JOBS_DIR"] = str(self.jobs)
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
        if self._env is None:
            os.environ.pop("GARRICK_JOBS_DIR", None)
        else:
            os.environ["GARRICK_JOBS_DIR"] = self._env
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


class TestRekey(ActionCase):
    """A second click on a row before the page rebuilds carries the key the
    line had when the page was built; the handler follows it to the line."""

    def test_a_second_date_finds_the_line(self):
        key = self.key("Invoice")
        self.act(verb="todo-date", zone="Work", file="Todo.md", key=key, date="2026-10-12")
        self.act(verb="todo-date", zone="Work", file="Todo.md", key=key, date="2026-10-14")
        self.assertIn("- [ ] Acme Corp: Invoice for September 📅 2026-10-14\n", (self.work / "Todo.md").read_text())
        self.act(verb="todo-date", zone="Work", file="Todo.md", key=key, date="2026-10-20")       # a third: the chain moves on
        self.assertIn("Invoice for September 📅 2026-10-20\n", (self.work / "Todo.md").read_text())

    def test_done_and_undo_after_a_date(self):
        key = self.key("Invoice")
        self.act(verb="todo-date", zone="Work", file="Todo.md", key=key, date="2026-10-12")
        self.assertEqual("Done: Acme Corp: Invoice for September", self.act(verb="todo-done", zone="Work", file="Todo.md", key=key))
        self.assertEqual("Reopened: Acme Corp: Invoice for September", self.act(verb="todo-undo", zone="Work", file="Todo.md", key=key))
        self.assertIn("- [ ] Acme Corp: Invoice for September 📅 2026-10-12\n", (self.work / "Todo.md").read_text())

    def test_only_within_the_hour_and_the_note(self):
        key = self.key("Invoice")
        self.act(verb="todo-date", zone="Work", file="Todo.md", key=key, date="2026-10-12")
        self.assertEqual({}, pa.rekeys("Personal", "Todo.md"))           # another note's map is its own
        store = self.jobs / "todo-rekeys.json"
        aged = {k: [v[0], v[1] - 2 * 3600] for k, v in json.loads(store.read_text()).items()}
        store.write_text(json.dumps(aged))
        with self.assertRaisesRegex(pa.Refused, "changed since the page was built"):
            self.act(verb="todo-date", zone="Work", file="Todo.md", key=key, date="2026-10-14")

    def test_a_line_dated_back_drops_out(self):
        key = self.key("Invoice")
        self.act(verb="todo-date", zone="Work", file="Todo.md", key=key, date="2026-10-12")
        self.act(verb="todo-date", zone="Work", file="Todo.md", key=key, date="-")
        self.assertEqual(key, self.key("Invoice"))
        self.assertNotIn(key, pa.rekeys("Work", "Todo.md"))


class TestAdd(ActionCase):
    """The Todo list's + button: one new line, committed, or nothing at all."""

    def add(self, **req):
        return self.act(verb="todo-add", zone="Work", **req)

    def test_a_line_with_no_thread_tops_the_inbox(self):
        self.assertEqual("Added to Inbox: Book the room | twice", self.add(text="  Book the room |  twice ", target="-", date="-"))
        todo = (self.work / "Todo.md").read_text()
        self.assertIn("## Inbox\n\n- [ ] Book the room | twice\n- [ ] [[Pricing]]", todo)
        self.assertEqual(("Work: added to Inbox, Book the room | twice", ""), self.last_commit())

    def test_a_thread_and_a_date(self):
        write(self.work / "Todo.md", (self.work / "Todo.md").read_text().replace("## Done", "## This week\n\n## Soon\n\n## Done"))
        git(self.work, "commit", "-qam", "sections")
        soon = (dt.date.today() + dt.timedelta(days=3)).isoformat()
        self.assertEqual("Added to This week: Call Dana", self.add(text="Call Dana", target="Acme Review/Pricing", date=soon))
        self.assertIn("## This week\n\n- [ ] [[Pricing]]: Call Dana 📅 %s\n" % soon, (self.work / "Todo.md").read_text())
        self.add(text="Chase the quote #waiting", target="Acme Review", date=soon)      # no Waiting on section: the Inbox
        self.assertIn("- [ ] [[Acme Review]]: Chase the quote #waiting ⏳ %s\n" % soon, (self.work / "Todo.md").read_text())

    def test_a_shared_name_is_linked_by_its_path(self):
        write(self.work / "Birch Entry" / "Threads" / "Pricing" / "Pricing.md", thread_note("Birch Entry", "Pricing"))
        self.add(text="Compare the two", target="Acme Review/Pricing")
        self.assertIn("- [ ] [[Acme Review/Threads/Pricing/Pricing|Pricing]]: Compare the two\n", (self.work / "Todo.md").read_text())

    def test_refusals_change_nothing(self):
        before = (self.work / "Todo.md").read_bytes()
        for req in ({"text": "", "target": "-"}, {"text": "x", "target": "../Personal"}, {"text": "x", "target": "Acme Review/Threads"},
                    {"text": "x", "target": "Acme Review/Nope"}, {"text": "x", "target": "No Such"}, {"text": "x", "date": "soon"},
                    {"text": "Acme Corp: Invoice for September"}, {"text": 7}, {"text": "x" * 1001}):
            with self.assertRaises(pa.Refused, msg=req):
                self.add(**req)
        self.assertEqual(before, (self.work / "Todo.md").read_bytes())
        self.assertEqual("start", git(self.work, "log", "-1", "--format=%s").strip())


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

    def test_a_parked_single_thread_project_passes_the_check(self):
        import check
        shutil.rmtree(self.work / "Acme Review" / "Threads")
        git(self.work, "add", "-A")
        git(self.work, "commit", "-q", "-m", "one thread")
        self.assertEqual("Acme Review is parked", self.act(verb="park", zone="Work", file="Acme Review/Acme Review.md"))
        self.assertIn("\nstatus: parked\n", (self.work / "Acme Review" / "Acme Review.md").read_text())
        self.assertEqual([], [f.message for f in check.run_checks(self.root) if f.severity == "error"])

    def test_only_threads(self):
        for rel in ("Todo.md", "Acme Review/Acme Review.md", "Acme Review/Sources/x.md"):
            with self.assertRaises(pa.Refused, msg=rel):
                self.act(verb="park", zone="Work", file=rel)


class TestRun(ActionCase):
    def plists(self):
        import plistlib
        folder = Path(self._tmp.name) / "LaunchAgents"
        folder.mkdir()
        with (folder / "com.garrick.whats-open.plist").open("wb") as f:
            plistlib.dump({"Label": "com.garrick.whats-open",
                           "ProgramArguments": ["/usr/bin/python3", "/w/System/jobs/job.py", "whats-open", "--", "python3", "x.py"]}, f)
        with (folder / "other.plist").open("wb") as f:
            plistlib.dump({"Label": "com.example.other", "ProgramArguments": ["/bin/echo", "whats-open"]}, f)
        return folder

    def test_run_starts_the_job_through_launchd(self):
        folder = self.plists()
        self.assertEqual("com.garrick.whats-open", pa.job_label("whats-open", folder))
        self.assertIsNone(pa.job_label("other", folder))
        started = []
        real, pa.kickstart = pa.kickstart, lambda label: started.append(label) or True
        try:
            self.assertEqual("whats-open is running now", pa.run_job({"verb": "run", "job": "whats-open"}, folder))
            self.assertEqual(["com.garrick.whats-open"], started)
            for bad in ("nothing-here", "../x", "", None):
                with self.assertRaises(pa.Refused, msg=bad):
                    pa.run_job({"verb": "run", "job": bad}, folder)
            pa.kickstart = lambda label: False
            with self.assertRaisesRegex(pa.Refused, "is it loaded"):
                pa.run_job({"verb": "run", "job": "whats-open"}, folder)
        finally:
            pa.kickstart = real
        self.assertEqual("", git(self.work, "status", "--porcelain").strip())      # running a job changes no note


class TestRunLock(ActionCase):
    """Run reads job.py's lock: a job still running is refused, a stale lock is not."""

    def setUp(self):
        super().setUp()
        self.started = []
        self._real = (pa.job_label, pa.kickstart)
        pa.job_label = lambda name, folder=None: "com.garrick." + name
        pa.kickstart = lambda label: self.started.append(label) or True

    def tearDown(self):
        pa.job_label, pa.kickstart = self._real
        super().tearDown()

    def lock(self, until=None):
        lock = self.jobs / "whats-open.lock"
        lock.mkdir(parents=True)
        if until is not None:
            (lock / "until").write_text("%d 4242\n" % until)
        return lock

    def test_a_held_lock_refuses(self):
        import time
        self.lock(time.time() + 600)
        with self.assertRaisesRegex(pa.Refused, "whats-open is already running"):
            pa.run_job({"verb": "run", "job": "whats-open"})
        self.assertEqual([], self.started)

    def test_a_stale_lock_runs(self):
        import time
        self.lock(time.time() - 60)
        self.assertEqual("whats-open is running now", pa.run_job({"verb": "run", "job": "whats-open"}))
        self.assertEqual(["com.garrick.whats-open"], self.started)

    def test_a_lock_with_no_record_goes_by_its_age(self):
        import time
        lock = self.lock()
        self.assertTrue(pa.lock_held("whats-open"))
        old = time.time() - pa.LOCK_HOLD - 60
        os.utime(lock, (old, old))
        self.assertFalse(pa.lock_held("whats-open"))

    def test_the_lock_is_where_job_py_takes_it(self):
        sys.path.insert(0, str(REPO / "extras" / "jobs"))
        try:
            import job
            self.jobs.mkdir()
            self.assertTrue(job.take_lock(self.jobs / "whats-open.lock", 600))
            self.assertTrue(pa.lock_held("whats-open"))
            job.release(self.jobs / "whats-open.lock")
            self.assertFalse(pa.lock_held("whats-open"))
        finally:
            sys.path.remove(str(REPO / "extras" / "jobs"))


class TestSettings(ActionCase):
    """Settings › Opening a thread, in one file every viewer reads."""

    def path(self):
        return self.root / "System" / "generated" / "status-settings.json"

    def test_saved_whole(self):
        self.assertEqual("Settings saved", self.act(verb="settings", launchers=["note", "cmux", "claude"], default="claude"))
        self.assertEqual({"launchers": {"note": True, "finder": False, "cmux": True, "codex": False, "claude": True},
                          "default": "claude"}, json.loads(self.path().read_text()))
        self.act(verb="settings", launchers=[])
        self.assertEqual("note", json.loads(self.path().read_text())["default"])
        self.assertEqual("", git(self.work, "status", "--porcelain").strip())      # nothing to commit

    def test_refused_names(self):
        for req in ({"launchers": ["note", "terminal"]}, {"launchers": "note"}, {"launchers": ["cmux", "cmux"]},
                    {"launchers": ["cmux"], "default": "codex"}, {"launchers": ["cmux"], "default": "vim"}, {"launchers": [1]}):
            with self.assertRaises(pa.Refused, msg=req):
                self.act(verb="settings", **req)
        self.assertFalse(self.path().exists())

    def test_the_launchers_are_the_pages(self):
        spec = importlib.util.spec_from_file_location("garrick_status_for_settings", REPO / "extras" / "status" / "status.py")
        status = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(status)
        self.assertEqual(("note",) + tuple(k for k, _, _, _ in status.LAUNCHERS), pa.LAUNCHERS)


class TestAudit(ActionCase):
    """page-actions.log: one line per request, with only the fields a verb reads."""

    def run_script(self, request):
        return subprocess.run([sys.executable, str(SCRIPT), "--workspace", str(self.root)], input=request,
                              capture_output=True, text=True)

    def lines(self):
        return (self.jobs / "page-actions.log").read_text().splitlines()

    def test_one_line_each_done_or_refused(self):
        self.run_script(json.dumps({"verb": "todo-done", "zone": "Work", "file": "Todo.md", "key": self.key("Invoice")}))
        self.run_script(json.dumps({"verb": "todo-add", "zone": "Work", "text": "Book the room " + "x" * 200,
                                    "password": "hunter2", "session": "abc"}))
        self.run_script("not json")
        lines = self.lines()
        self.assertEqual(3, len(lines))
        self.assertRegex(lines[0], r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d  todo-done zone=\"Work\" file=\"Todo.md\" key=\"[0-9a-f]{16}\"  ->  ok: Done: Acme Corp: Invoice for September$")
        self.assertIn('todo-add zone="Work" text="Book the room xxx', lines[1])
        self.assertIn("…\"  ->  ok: Added to Inbox", lines[1])
        self.assertLess(len(lines[1]), 320)
        self.assertNotIn("hunter2", "\n".join(lines))
        self.assertNotIn("abc", lines[1])
        self.assertTrue(lines[2].endswith("?  ->  refused: not a request"))

    def test_a_log_that_cannot_be_written_stops_nothing(self):
        self.jobs.parent.mkdir(parents=True, exist_ok=True)
        self.jobs.write_text("a file where the folder should be")
        done = self.run_script(json.dumps({"verb": "todo-done", "zone": "Work", "file": "Todo.md", "key": self.key("Invoice")}))
        self.assertEqual({"ok": True, "say": "Done: Acme Corp: Invoice for September"}, json.loads(done.stdout))


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


class VerbsTest(unittest.TestCase):
    """The page may only ask for the verbs docs/extras/status-page.md lists:
    a verb added to page_action.py fails here until it is documented, and so
    reviewed."""

    def test_the_verbs_are_the_documented_list(self):
        text = (REPO / "docs" / "extras" / "status-page.md").read_text(encoding="utf-8")
        section = text.split("## What the actions keep", 1)[1].split("\n## ", 1)[0]
        documented = re.findall(r"^\| `([a-z-]+)` \|", section, re.M)
        self.assertEqual(len(documented), len(set(documented)), documented)
        accepted = list(pa.VERBS) + list(pa.CMUX_VERBS)
        self.assertEqual(len(accepted), len(set(accepted)), accepted)
        self.assertEqual(sorted(accepted), sorted(documented))
