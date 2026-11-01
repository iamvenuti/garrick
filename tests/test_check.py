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
    git,
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

    def test_skills_named_in_separate_sentences_are_pointers(self):
        for name in ("intake", "threads", "setup-sync", "extra"):
            write(self.root / "System" / "skills" / name / "SKILL.md", "---\nname: %s\n---\n" % name)
        write(self.root / "System" / "rules.md", "# Rules\n\nThe `intake` skill is the procedure.\n")
        write(self.root / "System" / "rules.local.md",
              "# Your rules\n\n## Threads\n\n- Run the `threads` skill to do all of this.\n\n"
              "## Files\n\n- After any change, run the `setup-sync` skill.\n")
        hits = [f for f in self.findings("instructions") if "lists skills" in f.message]
        self.assertEqual([], hits)

    def test_one_bullet_list_of_three_skills_is_a_list(self):
        for name in ("intake", "threads", "setup-sync", "extra"):
            write(self.root / "System" / "skills" / name / "SKILL.md", "---\nname: %s\n---\n" % name)
        write(self.root / "System" / "rules.local.md",
              "# Your rules\n\n- `intake` for mail\n- `threads` for threads\n- `setup-sync` after a change\n")
        self.assertFinds("instructions", "warning", "not extra")


class TestLocalInstructions(CheckCase):
    """The local file beside each of Garrick's instruction files: the
    workspace's own rules and routing, checked like the rest."""

    def point(self):
        write(self.root / "AGENTS.md", "# Workspace\n\nRead `AGENTS.local.md` and `System/rules.local.md` next.\n")
        write(self.root / "System" / "rules.md", "# Rules\n\nRead `System/rules.local.md` next.\n")

    def test_a_local_file_needs_a_pointer(self):
        write(self.root / "System" / "rules.local.md", "# Your rules\n\n- Mine.\n")
        write(self.root / "AGENTS.local.md", "# Mine\n")
        hits = self.assertFinds("instructions", "warning", "does not point to it")
        self.assertEqual({"System/rules.local.md", "AGENTS.local.md"}, {h.path for h in hits})
        self.point()
        self.assertClean("instructions")

    def test_local_files_have_the_budget_of_the_file_beside_them(self):
        self.point()
        write(self.root / "AGENTS.local.md", "# Mine\n\n" + "word " * 900)
        self.assertFinds("instructions", "warning", "over its 800", path="AGENTS.local.md")
        write(self.work / "AGENTS.md", "# Work\n\nRead `AGENTS.local.md` here.\n")
        write(self.work / "AGENTS.local.md", "# Work, mine\n\n" + "word " * 1100)
        self.assertFinds("instructions", "warning", "over its 1000", path="Zones/Work/AGENTS.local.md")

    def test_a_sentence_copied_from_garricks_rules(self):
        self.point()
        sentence = "Every meeting page carries its zone and its parties, because those are what the walls read."
        write(self.root / "System" / "rules.md", "# Rules\n\nRead `System/rules.local.md` next.\n\n- %s\n" % sentence)
        write(self.root / "System" / "rules.local.md", "# Your rules\n\n- %s\n" % sentence)
        self.assertFinds("instructions", "warning", "the same text", path="System/rules.local.md and System/rules.md")

    def test_the_line_the_split_opens_each_local_file_with_is_not_a_copy(self):
        self.point()
        write(self.meetings / "AGENTS.md", "# Meetings\n\nRead `AGENTS.local.md` beside it next.\n")
        write(self.root / "AGENTS.local.md", "# Workspace, this workspace's own\n\n%s\n" % check.LOCAL_HEADER)
        write(self.meetings / "AGENTS.local.md", "# Meetings, this workspace's own\n\n%s\n" % check.LOCAL_HEADER)
        self.assertEqual([], [f.message for f in self.findings("instructions") if "the same text" in f.message])
        sentence = "Every meeting page carries its zone and its parties, because those are what the walls read."
        write(self.meetings / "AGENTS.local.md", "# Meetings, this workspace's own\n\n%s\n\n%s\n"
              % (check.LOCAL_HEADER, sentence))
        write(self.root / "AGENTS.local.md", "# Workspace, this workspace's own\n\n%s\n\n%s\n"
              % (check.LOCAL_HEADER, sentence))
        [hit] = self.assertFinds("instructions", "warning", "the same text")      # a sentence of the user's still is
        self.assertIn(sentence[:40].lower(), hit.message)

    def test_skills_named_across_a_file_and_its_local_file(self):
        self.point()
        for name in ("threads", "meetings", "knowledge", "extra"):
            write(self.root / "System" / "skills" / name / "SKILL.md", "---\nname: %s\n---\n" % name)
        write(self.root / "AGENTS.md", "# Workspace\n\nRead `AGENTS.local.md` next.\n")
        write(self.root / "AGENTS.local.md", "# Mine\n\nSkills: `threads`, `meetings` and `knowledge`.\n")
        self.assertFinds("instructions", "warning", "not extra", path="AGENTS.local.md")
        write(self.root / "AGENTS.md", "# Workspace\n\nRead `AGENTS.local.md` next. The `extra` skill does the rest.\n")
        self.assertClean("instructions")

    def test_a_zone_project_list_in_the_local_file(self):
        write(self.work / "AGENTS.md", "# Work\n\nRead `AGENTS.local.md` here.\n")
        write(self.work / "AGENTS.local.md", "# Work, mine\n\n- `Acme Review/Acme Review.md`\n- `Acme Review/Gone.md`\n")
        self.assertFinds("instructions", "warning", "not Birch Entry/Birch Entry.md", path="Zones/Work/AGENTS.local.md")
        self.assertFinds("instructions", "warning", "lists Acme Review/Gone.md", path="Zones/Work/AGENTS.local.md")

    def test_garricks_file_changed_here(self):
        from garrick_lib import fingerprint
        self.point()
        rules = self.root / "System" / "rules.md"
        write(self.root / "System" / "garrick-version.json",
              json.dumps({"commit": "abc1234", "files": {"System/rules.md": fingerprint(rules)}}))
        self.assertClean("instructions")
        rules.write_text(rules.read_text() + "- A rule of my own.\n")
        self.assertFinds("instructions", "warning", "differs from what Garrick shipped", path="System/rules.md")

    def test_passages_left_to_settle(self):
        self.point()
        write(self.root / "System" / "rules.local.md",
              "# Your rules\n\n## From your earlier rules.md, to review\n\nIntro.\n\n### 1. Changed, at the top\n\n"
              "Mine.\n\n### 2. Removed, under Files\n\nGone.\n")
        self.assertFinds("instructions", "warning", "still holds 2 passages", path="System/rules.local.md")


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

    def test_a_placeholder_quoted_as_code_is_not_unfilled(self):
        write(self.acme / "Notes" / "templates.md", "The installer fills `{{ZONE}}`.\n\n```\nzone: {{ZONE}}\n```\n")
        self.assertClean("placeholders")

    def test_a_nested_repository_is_not_the_zones(self):
        code = self.acme / "Code"
        write(code / "README.md", "# {{PROJECT}}\n")
        (code / ".git").mkdir()
        self.assertClean("placeholders")
        (code / ".git").rmdir()
        self.assertFinds("placeholders", "error", "{{PROJECT}}")


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

    def _people_as(self, text):
        import re as _re
        ctx = self.root / "System" / "context.md"
        body = ctx.read_text()
        body = _re.sub(r"(?s)## People\n.*?(?=\n## |\Z)", "## People\n\n" + text + "\n", body)
        ctx.write_text(body)

    def test_people_written_as_prose_is_an_error(self):
        self._people_as("Dana Whitlock runs procurement at Acme, and Theo Marsh is Birch's managing partner.")
        [hit] = [f for f in self.findings("context", "error") if "People" in f.message]
        self.assertIn("Make it a table: Name, Party, Role", hit.message)
        self.assertIn("sees no one's name", hit.message)

    def test_a_list_is_not_a_table_either(self):
        self._people_as("- Dana Whitlock, `acme`\n- Theo Marsh, `birch`")
        self.assertFinds("context", "error", "People is written as prose or a list")

    def test_a_table_without_a_needed_column_is_a_warning(self):
        self._people_as("| Who | Role |\n|---|---|\n| Dana Whitlock | Procurement |")
        self.assertFinds("context", "warning", "the People table has no Name or Party column")

    def test_an_empty_section_says_nothing(self):
        self._people_as("")
        self.assertEqual([], [f for f in self.findings("context") if "People" in f.message])


