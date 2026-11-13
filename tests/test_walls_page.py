"""The Context queue's wall question: page_action.py's `walls-look` and `walls-allow` (#548, #550).

    cd tests && python3 -m unittest test_walls_page

A wall false alarm in a fictional workspace (Acme, a Garden project of the Personal zone): the page asks which file the finding is
about, reads the words both files share into its reply, and, only from the app's bridge, writes one allowance after that.
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

import fixtures  # noqa: E402
from fixtures import GIT_ENV, build_workspace, git, write  # noqa: E402

import importlib.util  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location("garrick_page_action", REPO / "extras" / "status" / "page_action.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pa = _load()

SENTENCE = "the harvest plan for the whole autumn season stays with the garden club members"
COPY = "Zones/Work/Acme Review/Threads/Pricing/Copy.md"
SOURCE = "Zones/Personal/Garden/Notes.md"
LEDGER = "System/walls-allowed.json"


class WallsPageCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name).resolve()
        self.root = base / "Workspace"
        self.jobs = base / "jobs"
        env = mock.patch.dict(os.environ, dict(GIT_ENV, GARRICK_JOBS_DIR=str(self.jobs)))
        env.start()
        self.addCleanup(env.stop)
        build_workspace(self.root)
        shutil.copytree(REPO / "template" / "System" / "tools", self.root / "System" / "tools", dirs_exist_ok=True)
        write(self.root / SOURCE, "# Notes\n\n%s\n" % SENTENCE)
        write(self.root / COPY, "# Copy\n\nFrom the club: %s, and nothing else.\n" % SENTENCE)
        for zone in ("Work", "Personal"):
            shutil.rmtree(self.root / "Zones" / zone / ".git")
            git(self.root / "Zones" / zone, "init", "-q")
        git(self.root, "init", "-q")
        write(self.root / ".gitignore", "Zones/\nWikis/\nSystem/tools/\n")
        git(self.root, "add", ".gitignore")
        git(self.root, "commit", "-q", "-m", "start")

    def send(self, req, via=None):
        """One request as page_action.py's own command reads it: JSON on stdin, the reply on stdout. The audit log is written."""
        argv = ["--workspace", str(self.root)] + (["--via", via] if via else [])
        out = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(req))), mock.patch.object(sys, "stdout", out):
            pa.main(argv)
        return json.loads(out.getvalue())

    def findings(self, path=COPY):
        got = self.send({"verb": "walls-look", "place": "Zones/Work", "path": path})
        self.assertTrue(got["ok"], got)
        return got

    def wording(self):
        return next(f for f in self.findings()["findings"] if f["rule"] == "wording")

    def look(self, **more):
        f = self.wording()
        return self.send(dict({"verb": "walls-look", "place": "Zones/Work", "path": COPY, "id": f["id"]}, **more))

    def ledger(self):
        path = self.root / LEDGER
        return json.loads(path.read_text(encoding="utf-8"))["allowed"] if path.exists() else []

    def head(self):
        return git(self.root, "rev-parse", "HEAD").strip()

    def log_text(self):
        path = self.jobs / "page-actions.log"
        return path.read_text(encoding="utf-8") if path.exists() else ""


