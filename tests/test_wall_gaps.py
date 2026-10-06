"""What the check promises and now holds: the gaps between the rules and the
check, each closed with a case that must be caught and one that must pass.

Invented parties only: Acme Corp (`acme`) and Birch & Co (`birch`), walled
from each other, as in fixtures.py.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fixtures import HAVE_GIT, build_workspace, commit_all, git, meeting_page, write

import check  # noqa: E402  (fixtures puts the tools folder on sys.path)
from garrick_lib import WALL_HOOK, install_wall_hook  # noqa: E402

# Wording only one side ever saw. Never allowed to appear in a finding.
BRIEF = "The board plans to close the Leeds plant by the end of the third quarter and move the pump line to Gdansk"
BRIEF_WORDS = ("leeds", "plant", "gdansk")
ROWS = "supplier,part,spend\nHalden Castings,motor housing,410000\nKeld Seals,seal kit,186000\nOrrin Electronics,control board,352000\n"

# The checker runs git as the user would; these keep the user's own config out.
NO_USER_GIT = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def real_repo(folder: Path) -> None:
    shutil.rmtree(folder / ".git", ignore_errors=True)
    git(folder, "init", "-q")


class GapCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve() / "Workspace"
        build_workspace(self.root)
        self.work = self.root / "Zones" / "Work"
        self.acme = self.work / "Acme Review"
        self.birch = self.work / "Birch Entry"
        self.meetings = self.root / "Wikis" / "Meetings"
        self.knowledge = self.root / "Wikis" / "Knowledge"

    def tearDown(self):
        self._tmp.cleanup()

    def findings(self, name=None, severity=None):
        return [f for f in check.run_checks(self.root)
                if (name is None or f.check == name) and (severity is None or f.severity == severity)]

    def assertClean(self, name):
        self.assertEqual([], [(f.severity, f.path, f.message) for f in self.findings(name)])


class TestLinkIndex(GapCase):
    """Each link is matched against an index built once, not against every file."""

    def test_links_resolve_as_before(self):
        ws = check.discover(self.root)
        files = check.PathIndex(ws, check.walk_files(self.root))
        note = self.acme / "Threads" / "Pricing" / "Pricing.md"
        kickoff = self.meetings / "wiki" / "sources" / "260310-acme-kickoff.md"
        for target in ("260310-acme-kickoff", "Sources/260310-ACME-Kickoff.md", "Meetings/wiki/sources/260310-acme-kickoff",
                       "obsidian:Wikis:Meetings/wiki/sources/260310-acme-kickoff",
                       "../../../../../Wikis/Meetings/wiki/sources/260310-acme-kickoff.md",
                       "../../../../../Wikis/Meetings/wiki/sources/260310-acme-kickoff",
                       str(kickoff)):
            with self.subTest(target):
                self.assertEqual([kickoff], check.resolve(ws, note, target, files))
                self.assertEqual([kickoff], check.resolve(ws, note, target, list(check.walk_files(self.root))))
        for target in ("260310-acme", "wiki/260310-acme-kickoff", "../260310-acme-kickoff", "./", ""):
            with self.subTest(target):
                self.assertEqual([], check.resolve(ws, note, target, files))

    def test_knowledge_links_cost_one_lookup_each(self):
        concepts = self.knowledge / "wiki" / "concepts"
        n = 300
        for i in range(n):
            write(concepts / ("idea-%d.md" % i), "# Idea\n\nSee [[idea-%d]] and [[wiki/sources/supply-chain-report]].\n"
                  % ((i + 1) % n))
        write(concepts / "leak.md", "As heard in [[260310-acme-kickoff]].\n")
        calls = []
        real = check.rel
        check.rel = lambda ws, path: calls.append(path) or real(ws, path)
        try:
            found = check.check_knowledge(check.discover(self.root))
        finally:
            check.rel = real
        self.assertEqual(["Wikis/Knowledge/wiki/concepts/leak.md"], [f.path for f in found])
        # Once per file to index it, and a few per finding: never once per file per link.
        self.assertLess(len(calls), 4 * n, len(calls))


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class TestHooksPath(GapCase):
    """core.hooksPath set anywhere but a repository's own hooks folder means
    its wall check never runs: from the repository's config, the user's or the
    system's."""

    def setUp(self):
        super().setUp()
        env = mock.patch.dict(os.environ, NO_USER_GIT)
        env.start()
        self.addCleanup(env.stop)
        real_repo(self.work)
        install_wall_hook(self.work)
        real_repo(self.root / "Wikis")

    def test_own_hooks_are_clean(self):
        self.assertClean("hooks")
        git(self.work, "config", "core.hooksPath", ".git/hooks")
        self.assertClean("hooks")
        git(self.work, "config", "core.hooksPath", str(self.work / ".git" / "hooks"))
        self.assertClean("hooks")

    def test_repository_setting(self):
        git(self.work, "config", "core.hooksPath", "/nowhere/hooks")
        found = self.findings("hooks", "warning")
        self.assertEqual(["Zones/Work"], [f.path for f in found])
        self.assertIn("/nowhere/hooks", found[0].message)
        self.assertIn("wall check", found[0].message)
        self.assertIn("git config core.hooksPath .git/hooks", found[0].message)
        self.assertEqual("Git skips the wall check in the Work zone", found[0].ear)

    def test_user_setting_reaches_every_repository(self):
        config = write(self.root.parent / "user.gitconfig", "[core]\n\thooksPath = ~/.githooks\n")
        with mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": str(config)}):
            found = self.findings("hooks", "warning")
            self.assertEqual(["Wikis", "Zones/Work"], sorted(f.path for f in found))  # Personal is not a repository here
            git(self.work, "config", "core.hooksPath", ".git/hooks")  # the fix the message gives
            self.assertEqual(["Wikis"], [f.path for f in self.findings("hooks")])

    def test_a_folder_that_runs_the_wall_check_is_fine(self):
        shared = self.root.parent / "hooks"
        write(shared / "pre-commit", WALL_HOOK).chmod(0o755)
        git(self.work, "config", "core.hooksPath", str(shared))
        self.assertClean("hooks")
        (shared / "pre-commit").write_text("#!/bin/sh\nexit 0\n")
        self.assertEqual(["Zones/Work"], [f.path for f in self.findings("hooks")])


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class TestMeetingsInbox(GapCase):
    """Transcripts wait in Wikis/Meetings/raw/inbox/ and, like a zone's Inbox,
    never enter any history."""

    def setUp(self):
        super().setUp()
        self.wikis = self.root / "Wikis"
        self.inbox = self.meetings / "raw" / "inbox"
        real_repo(self.wikis)
        write(self.wikis / ".gitignore", "Meetings/raw/inbox/*\n!Meetings/raw/inbox/.gitkeep\n")  # as installed
        commit_all(self.wikis, "start")

    def test_a_transcript_waiting_is_untracked_and_clean(self):
        write(self.inbox / "Theo call 2026-03-20.vtt", "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHello.\n")
        self.assertEqual("", git(self.wikis, "status", "--porcelain"))
        commit_all(self.wikis, "nothing to add")
        self.assertEqual("Meetings/raw/inbox/.gitkeep\n", git(self.wikis, "ls-files", "Meetings/raw/inbox"))
        self.assertClean("inbox")

    def test_something_committed_there_is_an_error(self):
        write(self.inbox / "call.vtt", "WEBVTT\n")
        git(self.wikis, "add", "-f", "Meetings/raw/inbox/call.vtt")
        commit_all(self.wikis, "forced in")
        found = self.findings("inbox", "error")
        self.assertEqual(["Wikis/Meetings/raw/inbox/call.vtt"], [f.path for f in found])
        self.assertIn("never committed", found[0].message)
        self.assertEqual("Something in the Meetings inbox was committed", found[0].ear)

    def test_a_recording_instead_of_its_transcript(self):
        write(self.inbox / "call.m4a", "")
        found = self.findings("inbox")
        self.assertEqual([("warning", "Wikis/Meetings/raw/inbox/call.m4a")], [(f.severity, f.path) for f in found])
        self.assertIn("transcript", found[0].message)

    def test_staged_transcript_is_refused(self):
        write(self.inbox / "call.vtt", "WEBVTT\n")
        git(self.wikis, "add", "-f", "Meetings/raw/inbox/call.vtt")
        found = check.run_checks(self.root, staged=self.wikis)
        self.assertEqual([("error", "inbox", "Wikis/Meetings/raw/inbox/call.vtt")],
                         [(f.severity, f.check, f.path) for f in found])


