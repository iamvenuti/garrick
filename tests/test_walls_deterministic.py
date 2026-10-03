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
        self.assertIn("wall stands between birch and acme", found[0].message)
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
        self.assertTrue(lines[0].startswith("Commit refused: Zones/Work/Birch Entry/Threads/Market Sizing/Notes.md names Acme Corp"))
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
        env = dict(ENV, HOME=str(base))
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
        self.assertIn("Launch Plan.md names Acme Corp", res.stderr)
        self.assertNotIn("Dana", res.stderr)
        self.assertEqual(head, self.git(work, "rev-parse", "HEAD").stdout)

        res = self.git(work, "commit", "-q", "--no-verify", "-m", "Launch Plan: wrap, deliberately")
        self.assertEqual(0, res.returncode, res.stderr)


if __name__ == "__main__":
    unittest.main()
