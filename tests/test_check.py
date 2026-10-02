"""The checker, run against a fictional workspace: each check passes on the
clean fixture and fails on a broken one."""

from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from fixtures import (
    HAVE_GIT,
    build_workspace,
    commit_all,
    git_init,
    meeting_page,
    project_hub,
    thread_note,
    write,
)

import check  # noqa: E402  (fixtures puts the tools folder on sys.path)


class CheckCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve() / "Workspace"
        build_workspace(self.root)
        self.work = self.root / "Zones" / "Work"
        self.acme = self.work / "Acme Review"
        self.meetings = self.root / "Wikis" / "Meetings"

    def tearDown(self):
        self._tmp.cleanup()

    def findings(self, name=None, severity=None):
        found = check.run_checks(self.root)
        return [f for f in found
                if (name is None or f.check == name) and (severity is None or f.severity == severity)]

    def assertClean(self, name):
        self.assertEqual([], [(f.severity, f.path, f.message) for f in self.findings(name)])

    def assertFinds(self, name, severity, fragment=None, path=None):
        hits = self.findings(name, severity)
        if fragment is not None:
            hits = [f for f in hits if fragment in f.message]
        if path is not None:
            hits = [f for f in hits if f.path == path]
        self.assertTrue(hits, "no %s %s finding matching %r / %r in %s"
                        % (severity, name, fragment, path, self.findings()))
        return hits


