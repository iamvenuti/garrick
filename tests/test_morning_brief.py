"""One morning brief across the zones (#686): next_up.py's brief(), and the todo sweep that sends it.

    cd tests && python3 -m unittest test_morning_brief

The assistant is faked and every notice is recorded in place of being sent: nothing reaches this Mac. Invented
names only: Acme, Birch, Dana, Owen, a garden.
"""

from __future__ import annotations

import ast
import datetime as dt
import importlib.util
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

import fixtures  # noqa: E402
from fixtures import HAVE_GIT, git, write  # noqa: E402
from test_next_up import TODAY, workspace  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "template" / "System" / "tools"
JOBS = REPO / "extras" / "jobs"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


nu = _load("garrick_next_up_brief", TOOLS / "next_up.py")

NOTE_TEXT = "The work is going well."                # every thread note's own words, in the fixture
TODO_WORDS = ("we need it by Friday", "as Dana said on the call")   # a Todo line's quotation and aside
MEETING = "Acme kick-off"                            # a meeting page's name, which a Todo line links


class BriefTest(unittest.TestCase):
    """brief(): the band's ranking, said as one message."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = workspace(Path(self.tmp.name).resolve())
        write(self.root / "Wikis" / "Meetings" / "wiki" / "meetings" / "2026-10-01 Acme kick-off.md",
              "# Kick-off\n\nDana said the volumes are confidential.\n")

    def picks(self):
        return nu.next_up(self.root, today=TODAY)["picks"]

    def brief(self, zones=("Work", "Personal"), **kw):
        return nu.brief(self.root, list(zones), today=TODAY, **kw)

    def test_its_first_line_is_the_bands_first_pick(self):
        first = self.picks()[0]
        self.assertEqual("back", first["source"])
        self.assertEqual("- %s, in Work" % first["say"], self.brief(lines=50).splitlines()[0])
        out = io.StringIO()
        with redirect_stdout(out):
            nu.main(["--root", str(self.root), "--today", TODAY.isoformat(), "--say"])
        self.assertIn(out.getvalue().strip(), self.brief().splitlines()[0])            # what the band says first

    def test_the_lines_are_the_ranking_in_its_order(self):
        lines = self.brief(lines=50).splitlines()
        self.assertEqual(["- " + nu.brief_line(p) for p in self.picks()], lines)

    def test_eight_lines_at_most_then_each_zones_count_of_the_rest(self):
        picks = self.picks()
        self.assertGreater(len(picks), 8)
        lines = self.brief().splitlines()
        self.assertEqual(9, len(lines))
        self.assertEqual(["- " + nu.brief_line(p) for p in picks[:8]], lines[:8])
        counts = {}
        for p in picks[8:]:
            counts[p["zone"] or "the Meetings inbox"] = counts.get(p["zone"] or "the Meetings inbox", 0) + 1
        said = ", ".join(("%d more in %s" if i == 0 else "%d in %s") % (n, z) for i, (z, n) in enumerate(counts.items()))
        self.assertEqual("And %s." % said, lines[8])
        self.assertEqual(8, nu.BRIEF_LINES)
        short = self.brief(lines=2).splitlines()
        self.assertEqual(3, len(short))
        self.assertRegex(short[2], r"^And \d+ more in [A-Za-z ]+(, \d+ in [A-Za-z ]+)*\.$")
        self.assertEqual(len(picks) - 2, sum(int(n) for n in re.findall(r"(\d+) (?:more )?in", short[2])))

    def test_a_quiet_day_says_so(self):
        empty = Path(self.tmp.name) / "Quiet"
        write(empty / "System" / "rules.md", "# Rules\n")
        for zone in ("Work", "Personal"):
            write(empty / "Zones" / zone / "Todo.md", "# %s: open actions\n\n## Inbox\n\n## Done\n" % zone)
        self.assertEqual("Nothing needs you today.", nu.brief(empty, ["Work", "Personal"], today=TODAY))

    def test_a_zone_whose_sweep_failed_says_its_list_is_as_it_stood(self):
        text = self.brief(failed={"Personal": "sweep"})
        self.assertEqual("Personal: the sweep did not finish this morning; its list is as it stood.", text.splitlines()[0])
        self.assertIn("Work: the sweep finished this morning. The follow-up did not.",
                      self.brief(failed={"Work": "follow-up"}).splitlines()[0])
        empty = Path(self.tmp.name) / "Quiet"
        write(empty / "System" / "rules.md", "# Rules\n")
        write(empty / "Zones" / "Work" / "Todo.md", "# Work: open actions\n\n## Inbox\n\n## Done\n")
        self.assertEqual(["Work: the sweep did not finish this morning; its list is as it stood.", "Nothing needs you today."],
                         nu.brief(empty, ["Work"], today=TODAY, failed={"Work": "sweep"}).splitlines())

    def test_a_zone_left_out_is_not_in_it(self):
        text = self.brief(zones=("Work",), lines=50)
        self.assertNotIn("Personal", text)
        self.assertNotIn("nursery", text.lower())
        self.assertIn("Garden", self.brief(zones=("Personal",), lines=50))
        self.assertNotIn("Acme", self.brief(zones=("Personal",), lines=50))

    def test_it_never_quotes_a_note_a_meeting_or_more_of_a_todo_line_than_the_band_says(self):
        text = self.brief(lines=50)
        for words in TODO_WORDS + (NOTE_TEXT, MEETING, "confidential", "dana@acme.example", "·", "[src]", "📅", "⏳"):
            self.assertNotIn(words, text, words)
        says = {p["say"] for p in self.picks()}
        for line in text.splitlines():
            body = re.sub(r", in (Work|Personal)$", "", line[2:])
            self.assertIn(body, says, line)                                  # each line is a `say`, and nothing more


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class SweepBriefTest(unittest.TestCase):
    """extras/jobs/todo_sweep.py --digest, with the assistant faked and every notice recorded."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = workspace(Path(self._tmp.name).resolve() / "Workspace")
        shutil.copy(TOOLS / "notifications.py", self.root / "System" / "tools" / "notifications.py")
        env = mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                                           "GIT_AUTHOR_NAME": "Jo", "GIT_AUTHOR_EMAIL": "jo@example.invalid",
                                           "GIT_COMMITTER_NAME": "Jo", "GIT_COMMITTER_EMAIL": "jo@example.invalid",
                                           "GARRICK_JOBS_DIR": str(Path(self._tmp.name) / "jobs"),
                                           "HOME": str(Path(self._tmp.name) / "home")})
        env.start()
        self.addCleanup(env.stop)
        for name in ("GARRICK_NOTIFY", "GARRICK_NOTIFY_CMD"):
            if name in os.environ:
                p = mock.patch.dict(os.environ)
                p.start()
                self.addCleanup(p.stop)
                os.environ.pop(name, None)
        for zone in ("Work", "Personal"):
            z = self.root / "Zones" / zone
            git(z, "init", "-q")
            fixtures.stand_in_hook(z)
            git(z, "add", "-A")
            git(z, "commit", "-q", "-m", "start")
        sys.path.insert(0, str(JOBS))
        self.addCleanup(lambda: sys.path.remove(str(JOBS)) if str(JOBS) in sys.path else None)
        self.job = _load("garrick_todo_sweep_brief", JOBS / "todo_sweep.py")
        import job as job_module
        self.notices = []
        p = mock.patch.object(job_module, "notify", side_effect=lambda kind, title, message, **kw:
                              self.notices.append({"kind": kind, "title": title, "message": message,
                                                   "event": kw.get("event"), "zone": kw.get("zone")}) or True)
        p.start()
        self.addCleanup(p.stop)
        self.calls = []

    def settings(self, notifications):
        write(self.root / "System" / "garrick-settings.json", json.dumps({"notifications": notifications}))

    def fake(self, fail=()):
        def run(tier, prompt, allow=(), cwd=None, **kw):
            self.calls.append(prompt)
            if "follow-up" in prompt:
                return 0, self.job.FOLLOW_SENTINEL + "\n"
            if any("for the %s zone only" % z in prompt for z in fail):
                return 0, "I got halfway."
            return 0, "ADDED 0 FOLDED 0\n" + self.job.SENTINEL + "\n"
        return mock.patch.object(self.job.agent, "run", side_effect=run)

    def sweep(self, *extra, fail=()):
        with self.fake(fail):
            return self.job.main(["--workspace", str(self.root), "--zone", "Work", "--zone", "Personal", "--digest", *extra])

    def events(self):
        return [(n["event"], n["zone"].name if n["zone"] else None) for n in self.notices]

    def test_one_brief_after_every_zone_has_swept_and_no_summary_for_each(self):
        self.settings({"morning": "all"})
        self.assertEqual(0, self.sweep())
        self.assertEqual([("todo-refreshed", "Work"), ("todo-refreshed", "Personal"), ("morning-brief", None)], self.events())
        brief = self.notices[-1]
        self.assertEqual(("brief", "Morning summary"), (brief["kind"], brief["title"]))
        band = nu.next_up(self.root)["picks"]                             # the band, read at the same moment
        self.assertEqual("- " + nu.brief_line(band[0]), brief["message"].splitlines()[0])
        self.assertLessEqual(len([l for l in brief["message"].splitlines() if l.startswith("- ")]), 8)

    def test_one_summary_for_each_zone_without_the_key_as_before(self):
        self.settings({"tell": {"todo-summary": True}, "after": 2, "quiet": {"on": True}})          # a 0.79.0 file
        self.assertEqual(0, self.sweep())
        self.assertEqual([("todo-refreshed", "Work"), ("todo-summary", "Work"), ("todo-refreshed", "Personal"),
                          ("todo-summary", "Personal")], self.events())
        self.settings({"morning": "each"})
        self.notices.clear()
        self.sweep()
        self.assertNotIn("morning-brief", [e for e, _ in self.events()])

    def test_a_zone_with_a_route_of_its_own_keeps_its_summary_and_is_never_in_the_brief(self):
        self.settings({"morning": "all", "zones": {"Personal": {"to": ["telegram"], "chat": "777"}}})
        self.assertEqual(0, self.sweep())
        self.assertEqual([("todo-refreshed", "Work"), ("todo-refreshed", "Personal"), ("todo-summary", "Personal"),
                          ("morning-brief", None)], self.events())
        brief = self.notices[-1]["message"]
        self.assertNotIn("Personal", brief)
        self.assertNotIn("Garden", brief)

    def test_the_override_keeps_a_summary_for_each_zone(self):
        self.settings({"morning": "all"})
        with mock.patch.dict(os.environ, {"GARRICK_NOTIFY_CMD": "/bin/true"}):
            self.assertEqual(0, self.sweep())
        self.assertEqual(["todo-summary", "todo-summary"], [e for e, _ in self.events() if e != "todo-refreshed"])

    def test_a_zone_whose_sweep_failed_says_so_in_the_brief(self):
        self.settings({"morning": "all"})
        self.assertEqual(self.job.EXIT_INCOMPLETE, self.sweep(fail=("Personal",)))
        self.assertEqual("morning-brief", self.events()[-1][0])
        self.assertNotIn("todo-summary", [e for e, _ in self.events()])
        self.assertEqual("Personal: the sweep did not finish this morning; its list is as it stood.",
                         self.notices[-1]["message"].splitlines()[0])

    def test_the_lines_are_a_setting(self):
        self.settings({"morning": "all"})
        self.sweep("--brief-lines", "2")
        lines = self.notices[-1]["message"].splitlines()
        self.assertEqual(3, len(lines))
        self.assertTrue(lines[2].startswith("And "))
        with self.fake():
            self.assertEqual(64, self.job.main(["--workspace", str(self.root), "--zone", "Work", "--brief-lines", "0"]))

    def test_print_brief_sweeps_nothing_and_sends_nothing(self):
        self.settings({"morning": "all", "zones": {"Personal": {"to": ["telegram"]}}})
        out = io.StringIO()
        with self.fake(), redirect_stdout(out):
            code = self.job.main(["--workspace", str(self.root), "--zone", "Work", "--zone", "Personal", "--print-brief"])
        self.assertEqual(0, code)
        self.assertEqual([], self.calls)
        self.assertEqual([], self.notices)
        text = out.getvalue()
        self.assertIn("Personal keeps its own summary.", text)
        self.assertEqual(nu.brief(self.root, ["Work"]), text.rsplit("\nPersonal keeps", 1)[0])
        self.settings({"morning": "each"})
        out = io.StringIO()
        with self.fake(), redirect_stdout(out):
            self.job.main(["--workspace", str(self.root), "--zone", "Work", "--print-brief"])
        self.assertEqual("No morning brief: each zone gets its own summary.", out.getvalue().strip())


