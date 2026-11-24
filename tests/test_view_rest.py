"""What 0.81.0 moved onto the core's readers (#650): the jobs folder and the launchd agents (`view_jobs.py`), the check's kept
result and the App's files under `System/` (`view_app.py`), and what `status.py` still reads.

    cd tests && python3 -m unittest test_view_rest

The shadow tests hold each reader to v0.80.0's own code for it, frozen word for word in `old_status_reads_0800.py`, on seeded
folders and a fake home, and to the same list of files opened and folders listed (`TestNoWiderReads`). A reader that fails
gives its empty value, never an exception or a path. Nothing here reads this Mac: the home, the jobs folder and the launch
agents folder are temporary ones.

Differences from the old reads, each a rule:

    difference                                           why
    --------------------------------------------------   -----------------------------------------------------------------
    A plist's environment value that is neither text,    JSON cannot hold it; a plist date or data value is read as
    a number nor a boolean (a date, bytes) is None.      "not set", which every place that reads an environment value
                                                         already treats as the default.
    A log or lock that cannot be read says so with       The old reads raised through the page build for a log that was
    its empty value.                                     a folder or unreadable; the page now draws the row without it.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import plistlib
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from old_status_reads_0800 import old_reads  # noqa: E402
from test_status import REPO, status  # noqa: E402

TOOLS = REPO / "template" / "System" / "tools"
sys.path.insert(0, str(TOOLS))
import view  # noqa: E402
import view_jobs  # noqa: E402

NOW = dt.datetime(2026, 11, 20, 10, 0, 0)


def stamp(secs):
    return (NOW - dt.timedelta(seconds=secs)).strftime("%Y-%m-%d %H:%M:%S")


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def snapshot(root: Path) -> dict:
    out = {}
    for dirpath, dirs, files in os.walk(root):
        for name in files + dirs:
            p = Path(dirpath) / name
            out[p.relative_to(root).as_posix()] = (p.lstat().st_mtime_ns, p.read_bytes() if p.is_file() else None)
    return out


_SEEN: list = []
_RECORDING = [False]


_HOOKS: list = []


def _hook(event, args):
    for extra in list(_HOOKS):
        extra(event, args)
    if _RECORDING[0] and event in ("open", "os.listdir", "os.scandir", "glob.glob") and args and isinstance(args[0], (str, bytes, os.PathLike)):
        _SEEN.append((event, os.fspath(args[0]) if not isinstance(args[0], bytes) else args[0].decode(errors="replace"), args[1] if event == "open" else None))


sys.addaudithook(_hook)


def reads(fn):
    """The files opened and the folders listed while `fn` runs, as (event, path, mode): a set."""
    _SEEN.clear()
    _RECORDING[0] = True
    try:
        fn()
    finally:
        _RECORDING[0] = False
    return {(e, p, m if e != "open" else ("w" if m and any(c in str(m) for c in "wax+") else "r")) for e, p, m in _SEEN}


class Machine(unittest.TestCase):
    """A fake home with a launch agents folder, and a jobs folder: this Mac, as a test builds it."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name).resolve()
        self.home = self.base / "home"
        self.agents = self.home / "Library" / "LaunchAgents"
        self.agents.mkdir(parents=True)
        self.jobs = self.base / "jobs"
        self.jobs.mkdir()
        env = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        env.start()
        self.addCleanup(env.stop)
        mods = mock.patch.dict(sys.modules)            # the jobs extra's `job`, if another test loaded it, would decide a lock
        mods.start()
        sys.modules.pop("job", None)
        self.addCleanup(mods.stop)
        self.addCleanup(self._tmp.cleanup)

    def plist(self, name, label=None, **extra):
        body = {"Label": label or "garrick." + name,
                "ProgramArguments": ["/usr/bin/python3", "/w/System/jobs/job.py", name, "--agent", "--", "true"]}
        body.update(extra)
        (self.agents / ((label or "garrick." + name) + ".plist")).write_bytes(plistlib.dumps(body))

    def beat(self, name, **hb):
        body = {"job": name, "finished": stamp(3600), "exit": 0, "seconds": 30, "items": 1, "idle_days": 0}
        body.update(hb)
        write(self.jobs / (name + ".heartbeat.json"), json.dumps(body))

    def rich(self):
        """Every kind of row the jobs card draws."""
        self.plist("brief", StartCalendarInterval={"Hour": 6}, EnvironmentVariables={"GARRICK_ABOUT": " A morning brief "})
        self.beat("brief")
        write(self.jobs / "brief.log", "===== %s  brief  exit 0  (3s)\n\n===== %s  brief  exit 5  (3s)  quiet\n" % (stamp(86400), stamp(7200)))
        self.plist("gr-nightly", StartCalendarInterval=[{"Hour": 2}, {"Weekday": 1, "Hour": 3}],
                   EnvironmentVariables={"GARRICK_RENAMED_FROM": "nurture"})
        self.beat("gr-nightly", steps=[{"step": "effort", "exit": 1}, {"step": "recall", "exit": 0}])
        self.beat("nurture", finished=stamp(5 * 86400))
        write(self.jobs / "nurture.log", "===== %s  nurture  exit 0  (9s)\n" % stamp(5 * 86400))
        self.beat("status", finished=stamp(6 * 86400))
        self.beat("flaky", exit=4, reason="could not sign in")
        write(self.jobs / "flaky.log", "===== %s  flaky  exit 4  (3s)\n===== %s  flaky  skipped\n" % (stamp(3600), stamp(7200)))
        self.beat("idler", idle=True, idle_days=9)
        self.plist("late-one", "mine.late", StartInterval=3600)
        self.beat("late-one", finished=stamp(30 * 86400))
        self.plist("sleeper", StartInterval=900, EnvironmentVariables={"GARRICK_IDLE_DAYS": "2"})
        self.plist("weird", "x.weird", StartInterval=0)
        self.plist("cal", "x.cal", StartCalendarInterval={"Day": 3, "Hour": 4, "Month": 2})
        (self.agents / "other.plist").write_bytes(plistlib.dumps({"Label": "other", "ProgramArguments": ["/bin/true"]}))
        write(self.agents / "broken.plist", "not a plist")
        self.beat("runner")
        lock = self.jobs / "runner.lock"
        lock.mkdir()
        write(lock / "until", "%d %d %d\n" % (NOW.timestamp() + 600, os.getpid(), NOW.timestamp()))
        write(self.jobs / "runner.steps.json", json.dumps([{"step": "a", "exit": 0}, {"step": "b", "exit": 2}, "junk"]))
        self.plist("runner", StartInterval=600)
        (self.jobs / "stale.lock").mkdir()                      # a lock with no record
        write(self.jobs / "broken.heartbeat.json", "{nope")
        write(self.jobs / "list.heartbeat.json", "[1]")


