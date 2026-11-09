"""What the check promises and now holds: the gaps between the rules and the
check, each closed with a case that must be caught and one that must pass.

Invented parties only: Acme Corp (`acme`) and Birch & Co (`birch`), walled
from each other, as in fixtures.py.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fixtures import HAVE_GIT, build_workspace, commit_all, git, meeting_page, project_hub, thread_note, write

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
class TestProjectRepositories(GapCase):
    """A git repository inside a project, often pushed somewhere public, gets
    the wall check too, on its project's side of the walls."""

    def setUp(self):
        super().setUp()
        env = mock.patch.dict(os.environ, NO_USER_GIT)
        env.start()
        self.addCleanup(env.stop)
        tools = Path(check.__file__).resolve().parent
        (self.root / "System" / "tools").mkdir(parents=True, exist_ok=True)
        for name in ("check.py", "garrick_lib.py"):              # what the hook looks up for
            shutil.copy(tools / name, self.root / "System" / "tools" / name)
        self.site = self.acme / "Site"
        self.site.mkdir()
        git(self.site, "init", "-q")
        git(self.site, "config", "user.email", "jo@example.invalid")
        git(self.site, "config", "user.name", "Jo")
        write(self.meetings / "wiki" / "sources" / "260312-birch-call.md", meeting_page("Work", "[birch]", "Birch call"))

    def commit(self, name, text):
        write(self.site / name, text)
        git(self.site, "add", name)
        return subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=str(self.site), capture_output=True, text=True)

    def test_without_a_remote_nothing_is_said(self):
        self.assertEqual([], [f for f in self.findings("hooks") if "Site" in f.path])

    def test_a_remote_and_no_hook_is_a_warning(self):
        git(self.site, "remote", "add", "origin", "https://example.invalid/site.git")
        [found] = [f for f in self.findings("hooks") if "Site" in f.path]
        self.assertIn("--install-hooks", found.message)
        self.assertIn("Acme Review", found.message)

    def test_install_hooks_reaches_it_and_its_commits_are_checked(self):
        git(self.site, "remote", "add", "origin", "https://example.invalid/site.git")
        with mock.patch("sys.stdout"), mock.patch("sys.stderr"):
            check.install_hooks(self.root)
        self.assertEqual([], [f for f in self.findings("hooks") if "Site" in f.path])
        self.assertEqual(0, self.commit("index.md", "# Acme site\n\nAbout us.\n").returncode)
        refused = self.commit("notes.md", "Background: [[260312-birch-call]]\n")
        self.assertNotEqual(0, refused.returncode)
        self.assertIn("Commit refused", refused.stderr + refused.stdout)


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

    def _quoted_from(self, record, field, value, slug="260319-call"):
        write(self.meetings / "raw" / record, "Dana: we lose the Bergen warehouse lease at the end of the spring quarter.\n")
        page = meeting_page(None, None, "Second call").replace("type: meeting", "type: meeting\n%s: \"%s\"" % (field, value))
        write(self.meetings / "wiki" / "sources" / (slug + ".md"), page)
        write(self.acme / "Deliverables" / "260320 - Note.md", "They lose the Bergen warehouse lease at the end of the spring quarter.\n")
        return self.walls()

    def test_wording_from_a_raw_record_in_a_subfolder(self):
        found = self._quoted_from("2026/03/260319-call.txt", "raw", "[[raw/2026/03/260319-call.txt]]")
        self.assertEqual(["Zones/Work/Acme Review/Deliverables/260320 - Note.md"], [f.path for f in found])
        self.assertIn("260319-call", found[0].message)

    def test_wording_from_a_subfolder_record_found_by_the_slug(self):
        found = self._quoted_from("calls/260319-call.txt", "title2", "x")
        self.assertEqual(1, len(found), found)

    def test_a_transcript_field_names_the_record_too(self):
        found = self._quoted_from("calls/2026-03-19 call with acme.txt", "transcript",
                                  "[[calls/2026-03-19 call with acme]]", slug="260319-second-call")
        self.assertEqual(1, len(found), found)
        self.assertIn("260319-second-call", found[0].message)

    def test_a_record_of_the_same_name_elsewhere_lends_no_owner(self):
        write(self.meetings / "raw" / "260319-call.txt", "Dana: we lose the Bergen warehouse lease at the end of the spring quarter.\n")
        write(self.meetings / "raw" / "2026" / "260319-call.txt", "Theo: our launch is in May.\n")
        write(self.meetings / "wiki" / "sources" / "260319-call.md", meeting_page("Work", "[birch]", "Birch call").replace(
            "type: meeting", 'type: meeting\nraw: "[[raw/260319-call]]"'))
        write(self.meetings / "wiki" / "sources" / "260319-call-acme.md", meeting_page("Work", "[acme]", "Acme call").replace(
            "type: meeting", 'type: meeting\nraw: "[[raw/2026/260319-call]]"'))
        write(self.acme / "Deliverables" / "260320 - Note.md", "They lose the Bergen warehouse lease at the end of the spring quarter.\n")
        found = [f for f in self.walls() if "Note.md" in f.path]
        self.assertEqual(1, len(found), found)
        self.assertIn("is walled and", found[0].message)

    def test_the_inbox_is_still_not_a_record(self):
        write(self.meetings / "raw" / "inbox" / "260319-call.txt",
              "Dana: we lose the Bergen warehouse lease at the end of the spring quarter.\n")
        write(self.meetings / "wiki" / "sources" / "260319-call.md", meeting_page(None, None, "Second call"))
        write(self.acme / "Deliverables" / "260320 - Note.md", "They lose the Bergen warehouse lease at the end of the spring quarter.\n")
        self.assertEqual([], [f for f in self.walls() if "260319" in f.message])

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


class TestSplitPages(GapCase):
    """One record, a page per project: declared with split-with, each page
    read with its own parties."""

    def setUp(self):
        super().setUp()
        write(self.meetings / "raw" / "260310-weekly.txt", "Jo: Acme first. Then Birch.\n")

    def page(self, slug, parties, others):
        text = meeting_page("Work", parties, slug).replace(
            "type: meeting", 'type: meeting\nraw: "[[raw/260310-weekly]]"' +
            ("\nsplit-with: [%s]" % ", ".join('"[[%s]]"' % o for o in others) if others is not None else ""))
        write(self.meetings / "wiki" / "sources" / (slug + ".md"), text)

    def splits(self):
        return [f for f in self.findings("meetings", "error") if "split-with" in f.message]

    def test_a_two_way_split_that_names_each_other_is_fine(self):
        self.page("260310-weekly-acme", "[acme]", ["260310-weekly-birch"])
        self.page("260310-weekly-birch", "[birch]", ["260310-weekly-acme"])
        self.assertEqual([], self.splits())

    def test_a_three_way_split_names_every_other(self):
        self.page("260310-weekly-acme", "[acme]", ["260310-weekly-birch", "260310-weekly-cedar"])
        self.page("260310-weekly-birch", "[birch]", ["260310-weekly-acme", "260310-weekly-cedar"])
        self.page("260310-weekly-cedar", "[acme]", ["260310-weekly-acme"])
        [found] = self.splits()
        self.assertEqual("Wikis/Meetings/wiki/sources/260310-weekly-cedar.md", found.path)
        self.assertIn("260310-weekly-birch", found.message)

    def test_a_shared_record_without_split_with_is_reported(self):
        self.page("260310-weekly-acme", "[acme]", None)
        self.page("260310-weekly-birch", "[birch]", None)
        self.assertEqual(2, len(self.splits()))

    def test_each_page_is_walled_by_its_own_parties(self):
        self.page("260310-weekly-acme", "[acme]", ["260310-weekly-birch"])
        self.page("260310-weekly-birch", "[birch]", ["260310-weekly-acme"])
        write(self.acme / "Threads" / "Pricing" / "Notes.md", "From the call: [[260310-weekly-acme]].\n")
        self.assertEqual([], [f for f in self.findings("walls") if "Notes.md" in f.path])
        write(self.acme / "Threads" / "Pricing" / "Notes.md", "From the call: [[260310-weekly-birch]].\n")
        self.assertTrue([f for f in self.findings("walls") if "Notes.md" in f.path])


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
        self.assertIn("acme is walled and this project does not name it", found[0].message)
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


class TestFadedMeetings(GapCase):
    """A meeting page that faded, dormant or archived, still holds its parties
    against every commit."""

    @unittest.skipUnless(HAVE_GIT, "git is not installed")
    def test_the_hook_refuses_a_link_to_a_faded_meeting(self):
        for grade in ("dormant", "archive"):
            moved = self.meetings / grade / "wiki" / "sources" / "260312-birch-kickoff.md"
            moved.parent.mkdir(parents=True)
            (self.meetings / "wiki" / "sources" / moved.name).rename(moved)
            real_repo(self.work)
            note = self.acme / "Threads" / "Pricing" / "Notes.md"
            with mock.patch.dict(os.environ, NO_USER_GIT):
                commit_all(self.work, "start")
                write(note, "See [[%s/wiki/sources/260312-birch-kickoff|the call]].\n" % grade)
                git(self.work, "add", "-A")
                found = check.run_checks(self.root, staged=self.work)
            self.assertEqual([("error", "Zones/Work/Acme Review/Threads/Pricing/Notes.md")],
                             [(f.severity, f.path) for f in found], grade)
            self.assertIn("a meeting with birch", found[0].message)
            moved.rename(self.meetings / "wiki" / "sources" / moved.name)


