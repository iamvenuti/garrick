"""Graded oblivion: System/tools/fade.py, against small synthetic workspaces.

    python3 -m unittest discover -s tests -p test_fade.py

Pages fade by age, kind and use, into dormant/ and archive/ inside their
wiki, and wake when linked again. Nothing moves without a written proposal
and a yes on it; every move is a rename, and every link into the page, from
both wikis and every zone, follows it.
"""

from __future__ import annotations

import contextlib
import datetime
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import GIT_ENV, HAVE_GIT, build_workspace, git, meeting_page, thread_note, write  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "template" / "System" / "tools"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod                      # dataclasses look their module up by name
    spec.loader.exec_module(mod)
    return mod


fade = load("garrick_fade", TOOLS / "fade.py")

TODAY = datetime.date(2027, 6, 1)


def meeting(title: str, date: str, parties: str = "[acme]", body: str = "Decisions.", more: str = "") -> str:
    text = meeting_page("Work", parties, title).replace("date: 2026-03-10", "date: %s%s" % (date, more))
    return text.replace("Decisions.", body)


class SettingsTest(unittest.TestCase):
    def test_the_defaults_are_the_issues(self):
        d = fade.DEFAULTS
        self.assertEqual((6, 18), (d["kinds"]["meetings"]["dormant"], d["kinds"]["meetings"]["archived"]))
        self.assertEqual((3, 12), (d["kinds"]["newsletters"]["dormant"], d["kinds"]["newsletters"]["archived"]))
        self.assertEqual((24, None), (d["kinds"]["reports"]["dormant"], d["kinds"]["reports"]["archived"]))
        self.assertEqual({"Meetings": True, "Knowledge": True}, d["wikis"])
        self.assertEqual({"thread": True, "project": True, "todo": True, "pinned": True}, d["pins"])
        self.assertEqual((True, "dormant", {"on": True, "min": 10}), (d["wake"], d["reach"], d["nightly"]))

    def test_stored_settings_are_laid_over_the_defaults_and_what_does_not_read_is_ignored(self):
        s = fade.merged({"kinds": {"meetings": {"dormant": 3, "archived": "soon"},
                                   "contracts": {"wiki": "Knowledge", "types": ["Contract"], "dormant": 60,
                                                 "archived": None},
                                   "reports": None,
                                   "nowhere": {"types": ["x"]}},
                         "wikis": {"Knowledge": False, "Other": True},
                         "pins": {"todo": False, "thread": "no"},
                         "reach": "everything", "wake": False, "nightly": {"min": 4}})
        self.assertEqual((3, 18), (s["kinds"]["meetings"]["dormant"], s["kinds"]["meetings"]["archived"]))
        self.assertEqual({"wiki": "Knowledge", "types": ["contract"], "domains": [], "dormant": 60, "archived": None},
                         s["kinds"]["contracts"])
        self.assertNotIn("reports", s["kinds"])
        self.assertNotIn("nowhere", s["kinds"])
        self.assertEqual({"Meetings": True, "Knowledge": False}, s["wikis"])
        self.assertEqual((False, True), (s["pins"]["todo"], s["pins"]["thread"]))
        self.assertEqual(("dormant", False, {"on": True, "min": 4}), (s["reach"], s["wake"], s["nightly"]))
        self.assertEqual(fade.DEFAULTS, fade.merged("not a dict"))

    def test_dates_count_from_the_end_of_what_they_name(self):
        self.assertEqual(datetime.date(2026, 3, 10), fade.read_date("2026-03-10"))
        self.assertEqual(datetime.date(2026, 2, 28), fade.read_date("2026-02"))
        self.assertEqual(datetime.date(2025, 12, 31), fade.read_date("2025"))
        self.assertIsNone(fade.read_date("<YYYY-MM-DD>"))
        self.assertEqual(datetime.date(2026, 3, 10), fade.name_date("260310-acme-kickoff.md"))
        self.assertEqual(5, fade.months_since(datetime.date(2026, 3, 31), datetime.date(2026, 9, 30)))
        self.assertEqual(6, fade.months_since(datetime.date(2026, 3, 10), datetime.date(2026, 9, 10)))

    def test_it_imports_with_no_side_effects(self):
        self.assertTrue(callable(fade.settings) and callable(fade.counts))
        self.assertFalse(hasattr(fade, "out_refs"))