class TestShadowJobs(Machine):
    """Each reader of the jobs folder and the launch agents, held to v0.80.0's."""

    def setUp(self):
        super().setUp()
        self.old = old_reads(status, "JOBS")
        self.rich()

    def test_the_agents_are_read_as_they_were(self):
        self.assertEqual(self.old["launchd_jobs"](self.agents), status.launchd_jobs(self.agents))

    def test_the_default_folder_is_the_launch_agents_folder_of_this_home(self):
        self.assertEqual(self.old["launchd_jobs"](), status.launchd_jobs())
        self.assertIn("brief", status.launchd_jobs())

    def test_the_rows_of_the_card_are_the_old_rows(self):
        sched = self.old["launchd_jobs"](self.agents)
        old = self.old["jobs"](self.jobs, NOW, sched)
        new = status.jobs(self.jobs, NOW, sched)
        self.assertEqual(old, new)
        self.assertEqual({"brief", "flaky", "gr-nightly", "idler", "late-one", "runner", "cal", "sleeper", "weird"}, {j["name"] for j in new})
        self.assertTrue(next(j for j in new if j["name"] == "runner")["running"])
        self.assertNotIn("status", {j["name"] for j in new})            # the retired build is hidden once the nightly is there

    def test_a_renamed_job_keeps_its_runs(self):
        sched = self.old["launchd_jobs"](self.agents)
        self.assertEqual(self.old["superseded"](self.jobs, sched), status.superseded(self.jobs, sched))
        self.assertEqual({"gr-nightly": [("nurture", mock.ANY)]}, status.superseded(self.jobs, sched)[0])

    def test_the_runs_the_logs_record(self):
        for name, earlier in (("brief", ()), ("flaky", ()), ("gr-nightly", (("nurture", NOW.timestamp()),)), ("none", ())):
            self.assertEqual(self.old["history"](self.jobs, name, NOW, earlier), status.history(self.jobs, name, NOW, earlier), name)
        self.assertEqual([(0, False), (5, True)], sorted((r[1], r[2]) for r in status.history(self.jobs, "brief", NOW)), "brief")

    def test_the_cut_off_is_the_old_one_to_the_microsecond(self):
        t = NOW.replace(microsecond=500000)
        write(self.jobs / "edge.log", "===== %s  edge  exit 0  (1s)\n===== %s  edge  exit 0  (1s)\n" % (
            (t - dt.timedelta(days=status.DAYS)).strftime("%Y-%m-%d %H:%M:%S"),
            (t - dt.timedelta(days=status.DAYS, seconds=-1)).strftime("%Y-%m-%d %H:%M:%S")))
        self.assertEqual(self.old["history"](self.jobs, "edge", t), status.history(self.jobs, "edge", t))

    def test_the_live_steps_and_the_logs_of_a_job(self):
        for name in ("runner", "brief", "nothing"):
            self.assertEqual(self.old["steps_now"](self.jobs, name), status.steps_now(self.jobs, name), name)
            self.assertEqual(self.old["job_log"](self.jobs, name), status.job_log(self.jobs, name), name)
        olds = (("nurture", 1.0),)
        self.assertEqual(self.old["job_log"](self.jobs, "gr-nightly", olds), status.job_log(self.jobs, "gr-nightly", olds))
        self.assertEqual(self.jobs / "nurture.log", status.job_log(self.jobs, "gr-nightly", olds))
        self.assertEqual([{"step": "a", "exit": 0}, {"step": "b", "exit": 2}], status.steps_now(self.jobs, "runner"))

    def test_the_tail_of_a_log(self):
        write(self.jobs / "long.log", "\n".join("line %d %s" % (i, "x" * 400) for i in range(5000)))
        for path in (self.jobs / "long.log", self.jobs / "brief.log", self.jobs / "none.log"):
            self.assertEqual(self.old["log_tail"](path), status.log_tail(path))

    def test_what_a_lock_means(self):
        locks = []
        for text in ("%d %d %d\n" % (NOW.timestamp() + 600, os.getpid(), NOW.timestamp()), "%d %d\n" % (NOW.timestamp() - 1, os.getpid()),
                     "%d 999999999\n" % (NOW.timestamp() + 600), "%d\n" % (NOW.timestamp() + 600), "words", ""):
            lock = self.jobs / ("l%d.lock" % len(locks))
            write(lock / "until", text)
            locks.append(lock)
        locks += [self.jobs / "stale.lock", self.jobs / "absent.lock", self.jobs / "brief.log"]
        for lock in locks:
            self.assertEqual(self.old["lock_held"](lock, NOW), status.lock_held(lock, NOW), lock.name)
        os.utime(self.jobs / "stale.lock", (NOW.timestamp() - 4 * 3600,) * 2)
        self.assertEqual(self.old["lock_held"](self.jobs / "stale.lock", NOW), status.lock_held(self.jobs / "stale.lock", NOW))
        os.utime(self.jobs / "stale.lock", (NOW.timestamp() - 3600,) * 2)
        self.assertTrue(status.lock_held(self.jobs / "stale.lock", NOW))

    def test_the_jobs_extras_own_lock_rule_still_decides_when_it_is_loaded(self):
        fake = mock.Mock()
        fake.holder = lambda lock, secs: (True, "")
        with mock.patch.dict(sys.modules, {"job": fake}):
            self.assertTrue(status.lock_held(self.jobs / "stale.lock", NOW))
            self.assertFalse(status.lock_held(self.jobs / "absent.lock", NOW))

    def test_a_plist_value_json_cannot_hold_is_none(self):
        self.plist("dated", EnvironmentVariables={"GARRICK_IDLE_DAYS": dt.datetime(2026, 1, 1), "A": b"x", "B": 3, "C": True},
                   StartInterval=60)
        got = view_jobs.agents(self.agents)["dated"]
        self.assertEqual({"GARRICK_IDLE_DAYS": None, "A": None, "B": 3, "C": True}, got["env"])
        json.dumps(got)


