"""The todo skill's script: expire, archive and tidy a zone's Todo.md.

    python3 -m unittest discover -s tests
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

from fixtures import build_workspace, checkpoint, write  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("garrick_todo", str(REPO / "template" / "System" / "skills" / "todo" / "todo.py"))
todo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(todo)

_tl = importlib.util.spec_from_file_location("garrick_todo_lines_t", str(REPO / "extras" / "status" / "todo_lines.py"))
todo_lines = importlib.util.module_from_spec(_tl)
_tl.loader.exec_module(todo_lines)

LIST = """# Work: open actions

The header the list keeps.

## Inbox

- [ ] [[Pricing]]: send the sheet
- [ ] Dana: confirm volumes
- [ ] [[Freight]]: book the call 📅 2026-10-20
- [ ] [[Pricing]]: 🔺 check the tier 📅 2026-10-21 against Birch's

## This week

- [ ] [[Pricing]]: draft the memo 📅 2026-10-14

## Waiting on

- [ ] [[Pricing]]: Dana's volumes #waiting ⏳ 2026-10-16
- [ ] Theo: the signed letter #waiting

## Done

- [x] [[Pricing]]: old one ✅ 2026-10-01
    - [ ] a step left open under it
- [x] [[Freight]]: today's ✅ 2026-10-12
"""


class TodoTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "Workspace"
        build_workspace(self.root)
        self.zone = self.root / "Zones" / "Work"
        write(self.zone / "Todo.md", LIST)

    def text(self):
        return (self.zone / "Todo.md").read_text()

    def test_expire_waits_its_days_then_moves_the_untriaged_lines_out_unchanged(self):
        day = dt.date(2026, 10, 1)
        self.assertEqual(0, todo.expire(self.root, self.zone, day))
        seen = json.loads((self.zone / todo.LEDGER).read_text())
        self.assertEqual(day.isoformat(), seen[todo_lines.key("- [ ] Dana: confirm volumes")])   # the page's key
        self.assertEqual(0, todo.expire(self.root, self.zone, day + dt.timedelta(days=13)))
        self.assertEqual(3, todo.expire(self.root, self.zone, day + dt.timedelta(days=14)))   # two undated Inbox lines, one Waiting on
        text = self.text()
        self.assertNotIn("Theo: the signed letter", text)
        self.assertIn("Dana's volumes #waiting ⏳ 2026-10-16", text)          # a day to chase: triaged
        self.assertNotIn("send the sheet", text)
        self.assertNotIn("confirm volumes", text)
        self.assertIn("book the call 📅 2026-10-20", text)                   # dated: triaged
        self.assertIn("draft the memo", text)                               # moved to This week: triaged
        expired = (self.zone / "archive" / "Todo-expired-2026.md").read_text()
        self.assertIn("- [ ] [[Pricing]]: send the sheet\n", expired)       # open, as it was
        self.assertIn("- [ ] Theo: the signed letter #waiting\n", expired)

    def test_a_waiting_on_line_with_no_chase_day_survives_its_first_night(self):
        day = dt.date(2026, 10, 1)
        text = self.text().replace("- [ ] Theo: the signed letter #waiting\n", "")
        write(self.zone / "Todo.md", text.replace("## Waiting on\n\n", "## Waiting on\n\n- [ ] Send the contract → Dana #waiting\n"))
        line = "- [ ] Send the contract → Dana #waiting"
        for n in range(14):                                                 # the first night, and every night to the fourteenth
            todo.expire(self.root, self.zone, day + dt.timedelta(days=n))
            self.assertIn(line, self.text())
        self.assertEqual(day.isoformat(), json.loads((self.zone / todo.LEDGER).read_text())[todo_lines.key(line)])
        todo.expire(self.root, self.zone, day + dt.timedelta(days=14))     # the fifteenth night
        self.assertNotIn(line, self.text())
        self.assertIn(line + "\n", (self.zone / "archive" / "Todo-expired-2026.md").read_text())

    def test_the_days_can_be_set_per_zone(self):
        write(self.root / "System" / "garrick-checks.json", json.dumps({"todo-expire-days": {"Work": 3}}))
        self.assertEqual(3, todo.expire_days(self.root, "Work", None))
        self.assertEqual(14, todo.expire_days(self.root, "Personal", None))
        write(self.root / "System" / "garrick-checks.json", json.dumps({"todo-expire-days": 30}))
        self.assertEqual(30, todo.expire_days(self.root, "Personal", None))

    def test_a_lines_thread_and_the_day_it_was_done(self):
        """What briefing.py reads a thread's lines with (#27): the link an open
        or a ticked line opens with, and a ticked line's ✅ day."""
        self.assertEqual("Pricing", todo.link_of("- [x] [[Pricing]]: old one ✅ 2026-10-01"))
        self.assertEqual("Acme/Threads/Pricing/Pricing", todo.link_of("- [ ] [[Acme/Threads/Pricing/Pricing|Pricing]]: send it"))
        self.assertIsNone(todo.link_of("- [ ] Dana: confirm volumes"))
        self.assertEqual(dt.date(2026, 10, 1), todo.done_on("- [x] [[Pricing]]: old one ✅ 2026-10-01"))
        self.assertIsNone(todo.done_on("- [ ] [[Pricing]]: send it ✅ 2026-10-01"))
        self.assertIsNone(todo.done_on("- [x] [[Pricing]]: no day"))

    def test_archive_keeps_today_and_moves_the_rest_by_year(self):
        self.assertEqual(1, todo.archive(self.zone, dt.date(2026, 10, 12)))
        self.assertIn("today's ✅ 2026-10-12", self.text())
        self.assertNotIn("old one", self.text())
        archived = (self.zone / "archive" / "Todo-2026.md").read_text()
        self.assertIn("- [x] [[Pricing]]: old one ✅ 2026-10-01\n    - [ ] a step left open under it", archived)
        self.assertNotIn("a step left open", self.text())                  # it went with its task

    def test_a_moved_lines_relative_source_still_leads_to_its_page(self):
        """#318: a line's meeting source is a link relative to Todo.md. Moved
        into archive/, archived or expired, it is written again from there;
        a wikilink, an obsidian: link and a web link stay as they were."""
        page = self.root / "Wikis" / "Meetings" / "wiki" / "sources" / "260310-acme-kickoff.md"
        src = "[Acme kick-off](../../Wikis/Meetings/wiki/sources/260310-acme-kickoff.md)"
        write(self.zone / "Todo.md", LIST.replace("- [x] [[Pricing]]: old one ✅ 2026-10-01",
                                                  "- [x] [[Pricing]]: old one · %s ✅ 2026-10-01" % src)
              .replace("- [ ] [[Pricing]]: send the sheet",
                       "- [ ] [[Pricing]]: send the sheet · %s (also in [[260312-birch-kickoff]]) see https://example.com/a" % src))
        todo.archive(self.zone, dt.date(2026, 10, 12))
        day = dt.date(2026, 10, 1)
        todo.expire(self.root, self.zone, day)
        todo.expire(self.root, self.zone, day + dt.timedelta(days=14))
        deeper = "[Acme kick-off](../../../Wikis/Meetings/wiki/sources/260310-acme-kick-off.md)".replace("kick-off.md", "kickoff.md")
        archived = (self.zone / "archive" / "Todo-2026.md").read_text()
        expired = (self.zone / "archive" / "Todo-expired-2026.md").read_text()
        self.assertIn("- [x] [[Pricing]]: old one · %s ✅ 2026-10-01" % deeper, archived)
        self.assertIn("- [ ] [[Pricing]]: send the sheet · %s (also in [[260312-birch-kickoff]]) see https://example.com/a" % deeper, expired)
        target = re.search(r"\]\(([^)]+)\)", deeper).group(1)
        self.assertEqual(page.resolve(), (self.zone / "archive" / target).resolve())      # it leads to the page from there
        self.assertEqual("[x](obsidian://open?vault=W&file=a)", todo.relinked("[x](obsidian://open?vault=W&file=a)", self.zone,
                                                                              self.zone / "archive"))
        self.assertEqual("[x](../../../A%20b.md#h)", todo.relinked("[x](../../A%20b.md#h)", self.zone, self.zone / "archive"))
        moved = lambda line: todo.relinked(line, self.zone, self.zone / "archive")
        self.assertEqual("see `[code](../x.md)` and [x](../../x.md)", moved("see `[code](../x.md)` and [x](../x.md)"))   # code stays code
        self.assertEqual("[q](../a.md?x=1&y=2) [t](../../../W.md#Sec%20one)", moved("[q](a.md?x=1&y=2) [t](../../W.md#Sec%20one)"))
        self.assertEqual("[p](../../../Wikis/Meetings/wiki/sources/a(1).md) ✅", moved("[p](../../Wikis/Meetings/wiki/sources/a(1).md) ✅"))
        self.assertEqual("[a](#h) [w](https://e.com/a.md) [abs](/etc/hosts)", moved("[a](#h) [w](https://e.com/a.md) [abs](/etc/hosts)"))
        self.assertEqual("![i](../pic.png)", moved("![i](pic.png)"))

    def test_tidy_puts_fields_last_and_the_inbox_in_thread_order(self):
        self.assertGreater(todo.tidy(self.zone), 0)
        inbox = self.text().split("## Inbox\n\n", 1)[1].split("\n\n", 1)[0].splitlines()
        self.assertEqual(["- [ ] [[Pricing]]: send the sheet",
                          "- [ ] [[Pricing]]: check the tier against Birch's 🔺 📅 2026-10-21",
                          "- [ ] [[Freight]]: book the call 📅 2026-10-20",
                          "- [ ] Dana: confirm volumes"], inbox)
        self.assertEqual(0, todo.tidy(self.zone))                          # a second run changes nothing

    def test_the_inbox_can_follow_thread_names_as_a_tasks_query_does(self):
        write(self.zone / "Todo.md", LIST.replace("- [ ] Dana: confirm volumes\n",
                                                  "- [ ] Dana: confirm volumes\n- [ ] [[Acme/Threads/Zed|Audit]]: book it\n"))
        write(self.root / "System" / "garrick-checks.json", json.dumps({"todo-inbox-order": {"Work": "thread"}}))
        self.assertEqual("thread", todo.inbox_order(self.root, "Work"))
        self.assertEqual("first-seen", todo.inbox_order(self.root, "Personal"))
        todo.tidy(self.zone, "thread")
        inbox = self.text().split("## Inbox\n\n", 1)[1].split("\n\n", 1)[0].splitlines()
        self.assertEqual(["- [ ] [[Acme/Threads/Zed|Audit]]: book it",                 # by its alias
                          "- [ ] [[Freight]]: book the call 📅 2026-10-20",
                          "- [ ] [[Pricing]]: send the sheet",
                          "- [ ] [[Pricing]]: check the tier against Birch's 🔺 📅 2026-10-21",
                          "- [ ] Dana: confirm volumes"], inbox)
        found = [f for f in __import__("check").run_checks(self.root) if f.check == "settings"]
        self.assertEqual([], found)                                         # both todo keys are settings the check knows

    def test_tidy_keeps_a_moved_lines_first_seen_day_and_oldest_names_the_next_to_expire(self):
        day = dt.date(2026, 10, 1)
        todo.expire(self.root, self.zone, day)
        write(self.zone / "Todo.md", self.text().replace("## Inbox\n\n", "## Inbox\n\n- [ ] [[Freight]]: a new one\n"))
        todo.expire(self.root, self.zone, day + dt.timedelta(days=3))
        before = "- [ ] [[Pricing]]: 🔺 check the tier 📅 2026-10-21 against Birch's"
        todo.tidy(self.zone)
        after = "- [ ] [[Pricing]]: check the tier against Birch's 🔺 📅 2026-10-21"
        seen = json.loads((self.zone / todo.LEDGER).read_text())
        self.assertNotIn(todo.key(before), seen)
        self.assertEqual(day.isoformat(), seen[todo.key(after)])
        self.assertEqual("- [ ] [[Freight]]: a new one", todo.oldest(self.zone, day + dt.timedelta(days=3), 10)[-1])
        self.assertEqual(2, len(todo.oldest(self.zone, day, 2)))

    def test_the_digest_reads_the_list_as_a_person_would(self):
        today = dt.date(2026, 10, 21)
        write(self.zone / "archive" / "Todo-expired-2026.md", "# Work\n\n<!-- 2026-10-20 -->\n- [ ] old\n<!-- 2026-10-21 -->\n- [ ] gone today\n")
        text = todo.digest(self.zone, today)
        self.assertTrue(text.startswith("Todo · Work"))
        self.assertIn("Overdue · 2\n- Pricing: draft the memo (7d late)\n- Freight: book the call (1d late)", text)
        self.assertIn("Due today · 1\n- Pricing: check the tier against Birch's", text)
        self.assertIn("Chase, they owe you · 1\n- Pricing: Dana's volumes", text)
        self.assertIn("Inbox · 4 untriaged", text)
        self.assertNotIn("oldest three", text)                              # ten or fewer: the count says enough
        self.assertIn("Expired today · 1", text)
        self.assertIn("2 undated · 1 waiting with no chase date", text)
        self.assertNotIn("[[", text)
        self.assertNotIn("#waiting", text)

    def test_the_chase_days_are_the_zones_or_seven(self):
        self.assertEqual(7, todo.chase_days(self.root, "Work"))
        write(self.root / "System" / "garrick-checks.json", json.dumps({"todo-chase-days": {"Work": 0}}))
        self.assertEqual(0, todo.chase_days(self.root, "Work"))
        self.assertEqual(7, todo.chase_days(self.root, "Personal"))

    def test_all_from_the_command_line(self):
        import io
        from contextlib import redirect_stdout
        out = io.StringIO()
        with redirect_stdout(out):
            todo.main(["all", "--zone", "work", "--root", str(self.root), "--today", "2026-10-12", "--json"])
        self.assertEqual({"zone": "Work", "expired": 0, "archived": 1, "tidied": 3}, json.loads(out.getvalue()))
        self.assertIn("The header the list keeps.", self.text())

    def test_the_wrap_archives_a_zone_no_sweep_reaches(self):
        """The command the threads skill's wrap runs before its commit, as it
        gives it: a line ticked on an earlier day goes, whatever thread it names,
        and one ticked today the way the wrap ticks, with its ✅ date, stays."""
        import io
        import shlex
        from contextlib import redirect_stdout
        skill = (REPO / "template" / "System" / "skills" / "threads" / "SKILL.md").read_text(encoding="utf-8")
        line = next(l.strip() for l in skill.splitlines() if "todo/todo.py archive" in l)
        argv = shlex.split(line.replace("<Zone>", "Work"))
        self.assertEqual(["python3", "System/skills/todo/todo.py"], argv[:2])
        write(self.zone / "Todo.md", self.text().replace("- [ ] [[Pricing]]: send the sheet",
                                                         "- [x] [[Pricing]]: send the sheet ✅ 2026-10-12"))
        with redirect_stdout(io.StringIO()):
            todo.main(argv[2:] + ["--root", str(self.root), "--today", "2026-10-12"])
        after = self.text()
        self.assertIn("- [x] [[Pricing]]: send the sheet ✅ 2026-10-12", after)       # ticked by this wrap
        self.assertIn("today's ✅ 2026-10-12", after)
        self.assertNotIn("old one", after)                                            # ticked on an earlier day
        self.assertIn("old one", (self.zone / "archive" / "Todo-2026.md").read_text())
        self.assertIn("- [ ] Dana: confirm volumes", after)                           # nothing open moves
        self.assertIn("- [ ] Theo: the signed letter #waiting", after)