class TestMeetingsQuestions(QuoteCase):
    """A Meetings question (#224) holds its parties against every commit, as a
    meeting page does, and its wording is a conversation's material."""

    def setUp(self):
        super().setUp()
        self.question = self.meetings / "questions" / "260314 - plan-check.md"
        write(self.question, "---\ntype: question\nasked: 2026-03-14\nstatus: open\nzone: Work\nparties: [birch]\n"
                             "origin: \"[[raw/260312-birch-kickoff]]\"\n---\n\n**Birch: does the plan still hold?**\n\n"
                             + BRIEF + ".\n")

    @unittest.skipUnless(HAVE_GIT, "git is not installed")
    def test_the_hook_refuses_a_link_to_a_walled_question_even_once_it_is_deleted(self):
        real_repo(self.work)
        real_repo(self.root / "Wikis")
        note = self.acme / "Threads" / "Pricing" / "Notes.md"
        with mock.patch.dict(os.environ, NO_USER_GIT):
            commit_all(self.work, "start")
            commit_all(self.root / "Wikis", "start")
            write(note, "See [[260314 - plan-check]].\n")
            git(self.work, "add", "-A")
            for deleted in (False, True):
                if deleted:
                    self.question.unlink()       # gone from disk, still in the Wikis history
                found = check.run_checks(self.root, staged=self.work)
                self.assertEqual([("error", "Zones/Work/Acme Review/Threads/Pricing/Notes.md")],
                                 [(f.severity, f.path) for f in found], deleted)
                self.assertIn("birch is walled and this project does not name it", found[0].message)
                self.assertNoLeak(found, *BRIEF_WORDS)

    @unittest.skipUnless(HAVE_GIT, "git is not installed")
    def test_the_hook_refuses_a_link_to_a_walled_question_in_a_subfolder(self):
        moved = self.meetings / "questions" / "answered" / self.question.name
        moved.parent.mkdir()
        self.question.rename(moved)
        real_repo(self.work)
        real_repo(self.root / "Wikis")
        note = self.acme / "Threads" / "Pricing" / "Notes.md"
        with mock.patch.dict(os.environ, NO_USER_GIT):
            commit_all(self.work, "start")
            commit_all(self.root / "Wikis", "start")
            write(note, "See [[260314 - plan-check]].\n")
            git(self.work, "add", "-A")
            for deleted in (False, True):
                if deleted:
                    moved.unlink()               # gone from disk, still in the Wikis history
                found = check.run_checks(self.root, staged=self.work)
                self.assertEqual([("error", "Zones/Work/Acme Review/Threads/Pricing/Notes.md")],
                                 [(f.severity, f.path) for f in found], deleted)
                self.assertIn("a question with birch", found[0].message)

    @unittest.skipUnless(HAVE_GIT, "git is not installed")
    def test_the_hook_refuses_a_link_to_a_walled_raw_answer_even_once_it_is_deleted(self):
        answer = self.meetings / "raw" / "answers" / "260315 - plan-check.md"
        write(answer, "---\ntype: answer\nanswered: 2026-03-15\nzone: Work\nparties: [birch]\n"
                      "question: \"[[questions/260314 - plan-check]]\"\n---\n\nQuestion: Birch: does the plan hold?\n\n```\n"
                      + BRIEF + ".\n```\n")
        real_repo(self.work)
        real_repo(self.root / "Wikis")
        note = self.acme / "Threads" / "Pricing" / "Notes.md"
        with mock.patch.dict(os.environ, NO_USER_GIT):
            commit_all(self.work, "start")
            commit_all(self.root / "Wikis", "start")
            write(note, "See [[260315 - plan-check]].\n")
            git(self.work, "add", "-A")
            for deleted in (False, True):
                if deleted:
                    answer.unlink()              # gone from disk, still in the Wikis history
                found = check.run_checks(self.root, staged=self.work)
                self.assertEqual([("error", "Zones/Work/Acme Review/Threads/Pricing/Notes.md")],
                                 [(f.severity, f.path) for f in found], deleted)
                self.assertIn("a reply with birch", found[0].message)
                self.assertNoLeak(found, *BRIEF_WORDS)

    @unittest.skipUnless(HAVE_GIT, "git is not installed")
    def test_a_near_side_question_deleted_from_disk_still_never_vouches(self):
        # Acme's own question holds the wording a Birch meeting holds; deleted
        # from disk and read from git, it must still not clear the quotation.
        self.question.unlink()
        page = self.meetings / "wiki" / "sources" / "260312-birch-kickoff.md"
        page.write_text(page.read_text().replace("Decisions.", BRIEF + "."))
        near = self.meetings / "questions" / "260314 - near.md"
        write(near, "---\ntype: question\nasked: 2026-03-14\nstatus: open\nzone: Work\nparties: [acme]\n---\n\n"
                    "**Acme: does the plan still hold?**\n\n" + BRIEF + ".\n")
        real_repo(self.work)
        real_repo(self.root / "Wikis")
        note = self.acme / "Threads" / "Pricing" / "Notes.md"
        with mock.patch.dict(os.environ, NO_USER_GIT):
            commit_all(self.work, "start")
            commit_all(self.root / "Wikis", "start")
            near.unlink()
            write(note, BRIEF + ".\n")
            git(self.work, "add", "-A")
            found = check.run_checks(self.root, staged=self.work)
        self.assertEqual([("error", "Zones/Work/Acme Review/Threads/Pricing/Notes.md")],
                         [(f.severity, f.path) for f in found])
        self.assertIn("repeats wording from meeting 260312-birch-kickoff, a meeting with birch", found[0].message)
        self.assertNoLeak(found, *BRIEF_WORDS)

    def test_a_knowledge_page_repeating_a_question_is_named(self):
        write(self.knowledge / "wiki" / "concepts" / "plants.md", "# Plants\n\nReported: " + BRIEF + ".\n")
        found = self.findings("knowledge", "warning")
        self.assertEqual(["Wikis/Knowledge/wiki/concepts/plants.md"], [f.path for f in found])
        self.assertIn("with question 260314 - plan-check; wording in Knowledge", found[0].message)
        self.assertIn("If the question quoted", found[0].message)
        self.assertEqual("A Knowledge page repeats a Meetings question", found[0].ear)


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


class TestNearSidePersonPartyTag(GapCase):
    """A person who is a party, and also on the near side of a wall as themselves,
    is not caught through the party's tag (#98)."""

    def setUp(self):
        super().setUp()
        ctx_file = self.root / "System" / "context.md"
        ctx = ctx_file.read_text()
        ctx = ctx.replace(
            "| Birch & Co | Client. Market-entry advice; competes with Acme | Work | `birch` | yes | birchco.example, mail.birchco.example |\n",
            "| Birch & Co | Client. Market-entry advice; competes with Acme | Work | `birch` | yes | birchco.example, mail.birchco.example |\n"
            "| Dana Rossi | Advisor | Work | `rossi` | yes | |\n"
        )
        ctx = ctx.replace(
            "| `acme` | `birch` | Competitors, and both are clients |\n",
            "| `acme` | `birch` | Competitors, and both are clients |\n"
            "| `acme` | `rossi` | Walled |\n"
        )
        ctx = ctx.replace(
            "| Theo Marsh | `birch` | Managing partner |\n",
            "| Theo Marsh | `birch` | Managing partner |\n"
            "| Dana Rossi | `rossi` | Principal |\n"
        )
        self.ctx_without_near_side = ctx
        self.ctx_with_near_side = ctx.replace(
            "| Dana Rossi | `rossi` | Principal |\n",
            "| Dana Rossi | `rossi` | Principal |\n"
            "| Dana Rossi | `acme` | Advisor |\n"
        )
        self.ctx_file = ctx_file
        self.note = self.acme / "Threads" / "Pricing" / "Pricing.md"

    def test_near_side_person_clears_party_tag(self):
        self.ctx_file.write_text(self.ctx_with_near_side)
        write(self.note, thread_note("Acme Review", "Pricing", "acme", "Dana Rossi joined the pilot."))
        self.assertEqual([], [f for f in self.findings("walls") if "Pricing.md" in f.path])

        write(self.note, thread_note("Acme Review", "Pricing", "acme", "Rossi joined the pilot."))
        self.assertEqual([], [f for f in self.findings("walls") if "Pricing.md" in f.path])

    def test_without_near_side_person_breach_is_reported(self):
        self.ctx_file.write_text(self.ctx_without_near_side)
        write(self.note, thread_note("Acme Review", "Pricing", "acme", "Dana Rossi joined the pilot."))
        found = [f for f in self.findings("walls") if "Pricing.md" in f.path]
        self.assertEqual(1, len(found), found)
        self.assertIn("names Dana Rossi", found[0].message)
        self.assertNotIn('(as "rossi")', found[0].message)

        write(self.note, thread_note("Acme Review", "Pricing", "acme", "Rossi joined the pilot."))
        found = [f for f in self.findings("walls") if "Pricing.md" in f.path]
        self.assertEqual(1, len(found), found)
        self.assertIn('names Dana Rossi (as "rossi")', found[0].message)


class TestSharedSurname(GapCase):
    def test_far_side_party_word_in_near_side_person(self):
        ctx_file = self.root / "System" / "context.md"
        ctx = ctx_file.read_text().replace(
            "| Dana Whitlock | `acme` | Head of procurement |\n",
            "| Dana Whitlock | `acme` | Head of procurement |\n| Anna Birch | `acme` | Analyst |\n")
        ctx_file.write_text(ctx)
        note = self.acme / "Threads" / "Pricing" / "Pricing.md"
        write(note, thread_note("Acme Review", "Pricing", "acme", "Birch is pricing below us."))
        found = [f for f in self.findings("walls") if "Pricing.md" in f.path]
        self.assertEqual(1, len(found), found)




