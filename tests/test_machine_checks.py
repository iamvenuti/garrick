"""The checks and the jobs on a machine with a role (#612): sync conflict copies, the path the server records, a
launchd agent loaded on a roaming copy, and a job that refuses to run there. A fake HOME in every test.

    python3 -m unittest test_machine_checks
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import build_workspace, write  # noqa: E402

import check  # noqa: E402  (fixtures puts the tools folder on sys.path)

JOB = Path(__file__).resolve().parent.parent / "extras" / "jobs" / "job.py"


class Machine(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name).resolve()
        self.home = base / "home"
        self.home.mkdir()
        self.root = base / "Workspace"
        build_workspace(self.root)
        patch = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        patch.start()
        self.addCleanup(patch.stop)

    def role(self, role, **more):
        target = self.home / ".config" / "garrick" / "machine.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(dict(role=role, **more)))

    def findings(self):
        return [f for f in check.run_checks(self.root) if f.check == "machines"]

    def server_file(self):
        return self.root / "System" / "generated" / "server-path.json"


class ConflictCopies(Machine):
    def test_a_syncthing_conflict_copy_is_reported_on_a_server(self):
        self.role("server", name="mini")
        write(self.root / "Zones/Work/Acme Review/Threads/Pricing/Pricing.sync-conflict-20261101-101010-ABCDEFG.md", "x")
        found = self.findings()
        self.assertEqual(1, len(found))
        self.assertEqual("Zones/Work", found[0].path)
        self.assertIn("1 sync conflict copy", found[0].message)
        self.assertIn("Pricing.sync-conflict-", found[0].message)

    def test_dropbox_and_onedrive_copies_are_reported(self):
        self.role("server", name="mini", server="mini", peers=["laptop"])
        write(self.root / "Zones/Work/Todo (Jo's conflicted copy 2026-11-01).md", "x")
        write(self.root / "Zones/Personal/Plan-laptop.docx", "x")
        write(self.root / "Zones/Personal/Plan.docx", "x")
        write(self.root / "Zones/Personal/Plan-harbour.docx", "x")           # not a machine this file knows
        write(self.root / "Wikis/Meetings/wiki/index (conflicted copy).md", "x")
        found = {f.path: f.message for f in self.findings()}
        self.assertEqual({"Zones/Work", "Zones/Personal", "Wikis/Meetings"}, set(found))
        self.assertIn("Plan-laptop.docx", found["Zones/Personal"])
        self.assertNotIn("Plan-harbour", found["Zones/Personal"])

    def test_each_place_reports_its_own_files_and_count(self):
        self.role("server", name="mini")
        write(self.root / "Zones/Work/a.sync-conflict-1.md", "x")
        write(self.root / "Zones/Work/b.sync-conflict-2.md", "x")
        write(self.root / "Zones/Personal/c.sync-conflict-3.md", "x")
        found = {f.path: f.message for f in self.findings()}
        self.assertIn("2 sync conflict copies", found["Zones/Work"])
        self.assertIn("1 sync conflict copy", found["Zones/Personal"])
        self.assertNotIn("c.sync-conflict", found["Zones/Work"])
        self.assertNotIn("a.sync-conflict", found["Zones/Personal"])

    def test_one_inside_dot_git_is_found_and_objects_are_not_read(self):
        self.role("server", name="mini")
        write(self.root / "Zones/Work/.git/index.sync-conflict-1", "x")
        write(self.root / "Zones/Work/.git/objects/ab/cd.sync-conflict-2", "x")
        found = self.findings()
        self.assertEqual(1, len(found))
        self.assertIn("1 sync conflict copy", found[0].message)

    def test_solo_reports_nothing_and_reads_nothing(self):
        write(self.root / "Zones/Work/a.sync-conflict-1.md", "x")
        self.assertEqual([], self.findings())
        self.assertFalse(self.server_file().exists())

    def test_a_clean_server_is_clean(self):
        self.role("server", name="mini")
        self.assertEqual([], self.findings())


class PathMismatch(Machine):
    def test_the_server_records_its_path_where_the_sync_carries_it(self):
        self.role("server", name="mini")
        self.findings()
        data = json.loads(self.server_file().read_text())
        self.assertEqual(str(self.root), data["path"])

    def test_a_roaming_copy_at_another_path_is_warned(self):
        self.role("roaming", name="laptop", server="mini")
        write(self.server_file(), json.dumps({"path": "/Users/other/Garrick"}))
        with mock.patch.object(check, "launchd_labels", return_value=[]):
            found = self.findings()
        self.assertEqual(1, len(found))
        self.assertEqual("warning", found[0].severity)
        self.assertIn("/Users/other/Garrick", found[0].message)
        self.assertIn(str(self.root), found[0].message)

    def test_the_same_path_is_clean(self):
        self.role("roaming", name="laptop", server="mini")
        write(self.server_file(), json.dumps({"path": str(self.root)}))
        with mock.patch.object(check, "launchd_labels", return_value=[]):
            self.assertEqual([], self.findings())

    def test_no_record_yet_is_not_a_mismatch(self):
        self.role("roaming", name="laptop")
        with mock.patch.object(check, "launchd_labels", return_value=[]):
            self.assertEqual([], self.findings())

    def test_a_recorded_workspace_that_is_not_this_one_is_warned(self):
        self.role("roaming", name="laptop", workspace="/Users/other/Garrick")
        with mock.patch.object(check, "launchd_labels", return_value=[]):
            found = self.findings()
        self.assertEqual(1, len(found))
        self.assertIn("machine.json", found[0].path)


class LoadedAgent(Machine):
    def test_a_loaded_agent_on_a_roaming_machine_is_an_error(self):
        self.role("roaming", name="laptop")
        with mock.patch.object(check, "launchd_labels", return_value=["garrick.gr-nightly"]):
            found = self.findings()
        self.assertEqual(["error"], [f.severity for f in found])
        self.assertIn("garrick.gr-nightly", found[0].message)

    def test_a_server_and_a_solo_machine_may_load_agents(self):
        for role in ("server", "solo"):
            self.role(role, name="mini")
            with mock.patch.object(check, "launchd_labels", return_value=["garrick.gr-nightly"]) as labels:
                self.assertEqual([], self.findings(), role)
                labels.assert_not_called()

    def test_the_labels_are_launchctls_own_and_garricks(self):
        out = "PID\tStatus\tLabel\n-\t0\tgarrick.gr-notes\n123\t0\tcom.apple.Finder\n-\t0\tgarrick.gr-todo-sweep\n"
        agents = self.home / "Library" / "LaunchAgents"
        agents.mkdir(parents=True)
        import plistlib
        (agents / "mine.plist").write_bytes(plistlib.dumps({"Label": "home.sweep", "ProgramArguments": ["/usr/bin/python3", "/x/job.py", "sweep"]}))
        done = subprocess.CompletedProcess([], 0, stdout=out + "-\t0\thome.sweep\n", stderr="")
        with mock.patch("subprocess.run", return_value=done):
            self.assertEqual(["garrick.gr-notes", "garrick.gr-todo-sweep", "home.sweep"], check.launchd_labels())

    def test_no_launchctl_is_no_agent(self):
        with mock.patch("subprocess.run", side_effect=OSError):
            self.assertEqual([], check.launchd_labels())


class JobsOnARoamingMachine(Machine):
    def run_job(self):
        env = dict(os.environ, HOME=str(self.home), GARRICK_JOBS_DIR=str(self.home / "jobs"))
        env.pop("GARRICK_WORKSPACE", None)
        marker = self.home / "ran"
        done = subprocess.run([sys.executable, str(JOB), "tidy", "--cwd", str(self.home), "--", sys.executable, "-c",
                               "open(%r, 'w').write('x')" % str(marker)], env=env, capture_output=True, text=True, timeout=60)
        return done, marker

    def test_a_job_does_not_run_on_a_roaming_machine(self):
        self.role("roaming", name="laptop")
        done, marker = self.run_job()
        self.assertEqual(0, done.returncode, done.stderr)
        self.assertIn("roaming", done.stderr)
        self.assertFalse(marker.exists())
        self.assertFalse((self.home / "jobs" / "tidy.heartbeat.json").exists())

    def test_a_job_runs_on_solo_and_server(self):
        for role in (None, "solo", "server"):
            if role:
                self.role(role, name="mini")
            done, marker = self.run_job()
            self.assertEqual(0, done.returncode, (role, done.stderr))
            self.assertTrue(marker.exists(), role)
            marker.unlink()


if __name__ == "__main__":
    unittest.main()
