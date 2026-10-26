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
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

import fixtures  # noqa: E402
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
    for raw in re.findall(r'class="thread(?: sub)?"[^>]*data-card="([^"]*)"', html):     # a project's row is not a thread
        data = json.loads(htmllib.unescape(raw))
        out[(data["p"], data["n"])] = data
    return out


def thread_order(html, anchor='id="zone-work"'):
    """Row names in the order a zone lists them, live ones or its Parked fold:
    each project's row, then its threads."""
    start = html.index(anchor)
    block = html[start:html.index("</details>", start)]
    if anchor.startswith('id="zone-'):
        block = block.split('<details class="parked')[0]
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
        # This machine's own LaunchAgents stay out: a test that wants plists writes them here.
        agents = mock.patch.object(status, "launch_agents", lambda: base / "LaunchAgents")
        agents.start()
        self.addCleanup(agents.stop)

    def tearDown(self):
        self._tmp.cleanup()

    def page(self, **kw):
        return status.build(self.root, now=self.now, folder=self.jobs, **kw)


class TestMetadataOnly(StatusCase):
    def test_names_parties_and_dates(self):
        html = self.page()
        for text in ("Work", "Personal", "Acme Review", "Pricing", "Market Sizing"):
            self.assertIn(text, html)
        self.assertEqual(["acme"], cards(html)[("Acme Review", "Pricing")]["t"])       # the parties are in the card

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

    @mock.patch.object(status, "desk_ready", return_value=False)      # the desk's keys depend on cmux; tested with a fake one in test_status_more
    def test_names_and_kinds_only(self, _desk):
        html = self.page()
        data = graph_data(html)
        kinds = dict((i, k) for i, k in data["kinds"])
        by_name = {n["n"]: kinds[n["k"]] for n in data["nodes"]}
        self.assertEqual("project", by_name["Acme Review"])
        self.assertEqual("thread", by_name["Pricing"])
        self.assertEqual("meeting", by_name["Acme kick-off"])
        self.assertEqual({"n", "k", "z", "p", "t", "d", "s", "c", "h", "w", "u", "m", "hp", "pa", "pp", "oc"}, set().union(*(n.keys() for n in data["nodes"])))
        self.assertEqual(["Work", "Acme Review/Threads/Pricing/Pricing.md"], data["nodes"][self.node(data, "Pricing")]["oc"])   # what Open in Claude continues (#180)
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
        self.assertIn('<i style="background:%s"></i>Mail</span>' % dict((label, c) for (_, label, c) in status.KINDS)["mail"], html)

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
        self.assertEqual(20, html.count("</script>"))         # the graph's data, the menu's data, the state the page waits for, the dialogs' data, what the search box looks through, the zone icons Settings offers, the page's, the dialogs', the search box's, the running actions', the notifications', While you wait's, Catch up's, Memory's, the simple home's, where a work's files live's, the menu's, the Guide's, Preview's, the graph's
        self.assertEqual(html.count("<script"), html.count("</script>"))
        self.assertIn("<!--<script>&</script>", {n["n"] for n in graph_data(html)["nodes"]})
        self.assertTrue(html.rstrip().endswith("</script></body></html>"))

    def test_a_place_at_a_time_work_first(self):
        html = self.page()
        bar = html[html.index('<select class="gzsel" aria-label="Place">'):html.index("</select>")]
        places = re.findall(r'<option value="([^"]*)"', bar)                      # a drop-down, not a row of buttons
        self.assertEqual("Work", places[0])
        self.assertEqual("*", places[-1])                                         # and All, last
        self.assertIn("Meetings", places)                                         # a wiki is a place too
        self.assertIn("(zsel==='*'||n.z===zsel)", status.GRAPH_JS)
        graph = html[html.index('id="graph"'):html.index("</details>", html.index('id="graph"'))]
        self.assertLess(graph.index("glegend"), graph.index('id="gsum"'))          # the summary sits under the legend
        self.assertIn("<h2>Explore</h2>", graph)                                   # the graph sits behind Explore
        self.assertIn('<h2>Explore</h2><span class="meta"></span>', graph)            # folded, it has nothing to report

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
        self.assertIn("if(!inside&&q.s*q.s<.81*d2)", js)              # a far group pushes as one, from its centre
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

    def test_every_note_carries_its_path_for_preview(self):
        # Preview (#206) reads a node's note by its path from the workspace: the place's folder, in `pr`
        # once, and the note's path from it without `.md`, in `m`, so the page grows by little.
        data = graph_data(self.page())
        self.assertEqual({"Work": "Zones/Work", "Personal": "Zones/Personal", "Meetings": "Wikis/Meetings/wiki",
                          "Knowledge": "Wikis/Knowledge/wiki"}, data["pr"])
        self.assertEqual("Acme Review/Threads/Pricing/Pricing", data["nodes"][self.node(data, "Pricing")]["m"])
        self.assertEqual("sources/260310-acme-kickoff", data["nodes"][self.node(data, "Acme kick-off")]["m"])
        for n in data["nodes"]:
            self.assertTrue((self.root / (data["pr"][n["z"]] + "/" + n["m"] + ".md")).is_file(), n)
        self.assertIn("function notePath(n){return n.m!=null&&G.pr&&G.pr[n.z]?G.pr[n.z]+'/'+n.m+'.md':''}", status.GRAPH_JS)

    def test_preview_sits_in_its_own_script_beside_the_graph(self):
        html = self.page()
        self.assertIn("<script>%s</script><script>%s</script>" % (status.NOTE_JS, status.GRAPH_JS + status.FOLLOW_JS), html)
        self.assertIn(status.NOTE_CSS, html)
        bare = self.page(show_graph=False)
        self.assertNotIn(status.NOTE_JS, bare)
        self.assertNotIn("dialog.nview", bare)

    def test_preview_only_where_the_host_reads_a_note(self):
        # A browser cannot read a file, nor can an app built before #206: neither is offered Preview.
        js = status.NOTE_JS
        self.assertIn("function able(){var P=window.GarrickPrefs;return!!host&&!!window.GarrickReadsNotes&&!(P&&P.launchers().preview===false)}", js)
        self.assertIn("return path&&able()?'<button class=\"act nv-glass\" type=\"button\" data-note=\"'", js)
        self.assertIn("if(!b||!able())return;", js)
        self.assertIn("host.postMessage({act:{verb:'note-read',path:path}})", js)
        self.assertIn("host.postMessage({act:{verb:'note-open',path:path}})", js)
        # the card is drawn again for each node selected, a linked one included, so Preview reads the note in it
        self.assertIn("Panel.acts(o,window.GarrickNote?GarrickNote.button(notePath(n),n.N||n.n):'')", status.GRAPH_JS)
        self.assertIn("if(b){var m=N[+b.dataset.i];", status.GRAPH_JS)
        self.assertIn("select(m,true)}});", status.GRAPH_JS)

    @unittest.skipUnless(shutil.which("node"), "Node is not installed")
    def test_the_preview_button_in_node(self):
        harness = r"""
        const vm = require("vm");
        const [js, hosted, flag, prefs] = JSON.parse(process.argv[1]);
        const ctx = { JSON, String, document: { addEventListener: () => {} } };
        ctx.window = hosted ? { webkit: { messageHandlers: { garrick: { postMessage: () => {} } } } } : {};
        if (flag) ctx.window.GarrickReadsNotes = true;
        if (prefs) ctx.window.GarrickPrefs = { launchers: () => prefs };
        vm.createContext(ctx);
        vm.runInContext(js + ";this.out=[window.GarrickNote.button('Wikis/Meetings/wiki/people/a & b.md','Dana \"D\" <W>'),"
                        + "window.GarrickNote.button('','Nothing'),window.GarrickNote.shown()]", ctx);
        process.stdout.write(JSON.stringify(ctx.out));
        """

        def button(hosted, flag, prefs=None):
            done = subprocess.run(["node", "-e", harness, json.dumps([status.NOTE_JS, hosted, flag, prefs])],
                                  capture_output=True, text=True, timeout=30)
            self.assertEqual(0, done.returncode, done.stderr)
            return json.loads(done.stdout)

        self.assertEqual(["", "", False], button(False, False))       # a browser
        self.assertEqual(["", "", False], button(False, True))
        self.assertEqual(["", "", False], button(True, False))        # an app built before Preview
        drawn = button(True, True)
        self.assertEqual(["", False], drawn[1:])
        # a magnifier (#219), not the word: Preview is its tooltip and its accessible name, and the glass is hidden from a screen reader
        self.assertRegex(drawn[0], r'^<button class="act nv-glass" type="button" data-note="Wikis/Meetings/wiki/people/a &amp; b\.md" '
                                   r'data-title="Dana &quot;D&quot; &lt;W&gt;" title="Preview" aria-label="Preview" aria-haspopup="dialog">'
                                   r'<svg viewBox="0 0 16 16" aria-hidden="true">.*</svg></button>$')
        self.assertNotIn(">Preview<", drawn[0])
        self.assertEqual(drawn, button(True, True, {"note": True}))         # a choice saved before Preview had one: offered
        self.assertEqual(drawn, button(True, True, {"preview": True}))
        # Settings › Opening a thread switches it off: no icon, and nothing opens the preview
        self.assertEqual(["", "", False], button(True, True, {"preview": False}))
        self.assertIn("if(!b||!able())return;", status.NOTE_JS)

    def test_the_preview_closes_and_leaves_the_graph_as_it_was(self):
        js, graph = status.NOTE_JS, status.GRAPH_JS
        # a modal dialog, named by its title, the keyboard moved into it and handed back to Preview after
        for part in ("dlg.setAttribute('role','dialog');dlg.setAttribute('aria-modal','true');dlg.setAttribute('aria-labelledby','nview-h')",
                     '<h3 id="nview-h"></h3>', "dlg.showModal();el('.nv-body').focus();", "if(b)b.focus({preventScroll:true})",
                     'data-nv="open">Open in default app</button>', 'data-nv="close">Close</button>'):
            self.assertIn(part, js)
        # Close, a click that starts and ends outside the panel, and Escape, which the card underneath never hears
        self.assertIn("if(b){if(b.dataset.nv==='open')openIn(cur&&cur.path);else shut();return}", js)
        self.assertIn("if(e.target===dlg&&down===dlg)shut()", js)
        self.assertIn("if(e.key==='Escape'){e.preventDefault();e.stopPropagation();shut()}", js)
        self.assertIn("if(e.key==='Escape'&&sel&&!(window.GarrickNote&&GarrickNote.shown()))close()", graph)
        # closing it touches nothing of the graph's: no selection, place, zoom or panel
        shut = js[js.index("function shut(){"):js.index("function heard(")]
        for state in ("sel=", "px", "py", "scale", "theta", "pop.", "pop=", "select(", "GarrickGraph"):
            self.assertNotIn(state, shut)
        # loading, a refusal in the host's words, and no Open for a note that is not there
        self.assertIn("said('Reading the note…')", js)
        self.assertIn("if(out&&out.missing)el('[data-nv=\"open\"]').hidden=true;", js)
        self.assertIn("else said((out&&out.say)||'That note could not be read.',true)}", js)
        self.assertIn("if(!cur||!dlg.open||q.path!==cur.path)return;", js)     # a reply for a note no longer shown
        self.assertIn("if(q&&(q.verb==='note-read'||q.verb==='note-open')){heard(q,out);return}", js)
        self.assertIn("if(prev)return prev(q,out)};", js)
        css = status.NOTE_CSS
        for part in ("background:var(--surface)", "color:var(--ink)", ".nv-body>:not(.gd-table){max-width:70ch}", "overflow:auto"):
            self.assertIn(part, css)
        self.assertNotRegex(css, r"#[0-9a-fA-F]{3,6}\b")                    # the page's own colours, light or dark


class TestTabs(StatusCase):
    """Overview for where the work stands, Status for the machinery behind it."""

    def section(self, html, name):
        start = html.index('id="tab-%s"' % name)
        return html[start:html.index("</section>", start)]

    def job(self, code):
        now = self.now.timestamp()
        (self.jobs / "brief.heartbeat.json").write_text(json.dumps(
            {"job": "brief", "finished": stamp(now - 60), "exit": code, "seconds": 30, "items": 2, "idle_days": 0}))
        (self.jobs / "brief.log").write_text("===== %s  brief  exit %d  (30s) =====\n\n" % (stamp(now - 60), code))

    def test_the_default_split(self):
        self.job(0)
        html = self.page()
        self.assertIn('data-tab="overview">Overview</button><button type="button" role="tab" data-tab="todo">Todo', html)
        self.assertIn('</button><button type="button" role="tab" data-tab="status">Status', html)
        overview, machinery = self.section(html, "overview"), self.section(html, "status")
        for card_id in ("graph", "threads", "todo", "inboxes"):
            self.assertIn('id="%s"' % card_id, overview, card_id)
        for card_id in ("jobs", "checks", "repos", "wikis"):
            self.assertIn('id="%s"' % card_id, machinery, card_id)
        self.assertNotIn('class="top"', overview)                               # the overview is the work alone
        self.assertLess(machinery.index('class="top"'), machinery.index('class="onlybar"'))   # the figures lead Status
        self.assertIn('id="tab-status" hidden', html)

    def test_a_card_moves_between_tabs_and_reset_puts_it_back(self):
        html = self.page()
        self.assertGreaterEqual(html.count('class="totab"'), 4)
        self.assertNotIn('class="totab"', html[html.index('id="attention"'):html.index("</summary>", html.index('id="attention"'))]
                         if 'id="attention"' in html else "")
        self.assertIn("'#tab-'+to+' [data-slot$=\"left\"]'", status.LAYOUT_JS)
        self.assertIn("{v:2,c:c,", status.LAYOUT_JS)                         # a layout saved by the old page is not replayed

    def test_needs_attention_leads_the_status_tab(self):
        self.job(4)
        html = self.page()
        machinery = self.section(html, "status")
        self.assertLess(machinery.index('id="attention"'), machinery.index('id="jobs"'))
        self.assertNotIn('id="attention"', self.section(html, "overview"))

    def test_the_figures_lead_to_the_cards(self):
        self.job(0)
        html = self.page()
        machinery = self.section(html, "status")
        targets = re.findall(r'<a class="(?:hero|tile) go"[^>]*href="#([a-z]+)"', machinery)
        self.assertIn("threads", targets)
        self.assertIn("inboxes", targets)
        for t in targets:
            self.assertIn('id="%s"' % t, html, t)                               # every tile leads to a card that exists
        self.assertIn("if(!a.closest('nav')){e.preventDefault();", status.JS)      # and opens it, folded or not

    def test_one_pinned_row_and_no_sidebar(self):
        html = self.page()
        self.assertNotIn("<aside", html)                                      # the tabs move, the cards are in view
        self.assertNotIn('class="overall', html)                              # the Status tab's own figures say it
        bar = html[html.index('<header class="bar">'):html.index("</header>")]
        for piece in ('class="mark"', "<h1>", 'id="age"', 'class="tabs" role="tablist"', 'id="rebuild"', 'id="open-settings"',
                      'class="seg theme"'):
            self.assertIn(piece, bar, piece)
        self.assertIn("header.bar{position:sticky;top:0", status.BAR_CSS)
        for t in ("auto", "light", "dark"):                                  # icons, each named
            self.assertRegex(bar, r'<button type="button" data-t="%s" title="[^"]+" aria-label="Theme: [^"]+"><svg' % t)
        dialog = html[html.index('<dialog id="settings"'):html.index("</dialog>", html.index('<dialog id="settings"'))]
        self.assertIn('<div class="hiddencards" id="hidden-cards" hidden></div>', dialog)   # hidden cards are listed in Settings
        self.assertIn("'<p class=\"hint\">Hidden cards</p>", status.LAYOUT_JS)
        self.assertIn("var u=e.target.closest('.unhide')", status.LAYOUT_JS)       # and shown again from there
        self.assertIn("Bring it back from Settings", status.LAYOUT_JS)
        self.assertIn("document.body.dataset.tab=n", status.JS)

    def test_a_failure_marks_the_status_tab(self):
        self.job(0)
        self.assertNotIn('data-tab="status">Status<span class="dot critical"', self.page())
        self.job(4)
        html = self.page()
        self.assertIn('data-tab="status">Status<span class="dot critical"', html)


