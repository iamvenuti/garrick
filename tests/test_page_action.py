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
from unittest import mock

sys.dont_write_bytecode = True

import fixtures  # noqa: E402
from fixtures import build_workspace, project_hub, thread_note, write  # noqa: E402

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


def plain(reply):
    """A reply as 0.26.0 made it: what the record adds (operations.py) taken off."""
    return {k: v for k, v in reply.items() if k not in ("op", "state", "outcome")}


class ActionCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve() / "Workspace"
        self.jobs = Path(self._tmp.name).resolve() / "jobs"         # never the real jobs folder
        self._env = os.environ.get("GARRICK_JOBS_DIR")
        os.environ["GARRICK_JOBS_DIR"] = str(self.jobs)
        build_workspace(self.root)
        # the tools park and the manage verbs run: the scripts themselves, as
        # an installed workspace has them, and the templates folder they look
        # for to know they are in one. Nothing here uses the thread template.
        (self.root / "System" / "templates").mkdir(parents=True, exist_ok=True)
        (self.root / "System" / "tools").mkdir(parents=True, exist_ok=True)
        for tool in ("scaffold.py", "garrick_lib.py", "operations.py"):
            shutil.copy2(REPO / "template" / "System" / "tools" / tool, self.root / "System" / "tools" / tool)
        self.work = self.root / "Zones" / "Work"
        shutil.rmtree(self.work / ".git")                 # a real repository for Work, with no hook
        git(self.work, "init", "-q")
        git(self.work, "config", "user.name", "Sam Rivera")
        git(self.work, "config", "user.email", "sam@example.com")
        # Every commit then starts `git maintenance run --auto`, which takes
        # .git/objects/maintenance.lock once index.lock is gone: a commit the
        # test did not wait for would still be writing while tearDown deletes.
        git(self.work, "config", "maintenance.auto", "false")
        git(self.work, "config", "gc.auto", "0")
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


class TestBatch(ActionCase):
    """#107: the page sends the ticks made within a few seconds of each other as
    one request, with `keys`: one lock, one edit, one commit."""

    def setUp(self):
        super().setUp()
        write(self.work / "Todo.md", "# Work: open actions\n\n## Inbox\n\n"
              "- [ ] [[Pricing]]: Send the revised terms 📅 2026-10-09\n- [ ] Acme Corp: Invoice for September\n"
              "- [ ] Book the room for Birch & Co\n\n## Done\n")
        git(self.work, "commit", "-qam", "three lines")

    def keys(self, *texts):
        return [self.key(t) for t in texts]

    def test_three_ticks_are_one_commit(self):
        keys = self.keys("Send the revised", "Invoice", "Book the room")
        self.assertEqual("Saved 3", self.act(verb="todo-done", zone="Work", file="Todo.md", keys=keys))
        todo = (self.work / "Todo.md").read_text()
        self.assertEqual(3, len(re.findall(r"^- \[x\] .* ✅ \d{4}-\d\d-\d\d$", todo, re.M)))
        self.assertEqual(("Work: done, 3 actions", ""), self.last_commit())
        self.assertEqual(3, int(git(self.work, "rev-list", "--count", "HEAD")))          # start, three lines, the batch
        ticked = [t["key"] for t in tl.done_on(str(self.work), dt.date.today())]
        self.assertEqual(sorted(keys), sorted(ticked))                                   # an undo finds them by the same keys
        self.assertEqual("Saved 2", self.act(verb="todo-undo", zone="Work", file="Todo.md", keys=keys[:2]))
        self.assertEqual(("Work: reopened, 2 actions", ""), self.last_commit())
        self.assertIn("- [ ] Acme Corp: Invoice for September\n", (self.work / "Todo.md").read_text())

    def test_a_batch_of_one_says_what_one_tick_says(self):
        say = self.act(verb="todo-done", zone="Work", file="Todo.md", keys=self.keys("Invoice"))
        self.assertEqual("Done: Acme Corp: Invoice for September", say)
        self.assertEqual(("Work: done, Acme Corp: Invoice for September", ""), self.last_commit())

    def test_a_line_that_moved_refuses_the_whole_batch(self):
        keys = self.keys("Send the revised", "Invoice")
        write(self.work / "Todo.md", (self.work / "Todo.md").read_text().replace("Invoice for", "Invoices for"))
        git(self.work, "commit", "-qam", "edited in Obsidian")
        before = (self.work / "Todo.md").read_bytes()
        with self.assertRaisesRegex(pa.Refused, "changed since the page was built"):
            self.act(verb="todo-done", zone="Work", file="Todo.md", keys=keys)
        self.assertEqual(before, (self.work / "Todo.md").read_bytes())
        self.assertEqual("edited in Obsidian", self.last_commit()[0])

    def test_a_line_gone_between_the_precheck_and_its_edit_puts_back_the_ones_before_it(self):
        keys = self.keys("Send the revised", "Invoice")
        before = (self.work / "Todo.md").read_bytes()
        real = tl.done
        def done(zone, rel, k, today=None):
            if k == keys[1]:
                raise tl.NotFound
            return real(zone, rel, k, today)
        with mock.patch.object(pa, "todo_lines", return_value=mock.Mock(wraps=tl, done=done, NotFound=tl.NotFound)):
            with self.assertRaisesRegex(pa.Refused, "changed since the page was built"):
                self.act(verb="todo-done", zone="Work", file="Todo.md", keys=keys)
        self.assertEqual(before, (self.work / "Todo.md").read_bytes())
        self.assertEqual("three lines", self.last_commit()[0])

    def test_what_a_batch_may_carry(self):
        key = self.key("Invoice")
        before = (self.work / "Todo.md").read_bytes()
        for bad in ({"keys": []}, {"keys": key}, {"keys": [key, "x"]}, {"keys": [key], "key": key},
                    {"keys": [key] * 2 + ["%016x" % i for i in range(pa.KEYS_MAX)]}):
            with self.assertRaises(pa.Refused, msg=bad):
                self.act(verb="todo-done", zone="Work", file="Todo.md", **bad)
        with self.assertRaisesRegex(pa.Refused, "takes no keys field"):          # only a tick or an untick batches
            self.act(verb="todo-date", zone="Work", file="Todo.md", keys=[key], date="2026-10-12")
        self.assertEqual(before, (self.work / "Todo.md").read_bytes())
        self.assertEqual("Done: Acme Corp: Invoice for September",
                         self.act(verb="todo-done", zone="Work", file="Todo.md", keys=[key, key]))   # the same line twice is once


class TestSaid(ActionCase):
    """#107: what a Todo verb says it did is the line's words, with no Markdown
    link and no longer than SAID_TEXT; the commit keeps the line whole."""

    SOURCE = "[260917-acme-pricing-call](obsidian://open?vault=Workspace&file=Wikis%2FMeetings%2Fwiki%2Fsources%2F260917)"

    def test_the_link_back_to_a_meeting_is_left_to_the_note(self):
        write(self.work / "Todo.md", "# Work\n\n## Inbox\n\n- [ ] Send Birch & Co the [draft terms](https://example.com/terms) · %s\n\n"
              "## This week\n\n## Done\n" % self.SOURCE)
        git(self.work, "commit", "-qam", "a line from a meeting")
        key = self.key("Send Birch")
        for verb, extra in (("todo-done", {}), ("todo-undo", {}), ("todo-date", {"date": "2026-10-07"})):
            say = self.act(verb=verb, zone="Work", file="Todo.md", key=key, **extra)
            self.assertNotIn("](", say, verb)
            self.assertNotIn("obsidian://", say, verb)
            self.assertNotIn("260917", say, verb)
            self.assertIn("Send Birch & Co the draft terms", say, verb)
            self.assertIn("obsidian://", self.last_commit()[0], verb)                   # the commit says it all
        self.assertEqual("Added to Inbox: Read the brief before the call",
                         self.act(verb="todo-add", zone="Work", text="Read [the brief](https://example.com/b) before the call",
                                  target="-", date="-"))

    def test_a_long_line_is_cut_to_sixty(self):
        text = "Draft the reply to Acme Corp on the revised pallet terms, the volumes and the March start date"
        write(self.work / "Todo.md", "# Work\n\n## Inbox\n\n- [ ] %s\n\n## Done\n" % text)
        git(self.work, "commit", "-qam", "a long line")
        say = self.act(verb="todo-done", zone="Work", file="Todo.md", key=self.key("Draft the reply"))
        self.assertEqual(60, pa.SAID_TEXT)
        said = say[len("Done: "):]
        self.assertEqual(60, len(said))
        self.assertTrue(said.endswith("…"))
        self.assertTrue(text.startswith(said[:-1]))
        self.assertEqual("Work: done, " + text, self.last_commit()[0])


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

    def test_a_repeat_is_refused_however_it_is_worded(self):
        """#92: a request that comes a second time is written again from the
        words, not copied, so the comparison cannot be the whole line. The
        same thing to do on the same thread is the same line, whatever date
        it carries and however it is spaced or capitalised; another thread,
        or another tag, is another action."""
        soon = (dt.date.today() + dt.timedelta(days=3)).isoformat()
        self.assertEqual("Added to Inbox: Call Dana about the quote",
                         self.add(text="Call Dana about the quote", target="Acme Review/Pricing"))
        for req in ({"text": "Call Dana about the quote", "target": "Acme Review/Pricing"},
                    {"text": "call Dana  about the quote.", "target": "Acme Review/Pricing"},
                    {"text": "Call Dana about the quote", "target": "Acme Review/Pricing", "date": soon}):
            with self.assertRaisesRegex(pa.Refused, "already in the list", msg=req):
                self.add(**req)
        self.assertEqual(1, (self.work / "Todo.md").read_text().count("Dana about the quote"))
        self.assertEqual("Work: added to Inbox, Call Dana about the quote", self.last_commit()[0])
        self.add(text="Call Dana about the quote", target="Acme Review")                    # another thread
        self.add(text="Call Dana about the quote #waiting", target="Acme Review/Pricing")   # another tag
        self.assertEqual(3, (self.work / "Todo.md").read_text().count("Dana about the quote"))

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
        with self.assertRaisesRegex(pa.Refused, "^Pricing is active already, so nothing was changed$"):
            self.act(verb="wake", zone="Work", file=rel)

    def test_a_second_park_says_so_instead_of_writing_another_entry(self):
        """The precheck operations.py declares for park and wake: the note's
        status as it stands now, read under the zone's lock."""
        rel = "Acme Review/Threads/Pricing/Pricing.md"
        self.act(verb="park", zone="Work", file=rel)
        parked, commit = self.thread.read_bytes(), self.last_commit()
        with self.assertRaisesRegex(pa.Refused, "^Pricing was set aside already, so nothing was changed$"):
            self.act(verb="park", zone="Work", file=rel)
        self.assertEqual(parked, self.thread.read_bytes())               # no second dated entry
        self.assertEqual(commit, self.last_commit())                     # and no second commit
        self.assertEqual(1, self.thread.read_text().count("Parked."))

    def test_a_second_park_of_a_project_by_name_says_so_too(self):
        self.act(verb="park", zone="Work", project="Acme Review")
        with self.assertRaisesRegex(pa.Refused, "^Acme Review was set aside already"):
            self.act(verb="park", zone="Work", project="Acme Review")

    def test_a_field_park_does_not_declare_is_refused_by_name(self):
        before = self.thread.read_bytes()
        with self.assertRaisesRegex(pa.Refused, "^park takes no commit field$"):     # undo's field, not park's
            self.act(verb="park", zone="Work", file="Acme Review/Threads/Pricing/Pricing.md", commit="abc1234")
        self.assertEqual(before, self.thread.read_bytes())
        self.assertEqual("start", self.last_commit()[0])

    def test_a_parked_single_thread_project_passes_the_check(self):
        import check
        shutil.rmtree(self.work / "Acme Review" / "Threads")
        git(self.work, "add", "-A")
        git(self.work, "commit", "-q", "-m", "one thread")
        self.assertEqual("Acme Review is parked", self.act(verb="park", zone="Work", file="Acme Review/Acme Review.md"))
        self.assertIn("\nstatus: parked\n", (self.work / "Acme Review" / "Acme Review.md").read_text())
        self.assertEqual([], [f.message for f in check.run_checks(self.root) if f.severity == "error"])

    def test_a_project_by_its_name(self):
        import check
        hub = self.work / "Acme Review" / "Acme Review.md"
        self.assertEqual("Acme Review is parked", self.act(verb="park", zone="Work", project="Acme Review"))
        text = hub.read_text()
        self.assertIn("\nstatus: parked\n", text)
        self.assertIn("\nupdated: 2026-10-05\n", text)
        self.assertIn("\nstatus: active\n", self.thread.read_text())             # its threads keep their own status
        self.assertEqual(("Acme Review: parked", ""), self.last_commit())
        self.assertEqual([], [f.message for f in check.run_checks(self.root) if f.severity == "error"])
        self.assertEqual("Acme Review is awake again", self.act(verb="wake", zone="Work", project="Acme Review"))
        self.assertIn("\nstatus: active\n", hub.read_text())
        self.assertEqual("Acme Review: woken", self.last_commit()[0])
        self.assertEqual("Acme Review, Pricing is parked",                          # with a thread, the thread
                         self.act(verb="park", zone="Work", project="Acme Review", thread="Pricing"))

    def test_a_hub_with_a_state_of_play_gets_the_dated_entry(self):
        hub = self.work / "Acme Review" / "Acme Review.md"
        write(hub, hub.read_text() + "\n## State of play\n\n**1 March 2026.** Started.\n")
        git(self.work, "commit", "-qam", "state of play")
        self.act(verb="park", zone="Work", project="Acme Review")
        self.assertIn("## State of play\n\n**5 October 2026.** Parked.\n\n**1 March 2026.** Started.", hub.read_text())

    def test_a_project_name_that_is_no_project(self):
        for name in ("Nope", "../Personal", "Threads", ".git", ""):
            with self.assertRaises(pa.Refused, msg=name):
                self.act(verb="park", zone="Work", project=name)
        self.assertEqual("start", self.last_commit()[0])

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
        return self.root / "System" / "garrick-settings.json"

    def test_saved_whole(self):
        self.assertEqual("Settings saved", self.act(verb="settings", launchers=["note", "cmux", "claude"], default="claude"))
        self.assertEqual({"launchers": {"note": True, "preview": False, "finder": False, "cmux": True, "codex": False, "claude": True},
                          "default": "claude"}, json.loads(self.path().read_text()))
        self.act(verb="settings", launchers=[])
        self.assertEqual("note", json.loads(self.path().read_text())["default"])
        self.assertEqual("", git(self.work, "status", "--porcelain").strip())      # nothing to commit

    def test_refused_names(self):
        for req in ({"launchers": ["note", "terminal"]}, {"launchers": "note"}, {"launchers": ["cmux", "cmux"]},
                    {"launchers": ["cmux"], "default": "codex"}, {"launchers": ["cmux"], "default": "vim"}, {"launchers": [1]},
                    {"launchers": ["note", "preview"], "default": "preview"}):     # Preview opens nothing (#219)
            with self.assertRaises(pa.Refused, msg=req):
                self.act(verb="settings", **req)
        self.assertFalse(self.path().exists())

    def test_the_launchers_are_the_pages(self):
        spec = importlib.util.spec_from_file_location("garrick_status_for_settings", REPO / "extras" / "status" / "status.py")
        status = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(status)
        self.assertEqual(("note",) + tuple(k for k, _, _, _ in status.LAUNCHERS), tuple(k for k in pa.LAUNCHERS if k != "preview"))
        self.assertEqual(status.LAUNCH_KEYS, pa.LAUNCHERS)

    def test_preview_is_switched_on_and_off_with_them(self):
        # Explore's Preview (#219): a key beside the ways to open a thread, kept on or off as they are
        self.act(verb="settings", launchers=["note", "preview", "cmux"], default="cmux")
        self.assertTrue(json.loads(self.path().read_text())["launchers"]["preview"])
        self.act(verb="settings", launchers=["note", "cmux"], default="cmux")
        self.assertEqual({"note": True, "preview": False, "finder": False, "cmux": True, "codex": False, "claude": False},
                         json.loads(self.path().read_text())["launchers"])


