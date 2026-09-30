"""Clean-room check: no real name from the author's own work appears in the repository.

The names themselves never live in the repository, because a list of them would be
the leak. Put them one per line in `.cleanroom` at the repository root (gitignored),
or comma-separated in the GARRICK_CLEANROOM_NAMES environment variable. With neither,
the test is skipped.
"""
import os
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def names():
    found = [n.strip() for n in os.environ.get("GARRICK_CLEANROOM_NAMES", "").split(",")]
    listing = ROOT / ".cleanroom"
    if listing.exists():
        found += [l.strip() for l in listing.read_text(encoding="utf-8").splitlines()
                  if l.strip() and not l.startswith("#")]
    return [n for n in found if n]


class CleanRoomTest(unittest.TestCase):
    def test_no_real_names(self):
        wanted = names()
        if not wanted:
            self.skipTest("no .cleanroom file or GARRICK_CLEANROOM_NAMES")
        files = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"],
                               cwd=ROOT, capture_output=True, text=True, check=True).stdout.split("\n")
        hits = []
        for rel in filter(None, files):
            path = ROOT / rel
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8").lower()
            except UnicodeDecodeError:
                continue
            # Report the name's position in the list, never the name: CI logs are public.
            hits += [f"{rel}: name {i} of the list" for i, n in enumerate(wanted, 1)
                     if n.lower() in text]
        self.assertEqual(hits, [], "real names found:\n" + "\n".join(hits))


if __name__ == "__main__":
    unittest.main()
