"""The todo skill's script: expire, archive and tidy a zone's Todo.md.

    python3 -m unittest discover -s tests
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

from fixtures import build_workspace, write  # noqa: E402

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

    def test_archive_keeps_today_and_moves_the_rest_by_year(self):
        self.assertEqual(1, todo.archive(self.zone, dt.date(2026, 10, 12)))
        self.assertIn("today's ✅ 2026-10-12", self.text())
        self.assertNotIn("old one", self.text())
        archived = (self.zone / "archive" / "Todo-2026.md").read_text()
        self.assertIn("- [x] [[Pricing]]: old one ✅ 2026-10-01\n    - [ ] a step left open under it", archived)
        self.assertNotIn("a step left open", self.text())                  # it went with its task

    def test_tidy_puts_fields_last_and_the_inbox_in_thread_order(self):
        self.assertGreater(todo.tidy(self.zone), 0)
        inbox = self.text().split("## Inbox\n\n", 1)[1].split("\n\n", 1)[0].splitlines()
        self.assertEqual(["- [ ] [[Pricing]]: send the sheet",
                          "- [ ] [[Pricing]]: check the tier against Birch's 🔺 📅 2026-10-21",
                          "- [ ] [[Freight]]: book the call 📅 2026-10-20",
                          "- [ ] Dana: confirm volumes"], inbox)
        self.assertEqual(0, todo.tidy(self.zone))                          # a second run changes nothing

    def test_all_from_the_command_line(self):
        import io
        from contextlib import redirect_stdout
        out = io.StringIO()
        with redirect_stdout(out):
            todo.main(["all", "--zone", "work", "--root", str(self.root), "--today", "2026-10-12", "--json"])
        self.assertEqual({"zone": "Work", "expired": 0, "archived": 1, "tidied": 3}, json.loads(out.getvalue()))
        self.assertIn("The header the list keeps.", self.text())


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

    def text(self):
        return (self.zone / "Todo.md").read_text()


if __name__ == "__main__":
    unittest.main()
