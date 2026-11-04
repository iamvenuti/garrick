"""Recall (#341): a local keyword index over the notes, the wikis and past
sessions, with the walls applied before anything is returned.

    cd tests && python3 -m unittest test_recall

Each test below is a line of the issue's *Done when*, or a rule it states.
Invented names only: Acme Corp and Birch & Co stand either side of a wall.
"""

from __future__ import annotations

import contextlib
import dataclasses
import inspect
import io
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixtures  # noqa: E402  (puts the tools folder on sys.path)
from fixtures import build_workspace, commit_all, git_init, meeting_page, thread_note, write  # noqa: E402

import check  # noqa: E402
import garrick_lib  # noqa: E402
import recall  # noqa: E402
import recall_sessions  # noqa: E402

ACME = "Zones/Work/Acme Review"
BIRCH = "Zones/Work/Birch Entry"


def claude_line(kind, cwd, content, sid="s1", when="2026-09-01T10:00:00Z", **extra):
    d = {"type": kind, "cwd": cwd, "sessionId": sid, "timestamp": when,
         "message": {"role": kind, "content": content}}
    d.update(extra)
    return d


def write_jsonl(path: Path, records) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return path


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(str(self.tmp), ignore_errors=True))
        self.root = build_workspace(self.tmp / "ws").resolve()
        meetings = self.root / "Wikis" / "Meetings"
        write(meetings / "wiki" / "sources" / "260310-acme-kickoff.md",
              meeting_page("Work", "[acme]", "Acme kick-off").replace(
                  "---\n\n#", "raw: raw/260310-acme-kickoff.txt\n---\n\n#", 1).replace(
                  "Decisions.", "Decisions: the quokkaplan starts Monday."))
        write(meetings / "wiki" / "sources" / "260312-birch-kickoff.md",
              meeting_page("Work", "[birch]", "Birch kick-off").replace("Decisions.", "Decisions: the wombatplan is on."))
        write(meetings / "wiki" / "sources" / "260313-no-parties.md",
              meeting_page("Work", None, "No parties").replace("Decisions.", "Decisions: platypusplan."))
        write(meetings / "wiki" / "sources" / "260314-no-zone.md",
              meeting_page(None, "[acme]", "No zone").replace("Decisions.", "Decisions: echidnaplan."))
        write(meetings / "raw" / "260310-acme-kickoff.txt", "Dana: the quokkaplan raw words, then numbat.\n")
        write(self.root / ACME / "Threads" / "Pricing" / "Pricing.md",
              thread_note("Acme Review", "Pricing", "acme", "Renewal bands for the quokka account."))
        write(self.root / BIRCH / "Threads" / "Market Sizing" / "Market Sizing.md",
              thread_note("Birch Entry", "Market Sizing", "birch", "Renewal bands for the wombat account."))

    def find(self, words, project=ACME, **kw):
        return recall.search(words, project=project, root=self.root, **kw)

    def paths(self, words, project=ACME, **kw):
        return [r.path for r in self.find(words, project, **kw)]


class InterfaceTest(Base):
    def test_the_interface_is_stable(self):
        sig = inspect.signature(recall.search)
        self.assertEqual(["words", "project", "after", "zone", "wiki", "sessions", "limit"],
                         list(sig.parameters)[:7])
        self.assertEqual(["id", "path", "title", "date", "source", "snippet", "score"],
                         [f.name for f in dataclasses.fields(recall.Result)][:7])
        with self.assertRaises(dataclasses.FrozenInstanceError):
            self.find("quokkaplan")[0].path = "x"

    def test_sqlite_here_has_fts5(self):
        """CI's runner must have it: Recall's ranking stands on it."""
        self.assertTrue(recall.fts5_available(), "this Python's SQLite has no FTS5")

    def test_a_search_returns_ranked_results_with_paths(self):
        found = self.find("quokkaplan")
        self.assertEqual("Wikis/Meetings/wiki/sources/260310-acme-kickoff.md", found[0].path)
        self.assertEqual("Meetings", found[0].source)
        self.assertIn("quokkaplan", found[0].snippet)
        self.assertEqual("2026-03-10", found[0].date)
        self.assertLessEqual(len(self.find("renewal", limit=1)), 1)

    def test_a_project_outside_the_workspace_finds_nothing(self):
        self.assertEqual([], recall.search("quokkaplan", project=self.tmp, root=self.root))


