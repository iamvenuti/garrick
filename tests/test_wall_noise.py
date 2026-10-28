"""False alarms the wall check no longer raises: a zone's archive read as a
project, the code of HTML pages read as wording, a list of links to Knowledge
pages read as one run of words, files git ignores read as the project's own,
the published ledger's shipped header read as a quotation, alone or running
into the first row, the line a checkpoint's tool writes read as wording, and a
party who is a person caught through her party's tag. Each test pairs the case that must pass with one that must still be found.

Invented parties only: Acme Corp (`acme`) and Birch & Co (`birch`), walled
from each other, as in fixtures.py, with Rowan Keeler, Zeta Rossi and Keeler
added where a party is a person.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unittest

from fixtures import HAVE_GIT, TOOLS, git, meeting_page, write
from test_walls_deterministic import ENV, REPO, SECRET, WallCase, _copy_tools, _real_repo, _run

import check  # noqa: E402  (fixtures puts the tools folder on sys.path)


class TestZoneArchive(WallCase):
    """#23: a zone's `archive/` holds retired material, not a project."""

    def retired(self, folder):
        write(folder / "Todo 2026-09.md",
              "# Done in September\n\n- [x] Read the notes of [[260312-birch-kickoff]] with Theo Marsh\n")
        write(folder / "Old Lane" / "Old Lane.md", "# Old Lane\n\nMoved here when it closed.\n")

    def found_in(self, folder):
        prefix = check.rel(check.discover(self.root), folder) + "/"
        return [f for f in check.run_checks(self.root) if f.path == prefix[:-1] or f.path.startswith(prefix)]

    def test_archive_any_case_is_not_a_project(self):
        for name in ("archive", "Archive"):
            with self.subTest(name):
                folder = self.root / "Zones" / "Work" / name
                self.retired(folder)
                self.assertEqual([], self.found_in(folder))
                self.assertNotIn(folder, [p for p, _ in check.discover(self.root).projects])
                retired = folder.rename(folder.with_name("Retired"))
                found = self.found_in(retired)  # under any other name it is a project
                self.assertIn(("walls", "error"), [(f.check, f.severity) for f in found])
                self.assertIn(("projects", "error"), [(f.check, f.severity) for f in found])
                shutil.rmtree(retired)

    @unittest.skipUnless(HAVE_GIT, "git is not installed")
    def test_committing_the_archive_passes_the_hook(self):
        _copy_tools(self.root)
        zone = self.root / "Zones" / "Work"
        _real_repo(zone)
        self.retired(zone / "archive")
        git(zone, "add", "-A")
        res = _run([sys.executable, self.root / "System" / "tools" / "check.py", "--staged", "--walls-only"], zone)
        self.assertEqual((0, ""), (res.returncode, res.stderr))


# Two slide pages built from one template: the same styles, scripts and
# comments, each with its own visible words.
SLIDE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>%(title)s</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: var(--font-body); background: var(--paper); color: var(--ink); }
  .slide { position: absolute; inset: 0; width: 1920px; height: 1080px; overflow: hidden; }
</style>
<!-- Keyboard and touch navigation: arrow keys, space bar and swipe move between slides -->
</head>
<body>
<section class="slide" data-transition="fade slow" aria-label="opening slide with title and subtitle">
<h1>%(title)s</h1>
<p>%(text)s</p>
</section>
<script>
  document.addEventListener('keydown', function (event) { if (event.key === 'ArrowRight') nextSlide(); });
  document.addEventListener('touchstart', function (event) { startX = event.touches[0].clientX; });
