"""The wrap as one command (#645): the assistant writes the judgment, tools/wrap.py does the transaction.

    cd tests && python3 -m unittest test_wrap_tool

Every case builds a small workspace of three invented zones (two walled, one open), puts the real wall check
in each zone's repository as its hook, and runs the tool in this process, with a fake home folder.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

import fixtures  # noqa: E402
from fixtures import GIT_ENV, HAVE_GIT, commit_all, git, write  # noqa: E402
from zone_fixture import build  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "template" / "System" / "tools"
TODAY = datetime.date(2026, 11, 22)
sys.path.insert(0, str(TOOLS))
import wrap  # noqa: E402
import wrap_lock as wl  # noqa: E402

NOTE = textwrap.dedent("""\
    ---
    title: %(t)s
    type: thread
    project: "[[%(p)s]]"
    party: %(party)s
    status: %(status)s
    created: 2026-03-01
    updated: 2026-03-01
    ---

    # %(t)s

    A fictional thread.

    ## State of play

    ### Resume here

    **Where it stands, 1 March 2026.** Drafting.

    | | |
    |---|---|
    | Live artifact | none |
    | Rebuild with | none |
    | Next action | open the sheet |
    | Keep in mind | nothing |
    | Waiting on | nobody |
    | Deadline | not given |

    ---

    **1 March 2026.** Started.
    """)

CASES = {"Work": ("Northwind", "Pricing", "acme"), "Home": ("Garden", "Beds", "jo"), "Ventures": ("Orchard", "Drafts", "cedar")}


def note_text(project, thread, party, status="active"):
    return NOTE % {"t": thread, "p": project, "party": party, "status": status}


def payload(zone="Work", **over):
    project, thread, _ = CASES[zone]
    data = {
        "zone": zone, "project": project, "thread": thread,
        "resume": {"stands": "The sheet is drafted and the volumes are with the buyer.",
                   "rows": {"Live artifact": "none", "Rebuild with": "none",
                            "Next action": "open the sheet and fill in the tier-two volume",
                            "Keep in mind": "nothing", "Waiting on": "the buyer", "Deadline": "not given"}},
        "entry": "Sent the draft. Waiting on the volumes.",
        "message": "%s, %s: draft sent; waiting on volumes" % (project, thread),
    }
    data.update(over)
    return data


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name).resolve()
        self.base = base
        self.root = base / "Workspace"
        self.home = base / "home"
        (self.home / ".claude" / "projects" / "ws" / "memory").mkdir(parents=True)
        env = mock.patch.dict(os.environ, dict(GIT_ENV, HOME=str(self.home)))
        env.start()
        self.addCleanup(env.stop)
        build(self.root)
        tools = self.root / "System" / "tools"
        tools.mkdir(parents=True, exist_ok=True)
        for name in ("check.py", "garrick_lib.py", "wrap.py", "wrap_lock.py", "history.py", "work.py"):
            shutil.copy2(TOOLS / name, tools / name)
        shutil.copytree(str(REPO / "template" / "System" / "skills" / "todo"), str(self.root / "System" / "skills" / "todo"))
        for zone, (project, thread, party) in CASES.items():
            z = self.root / "Zones" / zone
            write(z / project / "Threads" / thread / (thread + ".md"), note_text(project, thread, party))
            shutil.rmtree(z / ".git", ignore_errors=True)
            git(z, "init", "-q")
            fixtures.install_wall_hook(z)
            commit_all(z, "start")
        self.work = self.root / "Zones" / "Work"
        self.thread = self.work / "Northwind" / "Threads" / "Pricing" / "Pricing.md"

    def run_wrap(self, data=None, **kw):
        return wrap.run(self.root, data if data is not None else payload(), today=TODAY, **kw)

    def head(self, zone="Work"):
        return git(self.root / "Zones" / zone, "rev-parse", "HEAD").strip()

    def count(self, zone="Work"):
        return int(git(self.root / "Zones" / zone, "rev-list", "--count", "HEAD").strip())

    def clean(self, zone="Work"):
        return git(self.root / "Zones" / zone, "status", "--porcelain", "--untracked-files=all").strip() == ""

    def generated(self, suffix):
        return sorted((self.root / "System" / "generated").glob("wrap-*" + suffix)) if (self.root / "System" / "generated").is_dir() else []


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class Saved(Base):
    def test_a_wrap_is_saved_and_committed_in_its_zone_only(self):
        heads = {z: self.head(z) for z in CASES}
        got = self.run_wrap()
        self.assertEqual("saved", got["outcome"], got)
        self.assertEqual("Saved: Northwind, Pricing is wrapped.", got["say"])
        self.assertEqual(heads["Home"], self.head("Home"))                  # a repository it did not change gets no commit
        self.assertEqual(heads["Ventures"], self.head("Ventures"))
        self.assertEqual(2, self.count("Work"))
        self.assertTrue(self.clean())
        self.assertEqual(["Northwind/Threads/Pricing/Pricing.md"], got["files"])
        text = self.thread.read_text(encoding="utf-8")
        self.assertIn("**Where it stands, 22 November 2026.** The sheet is drafted", text)
        self.assertIn("| Next action | open the sheet and fill in the tier-two volume |", text)
        self.assertIn("updated: 2026-11-22", text)
        self.assertLess(text.index("**22 November 2026.** Sent the draft."), text.index("**1 March 2026.** Started."))
        self.assertEqual(1, text.count("### Resume here"))
        self.assertEqual("Northwind, Pricing: draft sent; waiting on volumes", git(self.work, "log", "-1", "--format=%s").strip())

    def test_the_lock_is_gone_and_the_finish_record_is_written_after_the_commit(self):
        self.run_wrap()
        rel = self.thread.relative_to(self.root).as_posix()
        self.assertFalse(wl.lock_path(self.root, rel).exists())
        self.assertIsNotNone(wl.finished(wl.done_path(self.root, rel)))

    def test_todo_lines_are_added_ticked_and_archived_in_the_same_commit(self):
        write(self.work / "Todo.md", "# Work: open actions\n\n## Inbox\n\n- [ ] [[<Thread>]]: <action> 📅 <YYYY-MM-DD>\n- [ ] [[Pricing]]: send Dana the sheet 📅 2026-12-01\n"
              "- [x] [[Pricing]]: old one ✅ 2026-11-01\n\n## Done\n")
        commit_all(self.work, "todo")
        start = self.count()
        got = self.run_wrap(payload(todo={"add": ["[[Pricing]]: fill in the tier-two volume 📅 2026-11-25"], "tick": ["send Dana the sheet"]}))
        self.assertEqual("saved", got["outcome"], got)
        todo = (self.work / "Todo.md").read_text(encoding="utf-8")
        self.assertNotIn("<action>", todo)                                   # the example goes with the first real action
        self.assertIn("- [ ] [[Pricing]]: fill in the tier-two volume 📅 2026-11-25", todo)
        self.assertIn("- [x] [[Pricing]]: send Dana the sheet 📅 2026-12-01 ✅ 2026-11-22", todo)
        self.assertNotIn("old one", todo)                                    # ticked before today: archived
        self.assertIn("old one", (self.work / "archive" / "Todo-2026.md").read_text(encoding="utf-8"))
        self.assertTrue(self.clean())
        self.assertEqual(start + 1, self.count())                            # one commit for all of it

    def test_a_line_that_is_already_open_is_not_added_twice(self):
        write(self.work / "Todo.md", "# Work: open actions\n\n## Inbox\n\n- [ ] [[Pricing]]: fill in the volume 📅 2026-12-01\n\n## Done\n")
        commit_all(self.work, "todo")
        got = self.run_wrap(payload(todo={"add": ["[[Pricing]]: fill in the volume"]}))
        self.assertEqual("saved", got["outcome"])
        self.assertEqual(1, (self.work / "Todo.md").read_text(encoding="utf-8").count("fill in the volume"))

    def test_a_tick_that_names_no_line_or_two_fails_and_writes_nothing(self):
        write(self.work / "Todo.md", "# Work: open actions\n\n## Inbox\n\n- [ ] [[Pricing]]: send the sheet\n- [ ] [[Pricing]]: send the memo\n\n## Done\n")
        commit_all(self.work, "todo")
        before = self.thread.read_text(encoding="utf-8")
        for words in ("send", "call the buyer"):
            got = self.run_wrap(payload(todo={"tick": [words]}))
            self.assertEqual("failed", got["outcome"], words)
            self.assertEqual(before, self.thread.read_text(encoding="utf-8"))
            self.assertTrue(self.clean())

    def test_older_entries_go_to_history_and_are_committed_with_the_note(self):
        old = "".join("**%d March 2026.** An old entry %d.\n\n" % (d, d) for d in range(2, 9))
        text = self.thread.read_text(encoding="utf-8") + "\n" + old
        write(self.thread, text)
        commit_all(self.work, "old entries")
        got = self.run_wrap()
        self.assertEqual("saved", got["outcome"], got)
        history = list((self.thread.parent / "history").glob("*.md"))
        self.assertEqual(1, len(history))
        self.assertTrue(self.clean())
        self.assertTrue(any("/history/" in f for f in got["files"]))

    def test_a_project_that_keeps_its_resume_point_in_its_hub_is_wrapped_there(self):
        hub = self.work / "Northwind" / "Northwind.md"
        text = hub.read_text(encoding="utf-8")
        shutil.rmtree(self.work / "Northwind" / "Threads")
        write(hub, text + "\n## State of play\n\n" + NOTE.split("## State of play\n\n", 1)[1])
        commit_all(self.work, "one job")
        got = self.run_wrap({k: v for k, v in payload().items() if k != "thread"})
        self.assertEqual("saved", got["outcome"], got)
        self.assertEqual("Saved: Northwind is wrapped.", got["say"])
        self.assertIn("**Where it stands, 22 November 2026.**", hub.read_text(encoding="utf-8"))

    def test_the_note_is_found_by_one_function(self):
        self.assertEqual(self.thread, wrap.resume_note(self.root, "Work", "Northwind", "Pricing"))
        self.assertIsNone(wrap.resume_note(self.root, "Work", "Northwind", "Nothing"))

    def test_a_heading_has_no_resume_point_and_is_not_wrapped(self):
        hub = self.work / "Northwind" / "Northwind.md"
        write(hub, hub.read_text(encoding="utf-8").replace("status: active", "status: active\nlayout: thread-first") + "\n## State of play\n\n### Resume here\n\nx\n")
        shutil.rmtree(self.work / "Northwind" / "Threads")
        commit_all(self.work, "a heading")
        got = self.run_wrap({k: v for k, v in payload().items() if k != "thread"})
        self.assertEqual("failed", got["outcome"], got)
        self.assertTrue(self.clean())

    def test_a_note_with_no_rule_gets_one(self):
        text = self.thread.read_text(encoding="utf-8").split("\n---\n\n**1 March")[0] + "\n"
        write(self.thread, text)
        commit_all(self.work, "no rule")
        self.assertEqual("saved", self.run_wrap()["outcome"])
        self.assertIn("\n---\n\n**22 November 2026.** Sent", self.thread.read_text(encoding="utf-8"))


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class Checkpoint(Base):
    def test_a_note_with_a_checkpoint_needs_it_folded_first(self):
        text = fixtures.checkpoint(self.thread.read_text(encoding="utf-8"))
        write(self.thread, text)
        commit_all(self.work, "checkpoint")
        got = self.run_wrap()
        self.assertEqual("failed", got["outcome"])
        self.assertIn("checkpoint", got["say"])
        self.assertEqual(text, self.thread.read_text(encoding="utf-8"))
        done = self.run_wrap(payload(checkpoint="folded"))
        self.assertEqual("saved", done["outcome"], done)
        after = self.thread.read_text(encoding="utf-8")
        self.assertNotIn("garrick-checkpoint", after)
        self.assertNotIn("### Checkpoint", after)
        self.assertEqual(1, after.count("### Resume here"))


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class Refusals(Base):
    """An input the tool will not take, and the outcomes that end in nothing written."""

    def assert_nothing_written(self, got, outcome="failed"):
        self.assertEqual(outcome, got["outcome"], got)
        self.assertTrue(self.clean())
        self.assertEqual(1, self.count())
        self.assertEqual([], self.generated(".lock"))
        self.assertEqual([], self.generated(".done"))

    def test_inputs_it_will_not_take_fail_with_nothing_written(self):
        good = payload()
        bad = {
            "an unknown key": dict(good, extra=1),
            "a missing key": {k: v for k, v in good.items() if k != "entry"},
            "a zone that climbs": dict(good, zone="../Home"),
            "a project that climbs": dict(good, project="../Northwind"),
            "a thread that climbs": dict(good, thread="../../Other"),
            "a thread in the scrap folders": dict(good, thread="_scrap"),
            "a row missing": dict(good, resume={"stands": "x", "rows": {"Next action": "x"}}),
            "a row of two lines": dict(good, resume={"stands": "x", "rows": dict(good["resume"]["rows"], **{"Keep in mind": "a\nb"})}),
            "an empty row": dict(good, resume={"stands": "x", "rows": dict(good["resume"]["rows"], **{"Waiting on": " "})}),
            "an entry that is a heading": dict(good, entry="ok\n## Not here"),
            "an entry that is a rule": dict(good, entry="ok\n---\nmore"),
            "a todo key": dict(good, todo={"add": [], "drop": ["x"]}),
            "a long todo line": dict(good, todo={"add": ["x" * 300]}),
            "a lock word": dict(good, lock="steal"),
            "a checkpoint word": dict(good, checkpoint="yes"),
            "a thread that is not there": dict(good, thread="Nope"),
        }
        for what, data in bad.items():
            got = self.run_wrap(data)
            self.assert_nothing_written(got)
        self.assertTrue(all(self.clean(z) for z in CASES))

    def test_a_finished_or_parked_thread_is_not_wrapped(self):
        for status in ("done", "parked"):
            write(self.thread, note_text("Northwind", "Pricing", "acme", status))
            commit_all(self.work, status)
            got = self.run_wrap()
            self.assertEqual("failed", got["outcome"])
            self.assertIn(status, got["say"])

    def test_a_wrap_already_running_is_not_started_again_and_its_lock_stays(self):
        rel = self.thread.relative_to(self.root).as_posix()
        self.assertTrue(wl.start(self.root, rel))
        got = self.run_wrap()
        self.assertEqual("failed", got["outcome"])
        self.assertIn("already running", got["say"])
        self.assertTrue(wl.running(wl.lock_path(self.root, rel)))
        self.assertTrue(self.clean())

    def test_a_lock_the_band_took_is_released_by_the_wrap(self):
        rel = self.thread.relative_to(self.root).as_posix()
        self.assertTrue(wl.start(self.root, rel))
        got = self.run_wrap(payload(lock="held"))
        self.assertEqual("saved", got["outcome"], got)
        self.assertFalse(wl.lock_path(self.root, rel).exists())
        self.assertIsNotNone(wl.finished(wl.done_path(self.root, rel)))

    def test_a_held_lock_is_released_when_the_wrap_fails_before_it_starts(self):
        rel = self.thread.relative_to(self.root).as_posix()
        good = payload(lock="held")
        cases = {
            "a parked thread": (lambda: write(self.thread, note_text("Northwind", "Pricing", "acme", "parked")), good),
            "a missing key": (lambda: None, {k: v for k, v in good.items() if k != "entry"}),
            "an unknown key": (lambda: None, dict(good, extra=1)),
            "an unfolded checkpoint": (lambda: write(self.thread, fixtures.checkpoint(note_text("Northwind", "Pricing", "acme"))), good),
        }
        for what, (setup, data) in cases.items():
            write(self.thread, note_text("Northwind", "Pricing", "acme"))
            setup()
            commit_all(self.work, what)
            self.assertTrue(wl.start(self.root, rel))
            got = self.run_wrap(data)
            self.assertEqual("failed", got["outcome"], (what, got))
            self.assertFalse(wl.lock_path(self.root, rel).exists(), what)
            self.assertEqual([], self.generated(".done"), what)

    def test_the_hook_refusal_is_the_receipt_and_the_wrap_is_put_back(self):
        before = self.thread.read_text(encoding="utf-8")
        wl.start(self.root, "Zones/Work/Northwind/Threads/Pricing/Pricing.md")
        wl.end(self.root, "Zones/Work/Northwind/Threads/Pricing/Pricing.md")      # an earlier wrap's record
        earlier = wl.finished(wl.done_path(self.root, "Zones/Work/Northwind/Threads/Pricing/Pricing.md"))
        data = payload(entry="Sent it. See [[260311-home-call]].")        # a Meetings page of another walled zone
        got = self.run_wrap(data)
        self.assertEqual("refused", got["outcome"], got)
        self.assertTrue(got["say"].startswith("Refused: "))
        self.assertEqual(before, self.thread.read_text(encoding="utf-8"))
        self.assertTrue(self.clean())
        self.assertEqual(1, self.count())
        self.assertEqual([], self.generated(".lock"))
        self.assertEqual(earlier, wl.finished(wl.done_path(self.root, "Zones/Work/Northwind/Threads/Pricing/Pricing.md")))   # no new record

    def test_another_session_moving_the_repository_is_a_conflict_and_nothing_is_committed(self):
        before = self.thread.read_text(encoding="utf-8")

        def other_session():
            write(self.work / "Other.md", "# Somebody else's note\n")
            git(self.work, "add", "--", "Other.md")
            git(self.work, "-c", "commit.gpgsign=false", "-c", "core.hooksPath=" + os.devnull, "commit", "-q", "-m", "other")
        got = self.run_wrap(before_commit=other_session)
        self.assertEqual("conflict", got["outcome"], got)
        self.assertEqual(before, self.thread.read_text(encoding="utf-8"))
        self.assertEqual(2, self.count())                                   # theirs, and none of the wrap's
        self.assertEqual("other", git(self.work, "log", "-1", "--format=%s").strip())
        self.assertEqual([], self.generated(".lock"))                       # released with --abandon
        self.assertEqual([], self.generated(".done"))
        self.assertEqual("saved", self.run_wrap()["outcome"])               # the next run starts from the note as it was

    def test_the_note_changing_under_the_wrap_is_a_conflict(self):
        got = self.run_wrap(before_commit=lambda: write(self.thread, self.thread.read_text(encoding="utf-8") + "\nA hand edit.\n"))
        self.assertEqual("conflict", got["outcome"], got)
        self.assertEqual([], self.generated(".done"))

    def test_another_sessions_file_in_archive_or_history_stays_out_of_the_commit(self):
        old = "".join("**%d March 2025.** An old entry %d.\n\n" % (d, d) for d in range(2, 9))
        write(self.thread, self.thread.read_text(encoding="utf-8") + "\n" + old)
        write(self.work / "Todo.md", "# Work: open actions\n\n## Inbox\n\n- [x] [[Pricing]]: old one ✅ 2026-11-01\n\n## Done\n")
        commit_all(self.work, "old entries")
        write(self.work / "archive" / "Theirs.md", "# somebody else's\n")
        write(self.thread.parent / "history" / "Theirs.md", "# somebody else's\n")
        got = self.run_wrap()
        self.assertEqual("saved", got["outcome"], got)
        self.assertTrue(any(f.startswith("archive/Todo-2026") for f in got["files"]), got["files"])
        self.assertTrue(any("history/Pricing history" in f for f in got["files"]), got["files"])
        self.assertFalse(any("Theirs" in f for f in got["files"]), got["files"])
        left = git(self.work, "status", "--porcelain", "--untracked-files=all")
        self.assertIn("archive/Theirs.md", left)
        self.assertIn("history/Theirs.md", left)

    def test_other_staged_files_are_never_swept_into_the_commit(self):
        write(self.work / "Stray.md", "# stray\n")
        git(self.work, "add", "--", "Stray.md")
        got = self.run_wrap()
        self.assertEqual("failed", got["outcome"], got)
        self.assertEqual(1, self.count())
        self.assertIn("Stray.md", git(self.work, "diff", "--cached", "--name-only"))      # still theirs, still staged


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class Links(Base):
    """Todo.md, archive/ and history/ that lead out of the zone are refused before the first write."""

    def other(self):
        return self.root / "Zones" / "Home"

    def check(self, link, target, **over):
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.exists() or link.is_symlink():
            link.unlink() if link.is_file() or link.is_symlink() else shutil.rmtree(link)
        link.symlink_to(target)
        commit_all(self.work, "a link")
        before = self.thread.read_text(encoding="utf-8")
        other = tree(self.root / "Zones" / "Home")
        got = self.run_wrap(payload(todo={"add": ["[[Pricing]]: a new one"]}, **over))
        self.assertEqual("failed", got["outcome"], got)
        self.assertEqual(before, self.thread.read_text(encoding="utf-8"))
        self.assertEqual(other, tree(self.root / "Zones" / "Home"))
        self.assertTrue(self.clean("Home"))
        self.assertEqual([], self.generated(".lock"))

    def test_a_todo_that_is_a_link_into_another_zone(self):
        self.check(self.work / "Todo.md", self.other() / "Todo.md")

    def test_an_archive_folder_that_is_a_link_into_another_zone(self):
        self.check(self.work / "archive", self.other())

    def test_a_history_folder_that_is_a_link_into_another_zone(self):
        old = "".join("**%d March 2025.** An old entry %d.\n\n" % (d, d) for d in range(2, 9))
        write(self.thread, self.thread.read_text(encoding="utf-8") + "\n" + old)
        self.check(self.thread.parent / "history", self.other())

    def test_a_link_inside_the_zone_is_fine(self):
        real = self.work / "Real"
        real.mkdir()
        (self.work / "archive").symlink_to(real)
        commit_all(self.work, "a link inside")
        self.assertEqual("saved", self.run_wrap()["outcome"])


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class Memory(Base):
    def entry(self, name="thread.md"):
        return self.home / ".claude" / "projects" / "ws" / "memory" / name

    def text(self):
        return "Northwind, Pricing (Work zone). Resume from Zones/Work/Northwind/Threads/Pricing/Pricing.md, the Resume here block."

    def test_the_tool_builds_the_pointer_and_writes_it_with_its_origin(self):
        before = tree(self.base)
        got = self.run_wrap(payload(memory={"path": str(self.entry())}))
        self.assertEqual("saved", got["outcome"], got)
        body = self.entry().read_text(encoding="utf-8")
        self.assertIn("source: file:Zones/Work/Northwind/Threads/Pricing/Pricing.md", body)
        self.assertIn("created: 2026-11-22", body)
        self.assertIn(self.text(), body)
        self.assertEqual(set(), outside_allowed(before, tree(self.base), self.root, self.entry()))

    def test_free_text_for_the_pointer_is_an_unknown_key(self):
        before = tree(self.base)
        got = self.run_wrap(payload(memory={"path": str(self.entry()), "text": "Acme wants 12% royalty. Zones/Work/Northwind/Threads/Pricing/Pricing.md"}))
        self.assertEqual("failed", got["outcome"], got)
        self.assertEqual(before, tree(self.base))
        self.assertFalse(self.entry().exists())

    def test_a_pointer_the_tool_wrote_is_left_as_it_is(self):
        self.run_wrap(payload(memory={"path": str(self.entry())}))
        first = self.entry().read_bytes()
        self.assertEqual("saved", self.run_wrap(payload(memory={"path": str(self.entry())}))["outcome"])
        self.assertEqual(first, self.entry().read_bytes())

    def test_a_file_that_is_not_a_pointer_the_tool_wrote_is_never_rewritten(self):
        for old in ("---\nsource: user\ncreated: 2026-10-01\n---\nMine.\n", "Old pointer without keys.\n"):
            write(self.entry(), old)
            before = tree(self.base)
            got = self.run_wrap(payload(memory={"path": str(self.entry())}))
            self.assertEqual("failed", got["outcome"], got)
            self.assertEqual(old, self.entry().read_text(encoding="utf-8"))
            self.assertEqual(before, tree(self.base))

    def test_a_memory_path_outside_the_assistants_memory_roots_writes_nothing(self):
        (self.home / "Documents" / "memory").mkdir(parents=True)
        (self.home / ".ssh" / "memory").mkdir(parents=True)
        (self.home / ".codex" / "memories").mkdir(parents=True)
        (self.home / ".claude" / "projects" / "ws" / "notes").mkdir(parents=True)
        real = self.base / "elsewhere"
        real.mkdir()
        write(real / "data.txt", "keep\n")
        link = self.entry("link.md")
        link.symlink_to(real / "data.txt")
        before = tree(self.base)
        elsewhere = {
            "the workspace": self.root / "Zones" / "Work" / "Northwind" / "memory" / "x.md",
            "a system file": self.root / "System" / "rules.md",
            "the home folder": self.home / "x.md",
            "another folder": self.base / "other" / "memory" / "x.md",
            "a memory folder of any other program": self.home / "Documents" / "memory" / "x.md",
            "a hidden one": self.home / ".ssh" / "memory" / "x.md",
            "codex, which documents none": self.home / ".codex" / "memories" / "x.md",
            "a claude project folder that is not memory": self.home / ".claude" / "projects" / "ws" / "notes" / "x.md",
            "deeper than an entry": self.entry("sub") / "x.md",
            "the index": self.entry("MEMORY.md"),
            "not markdown": self.entry("x.txt"),
            "climbing out": Path(str(self.entry().parent) + "/../../x.md"),
            "relative": Path("memory/x.md"),
            "a link to another file": link,
        }
        for what, path in elsewhere.items():
            got = self.run_wrap(payload(memory={"path": str(path)}))
            self.assertEqual("failed", got["outcome"], (what, got))
        self.assertEqual("keep\n", (real / "data.txt").read_text())
        self.assertEqual(before, tree(self.base))


def tree(base: Path) -> dict:
    out = {}
    for p in sorted(Path(base).rglob("*")):
        if ".git" in p.parts or not p.is_file() or p.name == ".wrap-start.lock" or "walls" in p.parts:   # the hook's own refusal log is its own
            continue
        out[str(p)] = hashlib.sha1(p.read_bytes()).hexdigest()
    return out


def outside_allowed(before: dict, after: dict, root: Path, memory: Path) -> set:
    """Files that changed that a wrap may not change: anything but the thread note, its zone's Todo.md and archive,
    the history files beside the note, the records in System/generated/ and the named memory file."""
    changed = {p for p in set(before) | set(after) if before.get(p) != after.get(p)}
    ok_prefix = (str(root / "Zones" / "Work" / "Northwind" / "Threads" / "Pricing"),
                 str(root / "Zones" / "Work" / "archive"), str(root / "System" / "generated"))
    ok_files = {str(root / "Zones" / "Work" / "Todo.md"), str(memory)}
    return {p for p in changed if p not in ok_files and not p.startswith(ok_prefix)}


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class Writes(Base):
    def test_a_whole_wrap_writes_only_what_it_may(self):
        write(self.work / "Todo.md", "# Work: open actions\n\n## Inbox\n\n- [ ] [[Pricing]]: send the sheet\n\n## Done\n")
        commit_all(self.work, "todo")
        before = tree(self.base)
        mem = self.home / ".claude" / "projects" / "ws" / "memory" / "pricing.md"
        got = self.run_wrap(payload(todo={"add": ["[[Pricing]]: a new one"], "tick": ["send the sheet"]}, memory={"path": str(mem)}))
        self.assertEqual("saved", got["outcome"], got)
        self.assertEqual(set(), outside_allowed(before, tree(self.base), self.root, mem))

    def test_a_failed_wrap_leaves_the_tree_exactly_as_it_was(self):
        before = tree(self.base)
        got = self.run_wrap(payload(entry="See [[260311-home-call]]."))
        self.assertEqual("refused", got["outcome"])
        self.assertEqual(before, tree(self.base))


    def test_a_refused_wrap_takes_back_the_history_it_made(self):
        old = "".join("**%d March 2025.** An old entry %d.\n\n" % (d, d) for d in range(2, 9))
        write(self.thread, self.thread.read_text(encoding="utf-8") + "\n" + old)
        commit_all(self.work, "old entries")
        got = self.run_wrap(payload(entry="See [[260311-home-call]]."))
        self.assertEqual("refused", got["outcome"])
        self.assertFalse((self.thread.parent / "history").exists())
        self.assertTrue(self.clean())


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class HalfWay(Base):
    def test_a_wrap_killed_between_its_writes_and_its_commit_leaves_the_lock_to_expire(self):
        rel = self.thread.relative_to(self.root).as_posix()
        script = ("import json,os,signal,sys,datetime\nsys.path.insert(0, %r)\nimport wrap\n"
                  "data=json.loads(sys.stdin.read())\n"
                  "wrap.run(%r, data, today=datetime.date(2026,11,22), before_commit=lambda: os.kill(os.getpid(), signal.SIGKILL))\n"
                  % (str(self.root / "System" / "tools"), str(self.root)))
        done = subprocess.run([sys.executable, "-I", "-c", script], input=json.dumps(payload()), text=True, capture_output=True,
                              env=dict(os.environ))
        self.assertEqual(-9, done.returncode, done.stderr)
        lock = wl.lock_path(self.root, rel)
        self.assertTrue(lock.exists())                                      # the killed wrap could not release it
        self.assertTrue(wl.running(lock))
        self.assertFalse(wl.start(self.root, rel))                          # a second wrap waits
        self.assertEqual(" M Northwind/Threads/Pricing/Pricing.md", git(self.work, "status", "--porcelain", "--untracked-files=all").rstrip())   # written, not committed
        self.assertEqual(1, self.count())                                   # nothing was committed
        self.assertEqual([], self.generated(".done"))
        old = time.time() - wl.MAX_AGE - 5                                  # ten minutes pass
        os.utime(lock, (old, old))
        lock.write_text(json.dumps({"note": rel, "started": (datetime.datetime.utcnow() - datetime.timedelta(minutes=11)).strftime("%Y-%m-%dT%H:%M:%SZ")}))
        self.assertFalse(wl.running(lock))
        self.assertTrue(wl.start(self.root, rel))                           # the existing recovery path
        wl.end(self.root, rel, abandon=True)                                # and the abandon path
        self.assertFalse(lock.exists())
        self.assertEqual([], self.generated(".done"))

    def test_an_interrupt_between_writes_and_commit_puts_the_files_back_and_releases_the_lock(self):
        before = self.thread.read_text(encoding="utf-8")

        def interrupt():
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.run_wrap(before_commit=interrupt)
        self.assertEqual(before, self.thread.read_text(encoding="utf-8"))
        self.assertEqual([], self.generated(".lock"))
        self.assertEqual([], self.generated(".done"))


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class CommandLine(Base):
    def call(self, data, *args):
        return subprocess.run([sys.executable, "-B", str(self.root / "System" / "tools" / "wrap.py"), "--root", str(self.root), "--today", "2026-11-22", *args],
                              input=json.dumps(data), text=True, capture_output=True, env=dict(os.environ))

    def test_it_prints_one_sentence_or_json_and_exits_zero_only_for_saved(self):
        refused = self.call(payload(entry="See [[260311-home-call]]."))
        self.assertEqual(1, refused.returncode)
        self.assertTrue(refused.stdout.startswith("Refused: "), refused.stdout)
        saved = self.call(payload(), "--json")
        self.assertEqual(0, saved.returncode, saved.stderr)
        receipt = json.loads(saved.stdout)
        self.assertEqual("saved", receipt["outcome"])
        self.assertEqual(git(self.work, "rev-parse", "--short", "HEAD").strip(), receipt["commit"])
        bad = subprocess.run([sys.executable, "-B", str(self.root / "System" / "tools" / "wrap.py"), "--root", str(self.root)],
                             input="not json", text=True, capture_output=True, env=dict(os.environ))
        self.assertEqual(1, bad.returncode)
        self.assertTrue(bad.stdout.startswith("Failed: "))


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class SameVerdictsAsTheHandWrap(Base):
    """The wall verdicts of a wrap through the tool equal those of the hand wrap: the same files, staged by name and
    committed with plain git, in each of two walled invented zones and one open zone."""

    def hand(self, zone, data):
        project, thread, party = CASES[zone]
        note = self.root / "Zones" / zone / project / "Threads" / thread / (thread + ".md")
        job = wrap.check_input(data)
        original = note.read_text(encoding="utf-8")
        note.write_text(wrap.new_note_text(original, job, TODAY), encoding="utf-8")
        z = self.root / "Zones" / zone
        rel = note.relative_to(z).as_posix()
        git(z, "add", "--", rel)
        done = subprocess.run(["git", "commit", "-q", "-m", data["message"]], cwd=str(z), env=dict(os.environ), capture_output=True, text=True)
        if done.returncode == 0:
            git(z, "reset", "-q", "--hard", "HEAD~1")
        else:
            git(z, "reset", "-q", "--hard", "HEAD")
        return "saved" if done.returncode == 0 else "refused", " ".join(done.stderr.split())

    def test_each_case_has_the_verdict_the_hand_wrap_has(self):
        cases = [
            ("Work", "Sent. See [[260310-work-call]].", "saved"),                  # its own zone's page
            ("Work", "Sent. See [[260311-home-call]].", "refused"),                # a walled zone's page
            ("Work", "Sent. See [[260312-ventures-call]].", "saved"),              # an open zone's page
            ("Home", "Sent. See [[260311-home-call]].", "saved"),
            ("Home", "Sent. See [[260310-work-call]].", "refused"),
            ("Home", "Sent. See [[260312-ventures-call]].", "saved"),
            ("Ventures", "Sent. See [[260312-ventures-call]].", "saved"),
            ("Ventures", "Sent. See [[260310-work-call]].", "refused"),
            ("Ventures", "Sent. See [[260311-home-call]].", "refused"),
            ("Work", "Sent, with nothing linked.", "saved"),
        ]
        refused_seen = 0
        for zone, entry, expect in cases:
            data = payload(zone, entry=entry)
            verdict, sentence = self.hand(zone, data)
            self.assertEqual(expect, verdict, (zone, entry, sentence))
            got = self.run_wrap(data)
            self.assertEqual(verdict, got["outcome"], (zone, entry, got))
            if verdict == "refused":
                refused_seen += 1
                self.assertEqual(sentence, got["say"][len("Refused: "):], (zone, entry))      # the hook's own sentence
                self.assertTrue(self.clean(zone))
            else:
                git(self.root / "Zones" / zone, "reset", "-q", "--hard", "HEAD~1")             # back to the start for the next case
        self.assertGreaterEqual(refused_seen, 4)


class LineSeparators(unittest.TestCase):
    """Python reads more than \\n as a line end (S5): a one-line field holds none of them, and prose holds only \\n."""
    SEPARATORS = ("\u2028", "\u2029", "\x85", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e")

    def test_a_one_line_value_with_another_line_end_is_refused(self):
        for sep in self.SEPARATORS:
            with self.subTest(sep=repr(sep)):
                with self.assertRaises(wrap.Stop):
                    wrap.one_line("one" + sep + "- [ ] two", "a line")
                data = payload()
                data["resume"]["rows"]["Next action"] = "go" + sep + "## Heading"
                with self.assertRaises(wrap.Stop):
                    wrap.check_input(data)
        self.assertEqual("plain line", wrap.one_line(" plain line ", "a line"))

    def test_prose_may_hold_newlines_and_no_other_line_end(self):
        for sep in self.SEPARATORS:
            with self.subTest(sep=repr(sep)):
                with self.assertRaises(wrap.Stop):
                    wrap.prose("one" + sep + "## Heading", "entry")
        self.assertEqual("one\ntwo", wrap.prose("one\ntwo", "entry"))


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class CommitTrailers(Base):
    """The tool puts the operation's id in its commit when the page action hands it over (#716, #723), in that shape only."""

    GOOD = "Garrick-Op: 0123456789abcdef\nGarrick-Payload: " + "a" * 64

    def wrapped(self, value):
        env = dict(os.environ)
        env.pop("GARRICK_COMMIT_TRAILERS", None)
        if value is not None:
            env["GARRICK_COMMIT_TRAILERS"] = value
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual("saved", self.run_wrap()["outcome"])
        return git(self.work, "log", "-1", "--format=%B")

    def test_the_shape_it_takes_is_added_to_the_commit(self):
        said = self.wrapped(self.GOOD)
        self.assertIn("Garrick-Op: 0123456789abcdef", said)
        self.assertEqual("Northwind, Pricing: draft sent; waiting on volumes", said.splitlines()[0])

    def test_anything_else_or_nothing_leaves_the_commit_as_it_was(self):
        for value in (None, "", "Garrick-Op: x", self.GOOD + "\nFoo: bar"):
            with self.subTest(value=value):
                self.setUp()
                self.assertNotIn("Garrick-Op", self.wrapped(value))


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class PageRoute(Base):
    """The page_action.py executor routes the wrap verb to the same tool, with the words in `input`."""

    def setUp(self):
        super().setUp()
        import importlib.util
        spec = importlib.util.spec_from_file_location("garrick_page_action_for_wrap", REPO / "extras" / "status" / "page_action.py")
        self.pa = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.pa)
        shutil.copy2(TOOLS / "operations.py", self.root / "System" / "tools" / "operations.py")
        (self.root / "System" / "rules.md").write_text("# Rules\n", encoding="utf-8")
        jobs = mock.patch.dict(os.environ, {"GARRICK_JOBS_DIR": str(self.base / "jobs")})
        jobs.start()
        self.addCleanup(jobs.stop)

    def send(self, **req):
        data = dict(payload())
        words = {k: data[k] for k in ("resume", "entry", "message")}
        words.update(req.pop("words", {}))
        request = dict({"verb": "wrap", "zone": "Work", "project": "Northwind", "thread": "Pricing", "input": words}, **req)
        return self.pa.perform(self.root, request, via="session")[0]

    def test_the_verb_is_declared_and_routed(self):
        import operations
        self.assertIn("wrap", self.pa.VERBS)
        self.assertIn("wrap", operations.DECLARED)
        self.assertEqual(("zone", "project", "thread", "input"), operations.DECLARED["wrap"].fields)
        self.assertNotIn("wrap", operations.RECORDED)

    def test_a_saved_wrap_answers_with_the_receipt_sentence(self):
        reply = self.send()
        self.assertTrue(reply["ok"], reply)
        self.assertEqual("Saved: Northwind, Pricing is wrapped.", reply["say"])
        self.assertTrue(self.clean())
        self.assertEqual(2, self.count())

    def test_a_refused_wrap_shows_the_hooks_sentence(self):
        reply = self.send(words={"entry": "See [[260311-home-call]]."})
        self.assertFalse(reply["ok"])
        self.assertTrue(reply["say"].startswith("Refused: "), reply)
        self.assertEqual(1, self.count())

    def test_a_field_the_verb_does_not_declare_is_refused_by_name(self):
        reply = self.send(file="x.md")
        self.assertFalse(reply["ok"])
        self.assertIn("file", reply["say"])
        self.assertEqual(1, self.count())

    def test_two_wraps_of_one_thread_in_a_row_each_write_their_own_words(self):
        import operations
        first = self.pa.perform(self.root, self.request(entry="First words of the wrap."), operations, via="session")[0]
        second = self.pa.perform(self.root, self.request(entry="Second words of the wrap."), operations, via="session")[0]
        self.assertTrue(first["ok"] and second["ok"], (first, second))
        text = self.thread.read_text(encoding="utf-8")
        self.assertIn("First words of the wrap.", text)
        self.assertIn("Second words of the wrap.", text)
        self.assertEqual(3, self.count())                                    # a commit for each

    def test_the_journal_holds_no_wrap_and_none_of_its_words(self):
        import operations
        self.pa.perform(self.root, self.request(entry="A private sentence for the journal test."), operations, via="session")
        journal = self.base / "jobs" / operations.FILE
        text = journal.read_text(encoding="utf-8") if journal.is_file() else ""
        for word in ("wrap", "private sentence", "tier-two volume", "volumes are with the buyer"):
            self.assertNotIn(word, text)

    def request(self, **words):
        data = dict(payload())
        data = {k: data[k] for k in ("resume", "entry", "message")}
        data.update(words)
        return {"verb": "wrap", "zone": "Work", "project": "Northwind", "thread": "Pricing", "input": data}

    def test_a_wrap_with_an_operation_id_carries_it_in_its_commit_and_a_retry_runs_nothing(self):
        import operations
        git_env = mock.patch.dict(os.environ)          # the fixtures' GIT_CONFIG_COUNT, without its keys, is a git error for the record's own calls
        git_env.start()
        self.addCleanup(git_env.stop)
        for name in [k for k in os.environ if k.startswith("GIT_CONFIG_") and k != "GIT_CONFIG_GLOBAL" and k != "GIT_CONFIG_NOSYSTEM"]:
            os.environ.pop(name)
        req = dict(self.request(entry="Words kept once."), op="0123456789abcdef")
        first = self.pa.perform(self.root, dict(req), operations, via="remote")[0]
        self.assertTrue(first["ok"], first)
        self.assertEqual(first["commit"], git(self.work, "rev-parse", "--short", "HEAD").strip())
        self.assertIn("Garrick-Op: 0123456789abcdef", git(self.work, "log", "-1", "--format=%B"))
        again = self.pa.perform(self.root, dict(req), operations, via="remote")[0]
        self.assertTrue(again["ok"] and again.get("receipt"), again)
        self.assertEqual(2, self.count())
        self.assertEqual(1, self.thread.read_text(encoding="utf-8").count("Words kept once."))

    def test_a_remote_wrap_never_takes_memory_or_a_held_lock_and_writes_nothing(self):
        import operations
        memory = self.home / ".claude" / "projects" / "ws" / "memory" / "pointer.md"
        for extra in ({"memory": {"path": str(memory)}}, {"lock": "held"}, {"lock": "take"}):
            with self.subTest(extra=extra):
                reply = self.pa.perform(self.root, self.request(**extra), operations, via="remote")[0]
                self.assertFalse(reply["ok"], reply)
                self.assertIn("remote", reply["say"])
                self.assertEqual(1, self.count())
                self.assertFalse(memory.exists())
        for extra in ({"memory": {"path": str(memory)}}, {"lock": "held"}):                  # at the Mac, as it was
            reply = self.pa.perform(self.root, self.request(**extra), operations, via="session")[0]
            self.assertNotIn("remote", reply["say"])

    def test_a_wrap_without_a_record_commits_as_it_always_did(self):
        import operations
        self.pa.perform(self.root, self.request(), operations, via="session")
        self.assertNotIn("Garrick-Op", git(self.work, "log", "-1", "--format=%B"))

    def test_the_words_may_not_name_another_thread_than_the_request(self):
        reply = self.send(words={"thread": "Other"})
        self.assertFalse(reply["ok"])
        self.assertEqual(1, self.count())

    def test_a_request_with_no_words_is_refused(self):
        reply = self.pa.perform(self.root, {"verb": "wrap", "zone": "Work", "project": "Northwind", "thread": "Pricing"}, via="session")[0]
        self.assertFalse(reply["ok"])


if __name__ == "__main__":
    unittest.main()


class NoReader(unittest.TestCase):
    """A tools folder an update left half copied, with wrap.py and no work.py: the wrap fails in plain words
    and never crashes (0.76.0 confirmation pass, N1)."""

    def test_a_missing_reader_is_a_failed_wrap_not_a_crash(self):
        with mock.patch.object(wrap, "work", None):
            with self.assertRaises(wrap.Stop) as stop:
                wrap.resume_note(Path("/nowhere"), "Work", "Acme", "Pricing")
        self.assertEqual(stop.exception.outcome, "failed")
        self.assertIn("update Garrick", str(stop.exception.why))
