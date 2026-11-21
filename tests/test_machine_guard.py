"""The zone guard on a machine with a role (#612): a roaming copy refuses writes outside the drop folders, and no
edit tool writes the role file, ~/.config/garrick/machine.json, whatever its home or role. The rest of that folder is as before.

    python3 -m unittest test_machine_guard
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

import fixtures  # noqa: E402  (puts the tools folder on sys.path)
from fixtures import GIT_ENV, HAVE_GIT, TOOLS, build_workspace, git, write  # noqa: E402

GUARD = Path(__file__).resolve().parent.parent / "extras" / "hooks" / "zone_guard.py"


class MachineGuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(os.path.realpath(self.tmp.name))
        self.root = base / "workspace"
        for folder in ("System/tools", "Inbox", "Zones/Work/Inbox", "Zones/Work/Acme Review/Threads/Kickoff",
                       "Wikis/Meetings/wiki"):
            (self.root / folder).mkdir(parents=True)
        (self.root / "System" / "rules.md").write_text("# Rules\n")
        self.home = base / "home"
        (self.home / ".config" / "garrick").mkdir(parents=True)
        self.thread = self.root / "Zones/Work/Acme Review/Threads/Kickoff"

    def tearDown(self):
        self.tmp.cleanup()

    def role(self, role):
        (self.home / ".config" / "garrick" / "machine.json").write_text(json.dumps({"role": role, "name": "laptop"}))

    def run_guard(self, path, home=None, headless=False, tool="Write", stage="PreToolUse"):
        home = home or self.thread
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PROJECT_DIR", "GARRICK_HEADLESS")}
        env["HOME"] = str(self.home)
        env["TMPDIR"] = str(self.home)
        env["CLAUDE_PROJECT_DIR"] = str(home)
        if headless:
            env["GARRICK_HEADLESS"] = "1"
        event = {"session_id": "s1", "hook_event_name": stage, "tool_name": tool, "cwd": str(home),
                 "tool_input": {"file_path": str(path)}}
        done = subprocess.run([sys.executable, str(GUARD)], input=json.dumps(event), capture_output=True, text=True,
                              env=env, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stderr, "")
        return json.loads(done.stdout)["hookSpecificOutput"] if done.stdout.strip() else None

    def denied(self, out):
        self.assertIsNotNone(out)
        self.assertEqual(out["permissionDecision"], "deny")
        return out["permissionDecisionReason"]

    # roaming

    def test_a_roaming_machine_refuses_a_thread_note(self):
        self.role("roaming")
        reason = self.denied(self.run_guard(self.thread / "Kickoff.md"))
        self.assertIn("Inbox/", reason)
        self.assertIn("sync", reason)

    def test_a_roaming_machine_refuses_every_place_outside_the_drop_folders(self):
        self.role("roaming")
        for path in ("Zones/Work/Todo.md", "Zones/Work/Acme Review/Acme Review.md", "System/rules.md",
                     "Wikis/Meetings/wiki/page.md", "Inbox", "Zones/Work/Acme Review/Inbox/x.md", "Notes.md",
                     "Zones/Work/Inbox"):
            for home in (self.thread, self.root):
                self.denied(self.run_guard(self.root / path, home=home))

    def test_a_roaming_machine_allows_the_drop_folders(self):
        self.role("roaming")
        for path in ("Inbox/note.md", "Zones/Work/Inbox/mail.eml", "Zones/Work/Inbox/.outbox/r1.json", "inbox/x.md"):
            for home in (self.thread, self.root):
                out = self.run_guard(self.root / path, home=home)      # the zone check may still ask; the machine does not refuse
                self.assertNotEqual((out or {}).get("permissionDecision"), "deny", path)

    def test_a_roaming_machine_leaves_the_outside_alone(self):
        self.role("roaming")
        self.assertIsNone(self.run_guard(Path(self.tmp.name) / "scratch" / "x.md"))

    def test_a_roaming_machine_refuses_a_scheduled_job_too(self):
        self.role("roaming")
        self.denied(self.run_guard(self.thread / "Kickoff.md", headless=True))
        self.assertIsNone(self.run_guard(self.root / "Inbox/x.md", home=self.root, headless=True))

    def test_the_refusal_is_the_same_through_a_link(self):
        self.role("roaming")
        link = self.root / "Inbox" / "back"
        os.symlink(self.root / "System", link)
        self.denied(self.run_guard(link / "rules.md"))

    # solo and server

    def test_solo_and_server_change_nothing(self):
        for role in (None, "solo", "server", "primary"):
            if role:
                self.role(role)
            self.assertIsNone(self.run_guard(self.thread / "Kickoff.md"), role)
            self.assertIsNone(self.run_guard(self.root / "Zones/Work/Todo.md"), role)

    # the role file

    def test_no_session_writes_the_role_file(self):
        target = self.home / ".config" / "garrick" / "machine.json"
        for role in (None, "solo", "server", "roaming"):
            if role:
                self.role(role)
            for home in (self.thread, self.root, self.root / "System"):
                reason = self.denied(self.run_guard(target, home=home))
                self.assertIn("role", reason)
            self.denied(self.run_guard(target, headless=True))

    def test_the_temporary_sibling_of_the_role_file_is_refused(self):
        for role in (None, "solo", "roaming"):
            if role:
                self.role(role)
            self.denied(self.run_guard(self.home / ".config" / "garrick" / "machine.json.tmp"))

    def test_the_rest_of_the_folder_is_written_as_before(self):
        for role in (None, "solo", "server"):
            if role:
                self.role(role)
            for name in ("telegram.json", "work-mail.json", "bridge-cert.pem", "new/x.json", "machine.json.bak"):
                self.assertIsNone(self.run_guard(self.home / ".config" / "garrick" / name), (role, name))

    def test_the_folder_is_refused_through_a_link_and_in_another_case(self):
        link = self.root / "Inbox" / "cfg"
        os.symlink(self.home / ".config" / "garrick", link)
        self.denied(self.run_guard(link / "machine.json"))
        if sys.platform == "darwin":
            self.denied(self.run_guard(Path(str(self.home).swapcase()) / ".CONFIG" / "Garrick" / "machine.json"))

    def test_a_neighbour_of_the_folder_is_not_refused(self):
        self.assertIsNone(self.run_guard(self.home / ".config" / "garrick-other" / "x.json"))
        self.assertIsNone(self.run_guard(self.home / ".config" / "other.json"))

    def test_the_patch_tool_is_covered(self):
        patch = "*** Begin Patch\n*** Update File: %s\n@@\n-a\n+b\n*** End Patch" % (self.home / ".config" / "garrick" / "machine.json")
        event = {"session_id": "s1", "hook_event_name": "PreToolUse", "tool_name": "apply_patch", "cwd": str(self.thread),
                 "tool_input": {"command": patch}}
        env = dict(os.environ, HOME=str(self.home), TMPDIR=str(self.home))
        env.pop("CLAUDE_PROJECT_DIR", None)
        env.pop("GARRICK_HEADLESS", None)
        done = subprocess.run([sys.executable, str(GUARD)], input=json.dumps(event), capture_output=True, text=True, env=env)
        self.assertEqual(json.loads(done.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_the_hook_reads_the_role_as_machine_py_does(self):
        tools = Path(__file__).resolve().parent.parent / "template" / "System" / "tools"
        sys.path.insert(0, str(tools))
        sys.path.insert(0, str(GUARD.parent))
        try:
            import machine
            import zone_guard
            old = os.environ.get("HOME")
            os.environ["HOME"] = str(self.home)
            try:
                for text in (None, "", "{x", "[]", json.dumps({"role": "roaming"}), json.dumps({"role": " Server "}),
                             json.dumps({"role": "primary"}), json.dumps({"role": 3})):
                    target = self.home / ".config" / "garrick" / "machine.json"
                    if text is None:
                        target.unlink() if target.exists() else None
                    else:
                        target.write_text(text)
                    self.assertEqual(zone_guard.machine_role(), machine.role(), text)
            finally:
                if old is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old
        finally:
            sys.path.remove(str(tools))
            sys.path.remove(str(GUARD.parent))


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class CommitTest(unittest.TestCase):
    """Every zone's pre-commit hook runs check.py, which refuses a commit on a roaming machine."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name).resolve()
        self.root = base / "Workspace"
        build_workspace(self.root)
        tools = self.root / "System" / "tools"
        tools.mkdir(parents=True, exist_ok=True)
        for name in ("check.py", "garrick_lib.py", "machine.py"):
            shutil.copy2(TOOLS / name, tools / name)
        self.zone = self.root / "Zones" / "Work"
        shutil.rmtree(self.zone / ".git")
        git(self.zone, "init", "-q")
        fixtures.install_wall_hook(self.zone)
        self.home = base / "home"
        (self.home / ".config" / "garrick").mkdir(parents=True)

    def role(self, role):
        (self.home / ".config" / "garrick" / "machine.json").write_text(json.dumps({"role": role}))

    def commit(self, n=1):
        write(self.zone / "Todo.md", "# Work: open actions\n\n## Inbox\n\n- [ ] A new action %d\n\n## Done\n" % n)
        env = dict(GIT_ENV, HOME=str(self.home), PYTHONDONTWRITEBYTECODE="1")
        git(self.zone, "add", "-A")
        return subprocess.run(["git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "an action"], cwd=str(self.zone),
                              env=env, capture_output=True, text=True)

    def test_a_roaming_machine_refuses_a_commit(self):
        self.role("roaming")
        done = self.commit()
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("only receives", done.stderr)
        self.assertEqual(git(self.zone, "rev-list", "--all", "--count").strip(), "0")

    def test_solo_and_server_commit_as_before(self):
        for n, role in enumerate((None, "solo", "server")):
            if role:
                self.role(role)
            done = self.commit(n)
            self.assertEqual(done.returncode, 0, (role, done.stderr))

    def test_a_missing_machine_py_is_solo(self):
        (self.root / "System" / "tools" / "machine.py").unlink()
        self.role("roaming")
        self.assertEqual(self.commit().returncode, 0)


if __name__ == "__main__":
    unittest.main()
