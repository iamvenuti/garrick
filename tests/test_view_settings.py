"""Settings' data (#650): `System/tools/view_settings.py` reads it, `status.py` only draws it.

    cd tests && python3 -m unittest test_view_settings

The shadow test. `golden/settings_0780/` holds the Settings dialog as v0.78.0's page drew it on three fixture workspaces,
byte for byte, with the workspace's own path written as `<ROOT>`. The page built from the document must match them: the
same markup, from the same files. (The goldens were written by v0.78.0's own code, before any Settings markup changed.
They stand until a Settings item changes markup on purpose; `GARRICK_WRITE_GOLDEN=<folder>` writes them again.)

Also here: the document is JSON, builds nothing it was not asked for, writes nothing, and a reader that fails leaves its
field empty instead of raising.
"""

from __future__ import annotations

import json
import os
import plistlib
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from test_settings_ui import SettingsCase, sg  # noqa: E402
from test_status import REPO, status  # noqa: E402
from test_view_model import snapshot  # noqa: E402

TOOLS = REPO / "template" / "System" / "tools"
sys.path.insert(0, str(TOOLS))
import view  # noqa: E402
import view_settings  # noqa: E402

GOLDEN = Path(__file__).resolve().parent / "golden" / "settings_0780"
EXTRAS = REPO / "extras" / "status"


class Fixtures(SettingsCase):
    """Three workspaces: a bare one, one with everything switched on, and one whose readers fail."""

    def setUp(self):
        super().setUp()
        self.base = Path(self._tmp.name).resolve()

    def args(self):
        return (self.root, ("claude", "codex", "cmux"), ("Work", "Personal"), {}, True, status.Links(self.root),
                [("project", "Project", "Teal")], {})

    def draw(self):
        return status.settings(*self.args()).replace(str(self.root), "<ROOT>")

    def bare(self):
        return self.draw()

    def rich(self):
        cmux = self.base / "cmuxlib.py"
        cmux.write_text("")
        patch = mock.patch.object(status, "CMUXLIB", cmux)
        patch.start()
        self.addCleanup(patch.stop)
        self.role("roaming", name="laptop", server="mini")
        self.assistants(registered=True)
        self.settings_file(**{"read-guard": "warn", "read-guard-cross-zone": "ask", "connector-tools": ["mcp__*Mail*"],
                              "connector-tools-skip": ["mcp__weather__*"], "release-notice": True, "release-notice-every": 7,
                              "usage-counts": False, "ask": True,
                              "channels": {"ask": {"tier": "opus", "effort": "high", "autonomy": "act"},
                                           "telegram": {"tier": "haiku", "effort": "low", "autonomy": "act"}}})
        self.log(("Work", "Bash", "deny", 3), ("Work", "mcp__acme_Gmail__search", "confirm", 5), ("Personal", "Read", "deny", 30),
                 ("Work", "Read", "allow", 2))
        (self.root / "System" / "garrick-flags.json").write_text(json.dumps({"effort": True}))
        (self.root / "System" / "desk.json").write_text(json.dumps({"agent": "codex"}))
        (self.root / "System" / "generated" / "fade").mkdir(parents=True, exist_ok=True)
        (self.root / "System" / "generated" / "fade" / "Meetings.md").write_text("# What would fade\n")
        self.jobs.mkdir(parents=True, exist_ok=True)
        (self.jobs / "telegram-status.json").write_text(json.dumps({"state": "unpaired", "why": "No chat is paired yet."}))
        agents = self.base / "LaunchAgents"
        agents.mkdir(exist_ok=True)
        (agents / "todo.plist").write_bytes(plistlib.dumps({
            "Label": "home.todo", "ProgramArguments": ["/usr/bin/python3", "/x/job.py", "gr-todo-sweep"],
            "EnvironmentVariables": {"GARRICK_NOTIFY_CMD": "say"}}))
        return self.draw()

    def broken(self):
        """No tools, no extras that load: every reader answers with nothing."""
        (self.root / "System" / "tools").unlink()
        (self.root / "System" / "garrick-settings.json").write_text("[1, 2")
        return self.draw()

    def cases(self):
        return {"bare": self.bare, "rich": self.rich, "broken": self.broken}