class RespellTest(unittest.TestCase):
    """How a link is written once its page has moved."""

    OLD = "Wikis/Meetings/wiki/sources/260401-review.md"
    NEW = "Wikis/Meetings/dormant/wiki/sources/260401-review.md"

    def test_a_path_keeps_its_spelling_around_the_grade(self):
        self.assertEqual(("dormant/wiki/sources/260401-review", False),
                         fade.respell("wiki/sources/260401-review", self.OLD, self.NEW, "Wikis/Meetings/wiki/x.md"))
        self.assertEqual(("Meetings/dormant/wiki/sources/260401-review", False),
                         fade.respell("Meetings/wiki/sources/260401-review", self.OLD, self.NEW, "Zones/Work/x.md"))
        self.assertEqual(("Wikis/Meetings/dormant/wiki/sources/260401-review.md", False),
                         fade.respell("Wikis/Meetings/wiki/sources/260401-review.md", self.OLD, self.NEW, "Zones/W/x.md"))

    def test_a_bare_name_gains_the_path_from_its_wiki_or_with_the_wikis_name_outside_it(self):
        self.assertEqual(("dormant/wiki/sources/260401-review", True),
                         fade.respell("260401-review", self.OLD, self.NEW, "Wikis/Meetings/wiki/sources/b.md"))
        self.assertEqual(("Meetings/dormant/wiki/sources/260401-review", True),
                         fade.respell("260401-review", self.OLD, self.NEW, "Zones/Work/Todo.md"))
        self.assertEqual(("Meetings/dormant/wiki/sources/260401-review", True),
                         fade.respell("../sources/260401-review", self.OLD, self.NEW, "Zones/Work/a.md"))

    def test_waking_takes_the_grade_out(self):
        self.assertEqual(("wiki/sources/260401-review", False),
                         fade.respell("dormant/wiki/sources/260401-review", self.NEW, self.OLD, "Wikis/Meetings/x.md"))

    def test_a_table_cell_keeps_its_escape(self):
        self.assertEqual(("dormant/wiki/sources/260401-review\\", False),
                         fade.respell("wiki/sources/260401-review\\", self.OLD, self.NEW, "Wikis/Meetings/wiki/i.md"))

    def test_a_raw_record_written_without_its_extension_stays_so(self):
        self.assertEqual(("archive/raw/260401-review", False),
                         fade.respell("raw/260401-review", "Wikis/Meetings/raw/260401-review.txt",
                                      "Wikis/Meetings/archive/raw/260401-review.txt", "Wikis/Meetings/x.md"))


