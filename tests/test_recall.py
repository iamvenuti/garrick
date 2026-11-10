"""Recall (#341): a local keyword index over the notes, the wikis and past
sessions, with the walls applied before anything is returned.

    cd tests && python3 -m unittest test_recall

Each test below is a line of the issue's *Done when*, or a rule it states.
Invented names only: Acme Corp (the Work zone) and Birch & Co (the Personal
zone, which is walled too) stand either side of a wall; the zone is the wall,
the party is only an index.
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
BIRCH = "Zones/Personal/Birch Entry"


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
        __import__("shutil").move(str(self.root / "Zones" / "Work" / "Birch Entry"), str(self.root / BIRCH))
        write(meetings / "wiki" / "sources" / "260310-acme-kickoff.md",
              meeting_page("Work", "[acme]", "Acme kick-off").replace(
                  "---\n\n#", "raw: raw/260310-acme-kickoff.txt\n---\n\n#", 1).replace(
                  "Decisions.", "Decisions: the quokkaplan starts Monday."))
        write(meetings / "wiki" / "sources" / "260312-birch-kickoff.md",
              meeting_page("Personal", "[birch]", "Birch kick-off").replace("Decisions.", "Decisions: the wombatplan is on."))
        write(meetings / "wiki" / "sources" / "260313-no-parties.md",
              meeting_page("Work", None, "No parties").replace("Decisions.", "Decisions: platypusplan."))
        write(meetings / "wiki" / "sources" / "260314-no-zone.md",
              meeting_page(None, "[acme]", "No zone").replace("Decisions.", "Decisions: echidnaplan."))
        write(meetings / "raw" / "260310-acme-kickoff.txt", "Dana: the quokkaplan raw words, then numbat.\n")
        write(self.root / ACME / "Threads" / "Pricing" / "Pricing.md",
              thread_note("Acme Review", "Pricing", "acme", "Renewal bands for the quokka account."))
        write(self.root / BIRCH / "Threads" / "Market Sizing" / "Market Sizing.md",
              thread_note("Birch Entry", "Market Sizing", "birch", "Renewal bands for the wombat account."))

        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("CLAUDE_PROJECT_DIR", None)

    def set_flags(self, work=True, personal=True):
        """System/context.md as 0.63 writes it: a Walled column on Zones, no flag on a party."""
        flag = lambda w: "yes" if w else "no"
        write(self.root / "System" / "context.md", """\
            # Context

            ## Me

            Jo Example. Independent advisor.

            ## Zones

            | Zone | Holds | Walled |
            |---|---|---|
            | Work | Client work | %s |
            | Personal | Everything else | %s |

            ## Parties

            | Party | What it is | Zone | Tag | Domains |
            |---|---|---|---|---|
            | Acme Corp | Client | Work | `acme` | acmecorp.example |
            | Birch & Co | Client | Personal | `birch` | birchco.example |

            ## People

            | Name | Party | Role |
            |---|---|---|
            | Dana Whitlock | `acme` | Head of procurement |

            ## Aliases

            | Heard | Means |
            |---|---|
            | birch and co, birchen co | Birch & Co |
            """ % (flag(work), flag(personal)))

    def cli(self, cwd, *args, root=True, env=None):
        """Run the command line as a process opened in `cwd` would: its scope
        is that folder. Returns (exit code, stdout, stderr)."""
        here = os.getcwd()
        out, err = io.StringIO(), io.StringIO()
        try:
            os.chdir(str(cwd))
            with mock.patch.dict(os.environ, env or {}), contextlib.redirect_stdout(out), \
                    contextlib.redirect_stderr(err):
                try:
                    code = recall.main((["--root", str(self.root)] if root else []) + list(args))
                except SystemExit as why:
                    code = why.code
        finally:
            os.chdir(here)
        return code, out.getvalue(), err.getvalue()

    @property
    def at_root(self):
        """The environment of a session the harness opened at the root."""
        return {"CLAUDE_PROJECT_DIR": str(self.root)}

    def indexes(self):
        return sorted(p for p in self.root.rglob(".recall.sqlite*")
                      if not p.name.endswith(("-journal", "-wal", "-shm")) and ".new-" not in p.name)

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
        code, out, _ = self.cli(self.root / ACME, "search", "wombatplan wombat")
        self.assertEqual(0, code)
        self.assertEqual("0 results for 'wombatplan wombat'", out.strip())
        _, out, _ = self.cli(self.root / ACME, "stats")
        self.assertEqual(1, len(out.strip().splitlines()))           # one scope, one index
        self.assertTrue(out.startswith("work: "), out)

    def test_stats_counts_only_what_the_project_may_read(self):
        acme = recall.stats(ACME, self.root)
        birch = recall.stats(BIRCH, self.root)
        root = recall.stats(None, self.root)
        self.assertEqual(["work"], [r["index"] for r in acme])
        self.assertEqual(["personal"], [r["index"] for r in birch])
        self.assertEqual(["root"], [r["index"] for r in root])
        # the count is the index file's own: a walled file is not in it to be counted
        for rows, path in ((acme, self.root / "Zones/Work/.recall.sqlite"),
                           (birch, self.root / "Zones/Personal/.recall.sqlite")):
            con = sqlite3.connect(str(path))
            self.assertEqual(rows[0]["files"], con.execute("SELECT COUNT(DISTINCT path) FROM docs").fetchone()[0])
            con.close()
        self.assertGreater(root[0]["files"], acme[0]["files"])
        self.assertGreater(root[0]["files"], birch[0]["files"])

    def test_a_meetings_page_without_its_zone_is_never_returned_and_one_without_parties_is_read_by_its_zone(self):
        for project in (ACME, BIRCH, None):
            self.assertEqual([], self.find("echidnaplan", project, sessions=True), project)       # no zone: in no scope, the root's too
        self.assertEqual([], self.find("platypusplan", BIRCH))                                    # Work's page, from Personal
        for project in (ACME, None):
            self.assertEqual(1, len(self.find("platypusplan", project)), project)                  # `parties:` is an index only
        self.assertEqual(1, len(self.find("platypusplan", None, wiki="Meetings")))

    def test_a_meetings_page_naming_two_zones_or_one_the_table_does_not_know_is_in_no_scope(self):
        m = self.root / "Wikis" / "Meetings" / "wiki" / "sources"
        write(m / "260316-two.md", meeting_page("Work", "[acme]", "Two").replace("zone: Work", "zone: [Work, Personal]").replace(
            "Decisions.", "Decisions: lemurplan."))
        write(m / "260317-unknown.md", meeting_page("Nowhere", "[acme]", "Unknown").replace("Decisions.", "Decisions: gibbonplan."))
        for project in (ACME, BIRCH, None):
            self.assertEqual([], self.find("lemurplan", project), project)
            self.assertEqual([], self.find("gibbonplan", project), project)

    def test_a_meetings_page_of_another_zone_needs_the_zone_asked_for(self):
        write(self.root / "Wikis" / "Meetings" / "wiki" / "sources" / "260315-home.md",
              meeting_page("Personal", "[acme]", "Home call").replace("Decisions.", "Decisions: capybaraplan."))
        self.assertEqual([], self.find("capybaraplan"))
        self.assertEqual([], self.find("capybaraplan", zone="Personal"))            # a scope never reaches past its zone
        self.assertEqual(1, len(self.find("capybaraplan", None, zone="Personal")))  # the root holds no party

    def test_a_project_with_no_party_reads_its_zone_like_any_other(self):
        write(self.root / "Zones/Work/Loose/Loose.md", fixtures.project_hub("Work", "Loose", ""))
        write(self.root / "Zones/Work/Loose/Notes.md", "# Notes\n\nquokkaplan notes\n")
        self.assertIn("Zones/Work/Loose/Notes.md", self.paths("quokkaplan", "Zones/Work/Loose"))
        self.assertEqual("work", recall.scope_for_project(self.root, garrick_lib.load_context(self.root), "Zones/Work/Loose").key)
        self.assertEqual([], self.paths("quokkaplan notes wombatplan", "Zones/Work/Loose", wiki="Knowledge"))

    def test_cross_zone_search_applies_the_walls_too(self):
        write(self.root / "Zones/Personal/Home/Home.md", fixtures.project_hub("Personal", "Home", "birch"))
        write(self.root / "Zones/Personal/Home/Notes.md", "# Notes\n\nflamingoplan\n")
        self.assertEqual([], self.find("flamingoplan"))
        self.assertEqual([], self.find("flamingoplan", zone="Personal"))              # a scope never reaches past its zone
        self.assertEqual(["Zones/Personal/Home/Notes.md"], self.paths("flamingoplan", BIRCH, zone="Personal"))
        self.assertEqual(["Zones/Personal/Home/Notes.md"], self.paths("flamingoplan", "Zones/Personal/Home"))
        self.assertEqual(["Zones/Personal/Home/Notes.md"], self.paths("flamingoplan", None, zone="Personal"))

    def test_knowledge_is_not_filtered(self):
        for project in (ACME, BIRCH):
            self.assertEqual(["Wikis/Knowledge/wiki/sources/supply-chain-report.md"],
                             self.paths("supply", project, wiki="Knowledge"))

    def test_the_walls_are_the_ones_the_commit_hook_reads(self):
        self.assertIs(garrick_lib.may_flow, recall.may_flow)
        self.assertIs(garrick_lib.zone_of, recall.zone_of)
        self.assertFalse(hasattr(recall, "walled"))          # no wall test of its own


class IndexTest(Base):
    def snapshot(self):
        return [(r.path, r.score, r.snippet) for w in ("quokkaplan renewal", "wombat", "supply", "numbat", "pricing")
                for p in (ACME, BIRCH, None) for r in self.find(w, p, sessions=True)]

    def test_deleting_every_index_and_building_gives_the_same_results(self):
        before = self.snapshot()
        self.assertTrue(before)
        indexes = self.indexes()
        self.assertEqual(2, len(indexes))                # the two sides of Work; the root has none
        for p in indexes:
            p.unlink()
        recall.build(self.root)
        self.assertEqual(before, self.snapshot())
        recall.build(self.root, rebuild=True)
        self.assertEqual(before, self.snapshot())

    def test_an_index_sits_inside_its_zone_and_wiki(self):
        self.find("quokkaplan")
        self.find("quokkaplan", None)
        self.assertTrue((self.root / "Zones" / "Work" / recall.INDEX_NAME).is_file())
        self.assertFalse((self.root / "System" / recall.INDEX_NAME).exists())     # the root scope has no file
        self.assertFalse((self.root / recall.INDEX_NAME).exists())
        self.assertFalse((self.root / "Wikis" / "Meetings" / recall.INDEX_NAME).exists())     # the wikis keep none

    def test_a_changed_file_is_picked_up_and_a_deleted_one_forgotten(self):
        self.assertEqual([], self.paths("narwhalplan"))
        note = write(self.root / ACME / "Threads" / "Pricing" / "Extra.md", "# Extra\n\nnarwhalplan here\n")
        self.assertEqual([note.relative_to(self.root).as_posix()], self.paths("narwhalplan"))
        note.write_text("# Extra\n\nnothing now but a longer text\n")
        self.assertEqual([], self.paths("narwhalplan"))
        note.unlink()
        self.assertEqual([], self.paths("longer"))

    def test_an_open_zone_is_read_from_the_other_zone_and_a_walled_one_is_not(self):
        self.set_flags(work=True, personal=False)
        self.assertTrue(self.find("wombat"))                          # Personal is open: Work reads it
        self.assertEqual([], self.find("quokkaplan", BIRCH))          # Work is walled: Personal does not
        self.set_flags(work=False, personal=False)
        self.assertTrue(self.find("quokkaplan", BIRCH))
        self.set_flags(work=True, personal=True)
        self.assertEqual([], self.find("wombat"))
        self.assertEqual([], self.find("quokkaplan", BIRCH))

    def test_without_fts5_it_says_so_and_searches_plain_text(self):
        with mock.patch.object(recall, "fts5_available", return_value=False):
            found = self.find("quokkaplan renewal")
            self.assertEqual("Wikis/Meetings/wiki/sources/260310-acme-kickoff.md", found[0].path)
            self.assertNotIn("wombat", json.dumps([dataclasses.asdict(r) for r in found]))
            _, out, _ = self.cli(self.root / ACME, "search", "quokkaplan")
        self.assertIn("FTS5 is not in this Python's SQLite", out)
        self.assertIn("1 result", out)
        # And back again: an index made without FTS5 is made again with it.
        self.assertTrue(self.find("quokkaplan"))

    def test_an_index_in_a_synced_folder_is_kept_in_memory(self):
        with mock.patch.object(recall, "synced", return_value=True):
            self.assertTrue(self.find("quokkaplan"))
        self.assertEqual([], self.indexes())

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
        _, out, _ = self.cli(self.root / ACME, "search", "ocelotplan", "--limit", "10")
        self.assertIn("from older notes", out)

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
        self.assertEqual(["Zones/Work/.sessions/260901 - s1.md"], self.paths("invoicexport", None, sessions=True))
        self.assertEqual(["Zones/Work/.sessions/260901 - s1.md"], self.paths("invoicexport", ACME, sessions=True))   # its own zone reads it
        self.assertEqual([], self.paths("invoicexport", BIRCH, sessions=True))   # Work is walled: not from Personal
        self.assertEqual([], self.paths("invoicexport"))                      # sessions only when asked
        self.assertEqual([], self.paths("memoryindexword", None, sessions=True))
        self.assertIn("exit 2", self.find("retry", None, sessions=True)[0].snippet + text)

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
        # a past session takes its folder's zone: that zone's scope and the root read it, no other
        self.assertTrue(self.find("key", ACME, sessions=True))
        self.assertEqual([], self.find("key", BIRCH, sessions=True))
        found = self.find("key", None, sessions=True)
        self.assertTrue(found)
        for secret in (secret_a, secret_b):
            self.assertNotIn(secret, found[0].snippet)

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

    def test_a_session_of_one_zone_is_walled_from_the_other(self):
        self.session(self.work, text="narwhal acmeonly", sid="a")
        self.extract()
        self.assertTrue(self.find("acmeonly", ACME, sessions=True))           # a project of its own zone reads it
        self.assertEqual([], self.find("acmeonly", BIRCH, sessions=True))     # the other walled zone cannot
        self.assertTrue(self.find("acmeonly", None, sessions=True))

    def test_a_session_opened_at_a_zones_top_is_that_zones(self):
        self.session(str(self.root / "Zones" / "Work"), text="topsecret zoneword", sid="z")
        self.extract()
        self.assertTrue(self.find("zoneword", ACME, sessions=True))
        self.assertEqual([], self.find("zoneword", BIRCH, sessions=True))
        self.assertEqual([], self.find("zoneword", "Zones/Work", sessions=True))     # a zone's top holds no scope
        self.assertTrue(self.find("zoneword", None, sessions=True))

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


class ReviewFixesTest(Base):
    """What an independent security review found in the first cut."""

    def snap(self, words, project=ACME, **kw):
        return [(r.path, r.score) for r in self.find(words, project, **kw)]

    # -- 1: a walled row never changes the order of the rest ------------------

    def test_walled_rows_do_not_change_the_order_of_what_is_returned(self):
        write(self.root / ACME / "A.md", "# A\n\nalpha filler words go here today\n")
        write(self.root / ACME / "B.md", "# B\n\nbeta filler words go here today\n")
        before = self.snap("alpha beta")
        self.assertEqual(2, len([p for p, _ in before if "Acme Review" in p]))
        for n in range(6):
            write(self.root / BIRCH / ("W%d.md" % n), "# W\n\nalpha secret birch stuff %d\n" % n)
        self.assertEqual(before, self.snap("alpha beta"))
        # The same for Meetings pages and their raw records.
        write(self.root / "Wikis/Meetings/wiki/sources/260321-a2.md",
              meeting_page("Work", "[acme]", "A2").replace("Decisions.", "gammaword filler words").replace(
                  "---\n\n#", "raw: raw/260321-a2.txt\n---\n\n#", 1))
        write(self.root / "Wikis/Meetings/raw/260321-a2.txt", "gammaword here and deltaword")
        mine = self.snap("gammaword deltaword")
        self.assertTrue(mine)
        for n in range(8):
            write(self.root / "Wikis/Meetings/wiki/sources" / ("2603%02d-w.md" % (22 + n)),
                  meeting_page("Personal", "[birch]", "W%d" % n).replace("Decisions.", "gammaword gammaword"))
            write(self.root / "Wikis/Meetings/raw" / ("2603%02d-w.txt" % (22 + n)), "gammaword deltaword " * 5)
        self.assertEqual(mine, self.snap("gammaword deltaword"))
        with mock.patch.object(recall, "fts5_available", return_value=False):
            plain_before = self.snap("alpha beta")
            write(self.root / BIRCH / "Z.md", "# Z\n\nalpha alpha beta\n")
            self.assertEqual(plain_before, self.snap("alpha beta"))

    # -- 2: a party that is not a listed tag cannot be placed -----------------

    def test_parties_are_an_index_and_never_read_as_a_wall(self):
        forms = ["birch, acme", "acme birch", '"[acme, birch]"', "acme; birch", "[#acme, #birch]", "[acme and birch]", "acme",
                 "\n  - Acme", "[zzz]"]
        for n, form in enumerate(forms):
            write(self.root / "Wikis/Meetings/wiki/sources" / ("26041%d-any.md" % n),
                  meeting_page("Work", form, "Any %d" % n).replace("Decisions.", "Decisions: anypartyword%d." % n))
            for project, want in ((ACME, 1), (BIRCH, 0), (None, 1)):
                self.assertEqual(want, len(self.find("anypartyword%d" % n, project)), (form, project))

    def test_a_hub_that_names_any_party_or_none_changes_nothing(self):
        write(self.root / BIRCH / "Notes.md", "# Notes\n\nbirchnotesword\n")
        write(self.root / ACME / "Notes.md", "# Notes\n\nacmenotesword\n")
        self.assertEqual([BIRCH + "/Notes.md"], self.paths("birchnotesword", BIRCH))
        hub = self.root / BIRCH / "Birch Entry.md"
        hub.write_text(hub.read_text().replace("party: birch", "party: acme, zzz"))
        self.assertEqual([BIRCH + "/Notes.md"], self.paths("birchnotesword", BIRCH))
        self.assertEqual([BIRCH + "/Notes.md"], self.paths("birchnotesword", None))
        self.assertEqual([], self.paths("birchnotesword", ACME))                   # the zone is the wall, not the hub's party
        self.assertEqual([], self.paths("acmenotesword", BIRCH))

    # -- 3: a place no zone owns reads nothing --------------------------------

    def test_a_place_that_is_not_the_root_or_a_project_reads_nothing(self):
        for place in ("Wikis/Meetings", "Wikis/Knowledge/wiki", "Zones", str(self.tmp), "Nowhere/at/all"):
            self.assertEqual([], self.find("quokkaplan supply", place), place)
            self.assertEqual([], self.find("quokkaplan supply", place, sessions=True), place)
        for empty in ("", ".", Path(""), Path("."), " "):
            self.assertEqual([], self.find("quokkaplan supply", empty), repr(empty))
        self.assertTrue(self.find("quokkaplan", None))
        self.assertTrue(self.find("quokkaplan", str(self.root)))
        self.assertTrue(self.find("quokkaplan", "System"))
        self.assertEqual([], recall.stats("Wikis/Meetings", self.root))
        here = os.getcwd()
        try:
            for place in ("Wikis/Meetings", "Zones", "Wikis/Knowledge/wiki"):
                os.chdir(str(self.root / place))
                self.assertEqual(recall.NOWHERE, recall.cwd_project(self.root), place)
            os.chdir(str(self.tmp))
            self.assertEqual(recall.NOWHERE, recall.cwd_project(self.root))
            for place in (".", "System"):
                os.chdir(str(self.root / place))
                self.assertEqual(recall.NOWHERE, recall.cwd_project(self.root), place)      # a bare folder is no root session
                with mock.patch.dict(os.environ, self.at_root):
                    self.assertIsNone(recall.cwd_project(self.root), place)
            os.chdir(str(self.root / "Wikis/Meetings"))
            err, out = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                recall.main(["--root", str(self.root), "search", "quokkaplan"])
            self.assertTrue(out.getvalue().startswith("0 results"))
            self.assertIn("nothing was searched", err.getvalue())
        finally:
            os.chdir(here)

    # -- 5: Knowledge pages that name a zone or a party ------------------------

    def test_a_knowledge_page_that_names_a_party_follows_the_meetings_rule(self):
        k = self.root / "Wikis/Knowledge/wiki/sources"
        write(k / "a-birch.md", "---\ntitle: B\nparty: birch\nzone: Work\n---\n\n# B\n\nkbirchword\n")
        write(k / "a-acme.md", "---\ntitle: A\nparties: [acme]\nzone: Work\n---\n\n# A\n\nkacmeword\n")
        write(k / "a-party-only.md", "---\ntitle: P\nparty: acme\n---\n\n# P\n\nkpartyonlyword\n")
        write(k / "a-zone-only.md", "---\ntitle: Z\nzone: Work\n---\n\n# Z\n\nkzoneonlyword\n")
        write(k / "a-plain.md", "---\ntitle: Pl\n---\n\n# Pl\n\nkplainword\n")
        write(k / "a-owner.md", "---\ntitle: O\nraw: raw/o.txt\nparty: birch\nzone: Work\n---\n\n# O\n\nkownerword\n")
        write(self.root / "Wikis/Knowledge/raw/o.txt", "kbirchrawword\n")
        self.assertEqual([], self.find("kbirchword", ACME))
        self.assertEqual([], self.find("kbirchrawword", ACME))
        # a Knowledge page with a party or zone key is someone's, not published:
        # it is in no scope's index, the root's included
        for project in (ACME, BIRCH, None):
            for word in ("kbirchword", "kbirchrawword", "kacmeword", "kpartyonlyword", "kzoneonlyword"):
                self.assertEqual([], self.find(word, project), (word, project))
        self.assertEqual(1, len(self.find("kplainword", ACME)))
        self.assertEqual(1, len(self.find("kplainword", BIRCH)))
        self.assertEqual(1, len(self.find("kplainword", None)))

    # -- 6: an edit that keeps the size and the time still counts --------------

    def test_a_same_size_same_time_edit_changes_the_zone(self):
        page = self.root / "Wikis/Meetings/wiki/sources/260312-birch-kickoff.md"
        self.assertTrue(self.find("wombatplan", BIRCH))
        self.assertEqual([], self.find("wombatplan", ACME))
        st = page.stat()
        page.write_text(page.read_text().replace("zone: Personal", "zone: Work    "))
        os.utime(str(page), ns=(st.st_atime_ns, st.st_mtime_ns))
        self.assertEqual(st.st_size, page.stat().st_size)
        self.assertTrue(self.find("wombatplan", ACME))
        self.assertEqual([], self.find("wombatplan", BIRCH))

    # -- 8: a file at the zone's top is the zone's, not a project --------------

    def test_a_zone_level_search_finds_nothing_but_a_zones_top_file_is_the_zones(self):
        write(self.root / "Zones/Work/Todo.md", "# Todo\n\nzonetodoword\n")
        self.assertEqual([], self.paths("zonetodoword", "Zones/Work"))             # a zone's top is no project: no scope
        self.assertEqual(["Zones/Work/Todo.md"], self.paths("zonetodoword", ACME))
        self.assertEqual(["Zones/Work/Todo.md"], self.paths("zonetodoword", None))
        self.assertEqual([], self.paths("zonetodoword", BIRCH))
        self.assertEqual("", recall.locate(self.root, self.root / "Zones/Work/Todo.md").project)
        self.assertEqual("Acme Review", recall.locate(self.root, self.root / ACME).project)

    # -- 9: wiki= with sessions=True searches no zone notes --------------------

    def test_a_wiki_with_sessions_searches_sessions_not_notes(self):
        write(self.root / ACME / "Plain.md", "# Plain\n\nsharedtermword note\n")
        write(self.root / "Wikis/Knowledge/wiki/sources/k.md", "---\ntitle: K\n---\n\n# K\n\nsharedtermword\n")
        write_jsonl(self.tmp / "claude/p/s1.jsonl", [claude_line("user", str(self.root / ACME), "sharedtermword said")])
        recall_sessions.extract_all(self.root, str(self.tmp / "claude"), str(self.tmp / "none"))
        both = self.paths("sharedtermword", None, wiki="Knowledge", sessions=True)
        self.assertEqual(2, len(both))
        self.assertNotIn(ACME + "/Plain.md", both)
        self.assertEqual(["Wikis/Knowledge/wiki/sources/k.md"], self.paths("sharedtermword", wiki="Knowledge"))

    # -- 12: robustness --------------------------------------------------------

    def test_an_index_in_use_is_not_deleted_and_files_are_private(self):
        self.find("quokkaplan")
        path = self.root / "Zones/Work" / recall.INDEX_NAME
        self.assertEqual(0o600, path.stat().st_mode & 0o777)
        path.unlink()
        path.write_bytes(b"")                      # another process has just created it
        self.assertTrue(self.find("quokkaplan"))
        self.assertEqual(b"", path.read_bytes())
        old = time.time() - 600
        os.utime(str(path), (old, old))
        self.assertTrue(self.find("quokkaplan"))
        self.assertNotEqual(b"", path.read_bytes())
        self.assertEqual(0o600, path.stat().st_mode & 0o777)

    def test_a_failing_index_is_reported_without_counts(self):
        with mock.patch.object(recall.Refresher, "run", side_effect=sqlite3.OperationalError("locked")):
            done = recall.build(self.root)
        self.assertTrue(done)
        for item in done:
            self.assertTrue(item.endswith("(failed)"), item)
            self.assertFalse(any(c.isdigit() for c in item), item)

    def test_times_with_any_fraction_parse(self):
        for value in ("2026-09-01T10:00:00.1Z", "2026-09-01T10:00:00.123456789Z", "2026-09-01T10:00:00.12+00:00",
                      "2026-09-01T10:00:00Z"):
            parsed = recall_sessions.parse_time(value)
            self.assertIsNotNone(parsed, value)
            self.assertEqual((2026, 9, 1, 10), (parsed.year, parsed.month, parsed.day, parsed.hour))


class ReviewSessionFixesTest(Base):
    def setUp(self):
        super().setUp()
        self.claude, self.codex = self.tmp / "claude", self.tmp / "codex"
        self.work = str(self.root / ACME)

    def extract(self):
        return recall_sessions.extract_all(self.root, str(self.claude), str(self.codex))

    def test_a_session_that_began_at_the_zones_top_is_the_zones_and_names_no_project(self):
        write_jsonl(self.claude / "p" / "s1.jsonl", [
            claude_line("user", str(self.root / "Zones" / "Work"), "zonelevelword said", "s1"),
            claude_line("user", self.work, "then went into acme", "s1")])
        self.extract()
        text = next((self.root / "Zones/Work/.sessions").glob("*.md")).read_text()
        self.assertNotIn("project:", text)
        self.assertEqual(1, len(self.find("zonelevelword", ACME, sessions=True)))
        self.assertEqual([], self.find("zonelevelword", BIRCH, sessions=True))
        self.assertEqual([], self.find("zonelevelword", "Zones/Work", sessions=True))
        self.assertEqual(1, len(self.find("zonelevelword", None, sessions=True)))

    def test_a_crafted_session_id_cannot_forge_a_header(self):
        evil = "x\nproject: %s\ncwd: y" % BIRCH
        write_jsonl(self.claude / "p" / "s1.jsonl", [claude_line("user", self.work, "forgeword said", evil)])
        self.extract()
        files = list((self.root / "Zones/Work/.sessions").glob("*.md"))
        self.assertEqual(1, len(files))
        head = files[0].read_text().split("\n---", 2)[0]
        self.assertEqual(0, head.count("project:"))                       # a past session names no project, and the id forged none
        self.assertNotIn(BIRCH, head)
        self.assertEqual([], self.find("forgeword", BIRCH, sessions=True))
        self.assertEqual(1, len(self.find("forgeword", ACME, sessions=True)))
        self.assertEqual(1, len(self.find("forgeword", None, sessions=True)))
        s = recall_sessions.Session("a\rb c: d\nproject: q", "claude-code", turns=[("user", "t\nproject: z", None)])
        head = recall_sessions.render(s, ["Zones/Work/P\nx"], 1, 1).split("\n---", 2)[0].splitlines()
        self.assertEqual(1, len([l for l in head if l.startswith("project:")]))
        self.assertEqual(1, len([l for l in head if l.startswith("session:")]))
        self.assertEqual(1, len([l for l in head if l.startswith("title:")]))

    def test_sessions_are_not_written_into_a_synced_folder_and_are_private(self):
        write_jsonl(self.claude / "p" / "s1.jsonl", [claude_line("user", self.work, "syncword said")])
        with mock.patch.object(recall, "synced", return_value=True):
            self.assertIn("written: 0", self.extract())
        self.assertEqual([], list(self.root.rglob(".sessions/*.md")))
        self.extract()
        f = next((self.root / "Zones/Work/.sessions").glob("*.md"))
        self.assertEqual(0o600, f.stat().st_mode & 0o777)
        self.assertEqual(0o700, f.parent.stat().st_mode & 0o777)


class RawClaimantsTest(Base):
    """One raw record, several claimants: the strictest policy wins, in any order."""

    RAW = "Wikis/Meetings/raw/260312-birch-kickoff.txt"

    def setUp(self):
        super().setUp()
        m = self.root / "Wikis/Meetings"
        write(m / "raw/260312-birch-kickoff.txt", "Theo: the kiwifruit pricing is eleven euros.\n")
        self.birch = m / "wiki/sources/260312-birch-kickoff.md"
        self.acme = m / "wiki/sources/260320-acme-followup.md"
        self.birch.write_text(self.birch.read_text().replace("---\n\n#", "raw: raw/260312-birch-kickoff.txt\n---\n\n#", 1))
        write(self.acme, meeting_page("Work", "[acme]", "Acme follow-up").replace(
            "---\n\n#", "raw: raw/260312-birch-kickoff.txt\n---\n\n#", 1))

    def seen(self):
        return (self.paths("kiwifruit", ACME), self.paths("kiwifruit", BIRCH), self.paths("kiwifruit", None))

    def test_a_second_claimant_does_not_open_the_record_to_the_other_side(self):
        acme, birch, _ = self.seen()
        self.assertEqual([], acme)
        self.assertEqual([], birch)

    def test_the_result_does_not_depend_on_the_order_the_index_was_built(self):
        first = self.seen()
        for index in self.indexes():
            index.unlink()
        self.acme.rename(self.acme.with_name("250101-acme-followup.md"))     # read first now
        self.assertEqual(first, self.seen())
        for index in self.indexes():
            index.unlink()
        self.assertEqual(first, self.seen())

    def test_an_unfinished_claimant_keeps_the_record_out(self):
        self.acme.write_text(self.acme.read_text().replace("zone: Work", "zone: "))
        self.assertEqual(([], [], []), self.seen())
        # Only the finished owner: both sides of the policy come back.
        self.acme.unlink()
        acme, birch, _ = self.seen()
        self.assertEqual([], acme)
        self.assertEqual(1, len(birch))

    def test_removing_a_claimant_derives_the_policy_again(self):
        self.acme.unlink()
        acme, birch, _ = self.seen()
        self.assertEqual(([], 1), (acme, len(birch)))

    def test_a_record_claimed_on_one_side_of_a_wall_only_stays_readable_there(self):
        self.acme.unlink()
        self.assertEqual(1, len(self.paths("kiwifruit", BIRCH)))
        self.assertEqual([], self.paths("kiwifruit", ACME))


class CommandLineScopeTest(Base):
    """The command line's scope comes only from the process's real folder
    (and the session marker), never from an argument."""

    def sessions_at_root(self):
        write(self.root / "System" / ".sessions" / "260901 - r.md", "# Session\n\nrootsession pelicanword\n")

    def test_no_argument_picks_the_scope(self):
        self.sessions_at_root()
        acme = self.root / ACME
        for flag in ("System", ACME.replace("Acme Review", "Birch Entry"), str(self.root), "."):
            code, out, _ = self.cli(acme, "search", "wombatplan", "--project", flag)
            self.assertNotEqual(0, code, flag)
            self.assertNotIn("wombatplan", out)
            self.assertNotEqual(0, self.cli(acme, "stats", "--project", flag)[0], flag)
        self.assertTrue(self.cli(self.root, "search", "pelicanword", "--sessions", env=self.at_root)[1].startswith("1 result"))
        self.assertTrue(self.cli(self.root, "search", "pelicanword", "--sessions")[1].startswith("0 results"))   # no marker, no root
        code, out, _ = self.cli(acme, "search", "pelicanword", "--sessions")
        self.assertTrue(out.startswith("0 results"), out)
        self.assertEqual("0 results", self.cli(acme, "search", "wombatplan", "--zone", "Work", "--sessions")[1][:9])
        self.assertTrue(self.cli(acme, "search", "quokkaplan")[1].startswith("1 result"))

    def test_a_zone_flag_does_not_widen_past_the_projects_party(self):
        write(self.root / "Zones/Personal/Diary/Diary.md", "# Diary\n\nzonewidenword\n")
        write(self.root / "Zones/Personal/Diary/Threads/T/T.md", "# T\n\nzonewidenword\n")
        code, out, _ = self.cli(self.root / ACME, "search", "zonewidenword", "--zone", "Personal")
        self.assertTrue(out.startswith("0 results"), out)
        code, out, _ = self.cli(self.root / ACME, "search", "wombatplan", "--zone", "Personal")
        self.assertTrue(out.startswith("0 results"), out)

    def test_a_folder_outside_the_given_root_reads_nothing(self):
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        code, out, err = self.cli(elsewhere, "search", "quokkaplan")
        self.assertTrue(out.startswith("0 results"), out)
        other = build_workspace(self.tmp / "other").resolve()
        write(other / ACME / "N.md", "# N\n\nquokkaplan\n")
        # The process is in another workspace, --root names this one: nothing.
        code, out, _ = self.cli(other / ACME, "search", "quokkaplan")
        self.assertTrue(out.startswith("0 results"), out)
        # And the other way round.
        code, out, _ = self.cli(self.root / ACME, "search", "quokkaplan")
        self.assertTrue(out.startswith("1 result"), out)

    def test_symlinks_are_followed_to_the_real_folder(self):
        link = self.tmp / "link"
        os.symlink(str(self.root / ACME), str(link))
        self.assertEqual(self.root / ACME, self._cwd(link))
        out = self.cli(link, "search", "wombatplan")[1]
        self.assertTrue(out.startswith("0 results"), out)

    def _cwd(self, folder):
        here = os.getcwd()
        try:
            os.chdir(str(folder))
            return recall.cwd_project(self.root)
        finally:
            os.chdir(here)

    def test_the_session_marker_narrows_and_never_widens(self):
        acme = self.root / ACME
        marker = {"CLAUDE_PROJECT_DIR": str(acme)}
        # opened in Acme, cd to the root: nothing, even at depth 0
        out = self.cli(self.root, "search", "wombatplan", env=marker)[1]
        self.assertTrue(out.startswith("0 results"), out)
        self.assertEqual(recall.NOWHERE, self._with(marker, self.root))
        self.assertEqual(recall.NOWHERE, self._with(marker, self.root / BIRCH))
        self.assertEqual(recall.NOWHERE, self._with(marker, self.root / "System"))
        # opened in Acme, in a thread of Acme: the thread
        self.assertEqual(acme / "Threads" / "Pricing", self._with(marker, acme / "Threads" / "Pricing"))
        # opened at the root, working in Acme: Acme (the narrower)
        self.assertEqual(acme, self._with({"CLAUDE_PROJECT_DIR": str(self.root)}, acme))
        # opened at the root, at the root: the root
        self.assertIsNone(self._with({"CLAUDE_PROJECT_DIR": str(self.root)}, self.root))
        # a marker outside the workspace, or in a wiki: nothing
        self.assertEqual(recall.NOWHERE, self._with({"CLAUDE_PROJECT_DIR": str(self.tmp)}, acme))
        self.assertEqual(recall.NOWHERE, self._with({"CLAUDE_PROJECT_DIR": str(self.root / "Wikis")}, acme))

    def _with(self, env, folder):
        with mock.patch.dict(os.environ, env):
            return self._cwd(folder)

    def test_stats_comes_from_the_folder_too(self):
        _, out, _ = self.cli(self.root / ACME, "stats")
        self.assertNotIn("Meetings: 4", out)
        self.assertNotIn("Meetings:", self.cli(self.tmp, "stats")[1])


class MaskMoreTest(unittest.TestCase):
    SECRETS = [
        ("Authorization: Token abcd1234efgh", "abcd1234efgh"),
        ("Authorization: Basic dXNlcjpwYXNz", "dXNlcjpwYXNz"),
        ("the password is hunter2", "hunter2"),
        ("PASSWORD hunter2", "hunter2"),
        ("pass hunter2", "hunter2"),
        ("mysql -u root -phunter2", "hunter2"),
        ("mysql -p hunter2", "hunter2"),
        ("sshpass -p hunter2 ssh host", "hunter2"),
        ("curl -u admin:hunter2 https://host.example", "hunter2"),
        ("export DB_PASS=hunter2", "hunter2"),
        ("PASS=hunterx", "hunterx"),
        ("pw=hunter2", "hunter2"),
        ('{"pass": "hunter2"}', "hunter2"),
        ("key=abc123def456", "abc123def456"),
        ("api key is 9f8e7d6c5b4a", "9f8e7d6c5b4a"),
        ("https://hooks.slack" + ".com/services/T0123ABCD/B0123ABCD/abcdEFGHijklMNOPqrstUVWX", "abcdEFGH"),
        ("https://hooks.slack" + ".com/services/T0123ABCD/B0123ABCD/abcdEFGHijklMNOPqrstUVWX", "T0123ABCD"),
        ("https://api.telegram.org/bot123456:ABC-DEFghi_jkl/sendMessage", "ABC-DEF"),
        ("password: correct horse battery staple", "staple"),
        ("password: correct horse battery staple", "correct"),
        ("SECRET: |\n  first hunterline\n  second hunterline\nnext: ok", "hunterline"),
        ('secret="""hunter2"""', "hunter2"),
        ("otp 123456", "123456"),
        ("pwd=hunter2", "hunter2"),
        ("passwd: hunter2", "hunter2"),
        ("docker login -u u -p hunter2", "hunter2"),
        ("docker login -u u -p hunter2 registry.example", "hunter2"),
        ("echo hunter2 | docker login --password-stdin", "hunter2"),
        ("printf 'hunter2' | docker login -u u --password-stdin reg.example", "hunter2"),
        ("openssl enc -aes-256-cbc -k hunter2 -in a", "hunter2"),
        ("openssl enc -aes-256-cbc -pass pass:hunter2 -in a", "hunter2"),
        ("aws configure set aws_secret_access_key wJalrXUtnFEMI/K7MDENG/bPx" + "RfiCYEXAMPLEKEY", "wJalrXUtnFEMI"),
        ("aws configure set aws_access_key_id hunter2value", "hunter2value"),
        ("aws configure set aws_session_token hunter2value", "hunter2value"),
        ("wJalrXUtnFEMI/K7MDENG/bPx" + "RfiCYEXAMPLEKEY", "K7MDENG"),
        ("Cookie: session=abcdef0123", "abcdef0123"),
        ("Set-Cookie: sid=abcdef0123; Path=/", "abcdef0123"),
        ("curl -H 'Cookie: session=abcdef0123' https://h.example", "abcdef0123"),
    ]

    def test_each_shape_is_masked(self):
        for text, secret in self.SECRETS:
            self.assertNotIn(secret, recall_sessions.mask(text), text)

    def test_masking_keeps_the_rest_of_the_structure(self):
        self.assertEqual('{"pass": [masked], "user": "x"}', recall_sessions.mask('{"pass": "hunter2", "user": "x"}'))
        self.assertIn("next: ok", recall_sessions.mask("SECRET: |\n  a\n  b\nnext: ok"))
        self.assertEqual("mysql -u root -p [masked]", recall_sessions.mask("mysql -u root -phunter2"))
        self.assertEqual("see keyboard and compass settings", recall_sessions.mask("see keyboard and compass settings"))


@unittest.skipUnless(fixtures.HAVE_GIT, "git is needed")
class MaskSpeedTest(unittest.TestCase):
    """Masking stays fast on long hyphenated or dotted text, and cuts fail closed."""

    CASES = {"dashes": "-" * 20000, "key-": "key-" * 6000, "dots": "a." * 12000, "token_": "token_" * 4000,
             "mixed": ("Lorem ipsum key-value a.b.c -x- pass=hunter2 user@example.com \n" * 2000)[:100000],
             "docker -p": "docker login -u u -p " * 3000, "stdin": "echo x | docker login " * 3000,
             "openssl -k": "openssl enc -k -pass pass: " * 3000, "cookie": "Cookie: " * 4000 + "Set-Cookie:" * 3000,
             "slashes": "a/" * 20000, "plus-slash": "aB3+/" * 8000, "aws": "aws configure set aws_secret_access_key " * 2000}

    def render(self, text):
        s = recall_sessions.Session("s", "claude", turns=[("user", text, None), ("command", text, None)])
        return recall_sessions.render(s, [], 1, 1)

    def test_long_runs_mask_in_under_a_second(self):
        for name, text in self.CASES.items():
            started = time.time()
            out = self.render(text)
            elapsed = time.time() - started
            self.assertNotIn("hunter2", out, name)
            if not os.environ.get("CI"):
                self.assertLess(elapsed, 1.0, name)

    def test_a_secret_across_the_cut_does_not_survive_in_part(self):
        secret = "ghp_" + "Ab3dEf6hIj9lMn2pQr5tUv8xYz1BcDeFgHiJ"
        for pad in range(recall_sessions.MAX_TEXT - 40, recall_sessions.MAX_TEXT + 10, 3):
            out = self.render("word " * (pad // 5) + " " + secret + " tail")
            self.assertNotIn("ghp_", out, pad)
            self.assertNotIn("Ab3dEf", out, pad)
        for pad in range(recall_sessions.MAX_COMMAND - 30, recall_sessions.MAX_COMMAND + 10, 3):
            out = self.render("w " * (pad // 2) + " " + secret)
            self.assertNotIn("ghp_", out, pad)


class IgnoreGuardTest(Base):
    """Nothing is written where git would see it."""

    def zone_repo(self, ignore):
        zone = self.root / "Zones" / "Work"
        if (zone / ".git").is_dir():
            __import__("shutil").rmtree(str(zone / ".git"))
        git_init(zone)
        recall._IGNORED.clear()
        recall._IGNORE_SAID.clear()
        if ignore:
            write(zone / ".gitignore", garrick_lib.RECALL_IGNORES)
        return zone

    def test_no_ignore_line_means_no_index_file_and_a_search_still_works(self):
        zone = self.zone_repo(False)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertTrue(self.find("quokkaplan"))
        self.assertEqual([], list(zone.glob(".recall.sqlite*")))
        self.assertEqual(1, err.getvalue().count("is not ignored by git"))
        self.assertIn("check.py", err.getvalue())

    def test_an_ignored_zone_gets_its_index(self):
        zone = self.zone_repo(True)
        self.assertTrue(self.find("quokkaplan"))
        self.assertTrue((zone / recall.INDEX_NAME).is_file())

    def test_no_ignore_line_means_no_session_file(self):
        zone = self.zone_repo(False)
        src = write_jsonl(self.tmp / "claude" / "p" / "s.jsonl", [
            claude_line("user", str(self.root / ACME), "hello gnuword"),
            claude_line("assistant", str(self.root / ACME), "ok")])
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            made = recall_sessions.write_session(self.root, src, recall_sessions.parse_claude(src))
        self.assertIsNone(made)
        self.assertFalse((zone / recall.SESSIONS_DIR).exists())
        self.assertIn("is not ignored by git", err.getvalue())
        write(zone / ".gitignore", garrick_lib.RECALL_IGNORES)
        recall._IGNORED.clear()
        self.assertIsNotNone(recall_sessions.write_session(self.root, src, recall_sessions.parse_claude(src)))


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
        write(zone / ".gitignore", garrick_lib.RECALL_IGNORES)        # the index is only written where it is ignored
        write(zone / ".sessions" / "260901 - s.md", "x")
        self.find("quokkaplan")
        self.assertTrue((zone / recall.INDEX_NAME).is_file())
        (zone / ".gitignore").unlink()
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


class ScopeIndexTest(Base):
    """The wall at the store (#341, #358, #398): for each scope a session can
    hold, one index holding admitted rows only. A walled row is not in the
    file, so nothing it could shape is there to be shaped."""

    def db(self, name):
        return sqlite3.connect(str(self.root / name))

    def test_one_scope_index_per_zone_and_none_for_the_root(self):
        ctx = garrick_lib.load_context(self.root)
        scopes = recall.scopes_of(self.root, ctx)
        self.assertEqual(["root", "personal", "work"], [sc.key for sc in scopes])
        recall.build(self.root)
        self.assertEqual(sorted(sc.file(self.root) for sc in scopes if sc.kind != "root"), self.indexes())
        self.assertFalse((self.root / "System" / recall.INDEX_NAME).exists())     # the root scope is made in memory
        self.set_flags(work=False, personal=False)                                # a flag changes what a scope reads, not the scopes
        self.assertEqual(["root", "personal", "work"], [sc.key for sc in recall.scopes_of(self.root, garrick_lib.load_context(self.root))])

    def test_a_walled_row_is_not_in_the_index_file_at_all(self):
        write(self.root / ACME / "A.md", "# A\n\nacmeonlyword here\n")
        write(self.root / BIRCH / "B.md", "# B\n\nbirchonlyword here\n")
        self.find("acmeonlyword")
        self.find("birchonlyword", BIRCH)
        for name, mine, theirs in (("Zones/Work/.recall.sqlite", "acme", "birch"),
                                   ("Zones/Personal/.recall.sqlite", "birch", "acme")):
            con = self.db(name)
            paths = [r[0] for r in con.execute("SELECT DISTINCT path FROM docs")]
            self.assertTrue(paths, name)
            for table in ("docs", "files", "fts", "fts_tri"):
                columns = {"docs": "path || body || title", "files": "path", "fts": "body", "fts_tri": "body"}[table]
                self.assertEqual(0, con.execute("SELECT COUNT(*) FROM %s WHERE %s LIKE ?" % (table, columns),
                                                ("%" + theirs + "onlyword%",)).fetchone()[0], (name, table))
            self.assertFalse([p for p in paths if theirs in p.lower() and "kickoff" not in p.lower() or
                              ("birch entry" if theirs == "birch" else "acme review") in p.lower()], paths)
            con.close()
            data = (self.root / name).read_bytes()
            self.assertNotIn((theirs + "onlyword").encode(), data)
            self.assertNotIn(b"wombat" if theirs == "birch" else b"quokka", data)

    def test_a_row_that_leaves_a_scope_leaves_no_bytes_of_it_in_the_file(self):
        self.set_flags(work=True, personal=False)                       # Personal is open: Work's index holds its rows
        write(self.root / BIRCH / "B.md", "# B\n\nleavingmarkerword here\n")
        self.assertTrue(self.find("leavingmarkerword", ACME))
        path = self.root / "Zones/Work/.recall.sqlite"
        self.assertIn(b"leavingmarkerword", path.read_bytes())
        self.set_flags(work=True, personal=True)                        # the flag flips: Work no longer admits Personal
        self.assertEqual([], self.find("leavingmarkerword", ACME))
        self.assertNotIn(b"leavingmarkerword", path.read_bytes())
        self.assertTrue(self.find("leavingmarkerword", BIRCH))          # Personal still reads its own
        self.assertIn(b"leavingmarkerword", (self.root / "Zones/Personal/.recall.sqlite").read_bytes())

    def test_read_checks_the_id_is_in_the_scope_index_and_a_walled_id_is_an_unknown_one(self):
        mine = self.find("quokkaplan")[0]
        theirs = self.find("wombatplan", None)[0]
        self.assertIn("quokkaplan", recall.read(mine.id, project=ACME, root=self.root))
        self.assertIn("wombatplan", recall.read(theirs.id, project=BIRCH, root=self.root))
        unknown = recall.read("Meetings:Wikis/Meetings/wiki/sources/260399-nothing.md", project=ACME, root=self.root)
        walled = recall.read(theirs.id, project=ACME, root=self.root)
        self.assertIsNone(unknown)
        self.assertIsNone(walled)
        # a real file that is no row in the index is as unknown as a walled one
        self.assertIsNone(recall.read("Work:Zones/Work/Acme Review/Acme Review.md.bak", project=ACME, root=self.root))
        self.assertIsNone(recall.read("Work:../../etc/hosts", project=ACME, root=self.root))
        self.assertIsNone(recall.read(mine.id, project="Zones/Work", root=self.root))     # no scope
        # the command line says the same of both
        a = self.cli(self.root / ACME, "read", theirs.id)
        b = self.cli(self.root / ACME, "read", "Meetings:Wikis/Meetings/wiki/sources/260399-nothing.md")
        self.assertEqual((1, ""), a[:2])
        self.assertEqual((1, ""), b[:2])
        self.assertEqual(a[2].replace(theirs.id, "X"), b[2].replace("Meetings:Wikis/Meetings/wiki/sources/260399-nothing.md", "X"))

    def test_adding_a_walled_row_changes_no_result_count_rank_or_snippet(self):
        write(self.root / ACME / "A.md", "# A\n\nalpha beta filler words go here today\n")
        write(self.root / ACME / "B.md", "# B\n\nbeta filler words go here today and quokkaplan\n")

        def snapshot():
            out = []
            for words in ("alpha beta", "quokkaplan renewal", "beta filler", "renewal bands", "gammaword"):
                for kw in ({}, {"sessions": True}, {"wiki": "Meetings"}, {"limit": 1}, {"after": "2026-03-01"}):
                    out.append((words, sorted(kw), [dataclasses.asdict(r) for r in self.find(words, ACME, **kw)]))
            out.append(self.cli(self.root / ACME, "search", "alpha beta")[1])
            out.append(self.cli(self.root / ACME, "stats")[1])
            return out

        before = snapshot()
        for n in range(8):
            write(self.root / BIRCH / ("W%d.md" % n), "# W\n\nalpha beta alpha quokkaplan renewal bands gammaword %d\n" % n)
            write(self.root / "Wikis/Meetings/wiki/sources" / ("2603%02d-w.md" % (20 + n)),
                  meeting_page("Personal", "[birch]", "W%d" % n).replace("Decisions.", "Decisions: gammaword quokkaplan alpha"))
        write(self.root / "System/.sessions/260901 - x.md", "# x\n\nalpha beta quokkaplan\n")
        self.assertEqual(before, snapshot())
        self.assertTrue(self.find("gammaword", BIRCH))                 # the other side does see them

    def test_two_zones_never_share_a_file(self):
        self.find("quokkaplan")
        self.find("wombatplan", BIRCH)
        acme, birch = (self.root / "Zones/Work/.recall.sqlite"), (self.root / "Zones/Personal/.recall.sqlite")
        self.assertNotEqual(acme, birch)
        for table, word in (("docs", "wombat"), ("docs", "quokka")):
            pass
        self.assertEqual(0, self.db("Zones/Work/.recall.sqlite").execute(
            "SELECT COUNT(*) FROM docs WHERE body LIKE '%wombat%'").fetchone()[0])
        self.assertEqual(0, self.db("Zones/Personal/.recall.sqlite").execute(
            "SELECT COUNT(*) FROM docs WHERE body LIKE '%quokka%'").fetchone()[0])

    # -- the four rounds of findings, as cases that are impossible by construction ------------------

    def test_round_1_statistics_of_walled_rows_cannot_move_an_admitted_rank(self):
        """The ranking took its counts over walled rows. Now the index holds none."""
        write(self.root / ACME / "A.md", "# A\n\nalpha filler words go here today\n")
        write(self.root / ACME / "B.md", "# B\n\nbeta filler words go here today\n")
        before = [(r.path, r.score) for r in self.find("alpha beta")]
        for n in range(6):
            write(self.root / BIRCH / ("W%d.md" % n), "# W\n\nalpha secret stuff %d\n" % n)
        self.assertEqual(before, [(r.path, r.score) for r in self.find("alpha beta")])
        self.assertEqual(0, self.db("Zones/Work/.recall.sqlite").execute(
            "SELECT COUNT(*) FROM docs WHERE path LIKE '%Birch%'").fetchone()[0])

    def test_round_2_the_command_line_cannot_choose_its_scope(self):
        """`--project System` searched as the root. The command takes a scope, and only the session's own."""
        acme = self.root / ACME
        for flag in ("System", BIRCH, str(self.root)):
            code, out, _ = self.cli(acme, "search", "wombatplan", "--project", flag)
            self.assertNotEqual(0, code)
            self.assertEqual("", out)
        for scope in ("root", "personal", "personal", "nowhere"):
            code, out, err = self.cli(acme, "search", "wombatplan", "--scope", scope)
            self.assertTrue(out.startswith("0 results"), (scope, out))
        self.assertTrue(self.cli(acme, "search", "quokkaplan", "--scope", "work")[1].startswith("1 result"))
        # the root may name any scope; that is narrowing, not widening
        self.assertTrue(self.cli(self.root, "search", "wombatplan", "--scope", "personal", env=self.at_root)[1].startswith("1 result"))
        self.assertTrue(self.cli(self.root, "search", "wombatplan", "--scope", "work", env=self.at_root)[1].startswith("0 results"))
        # and the API holds the same line
        self.assertEqual([], self.find("wombatplan", ACME, scope="personal"))
        self.assertEqual([], self.find("wombatplan", ACME, scope="root"))

    def test_round_3_a_folder_or_a_variable_cannot_move_a_session_into_another_scope(self):
        """A link to the root, changed into, searched as the root; a session choosing its scope through the environment."""
        link = self.tmp / "rootlink"
        os.symlink(str(self.root), str(link))
        for folder in (self.root, self.root / "System", link):
            for word in ("wombatplan", "quokkaplan"):
                self.assertTrue(self.cli(folder, "search", word)[1].startswith("0 results"), folder)   # no marker, no root
            for env in ({recall.SCOPE_ENV: "work"}, {recall.SCOPE_ENV: "root"}):
                self.assertTrue(self.cli(folder, "search", "quokkaplan", env=env)[1].startswith("0 results"), (folder, env))
        # a marker naming the root is the harness's record of a root session; the variable then only narrows
        env = dict(self.at_root, **{recall.SCOPE_ENV: "work"})
        self.assertTrue(self.cli(self.root, "search", "quokkaplan", env=env)[1].startswith("1 result"))
        self.assertTrue(self.cli(self.root, "search", "wombatplan", env=env)[1].startswith("0 results"))
        # an Acme session cannot choose Birch or the root by the variable, by the marker or by moving
        acme = self.root / ACME
        for pin in ("personal", "root"):
            out = self.cli(acme, "search", "wombatplan", env={recall.SCOPE_ENV: pin})
            self.assertTrue(out[1].startswith("0 results"), pin)
            self.assertIn("nothing was searched", out[2])
        self.assertTrue(self.cli(acme, "search", "wombatplan", env=self.at_root)[1].startswith("0 results"))      # narrower of the two
        self.assertTrue(self.cli(self.root, "search", "wombatplan", env={"CLAUDE_PROJECT_DIR": str(acme)})[1].startswith("0 results"))
        # no root index is kept on disk, where any session could open it
        self.cli(self.root, "search", "quokkaplan", env=self.at_root)
        self.assertFalse((self.root / "System" / recall.INDEX_NAME).exists())
        self.assertNotIn(b"wombat", b"".join(p.read_bytes() for p in self.indexes() if p.name.endswith("acme")))

    def test_round_4_a_session_that_worked_in_two_zones_is_the_roots_only(self):
        """A session of two zones is no zone's: only the root reads it."""
        sessions = self.root / "Zones/Work/.sessions"
        header = "---\nsession: s9\ntitle: mixed\nproject: %s\n---\n\n# mixed\n\nmixedsessionword said\n"
        write(sessions / "260901 - mixed.md", header % json.dumps([ACME, BIRCH]))
        write(sessions / "260903 - gone.md", header % json.dumps([ACME, "Zones/Work/Deleted"]))
        write(sessions / "260905 - bad.md", header.replace("project: %s", "project: not a list"))
        for project in (ACME, BIRCH):
            self.assertEqual([], self.find("mixedsessionword", project, sessions=True), project)
        self.assertEqual(["Zones/Work/.sessions/260901 - mixed.md", "Zones/Work/.sessions/260903 - gone.md",
                          "Zones/Work/.sessions/260905 - bad.md"],
                         sorted(r.path for r in self.find("mixedsessionword", None, sessions=True)))
        # one zone alone is readable from that zone, and from no other walled zone
        write(sessions / "260904 - acme.md", header % json.dumps([ACME]))
        self.assertEqual(["Zones/Work/.sessions/260904 - acme.md"], [r.path for r in self.find("mixedsessionword", ACME, sessions=True)])
        self.assertEqual([], self.find("mixedsessionword", BIRCH, sessions=True))
        con = self.db("Zones/Personal/.recall.sqlite")
        self.assertEqual(0, con.execute("SELECT COUNT(*) FROM docs WHERE src = 'session'").fetchone()[0])

    def test_round_5_rows_that_name_no_zone_the_table_knows_are_in_no_index(self):
        """A conversation without a zone, a Knowledge page with a party, a zone nobody declared: used nowhere."""
        meetings = self.root / "Wikis/Meetings/wiki/sources"
        write(meetings / "260330-ghost.md", meeting_page("Ghostland", "[acme]", "Ghost").replace("Decisions.", "Decisions: ghostword."))
        write(meetings / "260331-mixed.md", meeting_page("Work", "[acme, birch]", "Mixed").replace("Decisions.", "Decisions: crossword."))
        for project in (ACME, BIRCH, None):
            self.assertEqual([], self.find("ghostword", project), project)
        self.assertEqual(1, len(self.find("crossword", ACME)))                    # two parties, one zone: `parties:` is an index
        self.assertEqual([], self.find("crossword", BIRCH))
        self.assertEqual(1, len(self.find("crossword", None)))
        for path in self.indexes():
            con = sqlite3.connect(str(path))
            self.assertEqual(0, con.execute("SELECT COUNT(*) FROM docs WHERE body LIKE '%ghostword%'").fetchone()[0], path)
            con.close()


class WallReviewTest(Base):
    """The wall review of the rebuilt Recall: four findings, each a test."""

    def hub(self, name, party):
        write(self.root / "Zones/Work" / name / (name + ".md"), fixtures.project_hub("Work", name, party, ["T"]))
        write(self.root / "Zones/Work" / name / "Threads/T/T.md", thread_note(name, "T", party))
        return "Zones/Work/" + name

    def extract_one(self, cwd, turns, sid="w1"):
        claude = self.tmp / "claude" / "p"
        claude.mkdir(parents=True, exist_ok=True)
        recs = [claude_line("assistant", str(cwd), [{"type": "tool_use", "id": "t%d" % n, "name": "Bash",
                                                      "input": {"command": content}}], sid) if kind == "command"
                else claude_line(kind, str(cwd), content, sid) for n, (kind, content) in enumerate(turns)]
        write_jsonl(claude / (sid + ".jsonl"), recs)
        return recall_sessions.extract_all(self.root, str(self.tmp / "claude"), str(self.tmp / "none"))

    def sessions(self):
        return sorted((self.root / "Zones/Work/.sessions").glob("*.md")) if (self.root / "Zones/Work/.sessions").is_dir() else []

    # F1: a session chooses its own scope
    def test_f1_no_variable_folder_or_file_gives_a_session_a_wider_scope(self):
        acme = self.root / ACME
        for env in ({recall.SCOPE_ENV: "personal"}, {recall.SCOPE_ENV: "root"}, {"CLAUDE_PROJECT_DIR": str(acme), recall.SCOPE_ENV: "root"}):
            self.assertTrue(self.cli(acme, "search", "wombatplan", env=env)[1].startswith("0 results"), env)
        # a bare working folder at the root or a zone is never the root scope
        for folder in (self.root, self.root / "Zones" / "Work", self.root / "System"):
            self.assertTrue(self.cli(folder, "search", "wombatplan")[1].startswith("0 results"), folder)
            self.assertTrue(self.cli(folder, "search", "quokkaplan")[1].startswith("0 results"), folder)
        # the root scope is never a file
        self.cli(self.root, "search", "wombatplan", env={"CLAUDE_PROJECT_DIR": str(self.root)})
        self.assertFalse((self.root / "System" / recall.INDEX_NAME).exists())
        self.assertEqual([], [p for p in self.indexes() if p.parent.name == "System"])
        for p in self.indexes():
            self.assertNotIn(b"quokka" if p.name.endswith("birch") else b"wombat", p.read_bytes())

    # F2: a name with " #"
    def test_f2_a_project_name_with_a_hash_is_read_back_whole(self):
        self.hub("Anvil", "acme")
        birch = self.hub("Anvil #2", "birch")
        self.extract_one(self.root / birch, [("user", "birch pricing floor narwhalsecret")])
        text = self.sessions()[0].read_text()
        self.assertNotIn("project:", text.split("\n---", 2)[0])            # a past session names no project
        self.assertEqual(1, len(self.find("narwhalsecret", "Zones/Work/Anvil", sessions=True)))     # one zone: its projects read it
        self.assertEqual(1, len(self.find("narwhalsecret", birch, sessions=True)))
        self.assertEqual([], self.find("narwhalsecret", BIRCH, sessions=True))                      # the other walled zone does not
        self.assertEqual(1, len(self.find("narwhalsecret", None, sessions=True)))
        # a name with a `#` still reads back whole from a header that carries it
        probe = recall_sessions.Session("h", "claude-code", turns=[("user", "t", None)])
        written = recall_sessions.render(probe, ["Zones/Work/Anvil #2"], 1, 1)
        self.assertIn('project: ["Zones/Work/Anvil #2"]', written)
        self.assertEqual(["Zones/Work/Anvil #2"], recall.session_projects(written))
        # a project line that does not read back plainly labels nothing
        for bad in ("project: Zones/Work/Anvil #2", "project: [Zones/Work/Anvil]", "project: 5"):
            self.assertIsNone(recall.session_projects("---\n%s\n---\n" % bad), bad)

    # F3: paths read without changing folder
    def test_f3_a_session_that_reads_another_projects_file_names_no_project(self):
        a, b = self.hub("Anvil", "acme"), self.hub("Harbour2", "birch")
        write(self.root / b / "Threads/T/Secret.md", "# Secret\n\nfloor price.\n")
        self.extract_one(self.root / a, [
            ("user", "compare with the harbour file"),
            ("command", "cat ../Harbour2/Threads/T/Secret.md"),
            ("assistant", "The file says quokkafloor.")])
        text = self.sessions()[0].read_text()
        self.assertEqual([], recall.session_projects(text))              # no project label, whatever it read
        for project in (a, b):
            self.assertEqual(1, len(self.find("quokkafloor", project, sessions=True)), project)       # both are Work's
        self.assertEqual([], self.find("quokkafloor", BIRCH, sessions=True))
        self.assertEqual(1, len(self.find("quokkafloor", None, sessions=True)))

    def test_f3_an_absolute_or_spaced_path_in_a_turn_counts_and_an_unplaceable_one_drops_the_session(self):
        a = self.hub("Anvil", "acme")
        self.extract_one(self.root / a, [("user", "see %s/Acme Review/Notes.md please wordone" % (self.root / "Zones/Work"))], "s1")
        self.assertEqual([], recall.session_projects(self.sessions()[0].read_text()))
        self.assertEqual(1, len(self.find("wordone", a, sessions=True)))
        self.assertEqual([], self.find("wordone", BIRCH, sessions=True))
        self.assertEqual(1, len(self.find("wordone", None, sessions=True)))
        self.extract_one(self.root / a, [("user", "open Zones/Work/Ghost/Threads/x.md wordtwo")], "s2")
        self.assertEqual(1, len(self.sessions()))                         # the second was dropped
        self.extract_one(self.root / a, [("user", "the pattern Zones/<Zone>/<Project> and Zones/Work/Todo.md wordthree")], "s3")
        self.assertEqual(2, len(self.sessions()))                         # a placeholder and a zone-top file are not paths to a place

    # F4: stale files
    def test_f4_a_flipped_flag_leaves_no_rows_and_an_old_root_file_is_removed(self):
        self.set_flags(work=True, personal=False)
        write(self.root / BIRCH / "Threads/Market Sizing/Secret.md", "# S\n\nzebrafinch here\n")
        self.assertTrue(self.find("zebrafinch", ACME))                    # Personal is open: in Work's index
        self.set_flags(work=True, personal=True)
        self.find("quokkaplan")                                           # the wall is back
        self.assertNotIn(b"zebrafinch", (self.root / "Zones/Work" / recall.INDEX_NAME).read_bytes())
        # an old root file, and a file of a side of the party walls, are removed by the next build
        stale = self.root / "System" / recall.INDEX_NAME
        stale.write_bytes(b"x")
        side = self.root / "Zones/Work" / (recall.INDEX_NAME + "-acme")
        side.write_bytes(b"x")
        recall.build(self.root)
        self.assertFalse(stale.exists())
        self.assertFalse(side.exists())


class NamesAndSpellingTest(Base):
    """Names are expanded before the query; a trigram table catches a near miss."""

    def test_a_name_is_searched_in_every_spelling_with_and_without_spaces(self):
        write(self.root / ACME / "Joined.md", "# Joined\n\nrenewal with acmecorp signed\n")
        write(self.root / ACME / "Spaced.md", "# Spaced\n\nrenewal with Acme Corp signed\n")
        for query in ("acme corp", "acmecorp", "Acme  Corp renewal"):
            found = {Path(r.path).name for r in self.find(query)}
            self.assertTrue({"Joined.md", "Spaced.md"} <= found, (query, found))

    def test_a_heard_alias_finds_the_name_it_means(self):
        write(self.root / BIRCH / "Names.md", "# Names\n\nthe call with Birch & Co went well, birch and co agreed\n")
        self.assertIn(BIRCH + "/Names.md", self.paths("birchen co", BIRCH))

    def test_a_near_misspelling_is_found_through_the_trigram_table(self):
        self.assertTrue(recall.trigram_available())
        self.assertEqual("Wikis/Meetings/wiki/sources/260310-acme-kickoff.md", self.find("quokaplan")[0].path)
        con = sqlite3.connect(str(self.root / "Zones/Work/.recall.sqlite"))
        self.assertTrue(con.execute("SELECT 1 FROM sqlite_master WHERE name = 'fts_tri'").fetchone())
        self.assertIn("trigram", con.execute("SELECT sql FROM sqlite_master WHERE name = 'fts_tri'").fetchone()[0])
        con.close()
        # a near miss never reaches across the wall: the other side's word is not in this index
        self.assertEqual([], self.find("wombaatplan"))

    def test_without_the_trigram_tokenizer_it_falls_back_and_does_not_crash(self):
        with mock.patch.object(recall, "trigram_available", return_value=False):
            self.assertEqual([], self.find("quokaplan"))
            self.assertTrue(self.find("quokkaplan"))
            con = sqlite3.connect(str(self.root / "Zones/Work/.recall.sqlite"))
            self.assertIsNone(con.execute("SELECT 1 FROM sqlite_master WHERE name = 'fts_tri'").fetchone())
            con.close()
        self.assertTrue(self.find("quokaplan"))             # and back again: the index is made again with it

    def test_a_changed_flag_makes_the_index_again(self):
        self.assertTrue(self.find("quokkaplan"))
        ctx = garrick_lib.load_context(self.root)
        stamp = recall.policy_stamp(ctx, recall.scopes_of(self.root, ctx)[2])
        self.set_flags(work=False, personal=True)
        ctx = garrick_lib.load_context(self.root)
        self.assertNotEqual(stamp, recall.policy_stamp(ctx, recall.scopes_of(self.root, ctx)[2]))
        self.assertTrue(self.find("quokkaplan"))
        # a Parties-table edit alone does not make an index again
        self.set_flags(work=False, personal=True)
        before = recall.policy_stamp(garrick_lib.load_context(self.root), recall.scopes_of(self.root, ctx)[2])
        context = self.root / "System" / "context.md"
        context.write_text(context.read_text().replace("| Acme Corp | Client |", "| Acme Corp | A client |"), encoding="utf-8")
        self.assertEqual(before, recall.policy_stamp(garrick_lib.load_context(self.root), recall.scopes_of(self.root, ctx)[2]))


class NoWallTestOfItsOwnTest(unittest.TestCase):
    def test_recall_holds_no_wall_test_of_its_own(self):
        import re
        for name in ("recall.py", "recall_sessions.py"):
            text = (Path(fixtures.__file__).resolve().parent.parent / "template" / "System" / "tools" / name).read_text()
            self.assertIsNone(re.search(r"\bwalled\(", text), name)
        text = (Path(fixtures.__file__).resolve().parent.parent / "template" / "System" / "tools" / "recall.py").read_text()
        self.assertIn("may_flow(", text)
        self.assertNotIn("decide(", text)
        self.assertNotIn("allowed_pids", text)
        self.assertNotIn("admit=", text)


if __name__ == "__main__":
    unittest.main()