class TestWaitSettings(ActionCase):
    """Settings › While you wait (#111), checked by next_up.py and kept beside the rest."""

    def path(self):
        return self.root / "System" / "garrick-settings.json"

    def test_saved_checked_and_beside_the_rest(self):
        self.act(verb="settings", launchers=["note", "cmux"], default="cmux")
        said = self.act(verb="settings", **{"while-you-wait": {"on": False, "threshold": 90, "same-zone": True,
                                                                 "sources": ["due", "stack"], "parked-days": 60}})
        self.assertEqual("Settings saved", said)
        saved = json.loads(self.path().read_text())
        self.assertEqual("cmux", saved["default"])                                   # the rest stays
        self.assertEqual({"on": False, "threshold": 90, "same-zone": True, "sources": ["due", "stack"],
                          "parked-days": 60, "wrap-days": 14}, saved["while-you-wait"])

    def test_refused_with_the_reason(self):
        for wait in ({"threshold": 2}, {"sources": ["mail"]}, {"same-zone": "yes"}, {"colour": "Teal"}, "on"):
            with self.assertRaises(pa.Refused, msg=wait):
                self.act(verb="settings", **{"while-you-wait": wait})
        self.assertFalse(self.path().exists())

    def test_a_pick_ticks_through_todo_done(self):
        shutil.copy2(REPO / "template" / "System" / "tools" / "next_up.py", self.root / "System" / "tools" / "next_up.py")
        (self.root / "System" / "skills" / "todo").mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / "template" / "System" / "skills" / "todo" / "todo.py", self.root / "System" / "skills" / "todo" / "todo.py")
        spec = importlib.util.spec_from_file_location("garrick_next_up_pa", str(self.root / "System" / "tools" / "next_up.py"))
        nu = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(nu)
        due = [p for p in nu.next_up(self.root, today=dt.date(2026, 10, 10))["picks"] if p["source"] == "due"]
        self.assertEqual(due[0]["say"], "Pricing: Send the revised terms (Work, 1 day late)")
        self.assertIn("Send the revised terms", self.act(**due[0]["tick"]))
        self.assertIn("- [x] [[Pricing]]: Send the revised terms", (self.work / "Todo.md").read_text())


class TestCatchUpSettings(ActionCase):
    """Settings › Catch up (#27): the default period, checked by briefing.py and kept beside the rest."""

    def path(self):
        return self.root / "System" / "garrick-settings.json"

    def test_saved_checked_and_beside_the_rest(self):
        self.act(verb="settings", launchers=["note", "cmux"], default="cmux")
        self.assertEqual("Settings saved", self.act(verb="settings", **{"catch-up": {"period": "week"}}))
        saved = json.loads(self.path().read_text())
        self.assertEqual("cmux", saved["default"])                                   # the rest stays
        self.assertEqual({"period": "week"}, saved["catch-up"])

    def test_refused_with_the_reason(self):
        for catch in ({"period": "month"}, {"colour": "Teal"}, "week"):
            with self.assertRaises(pa.Refused, msg=catch):
                self.act(verb="settings", **{"catch-up": catch})
        self.assertFalse(self.path().exists())


class TestMemorySettings(ActionCase):
    """Settings › Memory (#108): checked here against fade.py's shape, kept
    under "memory" beside the rest, and counted from unsaved values without
    a thing written. A stand-in fade.py, as the page's own tests use."""

    MEMORY = {"wikis": {"Meetings": True, "Knowledge": False},
              "kinds": {"meetings": {"wiki": "Meetings", "types": ["meeting", " email ", "", "meeting"], "domains": [],
                                     "dormant": 4, "archived": 12},
                        "contracts": {"wiki": "Knowledge", "types": ["contract"], "domains": ["acme.example"],
                                      "dormant": 24, "archived": None}},
              "pins": {"thread": True, "project": False, "todo": True, "pinned": True},
              "wake": True, "reach": "working", "nightly": {"on": False, "min": 25}}

    def setUp(self):
        super().setUp()
        fixtures.write_fade_stub(self.root)

    def path(self):
        return self.root / "System" / "garrick-settings.json"

    def test_saved_checked_and_beside_the_rest(self):
        self.act(verb="settings", launchers=["note", "cmux"], default="cmux")
        self.assertEqual("Settings saved", self.act(verb="settings", memory=self.MEMORY))
        saved = json.loads(self.path().read_text())
        self.assertEqual("cmux", saved["default"])                                   # the rest stays
        self.assertEqual(["meeting", "email"], saved["memory"]["kinds"]["meetings"]["types"])   # trimmed, once each
        self.assertIsNone(saved["memory"]["kinds"]["contracts"]["archived"])
        self.assertEqual({"on": False, "min": 25}, saved["memory"]["nightly"])
        self.assertEqual("", git(self.work, "status", "--porcelain").strip())      # nothing in a zone moved

    def test_refused_with_the_reason(self):
        kind = self.MEMORY["kinds"]["meetings"]
        for memory in ("on", {"colour": "Teal"}, {"wikis": {"Library": True}}, {"wikis": {"Meetings": "yes"}},
                       {"kinds": {"meetings": dict(kind, wiki="Mail")}}, {"kinds": {"meetings": dict(kind, dormant=0)}},
                       {"kinds": {"meetings": dict(kind, dormant=True)}}, {"kinds": {"meetings": dict(kind, archived=2)}},
                       {"kinds": {"meetings": {k: v for k, v in kind.items() if k != "archived"}}},
                       {"kinds": {"meetings": dict(kind, types="meeting")}}, {"kinds": {"meetings": dict(kind, size=3)}},
                       {"kinds": {"": kind}}, {"pins": {"starred": True}}, {"wake": 1}, {"reach": "archive"},
                       {"nightly": {"min": 0}}, {"nightly": {"on": "yes"}}, {"nightly": {"when": "06:00"}}):
            with self.assertRaises(pa.Refused, msg=memory):
                self.act(verb="settings", memory=memory)
        self.assertFalse(self.path().exists())

    def test_refused_without_fade(self):
        os.remove(str(self.root / "System" / "tools" / "fade.py"))
        pa._FADE.pop(self.root, None)
        with self.assertRaises(pa.Refused) as said:
            self.act(verb="settings", memory=self.MEMORY)
        self.assertIn("System/tools/fade.py", str(said.exception))
        with self.assertRaises(pa.Refused):
            self.act(verb="memory-preview", memory={})
        self.assertFalse(self.path().exists())

    def test_a_preview_counts_unsaved_values_and_writes_nothing(self):
        out = self.act(verb="memory-preview", memory={})
        self.assertEqual(4, out["counts"]["Meetings"]["to_dormant"])                # the saved, here the defaults: 24 // 6
        out = self.act(verb="memory-preview", memory=self.MEMORY)
        self.assertEqual(6, out["counts"]["Meetings"]["to_dormant"])                # 24 // 4, unsaved
        self.assertEqual(4, out["counts"]["Meetings"]["to_archive"])                # 48 // 12
        self.assertFalse(out["counts"]["Knowledge"]["on"])
        self.assertEqual(0, out["counts"]["Knowledge"]["to_dormant"])
        self.assertFalse(self.path().exists())
        with self.assertRaises(pa.Refused):
            self.act(verb="memory-preview", memory={"reach": "everywhere"})
        with self.assertRaises(pa.Refused):                                          # only `memory`, as declared
            self.act(verb="memory-preview", memory={}, path="Wikis/Meetings")

    def test_a_fade_older_than_its_preview_gives_the_counts_alone(self):
        self.assertNotIn("preview", self.act(verb="memory-preview", memory={}))

    def test_with_the_real_fade_the_preview_names_the_pages_too(self):
        fixtures.write_fade(self.root)
        pa._FADE.pop(self.root, None)
        out = self.act(verb="memory-preview", memory={})
        pv = out["preview"]["Meetings"]
        self.assertEqual(set(pa.COUNT_KEYS), set(out["counts"]["Meetings"]))            # counts as before, from the same plan
        self.assertEqual(out["counts"]["Meetings"], {k: pv[k] for k in pa.COUNT_KEYS})
        self.assertIn("Old call 1", [r["title"] for r in pv["moving"]])
        self.assertEqual(["Kept call"], [r["title"] for r in pv["keeping"] if r["date"] == "2020-01-08"])
        later = self.act(verb="memory-preview", memory={"pins": {"thread": False}})["preview"]["Meetings"]
        self.assertNotIn("Kept call", [r["title"] for r in later["keeping"]])            # unsaved values move the list too
        self.assertGreater(later["moves"], pv["moves"])
        self.assertLess(later["kept"], pv["kept"])
        self.assertFalse(self.path().exists())
        self.assertFalse((self.root / "System" / "generated" / "fade").exists())

    def test_through_the_script_as_a_host_sends_it(self):
        done = subprocess.run([sys.executable, str(SCRIPT), "--workspace", str(self.root)], capture_output=True, text=True,
                              input=json.dumps({"verb": "memory-preview", "memory": {"wake": False}}), timeout=60)
        reply = json.loads(done.stdout)
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(0, reply["counts"]["Meetings"]["to_wake"])
        self.assertFalse(self.path().exists())