class TestProjectLinks(GapCase):
    """A link or a path into a note of a project walled from this one is
    refused, by the commit hook and the full check alike, whether or not the
    path holds a name of the far party. Northwind is for Acme, Harbour for
    Birch, Lantern for Cobalt, which no wall keeps from either."""

    TAIL = ", a note of birch; birch is walled and this project does not name it"
    WALLED = ("[[Harbour/Threads/Tender/Tender]]",                 # a wikilink by its path
              "[[Tender|the tender]]",                             # a bare name, a thread only Harbour has
              "[[Harbour]]",                                       # the hub
              "`Harbour/Threads/Tender/Tender.md`",                # a path written as code
              "``Harbour/Threads/Tender/Tender.md``",              # in a longer run of backticks
              "[the tender](../../../Harbour/Threads/Tender/Tender.md)",
              "[the model](<../../../Harbour/Threads/Tender/Bid model.md>)",
              "[the tender][1]\n\n[1]: ../../../Harbour/Threads/Tender/Tender.md\n",
              '<a href="../../../Harbour/Threads/Tender/Tender.md">the tender</a>',
              "\n~~~\nHarbour/Threads/Tender/Tender.md\n~~~\n",     # a fence of tildes
              "\n```\nHarbour/Threads/Tender/Tender.md\n```\n",
              "obsidian://open?vault=Workspace&file=Zones%2FWork%2FHarbour%2FThreads%2FTender%2FTender",
              "[Bid brief (1).md](Zones/Work/Harbour/Sources/Bid%20brief%20(1).md)",   # as Obsidian writes one
              "[Bid brief (1).md](../../../Harbour/Sources/Bid%20brief%20(1).md)")
    OPEN = ("[[Lantern/Threads/Survey/Survey]]", "[[Survey]]", "`Lantern/Threads/Survey/Survey.md`",
            "[[Freight]]", "`Threads/Freight/Freight.md`", "[[Northwind/Threads/Freight/Freight]]")

    def setUp(self):
        super().setUp()
        self.build()

    def build(self):
        ctx = self.root / "System" / "context.md"
        ctx.write_text(ctx.read_text().replace(
            "mail.birchco.example |\n",
            "mail.birchco.example |\n| Cobalt Ltd | Client. Logistics audit | Work | `cobalt` | no | cobalt.example |\n", 1))
        for name, party, thread in (("Northwind", "acme", "Freight"), ("Harbour", "birch", "Tender"),
                                    ("Lantern", "cobalt", "Survey")):
            self.project(name, party, thread)
        write(self.work / "Harbour" / "Threads" / "Tender" / "Bid model.md", "# Bid model\n")
        write(self.work / "Harbour" / "Sources" / "Bid brief (1).md", "# Bid brief, as sent\n")
        self.note = self.work / "Northwind" / "Threads" / "Freight" / "Notes.md"
        self.where = "Zones/Work/Northwind/Threads/Freight/Notes.md"

    def project(self, name, party, *threads):
        folder = self.work / name
        write(folder / (name + ".md"), project_hub("Work", name, party, list(threads)))
        for thread in threads:
            write(folder / "Threads" / thread / (thread + ".md"), thread_note(name, thread, party))
        return folder

    def walls(self, where=None):
        return [f for f in self.findings("walls") if f.path == (where or self.where)]

    def says(self, written):
        write(self.note, "# Notes\n\nSee %s now.\n" % written)
        return [(f.severity, f.message) for f in self.walls()]

    def test_each_way_in_is_refused_by_the_full_check(self):
        self.assertEqual([], self.walls())
        for written in self.WALLED:
            with self.subTest(written):
                write(self.note, "# Notes\n\nSee %s now.\n" % written)
                found = self.walls()
                self.assertEqual(["error"], [f.severity for f in found], found)
                self.assertTrue(found[0].message.endswith(self.TAIL), found[0].message)
                self.assertEqual("A note in Northwind's Freight thread uses a note of Birch & Co", found[0].ear)


    def test_the_finding_names_the_link_and_the_party_only(self):
        self.assertEqual([("error", "writes the path `Harbour/Threads/Tender/Tender.md`" + self.TAIL)],
                         self.says("`Harbour/Threads/Tender/Tender.md`"))

    def test_an_unwalled_project_and_the_project_itself_pass(self):
        write(self.note, "# Notes\n\n%s\n" % "\n".join("See %s." % w for w in self.OPEN))
        self.assertEqual([], self.walls())

    def test_a_name_both_projects_hold_is_read_as_obsidian_reads_it(self):
        self.project("Northwind", "acme", "Freight", "Rates")
        self.project("Harbour", "birch", "Tender", "Rates")
        # From the Freight thread neither is under the note's folder, and Harbour's path is the shorter.
        self.assertEqual([("error", "links [[Rates]]" + self.TAIL)], self.says("[[Rates]]"))
        # Under the note's own folder, a subfolder's included, Obsidian takes this project's.
        for beside in ("Threads/Rates/Notes.md", "Notes.md"):
            with self.subTest(beside):
                note = self.work / "Northwind" / beside
                write(note, "# Notes\n\nSee [[Rates]].\n")
                self.assertEqual([], self.walls("Zones/Work/Northwind/" + beside))
        # A path written as code that lands in this project means it, wherever it is.
        self.assertEqual([], self.says("`Rates/Rates.md`"))

    def test_a_short_name_a_wiki_page_holds_too(self):
        write(self.work / "Harbour" / "Sources" / "Okta.md", "# Okta, as sent\n")
        write(self.knowledge / "wiki" / "entities" / "Okta.md", "# Okta\n")
        # Harbour's path is shorter than the Knowledge page's: Obsidian opens Harbour's.
        self.assertEqual([("error", "links [[Okta]]" + self.TAIL)], self.says("[[Okta]]"))
        sources = self.work / "Harbour" / "Sources"
        (sources / "Vendors").mkdir()
        (sources / "Okta.md").rename(sources / "Vendors" / "Okta.md")       # now the longer path
        self.assertEqual([], self.says("[[Okta]]"))
        (self.root / ".obsidian").mkdir()
        self.assertEqual([], self.says("[[Okta]]"))
        # A vault over the zone as well: there the Knowledge page is not there to open, and every vault counts.
        (self.work / ".obsidian").mkdir()
        self.assertEqual([("error", "links [[Okta]]" + self.TAIL)], self.says("[[Okta]]"))


    def test_the_note_folder_is_a_plain_prefix(self):
        # As Obsidian compares it: Harbour's path starts with "Zones/Work/Har".
        self.project("Har", "acme")
        self.project("Lim", "cobalt")
        write(self.work / "Harbour" / "Threads" / "Rates" / "Rates.md", thread_note("Harbour", "Rates", "birch"))
        write(self.work / "Lim" / "Rates.md", "# Rates\n")
        hub = self.work / "Har" / "Har.md"
        hub.write_text(hub.read_text() + "\nSee [[Rates]].\n")
        self.assertEqual([("error", "links [[Rates]]" + self.TAIL)],
                         [(f.severity, f.message) for f in self.walls("Zones/Work/Har/Har.md")])
        # And a sibling folder that starts with the note's folder's name comes first too.
        write(self.work / "Northwind" / "Threads" / "Freight 2" / "Plan.md", "# Plan\n")
        write(self.work / "Harbour" / "Plan.md", "# Plan\n")
        self.assertEqual([], self.says("[[Plan]]"))


    def test_what_obsidian_indexes_counts(self):
        harbour = self.work / "Harbour"
        (harbour / "Code" / ".git").mkdir(parents=True)                     # a repository of its own
        write(harbour / "Code" / "docs" / "Spec.md", "# Spec\n")
        write(harbour / "node_modules" / "kit" / "Kit notes.md", "# Kit\n")
        write(harbour / ".hidden" / "Hidden plan.md", "# Hidden\n")        # Obsidian leaves dot-folders out
        self.assertEqual([("error", "links [[Spec]]" + self.TAIL)], self.says("[[Spec]]"))
        self.assertEqual([("error", "links [[Kit notes]]" + self.TAIL)], self.says("[[Kit notes]]"))
        self.assertEqual([], self.says("[[Hidden plan]]"))



    def test_a_name_with_a_dot_is_a_note_too(self):
        tender = self.work / "Harbour" / "Threads" / "Tender"
        write(tender / "Sizing v1.2.md", "# Sizing\n")
        write(tender / "St. Louis plan.md", "# Plan\n")
        for written in ("[[Sizing v1.2]]", "[[St. Louis plan]]", "[[Tender/Sizing v1.2]]"):
            with self.subTest(written):
                self.assertEqual([("error", "links %s%s" % (written, self.TAIL))], self.says(written))

    def test_an_anchor_with_angle_brackets_in_a_quoted_value(self):
        self.assertEqual("error", self.says('<a title="a<b" href="../../../Harbour/Threads/Tender/Tender.md">t</a>')[0][0])



    def test_a_hub_name_names_its_project(self):
        write(self.work / "Lantern" / "Notes" / "Harbour.md", "# Harbour, the port\n")
        self.assertEqual([("error", "links [[Harbour]]" + self.TAIL)], self.says("[[Harbour]]"))

    def test_threads_of_one_project_written_for_walled_parties(self):
        lantern = self.project("Lantern", "cobalt", "Survey", "Audit", "Secret")
        write(lantern / "Threads" / "Audit" / "Audit.md", thread_note("Lantern", "Audit", "acme"))
        write(lantern / "Threads" / "Secret" / "Secret.md", thread_note("Lantern", "Secret", "birch"))
        audit = lantern / "Threads" / "Audit" / "Notes.md"
        write(audit, "# Notes\n\nSee [[Secret]] and [[Survey]].\n")
        found = self.walls("Zones/Work/Lantern/Threads/Audit/Notes.md")
        self.assertEqual([("error", "links [[Secret]]" + self.TAIL)], [(f.severity, f.message) for f in found])
        self.assertEqual("A note in Lantern's Audit thread uses a note of Birch & Co", found[0].ear)


    def test_sources_follow_the_link_check(self):
        # Sources/ is exempt from the name check, never from the link check.
        sent = self.work / "Northwind" / "Sources" / "Brief.md"
        write(sent, "# Brief\n\nSee [[Harbour/Threads/Tender/Tender]].\n")
        self.assertEqual(["error"], [f.severity for f in self.findings("walls")
                                     if f.path == "Zones/Work/Northwind/Sources/Brief.md"])

    @unittest.skipUnless(HAVE_GIT, "git is not installed")
    def test_the_hook_refuses_each_way_in(self):
        real_repo(self.work)
        with mock.patch.dict(os.environ, NO_USER_GIT):
            commit_all(self.work, "start")
            for written in self.WALLED:
                with self.subTest(written):
                    write(self.note, "# Notes\n\nSee %s now.\n" % written)
                    git(self.work, "add", "-A")
                    found = check.run_checks(self.root, staged=self.work)
                    self.assertEqual([("error", "walls", self.where)], [(f.severity, f.check, f.path) for f in found])
                    self.assertTrue(found[0].message.endswith(self.TAIL), found[0].message)
            write(self.note, "# Notes\n\n%s\n" % "\n".join("See %s." % w for w in self.OPEN))
            git(self.work, "add", "-A")
            self.assertEqual([], check.run_checks(self.root, staged=self.work))

    @unittest.skipUnless(HAVE_GIT, "git is not installed")
    def test_the_hook_reads_the_far_party_from_git_too(self):
        real_repo(self.work)
        hub = self.work / "Harbour" / "Harbour.md"
        with mock.patch.dict(os.environ, NO_USER_GIT):
            commit_all(self.work, "start")
            hub.write_text(hub.read_text().replace("party: birch\n", ""))   # on disk only, never staged
            write(self.note, "# Notes\n\nSee [[Harbour]] now.\n")
            git(self.work, "add", "--", str(self.note.relative_to(self.work)))
            found = check.run_checks(self.root, staged=self.work)
        self.assertIn(("error", self.where, "links [[Harbour]]" + self.TAIL),
                      [(f.severity, f.path, f.message) for f in found])






