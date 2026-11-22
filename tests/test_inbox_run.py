"""Process the Inbox in the background (#634): inbox_run.py, the two page verbs that start it, the unattended `intake.py ask`, and
the row's result. The assistant is a stub that writes the files a case says; the limit check, the commits and the hooks run for real
on a temporary workspace with real git repositories and Garrick's own wall hook.

    cd tests && python3 -m unittest test_inbox_run

Invented names only: Acme Corp and Birch & Co (Work), Own affairs (Personal).
"""

from __future__ import annotations

import datetime as dt
import fcntl
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

import fixtures  # noqa: E402
from fixtures import HAVE_GIT, TOOLS, build_workspace, commit_all, git, meeting_page, write  # noqa: E402
from garrick_lib import install_wall_hook  # noqa: E402
from test_page_action import REPO, pa  # noqa: E402
from test_status import status  # noqa: E402

STATUS = REPO / "extras" / "status"
sys.path.insert(0, str(STATUS))
import inbox_run as ir  # noqa: E402

INTAKE = REPO / "template" / "System" / "skills" / "intake" / "intake.py"
spec = importlib.util.spec_from_file_location("garrick_intake_for_inbox_test", str(INTAKE))
intake = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = intake
spec.loader.exec_module(intake)

CONTEXT = fixtures.CONTEXT.replace("| Birch & Co | Client. Market-entry advice; competes with Acme | Work | `birch` | yes | birchco.example, mail.birchco.example |\n",
                                   "| Birch & Co | Client. Market-entry advice; competes with Acme | Work | `birch` | yes | birchco.example, mail.birchco.example |\n"
                                   "| Own affairs | Matters of the home | Personal | `jo` | yes | |\n"
                                   "| Maple Studio | Craft club | Personal | `maple` | yes | maple.example |\n").replace(
    "| Theo Marsh | `birch` | Managing partner |\n", "| Theo Marsh | `birch` | Managing partner |\n| Pat Lee | `maple` | Treasurer |\n")


def mail(subject: str, sender: str = "dana@acmecorp.example") -> str:
    return "From: Dana <%s>\nTo: jo@example.com\nSubject: %s\nDate: Mon, 02 Nov 2026 09:00:00 +0000\n\nHello.\n" % (sender, subject)


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class RunCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name).resolve()
        self.root = base / "Workspace"
        self.jobs = base / "jobs"
        env = mock.patch.dict(os.environ, {"GARRICK_JOBS_DIR": str(self.jobs), "GARRICK_HARNESS": "claude", "HOME": str(base / "home")})
        env.start()
        self.addCleanup(env.stop)
        (base / "home").mkdir()
        build_workspace(self.root)
        write(self.root / "System" / "context.md", CONTEXT)
        (self.root / "System" / "tools").mkdir(parents=True, exist_ok=True)
        for name in ("check.py", "garrick_lib.py", "work.py"):
            shutil.copy2(TOOLS / name, self.root / "System" / "tools" / name)
        for skill in ("intake", "meetings"):          # the helper a question's words are read with, as an installed workspace has it
            shutil.copytree(str(REPO / "template" / "System" / "skills" / skill), str(self.root / "System" / "skills" / skill))
        self.work, self.home = self.root / "Zones" / "Work", self.root / "Zones" / "Personal"
        for zone in (self.work, self.home):
            shutil.rmtree(zone / ".git")
            git(zone, "init", "-q")
            write(zone / ".gitignore", "Inbox/\n")
            install_wall_hook(zone)
            commit_all(zone, "start")
        self.wikis = self.root / "Wikis"
        write(self.wikis / ".gitignore", "Meetings/raw/inbox/\n")
        git(self.wikis, "init", "-q")
        commit_all(self.wikis, "start")
        self.acme = self.work / "Acme Review"
        loaded = mock.patch.object(pa, "_INBOX", ir)          # the page's loader hands out this module, so a test can stand in for it
        loaded.start()
        self.addCleanup(loaded.stop)
        claude = mock.patch.object(ir.channels, "claude_path", return_value="/x/claude")
        claude.start()
        self.addCleanup(claude.stop)
        self.cap = ir.channels.evaluate(self.root, "--resume --allowedTools --strict-mcp-config Bash(git *)", True)

    def tearDown(self):
        self._tmp.cleanup()

    def heads(self):
        return {n: git(r, "rev-parse", "HEAD").strip() for n, r in (("Work", self.work), ("Personal", self.home), ("Wikis", self.wikis))}

    def run_with(self, act, answer=None):
        def runner(cmd, tier, cwd, env):
            self.last = (cmd, env)
            act()
            return 0, {"text": "Done."}
        return ir.run(self.root, answer, runner=runner, cap=self.cap, jobs=self.jobs)

    def drop(self, zone: str, name: str, text: str = None) -> Path:
        p = self.root / "Zones" / zone / "Inbox" / name
        write(p, text if text is not None else mail(name))
        return p


class TestWhatIsAllowed(unittest.TestCase):
    ROWS = [
        ("Zones/Work/Inbox/a.eml", True), ("Zones/Work/Todo.md", True), ("Zones/Personal/Todo.md", True),
        ("Zones/Work/Acme Review/Sources/a.pdf", True), ("Zones/Work/Acme Review/Threads/Pricing/Sources/a.pdf", True),
        ("Zones/Work/Needs you/261101 - ask a.md", True), ("Wikis/Meetings/wiki/sources/a.md", True),
        ("Wikis/Meetings/raw/inbox/a.txt", True), ("Wikis/Knowledge/raw/a.txt", True), ("Inbox/a.eml", True),
        ("Zones/Work/Acme Review/Acme Review.md", False),                   # another file of a project
        ("Zones/Personal/Garden/Garden.md", False), ("Zones/Work/Acme Review/Deliverables/a.md", False),
        ("Zones/Work/Acme Review/Threads/Pricing/Pricing.md", False), ("Zones/Work/archive/Acme/Sources/a.md", False),
        ("Zones/Work/AGENTS.md", False), ("Zones/Work/.git/config", False), ("Zones/Work/Inbox/../AGENTS.md", False),
        ("Zones/_template/Inbox/a", False), ("Wikis/Other/wiki/a.md", False), ("Wikis/AGENTS.md", False),
        ("System/context.md", False), ("AGENTS.md", False), ("Zones/Work", False), ("", False), ("/etc/passwd", False),
    ]

    def test_each_path_is_allowed_or_not(self):
        for path, ok in self.ROWS:
            self.assertEqual(ok, ir.allowed(path), path)