class TestZoneSettings(ActionCase):
    """Settings › Zones (#67): a colour and an icon per zone, beside the launchers."""

    def setUp(self):
        super().setUp()
        # Never this Mac's own cmux: the desk is a recording stand-in.
        p = mock.patch.object(pa, "run_desk")
        self.desk = p.start()
        self.addCleanup(p.stop)

    def path(self):
        return self.root / "System" / "garrick-settings.json"

    def saved(self):
        return json.loads(self.path().read_text())

    def test_saved_beside_the_launchers_and_each_kept_by_the_other(self):
        self.act(verb="settings", launchers=["note", "cmux"], default="cmux")
        self.assertEqual("Settings saved", self.act(verb="settings", zones={
            "Work": {"color": "Teal", "icon": "briefcase"}, "Personal": {"color": "", "icon": ""}}))
        data = self.saved()
        self.assertEqual({"Work": {"color": "Teal", "icon": "briefcase"}}, data["zones"])   # a zone with neither is left out
        self.assertEqual("cmux", data["default"])
        self.act(verb="settings", launchers=["note"])
        self.assertEqual({"Work": {"color": "Teal", "icon": "briefcase"}}, self.saved()["zones"])
        self.act(verb="settings", launchers=["note", "claude"], default="claude", zones={"Personal": {"icon": "house"}})
        self.assertEqual(({"Personal": {"icon": "house"}}, "claude"), (self.saved()["zones"], self.saved()["default"]))

    def test_refused_names_and_a_zone_no_longer_there(self):
        for zones in ({"Work": {"color": "Mauve"}}, {"Work": {"icon": "unicorn"}}, {"Work": "Teal"},
                      {"Work": {"color": "Teal", "size": 3}}, ["Work"]):
            with self.assertRaises(pa.Refused, msg=zones):
                self.act(verb="settings", zones=zones)
        with self.assertRaisesRegex(pa.Refused, "nothing to save"):
            self.act(verb="settings")
        self.assertFalse(self.path().exists())
        self.act(verb="settings", zones={"Old Name": {"color": "Teal"}, "../System": {"color": "Red"}, "Work": {"color": "Navy"}})
        self.assertEqual({"Work": {"color": "Navy"}}, self.saved()["zones"])

    def test_a_changed_colour_recolours_its_open_tab(self):
        self.act(verb="settings", zones={"Work": {"color": "Teal"}, "Personal": {"icon": "house"}})
        self.assertEqual([mock.call(self.root, "colour", "--", "Work", timeout=20)], self.desk.call_args_list)
        self.desk.reset_mock()
        self.act(verb="settings", zones={"Work": {"color": "Teal", "icon": "star"}, "Personal": {"icon": "leaf"}})
        self.desk.assert_not_called()                                             # icons are the page's alone
        self.act(verb="settings", zones={"Work": {}, "Personal": {"color": "Rose"}})
        self.assertEqual([mock.call(self.root, "colour", "--", "Personal", "Work", timeout=20)], self.desk.call_args_list)
        self.desk.side_effect = pa.Refused("cmux is not installed here")
        self.assertEqual("Settings saved", self.act(verb="settings", zones={"Work": {"color": "Red"}}))   # best effort

    def test_the_names_are_the_pages_and_cmuxs(self):
        spec = importlib.util.spec_from_file_location("garrick_status_for_zones", REPO / "extras" / "status" / "status.py")
        status = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(status)
        spec = importlib.util.spec_from_file_location("garrick_cmuxlib_for_zones", REPO / "extras" / "cmux" / "cmuxlib.py")
        cx = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cx)
        self.assertEqual(tuple(status.ZONE_COLOURS), pa.ZONE_COLOURS)
        self.assertEqual(cx.COLOURS, pa.ZONE_COLOURS)
        self.assertEqual(tuple(status.ZONE_ICONS), pa.ZONE_ICONS)


class TestAudit(ActionCase):
    """page-actions.log: one line per request, with only the fields a verb reads."""

    def run_script(self, request):
        return subprocess.run([sys.executable, str(SCRIPT), "--workspace", str(self.root)], input=request,
                              capture_output=True, text=True)

    def lines(self):
        return (self.jobs / "page-actions.log").read_text().splitlines()

    def test_one_line_each_done_or_refused(self):
        self.run_script(json.dumps({"verb": "todo-done", "zone": "Work", "file": "Todo.md", "key": self.key("Invoice")}))
        self.run_script(json.dumps({"verb": "todo-add", "zone": "Work", "text": "Book the room " + "x" * 200}))
        self.run_script("not json")
        # A field the verb does not declare is refused by name, and its value
        # reaches the log no more than it did when such a field was ignored.
        self.run_script(json.dumps({"verb": "todo-add", "zone": "Work", "text": "x",
                                    "password": "hunter2", "session": "abc"}))
        lines = self.lines()
        self.assertEqual(4, len(lines))
        self.assertRegex(lines[0], r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d  todo-done zone=\"Work\" file=\"Todo.md\" key=\"[0-9a-f]{16}\"  ->  ok: Done: Acme Corp: Invoice for September$")
        self.assertIn('todo-add zone="Work" text="Book the room xxx', lines[1])
        self.assertIn("…\"  ->  ok: Added to Inbox", lines[1])
        self.assertLess(len(lines[1]), 320)
        self.assertTrue(lines[2].endswith("?  ->  refused: not a request"))
        self.assertIn("refused: Not done. Todo-add takes no password field and no session field.", lines[3])
        self.assertNotIn("hunter2", "\n".join(lines))

    def test_an_open_by_folder_logs_the_folder_and_the_prompt_cut_short(self):
        pa.audit({"verb": "open", "folder": str(self.root), "prompt": "process the inbox " + "y" * 200}, False, "no")
        line = self.lines()[-1]
        self.assertIn('open folder="%s" prompt="process the inbox yyy' % self.root, line)
        self.assertIn("…\"  ->  refused: no", line)
        self.assertNotIn("y" * 61, line)

    def test_a_log_that_cannot_be_written_stops_nothing(self):
        (self.jobs / "page-actions.log").mkdir(parents=True)          # a folder where the log should be
        done = self.run_script(json.dumps({"verb": "todo-done", "zone": "Work", "file": "Todo.md", "key": self.key("Invoice")}))
        self.assertEqual({"ok": True, "say": "Done: Acme Corp: Invoice for September"}, plain(json.loads(done.stdout)))


