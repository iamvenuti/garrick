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


class WordsTest(unittest.TestCase):
    """What Settings › Memory says about age and waking is fade.py's own
    (AGE_SAID, WAKE_SAID, #205), held here against what the code does, so the
    words cannot drift from it again: the page shows them as they are."""

    def page(self, grade: str = "dormant", **more) -> "fade.Page":
        sub = "wiki/sources/260401-review.md"
        return fade.Page(fade.place("Meetings", grade, sub), "Meetings", grade, sub, title="Review", type="meeting",
                         date=datetime.date(2026, 4, 1), kind="meetings", **more)

    def ref(self, where: str, written: str = "260401-review") -> "fade.Ref":
        src = {"thread": "Zones/Work/Acme Review/Threads/Pricing/Pricing.md", "project": "Zones/Work/Acme Review/Acme Review.md",
               "todo": "Zones/Work/Todo.md", "working": "Wikis/Meetings/wiki/sources/270501-later.md",
               "note": "Zones/Work/Acme Review/Threads/Freight/Freight.md"}[where]
        return fade.Ref(src, written, where, True)

    def test_opening_a_page_wakes_nothing_and_a_link_from_active_work_proposes_it(self):
        s, said = fade.merged({}), fade.WAKE_SAID
        self.assertIn("Opening, reading or quoting a page brings nothing back", said)
        self.assertIsNone(fade.wake(self.page(), [], s))                    # reading leaves no link, and links are all it reads
        self.assertIsNone(fade.wake(self.page(), [self.ref("note")], s))    # nor a note outside live work
        for where, words in (("thread", "a live thread"), ("project", "a live project's notes"), ("todo", "an open action")):
            self.assertIn(words, said)
            self.assertEqual("working", fade.wake(self.page(), [self.ref(where)], s).to)
            self.assertIsNone(fade.wake(self.page(), [self.ref(where)], fade.merged({"pins": {where: False}})))
        self.assertIn("where that protection is switched on", said)
        self.assertIsNone(fade.wake(self.page(), [self.ref("thread")], fade.merged({"wake": False})))
        self.assertIn("a working page links it afresh rather than through the link the fade rewrote", said)
        self.assertEqual("working", fade.wake(self.page(), [self.ref("working")], s).to)
        self.assertIsNone(fade.wake(self.page(), [self.ref("working", "dormant/wiki/sources/260401-review")], s))
        self.assertIn("Marking it `pinned: true` brings it back too, and is the only way back from the archive", said)
        self.assertEqual("working", fade.wake(self.page(pinned=True), [], fade.merged({"wake": False})).to)
        self.assertIsNone(fade.wake(self.page("archived"), [self.ref("thread"), self.ref("working")], s))
        self.assertEqual("working", fade.wake(self.page("archived", pinned=True), [], s).to)
        self.assertIn("a superseded page never comes back", said)
        self.assertIsNone(fade.wake(self.page(pinned=True, superseded="replaced"), [self.ref("thread")], s))
        self.assertIn("nothing comes back until you confirm a review", said)
        woken = fade.decide(self.page(), [self.ref("thread")], s, TODAY, fade.Plan("Meetings", True, []))
        self.assertEqual(("working", "Wikis/Meetings/wiki/sources/260401-review.md"), (woken.to, woken.new))   # a move planned, not made

    def test_age_counts_from_the_dates_the_words_name_and_never_from_the_file(self):
        said = fade.AGE_SAID
        self.assertEqual({"Meetings": ("date",), "Knowledge": ("published", "date")}, fade.DATE_FIELDS)
        self.assertIn("the day its meeting took place (its `date:`)", said)
        self.assertIn("the day its reading came out (its `published:`, else its `date:`)", said)
        self.assertIn("it counts from the date its file name starts with, such as `260314` or `2026-03-14`", said)
        self.assertIn("It never counts from when the page was last opened or changed", said)
        self.assertIn("A date that names only a month or a year counts from the end of it", said)
        self.assertIn("a page with no date at all never fades by age", said)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve() / "Workspace"
            build_workspace(root)
            src = root / "Wikis" / "Meetings" / "wiki" / "sources"
            write(src / "call.md", meeting("Call", "2020-02"))
            write(src / "260314-named.md", meeting("Named", "").replace("date: \n", ""))
            write(src / "2026-03-15 named.md", meeting("Named too", "").replace("date: \n", ""))
            undated = write(src / "undated.md", meeting("Undated", "").replace("date: \n", ""))
            os.utime(str(undated), (0, 0))                                   # a file as old as it gets
            write(root / "Wikis" / "Knowledge" / "wiki" / "sources" / "report.md",
                  "---\ntitle: Report\ntype: report\npublished: 2021\ndate: 2025-01-01\n---\n\nText.\n")
            pages = {p.sub: p for w in fade.WIKIS for p in fade.scan_wiki(root, w)}
            self.assertEqual(datetime.date(2020, 2, 29), pages["wiki/sources/call.md"].date)
            self.assertEqual(datetime.date(2026, 3, 14), pages["wiki/sources/260314-named.md"].date)
            self.assertEqual(datetime.date(2026, 3, 15), pages["wiki/sources/2026-03-15 named.md"].date)
            self.assertEqual(datetime.date(2021, 12, 31), pages["wiki/sources/report.md"].date)   # published, first
            self.assertIsNone(pages["wiki/sources/undated.md"].date)                              # its file's time never counts
            p = fade.Plan("Meetings", True, [])
            page = pages["wiki/sources/undated.md"]
            page.kind = "meetings"
            self.assertIsNone(fade.decide(page, [], fade.merged({}), TODAY, p))
            self.assertEqual(1, p.undated)


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