class SourceFormsTest(unittest.TestCase):
    """#318: a Todo line's source is written as a relative link to the meeting
    page's file now; the lines already written keep a wikilink or an
    obsidian: link. The digest and the page's reader take all three."""

    LINES = ("- [ ] [[Pricing]]: chase Dana · [Acme kick-off](../../Wikis/Meetings/wiki/sources/260310-acme-kickoff.md) 📅 2026-03-12",
             "- [ ] [[Pricing]]: chase Dana · [Acme kick-off](obsidian://open?vault=Wikis&file=Meetings%2Fwiki%2Fsources%2F260310-acme-kickoff) 📅 2026-03-12",
             "- [ ] [[Pricing]]: chase Dana · [[260310-acme-kickoff]] 📅 2026-03-12")

    def test_the_digest_says_the_action_whatever_the_source(self):
        for line in self.LINES[:2]:                                     # a Markdown link's source is left out
            self.assertEqual("Pricing: chase Dana", todo.plain(line), line)
        self.assertTrue(todo.plain(self.LINES[2]).startswith("Pricing: chase Dana"))   # a wikilink's, as before

    def test_the_page_reads_the_line_whatever_the_source(self):
        for line in self.LINES:
            t = todo_lines.parse(line)
            self.assertEqual(("Pricing", "2026-03-12"), (t["thread"], t["due"]), line)
            self.assertTrue(t["text"].startswith("chase Dana · "), line)
            self.assertEqual(todo_lines.same_action(self.LINES[0]).split(" · ")[0], todo_lines.same_action(line).split(" · ")[0])