class TestLearnedEntries(CheckCase):
    """Every learned entry says where it came from (#153): a memory entry in the
    folder the check settings name, and a row with a Learned cell in context.md."""

    def remember(self, name, text):
        memory = Path(self._tmp.name).resolve() / "memory"
        write(memory / name, text)
        write(self.root / "System" / "garrick-checks.json", json.dumps({"memory": str(memory)}))
        return memory

    def test_no_setting_reads_no_memory(self):
        write(Path(self._tmp.name).resolve() / "memory" / "x.md", "No origin at all.\n")
        self.assertClean("memory")

    def test_an_entry_with_its_origin_passes_and_the_index_is_not_an_entry(self):
        self.remember("pricing.md", "---\nsource: file:Zones/Work/Acme Review/Threads/Pricing/Pricing.md\n"
                                    "created: 2026-10-16\n---\nResume from the Pricing note.\n")
        self.remember("MEMORY.md", "- [Pricing](pricing.md)\n")
        self.assertClean("memory")
        self.assertClean("settings")

    def test_an_entry_with_no_origin_is_reported(self):
        self.remember("domain.md", "---\nname: Acme's domain\n---\nAcme writes from acmecorp.example.\n")
        hit = self.assertFinds("memory", check.WARNING, "a learned entry with no origin")[0]
        self.assertIn("no `source:`", hit.message)
        self.assertIn("no `created:`", hit.message)
        self.assertTrue(hit.path.endswith("domain.md"), hit.path)

    def test_a_source_or_a_date_that_does_not_read_is_reported(self):
        self.remember("a.md", "---\nsource: a mail\ncreated: 2026-10-16\n---\nx\n")
        self.remember("b.md", "---\nsource: user\ncreated: 16 October\n---\nx\n")
        self.assertFinds("memory", check.WARNING, "is not `user`, `file:<path>` or `inbound:<raw path>`")
        self.assertFinds("memory", check.WARNING, "not written YYYY-MM-DD")

    def test_an_entry_whose_only_source_is_inbound_is_reported(self):
        self.remember("reports.md", "---\nsource: inbound:Wikis/Meetings/raw/261014-forecast.eml\n"
                                    "created: 2026-10-16\n---\nReports go elsewhere.\n")
        self.assertFinds("memory", check.WARNING, "only source is inbound")
        self.remember("reports.md", "---\nsource: [inbound:Wikis/Meetings/raw/261014-forecast.eml, user]\n"
                                    "created: 2026-10-16\n---\nConfirmed.\n")
        self.assertClean("memory")

    NESTED = ("---\nname: acme-review-pricing-thread\n"
              "description: \"Where the resume point for the Acme Review, Pricing thread lives\"\n"
              "metadata:\n  node_type: memory\n%s  type: project\n---\nResume from the Pricing note.\n")

    def test_an_origin_kept_under_metadata_is_read(self):
        self.remember("pricing.md", self.NESTED % (
            "  source: file:Zones/Work/Acme Review/Threads/Pricing/Pricing.md\n  created: 2026-10-17\n"))
        self.assertClean("memory")

    def test_a_nested_origin_from_inbound_only_is_still_reported(self):
        self.remember("reports.md", self.NESTED % (
            "  source: inbound:Wikis/Meetings/raw/261014-forecast.eml\n  created: 2026-10-17\n"))
        self.assertFinds("memory", check.WARNING, "only source is inbound")
        self.remember("reports.md", self.NESTED % (
            "  source:\n    - inbound:Wikis/Meetings/raw/261014-forecast.eml\n    - user\n  created: 2026-10-17\n"))
        self.assertClean("memory")

    def test_a_metadata_block_with_no_origin_is_still_reported(self):
        self.remember("domain.md", self.NESTED % "")
        hit = self.assertFinds("memory", check.WARNING, "a learned entry with no origin")[0]
        self.assertIn("no `source:`", hit.message)
        self.assertIn("no `created:`", hit.message)
        # The two keys under some other mapping are not an origin.
        self.remember("domain.md", "---\nname: x\nother:\n  source: user\n  created: 2026-10-17\n---\nx\n")
        self.assertFinds("memory", check.WARNING, "a learned entry with no origin")

    def test_a_memory_folder_that_is_not_there(self):
        write(self.root / "System" / "garrick-checks.json", json.dumps({"memory": "~/no-such-memory-folder-153"}))
        self.assertFinds("settings", check.WARNING, "which is not a folder")
        write(self.root / "System" / "garrick-checks.json", json.dumps({"memory": 3}))
        self.assertFinds("settings", check.ERROR, "a folder, or a list of folders")

    def context_with(self, cell):
        ctx = self.root / "System" / "context.md"
        text = ctx.read_text(encoding="utf-8")
        text = text.replace("| Heard | Means |\n|---|---|\n", "| Heard | Means | Learned |\n|---|---|---|\n")
        ctx.write_text(text.rstrip("\n") + "\n| acme corps | Acme Corp | %s |\n" % cell, encoding="utf-8")

    def test_a_learned_row_passes_and_rows_typed_by_hand_say_nothing(self):
        self.context_with("2026-10-16, user")
        self.assertClean("memory")
        self.assertClean("context")

    def test_a_learned_cell_that_does_not_read(self):
        self.context_with("last week")
        hit = self.assertFinds("memory", check.WARNING, "does not read as `YYYY-MM-DD, source`")[0]
        self.assertEqual("System/context.md", hit.path)
        self.assertIn("Aliases row acme corps", hit.message)

    def test_a_row_learned_only_from_a_mail(self):
        self.context_with("2026-10-16, inbound:Wikis/Meetings/raw/261014-forecast.eml")
        self.assertFinds("memory", check.WARNING, "only source is inbound")


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

    def said(self, note: Path, spoken: str) -> None:
        """Give a note a `spoken` form, under its title."""
        note.write_text(note.read_text().replace("type:", "spoken: %s\ntype:" % spoken, 1))

    def test_a_business_name_with_a_spoken_form_is_clean(self):
        t = self.acme / "Threads" / "Q4 Planning"
        write(t / "Q4 Planning.md", thread_note("Acme Review", "Q4 Planning"))
        self.said(t / "Q4 Planning.md", "fourth quarter planning")
        self.assertClean("names")

    def test_a_business_name_without_one_is_asked_for(self):
        p = self.work / "Acme Q3"
        write(p / "Acme Q3.md", project_hub("Work", "Acme Q3", "acme"))
        self.assertFinds("names", "warning", "`spoken:`", "Zones/Work/Acme Q3/Acme Q3.md")
        self.assertEqual([], self.findings("names", "error"))

    def test_a_spoken_form_that_does_not_say_how_it_is_said_either(self):
        t = self.acme / "Threads" / "ISO 27001"
        write(t / "ISO 27001.md", thread_note("Acme Review", "ISO 27001"))
        self.said(t / "ISO 27001.md", "ISO 27001 readiness")
        self.assertFinds("names", "warning", "does not say how it is said either",
                         "Zones/Work/Acme Review/Threads/ISO 27001/ISO 27001.md")

    def test_a_name_that_will_not_work(self):
        t = self.acme / "Threads" / "pricing_v2"
        write(t / "pricing_v2.md", thread_note("Acme Review", "pricing_v2"))
        self.assertFinds("names", "error", "will not work: it contains an underscore")

    def test_a_zone_name_has_to_say_how_it_is_said(self):
        z = self.root / "Zones" / "Clients 2"
        write(z / "AGENTS.md", "# Clients 2 zone\n")
        self.assertFinds("names", "error", "a zone has no note to carry a `spoken` form", "Zones/Clients 2")

    def test_siblings_sound_alike(self):
        t = self.acme / "Threads" / "Prizing"
        write(t / "Prizing.md", thread_note("Acme Review", "Prizing"))
        self.assertFinds("names", "warning", "sound alike", "Zones/Work/Acme Review/Threads")

    def test_siblings_whose_spoken_forms_sound_alike(self):
        t = self.acme / "Threads" / "Q4 Planning"
        write(t / "Q4 Planning.md", thread_note("Acme Review", "Q4 Planning"))
        self.said(t / "Q4 Planning.md", "pricing")
        self.assertFinds("names", "warning", 'said "Pricing" and "pricing"', "Zones/Work/Acme Review/Threads")


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

    def test_a_project_takes_a_threads_three_statuses(self):
        hub = self.acme / "Acme Review.md"
        text = hub.read_text()
        for status in ("parked", "done"):
            hub.write_text(text.replace("status: active", "status: " + status))
            self.assertClean("projects")
        hub.write_text(text.replace("status: active", "status: paused"))
        self.assertFinds("projects", "error", "should be active, parked or done")


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

    def test_parked_thread_is_not_checked(self):
        note = self.acme / "Threads" / "Pricing" / "Pricing.md"
        note.write_text(thread_note("Acme Review", "Pricing", status="parked") + "\n`Deliverables/gone.md`\n")
        self.assertClean("resume")
        self.assertClean("threads")

    def test_a_parked_projects_threads_are_not_checked(self):
        # Parked as a whole from the status page, the hub says parked and its
        # threads, whatever their own status, are parked with it.
        hub = self.acme / "Acme Review.md"
        self.resume("`Deliverables/gone.md`")
        self.assertFinds("resume", "warning", "is not there")
        hub.write_text(hub.read_text().replace("status: active", "status: parked"))
        self.assertClean("resume")
        self.assertClean("projects")

    def test_a_file_in_a_nested_repository_is_found(self):
        # Code checked out inside the project is somebody else's files to
        # every check that reads notes, but a path into it still exists (#168).
        code = self.acme / "Repo"
        write(code / "docs" / "extras" / "status-page.md", "# Status page\n")
        (code / ".git").mkdir()
        self.resume("`extras/status-page.md`")
        self.assertClean("resume")

    def test_a_nested_repository_still_skips_installed_packages(self):
        code = self.acme / "Repo"
        write(code / "node_modules" / "left-pad" / "index.js", "module.exports = 1;\n")
        (code / ".git").mkdir()
        self.resume("`left-pad/index.js`")
        self.assertFinds("resume", "warning", "`left-pad/index.js`, which is not there")

    def test_a_generated_file_is_not_checked(self):
        # interrupted.json exists only while a thread is held.
        self.resume("`System/generated/interrupted.json` and `%s/System/generated/status.html`" % self.root)
        self.assertClean("resume")

    def test_a_path_that_exists_nowhere_is_still_reported(self):
        (self.acme / "Repo" / ".git").mkdir(parents=True)
        self.resume("`extras/gone.md`")
        self.assertFinds("resume", "warning", "`extras/gone.md`, which is not there")

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


