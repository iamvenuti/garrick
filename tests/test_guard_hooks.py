"""The guard hooks, found the way the user's assistants name them (#670, #671, #672): a path written with `$HOME`, `${HOME}`
or `~`; a folder in the workspace never trusted; what Settings found, shown path by path with a reason. A fake HOME holds each
assistant's settings, the kept download and a marker environment value that must reach no page text.

    cd tests && python3 -m unittest test_guard_hooks
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

import test_settings_actions as sa  # noqa: E402

pa = sa.pa
REPO = sa.REPO
MARKER = "marker-value-7f3a"


class HooksCase(sa.SettingsCase):
    def setUp(self):
        super().setUp()
        env = mock.patch.dict(os.environ, {"GARRICK_MARKER": MARKER})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("UNSET_VAR", None)

    def kept(self, name="kept", files=("zone_guard.py", "read_guard.py"), release=True):
        folder = self.home / name / "extras" / "hooks"
        folder.mkdir(parents=True)
        for f in files:
            if release:
                (folder / f).write_bytes((REPO / "extras" / "hooks" / f).read_bytes())
            else:
                (folder / f).write_text("# another version\n")
        return folder

    def name(self, *commands, codex=False):
        (self.home / ".claude").mkdir(exist_ok=True)
        (self.home / ".claude" / "settings.json").write_text(json.dumps({"hooks": {"PreToolUse": [
            {"hooks": [{"type": "command", "command": c} for c in commands]}]}}))
        if codex:
            (self.home / ".codex").mkdir(exist_ok=True)

    def sg(self):
        return sa.pa_settings_guard()

    def installed_page(self, name="installed"):
        """A page with no hooks folder beside it, as an installed workspace has: `<name>/status/`, under a folder that is not
        `extras`. Only the release digests decide."""
        import contextlib
        status = Path(self._tmp.name).resolve() / name / "status"
        status.mkdir(parents=True, exist_ok=True)
        (status / "settings_guard.py").write_bytes((REPO / "extras" / "status" / "settings_guard.py").read_bytes())
        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch.object(pa, "HERE", status))
        stack.enter_context(mock.patch.object(pa, "_OUTBOX", pa._OUTBOX))
        return stack


class TestAPathWrittenWithAVariable(HooksCase):
    """#670: every way an assistant's settings name the zone guard finds the kept folder."""

    def test_home_braced_home_and_tilde_each_find_the_folder_and_register_the_read_guard(self):
        folder = self.kept()
        for written in ('python3 "$HOME/kept/extras/hooks/zone_guard.py"', 'python3 "${HOME}/kept/extras/hooks/zone_guard.py"',
                        "python3 ~/kept/extras/hooks/zone_guard.py"):
            with self.subTest(written=written):
                self.name(written)
                self.assertIn(folder, self.sg().hook_folders(str(self.home)))
                self.assistants()
                with self.installed_page():
                    out = self.go({"verb": "read-guard", "mode": "warn"})
                self.assertTrue(out["ok"], out)

    def test_a_variable_that_is_not_set_is_dropped_with_no_error(self):
        self.name('python3 "$UNSET_VAR/zone_guard.py"')
        self.assertEqual([], [f for f in self.sg().named_folders(str(self.home)) if f.parent.name != "extras"])
        self.assertEqual([REPO / "extras" / "hooks"], self.sg().hook_folders(str(self.home)))     # only the clone beside the page

    def test_a_relative_path_is_dropped(self):
        self.name("python3 kept/extras/hooks/zone_guard.py")
        self.assertNotIn(Path("kept/extras/hooks"), self.sg().named_folders(str(self.home)))


if __name__ == "__main__":
    unittest.main()