class TestStatusAndDates(GapCase):
    """A status no tool reads, or a date that does not sort, is an error."""

    def setUp(self):
        super().setUp()
        self.hub = self.acme / "Acme Review.md"
        self.note = self.acme / "Threads" / "Pricing" / "Pricing.md"

    def edit(self, path, old, new):
        text = path.read_text()
        self.assertIn(old, text)
        path.write_text(text.replace(old, new, 1))

    def test_the_values_in_use_pass(self):
        for status in ("active", "parked", "Parked   # until the budget is in"):
            with self.subTest(status):
                self.note.write_text(self.note.read_text().replace(
                    self.note.read_text().split("status: ", 1)[1].split("\n", 1)[0], status, 1))
                self.assertClean("threads")
        self.edit(self.hub, "status: active", "status: done")
        self.edit(self.hub, "updated: 2026-03-01", "updated: 2026-09-23  # wrapped")
        self.assertClean("projects")

    def test_thread_status_outside_the_three(self):
        self.edit(self.note, "status: active", "status: closed")
        found = self.findings("threads", "error")
        self.assertEqual(1, len(found), found)
        self.assertIn("'closed'", found[0].message)
        self.assertIn("active, parked or done", found[0].message)

    def test_project_status_outside_the_three(self):
        self.edit(self.hub, "status: active", "status: on-hold")
        found = self.findings("projects", "error")
        self.assertEqual(1, len(found), found)
        self.assertIn("'on-hold'", found[0].message)
        self.assertIn("active, parked or done", found[0].message)

    def test_dates_not_written_iso(self):
        self.edit(self.note, "updated: 2026-03-01", "updated: 23 September 2026")
        self.edit(self.hub, "created: 2026-03-01", "created: 2026-02-30")
        page = self.meetings / "wiki" / "sources" / "260310-acme-kickoff.md"
        self.edit(page, "date: 2026-03-10", "date: 2026-03-10\ncreated: 10/03/2026")
        self.assertIn("`updated` is '23 September 2026'", self.findings("threads", "error")[0].message)
        self.assertIn("`created` is '2026-02-30'", self.findings("projects", "error")[0].message)
        self.assertIn("`created` is '10/03/2026'", self.findings("meetings", "error")[0].message)


