"""Notes processed hourly (#572): template/System/skills/intake/process_notes.py and the gr-notes job.

    python3 -m unittest discover -s tests

The assistant is always a stub here: a function of (prompt, zone) that answers JSON. Nothing calls a real assistant.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import thread_note, write  # noqa: E402
from test_notes import NOTE, NoteCase, git, REPO  # noqa: E402

RESUME = """

## State of play

### Resume here

**Where it stands, 1 March 2026.** Drafting.

| | |
|---|---|
| Live artifact | none |
| Next action | Draft the price sheet |
| Keep in mind | nothing |
| Waiting on | Dana |
| Deadline | none |

---

**1 March 2026.** Started.
"""


def ids_in(prompt):
    return re.findall(r'<note id="([0-9a-f]+)"', prompt)


def answer(**by_class):
    """A stub assistant that gives every note in the prompt the same judgment."""
    calls = []

    def assess(prompt, zone):
        calls.append((zone, prompt))
        j = dict(by_class)
        return 0, json.dumps({"items": [dict(j, id=i) for i in ids_in(prompt)]})
    assess.calls = calls
    return assess


class ProcessCase(NoteCase):
    def setUp(self):
        super().setUp()
        self.pn = self.load()
        self.state = str(Path(os.environ["GARRICK_JOBS_DIR"]) / "notes-state.json")
        text = (self.pricing / "Pricing.md").read_text().split("## State of play")[0].rstrip() + "\n" + RESUME
        write(self.pricing / "Pricing.md", text)
        write(self.pricing / "Pricing.md", (self.pricing / "Pricing.md").read_text())
        write(self.work / "Todo.md", "# Work: open actions\n\n## Inbox\n\n- [ ] [[Acme Review/Threads/Pricing/Pricing|Pricing]]: Send Dana the sheet\n\n## Done\n")
        git(self.work, "add", "-A")
        git(self.work, "commit", "-q", "-m", "thread state")
        # a real repository for Personal too, so each zone commits on its own
        shutil_rm = self.personal / ".git"
        import shutil
        shutil.rmtree(shutil_rm)
        git(self.personal, "init", "-q")
        for cfg in (("user.name", "Sam Rivera"), ("user.email", "sam@example.com"), ("maintenance.auto", "false"), ("gc.auto", "0")):
            git(self.personal, "config", *cfg)
        hook = self.personal / ".git" / "hooks" / "pre-commit"
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text("#!/bin/sh\n# Garrick wall check (a stand-in)\n")
        hook.chmod(0o755)
        git(self.personal, "add", "-A")
        git(self.personal, "commit", "-q", "-m", "start")

    def load(self):
        src = self.root / "System" / "skills" / "intake" / "process_notes.py"
        sys.modules.pop("intake", None)           # the module this workspace's copy imports, never an earlier test's
        sys.modules.pop("process_notes", None)
        sys.path.insert(0, str(src.parent))
        spec = importlib.util.spec_from_file_location("garrick_test_process_notes", str(src))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def run_pass(self, assess=None, **kw):
        return self.pn.run(self.root, assess, self.state, "2026-11-14", **kw)

    def recs(self):
        return json.loads(Path(self.state).read_text())["items"]

    def drop_note(self, name="n.md", destination='destination: "Acme Review, pricing"', text=None, where=None):
        body = text if text is not None else NOTE % destination
        return self.drop(name, body, where)

    def thread(self):
        return (self.pricing / "Pricing.md").read_text()


class TestNothingToDo(ProcessCase):
    def test_an_empty_queue_calls_no_assistant(self):
        assess = answer(**{"class": "tentative"})
        res = self.run_pass(assess)
        self.assertEqual(0, res["calls"])
        self.assertEqual([], assess.calls)

    def test_a_note_with_no_destination_gets_one_question_and_no_call(self):
        self.drop_note(destination="")
        assess = answer(**{"class": "decision"})
        first = self.run_pass(assess)
        self.assertEqual((1, 0), (first["asked"], first["calls"]))
        again = self.run_pass(assess)
        self.assertEqual((0, 0, 1), (again["asked"], again["calls"], again["unchanged"]))
        self.assertEqual([], assess.calls)
        self.assertTrue((self.root / "Inbox" / "n.md").is_file())
        [rec] = self.recs().values()
        self.assertEqual("asked", rec["state"])
        self.assertIn("Where does the note about", rec["question"])

    def test_a_changed_note_is_asked_about_again(self):
        self.drop_note(destination="")
        self.run_pass()
        self.drop_note(text=NOTE % "" + "and one more thing\n")
        self.assertEqual(1, self.run_pass()["asked"])


class TestWhatANoteWarrants(ProcessCase):
    def test_a_clear_decision_updates_the_thread_and_links_its_source(self):
        self.drop_note(text=NOTE % 'destination: "Acme Review, pricing"')
        assess = answer(**{"class": "decision", "changes": [
            {"kind": "next_action", "text": "Send the price sheet at the revised floor"},
            {"kind": "decision", "text": "Use the revised forecast"}]})
        res = self.run_pass(assess)
        self.assertEqual((1, 1, 1), (res["calls"], res["filed"], res["applied"]))
        text = self.thread()
        self.assertRegex(text, r"\| Next action \| Send the price sheet at the revised floor \(\[261114 - [^\]]+\]\(\.\./?Pricing/|\(Notes/")
        self.assertIn("(Notes/261114%20-%20", text)
        self.assertRegex(text, r"\*\*14 November 2026\.\*\* From a note \(")
        self.assertIn("Decided,", text)
        self.assertIn("updated: 2026-11-14", text)
        self.assertFalse((self.root / "Inbox" / "n.md").exists())
        self.assertEqual("", git(self.work, "status", "--porcelain").strip())
        self.assertEqual("Work: notes processed in Acme Review, Pricing", git(self.work, "log", "-1", "--format=%s").strip())
        [rec] = self.recs().values()
        self.assertEqual(("done", "decision", ["next_action", "decision"]), (rec["state"], rec["class"], rec["applied"]))

    def test_the_decision_ticks_and_adds_only_what_it_is_shown(self):
        self.drop_note()
        from_todo = {}

        def assess(prompt, zone):
            key = re.search(r"([0-9a-f]{16})  \[\[[^\n]*Send Dana the sheet", prompt).group(1)
            from_todo["key"] = key
            return 0, json.dumps({"items": [{"id": ids_in(prompt)[0], "class": "decision",
                                              "changes": [{"kind": "waiting_on", "text": "nobody"}],
                                              "tick": [key, "0123456789abcdef"], "todo": ["Book the review"]}]})
        self.run_pass(assess)
        todo = (self.work / "Todo.md").read_text()
        self.assertRegex(todo, r"- \[x\] \[\[Acme Review/Threads/Pricing/Pricing\|Pricing\]\]: Send Dana the sheet ✅ 2026-11-14")
        self.assertIn("Book the review", todo)

    def test_a_tentative_idea_is_filed_for_review_and_leaves_the_state_alone(self):
        before = self.thread()
        self.drop_note()
        res = self.run_pass(answer(**{"class": "tentative"}))
        self.assertEqual((1, 1), (res["filed"], res["review"]))
        self.assertEqual(before, self.thread())
        [name] = self.notes()
        self.assertIn("review: pending", (self.pricing / "Notes" / name).read_text())
        got = self.intake.notes_since(self.root, "Zones/Work/Acme Review", "Pricing")
        self.assertEqual(1, len(got["awaiting_review"]))

    def test_with_no_assistant_every_resolved_note_is_filed_for_review(self):
        before = self.thread()
        self.drop_note()
        res = self.run_pass(None)
        self.assertEqual((0, 1, 1), (res["calls"], res["filed"], res["review"]))
        self.assertEqual(before, self.thread())

    def test_a_change_that_cannot_be_applied_without_guessing_is_kept_for_review(self):
        text = self.thread().replace("| Deadline | none |\n", "")
        write(self.pricing / "Pricing.md", text)
        git(self.work, "commit", "-qam", "no deadline row")
        self.drop_note()
        self.run_pass(answer(**{"class": "decision", "changes": [{"kind": "deadline", "text": "Friday"}]}))
        self.assertEqual(text, self.thread())
        [name] = self.notes()
        self.assertIn("review: pending", (self.pricing / "Notes" / name).read_text())

    def test_the_assistant_cannot_widen_what_it_may_do(self):
        self.drop_note()
        it = self.pn.queue(self.root)
        it[0]["place"] = {"said": "x"}
        shown = {it[0]["id"]: {"todo": [{"key": "aaaaaaaaaaaaaaaa", "line": "x"}]}}
        text = json.dumps({"items": [{"id": it[0]["id"], "class": "decision", "autonomy": "full",
                                      "changes": [{"kind": "autonomy", "text": "full"}, {"kind": "rule", "text": "x"},
                                                  {"kind": "next_action", "text": "ok"}],
                                      "tick": ["bbbbbbbbbbbbbbbb", "aaaaaaaaaaaaaaaa"], "send": "dana@example.com"},
                                     {"id": "made-up", "class": "decision"}]})
        got = self.pn.parse_judgments(text, it, shown)
        self.assertEqual([it[0]["id"]], list(got))
        self.assertEqual(([{"kind": "next_action", "text": "ok"}], ["aaaaaaaaaaaaaaaa"]), (got[it[0]["id"]]["changes"], got[it[0]["id"]]["tick"]))
        self.assertEqual({"class", "changes", "tick", "todo", "reason"}, set(got[it[0]["id"]]))
        self.assertEqual({}, self.pn.parse_judgments("not json", it, shown))

    def test_a_change_cannot_carry_a_link_into_the_thread_note(self):
        self.drop_note()
        it = self.pn.queue(self.root)
        it[0]["place"] = {"said": "x"}
        shown = {it[0]["id"]: {"todo": []}}
        text = json.dumps({"items": [{"id": it[0]["id"], "class": "decision", "changes": [
            {"kind": "next_action", "text": "See [[Personal/Home Move/Home Move|the plan]] and [x](https://example.com/a)"},
            {"kind": "decision", "text": "[[]]"}]}]})
        [change, *rest] = self.pn.parse_judgments(text, it, shown)[it[0]["id"]]["changes"]
        for part in ("[[", "]]", "]("):
            self.assertNotIn(part, change["text"])
        self.assertIn("Home Move", change["text"])
        self.assertEqual([], rest)                           # a change that is only link marks is empty and dropped

    def test_a_failed_call_files_nothing_and_the_note_waits(self):
        self.drop_note()
        res = self.run_pass(lambda prompt, zone: (1, ""))
        self.assertEqual((1, 1), (res["calls"], res["failed"]))
        self.assertTrue((self.root / "Inbox" / "n.md").is_file())
        self.assertEqual([], self.notes())


class TestWorkingBesideOtherSessions(ProcessCase):
    def test_no_open_session_is_needed(self):
        # nothing opened the thread and the lock for a wrap is idle: the note is filed
        self.drop_note()
        self.assertEqual(1, self.run_pass(answer(**{"class": "tentative"}))["filed"])

    def test_a_concurrent_edit_survives_and_the_conflict_is_held_for_review(self):
        mine = self.thread() + "\nAn edit another session has not committed yet.\n"
        write(self.pricing / "Pricing.md", mine)
        self.drop_note()
        assess = answer(**{"class": "decision", "changes": [{"kind": "next_action", "text": "x"}]})
        first = self.run_pass(assess)
        self.assertEqual(1, first["retry"])
        self.assertEqual([], self.notes())
        second = self.run_pass(assess)
        self.assertEqual(1, second["filed"])
        self.assertEqual(mine, self.thread())                       # never overwritten
        [name] = self.notes()
        self.assertIn("review: pending", (self.pricing / "Notes" / name).read_text())
        # and only the note was committed: the other session's edit is still uncommitted
        self.assertIn("Pricing.md", git(self.work, "status", "--porcelain"))
        self.assertNotIn("Pricing.md", git(self.work, "show", "--stat", "--format=", "HEAD"))

    def test_a_thread_changed_after_it_was_read_is_assessed_again(self):
        self.drop_note()

        def assess(prompt, zone):
            write(self.pricing / "Pricing.md", self.thread().replace("Drafting.", "Drafting, then sent."))
            git(self.work, "commit", "-qam", "another session wraps")
            return 0, json.dumps({"items": [{"id": ids_in(prompt)[0], "class": "decision",
                                              "changes": [{"kind": "next_action", "text": "x"}]}]})
        res = self.run_pass(assess)
        self.assertEqual(1, res["retry"])
        self.assertIn("Drafting, then sent.", self.thread())
        self.assertNotIn("| Next action | x", self.thread())
        self.assertTrue((self.root / "Inbox" / "n.md").is_file())

    def test_a_running_wrap_is_not_edited(self):
        tools = self.root / "System" / "tools"
        (self.root / "System" / "generated").mkdir(parents=True, exist_ok=True)
        __import__("shutil").copy2(REPO / "template" / "System" / "tools" / "wrap_lock.py", tools / "wrap_lock.py")
        subprocess.run([sys.executable, str(tools / "wrap_lock.py"), "--root", str(self.root), "start", "Zones/Work/Acme Review/Threads/Pricing/Pricing.md"],
                       check=True, capture_output=True)
        self.drop_note()
        res = self.run_pass(answer(**{"class": "decision", "changes": [{"kind": "next_action", "text": "x"}]}))
        self.assertEqual(1, res["retry"])
        self.assertNotIn("| Next action | x", self.thread())


class TestRetries(ProcessCase):
    def refuse_commits(self, yes):
        hook = self.work / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\n# Garrick wall check (a stand-in)\n" + ("exit 1\n" if yes else ""))

    def test_a_retry_after_an_interruption_makes_one_note_and_one_set_of_changes(self):
        self.drop_note()
        assess = answer(**{"class": "decision", "changes": [{"kind": "next_action", "text": "Send it"}], "todo": ["Book the review"]})
        self.refuse_commits(True)
        first = self.run_pass(assess)
        self.assertEqual(1, first["held"])
        self.assertTrue((self.root / "Inbox" / "n.md").is_file())             # not complete: its commit did not happen
        self.assertEqual("written", list(self.recs().values())[0]["state"])
        self.refuse_commits(False)
        second = self.run_pass(assess)
        self.assertEqual((1, 0), (second["filed"], second["calls"]))         # only the commit, no second call
        self.assertEqual(1, len(self.notes()))
        self.assertEqual(1, self.thread().count("| Next action | Send it"))
        self.assertEqual(1, (self.work / "Todo.md").read_text().count("Book the review"))
        self.assertEqual(1, self.thread().count("From a note ("))
        self.assertFalse((self.root / "Inbox" / "n.md").exists())
        third = self.run_pass(assess)
        self.assertEqual((0, 0), (third["filed"], third["calls"]))
        self.assertEqual("", git(self.work, "status", "--porcelain").strip())

    def test_a_done_note_whose_inbox_file_was_left_is_only_cleaned_up(self):
        path = self.drop_note()
        self.run_pass(answer(**{"class": "tentative"}))
        write(path, NOTE % 'destination: "Acme Review, pricing"')     # the same words again: a retry of the removal
        assess = answer(**{"class": "tentative"})
        res = self.run_pass(assess)
        self.assertEqual((0, 0), (res["calls"], res["filed"]))
        self.assertFalse(path.exists())
        self.assertEqual(1, len(self.notes()))


class TestZonesApart(ProcessCase):
    def test_each_zone_is_assessed_alone_and_committed_in_its_own_repository(self):
        self.drop_note("a.md", 'destination: "Acme Review, pricing"')
        self.drop_note("b.md", 'destination: "Home Move boxes"')
        assess = answer(**{"class": "tentative"})
        res = self.run_pass(assess)
        self.assertEqual((2, 2), (res["calls"], res["filed"]))
        zones = sorted(z for z, _ in assess.calls)
        self.assertEqual(["Personal", "Work"], zones)
        for zone, prompt in assess.calls:
            self.assertEqual(1, len(ids_in(prompt)))
            self.assertNotIn("Home Move" if zone == "Work" else "Acme Review", prompt.split("<note", 1)[1])
        self.assertEqual("Personal: notes processed in Home Move, Boxes; kept for review", git(self.personal, "log", "-1", "--format=%s").strip())
        self.assertEqual("Work: notes processed in Acme Review, Pricing; kept for review", git(self.work, "log", "-1", "--format=%s").strip())

    def test_a_note_in_one_zones_inbox_with_a_destination_in_another_is_asked_about(self):
        self.drop_note("a.md", 'destination: "Home Move boxes"', where=self.work / "Inbox")
        res = self.run_pass(answer(**{"class": "tentative"}))
        self.assertEqual((1, 0), (res["asked"], res["calls"]))


class TestTheJob(ProcessCase):
    def job(self):
        spec = importlib.util.spec_from_file_location("garrick_notes_job", str(self.root / "System" / "jobs" / "notes_job.py"))
        sys.path.insert(0, str(self.root / "System" / "jobs"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_a_failing_fetch_does_not_stop_the_notes_already_saved(self):
        self.drop_note()
        job = self.job()
        pn = self.pn
        real = pn.agent_assessor
        pn.agent_assessor = lambda root, tier="sonnet": answer(**{"class": "tentative"})
        try:
            with mock.patch.object(job, "processor", return_value=pn), \
                    mock.patch.dict(os.environ, {"GARRICK_JOBS_DIR": str(Path(self.state).parent)}):
                code = job.main(["--workspace", str(self.root), "--fetch", "/usr/bin/false", "--fetch", "/usr/bin/true"])
        finally:
            pn.agent_assessor = real
        self.assertEqual(1, code)
        self.assertEqual(1, len(self.notes()))

    def test_the_plist_runs_the_job_under_its_name(self):
        import plistlib
        plist = plistlib.loads((REPO / "extras" / "jobs" / "launchd" / "garrick.gr-notes.plist").read_bytes())
        args = plist["ProgramArguments"]
        self.assertEqual("gr-notes", args[args.index("/Users/<you>/Garrick/System/jobs/job.py") + 1])
        self.assertEqual("garrick.gr-notes", plist["Label"])
        self.assertEqual({"Minute": 10}, plist["StartCalendarInterval"])

    def test_the_same_step_runs_from_the_skill_for_a_workspaces_own_scheduler(self):
        self.drop_note()
        script = str(self.root / "System" / "skills" / "intake" / "intake.py")
        run = subprocess.run([sys.executable, script, "--root", str(self.root), "process-notes", "--dry-run", "--state", self.state],
                             capture_output=True, text=True)
        self.assertEqual(0, run.returncode, run.stderr)
        self.assertEqual(1, json.loads(run.stdout)["waiting"])
        self.assertTrue((self.root / "Inbox" / "n.md").is_file())

    def test_the_state_file_is_written_only_in_the_jobs_folder(self):
        self.drop_note()
        script = str(self.root / "System" / "skills" / "intake" / "intake.py")
        elsewhere = self.root / "Zones" / "Work" / "Todo.md"
        before = elsewhere.read_text()
        for bad in (str(elsewhere), str(self.root / "System" / "rules.md"), "/tmp/notes-state.json", str(Path(self.state).parent / "held-actions.json"),
                    str(Path(self.state).parent / "sub" / "notes-state.json")):
            run = subprocess.run([sys.executable, script, "--root", str(self.root), "process-notes", "--no-assistant", "--state", bad],
                                 capture_output=True, text=True)
            self.assertEqual(1, run.returncode, bad)
            self.assertIn("jobs folder", run.stderr)
        self.assertEqual(before, elsewhere.read_text())
        self.assertTrue((self.root / "Inbox" / "n.md").is_file())
        self.assertTrue(self.pn.state_in_jobs(self.state))


if __name__ == "__main__":
    unittest.main()
