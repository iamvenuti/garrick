"""What an update says and does about the guard hooks the assistants' settings name (#670, #672): a path written with `$HOME`,
`${HOME}` or `~` is read as the shell reads it, the report shows it as written, and a kept download's hook files are refreshed
on a yes. A fake HOME holds the settings and the kept download; this Mac's own are never read or written.

    cd tests && python3 -m unittest test_guard_update
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

import test_update as tu  # noqa: E402

update = tu.update
REPO = tu.REPO
MARKER = "marker-value-7f3a"


class GuardCase(tu.ExtrasCase):
    def setUp(self):
        super().setUp()
        env = mock.patch.dict(os.environ, {"GARRICK_MARKER": MARKER})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("UNSET_VAR", None)
        self.home = self.base / "home"
        (self.home / ".claude").mkdir(parents=True, exist_ok=True)

    def kept(self, text="# an older guard\n", name="kept", files=("zone_guard.py", "read_guard.py")):
        folder = self.home / name / "extras" / "hooks"
        folder.mkdir(parents=True, exist_ok=True)
        for f in files:
            (folder / f).write_text(text)
        return folder

    def name(self, *commands, codex=None):
        entry = {"hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": c} for c in commands]}]}}
        (self.home / ".claude" / "settings.json").write_text(json.dumps(entry))
        if codex is not None:
            (self.home / ".codex").mkdir(exist_ok=True)
            (self.home / ".codex" / "hooks.json").write_text(json.dumps(codex))

    def report(self):
        p = self.plan()
        p["then"] = [what for what, _ in update.next_steps(self.root, p)]
        return update.report(p)


class TestAGuardNamedThroughAVariable(GuardCase):
    def test_a_zone_guard_of_another_version_is_named_however_the_settings_write_the_path(self):
        self.kept()
        for written in ('python3 "$HOME/kept/extras/hooks/zone_guard.py"', 'python3 "${HOME}/kept/extras/hooks/zone_guard.py"',
                        "python3 ~/kept/extras/hooks/zone_guard.py"):
            with self.subTest(written=written):
                self.name(written)
                said = self.report()
                self.assertIn("The zone guard runs from ~/kept/extras/hooks/zone_guard.py, which differs from this Garrick's", said)
                self.assertNotIn(str(self.home), said)

    def test_a_read_guard_of_another_version_is_named_through_home_too(self):
        self.kept()
        self.name('python3 "$HOME/kept/extras/hooks/read_guard.py"')
        self.assertIn("The read guard runs from ~/kept/extras/hooks/read_guard.py, which differs", self.report())

    def test_a_guard_that_is_this_releases_is_not_named(self):
        folder = self.kept()
        (folder / "zone_guard.py").write_bytes((REPO / "extras/hooks/zone_guard.py").read_bytes())
        self.name('python3 "$HOME/kept/extras/hooks/zone_guard.py"')
        self.assertNotIn("zone guard", self.report())

    def test_a_variable_that_is_not_set_is_dropped_with_no_error(self):
        self.name('python3 "$UNSET_VAR/zone_guard.py"', 'python3 "$GARRICK_MARKER/zone_guard.py"')
        said = self.report()
        self.assertNotIn("zone guard", said)
        self.assertNotIn(MARKER, said)

    def test_no_value_of_an_environment_variable_reaches_the_report(self):
        self.kept(name="kept")
        with mock.patch.dict(os.environ, {"GARRICK_KEEP": str(self.home / "kept")}):
            self.name('python3 "$GARRICK_KEEP/extras/hooks/zone_guard.py"')
            said = self.report()
        self.assertIn("The zone guard runs from $GARRICK_KEEP/extras/hooks/zone_guard.py", said)
        self.assertNotIn(str(self.home / "kept"), said)


if __name__ == "__main__":
    unittest.main()
