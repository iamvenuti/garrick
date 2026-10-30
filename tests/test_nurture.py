"""Context Nurture: System/tools/nurture.py, and the jobs extra's nightly run
of it, against small synthetic workspaces.

    python3 -m unittest discover -s tests -p test_nurture.py

It sorts what the existing checks find into four kinds; applies the
mechanical ones on one yes, one commit per repository, of the files it
changed and nothing else; never repeats walled material; writes a report per
run; and with nobody watching applies only the kinds registered as
unattended.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import GIT_ENV, HAVE_GIT, build_workspace, git, meeting_page, thread_note, write  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "template" / "System" / "tools"
JOBS = REPO / "extras" / "jobs"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod                      # dataclasses look their module up by name
    spec.loader.exec_module(mod)
    return mod


nurture = load("garrick_nurture", TOOLS / "nurture.py")

WALLED_NOTE = "Theo Marsh said their tender closes on the ninth.\n"


class Base(unittest.TestCase):
    """A workspace with real repositories in Zones/Work and Wikis/, and a few
    things for nurture to find: a status synonym, a thread its hub does not
    list, an undated deliverable, a meeting page renamed by hand so a link to
    it broke, a meeting page with no zone, and a note across the wall."""

    def setUp(self):
        if not HAVE_GIT:
            self.skipTest("git is not installed")
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        env = {k: v for k, v in GIT_ENV.items() if k.startswith("GIT_")}
        env.pop("GIT_DIR", None)
        patch = mock.patch.dict(os.environ, env)
        patch.start()
        self.addCleanup(patch.stop)
        os.environ.pop("GARRICK_HEADLESS", None)
        self.root = Path(self._tmp.name).resolve() / "Workspace"
        build_workspace(self.root)
        self.work = self.root / "Zones" / "Work"
        self.wikis = self.root / "Wikis"
        shutil.rmtree(self.work / ".git")
        git(self.work, "init", "-q")
        git(self.wikis, "init", "-q")
        self.acme = self.work / "Acme Review"
        self.pricing = self.acme / "Threads" / "Pricing" / "Pricing.md"
        write(self.pricing, thread_note("Acme Review", "Pricing", "acme", "Draws on the kick-off.", status="paused"))
        write(self.acme / "Threads" / "Freight" / "Freight.md", thread_note("Acme Review", "Freight", "acme"))
        hub = self.acme / "Acme Review.md"
        hub.write_text(hub.read_text() + "\nThe rates are in `Deliverables/Rate card.md`.\n")
        write(self.acme / "Deliverables" / "Rate card.md", "# Rate card\n")
        write(self.acme / "Notes.md", WALLED_NOTE)
        self.loose = self.wikis / "Meetings" / "wiki" / "sources" / "260320-follow-up.md"
        write(self.loose, meeting_page(None, "[acme]", "Follow-up").replace("Decisions.", "After [[260310-acme-kickoff]]."))
        self.commit(self.work, "2026-03-05T10:00:00")
        self.commit(self.wikis, "2026-03-05T10:00:00")
        git(self.wikis, "mv", "Meetings/wiki/sources/260310-acme-kickoff.md", "Meetings/wiki/sources/260310-acme-start.md")
        git(self.wikis, "-c", "core.hooksPath=" + os.devnull, "commit", "-q", "-m", "renamed by hand")
        # Another session's work, not committed: one file changed, one new.
        write(self.work / "Birch Entry" / "Birch Entry.md",
              (self.work / "Birch Entry" / "Birch Entry.md").read_text() + "\nHalf a sentence being written\n")
        write(self.work / "Scratch.md", "a draft nobody has committed\n")

    def commit(self, repo: Path, when: str) -> None:
        env = dict(GIT_ENV, GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when)
        subprocess.run(["git", "add", "-A"], cwd=str(repo), env=env, check=True)
        subprocess.run(["git", "-c", "core.hooksPath=" + os.devnull, "commit", "-q", "-m", "start"], cwd=str(repo),
                       env=env, check=True)

    def run_tool(self, *args: str):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = nurture.main(list(args) + ["--root", str(self.root), "--json", "--today", "2026-10-17"])
        return code, json.loads(out.getvalue())

    def by_path(self, items, path_end):
        return [i for i in items if i["path"].endswith(path_end)]

    def log(self, repo: Path):
        return git(repo, "log", "--format=%h").split()


class ClassificationTest(Base):
    def test_findings_are_sorted_by_what_a_fix_needs(self):
        code, out = self.run_tool("list")
        items = out["items"]
        kinds = lambda end: {i["kind"] for i in self.by_path(items, end)}
        self.assertEqual({"mechanical"}, kinds("Pricing/Pricing.md"))
        self.assertIn("mechanical", kinds("Acme Review/Acme Review.md"))            # Freight, not listed
        self.assertEqual({"mechanical"}, kinds("Deliverables/Rate card.md"))
        self.assertEqual({"wall"}, kinds("Acme Review/Notes.md"))
        follow_up = self.by_path(items, "260320-follow-up.md")
        self.assertIn("attribution", {i["kind"] for i in follow_up})
        self.assertIn("mechanical", {i["kind"] for i in follow_up})                 # the link the rename broke
        asked = next(i for i in follow_up if i["kind"] == "attribution")
        self.assertIn("Which zone", asked["question"])
        self.assertEqual("zone Work, from its parties", asked["proposal"])
        for item in items:
            self.assertIn(item["kind"], ("wall", "mechanical", "attribution", "judgment", "fade"))
        self.assertEqual(sum(out["kinds"].values()), len(items))

    def test_the_mechanical_fixes_say_exactly_what_they_change(self):
        _, out = self.run_tool("list")
        fixes = {i["fix"]["op"]: i["fix"] for i in out["items"] if i["kind"] == "mechanical"}
        self.assertEqual(("paused", "parked"), (fixes["status"]["from"], fixes["status"]["to"]))
        self.assertEqual(("Freight", "Threads"), (fixes["list-thread"]["thread"], fixes["list-thread"]["section"]))
        self.assertEqual("260305 - Rate card.md", fixes["date"]["to"])               # the day it was first committed
        self.assertEqual(("260310-acme-kickoff", "260310-acme-start"), (fixes["relink"]["target"], fixes["relink"]["to"]))

    def test_a_wall_is_named_by_its_file_and_its_wall_never_its_material(self):
        _, out = self.run_tool("list")
        wall = self.by_path(out["items"], "Acme Review/Notes.md")[0]
        self.assertEqual("acme and birch", wall["wall"])
        self.assertEqual("", wall["message"])
        report = (self.root / out["report"]).read_text()
        for said in (json.dumps(out), report, wall["line"]):
            for word in ("Theo", "Marsh", "tender", "ninth"):
                self.assertNotIn(word, said)
        self.assertIn("Acme Review/Notes.md: the wall between acme and birch", report)

    def test_a_word_that_is_no_status_is_asked_not_fixed(self):
        write(self.pricing, thread_note("Acme Review", "Pricing", "acme", status="someday"))
        _, out = self.run_tool("list")
        item = self.by_path(out["items"], "Pricing/Pricing.md")[0]
        self.assertEqual("attribution", item["kind"])
        self.assertIn("is it active, parked or done?", item["question"])

    def test_a_meetings_question_with_no_zone_is_asked_as_attribution(self):
        write(self.wikis / "Meetings" / "questions" / "261015 - floor.md",
              "---\ntype: question\nasked: 2026-10-15\nstatus: open\nparties: [acme]\n---\n\n"
              "**Acme: which volume floor holds?**\n")
        _, out = self.run_tool("list")
        item = self.by_path(out["items"], "questions/261015 - floor.md")[0]
        self.assertEqual("attribution", item["kind"])
        self.assertEqual("Which zone does 261015 - floor belong to?", item["question"])

    def test_done_without_an_outcome_is_asked_not_fixed(self):
        text = thread_note("Acme Review", "Pricing", "acme", status="complete")
        write(self.pricing, text)
        _, out = self.run_tool("list")
        self.assertEqual("attribution", self.by_path(out["items"], "Pricing/Pricing.md")[0]["kind"])

    def test_a_scope_keeps_to_its_paths(self):
        _, out = self.run_tool("list", "--scope", "Wikis/Meetings")
        self.assertTrue(out["items"])
        self.assertTrue(all(i["path"].startswith("Wikis/Meetings/") for i in out["items"]), out["items"])
        _, out = self.run_tool("list", "--scope", "Zones/Work/Acme Review/Threads/Freight")
        self.assertEqual(["list-thread"], [i["fix"]["op"] for i in out["items"] if i["kind"] == "mechanical"])
        with contextlib.redirect_stderr(io.StringIO()):
            code = nurture.main(["list", "--root", str(self.root), "--scope", "Zones/Garden"])
        self.assertEqual(nurture.EXIT_USAGE, code)

    def test_said_aloud_in_one_sentence_or_two(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            nurture.main(["list", "--root", str(self.root), "--ear", "--today", "2026-10-17"])
        said = out.getvalue().strip()
        self.assertTrue(said.startswith("In the workspace:"), said)
        self.assertIn("one wall", said)
        self.assertIn("4 fixes ready", said)
        self.assertNotIn("/", said)


class ApplyTest(Base):
    def test_listing_and_planning_change_nothing(self):
        before = (self.log(self.work), self.log(self.wikis), git(self.work, "status", "--porcelain"))
        self.run_tool("list")
        self.run_tool("fix")
        self.assertEqual(before, (self.log(self.work), self.log(self.wikis), git(self.work, "status", "--porcelain")))
        self.assertIn("status: paused", self.pricing.read_text())

    def test_one_yes_applies_them_all_in_one_commit_per_repository_of_only_what_it_changed(self):
        work, wikis = self.log(self.work), self.log(self.wikis)
        code, out = self.run_tool("fix", "--yes")
        self.assertEqual(0, code, out)
        self.assertEqual(4, len(out["fixed"]), out["held"])
        self.assertEqual(len(work) + 1, len(self.log(self.work)))
        self.assertEqual(len(wikis) + 1, len(self.log(self.wikis)))
        changed = set(git(self.work, "show", "--no-renames", "--name-only", "--format=", "HEAD").split("\n")) - {""}
        self.assertEqual({"Acme Review/Acme Review.md", "Acme Review/Threads/Pricing/Pricing.md",
                          "Acme Review/Deliverables/Rate card.md", "Acme Review/Deliverables/260305 - Rate card.md"},
                         changed)
        self.assertEqual(["Meetings/wiki/sources/260320-follow-up.md"],
                         git(self.wikis, "show", "--name-only", "--format=", "HEAD").split())
        # Another session's work stays exactly as it was, uncommitted.
        status = git(self.work, "status", "--porcelain")
        self.assertTrue([l for l in status.splitlines() if l.startswith(" M") and "Birch Entry/Birch Entry.md" in l], status)
        self.assertIn("?? Scratch.md", status)
        self.assertEqual(2, len(status.strip().splitlines()), status)
        self.assertIn("Half a sentence being written", (self.work / "Birch Entry" / "Birch Entry.md").read_text())
        # And the fixes are what they said.
        self.assertIn("status: parked", self.pricing.read_text())
        hub = (self.acme / "Acme Review.md").read_text()
        self.assertIn("- [[Acme Review/Threads/Freight/Freight|Freight]]", hub.split("## Threads", 1)[1])
        self.assertIn("`Deliverables/260305 - Rate card.md`", hub)
        self.assertTrue((self.acme / "Deliverables" / "260305 - Rate card.md").is_file())
        self.assertIn("[[260310-acme-start]]", self.loose.read_text())
        self.assertIn("Work: context nurtured;", git(self.work, "log", "-1", "--format=%s"))

    def test_a_file_with_changes_not_committed_is_held_and_left_as_it_is(self):
        write(self.pricing, self.pricing.read_text() + "\nA line the other session is writing.\n")
        code, out = self.run_tool("fix", "--yes")
        self.assertEqual(0, code)
        held = self.by_path(out["held"], "Pricing/Pricing.md")
        self.assertEqual(1, len(held))
        self.assertIn("changes not committed", held[0]["held"])
        text = self.pricing.read_text()
        self.assertIn("status: paused", text)
        self.assertIn("A line the other session is writing.", text)
        self.assertIn("Pricing/Pricing.md", git(self.work, "status", "--porcelain"))
        self.assertNotIn("Pricing", git(self.work, "show", "--name-only", "--format=", "HEAD"))

    def test_a_commit_the_hook_refuses_is_put_back(self):
        hook = self.work / ".git" / "hooks" / "pre-commit"
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text("#!/bin/sh\necho 'a wall stands in the way' >&2\nexit 1\n")
        hook.chmod(0o755)
        before = self.log(self.work)
        code, out = self.run_tool("fix", "--yes")
        self.assertEqual(nurture.EXIT_FAILED, code)
        self.assertEqual(before, self.log(self.work))
        self.assertEqual(["Zones/Work"], [r["repo"] for r in out["refused"]])
        self.assertIn("status: paused", self.pricing.read_text())
        self.assertTrue((self.acme / "Deliverables" / "Rate card.md").is_file())
        self.assertFalse((self.acme / "Deliverables" / "260305 - Rate card.md").exists())
        self.assertEqual(2, len(git(self.work, "status", "--porcelain").strip().splitlines()))
        self.assertIn("[[260310-acme-start]]", self.loose.read_text())                # the wiki's went in

    def test_the_report_says_what_was_fixed_asked_and_left(self):
        _, out = self.run_tool("fix", "--yes")
        report = self.root / "System" / "generated" / "nurture" / "2026-10-17.md"
        self.assertEqual("System/generated/nurture/2026-10-17.md", out["report"])
        with contextlib.redirect_stdout(io.StringIO()):
            nurture.main(["answered", "--root", str(self.root), "--today", "2026-10-17",
                          "--path", "Wikis/Meetings/wiki/sources/260320-follow-up.md",
                          "--asked", "Which zone does 260320-follow-up belong to?", "--answer", "Work"])
        text = report.read_text()
        fixed = text.split("## Fixed", 1)[1].split("## Asked and answered", 1)[0]
        sha = git(self.work, "rev-parse", "--short", "HEAD").strip()
        self.assertIn("status paused is now parked (Work, %s)" % sha, fixed)
        asked = text.split("## Asked and answered", 1)[1].split("## Left", 1)[0]
        self.assertIn("Which zone does 260320-follow-up belong to? Answer: Work.", asked)
        left = text.split("## Left", 1)[1]
        self.assertIn("Walls, 1", left)
        self.assertNotIn("Which zone does 260320-follow-up", left)                   # answered, so no longer left
        self.assertEqual([], json.loads(report.with_suffix(".json").read_text())["failed"])


class RegistryTest(Base):
    def test_a_kind_plugs_in_and_waits_for_a_person_unless_it_says_otherwise(self):
        applied = []

        def claim(ctx, item):
            if item.source == "wiki-lint" and item.check == "orphan":
                item.fix, item.touches = {"op": "probe"}, [item.path]
                return True
            return False

        def apply(ctx, item, journal):
            applied.append(item.path)
            return "probed"

        nurture.register(nurture.Kind("probe", "Probe", 15, claim, what="a test's own", apply=apply))
        self.addCleanup(nurture.KINDS.pop, "probe")
        write(self.wikis / "Knowledge" / "wiki" / "concepts" / "alone.md", "# Alone\n")
        self.commit(self.wikis, "2026-03-06T10:00:00")
        _, out = self.run_tool("list")
        self.assertEqual("probe", self.by_path(out["items"], "concepts/alone.md")[0]["kind"])
        self.assertIn("probe", out["kinds"])
        _, out = self.run_tool("nightly")
        self.assertEqual([], applied)                       # not unattended: nobody watching, nothing applied
        self.assertTrue(out["fixed"])                       # while the mechanical kind went ahead
        _, out = self.run_tool("fix", "--yes")
        self.assertEqual(["Wikis/Knowledge/wiki/concepts/alone.md"], applied)

    def test_the_registration_point_is_documented(self):
        doc = nurture.__doc__
        for word in ("register()", "unattended", "claim(ctx, item)", "gather(ctx)", "apply(ctx, item,"):
            self.assertIn(word, doc)
        self.assertEqual(["wall", "mechanical", "correction", "attribution", "judgment", "behind", "fade"],
                         [k.name for k in nurture.ranked()])
        self.assertEqual(["mechanical"], [k.name for k in nurture.ranked() if k.unattended])


class LinkRulesTest(Base):
    """The two rules for notes the graph cannot place, with `parent-links`
    and `note-links` switched on for Work: a note path written as code
    becomes a wikilink when it leads to exactly one live note, and a note in a
    thread's folder with no `parent:` gets its thread's."""

    def setUp(self):
        super().setUp()
        write(self.root / "System" / "garrick-checks.json", json.dumps({"parent-links": ["Work"], "note-links": ["Work"]}))
        hub = self.acme / "Acme Review.md"
        hub.write_text(hub.read_text().replace("\nThe rates are in `Deliverables/Rate card.md`.\n", ""))
        threads = self.acme / "Threads"
        self.bench = write(threads / "Pricing" / "Benchmarks.md", "# Benchmarks\n")
        self.routes = write(threads / "Freight" / "Routes.md",
                            "---\ntitle: Routes\n---\n\n# Routes\n\nRates from `Pricing/Benchmarks.md`.\n\n"
                            "```\n`Pricing/Benchmarks.md`\n```\n")
        brief = '---\nparent: "[[%s]]"\n---\n# Brief\n'
        write(threads / "Pricing" / "Brief.md", brief % "Pricing")
        write(self.work / "Birch Entry" / "Threads" / "Market Sizing" / "Brief.md", brief % "Market Sizing")
        self.pricing.write_text(self.pricing.read_text() + "\nSee `Brief.md`.\n")             # two notes: a question
        self.ledger = write(threads / "Pricing" / "Deliverables" / "published.md",
                            "| Date | File | Destination | Recipients | Authoritative |\n|---|---|---|---|---|\n")
        self.source = write(threads / "Pricing" / "Sources" / "Tender notes.md", "# Tender notes, as received\n")
        git(self.work, "add", "-A", "--", ".", ":!Scratch.md", ":!Birch Entry/Birch Entry.md")
        git(self.work, "-c", "core.hooksPath=" + os.devnull, "commit", "-q", "-m", "notes")

    def mechanical(self, items):
        return {(i["path"].split("Acme Review/", 1)[-1], i["fix"]["op"]): i["fix"] for i in items if i["kind"] == "mechanical"}

    def test_each_rule_takes_only_the_one_right_answer(self):
        _, out = self.run_tool("list")
        fixes = self.mechanical(out["items"])
        self.assertEqual("Pricing", fixes[("Threads/Pricing/Benchmarks.md", "parent")]["thread"])
        self.assertEqual("Freight", fixes[("Threads/Freight/Routes.md", "parent")]["thread"])
        self.assertEqual("Pricing/Benchmarks.md", fixes[("Threads/Freight/Routes.md", "codelink")]["ref"])
        self.assertEqual({"Threads/Pricing/Benchmarks.md", "Threads/Freight/Routes.md"},
                         {path for path, op in fixes if op in ("parent", "codelink")})
        judged = {i["path"].split("Acme Review/", 1)[-1] for i in out["items"] if i["kind"] == "judgment"}
        for left in ("Notes.md",                                  # the project's own level: the hub's, or a thread's
                     "Threads/Pricing/Pricing.md",                # a thread note: its parent is the hub; and Brief.md is two notes
                     "Threads/Pricing/Sources/Tender notes.md",   # as received
                     "Deliverables/Rate card.md"):
            self.assertIn(left, judged)
        self.assertFalse([i for i in out["items"] if i["path"].endswith("Pricing/Deliverables/published.md")
                          and i["kind"] == "mechanical"])
        said = [i["line"] for i in out["items"] if i["kind"] == "mechanical" and i["fix"]["op"] in ("parent", "codelink")]
        self.assertIn('Zones/Work/Acme Review/Threads/Pricing/Benchmarks.md: add parent: "[[Pricing]]"', said)
        self.assertIn("Zones/Work/Acme Review/Threads/Freight/Routes.md: `Pricing/Benchmarks.md` becomes "
                      "[[Pricing/Benchmarks.md]]", said)

    def test_one_yes_applies_them_in_one_commit_of_only_the_files_they_touch(self):
        ledger, source = self.ledger.read_text(), self.source.read_text()
        before = len(self.log(self.work))
        code, out = self.run_tool("fix", "--yes")
        self.assertEqual(0, code, out)
        self.assertEqual(before + 1, len(self.log(self.work)))
        changed = set(git(self.work, "show", "--no-renames", "--name-only", "--format=", "HEAD").split("\n")) - {""}
        self.assertIn("Acme Review/Threads/Pricing/Benchmarks.md", changed)
        self.assertIn("Acme Review/Threads/Freight/Routes.md", changed)
        self.assertNotIn("Acme Review/Threads/Pricing/Deliverables/published.md", changed)
        self.assertEqual('---\nparent: "[[Pricing]]"\n---\n# Benchmarks\n', self.bench.read_text())
        self.assertEqual('---\ntitle: Routes\nparent: "[[Freight]]"\n---\n\n# Routes\n\nRates from [[Pricing/Benchmarks.md]].\n\n'
                         "```\n`Pricing/Benchmarks.md`\n```\n", self.routes.read_text())   # a fenced block stays as written
        self.assertEqual((ledger, source), (self.ledger.read_text(), self.source.read_text()))
        self.assertIn("See `Brief.md`.", self.pricing.read_text())
        subject = git(self.work, "log", "-1", "--format=%s")
        self.assertIn("2 parent links", subject)
        self.assertIn("1 path made a link", subject)
        self.assertEqual(2, len(git(self.work, "status", "--porcelain").strip().splitlines()))  # the other session's two
        _, out = self.run_tool("list")
        self.assertFalse([i for i in out["items"] if i["path"].endswith(("Benchmarks.md", "Routes.md"))])

    def test_a_note_with_changes_not_committed_is_held(self):
        self.bench.write_text("# Benchmarks\n\nA row the other session is adding.\n")
        code, out = self.run_tool("fix", "--yes")
        self.assertEqual(0, code)
        held = self.by_path(out["held"], "Pricing/Benchmarks.md")
        self.assertIn("changes not committed", held[0]["held"])
        self.assertEqual("# Benchmarks\n\nA row the other session is adding.\n", self.bench.read_text())
        self.assertIn('parent: "[[Freight]]"', self.routes.read_text())

    def test_a_thread_name_another_note_shares_is_a_question(self):
        write(self.wikis / "Knowledge" / "wiki" / "concepts" / "freight.md", "# Freight\n")
        _, out = self.run_tool("list")
        self.assertNotIn(("Threads/Freight/Routes.md", "parent"), self.mechanical(out["items"]))
        self.assertIn(("Threads/Pricing/Benchmarks.md", "parent"), self.mechanical(out["items"]))

    def test_the_night_applies_them_too(self):
        code, out = self.run_tool("nightly")
        self.assertEqual(0, code, out)
        self.assertEqual({"codelink", "parent"}, {i["fix"]["op"] for i in out["fixed"]} & {"codelink", "parent"})
        self.assertIn("parent link", out["digest"])


class CorrectionTest(Base):
    """A correction the user gives enters Nurture as one finding, and goes in
    through correct.py's own find and apply: one implementation, two callers."""

    OLD, NEW = "acme-corp.example", "acmecorp.example"

    def setUp(self):
        super().setUp()
        hub = self.acme / "Acme Review.md"
        hub.write_text(hub.read_text() + "\nMail goes to orders@acme-corp.example.\n")
        freight = self.acme / "Threads" / "Freight" / "Freight.md"
        freight.write_text(freight.read_text() + "\nThe portal is portal.acme-corp.example.\n")
        todo = self.work / "Todo.md"
        todo.write_text(todo.read_text().replace("## Inbox\n", "## Inbox\n\n- [ ] [[Acme Review/Threads/Pricing/Pricing|Pricing]]"
                                                 " send the sheet to acme-corp.example\n"))
        birch = self.work / "Birch Entry" / "Threads" / "Market Sizing" / "Market Sizing.md"
        birch.write_text(birch.read_text() + "\nTheo Marsh benchmarked acme-corp.example.\n")
        self.birch_note = birch
        self.raw = self.wikis / "Meetings" / "raw" / "260310-acme-kickoff.txt"
        self.raw.write_text("Dana: write to acme-corp.example.\n")
        self.page = self.wikis / "Meetings" / "wiki" / "sources" / "260310-acme-start.md"
        self.page.write_text(self.page.read_text() + "\nRecord: [[raw/260310-acme-kickoff]]. Domain acme-corp.example.\n")
        # Commit all but the other session's two files, which stay as they were.
        for repo in (self.work, self.wikis):
            git(repo, "add", "-A", "--", ".", ":!Scratch.md", ":!Birch Entry/Birch Entry.md")
            git(repo, "-c", "core.hooksPath=" + os.devnull, "commit", "-q", "-m", "values")
        self.raw_before = self.raw.read_bytes()

    def find_hits(self):
        sys.path.insert(0, str(TOOLS))
        self.addCleanup(sys.path.remove, str(TOOLS))
        import correct
        return correct.find_hits(self.root, self.OLD, self.NEW)

    def test_it_lists_every_hit_correct_finds_as_one_finding_and_changes_nothing(self):
        found = {h.path.resolve().relative_to(self.root).as_posix() for h in self.find_hits()}
        self.assertEqual(6, len(found))                     # five live files and the raw record
        before = (self.log(self.work), self.log(self.wikis), git(self.work, "status", "--porcelain"))
        code, out = self.run_tool("correct", "--old", self.OLD, "--new", self.NEW)
        self.assertEqual(0, code)
        self.assertEqual(found, {h["path"] for h in out["hits"]})
        self.assertEqual("correction", out["item"]["kind"])
        self.assertEqual(sorted(found), sorted(out["item"]["where"]))
        self.assertEqual(["Wikis/Meetings/raw/260310-acme-kickoff.txt"], out["item"]["fix"]["raw"])
        self.assertTrue(out["item"]["line"].startswith('Correct "acme-corp.example" to "acmecorp.example": 5 files'),
                        out["item"]["line"])
        self.assertEqual(before, (self.log(self.work), self.log(self.wikis), git(self.work, "status", "--porcelain")))
        left = (self.root / out["report"]).read_text().split("## Left", 1)[1]
        self.assertIn("Corrections, 1", left)

    def test_one_yes_applies_them_in_one_commit_per_repository_of_only_what_it_touched(self):
        work, wikis = self.log(self.work), self.log(self.wikis)
        code, out = self.run_tool("correct", "--old", self.OLD, "--new", self.NEW, "--yes", "--why", "no hyphen")
        self.assertEqual(0, code, out)
        self.assertEqual(len(work) + 1, len(self.log(self.work)))
        self.assertEqual(len(wikis) + 1, len(self.log(self.wikis)))
        self.assertEqual({"Zones/Work", "Wikis"}, {r for r, _ in out["commits"]})
        self.assertEqual({"Acme Review/Acme Review.md", "Acme Review/Threads/Freight/Freight.md", "Todo.md",
                          "Birch Entry/Threads/Market Sizing/Market Sizing.md"},
                         set(git(self.work, "show", "--name-only", "--format=", "HEAD").split("\n")) - {""})
        self.assertEqual(["Meetings/wiki/sources/260310-acme-start.md"],
                         git(self.wikis, "show", "--name-only", "--format=", "HEAD").split())
        self.assertIn('Correct "acme-corp.example" to "acmecorp.example"', git(self.work, "log", "-1", "--format=%B"))
        for f in (self.acme / "Acme Review.md", self.work / "Todo.md", self.page):
            self.assertIn(self.NEW, f.read_text())
            self.assertNotIn(self.OLD, f.read_text())
        # The raw record is the record: untouched. The page resting on it says so.
        self.assertEqual(self.raw_before, self.raw.read_bytes())
        self.assertIn("superseded:", self.page.read_text())
        # Another session's work stays exactly as it was, uncommitted.
        status = git(self.work, "status", "--porcelain")
        self.assertEqual(2, len(status.strip().splitlines()), status)
        self.assertTrue([l for l in status.splitlines() if l.startswith(" M") and "Birch Entry/Birch Entry.md" in l], status)
        self.assertIn("?? Scratch.md", status)
        # The report says what was fixed, and the yes.
        text = (self.root / out["report"]).read_text()
        fixed = text.split("## Fixed", 1)[1].split("## Asked and answered", 1)[0]
        self.assertIn('"acme-corp.example" is now "acmecorp.example" in Zones/Work/Acme Review/Acme Review.md', fixed)
        self.assertIn(git(self.work, "rev-parse", "--short", "HEAD").strip(), fixed)
        asked = text.split("## Asked and answered", 1)[1].split("## Left", 1)[0]
        self.assertIn('Correct "acme-corp.example" to "acmecorp.example" in 5 files? Answer: yes, no hyphen.', asked)
        self.assertNotIn("Corrections", text.split("## Left", 1)[1])

    def test_a_file_with_changes_not_committed_is_held(self):
        self.birch_note.write_text(self.birch_note.read_text() + "\nHalf a line.\n")
        code, out = self.run_tool("correct", "--old", self.OLD, "--new", self.NEW, "--yes")
        self.assertEqual(0, code)
        self.assertEqual(["Zones/Work/Birch Entry/Threads/Market Sizing/Market Sizing.md"],
                         [i["path"] for i in out["held"]])
        self.assertIn(self.OLD, self.birch_note.read_text())
        self.assertIn("Half a line.", self.birch_note.read_text())
        self.assertNotIn("Market Sizing", git(self.work, "show", "--name-only", "--format=", "HEAD"))
        self.assertNotIn(self.OLD, (self.acme / "Acme Review.md").read_text())

    def test_a_scope_stops_at_its_walls_and_says_only_the_rules_sentence(self):
        # A raw record no page rests on: nobody can tell whose it is, so a scope leaves it out too.
        orphan = self.wikis / "Meetings" / "raw" / "260401-unfiled.txt"
        orphan.write_text("Someone mentioned acme-corp.example.\n")
        sentence = nurture.WALL_REFUSAL
        scope = ["--scope", "Zones/Work/Acme Review"]
        said = {}
        for form in ("--ear", "text"):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
                nurture.main(["correct", "--root", str(self.root), "--old", self.OLD, "--new", self.NEW, "--today",
                              "2026-10-17"] + scope + ([form] if form != "text" else []))
            said[form] = buf.getvalue()
        code, out = self.run_tool("correct", "--old", self.OLD, "--new", self.NEW, *scope)
        said["json"] = json.dumps(out)
        code, out = self.run_tool("correct", "--old", self.OLD, "--new", self.NEW, "--yes", *scope)
        self.assertEqual(0, code)
        said["json --yes"] = json.dumps(out)
        self.assertEqual(sentence, out["refusal"])
        for form, text in said.items():
            self.assertEqual(1, text.count(sentence), form)
            rest = text.replace(sentence, "").replace('"wall": ""', "").lower()     # every item's empty field
            for word in ("market sizing", "birch", "theo", "marsh", "benchmarked", "260401", "unfiled", "wall",
                         "held back", "more"):
                self.assertNotIn(word, rest, form)
        report = (self.root / out["report"]).read_text().lower()
        for word in ("market sizing", "birch", "theo", "marsh", "benchmarked", "260401", "unfiled", "wall"):
            self.assertNotIn(word, report)
        # What is behind the wall, and the record nobody can place, are left exactly as they were.
        self.assertIn(self.OLD, self.birch_note.read_text())
        self.assertNotIn("Market Sizing", git(self.work, "show", "--name-only", "--format=", "HEAD"))
        self.assertEqual("Someone mentioned acme-corp.example.\n", orphan.read_text())
        self.assertNotIn(self.OLD, (self.acme / "Acme Review.md").read_text())   # this side's copies went in
        # With no scope, nothing is held back and no sentence is said.
        code, out = self.run_tool("correct", "--old", self.OLD, "--new", self.NEW)
        self.assertNotIn("refusal", out)
        self.assertIn("Zones/Work/Birch Entry/Threads/Market Sizing/Market Sizing.md", [h["path"] for h in out["hits"]])

    def test_never_with_nobody_watching(self):
        self.run_tool("correct", "--old", self.OLD, "--new", self.NEW)              # listed, so it waits in the record
        before = self.log(self.work)
        _, out = self.run_tool("nightly")
        self.assertTrue(out["fixed"])                                                # the mechanical kind went ahead
        self.assertNotIn("correction", {i["kind"] for i in out["fixed"]})
        for sha in set(self.log(self.work)) - set(before):
            self.assertNotIn("Correct", git(self.work, "log", "-1", "--format=%s", sha))
        self.assertIn(self.OLD, (self.acme / "Acme Review.md").read_text())
        self.assertIn(self.OLD, self.page.read_text())
        self.assertFalse(nurture.KINDS["correction"].unattended)
        self.assertIsNone(nurture.KINDS["correction"].apply)
        err = io.StringIO()
        with mock.patch.dict(os.environ, {"GARRICK_HEADLESS": "1"}), contextlib.redirect_stderr(err), \
                contextlib.redirect_stdout(io.StringIO()):
            code = nurture.main(["correct", "--root", str(self.root), "--old", self.OLD, "--new", self.NEW, "--yes"])
        self.assertEqual(nurture.EXIT_USAGE, code)
        self.assertIn("nobody watching", err.getvalue())
        self.assertIn(self.OLD, (self.acme / "Acme Review.md").read_text())
        self.assertEqual(self.raw_before, self.raw.read_bytes())

    def test_said_aloud(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            nurture.main(["correct", "--root", str(self.root), "--old", self.OLD, "--new", self.NEW, "--ear",
                          "--today", "2026-10-17"])
        self.assertEqual("5 places have the old value. Correct them all?", out.getvalue().strip())


class DebtTest(Base):
    """Context debt (#69): what is left after a run, weighed by kind, kept in
    the day's record by kind and by scope."""

    def weighed(self, items, weights=None):
        weights = weights or nurture.WEIGHTS
        return sum(weights.get(i["kind"], nurture.UNKNOWN_WEIGHT) for i in items)

    def test_the_debt_is_the_weight_of_what_is_left(self):
        _, out = self.run_tool("list")
        debt = out["debt"]
        self.assertEqual(self.weighed(out["items"]), debt["total"])
        self.assertTrue(debt["whole"])
        self.assertEqual(40, debt["threshold"])
        self.assertEqual(10, debt["kinds"]["wall"])                          # one wall, ten
        self.assertEqual(5, debt["kinds"]["attribution"])                    # one meeting page with no zone
        self.assertEqual({"Zones/Work", "Wikis/Meetings", "System"}, set(debt["scopes"]))
        self.assertEqual(10, debt["scopes"]["Zones/Work"]["wall"])
        self.assertEqual(debt["total"], sum(sum(k.values()) for k in debt["scopes"].values()))
        rec = json.loads((self.root / "System" / "generated" / "nurture" / "2026-10-17.json").read_text())
        self.assertEqual(debt, rec["debt"])
        self.assertEqual(len(out["items"]), len(rec["standing"]))
        for word in ("Theo", "tender"):                                      # a wall is weighed, never quoted
            self.assertNotIn(word, json.dumps(rec["standing"]))
        report = (self.root / out["report"]).read_text()
        self.assertIn("Context debt: %d (wall 10, attribution 5" % debt["total"], report)

    def test_a_mechanical_finding_counts_only_while_it_is_not_fixed(self):
        _, before = self.run_tool("list")
        _, out = self.run_tool("fix", "--yes")
        self.assertTrue(out["fixed"])
        left = before["debt"]["kinds"]["mechanical"] - len(out["fixed"])
        self.assertEqual(left, out["debt"]["kinds"].get("mechanical", 0))
        self.assertEqual(before["debt"]["total"] - len(out["fixed"]), out["debt"]["total"])
        self.assertEqual("", out["debt_line"])                              # 17, under the threshold, no history

    def test_the_weights_and_the_threshold_are_settings(self):
        write(self.root / "System" / "garrick-checks.json",
              json.dumps({"nurture-weights": {"judgment": 0, "wall": 20, "mechanical": "lots"}, "nurture-threshold": 25}))
        _, out = self.run_tool("list")
        weights = dict(nurture.WEIGHTS, judgment=0, wall=20)
        self.assertEqual(self.weighed(out["items"], weights), out["debt"]["total"])
        self.assertNotIn("judgment", out["debt"]["kinds"])                  # weighs nothing, so not listed
        self.assertEqual(4, out["debt"]["kinds"]["mechanical"])             # not a number: left as shipped
        self.assertEqual(25, out["debt"]["threshold"])

    def test_a_scoped_run_replaces_only_its_scope(self):
        _, whole = self.run_tool("list")
        _, out = self.run_tool("fix", "--yes", "--scope", "Wikis/Meetings")
        self.assertTrue(out["debt"]["whole"])
        self.assertEqual(whole["debt"]["scopes"]["Zones/Work"], out["debt"]["scopes"]["Zones/Work"])
        self.assertNotIn("mechanical", out["debt"]["scopes"]["Wikis/Meetings"])
        self.assertEqual(whole["debt"]["total"] - 1, out["debt"]["total"])

    def test_a_scoped_first_run_carries_what_stood_before_it(self):
        _, whole = self.run_tool("list")
        folder = self.root / "System" / "generated" / "nurture"
        os.rename(str(folder / "2026-10-17.json"), str(folder / "2026-10-15.json"))
        _, out = self.run_tool("list", "--scope", "Wikis/Meetings")
        self.assertEqual(whole["debt"], out["debt"])                         # nothing changed in between
        self.assertTrue(out["debt"]["whole"])
        shutil.rmtree(str(folder))
        _, out = self.run_tool("list", "--scope", "Wikis/Meetings")
        self.assertFalse(out["debt"]["whole"])                               # only a part seen: never read as the whole
        self.assertEqual({"Wikis/Meetings"}, set(out["debt"]["scopes"]))

    def test_an_answer_takes_its_question_off_the_debt(self):
        _, out = self.run_tool("list")
        page = self.by_path(out["items"], "260320-follow-up.md")[0]["path"]
        with contextlib.redirect_stdout(io.StringIO()):
            nurture.main(["answered", "--path", page, "--asked", "Which zone?", "--answer", "Work",
                          "--root", str(self.root), "--today", "2026-10-17"])
        rec = json.loads((self.root / "System" / "generated" / "nurture" / "2026-10-17.json").read_text())
        self.assertEqual(out["debt"]["total"] - 5, rec["debt"]["total"])
        self.assertNotIn("attribution", rec["debt"]["kinds"])


class DebtLineTest(unittest.TestCase):
    """The morning's debt line, from the records alone (#69)."""

    TODAY = nurture.datetime.date(2026, 10, 22)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.folder = self.root / "System" / "generated" / "nurture"
        self.folder.mkdir(parents=True)

    def debt(self, total, scopes=None, whole=True, threshold=40):
        scopes = scopes or {"Wikis/Meetings": {"attribution": total}}
        kinds = {}
        for ks in scopes.values():
            for k, v in ks.items():
                kinds[k] = kinds.get(k, 0) + v
        return {"total": total, "kinds": kinds, "scopes": scopes, "whole": whole, "threshold": threshold}

    def days(self, totals, **kw):
        """A record a day, the last of `totals` today's; None leaves a day out."""
        for back, total in enumerate(reversed(totals)):
            if total is None:
                continue
            day = self.TODAY - nurture.datetime.timedelta(days=back)
            write(self.folder / ("%s.json" % day.isoformat()), json.dumps({"date": day.isoformat(), "debt": self.debt(total, **kw)}))
        return self.debt(totals[-1], **kw)

    def line(self, debt):
        return nurture.debt_line(self.root, self.TODAY, debt)

    def test_over_the_threshold(self):
        debt = self.days([18, 20, 25, 22, 30, 35, 40, 42],
                         scopes={"Wikis/Meetings": {"attribution": 25, "judgment": 3}, "Zones/Work": {"wall": 10, "judgment": 4}})
        self.assertEqual('Context debt 42, up from 18 last week, mostly attribution in the Meetings wiki. '
                         'Say "nurture the meetings".', self.line(debt))

    def test_rising_for_a_week_under_the_threshold(self):
        debt = self.days([10, 12, 12, 13, 15, 16, 20], scopes={"Zones/Work": {"judgment": 20}})
        self.assertEqual('Context debt 20, up from 10 last week, mostly judgment in Work. Say "nurture Work".', self.line(debt))

    def test_not_rising_without_seven_days_or_with_a_fall(self):
        self.assertEqual("", self.line(self.days([10, 12, None, 13, 15, 16, 20])))
        shutil.rmtree(str(self.folder))
        self.folder.mkdir(parents=True)
        self.assertEqual("", self.line(self.days([10, 12, 11, 13, 15, 16, 20])))
        shutil.rmtree(str(self.folder))
        self.folder.mkdir(parents=True)
        self.assertEqual("", self.line(self.days([12, 12, 12, 12, 12, 12, 12])))       # level is not rising

    def test_quiet_under_the_threshold_and_for_a_part(self):
        self.assertEqual("", self.line(self.days([30])))
        self.assertEqual("", self.line(self.debt(90, whole=False)))
        self.assertEqual("", self.line(None))
        self.assertTrue(self.line(self.debt(41)).startswith("Context debt 41, mostly"))   # no week behind it

    def test_the_scope_names_the_request(self):
        for scope, said in (("Wikis/Knowledge", 'in the Knowledge wiki. Say "nurture the library".'),
                            ("System", 'in System. Say "nurture the context".'),
                            ("Zones/Personal", 'in Personal. Say "nurture Personal".')):
            self.assertTrue(self.line(self.debt(50, scopes={scope: {"wall": 50}})).endswith("mostly walls " + said))

    def test_the_history_reads_only_whole_records(self):
        self.days([5, 6, 7])
        write(self.folder / "2026-10-19.json", json.dumps({"debt": self.debt(99, whole=False)}))
        write(self.folder / "2026-10-18.json", "not json")
        got = nurture.debt_history(self.root, self.TODAY, 30)
        self.assertEqual([5, 6, 7], [d["total"] for _, d in got])
        self.assertEqual(self.TODAY, got[-1][0])


class NightlyTest(Base):
    def setUp(self):
        super().setUp()
        shutil.copytree(str(TOOLS), str(self.root / "System" / "tools"),
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        self.notices = Path(self._tmp.name) / "notices.txt"
        notifier = Path(self._tmp.name) / "notify.sh"
        notifier.write_text('printf "%s|%s\\n---\\n" "$GARRICK_NOTIFY_KIND" "$2" >> "' + str(self.notices) + '"\n')
        patch = mock.patch.dict(os.environ, {"GARRICK_NOTIFY_CMD": "/bin/sh %s" % notifier,
                                             "GARRICK_JOBS_DIR": str(Path(self._tmp.name) / "jobs")})
        patch.start()
        self.addCleanup(patch.stop)
        sys.path.insert(0, str(JOBS))
        self.addCleanup(sys.path.remove, str(JOBS))
        self.job = load("garrick_nurture_sweep", JOBS / "nurture_sweep.py")

    def test_the_night_applies_the_mechanical_kind_and_says_what_it_fixed(self):
        meeting = self.loose.read_text()
        notes = (self.acme / "Notes.md").read_text()
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = self.job.main(["--workspace", str(self.root), "--digest"])
        self.assertEqual(0, code, out.getvalue())
        self.assertIn("status: parked", self.pricing.read_text())
        self.assertIn("Work: context nurtured;", git(self.work, "log", "-1", "--format=%s"))
        # Attribution and walls never change with nobody watching.
        self.assertIn("[[260310-acme-start]]", self.loose.read_text())
        self.assertNotIn("zone:", self.loose.read_text().split("---")[1])
        self.assertEqual(meeting.replace("[[260310-acme-kickoff]]", "[[260310-acme-start]]"), self.loose.read_text())
        self.assertEqual(notes, (self.acme / "Notes.md").read_text())
        self.assertEqual(2, len(git(self.work, "status", "--porcelain").strip().splitlines()))
        notice = self.notices.read_text()
        self.assertTrue(notice.startswith("digest|Fixed 4 overnight (Wikis 1, Work 3):"), notice)
        self.assertIn("1 status word", notice)
        self.assertIn("Waiting for you: one wall", notice)
        for word in ("Theo", "tender"):
            self.assertNotIn(word, notice)
        report = (self.root / "System" / "generated" / "nurture").glob("*.md")
        self.assertIn("nobody watching", next(report).read_text())

    def test_headless_reads_the_drift_it_last_saved(self):
        write(self.root / "System" / "generated" / "drift.json", json.dumps({"checked": "2026-10-16T22:00:00", "files": [
            {"zone": "Work", "project": "Acme Review", "file": "260301 - Pricing memo.md", "state": "drifted",
             "say": "the bytes differ"}]}))
        _, out = self.run_tool("nightly")
        drift = [i for i in out["items"] if i["source"] == "drift"]
        self.assertEqual(1, len(drift))
        self.assertEqual("judgment", drift[0]["kind"])

    def test_a_copy_behind_the_share_is_listed_apart_and_never_in_the_morning_line(self):
        write(self.root / "System" / "generated" / "drift.json", json.dumps({"checked": "2026-10-16T22:00:00", "files": [
            {"zone": "Work", "project": "Acme Review", "file": "260301 - Pricing memo.md", "state": "drifted",
             "authoritative": "here", "say": "the bytes differ"},
            {"zone": "Work", "project": "Acme Review", "file": "260302 - Terms.docx", "state": "behind",
             "authoritative": "share", "say": "the project's copy is behind the share: word/document.xml differs"}]}))
        _, out = self.run_tool("nightly")
        drift = {i["check"]: i for i in out["items"] if i["source"] == "drift"}
        self.assertEqual(("judgment", "behind"), (drift["drifted"]["kind"], drift["behind"]["kind"]))
        self.assertEqual("A published file's copy here is behind the share", drift["behind"]["ear"])
        self.assertEqual(1, out["kinds"]["behind"])
        self.assertNotIn("behind", out["digest"])
        report = (self.root / out["report"]).read_text()
        judged, behind = report.split("Judgment, ", 1)[1].split("Behind the share, 1: ", 1)
        self.assertIn("260301 - Pricing memo.md", judged)
        self.assertNotIn("260302 - Terms.docx", judged)
        self.assertIn("260302 - Terms.docx: behind (the project's copy is behind the share", behind)
        # A night that finds only a copy behind the share leaves nothing waiting, so the job sends nothing.
        write(self.root / "System" / "generated" / "drift.json", json.dumps({"files": [
            {"zone": "Work", "project": "Acme Review", "file": "260302 - Terms.docx", "state": "behind"}]}))
        with mock.patch.object(nurture, "SOURCES", [nurture.from_drift]):
            _, out = self.run_tool("nightly")
        self.assertEqual((0, ["behind"]), (out["waiting"], [i["kind"] for i in out["items"] if i["kind"] != "fade"]))
        self.assertEqual("Nothing needed fixing overnight.", out["digest"])

    def test_the_debt_line_joins_the_digest_and_a_wall_is_said_whatever_the_total(self):
        write(self.root / "System" / "garrick-checks.json", json.dumps({"nurture-threshold": 1000}))
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.job.main(["--workspace", str(self.root), "--digest"])
        notice = self.notices.read_text()
        self.assertIn("Waiting for you: one wall", notice)                    # far under the threshold, still said
        self.assertNotIn("Context debt", notice)
        self.notices.unlink()
        write(self.root / "System" / "garrick-checks.json", json.dumps({"nurture-threshold": 5}))
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.job.main(["--workspace", str(self.root), "--digest"])
        notice = self.notices.read_text()
        self.assertIn("Waiting for you: one wall", notice)
        self.assertRegex(notice, r'\nContext debt \d+, mostly walls in Work\. Say "nurture Work"\.')
        for word in ("Theo", "tender"):
            self.assertNotIn(word, notice)

    def test_pages_that_would_fade_get_a_line_of_their_own_and_never_move(self):
        _, out = self.run_tool("nightly")
        fading = [i for i in out["items"] if i["kind"] == "fade"]
        self.assertEqual(["Wikis/Meetings/wiki"], [i["path"] for i in fading])
        self.assertEqual("", out["fade"])                    # fewer than the setting's ten
        write(self.root / "System" / "garrick-settings.json", json.dumps({"memory": {"nightly": {"min": 2}}}))
        _, out = self.run_tool("nightly")
        self.assertRegex(out["fade"], r'^\d+ meeting pages would go dormant\. Say "fade the meetings"\.$')
        self.assertTrue(out["digest"].endswith("\n" + out["fade"]))
        self.assertEqual(0, out["kinds"]["fade"] - 1)
        self.assertTrue((self.wikis / "Meetings" / "wiki" / "sources" / "260312-birch-kickoff.md").exists())
        self.assertFalse((self.wikis / "Meetings" / "dormant").exists())
        write(self.root / "System" / "garrick-settings.json", json.dumps({"memory": {"nightly": {"on": False, "min": 2}}}))
        _, out = self.run_tool("nightly")
        self.assertEqual("", out["fade"])

    def test_a_workspace_without_the_tool_is_refused(self):
        os.remove(str(self.root / "System" / "tools" / "nurture.py"))
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.job.EXIT_USAGE, self.job.main(["--workspace", str(self.root)]))

    def test_the_launchd_example_runs_it_through_job_py_with_no_assistant(self):
        plist = plistlib.loads((JOBS / "launchd" / "garrick.nurture.plist").read_bytes())
        args = plist["ProgramArguments"]
        self.assertEqual("garrick.nurture", plist["Label"])
        self.assertEqual(["/usr/bin/python3", "/Users/<you>/Garrick/System/jobs/job.py", "nurture"], args[:3])
        self.assertNotIn("--agent", args)
        self.assertIn("/Users/<you>/Garrick/System/jobs/nurture_sweep.py", args)
        self.assertIn("--digest", args)
        self.assertEqual({"Hour": 5, "Minute": 15}, plist["StartCalendarInterval"])
        r = subprocess.run([sys.executable, str(JOBS / "job.py"), "check-scripts", str(JOBS / "nurture_sweep.py")],
                           capture_output=True, text=True)
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)


class DocsTest(unittest.TestCase):
    def test_the_docs_say_the_night_applies_the_mechanical_kind(self):
        jobs = (REPO / "docs" / "extras" / "scheduled-jobs.md").read_text(encoding="utf-8")
        self.assertIn("### Nurturing the context each night", jobs)
        self.assertIn("`nurture_sweep.py`, `launchd/garrick.nurture.plist`", jobs)
        self.assertIn("never change overnight", jobs)
        commands = (REPO / "docs" / "commands.md").read_text(encoding="utf-8")
        self.assertIn("## Nurturing the context", commands)
        for phrase in ("nurture the context", "nurture Work", "nurture Acme", "nurture the meetings"):
            self.assertIn(phrase, (REPO / "template" / "System" / "skills" / "nurture" / "SKILL.md").read_text())


if __name__ == "__main__":
    unittest.main()