# ----------------------------------------------------------------------
# merged from test_wall_gaps_340.py
# ----------------------------------------------------------------------
# Six gaps the 0.52.0 wall reviews found in older code (#340).
# 
#     cd tests && python3 -m unittest test_wall_gaps_340
# 
# None let a Garrick tool write across a wall; each needed a hand edit and left
# the commit hook saying less than docs/enforced.md suggests. Each is closed by
# refusing what cannot be read plainly. Every workspace is built in a temporary
# folder.


import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

import fixtures  # noqa: E402  (puts the tools folder on sys.path)
from fixtures import GIT_ENV, HAVE_GIT, checkpoint, git, write  # noqa: E402

import check  # noqa: E402
import garrick_lib  # noqa: E402
import importlib.util  # noqa: E402


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

from test_person_employer import CONTEXT, Workspace as EmployerWorkspace, entity, person  # noqa: E402

TOOLS = Path(__file__).resolve().parent.parent / "template" / "System" / "tools"

# ---------------------------------------------------------------------------
# 1. A Resume here or checkpoint path into another zone
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# 2. Wikis has a pre-commit hook
# ---------------------------------------------------------------------------


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class WikiHookTest(EmployerWorkspace):
    def setUp(self):
        super().setUp()
        self.wikis = self.root / "Wikis"
        shutil.copytree(str(TOOLS), str(self.root / "System" / "tools"), ignore=shutil.ignore_patterns("__pycache__"))
        git(self.wikis, "init", "-q")
        git(self.wikis, "config", "user.email", "test@example.invalid")

    def hooks(self):
        return [f for f in check.run_checks(self.root) if f.check == "zones" and f.path == "Wikis"]

    def test_a_wiki_repository_with_no_wall_check_is_warned(self):
        found = self.hooks()
        self.assertEqual(1, len(found))
        self.assertEqual("warning", found[0].severity)
        self.assertIn("--install-hooks", found[0].message)

    def test_install_hooks_puts_it_in_the_wiki_and_the_warning_goes(self):
        self.assertEqual(0, check.install_hooks(self.root))
        self.assertTrue(garrick_lib.has_wall_hook(self.wikis))
        self.assertEqual([], self.hooks())

    def test_the_hook_refuses_a_commit_that_crosses_a_wall_and_passes_one_that_does_not(self):
        garrick_lib.install_wall_hook(self.wikis, wiki=True)
        env = dict(GIT_ENV)
        write(self.people / "pat-newcomer.md", person("Pat Newcomer", "acme", "Consultant.", "[[wiki/entities/birch-co]]"))
        git(self.wikis, "add", "-A")
        refused = subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=str(self.wikis), env=env,
                                 capture_output=True, text=True)
        self.assertNotEqual(0, refused.returncode)
        self.assertIn("Commit refused", refused.stderr)
        write(self.people / "pat-newcomer.md", person("Pat Newcomer", "acme", "Consultant.", "[[wiki/entities/acme-corp]]"))
        git(self.wikis, "add", "-A")
        passed = subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=str(self.wikis), env=env,
                                capture_output=True, text=True)
        self.assertEqual(0, passed.returncode, passed.stderr)


    def test_a_wiki_reached_through_a_symbolic_link_still_finds_the_workspace(self):
        elsewhere = Path(self._tmp.name).resolve() / "cloud" / "Wikis"
        elsewhere.parent.mkdir()
        shutil.rmtree(str(self.wikis / ".git"))
        shutil.move(str(self.wikis), str(elsewhere))
        os.symlink(str(elsewhere), str(self.wikis))
        git(elsewhere, "init", "-q")
        git(elsewhere, "config", "user.email", "test@example.invalid")
        garrick_lib.install_wall_hook(self.wikis, wiki=True, root=self.root)
        self.assertIn(shlex_quote(self.root), (elsewhere / ".git" / "hooks" / "pre-commit").read_text())
        write(self.people / "pat-newcomer.md", person("Pat Newcomer", "acme", "Consultant.", "[[wiki/entities/birch-co]]"))
        git(elsewhere, "add", "-A")
        refused = subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=str(elsewhere), env=dict(GIT_ENV),
                                 capture_output=True, text=True)
        self.assertNotEqual(0, refused.returncode)
        self.assertIn("Commit refused: ", refused.stderr)
        self.assertNotIn("no workspace found", refused.stderr)
        write(self.people / "pat-newcomer.md", person("Pat Newcomer", "acme", "Consultant.", "[[wiki/entities/acme-corp]]"))
        git(elsewhere, "add", "-A")
        passed = subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=str(elsewhere), env=dict(GIT_ENV),
                                capture_output=True, text=True)
        self.assertEqual(0, passed.returncode, passed.stderr)

    def commit_in(self, repo):
        return subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=str(repo), env=dict(GIT_ENV),
                              capture_output=True, text=True)

    def test_a_copied_workspace_is_checked_as_itself(self):
        garrick_lib.install_wall_hook(self.wikis, wiki=True, root=self.root)
        copy = self.root.parent / "Copy"
        shutil.copytree(str(self.root), str(copy), symlinks=True)
        # The original no longer draws the wall, so a hook that read it would pass.
        context = self.root / "System" / "context.md"
        context.write_text(context.read_text(encoding="utf-8").replace("| `acme` | `birch` |", "| `acme` | `cedar` |"))
        mine = copy / "Wikis" / "Meetings" / "wiki" / "people"
        write(mine / "pat-newcomer.md", person("Pat Newcomer", "acme", "Buyer at [[wiki/entities/birch-co]].",
                                               "[[wiki/entities/acme-corp]]"))
        git(copy / "Wikis", "add", "-A")
        res = self.commit_in(copy / "Wikis")
        self.assertNotEqual(0, res.returncode, res.stderr)
        self.assertIn("Commit refused", res.stderr)

    def test_a_walled_link_in_the_text_is_refused_in_a_wiki_reached_through_a_link(self):
        elsewhere = Path(self._tmp.name).resolve() / "cloud" / "Wikis"
        elsewhere.parent.mkdir()
        shutil.move(str(self.wikis), str(elsewhere))
        os.symlink(str(elsewhere), str(self.wikis))
        garrick_lib.install_wall_hook(self.wikis, wiki=True, root=self.root)
        for body in ("Buyer at [[wiki/entities/birch-co]].", "Buyer at [[birch-co]]."):
            write(self.people / "pat-newcomer.md", person("Pat Newcomer", "acme", body))
            git(elsewhere, "add", "-A")
            res = self.commit_in(elsewhere)
            self.assertNotEqual(0, res.returncode, body)
            self.assertIn("Wikis/Meetings/wiki/people/pat-newcomer.md", res.stderr)

    def test_a_repository_that_is_not_part_of_the_workspace_is_refused(self):
        outside = Path(self._tmp.name).resolve() / "elsewhere"
        outside.mkdir()
        git(outside, "init", "-q")
        write(outside / "note.md", "x\n")
        git(outside, "add", "-A")
        res = subprocess.run([sys.executable, str(TOOLS / "check.py"), "--root", str(self.root), "--staged",
                              "--walls-only"], cwd=str(outside), env=dict(GIT_ENV), capture_output=True, text=True)
        self.assertEqual(1, res.returncode, res.stdout + res.stderr)
        self.assertIn("not part of the workspace", res.stderr)

    def first_commit(self):
        garrick_lib.install_wall_hook(self.wikis, wiki=True, root=self.root)
        git(self.wikis, "add", "-A")
        git(self.wikis, "-c", "core.hooksPath=" + os.devnull, "commit", "-q", "-m", "start")

    def bad_page(self, folder):
        write(folder / "pat-newcomer.md", person("Pat Newcomer", "acme", "Buyer at [[wiki/entities/birch-co]].",
                                                 "[[wiki/entities/acme-corp]]"))

    def test_a_linked_worktree_of_the_wikis_is_refused_wherever_it_stands(self):
        self.first_commit()
        for i, where in enumerate((self.wikis / "wt", self.wikis / "Meetings" / "wt", self.root / "wt")):
            git(self.wikis, "worktree", "add", "-q", "-b", "br%d" % i, str(where))
            self.bad_page(where / "Meetings" / "wiki" / "people")
            git(where, "add", "-A")
            res = self.commit_in(where)
            self.assertNotEqual(0, res.returncode, where)
            self.assertIn("worktree", res.stderr)
            via_check = subprocess.run([sys.executable, str(TOOLS / "check.py"), "--root", str(self.root), "--staged",
                                        "--walls-only"], cwd=str(where), env=dict(GIT_ENV), capture_output=True, text=True)
            self.assertEqual(1, via_check.returncode, where)
            self.assertIn("this repository", via_check.stderr)

    def test_a_work_tree_moved_by_the_environment_or_the_configuration_is_refused(self):
        self.first_commit()
        self.bad_page(self.people)
        git(self.wikis, "add", "-A")
        sub = self.wikis / "Meetings"
        env = dict(GIT_ENV, GIT_DIR=str(self.wikis / ".git"), GIT_WORK_TREE=str(sub))
        res = subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=str(sub), env=env, capture_output=True, text=True)
        self.assertNotEqual(0, res.returncode)
        self.assertIn("work tree", res.stderr)
        git(self.wikis, "config", "core.worktree", str(sub))
        res = self.commit_in(sub)
        self.assertNotEqual(0, res.returncode)
        self.assertIn("work tree", res.stderr)

    def test_a_check_inside_the_repository_is_not_the_one_that_runs(self):
        self.first_commit()
        write(self.wikis / "System" / "tools" / "check.py", "import sys\nsys.exit(0)\n")
        os.symlink(".", str(self.wikis / "Wikis"))
        self.bad_page(self.people)
        git(self.wikis, "add", "-A")
        res = self.commit_in(self.wikis)
        self.assertNotEqual(0, res.returncode, res.stderr)
        self.assertIn("Commit refused", res.stderr)

    def test_a_meetings_wiki_alone_reached_through_a_link_is_checked_and_commits(self):
        cloud = Path(self._tmp.name).resolve() / "cloud"
        cloud.mkdir()
        shutil.rmtree(str(self.wikis / ".git"))
        shutil.move(str(self.wikis / "Meetings"), str(cloud / "Meetings"))
        os.symlink(str(cloud / "Meetings"), str(self.wikis / "Meetings"))
        meetings = self.wikis / "Meetings"
        git(meetings, "init", "-q")
        git(meetings, "config", "user.email", "test@example.invalid")
        garrick_lib.install_wall_hook(meetings, wiki=True, root=self.root)
        write(self.people / "pat-newcomer.md", person("Pat Newcomer", "acme", "Consultant.", "[[wiki/entities/acme-corp]]"))
        git(meetings, "add", "-A")
        self.assertEqual(0, self.commit_in(meetings).returncode)
        self.bad_page(self.people)
        git(meetings, "add", "-A")
        res = self.commit_in(meetings)
        self.assertNotEqual(0, res.returncode)
        self.assertIn("pat-newcomer.md", res.stderr)

    def test_a_wiki_whose_git_is_a_file_or_a_link_is_refused_with_the_true_reason(self):
        separate = Path(self._tmp.name).resolve() / "separate-git"
        shutil.rmtree(str(self.wikis / ".git"))
        git(self.wikis, "init", "-q", "--separate-git-dir", str(separate))
        self.assertTrue((self.wikis / ".git").is_file())
        with self.assertRaises(FileNotFoundError) as caught:
            garrick_lib.install_wall_hook(self.wikis, wiki=True, root=self.root)
        self.assertIn("pointing elsewhere", str(caught.exception))
        found = [f for f in check.run_checks(self.root) if f.check == "zones" and f.path == "Wikis"]
        self.assertEqual(1, len(found))
        self.assertIn("pointing elsewhere", found[0].message)
        self.assertNotIn("--install-hooks", found[0].message)
        (separate / "hooks").mkdir(exist_ok=True)
        (separate / "hooks" / "pre-commit").write_text(garrick_lib.wiki_hook_text(self.root))
        (separate / "hooks" / "pre-commit").chmod(0o755)
        write(self.wikis / "note.md", "x\n")
        git(self.wikis, "add", "-A")
        res = self.commit_in(self.wikis)
        self.assertNotEqual(0, res.returncode)
        self.assertIn("pointing elsewhere", res.stderr)
        via = subprocess.run([sys.executable, str(TOOLS / "check.py"), "--root", str(self.root), "--staged",
                              "--walls-only"], cwd=str(self.wikis), env=dict(GIT_ENV), capture_output=True, text=True)
        self.assertIn("pointing elsewhere", via.stderr)

    def test_python_and_the_hook_agree_on_a_git_that_is_a_link(self):
        ext = Path(self._tmp.name).resolve() / "gitext"
        shutil.move(str(self.wikis / ".git"), str(ext))
        os.symlink(str(ext), str(self.wikis / ".git"))
        write(self.wikis / "note.md", "x\n")
        git(self.wikis, "add", "-A")
        via = subprocess.run([sys.executable, str(TOOLS / "check.py"), "--root", str(self.root), "--staged",
                              "--walls-only"], cwd=str(self.wikis), env=dict(GIT_ENV), capture_output=True, text=True)
        self.assertEqual(1, via.returncode, via.stderr)
        self.assertIn("pointing elsewhere", via.stderr)
        (ext / "hooks" / "pre-commit").write_text(garrick_lib.wiki_hook_text(self.root))
        (ext / "hooks" / "pre-commit").chmod(0o755)
        res = self.commit_in(self.wikis)
        self.assertNotEqual(0, res.returncode)
        self.assertIn("pointing elsewhere", res.stderr)

    def test_a_wiki_folder_starting_with_an_underscore_is_not_a_wiki_and_the_hook_says_so(self):
        scratch = self.wikis / "_Scratch"
        write(scratch / "a.md", "hi\n")
        git(scratch, "init", "-q")
        git(scratch, "config", "user.email", "test@example.invalid")
        garrick_lib.install_wall_hook(scratch, wiki=True, root=self.root)
        git(scratch, "add", "-A")
        res = self.commit_in(scratch)
        self.assertNotEqual(0, res.returncode)
        self.assertIn("not starting with _", res.stderr)

    def test_a_hook_that_finds_no_workspace_refuses_the_commit(self):
        hook = garrick_lib.install_wall_hook(self.wikis, wiki=True, root=self.root / "nowhere")
        shutil.rmtree(str(self.root / "System" / "tools"))
        write(self.wikis / "note.md", "x\n")
        git(self.wikis, "add", "-A")
        res = subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=str(self.wikis), env=dict(GIT_ENV),
                             capture_output=True, text=True)
        self.assertNotEqual(0, res.returncode)
        self.assertIn("no workspace found", res.stderr)
        self.assertTrue(hook.is_file())

    def hooks_path_findings(self):
        return [f for f in check.run_checks(self.root) if f.check == "hooks" and f.path == "Wikis"]

    def test_a_shared_hooks_folder_with_the_zones_hook_is_warned_for_a_wiki_and_with_its_own_is_not(self):
        shared = Path(self._tmp.name).resolve() / "hooks"
        shared.mkdir()
        git(self.wikis, "config", "core.hooksPath", str(shared))
        (shared / "pre-commit").write_text(garrick_lib.WALL_HOOK)
        (shared / "pre-commit").chmod(0o755)
        found = self.hooks_path_findings()
        self.assertEqual(1, len(found))
        self.assertIn("zone's", found[0].message)
        (shared / "pre-commit").write_text(garrick_lib.wiki_hook_text(self.root))
        self.assertEqual([], self.hooks_path_findings())


