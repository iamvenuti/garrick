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
import re
import shlex
import shutil
import sys
import tempfile
import time
import unittest
import urllib.parse
from pathlib import Path

sys.dont_write_bytecode = True

from fixtures import build_workspace, project_hub, thread_note, write  # noqa: E402

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

    def test_inboxes_raw_and_catalogues_stay_out(self):
        write(self.root / "Zones" / "Work" / "Inbox" / "Note.md", "# A dropped note\n")
        names = {n["n"] for n in graph_data(self.page())["nodes"]}
        self.assertNotIn("A dropped note", names)
        self.assertNotIn("Note", names)
        self.assertNotIn("index", names)
        self.assertNotIn("260310-acme-kickoff.txt", names)

    def test_threads_carry_the_phrase_to_say(self):
        data = graph_data(self.page())
        self.assertEqual("Pricing", data["nodes"][self.node(data, "Pricing")]["w"])

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

    def test_no_field_the_layout_writes(self):
        layout = {"x", "y", "vx", "vy", "ax", "ay", "r", "i", "adj", "deg"}
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
        self.assertEqual(4, brand.count("<path"))           # Gr and the small ai
        icon = re.search(r'<link rel="icon" type="image/svg\+xml" href="data:image/svg\+xml,([^"]+)">', html)
        svg = urllib.parse.unquote(icon.group(1))
        self.assertTrue(svg.startswith('<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">'))
        self.assertIn('fill="#3D73E0"', svg)
        self.assertEqual(2, svg.count("<path"))             # the favicon cut: Gr alone

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


if __name__ == "__main__":
    unittest.main()
