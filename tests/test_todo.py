"""The todo skill's script: expire, archive and tidy a zone's Todo.md.

    python3 -m unittest discover -s tests
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import re
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

sys.dont_write_bytecode = True

import fixtures  # noqa: E402
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

    def test_classify_holds_every_open_line_for_a_list_of_them(self):
        """#316: the Ask box lists what is owed from this one reading, so the
        lines a digest only counts are here too, each once."""
        lines = ["## Inbox", "- [ ] late 📅 2026-10-01", "- [ ] today 📅 2026-10-12", "- [ ] soon 📅 2026-10-20",
                 "- [ ] undated", "- [ ] <action>", "## Waiting on", "- [ ] chased ⏳ 2026-10-11",
                 "- [ ] later chase ⏳ 2026-10-15", "- [ ] no chase", "- [x] done ✅ 2026-10-11"]
        got = todo.classify(lines, dt.date(2026, 10, 12))
        self.assertEqual([(11, "- [ ] late 📅 2026-10-01")], got["overdue"])
        self.assertEqual(["- [ ] today 📅 2026-10-12"], got["due"])
        self.assertEqual([("2026-10-20", "- [ ] soon 📅 2026-10-20")], got["later"])
        self.assertEqual(["- [ ] undated"], got["open"])
        self.assertEqual(["- [ ] chased ⏳ 2026-10-11"], got["chase"])
        self.assertEqual([("2026-10-15", "- [ ] later chase ⏳ 2026-10-15"), ("", "- [ ] no chase")], got["waiting"])
        self.assertEqual((1, 1), (got["undated"], got["no_chase"]))

    def test_a_date_no_calendar_has_is_no_date(self):
        """A typo such as 31 April fails no reader of the list: the line is
        read as undated, or as waiting with no chase date, and the rest as
        before."""
        lines = ["## Inbox", "- [ ] past typo 📅 2026-02-30", "- [ ] future typo 📅 2026-04-31",
                 "- [ ] late 📅 2026-10-01", "## Waiting on", "- [ ] chase typo ⏳ 2026-02-30",
                 "- [ ] later chase typo ⏳ 2026-11-31", "- [ ] chased ⏳ 2026-10-11"]
        got = todo.classify(lines, dt.date(2026, 10, 12))
        self.assertEqual([(11, "- [ ] late 📅 2026-10-01")], got["overdue"])
        self.assertEqual([], got["later"])
        self.assertEqual(["- [ ] past typo 📅 2026-02-30", "- [ ] future typo 📅 2026-04-31"], got["open"])
        self.assertEqual(["- [ ] chased ⏳ 2026-10-11"], got["chase"])
        self.assertEqual([("", "- [ ] chase typo ⏳ 2026-02-30"), ("", "- [ ] later chase typo ⏳ 2026-11-31")],
                         got["waiting"])
        self.assertEqual((2, 2), (got["undated"], got["no_chase"]))
        write(self.zone / "Todo.md", LIST.replace("📅 2026-10-14", "📅 2026-02-30").replace("✅ 2026-10-01", "✅ 2026-02-30"))
        text = todo.digest(self.zone, dt.date(2026, 10, 21))
        self.assertIn("Overdue · 1\n- Freight: book the call (1d late)", text)
        self.assertIn("3 undated", text)
        self.assertEqual(2, todo.archive(self.zone, dt.date(2026, 10, 21)))

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
        folder = REPO / "template" / "System" / "skills" / "threads"
        skill = "\n".join(f.read_text(encoding="utf-8") for f in [folder / "SKILL.md"] + sorted((folder / "reference").glob("*.md")))
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

    def test_the_digest_leaves_out_a_folded_source_with_its_link(self):
        line = ("- [ ] [[Pricing]]: chase Dana · [Acme kick-off](../../Wikis/Meetings/wiki/sources/260310-acme-kickoff.md)"
                " (also in [Acme 2](../../Wikis/Meetings/wiki/sources/260311-acme-2.md)) 📅 2026-03-12")
        self.assertEqual("Pricing: chase Dana", todo.plain(line))
        self.assertEqual("Pricing: chase Dana", todo.plain(line.replace(" (also in", " · (also in")))

    def test_the_skill_reads_a_folded_source_as_the_check_does(self):
        import garrick_lib
        self.assertEqual(garrick_lib.TODO_ALSO_RE.pattern, todo.ALSO.pattern)

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
        fixtures.stand_in_hook(self.zone)
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

    def next_rows(self, project, thread, action, status="active"):
        note = self.zone / project / "Threads" / thread / (thread + ".md")
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text("---\ntitle: %s\nstatus: %s\n---\n\n# %s\n\n### Resume here\n\n**Where it stands, 1 March 2026.** x.\n\n"
                        "| | |\n|---|---|\n| Next action | %s |\n| Waiting on | nobody |\n\n### Checkpoint\n\n| Next action | not this one |\n"
                        % (thread, status, thread, action), encoding="utf-8")

    def test_the_script_finds_the_meetings_pages_and_next_actions_of_the_zone_alone(self):
        """#567: the listing is the script's; the assistant is handed paths and rows of this zone only."""
        sources = self.root / "Wikis" / "Meetings" / "wiki" / "sources"
        write(sources / "260310-acme-kickoff.md", "---\ntitle: A\ndate: 2026-03-10\nzone: Work\n---\n")
        write(sources / "260101-old.md", "---\ntitle: B\ndate: 2026-01-01\nzone: Work\n---\n")
        write(sources / "260311-home.md", "---\ntitle: C\ndate: 2026-03-11\nzone: Personal\n---\n")
        write(sources / "260312-nozone.md", "---\ntitle: D\ndate: 2026-03-12\n---\n")
        self.next_rows("Acme Review", "Pricing", "Dana to send the volumes")
        self.next_rows("Acme Review", "Parked One", "never listed", status="parked")
        self.next_rows("Birch Entry", "Market Sizing", "<what is next>")
        self.assertEqual(["Wikis/Meetings/wiki/sources/260310-acme-kickoff.md", "Wikis/Meetings/wiki/sources/260312-birch-kickoff.md"],
                         self.job.meeting_pages(self.root, "Work", dt.date(2026, 3, 20)))
        rows = self.job.next_actions(self.root, self.zone)
        self.assertEqual([("Zones/Work/Acme Review/Threads/Pricing/Pricing.md", "Dana to send the volumes")], rows)

    def test_the_prompt_lists_paths_and_rows_and_names_its_tools_and_needs_no_listing(self):
        prompt = self.job.prompt_for("Work", "2026-03-20", 7, ["Wikis/Meetings/wiki/sources/260310-acme-kickoff.md"],
                                     [("Zones/Work/Acme Review/Threads/Pricing/Pricing.md", "Dana to send the volumes")])
        self.assertIn("Use Read, Grep, Glob and Edit only; there is no shell.", prompt)
        self.assertIn("  - Wikis/Meetings/wiki/sources/260310-acme-kickoff.md", prompt)
        self.assertIn("Pricing.md: Dana to send the volumes", prompt)
        for listing in ("whose `zone` is", "in the last 30 days", "of each live thread note", "find ", " ls ", "list the"):
            self.assertNotIn(listing, prompt, listing)

    def test_a_sweep_hands_the_assistant_the_found_paths(self):
        write(self.root / "Wikis" / "Meetings" / "wiki" / "sources" / "260310-acme-kickoff.md",
              "---\ntitle: A\ndate: %s\nzone: Work\n---\n" % dt.date.today().isoformat())
        with self.fake("ADDED 0 FOLDED 0\n" + self.job.SENTINEL + "\n", edit=False):
            self.job.sweep_zone(self.root, self.zone, "sonnet", dt.date.today().isoformat())
        self.assertIn("  - Wikis/Meetings/wiki/sources/260310-acme-kickoff.md", self.prompts[0])

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