class TestTheRun(RunCase):
    def test_four_items_that_settle_are_filed_one_that_does_not_is_asked_and_no_session_opens(self):
        names = ["a.eml", "b.eml", "c.eml", "d.eml", "e.eml"]
        for n in names:
            self.drop("Work", n)
        before = self.heads()

        def act():
            for n in names[:3]:
                shutil.move(str(self.work / "Inbox" / n), str(self.acme / "Sources" / n))
            page = self.root / "Wikis" / "Meetings" / "wiki" / "sources" / "261102-acme-call.md"
            write(page, meeting_page("Work", "[acme]", "Acme call"))
            (self.work / "Inbox" / "d.eml").unlink()
            intake.ask_question(self.root, self.work / "Inbox" / "e.eml", "Acme Review or Birch Entry?",
                                [("Acme Review", "File it in Acme Review"), ("Birch Entry", "File it in Birch Entry")], "2026-11-02")
        out = self.run_with(act)
        self.assertEqual("done", out["state"], out)
        self.assertEqual({"filed": 4, "questions": 1, "needs": 0}, out["places"]["Work"])
        self.assertEqual("Work: filed 4 · 1 question", out["say"])
        after = self.heads()
        self.assertNotEqual(before["Work"], after["Work"])                       # one commit in the zone
        self.assertEqual(1, len(git(self.work, "log", "--format=%H", before["Work"] + "..HEAD").split()))
        self.assertEqual(1, len(git(self.wikis, "log", "--format=%H", before["Wikis"] + "..HEAD").split()))
        self.assertEqual(before["Personal"], after["Personal"])                  # nothing in a repository that did not change
        self.assertEqual(["e.eml"], sorted(p.name for p in (self.work / "Inbox").iterdir() if p.name != ".gitkeep"))
        self.assertEqual("", git(self.work, "status", "--porcelain").strip())
        self.assertTrue(any((self.work / "Needs you").glob("*.md")))
        # the call is the background one: no visible session, the deny profile, and the tools named
        cmd, env = self.last
        self.assertIn("--settings", cmd)
        self.assertEqual("settings.json", Path(cmd[cmd.index("--settings") + 1]).name)       # the deny profile plus the run's own guard (S3)
        self.assertEqual("1", env["GARRICK_BACKGROUND"])
        self.assertEqual(str(self.root), env["GARRICK_INBOX_WS"])
        self.assertEqual(ir.ALLOW, cmd[cmd.index("--allowedTools") + 1:])
        self.assertEqual(out["state"], ir.read_state(self.root)["state"])
        rows = status.question_needs(self.root, dt.date(2026, 11, 3))              # the one question is a row of Waiting on you now, in Work
        self.assertEqual(["Work"], [r["zone"] for r in rows])
        self.assertEqual("Acme Review or Birch Entry?", rows[0]["text"])

    def test_a_write_outside_the_allowed_paths_keeps_that_repository_exactly_as_it_is_and_commits_nothing_there(self):
        # S2: a changed path outside allowed() is reported, never deleted or reverted; the repository is kept whole
        self.drop("Work", "a.eml")
        self.drop("Work", "b.eml")
        hub = self.acme / "Acme Review.md"
        was = hub.read_text()
        before = self.heads()

        def act():
            shutil.move(str(self.work / "Inbox" / "a.eml"), str(self.acme / "Sources" / "a.eml"))       # fine
            hub.write_text(was + "\nAdded by the call.\n")                                              # not
            write(self.home / "Garden" / "Plan.md", "A plan.\n")                                        # another zone's project file
        out = self.run_with(act)
        self.assertEqual("failed", out["state"])
        self.assertTrue(out["refused"])
        self.assertEqual(["Personal", "Work"], out["kept"])
        self.assertIn("Personal, Work", out["say"])
        self.assertNotIn("Plan.md", out["say"])                                 # a place, never a file
        self.assertIn("Added by the call", hub.read_text())                     # nothing deleted or reverted
        self.assertEqual("A plan.\n", (self.home / "Garden" / "Plan.md").read_text())
        self.assertTrue((self.acme / "Sources" / "a.eml").exists())
        self.assertEqual(["b.eml"], sorted(p.name for p in (self.work / "Inbox").iterdir() if p.name != ".gitkeep"))
        self.assertEqual(before, self.heads())                                  # no commit anywhere

    def test_a_repository_the_call_did_not_touch_outside_the_allowed_paths_is_still_committed(self):
        self.drop("Work", "a.eml")
        hub = self.acme / "Acme Review.md"

        def act():
            (self.work / "Inbox" / "a.eml").unlink()
            write(self.wikis / "Meetings" / "wiki" / "sources" / "261102-acme-call.md", meeting_page("Work", "[acme]", "Acme call"))
            hub.write_text(hub.read_text() + "\nAdded.\n")
        before = self.heads()
        out = self.run_with(act)
        self.assertEqual(["Work"], out["kept"])
        self.assertEqual(before["Work"], self.heads()["Work"])
        self.assertNotEqual(before["Wikis"], self.heads()["Wikis"])             # the wiki's own paths were all the call's own and allowed

    def test_another_writer_loses_nothing_a_clean_file_edited_and_a_new_note_added_during_a_run_that_fails(self):
        self.drop("Work", "a.eml")
        hub = self.acme / "Acme Review.md"
        note = self.acme / "Notes" / "my-new-note.md"
        edited = hub.read_text() + "\nMy edit while the run went.\n"

        def runner(cmd, tier, cwd, env):
            hub.write_text(edited)                                  # someone else, mid-run
            write(note, "A note I wrote.\n")
            shutil.move(str(self.work / "Inbox" / "a.eml"), str(self.acme / "Sources" / "a.eml"))
            return 1, {"text": ""}
        out = ir.run(self.root, None, runner=runner, cap=self.cap, jobs=self.jobs)
        self.assertEqual("failed", out["state"])
        self.assertEqual(edited, hub.read_text())
        self.assertEqual("A note I wrote.\n", note.read_text())
        self.assertEqual(["Work"], out["kept"])
        self.assertIn("Work", out["say"])

    def test_another_writer_loses_nothing_when_the_run_is_refused_for_what_it_wrote(self):
        self.drop("Work", "a.eml")
        note = self.acme / "Notes" / "my-new-note.md"
        hub = self.acme / "Acme Review.md"

        def act():
            (self.work / "Inbox" / "a.eml").unlink()
            write(note, "A note I wrote.\n")
            hub.write_text(hub.read_text() + "\nMy edit.\n")
        out = self.run_with(act)
        self.assertEqual("failed", out["state"])
        self.assertEqual("A note I wrote.\n", note.read_text())
        self.assertIn("My edit.", hub.read_text())

    def test_a_head_that_moved_during_the_run_keeps_every_file_and_commits_nothing_there(self):
        self.drop("Work", "a.eml")
        self.drop("Work", "b.eml")

        def act():
            shutil.move(str(self.work / "Inbox" / "a.eml"), str(self.acme / "Sources" / "a.eml"))
            write(self.work / "Other" / "theirs.md", "Committed by someone else.\n")        # another session commits in the zone
            git(self.work, "add", "--", "Other/theirs.md")
            git(self.work, "commit", "-q", "-m", "someone else")
        out = self.run_with(act)
        self.assertEqual("failed", out["state"])
        self.assertEqual(["Work"], out["kept"])
        self.assertEqual("Committed by someone else.\n", (self.work / "Other" / "theirs.md").read_text())
        self.assertEqual("someone else", git(self.work, "log", "-1", "--format=%s").strip())      # no commit of ours on top
        self.assertTrue((self.acme / "Sources" / "a.eml").exists())                             # kept, uncommitted
        self.assertIn("Sources/a.eml", git(self.work, "status", "--porcelain", "--untracked-files=all"))
        self.assertEqual(["b.eml"], sorted(p.name for p in (self.work / "Inbox").iterdir() if p.name != ".gitkeep"))

    def test_a_change_in_a_zone_the_run_filed_nothing_in_keeps_that_zone_as_it_is_w1(self):
        self.drop("Work", "a.eml")
        before = self.heads()

        def act():
            (self.work / "Inbox" / "a.eml").unlink()                                              # a Work item leaves ...
            write(self.home / "Garden" / "Sources" / "a.eml", mail("a.eml"))                      # ... and lands in a Personal project
        out = self.run_with(act)
        self.assertEqual("failed", out["state"])
        self.assertEqual(["Personal"], out["kept"])
        self.assertEqual(before["Personal"], self.heads()["Personal"])
        self.assertTrue((self.home / "Garden" / "Sources" / "a.eml").exists())

    def test_put_back_touches_only_paths_inside_the_allowed_set(self):
        snap = ir.Snapshot(self.root)
        theirs = self.acme / "Acme Review.md"
        was = theirs.read_text()
        theirs.write_text(was + "\nTheirs.\n")
        new = self.acme / "Notes" / "new.md"
        write(new, "New.\n")
        left = ir.put_back(snap, self.work, ["Acme Review/Acme Review.md", "Acme Review/Notes/new.md"])
        self.assertEqual(["Acme Review/Acme Review.md", "Acme Review/Notes/new.md"], left)
        self.assertIn("Theirs.", theirs.read_text())
        self.assertTrue(new.exists())

    def test_a_later_edit_of_a_file_changed_before_the_run_is_kept_before_it_is_replaced_and_the_sentence_says_so_n2(self):
        todo = self.work / "Todo.md"
        todo.write_text(todo.read_text() + "\n- [ ] First edit.\n")
        self.drop("Work", "a.eml")

        def runner(cmd, tier, cwd, env):
            shutil.move(str(self.work / "Inbox" / "a.eml"), str(self.acme / "Sources" / "a.eml"))       # the zone has an item of the run
            todo.write_text(todo.read_text() + "- [ ] Second edit.\n")
            return 1, {"text": ""}
        out = ir.run(self.root, None, runner=runner, cap=self.cap, jobs=self.jobs)
        self.assertEqual("failed", out["state"])
        self.assertNotIn("Second edit", todo.read_text())
        kept = list((self.work / ".git" / "garrick-put-back").rglob("Todo.md"))
        self.assertEqual(1, len(kept))
        self.assertIn("Second edit", kept[0].read_text())
        self.assertIn("kept", out["say"])
        self.assertNotIn("garrick-put-back", out["say"])
        self.assertIn("garrick-put-back", out["details"])

    def test_a_question_file_the_call_wrote_by_hand_that_names_another_walled_zone_is_not_kept(self):
        self.drop("Work", "a.eml")
        self.drop("Work", "b.eml")
        before = self.heads()

        def act():
            (self.work / "Inbox" / "a.eml").unlink()
            write(self.work / "Needs you" / "261102 - ask b.md",
                  "---\ntype: question\nstatus: open\nasked: 2026-11-02\nintake: \"b.eml\"\n---\n\n**Is this from Maple Studio?**\n\n- [Yes] Yes\n")
        out = self.run_with(act)
        self.assertEqual("failed", out["state"])
        self.assertEqual(ir.SAY_REFUSED, out["say"])
        self.assertFalse((self.work / "Needs you").exists() and list((self.work / "Needs you").iterdir()))
        self.assertTrue((self.work / "Inbox" / "a.eml").exists())
        self.assertEqual(before, self.heads())

    def test_a_zone_to_do_list_is_allowed_and_another_zones_project_file_is_not(self):
        self.drop("Work", "a.eml")

        def act():
            (self.work / "Inbox" / "a.eml").unlink()
            todo = self.work / "Todo.md"
            todo.write_text(todo.read_text().replace("## Done", "- [ ] [[Pricing]]: Reply to Dana\n\n## Done"))
        out = self.run_with(act)
        self.assertEqual("done", out["state"], out)
        self.assertIn("Reply to Dana", git(self.work, "show", "HEAD:Todo.md"))

    def test_a_commit_the_hook_refuses_is_put_back_and_its_items_stay(self):
        self.drop("Work", "a.eml")
        fixtures.stand_in_hook(self.work, "echo refused >&2\nexit 1\n")
        before = self.heads()

        def act():
            shutil.move(str(self.work / "Inbox" / "a.eml"), str(self.acme / "Sources" / "a.eml"))
        out = self.run_with(act)
        self.assertEqual("failed", out["state"])
        self.assertIn("A commit was refused", out["say"])
        self.assertEqual(before, self.heads())
        self.assertTrue((self.work / "Inbox" / "a.eml").exists())
        self.assertFalse((self.acme / "Sources" / "a.eml").exists())

    def test_a_file_already_changed_before_the_run_is_never_committed_by_it(self):
        mine = self.wikis / "Meetings" / "wiki" / "index.md"
        mine.write_text("# Index\n\nMy own edit.\n")
        self.drop("Work", "a.eml")

        def act():
            (self.work / "Inbox" / "a.eml").unlink()
            write(self.wikis / "Meetings" / "wiki" / "sources" / "261102-acme-call.md", meeting_page("Work", "[acme]", "Acme call"))
        out = self.run_with(act)
        self.assertEqual("done", out["state"], out)
        self.assertIn("My own edit", mine.read_text())
        self.assertNotIn("index.md", git(self.wikis, "show", "--name-only", "--format=", "HEAD"))
        self.assertEqual(" M Meetings/wiki/index.md", git(self.wikis, "status", "--porcelain").rstrip())          # still the user's own, uncommitted

    def test_a_failed_call_puts_everything_back(self):
        self.drop("Work", "a.eml")

        def runner(cmd, tier, cwd, env):
            shutil.move(str(self.work / "Inbox" / "a.eml"), str(self.acme / "Sources" / "a.eml"))
            return 1, {"text": ""}
        out = ir.run(self.root, None, runner=runner, cap=self.cap, jobs=self.jobs)
        self.assertEqual("failed", out["state"])
        self.assertTrue(out["say"].startswith(ir.SAY_FAILED), out["say"])        # a copy of the file put back is named after it (N2)
        self.assertTrue((self.work / "Inbox" / "a.eml").exists())
        self.assertFalse((self.acme / "Sources" / "a.eml").exists())

    def test_an_item_in_the_meetings_inbox_that_stays_is_counted_and_gets_no_question_in_any_zone(self):
        write(self.wikis / "Meetings" / "raw" / "inbox" / "call.txt", "A: hello\nB: hi\n")
        with self.assertRaises(intake.Refusal):
            intake.ask_question(self.root, self.wikis / "Meetings" / "raw" / "inbox" / "call.txt", "Which zone?", [("Work", "File it in Work")])
        self.drop("Work", "a.eml")

        def act():
            (self.work / "Inbox" / "a.eml").unlink()
        out = self.run_with(act)
        self.assertEqual({"filed": 0, "questions": 0, "needs": 1}, out["places"]["Meetings"])
        self.assertFalse((self.work / "Needs you").exists() and list((self.work / "Needs you").iterdir()))
        self.assertFalse((self.home / "Needs you").exists())
        self.assertIn("Meetings: 1 item needs you", out["say"])
        button, said = status.inbox_act(ir.read_state(self.root), self.root)
        self.assertIn("Process it with my assistant", button)
        self.assertIn("1 item needs you", said)

    def test_the_result_is_never_a_sum_over_two_zones(self):
        self.drop("Work", "a.eml")
        self.drop("Personal", "b.eml")

        def act():
            (self.work / "Inbox" / "a.eml").unlink()
            (self.home / "Inbox" / "b.eml").unlink()
        out = self.run_with(act)
        self.assertEqual("Personal: filed 1; Work: filed 1", out["say"])
        self.assertEqual({"Personal", "Work"}, set(out["places"]))

    def test_nothing_in_the_call_can_send_share_or_delete(self):
        cmd, env = ir.build(self.root, "x")
        text = " ".join(cmd[cmd.index("--allowedTools"):])
        for word in ("send", "reply", "forward", "share", "trash", "mcp__", "WebFetch", "curl"):
            self.assertNotIn(word, text)
        self.assertEqual(["Read", "Grep", "Glob", "Edit", "Write"] +
                         ["Bash(python3 System/skills/intake/intake.py %s:*)" % s for s in
                          ("list", "parse", "file-conversation", "file-reading", "file-to-project", "extract-attachment", "skip", "ask")] +
                         ["Bash(python3 System/skills/meetings/ingest.py %s:*)" % s for s in ("land", "index", "log", "link")], ir.ALLOW)
        deny = json.loads(Path(cmd[cmd.index("--settings") + 1]).read_text())["permissions"]["deny"]
        self.assertIn("mcp__claude_ai_Gmail__send_message", deny)
        self.assertIn("mcp__claude_ai_Google_Drive__share_file", deny)

    def test_no_rule_lets_the_call_run_a_subcommand_that_writes_the_rules_of_the_walls(self):
        # S1: a bare script rule would let a mail make the call run `learn` or `person`; each rule names its subcommand
        for rule in ir.ALLOW:
            self.assertNotRegex(rule, r"(intake|ingest)\.py:\*", rule)
        text = " ".join(ir.ALLOW)
        for sub in ("learn", "person", "move-to-zone", "file-note", "process-notes", "split"):
            self.assertNotIn(".py %s:" % sub, text)
        # and the skill's unattended section lists exactly the subcommands the rules allow
        skill = (REPO / "template" / "System" / "skills" / "intake" / "SKILL.md").read_text()
        section = skill.split("## Running unattended")[1].split("## A note to yourself")[0]
        for sub in ir.INTAKE_SUBS + ir.INGEST_SUBS:
            self.assertIn("`%s`" % sub, section)
        for sub in ("learn", "person", "move-to-zone"):
            self.assertIn("`%s`" % sub, section)          # named as refused

    def test_a_run_that_changes_the_context_file_or_the_rules_is_refused_and_says_so(self):
        for name, text in (("context.md", None), ("rules.md", "# Rules\n"), ("rules.local.md", None)):
            with self.subTest(name):
                target = self.root / "System" / name
                write(target, text or (CONTEXT if name == "context.md" else "# Mine\n"))
                self.drop("Work", "a-%s.eml" % name)
                was = target.read_text()
                before = self.heads()

                def act():
                    (self.work / "Inbox" / ("a-%s.eml" % name)).unlink()
                    write(self.acme / "Sources" / "kept.txt", "filed\n")
                    target.write_text(was + "\n| Evil | x | Work | `evil` | yes | evil.example |\n")
                out = self.run_with(act)
                self.assertEqual("failed", out["state"])
                self.assertTrue(out["say"].startswith(ir.SAY_SYSTEM), out["say"])
                self.assertTrue(out.get("system"))
                self.assertEqual(before, self.heads())                       # nothing committed
                self.assertFalse((self.acme / "Sources" / "kept.txt").exists())   # the run's own allowed change is put back
                self.assertTrue((self.work / "Inbox" / ("a-%s.eml" % name)).exists())
                self.assertNotEqual(was, target.read_text())                 # the file itself is left as it is, not guessed at
                target.write_text(was)

    def test_a_run_that_changes_a_root_file_or_a_share_link_is_refused_c3(self):
        for name in ("AGENTS.md", "AGENTS.local.md", "Zones/.shared/newlink"):
            with self.subTest(name):
                target = self.root / name
                if not name.endswith("newlink"):
                    write(target, "x\n")
                self.drop("Work", "c.eml")

                def act():
                    (self.work / "Inbox" / "c.eml").unlink()
                    if name.endswith("newlink"):
                        target.parent.mkdir(parents=True, exist_ok=True)
                        os.symlink("/tmp", str(target))
                    else:
                        target.write_text("changed\n")
                out = self.run_with(act)
                self.assertTrue(out["say"].startswith(ir.SAY_SYSTEM), out["say"])
                self.assertTrue((self.work / "Inbox" / "c.eml").exists())
                if target.is_symlink():
                    target.unlink()

    def test_a_run_that_leaves_the_rules_and_tools_as_they_were_is_not_refused(self):
        self.drop("Work", "a.eml")

        def act():
            (self.work / "Inbox" / "a.eml").unlink()
        out = self.run_with(act)
        self.assertEqual("done", out["state"], out)

    def test_the_call_goes_through_run_prepared_under_its_own_ledger_name(self):
        seen = {}
        agent = ir.engine.agent_lib()

        def prepared(cmd, tier, cwd=None, job=None, timeout=None, env=None):
            seen.update(job=job, timeout=timeout, cwd=cwd)
            return 0, {"text": "Done."}
        with mock.patch.object(agent, "run_prepared", prepared):
            ir.default_runner(["claude"], ir.TIER, self.root, {})
        self.assertEqual(("inbox", ir.TIMEOUT, self.root), (seen["job"], seen["timeout"], seen["cwd"]))