class QuoteCase(GapCase):
    def walls(self):
        return [f for f in check.run_checks(self.root) if f.check == "walls"]

    def assertNoLeak(self, findings, *secrets):
        text = check.report_text(findings, self.root) + check.report_ear(findings) + check.report_staged(findings)
        for secret in secrets:
            self.assertNotIn(secret.lower(), text.lower())


class TestUnfinishedPages(QuoteCase):
    """A page without its zone or parties may not be used: its wording is caught, as its links are."""

    def setUp(self):
        super().setUp()
        page = meeting_page("Work", None, "Call").replace("Decisions.", BRIEF + ".")
        write(self.meetings / "wiki" / "sources" / "260318-call.md", page)

    def test_wording_from_an_unfinished_page(self):
        write(self.acme / "Threads" / "Pricing" / "Notes.md", BRIEF + ".\n")
        found = self.walls()
        self.assertEqual(1, len(found), found)
        self.assertEqual("error", found[0].severity)
        self.assertIn("260318-call, an unfinished meeting page", found[0].message)
        self.assertNoLeak(found, *BRIEF_WORDS)

    def test_wording_from_its_raw_record(self):
        write(self.meetings / "raw" / "260319-call.txt", "Dana: we lose the Bergen warehouse lease at the end of the spring quarter.\n")
        write(self.meetings / "wiki" / "sources" / "260319-call.md", meeting_page(None, None, "Second call"))
        write(self.acme / "Deliverables" / "260320 - Note.md", "They lose the Bergen warehouse lease at the end of the spring quarter.\n")
        found = self.walls()
        self.assertEqual(["Zones/Work/Acme Review/Deliverables/260320 - Note.md"], [f.path for f in found])
        self.assertIn("260319-call", found[0].message)

    def test_linked_and_quoted_is_one_finding(self):
        write(self.acme / "Threads" / "Pricing" / "Notes.md", "[[260318-call]]: " + BRIEF + ".\n")
        found = self.walls()
        self.assertEqual(1, len(found), found)
        self.assertIn("uses 260318-call", found[0].message)

    def test_finished_it_is_walled_as_usual(self):
        page = self.meetings / "wiki" / "sources" / "260318-call.md"
        page.write_text(meeting_page("Work", "[acme]", "Call").replace("Decisions.", BRIEF + "."))
        write(self.acme / "Threads" / "Pricing" / "Notes.md", BRIEF + ".\n")
        self.assertEqual([], self.walls())


