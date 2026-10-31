"""The status page's Todo card reads a zone as the check reads it (#171).

A zone may keep a Garrick checkout inside a project, a JavaScript build with
its `node_modules/`, and folders the user excluded in Obsidian. None of their
checkboxes are the zone's actions: the card counts the lines of Todo.md and
of the zone's own notes, and nothing else.

    python3 -m unittest tests.test_todo_skips

Invented parties only, as in fixtures.py.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import build_workspace, write  # noqa: E402

import check  # noqa: E402  (fixtures puts the tools folder on sys.path)
import garrick_lib  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


status = _load("garrick_status_skips", REPO / "extras" / "status" / "status.py")
todo_lines = status.todo_lines()

TODO = "# Work: open actions\n\n## Inbox\n\n- [ ] [[Pricing]]: send the sheet\n- [ ] Dana: confirm volumes\n\n## Done\n"
CHECKLIST = "# A package\n\n## Before you publish\n\n- [ ] run the build\n- [ ] bump the version\n"


def checkout(top: Path, cloned: bool) -> None:
    """A Garrick checkout with the files that read as actions: the demo's
    Todo lists and the pull request template. A clone has a .git, a release
    ZIP unpacked has none."""
    write(top / "VERSION", "commit: 0000000\n")
    write(top / "install.py", "# The installer.\n")
    write(top / "template" / "AGENTS.md", "# Workspace\n")
    write(top / "examples" / "demo" / "content" / "Zones" / "Work" / "Todo.md", "## Inbox\n\n- [ ] [[Demo]]: a demo line\n")
    write(top / ".github" / "pull_request_template.md", "- [ ] The suite passes\n")
    if cloned:
        (top / ".git").mkdir(parents=True)


class TodoCardSkipsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "Workspace"
        build_workspace(self.root)
        self.zone = self.root / "Zones" / "Work"
        acme = self.zone / "Acme Review"
        write(self.zone / "Todo.md", TODO)
        write(acme / "Threads" / "Pricing" / "Notes.md", "# Notes\n\n- [ ] check the clause\n")
        checkout(acme / "Tooling" / "garrick", cloned=False)
        checkout(acme / "Tooling" / "garrick-clone", cloned=True)
        write(acme / "Site" / "node_modules" / "left-pad" / "README.md", CHECKLIST)
        write(acme / "Site" / "dist" / "README.md", CHECKLIST)
        write(acme / "Scratch" / "Ideas.md", "- [ ] an idea Obsidian hides\n")
        write(acme / "Threads" / "Pricing" / "Drafts" / "Draft.md", "- [ ] a draft line Obsidian hides\n")
        write(self.zone / ".obsidian" / "app.json", json.dumps({"userIgnoreFilters": ["Acme Review/Scratch", "/Drafts/"]}))

    def texts(self):
        return sorted(t["text"] for t in todo_lines.tasks(str(self.zone)))

    def test_only_the_list_and_the_zones_own_notes_count(self):
        self.assertEqual(["Dana: confirm volumes", "check the clause", "send the sheet"], self.texts())

    def test_the_card_counts_them_alone(self):
        card = next(z for z in status.todo_list(self.root, status.Links(self.root), dt.date(2026, 3, 2)) if z["zone"] == "Work")
        self.assertEqual(3, card["open"])
        self.assertEqual(3, card["undated"])
        self.assertEqual(["Inbox", "In thread notes"], [g for g, _ in card["groups"]])
        self.assertEqual(["Acme Review/Threads/Pricing/Notes.md"],
                         sorted({r["file"].replace("\\", "/") for _, rows in card["groups"] for r in rows} - {"Todo.md"}))

    def test_an_excluded_todo_md_still_counts(self):
        write(self.zone / ".obsidian" / "app.json", json.dumps({"userIgnoreFilters": ["/Todo/"]}))
        self.assertIn("Dana: confirm volumes", self.texts())

    def test_the_check_and_the_card_walk_alike(self):
        self.assertIs(check.live_files, garrick_lib.live_files)
        self.assertTrue(callable(todo_lines.walk_lib(self.root).live_files))
        ws = check.discover(self.root)
        read = {p for p, _ in check.zone_notes(ws, self.zone)}
        self.assertFalse([p for p in read if "node_modules" in p.parts or "dist" in p.parts or "garrick" in p.parts
                          or "garrick-clone" in p.parts])
        self.assertIn(self.zone / "Acme Review" / "Threads" / "Pricing" / "Notes.md", read)

    def test_a_workspace_lib_older_than_the_shared_walk_still_reads(self):
        with mock.patch.object(todo_lines, "walk_lib", lambda ws: None):
            texts = self.texts()
        self.assertIn("check the clause", texts)
        self.assertNotIn("an idea Obsidian hides", texts)                       # the vault's filters hold regardless

    def test_the_graph_reads_the_same_filters(self):
        filters = status.vault_filters(self.zone)
        self.assertTrue(status.ignored("Acme Review/Scratch/Ideas.md", filters))
        self.assertTrue(status.ignored("Acme Review/Threads/Pricing/Drafts/Draft.md", filters))
        self.assertFalse(status.ignored("Acme Review/Threads/Pricing/Notes.md", filters))
        self.assertEqual(self.zone, status.vault_of(self.root, self.zone / "Acme Review"))


if __name__ == "__main__":
    unittest.main()