class FollowUpTest(unittest.TestCase):
    """#603: the follow-up on a Waiting on line whose chase day has come, found in code with no model."""

    TODAY = dt.date(2026, 10, 20)
    LINE = "- [ ] [[Pricing]]: Dana's volumes #waiting ⏳ 2026-10-16"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "Workspace"
        build_workspace(self.root)
        self.zone = self.root / "Zones" / "Work"
        self.other = self.root / "Zones" / "Personal"
        write(self.zone / "Todo.md", LIST)
        write(self.zone / ".todo-seen.json", json.dumps({todo.key(self.LINE): "2026-10-10"}))
        self.sources = self.root / "Wikis" / "Meetings" / "wiki" / "sources"

    def page(self, name, zone="Work", day="2026-10-12", body="Dana will send the price sheet.", title="Acme pricing call"):
        write(self.sources / name, "---\ntitle: %s\ndate: %s\ncreated: %s\nzone: %s\n---\n\n%s\n" % (title, day, day, zone, body))

    def run_followup(self, today=None):
        return todo.followup(self.root, self.zone, today or self.TODAY)

    def test_no_line_due_records_nothing(self):
        write(self.zone / "Todo.md", LIST.replace("⏳ 2026-10-16", "⏳ 2026-10-25"))
        got = self.run_followup()
        self.assertEqual(0, got["due"])
        self.assertEqual([], got["pending"])
        self.assertFalse((self.zone / ".todo-followups.json").exists())

    def test_a_due_line_with_no_evidence_is_no_sign_and_needs_no_call(self):
        got = self.run_followup()
        self.assertEqual(1, got["no_sign"])
        self.assertEqual([], got["pending"])
        rec = json.loads((self.zone / ".todo-followups.json").read_text())[todo.key(self.LINE)]
        self.assertEqual(("no sign", "", self.LINE, "2026-10-20"), (rec["result"], rec["source"], rec["line"], rec["looked"]))

    def test_a_page_naming_the_person_in_the_zone_is_the_evidence_and_the_list_is_untouched(self):
        self.page("261012-acme-pricing.md")
        got = self.run_followup()
        self.assertEqual(0, got["no_sign"])
        self.assertEqual(1, len(got["pending"]))
        self.assertEqual("Dana Whitlock", got["pending"][0]["person"])
        self.assertEqual(["Wikis/Meetings/wiki/sources/261012-acme-pricing.md"], [e["path"] for e in got["pending"][0]["evidence"]])
        self.assertEqual(LIST, (self.zone / "Todo.md").read_text())

    def test_an_alias_of_the_person_counts(self):
        self.page("261012-acme-pricing.md", body="Dana Whitlaw sent the price sheet.")
        write(self.zone / "Todo.md", LIST.replace("Dana's volumes", "Dana Whitlaw's volumes"))
        line = self.LINE.replace("Dana's volumes", "Dana Whitlaw's volumes")
        write(self.zone / ".todo-seen.json", json.dumps({todo.key(line): "2026-10-10"}))
        got = self.run_followup()
        self.assertEqual(1, len(got["pending"]))

    def test_a_page_before_the_line_was_first_seen_does_not_count(self):
        self.page("261001-old.md", day="2026-10-01")
        self.assertEqual(1, self.run_followup()["no_sign"])

    def judged_texts(self, **patch):
        """The texts handed to the name matcher: what the follow-up opened and read as a page or a mail."""
        seen = []
        real = todo.name_hits

        def spy(text, forms):
            seen.append(text)
            return real(text, forms)
        with unittest.mock.patch.object(todo, "name_hits", spy):
            got = self.run_followup()
        return got, seen

    def test_a_page_of_another_walled_zone_is_never_read_or_a_source(self):
        self.page("261012-home.md", zone="Personal", body="Dana ARCHIVEWORD.")
        self.page("261013-nozone.md", zone="Elsewhere", body="Dana ARCHIVEWORD.")
        got, seen = self.judged_texts()
        self.assertEqual(1, got["no_sign"])
        self.assertEqual([], [t for t in seen if "ARCHIVEWORD" in t])
        self.assertNotIn("261012-home", (self.zone / ".todo-followups.json").read_text())

    def test_a_page_the_wall_refuses_for_the_zone_is_never_read(self):
        self.page("261012-acme-pricing.md", body="Dana ARCHIVEWORD.")
        lib = todo.tools_lib(self.root)
        with unittest.mock.patch.object(lib, "decide", return_value="deny"):
            got, seen = self.judged_texts()
        self.assertEqual(1, got["no_sign"])
        self.assertEqual([], [t for t in seen if "ARCHIVEWORD" in t])

    def test_an_inbox_item_from_the_person_counts_and_another_zones_does_not(self):
        write(self.zone / "Inbox" / "price-sheet.eml", "From: Dana Whitlock <dana@acmecorp.example>\nDate: Wed, 14 Oct 2026 09:00:00 +0000\n"
                                                     "Subject: Price sheet\n\nHere it is.\n")
        write(self.zone / "Inbox" / "from-theo.eml", "From: Theo Marsh <theo@birchco.example>\nDate: Wed, 14 Oct 2026 09:00:00 +0000\nSubject: x\n\nDana.\n")
        write(self.other / "Inbox" / "home.eml", "From: Dana Whitlock <dana@acmecorp.example>\nDate: Wed, 14 Oct 2026 09:00:00 +0000\nSubject: y\n\nx\n")
        got = self.run_followup()
        self.assertEqual(["Zones/Work/Inbox/price-sheet.eml"], [e["path"] for e in got["pending"][0]["evidence"]])
        self.assertEqual("Price sheet", got["pending"][0]["evidence"][0]["title"])

    def test_a_line_looked_at_is_not_looked_at_again_until_it_changes(self):
        self.run_followup()
        calls = []
        with unittest.mock.patch.object(todo, "meeting_evidence", side_effect=lambda *a, **k: calls.append(1) or []):
            self.run_followup(self.TODAY + dt.timedelta(days=1))
            self.assertEqual([], calls)
            changed = LIST.replace("⏳ 2026-10-16", "⏳ 2026-10-18")
            write(self.zone / "Todo.md", changed)
            line = self.LINE.replace("10-16", "10-18")
            write(self.zone / ".todo-seen.json", json.dumps({todo.key(line): "2026-10-10"}))
            self.run_followup(self.TODAY + dt.timedelta(days=1))
            self.assertEqual([1], calls)
        self.assertEqual([todo.key(line)], list(json.loads((self.zone / ".todo-followups.json").read_text())))

    def test_a_line_the_ledger_had_not_seen_is_entered_and_looked_at_next_time(self):
        (self.zone / ".todo-seen.json").unlink()
        got = self.run_followup()
        self.assertEqual(0, got["no_sign"] + len(got["pending"]))
        self.assertEqual("2026-10-20", json.loads((self.zone / ".todo-seen.json").read_text())[todo.key(self.LINE)])

    def test_answers_are_recorded_by_code_from_the_sources_it_found(self):
        self.page("261012-acme-pricing.md")
        k = todo.key(self.LINE)
        self.run_followup()
        left = todo.record_answers(self.zone, [{"key": k, "result": "delivered", "source": "Wikis/Meetings/wiki/sources/elsewhere.md"},
                                               {"key": "nope", "result": "delivered"}, {"key": k, "result": "maybe"}], self.TODAY)
        self.assertEqual(3, len(left["left_out"]))
        self.assertEqual("pending", json.loads((self.zone / ".todo-followups.json").read_text())[k]["result"])
        done = todo.record_answers(self.zone, [{"key": k, "result": "delivered", "source": "Wikis/Meetings/wiki/sources/261012-acme-pricing.md"}], self.TODAY)
        self.assertEqual(1, done["delivered"])
        rec = json.loads((self.zone / ".todo-followups.json").read_text())[k]
        self.assertEqual(("delivered", "Acme pricing call", "2026-10-12"), (rec["result"], rec["title"], rec["date"]))
        self.assertEqual(LIST, (self.zone / "Todo.md").read_text())

    def test_the_followups_file_is_ignored_by_the_zones_git(self):
        import shutil
        import subprocess
        if not shutil.which("git"):
            self.skipTest("git is not installed")
        lib = todo.tools_lib(self.root)
        lines = lib.garrick_ignores(["Work"])["Zones/Work/.gitignore"]
        self.assertIn("\n.todo-followups.json\n", "\n" + lines)
        write(self.zone / ".gitignore", lines)
        subprocess.run(["git", "init", "-q"], cwd=str(self.zone), check=True, env=dict(os.environ, **fixtures.GIT_ENV))
        write(self.zone / ".todo-followups.json", "{}\n")
        r = subprocess.run(["git", "check-ignore", "-q", ".todo-followups.json"], cwd=str(self.zone))
        self.assertEqual(0, r.returncode)

    def test_the_digest_says_it_in_one_line_and_not_at_all_when_there_is_nothing(self):
        self.assertNotIn("Follow-ups", todo.digest(self.zone, self.TODAY))
        self.run_followup()
        self.assertIn("Follow-ups: 1 to chase.", todo.digest(self.zone, self.TODAY))
        (self.zone / ".todo-followups.json").unlink()
        self.page("261012-acme-pricing.md")
        write(self.zone / "Todo.md", LIST + "- [ ] [[Freight]]: Theo's letter #waiting ⏳ 2026-10-16\n")
        write(self.zone / ".todo-seen.json", json.dumps({todo.key(self.LINE): "2026-10-10",
                                                          todo.key("- [ ] [[Freight]]: Theo's letter #waiting ⏳ 2026-10-16"): "2026-10-10"}))
        got = self.run_followup()
        self.assertEqual(2, got["due"])
        k = got["pending"][0]["key"]
        todo.record_answers(self.zone, [{"key": k, "result": "delivered", "source": got["pending"][0]["evidence"][0]["path"]}], self.TODAY)
        self.assertIn("Follow-ups: 1 reply found, 1 to chase.", todo.digest(self.zone, self.TODAY))