class InstallerWikiHookTest(unittest.TestCase):
    def test_a_pre_commit_hook_that_is_not_garricks_is_left_and_said_and_the_install_goes_on(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("garrick_install_340", str(Path(__file__).resolve().parent.parent / "install.py"))
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "Wikis" / ".git" / "hooks").mkdir(parents=True)
            hook = root / "Wikis" / ".git" / "hooks" / "pre-commit"
            hook.write_text("#!/bin/sh\necho mine\n")
            said = installer.wiki_hook(root)
            self.assertIn("not Garrick's", said)
            self.assertEqual("#!/bin/sh\necho mine\n", hook.read_text())
            hook.unlink()
            self.assertEqual("", installer.wiki_hook(root))
            self.assertIn("Garrick wall check", hook.read_text())


def shlex_quote(path) -> str:
    import shlex
    return shlex.quote(str(path))


# ---------------------------------------------------------------------------
# 3, 4, 5, 6. The hook's reading of entity pages, tables and person pages
# ---------------------------------------------------------------------------


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class HookTest(EmployerWorkspace):
    def setUp(self):
        super().setUp()
        self.wikis = self.root / "Wikis"
        git(self.wikis, "init", "-q")

    def commit(self):
        git(self.wikis, "add", "-A")
        git(self.wikis, "-c", "core.hooksPath=" + os.devnull, "commit", "-q", "-m", "start")

    def staged(self, repo=None, add=True):
        if repo is None:
            repo = self.wikis
            if add:
                git(repo, "add", "-A")
        return sorted((f.severity, f.check, f.path) for f in check.run_checks(self.root, walls_only=True, staged=repo))

    def refused(self, *names):
        return [("error", "walls", "Wikis/Meetings/wiki/people/%s.md" % n) for n in names]

    # 3. The entity index is the staged tree's

    def test_a_staged_delete_of_an_entity_page_leaves_no_link_dangling_unread(self):
        write(self.people / "theo-marsh.md", person("Theo Marsh", "birch", "Partner.", "[[wiki/entities/larch-partners]]"))
        self.commit()
        git(self.wikis, "rm", "-q", str(self.entities / "larch-partners.md"))
        self.assertEqual(self.refused("theo-marsh"), self.staged())

    def test_a_staged_rename_of_an_entity_page_leaves_no_link_dangling_unread(self):
        write(self.people / "theo-marsh.md", person("Theo Marsh", "birch", "Partner.", "[[wiki/entities/larch-partners]]"))
        self.commit()
        git(self.wikis, "mv", str(self.entities / "larch-partners.md"), str(self.entities / "larch-and-sons.md"))
        self.assertEqual(self.refused("theo-marsh"), self.staged())

    def test_moving_the_link_with_the_page_is_fine(self):
        write(self.people / "theo-marsh.md", person("Theo Marsh", "birch", "Partner.", "[[wiki/entities/larch-partners]]"))
        self.commit()
        git(self.wikis, "mv", str(self.entities / "larch-partners.md"), str(self.entities / "larch-and-sons.md"))
        write(self.people / "theo-marsh.md", person("Theo Marsh", "birch", "Partner.", "[[wiki/entities/larch-and-sons]]"))
        self.assertEqual([], self.staged())

    def test_an_entity_page_staged_and_then_deleted_from_disk_is_still_read(self):
        write(self.people / "pat-newcomer.md", person("Pat Newcomer", "acme", "Buyer.", "[[wiki/entities/acme-corp]]"))
        self.commit()
        write(self.entities / "acme-ltd.md", entity("Acme Corp", "birch"))      # a namesake of a walled party
        git(self.wikis, "add", "-A")
        (self.entities / "acme-ltd.md").unlink()                                   # staged, not on disk
        self.assertEqual(self.refused("pat-newcomer"), self.staged(add=False))

    # 4. The People and Parties tables

    def table_repo(self):
        git(self.root, "init", "-q")
        git(self.root, "add", "System/context.md", "System/rules.md")
        git(self.root, "-c", "core.hooksPath=" + os.devnull, "commit", "-q", "-m", "start")

    def test_a_second_walled_row_for_a_person_with_an_employer_link_is_read_in_the_root_commit(self):
        context = self.root / "System" / "context.md"
        write(context, CONTEXT.replace("| Theo Marsh | `birch` | Managing partner |",
                                       "| Theo Marsh | `birch` | Managing partner |\n| Kit Avery | `birch` | Architect |"))
        write(self.people / "kit-avery.md", person("Kit Avery", "birch", "Architect.", "[[wiki/entities/birch-co]]"))
        self.table_repo()
        write(context, context.read_text(encoding="utf-8").replace("| Kit Avery | `birch` | Architect |",
                                                                    "| Kit Avery | `birch` | Architect |\n"
                                                                    "| Kit Avery | `acme` | Architect |"))
        git(self.root, "add", "System/context.md")
        self.assertEqual(self.refused("kit-avery"), self.staged(self.root))

    def test_a_table_change_that_crosses_nothing_commits(self):
        self.table_repo()
        context = self.root / "System" / "context.md"
        write(context, context.read_text(encoding="utf-8") + "\n")
        git(self.root, "add", "System/context.md")
        self.assertEqual([], self.staged(self.root))

    def test_a_table_staged_differently_from_the_disk_is_refused(self):
        self.table_repo()
        context = self.root / "System" / "context.md"
        write(context, context.read_text(encoding="utf-8") + "\nstaged\n")
        git(self.root, "add", "System/context.md")
        write(context, context.read_text(encoding="utf-8") + "\nnot staged\n")
        self.assertEqual([("error", "walls", "System/context.md")], self.staged(self.root))

    # 5. A short form of a two-hat name

    SHORT = ("Blake", "Ro Blake", "Row Blake", "Blake, Ro", "R. Blake", "Blake Rowan", "Mr Blake", "Dr Blake",
             "Rowan Blake (Birch)", "Rowan Blake / Acme", "Blake (Acme)", "Blake Rowan Jr", "Kjaer Soren", "Kjær S.",
             "BLAKE", "rowan_blake", "Theo Blake", "Ronald Blake", "Rowan Blake-Smith")

    def test_a_page_sharing_a_surname_word_with_a_two_hat_person_meets_them(self):
        for name in self.SHORT:
            self.assertEqual({"acme", "birch"}, garrick_lib.people_parties(self.context, (name, name.lower())), name)
        for name in ("Dana Whitlock", "Dana Smith", "Rowan Blaek", "Blakely"):
            self.assertNotEqual({"acme", "birch"}, garrick_lib.people_parties(self.context, (name,)), name)

    def test_another_row_of_the_table_exactly_is_not_asked_about(self):
        context = dict(self.context)
        context["people"] = self.context["people"] + [{"name": "Theo Blake", "party": "`birch`", "role": "Buyer"}]
        self.assertEqual({"birch"}, garrick_lib.people_parties(context, ("Theo Blake",)))

    def test_no_link_is_proposed_to_such_a_page(self):
        for name in self.SHORT:
            self.assertEqual("", garrick_lib.organisation_link(self.root, self.context, name, "acme"), name)
            text = person(name, "acme", "Buyer.")
            self.assertEqual(("", []), garrick_lib.organisation_proposal(self.root, self.context, (name,), "acme", text))

    def test_such_a_page_is_asked_about(self):
        write(self.people / "ro-blake.md", person("Ro Blake", "acme", "Buyer."))
        write(self.people / "mr-blake.md", person("Mr Blake", "acme", "Buyer."))
        write(self.people / "dana-smith.md", person("Dana Smith", "acme", "Buyer."))
        found = {f.path: f for f in check.run_checks(self.root) if f.check == "people"}
        for slug in ("ro-blake", "mr-blake"):
            self.assertIn("short form", found["Wikis/Meetings/wiki/people/%s.md" % slug].message)
        self.assertNotIn("short form", found["Wikis/Meetings/wiki/people/dana-smith.md"].message)

    def test_the_hook_refuses_a_link_on_such_a_page(self):
        write(self.people / "blake.md", person("Blake", "none", "Buyer.", "[[wiki/entities/larch-partners]]"))
        write(self.people / "ro-blake.md", person("Ro Blake", "acme", "Buyer.", "[[wiki/entities/acme-corp]]"))
        write(self.people / "mr-blake.md", person("Blake Rowan Jr", "acme", "Buyer.", "[[wiki/entities/acme-corp]]"))
        write(self.people / "kjaer.md", person("Kjær S.", "none", "Engineer.", "[[wiki/entities/larch-partners]]"))
        self.assertEqual(self.refused("blake", "kjaer", "mr-blake", "ro-blake"), self.staged())

    # 6. Other keys, and links in the text

    def test_a_key_the_schema_does_not_have_is_refused(self):
        for i, line in enumerate(('company: "[[wiki/entities/birch-co]]"\n', 'employer: [[wiki/entities/birch-co]]\n',
                                  "aliases: [Pat]\n", "employer: Birch\n", "tags: []\n")):
            text = person("Pat Newcomer", "acme", "Buyer.").replace("created:", line + "created:")
            write(self.people / ("pat-%d.md" % i), text)
        self.assertEqual(self.refused(*("pat-%d" % i for i in range(5))), self.staged())

    def test_a_link_in_a_value_other_than_organisation_is_refused(self):
        write(self.people / "pat-newcomer.md",
              person("Pat Newcomer", "acme", "Buyer.").replace("title: Pat Newcomer", 'title: "[[wiki/entities/birch-co]]"'))
        write(self.people / "kit-avery.md", person("Kit Avery", "acme", "Buyer.").replace("type: person", "type: [[x]]"))
        self.assertEqual(self.refused("kit-avery", "pat-newcomer"), self.staged())

    def test_the_schemas_keys_alone_pass(self):
        write(self.people / "pat-newcomer.md", person("Pat Newcomer", "acme", "Buyer.", "[[wiki/entities/acme-corp]]"))
        self.assertEqual([], self.staged())

    IN_THE_TEXT = (
        "[[wiki/entities/birch-co]]", "[[wiki/entities/birch-co|Birch]]", "[[wiki/entities/birch-co#h]]", "[[birch-co]]",
        "[[Birch-Co]]", "[[birch-co|x]]", "[[birch-co#h]]",
    )
    NOT_PLAIN = (
        "[[../entities/birch-co]]", "[[./birch-co]]", "[[entities/birch-co]]", "[[wiki/birch-co]]", "[[birch-co.md]]",
        "[[birch-co.md|x]]", "[B](../entities/birch-co.md)", "[a [b]](wiki/entities/birch-co.md)",
        '[a](wiki/entities/birch-co.md "t (x)")', "[a](wiki/entities/birch-co.md#(x))",
        '[a](<wiki/entities/birch-co.md> "t")', "[B][1]\n\n[1]: wiki/entities/birch-co.md",
        '<a href="wiki/entities/birch-co.md">B</a>', "<wiki/entities/birch-co.md>", "![B](wiki/entities/birch-co.md)",
        "![[wiki/entities/birch-co.md]]", "[[wiki/entities/\nbirch-co]]", "[[a|[[wiki/entities/birch-co]]]]",
        "[a](obsidian://open?vault=Wikis&file=Meetings%2Fwiki%2Fentities%2Fbirch-co)", "[[Birch and Co]]",
        "[[wiki/entities/birch-co]]]]", "[[ wiki/entities/birch-co ]]", "<img src=x>",
    )

    def test_a_link_to_a_walled_entity_page_in_the_text_is_refused(self):
        for i, link in enumerate(self.IN_THE_TEXT):
            write(self.people / ("pat-%d.md" % i), person("Pat Newcomer", "acme", "Buyer, met at %s." % link,
                                                          "[[wiki/entities/acme-corp]]"))
        names = ["pat-%d" % i for i in range(len(self.IN_THE_TEXT))]
        self.assertEqual(self.refused(*sorted(names)), self.staged())
        self.assertEqual(sorted("Wikis/Meetings/wiki/people/%s.md" % n for n in names),
                         sorted(f.path for f in check.run_checks(self.root) if f.check == "walls"))

    def test_a_link_in_any_form_but_the_plain_one_is_refused_in_the_hook_and_the_full_check(self):
        for i, link in enumerate(self.NOT_PLAIN):
            write(self.people / ("pat-%d.md" % i), person("Pat Newcomer", "acme", "Buyer, met at %s." % link,
                                                          "[[wiki/entities/acme-corp]]"))
        names = ["pat-%d" % i for i in range(len(self.NOT_PLAIN))]
        self.assertEqual(self.refused(*sorted(names)), self.staged())
        full = [f for f in check.run_checks(self.root) if f.check == "walls"]
        self.assertEqual(sorted("Wikis/Meetings/wiki/people/%s.md" % n for n in names), sorted(f.path for f in full))
        self.assertIn("[[wiki/<folder>/<name>]]", full[0].message)

    def test_plain_links_to_pages_that_are_there_pass(self):
        write(self.people / "kit-avery.md", person("Kit Avery", "none", "Colleague of [[theo-marsh|Theo]].", ""))
        write(self.people / "theo-marsh.md", person("Theo Marsh", "birch", "Partner at [[wiki/entities/birch-co#h]]."))
        write(self.people / "pat-newcomer.md",
              person("Pat Newcomer", "acme", "Buyer at [[acme-corp]] and [[wiki/entities/acme-corp|Acme]].",
                     "[[wiki/entities/acme-corp]]"))
        self.assertEqual([], self.staged())

    def test_ordinary_prose_that_looks_like_a_link_is_refused_saying_what_and_how(self):
        for prose in ("[LinkedIn](https://www.example.com/in/pat)", "<pat@acme.example>", "x<y and y>z",
                      "Buyer [EMEA]: Italy", "Buyer <not sure>"):
            write(self.people / "pat-newcomer.md", person("Pat Newcomer", "acme", prose, "[[wiki/entities/acme-corp]]"))
            git(self.wikis, "add", "-A")
            found = [f for f in check.run_checks(self.root, walls_only=True, staged=self.wikis)]
            self.assertEqual(1, len(found), prose)
            self.assertIn("holds `", found[0].message)
            start = min(i for i in (prose.find("["), prose.find("<")) if i >= 0)
            self.assertIn(prose[start:start + 5], found[0].message)
            self.assertIn("web address bare", found[0].message)

    def test_an_alias_or_heading_that_could_start_another_link_is_not_plain(self):
        for link in ('[[wiki/entities/acme-corp|<a href="wiki/entities/birch-co.md">x</a>]]',
                     "[[wiki/entities/acme-corp|obsidian://open?file=birch-co]]",
                     "[[wiki/entities/acme-corp|<wiki/entities/birch-co.md>]]",
                     '[[wiki/entities/acme-corp#<a href="x">h</a>]]', "[[wiki/entities/acme-corp|x](wiki/entities/birch-co.md)",
                     "[[wiki/entities/acme-corp|see (this)]]", "[[wiki/entities/acme-corp|https://example.com]]"):
            write(self.people / "pat-newcomer.md", person("Pat Newcomer", "acme", "Buyer, %s." % link))
            self.assertEqual(self.refused("pat-newcomer"), self.staged(), link)

    def test_a_bare_name_is_read_against_every_page_of_that_name_dormant_and_archived_too(self):
        (self.entities / "birch-co.md").unlink()
        write(self.meetings / "wiki" / "topics" / "birch-co.md", "---\ntitle: x\ntype: topic\n---\nhi\n")
        for grade in ("dormant", "archive"):
            page = self.meetings / grade / "wiki" / "entities" / "birch-co.md"
            write(page, entity("Birch & Co", "birch"))
            write(self.people / "pat-newcomer.md", person("Pat Newcomer", "acme", "Buyer at [[birch-co]]."))
            self.assertEqual(self.refused("pat-newcomer"), self.staged(), grade)
            page.unlink()

    def test_what_fade_writes_into_a_person_page_is_plain_and_wall_checked(self):
        fade = _load("garrick_fade_340", TOOLS / "fade.py")
        text = person("Pat Newcomer", "acme", "Buyer at [[acme-corp]] and, once, [[wiki/entities/birch-co]] and "
                      "[[260310-acme-kickoff]].")
        links = fade.Links(self.root)
        for slug in ("acme-corp", "birch-co"):
            old = self.entities / (slug + ".md")
            new = self.meetings / "dormant" / "wiki" / "entities" / (slug + ".md")
            new.parent.mkdir(parents=True, exist_ok=True)
            os.rename(str(old), str(new))
        moved = {"Wikis/Meetings/wiki/entities/%s.md" % s_: "Wikis/Meetings/dormant/wiki/entities/%s.md" % s_
                 for s_ in ("acme-corp", "birch-co")}
        out = fade.relink(text, moved, links, "Wikis/Meetings/wiki/people/pat-newcomer.md")
        self.assertIn("[[dormant/wiki/entities/acme-corp|", out)
        pages, problem = check.text_entity_pages(check.discover(self.root), out)
        self.assertEqual("", problem)
        self.assertEqual(2, len(pages))
        write(self.people / "pat-newcomer.md", out)
        self.assertEqual(self.refused("pat-newcomer"), self.staged())      # the Birch link is across the wall
        clean = fade.relink(text.replace("once, [[wiki/entities/birch-co]] and ", ""), moved, links,
                            "Wikis/Meetings/wiki/people/pat-newcomer.md")
        self.assertNotIn("birch", clean)
        write(self.people / "pat-newcomer.md", clean)
        self.assertEqual([], self.staged())

    def test_a_change_under_a_dormant_or_archived_entity_folder_reads_the_people(self):
        for grade in ("dormant", "archive"):
            page = self.meetings / grade / "wiki" / "entities" / "old-acme.md"
            write(page, entity("Old Acme", "acme"))
            write(self.people / "pat-newcomer.md", person("Pat Newcomer", "acme", "Buyer at [[%s/wiki/entities/old-acme]]." % grade,
                                                          "[[wiki/entities/acme-corp]]"))
            self.commit()
            write(page, entity("Old Acme", "birch"))                       # edited in place, the person page untouched
            self.assertEqual(self.refused("pat-newcomer"), self.staged(), grade)
            git(self.wikis, "reset", "-q", "--hard")
            write(self.meetings / grade / "wiki" / "entities" / "acme-corp.md", entity("Acme Corp", "birch"))
            write(self.people / "pat-newcomer.md", person("Pat Newcomer", "acme", "Buyer at [[acme-corp]].",
                                                          "[[wiki/entities/acme-corp]]"))
            self.assertEqual(self.refused("pat-newcomer"), self.staged(), grade + " same name")
            git(self.wikis, "reset", "-q", "--hard")
            git(self.wikis, "clean", "-fdq")

    def test_person_pages_under_dormant_and_archive_are_wall_checked(self):
        for grade in ("dormant", "archive"):
            write(self.meetings / grade / "wiki" / "people" / "pat-two.md",
                  person("Pat Two", "acme", "Buyer at [[wiki/entities/birch-co]].", "[[wiki/entities/acme-corp]]"))
            write(self.meetings / grade / "wiki" / "people" / "pat-three.md",
                  person("Pat Three", "acme", "Buyer.", "[[wiki/entities/birch-co]]"))
        names = sorted("Wikis/Meetings/%s/wiki/people/%s.md" % (g, n) for g in ("dormant", "archive")
                       for n in ("pat-two", "pat-three"))
        self.assertEqual(names, sorted(f.path for f in check.run_checks(self.root) if f.check == "walls"))
        self.assertEqual(names, sorted(x[2] for x in self.staged()))

    def test_fade_never_moves_an_entity_or_person_page(self):
        import datetime
        fade = _load("garrick_fade_340b", TOOLS / "fade.py")
        write(self.entities / "old-acme.md", entity("Old Acme", "acme").replace("---\n\n", "updated: 2019-01-01\n---\n\n", 1))
        write(self.people / "pat-newcomer.md", person("Pat Newcomer", "acme", "Buyer.").replace("2026-03-10", "2019-01-01"))
        plans = fade.plan(self.root, today=datetime.date(2035, 1, 1), wikis=["Meetings"])
        subs = [m.page.sub for m in plans["Meetings"].moves]
        self.assertFalse([x for x in subs if "/entities/" in x or "/people/" in x], subs)
        fixed = {p.sub: p.fixed for p in plans["Meetings"].pages}
        self.assertTrue(fixed.get("wiki/entities/old-acme.md") and fixed.get("wiki/people/pat-newcomer.md"), fixed)

    def stage_as(self, source, name):
        """Stage the file `source` under `name` as typed, whatever the disk's case rules."""
        blob = git(self.wikis, "hash-object", "-w", str(source)).strip()
        git(self.wikis, "update-index", "--add", "--cacheinfo", "100644,%s,%s" % (blob, name))

    def test_a_folder_typed_in_another_case_is_read_as_the_folder(self):
        bad = self.people / "pat-newcomer.md"
        write(bad, person("Pat Newcomer", "acme", "Buyer at [[wiki/entities/birch-co]].", "[[wiki/entities/acme-corp]]"))
        for name in ("Meetings/Wiki/People/pat-newcomer.md", "Meetings/Dormant/wiki/people/pat-newcomer.md",
                     "Meetings/dormant/Wiki/People/pat-newcomer.md", "meetings/WIKI/PEOPLE/pat-newcomer.md",
                     "Meetings/ARCHIVE/wiki/people/pat-newcomer.md"):
            git(self.wikis, "reset", "-q")
            self.stage_as(bad, name)
            found = sorted((f.severity, f.check) for f in check.run_checks(self.root, walls_only=True, staged=self.wikis))
            self.assertEqual([("error", "walls")], found, name)

    def test_an_entity_page_typed_in_another_case_still_re_reads_the_people(self):
        write(self.people / "pat-newcomer.md", person("Pat Newcomer", "acme", "Buyer at [[acme-corp]].",
                                                      "[[wiki/entities/acme-corp]]"))
        self.commit()
        page = self.meetings / "dormant" / "wiki" / "entities" / "acme-corp.md"
        write(page, entity("Acme Corp", "birch"))
        self.stage_as(page, "Meetings/Dormant/wiki/entities/acme-corp.md")
        self.assertEqual(self.refused("pat-newcomer"), self.staged(add=False))

    def test_the_full_check_finds_person_pages_in_a_folder_of_another_case(self):
        write(self.meetings / "Dormant" / "Wiki" / "People" / "pat-two.md",
              person("Pat Two", "acme", "Buyer at [[wiki/entities/birch-co]].", "[[wiki/entities/acme-corp]]"))
        found = [f.path for f in check.run_checks(self.root) if f.check == "walls"]
        self.assertEqual(1, len(found), found)
        self.assertTrue(found[0].lower().endswith("/people/pat-two.md"), found)

    def test_a_submodule_in_a_wiki_is_refused_and_a_nested_git_is_warned_about(self):
        git(self.wikis, "update-index", "--add", "--cacheinfo", "160000,%s,Meetings/wiki/people" % ("a" * 40))
        found = [(f.severity, f.check, f.path) for f in check.run_checks(self.root, walls_only=True, staged=self.wikis)]
        self.assertEqual([("error", "walls", "Meetings/wiki/people")], found)
        git(self.wikis, "reset", "-q")
        write(self.meetings / "wiki" / "people" / "sub" / ".git", "gitdir: elsewhere\n")
        full = [f for f in check.run_checks(self.root) if f.check == "walls"]
        self.assertEqual(1, len(full))
        self.assertEqual("warning", full[0].severity)
        self.assertIn("not a wiki's own", full[0].message)

    def test_a_link_in_the_text_to_a_page_that_is_not_there_is_refused(self):
        write(self.people / "pat-newcomer.md", person("Pat Newcomer", "acme", "Buyer at [[wiki/entities/nowhere]]."))
        self.assertEqual(self.refused("pat-newcomer"), self.staged())

    def test_a_link_in_the_text_to_the_persons_own_entity_page_passes(self):
        write(self.people / "pat-newcomer.md", person("Pat Newcomer", "acme", "Buyer at [[wiki/entities/acme-corp]] and [[acme-corp]]."))
        self.assertEqual([], self.staged())

    def test_staging_an_entity_page_reads_the_people_who_link_it_in_their_text(self):
        write(self.people / "pat-newcomer.md", person("Pat Newcomer", "acme", "Buyer at [[acme-corp]]."))
        self.commit()
        write(self.entities / "acme-corp.md", entity("Acme Corp", "birch"))
        self.assertEqual(self.refused("pat-newcomer"), self.staged())