class TestGuide(StatusCase):
    """#133: the Guide tab shows the docs the workspace was installed with,
    and every link on it stays on the page or opens on GitHub."""

    def setUp(self):
        super().setUp()
        spec = importlib.util.spec_from_file_location("garrick_install", REPO / "install.py")
        install = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(install)
        for rel in install.docs_files():                                       # as the installer ships them
            target = self.root / "System" / "garrick-docs" / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((REPO / "docs" / rel).read_bytes())

    def guide(self, html):
        start = html.index('<section class="tab" id="tab-guide"')
        return html[start:html.index("</section>", start)]

    def pages(self, html):
        start = html.index('<script type="text/html" id="guide-src">')
        return html[start:html.index("</script>", start)]

    def test_the_tab_comes_after_status_and_holds_no_cards(self):
        html = self.page()
        self.assertEqual(["overview", "todo", "status", "guide"], re.findall(r'role="tab" data-tab="([a-z]+)"', html))
        self.assertIn('data-tab="guide">Guide</button>', html)
        guide = self.guide(html)
        self.assertIn('id="tab-guide" hidden', guide)
        for card in ('class="card', "data-slot", 'class="totab"'):           # never a place a card moves to
            self.assertNotIn(card, guide)

    def test_the_pages_wait_as_text_at_the_end_until_the_tab_opens(self):
        html = self.page()
        self.assertEqual('<div class="gd" id="guide"></div>', self.guide(html).split(">", 1)[1])
        start = html.index('<script type="text/html" id="guide-src">')
        self.assertTrue(html.endswith("</script></body></html>"))
        self.assertEqual(html.index("</script>", start) + len("</script></body></html>"), len(html))   # after every script
        self.assertEqual(html.count("<article"), html[start:].count("<article"))
        self.assertIn("if(n==='guide'&&window.GarrickGuide)GarrickGuide.mount()", status.JS)
        self.assertIn("GarrickGuide.reveal(id)", status.JS)                  # a link into it shows its page first
        self.assertIn("garrick-guide-page", status.guide_mod().GUIDE_JS)     # the last page read

    def test_every_page_in_reading_order(self):
        guide = self.pages(self.page())
        pages = sorted(p.relative_to(REPO / "docs").as_posix() for p in (REPO / "docs").rglob("*.md")
                       if not p.relative_to(REPO / "docs").as_posix().startswith("assets/"))
        ids = re.findall(r'<article class="gd-page" id="([^"]+)"', guide)
        self.assertEqual(sorted(status.guide_mod().page_id(p) for p in pages), sorted(ids))
        self.assertEqual(["Start here", "Understand", "Do", "Extras", "Look up"], re.findall(r'<div class="gd-sec"><h3>([^<]+)</h3>', guide))
        toc = re.findall(r'<li class="gd-it" data-p="guide-([^"]+)"', guide)
        self.assertEqual(["try-it-safely", "first-steps", "terminal-setup", "first-session", "guided-session",
                          "principles", "concepts", "architecture", "context", "enforced", "harnesses", "updating", "extras-index"],
                         toc[:13])
        self.assertEqual("commands", toc[toc.index("extras-toolkit") + 1])      # each extras page, then Look up
        self.assertIn('class="gd-q" type="search"', guide)

    def test_tables_code_headings_and_images(self):
        guide = self.pages(self.page())
        enforced = guide[guide.index('id="guide-enforced"'):]
        enforced = enforced[:enforced.index("</article>")]
        self.assertIn('<div class="gd-table"><table><thead><tr><th>Protection</th>', enforced)
        self.assertIn('<h2 id="guide-enforced--the-wall-checks-known-gaps">', enforced)
        self.assertIn('<pre><code class="lang-sh">', guide)
        self.assertRegex(guide, r'<img src="data:image/png;base64,[A-Za-z0-9+/=]{1000,}" alt="The Claude app')
        self.assertEqual([], [s for s in re.findall(r'\ssrc="([^"]*)"', guide) if not s.startswith("data:image/")])

    def test_every_link_stays_on_the_page_or_opens_on_github(self):
        html = self.page()
        guide = self.pages(html)
        ids = set(re.findall(r'\sid="([^"]+)"', html))
        hrefs = [htmllib.unescape(h) for h in re.findall(r'<a href="([^"]*)"', guide)]
        self.assertGreater(len(hrefs), 300)
        for h in hrefs:
            if h.startswith("#"):
                self.assertIn(h[1:], ids, h)
            else:
                self.assertTrue(h.startswith(("https://", "http://", "mailto:")), h)
            self.assertFalse(re.search(r"\.md(#|$)", h) and not h.startswith(status.PROJECT + "/blob/"), h)
        for tag in re.findall(r'<a href="(?:https?|mailto):[^>]*>', guide):
            self.assertIn('target="_blank" rel="noopener"', tag)              # outside, in a browser too
        self.assertIn("#guide-principles--what-the-check-covers", hrefs)       # page to page, with a heading
        self.assertIn("#guide-first-steps", hrefs)                             # page to page

    def test_a_link_into_garrick_opens_the_release_it_runs(self):
        write(self.root / "System" / "garrick-changelog.md", "# Changelog\n\n## [Unreleased]\n\n## [0.29.0] - 2026-10-15\n")
        write(self.root / "System" / "garrick-version.json", json.dumps({"commit": "abc1234", "from": "download"}))
        hrefs = [htmllib.unescape(h) for h in re.findall(r'<a href="([^"]*)"', self.pages(self.page()))]
        self.assertIn(status.PROJECT + "/blob/v0.29.0/template/System/rules.md#autonomy", hrefs)
        self.assertIn(status.PROJECT + "/blob/v0.29.0/extras/hooks/README.md", hrefs)
        self.assertIn(status.PROJECT + "/blob/v0.29.0/docs/architecture/overview.png", hrefs)   # in docs/, but not a page
        write(self.root / "System" / "garrick-version.json", json.dumps({"commit": "abc1234", "from": "clone"}))
        hrefs = [htmllib.unescape(h) for h in re.findall(r'<a href="([^"]*)"', self.pages(self.page()))]
        self.assertIn(status.PROJECT + "/blob/main/template/System/rules.md#autonomy", hrefs)   # a clone follows main

    def test_a_link_the_build_cannot_place_keeps_its_text(self):
        gd = status.guide_mod()
        docs = gd.Docs(self.root / "System" / "garrick-docs", "v1.0.0")
        self.assertEqual("#guide-concepts--wall", docs.resolve("extras/cmux.md", "../concepts.md#wall"))
        self.assertEqual("#guide-extras-cmux--a-sidebar", docs.resolve("extras/index.md", "#a-sidebar".join(("cmux.md", ""))))
        self.assertEqual("#guide-extras-index--x", docs.resolve("extras/index.md", "#x"))
        for bad in ("javascript:alert(1)", "file:///etc/passwd", "obsidian://open?vault=x", "/etc/passwd", "../../../x.md"):
            self.assertIsNone(docs.resolve("concepts.md", bad), bad)
        out = gd.inline("[x](javascript:alert(1)) and ![y](../../../secret.png)", lambda h: docs.resolve("concepts.md", h),
                        lambda s: docs.image("concepts.md", s))
        self.assertEqual("x and y", out)

    def test_no_docs_says_how_to_get_them(self):
        shutil.rmtree(self.root / "System" / "garrick-docs")
        html = self.page()
        guide = self.guide(html)
        self.assertIn("no copy of Garrick&#x27;s docs", guide)
        self.assertIn("Garrick App", guide)
        self.assertNotIn('id="guide-src"', html)


class TestLayout(StatusCase):
    def test_cards_can_move_and_hide(self):
        html = self.page()
        self.assertIn('data-slot="top"', html)
        self.assertGreaterEqual(html.count('class="grip"'), 6)
        self.assertIn('id="reset-view"', html)
        dialog = html[html.index('<dialog id="settings"'):html.index("</dialog>", html.index('<dialog id="settings"'))]
        self.assertIn('id="reset-view"', dialog)                               # Reset view lives in Settings
        self.assertIn("k!=='garrick-launchers'", status.LAYOUT_JS)             # and keeps the launcher choices

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


def overview(html):
    start = html.index('id="tab-overview"')
    return html[start:html.index("</section>", start)]


def card_order(section):
    return re.findall(r'<details class="card" id="([a-z]+)"', section)


class TestOpensOnTheWork(StatusCase):
    """#102: the Overview opens on what you were doing and what you owe, not on
    the graph; a thread is urgent for its own next action, never for its age."""

    def actions(self, *lines):
        write(self.root / "Zones" / "Work" / "Todo.md",
              "# Work: open actions\n\n## Inbox\n\n" + "".join("- [ ] %s\n" % l for l in lines) + "\n## Done\n")

    def touched(self, project, thread, day):
        note = self.root / "Zones" / "Work" / project / "Threads" / thread / (thread + ".md")
        note.write_text(thread_note(project, thread, "acme").replace("updated: 2026-03-01", "updated: " + day))

    def rows(self, html, card):
        """One card, whole: from its id to the next card, since the cards hold
        folds of their own."""
        start = html.index('<details class="card" id="%s"' % card)
        after = html.find('<details class="card" id="', start + 1)
        end = html.index("</section>", start) if after < 0 else after
        return html[start:end]

    def row(self, html, name):
        """One live thread's row on the Threads card, by its name."""
        threads = self.rows(html, "threads").split('<details class="parked')[0]
        start = threads.index('data-card="%s' % htmllib.escape('{"n":"%s"' % name, quote=True))
        start = threads.rindex('<div class="thread', 0, start)
        end = threads.find('<div class="thread', start + 1)
        return threads[start:end if end > 0 else len(threads)]

    def test_threads_lead_and_the_graph_sits_behind_explore(self):
        # #143: Recent work, Due and overdue, A thought and Waiting on you are gone.
        self.actions("[[Pricing]]: send the floor 📅 %s" % self.now.date())
        html = self.page()
        tab = overview(html)
        self.assertEqual(["threads", "todo", "inboxes", "graph"], card_order(tab))
        self.assertIn('<div class="slot full" data-slot="top"><details class="card" id="threads" open>', tab)
        self.assertIn('<div class="slot stack left" data-slot="left"><details class="card" id="todo"', tab)
        for gone in ("recent", "due", "thought", "waiting"):
            self.assertNotIn('id="%s"' % gone, html, gone)
        for gone in ("Recent work", "Due and overdue", "Waiting on you", "<textarea"):
            self.assertNotIn(gone, html, gone)
        self.assertIn('<details class="card" id="graph">', tab)                    # folded shut: Explore opens it
        self.assertNotIn('class="top"', tab)                                       # the figures stay on Status
        machinery = html[html.index('id="tab-status"'):html.index("</section>", html.index('id="tab-status"'))]
        for cid in ("jobs", "checks", "repos", "wikis"):                           # the Status tab is untouched
            self.assertNotIn('id="%s"' % cid, tab, cid)
        self.assertIn('id="checks"', machinery)
        self.assertLess(machinery.index('class="top"'), machinery.index('class="onlybar"'))

    def test_parked_and_finished_work_stays_out(self):
        note = self.root / "Zones" / "Work" / "Acme Review" / "Threads" / "Pricing" / "Pricing.md"
        note.write_text(thread_note("Acme Review", "Pricing", "acme", status="parked"))
        done = self.root / "Zones" / "Work" / "Birch Entry" / "Threads" / "Market Sizing" / "Market Sizing.md"
        done.write_text(thread_note("Birch Entry", "Market Sizing", "birch", status="done"))
        self.actions("[[Pricing]]: send the floor 📅 2026-03-18")
        threads = self.rows(self.page(), "threads")
        parked = threads[threads.index('<details class="parked'):]
        self.assertIn("Pricing", parked)                                     # in its fold, and quiet there
        self.assertNotIn("send the floor", parked)
        self.assertNotIn("tchip", parked)
        self.assertNotIn(">Market Sizing<", threads)

    def test_age_alone_is_never_a_fault(self):
        self.touched("Acme Review", "Pricing", "2025-01-01")        # well over a year
        html = self.page()
        threads = self.rows(html, "threads")
        self.assertNotIn('class="fresh warning', threads)           # no amber, no red for age
        self.assertNotIn('class="fresh critical', threads)
        self.assertIn('class="fresh age mu"', threads)              # a plain bar, and the figure beside it
        self.assertRegex(threads, r'class="num muted mu" style="text-align:right">\d+d<')
        self.assertNotIn("aging", threads)
        self.assertNotIn("stale", threads)
        self.assertNotIn("Over 45 days", html)
        self.assertNotIn("15 to 45 days", html)
        self.assertIn("a figure, not a fault", threads)
        self.assertIn("Last touched ", status.PANEL_JS)              # and the card says it plainly
        self.assertNotIn("Aging", status.PANEL_JS)
        row = threads[threads.index('data-card="%s' % htmllib.escape('{"n":"Pricing"', quote=True)) - 40:]
        self.assertIn('data-ok="1"', row[:60])                       # not something that needs attention
        self.assertNotIn("n.d>45", status.GRAPH_JS)                  # nor on the graph: its ring is the action's
        self.assertIn("function ring(n){return n.s||!n.lt?null:C['--critical']}", status.GRAPH_JS)

    def chips(self, row):
        """The chips under a row's name, as their words: `todo 2`, `check`."""
        small = re.search(r'<div class="t">.*?</div>', row, re.S).group(0)
        return [htmllib.unescape(t) for t in re.findall(r'<button type="button" class="chip tchip[^"]*"[^>]*>([^<]*)</button>', small)]

    def pop(self, row, kind):
        """The list a row's `todo` (tp) or `check` (cp) chip opens."""
        m = re.search(r'<div class="tpop" id="%s-[0-9a-f]+" hidden>' % kind, row)
        return row[m.start():] if m else ""

    def test_a_thread_with_open_actions_shows_only_its_todo_chip(self):
        # #179's follow-up: the next action no longer sits under the name; the chip carries the count.
        self.actions("[[Pricing]]: send the renewal floor to Dana 📅 2026-03-18",
                     "[[Market Sizing]]: chase the survey #waiting ⏳ 2026-03-19")
        html = self.page()
        for name in ("Pricing", "Market Sizing"):
            row = self.row(html, name)
            self.assertEqual(["todo 1"], self.chips(row), name)
            head = re.search(r'<div class="t">.*?</div>', row, re.S).group(0)
            self.assertEqual(name, re.sub(r"<[^>]+>|todo 1", "", head).strip(), name)     # no text under the name
            self.assertNotIn("tnext", row)
            self.assertNotIn("no next action", row)
        self.assertNotIn("tnext", status.CSS + status.HOME_CSS + status.TVIEW_CSS)

    def test_the_legend_reads_as_a_line_of_text_beside_its_swatch(self):
        # From 0.36.0 (#179): every text node and <code> of an entry was a flex item of its own, so the
        # sentence wrapped into narrow columns. An entry is its swatch and one run of text.
        legend = re.search(r'<div class="legend mu">(.*?)</div>', self.page(), re.S).group(1)
        entries = re.findall(r'<span><i[^>]*></i>(<span class="lt">.*?</span>)</span>', legend)
        self.assertEqual(2, len(entries), legend)
        self.assertIn("A red <code>todo</code>: an open action is overdue", entries[0])
        self.assertEqual("", re.sub(r'<span><i[^>]*></i><span class="lt">.*?</span></span>', "", legend))   # nothing loose
        self.assertIn(".legend>span{display:inline-flex", status.CSS)
        self.assertNotIn(".legend span{display:inline-flex", status.CSS)                 # not the text's own span

    def test_the_chip_sits_on_the_names_line_not_under_it(self):
        # #186: at the name's right, so a row with open actions takes one line; text under a name keeps its own.
        self.actions("[[Pricing]]: send the renewal floor to Dana 📅 2026-03-18",
                     "[[Market Sizing]]: chase the survey #waiting ⏳ 2026-03-19")
        html = self.page()
        for name in ("Pricing", "Market Sizing"):
            head = re.search(r'<div class="t">.*?</div>', self.row(html, name), re.S).group(0)
            self.assertRegex(head, r'</a>(?:<span class="live[^>]*></span>)?<span class="tchips"><button type="button" '
                                   r'class="chip tchip todo', name)
            self.assertNotRegex(head, r"<small>[^<]*<button", name)
        css = status.CSS
        self.assertIn(".thread:not(.proj)>.t>.tchips{flex:none", css)          # never squeezed: the name's ellipsis goes first
        self.assertIn(".thread:not(.proj)>.t>a{flex:0 1 auto;min-width:0", css)
        self.assertIn(".thread:not(.proj)>.t>small{flex:0 0 100%", css)        # text under the name stays below it

    def test_two_open_lines_neither_late_show_a_green_todo_2(self):
        later = self.now.date() + dt.timedelta(days=5)
        self.actions("[[Pricing]]: send the renewal floor to Dana 📅 %s" % later, "[[Pricing]]: book the call with Dana")
        pricing = self.row(self.page(), "Pricing")
        self.assertEqual(["todo 2"], self.chips(pricing))
        self.assertIn('class="chip tchip todo ok"', pricing)
        self.assertIn('title="2 open actions, none late. Click to list them">todo 2</button>', pricing)
        self.assertIn('data-ok="1"', pricing[:60])                             # owed, and nothing late: not a fault
        listed = self.pop(pricing, "tp")
        self.assertIn("2 open, none late", listed)
        self.assertEqual(2, listed.count(' data-k="'))
        self.assertEqual(2, listed.count('<button class="tick" type="button"'))    # each with its box, as the Todo tab draws it

    def test_a_late_line_turns_the_chip_red_and_leads_its_list(self):
        self.touched("Acme Review", "Pricing", str(self.now.date()))          # touched today: the red is the line's
        later = self.now.date() + dt.timedelta(days=5)
        self.actions("[[Pricing]]: book the call with Dana 📅 %s" % later, "[[Pricing]]: send the floor 📅 2026-03-01")
        html = self.page()
        threads, pricing = self.rows(html, "threads"), self.row(html, "Pricing")
        self.assertEqual(["todo 2"], self.chips(pricing))
        self.assertIn('class="chip tchip todo late"', pricing)
        self.assertIn('title="1 of 2 open actions late: send the floor, was due Sun 1 Mar. Click to list them"', pricing)
        listed = self.pop(pricing, "tp")
        self.assertIn("2 open · 1 late", listed)
        self.assertLess(listed.index("send the floor"), listed.index("book the call"))       # the late one first
        self.assertIn('<span class="lateby">was due Sun 1 Mar</span>', listed)                 # said in words, not by colour alone
        self.assertIn('data-ok="0"', threads)
        self.assertIn("1 needing a chase", threads)                          # the project's row, and its zone's meta
        for gone in (">overdue</span>", ">chase due</span>"):
            self.assertNotIn(gone, threads)

    def test_the_row_carries_its_urgency_so_a_park_recounts_in_the_same_words(self):
        self.touched("Acme Review", "Pricing", str(self.now.date()))
        self.actions("[[Pricing]]: send the floor 📅 2026-03-01")
        html = self.page()
        self.assertEqual(1, cards(html)[("Acme Review", "Pricing")]["lt"])          # the card says it, not its age
        self.assertNotIn("lt", cards(html)[("Birch Entry", "Market Sizing")])
        self.assertIn("' · '+a+' needing a chase'", status.PARK_JS)                 # and PARK_JS recounts in those words
        self.assertIn("' · '+urg+' needing a chase'", status.PARK_JS)
        for word in ("aging", "stale", ".fresh.warning", ".fresh.critical"):
            self.assertNotIn(word, status.PARK_JS, word)

    def test_a_chase_date_that_has_come_is_late_too(self):
        self.actions("[[Pricing]]: chase Dana #waiting ⏳ %s" % self.now.date())
        pricing = self.row(self.page(), "Pricing")
        self.assertIn('class="chip tchip todo late"', pricing)
        self.assertIn("chase Dana, to chase since today", pricing)
        self.assertIn('<span class="lateby">to chase since today</span>', self.pop(pricing, "tp"))

    def test_ticking_the_only_line_leaves_the_row_with_no_chip(self):
        self.actions("[[Pricing]]: send the floor 📅 2026-03-01")
        self.assertEqual(["todo 1"], self.chips(self.row(self.page(), "Pricing")))
        write(self.root / "Zones" / "Work" / "Todo.md",
              "# Work: open actions\n\n## Inbox\n\n## Done\n\n- [x] [[Pricing]]: send the floor 📅 2026-03-01 ✅ %s\n" % self.now.date())
        html = self.page()                                              # the rebuild after the tick
        pricing = self.row(html, "Pricing")
        self.assertEqual([], self.chips(pricing))
        self.assertNotIn('class="tpop"', pricing)
        self.assertNotIn("<small>", pricing)                            # its name and its age bar, nothing else
        self.assertIn('data-ok="1"', pricing[:60])
        self.assertIn(">1 thread<", self.rows(html, "threads"))         # and the project's row adds no count for it

    def fake_check(self, *findings):
        tools = self.root / "System" / "tools"
        tools.mkdir(parents=True, exist_ok=True)
        errors = sum(1 for f in findings if f["severity"] == "error")
        (tools / "check.py").write_text("import json\nprint(json.dumps(%r))\n" % {
            "errors": errors, "warnings": len(findings) - errors, "findings": list(findings)})

    def test_a_warning_never_marks_a_row(self):
        self.fake_check({"check": "deliverables", "severity": "warning",
                         "path": "Zones/Work/Acme Review/Threads/Pricing/261019 6.55pm - Deck.pptx",
                         "message": "name does not start with its creation date, `YYMMDD - <name>`"})
        html = self.page()
        pricing = self.row(html, "Pricing")
        self.assertEqual([], self.chips(pricing))
        self.assertIn('data-ok="1"', pricing[:60])
        self.assertIn("261019 6.55pm - Deck.pptx", self.rows(html, "checks"))     # it stays on the Checks card

    def test_an_error_the_page_cannot_explain_marks_no_row(self):
        self.fake_check({"check": "threads", "severity": "error",
                         "path": "Zones/Work/Acme Review/Threads/Pricing/Pricing.md", "message": "a kind no entry knows"})
        self.assertEqual([], self.chips(self.row(self.page(), "Pricing")))

    def test_an_error_finding_shows_check_with_what_is_wrong_and_what_fixes_it(self):
        self.fake_check({"check": "threads", "severity": "error",
                         "path": "Zones/Work/Acme Review/Threads/Pricing/Pricing.md", "message": "no `### Resume here` block"})
        pricing = self.row(self.page(), "Pricing")
        self.assertEqual(["check"], self.chips(pricing))
        self.assertIn('class="chip tchip check late"', pricing)
        self.assertIn('data-ok="0"', pricing[:60])
        found = self.pop(pricing, "cp")
        self.assertIn("<b>Pricing.md</b> It has no Resume here block, so nobody can pick it up cold.", found)
        self.assertIn("Wrap it: a wrap writes the block.", found)
        self.assertIn('data-copy="wrap Pricing"', found)                     # no mechanical fix: the request to copy
        self.assertNotIn('"verb": "fix"', htmllib.unescape(found))

    def test_a_wall_finding_is_explained_without_its_material(self):
        self.fake_check({"check": "walls", "severity": "error",
                         "path": "Zones/Work/Acme Review/Threads/Pricing/Pricing.md",
                         "message": "names Birch Entry, but a wall stands between acme and birch"})
        pricing = self.row(self.page(), "Pricing")
        self.assertEqual(["check"], self.chips(pricing))
        found = self.pop(pricing, "cp")
        self.assertIn("from the far side of a wall", found)
        self.assertIn('data-copy="nurture Pricing"', found)
        for said in ("birch", "Birch", "a wall stands between"):
            self.assertNotIn(said, pricing)

    def test_a_missing_resume_block_keeps_its_count_on_the_project_row(self):
        note = self.root / "Zones" / "Work" / "Acme Review" / "Threads" / "Pricing" / "Pricing.md"
        text = note.read_text(encoding="utf-8")
        note.write_text(re.sub(r"### Resume here.*?(?=\n## |\Z)", "", text, flags=re.S), encoding="utf-8")
        html = self.page()
        self.assertIn("1 thread · 1 without a resume block", self.rows(html, "threads"))
        self.assertNotIn("no resume block</span>", self.row(html, "Pricing"))      # on the row it is the check's error (#179)
        self.assertEqual(0, cards(html)[("Acme Review", "Pricing")]["r"])          # and its card still says so

    def test_by_name_or_recent(self):
        threads = self.rows(self.page(), "threads")
        self.assertIn('<div class="tview" data-tm="updated" data-to="name">', threads)
        self.assertIn('<div class="tmodes torder" role="group" aria-label="Order"><button type="button" data-to="name" class="on" '
                      'aria-pressed="true">By name</button><button type="button" data-to="recent" aria-pressed="false">Recent</button></div>',
                      threads)
        self.assertIn("· by name ·", threads)                         # the line under the card says which
        self.assertIn("garrick-threads-order", status.TVIEW_JS)       # remembered in this window, and Reset view clears it
        self.assertTrue("garrick-threads-order".startswith("garrick-"))

    def test_an_empty_workspace_offers_the_one_request(self):
        shutil.rmtree(self.root / "Zones" / "Work" / "Acme Review")
        shutil.rmtree(self.root / "Zones" / "Work" / "Birch Entry")
        html = self.page()
        tab = overview(html)
        self.assertEqual(["start", "threads", "todo", "inboxes", "graph"], card_order(tab))
        start = self.rows(html, "start")
        self.assertIn("help me prepare my next supplier call", start)              # the skill's own request
        self.assertIn("Nothing there yet: from an ordinary request to a saved brief", start)
        self.assertIn("System/skills/meetings/SKILL.md", start)
        self.assertIn("written there, not here", start)
        for step in ("scaffold.py party", "git commit", "Shall I add it as a party"):   # the route is not copied here
            self.assertNotIn(step, html, step)

    def test_a_long_name_and_a_long_action_keep_the_rows_whole(self):
        long_thread = "Supply Chain Resilience And Procurement Review Programme"
        write(self.root / "Zones" / "Work" / "Acme Review" / "Threads" / long_thread / (long_thread + ".md"),
              thread_note("Acme Review", long_thread, "acme"))
        self.actions("[[%s]]: %s 📅 2026-03-01" % (long_thread, "chase the quote " * 20))
        html = self.page()
        row = self.row(html, long_thread)
        self.assertIn(">%s</a>" % long_thread, row)                                # whole, never cut
        self.assertIn("chase the quote " * 19, row)
        self.assertIn(".thread .t small{display:block;color:var(--muted);font-size:11.5px;overflow:hidden;"
                      "text-overflow:ellipsis;white-space:nowrap}", status.CSS)    # one line, cut by the browser
        self.assertIn(".thread .t a{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}", status.CSS)

    def test_every_control_can_be_reached_from_the_keyboard(self):
        self.actions("[[Pricing]]: send the floor 📅 2026-03-01")
        html = self.page()
        threads = self.rows(html, "threads")
        self.assertIn('<summary class="head">', threads)                           # the fold itself takes the focus
        for button in re.findall(r'<button[^>]*data-to=[^>]*>', threads) + re.findall(r"<button[^>]*>", status.THOUGHT_LEFT):
            self.assertIn('type="button"', button, button)                         # never a submit, always focusable
            self.assertNotIn('tabindex="-1"', button, button)
        self.assertEqual(2, len(re.findall(r'<button[^>]*data-to=', threads)))
        self.assertNotIn("outline:none", status.HOME_CSS)                          # nothing here takes the focus ring away