class WallTest(Base):
    def everything_for(self, project, word):
        found = self.find(word, project, sessions=True, limit=50)
        return found, json.dumps([dataclasses.asdict(r) for r in found])

    def test_a_walled_row_is_not_returned_counted_or_quoted_from_either_side(self):
        for project, mine, theirs in ((ACME, "quokka", "wombat"), (BIRCH, "wombat", "quokka")):
            found, text = self.everything_for(project, "%s %splan %s %splan renewal" % (mine, mine, theirs, theirs))
            self.assertTrue(found, project)
            self.assertNotIn(theirs, text.lower(), project)
            self.assertNotIn(theirs.capitalize() + " ", text, project)
            for r in found:
                self.assertNotIn(theirs, r.path.lower())

    def test_the_command_line_header_counts_only_what_is_returned(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = recall.main(["--root", str(self.root), "search", "wombatplan wombat", "--project", ACME])
        self.assertEqual(0, code)
        self.assertEqual("0 results for 'wombatplan wombat'", out.getvalue().strip())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            recall.main(["--root", str(self.root), "stats", "--project", ACME])
        self.assertNotIn("Meetings: 4", out.getvalue())
        self.assertIn("Meetings: 2 files", out.getvalue())          # the Acme page and its raw record

    def test_stats_counts_only_what_the_project_may_read(self):
        rows = {r["index"]: r["files"] for r in recall.stats(ACME, self.root)}
        self.assertEqual(2, rows["Meetings"])
        self.assertEqual(1, {r["index"]: r["files"] for r in recall.stats(BIRCH, self.root)}["Meetings"])
        root_rows = {r["index"]: r["files"] for r in recall.stats(None, self.root)}
        self.assertEqual(3, root_rows["Meetings"])

    def test_a_meetings_page_without_its_zone_or_parties_is_never_returned(self):
        for project in (ACME, BIRCH, None):
            self.assertEqual([], self.find("platypusplan", project, sessions=True), project)
            self.assertEqual([], self.find("echidnaplan", project, sessions=True), project)
        self.assertEqual([], self.find("platypusplan", None, wiki="Meetings"))

    def test_a_meetings_page_of_another_zone_needs_the_zone_asked_for(self):
        write(self.root / "Wikis" / "Meetings" / "wiki" / "sources" / "260315-home.md",
              meeting_page("Personal", "[acme]", "Home call").replace("Decisions.", "Decisions: capybaraplan."))
        self.assertEqual([], self.find("capybaraplan"))
        self.assertEqual(1, len(self.find("capybaraplan", zone="Personal")))

    def test_a_project_with_no_party_sees_no_meetings(self):
        write(self.root / "Zones/Work/Loose/Loose.md", fixtures.project_hub("Work", "Loose", ""))
        write(self.root / "Zones/Work/Loose/Notes.md", "# Notes\n\nquokkaplan notes\n")
        found = self.paths("quokkaplan", "Zones/Work/Loose")
        self.assertEqual(["Zones/Work/Loose/Notes.md"], found)

    def test_cross_zone_search_applies_the_walls_too(self):
        write(self.root / "Zones/Personal/Home/Home.md", fixtures.project_hub("Personal", "Home", "birch"))
        write(self.root / "Zones/Personal/Home/Notes.md", "# Notes\n\nflamingoplan\n")
        self.assertEqual([], self.find("flamingoplan"))
        self.assertEqual([], self.find("flamingoplan", zone="Personal"))              # Acme and Birch are walled
        self.assertEqual(["Zones/Personal/Home/Notes.md"], self.paths("flamingoplan", BIRCH, zone="Personal"))

    def test_knowledge_is_not_filtered(self):
        for project in (ACME, BIRCH):
            self.assertEqual(["Wikis/Knowledge/wiki/sources/supply-chain-report.md"],
                             self.paths("supply", project, wiki="Knowledge"))

    def test_the_walls_are_the_ones_the_commit_hook_reads(self):
        self.assertIs(garrick_lib.walled, recall.walled)
        self.assertIs(garrick_lib.load_context, recall.load_context)


class IndexTest(Base):
    def snapshot(self):
        return [(r.path, r.score, r.snippet) for w in ("quokkaplan renewal", "wombat", "supply", "numbat", "pricing")
                for p in (ACME, BIRCH, None) for r in self.find(w, p, sessions=True)]

    def test_deleting_every_index_and_building_gives_the_same_results(self):
        before = self.snapshot()
        self.assertTrue(before)
        indexes = list(self.root.rglob(recall.INDEX_NAME))
        self.assertGreaterEqual(len(indexes), 4)
        for p in indexes:
            p.unlink()
        recall.build(self.root)
        self.assertEqual(before, self.snapshot())
        recall.build(self.root, rebuild=True)
        self.assertEqual(before, self.snapshot())

    def test_an_index_sits_inside_its_zone_and_wiki(self):
        self.find("quokkaplan")
        self.assertTrue((self.root / "Zones" / "Work" / recall.INDEX_NAME).is_file())
        self.assertTrue((self.root / "Wikis" / "Meetings" / recall.INDEX_NAME).is_file())
        self.assertFalse((self.root / recall.INDEX_NAME).exists())

    def test_a_changed_file_is_picked_up_and_a_deleted_one_forgotten(self):
        self.assertEqual([], self.paths("narwhalplan"))
        note = write(self.root / ACME / "Threads" / "Pricing" / "Extra.md", "# Extra\n\nnarwhalplan here\n")
        self.assertEqual([note.relative_to(self.root).as_posix()], self.paths("narwhalplan"))
        note.write_text("# Extra\n\nnothing now but a longer text\n")
        self.assertEqual([], self.paths("narwhalplan"))
        note.unlink()
        self.assertEqual([], self.paths("longer"))

    def test_a_hub_party_changed_moves_its_files_across_the_wall(self):
        self.assertEqual([], self.find("wombat"))
        hub = self.root / BIRCH / "Birch Entry.md"
        hub.write_text(hub.read_text().replace("party: birch", "party: acme"))
        note = self.root / BIRCH / "Threads" / "Market Sizing" / "Market Sizing.md"
        note.write_text(note.read_text().replace("party: birch", "party: acme"))
        self.assertTrue(self.find("wombat"))

    def test_without_fts5_it_says_so_and_searches_plain_text(self):
        with mock.patch.object(recall, "fts5_available", return_value=False):
            found = self.find("quokkaplan renewal")
            self.assertEqual("Wikis/Meetings/wiki/sources/260310-acme-kickoff.md", found[0].path)
            self.assertNotIn("wombat", json.dumps([dataclasses.asdict(r) for r in found]))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                recall.main(["--root", str(self.root), "search", "quokkaplan", "--project", ACME])
        self.assertIn("FTS5 is not in this Python's SQLite", out.getvalue())
        self.assertIn("1 result", out.getvalue())
        # And back again: an index made without FTS5 is made again with it.
        self.assertTrue(self.find("quokkaplan"))

    def test_an_index_in_a_synced_folder_is_kept_in_memory(self):
        with mock.patch.object(recall, "synced", return_value=True):
            self.assertTrue(self.find("quokkaplan"))
        self.assertFalse((self.root / "Wikis" / "Meetings" / recall.INDEX_NAME).exists())

    def test_accents_fold_and_there_is_no_stemming(self):
        write(self.root / ACME / "Cafe.md", "# Cafe\n\nUn p\u00e2t\u00e9 et des cr\u00eapes\n")
        self.assertEqual(["Zones/Work/Acme Review/Cafe.md"], self.paths("pate crepes"))
        self.assertEqual([], self.paths("crepe"))

    def test_the_ignores_cover_the_index_and_the_sessions(self):
        for path, lines in garrick_lib.garrick_ignores(["Work"]).items():
            if path.startswith("Zones/") or path.startswith("Wikis/") or "templates" in path:
                self.assertIn(".recall.sqlite*", lines.splitlines(), path)
                self.assertIn(".sessions/", lines.splitlines(), path)
            elif path == ".gitignore":
                self.assertIn("System/.recall.sqlite*", lines.splitlines())
                self.assertIn("System/.sessions/", lines.splitlines())


class RankingTest(Base):
    def test_the_raw_chunk_list_folds_into_its_page(self):
        found = self.find("numbat")
        self.assertEqual(["Wikis/Meetings/raw/260310-acme-kickoff.txt"], [r.path for r in found])
        both = self.find("quokkaplan")
        self.assertEqual(1, len([r for r in both if r.path.startswith("Wikis/Meetings")]))

    def test_a_recent_note_beats_an_old_one_and_a_superseded_one_scores_half(self):
        today = __import__("datetime").date.today()
        old = today - __import__("datetime").timedelta(days=900)
        write(self.root / ACME / "Old.md", "---\ndate: %s\n---\n\n# Old\n\nplumbfoo\n" % old)
        write(self.root / ACME / "New.md", "---\ndate: %s\n---\n\n# New\n\nplumbfoo\n" % today)
        found = self.find("plumbfoo")
        self.assertEqual(["New.md", "Old.md"], [Path(r.path).name for r in found])
        write(self.root / ACME / "New.md", "---\ndate: %s\nsuperseded: Old\n---\n\n# New\n\nplumbfoo\n" % today)
        again = {Path(r.path).name: r.score for r in self.find("plumbfoo")}
        self.assertLess(again["New.md"], found[0].score * 0.6)

    def test_after_keeps_only_newer_hits(self):
        self.assertTrue(self.find("quokkaplan", after="2026-03-10"))
        self.assertEqual([], self.find("quokkaplan", after="2026-03-11"))

    def test_grades_working_first_dormant_when_short_archived_only_asked(self):
        top = self.root / "Wikis" / "Meetings"
        write(top / "dormant" / "wiki" / "sources" / "250101-old.md",
              meeting_page("Work", "[acme]", "Old call").replace("Decisions.", "Decisions: ocelotplan."))
        write(top / "archive" / "wiki" / "sources" / "230101-older.md",
              meeting_page("Work", "[acme]", "Older call").replace("Decisions.", "Decisions: ocelotplan pangolinplan."))
        found = self.find("ocelotplan")
        self.assertEqual(["dormant"], [r.grade for r in found])
        self.assertEqual([], self.find("pangolinplan"))
        both = self.find("ocelotplan", archived=True)
        self.assertEqual(["dormant", "archived"], [r.grade for r in both])
        # With enough working hits, dormant pages stay out.
        for n in range(3):
            write(self.root / ACME / ("N%d.md" % n), "# N\n\nocelotplan\n")
        self.assertEqual({"working"}, {r.grade for r in self.find("ocelotplan", limit=3)})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            recall.main(["--root", str(self.root), "search", "ocelotplan", "--project", ACME, "--limit", "10"])
        self.assertIn("from older notes", out.getvalue())

    def test_the_reach_setting_keeps_dormant_pages_out(self):
        top = self.root / "Wikis" / "Meetings"
        write(top / "dormant" / "wiki" / "sources" / "250101-old.md",
              meeting_page("Work", "[acme]", "Old call").replace("Decisions.", "Decisions: ocelotplan."))
        write(self.root / "System" / "garrick-settings.json", json.dumps({"memory": {"reach": "working"}}))
        self.assertEqual([], self.find("ocelotplan"))

    def test_a_few_thousand_notes_return_in_under_a_second(self):
        notes = self.root / ACME / "Notes"
        for n in range(3000):
            write(notes / ("n%04d.md" % n), "# Note %d\n\nBody of note %d about pricing, renewals and wordnumber%d.\n"
                  % (n, n, n % 50))
        recall.build(self.root)
        start = time.time()
        found = self.find("pricing renewals wordnumber7")
        took = time.time() - start
        self.assertEqual(10, len(found))
        self.assertTrue(all(r.score > 0 for r in found))
        loaded = os.environ.get("CI") and (os.getloadavg()[0] > (os.cpu_count() or 1))
        if not loaded:
            self.assertLess(took, 1.0)


class MaskTest(unittest.TestCase):
    def test_secret_shaped_strings_are_masked(self):
        secrets = ["sk-abcdefghijklmnop1234", "ghp_" + "a1" * 12, "AKIAABCDEFGHIJKLMNOP",
                   "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc123def456",
                   "xoxb-1234567890-abcdefghij", "hunter2hunter2", "a9b8c7d6e5f4a9b8c7d6e5f4a9b8c7d6e5f4a9b8",
                   "-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----"]
        for secret in secrets:
            for shape in (("%s",) if secret != "hunter2hunter2" else ()) + ("password=%s", "token: %s", "--api-key %s", "Authorization: Bearer %s",
                          "https://user:%s@host.example/x", "export API_KEY=%s"):
                masked = recall_sessions.mask(shape % secret)
                for piece in (secret.split("\n")[1] if "\n" in secret else secret,):
                    self.assertNotIn(piece, masked, shape % secret)

    def test_ordinary_text_is_left_alone(self):
        text = "Fixed the retry flag in 260901 - session notes; see Zones/Work/Acme Review and commit abc1234."
        self.assertEqual(text, recall_sessions.mask(text))


class SessionTest(Base):
    def setUp(self):
        super().setUp()
        self.claude = self.tmp / "claude"
        self.codex = self.tmp / "codex"
        self.work = str(self.root / ACME)

    def extract(self):
        return recall_sessions.extract_all(self.root, str(self.claude), str(self.codex))

    def session(self, cwd, text="why did the invoicexport fail", sid="s1", **kw):
        return write_jsonl(self.claude / "p" / (sid + ".jsonl"), [claude_line("user", cwd, text, sid, **kw)])

    def test_a_session_is_extracted_and_found_by_what_was_said(self):
        write_jsonl(self.claude / "p" / "s1.jsonl", [
            claude_line("user", self.work, "why did the invoicexport fail"),
            claude_line("user", self.work, [{"type": "text", "text": "<system-reminder>memoryindexword</system-reminder>"}]),
            claude_line("assistant", self.work, [{"type": "text", "text": "Use the retry flag."},
                                                  {"type": "tool_use", "id": "t1", "name": "Bash",
                                                   "input": {"command": "export-tool --retry"}},
                                                  {"type": "tool_use", "id": "t2", "name": "Read",
                                                   "input": {"file_path": "/etc/hosts"}}]),
            claude_line("user", self.work, [{"type": "tool_result", "tool_use_id": "t1", "is_error": True,
                                              "content": "Exit code 2\nTOOLOUTPUTWORD"}]),
        ])
        self.assertIn("sessions written: 1", self.extract())
        files = list((self.root / "Zones" / "Work" / ".sessions").glob("*.md"))
        self.assertEqual(["260901 - s1.md"], [f.name for f in files])
        text = files[0].read_text()
        self.assertIn("exit 2", text)
        self.assertIn("export-tool --retry", text)
        for left_out in ("TOOLOUTPUTWORD", "memoryindexword", "hosts"):
            self.assertNotIn(left_out, text)
        self.assertEqual(["Zones/Work/.sessions/260901 - s1.md"], self.paths("invoicexport", sessions=True))
        self.assertEqual([], self.paths("invoicexport"))                      # sessions only when asked
        self.assertEqual([], self.paths("memoryindexword", sessions=True))
        self.assertIn("exit 2", self.find("retry", sessions=True)[0].snippet + text)

    def test_a_session_is_extracted_again_only_when_it_has_grown(self):
        src = self.session(self.work)
        self.assertIn("written: 1", self.extract())
        self.assertIn("written: 0", self.extract())
        write_jsonl(src, [claude_line("user", self.work, "why did the invoicexport fail"),
                          claude_line("user", self.work, "and the second thing")])
        self.assertIn("written: 1", self.extract())
        self.assertEqual(1, len(list((self.root / "Zones" / "Work" / ".sessions").glob("*.md"))))

    def test_a_secret_in_a_session_never_reaches_sessions(self):
        secret_a, secret_b = "sk-live1234567890abcdef", "hunter2hunter2"
        write_jsonl(self.claude / "p" / "s1.jsonl", [
            claude_line("user", self.work, "my key is %s and password=%s" % (secret_a, secret_b)),
            claude_line("assistant", self.work, [{"type": "tool_use", "id": "t", "name": "Bash",
                                                   "input": {"command": "curl -H 'Authorization: Bearer %s' x" % secret_a}}]),
        ])
        self.extract()
        everything = "".join(p.read_text() for p in self.root.rglob(".sessions/*.md"))
        self.assertTrue(everything)
        for secret in (secret_a, secret_b):
            self.assertNotIn(secret, everything)
        self.assertNotIn(secret_a, self.find("key", sessions=True)[0].snippet)

    def test_a_session_opened_in_one_zone_never_lands_in_another(self):
        self.session(self.work, sid="a")
        self.session(str(self.root / "Zones" / "Personal"), sid="b")
        self.session(str(self.root / "Zones" / "Personal" / "Nowhere" / "x"), sid="c")
        self.extract()
        work = sorted(p.name for p in (self.root / "Zones" / "Work" / ".sessions").glob("*.md"))
        personal = sorted(p.name for p in (self.root / "Zones" / "Personal" / ".sessions").glob("*.md"))
        self.assertEqual(["260901 - a.md"], work)
        self.assertEqual(["260901 - b.md", "260901 - c.md"], personal)

    def test_a_session_that_cannot_be_placed_goes_nowhere(self):
        outside = self.tmp / "elsewhere"
        outside.mkdir()
        self.session(str(outside), sid="out")
        write_jsonl(self.claude / "p" / "mixed.jsonl", [
            claude_line("user", self.work, "first", "mixed"),
            claude_line("user", str(self.root / "Zones" / "Personal"), "second", "mixed")])
        write_jsonl(self.claude / "p" / "rel.jsonl", [claude_line("user", "relative/path", "x", "rel")])
        write_jsonl(self.claude / "p" / "none.jsonl", [{"type": "user", "sessionId": "none",
                                                          "message": {"role": "user", "content": "no cwd"}}])
        write_jsonl(self.claude / "p" / "zone.jsonl", [claude_line("user", str(self.root / "Zones" / "Ghost"), "x", "zone")])
        self.extract()
        self.assertEqual([], list(self.root.rglob(".sessions/*.md")))

    def test_a_link_into_another_zone_is_decided_by_where_it_resolves(self):
        os.symlink(str(self.root / "Zones" / "Personal"), str(self.root / "Zones" / "Work" / "Link"))
        self.session(str(self.root / "Zones" / "Work" / "Link"), sid="l")
        self.extract()
        self.assertEqual([], list((self.root / "Zones" / "Work" / ".sessions").glob("*.md")) if
                         (self.root / "Zones" / "Work" / ".sessions").is_dir() else [])
        self.assertEqual(1, len(list((self.root / "Zones" / "Personal" / ".sessions").glob("*.md"))))

    def test_root_and_system_sessions_go_to_system_and_only_a_root_search_reads_them(self):
        self.session(str(self.root), text="rootonly zebraword", sid="r")
        self.session(str(self.root / "System"), text="systemonly zebraword", sid="y")
        self.extract()
        self.assertEqual(2, len(list((self.root / "System" / ".sessions").glob("*.md"))))
        self.assertEqual(2, len(self.find("zebraword", None, sessions=True)))
        for project in (ACME, BIRCH, "Zones/Personal"):
            self.assertEqual([], self.find("zebraword", project, sessions=True), project)
            self.assertEqual([], self.find("zebraword", project, sessions=True, zone="Personal"), project)

    def test_a_session_of_one_party_is_walled_from_the_other(self):
        self.session(self.work, text="narwhal acmeonly", sid="a")
        self.extract()
        self.assertTrue(self.find("acmeonly", ACME, sessions=True))
        self.assertEqual([], self.find("acmeonly", BIRCH, sessions=True))
        self.assertTrue(self.find("acmeonly", None, sessions=True))

    def test_a_session_opened_at_a_zones_top_is_read_only_there(self):
        self.session(str(self.root / "Zones" / "Work"), text="topsecret zoneword", sid="z")
        self.extract()
        self.assertEqual([], self.find("zoneword", ACME, sessions=True))
        self.assertTrue(self.find("zoneword", "Zones/Work", sessions=True))

    def test_codex_sessions_are_read_too(self):
        write_jsonl(self.codex / "2026" / "09" / "01" / "rollout-x.jsonl", [
            {"type": "session_meta", "timestamp": "2026-09-01T10:00:00Z", "payload": {"id": "cx1", "cwd": self.work}},
            {"type": "response_item", "payload": {"type": "message", "role": "developer",
                                                   "content": [{"type": "input_text", "text": "hidden rules"}]}},
            {"type": "response_item", "payload": {"type": "message", "role": "user",
                                                   "content": [{"type": "input_text", "text": "gnuquestion"}]}},
            {"type": "response_item", "payload": {"type": "function_call", "name": "shell", "call_id": "c1",
                                                   "arguments": json.dumps({"command": ["ls", "-la"]})}},
            {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "c1",
                                                   "output": [{"type": "output_text", "text": "Exit code: 3\nbig output"}]}},
            {"type": "response_item", "payload": {"type": "message", "role": "assistant",
                                                   "content": [{"type": "output_text", "text": "gnuanswer"}]}},
        ])
        self.extract()
        text = next((self.root / "Zones" / "Work" / ".sessions").glob("*.md")).read_text()
        self.assertIn("gnuquestion", text)
        self.assertIn("ls -la", text)
        self.assertIn("exit 3", text)
        self.assertNotIn("hidden rules", text)
        self.assertNotIn("big output", text)