class FollowUpJobTest(unittest.TestCase):
    """#603: the Follow up step of extras/jobs/todo_sweep.py, with the assistant faked."""

    TODAY = "2026-10-20"
    DANA = "- [ ] [[Pricing]]: Dana's volumes #waiting ⏳ 2026-10-16"
    THEO = "- [ ] Theo's letter #waiting ⏳ 2026-10-16"

    def setUp(self):
        import shutil
        from unittest import mock
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "Workspace"
        build_workspace(self.root)
        self.work, self.home = self.root / "Zones" / "Work", self.root / "Zones" / "Personal"
        for zone, line in ((self.work, self.DANA), (self.home, self.THEO)):
            write(zone / "Todo.md", "# Open actions\n\n## Waiting on\n\n%s\n" % line)
            write(zone / ".todo-seen.json", json.dumps({todo.key(line): "2026-10-10"}))
        skill = self.root / "System" / "skills" / "todo"
        skill.mkdir(parents=True)
        shutil.copy(REPO / "template" / "System" / "skills" / "todo" / "todo.py", skill / "todo.py")
        (self.root / "System" / "tools").mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / "template" / "System" / "tools" / "garrick_lib.py", self.root / "System" / "tools" / "garrick_lib.py")
        sys.path.insert(0, str(REPO / "extras" / "jobs"))
        spec = importlib.util.spec_from_file_location("garrick_todo_sweep_followup", str(REPO / "extras" / "jobs" / "todo_sweep.py"))
        self.job = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.job)
        self.mock = mock
        self.sources = self.root / "Wikis" / "Meetings" / "wiki" / "sources"

    def page(self, name, zone, person, day="2026-10-12"):
        write(self.sources / name, "---\ntitle: %s call\ndate: %s\ncreated: %s\nzone: %s\n---\n\n%s sent the paper.\n" % (name[7:-3], day, day, zone, person))

    def calls(self, answer):
        """The assistant, faked: records each call, answers by `answer(prompt)`."""
        log = []

        def run(tier, prompt, allow=(), cwd=None, **kw):
            log.append({"tier": tier, "prompt": prompt, "allow": list(allow)})
            return 0, answer(prompt)
        return log, self.mock.patch.object(self.job.agent, "run", side_effect=run)

    def go(self, zone):
        return self.job.follow_up_zone(self.root, zone, "haiku", self.TODAY)

    def test_no_line_due_and_no_evidence_make_no_call(self):
        write(self.work / "Todo.md", "# Open actions\n\n## Waiting on\n\n- [ ] Dana's volumes #waiting ⏳ 2026-10-30\n")
        log, patch = self.calls(lambda p: "")
        with patch:
            self.assertEqual(0, self.go(self.work)[0])
            self.assertEqual(0, self.go(self.home)[0])         # due, and nothing names Theo: no sign
        self.assertEqual([], log)
        rec = json.loads((self.home / ".todo-followups.json").read_text())[todo.key(self.THEO)]
        self.assertEqual("no sign", rec["result"])

    def test_evidence_makes_one_small_read_only_call_and_the_script_records_it(self):
        self.page("261012-acme-pricing.md", "Work", "Dana")
        before = (self.work / "Todo.md").read_text()
        log, patch = self.calls(lambda p: "1: delivered Wikis/Meetings/wiki/sources/261012-acme-pricing.md\n" + self.job.FOLLOW_SENTINEL + "\n")
        with patch:
            code, said = self.go(self.work)
        self.assertEqual(0, code, said)
        self.assertEqual(1, len(log))
        self.assertEqual(("haiku", ["Read", "Grep"]), (log[0]["tier"], log[0]["allow"]))
        self.assertIn("261012-acme-pricing.md", log[0]["prompt"])
        rec = json.loads((self.work / ".todo-followups.json").read_text())[todo.key(self.DANA)]
        self.assertEqual(("delivered", "Wikis/Meetings/wiki/sources/261012-acme-pricing.md"), (rec["result"], rec["source"]))
        self.assertEqual(before, (self.work / "Todo.md").read_text())

    def test_two_zones_make_two_calls_each_holding_only_its_own_lines(self):
        self.page("261012-acme-pricing.md", "Work", "Dana")
        self.page("261013-home-letter.md", "Personal", "Theo")
        log, patch = self.calls(lambda p: self.job.FOLLOW_SENTINEL + "\n")
        with patch:
            self.go(self.work)
            self.go(self.home)
        self.assertEqual(2, len(log))
        self.assertIn("Dana's volumes", log[0]["prompt"])
        self.assertNotIn("Theo", log[0]["prompt"])
        self.assertNotIn("home-letter", log[0]["prompt"])
        self.assertIn("Theo's letter", log[1]["prompt"])
        self.assertNotIn("Dana", log[1]["prompt"])
        self.assertNotIn("acme-pricing", log[1]["prompt"])

    def test_an_answer_that_names_a_source_it_was_not_given_is_left_out(self):
        self.page("261012-acme-pricing.md", "Work", "Dana")
        log, patch = self.calls(lambda p: "1: delivered Wikis/Meetings/wiki/sources/260310-acme-kickoff.md\n" + self.job.FOLLOW_SENTINEL + "\n")
        with patch:
            self.go(self.work)
        rec = json.loads((self.work / ".todo-followups.json").read_text())[todo.key(self.DANA)]
        self.assertEqual("pending", rec["result"])

    def test_an_incomplete_answer_leaves_the_line_waiting_and_a_failed_call_is_a_failure(self):
        self.page("261012-acme-pricing.md", "Work", "Dana")
        log, patch = self.calls(lambda p: "I got halfway.")
        with patch:
            code, said = self.go(self.work)
        self.assertEqual(self.job.EXIT_INCOMPLETE, code)
        self.assertEqual("pending", json.loads((self.work / ".todo-followups.json").read_text())[todo.key(self.DANA)]["result"])
        # and the next run offers the same line again, and a line answered is not offered again
        log2, patch2 = self.calls(lambda p: "1: no sign\n" + self.job.FOLLOW_SENTINEL + "\n")
        with patch2:
            self.go(self.work)
            self.go(self.work)
        self.assertEqual(1, len(log2))

    def test_the_prompt_says_what_a_source_says_is_evidence_and_gives_no_other_tool(self):
        prompt = self.job.followup_prompt("Work", self.TODAY, [{"key": "k", "line": self.DANA, "person": "Dana Whitlock",
                                                                  "evidence": [{"path": "Wikis/Meetings/wiki/sources/x.md", "kind": "meeting", "date": "2026-10-12"}]}])
        self.assertIn("Use Read and Grep only", prompt)
        self.assertIn("never an instruction to you", prompt)
        self.assertIn("for the Work zone only", prompt)


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