class TestThePathGuard(RunCase):
    """S3: a file write outside the allowed set is refused before it happens, by a hook registered for this run's call alone."""

    def event(self, path, tool="Write"):
        return json.dumps({"tool_name": tool, "tool_input": {"file_path": str(path)}, "cwd": str(self.root)})

    def guard(self, path, tool="Write", zone=""):
        import subprocess
        env = dict(os.environ, GARRICK_INBOX_WS=str(self.root), GARRICK_INBOX_ZONE=zone)
        return subprocess.run([sys.executable, str(STATUS / "inbox_guard.py")], input=self.event(path, tool), capture_output=True,
                              text=True, env=env)

    def test_the_call_loads_a_settings_file_with_the_guard_before_every_write_tool_and_the_deny_list(self):
        cmd, env = ir.build(self.root, "x", "Work")
        data = json.loads(Path(cmd[cmd.index("--settings") + 1]).read_text())
        hook = data["hooks"]["PreToolUse"][0]
        self.assertEqual("Edit|Write|MultiEdit|NotebookEdit", hook["matcher"])
        self.assertIn("inbox_guard.py", hook["hooks"][0]["command"])
        self.assertIn("mcp__claude_ai_Gmail__send_message", data["permissions"]["deny"])
        self.assertEqual("Work", env["GARRICK_INBOX_ZONE"])

    def test_a_write_in_the_home_folder_a_nested_repository_and_an_ignored_path_is_refused_before_it_happens(self):
        nested = self.work / "Acme Review" / "tools" / "x.py"
        ignored = self.root / "Zones" / "Projects" / "Garrick" / "Repo" / "x.py"
        for path in (Path(os.environ["HOME"]) / ".zshrc", nested, ignored, self.root / "System" / "context.md",
                     self.work / "Acme Review" / "Acme Review.md", self.root / "AGENTS.md", self.work / ".git" / "config"):
            for tool in ("Write", "Edit"):
                r = self.guard(path, tool)
                self.assertEqual(2, r.returncode, (path, tool, r.stdout))
                self.assertIn("deny", r.stdout)
                self.assertFalse(path.exists() and path.name == ".zshrc")

    def test_a_write_that_leads_out_through_a_link_is_refused_and_one_in_the_allowed_set_is_not(self):
        outside = Path(self._tmp.name) / "elsewhere"
        outside.mkdir()
        os.symlink(str(outside), str(self.acme / "Sources" / "out"))
        self.assertEqual(2, self.guard(self.acme / "Sources" / "out" / "x.md").returncode)
        for ok in (self.acme / "Sources" / "a.pdf", self.work / "Inbox" / "a.eml", self.work / "Todo.md",
                   self.wikis / "Meetings" / "wiki" / "sources" / "a.md", self.root / "Inbox" / "a.eml"):
            r = self.guard(ok)
            self.assertEqual(0, r.returncode, (ok, r.stdout, r.stderr))

    def test_an_answer_run_is_bound_to_its_zone(self):
        self.assertEqual(0, self.guard(self.acme / "Sources" / "a.pdf", zone="Work").returncode)
        self.assertEqual(2, self.guard(self.home / "Garden" / "Sources" / "a.pdf", zone="Work").returncode)

    def test_a_guard_that_cannot_read_its_event_refuses(self):
        import subprocess
        r = subprocess.run([sys.executable, str(STATUS / "inbox_guard.py")], input="not json", capture_output=True, text=True,
                           env=dict(os.environ, GARRICK_INBOX_WS=str(self.root)))
        self.assertEqual(2, r.returncode)