</script>
</body></html>
"""


class TestHtml(WallCase):
    """#24: an HTML page is compared by the words a reader sees."""

    def test_a_shared_template_is_not_wording(self):
        write(self.acme / "Deliverables" / "260302 - Pricing slides.html",
              SLIDE % {"title": "Pricing options", "text": "Three tiers, one floor price."})
        write(self.birch / "Deliverables" / "260302 - Market slides.html",
              SLIDE % {"title": "Nordic market", "text": "Demand grows in the north."})
        self.assertEqual([], self.walls())

    def test_visible_text_still_counts(self):
        text = "Freight volumes on the northern corridor doubled after the new customs rules came in"
        write(self.acme / "Deliverables" / "260302 - Pricing slides.html",
              SLIDE % {"title": "Pricing options", "text": text})
        write(self.birch / "Deliverables" / "260302 - Market slides.html",
              SLIDE % {"title": "Nordic market", "text": text})
        paths = sorted(f.path for f in self.walls())
        self.assertEqual(["Zones/Work/Acme Review/Deliverables/260302 - Pricing slides.html",
                          "Zones/Work/Birch Entry/Deliverables/260302 - Market slides.html"], paths)

    def test_a_meeting_quoted_on_a_page(self):
        write(self.meetings / "wiki" / "sources" / "260314-birch-call.md",
              meeting_page("Work", "[birch]", "Birch call").replace("Decisions.", SECRET + "."))
        write(self.acme / "Deliverables" / "260302 - Pricing slides.html",
              SLIDE % {"title": "Pricing", "text": SECRET.replace("Oslo depot", "<em>Oslo</em> depot")})
        found = self.walls()
        self.assertEqual(1, len(found), found)
        self.assertIn("260314-birch-call", found[0].message)
        self.assertNoLeak(found, "oslo", "depot", "november")

    def test_html_text(self):
        text = check.html_text('<p class="lead">Birch &amp; Co</p><!-- note --><script>var a = 1;</script>'
                               '<STYLE type="text/css">p { margin: 0 }</STYLE>')
        self.assertEqual(["birch", "and", "co"], check.words(text))


# The titles of three Knowledge pages, listed the same way in a note on each
# side of the wall: eight words and more of labels in a row.
KNOWLEDGE_PAGES = {
    "freight-corridors": "Freight corridors and cold chain capacity",
    "bonded-warehousing": "Bonded warehousing for regional distributors",
    "customs-rules": "Customs rules after the border reform",
}


class TestLinkLabels(WallCase):
    """#25: the label of a link to a shared file is that page's title, common to every side."""

    def setUp(self):
        super().setUp()
        for slug, title in KNOWLEDGE_PAGES.items():
            write(self.knowledge / "wiki" / "sources" / (slug + ".md"),
                  "---\ntitle: %s\ntype: source\nconfidence: medium\n---\n\n# %s\n" % (title, title))

    def reading_list(self, depth):
        up = "../" * depth
        slugs = list(KNOWLEDGE_PAGES)
        return ("# Reading\n\n"
                "- [[wiki/sources/%s|%s]]\n" % (slugs[0], KNOWLEDGE_PAGES[slugs[0]])
                + "- [%s](%sWikis/Knowledge/wiki/sources/%s.md)\n" % (KNOWLEDGE_PAGES[slugs[1]], up, slugs[1])
                + "- [%s](obsidian://open?vault=Knowledge&file=wiki%%2Fsources%%2F%s)\n" % (KNOWLEDGE_PAGES[slugs[2]], slugs[2]))

    def test_a_list_of_knowledge_pages_is_common(self):
        write(self.acme / "Threads" / "Pricing" / "Reading.md", self.reading_list(5))
        write(self.birch / "Threads" / "Market Sizing" / "Reading.md", self.reading_list(5))
        self.assertEqual([], self.walls())

    def test_obsidian_links_to_knowledge_pages(self):
        text = "".join("- [%s](obsidian://open?vault=Knowledge&file=wiki%%2Fsources%%2F%s)\n" % (title, slug)
                       for slug, title in KNOWLEDGE_PAGES.items())
        write(self.acme / "Threads" / "Pricing" / "Reading.md", text)
        write(self.birch / "Threads" / "Market Sizing" / "Reading.md", text)
        self.assertEqual([], self.walls())
        text = text.replace("wiki%2Fsources%2F", "Notes%2F")  # pages that are not there: their labels are wording
        write(self.acme / "Threads" / "Pricing" / "Reading.md", text)
        write(self.birch / "Threads" / "Market Sizing" / "Reading.md", text)
        self.assertEqual(2, len(self.walls()))

    def test_labels_of_other_links_still_count(self):
        text = self.reading_list(5).replace("wiki/sources/", "Notes/").replace("wiki%2Fsources%2F", "Notes%2F")
        write(self.acme / "Threads" / "Pricing" / "Reading.md", text)
        write(self.birch / "Threads" / "Market Sizing" / "Reading.md", text)
        self.assertEqual(2, len(self.walls()))


