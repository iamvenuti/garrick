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
        self.assertIn("wall stands between", found[0].message)

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
                self.assertIn("a wall stands between acme and birch", found[0].message)
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
            "| Birch & Co | Client. Market-entry advice; competes with Acme | Work | `birch` | birchco.example, mail.birchco.example |\n",
            "| Birch & Co | Client. Market-entry advice; competes with Acme | Work | `birch` | birchco.example, mail.birchco.example |\n"
            "| Dana Rossi | Advisor | Work | `rossi` | |\n"
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

    WALLED = ("[[Harbour/Threads/Tender/Tender]]",                 # a wikilink by its path
              "[[Tender|the tender]]",                             # a bare name that lands only across the wall
              "`Harbour/Threads/Tender/Tender.md`",                # a path written as code
              "[the tender](../../../Harbour/Threads/Tender/Tender.md)",
              "obsidian://open?vault=Workspace&file=Zones%2FWork%2FHarbour%2FThreads%2FTender%2FTender")
    OPEN = ("[[Lantern/Threads/Survey/Survey]]", "[[Survey]]", "`Lantern/Threads/Survey/Survey.md`",
            "[[Freight]]", "`Threads/Freight/Freight.md`", "[[Northwind/Threads/Freight/Freight]]")

    def setUp(self):
        super().setUp()
        ctx = self.root / "System" / "context.md"
        ctx.write_text(ctx.read_text().replace(
            "mail.birchco.example |\n",
            "mail.birchco.example |\n| Cobalt Ltd | Client. Logistics audit | Work | `cobalt` | cobalt.example |\n", 1))
        for name, party, thread in (("Northwind", "acme", "Freight"), ("Harbour", "birch", "Tender"),
                                    ("Lantern", "cobalt", "Survey")):
            folder = self.work / name
            write(folder / (name + ".md"), project_hub("Work", name, party, [thread]))
            write(folder / "Threads" / thread / (thread + ".md"), thread_note(name, thread, party))
        self.note = self.work / "Northwind" / "Threads" / "Freight" / "Notes.md"
        self.where = "Zones/Work/Northwind/Threads/Freight/Notes.md"

    def walls(self):
        return [f for f in self.findings("walls") if f.path == self.where]

    def test_each_way_in_is_refused_by_the_full_check(self):
        self.assertEqual([], self.walls())
        for written in self.WALLED:
            with self.subTest(written):
                write(self.note, "# Notes\n\nSee %s now.\n" % written)
                found = self.walls()
                self.assertEqual(["error"], [f.severity for f in found], found)
                self.assertTrue(found[0].message.endswith(
                    ", a note of project Harbour for birch; a wall stands between acme and birch"), found[0].message)
                self.assertEqual("A note in Northwind's Freight thread uses a note of Birch & Co", found[0].ear)

    def test_a_path_as_code_says_so(self):
        write(self.note, "# Notes\n\nSee `Harbour/Threads/Tender/Tender.md`.\n")
        self.assertEqual(["writes the path `Harbour/Threads/Tender/Tender.md`, a note of project Harbour for birch; "
                          "a wall stands between acme and birch"], [f.message for f in self.walls()])

    def test_an_unwalled_project_and_the_project_itself_pass(self):
        write(self.note, "# Notes\n\n%s\n" % "\n".join("See %s." % w for w in self.OPEN))
        self.assertEqual([], self.walls())

    def test_a_name_that_also_lands_in_the_project_itself_means_its_own(self):
        write(self.work / "Northwind" / "Threads" / "Freight" / "Tender.md", "# Tender\n")
        write(self.note, "# Notes\n\nSee [[Tender]].\n")
        self.assertEqual([], self.walls())

    def test_a_short_path_every_project_may_hold(self):
        # It is about the far project only when it names it, or lands nowhere else.
        write(self.work / "Harbour" / "Deliverables" / "published.md", "| Date | File |\n|---|---|\n")
        write(self.note, "# Notes\n\nRecord it in `Deliverables/published.md`.\n")
        self.assertEqual(1, len(self.walls()))
        write(self.work / "Lantern" / "Deliverables" / "published.md", "| Date | File |\n|---|---|\n")
        self.assertEqual([], self.walls())
        write(self.note, "# Notes\n\nSee [[Harbour/Deliverables/published]].\n")
        self.assertEqual(["links [[Harbour/Deliverables/published]], a note of project Harbour for birch; "
                          "a wall stands between acme and birch"], [f.message for f in self.walls()])

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
            for written in self.WALLED[:3]:
                with self.subTest(written):
                    write(self.note, "# Notes\n\nSee %s now.\n" % written)
                    git(self.work, "add", "-A")
                    found = check.run_checks(self.root, staged=self.work)
                    self.assertEqual([("error", "walls", self.where)], [(f.severity, f.check, f.path) for f in found])
                    self.assertIn("a note of project Harbour for birch", found[0].message)
            write(self.note, "# Notes\n\n%s\n" % "\n".join("See %s." % w for w in self.OPEN))
            git(self.work, "add", "-A")
            self.assertEqual([], check.run_checks(self.root, staged=self.work))


if __name__ == "__main__":
    unittest.main()