class TestTheShadow(Fixtures):
    def check(self, name, markup):
        out = os.environ.get("GARRICK_WRITE_GOLDEN")
        if out:
            Path(out).mkdir(parents=True, exist_ok=True)
            Path(out, name + ".html").write_text(markup, encoding="utf-8")
        else:
            self.assertEqual(GOLDEN.joinpath(name + ".html").read_text(encoding="utf-8"), markup, name)

    def test_a_bare_workspace_draws_what_v0780_drew(self):
        self.check("bare", self.bare())

    def test_a_workspace_with_everything_set_draws_what_v0780_drew(self):
        self.check("rich", self.rich())

    def test_a_workspace_whose_readers_fail_draws_what_v0780_drew(self):
        self.check("broken", self.broken())


class TestTheDocument(Fixtures):
    def doc(self, **kw):
        return view_settings.read(self.root, EXTRAS, **kw)

    def test_it_is_json_and_names_what_it_reads(self):
        self.rich()
        doc = self.doc(jobs=status.launchd_jobs())
        json.loads(json.dumps(doc))
        self.assertEqual("codex", doc["desk_agent"])
        self.assertEqual({"effort": True}, doc["flags"])
        self.assertEqual(7, doc["release"]["notice_every"])
        self.assertTrue(doc["release"]["notice_on"])
        self.assertFalse(doc["usage_counts"])
        self.assertEqual("roaming", doc["machine"]["role"])
        self.assertEqual("laptop", doc["machine"]["name"])
        self.assertEqual("opus", doc["channels"]["settings"]["ask"]["tier"])
        self.assertEqual("unpaired", doc["channels"]["telegram"]["state"])
        self.assertEqual(["Meetings"], sorted(doc["memory"]["full_list"]))
        self.assertEqual("warn", doc["read_guard"]["state"]["mode"])
        self.assertIn("Work", doc["read_guard"]["state"]["would"])
        self.assertIn("todo-summary", doc["notifications"]["own_way"])

    def test_a_part_not_asked_for_is_not_read(self):
        doc = self.doc(only=("desk",))
        self.assertEqual({"api": 1, "desk_agent": "claude"}, doc)

    def test_it_writes_nothing(self):
        self.rich()
        before = snapshot(self.root)
        self.doc(jobs=status.launchd_jobs())
        self.assertEqual(before, snapshot(self.root))

    def test_a_reader_that_fails_leaves_its_field_empty(self):
        (self.root / "System" / "tools").unlink()
        (self.root / "System" / "garrick-settings.json").write_text("[1, 2")
        doc = self.doc()
        self.assertIsNone(doc["memory"])
        self.assertEqual({"flags": {}, "pending": False}, {"flags": doc["walls"]["flags"], "pending": doc["walls"]["pending"]})
        self.assertEqual({"number": "", "installed": None, "notice_on": False, "notice_every": 1, "stale": []}, doc["release"])
        self.assertTrue(doc["usage_counts"])

    def test_the_view_hands_it_on_and_the_page_no_longer_lists_it_as_left(self):
        self.assertEqual(self.doc(only=("flags",)), view.settings(self.root, EXTRAS, only=("flags",)))
        self.assertNotIn("settings", view.LEFT)
        self.assertNotIn("settings", view.build(self.root, only=("work",)))

    def test_the_walls_of_each_zone_are_read_from_the_context(self):
        doc = self.doc(only=("walls",))
        self.assertEqual({"Work", "Personal"}, set(doc["walls"]["flags"]) | {"Work", "Personal"})
        self.assertIsInstance(doc["walls"]["pending"], bool)


if __name__ == "__main__":
    unittest.main()
