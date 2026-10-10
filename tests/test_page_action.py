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
        write(self.root / "System" / "garrick-flags.json", json.dumps({"page-actions": True}))
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

    def lock(self, until=None, pid=None, started=None):
        lock = self.jobs / "whats-open.lock"
        lock.mkdir(parents=True)
        if until is not None:
            (lock / "until").write_text("%d %d%s\n" % (until, pid or 4242, " %d" % started if started else ""))
        return lock

    def test_a_held_lock_refuses(self):
        import time
        self.lock(time.time() + 600, pid=os.getpid())                  # a job.py alive, within its time
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

    def test_job_py_decides_where_it_is_beside(self):
        import time
        lock = self.lock(time.time() - 60)
        seen = []

        class Job:
            def lock_state(self, path):
                seen.append(path)
                return {"pid": 4242}
        real = pa._JOB
        pa._JOB = Job()
        try:
            self.assertTrue(pa.lock_held("whats-open"))                 # its rule, not the clock's
            self.assertEqual([lock], seen)
            self.assertFalse(pa.lock_held("whats-open", now=time.time()))   # given a time, the clock's
            Job.lock_state = lambda self, path: 1 / 0
            self.assertFalse(pa.lock_held("whats-open"))                # a rule that fails: the clock's
        finally:
            pa._JOB = real

    @unittest.skipUnless(pa.job_py() is not None and hasattr(pa.job_py(), "holder"),
                         "job.py with holder(): a live job.py holds its lock past its time")
    def test_a_live_job_py_past_its_time_still_holds(self):
        import time
        started = pa.job_py().process_start(os.getpid())
        self.lock(time.time() - 60, pid=os.getpid(), started=started)   # the time ran on through a sleep
        with self.assertRaisesRegex(pa.Refused, "whats-open is already running"):
            pa.run_job({"verb": "run", "job": "whats-open"})
        self.assertEqual([], self.started)

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
        (self.jobs / "page-actions.log").mkdir(parents=True)          # a folder where the log should be
        done = self.run_script(json.dumps({"verb": "todo-done", "zone": "Work", "file": "Todo.md", "key": self.key("Invoice")}))
        self.assertEqual({"ok": True, "say": "Done: Acme Corp: Invoice for September"}, json.loads(done.stdout))


class TestFlag(ActionCase):
    """The page-actions flag is read at each request, not when the page was built."""

    def test_off_refuses_all_but_settings(self):
        write(self.root / "System" / "garrick-flags.json", json.dumps({"page-actions": False}))
        before = (self.work / "Todo.md").read_bytes()
        for req in ({"verb": "todo-done", "zone": "Work", "file": "Todo.md", "key": self.key("Invoice")},
                    {"verb": "todo-add", "zone": "Work", "text": "Book the room"},
                    {"verb": "park", "zone": "Work", "file": "Acme Review/Threads/Pricing/Pricing.md"},
                    {"verb": "run", "job": "whats-open"}):
            with self.assertRaisesRegex(pa.Refused, "preview feature, and they are off", msg=req):
                pa.act(self.root, req, today=TODAY)
        self.assertEqual(before, (self.work / "Todo.md").read_bytes())
        self.assertEqual("start", git(self.work, "log", "-1", "--format=%s").strip())
        self.assertEqual("Settings saved", self.act(verb="settings", launchers=["note"]))
        os.remove(self.root / "System" / "garrick-flags.json")                       # no flags at all: off
        with self.assertRaisesRegex(pa.Refused, "they are off"):
            self.act(verb="todo-add", zone="Work", text="Book the room")

    def test_cmux_verbs_need_the_flag_and_the_desk(self):
        real = pa.CMUX_EXTRA
        pa.CMUX_EXTRA = Path(self._tmp.name) / "no-cmux-extra"       # never the real desk
        try:
            write(self.root / "System" / "garrick-flags.json", json.dumps({}))
            with self.assertRaisesRegex(pa.Refused, "they are off"):
                pa.act(self.root, {"verb": "startup"})
            write(self.root / "System" / "garrick-flags.json", json.dumps({"page-actions": True}))
            for verb in ("open", "close", "startup", "shutdown"):
                with self.assertRaisesRegex(pa.Refused, "need the cmux extra", msg=verb):
                    pa.act(self.root, {"verb": verb, "zone": "Nowhere", "project": "Acme Review"})
        finally:
            pa.CMUX_EXTRA = real