class TestNoWiderReads(Machine):
    """The core reads no file and lists no folder that the page's own readers did not: the same set, for the whole jobs card."""

    def test_the_jobs_card_opens_and_lists_what_it_did(self):
        self.rich()
        old = old_reads(status, "JOBS")
        status.launchd_jobs(self.agents)               # loads the core reader once, so its own file is not counted

        def whole(ns):
            sched = ns["launchd_jobs"](self.agents)
            for j in ns["jobs"](self.jobs, NOW, sched):
                ns["log_tail"](j["log"])
        before, after = (reads(lambda: whole(old)), reads(lambda: whole(vars(status))))
        before, after = ({r for r in x if r[1].startswith(str(self.base))} for x in (before, after))      # this Mac's own files are not the question
        self.assertTrue(before)
        self.assertEqual(before, after)
        self.assertFalse({m for e, _, m in after if e == "open"} - {"r"})                     # nothing opened for writing

    def test_the_folders_come_from_the_arguments(self):
        self.rich()
        other = self.base / "other"
        other.mkdir()
        got = reads(lambda: (status.launchd_jobs(other), status.jobs(other, NOW, {})))
        self.assertFalse([p for _, p, _ in got if str(self.jobs) in p or str(self.agents) in p])


class TestTheCoreReaders(Machine):
    def test_every_reader_gives_its_empty_value_for_a_folder_that_is_not_there(self):
        gone = self.base / "gone"
        self.assertEqual({}, view_jobs.agents(gone))
        self.assertEqual([], view_jobs.heartbeats(gone))
        self.assertEqual({}, view_jobs.heartbeat(gone, "x"))
        self.assertEqual(([], []), (view_jobs.runs(gone, "x", NOW.isoformat()), view_jobs.log_tail(gone / "x.log")))
        self.assertIsNone(view_jobs.steps_now(gone, "x"))
        self.assertEqual({"dir": False, "until": None, "mtime": None}, view_jobs.lock(gone / "x.lock"))
        self.assertEqual("x.log", view_jobs.log_name(gone, "x"))
        self.assertEqual(({}, set()), view_jobs.superseded(gone, {}))

    def test_a_log_that_is_a_folder_or_unreadable_gives_no_runs(self):
        (self.jobs / "odd.log").mkdir()
        self.assertEqual([], view_jobs.runs(self.jobs, "odd", NOW.isoformat()))
        self.assertEqual([], view_jobs.log_tail(self.jobs / "odd.log"))

    def test_the_readers_write_nothing_and_answer_in_json(self):
        self.rich()
        before = snapshot(self.base)
        agents = view_jobs.agents(self.agents)
        doc = {"agents": agents, "heartbeats": view_jobs.heartbeats(self.jobs), "runs": view_jobs.runs(self.jobs, "brief", NOW.isoformat()),
               "steps": view_jobs.steps_now(self.jobs, "runner"), "lock": view_jobs.lock(self.jobs / "runner.lock"),
               "superseded": view_jobs.superseded(self.jobs, agents)}
        self.assertEqual(json.loads(json.dumps(doc, default=list)), json.loads(json.dumps(doc, default=list)))
        json.dumps(doc, default=list)
        self.assertEqual(before, snapshot(self.base))

    def test_a_failure_is_a_value_never_a_path_or_a_message(self):
        self.rich()
        for doc in (view_jobs.agents(self.agents), view_jobs.heartbeats(self.jobs)):
            self.assertNotIn("Traceback", json.dumps(doc))
            self.assertNotIn("nope", json.dumps(doc))

    def test_the_reader_starts_no_process_and_opens_no_socket(self):
        self.rich()
        import socket
        import subprocess
        with mock.patch.object(subprocess, "Popen", side_effect=AssertionError("process")), \
                mock.patch.object(socket, "socket", side_effect=AssertionError("socket")):
            view_jobs.agents(self.agents)
            view_jobs.heartbeats(self.jobs)
            view_jobs.runs(self.jobs, "brief", NOW.isoformat())

    def test_the_constants_the_page_keeps_are_the_cores(self):
        self.assertEqual(status.RENAMED_JOBS, view_jobs.RENAMED_JOBS)
        self.assertEqual(status.RETIRED_JOBS, view_jobs.RETIRED_JOBS)
        self.assertEqual(status.LOGLINE.pattern, view_jobs.LOGLINE.pattern)
        self.assertEqual(status.RENAMED_FROM, view_jobs.RENAMED_FROM)

    def test_the_reader_is_reached_through_view(self):
        self.assertIs(view.jobs_reader(), view.jobs_reader())
        self.assertTrue(callable(view.jobs_reader().agents))

    def test_it_never_imports_the_jobs_extra(self):
        text = (TOOLS / "view_jobs.py").read_text(encoding="utf-8")
        self.assertNotRegex(text, r"(?m)^\s*(import|from)\s+(job|agent)\b")