class TestIgnoredFiles(WallCase):
    """#26: files git never commits are not the project's own text."""

    def test_installed_packages_by_name(self):
        for name in ("node_modules", ".venv", "__pycache__", "dist"):
            write(self.acme / "Tool" / name / "pkg" / "README.md", "Built for Birch & Co pipelines. {{PROJECT}}\n")
        self.assertEqual([], [f for f in check.run_checks(self.root) if f.check in ("walls", "placeholders")])
        write(self.acme / "Tool" / "vendor" / "README.md", "Built for Birch & Co pipelines. {{PROJECT}}\n")
        found = [(f.check, f.path) for f in check.run_checks(self.root) if f.check in ("walls", "placeholders")]
        self.assertEqual([("placeholders", "Zones/Work/Acme Review/Tool/vendor/README.md"),
                          ("walls", "Zones/Work/Acme Review/Tool/vendor/README.md")], sorted(found))

    @unittest.skipUnless(HAVE_GIT, "git is not installed")
    def test_what_the_zone_ignores(self):
        zone = self.root / "Zones" / "Work"
        _real_repo(zone)
        write(zone / ".gitignore", "Inbox/*\n!Inbox/.gitkeep\ncache/\n")
        write(self.acme / "Tool" / "cache" / "README.md", "Built for Birch & Co pipelines. {{PROJECT}}\n")
        (zone / "Inbox" / "call.m4a").write_bytes(b"\0audio")
        found = {(f.check, f.path) for f in check.run_checks(self.root)}
        self.assertNotIn("walls", {c for c, _ in found})
        self.assertNotIn("placeholders", {c for c, _ in found})
        self.assertIn(("inbox", "Zones/Work/Inbox/call.m4a"), found)  # the inbox is ignored by design, and still read
        write(zone / ".gitignore", "Inbox/*\n!Inbox/.gitkeep\n")
        found = {(f.check, f.path) for f in check.run_checks(self.root)}
        self.assertIn(("walls", "Zones/Work/Acme Review/Tool/cache/README.md"), found)
        self.assertIn(("placeholders", "Zones/Work/Acme Review/Tool/cache/README.md"), found)

    @unittest.skipUnless(HAVE_GIT, "git is not installed")
    def test_the_root_ignoring_the_zones_hides_nothing(self):
        git(self.root, "init", "-q")
        write(self.root / ".gitignore", "Zones/\nWikis/\nSystem/generated/\n")
        write(self.acme / "Notes.md", "Built for Birch & Co pipelines.\n")
        self.assertEqual(["Zones/Work/Acme Review/Notes.md"], [f.path for f in self.walls()])


# Real content, in one ledger only: never common wording, whatever the header.
HANDOVER = "The board asked for the Nordic volumes to be split by depot before the handover.\n"