class Base(unittest.TestCase):
    """A workspace with real repositories in Zones/Work and Wikis/, and
    meetings of every age: one pinned by a live thread and an open action,
    one only a finished thread and a ticked action still link, one old enough
    for the archive, one superseded, two sharing one record, and one recent
    that links an older one."""

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
        self.meetings = self.wikis / "Meetings"
        shutil.rmtree(self.work / ".git")
        git(self.work, "init", "-q")
        git(self.wikis, "init", "-q")
        src = self.meetings / "wiki" / "sources"
        write(src / "260401-acme-review.md", meeting("Acme review", "2026-04-01"))
        write(src / "250101-acme-old.md", meeting("Acme old", "2025-01-01", more='\nraw: "[[raw/250101-acme-old]]"'))
        write(self.meetings / "raw" / "250101-acme-old.txt", "Dana: the old terms.\n")
        write(src / "260315-acme-draft.md", meeting("Acme draft", "2026-03-15",
                                                    more='\nsuperseded: "[[260401-acme-review]], the figures were wrong"'))
        write(src / "270501-acme-later.md", meeting(
            "Acme later", "2027-05-01",
            body="After [[260401-acme-review]], and [[wiki/sources/260401-acme-review#Decisions|its decisions]]."))
        for word in ("pricing", "freight"):
            write(src / ("260402-acme-weekly-%s.md" % word),
                  meeting("Weekly, %s" % word, "2026-04-02", more='\nraw: "[[raw/260402-acme-weekly]]"'))
        write(self.meetings / "raw" / "260402-acme-weekly.txt", "Both halves of one call.\n")
        write(self.meetings / "wiki" / "index.md",
              "# Index\n\nEvery page, newest first.\n\n<!-- garrick:index -->\n| Page | Type | Updated |\n|---|---|---|\n"
              "| [[wiki/sources/270501-acme-later\\|Acme later]] | meeting | 2027-05-01 |\n"
              "| [[wiki/sources/260401-acme-review\\|Acme review]] | meeting | 2026-04-01 |\n"
              "| [[wiki/sources/250101-acme-old\\|Acme old]] | meeting | 2025-01-01 |\n<!-- /garrick:index -->\n")
        acme = self.work / "Acme Review"
        write(acme / "Threads" / "Freight" / "Freight.md", thread_note(
            "Acme Review", "Freight", "acme",
            "Drew on [[260401-acme-review]] and [[Meetings/wiki/sources/250101-acme-old|the old terms]].",
            status="done"))
        pricing = acme / "Threads" / "Pricing" / "Pricing.md"
        write(pricing, pricing.read_text() + "\nSee [[260315-acme-draft]] and [[260402-acme-weekly-pricing]].\n")
        write(self.work / "Todo.md", "# Work: open actions\n\n## Inbox\n\n"
              "- [x] [[Freight]]: send the terms · [[260401-acme-review]]\n"
              "- [ ] [[Pricing]]: chase the rates · [[260310-acme-kickoff]]\n\n## Done\n")
        write(self.wikis / ".obsidian" / "app.json", json.dumps({"userIgnoreFilters": ["Meetings/drafts/"]}))
        self.commit_all()

    def commit_all(self):
        for repo in (self.work, self.wikis):
            git(repo, "add", "-A")
            git(repo, "-c", "core.hooksPath=" + os.devnull, "commit", "-q", "--allow-empty", "-m", "start")

    def run_tool(self, *args: str, today: datetime.date = TODAY):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = fade.main(list(args) + ["--root", str(self.root), "--today", today.isoformat()])
        return code, out.getvalue(), err.getvalue()

    def propose(self, wiki: str = "Meetings", today: datetime.date = TODAY, *more: str) -> dict:
        code, out, err = self.run_tool("propose", "--wiki", wiki, "--json", *more, today=today)
        self.assertEqual(0, code, err)
        return json.loads(out)

    def written_id(self, wiki: str = "Meetings") -> str:
        return json.loads((self.root / "System" / "generated" / "fade" / ("%s.json" % wiki)).read_text())["id"]

    def apply(self, wiki: str = "Meetings", today: datetime.date = TODAY, pid: str = None) -> dict:
        code, out, err = self.run_tool("apply", "--wiki", wiki, "--id", pid or self.written_id(wiki), "--json",
                                       today=today)
        self.assertIn(code, (0, 1), err)
        return json.loads(out)

    def page(self, rel: str) -> Path:
        return self.meetings / rel

    def text(self, path: Path) -> str:
        return path.read_text(encoding="utf-8")


