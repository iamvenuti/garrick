"""Explore draws what the zone's history holds (#399): folders the zone's git
ignores, and nested repositories, stay off the graph."""
from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import project_hub, write  # noqa: E402
from test_status import StatusCase, graph_data, status  # noqa: E402


def git(folder, *args):
    subprocess.run(["git", "-C", str(folder)] + list(args), check=True, capture_output=True)


class TestGraphIgnored(StatusCase):
    def setUp(self):
        super().setUp()
        self.work = self.root / "Zones" / "Work"
        git(self.work, "init", "-q")

    def names(self):
        return [n["n"] for n in graph_data(self.page())["nodes"]]

    def copy_in(self, folder, hub="Harbour Copy"):
        write(folder / (hub + ".md"), project_hub("Work", hub))

    def test_ignored_repo_and_worktrees_are_not_drawn(self):
        project = self.work / "Acme Review"
        for name in ("Repo", "Repo-1", "Repo-2"):
            self.copy_in(project / name, "Copy " + name)
        before = graph_data(self.page())
        self.assertIn("Copy Repo", [n["n"] for n in before["nodes"]])
        (self.work / ".gitignore").write_text("Repo/\nRepo-*/\n")
        after = graph_data(self.page())
        self.assertEqual(len(before["nodes"]) - 3, len(after["nodes"]))
        self.assertFalse([n for n in after["nodes"] if n["n"].startswith("Copy ")])

    def test_a_nested_repository_the_zone_does_not_ignore_is_not_drawn(self):
        self.copy_in(self.work / "Acme Review" / "Code", "Inside Folder")
        git(self.work / "Acme Review" / "Code", "init", "-q")
        self.copy_in(self.work / "Acme Review" / "Tree", "Inside File")
        (self.work / "Acme Review" / "Tree" / ".git").write_text("gitdir: /elsewhere\n")      # a worktree's
        self.copy_in(self.work / "Acme Review" / "Plain", "Plain Folder")
        names = self.names()
        self.assertNotIn("Inside Folder", names)
        self.assertNotIn("Inside File", names)
        self.assertIn("Plain Folder", names)

    def test_a_projects_archive_and_raw_stay(self):
        write(self.work / "Archive" / "Archive.md", project_hub("Work", "Archive"))
        write(self.work / "raw" / "raw.md", project_hub("Work", "raw"))
        (self.work / ".gitignore").write_text("Repo/\n")
        names = self.names()
        self.assertIn("Archive", names)
        self.assertIn("raw", names)

    def test_a_zone_that_is_not_a_repository_still_builds(self):
        other = self.root / "Zones" / "Personal"
        self.copy_in(other / "Nest" / "Repo", "Personal Copy")
        self.copy_in(other / "Nest" / "Own", "Personal Own")
        git(other / "Nest" / "Own", "init", "-q")
        names = self.names()
        self.assertIn("Personal Copy", names)         # no repository of its own to ask: today's walk
        self.assertNotIn("Personal Own", names)

    def test_git_missing_still_builds(self):
        self.copy_in(self.work / "Acme Review" / "Repo", "Copy Repo")
        (self.work / ".gitignore").write_text("Repo/\n")
        with mock.patch.object(status.subprocess, "run", side_effect=FileNotFoundError("git")):
            self.assertIn("Copy Repo", self.names())

    def test_one_ignore_listing_per_zone_and_no_slower_without_ignored_folders(self):
        for i in range(60):
            write(self.work / "Acme Review" / ("Notes%d" % i) / "Note.md", "# Note %d\n" % i)
        calls = []
        real = subprocess.run

        def counting(cmd, *a, **kw):
            calls.append(list(cmd))
            return real(cmd, *a, **kw)

        def timed(patch):
            best = None
            for _ in range(3):
                start = time.perf_counter()
                with patch:
                    graph_data(self.page())
                best = min(best or 1e9, time.perf_counter() - start)
            return best

        old = timed(mock.patch.object(status, "git_ignored", return_value=set()))      # the walk as it was
        with mock.patch.object(status.subprocess, "run", counting):
            new = timed(contextlib.nullcontext())
        asked = [c for c in calls if "--ignored" in c]
        repos = [z for z in (self.root / "Zones").iterdir() if (z / ".git").exists()]
        self.assertEqual(3 * len(repos), len(asked))   # three builds, one listing per repository of a zone in each
        self.assertEqual({str(z) for z in repos}, {c[2] for c in asked})
        self.assertLess(new, old * 3 + 1.0)

    def test_an_ignored_folder_is_not_entered(self):
        project = self.work / "Acme Review"
        self.copy_in(project / "Repo" / "deep" / "er", "Deep Copy")
        (self.work / ".gitignore").write_text("Repo/\n")
        entered = []
        real = status.walked

        def watching(root, folder, name, in_zone):
            entered.append(Path(folder).relative_to(root).as_posix())
            return real(root, folder, name, in_zone)

        with mock.patch.object(status, "walked", watching):
            names = self.names()
        self.assertNotIn("Deep Copy", names)
        self.assertEqual([], [f for f in entered if f.startswith("Acme Review/Repo")])   # never listed, let alone entered

    def test_a_path_git_cannot_encode_does_not_stop_the_build(self):
        raw = b"Acme Review/Bad\xff name/\0Acme Review/Repo/\0Acme Review/x.log\0"
        done = subprocess.CompletedProcess([], 0, stdout=raw, stderr=b"")
        with mock.patch.object(status.subprocess, "run", return_value=done):
            got = status.git_ignored(self.work)
        self.assertEqual({"Acme Review/Bad\udcff name", "Acme Review/Repo"}, got)
        self.assertIn(os.fsdecode(b"Acme Review/Bad\xff name"), got)        # as os.walk names it
        try:
            odd = self.work / "Acme Review" / os.fsdecode(b"Odd\xff")
            self.copy_in(odd, "Odd Copy")
        except OSError:
            return                                     # this file system takes no such name
        (self.work / ".gitignore").write_text("Repo/\n")
        self.assertIn("Odd Copy", self.names())


if __name__ == "__main__":
    unittest.main()