class TestLiteralPaths(RunCase):
    def test_a_filed_file_named_with_a_glob_is_committed_alone_and_never_takes_a_dirty_file_beside_it_s4(self):
        mine = self.acme / "Sources" / "ab.md"
        write(mine, "mine\n")
        commit_all(self.work, "ab")
        mine.write_text("mine, edited and not committed\n")
        self.drop("Work", "a.eml")

        def act():
            (self.work / "Inbox" / "a.eml").unlink()
            write(self.acme / "Sources" / "a*.md", "filed\n")
        out = self.run_with(act)
        self.assertEqual("done", out["state"], out)
        self.assertEqual(["Acme Review/Sources/a*.md"], git(self.work, "show", "--name-only", "--format=", "HEAD").split("\n")[:1])
        left = git(self.work, "status", "--porcelain").strip().splitlines()
        self.assertEqual(1, len(left))
        self.assertTrue(left[0].startswith("M ") and left[0].endswith('ab.md"'), left)


class TestTheBackupFolder(RunCase):
    def test_a_folder_an_earlier_run_left_is_cleared_at_the_start_and_the_runs_own_is_private_s5(self):
        stale = self.jobs / "inbox-run" / "999999" / "Work"
        write(stale / "old.eml", "an old item\n")
        self.drop("Work", "a.eml")
        seen = {}

        def act():
            mine = self.jobs / "inbox-run" / str(os.getpid())
            seen["mode"] = (mine.parent.stat().st_mode & 0o777, mine.stat().st_mode & 0o777, (mine / "Work").stat().st_mode & 0o777)
            seen["stale"] = stale.exists()
            (self.work / "Inbox" / "a.eml").unlink()
        self.run_with(act)
        self.assertFalse(seen["stale"])
        self.assertEqual((0o700, 0o700, 0o700), seen["mode"])
        self.assertFalse((self.jobs / "inbox-run" / str(os.getpid())).exists())


