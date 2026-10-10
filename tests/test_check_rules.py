"""The checks that came with the workspace's own rules: settings, skills, the
hub as index, single-thread projects, layouts, anonymous projects, to-do
lists, links, accepted raw changes, Garrick's own files and --quick. Each one
passes on the clean fixture and fails on a broken one."""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from fixtures import GIT_ENV, HAVE_GIT, commit_all, git, git_init, meeting_page, thread_note, write
from test_check import CheckCase

import check  # noqa: E402  (fixtures puts the tools folder on sys.path)
from garrick_lib import fingerprint  # noqa: E402


def settings(root: Path, data) -> None:
    write(root / "System" / "garrick-checks.json", data if isinstance(data, str) else json.dumps(data))


def commit_dated(folder: Path, message: str, when: str) -> None:
    env = dict(GIT_ENV, GIT_AUTHOR_DATE=when + "T12:00:00", GIT_COMMITTER_DATE=when + "T12:00:00")
    subprocess.run(["git", "add", "-A"], cwd=str(folder), env=env, check=True, capture_output=True)
    subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=" + os.devnull, "commit", "-q",
                    "--allow-empty", "-m", message], cwd=str(folder), env=env, check=True, capture_output=True)


def real_repo(folder: Path) -> None:
    """Swap the fixture's stand-in .git folder for a real repository."""
    shutil.rmtree(folder / ".git", ignore_errors=True)
    git_init(folder)


class TestSettings(CheckCase):
    def test_no_file_is_clean(self):
        self.assertClean("settings")

    def test_unreadable(self):
        settings(self.root, "{not json")
        self.assertFinds("settings", "error", "does not read as JSON")

    def test_unknown_key_and_wrong_kind(self):
        settings(self.root, {"parent-link": ["Work"], "todo-labels": "Work"})
        self.assertFinds("settings", "error", "`parent-link` is not a setting")
        self.assertFinds("settings", "error", "`todo-labels` should be a list")

    def test_unknown_zone_and_budget(self):
        settings(self.root, {"note-links": ["Wrok"], "word-budgets": {"root": "lots"}})
        self.assertFinds("settings", "warning", "zone Wrok")
        self.assertFinds("settings", "warning", "`word-budgets`")

    def test_good_settings_are_clean(self):
        settings(self.root, {"parent-links": ["Work"], "word-budgets": {"root": 900, "other": 1200},
                             "retired-skills": {"old-wrap": "threads"}})
        self.assertClean("settings")


class TestInstructionFilesPresent(CheckCase):
    def test_root_agents_missing(self):
        (self.root / "AGENTS.md").unlink()
        self.assertFinds("instructions", "error", "missing", path="AGENTS.md")

    def test_wiki_agents_missing(self):
        (self.meetings / "AGENTS.md").unlink()
        self.assertFinds("instructions", "error", "missing", path="Wikis/Meetings/AGENTS.md")

    def test_word_budget_from_settings(self):
        write(self.root / "AGENTS.md", "# Workspace\n\n" + "word " * 900)
        settings(self.root, {"word-budgets": {"root": 1000}})
        self.assertClean("instructions")
        settings(self.root, {"word-budgets": {"root": 500}})
        self.assertFinds("instructions", "warning", "over its 500")

    def test_zone_project_list(self):
        write(self.work / "AGENTS.md", "# Work\n\n- `Acme Review/Acme Review.md`\n")
        self.assertFinds("instructions", "warning", "not Birch Entry/Birch Entry.md")
        write(self.work / "AGENTS.md", "# Work\n\n- `Acme Review/Acme Review.md`\n- `Birch Entry/Birch Entry.md`\n"
                                       "- `Acme Review/Gone.md`\n")
        hits = self.assertFinds("instructions", "warning", "lists Acme Review/Gone.md")
        self.assertEqual(1, len(hits))

    def test_zone_without_a_list(self):
        write(self.work / "AGENTS.md", "# Work\n\nSee `../../System/rules.md`.\n")
        self.assertClean("instructions")