class TestJournal(ActionCase):
    """Each click leaves a durable record in the jobs folder (operations.py): a
    page that was reloaded finds the action again, and a refusal never reads as saved."""

    def hook(self, body):
        hook = self.work / ".git" / "hooks" / "pre-commit"
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text("#!/bin/sh\n" + body)
        hook.chmod(0o755)

    def start(self, request=None):
        p = subprocess.Popen([sys.executable, str(SCRIPT), "--workspace", str(self.root)], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             env=dict(os.environ, GARRICK_JOBS_DIR=str(self.jobs)))
        if request is not None:
            p.stdin.write(json.dumps(request))
            p.stdin.close()
        return p

    def finish(self, p):
        out = p.stdout.read()
        p.wait(timeout=60)
        p.stdout.close()
        p.stderr.close()
        return json.loads(out)

    def run_script(self, request, **kw):
        done = subprocess.run([sys.executable, str(SCRIPT), "--workspace", str(kw.get("ws", self.root))],
                              input=json.dumps(request) if not isinstance(request, str) else request,
                              capture_output=True, text=True, env=dict(os.environ, GARRICK_JOBS_DIR=str(self.jobs)))
        return json.loads(done.stdout)

    def records(self):
        return [json.loads(line) for line in (self.jobs / "operations.jsonl").read_text().splitlines()]

    def wait_for(self, path, seconds=20):
        import time
        deadline = time.time() + seconds
        while not path.exists() and time.time() < deadline:
            time.sleep(0.02)
        self.assertTrue(path.exists(), path)

    def requests(self):
        """One request of each journaled verb, with the state it needs set up first."""
        rel = "Acme Review/Threads/Pricing/Pricing.md"
        return {
            "park": {"verb": "park", "zone": "Work", "file": rel},
            "todo-done": {"verb": "todo-done", "zone": "Work", "file": "Todo.md", "key": self.key("Invoice")},
            "todo-date": {"verb": "todo-date", "zone": "Work", "file": "Todo.md", "key": self.key("Invoice"), "date": "2026-10-12"},
            "todo-add": {"verb": "todo-add", "zone": "Work", "text": "Book the room", "target": "-", "date": "-"},
        }

    def test_a_park_leaves_a_record_from_queued_to_saved(self):
        reply = self.run_script({"verb": "park", "zone": "Work", "file": "Acme Review/Threads/Pricing/Pricing.md", "op": "a19f3c80"})
        self.assertEqual(("a19f3c80", "completed", "saved", True), (reply["op"], reply["state"], reply["outcome"], reply["ok"]))
        self.assertEqual("Acme Review, Pricing is parked", reply["say"])
        records = self.records()
        self.assertEqual([("queued", ""), ("running", ""), ("running", "checking"), ("completed", "")],
                         [(r["state"], r["phase"]) for r in records])
        self.assertEqual("saved", records[-1]["outcome"])
        self.assertEqual("Acme Review, Pricing is parked", records[-1]["say"])
        self.assertEqual(("Acme Review, Pricing: parked", ""), self.last_commit())

    def test_a_tick_and_an_add_leave_one_each(self):
        for request in (self.requests()["todo-done"], self.requests()["todo-add"]):
            reply = self.run_script(request)
            self.assertEqual(("completed", "saved"), (reply["state"], reply["outcome"]), request["verb"])
            self.assertTrue(re.fullmatch(r"[0-9a-f]{16}", reply["op"]))              # minted: the caller sent none
        ends = [r for r in self.records() if r["state"] in ("completed", "failed")]
        self.assertEqual(["todo-done", "todo-add"], [r["verb"] for r in ends])
        self.assertEqual(["saved", "saved"], [r["outcome"] for r in ends])

    def test_the_record_is_in_the_jobs_folder_and_nowhere_else(self):
        self.run_script(self.requests()["todo-add"])
        self.assertTrue((self.jobs / "operations.jsonl").is_file())
        self.assertEqual([], [str(p) for p in self.root.rglob("operations.jsonl")])
        self.assertEqual([], [str(p) for p in self.root.rglob("op-*.run")])
        self.assertEqual("", git(self.work, "status", "--porcelain").strip())
        self.assertEqual([], list(self.jobs.glob("op-*.run")))                    # and the locks are cleared away

    def committing_requests(self):
        """One request of every verb page_action.py commits through commit() or
        commit_all(), with the state each needs committed first: the six the
        record keeps, and an interruption, an answer and a put-off question.
        The manage verbs commit through scaffold.py, and are held to the same in
        test_scaffold_manage.py, against an installed workspace's own check."""
        self.act(verb="todo-done", zone="Work", file="Todo.md", key=self.key("Send the revised"))
        ticked = tl.done_on(str(self.work), dt.date.today())[0]["key"]
        self.act(verb="park", zone="Work", file="Acme Review/Threads/Pricing/Pricing.md")
        import test_simple_home as home
        asked = "Birch Entry/Threads/Market Sizing/Needs you/261003 - floor.md"
        write(self.work / asked, home.question())
        git(self.work, "add", "-A")
        git(self.work, "commit", "-q", "-m", "asked")
        return dict(self.requests(), **{
            "wake": {"verb": "wake", "zone": "Work", "file": "Acme Review/Threads/Pricing/Pricing.md"},
            "todo-undo": {"verb": "todo-undo", "zone": "Work", "file": "Todo.md", "key": ticked},
            "park": {"verb": "park", "zone": "Work", "project": "Birch Entry"},
            "interrupt": {"verb": "interrupt", "zone": "Work", "project": "Birch Entry", "thread": "Market Sizing",
                          "where": "Halfway through the volumes", "next": "Fill in row 14"},
            "answer": {"verb": "answer", "zone": "Work", "file": asked, "label": "500 pallets"},
            "later": {"verb": "later", "zone": "Work", "file": asked}})

    def test_a_commit_the_wall_check_refuses_ends_on_the_rules_sentence_alone_for_every_verb(self):
        """#172: the hook prints what the zone's wall check prints, a line
        WALL_LINE recognises, naming the note and the far side's party. Every
        verb that commits says #116's sentence and nothing else, in its reply
        and in its record, and changes nothing."""
        import test_operations as t
        wall = t.ops.WALL_REFUSAL
        requests = self.committing_requests()
        self.assertEqual({"park", "wake", "todo-done", "todo-undo", "todo-date", "todo-add", "interrupt", "answer",
                          "later"}, set(requests))
        line = self.wall_line("Birch Entry/Threads/Market Sizing/Market Sizing.md",
                              "names Acme Corp (`acme`), or one of its people; a wall stands between birch and acme")
        self.assertTrue(pa.WALL_LINE.match(line), line)
        self.hook("cat >&2 <<'EOF'\n%s\nEOF\nexit 1\n" % line)
        head = git(self.work, "rev-parse", "HEAD")
        before = {p: p.read_bytes() for p in self.work.rglob("*.md")}
        for verb, request in requests.items():
            reply = self.run_script(request)
            self.assertEqual((False, wall), (reply["ok"], reply["say"]), verb)
            for leak in ("acme", "Acme", "birch", "Market Sizing", "Commit refused", "not committed", "Not done"):
                self.assertNotIn(leak, reply["say"], verb)
            if verb in t.ops.OPS:
                last = self.records()[-1]
                self.assertEqual(("failed", "refused", wall), (last["state"], last["outcome"], last["say"]), verb)
        self.assertEqual(head, git(self.work, "rev-parse", "HEAD"))
        self.assertEqual(before, {p: p.read_bytes() for p in self.work.rglob("*.md")})        # every note put back

    def test_a_commit_refused_for_any_other_reason_still_says_why(self):
        """A hook that fails for its own reasons is not the wall check: every
        verb says what it said, and never borrows the wall's sentence."""
        import test_operations as t
        requests = self.committing_requests()
        self.hook('echo "fatal: the disk is full" >&2\nexit 1\n')
        before = {p: p.read_bytes() for p in self.work.rglob("*.md")}
        for verb, request in requests.items():
            reply = self.run_script(request)
            self.assertFalse(reply["ok"], verb)
            self.assertIn("the disk is full", reply["say"], verb)
            self.assertNotIn(t.ops.WALL_REFUSAL, reply["say"], verb)
            self.assertTrue(t.only_in_the_negative(reply["say"]), (verb, reply["say"]))
            self.assertFalse(t.ops.affirms(reply["say"]), (verb, reply["say"]))
        self.assertEqual(before, {p: p.read_bytes() for p in self.work.rglob("*.md")})

    def wall_line(self, path, message):
        """What the zone's wall check prints when it refuses: check.py's own
        report_staged(), so the line the handler recognises is the real one."""
        import check            # fixtures puts the tools folder on sys.path
        return check.report_staged([check.Finding(check.ERROR, "walls", path, message)])

    def test_a_batch_the_wall_check_refuses_ends_on_the_rules_sentence_alone(self):
        """#107, with #116's sentence: no refusal wording of its own, and nothing
        of what the check found, the far side's tag and the note's path."""
        import test_operations as t
        wall = t.ops.WALL_REFUSAL
        line = self.wall_line("Acme Review/Acme Review.md", "names birch, a party across a wall")
        self.hook("cat >&2 <<'EOF'\n%s\nEOF\nexit 1\n" % line)
        keys = [self.key("Send the revised"), self.key("Invoice")]
        before = (self.work / "Todo.md").read_bytes()
        for request in ({"verb": "todo-done", "zone": "Work", "file": "Todo.md", "keys": keys},
                        {"verb": "todo-done", "zone": "Work", "file": "Todo.md", "key": keys[0]}):
            reply = self.run_script(request)
            self.assertEqual((False, "failed", "refused"), (reply["ok"], reply["state"], reply["outcome"]), reply)
            self.assertEqual(wall, reply["say"])
            self.assertEqual(wall, self.records()[-1]["say"])
            for leak in ("birch", "Acme Review", "Commit refused", "Not done"):
                self.assertNotIn(leak, reply["say"])
            self.assertEqual(before, (self.work / "Todo.md").read_bytes())             # the boxes go back because the note did
        self.assertEqual("start", self.last_commit()[0])
        self.hook("echo 'fatal: something else entirely' >&2\nexit 1\n")              # not the wall check: said as before
        reply = self.run_script({"verb": "todo-done", "zone": "Work", "file": "Todo.md", "keys": keys})
        self.assertIn("something else entirely", reply["say"])
        self.assertNotEqual(wall, reply["say"])

    def test_a_batch_is_one_record_that_lists_every_line(self):
        keys = [self.key("Send the revised"), self.key("Invoice")]
        reply = self.run_script({"verb": "todo-done", "zone": "Work", "file": "Todo.md", "keys": keys, "op": "a19f3c80"})
        self.assertEqual(("completed", "saved", "Saved 2"), (reply["state"], reply["outcome"], reply["say"]))
        records = self.records()
        self.assertEqual({"a19f3c80"}, {r["op"] for r in records})
        self.assertEqual(keys, records[0]["request"]["keys"])
        self.assertEqual("Ticking 2 lines…", records[0]["label"])
        import test_operations as t
        listed = t.ops.read(self.jobs)["ops"]
        self.assertEqual([keys], [r["keys"] for r in listed])                           # what a reload is told is pending
        self.assertIn('keys=["%s", "%s"]' % tuple(keys), (self.jobs / "page-actions.log").read_text())

    def test_a_stale_line_is_refused_in_the_record_too(self):
        key = self.key("Send the revised")
        write(self.work / "Todo.md", (self.work / "Todo.md").read_text().replace("revised terms", "final terms"))
        reply = self.run_script({"verb": "todo-done", "zone": "Work", "file": "Todo.md", "key": key})
        self.assertEqual(("failed", "refused"), (reply["state"], reply["outcome"]))
        self.assertIn("changed since the page was built", reply["say"])

    def test_a_bad_op_is_refused_before_anything_runs(self):
        reply = self.run_script(dict(self.requests()["todo-add"], op="../../etc/passwd"))
        self.assertEqual({"ok": False, "say": "not an operation id"}, reply)
        self.assertNotIn("Book the room", (self.work / "Todo.md").read_text())

    def test_the_only_field_a_page_adds_is_the_op(self):
        reply = self.run_script(dict(self.requests()["todo-add"], op="a19f3c80"))
        self.assertEqual("saved", reply["outcome"])
        self.assertEqual("Added to Inbox: Book the room", reply["say"])

    def test_anything_else_a_request_carries_is_refused_by_name(self):
        """Closed validation: until 0.26.0 these were ignored, so a request
        could carry anything and still be accepted."""
        reply = self.run_script(dict(self.requests()["todo-add"], op="b29f3c80", retry_of="a19f3c80", host="app"))
        self.assertEqual({"ok": False, "say": "Not done. Todo-add takes no host field and no retry_of field."},
                         {k: reply[k] for k in ("ok", "say")})
        self.assertEqual("refused", reply["outcome"])
        self.assertNotIn("Book the room", (self.work / "Todo.md").read_text())

    def test_a_second_identical_request_joins_and_makes_one_edit(self):
        mark = Path(self._tmp.name) / "in-the-hook"
        self.hook('touch "%s"\nsleep 2\n' % mark)
        request = self.requests()["todo-add"]
        first = self.start(dict(request, op="a19f3c80"))
        self.wait_for(mark)                                                       # the first is in the wall check
        second = self.finish(self.start(dict(request, op="b29f3c80")))
        self.assertEqual({"ok": True, "say": "Already adding to Work…", "op": "a19f3c80", "state": "running"}, second)
        self.assertNotIn("outcome", second)                                       # joined: ok, and not saved
        done = self.finish(first)
        self.assertEqual(("a19f3c80", "saved"), (done["op"], done["outcome"]))
        self.assertEqual(1, (self.work / "Todo.md").read_text().count("Book the room"))
        self.assertEqual(["Work: added to Inbox, Book the room", "start"], git(self.work, "log", "-2", "--format=%s").splitlines())
        self.assertEqual({"a19f3c80"}, {r["op"] for r in self.records()})          # the second made no record of its own
        self.assertIn("(running)", (self.jobs / "page-actions.log").read_text().splitlines()[0])

    def test_the_same_request_again_after_a_save_is_answered_and_not_done(self):
        request = self.requests()["todo-done"]
        first = self.run_script(dict(request, op="a19f3c80"))
        self.assertEqual("saved", first["outcome"])
        head = git(self.work, "rev-parse", "HEAD")
        second = self.run_script(dict(request, op="b29f3c80"))
        self.assertEqual({"ok": True, "say": "Done: Acme Corp: Invoice for September", "op": "a19f3c80", "state": "completed",
                          "outcome": "saved"}, second)
        self.assertEqual(head, git(self.work, "rev-parse", "HEAD"))              # executed, the old key would have been refused
        self.assertEqual({"a19f3c80"}, {r["op"] for r in self.records()})         # the second left no record of its own

    def age(self, seconds):
        """Every record made `seconds` earlier, as if the clock had moved on."""
        lines = []
        for r in self.records():
            for k in ("at", "done"):
                if isinstance(r.get(k), (int, float)):
                    r[k] -= seconds
            lines.append(json.dumps(r))
        (self.jobs / "operations.jsonl").write_text("\n".join(lines) + "\n")

    def test_a_retry_after_the_window_is_asked_about_and_makes_no_second_edit(self):
        """#137: the retry a client that gave up invites comes long after the
        double click's window. It is recognised all the same, and asked about."""
        import time
        request = self.requests()["todo-add"]
        first = self.run_script(dict(request, op="a19f3c80"))
        self.assertEqual("saved", first["outcome"])
        self.age(300)                                                             # five minutes on: past the window
        head = git(self.work, "rev-parse", "HEAD")
        second = self.run_script(dict(request, op="b29f3c80"))
        self.assertEqual((False, "asked", "a19f3c80", "a19f3c80"),
                         (second["ok"], second["state"], second["op"], second["again"]))
        self.assertNotIn("outcome", second)                                       # this request did nothing
        done = time.strftime("%H:%M", time.localtime(self.records()[-1]["done"]))
        self.assertEqual("The same request was done 5 minutes ago, at %s: Added to Inbox: Book the room. It has not "
                         "been done again. Do you want it done a second time?" % done, second["say"])
        self.assertEqual(head, git(self.work, "rev-parse", "HEAD"))              # no second edit, no second commit
        self.assertEqual(1, (self.work / "Todo.md").read_text().count("Book the room"))
        self.assertEqual({"a19f3c80"}, {r["op"] for r in self.records()})         # and no record of its own
        self.assertIn("The same request was done", (self.jobs / "page-actions.log").read_text().splitlines()[-1])

    def test_a_confirmed_retry_is_done_a_second_time(self):
        """The user meant it: the line went in, was ticked by hand, and is wanted again."""
        request = self.requests()["todo-add"]
        self.run_script(dict(request, op="a19f3c80"))
        todo = self.work / "Todo.md"
        write(todo, todo.read_text().replace("- [ ] Book the room", "- [x] Book the room ✅ 2026-10-05"))
        git(self.work, "commit", "-q", "-am", "ticked by hand")
        self.age(300)
        asked = self.run_script(dict(request, op="b29f3c80"))
        self.assertEqual("a19f3c80", asked["again"])
        self.assertNotIn("- [ ] Book the room", todo.read_text())                # asked: nothing added yet
        again = self.run_script(dict(request, op="c39f3c80", confirm=asked["again"]))
        self.assertEqual((True, "c39f3c80", "saved"), (again["ok"], again["op"], again["outcome"]))
        self.assertIn("- [ ] Book the room", todo.read_text())                   # the second edit
        self.assertEqual("Work: added to Inbox, Book the room", git(self.work, "log", "-1", "--format=%s").strip())
        self.assertEqual("a19f3c80", [r for r in self.records() if r["op"] == "c39f3c80"][0]["request"]["confirm"])

    def test_a_confirm_that_names_another_action_is_asked_again(self):
        request = self.requests()["todo-add"]
        self.run_script(dict(request, op="a19f3c80"))
        self.age(300)
        head = git(self.work, "rev-parse", "HEAD")
        reply = self.run_script(dict(request, op="b29f3c80", confirm="ffffffff"))
        self.assertEqual(("asked", "a19f3c80"), (reply["state"], reply["again"]))
        self.assertEqual(head, git(self.work, "rev-parse", "HEAD"))

    def test_a_different_request_after_the_window_runs_as_usual(self):
        self.run_script(dict(self.requests()["todo-add"], op="a19f3c80"))
        self.age(300)
        other = self.run_script(dict(self.requests()["todo-add"], text="Call Dana", op="b29f3c80"))
        self.assertEqual((True, "b29f3c80", "saved"), (other["ok"], other["op"], other["outcome"]))
        self.assertIn("Call Dana", (self.work / "Todo.md").read_text())

    def test_past_the_lookback_the_same_request_is_a_new_one(self):
        """Then the record is not consulted, and the handler's own check is
        the one that answers: the line is still open, so it is refused."""
        ops = pa.ops_lib(self.root)
        request = self.requests()["todo-add"]
        self.run_script(dict(request, op="a19f3c80"))
        self.age(ops.LOOKBACK + 5)
        reply = self.run_script(dict(request, op="b29f3c80"))
        self.assertEqual(("b29f3c80", "refused"), (reply["op"], reply["outcome"]))
        self.assertIn("already in the list", reply["say"])

    def test_a_refusal_is_run_again(self):
        self.hook("exit 1\n")
        request = self.requests()["todo-add"]
        self.assertEqual("refused", self.run_script(dict(request, op="a19f3c80"))["outcome"])
        (self.work / ".git" / "hooks" / "pre-commit").unlink()
        again = self.run_script(dict(request, op="b29f3c80"))
        self.assertEqual(("b29f3c80", "saved"), (again["op"], again["outcome"]))

    def test_a_park_then_a_wake_then_a_park_is_three_edits(self):
        rel = "Acme Review/Threads/Pricing/Pricing.md"
        for verb, status in (("park", "parked"), ("wake", "active"), ("park", "parked")):
            reply = self.run_script({"verb": verb, "zone": "Work", "file": rel})
            self.assertEqual("saved", reply["outcome"], verb)
            self.assertIn("\nstatus: %s\n" % status, self.thread.read_text())
        self.assertEqual(["Acme Review, Pricing: parked", "Acme Review, Pricing: woken", "Acme Review, Pricing: parked"],
                         git(self.work, "log", "-3", "--format=%s").splitlines())

    def test_the_operations_verb_returns_the_open_set_with_its_phase(self):
        mark = Path(self._tmp.name) / "in-the-hook"
        self.hook('touch "%s"\nsleep 2\n' % mark)
        worker = self.start(dict(self.requests()["todo-add"], op="a19f3c80"))
        self.wait_for(mark)
        reply = self.run_script({"verb": "operations"})
        self.assertEqual((True, True), (reply["ok"], reply["durable"]))
        self.assertEqual(["park", "todo-add", "todo-date", "todo-done", "todo-undo", "wake"], reply["verbs"])
        (running,) = reply["ops"]
        self.assertEqual(("a19f3c80", "running", "checking", "todo-add", "Work", None),
                         (running["op"], running["state"], running["phase"], running["verb"], running["zone"], running["outcome"]))
        self.assertEqual("Adding to Work…", running["label"])
        self.finish(worker)
        (ended,) = self.run_script({"verb": "operations"})["ops"]
        self.assertEqual(("completed", "saved"), (ended["state"], ended["outcome"]))        # still there, for a page that was away
        self.assertEqual([], [l for l in (self.jobs / "page-actions.log").read_text().splitlines() if "operations" in l])

    def test_a_worker_killed_midway_reads_back_unknown_with_what_to_check(self):
        import signal
        mark = Path(self._tmp.name) / "in-the-hook"
        self.hook('echo $PPID > "%s.tmp"\nmv "%s.tmp" "%s"\nsleep 3\n' % (mark, mark, mark))   # the hook's parent is the commit
        worker = self.start(dict(self.requests()["todo-add"], op="a19f3c80"))
        self.wait_for(mark)
        orphan = os.getpgid(int(mark.read_text()))             # the commit's own process group, which the kill leaves running
        os.kill(worker.pid, signal.SIGKILL)
        worker.wait(timeout=30)
        worker.stdout.close()
        worker.stderr.close()
        (found,) = self.run_script({"verb": "operations"})["ops"]
        self.assertEqual(("failed", "unknown"), (found["state"], found["outcome"]))
        self.assertIn("git log -1 in Work", found["say"])
        self.assertIn("Trying again is safe", found["say"])
        import test_operations as t
        self.assertIsNone(t.SUCCESS.search(found["say"]), found["say"])
        again = self.run_script({"verb": "operations"})["ops"]
        self.assertEqual("unknown", again[0]["outcome"])
        self.assertEqual(1, len([r for r in self.records() if r["op"] == "a19f3c80" and r["state"] == "failed"]))   # written once
        import time
        deadline = time.time() + 30
        while time.time() < deadline:                          # the orphaned commit finishes before the folder goes
            try:
                os.killpg(orphan, 0)
            except ProcessLookupError:
                break
            except PermissionError:                            # macOS: exited, not yet reaped by launchd
                pass
            time.sleep(0.1)
        else:
            self.fail("the orphaned commit was still running after 30 s")

    def test_without_the_module_every_reply_is_what_it_was(self):
        """A workspace and an extra with no operations.py anywhere: 0.26.0's replies, byte for byte."""
        (self.root / "System" / "tools" / "operations.py").unlink()      # nor in the workspace
        bare = Path(self._tmp.name) / "bare" / "System" / "status"
        bare.mkdir(parents=True)
        for name in ("page_action.py", "todo_lines.py"):
            shutil.copy(REPO / "extras" / "status" / name, bare / name)
        script = bare / "page_action.py"

        def run(request):
            return subprocess.run([sys.executable, str(script), "--workspace", str(self.root)], input=request, capture_output=True,
                                  text=True, env=dict(os.environ, GARRICK_JOBS_DIR=str(self.jobs))).stdout
        ok = run(json.dumps({"verb": "todo-done", "zone": "Work", "file": "Todo.md", "key": self.key("Invoice"), "op": "a19f3c80"}))
        self.assertEqual('{"ok": true, "say": "Done: Acme Corp: Invoice for September"}\n', ok)
        stale = run(json.dumps({"verb": "todo-done", "zone": "Work", "file": "Todo.md", "key": "0" * 16, "op": "a19f3c80"}))
        self.assertEqual('{"ok": false, "say": "that line has changed since the page was built; it rebuilds now, try again"}\n', stale)
        self.assertEqual('{"ok": false, "say": "unknown action"}\n', run('{"verb": "operations"}'))
        self.assertEqual('{"ok": false, "say": "not a request"}\n', run("nope"))
        self.assertEqual([], list(self.jobs.glob("operations.*")) + list(self.jobs.glob("op-*")))

    def test_the_degraded_replies_match_the_module_ones_apart_from_the_record(self):
        """Same workspace, the module present and then absent: the same verbs say the same thing when they save."""
        with mock.patch.object(pa, "ops_lib", return_value=None):
            old = pa.act(self.root, self.requests()["todo-add"], today=TODAY)
        new = self.run_script(dict(self.requests()["todo-add"], text="Call Dana"))
        self.assertEqual("Added to Inbox: Book the room", old)
        self.assertEqual("Added to Inbox: Call Dana", new["say"])

    def test_a_journal_that_cannot_be_written_stops_nothing_and_the_page_is_told(self):
        self.jobs.mkdir(parents=True)
        (self.jobs / "operations.jsonl").mkdir()                                  # a folder where the record should be
        done = subprocess.run([sys.executable, str(SCRIPT), "--workspace", str(self.root)], capture_output=True, text=True,
                              input=json.dumps(dict(self.requests()["todo-done"], op="a19f3c80")),
                              env=dict(os.environ, GARRICK_JOBS_DIR=str(self.jobs)))
        self.assertEqual('{"ok": true, "say": "Done: Acme Corp: Invoice for September"}\n', done.stdout)    # as it was, byte for byte
        refused = self.run_script({"verb": "todo-done", "zone": "Work", "file": "Todo.md", "key": "0" * 16})
        self.assertEqual({"ok": False, "say": "that line has changed since the page was built; it rebuilds now, try again"}, refused)
        reply = self.run_script({"verb": "operations"})
        self.assertEqual((True, False, []), (reply["ok"], reply["durable"], reply["ops"]))
        self.assertIn("not recoverable", reply["say"])

    def test_a_phase_that_cannot_be_written_stops_nothing(self):
        class Broken:
            def running(self):
                raise OSError("no space left")

            def phase(self, text):
                raise OSError("no space left")
        pa.CURRENT = Broken()
        try:
            self.assertEqual("Added to Inbox: Book the room", self.act(verb="todo-add", zone="Work", text="Book the room"))
        finally:
            pa.CURRENT = None
        self.assertEqual(("Work: added to Inbox, Book the room", ""), self.last_commit())