class NothingButSetupWritesAllTest(unittest.TestCase):
    """The orchestrator's acceptance case runs the update itself; this holds the code to it: only install() writes
    "all", and the update never calls it, so a 0.79.0 notifications file keeps one summary per zone."""

    def test_the_update_never_writes_the_morning_key(self):
        update = (REPO / "update.py").read_text(encoding="utf-8")
        self.assertNotIn("first_settings", update)
        self.assertNotIn('"morning"', update)
        called = {n.func.attr for n in ast.walk(ast.parse(update)) if isinstance(n, ast.Call)
                  and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name) and n.func.value.id == "install"}
        self.assertNotIn("install", called)
        self.assertNotIn("main", called)

    def test_only_install_calls_first_settings(self):
        tree = ast.parse((REPO / "install.py").read_text(encoding="utf-8"))
        callers = {f.name for f in ast.walk(tree) if isinstance(f, ast.FunctionDef)
                   for c in ast.walk(f) if isinstance(c, ast.Call) and getattr(c.func, "id", None) == "first_settings"}
        self.assertEqual({"install"}, callers)

    def test_a_0790_notifications_file_reads_one_summary_for_each_zone(self):
        n = _load("garrick_notifications_brief", TOOLS / "notifications.py")
        old = {"tell": {"needs-you": True, "finished": True, "todo-summary": True, "context-summary": True,
                        "job-failed": True, "release": True}, "after": 2, "quiet": {"on": True, "from": "22:00", "to": "07:00"}}
        self.assertEqual("each", n.normal(old)["morning"])


if __name__ == "__main__":
    unittest.main()