class ProposeTest(Base):
    def test_the_first_fade_only_proposes_and_keeps_its_id_in_the_written_proposal(self):
        before = git(self.wikis, "status", "--porcelain")
        out = self.propose()
        self.assertTrue(out["first"])
        self.assertIsNone(out["id"])                       # nothing a single run prints can apply it
        self.assertEqual(before, git(self.wikis, "status", "--porcelain"))
        self.assertTrue(self.page("wiki/sources/260401-acme-review.md").exists())
        written = self.text(self.root / out["proposal"])
        self.assertIn("first fade on this wiki, so it only proposes", written)
        self.assertIn("--id %s" % self.written_id(), written)
        code, said, _ = self.run_tool("propose", "--wiki", "Meetings")
        self.assertNotIn("--id", said)

    def test_what_moves_where_and_why(self):
        moves = {m["page"].rsplit("/", 1)[1]: m for m in self.propose()["moves"]}
        self.assertEqual("archived", moves["250101-acme-old.md"]["to"])
        self.assertIn("29 months old; meetings are archived at 18", moves["250101-acme-old.md"]["why"])
        self.assertEqual("dormant", moves["260401-acme-review.md"]["to"])
        self.assertEqual("dormant", moves["260315-acme-draft.md"]["to"])
        self.assertIn("superseded:", moves["260315-acme-draft.md"]["why"])
        self.assertNotIn("260310-acme-kickoff.md", moves)          # a live thread and an open action pin it
        self.assertNotIn("270501-acme-later.md", moves)            # one month old
        self.assertNotIn("dana-whitlock.md", moves)                # a person page never moves

    def test_the_written_proposal_names_each_pages_derived_copies(self):
        written = self.text(self.root / self.propose()["proposal"])
        review = written.split("`wiki/sources/260401-acme-review.md`", 1)[1].split("\n- `", 1)[0]
        self.assertIn("pointed at the new path: `Wikis/Meetings/wiki/sources/270501-acme-later.md`, "
                      "`Zones/Work/Acme Review/Threads/Freight/Freight.md`", review)
        self.assertIn("ticked actions pointed at the new path: `Zones/Work/Todo.md`", review)
        self.assertIn("listed under Earlier on `Wikis/Meetings/wiki/people/dana-whitlock.md`", review)
        old = written.split("`wiki/sources/250101-acme-old.md`", 1)[1].split("\n- `", 1)[0]
        self.assertIn("its record `raw/250101-acme-old.txt` moves with it", old)
        self.assertIn("## Superseded, and still linked from a live note", written)
        self.assertIn("`wiki/sources/260315-acme-draft.md`: [[260401-acme-review]], the figures were wrong. Linked "
                      "from `Zones/Work/Acme Review/Threads/Pricing/Pricing.md`", written)
        self.assertIn("`wiki/sources/260310-acme-kickoff.md`: an open action, Zones/Work/Todo.md; a live thread", written)

    def test_pages_that_share_a_record_move_together_or_not_at_all(self):
        moves = [m["page"] for m in self.propose()["moves"]]
        self.assertFalse([m for m in moves if "weekly" in m])        # the pricing half is pinned by a live thread
        written = self.text(self.root / "System" / "generated" / "fade" / "Meetings.md")
        self.assertIn("`wiki/sources/260402-acme-weekly-freight.md`: shares its record with "
                      "wiki/sources/260402-acme-weekly-pricing.md", written)
        pricing = self.work / "Acme Review" / "Threads" / "Pricing" / "Pricing.md"
        pricing.write_text(self.text(pricing).replace(" and [[260402-acme-weekly-pricing]]", ""))
        moves = [m["page"] for m in self.propose()["moves"]]
        self.assertEqual(2, len([m for m in moves if "weekly" in m]))

    def test_a_page_left_by_judgment_stays(self):
        out = self.propose("Meetings", TODAY, "--leave", "Meetings/wiki/sources/260401-acme-review.md")
        self.assertNotIn("Wikis/Meetings/wiki/sources/260401-acme-review.md", [m["page"] for m in out["moves"]])
        self.assertIn("left out by judgment", self.text(self.root / out["proposal"]))

    def test_age_comes_from_the_page_never_the_file(self):
        page = self.page("wiki/sources/260401-acme-review.md")
        os.utime(str(page), None)                                   # a re-ingest touches the file
        self.assertIn("Wikis/Meetings/wiki/sources/260401-acme-review.md", [m["page"] for m in self.propose()["moves"]])
        page.write_text(self.text(page).replace("date: 2026-04-01\n", ""))
        self.assertIn("Wikis/Meetings/wiki/sources/260401-acme-review.md", [m["page"] for m in self.propose()["moves"]])

    def test_switches_and_kinds_change_the_plan(self):
        write(self.root / "System" / "garrick-settings.json", json.dumps({"memory": {
            "kinds": {"meetings": {"dormant": 24, "archived": None}}, "pins": {"pinned": False}}}))
        moves = [m["page"] for m in self.propose()["moves"]]
        self.assertEqual(["Wikis/Meetings/wiki/sources/250101-acme-old.md",
                          "Wikis/Meetings/wiki/sources/260315-acme-draft.md"], sorted(moves))
        write(self.root / "System" / "garrick-settings.json", json.dumps({"memory": {"wikis": {"Meetings": False}}}))
        self.assertEqual([], self.propose()["moves"])

    def test_counts_are_what_each_grade_holds_and_what_would_move(self):
        c = fade.counts(self.root, today=TODAY)
        self.assertEqual({"on": True, "working": 9, "dormant": 0, "archived": 0, "to_dormant": 3, "to_archive": 1,
                          "to_wake": 0}, c["Meetings"])
        self.assertEqual({"Meetings", "Knowledge"}, set(c))
        off = fade.counts(self.root, {"wikis": {"Meetings": False}}, today=TODAY)
        self.assertEqual((False, 0, 0), (off["Meetings"]["on"], off["Meetings"]["to_dormant"], off["Meetings"]["to_archive"]))
        later = fade.counts(self.root, {"kinds": {"meetings": {"archived": 12}}}, today=TODAY)
        self.assertEqual(4, later["Meetings"]["to_archive"])        # unsaved settings, shown before they are saved
        self.assertFalse((self.root / "System" / "garrick-settings.json").exists())

    def test_what_would_fade_is_said_for_the_ear(self):
        code, out, _ = self.run_tool("propose", "--wiki", "Meetings", "--ear")
        self.assertEqual("In the meetings: 3 meeting pages would go dormant and 1 to the archive. Nothing has moved; "
                         "the list is written for you to read.", out.strip())