class TestLook(WallsPageCase):
    def test_it_names_the_file_and_the_other_zone(self):
        got = self.findings()
        f = [f for f in got["findings"] if f["path"] == COPY][0]
        self.assertEqual((COPY, "wording"), (f["path"], f["rule"]))
        self.assertIn("points into private material from Personal", f["sentence"])
        self.assertIn("“Copy” in Work", f["sentence"])
        self.assertRegex(f["id"], r"^[0-9a-f]{10}$")

    def test_a_place_wide_look_finds_the_same_finding_by_its_key(self):
        got = self.send({"verb": "walls-look", "place": "Zones/Work"})
        self.assertTrue(got["ok"], got)
        self.assertIn(COPY, [f["path"] for f in got["findings"]])
        self.assertTrue(all(f["path"].startswith("Zones/Work/") for f in got["findings"]))
        fq = pa.finding_queue()
        self.assertEqual(fq.later_key("wall", COPY), [f for f in got["findings"] if f["path"] == COPY][0]["key"])
        there = self.send({"verb": "walls-look", "place": "Zones/Personal"})["findings"]
        self.assertTrue(all(f["path"].startswith("Zones/Personal/") for f in there))                         # a place holds its own findings only

    def test_it_returns_the_shared_run_and_words_around_it_from_both_files(self):
        got = self.look()
        self.assertTrue(got["ok"], got)
        self.assertEqual(SENTENCE, got["a"]["run"].lower())
        self.assertEqual(SENTENCE, got["b"]["run"].lower())
        self.assertEqual("Copy From the club: ", got["a"]["before"])
        self.assertEqual(", and nothing else", got["a"]["after"])
        self.assertEqual("Notes ", got["b"]["before"])
        self.assertEqual("In “Copy”", got["a"]["where"])
        self.assertEqual("In “Notes”", got["b"]["where"])
        self.assertRegex(got["blob"], r"^[0-9a-f]{40}$")

    def test_the_texts_are_in_the_reply_and_nowhere_else(self):
        self.look()
        self.assertNotIn("harvest", self.log_text())                                   # the audit log: the request and the sentence
        self.assertFalse((self.jobs / "operations.jsonl").exists())                    # no journal record
        self.assertFalse((self.root / LEDGER).exists())                                # nothing was written
        for path in self.root.rglob("*"):
            if path.is_file() and ".git" not in path.parts and path.suffix in (".json", ".log") and path != self.root / COPY:
                self.assertNotIn("harvest", path.read_text(encoding="utf-8", errors="ignore"), str(path))
        for path in self.jobs.rglob("*"):
            if path.is_file():
                self.assertNotIn("harvest", path.read_text(encoding="utf-8", errors="ignore"), str(path))
        self.assertIn("walls-look", self.log_text())                                   # the request itself is logged, as every one is

    def test_only_the_apps_bridge_may_ask(self):
        f = self.wording()
        req = {"verb": "walls-look", "place": "Zones/Work", "path": COPY, "id": f["id"]}
        for via in ("ask", "session"):
            got = self.send(req, via)
            self.assertFalse(got["ok"], via)
            self.assertNotIn("run", got)
            self.assertNotIn("harvest", json.dumps(got))
        self.assertTrue(self.send(req, "page")["ok"])
        self.assertNotIn("walls-look", pa.CLI_FIELDS)                                  # the command line has no verb for it
        with self.assertRaises(SystemExit):
            pa.command_parser().parse_args(["walls-look"])

    def test_a_file_outside_the_place_is_refused(self):
        got = self.send({"verb": "walls-look", "place": "Zones/Personal", "path": COPY})
        self.assertFalse(got["ok"])
        self.assertIn("not in the place", got["say"])
        for place in ("Zones", "Zones/Work/Acme Review", "../Zones/Work", "Zones/Nowhere", "System"):
            self.assertFalse(self.send({"verb": "walls-look", "place": place, "path": COPY})["ok"], place)
        for path in ("/etc/hosts", "../x.md", "Zones/Work/Acme Review/Threads/Pricing", "Zones/Work/Nothing.md"):
            self.assertFalse(self.send({"verb": "walls-look", "place": "Zones/Work", "path": path})["ok"], path)

    def test_an_id_the_check_does_not_give_is_refused(self):
        got = self.send({"verb": "walls-look", "place": "Zones/Work", "path": COPY, "id": "0123456789"})
        self.assertFalse(got["ok"])
        self.assertIn("does not give that finding", got["say"])
        self.assertFalse(self.send({"verb": "walls-look", "place": "Zones/Work", "path": COPY, "id": "nope"})["ok"])
        self.assertFalse(self.send({"verb": "walls-look", "place": "Zones/Work", "id": self.wording()["id"]})["ok"])   # an id needs its file

    def test_a_file_with_no_finding_shows_nothing(self):
        got = self.send({"verb": "walls-look", "place": "Zones/Work", "path": "Zones/Work/Acme Review/Acme Review.md"})
        self.assertTrue(got["ok"])
        self.assertEqual([], got["findings"])
        self.assertIn("finds nothing", got["say"])

    def test_the_request_cannot_name_the_other_file_or_the_words(self):
        f = self.wording()
        for extra in ({"other": SOURCE}, {"run": "x"}, {"words": "x"}):
            got = self.send({"verb": "walls-look", "place": "Zones/Work", "path": COPY, "id": f["id"], **extra})
            self.assertFalse(got["ok"], extra)
            self.assertNotIn("harvest", json.dumps(got))


