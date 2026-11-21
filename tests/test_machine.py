"""machine.py: the role of this machine, from ~/.config/garrick/machine.json.

    python3 -m unittest test_machine
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

import fixtures  # noqa: E402,F401  (puts the tools folder on sys.path)
import machine  # noqa: E402


class FakeHome(unittest.TestCase):
    """A fake HOME, so that no test reads or writes this Mac's own file."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name).resolve()
        patch = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        patch.start()
        self.addCleanup(patch.stop)

    def put(self, text):
        target = self.home / ".config" / "garrick" / "machine.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return target


class RoleTest(FakeHome):
    def test_no_file_is_solo(self):
        self.assertEqual(machine.role(), "solo")
        self.assertEqual(machine.read(), {"role": "solo", "name": "", "server": "", "workspace": "", "peers": []})

    def test_the_three_roles(self):
        for role in ("solo", "server", "roaming"):
            self.put(json.dumps({"role": role, "name": "laptop", "server": "mini"}))
            self.assertEqual(machine.role(), role)
        self.assertEqual(machine.name(), "laptop")
        self.assertEqual(machine.read()["server"], "mini")

    def test_an_unknown_role_is_solo(self):
        self.put(json.dumps({"role": "primary", "name": "x"}))
        self.assertEqual(machine.role(), "solo")

    def test_a_file_that_cannot_be_read_is_solo(self):
        for text in ("", "{not json", "[]", '"roaming"', json.dumps({"role": 7})):
            self.put(text)
            self.assertEqual(machine.role(), "solo", text)

    def test_the_role_is_read_when_it_is_asked(self):
        self.assertEqual(machine.role(), "solo")
        self.put(json.dumps({"role": "roaming"}))
        self.assertEqual(machine.role(), "roaming")

    def test_known_names(self):
        self.put(json.dumps({"role": "server", "name": "Mini", "server": "Laptop", "peers": ["Tablet", 3, " "]}))
        self.assertEqual(machine.known_names(), {"mini", "laptop", "tablet"})


class SetTest(FakeHome):
    def test_set_writes_the_file_outside_the_workspace(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(machine.main(["set", "--role", "roaming", "--name", "laptop", "--server", "mini"]), 0)
        self.assertTrue((self.home / ".config" / "garrick" / "machine.json").is_file())
        self.assertEqual(machine.role(), "roaming")
        self.assertEqual(machine.name(), "laptop")

    def test_set_refuses_an_unknown_role(self):
        with self.assertRaises(SystemExit):
            with redirect_stdout(io.StringIO()), mock.patch("sys.stderr", io.StringIO()):
                machine.main(["set", "--role", "primary"])
        self.assertFalse((self.home / ".config" / "garrick" / "machine.json").exists())

    def test_the_default_prints_the_role(self):
        out = io.StringIO()
        with redirect_stdout(out):
            machine.main([])
        self.assertEqual(out.getvalue().strip(), "solo")


if __name__ == "__main__":
    unittest.main()