class ApplyTest(Base):
    def test_a_fade_needs_the_written_proposal(self):
        code, _, err = self.run_tool("apply", "--wiki", "Meetings", "--id", "deadbeef")
        self.assertEqual(1, code)
        self.assertIn("no written proposal", err)
        self.propose()
        code, _, err = self.run_tool("apply", "--wiki", "Meetings", "--id", "deadbeef")
        self.assertEqual(1, code)
        self.assertIn("not the proposal written", err)
        self.assertTrue(self.page("wiki/sources/260401-acme-review.md").exists())

    def test_nobody_watching_never_fades(self):
        self.propose()
        with mock.patch.dict(os.environ, {"GARRICK_HEADLESS": "1"}):
            code, _, err = self.run_tool("apply", "--wiki", "Meetings", "--id", self.written_id())
        self.assertEqual(1, code)
        self.assertIn("nobody watching", err)

    def test_every_grade_change_is_a_rename_and_links_follow_from_both_wikis_and_every_zone(self):
        self.propose()
        r = self.apply()
        self.assertEqual(["Wikis", "Zones/Work"], [c["repo"] for c in r["commits"]])
        self.assertTrue(self.page("dormant/wiki/sources/260401-acme-review.md").is_file())
        self.assertTrue(self.page("archive/wiki/sources/250101-acme-old.md").is_file())
        self.assertTrue(self.page("archive/raw/250101-acme-old.txt").is_file())
        self.assertFalse(self.page("raw/250101-acme-old.txt").exists())
        renames = git(self.wikis, "show", "--name-status", "-M", "--format=", "HEAD").splitlines()
        self.assertIn("R100\tMeetings/raw/250101-acme-old.txt\tMeetings/archive/raw/250101-acme-old.txt", renames)
        self.assertIn("R100\tMeetings/wiki/sources/260401-acme-review.md\t"
                      "Meetings/dormant/wiki/sources/260401-acme-review.md", renames)
        freight = self.text(self.work / "Acme Review" / "Threads" / "Freight" / "Freight.md")
        self.assertIn("[[Meetings/dormant/wiki/sources/260401-acme-review|260401-acme-review]]", freight)
        self.assertIn("[[Meetings/archive/wiki/sources/250101-acme-old|the old terms]]", freight)
        todo = self.text(self.work / "Todo.md")
        self.assertIn("- [x] [[Freight]]: send the terms · [[Meetings/dormant/wiki/sources/260401-acme-review|"
                      "260401-acme-review]]", todo)
        self.assertIn("- [ ] [[Pricing]]: chase the rates · [[260310-acme-kickoff]]", todo)
        later = self.text(self.page("wiki/sources/270501-acme-later.md"))
        self.assertIn("After [[dormant/wiki/sources/260401-acme-review|260401-acme-review]], and "
                      "[[dormant/wiki/sources/260401-acme-review#Decisions|its decisions]].", later)
        self.assertEqual("", git(self.work, "status", "--porcelain") + git(self.wikis, "status", "--porcelain"))

    def test_the_lists_follow(self):
        self.propose()
        self.apply()
        index = self.text(self.page("wiki/index.md"))
        self.assertIn("270501-acme-later", index)
        self.assertNotIn("260401-acme-review", index)
        self.assertNotIn("250101-acme-old", index)
        dormant = self.text(self.page("wiki/index-dormant.md"))
        self.assertIn("- [[dormant/wiki/sources/260401-acme-review|Acme review]] · 2026-04-01 · dormant since "
                      "2027-06-01 · 14 months old; meetings go dormant at 6", dormant)
        self.assertIn("· superseded: [[260401-acme-review]], the figures were wrong", dormant)
        self.assertNotIn("250101-acme-old", dormant)                     # the archive is in no index
        self.assertLess(dormant.index("260401-acme-review"), dormant.index("260315-acme-draft"))   # newest first

    def test_a_person_page_lists_what_faded_only_from_its_own_party(self):
        write(self.page("wiki/sources/260312-birch-kickoff.md"),
              meeting("Birch kick-off", "2026-03-12", "[birch]"))
        self.commit_all()
        self.propose()
        self.apply()
        dana = self.text(self.page("wiki/people/dana-whitlock.md"))
        earlier = dana.split("## Earlier", 1)[1]
        self.assertIn("- [[dormant/wiki/sources/260401-acme-review|Acme review]], 2026-04-01", earlier)
        self.assertIn("- [[archive/wiki/sources/250101-acme-old|Acme old]], 2025-01-01", earlier)
        self.assertNotIn("Birch", dana)
        self.assertTrue(self.page("dormant/wiki/sources/260312-birch-kickoff.md").exists())

    def test_obsidian_leaves_the_grades_out_and_keeps_the_users_filters(self):
        self.propose()
        self.apply()
        app = json.loads(self.text(self.wikis / ".obsidian" / "app.json"))
        self.assertEqual(["Meetings/drafts/", "Meetings/dormant/", "Meetings/archive/"], app["userIgnoreFilters"])
        self.assertEqual(["Wikis/.obsidian/app.json"], fade.apply_filters(self.root))     # Knowledge's, now
        self.assertEqual([], fade.apply_filters(self.root))                               # once, never twice

    def test_only_what_was_listed_and_still_qualifies_moves(self):
        self.propose()
        review = self.page("wiki/sources/260401-acme-review.md")
        review.write_text(self.text(review).replace("type: meeting", "type: meeting\npinned: true"))
        write(self.page("wiki/sources/240101-acme-older.md"), meeting("Older", "2024-01-01"))
        self.commit_all()
        r = self.apply()
        self.assertEqual(["Wikis/Meetings/wiki/sources/260401-acme-review.md"], r["gone"])
        self.assertTrue(review.exists())
        self.assertTrue(self.page("wiki/sources/240101-acme-older.md").exists())     # never proposed
        self.assertFalse((self.root / "System" / "generated" / "fade" / "Meetings.json").exists())
        code, _, err = self.run_tool("apply", "--wiki", "Meetings", "--id", r["id"])
        self.assertEqual(1, code)                                                     # applied once

    def test_a_note_another_session_is_changing_holds_the_moves_it_links(self):
        self.propose()
        freight = self.work / "Acme Review" / "Threads" / "Freight" / "Freight.md"
        freight.write_text(self.text(freight) + "\nHalf a sentence\n")
        r = self.apply()
        held = {h["page"] for h in r["held"]}
        self.assertEqual({"Wikis/Meetings/wiki/sources/260401-acme-review.md",
                          "Wikis/Meetings/wiki/sources/250101-acme-old.md"}, held)
        self.assertTrue(self.page("dormant/wiki/sources/260315-acme-draft.md").exists())
        self.assertIn("Half a sentence", self.text(freight))
        self.assertNotIn("Freight.md", git(self.work, "show", "--name-only", "--format=", "HEAD"))

    def test_a_refused_commit_puts_everything_back(self):
        self.propose()
        hook = self.wikis / ".git" / "hooks" / "pre-commit"
        write(hook, "#!/bin/sh\necho refused by the test >&2\nexit 1\n")
        hook.chmod(0o755)
        before = git(self.wikis, "rev-parse", "HEAD")
        r = self.apply()
        self.assertIn("refused", r["refused"])
        self.assertEqual(before, git(self.wikis, "rev-parse", "HEAD"))
        self.assertTrue(self.page("wiki/sources/260401-acme-review.md").exists())
        self.assertIn("[[260401-acme-review]]", self.text(self.work / "Todo.md"))
        self.assertEqual("", git(self.wikis, "status", "--porcelain", "--", "Meetings"))