class TestTogether(ActionCase):
    """Two requests at once: each click is its own process, so the zone's lock
    keeps one from reading the note while the other is still committing it."""

    def hook(self, body):
        hook = self.work / ".git" / "hooks" / "pre-commit"
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text("#!/bin/sh\n" + body)
        hook.chmod(0o755)

    def start(self):
        return subprocess.Popen([sys.executable, str(SCRIPT), "--workspace", str(self.root)], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                env=dict(os.environ, GARRICK_JOBS_DIR=str(self.jobs)))

    def test_two_quick_adds_both_land(self):
        mark = Path(self._tmp.name) / "in-the-hook"
        self.hook('touch "%s"\nsleep 1\n' % mark)
        first = self.start()
        first.stdin.write(json.dumps({"verb": "todo-add", "zone": "Work", "text": "Book the room"}))
        first.stdin.close()
        import time
        deadline = time.time() + 20
        while not mark.exists() and time.time() < deadline:      # the first is committing
            time.sleep(0.02)
        second = self.start()
        out2, _ = second.communicate(json.dumps({"verb": "todo-add", "zone": "Work", "text": "Call Dana"}), timeout=60)
        out1 = first.stdout.read()
        first.wait(timeout=60)
        first.stdout.close()
        first.stderr.close()
        self.assertEqual({"ok": True, "say": "Added to Inbox: Book the room"}, json.loads(out1))
        self.assertEqual({"ok": True, "say": "Added to Inbox: Call Dana"}, json.loads(out2))
        todo = (self.work / "Todo.md").read_text()
        self.assertIn("- [ ] Book the room\n", todo)
        self.assertIn("- [ ] Call Dana\n", todo)
        self.assertEqual("", git(self.work, "status", "--porcelain").strip())
        self.assertEqual(["Work: added to Inbox, Call Dana", "Work: added to Inbox, Book the room"],
                         git(self.work, "log", "-2", "--format=%s").splitlines())

    def test_an_edit_made_while_committing_is_kept(self):
        todo = self.work / "Todo.md"
        self.hook('printf "%%s\\n" "- [ ] Saved in Obsidian" >> "%s"\nexit 1\n' % todo)     # a save, then the wall check refuses
        with self.assertRaisesRegex(pa.Refused, "edited meanwhile, so it was left as it is"):
            self.act(verb="todo-add", zone="Work", text="Book the room")
        text = todo.read_text()
        self.assertIn("- [ ] Saved in Obsidian\n", text)
        self.assertIn("- [ ] Book the room\n", text)
        self.assertEqual("start", git(self.work, "log", "-1", "--format=%s").strip())

    def test_a_hook_that_hangs_is_stopped(self):
        import time
        self.hook("sleep 30\n")
        before = (self.work / "Todo.md").read_bytes()
        real, pa.GIT_TIMEOUT = pa.GIT_TIMEOUT, 1
        try:
            t0 = time.time()
            with self.assertRaisesRegex(pa.Refused, "longer than 1 s and was stopped"):
                self.act(verb="todo-done", zone="Work", file="Todo.md", key=self.key("Invoice"))
            self.assertLess(time.time() - t0, 15)
        finally:
            pa.GIT_TIMEOUT = real
        self.assertEqual(before, (self.work / "Todo.md").read_bytes())
        self.assertFalse((self.work / ".git" / "index.lock").exists())             # git took its lock away
        self.assertEqual("", git(self.work, "status", "--porcelain").strip())

    def test_a_held_zone_waits_then_refuses(self):
        real, pa.LOCK_WAIT = pa.LOCK_WAIT, 0.3
        try:
            with pa.zone_lock(self.work):              # a lock of its own, as another process's would be
                with self.assertRaisesRegex(pa.Refused, "another action in Work is still running; try again in a moment"):
                    self.act(verb="todo-add", zone="Work", text="Book the room")
        finally:
            pa.LOCK_WAIT = real
        self.assertEqual("start", git(self.work, "log", "-1", "--format=%s").strip())
        self.assertNotIn("Book the room", (self.work / "Todo.md").read_text())
        self.assertEqual("Added to Inbox: Book the room", self.act(verb="todo-add", zone="Work", text="Book the room"))

    def test_rekeys_from_two_processes_are_all_kept(self):
        code = ("import importlib.util, sys\n"
                "spec = importlib.util.spec_from_file_location('pa', %r)\n"
                "pa = importlib.util.module_from_spec(spec); spec.loader.exec_module(pa)\n"
                "for i in range(60):\n"
                "    pa.rekeys(sys.argv[1], 'Todo.md', ('%%016x' %% i, '%%016x' %% (i + 1000)))\n") % str(SCRIPT)
        procs = [subprocess.Popen([sys.executable, "-c", code, zone], env=dict(os.environ, GARRICK_JOBS_DIR=str(self.jobs)))
                 for zone in ("Work", "Personal")]
        for p in procs:
            p.wait(timeout=60)
        self.assertEqual(60, len(pa.rekeys("Work", "Todo.md")))
        self.assertEqual(60, len(pa.rekeys("Personal", "Todo.md")))


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

    def test_a_fault_still_answers_and_is_logged(self):
        import contextlib
        import io
        real, stdin = pa.act, sys.stdin

        def broken(ws, req, today=None):
            raise OSError("the disk went away")
        pa.act, sys.stdin = broken, io.StringIO(json.dumps({"verb": "todo-done", "zone": "Work"}))
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                code = pa.main(["--workspace", str(self.root)])
        finally:
            pa.act, sys.stdin = real, stdin
        self.assertEqual(1, code)
        self.assertEqual({"ok": False, "say": "that did not work: OSError: the disk went away"}, json.loads(buf.getvalue()))
        self.assertTrue((self.jobs / "page-actions.log").read_text().rstrip().endswith(
            'todo-done zone="Work"  ->  refused: that did not work: OSError: the disk went away'))


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