@unittest.skipUnless(fixtures.HAVE_GIT, "git is needed")
class CheckTest(Base):
    def recall_findings(self):
        return [f for f in check.run_checks(self.root) if f.check == "recall"]

    def test_a_committed_index_or_session_is_reported(self):
        zone = self.root / "Zones" / "Work"
        for p in (zone / ".git",):
            if p.is_dir() and not (p / "HEAD").exists():
                __import__("shutil").rmtree(str(p))
        git_init(zone)
        self.assertEqual([], self.recall_findings())
        write(zone / ".sessions" / "260901 - s.md", "x")
        self.find("quokkaplan")
        self.assertTrue((zone / recall.INDEX_NAME).is_file())
        commit_all(zone)                                              # no ignore file: everything is staged
        found = self.recall_findings()
        self.assertEqual({"Zones/Work/.sessions/260901 - s.md", "Zones/Work/.recall.sqlite"}, {f.path for f in found})
        self.assertEqual({"error"}, {f.severity for f in found})

    def test_an_ignored_index_is_clean(self):
        zone = self.root / "Zones" / "Work"
        __import__("shutil").rmtree(str(zone / ".git"))
        git_init(zone)
        write(zone / ".gitignore", garrick_lib.RECALL_IGNORES)
        write(zone / ".sessions" / "260901 - s.md", "x")
        self.find("quokkaplan")
        commit_all(zone)
        self.assertEqual([], self.recall_findings())


if __name__ == "__main__":
    unittest.main()