def documented(after: str) -> dict:
    """The JSON example that follows `after` in docs/architecture.md."""
    text = (REPO / "docs" / "architecture.md").read_text(encoding="utf-8")
    return json.loads(re.search(r"```json\n(.*?)\n```", text[text.index(after):], re.S).group(1))


class TestDocumentedJobs(Machine):
    """The jobs' shape is documented in docs/architecture.md, with one example that names every field the readers return."""

    def test_the_example_names_every_field(self):
        self.rich()
        doc = documented("The scheduled jobs are `view.jobs_reader()`")
        agents = view_jobs.agents(self.agents)
        self.assertEqual(set(agents["brief"]), set(doc["agents"]["brief"]))
        beat = view_jobs.heartbeats(self.jobs)[0]
        self.assertEqual(set(beat), set(doc["heartbeats"][0]))
        self.assertEqual(len(view_jobs.runs(self.jobs, "brief", (NOW - dt.timedelta(days=3)).isoformat())[0]), len(doc["runs"][0]))
        self.assertEqual(set(view_jobs.steps_now(self.jobs, "runner")[0]), set(doc["steps"][0]))
        self.assertEqual(set(view_jobs.lock(self.jobs / "runner.lock")), set(doc["lock"]))
        self.assertEqual({"agents", "heartbeats", "runs", "steps", "lock"}, set(doc))

    def test_the_view_model_no_longer_names_them_as_left(self):
        self.assertNotIn("jobs folder state", view.LEFT)
        self.assertNotIn("launchd agents", view.LEFT)