class CodeTest(unittest.TestCase):
    """A link in a code block, fenced or inline, is text: an instructions
    file's example of the frontmatter, say. Fading neither rewrites it nor
    counts it as use (#256)."""

    OLD = "Wikis/Meetings/wiki/sources/260401-review.md"
    NEW = "Wikis/Meetings/dormant/wiki/sources/260401-review.md"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        write(root / self.OLD, "# Review\n")
        self.links = fade.Links(root)

    def test_a_fenced_block_is_neither_read_nor_rewritten(self):
        text = ("Before [[260401-review]].\n\n```yaml\nrelated:\n  - \"[[wiki/sources/260401-review]]\"\n```\n\n"
                "~~~~\n[[260401-review]]\n~~~\nstill inside, the fence is four long\n~~~~\n\n"
                "````md\n```\n[[260401-review]]\n````\n\nAfter [[wiki/sources/260401-review]].\n")
        self.assertEqual([(0, "260401-review"), (18, "wiki/sources/260401-review")], list(fade.links_in(text)))
        out = fade.relink(text, {self.OLD: self.NEW}, self.links, "Wikis/Meetings/wiki/x.md")
        self.assertEqual(text.replace("Before [[260401-review]]",
                                      "Before [[dormant/wiki/sources/260401-review|260401-review]]")
                             .replace("After [[wiki/", "After [[dormant/wiki/"), out)

    def test_a_fence_never_closed_runs_to_the_end(self):
        text = "```\n[[260401-review]]\n"
        self.assertEqual([], list(fade.links_in(text)))
        self.assertEqual(text, fade.relink(text, {self.OLD: self.NEW}, self.links, "Wikis/Meetings/wiki/x.md"))

    def test_inline_code_is_neither_read_nor_rewritten(self):
        text = "Write `[[wiki/sources/260401-review]]`, as in [[260401-review]] or `obsidian://open?file=260401-review`."
        self.assertEqual([(0, "260401-review")], list(fade.links_in(text)))
        self.assertEqual(text.replace("in [[260401-review]]", "in [[dormant/wiki/sources/260401-review|260401-review]]"),
                         fade.relink(text, {self.OLD: self.NEW}, self.links, "Wikis/Meetings/wiki/x.md"))
        row = "| `[[260401-review]]` | [[260401-review]] |"
        self.assertEqual("| `[[260401-review]]` | [[dormant/wiki/sources/260401-review\\|260401-review]] |",
                         fade.relink(row, {self.OLD: self.NEW}, self.links, "Wikis/Meetings/wiki/x.md"))


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

    def test_a_preview_names_the_pages_behind_the_counts_in_the_proposals_order(self):
        pv = fade.preview(self.root, today=TODAY, limit=2)["Meetings"]
        c = fade.counts(self.root, today=TODAY)["Meetings"]
        self.assertEqual(c, {k: pv[k] for k in c})                          # counts(), and more
        self.assertEqual((4, 2), (pv["moves"], len(pv["moving"])))
        kept = {r["page"].rsplit("/", 1)[1]: r for r in pv["keeping"]}
        self.assertIn("a live thread, Zones/Work/Acme Review/Threads/Pricing/Pricing.md", kept["260310-acme-kickoff.md"]["why"])
        self.assertEqual(("Acme kick-off", "2026-03-10"), (kept["260310-acme-kickoff.md"]["title"], kept["260310-acme-kickoff.md"]["date"]))
        self.assertEqual(("System/generated/fade/Meetings.md", False), (pv["proposal"], pv["written"]))
        self.assertFalse((self.root / "System" / "generated").exists())       # it writes nothing
        self.propose()
        every = fade.preview(self.root, today=TODAY, limit=100)["Meetings"]
        self.assertTrue(every["written"])
        written = self.text(self.root / "System" / "generated" / "fade" / "Meetings.md")
        at = [written.index("`%s`, %s" % (m["page"].split("/Meetings/", 1)[1], m["title"])) for m in every["moving"]]
        self.assertEqual(sorted(at), at)                                    # in the order the written list has them
        self.assertEqual(sorted((m["page"], m["to"], m["why"]) for m in self.propose()["moves"]),
                         sorted((m["page"], m["to"], m["why"]) for m in every["moving"]))

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


    def test_an_example_in_a_code_block_survives_the_fade_byte_for_byte(self):
        agents = self.meetings / "AGENTS.local.md"
        example = ("# Meetings: this workspace's own\n\nA page's frontmatter, as in `[[260401-acme-review]]`:\n\n"
                   "```yaml\nrelated:\n  - \"[[wiki/sources/260401-acme-review]]\"\n```\n")
        write(agents, example)
        later = self.page("wiki/sources/270501-acme-later.md")
        block = "\n~~~\n[[260401-acme-review]]\n~~~\n"
        later.write_text(self.text(later) + block)
        self.commit_all()
        self.propose()
        self.apply()
        self.assertTrue(self.page("dormant/wiki/sources/260401-acme-review.md").is_file())
        self.assertEqual(example.encode("utf-8"), agents.read_bytes())
        self.assertIn("After [[dormant/wiki/sources/260401-acme-review|260401-acme-review]]", self.text(later))
        self.assertTrue(self.text(later).endswith(block))

    def test_a_todo_lines_relative_source_pins_its_page_and_follows_it(self):
        """#318: a Todo line's source is a relative link to the page's file. An
        open line's pins the page, as a wikilink does; a ticked line's is
        pointed at where the page went. Elsewhere a Markdown link stays as
        written (the test below)."""
        write(self.work / "Todo.md", "# Work: open actions\n\n## Inbox\n\n"
              "- [x] [[Freight]]: send the terms · [Acme review](../../Wikis/Meetings/wiki/sources/260401-acme-review.md)\n"
              "- [ ] [[Pricing]]: book the call · [Acme old](../../Wikis/Meetings/wiki/sources/250101-acme-old.md)\n"
              "- [ ] [[Pricing]]: chase the rates · [[260310-acme-kickoff]]\n\n## Done\n")
        self.commit_all()
        moves = {m["page"].rsplit("/", 1)[1] for m in self.propose()["moves"]}
        self.assertNotIn("250101-acme-old.md", moves)                  # an open action pins it
        self.assertIn("260401-acme-review.md", moves)                  # a ticked one does not
        self.apply()
        self.assertTrue(self.page("dormant/wiki/sources/260401-acme-review.md").is_file())
        todo = self.text(self.work / "Todo.md")
        self.assertIn("- [x] [[Freight]]: send the terms · "
                      "[Acme review](../../Wikis/Meetings/dormant/wiki/sources/260401-acme-review.md)\n", todo)
        self.assertIn("[Acme old](../../Wikis/Meetings/wiki/sources/250101-acme-old.md)", todo)

    def test_a_full_path_in_code_to_a_walled_page_is_reported_before_and_after_it_fades(self):
        """Fade leaves a link in code as written (#256), and a Markdown link
        too; the walls still find the page behind it once it has faded (#297)."""
        pricing = self.work / "Acme Review" / "Threads" / "Pricing" / "Pricing.md"
        said = ("\nTheir terms: `[[Meetings/wiki/sources/260312-birch-kickoff]]`.\n\n"
                "```\nWikis/Meetings/wiki/sources/260312-birch-kickoff.md\n```\n\n"
                "As [the call](../../../../../Wikis/Meetings/wiki/sources/260312-birch-kickoff.md) had it.\n")
        pricing.write_text(self.text(pricing) + said)
        self.commit_all()

        def walled():
            r = subprocess.run([sys.executable, str(TOOLS / "check.py"), "--root", str(self.root), "--json"],
                               capture_output=True, text=True)
            return sorted(f["message"] for f in json.loads(r.stdout)["findings"]
                          if f["check"] == "walls" and f["path"].endswith("Pricing/Pricing.md")
                          and "a meeting with birch" in f["message"])

        before = walled()
        self.assertEqual(3, len(before), before)
        self.propose()
        self.apply()
        self.assertTrue(self.page("dormant/wiki/sources/260312-birch-kickoff.md").is_file())
        self.assertTrue(self.text(pricing).endswith(said))                    # left as written
        self.assertEqual(before, walled())

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
        self.assertIn("- [[dormant/wiki/sources/260401-acme-review|meeting of 2026-04-01]]", earlier)
        self.assertIn("- [[archive/wiki/sources/250101-acme-old|meeting of 2025-01-01]]", earlier)
        self.assertNotIn("Acme review", dana)                            # the title says what was discussed
        self.assertNotIn("Birch", dana)
        self.assertTrue(self.page("dormant/wiki/sources/260312-birch-kickoff.md").exists())

    def test_a_fade_leaves_no_person_page_warning(self):
        title = "Acme freight terms, the volume rebate and the penalty clause for late delivery"
        write(self.page("wiki/sources/260403-acme-freight-terms.md"), meeting(title, "2026-04-03"))
        self.commit_all()
        self.propose()
        self.apply()
        self.assertIn("|meeting of 2026-04-03]]", self.text(self.page("wiki/people/dana-whitlock.md")))
        r = subprocess.run([sys.executable, str(TOOLS / "check.py"), "--root", str(self.root), "--json"],
                           capture_output=True, text=True)
        people = [f for f in json.loads(r.stdout)["findings"]
                  if f["check"] == "people" and "repeats" in f["message"]]
        self.assertEqual([], people)

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


    def test_a_link_in_a_code_block_neither_holds_a_page_nor_wakes_it(self):
        pricing = self.work / "Acme Review" / "Threads" / "Pricing" / "Pricing.md"
        before = self.text(pricing)
        pricing.write_text(before + "\n```\n[[260401-acme-review]]\n```\n\nNot `[[260401-acme-review]]` either.\n")
        git(self.work, "commit", "-qam", "an example")
        self.assertIn("Wikis/Meetings/wiki/sources/260401-acme-review.md", [m["page"] for m in self.propose()["moves"]])
        self.apply()
        self.assertEqual([], self.propose(today=TODAY + datetime.timedelta(days=1))["moves"])
        self.assertIn("```\n[[260401-acme-review]]\n```", self.text(pricing))
        pricing.write_text(self.text(pricing) + "\nBack to [[260401-acme-review]].\n")       # a link, not an example
        git(self.work, "commit", "-qam", "linked again")
        self.assertEqual(["working"], [m["to"] for m in self.propose(today=TODAY + datetime.timedelta(days=2))["moves"]])

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
