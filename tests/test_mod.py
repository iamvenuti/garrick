"""The Claude Code mod in extras/mods/: it validates and its own tests pass.

Both need Claude Code's `claude` command. Without it the test is skipped; CI
installs the version the mod's README names as tested.
"""
import shutil
import subprocess
import unittest
from pathlib import Path

MODS = Path(__file__).resolve().parent.parent / "extras" / "mods"


@unittest.skipUnless(shutil.which("claude"), "claude is not installed")
class ModTest(unittest.TestCase):
    def run_claude(self, *args):
        done = subprocess.run(["claude", "plugin", *args, "garrick-band"], cwd=MODS,
                              capture_output=True, text=True, timeout=300)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_validates(self):
        self.run_claude("validate")

    def test_its_tests_pass(self):
        self.run_claude("test")


if __name__ == "__main__":
    unittest.main()