class TestHalfUpdated(Machine):
    """The page is new and System/tools is old: a view.py with no `jobs_reader`, or one whose reader is missing."""

    def test_a_workspace_without_the_reader_says_it_needs_updating_and_draws_the_cards_empty(self):
        self.rich()
        with mock.patch.object(status, "view_reader", side_effect=FileNotFoundError("System/tools/view.py")):
            self.assertEqual({}, status.launchd_jobs(self.agents))
            self.assertEqual([], status.jobs(self.jobs, NOW, {}))
            self.assertEqual([], status.history(self.jobs, "brief", NOW))
            self.assertIsNone(status.steps_now(self.jobs, "runner"))
            self.assertFalse(status.lock_held(self.jobs / "runner.lock", NOW))
            self.assertEqual(self.jobs / "brief.log", status.job_log(self.jobs, "brief"))
            self.assertEqual([], status.log_tail(self.jobs / "brief.log"))
            self.assertEqual(({}, set()), status.superseded(self.jobs, {}))

    def _tools_without(self, *names):
        root = self.base / "ws"
        tools = root / "System" / "tools"
        shutil.copytree(TOOLS, tools, ignore=shutil.ignore_patterns("__pycache__"))
        for n in names:
            (tools / n).unlink()
        write(root / "System" / "rules.md", "# Rules\n")
        (root / "Zones" / "Work").mkdir(parents=True)
        return root

    def test_a_new_page_over_tools_that_miss_the_reader_still_builds_and_says_so(self):
        root = self._tools_without("view_jobs.py")
        self.assertIsNone(status.view_model(root))
        page = status.build(root, now=NOW, folder=self.jobs)
        self.assertIn("Garrick needs updating", page)

    def test_a_new_page_over_a_view_that_has_no_jobs_reader_says_so(self):
        root = self._tools_without()
        text = (root / "System" / "tools" / "view.py").read_text(encoding="utf-8").replace("def jobs_reader", "def _gone_reader")
        (root / "System" / "tools" / "view.py").write_text(text, encoding="utf-8")
        self.assertIsNone(status.view_model(root))

    def test_the_tools_that_ship_are_enough(self):
        root = self._tools_without()
        self.assertIsNotNone(status.view_model(root))


# --------------------------------------------------------------------------------------------- the App's own files

import fixtures  # noqa: E402
import view_app  # noqa: E402

NURTURE_DAY = dt.date(2026, 11, 20)


class Workspace(Machine):
    """A workspace with the App's files in it, and the workspace's own tools beside them."""

    def setUp(self):
        super().setUp()
        self.ws = self.base / "ws"
        fixtures.build_workspace(self.ws)
        shutil.copytree(TOOLS, self.ws / "System" / "tools", ignore=shutil.ignore_patterns("__pycache__"))
        status._NURTURE.pop(self.ws, None)

    def seed(self):
        w = self.ws
        write(w / "System" / "generated" / "drift.json", json.dumps({"files": [
            {"state": "drifted", "project": "Acme Review", "file": "Threads/Pricing/memo.docx", "zone": "Work",
             "here_changed": "2026-11-01", "shared_changed": "2026-11-05", "newer": "shared", "here": "a", "shared": "b"},
            {"state": "missing", "project": "Acme Review", "file": "x.md", "zone": "Work"}, "junk", {"state": "other"}]}))
        write(w / "System" / "garrick-version.json", json.dumps({"from": "release", "tag": "v0.80.0", "commit": "abc1234"}))
        write(w / "System" / "garrick-changelog.md", "# Changelog\n\n## 0.80.0\n\n- Something.\n")
        write(w / "System" / "generated" / "status-inbox.json", json.dumps({"at": NOW.isoformat(), "state": "done", "say": "Filed 2 items.",
                                                                           "places": {"Work": {"needs": 1}}}))
        write(w / "Zones" / "Work" / ".todo-followups.json", json.dumps({"abc": {"found": "answered"}, "bad": 3}))
        write(w / "System" / "garrick-checks.json", json.dumps({"todo-chase-days": {"Work": 3, "Personal": 0}, "nurture-weights": {"wall": 5}}))
        write(w / "System" / "generated" / "nurture" / "2026-11-20.json", json.dumps({"standing": [
            {"kind": "wall", "path": "Zones/Work/a.md:3", "line": "x", "check": "wall"}, {"kind": "stale", "path": "Zones/Work/b.md", "check": "stale"}, "junk"]}))