class SweepJobTest(unittest.TestCase):
    """extras/jobs/todo_sweep.py with the assistant faked: one call per zone,
    then the script, then one commit."""

    def setUp(self):
        import os
        import shutil
        from unittest import mock
        from fixtures import git, HAVE_GIT
        if not HAVE_GIT:
            self.skipTest("git is not installed")
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "Workspace"
        build_workspace(self.root)
        self.zone = self.root / "Zones" / "Work"
        shutil.rmtree(self.zone / ".git")
        env = mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                                           "GIT_AUTHOR_NAME": "Jo", "GIT_AUTHOR_EMAIL": "jo@example.invalid",
                                           "GIT_COMMITTER_NAME": "Jo", "GIT_COMMITTER_EMAIL": "jo@example.invalid",
                                           "GARRICK_JOBS_DIR": str(Path(self._tmp.name) / "jobs")})
        env.start()
        self.addCleanup(env.stop)
        self.git = lambda *a: git(self.zone, *a)
        self.git("init", "-q")
        write(self.zone / "Todo.md", LIST)
        write(self.zone / ".gitignore", ".todo-seen.json\n")                    # as Garrick's zone ignore lines say
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "start")
        skill = self.root / "System" / "skills" / "todo"
        skill.mkdir(parents=True)
        shutil.copy(REPO / "template" / "System" / "skills" / "todo" / "todo.py", skill / "todo.py")
        sys.path.insert(0, str(REPO / "extras" / "jobs"))
        spec = importlib.util.spec_from_file_location("garrick_todo_sweep", str(REPO / "extras" / "jobs" / "todo_sweep.py"))
        self.job = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.job)
        self.mock = mock

    def fake(self, answer, edit=True):
        def run(tier, prompt, allow=(), cwd=None, **kw):
            self.prompts.append(prompt)
            if edit:
                todo_md = self.zone / "Todo.md"
                todo_md.write_text(todo_md.read_text().replace("## Inbox\n\n", "## Inbox\n\n- [ ] [[Pricing]]: call Dana back\n", 1))
            return 0, answer
        self.prompts = []
        return self.mock.patch.object(self.job.agent, "run", side_effect=run)

    def test_a_sweep_adds_tidies_and_commits_in_one(self):
        with self.fake("Done.\nADDED 1 FOLDED 2\n" + self.job.SENTINEL + "\n"):
            code, changed, said = self.job.sweep_zone(self.root, self.zone, "sonnet", "2026-10-12")
        self.assertEqual(0, code, said)
        self.assertIn("for the Work zone only", self.prompts[0])
        self.assertIn("call Dana back", self.text())
        self.assertEqual("", self.git("status", "--porcelain").strip())
        self.assertIn("Work: actions swept; 1 added, 2 folded", self.git("log", "-1", "--format=%s"))
        self.assertIn("archive/Todo-2026.md", self.git("show", "--stat", "--format=", "HEAD"))
        self.assertGreaterEqual(changed, 3)

    def test_an_incomplete_answer_leaves_the_list_as_it_was(self):
        with self.fake("I got halfway."):
            code, changed, said = self.job.sweep_zone(self.root, self.zone, "sonnet", "2026-10-12")
        self.assertEqual(self.job.EXIT_INCOMPLETE, code)
        self.assertEqual(LIST, self.text())
        self.assertEqual("", self.git("status", "--porcelain").strip())

    def test_the_prompt_follows_the_chase_days(self):
        self.assertIn("7 days from today when the source gives none", self.job.prompt_for("Work", "2026-10-12"))
        write(self.root / "System" / "garrick-checks.json", json.dumps({"todo-chase-days": 0}))
        with self.fake("ADDED 1 FOLDED 0\n" + self.job.SENTINEL + "\n"):
            self.job.sweep_zone(self.root, self.zone, "sonnet", "2026-10-12")
        self.assertIn("only when the source gives one: never one of your own", self.prompts[0])

    def test_the_digest_goes_through_the_notifier_from_the_zone_even_when_the_sweep_failed(self):
        import os
        out = Path(self._tmp.name) / "notices.txt"
        notifier = Path(self._tmp.name) / "notify.sh"
        notifier.write_text('printf "%s|%s|%s|%s\\n---\\n" "$GARRICK_NOTIFY_KIND" "$GARRICK_ZONE" "$PWD" "$2" >> "' + str(out) + '"\n')
        with self.mock.patch.dict(os.environ, {"GARRICK_NOTIFY_CMD": "/bin/sh %s" % notifier}):
            with self.fake("I got halfway.", edit=False):
                code = self.job.main(["--workspace", str(self.root), "--zone", "Work", "--digest"])
        self.assertEqual(self.job.EXIT_INCOMPLETE, code)
        notice = out.read_text()
        self.assertTrue(notice.startswith("digest|Work|%s|The sweep did not finish this morning" % self.zone.resolve()), notice)
        self.assertIn("Todo · Work", notice)

    def text(self):
        return (self.zone / "Todo.md").read_text()