class TestFlag(ActionCase):
    """The actions were a preview, `page-actions`; released, they need no flag."""

    def test_a_leftover_flag_changes_nothing(self):
        write(self.root / "System" / "garrick-flags.json", json.dumps({"page-actions": False}))
        self.assertEqual("Added to Inbox: Book the room", self.act(verb="todo-add", zone="Work", text="Book the room"))
        (self.root / "System" / "garrick-flags.json").unlink()                        # no flags at all
        self.assertTrue(self.act(verb="todo-done", zone="Work", file="Todo.md", key=self.key("Invoice")).startswith("Done: "))

    def test_cmux_verbs_need_the_desk(self):
        real = pa.CMUX_EXTRA
        pa.CMUX_EXTRA = Path(self._tmp.name) / "no-cmux-extra"       # never the real desk
        try:
            # each verb in the shape the table declares for it: startup and
            # shutdown carry nothing, so they cannot be asked about a project
            for req in ({"verb": "open", "zone": "Nowhere", "project": "Acme Review"},
                        {"verb": "close", "zone": "Nowhere", "project": "Acme Review"},
                        {"verb": "startup"}, {"verb": "shutdown"}):
                with self.assertRaisesRegex(pa.Refused, "need the cmux extra", msg=req["verb"]):
                    pa.act(self.root, req)
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
        self.assertEqual({"ok": True, "say": "Added to Inbox: Book the room"}, plain(json.loads(out1)))
        self.assertEqual({"ok": True, "say": "Added to Inbox: Call Dana"}, plain(json.loads(out2)))
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
        real, pa.COMMIT_TIMEOUT = pa.COMMIT_TIMEOUT, 1
        try:
            t0 = time.time()
            with self.assertRaisesRegex(pa.Refused, "^not committed: the wall check was still running after 1 s and was "
                                        "stopped, so the note was put back as it was. Make the change again and commit "
                                        "it by hand: that commit waits for the check and goes through$"):
                self.act(verb="todo-done", zone="Work", file="Todo.md", key=self.key("Invoice"))
            self.assertLess(time.time() - t0, 15)
        finally:
            pa.COMMIT_TIMEOUT = real
        self.assertEqual(before, (self.work / "Todo.md").read_bytes())
        self.assertFalse((self.work / ".git" / "index.lock").exists())             # git took its lock away
        self.assertEqual("", git(self.work, "status", "--porcelain").strip())

    def test_a_slow_wall_check_outlasts_a_git_command(self):
        """A commit has COMMIT_TIMEOUT, however short the read-only calls' GIT_TIMEOUT."""
        self.hook("sleep 4\n")
        real = pa.GIT_TIMEOUT, pa.COMMIT_TIMEOUT
        pa.GIT_TIMEOUT, pa.COMMIT_TIMEOUT = 2, 60
        try:
            self.assertEqual("Done: Acme Corp: Invoice for September",
                             self.act(verb="todo-done", zone="Work", file="Todo.md", key=self.key("Invoice")))
        finally:
            pa.GIT_TIMEOUT, pa.COMMIT_TIMEOUT = real
        self.assertEqual(("Work: done, Acme Corp: Invoice for September", ""), self.last_commit())

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