class WakeTest(Base):
    def faded(self):
        self.propose()
        self.apply()

    def test_a_dormant_page_linked_again_from_a_live_thread_wakes_and_links_follow_back(self):
        self.faded()
        pricing = self.work / "Acme Review" / "Threads" / "Pricing" / "Pricing.md"
        pricing.write_text(self.text(pricing) + "\nBack to [[260401-acme-review]].\n")
        git(self.work, "commit", "-qam", "linked again")
        out = self.propose(today=TODAY + datetime.timedelta(days=1))
        self.assertFalse(out["first"])
        self.assertEqual([("Wikis/Meetings/dormant/wiki/sources/260401-acme-review.md", "working")],
                         [(m["page"], m["to"]) for m in out["moves"]])
        self.assertIn("a live thread, Zones/Work/Acme Review/Threads/Pricing/Pricing.md", out["moves"][0]["why"])
        self.apply(pid=out["id"], today=TODAY + datetime.timedelta(days=1))
        self.assertTrue(self.page("wiki/sources/260401-acme-review.md").exists())
        self.assertIn("Back to [[260401-acme-review]].", self.text(pricing))     # it still lands: left as written
        self.assertIn("[[Meetings/wiki/sources/260401-acme-review|260401-acme-review]]",
                      self.text(self.work / "Acme Review" / "Threads" / "Freight" / "Freight.md"))
        self.assertIn("[[wiki/sources/260401-acme-review#Decisions|its decisions]]",
                      self.text(self.page("wiki/sources/270501-acme-later.md")))
        self.assertNotIn("260401-acme-review", self.text(self.page("wiki/index-dormant.md")))
        self.assertIn("| [[wiki/sources/260401-acme-review\\|Acme review]] | meeting | 2026-04-01 |",
                      self.text(self.page("wiki/index.md")))
        self.assertNotIn("Acme review", self.text(self.page("wiki/people/dana-whitlock.md")))

    def test_a_working_page_waking_it_must_link_it_afresh(self):
        self.faded()
        # The fade wrote the grade into the later page's link: that does not wake it.
        self.assertEqual([], self.propose(today=TODAY + datetime.timedelta(days=1))["moves"])
        write(self.page("wiki/sources/270520-acme-next.md"),
              meeting("Next", "2027-05-20", body="As agreed in [[260401-acme-review]]."))
        self.commit_all()
        moves = self.propose(today=TODAY + datetime.timedelta(days=1))["moves"]
        self.assertEqual(["working"], [m["to"] for m in moves])
        self.assertIn("linked again from the working page Wikis/Meetings/wiki/sources/270520-acme-next.md",
                      moves[0]["why"])

    def test_a_superseded_page_never_wakes(self):
        self.faded()
        self.assertTrue(self.page("dormant/wiki/sources/260315-acme-draft.md").exists())
        out = self.propose(today=TODAY + datetime.timedelta(days=1))     # the live thread still links it
        self.assertEqual([], out["moves"])
        self.assertIn("Superseded, and still linked from a live note", self.text(self.root / out["proposal"]))

    def test_keep_pins_a_page_and_proposes_waking_one_that_faded(self):
        self.faded()
        code, out, err = self.run_tool("keep", "--page", "250101-acme-old", "--json")
        self.assertEqual(0, code, err)
        r = json.loads(out)
        self.assertEqual("archived", r["grade"])
        self.assertTrue(r["commit"])
        self.assertIn("pinned: true", self.text(self.page("archive/wiki/sources/250101-acme-old.md")))
        self.assertEqual([("Wikis/Meetings/archive/wiki/sources/250101-acme-old.md", "working", "pinned: true")],
                         [(m["page"], m["to"], m["why"]) for m in r["proposal"]["moves"]])
        self.apply(pid=r["proposal"]["id"])
        self.assertTrue(self.page("wiki/sources/250101-acme-old.md").exists())
        self.assertTrue(self.page("raw/250101-acme-old.txt").exists())

    def test_an_archived_page_is_listed_with_its_date(self):
        self.faded()
        code, out, _ = self.run_tool("list", "--wiki", "Meetings", "--grade", "archived", "--json")
        self.assertEqual([{"page": "Wikis/Meetings/archive/wiki/sources/250101-acme-old.md", "title": "Acme old",
                           "date": "2025-01-01", "superseded": ""}], json.loads(out))