class TestContextNames(CheckCase):
    def add_row(self, wall: bool):
        ctx = self.root / "System" / "context.md"
        text = ctx.read_text().replace(
            "| Birch & Co | Client.", "| Acme Corp | Advisory to Acme's board, a second role | Work | `acme-board` | |\n"
                                    "| Birch & Co | Client.")
        if wall:
            text = text.replace("| `acme` | `birch` |", "| `acme` | `acme-board` | Two roles |\n| `acme` | `birch` |")
        ctx.write_text(text)

    def test_shared_name_without_a_wall(self):
        self.add_row(wall=False)
        self.assertFinds("context", "warning", "no wall between them")

    def test_shared_name_with_a_wall(self):
        self.add_row(wall=True)
        self.assertClean("context")

    def test_no_aliases_table(self):
        ctx = self.root / "System" / "context.md"
        ctx.write_text(ctx.read_text().split("## Aliases")[0])
        self.assertFinds("context", "warning", "Aliases")


class TestSkills(CheckCase):
    def setUp(self):
        super().setUp()
        self.home = self.root.parent / "home"
        self.home.mkdir()
        patcher = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.skills = self.root / "System" / "skills"
        write(self.skills / "threads" / "SKILL.md", "---\nname: threads\nmodel: sonnet\n---\n")

    def link_all(self):
        for repo in [self.root, self.work, self.root / "Zones" / "Personal"]:
            for f in (".claude", ".agents"):
                (repo / f).mkdir(exist_ok=True)
                os.symlink(os.path.relpath(self.skills, repo / f), repo / f / "skills")

    def test_linked_in_every_repository(self):
        self.link_all()
        self.assertClean("skills")

    def test_unreachable(self):
        hits = self.assertFinds("skills", "warning", "finds no threads")
        self.assertEqual(6, len(hits))  # the root and two zones, for each assistant

    def test_user_level_links_reach_everywhere(self):
        for f in (".claude", ".agents"):
            (self.home / f / "skills").mkdir(parents=True)
            os.symlink(self.skills / "threads", self.home / f / "skills" / "threads")
        self.assertClean("skills")

    def test_assistants_see_different_skills(self):
        self.link_all()
        (self.meetings / ".git").mkdir()
        for f in (".claude", ".agents"):
            (self.home / f / "skills").mkdir(parents=True)
            os.symlink(self.skills / "threads", self.home / f / "skills" / "threads")
        wiki_skills = self.meetings / ".claude" / "skills"
        write(wiki_skills / "ingest" / "SKILL.md", "---\nname: ingest\n---\n")
        (self.meetings / ".agents" / "skills").mkdir(parents=True)
        self.assertFinds("skills", "warning", "different skills")
        shutil.rmtree(self.meetings / ".agents")
        (self.meetings / ".agents").mkdir()
        os.symlink("../.claude/skills", self.meetings / ".agents" / "skills")
        self.assertClean("skills")

    def test_retired_skill(self):
        self.link_all()
        settings(self.root, {"retired-skills": {"old-wrap": "threads"}})
        self.assertClean("skills")
        write(self.root / "System" / "rules.md", "# Rules\n\n- Run old-wrap at the end.\n- old-wrap was retired.\n")
        hits = self.assertFinds("skills", "warning", "sends work to `old-wrap`")
        self.assertEqual("System/rules.md:3", hits[0].path)
        write(self.skills / "old-wrap" / "SKILL.md", "---\nname: old-wrap\n---\n")
        self.assertFinds("skills", "error", "is back")

    def test_model_version(self):
        self.link_all()
        write(self.skills / "threads" / "SKILL.md", "---\nname: threads\nmodel: model-4-5-20250101\n---\n")
        self.assertFinds("skills", "warning", "a version")

    def test_vendored_without_commit(self):
        self.link_all()
        write(self.skills / "threads" / "VENDORED.md", "# Vendored\n\n- Source: https://example.invalid/skill\n")
        self.assertFinds("skills", "warning", "no source commit")
        write(self.skills / "threads" / "VENDORED.md", "# Vendored\n\n- Commit: 9e35d2b (2026-09-23)\n")
        self.assertClean("skills")