class TestPublishedLedger(WallCase):
    """#91: every project's `Deliverables/published.md` opens with the same
    shipped explanation, so two walled ledgers are not quoting each other."""

    TEMPLATE = REPO / "template" / "System" / "templates" / "published.md"

    def setUp(self):
        super().setUp()
        self.shipped = self.root / "System" / "templates" / "published.md"
        write(self.shipped, self.TEMPLATE.read_text(encoding="utf-8"))
        self.ledgers = {}
        for project, row in ((self.acme, "| 2026-10-01 | `260301 - Pricing memo.md` | `Pricing memo.md` | Dana | share |\n"),
                             (self.birch, "| 2026-10-02 | `260302 - Sizing.md` | `Sizing.md` | Theo | here |\n")):
            self.ledgers[project] = write(project / "Deliverables" / "published.md",
                                          self.shipped.read_text(encoding="utf-8") + row)

    def test_both_ledgers_can_hold_the_shipped_header(self):
        self.assertEqual([], self.walls())

    def test_the_header_is_common_only_because_it_is_shipped(self):
        """The reproduction: with no template to vouch for the wording, each
        ledger reads as a quotation of the other."""
        self.shipped.unlink()
        self.assertEqual({"Zones/Work/Acme Review/Deliverables/published.md",
                          "Zones/Work/Birch Entry/Deliverables/published.md"},
                         {f.path for f in self.walls()})

    def test_a_quotation_of_real_content_is_still_refused(self):
        for project, ledger in self.ledgers.items():
            ledger.write_text(ledger.read_text(encoding="utf-8") + "\n" + HANDOVER, encoding="utf-8")
        self.assertEqual({"Zones/Work/Acme Review/Deliverables/published.md",
                          "Zones/Work/Birch Entry/Deliverables/published.md"},
                         {f.path for f in self.walls()})

    def test_a_heading_stands_directly_above_the_table(self):
        """Load-bearing, not decoration: no run of words crosses a heading, so
        the heading is what keeps the shipped explanation and the rows a
        project writes under it from reading as one sentence."""
        lines = [line for line in self.TEMPLATE.read_text(encoding="utf-8").splitlines() if line.strip()]
        table = next(i for i, line in enumerate(lines) if line.startswith("| Date |"))
        self.assertTrue(lines[table - 1].startswith("#"), lines[table - 1])

    def test_the_rows_still_read_as_a_ledger(self):
        """The header the skill copies must not break the table drift.py reads."""
        from drift import ledger_rows
        rows, bad = ledger_rows(self.ledgers[self.acme])
        self.assertEqual(([("2026-10-01", "260301 - Pricing memo.md", "share")]),
                         [(r["date"], r["file"], r["authoritative"]) for r in rows])
        self.assertEqual([], bad)
        self.assertEqual([], [f for f in check.run_checks(self.root) if f.check == "deliverables"])