class TestKeptChoices(CheckCase):
    """The choices a user keeps -- each zone's colour and icon, how a thread
    opens -- are committed with the workspace, so a restore brings them back (#81)."""

    def kept(self):
        write(self.root / "System" / "garrick-settings.json",
              json.dumps({"zones": {"Work": {"color": "Teal"}}}) + "\n")

    def test_no_file_and_no_repository_are_clean(self):
        self.assertClean("preferences")
        self.kept()
        self.assertClean("preferences")

    @unittest.skipUnless(HAVE_GIT, "git is not installed")
    def test_untracked_warns_and_committed_is_clean(self):
        git_init(self.root)
        write(self.root / ".gitignore", "Zones/\nWikis/\nSystem/generated/\n")
        self.kept()
        self.assertFinds("preferences", "warning", "not in the workspace's history")
        commit_all(self.root)
        self.assertClean("preferences")


class TestReviewRecord(CheckCase):
    """#258: the review record sits in the root repository, which no wall hook
    checks, so it holds keys and fixed words only."""

    HEAD = ("---\ntype: nurture-review\nstatus: open\nstarted: 2026-03-14\nlast_completed:\nlimit: 15 minutes\n---\n"
            "# Context review\n\n| Id | Source | Decision | Reason | Date |\n|---|---|---|---|---|\n")

    def record(self, *rows):
        write(self.root / "System" / "nurture-review.md", self.HEAD + "".join("| %s |\n" % r for r in rows))

    def test_no_record_and_a_record_in_its_form_are_clean(self):
        self.assertClean("review")
        self.record("3f2a9c1d0b4e | check.py | answered |  | 2026-03-14",
                    "9b07e4a2c6d1 | wiki_lint.py, audit | fixed 1a2b3c4 |  | 2026-03-14",
                    "c4d8e0f1a2b3 | check.py | deferred to 2026-03-21 | another session holds the file | 2026-03-14",
                    "77aa01bc9e3f | check.py | skipped | not now | 2026-03-14",
                    "drift.py | drift.py | source failed | source did not run | 2026-03-14")
        self.assertClean("review")

    def test_a_path_a_value_or_words_of_its_own_warn_without_being_repeated(self):
        self.record("check:meetings:Wikis/Meetings/wiki/sources/260402-cedar-call.md | check.py | answered: Work, acme "
                    "| the renewal floor is private | 2026-03-14",
                    "3f2a9c1d0b4e | the Cedar folder | skipped |  | 14 March")
        found = self.findings("review")
        said = " ".join(f.message + f.ear for f in found)
        for problem in ("row 1 has an Id", "row 1 has a Decision", "row 1 has a Reason", "row 2 has a Source",
                        "row 2 has a Date"):
            self.assertIn(problem, said)
        self.assertEqual(5, len(found), said)
        for word in ("cedar", "Cedar", "renewal", "acme", "March"):
            self.assertNotIn(word, said)

    def test_the_counts_in_the_frontmatter_are_whole_numbers(self):
        self.HEAD = self.HEAD.replace("limit:", "fixed: 6\nanswered: 0\ndeferred:\nlimit:")
        self.record("3f2a9c1d0b4e | check.py | answered |  | 2026-03-14")
        self.assertClean("review")
        self.HEAD = self.HEAD.replace("answered: 0", "answered: the Cedar floor")
        self.record("3f2a9c1d0b4e | check.py | answered |  | 2026-03-14")
        found = self.assertFinds("review", "warning", "`answered` in the frontmatter is not a whole number")
        self.assertNotIn("Cedar", " ".join(f.message + f.ear for f in found))

    def test_a_tool_name_is_an_id_only_for_a_source_that_did_not_run(self):
        self.record("drift.py | drift.py | skipped |  | 2026-03-14")
        self.assertFinds("review", "warning", "row 1 has an Id")

    def test_the_skill_names_the_same_reasons_and_sources(self):
        skill = (Path(check.__file__).resolve().parent.parent / "skills" / "nurture" / "SKILL.md").read_text()
        review = " ".join(skill.split("### The review record", 1)[1].split("### The review\n", 1)[0].split())
        for reason in check.REVIEW_REASONS:
            self.assertIn('"%s"' % reason, review)
        for source in check.REVIEW_SOURCES:
            self.assertIn("`%s`" % source, review)