class TestCleanWorkspace(CheckCase):
    def test_no_findings(self):
        self.assertEqual([], [(f.check, f.path, f.message) for f in self.findings()])

    def test_exit_code_and_outputs(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = check.main(["--root", str(self.root)])
        self.assertEqual(0, code)
        self.assertIn("No problems found.", buf.getvalue())
        buf = io.StringIO()
        with redirect_stdout(buf):
            check.main(["--root", str(self.root), "--ear"])
        self.assertEqual("All clear.", buf.getvalue().strip())

    def test_root_found_from_subfolder(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = check.main(["--root", str(self.acme), "--json"])
        self.assertEqual(0, code)
        self.assertEqual(str(self.root), json.loads(buf.getvalue())["root"])


class TestClaudeMd(CheckCase):
    def test_pass(self):
        self.assertClean("claude-md")

    def test_claude_md_in_zone(self):
        write(self.work / "CLAUDE.md", "# nope\n")
        self.assertFinds("claude-md", "error", path="Zones/Work/CLAUDE.md")

    def test_dot_claude_and_local(self):
        write(self.root / ".claude" / "CLAUDE.md", "x")
        write(self.acme / "CLAUDE.local.md", "x")
        paths = {f.path for f in self.findings("claude-md", "error")}
        self.assertEqual({".claude/CLAUDE.md", "Zones/Work/Acme Review/CLAUDE.local.md"}, paths)


class TestInstructions(CheckCase):
    def test_pass(self):
        self.assertClean("instructions")

    def test_root_agents_over_budget(self):
        write(self.root / "AGENTS.md", "# Workspace\n\n" + "word " * 900)
        self.assertFinds("instructions", "warning", "over its 800", path="AGENTS.md")

    def test_copied_sentence(self):
        sentence = "Every meeting page carries its zone and its parties, because those are what the walls read."
        write(self.root / "System" / "rules.md", "# Rules\n\n- %s\n" % sentence)
        write(self.work / "AGENTS.md", "# Work zone\n\n%s\n" % sentence)
        self.assertFinds("instructions", "warning", "the same text")

    def test_sibling_boilerplate_is_allowed(self):
        sentence = "Before anything else, read the root AGENTS.md, the rules and the context file in this workspace."
        write(self.work / "AGENTS.md", "# Work zone\n\n%s\n" % sentence)
        write(self.root / "Zones" / "Personal" / "AGENTS.md", "# Personal zone\n\n%s\n" % sentence)
        self.assertClean("instructions")

    def test_stale_skill_list(self):
        for name in ("threads", "meetings", "knowledge", "extra"):
            write(self.root / "System" / "skills" / name / "SKILL.md", "---\nname: %s\n---\n" % name)
        write(self.root / "AGENTS.md", "# Workspace\n\nSkills: `threads`, `meetings`, `knowledge`.\n")
        self.assertFinds("instructions", "warning", "not extra", path="AGENTS.md")


class TestPlaceholders(CheckCase):
    def test_pass_and_templates_ignored(self):
        write(self.root / "System" / "templates" / "_project" / "{{PROJECT}}.md", "zone: {{ZONE}}\n")
        write(self.work / "_project" / "{{PROJECT}}.md", "zone: {{ZONE}}\n")
        self.assertClean("placeholders")

    def test_placeholder_in_text(self):
        write(self.work / "AGENTS.md", "# {{ZONE}} zone\n")
        self.assertFinds("placeholders", "error", "{{ZONE}}", "Zones/Work/AGENTS.md")

    def test_placeholder_in_file_name(self):
        write(self.acme / "Sources" / "{{DATE}} notes.md", "fine\n")
        self.assertFinds("placeholders", "error", "{{DATE}}")

    def test_angle_brackets_are_not_placeholders(self):
        write(self.acme / "Sources" / "draft.md", "<your name here>\n")
        self.assertClean("placeholders")


class TestContext(CheckCase):
    def test_pass(self):
        self.assertClean("context")

    def test_wall_names_unknown_tag(self):
        ctx = self.root / "System" / "context.md"
        ctx.write_text(ctx.read_text().replace("| `acme` | `birch` |", "| `acme` | `cedar` |"))
        self.assertFinds("context", "error", "`cedar`")

    def test_missing_context(self):
        (self.root / "System" / "context.md").unlink()
        self.assertFinds("context", "error", "missing")


class TestZones(CheckCase):
    def test_pass(self):
        self.assertClean("zones")

    def test_not_a_repo(self):
        shutil.rmtree(self.work / ".git")
        self.assertFinds("zones", "error", "git repository", "Zones/Work")

    def test_missing_agents_and_todo(self):
        (self.work / "AGENTS.md").unlink()
        (self.work / "Todo.md").unlink()
        self.assertFinds("zones", "error", "AGENTS.md")
        self.assertFinds("zones", "error", "Todo.md")

    def test_underscore_folders_are_not_zones(self):
        write(self.root / "Zones" / "_zone" / "AGENTS.md", "template\n")
        self.assertClean("zones")


class TestNames(CheckCase):
    def test_pass(self):
        self.assertClean("names")

    def test_unspeakable_project(self):
        p = self.work / "Acme Q3"
        write(p / "Acme Q3.md", project_hub("Work", "Acme Q3", "acme"))
        self.assertFinds("names", "error", "digit", "Zones/Work/Acme Q3")

    def test_unspeakable_thread(self):
        t = self.acme / "Threads" / "pricing_v2"
        write(t / "pricing_v2.md", thread_note("Acme Review", "pricing_v2"))
        self.assertFinds("names", "error", "not speakable")

    def test_siblings_sound_alike(self):
        t = self.acme / "Threads" / "Prizing"
        write(t / "Prizing.md", thread_note("Acme Review", "Prizing"))
        self.assertFinds("names", "warning", "sound alike", "Zones/Work/Acme Review/Threads")


class TestProjects(CheckCase):
    def test_pass(self):
        self.assertClean("projects")

    def test_missing_hub(self):
        (self.acme / "Acme Review.md").unlink()
        self.assertFinds("projects", "error", "no hub note")

    def test_wrong_type_zone_and_unknown_party(self):
        hub = self.acme / "Acme Review.md"
        hub.write_text(hub.read_text().replace("type: project", "type: note")
                       .replace("zone: Work", "zone: Personal").replace("party: acme", "party: cedar"))
        self.assertFinds("projects", "error", "`type`")
        self.assertFinds("projects", "error", "`zone`")
        self.assertFinds("projects", "error", "cedar")

    def test_no_party_is_a_warning(self):
        write(self.acme / "Acme Review.md", project_hub("Work", "Acme Review", party=""))
        self.assertFinds("projects", "warning", "no `party`")
        self.assertFalse(self.findings("projects", "error"))

    def test_no_threads(self):
        shutil.rmtree(self.acme / "Threads")
        self.assertFinds("projects", "warning", "no threads")


class TestThreads(CheckCase):
    def test_pass(self):
        self.assertClean("threads")

    def test_missing_note(self):
        (self.acme / "Threads" / "Logistics").mkdir()
        self.assertFinds("threads", "error", "no thread note")

    def test_missing_resume_here(self):
        note = self.acme / "Threads" / "Pricing" / "Pricing.md"
        note.write_text(note.read_text().replace("### Resume here", "### Notes"))
        self.assertFinds("threads", "error", "Resume here")

    def test_missing_state_of_play_and_type(self):
        note = self.acme / "Threads" / "Pricing" / "Pricing.md"
        note.write_text(note.read_text().replace("## State of play", "## Progress").replace("type: thread", "type: note"))
        self.assertFinds("threads", "error", "State of play")
        self.assertFinds("threads", "error", "`type`")

    def test_resume_outside_state_of_play(self):
        note = self.acme / "Threads" / "Pricing" / "Pricing.md"
        text = note.read_text()
        head, tail = text.split("## State of play", 1)
        note.write_text(head + "### Resume here\n\nx\n\n## State of play\n\nnothing\n")
        self.assertFinds("threads", "error", "outside")

    def test_done_thread_needs_outcome_not_resume(self):
        note = self.acme / "Threads" / "Pricing" / "Pricing.md"
        note.write_text(thread_note("Acme Review", "Pricing", status="done"))
        self.assertClean("threads")
        note.write_text(note.read_text().replace("### Outcome", "### Summary"))
        self.assertFinds("threads", "error", "Outcome")

    def test_party_differs_from_project(self):
        note = self.acme / "Threads" / "Pricing" / "Pricing.md"
        note.write_text(note.read_text().replace("party: acme", "party: birch"))
        self.assertFinds("threads", "warning", "differs")


class TestResume(CheckCase):
    def resume(self, row):
        note = self.acme / "Threads" / "Pricing" / "Pricing.md"
        note.write_text(note.read_text() + "\n| | |\n|---|---|\n| Live artifact | %s |\n" % row)

    def test_pass(self):
        self.resume("`Deliverables/260301 - Pricing memo.md` and [[Pricing]]")
        self.assertClean("resume")

    def test_moved_file(self):
        self.resume("`Deliverables/260301 - Pricing memo-v2.md`")
        self.assertFinds("resume", "warning", "is not there")

    def test_dangling_link(self):
        self.resume("[[Pricing deck]]")
        self.assertFinds("resume", "warning", "leads nowhere")

    def test_not_paths(self):
        self.resume("`<path, and what it is>`, `python3 tools/build.py`, `/tmp/scratch/x.md`, `https://example.com/a.md`")
        self.assertClean("resume")

    def test_done_thread_is_not_checked(self):
        note = self.acme / "Threads" / "Pricing" / "Pricing.md"
        note.write_text(thread_note("Acme Review", "Pricing", status="done").replace(
            "### Outcome", "### Resume here\n\n`Deliverables/gone.md`\n\n### Outcome"))
        self.assertClean("resume")

    def test_only_the_resume_block(self):
        note = self.acme / "Threads" / "Pricing" / "Pricing.md"
        note.write_text(note.read_text() + "\n---\n\n**2 March 2026.** Drafted `Deliverables/old draft.md`, since replaced.\n")
        self.assertClean("resume")


class TestGenerated(CheckCase):
    def page(self):
        write(self.root / "System" / "generated" / "status.html", "<p>Workspace status</p>\n")

    def repo(self, ignore):
        git_init(self.root)
        write(self.root / ".gitignore", "Zones/\nWikis/\n" + ignore)

    def test_no_repository_no_findings(self):
        self.page()
        self.assertClean("generated")

    @unittest.skipUnless(HAVE_GIT, "git is not installed")
    def test_ignored_folder_is_clean(self):
        self.repo("System/generated/\n")
        self.page()
        self.assertClean("generated")

    @unittest.skipUnless(HAVE_GIT, "git is not installed")
    def test_folder_not_ignored_warns(self):
        self.repo("")
        self.page()
        self.assertFinds("generated", "warning", "does not ignore")

    @unittest.skipUnless(HAVE_GIT, "git is not installed")
    def test_committed_page_is_an_error(self):
        self.repo("")
        self.page()
        commit_all(self.root)
        self.assertFinds("generated", "error", "committed")

    def test_placeholders_in_generated_output_are_not_an_unfinished_install(self):
        write(self.root / "System" / "generated" / "brief.md", "Fill {{ZONE}} later\n")
        self.assertClean("placeholders")


class TestDeliverables(CheckCase):
    def test_pass(self):
        self.assertClean("deliverables")

    def test_undated(self):
        write(self.acme / "Deliverables" / "Pricing memo final.md", "x")
        write(self.acme / "Deliverables" / "261345 - Bad date.md", "x")
        self.assertEqual(2, len(self.assertFinds("deliverables", "warning", "creation date")))


class TestMeetings(CheckCase):
    def test_pass(self):
        self.assertClean("meetings")

    def test_unfinished_is_a_warning(self):
        write(self.meetings / "wiki" / "sources" / "260315-call.md", meeting_page(zone=None, parties="[]"))
        hits = self.assertFinds("meetings", "warning", "unfinished")
        self.assertIn("zone or parties", hits[0].message)
        self.assertFalse(self.findings("meetings", "error"))

    def test_unknown_party_is_an_error(self):
        write(self.meetings / "wiki" / "sources" / "260315-call.md", meeting_page(parties="[acme, cedar]"))
        self.assertFinds("meetings", "error", "cedar")

    def test_block_list_parties(self):
        page = meeting_page(parties=None).replace("---\n\n#", "parties:\n  - acme\n---\n\n#", 1)
        write(self.meetings / "wiki" / "sources" / "260315-call.md", page)
        self.assertClean("meetings")


class TestWalls(CheckCase):
    def test_pass_same_party(self):
        self.assertClean("walls")

    def test_wikilink_across_wall(self):
        write(self.acme / "Threads" / "Pricing" / "Benchmarks.md",
              "Their pricing: see [[260312-birch-kickoff|the Birch call]].\n")
        hit = self.assertFinds("walls", "error", "wall stands between acme and birch")[0]
        self.assertEqual("Zones/Work/Acme Review/Threads/Pricing/Benchmarks.md", hit.path)
        self.assertIn("[[260312-birch-kickoff|the Birch call]]", hit.message)

    def test_obsidian_uri_across_wall(self):
        uri = "obsidian://open?vault=Wikis&file=Meetings%2Fwiki%2Fsources%2F260312-birch-kickoff"
        write(self.acme / "Deliverables" / "260302 - Board note.md", "Source: [call](%s)\n" % uri)
        self.assertFinds("walls", "error", "birch", "Zones/Work/Acme Review/Deliverables/260302 - Board note.md")

    def test_relative_markdown_link_across_wall(self):
        write(self.acme / "Acme Review.md", project_hub("Work", "Acme Review", "acme")
              + "\n[call](../../../Wikis/Meetings/wiki/sources/260312-birch-kickoff.md)\n")
        self.assertFinds("walls", "error", "birch", "Zones/Work/Acme Review/Acme Review.md")

    def test_unfinished_meeting_used(self):
        write(self.meetings / "wiki" / "sources" / "260315-call.md", meeting_page(parties=None))
        write(self.acme / "Threads" / "Pricing" / "Notes.md", "[[260315-call]]\n")
        self.assertFinds("walls", "error", "unfinished")

    def test_project_without_party_uses_meeting(self):
        write(self.acme / "Acme Review.md", project_hub("Work", "Acme Review", party=""))
        note = self.acme / "Threads" / "Pricing" / "Pricing.md"
        note.write_text(note.read_text().replace("party: acme\n", ""))
        self.assertFinds("walls", "error", "no party")

    def test_cross_zone_is_a_warning(self):
        home = self.root / "Zones" / "Personal" / "Home Move"
        write(home / "Home Move.md", project_hub("Personal", "Home Move", "acme"))
        write(home / "Threads" / "Boxes" / "Boxes.md", thread_note("Home Move", "Boxes", "acme", "[[260310-acme-kickoff]]"))
        self.assertFinds("walls", "warning", "cross-zone")
        self.assertFalse(self.findings("walls", "error"))

    def test_ear_report_names_the_wall(self):
        write(self.acme / "Threads" / "Pricing" / "Benchmarks.md", "[[260312-birch-kickoff]]\n")
        write(self.meetings / "wiki" / "sources" / "260315-call.md", meeting_page(parties="[]"))
        text = check.report_ear(check.run_checks(self.root))
        self.assertEqual(
            "One problem and one warning. A note in Acme Review's Pricing thread uses a meeting with Birch & Co. "
            "One meeting page has no parties.", text)
        self.assertLessEqual(text.count(". "), 2)

    def test_exit_code_on_error(self):
        write(self.acme / "Threads" / "Pricing" / "Benchmarks.md", "[[260312-birch-kickoff]]\n")
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = check.main(["--root", str(self.root)])
        self.assertEqual(1, code)
        self.assertIn("1 error, 0 warnings.", buf.getvalue())


class TestKnowledge(CheckCase):
    def test_pass(self):
        self.assertClean("knowledge")

    def test_link_into_meetings(self):
        write(self.root / "Wikis" / "Knowledge" / "wiki" / "concepts" / "pricing.md",
              "As discussed in [[Meetings/wiki/sources/260310-acme-kickoff]].\n")
        self.assertFinds("knowledge", "error", "Meetings page")

    def test_bare_link_resolving_into_meetings(self):
        write(self.root / "Wikis" / "Knowledge" / "wiki" / "concepts" / "people.md", "[[dana-whitlock]]\n")
        self.assertFinds("knowledge", "error")


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class TestRaw(CheckCase):
    def setUp(self):
        super().setUp()
        git_init(self.meetings)
        commit_all(self.meetings, "first ingest")
        self.record = self.meetings / "raw" / "260310-acme-kickoff.txt"

    def test_pass(self):
        write(self.meetings / "raw" / "inbox" / "260320-new.txt", "fresh\n")
        commit_all(self.meetings, "drop in inbox")
        (self.meetings / "raw" / "inbox" / "260320-new.txt").write_text("edited in the inbox\n")
        commit_all(self.meetings, "inbox edit")
        self.assertClean("raw")

    def test_committed_edit(self):
        self.record.write_text("Dana: we start Tuesday.\n")
        commit_all(self.meetings, "tidy")
        self.assertFinds("raw", "error", "edited", "Wikis/Meetings/raw/260310-acme-kickoff.txt")

    def test_uncommitted_edit(self):
        self.record.write_text("Dana: we start Tuesday.\n")
        self.assertFinds("raw", "error", "edited")

    def test_deleted(self):
        self.record.unlink()
        commit_all(self.meetings, "remove")
        self.assertFinds("raw", "error", "deleted")

    def test_not_a_repo_is_skipped(self):
        shutil.rmtree(self.meetings / ".git")
        self.record.write_text("changed\n")
        self.assertClean("raw")


class TestTextReport(CheckCase):
    def test_grouped_with_count(self):
        write(self.work / "CLAUDE.md", "x")
        write(self.acme / "Deliverables" / "memo.md", "x")
        text = check.report_text(check.run_checks(self.root), self.root)
        self.assertIn("Instruction files\n  error   Zones/Work/CLAUDE.md:", text)
        self.assertIn("Deliverables\n  warning Zones/Work/Acme Review/Deliverables/memo.md:", text)
        self.assertTrue(text.rstrip().endswith("1 error, 1 warning."))

    def test_ear_many_groups_stays_three_sentences(self):
        write(self.work / "CLAUDE.md", "x")
        write(self.acme / "Deliverables" / "memo.md", "x")
        write(self.acme / "Threads" / "Pricing" / "Benchmarks.md", "[[260312-birch-kickoff]]\n")
        write(self.meetings / "wiki" / "sources" / "260315-call.md", meeting_page(parties="[]"))
        text = check.report_ear(check.run_checks(self.root))
        self.assertEqual(3, text.count("."), text)
        self.assertTrue(text.startswith("Two problems and two warnings."), text)


if __name__ == "__main__":
    unittest.main()