class TestLedgerHeaderIsNotARun(WallCase):
    """#221: the separator row under a ledger's header holds no words, so a
    run of words used to cross from the shipped header into the first row's
    date cell, and two walled ledgers whose first rows were both `sent` in
    the same month read as quoting each other. The header is a break now, as
    a heading is; what the rows hold is still read."""

    def setUp(self):
        super().setUp()
        self.shipped = self.root / "System" / "templates" / "published.md"
        write(self.shipped, TestPublishedLedger.TEMPLATE.read_text(encoding="utf-8"))
        self.ledgers = {}
        for project, row in ((self.acme, "| sent 2026-10-03 | `261003 - Pricing memo.md` | `Pricing memo.md` | Dana | here |\n"),
                             (self.birch, "| sent 2026-10-14 | `261014 - Sizing.md` | `Sizing.md` | Theo | here |\n")):
            self.ledgers[project] = write(project / "Deliverables" / "published.md",
                                          self.shipped.read_text(encoding="utf-8") + row)

    def add_row(self, project, row):
        ledger = self.ledgers[project]
        ledger.write_text(ledger.read_text(encoding="utf-8") + row, encoding="utf-8")

    def test_first_rows_dated_alike_are_not_a_quotation(self):
        self.assertEqual([], self.walls())

    def test_so_is_a_thread_first_ledger(self):
        ledger = self.ledgers.pop(self.birch)
        moved = self.birch / "Threads" / "Market Sizing" / "Deliverables" / "published.md"
        write(moved, ledger.read_text(encoding="utf-8"))
        ledger.unlink()
        self.assertEqual([], self.walls())

    def test_eight_words_shared_inside_the_rows_are_still_refused(self):
        """Real wording in a ledger's own cells is still a quotation, however
        the rows are dated."""
        cell = "Nordic depot volumes split before the regional board handover"
        self.add_row(self.acme, "| sent 2026-10-05 | `261005 - Depots.md` | `Depots.md` | %s | here |\n" % cell)
        self.add_row(self.birch, "| sent 2026-10-16 | `261016 - Regions.md` | `Regions.md` | %s | here |\n" % cell)
        self.assertEqual({"Zones/Work/Acme Review/Deliverables/published.md",
                          "Zones/Work/Birch Entry/Deliverables/published.md"},
                         {f.path for f in self.walls()})

    def test_only_the_ledger_header_is_a_break(self):
        """Any other table's header still runs into its first row: a table
        lifted whole from a walled page is caught across that line."""
        header = "| Item | Region | Volume |\n|---|---|---|\n"
        row = "| Nordic depot | north | eleven thousand pallets |\n"
        self.assertTrue(check.runs(header + row) - check.runs(header) - check.runs(row))
        ledger = "| Date | File | Destination | Recipients | Authoritative |\n|---|---|---|---|---|\n"
        dated = "| sent 2026-10-03 | `a.md` | `b.md` | Dana | here |\n"
        self.assertEqual(check.runs(ledger) | check.runs(dated), check.runs(ledger + dated))

    @unittest.skipUnless(HAVE_GIT, "git is not installed")
    def test_committing_both_ledgers_passes_the_hook(self):
        texts = {ledger: ledger.read_text(encoding="utf-8") for ledger in self.ledgers.values()}
        for ledger in texts:
            ledger.unlink()
        _copy_tools(self.root)
        zone = self.root / "Zones" / "Work"
        _real_repo(zone)
        for ledger, text in texts.items():  # staged, not part of the first commit
            write(ledger, text)
        git(zone, "add", "-A")
        res = _run([sys.executable, self.root / "System" / "tools" / "check.py", "--staged", "--walls-only"], zone)
        self.assertEqual((0, ""), (res.returncode, res.stderr))