class TestDeliverables(CheckCase):
    def test_pass(self):
        self.assertClean("deliverables")

    def test_undated(self):
        write(self.acme / "Deliverables" / "Pricing memo final.md", "x")
        write(self.acme / "Deliverables" / "261345 - Bad date.md", "x")
        self.assertEqual(2, len(self.assertFinds("deliverables", "warning", "creation date")))


class TestParentLinks(CheckCase):
    """The ledger of what a project published is a table for drift.py, and
    its folder already says whose it is: it is not asked for `parent:` (#169)."""

    LEDGER = "| Date | File | Destination | Copy |\n|---|---|---|---|\n"

    def setUp(self):
        super().setUp()
        write(self.root / "System" / "garrick-checks.json", json.dumps({"parent-links": ["Work"]}))

    def missing(self):
        return sorted(f.path for f in self.findings("links") if "no `parent:`" in f.message)

    def test_a_ledger_needs_no_parent(self):
        write(self.acme / "Deliverables" / "published.md", self.LEDGER)
        write(self.acme / "Threads" / "Pricing" / "Deliverables" / "published.md", self.LEDGER)
        self.assertEqual([], [p for p in self.missing() if p.endswith("published.md")])

    def test_a_note_beside_the_ledger_is_still_asked(self):
        write(self.acme / "Deliverables" / "published.md", self.LEDGER)
        write(self.acme / "Deliverables" / "260301 - Pricing memo.md", "# Pricing memo\n")
        write(self.acme / "Threads" / "Pricing" / "published.md", self.LEDGER)
        missing = self.missing()
        self.assertIn("Zones/Work/Acme Review/Deliverables/260301 - Pricing memo.md", missing)
        self.assertIn("Zones/Work/Acme Review/Threads/Pricing/published.md", missing)
        self.assertNotIn("Zones/Work/Acme Review/Deliverables/published.md", missing)


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