class TestTheWordsOfAQuestion(RunCase):
    def test_the_name_of_the_item_in_the_question_file_is_not_a_word_of_the_question_c5(self):
        self.drop("Work", "Maple Studio invoice.eml")             # a party of another walled zone, in an item's own file name

        def act():
            intake.ask_question(self.root, self.work / "Inbox" / "Maple Studio invoice.eml", "Acme Review or Birch Entry?",
                                [("Acme Review", "File it in Acme Review"), ("Birch Entry", "File it in Birch Entry")], "2026-11-02")
        out = self.run_with(act)
        self.assertEqual("done", out["state"], out)
        self.assertEqual(1, out["places"]["Work"]["questions"])


class TestTheIntakeLine(RunCase):
    def test_the_intake_line_is_screened_unless_it_is_a_file_name_in_that_zones_inbox_n3(self):
        self.drop("Work", "a.eml")
        q = "---\ntype: question\nstatus: open\nasked: 2026-11-02\nintake: %s\n---\n\n**Which one?**\n\n- [Yes] Yes\n"
        for line, bad in (('"a.eml"', False), ('"Maple Studio notes"', True), ('"a.eml Maple Studio"', True)):
            f = self.work / "Needs you" / "261102 - ask.md"
            write(f, q % line)
            found = ir.question_problems(self.root, {self.work: ["Needs you/261102 - ask.md"]})
            self.assertEqual(bad, bool(found), line)