if __name__ == "__main__":
    unittest.main()


class CheckpointStaysOutTest(unittest.TestCase):
    """The sweep reads the Resume here block's Next action and never the
    checkpoint beside it, so an unconfirmed next action and the actions a
    checkpoint is holding to file never turn into lines of their own."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "Workspace"
        build_workspace(self.root)
        self.zone = self.root / "Zones" / "Work"
        write(self.zone / "Todo.md", LIST)
        self.note = self.zone / "Acme Review" / "Threads" / "Pricing" / "Pricing.md"
        write(self.note, checkpoint(self.note.read_text()))

    def test_no_line_of_the_block_is_a_task(self):
        lines = [t["line"] for t in todo_lines.tasks(str(self.zone))]
        self.assertTrue(lines)                                        # the list's own lines are found
        for line in lines:
            self.assertNotIn("<!--", line)
        for held in ("send Dana the price sheet", "fill in the tier-two volume on row 14",
                     "the tier-three tab is half filled"):
            self.assertFalse([l for l in lines if held in l], held)

    def test_the_sweep_leaves_the_list_and_the_block_as_they_are(self):
        before = self.note.read_bytes()
        day = dt.date(2026, 10, 15)
        todo.expire(self.root, self.zone, day)
        todo.archive(self.zone, day)
        todo.tidy(self.zone)
        self.assertEqual(before, self.note.read_bytes())              # the script never touches a thread note
        text = (self.zone / "Todo.md").read_text()
        self.assertNotIn("send Dana the price sheet", text)
        self.assertNotIn("row 14", text)

    def test_the_digest_counts_only_the_list(self):
        said = todo.digest(self.zone, dt.date(2026, 10, 15))
        self.assertNotIn("price sheet", said)
        self.assertNotIn("row 14", said)

    def test_the_skill_says_the_block_is_not_read(self):
        skill = (REPO / "template" / "System" / "skills" / "todo" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Never\n     the `### Checkpoint` block beside it", skill)