class TestCheckpointChip(StatusCase):
    """The checkpoint beside a resume point, read from the block's comment line
    and nothing else: a chip saying when the work was recorded, or that the
    block is out of date, and the order Recent gives the Threads card. No
    content of the block reaches the page, and the page gets no button for
    it: confirming a checkpoint is a wrap."""

    def setUp(self):
        super().setUp()
        # Whether a block is out of date is the workspace's own `resume_hash`
        # to answer, so the page reads a note the way the check does.
        tools = self.root / "System" / "tools"
        tools.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / "template" / "System" / "tools" / "garrick_lib.py", tools / "garrick_lib.py")
        status._LIBS.clear()
        self.addCleanup(status._LIBS.clear)

    def note(self, project="Acme Review", thread="Pricing"):
        return self.root / "Zones" / "Work" / project / "Threads" / thread / (thread + ".md")

    def put(self, project="Acme Review", thread="Pricing", **kw):
        note = self.note(project, thread)
        note.write_text(fixtures.checkpoint(note.read_text(encoding="utf-8"), **kw), encoding="utf-8")
        return note

    def updated(self, project, thread, day):
        note = self.note(project, thread)
        note.write_text(note.read_text(encoding="utf-8").replace("updated: 2026-03-01", "updated: " + day),
                        encoding="utf-8")

    def touched(self, html, name):
        """What Recent on the Threads card sorts a row by: its data-r."""
        card = 'data-card="%s' % htmllib.escape('{"n":"%s"' % name, quote=True)
        tag = html[html.index(card):]
        return re.search(r' data-r="([^"]*)"', tag[:tag.index(">")]).group(1)

    def test_the_chip_says_when_the_work_was_recorded(self):
        self.put()
        html = self.page()
        self.assertIn(">unwrapped since 14:32</span>", html)
        self.assertIn("Work this session recorded at 14:32 on 14 March 2026 and no wrap has folded in yet", html)
        self.assertNotIn("checkpoint out of date", html)

    def test_a_block_a_wrap_left_behind_says_it_is_out_of_date(self):
        self.put(base="0" * 12)
        html = self.page()
        self.assertIn(">checkpoint out of date</span>", html)
        self.assertIn("was written against an older resume point", html)
        self.assertNotIn("unwrapped since", html)

    def test_no_content_of_the_block_reaches_the_page(self):
        self.put()
        html = self.page()
        for held in ("tier-two rate as drafted", "dropping tier three", "row 14", "send Dana the price sheet",
                     "tier-three tab is half filled", "Pricing memo.md", "garrick-checkpoint", "Unconfirmed"):
            self.assertNotIn(held, html, held)

    def test_the_page_offers_no_way_to_write_or_confirm_one(self):
        self.put()
        html = self.page()
        self.assertNotIn('"checkpoint"', html)
        self.assertNotIn("verb: 'checkpoint'", html)
        self.assertNotIn("checkpoint", status.ZONE_VERBS)

    def test_recent_orders_by_the_later_of_updated_and_the_checkpoint(self):
        self.updated("Birch Entry", "Market Sizing", "2026-03-20")
        html = self.page()
        self.assertEqual(("2026-03-01", "2026-03-20"), (self.touched(html, "Pricing"), self.touched(html, "Market Sizing")))
        self.put(at="2026-03-25T14:32:10+01:00")                    # unwrapped work since that wrap
        html = self.page()
        self.assertEqual("2026-03-25", self.touched(html, "Pricing"))
        self.assertEqual("2026-03-25", self.touched(html, "Acme Review"))      # the project's row, its newest thread's

    def test_the_days_figure_stays_the_days_since_the_note_moved(self):
        self.put(at="2026-03-25T14:32:10+01:00")
        row = status.threads(self.root)["Work"]["rows"]
        pricing = next(r for r in row if r["thread"] == "Pricing")
        self.assertEqual(dt.date(2026, 3, 1), pricing["updated"])
        self.assertEqual(dt.date(2026, 3, 25), pricing["touched"])

    def test_a_block_that_cannot_be_read_still_carries_its_time(self):
        note = self.put()
        note.write_text(note.read_text(encoding="utf-8").replace("dropping tier three", "dropping tier two"),
                        encoding="utf-8")
        html = self.page()
        self.assertIn("unwrapped since 14:32", html)        # the comment line is all the page reads
        self.assertNotIn("dropping tier two", html)

    def test_without_the_workspaces_own_library_the_time_still_shows(self):
        self.put(base="0" * 12)
        (self.root / "System" / "tools" / "garrick_lib.py").unlink()
        status._LIBS.clear()
        html = self.page()
        self.assertIn("unwrapped since 14:32", html)        # true either way
        self.assertNotIn("checkpoint out of date", html)    # the second claim would be a guess

    def test_a_thread_with_no_checkpoint_has_no_chip(self):
        html = self.page()
        self.assertNotIn("unwrapped since", html)
        self.assertNotIn("checkpoint out of date", html)
        self.assertIsNone(status.checkpoint_mark(self.note(), self.root))


class TestSelfContained(StatusCase):
    def test_nothing_from_the_network(self):
        # Settings' links to Garrick's GitHub page are the only web addresses,
        # and only as links the reader follows; TestSettings holds them to that.
        html = re.sub(r'<a class="setlink" href="https://github\.com/iamvenuti/garrick/[^"]*"', "<a", self.page())
        html = re.sub(r'<a href="https://github\.com/iamvenuti/garrick/security/advisories/new"', "<a", html)
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
        self.assertEqual(["Birch Entry", "Market Sizing"], thread_order(html, 'id="parked-work"'))

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
        rows = [json.loads(htmllib.unescape(raw)) for raw in re.findall(r'class="thread(?: sub)?"[^>]*data-card="([^"]*)"', html)]
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
        block = html[start:html.index('<div class="legend', start)]
        self.assertEqual(set(re.findall(r'<button type="button" class="(\w+)"', block)), {"pchev"})   # only the folds of a project's threads
        self.assertEqual(block.count("<button"), block.count('class="pchev"'))
        self.assertNotIn("data-tip", block)
        self.assertEqual({("Acme Review", "Pricing"), ("Birch Entry", "Market Sizing")}, set(cards(html)))

    @mock.patch.object(status, "desk_ready", return_value=False)      # the desk's keys depend on cmux; tested with a fake one in test_status_more
    def test_a_card_carries_names_tags_dates_status_and_phrases_only(self, _desk):
        note = self.root / "Zones" / "Work" / "Acme Review" / "Threads" / "Pricing" / "Pricing.md"
        note.write_text(thread_note("Acme Review", "Pricing", "acme", "The renewal floor is a private figure."))
        card = cards(self.page(now=dt.datetime(2026, 3, 11, 9, 0)))[("Acme Review", "Pricing")]
        self.assertEqual({"n", "kl", "z", "p", "t", "d", "s", "w", "h", "u", "r", "rd", "mg", "pa", "oc"}, set(card))
        self.assertEqual(["Work", "Acme Review/Threads/Pricing/Pricing.md"], card["oc"])     # what Open in Claude continues (#180)
        self.assertEqual((1, 10), (card["r"], card["rd"]))                     # a Resume here block, dated 1 March
        self.assertEqual(("Pricing", "thread", "Work", "Acme Review", ["acme"], 10, 0, "Pricing", 0),
                         tuple(card[k] for k in ("n", "kl", "z", "p", "t", "d", "s", "w", "h")))
        self.assertTrue(card["u"].startswith("file://") and card["u"].endswith("/Pricing/Pricing.md"))
        self.assertNotIn("private figure", json.dumps(card))

    def page(self, **kw):
        return status.build(self.root, folder=self.jobs, **dict({"now": self.now}, **kw))

    def test_one_helper_builds_both_sets_of_actions(self):
        # The graph panel and the thread card draw their actions from Panel.acts
        # and their heading from Panel.head; neither builds a button of its own.
        self.assertEqual(1, status.PANEL_JS.count("function acts("))
        for label in (">Open</a>", "Copy “", "'open '", "'wake '", "'park '"):
            self.assertIn(label, status.PANEL_JS)
        for js in (status.JS, status.GRAPH_JS):
            # a row's card as itself, the graph's as a panel, with Preview before the rest (#206)
            self.assertRegex(js, r"Panel\.head\(o(,1)?\)\+Panel\.acts\(o(,window\.GarrickNote\?GarrickNote\.button\(notePath\(n\),n\.N\|\|n\.n\):'')?\)")
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
        self.assertEqual(["Acme Review", "alpha", "Pricing", "Zebra", "Birch Entry", "Market Sizing"], thread_order(html))   # projects, then threads, by name
        self.assertEqual(["Acme Review", "Aardvark", "beta"], thread_order(html, 'id="parked-work"'))


class TestProjectRows(StatusCase):
    """Issue #14: threads fold under an expandable row for their project."""

    def test_a_project_row_folds_its_threads(self):
        write(self.root / "Zones" / "Work" / "Cedar Notes" / "Cedar Notes.md", project_hub("Work", "Cedar Notes", "cedar"))
        html = self.page()
        zone = html[html.index('id="zone-work"'):]
        zone = zone[:zone.index("</details>")]
        self.assertIn('<button type="button" class="pchev" data-sub="sub-work-acme-review" aria-expanded="false" title="Show its 1 thread">', zone)
        self.assertIn('<div class="subthreads tsort" id="sub-work-acme-review" hidden><div class="thread sub"', zone)
        self.assertIn('<span class="muted subn">1 thread</span>', zone)
        self.assertNotIn('data-sub="sub-work-cedar-notes"', zone)           # a project with no thread notes is a row of its own
        project = [c for c in re.findall(r'class="thread proj"[^>]*data-card="([^"]*)"', zone)]
        self.assertEqual({json.loads(htmllib.unescape(c))["kl"] for c in project}, {"project"})
        self.assertIn("st.get('garrick-fold-'+b.dataset.sub)==='1'", status.JS)   # the fold is remembered


class TestSettings(StatusCase):
    """Settings › About Garrick: the version, and links to Garrick's GitHub page."""

    def dialog(self):
        html = self.page()
        return html[html.index('<dialog id="settings"'):html.index("</dialog>", html.index('<dialog id="settings"'))]

    def stamp(self):
        (self.root / "System" / "tools").mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / "template" / "System" / "tools" / "garrick_lib.py", self.root / "System" / "tools")
        write(self.root / "System" / "garrick-version.json",
              json.dumps({"commit": "abc1234", "date": "2026-10-04", "from": "download"}))
        status._LIBS.clear()

    def hrefs(self, dialog):
        return [htmllib.unescape(h) for h in re.findall(r'href="(https://[^"]*)"', dialog)]

    def test_without_a_stamp_the_version_is_unknown(self):
        self.assertIn(htmllib.escape(status.UNKNOWN), self.dialog())

    def test_the_version_is_the_stamps(self):
        self.stamp()
        self.assertIn("Garrick abc1234 of 4 October 2026, installed from a download.", self.dialog())

    def test_the_bug_form_arrives_with_the_version(self):
        self.stamp()
        bug = next(h for h in self.hrefs(self.dialog()) if "/issues/new?template=bug.yml" in h)
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(bug).query)
        form = (REPO / ".github" / "ISSUE_TEMPLATE" / query["template"][0]).read_text(encoding="utf-8")
        self.assertIn("id: garrick\n", form)                  # the field the link fills must still exist
        self.assertTrue(query["garrick"][0].startswith("Garrick abc1234 of 4 October 2026"))

    def test_links_go_only_to_garrick_and_open_outside(self):
        dialog = self.dialog()
        links = self.hrefs(dialog)
        self.assertEqual(8, len(links))
        for h in links:
            self.assertTrue(h.startswith(status.PROJECT + "/"), h)
        for tag in re.findall(r'<a [^>]*href="https://[^>]*>', dialog):
            self.assertIn('target="_blank" rel="noopener"', tag)
        self.assertTrue((REPO / ".github" / "ISSUE_TEMPLATE" / "wall-check.yml").is_file())
        chooser = (REPO / ".github" / "ISSUE_TEMPLATE" / "config.yml").read_text(encoding="utf-8")
        self.assertIn(status.PROJECT + "/discussions/categories/ideas", chooser)   # the same category the chooser names
        self.assertIn(status.PROJECT + "/discussions/new?category=ideas", links)
        self.assertIn(status.PROJECT + "/releases", links)
        self.assertIn(status.PROJECT + "/discussions/categories/announcements", links)

    def test_a_report_to_copy_carries_the_version_and_the_warning(self):
        self.stamp()
        report = htmllib.unescape(re.search(r'data-copy="([^"]*)"[^>]*>Copy a report<', self.dialog()).group(1))
        self.assertIn("Which Garrick: Garrick abc1234", report)
        self.assertIn("invented names", report)

    def test_each_explanation_is_behind_a_question_mark(self):
        dialog = self.dialog()
        for key, name in (("launchers", "Opening a thread"), ("zones", "Zones"), ("menu", "Menu bar"),
                          ("about", "About Garrick"), ("preview", "Preview features")):
            self.assertIn('<h3>%s<button class="qhelp" type="button" aria-expanded="false" aria-controls="help-%s" '
                          'aria-label="Explain %s"' % (name, key, name), dialog)      # a button, so the keyboard reaches it
        for key in ("launchers", "zones", "menu", "about", "preview", "view"):
            self.assertEqual(1, dialog.count('<p class="hint sethelp" id="help-%s" hidden>' % key), key)   # hidden until asked for
        self.assertNotIn('<p class="hint">', dialog)                                  # no explanation left showing
        self.assertNotIn("<h3>View</h3>", dialog)                                     # the section went; its button stayed
        self.assertIn("q.setAttribute('aria-expanded',String(!p.hidden))", status.JS)
        for key, lede in (("launchers", "Which apps a project or thread can open in"), ("about", "Which Garrick this is"),
                          ("preview", "Features that are built but not released yet")):
            self.assertRegex(dialog, r'aria-controls="help-%s"[^>]*>\?</button></h3><p class="setlede">%s' % (key, lede))  # said, not asked for

    def test_explanations_keep_their_words(self):
        dialog = htmllib.unescape(self.dialog())
        for words in ("Tick what project and thread cards offer; the dot marks what clicking a thread's name does.",
                      "A colour and an icon for each zone, shown wherever the page names it.",
                      "A menu of the live projects of the zone the graph shows, with their threads, kept at hand outside this window.",
                      "These open GitHub in your browser. The page sends nothing: a report goes only when you submit it there.",
                      "In Garrick's source but not yet released, so they may still change.",
                      "Cards dragged or hidden, folds, the graph's view and the open tab are remembered in this window only."):
            self.assertIn(words, dialog)

    def test_a_bypass_has_a_row_of_its_own(self):
        dialog = self.dialog()
        row = re.search(r'<a class="setlink" href="([^"]*)"[^>]*><b>Report a bypass privately</b>', dialog)
        self.assertIsNotNone(row)
        self.assertEqual(status.PROJECT + "/security/advisories/new", htmllib.unescape(row.group(1)))
        para = dialog[dialog.index('id="help-about"'):]
        self.assertIn('<a href="%s" target="_blank" rel="noopener">report it privately</a>' % row.group(1), para)   # the same address
        labels = re.findall(r'class="setlink"[^>]*><b>([^<]+)</b>', dialog)
        self.assertEqual(["Report a bug", "Report a wrong refusal", "Report a bypass privately"], labels[:3])

    def test_the_forms_that_publish_warn_in_their_tooltip(self):
        dialog = self.dialog()
        warn = htmllib.escape("Use invented names (Acme, Birch), never a real client's.")
        for label in ("Report a bug", "Report a wrong refusal"):
            self.assertRegex(dialog, r'<a class="setlink" [^>]*title="%s"><b>%s</b>' % (re.escape(warn), label))
        self.assertEqual(2, dialog.count('title="%s"' % warn))

    def test_reset_view_is_a_button_at_the_foot(self):
        dialog = self.dialog()
        foot = dialog[dialog.index('<div class="setfoot">'):]
        self.assertGreater(dialog.index('<div class="setfoot">'), dialog.index('id="help-preview"'))   # after the last section
        button = re.search(r'<button class="act" type="button" id="reset-view" title="([^"]*)">Reset view</button>', foot)
        self.assertIsNotNone(button)
        self.assertTrue(htmllib.unescape(button.group(1)).startswith(
            "Cards dragged or hidden, folds, the graph's view and the open tab are remembered in this window only."))
        self.assertIn('aria-controls="help-view" aria-label="Explain Reset view"', foot)
        self.assertIn('<div class="hiddencards" id="hidden-cards" hidden></div>', foot)

    def test_the_app_opens_it(self):
        swift = (REPO / "extras" / "status" / "app" / "Garrick.swift").read_text(encoding="utf-8")
        self.assertIn("window.StatusSettings.open()", swift)
        self.assertIn("window.StatusSettings=", status.JS)