class TestProjectFiles(QuoteCase):
    """A project's own files are its party's material: a brief or a data file
    pasted across a wall is caught as a meeting would be."""

    def setUp(self):
        super().setUp()
        write(self.acme / "Sources" / "Acme brief.md", "# Brief\n\n" + BRIEF + ".\n")
        write(self.acme / "Sources" / "Acme supplier list.csv", ROWS)
        self.note = self.birch / "Threads" / "Market Sizing" / "Notes.md"

    def test_a_sentence_from_the_brief(self):
        write(self.note, "Worth knowing: " + BRIEF.lower() + ".\n")
        found = self.walls()
        self.assertEqual(1, len(found), found)
        self.assertEqual(("error", "Zones/Work/Birch Entry/Threads/Market Sizing/Notes.md"), (found[0].severity, found[0].path))
        self.assertIn("Zones/Work/Acme Review/Sources/Acme brief.md, in project Acme Review for acme", found[0].message)
        self.assertIn("a wall stands between birch and acme", found[0].message)
        self.assertEqual("A note in Birch Entry's Market Sizing thread quotes a file of Acme Corp", found[0].ear)
        self.assertNoLeak(found, *BRIEF_WORDS)

    def test_rows_of_a_data_file(self):
        write(self.birch / "Deliverables" / "260321 - Suppliers.csv", ROWS.split("\n", 1)[1])
        found = self.walls()
        self.assertEqual(["Zones/Work/Birch Entry/Deliverables/260321 - Suppliers.csv"], [f.path for f in found])
        self.assertNoLeak(found, "halden", "keld", "orrin", "410000")

    def test_the_same_side_passes(self):
        write(self.acme / "Threads" / "Pricing" / "Notes.md", BRIEF + ".\n")
        write(self.acme / "Deliverables" / "260321 - Suppliers.csv", ROWS)
        self.assertEqual([], self.walls())

    def test_a_copy_never_vouches_for_another(self):
        write(self.note, BRIEF + ".\n")
        write(self.birch / "Deliverables" / "260321 - Memo.md", BRIEF + ".\n")
        self.assertEqual(2, len(self.walls()))

    def test_what_a_party_sent_vouches_for_its_notes(self):
        # Both clients sent the same supplier terms: each side quotes its own copy.
        terms = "Rates hold for thirty days from the quote and exclude the quarterly fuel surcharge"
        write(self.acme / "Sources" / "Carrier terms.md", terms + ".\n")
        write(self.birch / "Sources" / "Carrier terms.md", terms + ".\n")
        write(self.note, "Carrier says: " + terms.lower() + ".\n")
        self.assertEqual([], self.walls())

    def test_notes_copied_across_both_named(self):
        # Wording that sits in notes on both sides and nowhere else: the check
        # cannot tell which came first, so it names both.
        line = "Pallet volumes fall by a fifth when the northern depot closes for refitting"
        write(self.acme / "Threads" / "Pricing" / "Notes.md", line + ".\n")
        write(self.note, line + ".\n")
        self.assertEqual(["Zones/Work/Acme Review/Threads/Pricing/Notes.md",
                          "Zones/Work/Birch Entry/Threads/Market Sizing/Notes.md"], sorted(f.path for f in self.walls()))

    def test_a_meeting_is_named_before_a_file(self):
        page = meeting_page("Work", "[acme]", "Acme call").replace("Decisions.", BRIEF + ".")
        write(self.meetings / "wiki" / "sources" / "260315-acme-call.md", page)
        write(self.note, BRIEF + ".\n")
        found = self.walls()
        self.assertEqual(1, len(found), found)
        self.assertIn("meeting 260315-acme-call", found[0].message)

    def test_published_wording_and_templates_cross_every_wall(self):
        write(self.knowledge / "raw" / "plant-report.txt", "Reported: " + BRIEF + ".\n")
        write(self.note, BRIEF + ".\n")
        self.assertEqual([], self.walls())
        (self.knowledge / "raw" / "plant-report.txt").unlink()
        disclaimer = "This memo was prepared for its addressee alone and relies on figures supplied by the client"
        write(self.acme / "Deliverables" / "260321 - Memo.md", disclaimer + ".\n")
        write(self.birch / "Deliverables" / "260321 - Memo.md", disclaimer + ".\n")
        self.assertEqual(3, len(self.walls()))  # the note, and the memo on each side
        write(self.root / "System" / "templates" / "memo.md", disclaimer + ".\n")
        self.assertEqual(["Zones/Work/Birch Entry/Threads/Market Sizing/Notes.md"], [f.path for f in self.walls()])

    def test_same_day_wraps_are_not_quotes(self):
        # "Close for the day" wraps every thread worked on: the same date, the same headings.
        for project, thread, waiting in ((self.acme, "Pricing", "Owen's quote"), (self.birch, "Market Sizing", "the board")):
            note = project / "Threads" / thread / (thread + ".md")
            note.write_text(note.read_text().split("## State of play")[0]
                            + "## State of play\n\n### Resume here\n\n**Where it stands, 3 October 2026.** Waiting on %s.\n\n"
                              "| | |\n|---|---|\n| Waiting on | %s |\n| Deadline | 9 October 2026 |\n\n---\n\n"
                              "**3 October 2026.** Wrapped.\n\n**2 October 2026.** Wrapped.\n" % (waiting, waiting))
        self.assertEqual([], self.walls())

    @unittest.skipUnless(HAVE_GIT, "git is not installed")
    def test_the_hook_refuses_it(self):
        real_repo(self.work)
        with mock.patch.dict(os.environ, NO_USER_GIT):
            commit_all(self.work, "start")
            write(self.note, BRIEF + ".\n")
            git(self.work, "add", "-A")
            found = check.run_checks(self.root, staged=self.work)
        self.assertEqual([("error", "Zones/Work/Birch Entry/Threads/Market Sizing/Notes.md")],
                         [(f.severity, f.path) for f in found])
        self.assertNoLeak(found, *BRIEF_WORDS)