FULL_BLOCK = """### Resume here

**Where it stands, 1 March 2026.** The first draft is out;
Dana has it.

| | |
|---|---|
| Live artifact | `Deliverables/260301 - Pricing memo.md` |
| Rebuild with | by hand |
| Next action | Wait for Dana's volumes |
| Keep in mind | The tier-two rate is a guess |
| Waiting on | Dana |
| Deadline | none |
"""


class TestCheckpointAndTheStack(ActionCase):
    """A hold rewrites Resume here without folding the checkpoint, because it
    has to take thirty seconds, so it rebases the block instead: the same items
    at the same time, against the block it just wrote. Back says one clause
    more when one is waiting."""

    AT = dt.datetime(2026, 10, 13, 14, 32)

    def setUp(self):
        super().setUp()
        self.lib = pa.checkpoint_lib(self.root)
        self.assertIsNotNone(self.lib, "the workspace's garrick_lib should carry the checkpoint primitives")

    def put(self, **kw):
        write(self.thread, fixtures.checkpoint(self.thread.read_text(), **kw))
        git(self.work, "commit", "-qam", "a checkpoint")
        return self.block()

    def block(self):
        return self.lib.read_checkpoint(self.thread.read_text())

    def marked(self, text):
        """The block from one marker to the other, and nothing around it."""
        start, end = self.lib.checkpoint_span(text)
        return text[start:end]

    def stale(self):
        text = self.thread.read_text()
        return self.lib.read_checkpoint(text)["base"] != self.lib.resume_hash(text)

    def hold(self, **answers):
        answers.setdefault("where", "Halfway through the tier-two volumes")
        answers.setdefault("next", "Fill in row 14 of the volume sheet")
        return pa.act(self.root, dict(verb="interrupt", zone="Work", project="Acme Review",
                                      thread="Pricing", **answers), now=self.AT)

    def test_a_hold_rebases_the_checkpoint_instead_of_leaving_it_stale(self):
        before = self.put()
        self.assertTrue(before["valid"])
        self.hold()
        after = self.block()
        self.assertTrue(after["valid"], after["why"])
        self.assertEqual(before["at"], after["at"])                         # the same time it covers
        self.assertEqual([i["line"] for i in before["items"]], [i["line"] for i in after["items"]])
        self.assertNotEqual(before["base"], after["base"])                  # against the block just written
        self.assertEqual(self.lib.resume_hash(self.thread.read_text()), after["base"])
        self.assertFalse(self.stale())
        self.assertIn("Interrupted 14:32", self.thread.read_text())
        self.assertEqual(("Acme Review, Pricing: interrupted", ""), self.last_commit())

    def test_the_hold_writes_the_rows_and_the_entry_around_it(self):
        self.put()
        self.hold(keep="Owen wants the lower rate")
        text = self.thread.read_text()
        self.assertLess(text.index("### Resume here"), text.index("### Checkpoint"))
        self.assertIn("| Next action | Fill in row 14 of the volume sheet |", text)
        self.assertIn("**13 October 2026.** Interrupted at 14:32.", text)   # below the rule, not in the block
        self.assertLess(text.index("<!-- /garrick-checkpoint -->"), text.index("**13 October 2026.**"))
        self.assertEqual(1, text.count("### Checkpoint"))

    def test_a_block_edited_by_hand_is_left_exactly_as_it_is(self):
        self.put()
        write(self.thread, self.thread.read_text().replace("dropping tier three", "dropping tier two"))
        git(self.work, "commit", "-qam", "a hand edit")
        before = self.thread.read_text()
        self.hold()
        after = self.thread.read_text()
        self.assertEqual(self.marked(before), self.marked(after))
        self.assertFalse(self.block()["valid"])                             # reported, never rewritten

    def test_a_thread_with_no_checkpoint_is_held_as_it_always_was(self):
        self.assertEqual("Held Acme Review, Pricing at 14:32", self.hold())
        self.assertIsNone(self.block())

    def test_back_says_one_clause_more_when_a_checkpoint_is_waiting(self):
        self.put()
        self.hold(keep="Owen wants the lower rate")
        said = pa.act(self.root, {"verb": "back"}, today=TODAY)
        self.assertTrue(said["say"].endswith("There's also an unwrapped checkpoint from 14:32."), said["say"])
        self.assertEqual("14:32", said["checkpoint"])
        self.assertIn("Keep in mind: Owen wants the lower rate.", said["say"])

    def test_back_says_nothing_of_one_that_cannot_be_read_and_nothing_at_all_without_one(self):
        self.hold()
        said = pa.act(self.root, {"verb": "back"}, today=TODAY)
        self.assertNotIn("checkpoint", said["say"])
        self.assertIsNone(said["checkpoint"])
        self.put()
        write(self.thread, self.thread.read_text().replace("dropping tier three", "dropping tier two"))
        self.hold()
        said = pa.act(self.root, {"verb": "back"}, today=TODAY)
        self.assertNotIn("checkpoint", said["say"])                         # never resumed from, so never offered
        self.assertIsNone(said["checkpoint"])

    def test_back_never_writes_the_note(self):
        self.put()
        self.hold()
        before = self.thread.read_bytes()
        pa.act(self.root, {"verb": "back"}, today=TODAY)
        self.assertEqual(before, self.thread.read_bytes())

    def test_without_the_library_the_hold_still_goes_through(self):
        self.put()
        with mock.patch.object(pa, "checkpoint_lib", lambda ws: None):
            self.assertEqual("Held Acme Review, Pricing at 14:32", self.hold())
            said = pa.act(self.root, {"verb": "back"}, today=TODAY)
        self.assertNotIn("checkpoint", said["say"])
        self.assertIn("Interrupted 14:32", self.thread.read_text())
        self.assertTrue(self.stale())        # the resume point moved and nothing rebased the block