class TestAllow(WallsPageCase):
    def allow(self, via=None, **more):
        look = self.look()
        req = {"verb": "walls-allow", "path": COPY, "id": self.wording()["id"], "blob": look["blob"]}
        req.update(more)
        return self.send(req, via), look

    def test_after_a_look_it_writes_one_entry_by_page_and_commits_the_ledger_alone(self):
        before = self.head()
        got, look = self.allow()
        self.assertTrue(got["ok"], got)
        entries = self.ledger()
        self.assertEqual(1, len(entries))
        self.assertEqual((COPY, "page", "wording", look["blob"]), (entries[0]["path"], entries[0]["by"], entries[0]["rule"], entries[0]["blob"]))
        self.assertNotEqual(before, self.head())
        self.assertEqual([LEDGER], git(self.root, "show", "--name-only", "--format=", "HEAD").split())
        self.assertEqual("", git(self.root, "status", "--porcelain", "--untracked-files=no").strip())
        self.assertNotIn("harvest", json.dumps(entries))                               # the ledger names no token

    def test_the_wall_check_then_lets_that_file_through_until_it_changes(self):
        import check
        self.assertTrue(any(f.path == COPY for f in check.run_checks(self.root, walls_only=True)))
        got, _ = self.allow()
        self.assertTrue(got["ok"], got)
        self.assertFalse(any(f.path == COPY for f in check.run_checks(self.root, walls_only=True)))
        write(self.root / COPY, "# Copy\n\nChanged: %s, and more.\n" % SENTENCE)
        self.assertTrue(any(f.path == COPY for f in check.run_checks(self.root, walls_only=True)))

    def test_the_ask_box_and_a_session_are_refused_and_write_nothing(self):
        before = self.head()
        for via in ("ask", "session"):
            got, _ = self.allow(via)
            self.assertFalse(got["ok"], via)
            self.assertEqual([], self.ledger(), via)
            self.assertEqual(before, self.head(), via)
            self.assertFalse((self.root / LEDGER).exists(), via)
        self.assertNotIn("walls-allow", pa.CLI_FIELDS)
        with self.assertRaises(SystemExit):
            pa.command_parser().parse_args(["walls-allow"])

    def test_a_blob_that_is_not_the_files_now_is_refused_and_writes_nothing(self):
        before = self.head()
        got, look = self.allow(blob="a" * 40)
        self.assertFalse(got["ok"])
        self.assertIn("changed since you looked", got["say"])
        write(self.root / COPY, "# Copy\n\nChanged after the look: %s.\n" % SENTENCE)      # and a file that changed after the look
        got = self.send({"verb": "walls-allow", "path": COPY, "id": self.wording()["id"], "blob": look["blob"]})
        self.assertFalse(got["ok"])
        self.assertEqual([], self.ledger())
        self.assertEqual(before, self.head())

    def test_a_malformed_request_is_refused(self):
        f = self.wording()
        for req in ({"path": COPY, "id": f["id"]}, {"path": COPY, "id": f["id"], "blob": "xyz"}, {"path": COPY, "id": "nope", "blob": "a" * 40},
                    {"path": "../x.md", "id": f["id"], "blob": "a" * 40}, {"path": COPY, "id": "0123456789", "blob": "a" * 40},
                    {"path": COPY, "id": f["id"], "blob": "a" * 40, "by": "terminal"}):
            self.assertFalse(self.send(dict(req, verb="walls-allow"))["ok"], req)
        self.assertEqual([], self.ledger())

    def test_the_terminals_rule_is_unchanged(self):
        import garrick_lib
        self.assertFalse(garrick_lib.allow_may_write("page"))
        self.assertFalse(garrick_lib.allow_may_write("assistant"))

    def test_no_skill_doc_or_ask_tool_names_the_verb(self):
        for folder in ("template/System/skills", "docs", "template/System/garrick-docs"):
            for path in (REPO / folder).rglob("*") if (REPO / folder).is_dir() else []:
                if path.is_file() and path.suffix in (".md", ".py", ".json", ".txt"):
                    self.assertIsNone(re.search(r"walls-allow(?!ed)", path.read_text(encoding="utf-8", errors="ignore")), str(path))
        for path in (REPO / "extras" / "status").glob("ask*"):
            self.assertIsNone(re.search(r"walls-allow(?!ed)", path.read_text(encoding="utf-8", errors="ignore")), str(path))


class OtherFileNameTest(unittest.TestCase):
    """The other file of a wording finding, read from check.py's message: a path or a stem may hold spaces and commas."""

    def name(self, message):
        m = pa.WALL_OTHER_PATH_RE.search(message) or pa.WALL_OTHER_FROM_RE.search(message)
        return m.group(1) if m else None

    def test_a_project_path_with_spaces(self):
        self.assertEqual(self.name("repeats wording from Zones/Personal/Garden Club/Threads/Seed Swap/Seed Swap.md, in project "
                                   "Garden Club of Personal; that zone is walled and this file is in Work"),
                         "Zones/Personal/Garden Club/Threads/Seed Swap/Seed Swap.md")

    def test_a_path_with_a_comma_and_more_files(self):
        self.assertEqual(self.name("repeats wording from Zones/Personal/Cedar, Maple/Notes one.md and 2 more of its files, in project "
                                   "Cedar, Maple of Personal; that zone is walled"), "Zones/Personal/Cedar, Maple/Notes one.md")

    def test_a_meeting_stem_with_spaces(self):
        self.assertEqual(self.name("repeats wording from meeting 261101 - Seed swap review, a meeting of Personal; that zone is walled"),
                         "261101 - Seed swap review")
        self.assertEqual(self.name("repeats wording from person page Jo Cedar, a person page that names no zone, so nothing says"),
                         "Jo Cedar")

    def test_the_files_are_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            write(ws / "Zones/Personal/Garden Club/Notes one.md", "x")
            write(ws / "Wikis/Meetings/wiki/meetings/261101 - Seed swap review.md", "x")
            got = pa.walls_other_files(ws, "repeats wording from Zones/Personal/Garden Club/Notes one.md, in project Garden Club of Personal; x")
            self.assertEqual([p.name for p in got], ["Notes one.md"])
            got = pa.walls_other_files(ws, "repeats wording from meeting 261101 - Seed swap review, a meeting of Personal; x")
            self.assertEqual([p.name for p in got], ["261101 - Seed swap review.md"])


if __name__ == "__main__":
    unittest.main()
