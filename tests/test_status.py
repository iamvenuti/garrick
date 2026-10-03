"""The optional status page, extras/status/, against a fictional workspace.

    python3 -m unittest discover -s tests

The page must show names, parties, dates, counts, check findings and link
targets and never the body of a note, load nothing from the network, and write
nothing but itself.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import html as htmllib
import importlib.util
import io
import json
import os
import plistlib
import re
import shlex
import shutil
import sys
import tempfile
import time
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import build_workspace, meeting_page, project_hub, thread_note, write  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
STATUS = REPO / "extras" / "status" / "status.py"


def _load():
    spec = importlib.util.spec_from_file_location("garrick_status", STATUS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


status = _load()


def stamp(t):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))


def cards(html):
    """Every thread row's card, by thread name, as the page's script reads it."""
    out = {}
    for raw in re.findall(r'class="thread"[^>]*data-card="([^"]*)"', html):
        data = json.loads(htmllib.unescape(raw))
        out[(data["p"], data["n"])] = data
    return out


def thread_order(html, anchor='id="zone-work"'):
    """Thread names in the order a zone lists them, live ones or its Parked fold."""
    start = html.index(anchor)
    block = html[start:html.index("</details>", start)]
    if anchor.startswith('id="zone-'):
        block = block.split('<details class="parked"')[0]
    return [json.loads(htmllib.unescape(raw))["n"] for raw in re.findall(r'data-card="([^"]*)"', block)]


def luminance(hexa):
    def lin(c):
        c = int(c, 16) / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    h = hexa.lstrip("#")
    return 0.2126 * lin(h[0:2]) + 0.7152 * lin(h[2:4]) + 0.0722 * lin(h[4:6])


def contrast(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


class StatusCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name).resolve()
        self.root = base / "Workspace"
        build_workspace(self.root)
        self.jobs = base / "jobs"
        self.jobs.mkdir()
        self.now = dt.datetime.now()

    def tearDown(self):
        self._tmp.cleanup()

    def page(self, **kw):
        return status.build(self.root, now=self.now, folder=self.jobs, **kw)


class TestMetadataOnly(StatusCase):
    def test_names_parties_and_dates(self):
        html = self.page()
        for text in ("Work", "Personal", "Acme Review", "Pricing", "Market Sizing", ">acme<", ">birch<"):
            self.assertIn(text, html)

    def test_never_note_content(self):
        note = self.root / "Zones" / "Work" / "Acme Review" / "Threads" / "Pricing" / "Pricing.md"
        note.write_text(thread_note("Acme Review", "Pricing", "acme", "The renewal floor is a private figure."))
        html = self.page()
        self.assertNotIn("private figure", html)
        self.assertNotIn("Drafting", html)          # the Where it stands line
        self.assertNotIn("Draws on", html)          # the words around a link
        bare = self.page(show_graph=False)
        self.assertNotIn("private figure", bare)
        self.assertNotIn("260310-acme-kickoff", bare)  # without the graph, not even a link's target
        self.assertNotIn("graph-data", bare)

    def test_done_threads_are_counted_not_listed(self):
        note = self.root / "Zones" / "Work" / "Birch Entry" / "Threads" / "Market Sizing" / "Market Sizing.md"
        note.write_text(thread_note("Birch Entry", "Market Sizing", "birch", status="done"))
        html = self.page()
        self.assertNotIn(">Market Sizing<", html)
        self.assertIn("1 done", html)


def graph_data(html):
    start = html.index('id="graph-data">') + len('id="graph-data">')
    return json.loads(html[start:html.index("</script>", start)])


class TestGraph(StatusCase):
    def node(self, data, name):
        return next(i for i, n in enumerate(data["nodes"]) if n["n"] == name)

    def test_a_link_becomes_a_line(self):
        data = graph_data(self.page())
        pricing, kickoff = self.node(data, "Pricing"), self.node(data, "Acme kick-off")
        self.assertIn([min(pricing, kickoff), max(pricing, kickoff)], data["edges"])

    def test_links_resolve_by_path_suffix_and_name(self):
        write(self.root / "Zones" / "Work" / "Birch Entry" / "Threads" / "Market Sizing" / "Market Sizing.md",
              thread_note("Birch Entry", "Market Sizing", "birch", "See [[Meetings/wiki/sources/260312-birch-kickoff|the kick-off]]."))
        data = graph_data(self.page())
        a, b = self.node(data, "Market Sizing"), self.node(data, "Birch kick-off")
        self.assertIn([min(a, b), max(a, b)], data["edges"])

    def test_names_and_kinds_only(self):
        html = self.page()
        data = graph_data(html)
        kinds = dict((i, k) for i, k in data["kinds"])
        by_name = {n["n"]: kinds[n["k"]] for n in data["nodes"]}
        self.assertEqual("project", by_name["Acme Review"])
        self.assertEqual("thread", by_name["Pricing"])
        self.assertEqual("meeting", by_name["Acme kick-off"])
        self.assertEqual({"n", "k", "z", "p", "t", "d", "s", "c", "h", "w", "u"}, set().union(*(n.keys() for n in data["nodes"])))
        self.assertNotIn("Decisions.", html)

    def test_mail_pages_have_a_kind_of_their_own(self):
        write(self.root / "Wikis" / "Meetings" / "wiki" / "sources" / "260314-acme-forecast.md",
              meeting_page("Work", "[acme]", "Pallet forecast").replace("type: meeting", "type: email"))
        html = self.page()
        data = graph_data(html)
        kinds = dict((i, k) for i, k in data["kinds"])
        self.assertEqual("mail", kinds[data["nodes"][self.node(data, "Pallet forecast")]["k"]])
        self.assertEqual("meeting", kinds[data["nodes"][self.node(data, "Acme kick-off")]["k"]])
        colour = dict((label, c) for (_, label, c) in status.KINDS)["mail"].lower()
        rings = re.search(r"--warning:(#[0-9a-f]{6});--critical:(#[0-9a-f]{6})", status.CSS).groups()
        self.assertNotIn(colour, set(rings) | {status.BRAND.lower()})          # not amber, red or the brand blue
        self.assertEqual(len(status.KINDS), len({c.lower() for _, _, c in status.KINDS}))   # and no other kind's
        self.assertIn('<i style="background:%s"></i>mail</span>' % dict((label, c) for (_, label, c) in status.KINDS)["mail"], html)

    def test_inboxes_raw_and_catalogues_stay_out(self):
        write(self.root / "Zones" / "Work" / "Inbox" / "Note.md", "# A dropped note\n")
        names = {n["n"] for n in graph_data(self.page())["nodes"]}
        self.assertNotIn("A dropped note", names)
        self.assertNotIn("Note", names)
        self.assertNotIn("index", names)
        self.assertNotIn("260310-acme-kickoff.txt", names)

    def test_projects_and_threads_named_like_skipped_folders_stay(self):
        work = self.root / "Zones" / "Work"
        write(work / "Archive" / "Archive.md", project_hub("Work", "Archive", "acme"))
        write(work / "Archive" / "Threads" / "raw" / "raw.md", thread_note("Archive", "raw", "acme"))
        write(work / "Archive" / "Threads" / "Generated" / "Generated.md", thread_note("Archive", "Generated", "acme"))
        write(work / "Acme Review" / "Deliverables" / "archive" / "Old memo.md", "# Old memo\n")
        write(work / "Acme Review" / "Threads" / "Pricing" / "Archive" / "Pricing v1.md", "# Pricing v1\n")
        names = {n["n"] for n in graph_data(self.page())["nodes"]}
        self.assertTrue({"Archive", "raw", "Generated"} <= names)
        self.assertFalse({"Old memo", "Pricing v1"} & names)        # an archive folder below them still stays out

    def test_a_link_in_a_table_keeps_its_line(self):
        write(self.root / "Zones" / "Work" / "Birch Entry" / "Threads" / "Market Sizing" / "Market Sizing.md",
              thread_note("Birch Entry", "Market Sizing", "birch",
                          "| Source | Use |\n|---|---|\n| [[260312-birch-kickoff\\|the kick-off]] | sizing |"))
        data = graph_data(self.page())
        a, b = self.node(data, "Market Sizing"), self.node(data, "Birch kick-off")
        self.assertIn([min(a, b), max(a, b)], data["edges"])

    def test_threads_carry_the_phrase_to_say(self):
        data = graph_data(self.page())
        self.assertEqual("Pricing", data["nodes"][self.node(data, "Pricing")]["w"])

    def test_todo_and_instructions_stay_out(self):
        data = graph_data(self.page())
        names = {n["n"] for n in data["nodes"]}
        self.assertFalse({"Todo", "AGENTS"} & names)
        self.assertNotIn("open actions", [label for _, label in data["kinds"]])

    def test_legend_lists_only_drawn_kinds(self):
        html = self.page()
        data = graph_data(html)
        self.assertEqual(sorted({n["k"] for n in data["nodes"]}), [i for i, _ in data["kinds"]])
        legend = html[html.index('class="legend glegend"'):]
        legend = legend[:legend.index("</div>")]
        self.assertEqual([str(i) for i, _ in data["kinds"]], re.findall(r'data-k="(\d+)"', legend))
        self.assertIn("drawn[s.dataset.k]", status.GRAPH_JS)    # and in the browser, only what the view draws

    def test_parked_threads_and_their_notes_are_marked(self):
        sizing = self.root / "Zones" / "Work" / "Birch Entry" / "Threads" / "Market Sizing"
        write(sizing / "Market Sizing.md", thread_note("Birch Entry", "Market Sizing", "birch", status="parked"))
        write(sizing / "Interviews.md", "# Interviews\n")
        data = graph_data(self.page())
        held = {n["n"] for n in data["nodes"] if n["s"]}
        # Birch Entry has no live thread left, so the project is parked with it.
        self.assertEqual({"Market Sizing", "Interviews", "Birch Entry"}, held)
        self.assertNotIn("Acme Review", held)

    def test_parked_toggle(self):
        html = self.page()
        self.assertIn('id="gpark"', html)
        self.assertIn("garrick-graph-parked", status.GRAPH_JS)
        self.assertIn("(parked||!n.s)", status.GRAPH_JS)              # hidden unless asked for
        self.assertIn("if(m.s&&!parked){parked=true", status.GRAPH_JS)  # following a link to one shows them
        # Reset view clears every garrick- key but the theme, the toggle among them.
        self.assertIn("k.indexOf('garrick-')===0&&k!=='garrick-status-theme'", status.LAYOUT_JS)

    def test_projects_carry_their_phrase(self):
        data = graph_data(self.page())
        self.assertEqual("Acme Review", data["nodes"][self.node(data, "Acme Review")]["w"])
        write(self.root / "Zones" / "Personal" / "House" / "Threads" / "Acme Review" / "Acme Review.md",
              thread_note("House", "Acme Review", ""))
        write(self.root / "Zones" / "Personal" / "House" / "House.md", project_hub("Personal", "House", ""))
        data = graph_data(self.page())
        hub = next(n for n in data["nodes"] if n["n"] == "Acme Review" and n["h"])
        self.assertEqual("", hub["w"])          # "open Acme Review" would reach the thread, so no phrase

    def test_titles_cannot_close_the_data(self):
        note = self.root / "Zones" / "Work" / "Acme Review" / "Threads" / "Pricing" / "Pricing.md"
        note.write_text(thread_note("Acme Review", "Pricing").replace("title: Pricing", "title: <!--<script>&</script>"))
        html = self.page()
        self.assertNotIn("<!--", html)
        self.assertEqual(2, html.count("</script>"))          # the graph's data and the page's script, no more
        self.assertEqual(html.count("<script"), html.count("</script>"))
        self.assertIn("<!--<script>&</script>", {n["n"] for n in graph_data(html)["nodes"]})
        self.assertTrue(html.rstrip().endswith("</script></body></html>"))

    def test_the_graph_fills_its_card(self):
        js = status.GRAPH_JS
        self.assertNotIn("Math.min(W,H)", js)                       # no circle scaled into the shorter side
        self.assertIn("function spots(", js)                        # each place has a spot along the card
        self.assertIn("A[p]=asp>=1?[x,0]:[0,x]", js)                # a row when a few places fit across it
        self.assertIn("k*asp+(asp-1)*rm", js)                       # else an ellipse in the card's proportions
        # One scale for both directions, fitted to the box the notes fill, and centred.
        self.assertIn("k=Math.min((W-l-r)/Math.max(1,b[1]-b[0]),(H-t-u)/Math.max(1,b[3]-b[2]),2.2)", js)
        self.assertIn("theta=SWAY*Math.sin(phase)", js)             # it sways, so a wide fit holds while it moves
        self.assertNotIn("Math.random", js)                         # seeded, so the same notes lie the same way

    def test_names_do_not_cover_each_other(self):
        js = status.GRAPH_JS
        # Placed in order: the note in focus, its links, projects, threads, the rest.
        self.assertIn("var w=n===f?0:f&&near[n.i]?1:n.h?2:n.c?3:scale>1.4?4:-1", js)
        self.assertIn("if(free(b)){got=tries[i]", js)                 # below, above, then beside the note
        self.assertIn("if(got<0&&(n===f||n.h)){got=0", js)            # the focus and projects are never left out
        self.assertIn("return out.reverse()", js)                     # the most wanted is drawn last, on top

    def test_large_workspaces_stay_quick(self):
        # Measured in headless Chrome on a generated workspace of 2,000 notes with
        # Everything chosen: the first frame came after 4.9 s with every pair
        # compared, and after 0.6 s with this. Small graphs keep the exact sum.
        js = status.GRAPH_JS
        self.assertIn("var BIG=400;", js)
        self.assertIn("if(V.length>BIG){var t=tree();V.forEach(function(n){shove(t,n,S)})}", js)
        self.assertIn("if(q.s*q.s<.81*d2)", js)                       # a far group pushes as one, from its centre
        self.assertIn("for(var i=0;i<(V.length>BIG?160:400);i++)step();", js)

    def test_a_still_graph_stops_drawing(self):
        # Measured in headless Chrome on the demo with rotation paused: no frame
        # drawn in two quiet seconds once the graph settled, where it drew 120.
        js = status.GRAPH_JS
        self.assertIn("if(moving)requestAnimationFrame(frame);else running=false", js)
        for wakes in ("setPointerCapture(e.pointerId);wake()", "if(down||h.n!==hover)wake()", "scale*=k;wake()",
                      "function close(){sel=null;pop.hidden=true;wake()}", "auto=true;theta=phase=0;wake()"):
            self.assertIn(wakes, js)
        self.assertIn("new MutationObserver(recolor)", js)            # a still graph follows the theme switch

    def test_no_field_the_layout_writes(self):
        layout = {"x", "y", "vx", "vy", "ax", "ay", "r", "i", "adj", "deg", "lp", "lw"}
        for n in graph_data(self.page())["nodes"]:
            self.assertEqual(set(), layout & set(n))


class TestLayout(StatusCase):
    def test_cards_can_move_and_hide(self):
        html = self.page()
        self.assertIn('data-slot="top"', html)
        self.assertGreaterEqual(html.count('class="grip"'), 6)
        self.assertIn('id="reset-view"', html)

    def test_right_column_is_not_right_aligned(self):
        html = self.page()
        self.assertIn('class="slot stack right" data-slot="right"', html)
        self.assertIsNone(re.search(r"(^|[\s,}>])\.r[\s{,:.\[]", status.CSS))  # .r styles table cells only
        self.assertIn("th.r,td.r{text-align:right", status.CSS)

    def test_needs_attention_is_pinned(self):
        write(self.root / "Zones" / "Work" / "Inbox" / "Quote.eml", "Subject: quote\n\nhello\n")
        html = self.page()
        start = html.index('id="attention"')
        self.assertNotIn('class="grip"', html[start:html.index("</details>", start)])


class TestSelfContained(StatusCase):
    def test_nothing_from_the_network(self):
        html = self.page()
        self.assertNotIn("http://", html)
        self.assertNotIn("https://", html)
        self.assertNotIn("<script src", html)
        links = re.findall(r"<link[^>]*>", html)
        self.assertEqual(1, len(links))                      # the tab icon, carried in the page
        self.assertIn('rel="icon" type="image/svg+xml" href="data:image/svg+xml,', links[0])
        self.assertNotRegex(html, r"<[^>]+\ssrc=")

    def test_file_links_by_default(self):
        html = self.page()
        self.assertIn("file://", html)
        self.assertNotIn("obsidian://", html)

    def test_obsidian_links_on_request(self):
        html = self.page(vault="My Work")
        self.assertIn("obsidian://open?vault=My%20Work&amp;file=Zones/Work/Acme%20Review/Threads/Pricing/Pricing", html)

    def test_obsidian_links_a_symlinked_note_by_its_place_in_the_vault(self):
        outside = Path(self._tmp.name).resolve() / "Elsewhere" / "Shared notes.md"
        write(outside, "# Shared notes\n")
        os.symlink(str(outside), str(self.root / "Zones" / "Work" / "Acme Review" / "Threads" / "Pricing" / "Shared notes.md"))
        (self.jobs / "brief.heartbeat.json").write_text(json.dumps({"job": "brief", "finished": stamp(time.time()), "exit": 0}))
        html = self.page(vault="My Work")
        node = next(n for n in graph_data(html)["nodes"] if n["n"] == "Shared notes")
        self.assertEqual("obsidian://open?vault=My%20Work&file=Zones/Work/Acme%20Review/Threads/Pricing/Shared%20notes", node["u"])
        self.assertIn('href="%s"' % (self.jobs / "brief.log").as_uri(), html)   # a job's log is outside the vault: a file link

    def test_builds_without_git(self):
        (self.root / ".git").mkdir()
        empty = Path(self._tmp.name) / "no-tools"
        empty.mkdir()
        with mock.patch.dict(os.environ, {"PATH": str(empty)}):
            self.run_main()
        self.assertTrue((self.root / "System" / "generated" / "status.html").is_file())

    def run_main(self, *extra):
        old = os.environ.get("GARRICK_JOBS_DIR")
        os.environ["GARRICK_JOBS_DIR"] = str(self.jobs)
        err = io.StringIO()
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                status.main(["--workspace", str(self.root), *extra])
        finally:
            if old is None:
                os.environ.pop("GARRICK_JOBS_DIR", None)
            else:
                os.environ["GARRICK_JOBS_DIR"] = old
        return err.getvalue()

    def test_writes_nothing_but_itself(self):
        before = set(str(p.relative_to(self.root)) for p in self.root.rglob("*"))
        self.run_main()
        after = set(str(p.relative_to(self.root)) for p in self.root.rglob("*"))
        self.assertEqual({"System/generated", "System/generated/status.html"}, after - before)
        self.assertEqual(set(), before - after)
        self.assertEqual([], list(self.jobs.iterdir()))

    def test_warns_when_written_elsewhere_in_the_workspace(self):
        err = self.run_main("--out", str(self.root / "Zones" / "Work" / "status.html"))
        self.assertIn("not in System/generated/", err)

    @unittest.skipUnless(shutil.which("git"), "git is not installed")
    def test_names_the_missing_ignore_line(self):
        from fixtures import git_init
        git_init(self.root)
        write(self.root / ".gitignore", "Zones/\nWikis/\n")
        self.assertIn("does not name System/generated/", self.run_main())
        write(self.root / ".gitignore", "Zones/\nWikis/\nSystem/generated/\n")
        self.assertNotIn("System/generated", self.run_main())


class TestParkedAndCopy(StatusCase):
    def park(self):
        note = self.root / "Zones" / "Work" / "Birch Entry" / "Threads" / "Market Sizing" / "Market Sizing.md"
        note.write_text(thread_note("Birch Entry", "Market Sizing", "birch", status="parked"))

    def test_parked_is_folded_away_and_not_live(self):
        self.park()
        html = self.page()
        self.assertIn('id="parked-work"', html)
        self.assertIn("1 live · 1 parked", html)
        card = cards(html)[("Birch Entry", "Market Sizing")]
        self.assertEqual((1, "Market Sizing"), (card["s"], card["w"]))   # the card offers "wake", not "park"
        self.assertEqual(["Market Sizing"], thread_order(html, 'id="parked-work"'))

    def test_cards_carry_the_phrase_to_say(self):
        html = self.page()
        card = cards(html)[("Acme Review", "Pricing")]
        self.assertEqual((0, "Pricing"), (card["s"], card["w"]))          # "open Pricing" and "park Pricing"
        self.assertIn("status.py", html)

    def test_shared_names_are_said_with_their_project(self):
        write(self.root / "Zones" / "Work" / "Birch Entry" / "Threads" / "Pricing" / "Pricing.md",
              thread_note("Birch Entry", "Pricing", "birch"))
        found = cards(self.page())
        self.assertEqual("Acme Review, Pricing", found[("Acme Review", "Pricing")]["w"])
        self.assertEqual("Birch Entry, Pricing", found[("Birch Entry", "Pricing")]["w"])

    def test_a_shared_project_name_is_said_with_its_zone(self):
        for zone in ("Work", "Personal"):
            write(self.root / "Zones" / zone / "House" / "House.md", project_hub(zone, "House", ""))
            write(self.root / "Zones" / zone / "House" / "Threads" / "Kitchen" / "Kitchen.md", thread_note("House", "Kitchen", ""))
        write(self.root / "Zones" / "Personal" / "House" / "Threads" / "Roof" / "Roof.md", thread_note("House", "Roof", ""))
        html = self.page()
        rows = [json.loads(htmllib.unescape(raw)) for raw in re.findall(r'class="thread"[^>]*data-card="([^"]*)"', html)]
        said = {(c["z"], c["p"], c["n"]): c["w"] for c in rows}
        self.assertEqual("Work, House, Kitchen", said[("Work", "House", "Kitchen")])
        self.assertEqual("Personal, House, Kitchen", said[("Personal", "House", "Kitchen")])
        self.assertEqual("Roof", said[("Personal", "House", "Roof")])        # unique, so said alone
        nodes = {(n["z"], n["n"]): n["w"] for n in graph_data(html)["nodes"] if n["n"] == "Kitchen"}
        self.assertEqual({("Work", "Kitchen"): "Work, House, Kitchen", ("Personal", "Kitchen"): "Personal, House, Kitchen"}, nodes)

    def test_buttons_only_copy(self):
        html = self.page()
        self.assertNotIn("shortcuts://", html)
        self.assertNotIn("<form", html)
        for js in (status.PANEL_JS, status.JS, status.GRAPH_JS):
            self.assertNotIn("fetch(", js)
            self.assertNotIn("XMLHttpRequest", js)
            self.assertNotIn("location.href=", js.replace("location.href=h.n.u", ""))  # double-click opens the note itself


class TestThreadCards(StatusCase):
    def test_rows_carry_a_card_not_buttons(self):
        html = self.page()
        start = html.index('<div class="zones">')
        block = html[start:html.index('<div class="legend">', start)]
        self.assertNotIn("<button", block)
        self.assertNotIn("data-tip", block)
        self.assertEqual({("Acme Review", "Pricing"), ("Birch Entry", "Market Sizing")}, set(cards(html)))

    def test_a_card_carries_names_tags_dates_status_and_phrases_only(self):
        note = self.root / "Zones" / "Work" / "Acme Review" / "Threads" / "Pricing" / "Pricing.md"
        note.write_text(thread_note("Acme Review", "Pricing", "acme", "The renewal floor is a private figure."))
        card = cards(self.page(now=dt.datetime(2026, 3, 11, 9, 0)))[("Acme Review", "Pricing")]
        self.assertEqual({"n", "kl", "z", "p", "t", "d", "s", "w", "h", "u", "pu"}, set(card))
        self.assertEqual(("Pricing", "thread", "Work", "Acme Review", ["acme"], 10, 0, "Pricing", 0),
                         tuple(card[k] for k in ("n", "kl", "z", "p", "t", "d", "s", "w", "h")))
        self.assertTrue(card["u"].startswith("file://") and card["u"].endswith("/Pricing/Pricing.md"))
        self.assertTrue(card["pu"].endswith("/Acme%20Review/Acme%20Review.md"))
        self.assertNotIn("private figure", json.dumps(card))

    def page(self, **kw):
        return status.build(self.root, folder=self.jobs, **dict({"now": self.now}, **kw))

    def test_one_helper_builds_both_sets_of_actions(self):
        # The graph panel and the thread card draw their actions from Panel.acts
        # and their heading from Panel.head; neither builds a button of its own.
        self.assertEqual(1, status.PANEL_JS.count("function acts("))
        for label in (">Open</a>", ">Open project</a>", "Copy “", "'open '", "'wake '", "'park '"):
            self.assertIn(label, status.PANEL_JS)
        for js in (status.JS, status.GRAPH_JS):
            self.assertIn("Panel.head(o)+Panel.acts(o)", js)
            self.assertNotIn("data-copy=", js)
            self.assertNotIn('class="act"', js)

    def test_the_card_stays_reachable(self):
        # What a card needs so the pointer can reach it on a scrolled page.
        self.assertIn(".tcard{position:fixed", status.CSS)
        self.assertNotRegex(status.CSS, r"\.tcard\{[^}]*position:absolute")
        self.assertIn("y=b.bottom-1", status.JS)           # overlaps its row by a pixel
        self.assertIn("350", status.JS)                     # the dwell before another row takes over
        self.assertIn("tc.addEventListener('mouseenter'", status.JS)
        self.assertIn("'focusin'", status.JS)
        self.assertIn("'Escape'", status.JS)
        self.assertIn("document.addEventListener('click'", status.JS)   # copies inside a card work

    def test_threads_sorted_by_name(self):
        acme = self.root / "Zones" / "Work" / "Acme Review" / "Threads"
        write(acme / "Zebra" / "Zebra.md", thread_note("Acme Review", "Zebra").replace("updated: 2026-03-01", "updated: 2026-03-09"))
        write(acme / "alpha" / "alpha.md", thread_note("Acme Review", "alpha").replace("updated: 2026-03-01", "updated: 2026-01-09"))
        write(acme / "beta" / "beta.md", thread_note("Acme Review", "beta", status="parked"))
        write(acme / "Aardvark" / "Aardvark.md", thread_note("Acme Review", "Aardvark", status="parked"))
        html = self.page()
        self.assertEqual(["alpha", "Market Sizing", "Pricing", "Zebra"], thread_order(html))
        self.assertEqual(["Aardvark", "beta"], thread_order(html, 'id="parked-work"'))


class TestPanels(StatusCase):
    def test_inbox_waiting(self):
        write(self.root / "Zones" / "Work" / "Inbox" / "Quote.eml", "Subject: quote\n\nhello\n")
        html = self.page()
        self.assertIn("1 waiting", html)
        self.assertIn("1 item waiting in the inboxes", html)

    def test_open_actions_skip_the_placeholder_and_done(self):
        write(self.root / "Zones" / "Work" / "Todo.md",
              "# Work\n\n## Inbox\n\n- [ ] <action> · <project or person> · <date>\n- [ ] Send the memo · Acme · 3 March\n\n## Done\n\n- [ ] stray\n")
        html = self.page()
        self.assertIn('<span class="num">1</span>', html)

    def test_no_check_tool_is_said_plainly(self):
        self.assertIn("check.py", self.page())

    def test_check_runs_when_present(self):
        tools = self.root / "System" / "tools"
        shutil.copytree(REPO / "template" / "System" / "tools", tools, dirs_exist_ok=True)
        html = self.page()
        self.assertIn('id="checks"', html)
        self.assertNotIn("did not run", html)


class TestJobs(StatusCase):
    def heartbeat(self, code=0):
        now = self.now.timestamp()
        (self.jobs / "brief.heartbeat.json").write_text(json.dumps(
            {"job": "brief", "finished": stamp(now - 60), "exit": code, "seconds": 30, "items": 2, "idle_days": 0}))

    def test_no_jobs_no_panel(self):
        self.assertNotIn('id="jobs"', self.page())

    def test_day_that_ended_failed_is_red(self):
        self.heartbeat(0)
        t = self.now.timestamp() - 2 * 86400
        (self.jobs / "brief.log").write_text(
            "===== %s  brief  exit 0  (30s) =====\n\n===== %s  brief  exit 4  (5s) =====\n\n" % (stamp(t), stamp(t + 600)))
        html = self.page()
        self.assertIn('id="jobs"', html)
        self.assertIn('class="critical" tabindex="0"', html)

    def test_day_that_recovered_is_amber(self):
        self.heartbeat(0)
        t = self.now.timestamp() - 2 * 86400
        (self.jobs / "brief.log").write_text(
            "===== %s  brief  exit 4  (5s) =====\n\n===== %s  brief  exit 0  (30s) =====\n\n===== %s  brief  exit 0  (30s) =====\n\n"
            % (stamp(t), stamp(t + 600), stamp(t + 1200)))
        html = self.page()
        self.assertIn('class="warning" tabindex="0"', html)
        self.assertNotIn('class="critical" tabindex="0"', html)

    def test_failed_last_run_needs_attention(self):
        self.heartbeat(8)
        html = self.page()
        self.assertIn("brief: exit 8: spending cap", html)

    def plists(self, **jobs):
        """A LaunchAgents folder holding one plist per job, each as given."""
        folder = self.jobs.parent / "LaunchAgents"
        folder.mkdir(exist_ok=True)
        for name, extra in jobs.items():
            body = {"Label": "garrick." + name, "ProgramArguments": ["/usr/bin/python3", "/w/System/jobs/job.py", name, "--", "true"]}
            body.update(extra)
            (folder / (name + ".plist")).write_bytes(plistlib.dumps(body))
        return mock.patch.object(status, "launch_agents", lambda: folder)

    def test_schedules_read_monthly_weekly_and_daily(self):
        with self.plists(monthly={"StartCalendarInterval": {"Day": 1, "Hour": 9, "Minute": 0}},
                         weekly={"StartCalendarInterval": [{"Weekday": 1, "Hour": 7}, {"Weekday": 4, "Hour": 7}]},
                         daily={"StartCalendarInterval": {"Hour": 23, "Minute": 30}}):
            got = status.launchd_jobs()
        self.assertEqual(("monthly day 1, 09:00", dt.timedelta(days=32)), (got["monthly"]["schedule"], got["monthly"]["late"]))
        self.assertEqual(("weekly Mon 07:00, Thu 07:00", dt.timedelta(days=8)), (got["weekly"]["schedule"], got["weekly"]["late"]))
        self.assertEqual(("daily 23:30", dt.timedelta(days=2)), (got["daily"]["schedule"], got["daily"]["late"]))

    def test_a_monthly_job_is_not_late_after_a_week(self):
        (self.jobs / "brief.heartbeat.json").write_text(json.dumps(
            {"job": "brief", "finished": stamp(self.now.timestamp() - 7 * 86400), "exit": 0, "seconds": 30}))
        with self.plists(brief={"StartCalendarInterval": {"Day": 1, "Hour": 9}}):
            html = self.page()
        self.assertIn("monthly day 1, 09:00", html)
        self.assertNotIn("late: last ran", html)

    def ledger(self, *entries):
        with (self.jobs / "ledger.jsonl").open("w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(dict({"ts": self.now.timestamp() - 600}, **e)) + "\n")

    def attention(self, html):
        start = html.index('id="attention"')
        return html[start:html.index("</details>", start)]

    def test_one_attention_line_per_capped_job(self):
        refused = {"job": "brief", "refused": True}
        self.ledger(refused, refused, refused, {"job": "digest", "refused": True}, {"job": "digest", "cost_usd": 0.2, "exit": 0})
        with self.plists():
            block = self.attention(self.page())
        self.assertEqual(1, block.count("The spending cap stopped brief"))
        self.assertIn("The spending cap stopped brief 3 times in 24 hours<", block)
        self.assertIn("The spending cap stopped digest<", block)

    def test_caps_come_from_the_plist_of_the_job_that_calls(self):
        self.ledger({"job": "brief", "cost_usd": 0.5, "exit": 0})
        args = ["/usr/bin/python3", "/w/System/jobs/job.py", "brief", "--agent", "--", "python3", "brief.py"]
        env = {"PATH": "/usr/bin", "GARRICK_CAP_CALLS_DAY": "10", "GARRICK_CAP_COST_DAY": "0"}
        with self.plists(brief={"ProgramArguments": args, "EnvironmentVariables": env, "StartCalendarInterval": {"Hour": 6}},
                         status={"StartCalendarInterval": {"Hour": 23}}), \
                mock.patch.dict(os.environ, {"GARRICK_CAP_CALLS_DAY": "99"}):
            html = self.page()
        self.assertIn("1<small>of 10</small>", html)         # the job's cap, not this shell's 99
        self.assertIn(">1 / 10<", html)
        self.assertIn(">1 / 12<", html)                      # a cap the plist leaves out is agent.py's default
        self.assertIn(">$0.50, no cap<", html)               # 0 removes a cap
        self.assertIn("Caps from the launchd plist of brief.", html)

    def test_without_a_plist_the_caps_say_where_they_come_from(self):
        self.ledger({"job": "brief", "cost_usd": 0.5, "exit": 0})
        with self.plists(), mock.patch.dict(os.environ, {"GARRICK_CAP_CALLS_DAY": "0"}):
            html = self.page()
        self.assertIn("1<small>no cap</small>", html)
        self.assertIn(">1, no cap<", html)
        self.assertIn("Caps from the GARRICK_CAP_* settings the page was built with", html)

    def test_odd_plists_are_passed_over(self):
        folder = self.jobs.parent / "LaunchAgents"
        folder.mkdir()
        (folder / "list.plist").write_bytes(plistlib.dumps(["not", "a", "dict"]))
        (folder / "args.plist").write_bytes(plistlib.dumps({"ProgramArguments": "job.py brief"}))
        (folder / "broken.plist").write_text("<plist>")
        with mock.patch.object(status, "launch_agents", lambda: folder):
            self.assertEqual({}, status.launchd_jobs())



class TestNameAndMark(StatusCase):
    def test_called_garricks_status(self):
        html = self.page()
        self.assertIn("<title>Garrick&#x27;s Status</title>", html)
        self.assertIn("<h1>Garrick&#x27;s Status</h1>", html)

    def test_mark_beside_the_heading_and_in_the_tab(self):
        html = self.page()
        brand = html[html.index('<div class="brand">'):html.index("<h1>")]
        self.assertIn('class="mark" aria-hidden="true"', brand)
        self.assertIn('fill="#3D73E0"', brand)
        self.assertEqual(2, brand.count("<path"))           # Gr alone: the small "ai" cannot be read at heading size
        icon = re.search(r'<link rel="icon" type="image/svg\+xml" href="data:image/svg\+xml,([^"]+)">', html)
        svg = urllib.parse.unquote(icon.group(1))
        self.assertTrue(svg.startswith('<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">'))
        self.assertIn('fill="#3D73E0"', svg)
        self.assertEqual(2, svg.count("<path"))             # the favicon cut: Gr alone

    def test_display_headings_in_baskerville(self):
        # Garrick's typeface, from fonts already on the machine: nothing is fetched.
        stack = '"Baskervville","Libre Baskerville",Baskerville,"Baskerville Old Face",Georgia,serif'
        self.assertIn("--display:%s;" % stack, status.CSS)
        for rule in (r"\.brand h1\{[^}]*", r"\.head h2\{[^}]*", r"\.hero \.fig\{[^}]*"):
            self.assertIn("var(--display)", re.search(rule, status.CSS).group(0))
        self.assertIn('body{margin:0;background:var(--page);color:var(--ink);font:14px/1.45 system-ui', status.CSS)
        self.assertNotIn("@font-face", status.CSS)
        self.assertNotIn("url(", status.CSS)

    def test_accent_is_the_brand_blue_and_readable(self):
        light = re.search(r":root\{[^}]*--accent:(#[0-9a-f]{6})", status.CSS).group(1)
        self.assertEqual(status.BRAND.lower(), light)
        dark = re.findall(r'color-scheme:dark;[^}]*?--page:(#[0-9a-f]{6});[^}]*?--surface:(#[0-9a-f]{6});--raise:(#[0-9a-f]{6});'
                          r'[^}]*?--accent:(#[0-9a-f]{6})', status.CSS)
        self.assertEqual(2, len(dark))                      # the automatic dark theme and the chosen one agree
        self.assertEqual(dark[0], dark[1])
        page, surface, raise_, accent = dark[0]
        for bg in (page, surface, raise_):
            self.assertGreaterEqual(contrast(accent, bg), 4.5, "%s on %s" % (accent, bg))


class TestWikisAndRepos(StatusCase):
    def test_wikis_show_the_newest_entry(self):
        write(self.root / "Wikis" / "Meetings" / "wiki" / "log.md",
              "# Log\n\nOne line per ingest, newest first.\n\n"
              "- 2026-03-12: [[wiki/sources/260312-birch-kickoff|Birch kick-off]] (Work; birch)\n"
              "- 2026-03-10: [[wiki/sources/260310-acme-kickoff|Acme kick-off]] (Work; acme)\n")
        write(self.root / "Wikis" / "Knowledge" / "wiki" / "log.md", "# Log\n\nOne line per ingest, newest first.\n")
        html = self.page()
        start = html.index('id="wikis"')
        block = html[start:html.index("</details>", start)]
        self.assertIn("12 Mar 2026 · <a href=", block)
        self.assertIn(">Birch kick-off</a>", block)
        self.assertNotIn("Acme kick-off", block)
        self.assertNotIn("Work; birch", block)                 # nothing else from the line
        self.assertEqual(1, block.count("nothing logged yet"))  # the Knowledge log has no entry

    def test_the_wikis_repository_is_listed(self):
        from fixtures import git_init
        git_init(self.root / "Wikis")
        html = self.page()
        start = html.index('id="repos"')
        self.assertIn('<div class="name">Wikis<small>', html[start:html.index("</details>", start)])


class TestRebuildAndWorkspace(StatusCase):
    def test_rebuild_command_is_absolute_quoted_and_complete(self):
        ws = Path(self._tmp.name).resolve() / "My Workspace"
        build_workspace(ws)
        out = Path(self._tmp.name).resolve() / "pages here" / "status.html"
        words = shlex.split(status.rebuild_command(ws, "My Work", False, out))
        self.assertEqual(["python3", str(STATUS.resolve()), "--workspace", str(ws), "--obsidian", "My Work",
                          "--no-graph", "--out", str(out), "--open"], words)
        self.assertEqual(["python3", str(STATUS.resolve()), "--workspace", str(ws), "--open"],
                         shlex.split(status.rebuild_command(ws)))

    def test_the_page_copies_the_command_it_was_built_with(self):
        out = Path(self._tmp.name).resolve() / "elsewhere" / "status.html"
        self.run_main("--out", str(out), "--no-graph", "--obsidian", "My Work")
        html = out.read_text(encoding="utf-8")
        raw = re.search(r'data-copy="([^"]*)" data-say="Copied. Run it in a terminal', html).group(1)
        self.assertEqual(status.rebuild_command(self.root, "My Work", False, out), htmllib.unescape(raw))

    def run_main(self, *extra):
        return TestSelfContained.run_main(self, *extra)

    def test_a_mistyped_workspace_stops(self):
        wrong = Path(self._tmp.name).resolve() / "Workspce"
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as stop:
            status.main(["--workspace", str(wrong)])
        self.assertIn("is not a Garrick workspace", str(stop.exception.code))
        self.assertFalse(wrong.exists())
        bare = Path(self._tmp.name).resolve() / "Elsewhere"
        bare.mkdir()
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
            status.main(["--workspace", str(bare)])
        self.assertEqual([], list(bare.iterdir()))


class TestFrontmatter(StatusCase):
    def note(self, text):
        write(self.root / "Zones" / "Work" / "Birch Entry" / "Threads" / "Market Sizing" / "Market Sizing.md", text)

    def parked_with_comment_and_block_list(self):
        self.note("---\ntitle: Market Sizing\ntype: thread\nparty:\n  - birch\n  - acme\n"
                  "status: parked   # until the spring\nupdated: 2026-03-01\n---\n\n# Market Sizing\n")
        html = self.page()
        self.assertIn('id="parked-work"', html)               # the comment does not make it live
        node = next(n for n in graph_data(html)["nodes"] if n["n"] == "Market Sizing")
        self.assertEqual(["birch", "acme"], node["t"])

    def test_the_workspace_parser_is_used(self):
        tools = self.root / "System" / "tools"
        tools.mkdir(parents=True)
        shutil.copy(REPO / "template" / "System" / "tools" / "garrick_lib.py", tools / "garrick_lib.py")
        self.assertIsNotNone(status.workspace_lib(self.root))
        self.parked_with_comment_and_block_list()
        self.assertEqual([], list(tools.glob("__pycache__")))   # nothing written beside it

    def test_the_fallback_reads_comments_and_block_lists_too(self):
        self.assertIsNone(status.workspace_lib(self.root))
        self.parked_with_comment_and_block_list()


class TestOpenActions(StatusCase):
    def test_each_zone_line_opens_its_todo(self):
        html = self.page()
        start = html.index('id="todo"')
        block = html[start:html.index("</details>", start)]
        url = (self.root / "Zones" / "Work" / "Todo.md").as_uri()
        self.assertIn('<a class="act" href="%s" title="Open Work/Todo.md">Open</a>' % url, block)
        vault = self.page(vault="My Work")
        self.assertIn("file=Zones/Work/Todo\" title=\"Open Work/Todo.md\">Open</a>", vault)


if __name__ == "__main__":
    unittest.main()