class NamesTest(Base):
    def test_a_faded_name_stays_taken_and_its_record_stays_filed(self):
        ingest = load("garrick_ingest", REPO / "template" / "System" / "skills" / "meetings" / "ingest.py")
        self.propose()
        self.apply()
        self.assertIn("250101-acme-old", ingest.taken_stems(self.meetings, "raw", "wiki/sources"))
        self.assertIn("260401-acme-review", ingest.taken_stems(self.meetings, "raw", "wiki/sources"))
        again = write(self.meetings / "raw" / "inbox" / "again.txt", "Dana: the old terms.\n")
        self.assertEqual("archive/250101-acme-old", ingest.already_filed(self.root, again))


class KnowledgeTest(Base):
    def test_reading_fades_by_kind_and_its_raw_goes_with_its_summary(self):
        k = self.wikis / "Knowledge"
        write(k / "raw" / "weekly-letter.eml", "Subject: Weekly letter\n\nNews.\n")
        write(k / "wiki" / "sources" / "weekly-letter.md",
              '---\ntitle: Weekly letter\ntype: source\nauthor: Fictus Weekly\npublished: 2027-01-15\n'
              'raw: "[[raw/weekly-letter]]"\nconfidence: low\n---\n\nNews.\n')
        write(k / "wiki" / "sources" / "big-report.md",
              '---\ntitle: Big report\ntype: source\nauthor: Northwind Analytics\npublished: 2026-01\n'
              'confidence: high\n---\n\nFindings.\n')
        write(k / "wiki" / "entities" / "fictus-weekly.md",
              "---\ntitle: Fictus Weekly\ntype: entity\n---\n\n## Claims\n\n- News. [[../sources/weekly-letter|Weekly letter]]\n")
        self.commit_all()
        moves = {m["page"]: m for m in self.propose("Knowledge")["moves"]}
        self.assertEqual(["Wikis/Knowledge/wiki/sources/weekly-letter.md"], list(moves))   # newsletters: 3 months
        self.assertIn("newsletters go dormant at 3", moves["Wikis/Knowledge/wiki/sources/weekly-letter.md"]["why"])
        self.apply("Knowledge")
        self.assertTrue((k / "dormant" / "raw" / "weekly-letter.eml").exists())
        entity = self.text(k / "wiki" / "entities" / "fictus-weekly.md")
        self.assertIn("- News. [[dormant/wiki/sources/weekly-letter|Weekly letter]]", entity)
        self.assertIn("## Earlier\n\n- [[dormant/wiki/sources/weekly-letter|Weekly letter]], 2027-01-15", entity)
        self.assertTrue((k / "wiki" / "sources" / "big-report.md").exists())                 # reports: 24 months


if __name__ == "__main__":
    unittest.main()