class TestCheckpointIsNotWording(WallCase):
    """#225: every checkpoint opens with the line its tool writes, the time it
    was written and a fixed sentence that no shared file holds, so two
    checkpoints in walled projects read as quoting each other on that line
    alone. What the tool writes is not read now, nor are an item's kind and
    id; the words of each item still are."""

    ACME = [{"kind": "considering", "text": "dropping tier three for the smaller accounts"},
            {"kind": "incomplete", "text": "the rebate column is half filled"}]
    BIRCH = [{"kind": "next", "text": "rerun the survey weighting for the coastal towns", "by": "user"},
             {"kind": "action", "text": "ask Theo for the census extract"}]

    def setUp(self):
        super().setUp()
        (self.root / "System" / "templates").mkdir(parents=True, exist_ok=True)  # what the tool takes for installed

    def note(self, project):
        thread = "Pricing" if project == self.acme else "Market Sizing"
        return project / "Threads" / thread / (thread + ".md")

    def tool(self, project, now, **fields):
        """`scaffold.py checkpoint`, run as a session runs it."""
        req = {"verb": "checkpoint", "zone": "Work", "project": project.name, "thread": self.note(project).parent.name}
        req.update(fields)
        done = subprocess.run([sys.executable, str(TOOLS / "scaffold.py"), "--root", str(self.root), "checkpoint",
                               "--now", now], input=json.dumps(req), capture_output=True, text=True, env=ENV)
        self.assertEqual("", done.stderr)
        return json.loads(done.stdout)

    def checkpoint(self, project, now, items):
        read = self.tool(project, now, read=True)
        reply = self.tool(project, now, base=read["base"], prev=read["key"], items=items)
        self.assertTrue(reply["wrote"], reply)

    def both(self, acme_at, birch_at, acme=ACME, birch=BIRCH):
        self.checkpoint(self.acme, acme_at, acme)
        self.checkpoint(self.birch, birch_at, birch)

    def test_two_checkpoints_are_not_a_quotation(self):
        for acme_at, birch_at in (("2026-03-14T14:32:10+01:00", "2026-03-14T14:32:10+01:00"),
                                  ("2026-03-14T14:32:10+01:00", "2026-03-20T09:05:00+01:00"),
                                  ("2026-03-14T14:32:10+01:00", "2026-05-02T17:40:00+02:00")):
            with self.subTest(acme=acme_at, birch=birch_at):
                for project in (self.acme, self.birch):
                    text = self.note(project).read_text(encoding="utf-8")
                    self.note(project).write_text(text.split("\n### Checkpoint\n")[0], encoding="utf-8")
                self.both(acme_at, birch_at)
                self.assertIn("Recorded since the resume point above", self.note(self.birch).read_text(encoding="utf-8"))
                self.assertEqual([], self.walls())

    def test_a_note_that_quotes_the_line_is_not_a_quotation_either(self):
        self.checkpoint(self.acme, "2026-03-14T14:32:10+01:00", self.ACME)
        line = next(l for l in self.note(self.acme).read_text(encoding="utf-8").splitlines()
                    if l.startswith("**Unconfirmed, "))
        write(self.birch / "Threads" / "Market Sizing" / "Notes.md", "Left as it was:\n\n%s\n" % line)
        self.assertEqual([], self.walls())

    def test_what_the_tool_writes_is_no_run_of_words(self):
        before = check.runs(self.note(self.acme).read_text(encoding="utf-8"))
        self.checkpoint(self.acme, "2026-03-14T14:32:10+01:00", [{"kind": "incomplete", "text": "half done"}])
        self.assertEqual(before, check.runs(self.note(self.acme).read_text(encoding="utf-8")))
        item = "the rebate column for the northern accounts is still half filled"
        self.assertEqual(check.runs(item), check.runs("- **Incomplete** %s <!-- i -->\n" % item))

    def test_eight_words_quoted_from_a_walled_meeting_in_an_item_are_refused(self):
        write(self.meetings / "wiki" / "sources" / "260314-birch-call.md",
              meeting_page("Work", "[birch]", "Birch call").replace("Decisions.", SECRET + "."))
        self.both("2026-03-14T14:32:10+01:00", "2026-03-14T14:32:10+01:00",
                  acme=[{"kind": "considering", "text": SECRET.lower()}])
        self.assertEqual({"Zones/Work/Acme Review/Threads/Pricing/Pricing.md"}, {f.path for f in self.walls()})

    def test_eight_words_quoted_from_a_walled_project_file_in_an_item_are_refused(self):
        write(self.birch / "Threads" / "Market Sizing" / "Notes.md", SECRET + "\n")
        self.both("2026-03-14T14:32:10+01:00", "2026-03-20T09:05:00+01:00",
                  acme=[{"kind": "incomplete", "text": "the clause that says " + SECRET.lower()}])
        self.assertEqual({"Zones/Work/Acme Review/Threads/Pricing/Pricing.md",
                          "Zones/Work/Birch Entry/Threads/Market Sizing/Notes.md"},
                         {f.path for f in self.walls()})

    @unittest.skipUnless(HAVE_GIT, "git is not installed")
    def test_committing_both_checkpoints_passes_the_hook(self):
        before = {self.note(p): self.note(p).read_text(encoding="utf-8") for p in (self.acme, self.birch)}
        self.both("2026-03-14T14:32:10+01:00", "2026-03-14T16:05:00+01:00")
        after = {note: note.read_text(encoding="utf-8") for note in before}
        for note, text in before.items():
            write(note, text)
        _copy_tools(self.root)
        zone = self.root / "Zones" / "Work"
        _real_repo(zone)
        for note, text in after.items():  # staged, not part of the first commit
            write(note, text)
        git(zone, "add", "-A")
        res = _run([sys.executable, self.root / "System" / "tools" / "check.py", "--staged", "--walls-only"], zone)
        self.assertEqual((0, ""), (res.returncode, res.stderr))