class TestSettingsLayout(StatusCase):
    """Settings as one column of sections, read in order, with the list of
    them beside it (#205): a link per section, grouped by what people come
    for, and the one being read marked."""

    ORDER = ["home-settings", "launcher-settings", "follow-settings", "zone-settings", "menu-settings", "wait-settings",
             "notify-settings", "catch-settings", "memory-settings", "about-settings", "preview-settings"]

    def dialog(self, **kw):
        html = self.page(**kw)
        return html[html.index('<dialog id="settings"'):html.index("</dialog>", html.index('<dialog id="settings"'))]

    def test_one_column_in_the_order_the_list_names(self):
        fixtures.write_fade_stub(self.root)
        dialog = self.dialog()
        nav = dialog[dialog.index('<nav class="setnav" aria-label="Settings sections">'):dialog.index("</nav>")]
        listed = re.findall(r'<a href="#([a-z-]+)" data-setgo="\1">', nav)
        built = re.findall(r'<section class="setsec[^"]*" id="([a-z-]+)"', dialog)
        self.assertEqual(built, listed)                                             # every section, once, in its order
        self.assertEqual([k for k in self.ORDER if k in built], built)
        for must in ("home-settings", "launcher-settings", "zone-settings", "menu-settings", "notify-settings",
                     "memory-settings", "about-settings", "preview-settings"):
            self.assertIn(must, built)
        heads = dict(re.findall(r'<section class="setsec[^"]*" id="([a-z-]+)"[^>]*><h3>([^<]+)<', dialog))
        self.assertEqual(heads, dict(re.findall(r'data-setgo="([a-z-]+)">([^<]+)</a>', nav)))   # named as its heading
        self.assertEqual("Manage older material", heads["memory-settings"])
        self.assertEqual([t for _, t in status.SET_GROUPS], re.findall(r'<p class="setnavh" id="sn-[a-z]+">([^<]+)</p>', nav))
        self.assertEqual([t for _, t in status.SET_GROUPS], re.findall(r'<p class="setgrp" id="sg-[a-z]+">([^<]+)</p>', dialog))
        main = dialog[dialog.index('<div class="setmain" id="settings-main">'):]
        self.assertLess(main.index('id="notify-settings"'), main.index('id="memory-settings"'))
        self.assertLess(main.index('id="preview-settings"'), main.index('<div class="setfoot">'))   # Reset view at the end
        self.assertNotIn("setcols", dialog)
        self.assertEqual(len(built), dialog.count('<p class="setlede">'))           # each opens with what it is for

    def test_a_section_left_out_is_not_listed(self):
        dialog = self.dialog()                                                      # no fade.py here
        self.assertNotIn('id="memory-settings"', dialog)
        self.assertNotIn("#memory-settings", dialog)
        self.assertNotIn("How it keeps older material", dialog)                     # nor its group

    def test_the_list_follows_what_the_host_shows_and_marks_where_the_reader_is(self):
        js = status.JS
        self.assertIn("function snShown(s){return!!s&&!s.hidden&&getComputedStyle(s).display!=='none'}", js)   # .apponly, Menu bar
        self.assertIn("a.parentNode.hidden=!snShown(document.getElementById(a.dataset.setgo))", js)
        self.assertIn("g.hidden=!g.querySelector('li:not([hidden])')", js)                # a group with none left goes
        self.assertIn("a.setAttribute('aria-current','true')", js)
        self.assertIn("sd.showModal();snHold=null;snSync()", js)                         # checked each time it opens
        self.assertIn("s.focus({preventScroll:true})", js)                               # the keyboard lands on the section
        css = status.SETTINGS_CSS
        self.assertIn("dialog.settings[open]{display:flex;flex-direction:column}", css)
        self.assertIn(".setbody{flex:1 1 auto;min-height:0;display:grid;grid-template-columns:212px minmax(0,1fr)}", css)
        self.assertIn(".setmain{position:relative;overflow:auto", css)
        self.assertIn("max-width:1040px", css)
        self.assertIn("@media (max-width:759px){.setbody{grid-template-columns:minmax(0,1fr)", css)   # a strip on top
        self.assertIn(".setnav a[aria-current]", css)
        self.assertIn(".nohost .apponly{display:none}", css)

    @unittest.skipUnless(shutil.which("node"), "Node is not installed")
    def test_the_script_parses(self):
        done = subprocess.run(["node", "-e", "new Function(require('fs').readFileSync(0,'utf8'))"], input=status.JS,
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(0, done.returncode, done.stderr)


class TestWaitSettings(StatusCase):
    """Settings › While you wait (#111): next_up.py's keys, drawn and read back."""

    def section(self):
        html = self.page()
        start = html.index('<section class="setsec apponly" id="wait-settings">')
        return html[start:html.index("</section>", start)]

    def lib(self):
        return status.wait_lib(self.root)

    def test_the_defaults_as_next_up_has_them(self):
        sec = self.section()
        self.assertIn('<input type="checkbox" id="w-on" checked>', sec)
        self.assertIn('<input type="checkbox" id="w-zone">', sec)
        self.assertIn('data-wnum="threshold" min="10" max="600" value="45"', sec)
        self.assertIn('data-wnum="parked-days" min="1" max="365" value="30"', sec)
        self.assertIn('data-wnum="wrap-days" min="1" max="365" value="14"', sec)
        self.assertEqual(list(self.lib().SOURCES), re.findall(r'data-wsrc="([a-z]+)"', sec))
        self.assertEqual(6, sec.count('data-won checked'))

    def test_what_was_saved_is_shown_in_its_order(self):
        write(self.root / "System" / "garrick-settings.json", json.dumps({"while-you-wait": {
            "on": False, "threshold": 120, "same-zone": True, "sources": ["inbox", "due"], "wrap-days": 21}}))
        sec = self.section()
        self.assertIn('<input type="checkbox" id="w-on">', sec)
        self.assertIn('<input type="checkbox" id="w-zone" checked>', sec)
        self.assertIn('value="120"', sec)
        self.assertIn('data-wnum="wrap-days" min="1" max="365" value="21"', sec)
        order = re.findall(r'data-wsrc="([a-z]+)"', sec)
        self.assertEqual(["inbox", "due"], order[:2])                      # the chosen first, in their order
        self.assertEqual(set(self.lib().SOURCES), set(order))              # the rest after, switched off
        self.assertEqual(2, sec.count('data-won checked'))

    def test_the_form_reads_back_into_next_ups_keys(self):
        for key in self.lib().DEFAULTS:
            self.assertIn(key, status.WAIT_JS)
        self.assertIn("window.GarrickWait=", status.WAIT_JS)
        self.assertIn("q['while-you-wait']=W.request()", status.JS)        # sent with the rest when Settings closes

    def test_its_own_block(self):
        page = self.page()
        self.assertIn(status.WAIT_CSS.strip()[:60], page)
        self.assertIn("window.GarrickWait=", page)
        self.assertEqual(1, page.count('id="wait-settings"'))

    def test_left_out_without_next_up(self):
        with mock.patch.object(status, "wait_lib", lambda ws: None):
            self.assertNotIn('id="wait-settings"', self.page())

    @unittest.skipUnless(shutil.which("node"), "Node is not installed")
    def test_the_script_parses(self):
        done = subprocess.run(["node", "-e", "new Function(require('fs').readFileSync(0,'utf8'))"], input=status.WAIT_JS,
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(0, done.returncode, done.stderr)


class TestCatchUp(StatusCase):
    """Catch up (#27): beside Settings, a dialog that picks the period and,
    if wanted, the projects and threads of one zone, and hands "catch me up
    ..." to the default assistant; Settings › Catch up keeps the default
    period, briefing.py's; the menu bar's menu and the panel get the periods."""

    def dialog(self, html=None):
        html = html or self.page()
        start = html.index('<dialog id="catchup"')
        return html[start:html.index("</dialog>", start)]

    def menu(self, html):
        return json.loads(htmllib.unescape(re.search(r'id="menu-data">(.*?)</script>', html, re.S).group(1)))

    def test_a_button_beside_settings_opens_it(self):
        html = self.page()
        bar = html[html.index('<div class="bacts">'):html.index('id="open-settings"')]
        self.assertIn('id="open-catchup" aria-label="Catch up"', bar)
        self.assertIn("window.GarrickCatchUp={open:open,phrase:phrase}", status.CATCH_JS)
        self.assertIn("var b=document.getElementById('open-catchup');if(b)b.onclick=open;", status.CATCH_JS)

    def test_the_periods_and_the_default_are_briefings(self):
        lib = status.catch_lib(self.root)
        sec = self.dialog()
        self.assertEqual([k for k, _, _ in lib.PERIODS], re.findall(r'name="cu-period" value="([^"]+)"', sec))
        self.assertIn('value="day" data-words="since yesterday" checked', sec)
        write(self.root / "System" / "garrick-settings.json", json.dumps({"catch-up": {"period": "week"}}))
        sec = self.dialog()
        self.assertIn('data-default="week"', sec)
        self.assertIn('value="week" data-words="this week" checked', sec)

    def test_projects_and_threads_by_the_names_a_request_says(self):
        sec = self.dialog()
        self.assertIn('data-root="%s"' % htmllib.escape(str(self.root)), sec)
        self.assertIn('<input type="checkbox" data-cu="Acme Review"> Acme Review', sec)
        self.assertIn('data-cu="Acme Review, Pricing" data-cup="Acme Review"> Pricing', sec)   # "Project, Thread"
        self.assertIn('<ul class="cuz" data-zone="Work">', sec)

    def test_the_request_goes_to_the_default_assistant_or_is_copied(self):
        js = status.CATCH_JS
        self.assertIn("return'catch me up'+(n.length?' on '+and(n):shown()?' on '+shown():'')+' '+(p?p.dataset.words:'since yesterday')}", js)
        self.assertIn("var m={launch:a,folder:dlg.dataset.root,phrase:p};if(a==='cmux'&&dlg.dataset.dk)m.dk=1;host.postMessage(m)", js)
        self.assertIn("GarrickCopy(p).then(function(){say('Copied “'+p+'”. Paste it to your assistant.')})", js)
        self.assertIn("return a.indexOf(d)>=0?d:a[0]||null", js)                          # as the app's assistant()

    def test_settings_keeps_the_default_period(self):
        html = self.page()
        start = html.index('<section class="setsec apponly" id="catch-settings">')
        sec = html[start:html.index("</section>", start)]
        self.assertIn('<input type="radio" name="cu-default" value="day" checked> <span>The last day</span>', sec)
        self.assertIn("q['catch-up']=C.request();C.saved()", status.JS)                   # sent with the rest when Settings closes
        self.assertIn("System/briefing.local.md", sec)

    def test_the_menu_gets_the_periods(self):
        catch = self.menu(self.page(launchers=("claude",)))["catchup"]
        self.assertEqual({"n": "Catch Up", "f": str(self.root), "d": "day",
                          "p": [list(p) for p in status.catch_lib(self.root).PERIODS]}, catch)
        self.assertNotIn("catchup", self.menu(self.page()))                               # nothing installed to open it in

    def test_left_out_without_briefing(self):
        with mock.patch.object(status, "catch_lib", lambda ws: None):
            html = self.page(launchers=("claude",))
        for gone in ('id="catchup"', 'id="open-catchup"', 'id="catch-settings"'):
            self.assertNotIn(gone, html)
        self.assertNotIn("catchup", self.menu(html))

    def test_the_app_and_obsidian_open_the_same_dialog(self):
        swift = (REPO / "extras" / "status" / "app" / "Garrick.swift").read_text(encoding="utf-8")
        self.assertIn('web.evaluateJavaScript("window.GarrickCatchUp && window.GarrickCatchUp.open()")', swift)
        self.assertIn('item("Catch Up…", #selector(openCatchUp(_:)), "")', swift)            # File › Catch Up…
        self.assertIn("if text.isEmpty, let catchUp = catchItem() { menu.addItem(catchUp) }", swift)
        self.assertIn('return "catch me up" + (zones.isEmpty ? "" : " on " + zones.joined(separator: " and ")) + " " + words', swift)
        self.assertIn("self.launch(c.app, c.folder, phrase: self.catchPhrase(def[2]))", swift)   # the panel's row
        main = (REPO / "extras" / "status" / "obsidian" / "main.js").read_text(encoding="utf-8")
        self.assertIn('this.addCommand({ id: "catch-up", name: "Catch up", callback: () => this.catchUp() });', main)
        self.assertIn('window.GarrickCatchUp&&window.GarrickCatchUp.open()', main)

    @unittest.skipUnless(shutil.which("node"), "Node is not installed")
    def test_the_script_parses(self):
        done = subprocess.run(["node", "-e", "new Function(require('fs').readFileSync(0,'utf8'))"], input=status.CATCH_JS,
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(0, done.returncode, done.stderr)


class TestLaunchers(StatusCase):
    """Open in Claude, Codex or cmux: offered for what is installed, chosen in Settings."""

    def app(self, folder, name, bundle=None, cli=None):
        app = folder / (name + ".app")
        (app / "Contents").mkdir(parents=True)
        if bundle:
            with (app / "Contents" / "Info.plist").open("wb") as f:
                plistlib.dump({"CFBundleIdentifier": bundle}, f)
        if cli:                                  # the launcher inside the bundle, as Codex's own is
            (app / cli).parent.mkdir(parents=True, exist_ok=True)
            (app / cli).write_text("#!/bin/sh\n")
            (app / cli).chmod(0o755)
        return app

    @unittest.skipUnless(sys.platform == "darwin", "the launchers are Mac apps")
    def test_known_by_bundle_id(self):
        apps = Path(self._tmp.name) / "Applications"
        self.app(apps, "ChatGPT", "com.openai.chat")                     # ChatGPT is not Codex
        self.app(apps, "Claude", "com.anthropic.claudefordesktop")
        self.app(apps, "cmux")                                           # no Info.plist: taken at its name
        self.assertEqual(("finder", "cmux", "claude"), status.launchers_installed([apps]))   # Finder: every Mac has it
        self.app(apps, "Codex", "com.openai.codex", cli=status.CODEX_CLI[0])
        self.assertEqual(("finder", "cmux", "codex", "claude"), status.launchers_installed([apps]))

    @unittest.skipUnless(sys.platform == "darwin", "the launchers are Mac apps")
    def test_a_launcher_that_cannot_work_is_not_offered(self):
        # Codex opens a folder through its own launcher inside the bundle. Without
        # one it was offered, clicked, and only then refused; now it is never offered.
        apps = Path(self._tmp.name) / "Applications"
        self.app(apps, "Codex", "com.openai.codex")                      # installed, no launcher in it
        self.assertEqual(("finder",), status.launchers_installed([apps]))
        self.assertEqual({"finder": None, "cmux": status.NOT_INSTALLED, "codex": status.NO_CODEX_CLI,
                          "claude": status.NOT_INSTALLED}, status.launcher_state([apps]))
        for rel in status.CODEX_CLI:                                     # any of the three it may carry will do
            shutil.rmtree(apps)
            self.app(apps, "Codex", "com.openai.codex", cli=rel)
            self.assertIsNone(status.launcher_state([apps])["codex"], rel)

    def test_a_greyed_row_says_why_it_cannot_work(self):
        # The reason sits on the row, before any click rather than after it.
        dialog = status.launcher_choices(("finder", "claude"), why={"codex": status.NO_CODEX_CLI,
                                                                   "cmux": status.NOT_INSTALLED})
        self.assertIn('<input type="checkbox" data-launcher="codex" disabled> <span>Open in Codex<small>%s</small>'
                      % htmllib.escape(status.NO_CODEX_CLI, quote=False), dialog)
        self.assertIn('<input type="checkbox" data-launcher="cmux" disabled> <span>Open in cmux<small>%s</small>'
                      % status.NOT_INSTALLED, dialog)
        self.assertIn('data-launcher="claude"> <span>Open in Claude<small>Installed</small>', dialog)
        self.assertIn('data-launcher="finder"> <span>Reveal in Finder<small>Installed</small>', dialog)

    def test_the_page_names_what_is_installed(self):
        html = self.page(launchers=("claude", "cmux"))
        self.assertIn('data-launchers="claude,cmux"', html)
        self.assertIn('"f":', htmllib.unescape(html))                   # cards carry their folder
        dialog = html[html.index('<dialog id="settings"'):html.index("</dialog>", html.index('<dialog id="settings"'))]
        self.assertIn('data-launcher="codex" disabled', dialog)          # not installed: shown, greyed
        self.assertNotIn('data-launcher="claude" disabled', dialog)
        self.assertNotIn('"f":', htmllib.unescape(self.page()))          # nothing to open it in, no folder

    def test_only_the_app_opens_anything(self):
        self.assertIn("if(o.f&&host)chosen().forEach", status.PANEL_JS)
        self.assertIn("local('garrick-launchers')", status.PANEL_JS)   # in a browser the choice stays in this viewer
        self.assertIn("var m={launch:", status.JS)
        self.assertIn("if(m.launch==='cmux'){m.cmux=m.folder;m.copy=m.phrase}", status.JS)   # an older app still opens cmux

    def test_a_checkbox_and_a_default_for_each_way_to_open(self):
        dialog = self.page(launchers=("finder", "claude"))
        dialog = dialog[dialog.index('<dialog id="settings"'):dialog.index("</dialog>", dialog.index('<dialog id="settings"'))]
        self.assertEqual(["note", "preview", "finder", "cmux", "codex", "claude"], re.findall(r'data-launcher="([a-z]+)"', dialog))
        # Explore's Preview (#219) is a box beside them, on by default, and never what a click does
        self.assertEqual(["note", "finder", "cmux", "codex", "claude"], re.findall(r'name="garrick-default" value="([a-z]+)"', dialog))
        self.assertIn('<div class="launcher-row apponly"><label class="launcher-choice"><input type="checkbox" data-launcher="preview"> '
                      '<span>Preview<small>', dialog)                                # a browser, which never offers it, leaves it out
        self.assertIn("KEYS=['note','preview','finder','cmux','codex','claude']", status.PANEL_JS)
        self.assertEqual(("note", "preview", "finder", "cmux", "codex", "claude"), status.LAUNCH_KEYS)
        self.assertIn('value="cmux" disabled', dialog)                            # not installed: no default either
        self.assertIn('id="close-settings"', dialog[:dialog.index("<h2")])          # the close box, top right
        self.assertNotIn(">Done<", dialog)
        self.assertIn("e.target.closest('.thread .t>a,.sres .t>a')", status.PANEL_JS)   # a click on a thread, or a match for one, follows the default

    def test_settings_open_from_the_cog(self):
        html = self.page()
        brand = html[html.index('<header class="bar">'):html.index("</header>")]
        self.assertIn('id="open-settings"', brand)
        self.assertIn('aria-label="Settings"', brand)


class TestReleaseNotes(StatusCase):
    CHANGES = ("# Changelog\n\n## [Unreleased]\n\n### Added\n\n- Something on main, with `code`.\n\n"
               "## [0.4.0] - 2026-10-05\n\nA summary line.\n\n### Added\n\n- **Settings** with a cog\n"
               "  that wraps onto a second line.\n- A [link](https://example.com) and <script>x</script>.\n\n"
               "## [0.3.1] - 2026-10-04\n\n- Older.\n\n[0.4.0]: https://github.com/iamvenuti/garrick/compare/v0.3.1...v0.4.0\n")

    def test_the_newest_release_only_for_a_download(self):
        notes = status.release_notes(self.CHANGES)
        self.assertIn("What&#x27;s new in 0.4.0, 2026-10-05", notes)
        self.assertNotIn("Older", notes)
        self.assertNotIn("Something on main", notes)
        self.assertIn("<b>Settings</b> with a cog that wraps onto a second line.", notes)

    def test_main_shows_what_is_coming(self):
        notes = status.release_notes(self.CHANGES, edge=True)
        self.assertLess(notes.index("Coming next, on main"), notes.index("What&#x27;s new in 0.4.0"))
        self.assertIn("<code>code</code>", notes)

    def test_nothing_from_the_changelog_runs_or_links_out(self):
        notes = status.release_notes(self.CHANGES)
        self.assertNotIn("<script>", notes)
        self.assertNotIn("example.com", notes)
        self.assertNotIn("compare/", notes)                              # link references stay out
        self.assertIn("A link and &lt;script&gt;", notes)

    def test_the_page_reads_the_installed_changelog(self):
        write(self.root / "System" / "garrick-changelog.md", self.CHANGES)
        write(self.root / "System" / "garrick-version.json", json.dumps({"commit": "abc1234", "from": "download"}))
        status._LIBS.clear()
        html = self.page()
        self.assertIn("What&#x27;s new in 0.4.0", html)
        self.assertNotIn("Coming next", html)
        write(self.root / "System" / "garrick-version.json", json.dumps({"commit": "abc1234", "from": "clone"}))
        self.assertIn("Coming next, on main", self.page())


class TestPreviewFeatures(StatusCase):
    """The Todo list, the buttons that act and the menu bar, previews once and on with no flag now;
    the features still in preview stay off unless the workspace switches them on."""

    def todo(self):
        write(self.root / "Zones" / "Work" / "Todo.md",
              "# Work: open actions\n\n## Inbox\n\n- [ ] <action>\n- [ ] [[Pricing]]: Send the revised terms 📅 2000-01-03\n"
              "- [ ] Book the room · [src](https://example.com/mail) 📅 2999-01-01\n\n## Waiting on\n\n"
              "- [ ] [[Market Sizing]]: Numbers from Birch #waiting ⏳ 2999-02-01\n\n## Done\n\n- [x] Old one ✅ 2000-01-01\n")
        write(self.root / "Zones" / "Work" / "Acme Review" / "Threads" / "Pricing" / "Notes.md", "- [ ] Check the clause\n")

    def test_the_previews_left(self):
        html = self.page()
        self.assertEqual(["Effort", "Ask"], re.findall(r'<div class="flagrow"><b>([^<]+)</b><span class="chip">off</span>', html))
        self.assertIn('<code>{"effort": true}</code>', html)
        for broken in ("{not json", json.dumps(["effort"]), json.dumps({"effort": "yes"})):
            write(self.root / "System" / "garrick-flags.json", broken)
            self.assertFalse(status.preview_flags(self.root)["effort"])
        write(self.root / "System" / "garrick-flags.json", json.dumps({"effort": True}))
        self.assertRegex(self.page(), r'Effort</b><span class="chip on">on</span>')

    def test_a_released_flag_left_behind_changes_nothing(self):
        self.todo()
        write(self.root / "System" / "garrick-flags.json", json.dumps({"todo-list": False, "page-actions": False, "menu-bar": False}))
        html = self.page()
        for gone in ("Todo list</b>", "Actions</b>", "Menu bar</b>"):
            self.assertNotIn(gone, html)
        self.assertIn('id="todolist"', html)
        self.assertIn('<button class="tick" type="button"', html)
        self.assertIsNotNone(self.menu(html))

    def test_the_todo_list(self):
        self.todo()
        html = self.page()
        self.assertIn('id="todolist"', html)
        self.assertIn('href="#todolist"', html)                                   # in the sidebar too
        card = html[html.index('id="todolist"'):]
        self.assertNotIn("&lt;action&gt;", card)                                  # the template's placeholder
        self.assertNotIn("Old one", card)                                         # ticked
        order = [card.index(t) for t in ("Book the room", "Send the revised terms", "Numbers from Birch", "Check the clause")]
        self.assertEqual(sorted(order), order)                                    # by section, then A-Z by thread
        self.assertIn('<button class="tdate overdue" type="button" title="Set the date">Due Mon 3 Jan</button>', card)
        self.assertIn("Chase", card)
        for group in ("Inbox", "Waiting on", "In thread notes"):
            self.assertIn('<span class="tname">%s</span>' % group, card)
        self.assertIn("Check the clause", card)                                  # a thread note's own action
        self.assertIn("in the thread note", card)
        self.assertNotIn("example.com", card)                                     # a source link is not followed

    def test_the_todo_list_is_a_tab(self):
        self.todo()
        html = self.page()
        self.assertIn('<button type="button" role="tab" data-tab="todo">Todo<span class="n">', html)
        over, todo = html.index('id="tab-overview"'), html.index('id="tab-todo" hidden')
        self.assertLess(over, html.index('id="graph"'))
        self.assertLess(html.index('id="graph"'), todo)
        self.assertLess(todo, html.index('id="todolist"'))                    # the list sits in its own tab
        self.assertIn("StatusTab(sec.id.slice(4))", status.JS)                  # a link opens the tab its target is in

    def test_add_a_line(self):
        self.todo()
        html = self.page()
        self.assertIn('<button type="button" class="act primary tadd-open" data-zone="Work"', html)
        self.assertIn('<button type="button" class="act primary tadd-open" data-zone="Personal"', html)   # an empty list takes a line too
        dialog = html[html.index('<dialog id="tadd"'):html.index("</dialog>", html.index('<dialog id="tadd"'))]
        work = dialog[dialog.index('<div class="ttree" data-zone="Work"'):]
        self.assertIn('value="-" checked><span>No thread</span>', work)
        self.assertIn('value="Acme Review"', work)                               # a project can be picked
        self.assertIn('value="Acme Review/Pricing"', work)                       # and a thread under it
        self.assertIn('<input type="date" id="tadd-date"', dialog)
        self.assertIn("verb:'todo-add'", status.JS)                               # the app runs page_action.py with it
        self.assertIn("window.TaddOpen=function(z)", status.TADD_JS)
        self.assertIn(".nohost .tadd-open{display:none}", status.CSS)             # a browser cannot act

    def test_actions(self):
        self.todo()
        html = self.page()
        rows = re.findall(r'<div class="trow[^"]*" data-z="([^"]*)" data-f="([^"]*)" data-k="([^"]*)"', html)
        self.assertTrue(rows)
        self.assertTrue(all(z == "Work" and re.fullmatch(r"[0-9a-f]{16}", k) for z, _, k in rows))     # what a button sends back
        self.assertEqual(len(rows), html.count('<button class="tick" type="button"'))
        self.assertEqual(len(rows), html.count('<button class="tdate'))
        self.assertIn("var q={verb:verb,zone:r.dataset.z,file:r.dataset.f,key:r.dataset.k}", status.TODO_JS)
        for verb in ("'todo-done'", "'todo-undo'", "'todo-date'"):
            self.assertIn(verb, status.TODO_JS)
        card = cards(html)[("Acme Review", "Pricing")]
        self.assertEqual(["Work", "Acme Review/Threads/Pricing/Pricing.md"], card["pa"])     # what Park acts on
        self.assertIn("if(host&&(o.h?o.pp:o.pa))return park(o)", status.PANEL_JS)          # only the app parks
        self.assertIn("'<div class=\"phead\"><h4>'+esc(o.N||o.n)+'</h4>'+flip(o)+'</div>", status.PANEL_JS)   # beside the name
        self.assertIn("if(!host)document.body.classList.add('nohost')", status.JS)          # a browser hides them
        self.assertIn(".nohost .tacts{display:none}", status.CSS)

    def menu(self, html):
        m = re.search(r'<script type="application/json" id="menu-data">(.*?)</script>', html, re.S)
        return json.loads(m.group(1)) if m else None

    def test_the_menu_bar(self):
        html = self.page()
        self.assertIsNotNone(self.menu(html))
        self.assertIn("host.postMessage({menu:data&&", status.MENU_JS)       # a page with none takes the icon away
        self.assertIn('<section class="setsec apponly" id="menu-settings" hidden>', html)   # until the app answers
        self.assertIn("if(!host||!box)return;box.hidden=false", status.MENU_SETTINGS_JS)
        for control in ('id="menu-show"', 'id="menu-style"', 'id="menu-login"', 'id="menu-hotkey"'):   # the four settings
            self.assertIn(control, html)
        for edge in ("left", "right", "top"):
            self.assertIn('<option value="%s">' % edge, html)
        self.assertIn("'style' in a?'':'none'", status.MENU_SETTINGS_JS)    # an app without the panel never shows the choice
        self.assertIn(".nohost .apponly{display:none}", status.SETTINGS_CSS)   # a browser has no menu bar to offer

    @mock.patch.object(status, "desk_ready", return_value=False)      # the desk's keys depend on cmux; tested with a fake one in test_status_more
    def test_what_the_menu_lists(self, _desk):
        work = self.root / "Zones" / "Work"
        write(work / "Acme Review" / "Threads" / "Renewal" / "Renewal.md", thread_note("Acme Review", "Renewal", "acme", status="parked"))
        write(work / "Solo" / "Solo.md", project_hub("Work", "Solo", "acme"))
        menu = self.menu(self.page())
        self.assertFalse(menu["trouble"])
        zones = {z["z"]: z for z in menu["zones"]}
        self.assertEqual({"Work", "Personal"}, set(zones))
        self.assertEqual([], zones["Personal"]["p"])
        projects = {p["n"]: p for p in zones["Work"]["p"]}
        self.assertEqual(["Acme Review", "Birch Entry", "Solo"], list(projects))           # projects first, by name
        acme = projects["Acme Review"]
        self.assertEqual(["Pricing"], [t["n"] for t in acme["t"]])                          # parked threads stay out
        self.assertEqual({"n", "w", "u", "t"}, set(acme))                             # names and links, no figures
        self.assertIn("Acme%20Review", acme["u"])                                           # the project's own hub
        self.assertEqual("Acme Review", acme["w"])
        self.assertEqual([], projects["Solo"]["t"])                                         # a project that is its own thread
        self.assertEqual("Solo", projects["Solo"]["w"])
        pricing = acme["t"][0]
        self.assertEqual({"n", "w", "u", "oc"}, set(pricing))
        self.assertEqual("Pricing", pricing["w"])
        # the note Open in Claude continues (#180): a thread's, or the hub of a project that is its own thread
        self.assertEqual(["Work", "Acme Review/Threads/Pricing/Pricing.md"], pricing["oc"])
        self.assertEqual(["Work", "Solo/Solo.md"], projects["Solo"]["oc"])
        self.assertNotIn("cli", menu)                                                       # no CLI said: the deep link
        self.assertEqual(1, self.menu(self.page(cli=True))["cli"])
        work_zone = [z for z in self.menu(self.page(launchers=("claude",)))["zones"] if z["z"] == "Work"][0]
        self.assertEqual(str(work / "Acme Review" / "Threads" / "Pricing"), work_zone["p"][0]["t"][0]["f"])   # a folder where an app can open it
        self.assertEqual(str(work / "Acme Review"), work_zone["p"][0]["f"])

    def test_the_menu_offers_the_inbox(self):
        write(self.root / "Zones" / "Work" / "Inbox" / "Quote.eml", "Subject: quote\n\nhello\n")
        write(self.root / "Wikis" / "Meetings" / "raw" / "inbox" / "call.txt", "A: hello\n")
        intake = self.menu(self.page(launchers=("claude",)))["intake"]
        self.assertEqual({"n": "Process the Inbox", "w": "process the inbox", "f": str(self.root), "c": 2,
                          "b": [["Work", 1], ["Meetings", 1]]}, intake)   # the page's own count, and where they wait
        self.assertNotIn("intake", self.menu(self.page()))                    # nothing installed to open it in

    def test_the_menus_script_stands_alone(self):
        # In a script element of its own, an error anywhere else on the page
        # cannot keep the app from hearing what its menu lists.
        html = self.page()
        self.assertIn("<script>%s</script>" % status.MENU_JS, html)
        self.assertEqual(1, html.count(status.MENU_JS))
        if not shutil.which("node"):
            self.skipTest("Node is not installed")
        js = """const vm=require("vm");const [code,data]=JSON.parse(process.argv[1]);const posted=[];
const ctx={JSON,String,setTimeout:()=>0,localStorage:{getItem:()=>null},document:{body:{dataset:{launchers:"claude,cmux"}},
addEventListener:()=>{},getElementById:(id)=>id==="menu-data"?{textContent:data}:null}};
ctx.window={webkit:{messageHandlers:{garrick:{postMessage:(m)=>posted.push(m)}}}};vm.createContext(ctx);vm.runInContext(code,ctx);
process.stdout.write(JSON.stringify(posted));"""
        data = re.search(r'id="menu-data">(.*?)</script>', html, re.S).group(1)
        done = subprocess.run(["node", "-e", js, json.dumps([status.MENU_JS, data])], capture_output=True, text=True, timeout=30)
        self.assertEqual(0, done.returncode, done.stderr)
        menu = json.loads(done.stdout)[0]["menu"]                 # no GarrickPrefs: PANEL_JS's script failed, and still it says
        self.assertEqual(("note", True, ["claude", "cmux"]), (menu["def"], menu["note"], menu["launchers"]))
        self.assertEqual({"Work", "Personal"}, {z["z"] for z in menu["data"]["zones"]})

    def test_the_menu_follows_the_graph_and_settings(self):
        self.assertIn("g('garrick-graph-place')", status.MENU_JS)
        self.assertIn("def:P?P.def():'note'", status.MENU_JS)                                 # what Settings chose, shared or this window's
        self.assertIn("var P=window.GarrickPrefs,on=P?P.launchers():{}", status.MENU_JS)
        self.assertIn("document.addEventListener('change',function(){setTimeout(sync,0)},true)", status.MENU_JS)
        self.assertIn("note:on.note!==false", status.MENU_JS)                                  # the note's link, unless switched off
        self.assertIn("e.stopPropagation();host.postMessage({app:o})", status.MENU_SETTINGS_JS)     # the app's settings do not rebuild the page

    def test_a_project_without_threads_is_its_own_thread(self):
        write(self.root / "Zones" / "Work" / "Solo" / "Solo.md",
              "---\ntitle: Solo\ntype: project\nparty: acme\nstatus: dormant\nupdated: 2026-03-02\n---\n\n# Solo\n")
        write(self.root / "Zones" / "Work" / "Gone" / "Gone.md", "---\ntype: project\nstatus: closed\n---\n")
        T = status.threads(self.root)
        solo = [r for r in T["Work"]["parked"] if r["project"] == "Solo"]
        self.assertEqual(1, len(solo))                                   # dormant reads as parked
        self.assertEqual(("Solo", "Solo/Solo.md"), (solo[0]["thread"], solo[0]["rel"]))
        self.assertFalse([r for r in T["Work"]["rows"] + T["Work"]["parked"] if r["project"] == "Gone"])
        self.assertEqual(["Acme Review", "Birch Entry"], sorted({r["project"] for r in T["Work"]["rows"]}))   # projects with threads list those

    def test_garrick_and_the_workspace_read_lines_alike(self):
        tl = status.todo_lines()
        p = tl.parse("- [ ] [[Acme/Pricing|Pricing]]: Send it #waiting 🔺 ⏳ 2026-10-09")
        self.assertEqual(("Pricing", "Send it", "2026-10-09", True), (p["thread"], p["text"], p["scheduled"], p["waiting"]))


class TestPanels(StatusCase):
    def test_inbox_waiting(self):
        write(self.root / "Zones" / "Work" / "Inbox" / "Quote.eml", "Subject: quote\n\nhello\n")
        html = self.page()
        self.assertIn("1 waiting", html)
        self.assertIn("1 item waiting in the inboxes", html)

    def inboxes(self, html):
        start = html.index('id="inboxes"')
        return html[start:html.index("</details>", start)]

    def test_process_the_inbox_is_a_button_while_anything_waits(self):
        self.assertNotIn("data-request", self.inboxes(self.page()))                 # every inbox empty: no button
        write(self.root / "Zones" / "Work" / "Inbox" / "Quote.eml", "Subject: quote\n\nhello\n")
        card = self.inboxes(self.page())
        self.assertIn('<h2>Inboxes</h2><span class="meta"></span>', card)          # no "say …" in the caption (#234)
        self.assertIn('<div class="gacts"><button class="act" type="button" data-request="process the inbox" data-folder="%s"' % self.root, card)
        self.assertIn(">Process the Inbox</button>", card)
        self.assertNotIn('say "process the inbox"', self.page())

    def test_a_request_button_opens_the_menus_assistant_or_copies(self):
        js = status.JS
        self.assertIn("var q=t.closest('button[data-request]')", js)
        self.assertIn("host.postMessage({launch:a,folder:q.dataset.folder,phrase:p})", js)   # the launch the menu's row makes
        self.assertIn("put(p).then(", js)                                                    # a browser, or no assistant: copied
        self.assertIn("return a.indexOf(d)>=0?d:a[0]||null", js)                             # the default, else the first switched on

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

    def test_the_page_runs_the_quick_check(self):
        tools = self.root / "System" / "tools"
        shutil.copytree(REPO / "template" / "System" / "tools", tools, dirs_exist_ok=True)
        seen = []
        real = status.subprocess.run
        def spy(cmd, *a, **k):
            if any(str(c).endswith("check.py") for c in cmd):
                seen.append(list(cmd))
            return real(cmd, *a, **k)
        with mock.patch.object(status.subprocess, "run", spy):
            self.page()
        self.assertTrue(seen and "--quick" in seen[0])
        (tools / "check.py").write_text("print('{}')\n")                 # an older check.py, without --quick
        seen.clear()
        with mock.patch.object(status.subprocess, "run", spy):
            self.page()
        self.assertTrue(seen and "--quick" not in seen[0])


class TestJobs(StatusCase):
    def heartbeat(self, code=0):
        now = self.now.timestamp()
        (self.jobs / "brief.heartbeat.json").write_text(json.dumps(
            {"job": "brief", "finished": stamp(now - 60), "exit": code, "seconds": 30, "items": 2, "idle_days": 0}))

    def test_no_jobs_no_panel(self):
        self.assertNotIn('id="jobs"', self.page())

    def test_day_that_ended_failed_is_red(self):
        self.heartbeat(0)
        t = (self.now - dt.timedelta(days=2)).replace(hour=12, minute=0, second=0).timestamp()   # one day, whatever the hour
        (self.jobs / "brief.log").write_text(
            "===== %s  brief  exit 0  (30s) =====\n\n===== %s  brief  exit 4  (5s) =====\n\n" % (stamp(t), stamp(t + 600)))
        html = self.page()
        self.assertIn('id="jobs"', html)
        self.assertIn('class="critical" tabindex="0"', html)

    def test_the_strip_has_no_legend(self):
        self.heartbeat(0)
        html = self.page()
        card = html[html.index('id="jobs"'):html.index("</details>", html.index('id="jobs"'))]
        self.assertNotIn('class="legend"', card)                         # each cell's tooltip says its day (#232)
        self.assertNotIn("One cell per day", card)
        self.assertIn("· no run", card)

    def test_day_that_recovered_is_amber(self):
        self.heartbeat(0)
        t = (self.now - dt.timedelta(days=2)).replace(hour=12, minute=0, second=0).timestamp()   # one day, whatever the hour
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
        self.assertIn('<h2>Scheduled jobs</h2><span class="meta">1 failed</span>', html)    # a folded card still says it (#231)

    def test_the_caption_is_empty_when_every_job_is_fine(self):
        self.heartbeat(0)
        html = self.page()
        self.assertIn('<h2>Scheduled jobs</h2><span class="meta"></span>', html)
        self.assertNotIn("heartbeats and logs in", html)

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

    def test_a_job_not_run_yet_has_a_neutral_row(self):
        self.heartbeat(0)
        with self.plists(brief={"StartCalendarInterval": {"Hour": 7}}, sweep={"StartCalendarInterval": {"Hour": 6, "Minute": 30}}):
            html = self.page()
            J = status.jobs(self.jobs, self.now)
        sweep = next(j for j in J if j["name"] == "sweep")
        self.assertEqual(("none", "not run yet", "daily 06:30", None), (sweep["state"], sweep["status"], sweep["schedule"], sweep["when"]))
        self.assertEqual(["brief", "sweep"], [j["name"] for j in J])                     # beside the jobs that ran, by name
        row = next(r for r in html[html.index('id="jobs"'):].split('<div class="row" ')[1:] if ">sweep</a>" in r)
        self.assertTrue(row.startswith('data-ok="1">' + status.ICON["none"]))         # hollow, and not something that needs attention
        self.assertIn("<small>daily 06:30</small>", row)
        self.assertIn("not run yet", row)
        self.assertNotIn("sweep: not run yet", html)                                      # no line in Needs attention
        self.assertNotIn('title="something failed"', html)                               # and no red dot on the Status tab

    def test_a_job_not_run_yet_shows_without_a_jobs_folder(self):
        with self.plists(sweep={"StartInterval": 900}):
            J = status.jobs(self.jobs.parent / "no-such-folder", self.now)
        self.assertEqual([("sweep", "not run yet", "every 15 min")], [(j["name"], j["status"], j["schedule"]) for j in J])

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
        self.assertIn('<div class="m" data-tip="Caps from the launchd plist of brief.">', html)   # in the meters' tooltip (#232)
        self.assertNotIn('<p class="hint">Caps from', html)

    def test_without_a_plist_the_caps_say_where_they_come_from(self):
        self.ledger({"job": "brief", "cost_usd": 0.5, "exit": 0})
        with self.plists(), mock.patch.dict(os.environ, {"GARRICK_CAP_CALLS_DAY": "0"}):
            html = self.page()
        self.assertIn("1<small>no cap</small>", html)
        self.assertIn(">1, no cap<", html)
        self.assertIn('data-tip="Caps from the GARRICK_CAP_* settings the page was built with', html)

    def test_odd_plists_are_passed_over(self):
        folder = self.jobs.parent / "LaunchAgents"
        folder.mkdir()
        (folder / "list.plist").write_bytes(plistlib.dumps(["not", "a", "dict"]))
        (folder / "args.plist").write_bytes(plistlib.dumps({"ProgramArguments": "job.py brief"}))
        (folder / "broken.plist").write_text("<plist>")
        with mock.patch.object(status, "launch_agents", lambda: folder):
            self.assertEqual({}, status.launchd_jobs())



class TestNameAndMark(StatusCase):
    def test_called_garrick(self):
        html = self.page()                                  # the page is called as the app is
        self.assertIn("<title>Garrick</title>", html)
        self.assertIn("<h1>Garrick</h1>", html)

    def test_mark_beside_the_heading_and_in_the_tab(self):
        html = self.page()
        brand = html[html.index('<div class="brand">'):html.index("<h1>")]
        self.assertIn('class="mark" aria-hidden="true"', brand)
        self.assertEqual(2, brand.count("<path"))           # the cabinet: the walls in ink, the open compartment in blue
        self.assertIn('class="mi" fill="#1E2833"', brand)
        self.assertIn('class="mb" fill="#3D73E0"', brand)
        icon = re.search(r'<link rel="icon" type="image/svg\+xml" href="data:image/svg\+xml,([^"]+)">', html)
        svg = urllib.parse.unquote(icon.group(1))
        self.assertTrue(svg.startswith('<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">'))
        self.assertEqual(2, svg.count("<path"))
        self.assertIn('d="M24 4V60H6', svg)                 # the small cut, on the 16-pixel grid
        self.assertIn("@media (prefers-color-scheme:dark){.mi{fill:#F5F0E6}.mb{fill:#8EB1F5}}", svg)

    def test_mark_follows_the_theme(self):
        # Navy and BRAND on light; cream and the lighter blue on dark, chosen or automatic.
        self.assertIn(".mark .mi{fill:var(--mark-ink)}.mark .mb{fill:var(--mark-blue)}", status.CSS)
        light = re.search(r":root\{[^}]*--mark-ink:(#[0-9a-f]{6});--mark-blue:(#[0-9a-f]{6})\}", status.CSS).groups()
        self.assertEqual((status.MARK_INK.lower(), status.BRAND.lower()), light)
        dark = re.findall(r"color-scheme:dark;[^}]*--mark-ink:(#[0-9a-f]{6});--mark-blue:(#[0-9a-f]{6})\}", status.CSS)
        self.assertEqual([(status.MARK_INK_ON_DARK.lower(), status.BRAND_ON_DARK.lower())] * 2, dark)

    def test_app_icon_is_the_mark_on_a_navy_tile(self):
        icon = status.app_icon()
        self.assertTrue(icon.startswith('<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024"'))
        self.assertIn('<rect x="100" y="100" width="824" height="824" rx="185.4" fill="%s"/>' % status.MARK_INK, icon)
        self.assertIn('fill="%s"' % status.MARK_INK_ON_DARK, icon)
        self.assertIn('fill="%s"' % status.BRAND_ON_DARK, icon)
        self.assertNotIn("<style>", icon)                   # sips draws it without a stylesheet
        self.assertIn("mod.app_icon()", (Path(status.__file__).parent / "app" / "make-app.sh").read_text())

    def test_display_headings_in_baskerville(self):
        # Garrick's typeface, from fonts already on the machine: nothing is fetched.
        stack = '"Baskervville","Libre Baskerville",Baskerville,"Baskerville Old Face",Georgia,serif'
        self.assertIn("--display:%s;" % stack, status.CSS)
        for rule in (r"\.bar h1\{[^}]*", r"\.head h2\{[^}]*", r"\.hero \.fig\{[^}]*"):
            self.assertIn("var(--display", re.search(rule, status.CSS + status.BAR_CSS).group(0))
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


class TestCaptions(StatusCase):
    """A card's caption says a state worth acting on, or nothing (#231): never
    the file, flag or colour behind the card."""

    def metas(self, html):
        return dict(re.findall(r'<h2>([^<]*)</h2><span class="meta">([^<]*)</span>', html))

    def test_a_healthy_page_has_empty_captions(self):
        metas = self.metas(self.page())
        for title in ("Open actions", "Checks", "Repositories", "Wikis"):
            self.assertEqual("", metas.get(title, ""), title)
        page = self.page()
        for said in ("unticked items", "check.py --quick", "a ring means", "newest entry in each log",
                     "in the zone and meeting inboxes", "run just now"):
            self.assertNotIn(said, page)

    def test_the_checks_caption_counts_the_findings(self):
        tools = self.root / "System" / "tools"
        tools.mkdir(parents=True, exist_ok=True)
        findings = [{"check": "threads", "severity": "error", "path": "a.md", "message": "x"},
                    {"check": "threads", "severity": "warning", "path": "b.md", "message": "y"},
                    {"check": "threads", "severity": "warning", "path": "c.md", "message": "z"}]
        (tools / "check.py").write_text("import json\nprint(json.dumps(%r))\n" % {"errors": 1, "warnings": 2, "findings": findings})
        self.assertEqual("1 error · 2 warnings", self.metas(self.page())["Checks"])


class TestChangedFiles(StatusCase):
    """The Repositories card counts changed files and says what they are. It
    never calls them commits, and it offers no way to commit them."""

    def test_reads_porcelain_one_entry_per_file(self):
        porcelain = "\0".join(["M  staged.md", " M edited.md", "MM both.md", "R  new name.md", "old name.md",
                               "?? notes/draft.md", "UU merge.md", " D gone.md", ""])
        self.assertEqual([("staged.md", ("staged",)), ("edited.md", ("unstaged",)), ("both.md", ("staged", "unstaged")),
                          ("new name.md", ("staged",)), ("notes/draft.md", ("untracked",)), ("merge.md", ("conflicted",)),
                          ("gone.md", ("unstaged",))], status.changed_files(porcelain))
        self.assertEqual([], status.changed_files(""))

    @unittest.skipUnless(shutil.which("git"), "needs git")
    def test_counts_match_git_status(self):
        from fixtures import commit_all, git, git_init
        work = self.root / "Zones" / "Work"
        git_init(work)
        commit_all(work)
        hub = work / "Acme Review" / "Acme Review.md"
        hub.write_text(hub.read_text() + "\nEdited.\n")                     # not staged
        write(work / "Acme Review" / "Sources" / "a.csv", "x\n")             # untracked, in a new folder
        write(work / "Acme Review" / "Sources" / "b.csv", "y\n")             # untracked, same folder
        git(work, "mv", "Acme Review/Threads/Pricing/Pricing.md", "Acme Review/Threads/Pricing/Pricing notes.md")
        R = {r["name"]: r for r in status.repos(self.root)}
        self.assertEqual(4, R["Work"]["dirty"])                               # files, the new folder's two included
        self.assertEqual("1 staged, 1 not staged, 2 untracked", status.say_kinds(R["Work"]["changes"]))
        html = self.page()
        start = html.index('id="repos"')
        block = html[start:html.index('<script', start)]     # the last card, before the page's script
        self.assertIn("<small>4 changed files</small>", block)
        self.assertNotIn("uncommitted", block)
        self.assertIn("Work: 4 changed files", block)
        self.assertIn("<code>Acme Review/Sources/a.csv</code>", block)
        self.assertIn("<code>Acme Review/Threads/Pricing/Pricing notes.md</code>", block)
        self.assertNotIn("In Zones/Work.", block)
        self.assertIn('<h2>Repositories</h2><span class="meta">1 with changes</span>', html)
        self.assertNotIn("data-act", block)                                   # nothing here commits
        self.assertNotRegex(block.lower(), r">\s*commit")

    @unittest.skipUnless(shutil.which("git"), "needs git")
    def test_a_git_status_that_fails_is_never_all_committed(self):
        from fixtures import commit_all, git_init
        work = self.root / "Zones" / "Work"
        git_init(work)
        commit_all(work)
        run = subprocess.run

        def slow(cmd, *args, **kw):
            if "status" in cmd:
                raise subprocess.TimeoutExpired(cmd, 30)
            return run(cmd, *args, **kw)
        with mock.patch.object(status.subprocess, "run", slow):
            R = {r["name"]: r for r in status.repos(self.root)}
            html = self.page()
        self.assertTrue(R["Work"]["unread"])
        start = html.index('id="repos"')
        block = html[start:html.index('<script', start)]
        self.assertIn("Work<small>could not be read</small>", block)
        self.assertNotIn("all committed", block)

    def test_one_file_is_singular_and_a_clean_repository_says_so(self):
        self.assertEqual("1 changed file", status.say_files(1))
        self.assertEqual("12 changed files", status.say_files(12))
        self.assertEqual("", status.say_kinds([]))

    def test_the_root_repository_is_the_workspace_folder(self):
        out = status.repo_changes(self.root, {"name": "Workspace", "folder": self.root, "dirty": 1,
                                              "changes": [("AGENTS.md", ("unstaged",))]})
        self.assertIn("<code>AGENTS.md</code>", out)
        self.assertIn('data-copy="%s"' % self.root, out)
        self.assertNotIn("In the workspace folder", out)                 # the summary above already counts them (#232)
        self.assertNotIn("Nothing here commits", out)                    # the docs say it once

    def test_a_long_list_is_cut_but_the_count_is_not(self):
        changes = [("f%02d.md" % i, ("untracked",)) for i in range(status.REPO_LIST_CAP + 5)]
        out = status.repo_changes(self.root, {"name": "Work", "folder": self.root / "Zones" / "Work",
                                              "dirty": len(changes), "changes": changes})
        self.assertIn("%d changed files" % len(changes), out)
        self.assertIn("and 5 more", out)
        self.assertEqual(status.REPO_LIST_CAP, out.count("<code>"))


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
        self.assertIn('<a class="act" href="#todolist" data-tz-go="Work" title="Open Work&#39;s list on the Todo tab">Open the list</a>', block)
        url = (self.root / "Zones" / "Work" / "Todo.md").as_uri()
        self.assertIn('<a class="act" href="%s" title="Open Work/Todo.md">Open Todo.md</a>' % url, html)   # on the tab
        vault = self.page(vault="My Work")
        self.assertIn("file=Zones/Work/Todo\" title=\"Open Work/Todo.md\">Open Todo.md</a>", vault)

    def test_no_todo_no_open_actions(self):
        self.assertIn('class="top" style="--tiles:4"', self.page())
        for todo in (self.root / "Zones").glob("*/Todo.md"):
            todo.unlink()
        html = self.page()
        self.assertNotIn('id="todo"', html)
        self.assertNotIn("Open actions", html)                    # no card, no tile, no sidebar line
        self.assertIn('class="top" style="--tiles:3"', html)     # the tiles still fill their row


class TestWhatThisMachineHas(StatusCase):
    """Obsidian and cmux are optional: the page asks at every build and offers
    only what will work."""

    def setUp(self):
        super().setUp()
        self.apps = Path(self._tmp.name).resolve() / "Applications"
        self.apps.mkdir()

    def install(self, name):
        (self.apps / (name + ".app")).mkdir()

    def register(self, *folders):
        config = Path(self._tmp.name).resolve() / "obsidian.json"
        config.write_text(json.dumps({"vaults": {"id%d" % i: {"path": str(f), "ts": 1} for i, f in enumerate(folders)}}))
        return config

    def test_vaults_come_from_obsidians_own_list(self):
        self.install("Obsidian")
        elsewhere = Path(self._tmp.name).resolve() / "Elsewhere"
        elsewhere.mkdir()
        config = self.register(self.root, self.root / "Zones" / "Work", elsewhere)
        found = status.obsidian_vaults(self.root, config=config, apps=[self.apps])
        self.assertEqual([(self.root / "Zones" / "Work", "Work"), (self.root, "Workspace")], found)   # deepest first, none elsewhere

    def test_a_shared_vault_name_is_given_by_id(self):
        self.install("Obsidian")
        other = Path(self._tmp.name).resolve() / "Old" / "Work"
        other.mkdir(parents=True)
        config = self.register(self.root / "Zones" / "Work", other)
        self.assertEqual([(self.root / "Zones" / "Work", "id0")], status.obsidian_vaults(self.root, config=config, apps=[self.apps]))

    @unittest.skipUnless(sys.platform == "darwin", "the app check is macOS's")
    def test_no_obsidian_app_no_vaults(self):
        config = self.register(self.root)
        self.assertEqual([], status.obsidian_vaults(self.root, config=config, apps=[self.apps]))

    def test_unreadable_list_no_vaults(self):
        self.install("Obsidian")
        config = Path(self._tmp.name).resolve() / "obsidian.json"
        config.write_text("{not json")
        self.assertEqual([], status.obsidian_vaults(self.root, config=config, apps=[self.apps]))

    def test_a_note_opens_in_the_closest_vault(self):
        html = self.page(vaults=[(self.root / "Zones" / "Work", "Work"), (self.root, "Workspace")])
        pricing = cards(html)[("Acme Review", "Pricing")]
        self.assertEqual("obsidian://open?vault=Work&file=Acme%20Review/Threads/Pricing/Pricing", pricing["u"])
        self.assertIn("obsidian://open?vault=Workspace&amp;file=Zones/Personal/Todo", html)   # Personal is only in the root vault
        self.assertNotIn((self.root / "Zones").as_uri(), html)

    @unittest.skipUnless(sys.platform == "darwin", "cmux is a macOS app")
    def test_cmux_is_found_by_its_app(self):
        self.assertFalse(status.cmux_installed(apps=[self.apps]))
        self.install("cmux")
        self.assertTrue(status.cmux_installed(apps=[self.apps]))

    def test_folders_only_where_cmux_is(self):
        self.assertNotIn('"f":', htmllib.unescape(self.page()))
        html = self.page(cmux=True)
        pricing = cards(html)[("Acme Review", "Pricing")]
        self.assertEqual(str(self.root / "Zones" / "Work" / "Acme Review" / "Threads" / "Pricing"), pricing["f"])
        nodes = graph_data(html)["nodes"]
        self.assertTrue(all(("f" in n) == bool(n["p"]) for n in nodes))       # every note in a project, nothing outside one
        hub = next(n for n in nodes if n["n"] == "Acme Review")
        self.assertEqual(str(self.root / "Zones" / "Work" / "Acme Review"), hub["f"])

    def test_open_in_cmux_only_inside_the_app(self):
        # A browser has no window.webkit.messageHandlers.garrick, so there the
        # page offers no cmux and every button only copies.
        self.assertIn("if(o.f&&host)chosen().forEach", status.PANEL_JS)
        self.assertIn("window.webkit.messageHandlers.garrick", status.PANEL_JS)
        self.assertIn("if(c&&host){var m={launch:", status.JS)
        self.assertIn("if(host&&rb){rb.removeAttribute('data-copy');rb.title='Rebuild the page now'", status.JS)
        brand = self.page()
        brand = brand[brand.index('<header class="bar">'):brand.index("</header>")]
        self.assertIn('id="rebuild"', brand)                      # an icon beside the cog: rebuilds in the app, copies elsewhere
        self.assertIn('data-copy="', brand)

    @unittest.skipUnless(shutil.which("node"), "Node is not installed")
    def test_copy_open_x_only_where_nothing_opens_it(self):
        # PANEL_JS run in Node, as a browser and as a host with the bridge (the
        # app, or Obsidian's tab), on a card with a folder and one without.
        harness = r"""
        const vm = require("vm");
        const [js, hosted, launchers, card] = JSON.parse(process.argv[1]);
        const store = {};
        const ctx = { JSON, String, Array, localStorage: { getItem: (k) => store[k] || null, setItem: (k, v) => { store[k] = v; } },
                      document: { getElementById: () => null, addEventListener: () => {}, body: { dataset: { launchers } } } };
        ctx.window = hosted ? { webkit: { messageHandlers: { garrick: { postMessage: () => {} } } } } : {};
        vm.createContext(ctx);
        vm.runInContext(js + ";this.out=Panel.acts(" + JSON.stringify(card) + ")", ctx);
        process.stdout.write(ctx.out);
        """
        import subprocess

        def acts(hosted, launchers, card):
            done = subprocess.run(["node", "-e", harness, json.dumps([status.PANEL_JS, hosted, launchers, card])],
                                  capture_output=True, text=True, timeout=30)
            self.assertEqual(0, done.returncode, done.stderr)
            return done.stdout

        card = {"n": "Pricing", "w": "Pricing", "u": "obsidian://open?file=Pricing", "f": "/ws/Zones/Work/Acme Review/Threads/Pricing"}
        self.assertIn("Copy “open Pricing”", acts(False, "finder,cmux", card))         # a browser can only copy
        hosted = acts(True, "finder,cmux", card)
        self.assertIn('data-launch="finder"', hosted)                                   # the app offers its launchers
        self.assertNotIn("Copy “open Pricing”", hosted)                                 # and no phrase to copy beside them
        self.assertIn("Copy “open Pricing”", acts(True, "", card))                      # no app offered: copying is all there is
        self.assertIn("Copy “open Pricing”", acts(True, "finder,cmux", dict(card, f=None)))   # nor a folder to open

    def test_main_asks_the_machine_and_honours_the_switches(self):
        out = Path(self._tmp.name).resolve() / "page.html"
        with mock.patch.object(status, "launchers_installed", return_value=("cmux",)), \
                mock.patch.object(status, "obsidian_vaults", return_value=[(self.root, "Workspace")]), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            status.main(["--workspace", str(self.root), "--out", str(out)])
            found = out.read_text()
            status.main(["--workspace", str(self.root), "--out", str(out), "--no-cmux", "--no-obsidian"])
            kept = out.read_text()
        self.assertIn('"f":', htmllib.unescape(found))
        self.assertIn("obsidian://open?vault=Workspace", found)
        self.assertNotIn('"f":', htmllib.unescape(kept))
        self.assertNotIn("obsidian://", kept)
        self.assertIn("--no-obsidian --no-cmux", htmllib.unescape(kept))           # the rebuild command keeps them


class TestApp(unittest.TestCase):
    APP = REPO / "extras" / "status" / "app"

    def test_the_app_is_built_not_shipped(self):
        self.assertTrue(os.access(self.APP / "make-app.sh", os.X_OK))
        self.assertEqual({"Garrick.swift", "make-app.sh"}, {p.name for p in self.APP.iterdir() if not p.name.startswith(".")})

    def test_the_app_changes_no_file(self):
        swift = (self.APP / "Garrick.swift").read_text()
        # It only looks, but for what it last filled its menu with, in the jobs folder, outside the workspace.
        self.assertEqual({"attributesOfItem", "fileExists", "isExecutableFile", "createDirectory"},
                         set(re.findall(r"FileManager\.default\.(\w+)", swift)))
        self.assertEqual(["try? FileManager.default.createDirectory(at: jobsDir,"], re.findall(r"try\? FileManager\.default\.createDirectory\(at: \w+,", swift))
        self.assertEqual(["write(to: menuReport,"], re.findall(r"write\(to: \w+,", swift))
        self.assertIn("withBundleIdentifier: cmuxBundle", swift)               # cmux through Launch Services, no socket
        for bundle in ("claudeBundle", "codexBundle"):
            self.assertIn("withBundleIdentifier: %s" % bundle, swift)
        self.assertIn("guard let folder = inWorkspace(path)", swift)          # only a folder of this workspace

    def test_the_menu_bar(self):
        swift = (self.APP / "Garrick.swift").read_text()
        self.assertIn("statusItem == nil }", swift)                           # with the icon, closing the window keeps the app
        self.assertIn("RegisterEventHotKey(", swift)                          # a hotkey without Accessibility permission
        dictation = swift[swift.index("	// MARK: dictation (preview ask)"):swift.index("	// File › Ask Garrick… is there only")]
        self.assertEqual(swift.count("AXIsProcessTrusted"), dictation.count("AXIsProcessTrusted"))   # asked for only to press a dictation key
        self.assertIn("SMAppService.mainApp", swift)                          # open at login, as a login item
        self.assertIn("final class RowView: NSView", swift)                   # a row is clicked and opens a submenu
        self.assertIn("override func mouseUp(with event: NSEvent)", swift)
        self.assertIn("final class ActionBar: NSView", swift)                 # the actions on one line, as icons
        self.assertIn("guard menu === statusItem?.menu else { return }", swift)   # a submenu is never refilled with the menu
        self.assertIn("if !window.isVisible { showWindow() }", swift)          # never an app with nothing to click
        self.assertIn("NSColor.labelColor.setFill()", swift)                 # the mark in the menu bar's own colours
        self.assertIn("NSAppearance.currentDrawing()", swift)

    def test_the_ask_box_can_start_dictation(self):
        swift = (self.APP / "Garrick.swift").read_text()
        show = swift[swift.index("	@objc func showAsk("):swift.index("	// MARK: dictation (preview ask)")]
        self.assertIn("let opening = !(p.isVisible && p.isKeyWindow)", show)   # a second press never stops a tool that toggles
        self.assertLess(show.index("p.makeFirstResponder(askField)"), show.index("if opening { startDictation() }"))   # the field first
        start = swift[swift.index("	func startDictation()"):swift.index("	func setDictation(")]
        self.assertIn('if checking { return heard.append("dictation:" + mode.rawValue) }', start)   # --check presses nothing
        self.assertIn('NSApp.sendAction(Selector(("startDictation:")), to: NSApp, from: nil)', start)   # macOS Dictation needs no key
        self.assertIn("guard self?.askPanel?.isKeyWindow == true else { return }", start)   # the box gone, nothing is pressed
        fn = swift[swift.index("func tapFn()"):swift.index("func press(_ spec:")]
        for part in ("virtualKey: 63", "e.type = .flagsChanged", ".maskSecondaryFn", "e.post(tap: .cghidEventTap)", "now() + 0.08"):
            self.assertIn(part, fn)                                          # Fn as the probes on #35 found a tool hears it
        # A tool that pastes its transcript with ⌘V reaches the field only through Edit › Paste.
        self.assertIn('item("Paste", #selector(NSText.paste(_:)), "v")', swift[swift.index('sub("Edit", ['):])

    def test_the_panel(self):
        swift = (self.APP / "Garrick.swift").read_text()
        self.assertIn("enum PanelEdge: String { case left, right, top }", swift)
        self.assertIn("[.borderless, .nonactivatingPanel]", swift)             # it never brings the app forward
        self.assertIn(".canJoinAllSpaces, .fullScreenAuxiliary", swift)        # on every Space, beside full-screen apps
        self.assertIn("auxiliaryTopLeftArea", swift)                           # the notch, from the screen itself
        self.assertIn("addGlobalMonitorForEvents(matching: [.mouseMoved", swift)   # the pointer, which needs no permission
        self.assertNotIn("addGlobalMonitorForEvents(matching: [.keyDown", swift)   # keys from other apps would
        self.assertIn("asyncAfter(deadline: .now() + 0.25", swift)              # resting at the edge, not passing by
        self.assertIn("p.y >= v.maxY - v.height / 3", swift)                   # a side opens from its top third only
        self.assertIn('"Find a thread, or ask Garrick"', swift)                # the field asks too
        self.assertIn("self.launch(app, workspace.path, phrase: text)", swift)  # a question opens the assistant at the root, as the inbox does
        self.assertIn("func takeAway()", swift)                                # neither icon nor panel: the window comes back
        self.assertIn("edgePanel == nil && statusItem == nil }", swift)

    def test_the_icon_menu_finds_and_asks(self):
        swift = (self.APP / "Garrick.swift").read_text()
        self.assertIn("final class MenuField: NSView, NSSearchFieldDelegate", swift)   # a field at the top of the menu
        fill = swift[swift.index("	func fill(_ menu: NSMenu) {"):swift.index("	func fillRows(")]
        self.assertLess(fill.index("menu.addItem(field)"), fill.index('fillRows(menu, "")'))   # first, above every row
        self.assertIn("box.changed = { [weak self, weak menu] text in if let self, let menu { self.fillRows(menu, text) } }", fill)
        self.assertIn('let projects = found(zone["p"] as? [[String: Any]] ?? [], text)', swift)   # it finds as the panel does
        self.assertIn("box.window?.makeFirstResponder(box.field)", swift)             # typing goes to it as the menu opens
        self.assertIn("if let open { self.run(open) } else { self.askFrom(text) }", swift)   # Return opens what it found, or asks
        ask = swift[swift.index("	func askFrom(_ text: String) {"):]
        ask = ask[:ask.index("\n	}\n")]
        self.assertIn("askSubmit(askField)", ask)                                     # through the Ask box, to ask.py, as the panel asks
        self.assertIn("self.askGarrick(text)", swift)                                 # the panel's field
        self.assertIn("askGarrick(text) { [weak self] reply, ranAway in", swift)      # and the Ask box, the same call
        self.assertIn("launch(app, workspace.path, phrase: text)", ask)               # with the preview off, the assistant opens with the words

    def test_the_ask_hotkey_is_a_setting(self):
        swift = (self.APP / "Garrick.swift").read_text()
        self.assertIn('let kAskHotkey = "askHotkey"', swift)
        self.assertIn('let askDefault: [String: Any] = ["code": "KeyG", "mods": ["cmd"], "label": "⌘G"]', swift)
        self.assertIn("if let set = defaults.dictionary(forKey: kAskHotkey) { return set[\"code\"] == nil ? nil : set }", swift)  # set, or none
        self.assertIn("return sameKey(defaults.dictionary(forKey: kHotkey), askDefault) ? nil : askDefault", swift)   # ⌘G gives way to the menu's
        self.assertIn("let wanted = askOn() && !checking && !recording ? askSpec() : nil", swift)   # with the preview, not while recording
        self.assertIn("if register(wanted, 2, &askKey) == noErr", swift)
        self.assertIn("if which == 2 { return showAsk() }", swift)
        self.assertIn("askMenuItem?.keyEquivalent = key", swift)                      # File › Ask Garrick… shows what is set
        self.assertIn('let ask = item("Ask Garrick…", #selector(showAsk(_:)), "g")', swift)
        self.assertIn('if let key = request["askhotkey"] { setKey(kAskHotkey, "askhotkey", key as? [String: Any]) }', swift)
        self.assertIn('"askhotkey": askSpec()?["label"] as? String ?? ""', swift)
        self.assertNotIn("} else if askOn() { showAsk() }", swift)                     # the hotkey opens the menu, never the box instead

    def test_a_launch_you_make_shows_the_window(self):
        # Left with its window closed, the app starts out of sight only when
        # macOS opens it at login; opened from the Finder, the Dock or
        # Spotlight it shows the window, so one launch is always seen.
        swift = (self.APP / "Garrick.swift").read_text()
        self.assertIn("let outOfSight = startHidden && launchedAtLogin()", swift)
        self.assertIn("if !outOfSight { showWindow() }", swift)
        self.assertIn("event.paramDescriptor(forKeyword: AEKeyword(keyAEPropData))?.enumCodeValue == OSType(keyAELaunchedAsLogInItem)", swift)
        self.assertIn("if !hasVisibleWindows { showWindow() }", swift)          # and a second one, while it runs
        self.assertIn('print("saved menu: "', swift)                              # --check says what a launch shows first

    def test_a_launch_goes_straight_to_the_window(self):
        # Made an accessory before it ran and a regular app again when the
        # window showed, a launch from the Finder showed the Dock icon, took it
        # away and brought it back. Regular from the start, only a login launch
        # left out of sight turns accessory.
        swift = (self.APP / "Garrick.swift").read_text()
        self.assertIn("app.setActivationPolicy(checking ? .prohibited : .regular)", swift)
        self.assertNotIn("startHidden ? .accessory", swift)
        launch = swift[swift.index("	func applicationDidFinishLaunching("):swift.index("	func applicationShouldTerminateAfterLastWindowClosed(")]
        self.assertEqual(1, launch.count("setActivationPolicy"))
        self.assertLess(launch.index("if outOfSight { NSApp.setActivationPolicy(.accessory) }"), launch.index("WKWebView("))   # first thing

    def test_the_app_says_what_it_filled_its_menu_with(self):
        # For a menu that lists less than the page holds: each fill leaves
        # garrick-app-menu.json in the jobs folder, in counts and zone names.
        swift = (self.APP / "Garrick.swift").read_text()
        self.assertIn('ProcessInfo.processInfo.environment["GARRICK_JOBS_DIR"]', swift)     # agent.py's jobs folder
        self.assertIn('NSHomeDirectory() + "/Library/Logs/garrick-jobs"', swift)
        self.assertIn('let menuReport = jobsDir.appendingPathComponent("garrick-app-menu.json")', swift)
        rows = swift[swift.index("	func fillRows("):swift.index("	func header(")]
        self.assertIn('reportMenu("menu", query: text, rows: menu.items.filter { $0.view is RowView }.count)', rows)
        panel = swift[swift.index("	func fillPanel("):swift.index("	// MARK: ask (preview, ask)")]
        self.assertIn('reportMenu("panel", query: m.filter, rows: m.zones.reduce(0) { $0 + $1.rows.count })', panel)
        report = swift[swift.index("	func reportMenu("):swift.index("	// A row's actions, as its card offers them")]
        self.assertIn("guard !checking else { return }", report)                          # a check never writes over the app's
        for key in ('"style"', '"zones"', '"place"', '"shownZones"', '"query"', '"rows"', '"pagePost"', '"pageLoaded"', '"pageErrors"', '"saved"'):
            self.assertIn(key, report)
        self.assertIn('"z": $0["z"] as? String ?? "?", "projects":', report)                # zone names and counts
        for name in ('["n"]', '["w"]', '["u"]', '["f"]'):
            self.assertNotIn(name, report)                                                 # never a project's or thread's name, link or folder
        self.assertIn(".count, \"rows\": rows", report.replace("\n", " ").replace("\t", ""))  # the query's length, not its words
        self.assertIn('menuHeard = (Date(), data != nil, (data?["zones"] as? [Any])?.count ?? -1, (menuHeard?.count ?? 0) + 1)', swift)
        self.assertIn("guard checking else {\n\t\t\tpageLoaded = Date()\n", swift)                 # and Settings asked for (#34)
        self.assertIn("window.addEventListener('error',function(e){try{window.webkit.messageHandlers.garrick.postMessage({pageError:", swift)
        self.assertIn('print("page errors: ', swift)                                        # --check says them too

    def test_a_field_records_a_key_this_app_holds(self):
        # Carbon's hot keys are taken before any window sees the key, so while
        # a field in Settings records, the app lets go of both; one key never
        # serves both, and macOS's own refusals are said as such.
        swift = (self.APP / "Garrick.swift").read_text()
        self.assertIn('if let on = request["recording"] as? Bool, on != recording {', swift)
        self.assertIn("if !recording && !checking, let spec = defaults.dictionary(forKey: kHotkey)", swift)
        self.assertIn("recording = false     // a page loaded again has no field with the keys", swift)
        self.assertIn("if recording { recording = false; applyHotKeys() }", swift)      # nor a closed window
        self.assertIn("if sameKey(spec, other) {", swift)
        self.assertIn("if status == OSStatus(eventHotKeyExistsErr) {", swift)
        self.assertIn("macOS does not let an app take", swift)
        self.assertIn("RegisterEventHotKey(", swift)

    def test_the_panel_starts_folded_and_remembers(self):
        swift = (self.APP / "Garrick.swift").read_text()
        self.assertNotIn("@State private var folded", swift)                          # not kept in the view, which forgets
        self.assertIn('let kPanelOpen = "panelUnfolded"', swift)
        self.assertIn("@Published var unfolded = Set(defaults.stringArray(forKey: kPanelOpen) ?? [])", swift)
        self.assertIn("defaults.set(unfolded.sorted(), forKey: kPanelOpen)", swift)
        self.assertIn("let shut = query.isEmpty && !model.unfolded.contains(r.id)", swift)   # folded unless unfolded
        self.assertIn("model.resized = { [weak self] in self?.relayout() }", swift)

    def test_trouble_is_the_red_dot_not_words(self):
        swift = (self.APP / "Garrick.swift").read_text()
        self.assertNotIn('Text("Something failed")', swift)
        self.assertIn('let troubleSaid = "Something on the Status tab failed"', swift)
        self.assertIn('.help(model.trouble ? troubleSaid : "Garrick")', swift)        # the panel's mark says it on hover
        self.assertIn("statusItem?.button?.toolTip = said", swift)                    # and the menu bar's

    @unittest.skipUnless(sys.platform == "darwin" and shutil.which("xcrun"), "needs the Swift compiler")
    def test_the_app_compiles(self):
        import subprocess
        if subprocess.run(["xcrun", "--find", "swiftc"], capture_output=True).returncode:
            self.skipTest("no swiftc")
        done = subprocess.run(["xcrun", "swiftc", "-typecheck", str(self.APP / "Garrick.swift")], capture_output=True, text=True)
        self.assertEqual(0, done.returncode, done.stderr)


@unittest.skipUnless(fixtures.HAVE_GIT, "git is not installed")
class TestCheckChipFix(StatusCase):
    """#179: a `check` chip's Fix runs Nurture's own mechanical fix, and the
    chip is gone once the page rebuilds. Real tools, a real repository."""

    rows, row = TestOpensOnTheWork.rows, TestOpensOnTheWork.row

    def setUp(self):
        super().setUp()
        env = mock.patch.dict(os.environ, dict({k: v for k, v in fixtures.GIT_ENV.items() if k.startswith("GIT_")},
                                               GARRICK_JOBS_DIR=str(self.jobs)))
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("GIT_DIR", None)
        os.environ.pop("GARRICK_HEADLESS", None)
        shutil.copytree(REPO / "template" / "System" / "tools", self.root / "System" / "tools",
                        ignore=shutil.ignore_patterns("__pycache__"))
        self.work = self.root / "Zones" / "Work"
        self.note = self.work / "Birch Entry" / "Threads" / "Market Sizing" / "Market Sizing.md"
        self.note.write_text(self.note.read_text(encoding="utf-8").replace("status: active", "status: ongoing"), encoding="utf-8")
        shutil.rmtree(self.work / ".git")
        fixtures.git(self.work, "init", "-q")
        fixtures.git(self.work, "add", "-A")
        fixtures.git(self.work, "-c", "core.hooksPath=" + os.devnull, "commit", "-q", "-m", "start")

    def test_fix_clears_the_chip_once_the_rebuild_finishes(self):
        row = self.row(self.page(), "Market Sizing")
        self.assertIn('class="chip tchip check late"', row)
        self.assertIn("Its status says “ongoing”, a word no tool reads", row)
        self.assertIn("Change it to <code>active</code>, the word every tool reads.", row)
        act = re.search(r'<button class="act primary tacts" type="button" data-act="([^"]+)"[^>]*>Fix</button>', row)
        req = json.loads(htmllib.unescape(act.group(1)))
        self.assertEqual({"verb": "fix", "zone": "Work", "file": "Birch Entry/Threads/Market Sizing/Market Sizing.md"}, req)
        self.assertIn("fix", status.ZONE_VERBS)                       # shown running, and its zone held, while it works
        spec = importlib.util.spec_from_file_location("page_action_for_fix", REPO / "extras" / "status" / "page_action.py")
        page_action = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(page_action)
        said = page_action.act(self.root, req)
        self.assertIn("Fixed: ", said)
        self.assertIn("status: active", self.note.read_text(encoding="utf-8"))
        self.assertEqual("", fixtures.git(self.work, "status", "--porcelain").strip())      # committed, in the zone
        self.assertEqual(2, len(fixtures.git(self.work, "log", "--format=%h").split()))
        row = self.row(self.page(), "Market Sizing")
        self.assertNotIn("tchip", row)
        with self.assertRaises(page_action.Refused):                   # a second click finds nothing left to fix
            page_action.act(self.root, req)



class TestMemorySettings(StatusCase):
    """Settings › Memory (#108): fade.py's settings drawn as they are, kinds
    and all, with what they would do now beside them. A stand-in fade.py,
    since the real one is graded oblivion's and has its own tests."""

    def setUp(self):
        super().setUp()
        fixtures.write_fade_stub(self.root)

    def section(self, html=None):
        html = html or self.page()
        start = html.index('<section class="setsec apponly" id="memory-settings">')
        return html[start:html.index("</section>", start)]

    def test_the_defaults_as_fade_has_them(self):
        sec = self.section()
        self.assertIn('<input type="checkbox" data-mwikion="Meetings" checked', sec)
        self.assertIn('<input type="checkbox" data-mwikion="Knowledge" checked', sec)
        self.assertEqual(["meetings", "reading", "reference"], re.findall(r'data-mkind="([a-z]+)"', sec))
        meetings = sec[sec.index('data-mkind="meetings"'):sec.index('data-mkind="reading"')]
        self.assertIn('data-mwiki="Meetings"', meetings)
        self.assertIn('data-mk="dormant" min="1" max="240" value="6"', meetings)
        self.assertIn('data-mk="archived" min="1" max="240" value="18"', meetings)
        self.assertIn('data-mk="types" value="meeting, email"', meetings)
        self.assertIn('<input type="checkbox" data-mk="never" aria-label', meetings)
        reference = sec[sec.index('data-mkind="reference"'):]
        self.assertIn('<input type="checkbox" data-mk="never" checked', reference)          # archived: never
        self.assertRegex(reference, r'data-mk="archived"[^>]*disabled>')
        self.assertEqual(4, len(re.findall(r'data-mpin="[a-z]+" checked', sec)))
        self.assertIn('<input type="checkbox" id="m-wake" checked aria-label="Propose bringing back a dormant page that active '
                      'work links again">', sec)
        self.assertIn('<option value="dormant" selected>working and dormant pages</option>', sec)
        self.assertIn('<input type="checkbox" id="m-night" checked', sec)
        self.assertIn('id="m-min" min="1" max="1000" value="10"', sec)
        self.assertIn("dormant ones in its <code>dormant/</code> folder, archived ones in its <code>archive/</code> folder", sec)
        self.assertIn('<div class="mwiki" data-mw="Meetings"><p class="mcount"><b>Meetings</b> <span data-mc="grades">40 working · '
                      '12 dormant · 5 archived</span><span class="mnext" data-mc="next">Next pass: 4 to dormant, 2 to the archive, '
                      '1 woken</span></p>', sec)
        self.assertIn("Next pass: 9 to dormant, 4 to the archive, 1 woken", sec)              # Knowledge's two kinds
        # a fade.py older than preview() and its sentences: the counts alone, and no rule worded here in its place
        self.assertNotIn('data-mc="moving"', sec)
        self.assertNotIn('class="hint msaid"', sec)
        self.assertIn("The full list, every page with why: <code>System/generated/fade/Meetings.md</code>", sec)

    def test_what_was_saved_is_shown(self):
        write(self.root / "System" / "garrick-settings.json", json.dumps({"memory": {
            "wikis": {"Knowledge": False}, "reach": "working", "wake": False, "nightly": {"min": 25},
            "kinds": {"board meetings": {"wiki": "Meetings", "types": ["meeting"], "domains": ["board.example"],
                                          "dormant": 12, "archived": None}}}}))
        sec = self.section()
        self.assertEqual(["board meetings"], re.findall(r'data-mkind="([^"]+)"', sec))      # whatever kinds fade.py returns
        self.assertIn('data-mk="domains" value="board.example"', sec)
        self.assertIn('<input type="checkbox" data-mwikion="Knowledge" aria-label', sec)
        self.assertIn('<option value="working" selected>', sec)
        self.assertIn('<input type="checkbox" id="m-wake" aria-label', sec)
        self.assertIn('id="m-min" min="1" max="1000" value="25"', sec)
        self.assertIn("Next pass: 2 to dormant</span>", sec)                                 # 24 // 12, never archived, no waking
        self.assertIn('<span class="mnext" data-mc="next">Off: nothing fades</span>', sec)

    def test_left_out_without_fade_and_said_when_it_fails(self):
        os.remove(str(self.root / "System" / "tools" / "fade.py"))
        status._FADE.pop(self.root, None)
        html = self.page()
        self.assertNotIn('id="memory-settings"', html)
        self.assertIn('id="settings"', html)
        write(self.root / "System" / "tools" / "fade.py", "def settings(root):\n    raise RuntimeError('no')\n"
                                                           "def counts(root, memory=None):\n    return {}\n")
        status._FADE.pop(self.root, None)
        sec = self.section()
        self.assertIn("did not give its settings (RuntimeError)", sec)
        self.assertNotIn('id="m-prev"', sec)
        write(self.root / "System" / "tools" / "fade.py", "import nothing_by_this_name\n")
        status._FADE.pop(self.root, None)
        self.assertNotIn('id="memory-settings"', self.page())

    def test_the_form_reads_back_into_fades_keys_and_counts_again(self):
        for key in ("wikis", "kinds", "pins", "wake", "reach", "nightly", "dormant", "archived", "types", "domains", "min"):
            self.assertIn(key, status.MEMORY_JS)
        self.assertIn("window.GarrickMemory=", status.MEMORY_JS)
        self.assertIn("host.postMessage({act:{verb:'memory-preview',memory:request()}})", status.MEMORY_JS)
        self.assertIn("window.GarrickReadsMemory", status.MEMORY_JS)          # only where the host answers it
        self.assertIn("if(m){q.memory=M.request();M.saved()}", status.JS)     # sent with the rest when Settings closes
        page = self.page()
        self.assertIn(status.MEMORY_CSS.strip()[:60], page)
        self.assertEqual(1, page.count('id="memory-settings"'))
        self.assertLess(page.index("window.GarrickWait="), page.index("window.GarrickMemory="))

    def test_the_page_and_its_script_say_the_counts_alike(self):
        c = {"on": True, "working": 3, "dormant": 2, "archived": 1, "to_dormant": 0, "to_archive": 4, "to_wake": 0}
        self.assertEqual(("3 working · 2 dormant · 1 archived", "Next pass: 4 to the archive"), status.memory_said(c))
        self.assertEqual("Next pass: nothing moves", status.memory_said(dict(c, to_archive=0))[1])
        self.assertEqual("Off: nothing fades", status.memory_said(dict(c, on=False))[1])
        for words in ("' working · '", "' dormant · '", "' archived'", "'Off: nothing fades'", "'to dormant'",
                      "'to the archive'", "'woken'", "'Next pass: '", "'nothing moves'"):
            self.assertIn(words, status.MEMORY_JS)

    def test_it_reads_as_three_grades_and_three_steps_before_any_rule(self):
        sec = htmllib.unescape(self.section())
        for words in ("Older meetings and reading move out of the way, so today's work is quicker to find. Nothing is ever "
                      "deleted, and nothing moves until you say yes.",
                      "Put aside: out of the index, but still found when a search reaches back for it",
                      "Kept out of the way: found only when you ask to search the archive.",
                      "Closing Settings saves the rules below. Saving moves nothing.",
                      "Ask “what would fade”: it writes the list of what the next pass would move, and why.",
                      "Pages move only when you say yes to that list",
                      "Active work is never put aside"):
            self.assertIn(words, sec)                                               # on screen, not behind the "?"
        order = [sec.index(x) for x in ('class="mgradesay"', 'class="msteps"', 'id="m-prev"', 'data-mwikion=',
                                        'data-mkind=', 'data-mpin=', 'id="m-wake"', 'id="m-reach"', 'id="m-night"')]
        self.assertEqual(sorted(order), order)                                      # what would happen, then the rules
        self.assertEqual(3, sec.count('class="madv"'))                              # each kind's lists, under Advanced
        self.assertRegex(sec, r'<details class="madv"><summary>Advanced: which pages this kind takes</summary>'
                              r'<label class="mlist">Types <input type="text" data-mk="types"')
        for gone in ("Use wakes a dormant page", "Opened, quoted or linked again"):
            self.assertNotIn(gone, sec)

    def test_with_the_real_fade_it_names_the_pages_and_says_its_own_rules(self):
        fixtures.write_fade(self.root)
        status._FADE.pop(self.root, None)
        fade = status.fade_lib(self.root)
        self.assertTrue(callable(fade.preview))
        sec = self.section()
        for name in ("AGE_SAID", "WAKE_SAID"):
            self.assertIn('<p class="hint msaid">%s</p>' % status.said_html(getattr(fade, name)), sec)   # fade.py's words, as they are
        self.assertIn("<code>pinned: true</code>", status.said_html(fade.WAKE_SAID))
        meetings = sec[sec.index('data-mw="Meetings"'):sec.index('data-mw="Knowledge"')]
        moving = re.search(r'<ul class="mrows" data-mc="moving">(.*?)</ul>', meetings).group(1)
        self.assertEqual(fade.PREVIEW_LIMIT, moving.count("<li>"))                  # a short list
        self.assertIn('<li><b>Old call 1</b> <span class="mdate">2020-01-01</span> <span class="mto">to the archive</span>'
                      '<small>', moving)
        self.assertIn("months old; meetings are archived at 18</small>", moving)    # and why
        self.assertRegex(meetings, r'<p class="mmore" data-mc="moves">and \d+ more</p>')
        keeping = re.search(r'<ul class="mrows" data-mc="keeping">(.*?)</ul>', meetings).group(1)
        self.assertIn('<li><b>Kept call</b> <span class="mdate">2020-01-08</span><small>Kept by a live thread, '
                      'Zones/Work/Acme Review/Threads/Pricing/Pricing.md</small></li>', keeping)
        self.assertIn('<p class="mkeptlab" data-mc="keptlab">Old enough to go, but kept for active work</p>', meetings)
        self.assertIn("<code>System/generated/fade/Meetings.md</code>, written when you ask", htmllib.unescape(meetings))
        self.assertFalse((self.root / "System" / "generated").exists())             # building the page writes nothing
        fade.propose(self.root, "Meetings")
        meetings = self.section().split('data-mw="Meetings"', 1)[1]
        self.assertRegex(meetings, r'<a href="[^"]+">System/generated/fade/Meetings\.md</a>, as last written')

    def test_the_script_draws_the_pages_as_the_page_does(self):
        js = status.MEMORY_JS
        self.assertIn("paint(out.counts,out.preview)", js)
        for words in ("'to dormant'", "'to the archive'", "'back to working'", "'Kept by '", "'undated'", "'and '", "' more'"):
            self.assertIn(words, js)
        self.assertEqual({"dormant": "to dormant", "archived": "to the archive", "working": "back to working"}, status.MEMORY_TO)
        self.assertIn("textContent", js)
        self.assertNotIn("innerHTML", js)                                           # a title is the user's text, never markup

    @unittest.skipUnless(shutil.which("node"), "Node is not installed")
    def test_the_script_parses(self):
        done = subprocess.run(["node", "-e", "new Function(require('fs').readFileSync(0,'utf8'))"], input=status.MEMORY_JS,
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(0, done.returncode, done.stderr)

class TestContextDebt(StatusCase):
    """#69: the context debt beside the check's findings, read from the
    records nurture.py keeps, with nothing run."""

    def setUp(self):
        super().setUp()
        shutil.copytree(REPO / "template" / "System" / "tools", self.root / "System" / "tools",
                        ignore=shutil.ignore_patterns("__pycache__"))
        self.folder = self.root / "System" / "generated" / "nurture"

    def record(self, back, total, scopes=None, whole=True):
        day = self.now.date() - dt.timedelta(days=back)
        scopes = scopes or {"Wikis/Meetings": {"attribution": total}}
        kinds = {}
        for ks in scopes.values():
            for k, v in ks.items():
                kinds[k] = kinds.get(k, 0) + v
        write(self.folder / ("%s.json" % day.isoformat()), json.dumps({"date": day.isoformat(), "debt": {
            "total": total, "kinds": kinds, "scopes": scopes, "whole": whole, "threshold": 40}}))

    def block(self, html):
        start = html.index('<div class="debt" id="debt">')
        return html[start:html.index("</p></div>", start)]

    def test_nothing_without_a_record(self):
        html = self.page()
        self.assertNotIn('id="debt"', html)
        self.record(0, 12, whole=False)                     # a scoped run's part is not the workspace's debt
        self.assertNotIn('id="debt"', self.page())

    def test_the_figure_its_trend_and_the_scopes_carrying_most(self):
        for back, total in ((40, 3), (6, 18), (5, 20), (3, 30), (2, 35), (1, 40)):
            self.record(back, total)
        self.record(0, 42, {"Wikis/Meetings": {"attribution": 25}, "Zones/Work": {"wall": 10, "judgment": 2},
                            "System": {"judgment": 5}})
        b = self.block(self.page())
        self.assertIn('<span class="dfig">42</span><span class="dlbl">context debt</span>', b)
        self.assertIn('<span class="chip late"', b)
        self.assertIn(">over 40</span>", b)
        self.assertEqual(2, b.count('<polyline class="dl"'))               # broken where a day has no record
        self.assertEqual(6, b.count('class="dd'))                          # thirty days: the one 40 days back left out
        self.assertEqual(1, b.count('class="dd now"'))
        self.assertIn('class="dt"', b)                                     # the threshold, dashed
        self.assertIn('role="img" aria-label="Context debt, last 30 days: 18 on ', b)
        self.assertIn("Most in the Meetings wiki 25 · Work 12 · System 5.", b)
        self.assertIn('data-request="nurture the meetings" data-folder="%s"' % self.root, b)      # a button, not "Say …" (#234)
        self.assertIn('>Nurture the meetings</button>', b)
        self.assertNotIn("Say &#8220;", b)
        for colour in re.findall(r"(?<![&\w])#[0-9a-fA-F]{3,6}\b", b):                # the page's tokens only, for light and dark
            self.fail("a fixed colour in the chart: %s" % colour)
        self.assertIn(status.DEBT_CSS.strip()[:60], self.page())

    def test_under_the_threshold_and_an_older_day(self):
        self.record(2, 9, {"Zones/Work": {"judgment": 9}})
        b = self.block(self.page())
        self.assertIn('<span class="dfig">9</span><span class="dlbl">context debt as of ', b)
        self.assertIn('<span class="chip"', b)
        self.assertIn(">under 40</span>", b)
        self.assertIn('<button class="act dask" type="button" data-request="nurture Work"', b)
        self.assertIn(">Nurture Work</button>", b)
        self.assertNotIn("<polyline", b)                                    # one day: a dot, no line

    def test_left_out_without_a_nurture_that_keeps_it(self):
        self.record(0, 42)
        with mock.patch.object(status, "nurture_lib", lambda ws: None):
            self.assertNotIn('id="debt"', self.page())

if __name__ == "__main__":
    unittest.main()
