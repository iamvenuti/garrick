"""#670: one reader of a hook path, written four times because the hooks run from a kept download and stay self-contained.
`settings_guard.hook_path`, `update.hook_path`, `read_guard.hook_path` and `check.hook_path` (#685) are fed one table of command words and must give one
answer each. A fake HOME and a marker value stand in for this Mac's environment.

    cd tests && python3 -m unittest test_hook_path
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def check_module():
    """template/System/tools/check.py, with garrick_lib beside it on the path, as the check runs (#685: the fourth copy)."""
    tools = str(REPO / "template" / "System" / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import check
    return check


class TestOneReaderThreeCopies(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = str(Path(self._tmp.name).resolve() / "home")
        os.mkdir(self.home)
        env = mock.patch.dict(os.environ, {"HOME": self.home, "GARRICK_MARKER": "marker-value-7f3a"})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("UNSET_VAR", None)
        self.readers = {
            "settings_guard": load("sg_hp", REPO / "extras" / "status" / "settings_guard.py").hook_path,
            "update": load("up_hp", REPO / "update.py").hook_path,
            "read_guard": load("rg_hp", REPO / "extras" / "hooks" / "read_guard.py").hook_path,
            "check": check_module().hook_path,
        }

    def table(self):
        h = self.home
        return [
            ("$HOME/kept/extras/hooks/zone_guard.py", h + "/kept/extras/hooks/zone_guard.py"),
            ("${HOME}/kept/extras/hooks/zone_guard.py", h + "/kept/extras/hooks/zone_guard.py"),
            ("~/kept/extras/hooks/zone_guard.py", h + "/kept/extras/hooks/zone_guard.py"),
            ("/opt/garrick/extras/hooks/zone_guard.py", "/opt/garrick/extras/hooks/zone_guard.py"),
            ("kept/extras/hooks/zone_guard.py", None),
            ("./zone_guard.py", None),
            ("$UNSET_VAR/zone_guard.py", None),
            ("${UNSET_VAR}/zone_guard.py", None),
            ("$GARRICK_MARKER/zone_guard.py", None),
            (h + "/my hooks/zone_guard.py", h + "/my hooks/zone_guard.py"),
            ("python3", None),
            ("--check", None),
            ("", None),
        ]

    def test_the_four_readers_give_one_answer_for_every_word(self):
        for word, want in self.table():
            for name, reader in self.readers.items():
                with self.subTest(word=word, reader=name):
                    self.assertEqual(want, reader(word))

    def test_a_variable_that_is_set_to_a_relative_value_is_still_dropped(self):
        with mock.patch.dict(os.environ, {"GARRICK_REL": "kept/extras"}):
            for name, reader in self.readers.items():
                with self.subTest(reader=name):
                    self.assertIsNone(reader("$GARRICK_REL/hooks/zone_guard.py"))


if __name__ == "__main__":
    unittest.main()