class TestChangelogIsCommon(WallCase):
    """#91: `System/garrick-changelog.md` is Garrick's published release notes,
    so two notes that describe a feature in its words are not quoting each other."""

    NOTES = ("# Garrick 0.25.0\n\n- A row of the published ledger is never deleted, because the row is "
             "the record of what left the workspace, and drift.py reads it without comparing it again.\n")
    BORROWED = ("# How this works\n\nA row of the published ledger is never deleted, because the row is "
                "the record of what left the workspace, and drift.py reads it without comparing it again.\n")

    def borrow(self):
        write(self.acme / "Threads" / "Pricing" / "How it works.md", self.BORROWED)
        write(self.birch / "Threads" / "Market Sizing" / "How it works.md", self.BORROWED)

    def test_wording_borrowed_from_the_release_notes_is_not_a_leak(self):
        write(self.root / "System" / "garrick-changelog.md", self.NOTES)
        self.borrow()
        self.assertEqual([], self.walls())

    def test_the_same_wording_without_the_release_notes_is_a_quotation(self):
        self.borrow()
        self.assertEqual({"Zones/Work/Acme Review/Threads/Pricing/How it works.md",
                          "Zones/Work/Birch Entry/Threads/Market Sizing/How it works.md"},
                         {f.path for f in self.walls()})


class PersonPartyCase(WallCase):
    """A party that is a person, walled from Birch & Co, so that a note in the
    Birch project is the one being checked."""

    PARTY = "| %s | Advisory client, one to one | Work | `%s` | |"
    WALL = "| `%s` | `birch` | Her own affairs are not the market study |"

    def party(self, name, tag, near_side_row=False, role="Herself"):
        """Add a party that is `name`, tagged `tag`, walled from `birch`, with
        a People row of her own and, when asked, one under `birch` too."""
        path = self.root / "System" / "context.md"
        text = path.read_text(encoding="utf-8")
        text = text.replace("| Birch & Co |", (self.PARTY % (name, tag)) + "\n| Birch & Co |", 1)
        text = text.replace("| `acme` | `birch` | Competitors, and both are clients |",
                            "| `acme` | `birch` | Competitors, and both are clients |\n" + self.WALL % tag, 1)
        rows = "| %s | `%s` | %s |" % (name, tag, role)
        if near_side_row:
            rows += "\n| %s | `birch` | In the market study, as herself |" % name
        text = text.replace("| Theo Marsh | `birch` | Managing partner |",
                            "| Theo Marsh | `birch` | Managing partner |\n" + rows, 1)
        path.write_text(text, encoding="utf-8")

    def note(self, text):
        return write(self.birch / "Threads" / "Market Sizing" / "Notes.md", text)