class TestHubIndex(CheckCase):
    def test_unlinked_thread(self):
        write(self.acme / "Threads" / "Renewal" / "Renewal.md", thread_note("Acme Review", "Renewal"))
        self.assertFinds("projects", "warning", "does not link the thread Renewal")

    def test_finished_thread_listed(self):
        hub = self.acme / "Acme Review.md"
        write(self.acme / "Threads" / "Pricing" / "Pricing.md", thread_note("Acme Review", "Pricing", status="done"))
        self.assertFinds("projects", "warning", "not listed under `## Finished`")
        hub.write_text(hub.read_text().replace("## Threads", "## Finished"))
        self.assertClean("projects")

    def test_project_that_is_one_thread(self):
        shutil.rmtree(self.acme / "Threads")
        hub = self.acme / "Acme Review.md"
        hub.write_text(hub.read_text().split("## Threads")[0]
                       + "## State of play\n\n### Resume here\n\n**Where it stands.** Drafting.\n")
        self.assertClean("projects")

    def test_renamed_hub_and_thread(self):
        (self.acme / "Acme Review.md").rename(self.acme / "Acme Review-v2.md")
        self.assertFinds("projects", "error", "Acme Review-v2.md is there")
        note = self.root / "Zones" / "Work" / "Birch Entry" / "Threads" / "Market Sizing"
        (note / "Market Sizing.md").rename(note / "Market Sizing-v3.md")
        self.assertFinds("threads", "error", "Market Sizing-v3.md is there")

    def test_thread_with_unknown_party(self):
        write(self.acme / "Threads" / "Pricing" / "Pricing.md", thread_note("Acme Review", "Pricing", party="cedar"))
        self.assertFinds("threads", "error", "`party` cedar")


class TestLayout(CheckCase):
    def hub(self, layout):
        hub = self.acme / "Acme Review.md"
        hub.write_text(hub.read_text().replace("status: active", "status: active\nlayout: %s" % layout))

    def test_thread_first(self):
        self.hub("thread-first")
        hits = self.assertFinds("projects", "warning", "thread-first")
        self.assertEqual({"Zones/Work/Acme Review/Deliverables", "Zones/Work/Acme Review/Sources"}, {h.path for h in hits})
        shutil.rmtree(self.acme / "Deliverables")
        shutil.rmtree(self.acme / "Sources")
        write(self.acme / "Threads" / "Pricing" / "Deliverables" / "260301 - Memo.md", "x")
        self.assertClean("projects")
        self.assertClean("deliverables")

    def test_unknown_layout(self):
        self.hub("flat")
        self.assertFinds("projects", "warning", "`layout` is 'flat'")


class TestSystemProject(CheckCase):
    def test_system_project_needs_no_zone_or_party(self):
        setup = self.root / "System" / "Workspace Setup"
        write(setup / "Workspace Setup.md",
              "---\ntitle: Workspace Setup\ntype: project\nstatus: active\ncreated: 2026-03-01\nupdated: 2026-03-01\n---\n\n"
              "# Workspace Setup\n\n## State of play\n\n### Resume here\n\nSee `Notes/plan.md`.\n")
        self.assertClean("projects")
        self.assertFinds("resume", "warning", "`Notes/plan.md`")
        write(setup / "Notes" / "plan.md", "# Plan\n")
        self.assertClean("resume")

    def test_other_system_folders_are_not_projects(self):
        write(self.root / "System" / "templates" / "templates.md", "# Not a project\n")
        self.assertClean("projects")