class TestTheAnswerArgument(RunCase):
    def test_a_label_that_starts_with_a_dash_reaches_the_run_as_the_label_c6(self):
        spawned = []
        label = "-Keep both"
        with mock.patch.object(ir, "available", return_value=True):
            ir.start(self.root, {"zone": "Work", "file": "261102 - ask a.md", "label": label}, spawn=lambda a, fd: spawned.append(a))
        args = spawned[0]
        self.assertEqual(1, len([a for a in args if a.startswith("--answer-json=")]))
        got = {}

        def fake_run(ws, answer=None, **kw):
            got["answer"] = answer
            return {"state": "done"}
        with mock.patch.object(ir, "run", fake_run):
            self.assertEqual(0, ir.main([a for a in args[2:] if a != "--lock-fd" and not a.isdigit()]))
        self.assertEqual({"zone": "Work", "file": "261102 - ask a.md", "label": label}, got["answer"])

    def test_an_answer_that_does_not_read_fails_the_run_and_says_so(self):
        self.assertEqual(1, ir.main(["run", "--workspace", str(self.root), "--answer-json=[1]"]))
        self.assertEqual("failed", ir.read_state(self.root)["state"])


class TestAnswering(RunCase):
    def test_answering_the_question_files_that_item_in_the_background_and_closes_the_question(self):
        self.drop("Work", "e.eml")
        q, fresh = intake.ask_question(self.root, self.work / "Inbox" / "e.eml", "Acme Review or Birch Entry?",
                                       [("Acme Review", "File it in Acme Review"), ("Birch Entry", "File it in Birch Entry")], "2026-11-02")
        self.assertTrue(fresh)
        git(self.work, "add", "-A")
        git(self.work, "commit", "-q", "-m", "a question")
        answer = {"zone": "Work", "file": q.name, "label": "Acme Review"}
        seen = []

        def act():
            seen.append(self.last[0][2])
            shutil.move(str(self.work / "Inbox" / "e.eml"), str(self.acme / "Sources" / "e.eml"))
        out = self.run_with(act, answer)
        self.assertEqual("done", out["state"], out)
        self.assertIn("answered", q.read_text())
        self.assertIn("Acme Review", seen[0])
        self.assertTrue((self.acme / "Sources" / "e.eml").exists())
        self.assertEqual("", git(self.work, "status", "--porcelain").strip())

    def test_a_run_that_does_not_file_the_item_opens_its_question_again(self):
        self.drop("Work", "e.eml")
        q, _ = intake.ask_question(self.root, self.work / "Inbox" / "e.eml", "Acme Review or Birch Entry?",
                                   [("Acme Review", "File it in Acme Review")], "2026-11-02")
        git(self.work, "add", "-A")
        git(self.work, "commit", "-q", "-m", "a question")
        out = self.run_with(lambda: None, {"zone": "Work", "file": q.name, "label": "Acme Review"})
        self.assertIn("status: open", q.read_text())
        self.assertTrue((self.work / "Inbox" / "e.eml").exists())

    def test_the_verb_reads_the_question_from_its_file_and_refuses_a_label_it_does_not_hold(self):
        self.drop("Work", "e.eml")
        q, _ = intake.ask_question(self.root, self.work / "Inbox" / "e.eml", "Acme Review or Birch Entry?",
                                   [("Acme Review", "File it in Acme Review")], "2026-11-02")
        started = []
        with mock.patch.object(ir, "start", lambda ws, answer=None, spawn=None: started.append(answer) or {"say": "ok", "state": "running"}):
            for bad in ({"zone": "Work", "file": "Needs you/" + q.name, "label": "Birch Entry"},
                        {"zone": "Work", "file": "../Todo.md", "label": "Acme Review"},
                        {"zone": "Work", "file": "Needs you/missing.md", "label": "Acme Review"},
                        {"zone": "Nowhere", "file": "Needs you/" + q.name, "label": "Acme Review"}):
                with self.assertRaises(pa.Refused):
                    pa.intake_answer(self.root, dict(bad, verb="intake-answer"), dt.date(2026, 11, 3))
            pa.intake_answer(self.root, {"verb": "intake-answer", "zone": "Work", "file": "Needs you/" + q.name, "label": "Acme Review"},
                             dt.date(2026, 11, 3))
        self.assertEqual([{"zone": "Work", "file": q.name, "label": "Acme Review"}], started)


