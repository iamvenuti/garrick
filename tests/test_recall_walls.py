"""Recall (#341): the release review's wall findings.

    cd tests && python3 -m unittest test_recall_walls

Invented names only. Acme Review and Birch Entry stand either side of a wall.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixtures  # noqa: E402
from fixtures import build_workspace, meeting_page, project_hub, thread_note, write  # noqa: E402

import recall  # noqa: E402
import recall_sessions  # noqa: E402

ACME = "Zones/Work/Acme Review"
BIRCH = "Zones/Work/Birch Entry"


class Walls(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = build_workspace(Path(self.tmp.name) / "ws").resolve()
        work = self.root / "Zones" / "Work"
        write(work / "Acme Review" / "Threads" / "Pricing" / "Pricing.md",
              thread_note("Acme Review", "Pricing", "acme", "quokkaplan renewal"))
        write(work / "Birch Entry" / "Threads" / "Market Sizing" / "Market Sizing.md",
              thread_note("Birch Entry", "Market Sizing", "birch", "wombatplan sizing numbers"))
        self.A = str(work / "Acme Review")
        self.B = str(work / "Birch Entry")

    def cli(self, cwd, *args, env=None):
        here = os.getcwd()
        out, err = io.StringIO(), io.StringIO()
        try:
            os.chdir(str(cwd))
            with mock.patch.dict(os.environ, env or {}), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    code = recall.main(["--root", str(self.root)] + list(args))
                except SystemExit as stop:
                    code = stop.code
        finally:
            os.chdir(here)
        return code, out.getvalue(), err.getvalue()

    # -- F4 ---------------------------------------------------------------

    def session(self, name, tool_uses, said):
        folder = Path(self.tmp.name) / "claude" / "proj"
        folder.mkdir(parents=True, exist_ok=True)
        recs = [{"type": "user", "cwd": self.A, "sessionId": name, "timestamp": "2026-09-01T10:00:00Z",
                 "message": {"role": "user", "content": "compare"}},
                {"type": "assistant", "cwd": self.A, "sessionId": name, "timestamp": "2026-09-01T10:01:00Z",
                 "message": {"role": "assistant", "content": tool_uses + [{"type": "text", "text": said}]}}]
        (folder / (name + ".jsonl")).write_text("\n".join(json.dumps(r) for r in recs) + "\n")

    def extract_and_search(self, word):
        recall_sessions.extract_all(self.root, str(Path(self.tmp.name) / "claude"), str(Path(self.tmp.name) / "none"))
        return [h.path for h in recall.search(word, project=ACME, root=self.root, sessions=True)]

    def bash(self, command):
        return [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": command}}]

    def test_read_tool_path_into_another_project_keeps_the_session_out_of_acme(self):
        self.session("r1", [{"type": "tool_use", "id": "t1", "name": "Read",
                             "input": {"file_path": self.B + "/Birch Entry.md"}}], "Birch says readwombat is 9 million.")
        self.assertEqual(self.extract_and_search("readwombat"), [])

    def test_shell_spellings_of_a_sibling_keep_the_session_out_of_acme(self):
        commands = {
            "q": 'cd "../Birch Entry" && cat "Birch Entry.md"',
            "e": "cat ../Birch\\ Entry/Threads/Market\\ Sizing/Market\\ Sizing.md",
            "l": "cat '../birch entry/Birch Entry.md'",
            "g": "cd .. && cd Birch* && cat *.md",
            "d": "cat ../birch-entry/x.md",
        }
        for name, command in commands.items():
            self.session(name, self.bash(command), "%swombat finding." % name)
        for name in commands:
            self.assertEqual(self.extract_and_search(name + "wombat"), [], name)

    def test_other_tool_inputs_are_scanned_not_rendered(self):
        self.session("gr", [{"type": "tool_use", "id": "t1", "name": "Grep",
                             "input": {"pattern": "budget", "path": "../Birch Entry"}}], "grepwombat finding.")
        self.assertEqual(self.extract_and_search("grepwombat"), [])
        for p in self.root.rglob(".sessions/*.md"):
            self.assertNotIn("budget", p.read_text())

    def test_a_way_up_that_names_no_place_makes_the_session_root_only(self):
        self.session("up", self.bash("cd .. && ls"), "upwombat finding.")
        self.assertEqual(self.extract_and_search("upwombat"), [])

    def test_a_session_that_stays_in_its_project_is_still_found(self):
        self.session("own", self.bash("cat Threads/Pricing/Pricing.md"), "ownwombat finding.")
        self.assertEqual(len(self.extract_and_search("ownwombat")), 1)

    # -- F2 ---------------------------------------------------------------

    def test_a_zone_top_marker_reads_no_project_by_changing_folder(self):
        zone = self.root / "Zones" / "Work"
        for folder in (self.B, self.A):
            _, out, err = self.cli(folder, "search", "wombatplan quokkaplan", env={"CLAUDE_PROJECT_DIR": str(zone)})
            self.assertIn("not a place Recall reads from", err)
            self.assertTrue(out.startswith("0 results"), out)
        self.assertIs(recall.cwd_project.__name__ and None, None)

    def test_a_project_marker_still_reads_its_project(self):
        code, out, _ = self.cli(self.A, "search", "quokkaplan", env={"CLAUDE_PROJECT_DIR": self.A})
        self.assertEqual(code, 0)
        self.assertIn("quokkaplan", out)

    # -- F3 ---------------------------------------------------------------

    def test_a_raw_stem_two_files_share_has_no_owner(self):
        meetings = self.root / "Wikis" / "Meetings"
        write(meetings / "wiki" / "sources" / "260310-acme-kickoff.md",
              meeting_page("Work", "[acme]", "Acme kick-off").replace("---\n\n#", "raw: raw/260310-acme-kickoff.txt\n---\n\n#", 1))
        write(meetings / "raw" / "260310-acme-kickoff.txt", "Dana: acmerawfact.\n")
        write(meetings / "raw" / "birch" / "260310-acme-kickoff.txt", "Theo: secretwombatraw budget.\n")
        hits = recall.search("secretwombatraw", project=self.A, root=self.root)
        self.assertEqual(hits, [])
        self.assertEqual(recall.search("acmerawfact", project=self.A, root=self.root), [])

    def test_a_unique_raw_stem_is_still_served(self):
        meetings = self.root / "Wikis" / "Meetings"
        write(meetings / "wiki" / "sources" / "260311-acme-call.md",
              meeting_page("Work", "[acme]", "Acme call").replace("---\n\n#", "raw: raw/260311-acme-call.txt\n---\n\n#", 1))
        write(meetings / "raw" / "260311-acme-call.txt", "Dana: uniquerawfact here.\n")
        self.assertEqual(len(recall.search("uniquerawfact", project=self.A, root=self.root)), 1)

    # -- F1 ---------------------------------------------------------------

    def test_no_allow_rule_matches_an_environment_prefixed_command(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("garrick_install", Path(__file__).resolve().parent.parent / "install.py")
        install = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(install)
        for rule in install.claude_allow_rules(["Work"]):
            if "recall.py" in rule:
                self.assertTrue(rule.startswith("Bash(python3 "), rule)


if __name__ == "__main__":
    unittest.main()
