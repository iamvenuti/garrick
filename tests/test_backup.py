"""The backup extra: extras/jobs/backup.py commits and pushes every
repository of the workspace, holding back only what the wall check refuses.

    python3 -m unittest discover -s tests

Every repository and remote is a real git repository in a temporary folder.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import HAVE_GIT, build_workspace, git, meeting_page, write  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
JOBS = REPO / "extras" / "jobs"
TOOLS = REPO / "template" / "System" / "tools"
sys.path.insert(0, str(JOBS))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


backup = _load("garrick_backup", JOBS / "backup.py")

NO_USER_GIT = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "Jo",
               "GIT_AUTHOR_EMAIL": "jo@example.invalid", "GIT_COMMITTER_NAME": "Jo",
               "GIT_COMMITTER_EMAIL": "jo@example.invalid"}


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class BackupTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name).resolve()
        env = mock.patch.dict(os.environ, NO_USER_GIT)
        env.start()
        self.addCleanup(env.stop)
        self.ws = base / "Workspace"
        build_workspace(self.ws)
        (self.ws / "System" / "tools").mkdir(parents=True, exist_ok=True)
        for name in ("check.py", "garrick_lib.py"):
            shutil.copy(TOOLS / name, self.ws / "System" / "tools" / name)
        self.work = self.ws / "Zones" / "Work"
        shutil.rmtree(self.work / ".git")
        git(self.work, "init", "-q", "-b", "main")
        shutil.rmtree(self.ws / "Zones" / "Personal" / ".git")      # one zone is enough here
        self.remote = base / "work-remote.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.remote)], check=True)
        git(self.work, "remote", "add", "origin", str(self.remote))
        self.jobs = base / "jobs"
        self.said = []
        notify = mock.patch.object(backup.job, "notify")
        self.notify = notify.start()
        self.addCleanup(notify.stop)
        write(self.ws / "Wikis" / "Meetings" / "wiki" / "sources" / "260312-birch-call.md",
              meeting_page("Work", "[birch]", "Birch call"))

    def run_backup(self, now=None):
        return backup.run(self.ws, now=now, folder=self.jobs, say=self.said.append)

    def pushed(self):
        r = subprocess.run(["git", "--git-dir", str(self.remote), "log", "--format=%s", "main"],
                           capture_output=True, text=True)
        return r.stdout.split("\n") if r.returncode == 0 else []

    def test_everything_clean_is_committed_and_pushed(self):
        self.assertEqual(backup.OK, self.run_backup())
        self.assertTrue(self.pushed()[0].startswith("Backup, "))
        self.assertEqual("", git(self.work, "status", "--porcelain").strip())
        self.assertEqual(backup.OK, self.run_backup())                   # nothing new: nothing to do
        self.notify.assert_not_called()

    def test_a_walled_file_is_held_back_and_the_rest_backed_up(self):
        acme = self.work / "Acme Review"
        write(acme / "Notes.md", "Background: [[260312-birch-call]]\n")
        self.assertEqual(backup.HELD, self.run_backup())
        tracked = git(self.work, "ls-files").split("\n")
        self.assertIn("Acme Review/Acme Review.md", tracked)
        self.assertNotIn("Acme Review/Notes.md", tracked)
        self.assertTrue((acme / "Notes.md").is_file())                   # held, never lost
        self.assertTrue(self.pushed())
        self.notify.assert_called_once()
        self.assertIn("Zones/Work/Acme Review/Notes.md", self.notify.call_args[0][2])
        self.assertEqual(backup.HELD, self.run_backup())                 # the same list: no second notice
        self.notify.assert_called_once()
        code = (JOBS / "backup.py").read_text()
        for flag in ('"--no-verify"', '"--force"', '"-f"', '"rebase"', '"merge"'):
            self.assertNotIn(flag, code)                                # never passed to git

    def test_a_remote_ahead_is_left_alone(self):
        self.assertEqual(backup.OK, self.run_backup())
        other = Path(self._tmp.name) / "other"
        subprocess.run(["git", "clone", "-q", str(self.remote), str(other)], check=True)
        write(other / "elsewhere.md", "From another machine.\n")
        git(other, "add", "-A")
        git(other, "commit", "-q", "-m", "elsewhere")
        git(other, "push", "-q")
        write(self.work / "Todo.md", "# Work: open actions\n\n## Inbox\n\n- [ ] Call Dana\n\n## Done\n")
        self.assertEqual(backup.FAILED, self.run_backup())
        self.assertTrue(any("Pull by hand" in line for line in self.said))
        self.assertEqual("elsewhere", self.pushed()[0])

    def test_offline_is_quiet_then_a_failure_then_recovers(self):
        git(self.work, "remote", "set-url", "origin", str(Path(self._tmp.name) / "gone.git"))
        start = dt.datetime(2026, 10, 1, 9, 0)
        self.assertEqual(backup.OFFLINE, self.run_backup(start))
        self.assertTrue(git(self.work, "log", "--format=%s").startswith("Backup, "))   # committed all the same
        self.assertEqual(backup.FAILED, self.run_backup(start + dt.timedelta(days=4)))
        git(self.work, "remote", "set-url", "origin", str(self.remote))
        self.assertEqual(backup.OK, self.run_backup(start + dt.timedelta(days=4, hours=1)))
        self.assertTrue(self.pushed())
        self.assertEqual("recovered", self.notify.call_args[0][0])
        self.assertNotIn("offline_since", json.loads((self.jobs / backup.STATE).read_text()))

    def test_the_launchd_example_runs_it_through_job_py_twice_a_day(self):
        import plistlib
        plist = plistlib.loads((JOBS / "launchd" / "garrick.backup.plist").read_bytes())
        args = plist["ProgramArguments"]
        self.assertEqual(["/usr/bin/python3", "/Users/<you>/Garrick/System/jobs/job.py", "backup"], args[:3])
        self.assertNotIn("--agent", args)
        self.assertEqual("/Users/<you>/Garrick/System/jobs/backup.py", args[args.index("--") + 2])
        self.assertEqual("5 6", plist["EnvironmentVariables"]["GARRICK_QUIET_EXITS"])
        self.assertEqual(2, len(plist["StartCalendarInterval"]))

    def test_a_merge_under_way_is_left_alone(self):
        self.assertEqual(backup.OK, self.run_backup())
        (self.work / ".git" / "MERGE_HEAD").write_text(git(self.work, "rev-parse", "HEAD"))
        write(self.work / "Todo.md", "# Work\n\n<<<<<<< ours\n=======\n>>>>>>> theirs\n")
        before = git(self.work, "rev-parse", "HEAD")
        self.assertEqual(backup.FAILED, self.run_backup())
        self.assertEqual(before, git(self.work, "rev-parse", "HEAD"))
        self.assertTrue(any("middle of a merge" in line for line in self.said))

    def test_a_refusal_no_unstaging_clears_stops_at_once_and_says_so(self):
        calls = []

        def refused(ws, repo):
            calls.append(1)
            return [("Acme Review/Acme Review.md", "names a different party on disk from the one staged")], None
        self.assertEqual(backup.OK, self.run_backup())                  # everything else is backed up already
        write(self.work / "Notes.md", "A note.\n")
        with mock.patch.object(backup, "refused", side_effect=refused):
            self.assertEqual(backup.HELD, self.run_backup())
        self.assertEqual(2, len(calls))                       # held once, then seen to be no progress
        self.assertTrue(any("settled by hand" in line for line in self.said), self.said)
        self.assertEqual("", git(self.work, "diff", "--cached", "--name-only").strip())

    def test_the_worst_outcome_decides(self):
        self.assertEqual(backup.FAILED, backup.worst([backup.HELD, backup.FAILED, backup.OFFLINE]))
        self.assertEqual(backup.OFFLINE, backup.worst([backup.HELD, backup.OFFLINE, backup.OK]))
        self.assertEqual(backup.HELD, backup.worst([backup.OK, backup.HELD]))
        self.assertEqual(backup.OK, backup.worst([]))


if __name__ == "__main__":
    unittest.main()