class TestTheQuestion(RunCase):
    def test_a_question_names_nothing_of_another_walled_zone(self):
        self.drop("Work", "a.eml")
        item = self.work / "Inbox" / "a.eml"
        for words in ("Maple Studio or Acme Corp?", "Is it from Pat Lee?", "Work or maple.example?", "Own affairs or Work?"):
            with self.assertRaises(intake.Refusal, msg=words):
                intake.ask_question(self.root, item, words, [("Work", "File it in Work")])
        with self.assertRaises(intake.Refusal):
            intake.ask_question(self.root, item, "Which one?", [("Work", "File it for Maple Studio")])
        q, fresh = intake.ask_question(self.root, item, "Work, from Acme?", [("Work", "File it in Work"), ("Personal", "It is not for Work")])
        self.assertTrue(fresh)
        text = q.read_text()
        self.assertIn("**Work, from Acme?**", text)
        self.assertIn("- [Work] File it in Work", text)
        self.assertIn("intake:", text)
        again, fresh = intake.ask_question(self.root, item, "Work, from Acme?", [("Work", "File it in Work")])
        self.assertEqual((q, False), (again, fresh))

    def test_a_question_is_written_only_for_an_item_waiting_in_a_zones_inbox(self):
        write(self.root / "Inbox" / "x.eml", mail("x"))
        for path in (self.root / "Inbox" / "x.eml", self.acme / "Acme Review.md", self.work / "Inbox" / "missing.eml"):
            with self.assertRaises(intake.Refusal):
                intake.ask_question(self.root, path, "Which zone?", [("Work", "File it in Work")])

    def test_a_label_and_the_number_of_answers_are_held(self):
        self.drop("Work", "a.eml")
        item = self.work / "Inbox" / "a.eml"
        for options in ([], [("x", "does")], [("Not now", "does")], [("a]b", "does")], [("A", "d"), ("a", "d")], [("L%d" % i, "d") for i in range(7)]):
            with self.assertRaises(intake.Refusal, msg=options):
                intake.ask_question(self.root, item, "Which one?", options)


class TestStarting(RunCase):
    def test_the_second_press_while_a_run_holds_the_lock_says_so_and_starts_nothing(self):
        self.jobs.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self.jobs / ir.LOCK), os.O_RDWR | os.O_CREAT)
        fcntl.flock(fd, fcntl.LOCK_EX)
        self.addCleanup(os.close, fd)
        spawned = []
        with mock.patch.object(ir, "available", return_value=True):
            got = ir.start(self.root, spawn=lambda args, fd: spawned.append(args))
        self.assertEqual((ir.SAY_BUSY, []), (got["say"], spawned))
        with mock.patch.object(ir, "available", return_value=True):
            with self.assertRaises(pa.Refused):
                mock_start = mock.patch.object(ir, "start", return_value=got)
                with mock_start:
                    pa.inbox_run_start(self.root)

    def test_one_press_starts_one_run_holding_the_lock_and_a_second_press_is_refused_until_it_ends(self):
        spawned = []

        def spawn(args, fd):
            spawned.append(args)
            self.child = os.dup(fd)             # the child's own copy of the open lock
        with mock.patch.object(ir, "available", return_value=True):
            first = ir.start(self.root, spawn=spawn)
            second = ir.start(self.root, spawn=spawn)
        self.assertEqual("running", first["state"])
        self.assertTrue(second.get("busy"))
        self.assertEqual(1, len(spawned))
        self.assertIn("--lock-fd", spawned[0])
        os.close(self.child)
        with mock.patch.object(ir, "available", return_value=True):
            third = ir.start(self.root, spawn=lambda a, f: spawned.append(a))
        self.assertEqual("running", third["state"])

    def test_with_ask_at_read_another_assistant_or_no_background_assistant_the_run_is_unavailable(self):
        spawned = []
        read = dict(self.cap, ok=False)
        for env, cap in (({"GARRICK_HARNESS": "codex"}, self.cap), ({}, read)):
            with mock.patch.dict(os.environ, env), mock.patch.object(ir.channels, "capability", return_value=cap):
                got = ir.start(self.root, spawn=lambda a, f: spawned.append(a))
            self.assertTrue(got.get("unavailable"), env)
            self.assertIn("visible", got["say"])
        self.assertEqual([], spawned)

    def test_the_two_verbs_are_for_the_page_alone_and_declared(self):
        ops = pa.ops_lib(self.root)
        for verb in ("inbox-run", "intake-answer"):
            self.assertIn(verb, pa.VERBS)
            self.assertIn(verb, pa.PAGE_ONLY)
            self.assertIn(verb, ops.DECLARED)
        self.assertEqual((), ops.DECLARED["inbox-run"].fields)
        self.assertEqual(("zone", "file", "label"), ops.DECLARED["intake-answer"].fields)
        got = pa.perform(self.root, {"verb": "inbox-run"}, ops, via="ask")[0]
        self.assertFalse(got["ok"])
        got = pa.perform(self.root, {"verb": "inbox-run", "folder": "/tmp"}, ops, via="page")[0]
        self.assertFalse(got["ok"])                                           # a field it does not declare

    def test_a_stale_visible_request_is_cleared_when_the_run_is_entered_again_and_when_the_act_cannot_start_c9(self):
        swift = (STATUS / "app" / "Garrick.swift").read_text()
        run = swift[swift.index("func runInbox("):]
        run = run[:run.index("\n\t}\n")]
        self.assertLess(run.index("inboxFallback = nil"), run.index("inboxFallback = visible"))
        act = swift[swift.index("\tfunc act(_ request: [String: Any]) {"):]
        guard = act[:act.index("let script =")]
        self.assertIn('request["verb"] as? String == "inbox-run" { inboxFallback = nil }', guard)

    def test_the_app_and_the_page_fall_back_to_the_visible_session_only_on_an_unavailable_reply(self):
        swift = (STATUS / "app" / "Garrick.swift").read_text()
        self.assertIn('act(["verb": "inbox-run"])', swift)
        self.assertIn('if said["unavailable"] as? Bool == true { return openInbox(visible) }', swift)
        self.assertEqual(2, swift.count("runInbox(act)"))                         # the menu and the panel; nothing else opens the session first
        self.assertEqual(1, swift.count("self.openInbox(") + swift.count("openInbox(visible)") - 0)
        js = status.INBOX_JS
        self.assertIn("out.unavailable", js)
        self.assertIn("button[data-request=\"process the inbox\"]", js)
        self.assertIn("'intake-answer'", js)

    def test_the_run_keeps_off_the_nightly_job(self):
        jobs = (REPO / "extras" / "jobs")
        for f in jobs.glob("*.py"):
            self.assertNotIn("inbox_run", f.read_text(), f.name)
            self.assertNotIn("intake.py ask", f.read_text(), f.name)