class TestPersonPages(GapCase):
    """A person page says who someone is and which party: read on both sides of every wall."""

    def setUp(self):
        super().setUp()
        self.people = self.meetings / "wiki" / "people"
        page = meeting_page("Work", "[birch]", "Birch call").replace("Decisions.", BRIEF + ".")
        write(self.meetings / "wiki" / "sources" / "260314-birch-call.md", page)

    def person(self, party="birch", body="Managing partner of Birch & Co."):
        party_line = "party: %s\n" % party if party is not None else ""
        return write(self.people / "theo-marsh.md", "---\ntitle: Theo Marsh\ntype: person\n%screated: 2026-03-12\n"
                     "updated: 2026-03-12\n---\n\n# Theo Marsh\n\n%s\n" % (party_line, body))

    def test_a_finished_page_and_no_party_at_all(self):
        self.person()
        self.assertClean("people")
        self.person(party="none", body="A friend; belongs to no party.")
        self.assertClean("people")

    def test_party_missing_or_unknown(self):
        self.person(party=None)
        found = self.findings("people")
        self.assertEqual([("warning", "Wikis/Meetings/wiki/people/theo-marsh.md")], [(f.severity, f.path) for f in found])
        self.assertIn("party: none", found[0].message)
        self.person(party="cedar")
        self.assertIn("`cedar`", self.findings("people", "error")[0].message)

    def test_type_and_dates(self):
        self.person().write_text(self.person().read_text().replace("type: person", "type: contact")
                                 .replace("updated: 2026-03-12", "updated: March 2026"))
        self.assertEqual(["error", "warning"], sorted(f.severity for f in self.findings("people")))

    def test_wording_from_a_meeting(self):
        self.person(body="Managing partner. Said that " + BRIEF.lower() + ".")
        found = self.findings("people", "warning")
        self.assertEqual(1, len(found), found)
        self.assertIn("meeting 260314-birch-call", found[0].message)
        for word in BRIEF_WORDS:
            self.assertNotIn(word, (found[0].message + found[0].ear).lower())

    def test_wording_from_a_transcript(self):
        write(self.meetings / "raw" / "260314-birch-call.txt", "Theo: our pallet volumes fall by a fifth whenever the northern depot shuts.\n")
        self.person(body="Thinks pallet volumes fall by a fifth whenever the northern depot shuts.")
        self.assertIn("260314-birch-call", self.findings("people", "warning")[0].message)

    def test_wording_every_side_reads_is_fine(self):
        role = "Managing partner who chairs the board and signs every carrier contract himself"
        ctx = self.root / "System" / "context.md"
        ctx.write_text(ctx.read_text().replace("| Theo Marsh | `birch` | Managing partner |", "| Theo Marsh | `birch` | %s |" % role))
        write(self.meetings / "wiki" / "sources" / "260316-birch-board.md",
              meeting_page("Work", "[birch]", "Board").replace("Decisions.", "Attending: Theo Marsh, %s." % role.lower()))
        self.person(body=role + ".")
        self.assertClean("people")


