"""extras/hooks/waiting_hook.py: the Notification hook that marks a session waiting on a permission prompt (#474)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "extras" / "status"))
import agents_working as aw  # noqa: E402

HOOK = Path(__file__).resolve().parent.parent / "extras" / "hooks" / "waiting_hook.py"
SECRET = "Should we tell Birch & Co about the 40 percent discount?"


class Hook(unittest.TestCase):
    """The Notification hook: a marker per session, never the message."""

    def setUp(self):
        self.home = Path(tempfile.mkdtemp())

    def fire(self, **event):
        done = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(event), capture_output=True, text=True,
                              env=dict(os.environ, GARRICK_HOME=str(self.home)), timeout=30)
        self.assertEqual((0, "", ""), (done.returncode, done.stdout, done.stderr))

    def marker(self, sid="s1"):
        try:
            return json.loads((self.home / aw.MARKERS / (sid + ".json")).read_text())
        except OSError:
            return None

    def test_a_permission_prompt_writes_the_kind_the_tool_and_the_time_and_nothing_else(self):
        self.fire(hook_event_name="Notification", session_id="s1", notification_type="permission_prompt",
                  message="Claude needs your permission to use Bash for " + SECRET, cwd="/x")
        m = self.marker()
        self.assertEqual({"session", "kind", "tool", "since"}, set(m))
        self.assertEqual(("permission_prompt", "Bash"), (m["kind"], m["tool"]))
        self.assertNotIn("discount", json.dumps(m))
        self.assertEqual(0, len(list((self.home / aw.MARKERS).glob(".w-*"))))

    def test_the_next_prompt_or_tool_result_clears_it(self):
        for later in ("UserPromptSubmit", "PostToolUse"):
            self.fire(hook_event_name="Notification", session_id="s1", notification_type="idle_prompt", message="waiting")
            self.assertEqual("idle_prompt", self.marker()["kind"])
            self.fire(hook_event_name=later, session_id="s1")
            self.assertIsNone(self.marker(), later)

    def test_an_idle_prompt_never_replaces_an_open_permission_prompt(self):
        self.fire(hook_event_name="Notification", session_id="s1", notification_type="permission_prompt", message="needs permission to use Bash")
        self.fire(hook_event_name="Notification", session_id="s1", notification_type="idle_prompt", message="waiting")
        self.assertEqual(("permission_prompt", "Bash"), (self.marker()["kind"], self.marker()["tool"]))

    def test_another_tools_result_leaves_the_marker_and_the_asked_tools_result_clears_it(self):
        self.fire(hook_event_name="Notification", session_id="s1", notification_type="permission_prompt", message="needs permission to use Bash")
        self.fire(hook_event_name="PostToolUse", session_id="s1", tool_name="Read")
        self.assertIsNotNone(self.marker())
        self.fire(hook_event_name="PostToolUse", session_id="s1", tool_name="Bash")
        self.assertIsNone(self.marker())
        self.fire(hook_event_name="Notification", session_id="s1", notification_type="permission_prompt", message="needs permission to use Bash")
        self.fire(hook_event_name="UserPromptSubmit", session_id="s1")
        self.assertIsNone(self.marker())

    def test_other_notifications_and_bad_ids_write_nothing(self):
        self.fire(hook_event_name="Notification", session_id="s1", notification_type="auth_success", message="x")
        self.fire(hook_event_name="Notification", session_id="../evil", notification_type="permission_prompt", message="x")
        self.fire(hook_event_name="Notification", notification_type="permission_prompt")
        self.assertFalse((self.home / aw.MARKERS).exists())
        done = subprocess.run([sys.executable, str(HOOK)], input="not json", capture_output=True, text=True,
                              env=dict(os.environ, GARRICK_HOME=str(self.home)), timeout=30)
        self.assertEqual(0, done.returncode)


if __name__ == "__main__":
    unittest.main()
