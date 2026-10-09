"""The zone guard in extras/hooks/: what it lets through, what it stops, and
how it answers Claude Code and Codex."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

GUARD = Path(__file__).resolve().parent.parent / "extras" / "hooks" / "zone_guard.py"


class ZoneGuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(os.path.realpath(self.tmp.name))
        self.root = base / "workspace"
        for folder in ("System/tools", "Zones/Work/Acme Review/Threads/Kickoff",
                       "Zones/Work/Birch Entry", "Zones/Personal/Home", "Wikis/Meetings/wiki",
                       "Wikis/Knowledge/wiki"):
            (self.root / folder).mkdir(parents=True)
        (self.root / "System" / "rules.md").write_text("# Rules\n")
        self.state = base / "state"
        self.state.mkdir()
        self.thread = self.root / "Zones/Work/Acme Review/Threads/Kickoff"
        self.session = "s1"

    def tearDown(self):
        self.tmp.cleanup()

    def run_guard(self, event, project_dir=None, headless=False):
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PROJECT_DIR", "GARRICK_HEADLESS")}
        env["TMPDIR"] = str(self.state)
        if headless:
            env["GARRICK_HEADLESS"] = "1"
        if project_dir is not None:
            env["CLAUDE_PROJECT_DIR"] = str(project_dir)
        done = subprocess.run([sys.executable, str(GUARD)], input=event if isinstance(event, str) else json.dumps(event),
                              capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stderr, "")
        return json.loads(done.stdout) if done.stdout.strip() else None

    def claude(self, path, stage="PreToolUse", home=None, cwd=None, tool="Edit"):
        home = self.thread if home is None else home
        event = {"session_id": self.session, "hook_event_name": stage, "tool_name": tool,
                 "cwd": str(cwd or home), "tool_input": {"file_path": str(path)}}
        return self.run_guard(event, project_dir=home)

    def codex(self, patch, home=None):
        event = {"session_id": self.session, "hook_event_name": "PreToolUse", "tool_name": "apply_patch",
                 "cwd": str(home or self.thread), "tool_input": {"command": patch}}
        return self.run_guard(event)

    def decision(self, reply):
        self.assertIsNotNone(reply)
        out = reply["hookSpecificOutput"]
        self.assertEqual(out["hookEventName"], "PreToolUse")
        return out["permissionDecision"], out["permissionDecisionReason"]

    # Claude Code

    def test_inside_the_project_goes_ahead(self):
        self.assertIsNone(self.claude(self.thread / "Kickoff.md"))
        self.assertIsNone(self.claude(self.root / "Zones/Work/Acme Review/Acme Review.md"))

    def test_a_file_loose_in_the_zone_goes_ahead(self):
        self.assertIsNone(self.claude(self.root / "Zones/Work/Todo.md"))

    def test_outside_the_workspace_goes_ahead(self):
        self.assertIsNone(self.claude(Path(self.tmp.name) / "scratch" / "notes.md"))

    def test_system_is_asked(self):
        decision, reason = self.decision(self.claude(self.root / "System/tools/check.py"))
        self.assertEqual(decision, "ask")
        self.assertIn("Work › Acme Review", reason)
        self.assertIn("System (System/tools/check.py)", reason)

    def test_another_project_and_another_zone_are_asked(self):
        decision, reason = self.decision(self.claude(self.root / "Zones/Work/Birch Entry/Birch Entry.md"))
        self.assertEqual(decision, "ask")
        self.assertIn("Work › Birch Entry", reason)
        decision, reason = self.decision(self.claude(self.root / "Zones/Personal/Home/Home.md"))
        self.assertIn("Personal › Home", reason)

    def test_a_folder_in_the_zone_is_not_loose(self):
        decision, _ = self.decision(self.claude(self.root / "Zones/Work/.share/deck.pptx"))
        self.assertEqual(decision, "ask")

    def test_every_editing_tool_is_covered(self):
        for tool in ("Write", "MultiEdit"):
            self.assertEqual(self.decision(self.claude(self.root / "System/rules.md", tool=tool))[0], "ask")
        event = {"session_id": "nb", "hook_event_name": "PreToolUse", "tool_name": "NotebookEdit",
                 "cwd": str(self.thread), "tool_input": {"notebook_path": str(self.root / "System/a.ipynb")}}
        self.assertEqual(self.decision(self.run_guard(event, project_dir=self.thread))[0], "ask")

    def test_other_tools_are_ignored(self):
        event = {"session_id": self.session, "hook_event_name": "PreToolUse", "tool_name": "Bash",
                 "cwd": str(self.thread), "tool_input": {"command": "touch ../../../../System/x"}}
        self.assertIsNone(self.run_guard(event, project_dir=self.thread))

    def test_a_session_at_the_root_is_never_stopped(self):
        self.assertIsNone(self.claude(self.root / "Zones/Personal/Home/Home.md", home=self.root))

    def test_a_session_in_system_is_never_stopped(self):
        for home in (self.root / "System", self.root / "System/tools"):
            for target in ("Zones/Personal/Home/Home.md", "Zones/Work/Acme Review/x.md",
                           "Wikis/Meetings/wiki/index.md", "Wikis/Knowledge/wiki/index.md"):
                self.assertIsNone(self.claude(self.root / target, home=home))
        patch = "*** Begin Patch\n*** Update File: ../Zones/Work/Birch Entry/x.md\n*** End Patch\n"
        self.assertIsNone(self.codex(patch, home=self.root / "System"))

    def test_a_zone_session_may_write_its_zone(self):
        zone = self.root / "Zones/Work"
        self.assertIsNone(self.claude(self.root / "Zones/Work/Birch Entry/x.md", home=zone))
        decision, reason = self.decision(self.claude(self.root / "Zones/Personal/Todo.md", home=zone))
        self.assertIn("the Work zone", reason)
        self.assertIn("the Personal zone", reason)

    def test_a_wiki_is_its_own_place(self):
        wiki = self.root / "Wikis/Meetings"
        self.assertIsNone(self.claude(wiki / "wiki/index.md", home=wiki))
        decision, reason = self.decision(self.claude(self.root / "Wikis/Knowledge/wiki/index.md", home=wiki))
        self.assertIn("Wikis › Meetings", reason)
        self.assertIn("Wikis › Knowledge", reason)

    def test_the_session_home_stays_where_it_started(self):
        # A command changed folder to System/; the session still belongs to the thread.
        reply = self.claude(self.root / "System/tools/check.py", cwd=self.root / "System")
        self.assertEqual(self.decision(reply)[0], "ask")

    def test_an_allowed_place_is_not_asked_again(self):
        target = self.root / "System/tools/check.py"
        self.assertEqual(self.decision(self.claude(target))[0], "ask")
        self.assertEqual(self.decision(self.claude(target))[0], "ask")  # refused: ask again
        self.assertIsNone(self.claude(target, stage="PostToolUse"))   # allowed and written
        self.assertIsNone(self.claude(self.root / "System/rules.md"))
        self.assertEqual(self.decision(self.claude(self.root / "Zones/Personal/Home/Home.md"))[0], "ask")
        self.session = "s2"
        self.assertEqual(self.decision(self.claude(target))[0], "ask")

    # Codex

    def test_codex_is_refused_once_per_place(self):
        patch = ("*** Begin Patch\n*** Update File: ../../../../../System/tools/check.py\n"
                 "@@\n-a\n+b\n*** End Patch\n")
        decision, reason = self.decision(self.codex(patch))
        self.assertEqual(decision, "deny")
        self.assertIn("Ask the user", reason)
        self.assertIn("System (System/tools/check.py)", reason)
        self.assertIsNone(self.codex(patch))

    def test_codex_inside_the_project_goes_ahead(self):
        patch = "*** Begin Patch\n*** Add File: notes.md\n+hello\n*** End Patch\n"
        self.assertIsNone(self.codex(patch))

    def test_codex_names_every_place_a_patch_reaches(self):
        patch = ("*** Begin Patch\n*** Update File: Kickoff.md\n@@\n-a\n+b\n"
                 "*** Update File: %s\n@@\n-a\n+b\n"
                 "*** Update File: %s\n*** Move to: %s\n*** End Patch\n"
                 % (self.root / "Wikis/Meetings/wiki/index.md", self.thread / "a.md",
                    self.root / "Zones/Personal/Home/a.md"))
        _, reason = self.decision(self.codex(patch))
        self.assertIn("Wikis › Meetings", reason)
        self.assertIn("Personal › Home", reason)
        self.assertNotIn("Kickoff.md", reason)

    # Whatever happens, it never stops work by breaking

    def test_bad_input_lets_the_edit_through(self):
        self.assertIsNone(self.run_guard("not json"))
        self.assertIsNone(self.run_guard({"hook_event_name": "PreToolUse", "tool_name": "Edit"}))

    def test_a_scheduled_job_is_never_stopped(self):
        event = {"session_id": self.session, "hook_event_name": "PreToolUse", "tool_name": "Write",
                 "cwd": str(self.thread), "tool_input": {"file_path": str(self.root / "System/rules.md")}}
        self.assertIsNone(self.run_guard(event, project_dir=self.thread, headless=True))

    def test_outside_any_workspace_it_is_silent(self):
        elsewhere = Path(os.path.realpath(self.tmp.name)) / "elsewhere"
        elsewhere.mkdir()
        self.assertIsNone(self.claude(self.root / "System/rules.md", home=elsewhere))


if __name__ == "__main__":
    unittest.main()