class TestInterrupted(ActionCase):
    """Interrupted and Back (#32): the place saved in the note and committed,
    the order kept in an uncommitted stack, last in, first out."""

    AT = dt.datetime(2026, 10, 13, 14, 32)

    def setUp(self):
        super().setUp()
        self.sizing = self.work / "Birch Entry" / "Threads" / "Market Sizing" / "Market Sizing.md"
        write(self.sizing, self.sizing.read_text() + "\n---\n\n**1 March 2026.** Started.\n")
        git(self.work, "commit", "-qam", "rule")

    def stack_file(self):
        return self.root / "System" / "generated" / "interrupted.json"

    def stacked(self):
        return [e.get("thread") or e["project"] for e in json.loads(self.stack_file().read_text())["stack"]]

    def hold(self, thread="Pricing", project="Acme Review", at=None, **answers):
        answers.setdefault("where", "Halfway through the tier-two volumes")
        answers.setdefault("next", "Fill in row 14 of the volume sheet")
        return pa.act(self.root, dict(verb="interrupt", zone="Work", project=project, thread=thread, **answers),
                      now=at or self.AT)

    def test_interrupt_writes_the_place_and_commits(self):
        text = self.thread.read_text().replace("### Resume here\n\n**Where it stands, 1 March 2026.** Drafting.\n", FULL_BLOCK)
        write(self.thread, text)
        git(self.work, "commit", "-qam", "a full block")
        self.assertEqual("Held Acme Review, Pricing at 14:32",
                         self.hold(keep="Dana | Owen disagree on the rate", by="a call from Birch"))
        text = self.thread.read_text()
        self.assertIn("### Resume here\n\n**Interrupted 14:32, 13 October 2026.** Halfway through the tier-two volumes\n\n"
                      "| | |\n", text)
        self.assertNotIn("Where it stands", text)                          # one resume point, overwritten
        self.assertIn("| Next action | Fill in row 14 of the volume sheet |\n", text)
        self.assertIn("| Keep in mind | Dana \\| Owen disagree on the rate |\n", text)
        for kept in ("| Live artifact | `Deliverables/260301 - Pricing memo.md` |", "| Waiting on | Dana |", "| Deadline | none |"):
            self.assertIn(kept, text)
        self.assertIn("<Dated entries, newest first. Never edit an old one.>\n\n"
                      "**13 October 2026.** Interrupted at 14:32, by a call from Birch.\n\n**1 March 2026.** Started.", text)
        self.assertIn("\nstatus: active\n", text)
        self.assertIn("\nupdated: 2026-10-13\n", text)
        self.assertEqual(("Acme Review, Pricing: interrupted, by a call from Birch", ""), self.last_commit())
        self.assertEqual(["Pricing"], self.stacked())
        self.assertEqual({"where": "Interrupted 14:32, 13 October 2026. Halfway through the tier-two volumes",
                          "next": "Fill in row 14 of the volume sheet", "keep": "Dana | Owen disagree on the rate"},
                         pa.saved_lines(self.thread))

    def test_a_skipped_keep_in_mind_is_left_or_says_nothing(self):
        self.hold()                                                         # the fixture's block has no table yet
        text = self.thread.read_text()
        self.assertIn("**Interrupted 14:32, 13 October 2026.** Halfway through the tier-two volumes\n\n| | |\n|---|---|\n"
                      "| Next action | Fill in row 14 of the volume sheet |\n| Keep in mind | nothing |\n\n---\n", text)
        write(self.thread, self.thread.read_text().replace("| Keep in mind | nothing |", "| Keep in mind | the rate |"))
        git(self.work, "commit", "-qam", "kept")
        self.hold(where="Back on the volumes", keep="")
        self.assertIn("| Keep in mind | the rate |", self.thread.read_text())
        self.assertEqual(1, self.thread.read_text().count("**Interrupted"))

    def test_held_again_moves_to_the_top_once(self):
        self.hold()
        self.assertEqual("Held Birch Entry, Market Sizing at 15:00; 2 on the stack",
                         self.hold("Market Sizing", "Birch Entry", at=dt.datetime(2026, 10, 13, 15, 0)))
        self.hold(at=dt.datetime(2026, 10, 13, 15, 10))
        self.assertEqual(["Pricing", "Market Sizing"], self.stacked())
        self.assertEqual("2026-10-13T15:10", json.loads(self.stack_file().read_text())["stack"][0]["at"])

    def test_back_is_last_in_first_out_and_reads_the_lines_back(self):
        self.hold(keep="Owen wants the lower rate")
        self.hold("Market Sizing", "Birch Entry", where="Counting the shops", next="Call the council")
        before = self.last_commit()
        said = self.act(verb="back")
        self.assertEqual("Back to Birch Entry, Market Sizing. Interrupted 14:32, 13 October 2026. Counting the shops. "
                         "Next: Call the council.", said["say"])             # a Keep in mind of nothing goes unsaid
        self.assertEqual(("Zones/Work/Birch Entry/Threads/Market Sizing/Market Sizing.md", "Call the council", 1),
                         (said["path"], said["next"], said["left"]))
        said = self.act(verb="back")
        self.assertEqual("Acme Review, Pricing", said["name"])
        self.assertTrue(said["say"].endswith("Next: Fill in row 14 of the volume sheet. Keep in mind: Owen wants the lower rate."))
        self.assertEqual(before, self.last_commit())                        # back writes no note
        self.assertEqual([], self.stacked())

    def test_back_to_a_thread_takes_it_out_of_the_middle(self):
        for thread, project in (("Pricing", "Acme Review"), ("Market Sizing", "Birch Entry")):
            self.hold(thread, project)
        write(self.work / "Acme Review" / "Threads" / "Rates" / "Rates.md", thread_note("Acme Review", "Rates"))
        self.hold("Rates")
        said = self.act(verb="back", zone="Work", project="Birch Entry", thread="Market Sizing")
        self.assertEqual("Birch Entry, Market Sizing", said["name"])
        self.assertEqual(["Rates", "Pricing"], self.stacked())
        with self.assertRaisesRegex(pa.Refused, "Birch Entry, Market Sizing is not on the stack; open it instead"):
            self.act(verb="back", zone="Work", project="Birch Entry", thread="Market Sizing")

    def test_an_empty_stack_says_so_and_offers_the_latest_thread(self):
        write(self.sizing, self.sizing.read_text().replace("updated: 2026-03-01", "updated: 2026-10-01"))
        said = self.act(verb="back")
        self.assertEqual("Nothing is on the stack. The most recent live thread is Birch Entry, Market Sizing.", said["say"])
        self.assertEqual(("Work", "Birch Entry", "Market Sizing"), (said["offer"]["zone"], said["offer"]["project"],
                                                                    said["offer"]["thread"]))
        self.assertEqual({"say": "Nothing is on the stack.", "stack": []}, self.act(verb="stack"))

    def test_a_missing_or_broken_stack_is_empty(self):
        for broken in ("", "not json", "[1, 2]", '{"stack": 7}', '{"stack": [{"zone": "Work", "file": "Gone/Gone.md"}, 3]}'):
            write(self.stack_file(), broken)
            self.assertTrue(self.act(verb="back")["empty"], broken)
            self.assertEqual([], self.act(verb="stack")["stack"], broken)
        self.hold()
        self.assertEqual(["Pricing"], self.stacked())

    def test_the_stack_lists_and_close_for_the_day_leaves_it(self):
        self.hold()
        self.hold("Market Sizing", "Birch Entry", next="Call the council")
        listed = self.act(verb="stack")
        self.assertEqual("2 on the stack: Birch Entry, Market Sizing; Acme Review, Pricing.", listed["say"])
        self.assertEqual(["Call the council", "Fill in row 14 of the volume sheet"], [e["next"] for e in listed["stack"]])
        self.assertEqual(["Market Sizing", "Pricing"], self.stacked())      # listing changes nothing

    def test_park_and_unstack_take_it_off(self):
        self.hold()
        self.hold("Market Sizing", "Birch Entry")
        self.act(verb="park", zone="Work", file="Acme Review/Threads/Pricing/Pricing.md")
        self.assertEqual(["Market Sizing"], self.stacked())
        self.act(verb="park", zone="Work", project="Birch Entry")            # a parked project takes its threads
        self.assertEqual([], self.stacked())
        self.act(verb="wake", zone="Work", file="Acme Review/Threads/Pricing/Pricing.md")
        self.hold()
        self.assertEqual("Acme Review, Pricing is off the stack",
                         self.act(verb="unstack", zone="Work", project="Acme Review", thread="Pricing"))
        self.assertEqual("Acme Review, Pricing was not on the stack",
                         self.act(verb="unstack", zone="Work", project="Acme Review", thread="Pricing"))
        self.hold()
        self.assertEqual("Acme Review is off the stack", self.act(verb="unstack", zone="Work", project="Acme Review"))
        for bad in ({"project": "../Personal"}, {"project": "Acme Review", "thread": "a/b"}, {"zone": "Nope", "project": "X"}):
            with self.assertRaises(pa.Refused, msg=bad):
                pa.act(self.root, dict({"verb": "unstack", "zone": "Work"}, **bad))

    def test_a_note_gone_by_hand_leaves_the_stack(self):
        self.hold()
        self.hold("Market Sizing", "Birch Entry")
        shutil.rmtree(self.sizing.parent)                                  # deleted outside the page
        self.assertEqual(["Acme Review, Pricing"], [e["name"] for e in self.act(verb="stack")["stack"]])
        self.assertEqual("Acme Review, Pricing", self.act(verb="back")["name"])
        self.assertEqual([], self.stacked())                                # and gone from the file at the next change

    def test_refusals_change_nothing(self):
        before = self.thread.read_bytes()
        for req in ({"where": ""}, {"next": None}, {"where": 7}, {"where": "x" * 401}, {"by": "x" * 121},
                    {"thread": "Nope"}, {"thread": None}):
            with self.assertRaises(pa.Refused, msg=req):
                self.hold(**req)
        self.act(verb="park", zone="Work", file="Acme Review/Threads/Pricing/Pricing.md")
        with self.assertRaisesRegex(pa.Refused, "Acme Review, Pricing is parked; wake it first"):
            self.hold()
        write(self.sizing, thread_note("Birch Entry", "Market Sizing", status="done"))
        with self.assertRaisesRegex(pa.Refused, "is finished"):
            self.hold("Market Sizing", "Birch Entry")
        self.assertFalse(self.stack_file().exists())
        self.assertIn(b"**Where it stands, 1 March 2026.** Drafting.", before)

    def test_a_refused_commit_leaves_the_stack_alone(self):
        personal = self.root / "Zones" / "Personal"                       # the fixture's stand-in repository: every commit fails
        write(personal / "House" / "House.md", project_hub("Personal", "House", "", ["Roof"]))
        note = write(personal / "House" / "Threads" / "Roof" / "Roof.md", thread_note("House", "Roof"))
        before = note.read_bytes()
        with self.assertRaisesRegex(pa.Refused, "not committed, so nothing changed"):
            pa.act(self.root, {"verb": "interrupt", "zone": "Personal", "project": "House", "thread": "Roof",
                               "where": "On the gutters", "next": "Ring the roofer"}, now=self.AT)
        self.assertEqual(before, note.read_bytes())
        self.assertFalse(self.stack_file().exists())

    def test_the_reply_carries_the_lines_as_json(self):
        self.hold()
        done = subprocess.run([sys.executable, str(SCRIPT), "--workspace", str(self.root)], input='{"verb": "back"}',
                              capture_output=True, text=True)
        reply = json.loads(done.stdout)
        self.assertEqual((True, "Fill in row 14 of the volume sheet", "Acme Review/Threads/Pricing/Pricing.md"),
                         (reply["ok"], reply["next"], reply["file"]))
        self.assertTrue(reply["say"].startswith("Back to Acme Review, Pricing."))
        log = (self.jobs / "page-actions.log").read_text()
        self.assertNotIn("Fill in row 14", log)                              # the answers stay out of the log