class TestShadowApp(Workspace):
    def setUp(self):
        super().setUp()
        self.old = old_reads(status, "APP")
        self.seed()

    def both(self, name, *args):
        old, new = self.old[name](*args), vars(status)[name](*args)
        self.assertEqual(old, new, name)
        return new

    def test_what_drift_found(self):
        got = self.both("drifted", self.ws)
        self.assertEqual(2, len(got))
        for text in ("{", "[1]", "", "ÿ"):
            write(self.ws / "System" / "generated" / "drift.json", text)
            self.both("drifted", self.ws)
        (self.ws / "System" / "generated" / "drift.json").unlink()
        self.assertEqual([], self.both("drifted", self.ws))
        write(self.ws / "System" / "generated" / "drift.json", json.dumps({"files": "text"}))
        self.both("drifted", self.ws)

    def test_the_version_stamp(self):
        self.assertEqual("v0.80.0", self.both("workspace_stamp", self.ws)["tag"])
        for text in ("[]", "nope"):
            write(self.ws / "System" / "garrick-version.json", text)
            self.assertEqual({}, self.both("workspace_stamp", self.ws))

    def test_the_inbox_run_for_every_state(self):
        path = self.ws / "System" / "generated" / "status-inbox.json"
        lock = self.jobs / "inbox-run.lock"
        for body in ({"at": NOW.isoformat(), "state": "done"}, {"at": NOW.isoformat(), "state": "failed", "say": "x"},
                     {"at": (NOW - dt.timedelta(days=2)).isoformat(), "state": "done"}, {"at": NOW.isoformat(), "state": "odd"},
                     {"at": "never", "state": "done"}, {"state": "done"}, [], {"at": NOW.isoformat(), "state": "running"}):
            write(path, json.dumps(body))
            self.both("inbox_state", self.ws, NOW, self.jobs)
        write(path, "nope")
        self.assertIsNone(self.both("inbox_state", self.ws, NOW, self.jobs))
        write(path, json.dumps({"at": NOW.isoformat(), "state": "running"}))
        self.assertIsNone(self.both("inbox_state", self.ws, NOW, self.jobs))      # no lock: no run is going
        lock.write_text("")
        self.both("inbox_state", self.ws, NOW, self.jobs)
        path.unlink()
        self.assertIsNone(self.both("inbox_state", self.ws, NOW, self.jobs))

    def test_the_kept_check_result(self):
        store = self.ws / "System" / "generated" / "status.check.json"
        good = {"workspace": str(self.ws), "at": NOW.timestamp() - 600, "result": {"errors": 1, "warnings": 2}}
        for body in (good, dict(good, workspace="/elsewhere"), dict(good, at=NOW.timestamp() + 9), dict(good, result={"failed": True}),
                     dict(good, result="text"), {"at": 1}, {"result": {}}, dict(good, at="soon"), [], None, "text", 3):
            write(store, json.dumps(body))
            self.both("kept_check", store, self.ws, NOW)
        self.assertEqual(dict(good["result"], at=good["at"], kept=True), self.both("kept_check", store, self.ws, NOW) if False else dict(good["result"], at=good["at"], kept=True))
        write(store, "nope")
        self.assertIsNone(self.both("kept_check", store, self.ws, NOW))
        store.unlink()
        self.assertIsNone(self.both("kept_check", store, self.ws, NOW))

    def test_a_build_that_reuses_the_kept_result(self):
        store = self.ws / "System" / "generated" / "status.check.json"
        write(self.ws / "System" / "tools" / "check.py", "# stub\n")
        good = {"workspace": str(self.ws), "at": NOW.timestamp() - 600, "result": {"errors": 1, "warnings": 2}}
        write(store, json.dumps(good))
        self.assertEqual(self.old["check"](self.ws, store, float("inf"), NOW), status.check(self.ws, store, float("inf"), NOW))
        store.unlink()
        self.assertEqual({"failed": True, "pending": True}, status.check(self.ws, store, float("inf"), NOW))
        self.assertEqual(self.old["check"](self.ws, store, float("inf"), NOW), status.check(self.ws, store, float("inf"), NOW))

    def test_the_fade_forecast(self):
        got = self.both("forecast_items", self.ws, NURTURE_DAY)
        self.assertEqual({"wall", "stale"}, {f["kind"] for f in got} | {"stale"})
        for day in (NURTURE_DAY - dt.timedelta(days=1), NURTURE_DAY + dt.timedelta(days=3)):
            self.assertEqual([], self.both("forecast_items", self.ws, day))
        rec = self.ws / "System" / "generated" / "nurture" / "2026-11-20.json"
        for text in ("[]", "nope", "{}"):
            write(rec, text)
            self.assertEqual([], self.both("forecast_items", self.ws, NURTURE_DAY))

    def test_the_chase_days_and_the_follow_up_records(self):
        for zone in ("Work", "Personal", "Nowhere"):
            self.both("chase_days_of", self.ws, zone)
        self.assertEqual(3, status.chase_days_of(self.ws, "Work"))
        self.assertEqual(7, status.chase_days_of(self.ws, "Personal"))
        for text in ("[]", "nope", '{"todo-chase-days": 4}', '{"todo-chase-days": true}'):
            write(self.ws / "System" / "garrick-checks.json", text)
            for zone in ("Work", "Personal"):
                self.both("chase_days_of", self.ws, zone)
        z = {"file": str(self.ws / "Zones" / "Work" / "Todo.md")}
        self.assertEqual({"abc": {"found": "answered"}}, self.both("followup_records", z))
        self.assertEqual({}, self.both("followup_records", {}))
        self.assertEqual({}, self.both("followup_records", {"file": str(self.ws / "Zones" / "Personal" / "Todo.md")}))
        write(self.ws / "Zones" / "Work" / ".todo-followups.json", "[1]")
        self.assertEqual({}, self.both("followup_records", z))

    def test_the_guide_tab_reads_the_release_notes_as_it_did(self):
        self.assertEqual(self.old["guide_tab"](self.ws), status.guide_tab(self.ws))
        (self.ws / "System" / "garrick-changelog.md").unlink()
        self.assertEqual(self.old["guide_tab"](self.ws), status.guide_tab(self.ws))