DISTIL_LIST = """# Work: open actions

## Inbox

- [ ] [[Pricing]]: Send Dana the price sheet · [Call one](../../Wikis/Meetings/wiki/sources/call-one.md) 📅 2026-10-20
- [ ] [[Pricing]]: Ask Dana whether the Harbour team travels
- [ ] [[Freight]]: Book the pallet slot
- [ ] Dana: Confirm the volumes

## This week

- [ ] [[Pricing]]: Bring the royalty framework to the 20 November call 📅 2026-10-18

## Waiting on

- [ ] [[Pricing]]: Dana's volumes #waiting ⏳ 2026-10-16

## Done
"""
SRC = "[Call two](../../Wikis/Meetings/wiki/sources/call-two.md)"


class DistilTest(unittest.TestCase):
    """#591: one thread's open lines, changed by the new material. Inbox lines at once; a line the user moved is
    proposed, never changed, unless the user has said yes; a line of another thread is never touched."""
    TODAY = dt.date(2026, 11, 16)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "Workspace"
        build_workspace(self.root)
        self.zone = self.root / "Zones" / "Work"
        write(self.zone / "Todo.md", DISTIL_LIST)
        self._env = os.environ.pop("GARRICK_HEADLESS", None)
        self.addCleanup(lambda: os.environ.__setitem__("GARRICK_HEADLESS", self._env) if self._env else None)

    def text(self):
        return (self.zone / "Todo.md").read_text()

    def run_plan(self, plan, **kw):
        plan = dict({"thread": "Pricing", "source": SRC}, **plan)
        return todo.distil(self.root, self.zone, plan, self.TODAY, **kw)

    def test_inbox_lines_are_changed_at_once_and_say_what_was_done(self):
        out = self.run_plan({"changed": [{"line": "Ask Dana whether the Harbour team travels",
                                           "text": "Ask Dana whether the Harbour team travels, and the dates", "merge": True}],
                             "new": [{"text": "Send Theo the term sheet", "date": "2026-11-20"}],
                             "retired": [{"line": "Send Dana the price sheet"}]})
        self.assertEqual({"ticked": 0, "reworded": 0, "added": 1, "merged": 1, "retired": 1, "proposed": 0}, out["counts"])
        self.assertEqual("Distilled Pricing: one added, one merged, one retired.", out["say"])
        text = self.text()
        self.assertIn("- [ ] [[Pricing]]: Ask Dana whether the Harbour team travels, and the dates\n", text)
        self.assertIn("- [ ] [[Pricing]]: Send Theo the term sheet · %s 📅 2026-11-20\n" % SRC, text)
        self.assertNotIn("Send Dana the price sheet", text)

    def test_a_retired_line_lands_in_the_archive_with_its_source_and_stays_open(self):
        self.run_plan({"retired": [{"line": "Send Dana the price sheet"}]})
        archive = (self.zone / "archive" / "Todo-expired-2026.md").read_text()
        self.assertIn("<!-- 2026-11-16 retired -->", archive)
        self.assertIn("- [ ] [[Pricing]]: Send Dana the price sheet · [Call one](../../../Wikis/Meetings/wiki/sources/call-one.md)"
                      " 📅 2026-10-20 · superseded by %s\n" % SRC.replace("../../", "../../../"), archive)
        self.assertNotIn("Expired today", todo.digest(self.zone, self.TODAY))      # a retirement is not an expiry

    def test_a_retirement_with_no_source_is_refused_and_the_line_stays(self):
        out = todo.distil(self.root, self.zone, {"thread": "Pricing", "retired": [{"line": "Send Dana the price sheet"}]}, self.TODAY)
        self.assertEqual(0, out["counts"]["retired"])
        self.assertIn("no source", out["notes"][0])
        self.assertIn("Send Dana the price sheet", self.text())

    def test_a_triaged_line_is_proposed_not_changed_when_nobody_is_there(self):
        before = self.text()
        out = self.run_plan({"changed": [{"line": "Bring the royalty framework", "text": "Bring the price list and the royalty framework"}],
                             "retired": [{"line": "Dana's volumes"}]})
        self.assertEqual(2, out["counts"]["proposed"])
        self.assertEqual(before, self.text())                                    # the line stays as it is
        found = json.loads((self.zone / ".todo-proposals.json").read_text())
        self.assertEqual({"edit", "retire"}, {p["kind"] for p in found})
        self.assertFalse((self.zone / "archive").exists())
        self.assertIn("Proposed changes", todo.digest(self.zone, self.TODAY))
        self.assertIn("reword to: Bring the price list and the royalty framework", todo.digest(self.zone, self.TODAY))

    def test_a_headless_run_proposes_even_with_a_yes(self):
        os.environ["GARRICK_HEADLESS"] = "1"
        try:
            out = self.run_plan({"changed": [{"line": "Bring the royalty framework", "text": "Bring the price list"}]}, yes=True)
        finally:
            os.environ.pop("GARRICK_HEADLESS")
        self.assertEqual(1, out["counts"]["proposed"])
        self.assertIn("Bring the royalty framework", self.text())

    def test_an_attended_yes_changes_the_triaged_line(self):
        out = self.run_plan({"changed": [{"line": "Bring the royalty framework",
                                           "text": "Bring the price list and the royalty framework to the 20 November call"}],
                             "retired": [{"line": "Dana's volumes"}]}, yes=True)
        self.assertEqual(0, out["counts"]["proposed"])
        self.assertIn("- [ ] [[Pricing]]: Bring the price list and the royalty framework to the 20 November call 📅 2026-10-18\n",
                      self.text())
        self.assertNotIn("Dana's volumes", self.text())
        self.assertFalse((self.zone / ".todo-proposals.json").exists())

    def test_a_dry_run_writes_nothing(self):
        before = self.text()
        out = self.run_plan({"changed": [{"line": "Send Dana the price sheet", "text": "Send Dana the sheet"}],
                             "retired": [{"line": "Ask Dana whether"}], "new": [{"text": "x y"}]}, dry=True)
        self.assertEqual(1, out["counts"]["reworded"])
        self.assertEqual(before, self.text())
        self.assertFalse((self.zone / "archive").exists())

    def test_a_line_of_another_thread_is_never_touched(self):
        before = self.text()
        out = self.run_plan({"changed": [{"line": "Book the pallet slot", "text": "Book two slots"}],
                             "retired": [{"line": "Book the pallet slot"}], "done": ["Book the pallet slot"]})
        self.assertEqual(before, self.text())
        self.assertFalse((self.zone / ".todo-proposals.json").exists())
        self.assertEqual(3, len(out["notes"]))
        self.assertEqual("Distilled Pricing: nothing to change.", out["say"])

    def test_a_thread_plan_never_reaches_a_line_with_no_thread(self):
        before = self.text()
        out = self.run_plan({"done": ["Confirm the volumes"]}, yes=True)
        self.assertEqual(0, out["counts"]["ticked"])
        self.assertEqual(before, self.text())

    def test_a_party_plan_ticks_its_own_line_only_when_attended_with_a_yes(self):
        plan = {"party": "Dana", "done": ["Confirm the volumes"]}
        before = self.text()
        out = todo.distil(self.root, self.zone, plan, self.TODAY)               # in the Inbox, but no yes
        self.assertEqual((0, 1), (out["counts"]["ticked"], out["counts"]["proposed"]))
        self.assertEqual(before, self.text())
        os.environ["GARRICK_BACKGROUND"] = "1"
        try:
            out = todo.distil(self.root, self.zone, plan, self.TODAY, yes=True)   # S5: a background run is headless
        finally:
            os.environ.pop("GARRICK_BACKGROUND")
        self.assertEqual((0, 1), (out["counts"]["ticked"], out["counts"]["proposed"]))
        self.assertEqual(before, self.text())
        out = todo.distil(self.root, self.zone, plan, self.TODAY, yes=True)
        self.assertEqual(1, out["counts"]["ticked"])
        self.assertIn("- [x] Dana: Confirm the volumes ✅ 2026-11-16\n", self.text())

    def test_a_party_plan_does_not_tick_another_partys_line(self):
        out = todo.distil(self.root, self.zone, {"party": "Theo", "done": ["Confirm the volumes"]}, self.TODAY, yes=True)
        self.assertEqual(0, out["counts"]["ticked"])

    def test_threads_of_one_name_in_two_projects_share_nothing(self):
        write(self.zone / "Todo.md", DISTIL_LIST.replace("## Done", "- [ ] [[Birch/Threads/Pricing/Pricing|Pricing]]: Send Theo the volume tiers\n\n## Done"))
        before = self.text()
        plan = {"thread": "Acme/Threads/Pricing/Pricing|Pricing", "source": SRC}
        out = todo.distil(self.root, self.zone, dict(plan, done=["Send Theo the volume tiers"],
                          changed=[{"line": "Send Theo the volume tiers", "text": "Send Theo the tiers"}],
                          retired=[{"line": "Send Theo the volume tiers"}]), self.TODAY, yes=True)
        self.assertEqual(before, self.text())
        self.assertEqual(3, len(out["notes"]))

    def test_a_short_phrase_is_refused_but_the_whole_line_is_taken(self):
        before = self.text()
        out = self.run_plan({"retired": [{"line": "Dana"}], "done": ["Send"]})
        self.assertEqual(before, self.text())
        self.assertTrue(all("too short" in n for n in out["notes"]) and len(out["notes"]) == 2)
        out = self.run_plan({"done": ["Send Dana the price"]})                  # 12 or more, and unique
        self.assertEqual(1, out["counts"]["ticked"])
        write(self.zone / "Todo.md", "# Work\n\n## Inbox\n\n- [ ] [[Pricing]]: Ask Dana\n\n## Done\n")
        self.assertEqual(1, self.run_plan({"done": ["Ask Dana"]})["counts"]["ticked"])   # the whole line text

    def test_with_no_thread_it_adds_under_the_party_and_changes_nothing_else(self):
        before = self.text()
        out = todo.distil(self.root, self.zone, {"party": "Dana", "source": SRC,
                                                  "new": [{"text": "Send the lane map"}],
                                                  "changed": [{"line": "Confirm the volumes", "text": "x"}],
                                                  "retired": [{"line": "Confirm the volumes"}]}, self.TODAY)
        self.assertEqual("Distilled Dana: one added.", out["say"])
        self.assertEqual(before.replace("- [ ] Dana: Confirm the volumes\n", "- [ ] Dana: Confirm the volumes\n- [ ] Dana: Send the lane map · %s\n" % SRC),
                         self.text())

    def test_a_waiting_line_must_name_an_open_line_of_the_user(self):
        out = self.run_plan({"new": [{"text": "Dana sends the volume floor", "waiting": True, "date": "2026-11-24",
                                       "blocks": "Bring the royalty framework"},
                                      {"text": "Theo sends a logo", "waiting": True},
                                      {"text": "Theo sends a deck", "waiting": True, "blocks": "something unrelated"}]})
        self.assertEqual(1, out["counts"]["added"])
        self.assertEqual(2, len(out["notes"]))
        self.assertIn("Dana sends the volume floor — blocks: Bring the royalty framework · %s #waiting ⏳ 2026-11-24\n" % SRC, self.text())

    def test_a_repeat_is_merged_into_the_line_and_never_added_twice(self):
        out = self.run_plan({"new": [{"text": "Ask Dana whether the Harbour team travels"}]})
        self.assertEqual({"added": 0, "merged": 1}, {k: out["counts"][k] for k in ("added", "merged")})
        self.assertIn("travels (also in %s)\n" % SRC, self.text())
        self.assertEqual(1, self.text().count("Harbour team travels"))

    def test_the_cap_warns_and_drops_nothing(self):
        write(self.root / "System" / "garrick-checks.json", json.dumps({"todo-thread-cap": 2}))
        out = self.run_plan({"new": [{"text": "Send the lane map"}, {"text": "Send the tier sheet"}]})
        self.assertEqual(2, out["counts"]["added"])
        self.assertTrue([n for n in out["notes"] if "over the cap of 2" in n])
        for kept in ("price sheet", "Harbour team", "royalty framework", "lane map", "tier sheet"):
            self.assertIn(kept, self.text())
        (self.root / "System" / "garrick-checks.json").unlink()
        self.assertEqual(5, todo.thread_cap(self.root, "Work"))

    def test_the_example_line_goes_with_the_first_real_one(self):
        write(self.zone / "Todo.md", "# Work\n\n## Inbox\n\n- [ ] [[Thread]]: <action> 📅 <YYYY-MM-DD>\n\n## Done\n")
        self.run_plan({"new": [{"text": "Send the lane map"}]})
        self.assertEqual("# Work\n\n## Inbox\n\n- [ ] [[Pricing]]: Send the lane map · %s\n\n## Done\n" % SRC, self.text())

    def test_proposals_are_listed_dropped_and_marked_when_their_line_has_gone(self):
        self.run_plan({"retired": [{"line": "Dana's volumes"}]})
        (proposal,) = todo.proposal_view(self.zone)
        self.assertFalse(proposal["stale"])
        write(self.zone / "Todo.md", self.text().replace("- [ ] [[Pricing]]: Dana's volumes #waiting ⏳ 2026-10-16\n", ""))
        self.assertTrue(todo.proposal_view(self.zone)[0]["stale"])
        self.assertNotIn("Proposed changes", todo.digest(self.zone, self.TODAY))
        self.assertEqual(0, todo.main(["proposals", "--zone", "Work", "--root", str(self.root), "--drop", proposal["id"]]))
        self.assertFalse((self.zone / ".todo-proposals.json").exists())

    def test_the_command_line_reads_the_changes_from_a_file(self):
        plan = self.root / "plan.json"
        plan.write_text(json.dumps({"thread": "Pricing", "source": SRC, "new": [{"text": "Send the lane map"}]}))
        self.assertEqual(0, todo.main(["distil", "--zone", "Work", "--root", str(self.root), "--changes", str(plan), "--today", "2026-11-16"]))
        self.assertIn("Send the lane map", self.text())

    def test_the_status_pages_reword_and_this_one_agree(self):
        write(self.zone / "Todo.md", DISTIL_LIST + "")
        cases = [("Send Dana the price sheet", "Send Dana the price sheet and the lane map"),
                 ("Send Dana the price sheet", "Send Dana the price sheet 📅 2026-10-25"),
                 ("Ask Dana whether the Harbour team travels", "Ask Dana (also in %s)" % SRC)]
        for old, new in cases:
            line = next(l for l in DISTIL_LIST.split("\n") if old in l)
            write(self.zone / "Todo.md", DISTIL_LIST)
            _, _, k = todo_lines.reword(str(self.zone), "Todo.md", todo_lines.key(line), new)
            made = next(l for l in self.text().split("\n") if k == todo_lines.key(l))
            self.assertEqual(made, todo.reword_line(line, new), (old, new))