class TestFadedPages(CheckCase):
    """A page that faded lives under its wiki's dormant/ or archive/, its raw
    file beside it. The walls read it as they read a working page; nothing
    else reports on it, and a link into it still lands."""

    def fade(self, grade, wiki="Meetings", page="wiki/sources/260312-birch-kickoff.md"):
        wiki = self.root / "Wikis" / wiki
        moved = wiki / grade / page
        moved.parent.mkdir(parents=True, exist_ok=True)
        (wiki / page).rename(moved)
        return moved

    def test_a_link_across_a_wall_is_refused_whatever_the_grade(self):
        for grade in ("dormant", "archive"):
            with self.subTest(grade=grade):
                moved = self.fade(grade)
                for link in ("[[260312-birch-kickoff]]", "[[%s/wiki/sources/260312-birch-kickoff]]" % grade,
                             "[[Wikis/Meetings/%s/wiki/sources/260312-birch-kickoff|the call]]" % grade):
                    write(self.acme / "Threads" / "Pricing" / "Benchmarks.md", "Their pricing: %s.\n" % link)
                    self.assertFinds("walls", "error", "links %s, a meeting with birch" % link,
                                     "Zones/Work/Acme Review/Threads/Pricing/Benchmarks.md")
                moved.rename(self.meetings / "wiki" / "sources" / moved.name)

    def test_wording_from_a_faded_record_across_a_wall_is_refused(self):
        quote = "Theo confirmed the Bergen warehouse lease runs out at the end of the spring quarter"
        page = self.fade("dormant")
        page.write_text(meeting_page("Work", "[birch]", "Birch kick-off").replace(
            "type: meeting", 'type: meeting\nraw: "[[dormant/raw/260312-birch-kickoff]]"'))
        write(self.meetings / "dormant" / "raw" / "260312-birch-kickoff.txt", "%s.\n" % quote)
        write(self.acme / "Threads" / "Pricing" / "Notes.md", "%s.\n" % quote)
        self.assertFinds("walls", "error", "repeats wording from meeting 260312-birch-kickoff")

    def test_nothing_else_reports_on_a_faded_page(self):
        write(self.meetings / "dormant" / "wiki" / "sources" / "old call.md", meeting_page(zone=None, parties="[cedar]"))
        write(self.meetings / "archive" / "wiki" / "sources" / "260101-old.md",
              meeting_page(parties="[acme, birch]").replace("date: 2026-03-10", "date: 2026-03-10\ncreated: 1 March"))
        knowledge = self.root / "Wikis" / "Knowledge"
        write(knowledge / "archive" / "wiki" / "concepts" / "old.md", "---\ntitle: Old\ncreated: 1 March\n---\n\n# Old\n")
        write(knowledge / "dormant" / "raw" / "notes.md", "---\nzone: Work\n---\n\nFrozen notes.\n")
        self.assertClean("meetings")
        self.assertClean("knowledge")
        self.assertClean("links")

    def test_a_path_written_where_the_page_stood_in_another_grade_is_refused(self):
        """Fade leaves a link in code as it was written (#256), and a link it
        does not rewrite, such as a Markdown one, too: whichever grade's
        place it names, the page still stands behind it (#297)."""
        for before, after in (("", "dormant"), ("", "archive"), ("dormant", "archive"), ("dormant", ""),
                              ("archive", "")):
            with self.subTest(before=before, after=after):
                place = "/".join(p for p in (before, "wiki/sources/260312-birch-kickoff") if p)
                moved = self.meetings / "wiki" / "sources" / "260312-birch-kickoff.md"
                if after:
                    moved = self.fade(after)
                try:
                    for link in ("`[[Meetings/%s]]`" % place, "`Wikis/Meetings/%s.md`" % place,
                                 "\n```\n[[Meetings/%s]]\n```\n" % place,
                                 "[the call](../../../../../Wikis/Meetings/%s.md)" % place,
                                 "[the call](Meetings/%s.md)" % place):
                        write(self.acme / "Threads" / "Pricing" / "Benchmarks.md", "Their pricing: %s\n" % link)
                        self.assertFinds("walls", "error", "a meeting with birch",
                                         "Zones/Work/Acme Review/Threads/Pricing/Benchmarks.md")
                finally:
                    moved.rename(self.meetings / "wiki" / "sources" / moved.name)

    def test_a_knowledge_link_to_where_a_meeting_stood_is_refused(self):
        self.fade("dormant", page="wiki/sources/260310-acme-kickoff.md")
        for link in ("[the call](../../../Meetings/wiki/sources/260310-acme-kickoff.md)",
                     "[the call](Meetings/wiki/sources/260310-acme-kickoff.md)"):
            write(self.root / "Wikis" / "Knowledge" / "wiki" / "concepts" / "pricing.md", "As in %s.\n" % link)
            self.assertFinds("knowledge", "error", "Meetings page")

    def test_a_link_into_a_faded_page_still_lands(self):
        self.fade("dormant", page="wiki/sources/260310-acme-kickoff.md")
        note = self.acme / "Threads" / "Pricing" / "Pricing.md"
        note.write_text(note.read_text() + "\n| | |\n|---|---|\n| Live artifact | [[260310-acme-kickoff]] |\n")
        self.assertClean("resume")
        self.assertClean("walls")


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