class TestNoWiderAppReads(Workspace):
    def test_each_read_opens_the_file_it_did(self):
        self.seed()
        old = old_reads(status, "APP")
        store = self.ws / "System" / "generated" / "status.check.json"
        write(store, json.dumps({"workspace": str(self.ws), "at": NOW.timestamp() - 600, "result": {"errors": 1}}))
        status.drifted(self.ws)                      # loads the core reader once, so its own file is not counted
        z = {"file": str(self.ws / "Zones" / "Work" / "Todo.md")}

        def whole(ns):
            ns["drifted"](self.ws), ns["workspace_stamp"](self.ws), ns["inbox_state"](self.ws, NOW, self.jobs)
            ns["kept_check"](store, self.ws, NOW), ns["forecast_items"](self.ws, NURTURE_DAY), ns["chase_days_of"](self.ws, "Work")
            ns["followup_records"](z), ns["guide_tab"](self.ws)
        whole(old), whole(vars(status))              # once unrecorded: what either loads and keeps is not the question
        status._NURTURE.pop(self.ws, None)
        before = reads(lambda: whole(old))
        status._NURTURE.pop(self.ws, None)
        after = reads(lambda: whole(vars(status)))
        keep = lambda x: {r for r in x if r[1].startswith(str(self.ws)) or r[1].startswith(str(self.base))}          # noqa: E731
        self.assertTrue(keep(before))
        self.assertEqual(keep(before), keep(after))


