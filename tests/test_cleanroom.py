"""Clean-room check: no real name from the author's own work appears in the repository.

The names themselves never live in the repository, because a list of them would be
the leak. Put them one per line in `.cleanroom` at the repository root (gitignored),
or comma-separated in the GARRICK_CLEANROOM_NAMES environment variable. With neither,
the test is skipped.

Because `.cleanroom` is gitignored it exists only where somebody put it, which is
the primary working tree. A linked worktree has a root of its own and no copy of
the file, so the list is looked for beside the common git directory as well: that
directory is the primary tree's `.git`, and the list sits beside it. A tree that
can see a list and cannot read it fails rather than skipping, since skipping there
runs the suite with the one check that protects the clean-room rule switched off.
`tests/test_cleanroom_worktree.py` holds both of those against a repository it
builds itself.
"""
import os
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def listings():
    """Where a list may sit, nearest first: this working tree's root, then the
    primary working tree's. The second is the parent of the common git directory,
    which outside a linked worktree is this tree's own root, so the two collapse
    into one. A path that does not exist stays in the list, so that a list which
    exists and cannot be read can be told from one that was never there."""
    found = [ROOT / ".cleanroom"]
    try:
        common = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=str(ROOT),
                                capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        common = ""  # not a repository, or no git here: nothing else to look at
    if common:
        # Relative in the primary tree (".git"), absolute in a linked worktree.
        found.append((ROOT / common).resolve().parent / ".cleanroom")
    out = []
    for path in found:
        if path not in out:
            out.append(path)
    return out


def names():
    """(the names to look for, the lists that exist but could not be read)."""
    found = [n.strip() for n in os.environ.get("GARRICK_CLEANROOM_NAMES", "").split(",")]
    unreadable = []
    for listing in listings():
        try:
            text = listing.read_text(encoding="utf-8")
        except FileNotFoundError:
            continue
        except (OSError, UnicodeDecodeError):
            unreadable.append(listing)
            continue
        found += [l.strip() for l in text.splitlines()
                  if l.strip() and not l.startswith("#")]
    return [n for n in found if n], unreadable


class CleanRoomTest(unittest.TestCase):
    def test_no_real_names(self):
        wanted, unreadable = names()
        if unreadable:
            # Which tree, never the path: a path names the machine that holds the list.
            where = ", ".join("this working tree" if l.parent == ROOT
                              else "the primary working tree" for l in unreadable)
            self.fail("a .cleanroom list exists but could not be read (" + where +
                      "), so this run would scan with part of the list missing")
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