class TestPartyWhoIsAPerson(PersonPartyCase):
    """#98: a party that is a person, Rowan Keeler (`keeler`), who also takes
    part in a walled project as herself. The People row under that project's
    party clears her full name, and has to clear the party's tag with it, since
    the tag here is her surname.

    `tests/test_wall_gaps.py` covers the rule as well, from the other side of
    the wall and on the `GapCase` fixture. These tests are not that test over
    again: they run from the Birch side on `WallCase`, and they add the two
    cases that one does not reach, a tag that is not the party's name and the
    commit passing the installed hook."""

    JOINED = "Rowan Keeler joined the pilot, and wants the summary by Friday.\n"

    def test_the_people_row_clears_her_name_and_the_tag_with_it(self):
        self.party("Rowan Keeler", "keeler", near_side_row=True)
        self.note(self.JOINED)
        self.assertEqual([], self.walls())
        self.note("Keeler joined the pilot, and wants the summary by Friday.\n")
        self.assertEqual([], self.walls())

    def test_without_the_near_side_row_the_same_note_is_still_refused(self):
        self.party("Rowan Keeler", "keeler")
        self.note(self.JOINED)
        found = self.walls()
        self.assertEqual(1, len(found), found)
        self.assertEqual("Zones/Work/Birch Entry/Threads/Market Sizing/Notes.md", found[0].path)
        self.assertIn("names Rowan Keeler, or one of its people", found[0].message)
        self.assertIn("wall stands between birch and keeler", found[0].message)

    def test_an_unrelated_near_side_name_holding_the_word_clears_nothing(self):
        """The containing name has to be a form of the walled party itself. An
        analyst called Anna Birch at Acme does not make "Birch" safe to write."""
        path = self.root / "System" / "context.md"
        path.write_text(path.read_text(encoding="utf-8").replace(
            "| Dana Whitlock | `acme` | Head of procurement |",
            "| Dana Whitlock | `acme` | Head of procurement |\n| Anna Birch | `acme` | Analyst |", 1),
            encoding="utf-8")
        write(self.acme / "Threads" / "Pricing" / "Notes.md", "Birch is pricing below us.\n")
        [found] = self.walls()
        self.assertEqual("Zones/Work/Acme Review/Threads/Pricing/Notes.md", found.path)
        self.assertIn('names Birch & Co (as "birch"), or one of its people', found.message)

    @unittest.skipUnless(HAVE_GIT, "git is not installed")
    def test_committing_her_name_passes_the_hook(self):
        self.party("Rowan Keeler", "keeler", near_side_row=True)
        _copy_tools(self.root)
        zone = self.root / "Zones" / "Work"
        _real_repo(zone)
        self.note(self.JOINED)
        git(zone, "add", "-A")
        res = _run([sys.executable, self.root / "System" / "tools" / "check.py", "--staged", "--walls-only"], zone)
        self.assertEqual((0, ""), (res.returncode, res.stderr))


class TestWhichFormIsNamed(PersonPartyCase):
    """#98 again, the part of it that says which form matched. A finding has to
    read as a tag hit only where the tag is what the text holds."""

    def test_the_most_telling_form_is_named_not_the_first_alphabetically(self):
        """`rossi` sorts before `zeta rossi`, so trying the forms in
        alphabetical order calls a note that writes her name in full a tag
        hit. The forms are tried longest first for that reason."""
        self.party("Zeta Rossi", "rossi")
        self.note("Zeta Rossi joined the pilot, and wants the summary by Friday.\n")
        [found] = self.walls()
        self.assertIn("names Zeta Rossi, or one of its people", found.message)
        self.assertNotIn('(as "', found.message)

    def test_a_tag_hit_says_so(self):
        self.party("Zeta Rossi", "rossi")
        self.note("Rossi joined the pilot, and wants the summary by Friday.\n")
        [found] = self.walls()
        self.assertIn('names Zeta Rossi (as "rossi"), or one of its people', found.message)

    def test_nothing_is_said_when_the_tag_reads_as_the_name_does(self):
        """`names Keeler (as "keeler")` tells nobody anything."""
        self.party("Keeler", "keeler", role="Herself, one name")
        self.note("Keeler joined the pilot, and wants the summary by Friday.\n")
        [found] = self.walls()
        self.assertIn("names Keeler, or one of its people", found.message)
        self.assertNotIn('(as "', found.message)

    def test_names_hit_is_a_boolean_and_name_hit_gives_the_form(self):
        """Two callers, two questions: the anonymous check asks whether a
        deliverable names anybody, the wall check asks which form it holds."""
        forms = [(False, "zeta rossi"), (False, "rossi")]
        self.assertIs(True, check.names_hit("Zeta Rossi joined the pilot", forms))
        self.assertIs(False, check.names_hit("nobody of that name", forms))
        self.assertEqual("zeta rossi", check.name_hit("Zeta Rossi joined the pilot", forms))
        self.assertIsNone(check.name_hit("nobody of that name", forms))


if __name__ == "__main__":
    unittest.main()