class TestScript(ActionCase):
    def run_script(self, request, ws=None):
        return subprocess.run([sys.executable, str(SCRIPT), "--workspace", str(ws or self.root)], input=request,
                              capture_output=True, text=True)

    def test_one_line_of_json(self):
        done = self.run_script(json.dumps({"verb": "todo-done", "zone": "Work", "file": "Todo.md", "key": self.key("Invoice")}))
        self.assertEqual(0, done.returncode, done.stderr)
        self.assertEqual({"ok": True, "say": "Done: Acme Corp: Invoice for September"}, plain(json.loads(done.stdout)))
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
        reply = json.loads(buf.getvalue())
        self.assertEqual(("failed", "crashed", False), (reply["state"], reply["outcome"], reply["ok"]))
        self.assertEqual("That did not work: OSError: the disk went away. Check git status in Work before trying again.", reply["say"])
        self.assertTrue((self.jobs / "page-actions.log").read_text().rstrip().endswith(
            'todo-done zone="Work"  ->  refused: ' + reply["say"]))
        last = [json.loads(line) for line in (self.jobs / "operations.jsonl").read_text().splitlines()][-1]
        self.assertEqual(("failed", "crashed"), (last["state"], last["outcome"]))

    def test_a_fault_without_the_record_answers_as_it_did(self):
        import contextlib
        import io
        real, stdin = pa.act, sys.stdin

        def broken(ws, req, today=None):
            raise OSError("the disk went away")
        pa.act, sys.stdin = broken, io.StringIO(json.dumps({"verb": "todo-done", "zone": "Work"}))
        buf = io.StringIO()
        try:
            with mock.patch.object(pa, "ops_lib", return_value=None), contextlib.redirect_stdout(buf):
                code = pa.main(["--workspace", str(self.root)])
        finally:
            pa.act, sys.stdin = real, stdin
        self.assertEqual(1, code)
        self.assertEqual('{"ok": false, "say": "that did not work: OSError: the disk went away"}\n', buf.getvalue())
        self.assertTrue((self.jobs / "page-actions.log").read_text().rstrip().endswith(
            'todo-done zone="Work"  ->  refused: that did not work: OSError: the disk went away'))
        self.assertFalse((self.jobs / "operations.jsonl").exists())


class TestNotePreview(ActionCase):
    """Explore's Preview (#206): a note read and drawn, and opened in its own
    app, by its path from the workspace; only inside the zones and wikis, and
    nothing written either way."""

    NOTE = "Wikis/Knowledge/wiki/concepts/lead-times.md"
    TEXT = ("---\ntitle: Lead times\ntype: concept\nparties:\n  - acme\n  - birch\ntags: [freight, \"supply\"]\nsources:\n"
            "  first:\n    - nested\n---\n\n# Lead times\n\nHow long an order takes, from [[supply-chain-report|the report]] "
            "and [[wiki/concepts/resilience]].\n\n## Kinds\n\n- **Quoted**: what the supplier says\n- *Actual*: what arrived\n\n"
            "| Supplier | Weeks |\n|---|---:|\n| Acme Corp | 6 |\n\n```python\nweeks = 6 < 8\n```\n\n<script>alert(1)</script>\n")

    def setUp(self):
        super().setUp()
        write(self.root / self.NOTE, self.TEXT)

    def read(self, path):
        return self.act(verb="note-read", path=path)

    def test_a_note_is_drawn_with_its_properties_and_its_title(self):
        out = self.read(self.NOTE)
        self.assertEqual(("Read lead-times", "Lead times"), (out["say"], out["title"]))
        html = out["html"]
        self.assertTrue(html.startswith('<dl class="nv-props"><div><dt>type</dt><dd>concept</dd></div>'
                                        '<div><dt>parties</dt><dd>acme, birch</dd></div><div><dt>tags</dt><dd>freight, supply</dd></div>'), html)
        self.assertNotIn("<dt>title</dt>", html)             # it heads the preview
        self.assertNotIn("<dt>sources</dt>", html)           # a nested map is left out
        self.assertNotIn("nested", html)
        self.assertIn("<h1>Lead times</h1>", html)
        self.assertIn("<h2>Kinds</h2>", html)
        self.assertIn("<ul><li><b>Quoted</b>: what the supplier says</li><li><i>Actual</i>: what arrived</li></ul>", html)
        self.assertIn("<th>Supplier</th>", html)
        self.assertIn('<td style="text-align:right">6</td>', html)
        self.assertIn('<pre><code class="lang-python">weeks = 6 &lt; 8</code></pre>', html)
        self.assertIn("from the report and resilience.", html)              # a [[link]] is its words, never a link
        self.assertNotIn("[[", html)
        self.assertNotIn("<a ", html)
        self.assertNotIn("<script", html)                                   # what the note holds is text, escaped
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)

    def test_a_note_without_frontmatter_takes_its_name(self):
        out = self.read("Wikis/Knowledge/wiki/concepts/resilience.md")
        self.assertEqual("resilience", out["title"])
        self.assertEqual("<h1>Resilience</h1>", out["html"])
        write(self.root / "Zones" / "Work" / "Acme Review" / "Empty.md", "---\ntype: note\n---\n")
        out = self.read("Zones/Work/Acme Review/Empty.md")
        self.assertIn('<p class="nv-none">This note is empty.</p>', out["html"])

    def test_nothing_outside_the_zones_and_wikis(self):
        for path in ("System/context.md", "AGENTS.md", "/etc/hosts.md", str(self.root / self.NOTE), "Wikis/../System/context.md",
                     "Zones/Work/../../System/context.md", "Zones/./Work/Todo.md", "Zones//Work/Todo.md",
                     "Zones/Work/.git/notes.md", "Zones\\Work\\Todo.md", "Zones/Work/Todo.md\n", "", None, 3, ["Zones"]):
            with self.assertRaises(pa.Refused, msg=path) as said:
                self.read(path)
            self.assertNotIsInstance(said.exception, pa.Missing, path)

    def test_a_link_is_followed_and_must_stay_inside(self):
        outside = Path(self._tmp.name) / "elsewhere.md"
        write(outside, "# Not the workspace's\n")
        links = self.root / "Zones" / "Work" / "Acme Review"
        os.symlink(str(outside), str(links / "Away.md"))
        os.symlink(str(self.root / "System" / "context.md"), str(links / "Context.md"))
        os.symlink(str(self.root / self.NOTE), str(links / "Lead times.md"))                # into a wiki: read
        for name in ("Away.md", "Context.md"):
            with self.assertRaises(pa.Refused, msg=name) as said:
                self.read("Zones/Work/Acme Review/" + name)
            self.assertIn("leads outside the zones and wikis", str(said.exception))
        self.assertEqual("Lead times", self.read("Zones/Work/Acme Review/Lead times.md")["title"])
        os.symlink(str(self.root / "System"), str(links / "System"))                        # a folder that leads out
        with self.assertRaises(pa.Refused):
            self.read("Zones/Work/Acme Review/System/context.md")

    def test_only_a_markdown_note(self):
        write(self.root / "Zones" / "Work" / "Acme Review" / "Sources" / "rates.csv", "a,b\n")
        os.symlink(str(self.root / "Zones" / "Work" / "Acme Review" / "Sources" / "rates.csv"),
                   str(self.root / "Zones" / "Work" / "Acme Review" / "Rates.md"))
        for path in ("Zones/Work/Acme Review/Sources/rates.csv", "Zones/Work/Acme Review/Rates.md", "Zones/Work/Acme Review"):
            with self.assertRaises(pa.Refused, msg=path) as said:
                self.read(path)
            self.assertIn("Garrick does not preview it", str(said.exception))

    def test_a_note_that_is_not_there_says_so_and_offers_no_open(self):
        with self.assertRaises(pa.Missing) as said:
            self.read("Wikis/Meetings/wiki/people/rowan-ash.md")
        self.assertEqual("rowan-ash is not there any more: it was moved, renamed or deleted after the page was built",
                         str(said.exception))
        out, _, why = pa.perform(self.root, {"verb": "note-read", "path": "Wikis/Meetings/wiki/people/rowan-ash.md"})
        self.assertEqual({"ok": False, "say": why, "missing": True}, out)
        out, _, _ = pa.perform(self.root, {"verb": "note-read", "path": "System/context.md"})
        self.assertNotIn("missing", out)                    # refused, not gone: the page keeps its Open

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root reads a file whatever its mode")
    def test_a_note_that_cannot_be_read_says_why(self):
        note = self.root / self.NOTE
        note.chmod(0)
        try:
            with self.assertRaises(pa.Refused) as said:
                self.read(self.NOTE)
        finally:
            note.chmod(0o644)
        self.assertEqual("lead-times could not be read: permission denied", str(said.exception))
        note.write_bytes(b"# Rates\n\n\xff\xfe caf\xe9\n")
        with self.assertRaises(pa.Refused) as said:
            self.read(self.NOTE)
        self.assertEqual("lead-times could not be read: it is not text Garrick can read (UTF-8)", str(said.exception))

    def test_a_note_too_large_is_left_to_its_own_app(self):
        (self.root / self.NOTE).write_text("# Big\n\n" + "word " * (pa.NOTE_MAX // 5), encoding="utf-8")
        with self.assertRaises(pa.Refused) as said:
            self.read(self.NOTE)
        self.assertEqual("lead-times is too large to preview here (400 KB); open it in its own app", str(said.exception))
        self.assertNotIsInstance(said.exception, pa.Missing)

    def test_only_the_path_is_taken(self):
        with self.assertRaises(pa.Refused) as said:
            self.act(verb="note-read", path=self.NOTE, zone="Work")
        self.assertEqual("note-read takes no zone field", str(said.exception))
        with self.assertRaises(pa.Refused):
            self.act(verb="note-open", path=self.NOTE, app="TextEdit")

    def test_open_hands_the_note_to_the_macs_own_app(self):
        with mock.patch.object(pa, "open_path") as opened:               # never this Mac's own `open`
            self.assertEqual("Opened lead-times", self.act(verb="note-open", path=self.NOTE))
            opened.assert_called_once_with((self.root / self.NOTE).resolve())
            for path in ("System/context.md", "Zones/Work/../../AGENTS.md", "Zones/Work/Acme Review/Sources/.gitkeep"):
                with self.assertRaises(pa.Refused, msg=path):
                    self.act(verb="note-open", path=path)
            with self.assertRaises(pa.Missing):
                self.act(verb="note-open", path="Wikis/Meetings/wiki/people/rowan-ash.md")
            self.assertEqual(1, opened.call_count)

    def test_open_runs_the_opener_with_the_file(self):
        stub, log = Path(self._tmp.name) / "open", Path(self._tmp.name) / "opened"
        write(stub, '#!/bin/sh\nprintf "%s\\n" "$@" >> "$OPEN_LOG"\n')
        stub.chmod(0o755)
        with mock.patch.dict(os.environ, {"GARRICK_OPEN": str(stub), "OPEN_LOG": str(log)}):
            self.act(verb="note-open", path=self.NOTE)
        self.assertEqual(str((self.root / self.NOTE).resolve()) + "\n", log.read_text())

    def test_through_the_script_as_a_host_sends_it(self):
        def run(req):
            done = subprocess.run([sys.executable, str(SCRIPT), "--workspace", str(self.root)], capture_output=True, text=True,
                                  input=json.dumps(req), timeout=60)
            return json.loads(done.stdout)
        reply = run({"verb": "note-read", "path": self.NOTE})
        self.assertTrue(reply["ok"], reply)
        self.assertEqual("Lead times", reply["title"])
        self.assertIn("<h2>Kinds</h2>", reply["html"])
        gone = run({"verb": "note-read", "path": "Zones/Work/Acme Review/Gone.md"})
        self.assertEqual((False, True), (gone["ok"], gone["missing"]))
        log = (self.jobs / "page-actions.log").read_text()
        self.assertIn('note-read path="%s"  ->  ok: Read lead-times' % self.NOTE, log)      # the sentence, never the note
        self.assertNotIn("Kinds", log)
        self.assertEqual("", git(self.work, "status", "--porcelain").strip())       # nothing written


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