class TestResumeMore(CheckCase):
    def resume(self, line, hub=False):
        if hub:
            path = self.acme / "Acme Review.md"
            path.write_text(path.read_text() + "\n## State of play\n\n### Resume here\n\n%s\n" % line)
        else:
            body = thread_note("Acme Review", "Pricing").replace("Drafting.", "Drafting. %s" % line)
            write(self.acme / "Threads" / "Pricing" / "Pricing.md", body)

    def test_hub_block_is_read(self):
        self.resume("See [[Nowhere at all]].", hub=True)
        self.assertFinds("resume", "warning", "[[Nowhere at all]]", path="Zones/Work/Acme Review/Acme Review.md")

    def test_more_places_a_path_starts(self):
        self.resume("Actions in `Work/Todo.md`, transcript in `Meetings/raw/260310-acme-kickoff.txt`, "
                    "memo `Deliverables/260301 - Pricing memo.md`.")
        self.assertClean("resume")

    def test_share_and_office_parts(self):
        self.resume("On the shared drive: `Acme/Board/Pack.pptx`. Inside it, `ppt/slides/slide1.xml`.")
        self.assertClean("resume")
        self.resume("Draft at `Acme/Board/Pack.pptx`.")
        self.assertFinds("resume", "warning", "`Acme/Board/Pack.pptx`")
        hub = self.acme / "Acme Review.md"
        hub.write_text(hub.read_text().replace("status: active", "status: active\nshare: Clients/Acme"))
        self.assertClean("resume")

    @unittest.skipUnless(HAVE_GIT, "git is not installed")
    def test_left_behind(self):
        real_repo(self.work)
        commit_dated(self.work, "start", "2026-03-01")
        write(self.acme / "Deliverables" / "260320 - Second memo.md", "x")
        commit_dated(self.work, "a week later", "2026-03-08")
        self.assertClean("resume")
        write(self.acme / "Deliverables" / "260325 - Third memo.md", "x")
        commit_dated(self.work, "much later", "2026-03-25")
        self.assertFinds("resume", "warning", "last updated on 2026-03-01")


class TestDeliverablesMore(CheckCase):
    def test_not_deliverables(self):
        d = self.acme / "Deliverables"
        for name in ("README.md", "published.md", "build/make.py", "render-1/a.png", "specs/x.md", "build.py", "~$memo.docx"):
            write(d / name, "x")
        write(d / "Board pack" / "build.sh", "x")
        self.assertClean("deliverables")

    def test_grouping_folder(self):
        d = self.acme / "Deliverables" / "Workshops"
        write(d / "260301 - Agenda.md", "x")
        self.assertClean("deliverables")
        write(d / "Notes.md", "x")
        self.assertFinds("deliverables", "warning", path="Zones/Work/Acme Review/Deliverables/Workshops/Notes.md")

    def test_thread_and_archive_folders(self):
        write(self.acme / "Threads" / "Pricing" / "Deliverables" / "Memo.md", "x")
        write(self.acme / "Deliverables" / "archive" / "Old memo.md", "x")
        hits = self.assertFinds("deliverables", "warning")
        self.assertEqual(2, len(hits))


