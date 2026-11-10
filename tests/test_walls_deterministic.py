"""The deterministic wall check: names and quotes across a wall, the staged
mode, and the pre-commit hook the installer puts in every zone.

Invented parties only: Acme Corp (`acme`) and Birch & Co (`birch`), walled
from each other, as in fixtures.py.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import fixtures
from fixtures import GIT_ENV, HAVE_GIT, TOOLS, build_workspace, commit_all, git, meeting_page, write

import check  # noqa: E402  (fixtures puts the tools folder on sys.path)
from garrick_lib import has_wall_hook, install_wall_hook  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
INSTALL = REPO / "install.py"
ENV = dict(GIT_ENV, PYTHONDONTWRITEBYTECODE="1")

# Wording only the Birch side ever heard. Never allowed to appear in a finding.
SECRET = "The board wants the Oslo depot signed before the tenth of November at any price"
SECRET_WORDS = ("oslo", "depot", "november")


class WallCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve() / "Workspace"
        build_workspace(self.root)
        self.acme = self.root / "Zones" / "Work" / "Acme Review"
        self.birch = self.root / "Zones" / "Work" / "Birch Entry"
        self.meetings = self.root / "Wikis" / "Meetings"
        self.knowledge = self.root / "Wikis" / "Knowledge"

    def tearDown(self):
        self._tmp.cleanup()

    def walls(self):
        return [f for f in check.run_checks(self.root) if f.check == "walls"]

    def assertNoLeak(self, findings, *secrets):
        text = check.report_text(findings, self.root) + check.report_ear(findings) + check.report_staged(findings)
        for secret in secrets:
            self.assertNotIn(secret.lower(), text.lower())


class TestNames(WallCase):
    def test_person_across_the_wall(self):
        write(self.birch / "Threads" / "Market Sizing" / "Notes.md", "Compare with what Dana Whitlock expects.\n")
        found = self.walls()
        self.assertEqual(1, len(found), found)
        self.assertEqual("error", found[0].severity)
        self.assertEqual("Zones/Work/Birch Entry/Threads/Market Sizing/Notes.md", found[0].path)
        self.assertIn("Acme Corp", found[0].message)
        self.assertIn("acme is walled and this project does not name it", found[0].message)
        self.assertNoLeak(found, "Dana", "Whitlock")

    def test_party_name_tag_and_possessive(self):
        write(self.birch / "Birch Entry.md", (self.birch / "Birch Entry.md").read_text() + "\nACME's numbers look soft.\n")
        write(self.acme / "Deliverables" / "260302 - Board note.md", "Unlike Birch & Co. we stay local.\n")
        paths = {f.path for f in self.walls()}
        self.assertEqual({"Zones/Work/Birch Entry/Birch Entry.md",
                          "Zones/Work/Acme Review/Deliverables/260302 - Board note.md"}, paths)

    def test_alias(self):
        write(self.birch / "Threads" / "Market Sizing" / "Notes.md", "dana whitlaw called again\n")
        write(self.acme / "Threads" / "Pricing" / "Notes.md", "the birchen co numbers\n")
        self.assertEqual(2, len(self.walls()))

    def test_first_name_alone_as_written(self):
        write(self.acme / "Threads" / "Pricing" / "Notes.md", "Theo is moving first.\n")
        self.assertEqual(1, len(self.walls()))
        write(self.acme / "Threads" / "Pricing" / "Notes.md", "the theodolite survey\n")
        self.assertEqual([], self.walls())

    def test_person_counts_only_for_their_own_party(self):
        write(self.acme / "Threads" / "Pricing" / "Notes.md", "Dana Whitlock signed off. Dana wants it by Friday.\n")
        write(self.birch / "Threads" / "Market Sizing" / "Notes.md", "Theo Marsh agreed the scope.\n")
        self.assertEqual([], self.walls())

    def test_name_on_both_sides_is_not_evidence(self):
        ctx = (self.root / "System" / "context.md").read_text()
        ctx = ctx.replace("| Theo Marsh | `birch` | Managing partner |",
                          "| Theo Marsh | `birch` | Managing partner |\n| Dana Rook | `birch` | Analyst |")
        (self.root / "System" / "context.md").write_text(ctx)
        write(self.acme / "Threads" / "Pricing" / "Notes.md", "Dana wants it by Friday.\n")
        self.assertEqual([], self.walls())
        write(self.acme / "Threads" / "Pricing" / "Notes.md", "Dana Rook wants it by Friday.\n")
        self.assertEqual(1, len(self.walls()))

    def test_no_names_no_finding(self):
        write(self.birch / "Threads" / "Market Sizing" / "Notes.md", "Nordic demand, three scenarios, one chart.\n")
        self.assertEqual([], self.walls())

    def test_own_party_field_is_ignored(self):
        write(self.birch / "Notes.md", "---\ntitle: Scope\nparty:\n  - acme\n---\n\nScope for the entry work.\n")
        self.assertEqual([], self.walls())

    def test_sources_are_exempt_from_names(self):
        write(self.acme / "Sources" / "Their supplier list.csv", "supplier,notes\nNorth Mill,also supplies Birch & Co\n")
        self.assertEqual([], self.walls())

    def test_file_name_counts(self):
        write(self.birch / "Deliverables" / "260302 - Acme comparison.md", "A comparison.\n")
        self.assertEqual(1, len(self.walls()))


class TestQuotes(WallCase):
    def setUp(self):
        super().setUp()
        page = meeting_page("Work", "[birch]", "Birch call").replace("Decisions.", SECRET + ".")
        write(self.meetings / "wiki" / "sources" / "260314-birch-call.md", page)

    def test_quote_across_the_wall(self):
        write(self.acme / "Threads" / "Pricing" / "Notes.md", "Heard that the Oslo depot signed before the tenth of November.\n")
        found = self.walls()
        self.assertEqual(1, len(found), found)
        self.assertIn("260314-birch-call", found[0].message)
        self.assertIn("birch", found[0].message)
        self.assertNoLeak(found, *SECRET_WORDS)

    def test_quote_from_the_raw_transcript(self):
        write(self.meetings / "raw" / "260312-birch-kickoff.vtt",
              "WEBVTT\n\n00:00:01.000 --> 00:00:04.000\n<v Theo Marsh>We lose the Bergen warehouse lease\n\n"
              "00:00:04.500 --> 00:00:08.000\n<v Theo Marsh>at the end of the spring quarter.\n")
        write(self.acme / "Deliverables" / "260302 - Board note.md",
              "They lose the Bergen warehouse lease at the end of the spring quarter.\n")
        found = self.walls()
        self.assertEqual(1, len(found), found)
        self.assertIn("260312-birch-kickoff", found[0].message)
        self.assertNoLeak(found, "bergen", "warehouse", "lease")

    def test_quote_on_the_same_side_passes(self):
        write(self.birch / "Threads" / "Market Sizing" / "Notes.md", SECRET + "\n")
        self.assertEqual([], self.walls())

    def test_common_phrase_is_not_a_quote(self):
        phrase = "Let me know if you have any questions about it and we will get back to you"
        page = meeting_page("Work", "[birch]", "Birch wrap").replace("Decisions.", phrase + ".")
        write(self.meetings / "wiki" / "sources" / "260316-birch-wrap.md", page)
        write(self.acme / "Threads" / "Pricing" / "Notes.md", phrase + ".\n")
        self.assertEqual([], self.walls())

    def test_seven_words_is_below_the_threshold(self):
        write(self.acme / "Threads" / "Pricing" / "Notes.md", "the Oslo depot signed before the tenth\n")
        self.assertEqual([], self.walls())

    def test_wording_also_on_the_near_side_passes(self):
        page = meeting_page("Work", "[acme]", "Acme call").replace("Decisions.", SECRET + ".")
        write(self.meetings / "wiki" / "sources" / "260315-acme-call.md", page)
        write(self.acme / "Threads" / "Pricing" / "Notes.md", SECRET + "\n")
        self.assertEqual([], self.walls())

    def test_published_wording_crosses_every_wall(self):
        write(self.knowledge / "raw" / "depot-article.txt", "Report: " + SECRET + ".\n")
        write(self.acme / "Threads" / "Pricing" / "Notes.md", "the Oslo depot signed before the tenth of November at any price\n")
        self.assertEqual([], self.walls())

    def assertSharedCrosses(self, *names):
        """Wording in each of these files, one at a time, crosses every wall."""
        write(self.acme / "Threads" / "Pricing" / "Notes.md", SECRET + "\n")
        for name in names:
            with self.subTest(name):
                path = self.root / name
                before = path.read_bytes() if path.is_file() else None
                write(path, (before.decode() if before else "") + "\nReminder: " + SECRET + ".\n")
                try:
                    self.assertEqual([], self.walls())
                finally:
                    if before is None:
                        path.unlink()
                    else:
                        path.write_bytes(before)
        self.assertEqual(1, len(self.walls()))  # each file put back: a quote again

    def test_system_wording_crosses_every_wall(self):
        # Only the files in System/ that every side reads by design.
        self.assertSharedCrosses("System/rules.md", "System/context.md", "System/skills/threads/SKILL.md",
                                 "System/templates/thread/Thread.md", "System/tools/README.md")

    def test_instruction_files_cross_every_wall(self):
        self.assertSharedCrosses("AGENTS.md", "Wikis/AGENTS.md", "Wikis/Meetings/AGENTS.md")

    def test_the_local_files_beside_them_cross_every_wall(self):
        self.assertSharedCrosses("AGENTS.local.md", "Wikis/AGENTS.local.md", "Wikis/Meetings/AGENTS.local.md",
                                 "System/rules.local.md")

    def test_other_system_files_exempt_nothing(self):
        # A file dropped into System/ is not one every side reads by design.
        write(self.root / "System" / "notes.md", "Reminder: " + SECRET + ".\n")
        write(self.acme / "Threads" / "Pricing" / "Notes.md", SECRET + "\n")
        found = self.walls()
        self.assertEqual(1, len(found), found)
        self.assertIn("260314-birch-call", found[0].message)
        self.assertNoLeak(found, *SECRET_WORDS)

    def test_interview_record_exempts_nothing(self):
        # The interview keeps its record in System/interviews/, in the user's own
        # words. A confidence that slips into it must not become common wording.
        write(self.root / "System" / "interviews" / "261003 - Getting started.md",
              "# Interview: Getting started\n\n## 2. Whose confidences you hold\n\n" + SECRET + ".\n")
        write(self.acme / "Threads" / "Pricing" / "Notes.md", SECRET + "\n")
        found = self.walls()
        self.assertEqual(1, len(found), found)
        self.assertEqual("Zones/Work/Acme Review/Threads/Pricing/Notes.md", found[0].path)
        self.assertIn("260314-birch-call", found[0].message)
        self.assertNoLeak(found, *SECRET_WORDS)
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(1, check.main(["--root", str(self.root)]))
        self.assertNotIn("No problems found.", buf.getvalue())

    def test_generated_pages_exempt_nothing(self):
        # A page that gathers every zone, kept in System/generated/, must not
        # turn what it repeats into common wording.
        write(self.root / "System" / "generated" / "status.html", "<p>" + SECRET + "</p>\n")
        write(self.acme / "Threads" / "Pricing" / "Notes.md", SECRET + "\n")
        found = self.walls()
        self.assertEqual(1, len(found), found)
        self.assertIn("260314-birch-call", found[0].message)
        self.assertNoLeak(found, *SECRET_WORDS)

    def test_sources_are_checked_for_quotes(self):
        write(self.acme / "Sources" / "Pasted.txt", SECRET + "\n")
        found = self.walls()
        self.assertEqual(["Zones/Work/Acme Review/Sources/Pasted.txt"], [f.path for f in found])

    def test_one_finding_per_meeting_when_it_is_also_linked(self):
        write(self.acme / "Threads" / "Pricing" / "Notes.md", "[[260314-birch-call]]: " + SECRET + "\n")
        found = self.walls()
        self.assertEqual(1, len(found), found)
        self.assertIn("links", found[0].message)


def _real_repo(zone: Path) -> None:
    shutil.rmtree(zone / ".git")
    git(zone, "init", "-q")
    install_wall_hook(zone)
    commit_all(zone, "start")


def _copy_tools(root: Path) -> None:
    tools = root / "System" / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    for name in ("check.py", "garrick_lib.py"):
        shutil.copy2(TOOLS / name, tools / name)


def _run(args, cwd):
    return subprocess.run([str(a) for a in args], cwd=str(cwd), env=ENV, capture_output=True, text=True)


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class TestStaged(WallCase):
    def setUp(self):
        super().setUp()
        _copy_tools(self.root)
        self.zone = self.root / "Zones" / "Work"
        _real_repo(self.zone)
        self.note = self.birch / "Threads" / "Market Sizing" / "Notes.md"

    def staged(self):
        return _run([sys.executable, self.root / "System" / "tools" / "check.py", "--staged", "--walls-only"], self.zone)

    def test_clean_stage_passes_silently(self):
        write(self.note, "Three scenarios.\n")
        git(self.zone, "add", "-A")
        res = self.staged()
        self.assertEqual((0, "", ""), (res.returncode, res.stdout, res.stderr))

    def test_staged_breach_is_one_plain_line(self):
        write(self.note, "Dana Whitlock called.\n")
        git(self.zone, "add", "-A")
        res = self.staged()
        self.assertEqual(1, res.returncode)
        lines = res.stderr.strip().splitlines()
        self.assertEqual(1, len(lines), res.stderr)
        self.assertTrue(lines[0].startswith("Commit refused: Zones/Work/Birch Entry/Threads/Market Sizing/Notes.md names <acme>"))
        self.assertIn("--no-verify", lines[0])
        self.assertNotIn("Dana", res.stderr)

    def test_only_the_staged_version_counts(self):
        write(self.note, "Dana Whitlock called.\n")  # in the working tree, not staged
        self.assertEqual(0, self.staged().returncode)
        git(self.zone, "add", "-A")
        write(self.note, "Three scenarios.\n")  # fixed in the tree, but the breach is what is staged
        self.assertEqual(1, self.staged().returncode)

    def test_only_staged_files_are_read(self):
        write(self.acme / "Threads" / "Pricing" / "Notes.md", "Theo Marsh called.\n")  # a breach, left unstaged
        write(self.note, "Three scenarios.\n")
        git(self.zone, "add", "--", str(self.note.relative_to(self.zone)))
        self.assertEqual(0, self.staged().returncode)
        self.assertEqual(1, len(self.walls()))  # the full check still sees it

    def test_files_outside_projects_are_not_walled(self):
        todo = self.zone / "Todo.md"
        todo.write_text(todo.read_text() + "- [ ] Send Theo Marsh and Dana Whitlock their notes\n")
        git(self.zone, "add", "-A")
        self.assertEqual(0, self.staged().returncode)

    def test_quote_is_refused_without_leaking(self):
        page = meeting_page("Work", "[birch]", "Birch call").replace("Decisions.", SECRET + ".")
        write(self.meetings / "wiki" / "sources" / "260314-birch-call.md", page)
        write(self.acme / "Deliverables" / "260302 - Board note.md", SECRET + "\n")
        git(self.zone, "add", "-A")
        res = self.staged()
        self.assertEqual(1, res.returncode)
        self.assertIn("260314-birch-call", res.stderr)
        for word in SECRET_WORDS:
            self.assertNotIn(word, res.stderr.lower())

    def test_interview_record_does_not_open_the_hook(self):
        page = meeting_page("Work", "[birch]", "Birch call").replace("Decisions.", SECRET + ".")
        write(self.meetings / "wiki" / "sources" / "260314-birch-call.md", page)
        write(self.root / "System" / "interviews" / "261003 - Getting started.md",
              "# Interview: Getting started\n\n## 2. Whose confidences you hold\n\n" + SECRET + ".\n")
        write(self.acme / "Deliverables" / "260302 - Board note.md", SECRET + "\n")
        git(self.zone, "add", "-A")
        head = git(self.zone, "rev-parse", "HEAD")
        res = _run(["git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "Board note"], self.zone)
        self.assertEqual(1, res.returncode, res.stderr)
        lines = res.stderr.strip().splitlines()
        self.assertEqual(1, len(lines), res.stderr)
        self.assertTrue(lines[0].startswith("Commit refused: Zones/Work/Acme Review/Deliverables/260302 - Board note.md "
                                            "repeats wording from meeting 260314-birch-call"), lines[0])
        for word in SECRET_WORDS:
            self.assertNotIn(word, res.stderr.lower())
        self.assertEqual(head, git(self.zone, "rev-parse", "HEAD"))

    def test_a_saved_brief_goes_through_the_hook(self):
        # Prep, asked to save, writes Deliverables/YYMMDD - <name>.md with the
        # pages it drew on linked as [[Meetings/wiki/sources/<slug>|<title>]],
        # and commits it in the zone: the hook reads those links.
        brief = self.acme / "Deliverables" / "260315 - Brief for the kick-off.md"
        name = str(brief.relative_to(self.zone))
        commit = ["git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "Acme Review: brief for Acme"]
        write(brief, "# Brief for the kick-off\n\nFrom [[Meetings/wiki/sources/260310-acme-kickoff|Acme kick-off]]: "
                     "work starts on Monday.\n")
        git(self.zone, "add", "--", name)
        res = _run(commit, self.zone)
        self.assertEqual(0, res.returncode, res.stderr)
        self.assertEqual([], [f for f in check.run_checks(self.root) if f.check in ("walls", "deliverables")])

        write(brief, brief.read_text() + "\nSee also [[Meetings/wiki/sources/260312-birch-kickoff|the other kick-off]].\n")
        git(self.zone, "add", "--", name)
        head = git(self.zone, "rev-parse", "HEAD")
        res = _run(commit, self.zone)
        self.assertEqual(1, res.returncode, res.stderr)
        self.assertIn("Commit refused: Zones/Work/Acme Review/Deliverables/260315 - Brief for the kick-off.md links",
                      res.stderr)
        self.assertEqual(head, git(self.zone, "rev-parse", "HEAD"))

    def test_hook_blocks_and_no_verify_overrides(self):
        self.assertTrue(has_wall_hook(self.zone))
        write(self.note, "Dana Whitlock called.\n")
        git(self.zone, "add", "-A")
        head = git(self.zone, "rev-parse", "HEAD")
        res = _run(["git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "notes"], self.zone)
        self.assertEqual(1, res.returncode)
        self.assertIn("Commit refused", res.stderr)
        self.assertEqual(head, git(self.zone, "rev-parse", "HEAD"))
        res = _run(["git", "-c", "commit.gpgsign=false", "commit", "-q", "--no-verify", "-m", "notes"], self.zone)
        self.assertEqual(0, res.returncode, res.stderr)

    def test_install_hook_refuses_a_foreign_hook(self):
        hook = self.zone / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\nexit 0\n")
        with self.assertRaises(FileExistsError):
            install_wall_hook(self.zone)
        self.assertFalse(has_wall_hook(self.zone))
        found = [f for f in check.run_checks(self.root) if f.check == "zones"]
        self.assertIn("--install-hooks", " ".join(f.message for f in found))


# Each way a YAML reader finds a key at the left margin that a line reader
# does not, and a key given twice, of which YAML keeps the last. `{key}` is
# the key the walls read on the page, `{value}` the party it would say.
OTHER_KEYS = {
    "double-quoted": '"{key}": {value}',
    "single-quoted": "'{key}': {value}",
    "complex": "? {key}\n: {value}",
    "tagged": "!!str {key}: {value}",
    "anchored": "&k {key}: {value}",
    "aliased": "*k : {value}",
    "merged": "<<: {{{key}: {value}}}",
    "flow mapping": "{{{key}: {value}}}",
    "flow sequence": "[{key}]: {value}",
    "duplicate": "{key}: {value}",
}

NORTHWIND = "---\ntitle: Northwind Labs\ntype: entity\nparty: none\n%s\n---\n\n# Northwind Labs\n"


class TestFrontmatterForm(WallCase):
    """A page the walls read must say its keys one way (#330): a quoted,
    complex, tagged, anchored, aliased, merged or flow key, or a key given
    twice, could give a YAML reader another party from the one the walls
    read, so each is refused."""

    def entity(self, form: str) -> Path:
        line = OTHER_KEYS[form].format(key="party", value="birch")
        return write(self.meetings / "wiki" / "entities" / "northwind-labs.md", NORTHWIND % line)

    def meeting(self, form: str) -> Path:
        page = self.meetings / "wiki" / "sources" / "260314-second-kickoff.md"
        line = OTHER_KEYS[form].format(key="parties", value="[birch]")
        write(page, meeting_page("Work", "[acme]", "Second kick-off").replace("people:", line + "\npeople:"))
        pricing = self.acme / "Threads" / "Pricing" / "Pricing.md"
        write(pricing, pricing.read_text() + "\nAlso [[260314-second-kickoff]].\n")
        return page

    def form_errors(self, findings):
        return sorted(f.path for f in findings if f.severity == "error" and f.message.startswith(check.FRONTMATTER_PLAIN))

    def test_an_entity_page_in_each_form_is_refused(self):
        for form in OTHER_KEYS:
            with self.subTest(form=form):
                self.entity(form)
                self.assertEqual(["Wikis/Meetings/wiki/entities/northwind-labs.md"], self.form_errors(self.walls()))

    def test_an_entity_page_read_two_ways_is_whose_to_no_one(self):
        self.entity("double-quoted")
        write(self.meetings / "wiki" / "people" / "dana-whitlock.md",
              '---\ntitle: Dana Whitlock\ntype: person\nparty: acme\norganisation: "[[wiki/entities/northwind-labs]]"\n'
              "---\n\n# Dana Whitlock\n\nHead of procurement.\n")
        found = [f for f in self.walls() if f.path.endswith("dana-whitlock.md")]
        self.assertEqual(1, len(found), found)
        self.assertEqual("error", found[0].severity)
        index = check.entity_index(check.discover(self.root))
        self.assertFalse(next(e for e in index if e["rel"] == "northwind-labs")["tagged"])
        self.entity("duplicate")
        self.assertNotIn("northwind-labs", sum(check.party_entities(self.root).values(), []))

    def test_a_meeting_page_in_each_form_is_refused_and_so_is_its_use(self):
        for form in OTHER_KEYS:
            with self.subTest(form=form):
                self.meeting(form)
                found = self.walls()
                self.assertEqual(["Wikis/Meetings/wiki/sources/260314-second-kickoff.md"], self.form_errors(found))
                use = [f for f in found if f.path.endswith("Pricing.md") and "260314-second-kickoff" in f.message]
                self.assertEqual(["error"], [f.severity for f in use], [f.message for f in found])

    def test_plain_pages_pass(self):
        write(self.meetings / "wiki" / "entities" / "northwind-labs.md",
              "---\n# a comment\ntitle: Northwind Labs\ntype: entity\nparty: none\naliases:\n  - Northwind\n"
              "---\n\n# Northwind Labs\n")
        self.assertEqual([], self.form_errors(self.walls()))

    def test_a_knowledge_page_counts_only_its_party_keys_twice(self):
        page = self.knowledge / "wiki" / "sources" / "supply-chain-report.md"
        base = "---\ntitle: Supply chains\ntype: source\nconfidence: medium\n%s---\n\nSee [[resilience]].\n"
        write(page, base % "tags: [a]\ntags: [b]\n")
        self.assertEqual([], self.form_errors(self.walls()))
        write(page, base % '"party": birch\n')
        self.assertEqual(["Wikis/Knowledge/wiki/sources/supply-chain-report.md"], self.form_errors(self.walls()))
        write(page, base % "zone: Work\nzone: Personal\n")
        self.assertEqual(["Wikis/Knowledge/wiki/sources/supply-chain-report.md"], self.form_errors(self.walls()))

    def test_a_hub_and_a_thread_note_are_read_for_their_form(self):
        hub = self.acme / "Acme Review.md"
        write(hub, hub.read_text().replace("party: acme", 'party: acme\n"party": birch', 1))
        note = self.birch / "Threads" / "Market Sizing" / "Market Sizing.md"
        write(note, note.read_text().replace("party: birch", "party: birch\nparty: acme", 1))
        self.assertEqual(["Zones/Work/Acme Review/Acme Review.md",
                          "Zones/Work/Birch Entry/Threads/Market Sizing/Market Sizing.md"],
                         self.form_errors(self.walls()))

    @unittest.skipUnless(HAVE_GIT, "git is not installed")
    def test_the_hook_refuses_each_form_staged(self):
        wikis = self.root / "Wikis"
        git(wikis, "init", "-q")
        commit_all(wikis, "start")
        for form in OTHER_KEYS:
            with self.subTest(form=form):
                entity, meeting = self.entity(form), self.meeting(form)
                git(wikis, "add", "-A")
                found = check.run_checks(self.root, walls_only=True, staged=wikis)
                self.assertEqual(["Wikis/Meetings/wiki/entities/northwind-labs.md",
                                  "Wikis/Meetings/wiki/sources/260314-second-kickoff.md"], self.form_errors(found))
                git(wikis, "reset", "-q")
                entity.unlink()
                meeting.unlink()

    @unittest.skipUnless(HAVE_GIT, "git is not installed")
    def test_the_hook_reads_the_hub_of_a_staged_project_file(self):
        zone = self.root / "Zones" / "Work"
        hub = self.acme / "Acme Review.md"
        write(hub, hub.read_text().replace("party: acme", "party: acme\n? party\n: birch", 1))
        _real_repo(zone)
        write(self.acme / "Threads" / "Pricing" / "Notes.md", "Three scenarios.\n")
        git(zone, "add", "-A")
        found = check.run_checks(self.root, walls_only=True, staged=zone)
        self.assertEqual(["Zones/Work/Acme Review/Acme Review.md"], self.form_errors(found))


# Each way a value says more to a YAML reader than to a line reader: `{key}`
# is the key the walls read, `{value}` the party a YAML reader would find.
VALUE_FORMS = {
    "block scalar holding a dash": "notes: |\n  ---\n{key}: {value}",
    "quote over two lines": 'title: "Second\n{key}: {value}\ntype: x"',
    "flow list over two lines": "{key}: [cedar,\n  {value}]",
    "folded block": "{key}: >-\n  {value}",
    "literal block": "{key}: |\n  {value}",
    "tagged value": "{key}: !!str {value}",
    "anchored value": "{key}: &p {value}",
    "aliased value": "{key}: *p",
    "plain value continued": "{key}: cedar\n  {value}",
    "value on the next line": "{key}:\n  {value}",
    "item under a key with a value": "{key}: cedar\n  - {value}",
}

CEDAR = "| Cedar Ltd | Supplier | Work | `cedar` | no | cedar.example |\n| Birch & Co | Client."


class TestFrontmatterValues(WallCase):
    """A value the walls read as text where a YAML reader finds a party, a
    frontmatter a YAML reader ends somewhere else, or a party or zone the
    walls do not know, is refused rather than read as no party (#330)."""

    def setUp(self):
        super().setUp()
        ctx = self.root / "System" / "context.md"
        ctx.write_text(ctx.read_text().replace("| Birch & Co | Client.", CEDAR, 1))

    def meeting(self, lines: str) -> Path:
        page = self.meetings / "wiki" / "sources" / "260314-second-kickoff.md"
        write(page, "---\ntitle: Second\ntype: meeting\ndate: 2026-03-14\nzone: Work\n%s\n---\n\n# Second\n" % lines)
        pricing = self.acme / "Threads" / "Pricing" / "Pricing.md"
        if "260314-second-kickoff" not in pricing.read_text():
            write(pricing, pricing.read_text() + "\nAlso [[260314-second-kickoff]].\n")
        return page

    def entity(self, lines: str) -> Path:
        return write(self.meetings / "wiki" / "entities" / "northwind-labs.md",
                     "---\ntitle: Northwind Labs\ntype: entity\n%s\n---\n\n# Northwind Labs\n" % lines)

    def errors_on(self, findings, *names):
        return sorted({f.path.rsplit("/", 1)[-1] for f in findings if f.severity == "error"} & set(names))

    def test_only_a_plain_dash_line_ends_the_frontmatter(self):
        import garrick_lib
        text = "---\ntitle: a\nnotes: |\n  ---\nparty: birch\n--- \nparty: acme\n---\nBody.\n"
        self.assertEqual("acme", garrick_lib.parse_frontmatter_text(text)["party"])
        self.assertEqual({}, garrick_lib.parse_frontmatter_text("---\nparty: birch\n  ---\nBody.\n"))
        self.assertTrue(garrick_lib.frontmatter_form_problem("---\nparty: none\n--- \nparty: birch\n"))

    def test_a_meeting_page_in_each_value_form_is_refused_and_so_is_its_use(self):
        for form, line in VALUE_FORMS.items():
            with self.subTest(form=form):
                self.meeting(line.format(key="parties", value="birch"))
                found = self.walls()
                self.assertEqual(["260314-second-kickoff.md", "Pricing.md"],
                                 self.errors_on(found, "260314-second-kickoff.md", "Pricing.md"),
                                 [f.message for f in found])

    def test_an_entity_page_in_each_value_form_is_refused(self):
        for form, line in VALUE_FORMS.items():
            with self.subTest(form=form):
                lead = "party: none\n" if form.startswith(("block", "quote")) else ""
                self.entity(lead + line.format(key="party", value="birch"))
                self.assertEqual(["northwind-labs.md"], self.errors_on(self.walls(), "northwind-labs.md"))

    def test_a_hub_and_a_thread_note_in_each_value_form_are_refused(self):
        hub = self.birch / "Birch Entry.md"
        note = self.birch / "Threads" / "Market Sizing" / "Market Sizing.md"
        plain = {p: p.read_text() for p in (hub, note)}
        for form, line in VALUE_FORMS.items():
            if form.startswith(("block", "quote")):
                continue                                # the party line is the duplicate: covered above
            with self.subTest(form=form):
                for p, text in plain.items():
                    write(p, text.replace("party: birch", line.format(key="party", value="birch"), 1))
                self.assertEqual(["Birch Entry.md", "Market Sizing.md"],
                                 self.errors_on(self.walls(), "Birch Entry.md", "Market Sizing.md"))

    def test_a_party_or_zone_the_walls_do_not_know_turns_them_on(self):
        for lines in ("parties: [birch-co]", "parties: [cedar, birch\u200b]"):
            with self.subTest(lines=lines):
                self.meeting(lines)
                found = self.walls()
                self.assertEqual(["260314-second-kickoff.md", "Pricing.md"],
                                 self.errors_on(found, "260314-second-kickoff.md", "Pricing.md"))
                self.assertTrue(any(f.message.startswith(check.WALLS_VALUE) for f in found))
        page = self.meeting("parties: [cedar]")
        write(page, page.read_text().replace("zone: Work", "zone: Wrok"))
        self.assertEqual(["260314-second-kickoff.md", "Pricing.md"],
                         self.errors_on(self.walls(), "260314-second-kickoff.md", "Pricing.md"))
        self.entity("party: birchco")
        self.assertIn("northwind-labs.md", self.errors_on(self.walls(), "northwind-labs.md"))
        hub = self.birch / "Birch Entry.md"
        write(hub, hub.read_text().replace("party: birch", "party: birch\u200b", 1))
        self.assertIn("Birch Entry.md", self.errors_on(self.walls(), "Birch Entry.md"))

    def test_plain_values_pass(self):
        self.meeting('parties: [cedar]      # from the Parties table\npeople: ["[[wiki/people/dana-whitlock]]"]\n'
                     'aliases:\n  - "Second, again"\n  - other\nnote: "a # b" # c\nsee: [[wiki/entities/acme-corp]]')
        self.entity("party: none\naliases: [Northwind, \"NW Labs\"]")
        self.assertEqual([], [f for f in self.walls() if f.severity == "error"])

    @unittest.skipUnless(HAVE_GIT, "git is not installed")
    def test_the_hook_refuses_the_use_of_a_meeting_page_committed_before(self):
        # A line reader stopping at the indented `---` reads `parties: [cedar]`; YAML reads `[birch]`.
        self.meeting('summary: "Second meeting\nparties: [cedar]\nsaid: none"\nnotes: |\n  ---\nparties: [birch]')
        wikis = self.root / "Wikis"
        git(wikis, "init", "-q")
        commit_all(wikis, "start")
        zone = self.root / "Zones" / "Work"
        pricing = self.acme / "Threads" / "Pricing" / "Pricing.md"
        text = pricing.read_text()
        write(pricing, text.replace("\nAlso [[260314-second-kickoff]].\n", ""))
        _real_repo(zone)
        write(pricing, text)
        git(zone, "add", "-A")
        found = check.run_checks(self.root, walls_only=True, staged=zone)
        self.assertEqual(["Pricing.md"], self.errors_on(found, "Pricing.md"), [f.message for f in found])

    @unittest.skipUnless(HAVE_GIT, "git is not installed")
    def test_the_hook_reads_a_tagged_party_on_the_hub_of_a_staged_file(self):
        zone = self.root / "Zones" / "Work"
        for p in (self.birch / "Birch Entry.md", self.birch / "Threads" / "Market Sizing" / "Market Sizing.md"):
            write(p, p.read_text().replace("party: birch", "party: !!str birch", 1))
        _real_repo(zone)
        write(self.birch / "Threads" / "Market Sizing" / "Notes.md", "Three scenarios.\n")
        git(zone, "add", "-A")
        found = check.run_checks(self.root, walls_only=True, staged=zone)
        self.assertEqual(["Birch Entry.md", "Market Sizing.md"], self.errors_on(found, "Birch Entry.md", "Market Sizing.md"))


# Wording only the Acme side wrote, in an Acme note. Never allowed in a finding either.
PLAN = "The client intends to fold its three northern warehouses into one bonded hub by spring"
PLAN_WORDS = ("warehouses", "bonded", "spring")


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class TestStagedAgainstDisk(WallCase):
    """The commit check reads what it is not committing, the other projects and
    the meetings, as git holds it as well as from disk: an edit left unstaged
    must not decide what the commit is allowed to quote."""

    def setUp(self):
        super().setUp()
        _copy_tools(self.root)
        self.zone = self.root / "Zones" / "Work"
        _real_repo(self.zone)
        self.note = self.birch / "Threads" / "Market Sizing" / "Notes.md"
        self.acme_note = self.acme / "Threads" / "Pricing" / "Notes.md"
        write(self.acme_note, PLAN + ".\n")
        commit_all(self.zone, "Acme notes")

    def staged(self, cwd=None):
        return _run([sys.executable, self.root / "System" / "tools" / "check.py", "--staged", "--walls-only"],
                    cwd or self.zone)

    def stage(self, path):
        git(self.zone, "add", "--", str(path.relative_to(self.zone)))

    def stage_quote(self):
        write(self.note, "Worth knowing: " + PLAN.lower() + ".\n")
        self.stage(self.note)

    def stage_secret(self):
        brief = self.acme / "Deliverables" / "260302 - Board note.md"
        write(brief, SECRET + "\n")
        self.stage(brief)

    def birch_call(self, parties="[birch]"):
        """A Birch meeting holding SECRET, committed in the Wikis repository."""
        wikis = self.root / "Wikis"
        if not (wikis / ".git").exists():
            git(wikis, "init", "-q")
        page = self.meetings / "wiki" / "sources" / "260314-birch-call.md"
        write(page, meeting_page("Work", parties, "Birch call").replace("Decisions.", SECRET + "."))
        commit_all(wikis, "Birch call")
        return page

    def assertRefused(self, *expect):
        res = self.staged()
        self.assertEqual(1, res.returncode, res.stderr)
        for text in expect:
            self.assertIn(text, res.stderr)
        for word in PLAN_WORDS + SECRET_WORDS:
            self.assertNotIn(word, res.stderr.lower())
        return res

    def test_source_edited_on_disk_only(self):
        source = "repeats wording from Zones/Work/Acme Review/Threads/Pricing/Notes.md"
        self.stage_quote()
        self.assertRefused(source)
        write(self.acme_note, "Nothing much.\n")           # the index still holds the plan
        self.assertRefused(source)
        self.acme_note.unlink()                             # and still holds it once the file is gone from disk
        self.assertRefused(source)

    def test_cut_and_paste_staged_whole_is_a_known_limit(self):
        # Moving the sentence, and staging both sides, leaves only history to
        # say where it came from. The check does not read history, and the
        # docs say so, next to paraphrase. If this ever fails, update them.
        self.stage_quote()
        write(self.acme_note, "Nothing much.\n")
        git(self.zone, "add", "-A")
        self.assertEqual(0, self.staged().returncode)

    def test_meeting_edited_in_its_own_repository(self):
        page = self.birch_call()
        self.stage_secret()
        self.assertRefused("260314-birch-call")
        write(page, meeting_page("Work", "[birch]", "Birch call"))   # its last commit still holds the words
        self.assertRefused("260314-birch-call")
        page.unlink()
        self.assertRefused("260314-birch-call")

    def test_meeting_parties_edited_in_its_own_repository(self):
        page = self.birch_call()
        page.write_text(page.read_text().replace("parties: [birch]", "parties: [acme]"))
        self.stage_secret()
        self.assertRefused("repeats wording from meeting 260314-birch-call, a meeting with birch")

    def test_party_changed_on_disk_only(self):
        # Read from disk alone, both notes would say the project is Acme's,
        # and the quotation of an Acme note would pass.
        self.stage_quote()
        hub = self.birch / "Birch Entry.md"
        thread = self.birch / "Threads" / "Market Sizing" / "Market Sizing.md"
        for note in (hub, thread):
            note.write_text(note.read_text().replace("party: birch", "party: acme"))
        res = self.assertRefused("Birch Entry/Birch Entry.md names a different party on disk from the one staged",
                                 "Market Sizing/Market Sizing.md names a different party on disk from the one staged")
        self.assertEqual(2, len(res.stderr.strip().splitlines()), res.stderr)
        git(self.zone, "add", "-A")                         # staged, the commit declares it: nothing ambiguous
        res = self.staged()
        self.assertNotIn("different party", res.stderr)
        self.assertNotIn("repeats wording", res.stderr)
        self.assertIn("names <birch>", res.stderr)       # an Acme project called Birch Entry names Birch; a run with no terminal says the tag

    def test_thread_party_changed_on_disk_only(self):
        self.stage_quote()
        thread = self.birch / "Threads" / "Market Sizing" / "Market Sizing.md"
        thread.write_text(thread.read_text().replace("party: birch", "party: acme"))
        self.assertRefused("Market Sizing/Market Sizing.md names a different party on disk from the one staged")

    def test_source_party_changed_in_another_zone(self):
        personal = self.root / "Zones" / "Personal"
        _real_repo(personal)
        house = personal / "House"
        write(house / "House.md", fixtures.project_hub("Personal", "House", "birch"))
        write(house / "Threads" / "Notes" / "Notes.md", "# Notes\n\n" + SECRET + ".\n")
        commit_all(personal, "House, for Birch")
        hub = house / "House.md"
        hub.write_text(hub.read_text().replace("party: birch", "party: acme"))   # on disk only, another repository
        self.stage_secret()
        self.assertRefused("repeats wording from Zones/Personal/House/Threads/Notes/Notes.md")

    def test_shared_file_edited_on_disk_only(self):
        git(self.root, "init", "-q")
        git(self.root, "add", "AGENTS.md", "System/rules.md")
        git(self.root, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "root")
        rules = self.root / "System" / "rules.md"
        rules.write_text(rules.read_text() + "\n" + PLAN + ".\n")   # would make the plan common wording
        self.stage_quote()
        source = "repeats wording from Zones/Work/Acme Review/Threads/Pricing/Notes.md"
        self.assertRefused(source)
        git(self.root, "add", "System/rules.md")            # staged in the root is still not committed there
        self.assertRefused(source)

    def test_nested_inbox_files_are_refused(self):
        inbox = self.zone / "Inbox"
        write(inbox / "nested" / "unfiled.txt", "A note dropped as a folder.\n")
        (inbox / "bundle").mkdir()
        (inbox / "bundle" / "scan.pdf").write_bytes(b"%PDF-1.4\n\0\x01\x02binary")
        write(inbox / "bundle" / ".gitkeep")                # only the inbox's own placeholder is exempt
        git(self.zone, "add", "-f", "Inbox")
        res = self.staged()
        self.assertEqual(1, res.returncode)
        refused = sorted(line.split(" is waiting")[0] for line in res.stderr.strip().splitlines())
        self.assertEqual(["Commit refused: Zones/Work/Inbox/bundle/.gitkeep",
                          "Commit refused: Zones/Work/Inbox/bundle/scan.pdf",
                          "Commit refused: Zones/Work/Inbox/nested/unfiled.txt"], refused)

    def test_the_inbox_placeholder_alone_passes(self):
        (self.zone / "Inbox" / ".gitkeep").write_text("\n")
        git(self.zone, "add", "-A")
        self.assertEqual(0, self.staged().returncode)

    def test_nested_meetings_inbox_files_are_refused(self):
        wikis = self.root / "Wikis"
        git(wikis, "init", "-q")
        commit_all(wikis, "start")
        inbox = self.meetings / "raw" / "inbox"
        write(inbox / "export" / "call.vtt", "WEBVTT\n")
        (inbox / "export" / "audio.bin").write_bytes(b"\0\x01binary")
        git(wikis, "add", "-f", "Meetings/raw/inbox")
        res = self.staged(wikis)
        self.assertEqual(1, res.returncode)
        self.assertIn("Wikis/Meetings/raw/inbox/export/call.vtt is waiting in the Meetings inbox", res.stderr)
        self.assertIn("Wikis/Meetings/raw/inbox/export/audio.bin is waiting in the Meetings inbox", res.stderr)


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class TestInstalledHook(unittest.TestCase):
    """The installer puts the hook in every zone; scaffolding commits pass it and a breach does not."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(cls.tmp.name).resolve()
        cls.root = base / "ws"
        cfg = {
            "owner": {"name": "Jo Example", "description": "Independent advisor."},
            "zones": ["Work", "Personal"],
            "parties": [{"name": "Acme Corp", "what": "Client", "zone": "Work", "tag": "acme"},
                        {"name": "Birch & Co", "what": "Client", "zone": "Work", "tag": "birch"}],
            "walls": [["acme", "birch", "Competitors"]],
            "people": [{"name": "Dana Whitlock", "party": "acme", "role": "Procurement"},
                       {"name": "Theo Marsh", "party": "birch", "role": "Managing partner"}],
        }
        config = base / "config.json"
        config.write_text(json.dumps(cfg))
        env = dict(ENV, HOME=str(base), GARRICK_INSTALL_NO_PAGE="1",     # the status page put in place, not built,
                   GARRICK_CALLER_BUILDS_PAGE="1")                      # nor by scaffold.py in the background
        cls.env = env
        cls.install = subprocess.run([sys.executable, str(INSTALL), "--config", str(config), "--target", str(cls.root)],
                                     env=env, capture_output=True, text=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def git(self, zone, *args):
        return subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=str(zone), env=self.env,
                              capture_output=True, text=True)

    def test_every_zone_has_the_hook_and_the_check_is_clean(self):
        self.assertEqual(0, self.install.returncode, self.install.stderr)
        for zone in ("Work", "Personal"):
            hook = self.root / "Zones" / zone / ".git" / "hooks" / "pre-commit"
            self.assertTrue(os.access(hook, os.X_OK), hook)
        res = subprocess.run([sys.executable, str(self.root / "System" / "tools" / "check.py"), "--ear"],
                             env=self.env, capture_output=True, text=True)
        self.assertEqual("All clear.", res.stdout.strip(), res.stdout)

    def test_the_meetings_inbox_stays_out_of_the_wikis_history(self):
        self.assertEqual(0, self.install.returncode, self.install.stderr)
        wikis = self.root / "Wikis"
        self.assertEqual(0, self.git(wikis, "check-ignore", "-q", "Meetings/raw/inbox/call.vtt").returncode)
        self.assertEqual("Meetings/raw/inbox/.gitkeep", self.git(wikis, "ls-files", "Meetings/raw/inbox").stdout.strip())

    def test_scaffold_commits_and_a_breach_is_refused(self):
        self.assertEqual(0, self.install.returncode, self.install.stderr)
        work = self.root / "Zones" / "Work"
        res = subprocess.run([sys.executable, str(self.root / "System" / "tools" / "scaffold.py"), "project",
                              "--zone", "Work", "--name", "Birch Entry", "--party", "birch", "--thread", "Launch Plan"],
                             cwd=str(self.root), env=self.env, capture_output=True, text=True)
        self.assertEqual(0, res.returncode, res.stdout + res.stderr)
        self.git(work, "add", "-A")
        res = self.git(work, "commit", "-q", "-m", "New project Birch Entry (birch), first thread Launch Plan")
        self.assertEqual(0, res.returncode, res.stderr)

        note = work / "Birch Entry" / "Threads" / "Launch Plan" / "Launch Plan.md"
        note.write_text(note.read_text() + "\nDana Whitlock thinks the launch is early.\n")
        self.git(work, "add", "-A")
        head = self.git(work, "rev-parse", "HEAD").stdout
        res = self.git(work, "commit", "-q", "-m", "Launch Plan: wrap")
        self.assertEqual(1, res.returncode)
        self.assertEqual(1, len(res.stderr.strip().splitlines()), res.stderr)
        self.assertIn("Launch Plan.md names <acme>", res.stderr)
        self.assertNotIn("Dana", res.stderr)
        self.assertEqual(head, self.git(work, "rev-parse", "HEAD").stdout)

        res = self.git(work, "commit", "-q", "--no-verify", "-m", "Launch Plan: wrap, deliberately")
        self.assertEqual(0, res.returncode, res.stderr)


if __name__ == "__main__":
    unittest.main()