def wiki_question(fields="zone: Work\nparties: [acme]\n", status="open", bold=True,
                  pages='["[[wiki/sources/260310-acme-kickoff]]"]', body="The Acme pages give both figures."):
    """A wiki question (#224), in the Needs you form, with what a wiki adds."""
    ask = "Acme: which volume floor holds, 400 pallets or 500?"
    return ("---\ntype: question\nasked: 2026-03-12\nstatus: %s\n%sorigin: \"[[raw/260310-acme-kickoff]]\"\n"
            "pages: %s\n---\n\n%s\n\n%s\n\n- [400 pallets] The floor is 400\n- [500 pallets] The floor moved to 500\n"
            % (status, fields, pages, "**%s**" % ask if bold else ask, body))


class TestWikiQuestions(CheckCase):
    """A question an ingest or a lint finds only the user can answer is a file
    in the wiki's questions/ (#224), held to the Needs you rules; a Meetings
    question carries a zone and parties, and the walls read it as a page."""

    def setUp(self):
        super().setUp()
        self.asked = self.meetings / "questions"
        self.kasked = self.root / "Wikis" / "Knowledge" / "questions"

    def messages(self, path):
        return sorted(f.message for f in self.findings("questions") if f.path == path)

    def test_a_meetings_question_as_written_passes(self):
        write(self.asked / "260312 - volume-floor.md", wiki_question())
        for name in ("questions", "meetings", "walls", "links", "knowledge", "raw"):
            self.assertClean(name)

    def test_one_with_no_zone_or_no_parties_warns(self):
        write(self.asked / "260312 - no-zone.md", wiki_question("parties: [acme]\n"))
        write(self.asked / "260312 - no-parties.md", wiki_question("zone: Work\n"))
        self.assertEqual(["unfinished: no zone; nothing on it may be used in a project"],
                         self.messages("Wikis/Meetings/questions/260312 - no-zone.md"))
        self.assertEqual(["unfinished: no parties; nothing on it may be used in a project"],
                         self.messages("Wikis/Meetings/questions/260312 - no-parties.md"))
        self.assertFalse(self.findings("questions", "error"))
        self.assertClean("meetings")       # a question is not a meeting page: no name or type to fix
        self.assertEqual("No problems, two warnings. Two things need fixing in question files.",
                         check.report_ear(check.run_checks(self.root, quick=True)))
        (self.asked / "260312 - no-zone.md").unlink()
        self.assertEqual("No problems, one warning. One Meetings question has no parties.",
                         check.report_ear(check.run_checks(self.root, quick=True)))

    def test_every_check_can_be_said_aloud_in_a_group(self):
        self.assertEqual([], [c for c, _ in check.CHECKS if c not in check.EAR_GROUP])

    def test_an_unknown_party_and_both_sides_of_a_wall_are_named(self):
        write(self.asked / "260312 - cedar.md", wiki_question("zone: Work\nparties: [cedar]\n"))
        write(self.asked / "260312 - both.md", wiki_question("zone: Work\nparties: [acme, birch]\n"))
        self.assertFinds("questions", "error", "party `cedar` is not a tag", "Wikis/Meetings/questions/260312 - cedar.md")
        self.assertFinds("questions", "warning", "names both acme and birch, which a wall keeps apart, so no project "
                         "of either may use it; ask it once for each side", "Wikis/Meetings/questions/260312 - both.md")

    def test_a_knowledge_question_with_no_parties_passes(self):
        write(self.kasked / "260312 - failover-figure.md",
              wiki_question("", pages='["[[wiki/sources/supply-chain-report]]"]'))
        self.assertClean("questions")
        self.assertClean("knowledge")

    def test_a_knowledge_question_with_a_zone_or_parties_is_refused_as_any_knowledge_file(self):
        write(self.kasked / "260312 - failover-figure.md",
              wiki_question(pages='["[[wiki/sources/supply-chain-report]]"]'))
        self.assertFinds("knowledge", "error", "carries `parties` and `zone`")
        self.assertClean("questions")      # no zone or parties is asked of a Knowledge question

    def test_a_malformed_one_fails_as_a_needs_you_file_would(self):
        broken = [("a", "pending", True), ("b", "later", True), ("c", "open", False)]
        box = self.acme / "Threads" / "Pricing" / "Needs you"
        for name, status, bold in broken:
            write(self.asked / ("%s.md" % name), wiki_question(status=status, bold=bold))
            write(self.kasked / ("%s.md" % name), wiki_question("", status=status, bold=bold, pages="[]"))
            write(box / ("%s.md" % name), wiki_question(status=status, bold=bold))
        write(self.asked / "d.md", wiki_question().replace("type: question", "type: meeting"))
        write(box / "d.md", wiki_question().replace("type: question", "type: meeting"))
        for name in "abcd":
            home = [m.replace("the home", "Garrick") for m in
                    self.messages("Zones/Work/Acme Review/Threads/Pricing/Needs you/%s.md" % name)]
            self.assertTrue(home)
            self.assertEqual(home, self.messages("Wikis/Meetings/questions/%s.md" % name))
            if name != "d":
                self.assertEqual(home, self.messages("Wikis/Knowledge/questions/%s.md" % name))
        self.assertIn("`status` is 'pending'; Garrick reads open, answered, later",
                      self.messages("Wikis/Meetings/questions/a.md"))
        self.assertIn("no bold line to ask, so Garrick leaves it out", self.messages("Wikis/Meetings/questions/c.md"))

    def test_a_project_may_not_link_a_question_across_a_wall(self):
        write(self.asked / "260312 - birch-lease.md", wiki_question("zone: Work\nparties: [birch]\n",
                                                                     pages='["[[wiki/sources/260312-birch-kickoff]]"]'))
        write(self.acme / "Threads" / "Pricing" / "Notes.md", "See [[260312 - birch-lease]].\n")
        self.assertFinds("walls", "error", "links [[260312 - birch-lease]], a question with birch; a wall stands "
                         "between acme and birch", "Zones/Work/Acme Review/Threads/Pricing/Notes.md")

    def test_a_question_in_a_subfolder_or_named_apart_is_read_too(self):
        for name in ("answered/260312 - birch-lease.md", "_260312 - birch-lease.md"):
            with self.subTest(name=name):
                q = write(self.asked / name, wiki_question("zone: Work\nparties: [birch]\n",
                                                          pages='["[[wiki/sources/260312-birch-kickoff]]"]'))
                link = Path(name).stem
                write(self.acme / "Threads" / "Pricing" / "Notes.md", "See [[%s]].\n" % link)
                self.assertFinds("walls", "error", "links [[%s]], a question with birch" % link,
                                 "Zones/Work/Acme Review/Threads/Pricing/Notes.md")
                q.unlink()

    def test_nor_an_unfinished_one(self):
        write(self.asked / "260312 - floor.md", wiki_question("parties: [acme]\n"))
        write(self.acme / "Threads" / "Pricing" / "Notes.md", "See [[260312 - floor]].\n")
        hit = self.assertFinds("walls", "error", "uses 260312 - floor, an unfinished question (no zone or parties)")
        self.assertEqual("A note in Acme Review's Pricing thread uses an unfinished question", hit[0].ear)

    def test_wording_from_a_question_across_a_wall_is_refused(self):
        quote = "Theo confirmed the Bergen warehouse lease runs out at the end of the spring quarter"
        write(self.asked / "260312 - birch-lease.md", wiki_question("zone: Work\nparties: [birch]\n", body=quote + "."))
        write(self.acme / "Threads" / "Pricing" / "Notes.md", "%s.\n" % quote)
        hit = self.assertFinds("walls", "error", "repeats wording from question 260312 - birch-lease, a question with birch")
        self.assertEqual("A note in Acme Review's Pricing thread quotes a question with Birch & Co", hit[0].ear)

    def test_a_question_on_the_near_side_never_vouches_for_wording(self):
        quote = "Theo confirmed the Bergen warehouse lease runs out at the end of the spring quarter"
        page = self.meetings / "wiki" / "sources" / "260312-birch-kickoff.md"
        page.write_text(page.read_text().replace("Decisions.", quote + "."))
        write(self.asked / "260312 - lease.md", wiki_question(body=quote + "."))   # filed for acme
        write(self.acme / "Threads" / "Pricing" / "Notes.md", "%s.\n" % quote)
        self.assertFinds("walls", "error", "repeats wording from meeting 260312-birch-kickoff")

    def test_a_question_citing_a_meeting_across_its_wall_warns(self):
        write(self.asked / "260312 - floor.md", wiki_question(pages='["[[wiki/sources/260312-birch-kickoff]]"]'))
        self.assertFinds("questions", "warning", "cites 260312-birch-kickoff, a meeting with birch, but is written "
                         "for acme, across a wall", "Wikis/Meetings/questions/260312 - floor.md")

    def test_the_wiki_lint_counts_no_question_as_a_page(self):
        import wiki_lint  # noqa: E402
        before = wiki_lint.lint(self.meetings)
        write(self.asked / "260312 - floor.md", wiki_question())
        self.assertEqual(before, wiki_lint.lint(self.meetings))

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

    def test_an_edit_in_a_subfolder(self):
        nested = self.meetings / "raw" / "2026" / "03" / "260311-acme-follow-up.txt"
        write(nested, "Dana: Tuesday.\n")
        commit_all(self.meetings, "file")
        nested.write_text("Dana: Wednesday.\n")
        self.assertFinds("raw", "error", "edited", "Wikis/Meetings/raw/2026/03/260311-acme-follow-up.txt")

    def test_deleted(self):
        self.record.unlink()
        commit_all(self.meetings, "remove")
        self.assertFinds("raw", "error", "deleted")

    def test_a_rename_alone_is_not_a_change(self):
        git(self.meetings, "mv", "raw/260310-acme-kickoff.txt", "raw/260310-acme-kick-off.txt")
        self.assertClean("raw")                                 # staged, not yet committed
        commit_all(self.meetings, "name corrected")
        self.assertClean("raw")

    def test_a_rename_with_an_edit_is_reported_under_the_new_name(self):
        self.record.write_text("".join("Dana: line %d of the call.\n" % n for n in range(1, 11)))
        commit_all(self.meetings, "full transcript")
        git(self.meetings, "mv", "raw/260310-acme-kickoff.txt", "raw/260310-acme-kick-off.txt")
        renamed = self.meetings / "raw" / "260310-acme-kick-off.txt"
        renamed.write_text(renamed.read_text().replace("line 5", "line five"))
        commit_all(self.meetings, "name corrected, and a line")
        hits = self.assertFinds("raw", "error", "edited")
        self.assertEqual(["Wikis/Meetings/raw/260310-acme-kick-off.txt"], [f.path for f in hits])

    def test_an_earlier_edit_follows_the_record_when_it_moves(self):
        self.record.write_text("Dana: we start Tuesday.\n")
        commit_all(self.meetings, "tidy")
        git(self.meetings, "mv", "raw/260310-acme-kickoff.txt", "raw/260310-acme-kick-off.txt")
        commit_all(self.meetings, "name corrected")
        hits = self.assertFinds("raw", "error", "edited")
        self.assertEqual(["Wikis/Meetings/raw/260310-acme-kick-off.txt"], [f.path for f in hits])

    def test_filed_out_of_the_inbox_is_not_a_change(self):
        write(self.meetings / "raw" / "inbox" / "call.txt", "".join("line %d\n" % n for n in range(10)))
        commit_all(self.meetings, "dropped in")
        git(self.meetings, "mv", "raw/inbox/call.txt", "raw/260320-acme-call.txt")
        filed = self.meetings / "raw" / "260320-acme-call.txt"
        filed.write_text(filed.read_text().replace("line 5", "line five"))
        commit_all(self.meetings, "filed")
        self.assertClean("raw")

    def test_a_record_fades_and_wakes_with_its_page(self):
        for grade in ("dormant", "archive"):
            (self.meetings / grade / "raw").mkdir(parents=True, exist_ok=True)
            moved = "%s/raw/260310-acme-kickoff.txt" % grade
            git(self.meetings, "mv", "raw/260310-acme-kickoff.txt", moved)
            self.assertClean("raw")                             # staged across the folders
            commit_all(self.meetings, "faded to " + grade)
            self.assertClean("raw")
            git(self.meetings, "mv", moved, "raw/260310-acme-kickoff.txt")
            commit_all(self.meetings, "woken")
            self.assertClean("raw")

    def test_a_faded_record_stays_protected(self):
        (self.meetings / "dormant" / "raw").mkdir(parents=True)
        (self.meetings / "archive" / "raw").mkdir(parents=True)
        nested = write(self.meetings / "raw" / "2026" / "03" / "260311-acme-follow-up.txt", "Dana: Tuesday.\n")
        commit_all(self.meetings, "file")
        git(self.meetings, "mv", "raw/260310-acme-kickoff.txt", "dormant/raw/260310-acme-kickoff.txt")
        (self.meetings / "archive" / "raw" / "2026" / "03").mkdir(parents=True)
        git(self.meetings, "mv", "raw/2026/03/260311-acme-follow-up.txt", "archive/raw/2026/03/260311-acme-follow-up.txt")
        commit_all(self.meetings, "faded")
        self.assertFalse(nested.exists())
        (self.meetings / "dormant" / "raw" / "260310-acme-kickoff.txt").write_text("Dana: we start Tuesday.\n")
        (self.meetings / "archive" / "raw" / "2026" / "03" / "260311-acme-follow-up.txt").unlink()
        self.assertFinds("raw", "error", "edited", "Wikis/Meetings/dormant/raw/260310-acme-kickoff.txt")
        self.assertFinds("raw", "error", "deleted", "Wikis/Meetings/archive/raw/2026/03/260311-acme-follow-up.txt")
        commit_all(self.meetings, "tidied")
        self.assertFinds("raw", "error", "edited", "Wikis/Meetings/dormant/raw/260310-acme-kickoff.txt")
        self.assertFinds("raw", "error", "deleted", "Wikis/Meetings/archive/raw/2026/03/260311-acme-follow-up.txt")

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