class TestKnowledgePages(GapCase):
    """Knowledge carries no party, and no meeting's wording: what is there is common to every side."""

    def setUp(self):
        super().setUp()
        page = meeting_page("Work", "[birch]", "Birch call").replace("Decisions.", BRIEF + ".")
        write(self.meetings / "wiki" / "sources" / "260314-birch-call.md", page)
        self.page = self.knowledge / "wiki" / "concepts" / "plants.md"

    def test_party_singular_is_refused_like_parties(self):
        write(self.page, "---\ntitle: Plants\ntype: concept\nparty: birch\n---\n\n# Plants\n")
        found = self.findings("knowledge", "error")
        self.assertEqual(["Wikis/Knowledge/wiki/concepts/plants.md"], [f.path for f in found])
        self.assertIn("`party`", found[0].message)

    def test_a_page_repeating_a_meeting(self):
        write(self.page, "# Plants\n\nReported: " + BRIEF + ".\n")
        found = self.findings("knowledge")
        self.assertEqual([("warning", "Wikis/Knowledge/wiki/concepts/plants.md")], [(f.severity, f.path) for f in found])
        self.assertIn("meeting 260314-birch-call", found[0].message)
        for word in BRIEF_WORDS:
            self.assertNotIn(word, found[0].message.lower())

    def test_a_raw_record_repeating_a_transcript(self):
        write(self.meetings / "raw" / "260314-birch-call.vtt",
              "WEBVTT\n\n00:00:01.000 --> 00:00:04.000\n<v Theo Marsh>Pallet volumes fall by a fifth\n\n"
              "00:00:04.500 --> 00:00:08.000\n<v Theo Marsh>whenever the northern depot shuts.\n")
        write(self.knowledge / "raw" / "depot-mail.eml", "From: a@b.example\nSubject: Depots\n\n"
              "Pallet volumes fall by a fifth whenever the northern depot shuts.\n")
        found = self.findings("knowledge", "warning")
        self.assertEqual(["Wikis/Knowledge/raw/depot-mail.eml"], [f.path for f in found])

    def test_laundered_wording_still_shows(self):
        # Copied into Knowledge, the wording becomes common and a walled note
        # repeating it passes the walls: the Knowledge page is where it shows.
        write(self.knowledge / "raw" / "depot-article.txt", "Report: " + BRIEF + ".\n")
        write(self.acme / "Threads" / "Pricing" / "Notes.md", BRIEF + ".\n")
        self.assertEqual([], self.findings("walls"))
        self.assertEqual(["Wikis/Knowledge/raw/depot-article.txt"], [f.path for f in self.findings("knowledge", "warning")])

    def test_wording_the_instructions_share_is_fine(self):
        rule = "Before material from a meeting goes into a project's notes compare the project's party with the meeting's parties"
        write(self.root / "System" / "rules.md", "# Rules\n\n" + rule + ".\n")
        write(self.meetings / "wiki" / "sources" / "260316-birch-wrap.md",
              meeting_page("Work", "[birch]", "Wrap").replace("Decisions.", "As the rules say: " + rule.lower() + "."))
        write(self.page, "# Walls\n\n" + rule + ".\n")
        self.assertClean("knowledge")


if __name__ == "__main__":
    unittest.main()