class TestAnonymous(CheckCase):
    def setUp(self):
        super().setUp()
        hub = self.acme / "Acme Review.md"
        hub.write_text(hub.read_text().replace("status: active", "status: active\nanonymous: true"))
        self.d = self.acme / "Deliverables"

    def test_clean(self):
        write(self.d / "260302 - Template.md", "A pricing template for any client.\n")
        self.assertClean("anonymous")

    def test_names_another_party(self):
        write(self.d / "260302 - Template.md", "Built from the work for Birch & Co.\n")
        self.assertFinds("anonymous", "warning", path="Zones/Work/Acme Review/Deliverables/260302 - Template.md")

    def test_person_in_an_office_file(self):
        path = self.d / "260302 - Term sheet.docx"
        with zipfile.ZipFile(str(path), "w") as z:
            z.writestr("word/document.xml", "<w:t>Agreed with Theo</w:t><w:t> Marsh</w:t>")
            z.writestr("docProps/core.xml", "<dc:creator>Birch</dc:creator>")
        self.assertFinds("anonymous", "warning", path="Zones/Work/Acme Review/Deliverables/260302 - Term sheet.docx")

    def test_who_saved_it_does_not_count(self):
        path = self.d / "260302 - Term sheet.docx"
        with zipfile.ZipFile(str(path), "w") as z:
            z.writestr("word/document.xml", "<w:t>A term sheet.</w:t>")
            z.writestr("docProps/core.xml", "<dc:creator>Theo Marsh</dc:creator>")
        self.assertClean("anonymous")

    def test_extra_names_and_sources(self):
        hub = self.acme / "Acme Review.md"
        hub.write_text(hub.read_text().replace("anonymous: true", "anonymous: [Cedar Labs]"))
        write(self.acme / "Sources" / "brief.md", "From Birch & Co and Cedar Labs.\n")
        self.assertClean("anonymous")
        write(self.d / "260302 - Template.md", "Compared with Cedar Labs.\n")
        self.assertFinds("anonymous", "warning")

    def test_a_damaged_office_file_is_read_as_empty(self):
        path = self.d / "260302 - Term sheet.docx"
        with zipfile.ZipFile(str(path), "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("word/document.xml", "<w:t>Agreed with Theo Marsh</w:t>" * 50)
        data = bytearray(path.read_bytes())
        start = data.index(b"word/document.xml") + len(b"word/document.xml")
        data[start:start + 40] = b"\xff" * 40                  # the compressed stream, broken
        path.write_bytes(bytes(data))
        self.assertClean("anonymous")

    def test_not_anonymous(self):
        hub = self.acme / "Acme Review.md"
        hub.write_text(hub.read_text().replace("anonymous: true\n", ""))
        write(self.d / "260302 - Template.md", "Built from the work for Birch & Co.\n")
        self.assertClean("anonymous")


class TestTodo(CheckCase):
    def todo(self, *lines):
        write(self.work / "Todo.md", "# Work: open actions\n\n## Inbox\n\n%s\n\n## Done\n" % "\n".join(lines))

    def test_clean(self):
        self.todo("- [ ] [[Pricing]]: send the memo 📅 2026-03-20",
                  "- [ ] [[Acme Review/Threads/Pricing/Pricing|Pricing]]: book the call",
                  "- [ ] Acme Corp: chase the invoice ⏳ 2026-03-22 #waiting")
        self.assertClean("todo")

    def test_template_line_is_not_a_thread(self):
        self.todo("- [ ] [[<Thread>]]: <action> 📅 <YYYY-MM-DD>")
        self.assertClean("todo")

    def test_label_leads_nowhere(self):
        self.todo("- [ ] [[Old Pricing]]: send the memo")
        self.assertFinds("todo", "warning", "[[Old Pricing]]")

    def test_date_not_last(self):
        self.todo("- [ ] [[Pricing]]: send the memo 📅 2026-03-20 then call Dana")
        self.assertFinds("todo", "warning", "date with text after it")

    def test_labels_required(self):
        self.todo("- [ ] Acme Corp: chase the invoice")
        self.assertClean("todo")
        settings(self.root, {"todo-labels": ["Work"]})
        self.assertFinds("todo", "warning", "1 open action does not open")

    @unittest.skipUnless(HAVE_GIT, "git is not installed")
    def test_inbox_growth(self):
        real_repo(self.work)
        self.todo("- [ ] [[Pricing]]: one")
        commit_dated(self.work, "a fortnight ago", "2026-01-01")
        self.todo(*["- [ ] [[Pricing]]: action %d" % i for i in range(25)])
        commit_all(self.work, "today")
        self.assertFinds("todo", "warning", "grew by 24")


class TestLinks(CheckCase):
    def test_clean(self):
        self.assertClean("links")

    def test_link_into_another_zone(self):
        write(self.acme / "Threads" / "Pricing" / "Notes.md", "See [[Zones/Personal/Garden/Garden]].\n")
        self.assertFinds("links", "error", "the Personal zone")

    def test_relative_link_into_another_zone(self):
        write(self.root / "Zones" / "Personal" / "Garden" / "Plan.md", "# Plan\n")
        write(self.acme / "Notes.md", "See [plan](../../Personal/Garden/Plan.md).\n")
        self.assertFinds("links", "error", "the Personal zone")

    def test_zone_instructions_may_name_another_zone(self):
        write(self.work / "AGENTS.md", "# Work\n\nPersonal matters: [[Zones/Personal/Todo]].\n")
        self.assertClean("links")

    def test_cloud_path(self):
        write(self.acme / "Notes.md", "x\nThe pack is in ~/Library/CloudStorage/Drive-Acme/Board/pack.pptx\n")
        self.assertFinds("links", "warning", "cloud-synced", path="Zones/Work/Acme Review/Notes.md:2")

    def test_a_repository_inside_a_project_is_not_notes(self):
        code = self.acme / "Tool"
        write(code / "README.md", "Install to ~/Library/CloudStorage/Drive-Acme/tool\n")
        self.assertFinds("links", "warning", "cloud-synced")
        (code / ".git").mkdir()
        self.assertClean("links")

    def test_name_in_both_wikis(self):
        knowledge = self.root / "Wikis" / "Knowledge"
        write(knowledge / "wiki" / "people" / "dana-whitlock.md", "# Dana Whitlock, the author\n")
        write(self.acme / "Notes.md", "Met [[wiki/people/dana-whitlock]] and [[Meetings/wiki/people/dana-whitlock]].\n")
        hits = self.assertFinds("links", "warning", "both wikis hold")
        self.assertEqual(["Zones/Work/Acme Review/Notes.md"], [h.path for h in hits])  # the meetings' own links land in Meetings
        write(self.acme / "Notes.md", "Met [[Meetings/wiki/people/dana-whitlock]].\n")
        self.assertClean("links")
        (self.root / "Wikis" / "Registry").mkdir()
        self.assertFinds("links", "warning", "no Registry note")
        write(self.root / "Wikis" / "Registry" / "dana-whitlock.md", "# dana-whitlock\n")
        self.assertClean("links")

    def test_parent_links(self):
        write(self.acme / "Threads" / "Pricing" / "Benchmarks.md", "# Benchmarks\n")
        self.assertClean("links")
        settings(self.root, {"parent-links": ["Work"]})
        self.assertFinds("links", "warning", "no `parent:`")
        write(self.acme / "Threads" / "Pricing" / "Benchmarks.md", '---\nparent: "[[Gone]]"\n---\n# Benchmarks\n')
        self.assertFinds("links", "warning", "leads to no live note")
        write(self.acme / "Threads" / "Pricing" / "Benchmarks.md", '---\nparent: "[[Pricing]]"\n---\n# Benchmarks\n')
        for thread in (self.acme / "Threads" / "Pricing" / "Pricing.md",
                       self.work / "Birch Entry" / "Threads" / "Market Sizing" / "Market Sizing.md"):
            thread.write_text(thread.read_text().replace("---\n", '---\nparent: "[[%s]]"\n' % thread.parents[2].name, 1))
        write(self.acme / "Deliverables" / "260301 - Pricing memo.md", '---\nparent: "[[Acme Review]]"\n---\n')
        self.assertClean("links")

    def test_note_named_as_code(self):
        write(self.acme / "Threads" / "Pricing" / "Benchmarks.md", "# Benchmarks\n")
        note = self.acme / "Threads" / "Pricing" / "Pricing.md"
        note.write_text(note.read_text() + "\nDetail in `Benchmarks.md`; data in `figures.xlsx`.\n")
        self.assertClean("links")
        settings(self.root, {"note-links": ["Work"]})
        self.assertFinds("links", "warning", "names `Benchmarks.md` as code")


class TestMeetingWalls(CheckCase):
    def test_party_page_cites_across_a_wall(self):
        page = self.meetings / "wiki" / "entities" / "acme-corp.md"
        write(page, "---\ntitle: Acme Corp\ntype: entity\nparty: acme\nsources:\n  - \"[[wiki/sources/260310-acme-kickoff]]\"\n---\n")
        self.assertClean("meetings")
        page.write_text(page.read_text().replace("---\n\n", "") + "\nSee [[260312-birch-kickoff]].\n")
        self.assertFinds("meetings", "warning", "260312-birch-kickoff, a meeting with birch",
                         path="Wikis/Meetings/wiki/entities/acme-corp.md")
        page.write_text(page.read_text().replace("party: acme", "party: none"))
        self.assertClean("meetings")

    def test_both_sides_of_a_wall(self):
        write(self.meetings / "wiki" / "sources" / "260315-panel.md", meeting_page(parties="[acme, birch]"))
        self.assertFinds("meetings", "warning", "both acme and birch")


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class TestRawAccepted(CheckCase):
    def setUp(self):
        super().setUp()
        git_init(self.meetings)
        commit_all(self.meetings, "first ingest")
        self.raw = self.meetings / "raw" / "260310-acme-kickoff.txt"
        self.raw.write_text("Dana: we start Monday. (A late line, kept on purpose.)\n")
        commit_all(self.meetings, "accepted edit")
        self.accepted = git(self.meetings, "rev-parse", "--short", "HEAD").strip()

    def test_accepted_change(self):
        self.assertFinds("raw", "error", "edited")
        settings(self.root, {"raw-accepted": {"Wikis/Meetings/raw/260310-acme-kickoff.txt": self.accepted}})
        self.assertClean("raw")
        self.raw.write_text("Dana: we start Tuesday.\n")
        commit_all(self.meetings, "another edit")
        self.assertFinds("raw", "error", "edited")

    def test_unknown_commit(self):
        settings(self.root, {"raw-accepted": {"Wikis/Meetings/raw/260310-acme-kickoff.txt": "0123abc"}})
        self.assertFinds("raw", "warning", "git does not know")


    def test_an_accepted_change_must_name_a_commit(self):
        settings(self.root, {"raw-accepted": {"Wikis/Meetings/raw/260310-acme-kickoff.txt": "--output=/tmp/x"}})
        self.assertFinds("settings", "warning", "not a commit")
        self.assertFinds("raw", "error", "edited")                 # left out, so the edit still counts


class TestOneCheckStops(CheckCase):
    def test_the_others_still_run(self):
        def broken(ws):
            raise ValueError("a file it could not read")
        with mock.patch.object(check, "ALL_CHECKS", [broken] + list(check.ALL_CHECKS)):
            found = check.run_checks(self.root)
        self.assertTrue(any(f.severity == "error" and "the check stopped: ValueError" in f.message for f in found))


class TestShipped(CheckCase):
    def stamp(self, files):
        write(self.root / "System" / "garrick-version.json", json.dumps({"commit": "abc1234", "files": files}))

    def test_unreadable_stamp(self):
        write(self.root / "System" / "garrick-version.json", "{")
        self.assertFinds("updates", "warning", "does not read as JSON")

    def test_changed_and_missing(self):
        tool = write(self.root / "System" / "tools" / "check.py", "# shipped\n")
        self.stamp({"System/tools/check.py": fingerprint(tool), "System/tools/scaffold.py": "0" * 64,
                    "System/rules.md": "0" * 64})
        hits = self.findings("updates")
        self.assertEqual(["System/tools/scaffold.py"], [h.path for h in hits])
        self.assertIn("missing", hits[0].message)
        tool.write_text("# changed here\n")
        self.assertFinds("updates", "warning", "differs from what Garrick shipped", path="System/tools/check.py")

    def test_prefixes_from_settings(self):
        rules = self.root / "System" / "rules.md"
        self.stamp({"System/rules.md": "0" * 64})
        self.assertClean("updates")
        settings(self.root, {"as-shipped": ["System/rules.md"]})
        self.assertFinds("updates", "warning", "differs", path="System/rules.md")
        self.stamp({"System/rules.md": fingerprint(rules)})
        self.assertClean("updates")


class TestQuick(CheckCase):
    def test_quick_leaves_out_wording_only(self):
        quote = "Dana confirmed the freight consolidation saves forty thousand pounds across the northern depots"
        write(self.meetings / "wiki" / "sources" / "260312-birch-kickoff.md",
              meeting_page("Work", "[birch]", "Birch kick-off") + "\n%s.\n" % quote)
        write(self.acme / "Threads" / "Pricing" / "Notes.md", "%s.\nTheo Marsh said so.\n" % quote)
        full = [f.message for f in check.run_checks(self.root) if f.check == "walls"]
        quick = [f.message for f in check.run_checks(self.root, quick=True) if f.check == "walls"]
        self.assertTrue(any(m.startswith("repeats wording") for m in full), full)
        self.assertFalse(any(m.startswith("repeats wording") for m in quick), quick)
        self.assertTrue(any(m.startswith("names Birch") for m in quick), quick)

    def test_json_shape(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = check.main(["--root", str(self.root), "--json", "--quick"])
        self.assertEqual(0, code)
        data = json.loads(buf.getvalue())
        self.assertEqual({"root", "errors", "warnings", "findings"}, set(data))


if __name__ == "__main__":
    unittest.main()
