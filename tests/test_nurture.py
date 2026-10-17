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
            self.assertIn(item["kind"], ("wall", "mechanical", "attribution", "judgment"))
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
        self.assertEqual(["wall", "mechanical", "attribution", "judgment"], [k.name for k in nurture.ranked()])
        self.assertEqual(["mechanical"], [k.name for k in nurture.ranked() if k.unattended])


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