# ----------------------------------------------------------------------
# merged from test_recall_walls.py
# ----------------------------------------------------------------------
# Recall (#341): the release review's wall findings.
# 
#     cd tests && python3 -m unittest test_recall_walls
# 
# Invented names only. Acme Review and Birch Entry stand either side of a wall.


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

    def test_a_folder_found_at_run_time_makes_the_session_root_only(self):
        # The confirmation pass of the 0.59.0 review: a way up with no `..`, no glob and no name.
        commands = {
            "dn": 'cd "$(dirname "$PWD")" && ls',
            "py": 'python3 -c "import os; os.chdir(os.path.dirname(os.getcwd())); print(os.listdir())"',
            "ev": "d=$(echo . .); cd ${d// /} && ls",
            "pc": 'cd "${PWD%/*}" && ls',
        }
        for name, command in commands.items():
            self.session(name, self.bash(command), "%sdirnfact finding." % name)
        for name in commands:
            self.assertEqual(self.extract_and_search(name + "dirnfact"), [], name)

    def test_other_tool_inputs_are_scanned_not_rendered(self):
        self.session("gr", [{"type": "tool_use", "id": "t1", "name": "Grep",
                             "input": {"pattern": "budget", "path": "../Birch Entry"}}], "grepwombat finding.")
        self.assertEqual(self.extract_and_search("grepwombat"), [])
        for p in self.root.rglob(".sessions/*.md"):
            self.assertNotIn("budget", p.read_text())

    def test_a_way_up_that_names_no_place_makes_the_session_root_only(self):
        self.session("up", self.bash("cd .. && ls"), "upwombat finding.")
        self.assertEqual(self.extract_and_search("upwombat"), [])

    def test_a_session_is_read_from_the_root_only_in_a_zone_with_a_wall_inside(self):
        self.session("own", self.bash("cat Threads/Pricing/Pricing.md"), "ownwombat finding.")
        self.assertEqual(self.extract_and_search("ownwombat"), [])        # not from its own project
        for project in (ACME, BIRCH):
            self.assertEqual([], [h.path for h in recall.search("ownwombat", project=project, root=self.root, sessions=True)])
        found = [h.path for h in recall.search("ownwombat", project=None, root=self.root, sessions=True)]
        self.assertEqual(1, len(found))                                   # from the root it is found

    def test_a_session_is_read_from_the_root_only_in_a_zone_with_no_wall_inside_too(self):
        context = self.root / "System" / "context.md"
        text = context.read_text(encoding="utf-8")
        context.write_text(text.replace("| `acme` | yes |", "| `acme` | no |").replace("| `birch` | yes |", "| `birch` | no |"), encoding="utf-8")
        self.session("own", self.bash("cat Threads/Pricing/Pricing.md"), "ownwombat finding.")
        self.assertEqual(self.extract_and_search("ownwombat"), [])        # no zone or project scope reads a session
        found = [h.path for h in recall.search("ownwombat", project=None, root=self.root, sessions=True)]
        self.assertEqual(1, len(found))

    def test_an_old_project_header_is_not_trusted(self):
        # A session file written by an earlier extractor, naming its project in the header.
        self.session("old", self.bash("ls"), "oldwombat finding.")
        self.assertEqual(self.extract_and_search("oldwombat"), [])       # extracted from the test's own folders
        patched = 0
        for f in self.root.rglob(".sessions/*.md"):
            text = f.read_text(encoding="utf-8")
            if "oldwombat" in text and "project:" not in text:
                f.write_text(text.replace("---\n", "---\nproject: [\"Zones/Work/Acme Review\"]\n", 1), encoding="utf-8")
                patched += 1
        self.assertEqual(1, patched)
        for project in (ACME, BIRCH):
            self.assertEqual([], [h.path for h in recall.search("oldwombat", project=project, root=self.root, sessions=True)])

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