class TestTheRow(unittest.TestCase):
    def setUp(self):
        self.status = status
        self.ws = Path("/w")

    def state(self, **more):
        return dict({"state": "done", "at": dt.datetime.now().isoformat(timespec="seconds"), "say": "Work: filed 7 · 2 questions",
                     "places": {"Work": {"filed": 7, "questions": 2, "needs": 0}}}, **more)

    def test_the_button_starts_the_run_in_the_app_and_keeps_the_visible_request_for_a_browser(self):
        button, said = self.status.inbox_act(None, self.ws)
        self.assertIn('data-act="{&quot;verb&quot;: &quot;inbox-run&quot;}"', button)
        self.assertIn("act apponly", button)
        self.assertIn('data-request="process the inbox"', button)
        self.assertIn("webonly", button)
        self.assertEqual("", said)

    def test_the_result_is_one_sentence_a_failure_offers_the_visible_session_and_a_run_going_waits(self):
        button, said = self.status.inbox_act(self.state(), self.ws)
        self.assertEqual("Work: filed 7 · 2 questions", said)
        button, said = self.status.inbox_act(self.state(state="failed", say=ir.SAY_FAILED), self.ws)
        self.assertEqual(ir.SAY_FAILED, said)
        self.assertIn("Process it with my assistant", button)
        for shown in (said, button):
            self.assertNotRegex(shown, r"exit|\b124\b|Traceback")
        button, said = self.status.inbox_act(self.state(state="running"), self.ws)
        self.assertIn("disabled", button)
        self.assertEqual("Processing the inbox…", said)

    def test_the_row_shows_only_the_places_it_lists_w4(self):
        both = self.state(say="Personal: filed 1; Work: filed 7 \u00b7 2 questions", places={"Work": {"filed": 7, "questions": 2, "needs": 0},
                          "Personal": {"filed": 1, "questions": 0, "needs": 0}},
                          lines={"Work": "filed 7 \u00b7 2 questions", "Personal": "filed 1"}, tail="", kept=["Personal"])
        _, said = self.status.inbox_act(both, self.ws, ["Work"])
        self.assertEqual("Work: filed 7 \u00b7 2 questions", said)
        self.assertNotIn("Personal", said)
        _, said = self.status.inbox_act(both, self.ws, ["Personal"])
        self.assertIn("Personal: filed 1", said)
        self.assertNotIn("Work", said)
        self.assertIn("nothing was committed or put back in Personal", said)
        _, said = self.status.inbox_act(both, self.ws)                               # no list: the whole sentence
        self.assertIn("Work: filed 7", said)
        self.assertIn("Personal: filed 1", said)

    def test_a_place_the_row_does_not_list_is_not_named_by_a_kept_repository_either_w4(self):
        state = self.state(state="failed", say="x", lines={}, tail=ir.SAY_FAILED, kept=["Personal"])
        _, said = self.status.inbox_act(state, self.ws, ["Work"])
        self.assertEqual(ir.SAY_FAILED, said)

    def test_a_run_that_died_is_not_shown_as_going_and_an_old_result_is_not_shown(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws, jobs = Path(tmp) / "w", Path(tmp) / "jobs"
            jobs.mkdir()
            (ws / "System" / "generated").mkdir(parents=True)
            (ws / "System" / "generated" / "status-inbox.json").write_text(json.dumps(self.state(state="running")))
            now = dt.datetime.now()
            self.assertIsNone(self.status.inbox_state(ws, now, jobs))                         # no lock held: it is not going
            fd = os.open(str(jobs / "inbox-run.lock"), os.O_RDWR | os.O_CREAT)
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                self.assertEqual("running", self.status.inbox_state(ws, now, jobs)["state"])
            finally:
                os.close(fd)
            (ws / "System" / "generated" / "status-inbox.json").write_text(json.dumps(self.state(at=(now - dt.timedelta(days=3)).isoformat())))
            self.assertIsNone(self.status.inbox_state(ws, now, jobs))

    def test_an_intake_question_is_a_row_in_its_own_zone_with_the_intake_verb(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            write(ws / "Zones" / "Work" / "Needs you" / "261102 - ask a.md",
                  "---\ntype: question\nstatus: open\nasked: 2026-11-02\nintake: \"a.eml\"\n---\n\n**Acme Review or Birch Entry?**\n\n"
                  "- [Acme Review] File it in Acme Review\n- [Birch Entry] File it in Birch Entry\n")
            write(ws / "Zones" / "Work" / "Needs you" / "261102 - other.md", "---\ntype: question\nstatus: open\n---\n\n**Not an inbox question**\n\n- [Yes] Yes\n")
            rows = self.status.question_needs(ws, dt.date(2026, 11, 3))
            self.assertEqual(1, len(rows))
            self.assertEqual("Work", rows[0]["zone"])
            self.assertEqual("Acme Review or Birch Entry?", rows[0]["text"])
            self.assertEqual(3, rows[0]["act"].count("&quot;intake-answer&quot;"))          # two answers and Not now
            self.assertIn("Not now", rows[0]["act"])
            self.assertNotIn("&quot;verb&quot;: &quot;answer&quot;", rows[0]["act"])


if __name__ == "__main__":
    unittest.main()