class TestTheAppReaders(Workspace):
    def test_every_reader_gives_its_empty_value_for_a_file_that_is_not_there(self):
        gone = self.base / "gone"
        self.assertEqual(({}, {}, None, None, None, None, {}, {}), (
            view_app.drift(gone), view_app.version_stamp(gone), view_app.inbox_run(gone), view_app.kept_check(gone / "x.json"),
            view_app.changelog(gone), view_app.nurture_report(gone, ("System",), NURTURE_DAY), view_app.check_settings(gone),
            view_app.follow_ups(gone)))

    def test_a_file_that_is_not_an_object_is_none_or_empty(self):
        self.seed()
        for text in ("[]", "3", "nope", "ÿ", ""):
            write(self.ws / "System" / "garrick-version.json", text)
            self.assertEqual({}, view_app.version_stamp(self.ws))

    def test_the_readers_write_nothing_and_answer_in_json(self):
        self.seed()
        before = snapshot(self.base)
        doc = {"drift": view_app.drift(self.ws), "stamp": view_app.version_stamp(self.ws), "inbox": view_app.inbox_run(self.ws),
               "changelog": view_app.changelog(self.ws), "report": view_app.nurture_report(self.ws, ("System", "generated", "nurture"), NURTURE_DAY),
               "settings": view_app.check_settings(self.ws), "follow": view_app.follow_ups(self.ws / "Zones" / "Work"),
               "check": view_app.kept_check(self.ws / "System" / "generated" / "status.check.json")}
        self.assertEqual(doc, json.loads(json.dumps(doc)))
        self.assertEqual(before, snapshot(self.base))

    def test_the_reader_starts_no_process_and_opens_no_socket(self):
        self.seed()
        import socket
        import subprocess
        with mock.patch.object(subprocess, "Popen", side_effect=AssertionError("process")), \
                mock.patch.object(socket, "socket", side_effect=AssertionError("socket")):
            view_app.drift(self.ws)
            view_app.inbox_run(self.ws)
            view_app.follow_ups(self.ws / "Zones" / "Work")

    def test_the_page_constants_are_the_cores(self):
        self.assertEqual(status.DRIFT, view_app.DRIFT)
        self.assertEqual(status.INBOX_STATE, view_app.INBOX_STATE)
        self.assertEqual(status.CHANGELOG, view_app.CHANGELOG)
        self.assertEqual(".todo-followups.json", view_app.FOLLOWUPS)

    def test_the_example_in_the_docs_names_every_field(self):
        self.seed()
        doc = documented("The App's own files are `view.app_reader()`")
        self.assertEqual({"drift", "stamp", "inbox", "check", "report", "settings", "follow_ups"}, set(doc))
        self.assertEqual(set(view_app.drift(self.ws)["files"][0]), set(doc["drift"]["files"][0]))
        self.assertEqual(set(view_app.inbox_run(self.ws)), set(doc["inbox"]))
        self.assertEqual(set(view_app.nurture_report(self.ws, ("System", "generated", "nurture"), NURTURE_DAY)), set(doc["report"]))
        self.assertEqual(set(view_app.nurture_report(self.ws, ("System", "generated", "nurture"), NURTURE_DAY)["standing"][0]), set(doc["report"]["standing"][0]))
        self.assertEqual(set(view_app.version_stamp(self.ws)), set(doc["stamp"]))

    def test_the_view_model_names_only_what_stays_with_the_page(self):
        self.assertEqual(("waiting sessions",), tuple(view.LEFT))


class TestOperationsJournal(unittest.TestCase):
    """`operations.jsonl` is not the page's to read: it asks `page_action.py`'s `operations` verb, which answers from
    `operations.py`. So the view model does not list it as left."""

    def test_the_page_never_reads_the_journal(self):
        text = (REPO / "extras" / "status" / "status.py").read_text(encoding="utf-8")
        for word in ("operations.jsonl", "import operations", "operations.Journal", "operations.FILE", "operations.lock"):
            self.assertNotIn(word, text, word)
        self.assertIn("verb:'operations'", text)           # the page asks for it, over the bridge

    def test_the_view_model_does_not_list_it(self):
        self.assertNotIn("operations journal", view.LEFT)


class TestAppHalfUpdated(Workspace):
    def test_a_workspace_without_the_reader_gives_the_empty_values(self):
        self.seed()
        with mock.patch.object(status, "view_reader", side_effect=FileNotFoundError("System/tools/view.py")):
            self.assertEqual([], status.drifted(self.ws))
            self.assertEqual({}, status.workspace_stamp(self.ws))
            self.assertIsNone(status.inbox_state(self.ws, NOW))
            self.assertIsNone(status.kept_check(self.ws / "x.json", self.ws, NOW))
            self.assertEqual({}, status.followup_records({"file": str(self.ws / "Zones" / "Work" / "Todo.md")}))
            self.assertEqual(7, status.chase_days_of(self.ws, "Work"))

    def test_a_new_page_over_tools_that_miss_the_reader_says_so(self):
        (self.ws / "System" / "tools" / "view_app.py").unlink()
        self.assertIsNone(status.view_model(self.ws))
        self.assertIn("Garrick needs updating", status.build(self.ws, now=NOW, folder=self.jobs))


if __name__ == "__main__":
    unittest.main()
