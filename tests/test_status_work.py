"""An action that runs (#77): the status page shows a request that commits in a
zone running until its reply comes, holds that zone's buttons meanwhile, and
keeps a slow failure on screen until it is dismissed, while a slow success
fades (#107). Ticks are queued while the zone is busy and go as one batch
(#107). WORK_JS is run in Node against a stand-in for the page, and the hosts
are read for what they hand it.

    python3 -m unittest discover -s tests
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

from test_status import REPO, StatusCase, status  # noqa: E402

HERE = REPO / "extras" / "status"
spec = importlib.util.spec_from_file_location("page_action_for_work", HERE / "page_action.py")
page_action = importlib.util.module_from_spec(spec)
spec.loader.exec_module(page_action)

# Just enough of a page for WORK_JS: the two toasts, a head for its style, a
# clock the test moves, sessionStorage that outlives a reload, and the
# messages it posts. Each step is [what, at seconds, ...]; each reload runs
# the script again on the same storage, as a rebuilt page does. Todo rows, when
# given, are drawn afresh on each load as the note has them, and a click on
# one does what TODO_JS does: strikes it through and hands it to GarrickTick.
HARNESS = textwrap.dedent(r"""
    const vm = require("vm");
    const [js, steps, reads, drawn] = JSON.parse(process.argv[1]);
    const store = {}, posted = [], asked = [], out = [];
    let toasts = 0;
    let clock = 1000000, ctx, box, toast, style, interval, chained = [], rows = [];
    function row(r) {
      const cls = new Set(r.done ? ["trow", "done"] : ["trow"]);
      const tick = { label: (r.done ? "Reopen: " : "Mark done: ") + r.text,
                     getAttribute(k) { return this.label; }, setAttribute(k, v) { this.label = v; } };
      return { dataset: { z: r.z || "Work", f: r.f || "Todo.md", k: r.k },
               classList: { contains: (c) => cls.has(c), toggle: (c, on) => { if (on === undefined) on = !cls.has(c); on ? cls.add(c) : cls.delete(c); return on; } },
               querySelector: (sel) => (sel === ".tick" ? tick : null), tick };
    }
    function load() {
      rows = (drawn || []).map(row);
      box = { innerHTML: "", hidden: true, offsetHeight: 40, listeners: {}, addEventListener(k, f) { this.listeners[k] = f; },
              // each running request's time, written back into the markup
              querySelectorAll(sel) {
                if (sel !== ".wt") return [];
                return [...this.innerHTML.matchAll(/data-t0="(\d+)"/g)].map((m) => ({ dataset: { t0: m[1] },
                  set textContent(v) { box.innerHTML = box.innerHTML.replace(new RegExp('(data-t0="' + m[1] + '"[^>]*>)[^<]*'), "$1" + v); } }));
              } };
      toast = { _t: "", set textContent(v) { this._t = v; toasts += 1; }, get textContent() { return this._t; }, style: { opacity: 0 } };
      style = null;
      interval = null;
      const document = {
        getElementById: (id) => id === "work" ? box : id === "toast" ? toast : id === "work-hold" ? style : null,
        createElement: () => ({ textContent: "" }),
        head: { appendChild: (el) => { style = el; } },
        body: { style: { setProperty: () => {} } },
        querySelectorAll: (sel) => (sel === ".trow" ? rows : []),
      };
      ctx = { JSON, String, Math, document, Date: { now: () => clock },
              sessionStorage: { getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); } },
              setInterval: (f) => { interval = f; return 1; }, clearInterval: () => { interval = null; },
              setTimeout: () => 0, clearTimeout: () => {} };
      ctx.window = ctx;                    // as in a browser, the page's globals are the window's
      ctx.webkit = { messageHandlers: { garrick: { postMessage: (m) => (m.act && m.act.verb === "operations" ? asked : posted).push(m) } } };
      ctx.GarrickActed = (q, o) => chained.push(q.verb);
      if (reads) ctx.GarrickReads = true;        // as the Mac app sets it, before the page's scripts run
      vm.createContext(ctx);
      vm.runInContext(js, ctx);
    }
    load();
    for (const [what, at, a, b] of steps) {
      clock = 1000000 + at * 1000;
      let r = null;
      if (what === "act") r = ctx.window.GarrickAct(a, b);
      if (what === "reply") ctx.window.GarrickActed(a, b);
      if (what === "ops") ctx.window.GarrickActed({ verb: "operations" }, a);
      if (what === "tick" && interval) interval();
      if (what === "reload") load();
      // as the Obsidian plugin does it, once the page's script has already run
      if (what === "host") { ctx.GarrickReads = true; if (ctx.window.GarrickReady) ctx.window.GarrickReady(); }
      if (what === "dismiss") box.listeners.click({ target: { closest: () => ({ dataset: { wx: String(a) } }) } });
      if (what === "again") box.listeners.click({ target: { closest: (sel) => (sel === "[data-again]" ? { dataset: { again: String(a) } } : null) } });
      if (what === "busy") r = ctx.window.GarrickBusy(a);
      if (what === "click") {                // TODO_JS's click on a row's box
        const el = rows.find((x) => x.dataset.k === a), d = !el.classList.contains("done");
        r = ctx.window.GarrickTick({ verb: d ? "todo-done" : "todo-undo", zone: el.dataset.z, file: el.dataset.f, key: a });
        el.classList.toggle("done", d);
      }
      const card = (i) => ({ closest: (sel) => (sel === "[data-i]" && i !== null ? { dataset: { i: String(i) } } : null) });
      if (what === "hover") box.listeners.mouseover({ target: card(a) });
      if (what === "leave") box.listeners.mouseout({ target: card(a), relatedTarget: null });
      out.push({ r, box: box.hidden ? "" : box.innerHTML, toast: toast.textContent, opacity: toast.style.opacity,
                 hold: style ? style.textContent : "", posted: posted.length, asked: asked.length, toasts, sent: posted.slice(), ticking: !!interval, chained: chained.slice(),
                 done: Object.fromEntries(rows.map((x) => [x.dataset.k, x.classList.contains("done")])),
                 labels: Object.fromEntries(rows.map((x) => [x.dataset.k, x.tick.label])) });
    }
    process.stdout.write(JSON.stringify(out));
""")

ACME = {"verb": "new-project", "zone": "Work", "name": "Acme", "party": "acme", "thread": "Pricing"}
# The same request as the host hands it back: Swift's JSON does not keep the keys' order.
ACME_BACK = {"thread": "Pricing", "zone": "Work", "party": "acme", "name": "Acme", "verb": "new-project"}
PARK = {"verb": "park", "zone": "Work", "file": "Birch Entry/Birch Entry.md"}
HOME = {"verb": "todo-add", "zone": "Personal", "target": "-", "date": "-", "text": "Book the car service"}


class NodeCase(unittest.TestCase):
    def run_js(self, *steps, **kw):
        """`reads`: whether the host says it can answer a request that reads, as
        the Mac app does at document start. False for a host from 0.26.0."""
        done = subprocess.run(["node", "-e", HARNESS, json.dumps([status.WORK_JS, [list(s) for s in steps],
                                                                  kw.get("reads", True), kw.get("rows", [])])],
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(0, done.returncode, done.stderr)
        return json.loads(done.stdout)


@unittest.skipUnless(shutil.which("node"), "Node is not installed")
class TestWorkUnderNode(NodeCase):

    def test_a_slow_new_project_shows_it_is_working_until_its_reply_and_the_reply_fades(self):
        out = self.run_js(("act", 0, ACME, "Making Acme…"), ("tick", 5), ("tick", 12), ("tick", 75),
                          ("reload", 80), ("reply", 81, ACME_BACK, {"ok": True, "say": "Made Acme, first thread Pricing"}),
                          ("reload", 83), ("tick", 84), ("tick", 85.5))
        sent, five, twelve, late, reloaded, replied, rebuilt, still, faded = out
        self.assertTrue(sent["r"])
        self.assertEqual(1, sent["posted"])
        self.assertIn("Making Acme…", sent["box"])
        self.assertIn('class="wspin"', sent["box"])                         # a spinner
        self.assertIn(">0 s<", sent["box"])
        self.assertTrue(sent["ticking"])
        self.assertNotIn("wall check", five["box"])                          # why, only after ten seconds
        self.assertIn("Committing: the wall check can take a minute.", twelve["box"])
        self.assertIn(">12 s<", twelve["box"])
        self.assertIn(">1 min 15 s<", late["box"])                           # still working, past a minute
        self.assertIn("Making Acme…", reloaded["box"])                       # a rebuild meanwhile keeps it
        self.assertIn(">1 min 20 s<", reloaded["box"])
        self.assertIn("Made Acme, first thread Pricing", replied["box"])     # the reply takes its place
        self.assertIn("Making Acme, 1 min 21 s", replied["box"])
        self.assertIn('data-wx="0"', replied["box"])                         # with its × to close it sooner
        self.assertNotIn("wspin", replied["box"])
        self.assertEqual(0, replied["opacity"])                              # the host's own toast steps aside
        self.assertTrue(replied["ticking"])                                  # counting down to its fade
        self.assertEqual(["new-project"], replied["chained"])                # the hooks set before it still run
        self.assertIn("Made Acme, first thread Pricing", rebuilt["box"])     # the rebuild after the reply keeps it
        self.assertIn("Made Acme, first thread Pricing", still["box"])       # three seconds on, still there
        self.assertEqual("", faded["box"])                                   # ACTION_TOAST after it came, gone by itself
        self.assertFalse(faded["ticking"])

    def test_a_quick_reply_is_the_hosts_toast_as_before(self):
        out = self.run_js(("act", 0, PARK, "Parking Birch Entry…"), ("reply", 2, PARK, {"ok": True, "say": "Parked"}))
        self.assertIn("Parking Birch Entry…", out[0]["box"])
        self.assertEqual("", out[1]["box"])
        self.assertEqual(0, out[1]["opacity"])                               # the stand-in host showed no toast; nothing changed it
        self.assertFalse(out[1]["ticking"])

    def test_a_refusal_after_a_long_wait_stays_too(self):
        out = self.run_js(("act", 0, ACME, "Making Acme…"),
                          ("reply", 30, ACME, {"ok": False, "say": "made, but not committed: the wall check refused"}))
        self.assertIn('class="wk bad"', out[1]["box"])
        self.assertIn("made, but not committed: the wall check refused", out[1]["box"])

    def test_a_quick_refusal_of_a_rename_stays_until_it_is_dismissed(self):
        """#177: the dialog has closed and the eye is on the card, so a refused
        rename, deletion, new project or new thread stays, however quick."""
        why = ("Acme/Threads/Pricing/notes.txt is in Pricing but not in the zone's history, so nothing could bring it back. "
               "Commit it or move it out, then rename.")
        rename = {"verb": "rename", "zone": "Work", "project": "Acme", "thread": "Pricing", "to": "Renewal"}
        out = self.run_js(("act", 0, rename, "Renaming Pricing…"), ("reply", 0.6, rename, {"ok": False, "say": why}),
                          ("tick", 5), ("tick", 60), ("reload", 61), ("dismiss", 62, 0))
        sent, replied, five, minute, rebuilt, dismissed = out
        self.assertIn('class="wk bad"', replied["box"])
        self.assertIn("notes.txt is in Pricing but not in the zone", replied["box"])
        self.assertIn("Renaming Pricing, 1 s", replied["box"])
        self.assertIn('data-wx="0"', replied["box"])
        self.assertEqual(0, replied["opacity"])                              # the card says it; the toast steps aside
        for later in (five, minute, rebuilt):                                # no fade, and a rebuild keeps it
            self.assertIn("notes.txt", later["box"])
        self.assertEqual("", dismissed["box"])
        for verb, q in (("delete", {"verb": "delete", "zone": "Work", "project": "Acme", "confirm": "Acme"}), ("new-project", ACME),
                        ("new-thread", {"verb": "new-thread", "zone": "Work", "project": "Acme", "name": "Freight"})):
            out = self.run_js(("act", 0, q, "Working…"), ("reply", 1, q, {"ok": False, "say": "Refused."}), ("tick", 30))
            self.assertIn("Refused.", out[-1]["box"], verb)
        # a quick refusal of anything else is the host's toast, as before; and so is a quick success of these
        out = self.run_js(("act", 0, PARK, "Parking Birch Entry…"), ("reply", 1, PARK, {"ok": False, "say": "Refused."}))
        self.assertEqual("", out[-1]["box"])
        out = self.run_js(("act", 0, rename, "Renaming Pricing…"), ("reply", 1, rename, {"ok": True, "say": "Renamed."}))
        self.assertEqual("", out[-1]["box"])

    def test_the_zone_is_held_and_the_others_are_not(self):
        out = self.run_js(("act", 0, ACME, "Making Acme…"), ("act", 3, PARK, "Parking Birch Entry…"),
                          ("act", 4, HOME, "Adding to Personal: Book the car service…"),
                          ("act", 5, {"verb": "settings", "launchers": ["note"]}, "Saving…"),
                          ("busy", 6, "Work"), ("busy", 6, "Personal"),
                          ("reply", 40, ACME, {"ok": True, "say": "Made Acme"}), ("busy", 41, "Work"),
                          ("act", 42, PARK, "Parking Birch Entry…"))
        first, again, other, unzoned, work, home, replied, free, after = out
        self.assertNotIn("button.tick", first["hold"])                        # a Todo box stays clickable (#107)
        for sel in ('.trow[data-z="Work"] button.tdate', '.tadd-open[data-zone="Work"]',
                    'button[data-mg^="[\\"Work\\","]', 'button[data-act*="\\"verb\\":\\"park\\""][data-act*="\\"zone\\":\\"Work\\""]',
                    'button[data-act*="\\"verb\\":\\"wake\\""][data-act*="\\"zone\\":\\"Work\\""]'):
            self.assertIn(sel, first["hold"])
        self.assertIn("pointer-events:none", first["hold"])
        self.assertTrue(again["r"])                                          # taken, and refused
        self.assertEqual(1, again["posted"])                                 # nothing sent
        self.assertEqual("Work is still busy: Making Acme…", again["toast"])
        self.assertEqual(2, other["posted"])                                 # another zone goes ahead
        self.assertIn('.trow[data-z="Personal"] button.tdate', other["hold"])
        self.assertFalse(unzoned["r"])                                       # not a zone's: the button sends it as before
        self.assertEqual(2, unzoned["posted"])
        self.assertEqual("Making Acme…", work["r"])
        self.assertEqual("Adding to Personal: Book the car service…", home["r"])
        self.assertNotIn('"Work"', replied["hold"])                          # done: the zone is free again
        self.assertEqual("", free["r"])
        self.assertEqual(3, after["posted"])

    def test_a_request_with_no_reply_is_given_up(self):
        lost = status.ACTION_LOST
        out = self.run_js(("act", 0, ACME, "Making Acme…"), ("tick", lost - 1), ("tick", lost + 1), ("busy", lost + 2, "Work"))
        self.assertIn("Making Acme…", out[1]["box"])
        self.assertIn("No reply after 16 min. Look at git status in Work before trying again.", out[2]["box"])
        self.assertEqual("", out[3]["r"])

    def test_a_request_done_already_is_asked_about_and_do_it_again_confirms_it(self):
        """#137: past the double click's window the record asks rather than
        doing it twice. The question stays, however quick, and its button sends
        the same request once more, naming the action it was asked about."""
        question = ("The same request was done 5 minutes ago, at 14:02: Birch Entry is parked. It has not been done again. "
                    "Do you want it done a second time?")
        asked = {"ok": False, "say": question, "op": "a19f3c80", "state": "asked", "again": "a19f3c80"}
        out = self.run_js(("act", 0, PARK, "Parking Birch Entry…"), ("reply", 1, PARK, asked), ("reload", 2),
                          ("again", 3, 0))
        sent, replied, rebuilt, again = out
        self.assertIn('class="wk ask"', replied["box"])                      # neither a success nor a failure
        self.assertIn(question, replied["box"])
        self.assertIn('data-again="0">Do it again</button>', replied["box"])
        self.assertEqual(0, replied["opacity"])                              # the box says it; the toast steps aside
        self.assertFalse(replied["ticking"])
        self.assertIn("Do it again", rebuilt["box"])                         # a rebuild keeps the question
        self.assertEqual(2, again["posted"])
        first, second = again["sent"][0]["act"], again["sent"][1]["act"]
        self.assertNotIn("confirm", first)
        self.assertEqual("a19f3c80", second["confirm"])                      # the action it was asked about
        self.assertNotEqual(first["op"], second["op"])                       # and an id of its own
        self.assertTrue(re.fullmatch(r"[0-9a-f]{16}", second["op"]))
        self.assertEqual({k: v for k, v in first.items() if k != "op"}, {k: v for k, v in second.items() if k not in ("op", "confirm")})
        self.assertNotIn("Do it again", again["box"])                        # the question gives way to the request
        self.assertIn("Parking Birch Entry…", again["box"])
        self.assertIn('class="wspin"', again["box"])

    def test_dismissing_the_question_sends_nothing(self):
        asked = {"ok": False, "say": "The same request was done…?", "op": "a19f3c80", "state": "asked", "again": "a19f3c80"}
        out = self.run_js(("act", 0, PARK, "Parking Birch Entry…"), ("reply", 1, PARK, asked), ("dismiss", 2, 0))
        self.assertEqual("", out[-1]["box"])
        self.assertEqual(1, out[-1]["posted"])

    def test_a_browser_gets_none_of_it(self):
        done = subprocess.run(["node", "-e", "const vm=require('vm');const c={window:{}};vm.createContext(c);"
                               "vm.runInContext(process.argv[1],c);process.stdout.write(String(typeof c.window.GarrickAct))",
                               status.WORK_JS], capture_output=True, text=True, timeout=30)
        self.assertEqual("undefined", done.stdout, done.stderr)


# Five open lines in Work, as the Todo tab draws them, and a sixth already ticked today.
LINES = [{"k": "%016x" % i, "text": "Line %d for Acme Corp" % i} for i in range(1, 6)] + \
        [{"k": "%016x" % 6, "text": "Line 6 for Birch & Co", "done": True}]
K = [line["k"] for line in LINES]
WALL = "A wall holds some material back from this project, so I have not used it. Nothing was written."


def acts(out):
    return [m["act"] for m in out["sent"]]


@unittest.skipUnless(shutil.which("node"), "Node is not installed")
class TestTicksUnderNode(NodeCase):
    """#107: a tick is struck through on the click, queued while the zone is busy,
    and sent with the ticks around it as one request with `keys`."""

    def run_rows(self, *steps, **kw):
        return self.run_js(*steps, rows=LINES, **kw)

    def test_five_ticks_while_a_commit_runs_land_in_two_requests(self):
        out = self.run_rows(("click", 0, K[0]), ("tick", 1), ("tick", 2.5),                    # the first goes on its own
                            ("click", 3, K[1]), ("click", 3.5, K[2]), ("click", 4, K[3]), ("click", 4.5, K[4]),
                            ("tick", 5), ("tick", 8),                                            # its commit is still running
                            ("reply", 9, {"verb": "todo-done", "zone": "Work", "op": "x"}, None),
                            ("tick", 10))
        first, waited, went = out[0], out[1], out[2]
        self.assertTrue(first["r"])
        self.assertEqual(0, first["posted"])                                  # struck through, not sent yet
        self.assertTrue(first["done"][K[0]])
        self.assertEqual(0, waited["posted"])                                 # within ACTION_BATCH of the click
        self.assertEqual([{"verb": "todo-done", "zone": "Work", "file": "Todo.md", "keys": [K[0]], "op": acts(went)[0]["op"]}],
                         acts(went))
        self.assertEqual("", went["box"])                                     # no toast of its own yet
        self.assertNotIn("button.tick", went["hold"])                         # the boxes stay clickable while it commits
        self.assertIn("button.tdate", went["hold"])                           # and everything else in the zone is held
        for o in out[3:7]:
            self.assertTrue(o["r"])                                           # taken, never refused for a busy zone
            self.assertEqual(1, o["posted"])
        self.assertEqual([True] * 5 + [True], [out[6]["done"][k] for k in K])
        self.assertEqual(1, out[8]["posted"])                                 # busy: the four wait for the first
        self.assertIn("Ticking it…", out[8]["box"])                           # which, past ACTION_TOAST, shows it is working
        done = out[10]
        self.assertEqual(2, done["posted"])                                   # five ticks, two requests
        self.assertEqual(K[1:5], acts(done)[1]["keys"])
        self.assertIn("Ticking 4 lines…", self.run_rows(
            ("click", 0, K[1]), ("click", 0.5, K[2]), ("click", 1, K[3]), ("click", 1.5, K[4]), ("tick", 4), ("tick", 9))[-1]["box"])

    def test_a_batch_that_saved_is_one_small_notice_and_no_card(self):
        out = self.run_rows(("click", 0, K[0]), ("click", 0.5, K[1]), ("click", 1, K[2]), ("tick", 3.5),
                            ("reply", 30, {"verb": "todo-done", "zone": "Work", "file": "Todo.md", "keys": K[:3]},
                             {"ok": True, "say": "Saved 3", "op": "x", "state": "completed", "outcome": "saved"}),
                            ("tick", 60))
        sent, replied, later = out[3], out[4], out[5]
        self.assertEqual(K[:3], acts(sent)[0]["keys"])
        self.assertEqual("", replied["box"])                                  # however long it took: no card to close
        self.assertEqual("Saved 3", replied["toast"])
        self.assertEqual(1, replied["opacity"])                               # the small toast, which fades by itself
        self.assertEqual("", later["box"])
        self.assertFalse(later["ticking"])
        self.assertEqual([True, True, True], [later["done"][k] for k in K[:3]])

    def test_a_refused_batch_stays_names_its_lines_and_puts_their_boxes_back(self):
        """The wall check refused it: the card is the rule's sentence, word for
        word, and the lines; nothing of the page's own about why."""
        refused = {"ok": False, "say": WALL, "op": "x", "state": "failed", "outcome": "refused"}
        out = self.run_rows(("click", 0, K[0]), ("click", 0.5, K[5]), ("click", 1, K[1]), ("tick", 3.5),
                            ("click", 4, K[0]),                               # clicked again while its tick commits
                            ("reply", 6, {"verb": "todo-done", "zone": "Work", "file": "Todo.md", "keys": [K[0], K[1]]}, refused),
                            ("tick", 7), ("tick", 60), ("reload", 61))
        sent, again, replied, after, later, rebuilt = out[3], out[4], out[5], out[6], out[7], out[8]
        self.assertEqual([[K[0], K[1]]], [a["keys"] for a in acts(sent)])    # the ticks: one request
        self.assertNotIn(K[5], acts(sent)[0]["keys"])                         # the untick waits for its own
        self.assertFalse(again["done"][K[0]])
        self.assertIn('class="wk bad"', replied["box"])
        text = re.sub(r"<[^>]+>", "|", replied["box"])
        self.assertIn("|" + WALL + "|", text)                                 # word for word, with nothing added to it
        self.assertIn("Line 1 for Acme Corp · Line 2 for Acme Corp", replied["box"])
        self.assertIn('data-wx="0"', replied["box"])
        self.assertEqual((False, False), (replied["done"][K[0]], replied["done"][K[1]]))   # their boxes back
        self.assertEqual("Mark done: Line 2 for Acme Corp", replied["labels"][K[1]])
        self.assertFalse(replied["done"][K[5]])                               # the untick, still queued, keeps its row
        self.assertEqual(["todo-undo"], [a["verb"] for a in acts(after)[1:]])   # and goes; the second click on line 1 was dropped
        self.assertIn(WALL, later["box"])                                     # a failure stays
        self.assertIn(WALL, rebuilt["box"])

    def test_a_second_click_before_it_went_sends_nothing(self):
        out = self.run_rows(("click", 0, K[0]), ("click", 1, K[0]), ("tick", 4), ("tick", 8))
        self.assertEqual(0, out[-1]["posted"])
        self.assertFalse(out[-1]["done"][K[0]])
        self.assertFalse(out[-1]["ticking"])

    def test_a_rebuild_draws_a_queued_tick_as_clicked(self):
        out = self.run_rows(("act", 0, PARK, "Parking Birch Entry…"), ("click", 1, K[2]), ("click", 1.5, K[5]),
                            ("reload", 2), ("tick", 5))
        rebuilt = out[3]
        self.assertTrue(rebuilt["done"][K[2]])                                # drawn from the note: open; from the queue: ticked
        self.assertFalse(rebuilt["done"][K[5]])
        self.assertEqual(1, out[4]["posted"])                                 # the park still runs: they wait

    def test_a_reload_finds_a_batch_in_the_record_with_its_lines(self):
        running = record(OP, verb="todo-done", label="Ticking 2 lines…", keys=[K[0], K[1]], phase="checking")
        refused = dict(running, state="failed", outcome="refused", done=1009.0, say=WALL)
        out = self.run_rows(("ops", 3, reply(running)), ("ops", 10, reply(refused)))
        self.assertEqual((True, True), (out[0]["done"][K[0]], out[0]["done"][K[1]]))
        self.assertIn("Ticking 2 lines…", out[0]["box"])
        self.assertIn(WALL, out[1]["box"])
        self.assertIn("Line 1 for Acme Corp · Line 2 for Acme Corp", out[1]["box"])
        self.assertEqual((False, False), (out[1]["done"][K[0]], out[1]["done"][K[1]]))
        saved = dict(running, state="completed", outcome="saved", done=1009.0, say="Saved 2")
        out = self.run_rows(("ops", 10, reply(saved)))
        self.assertEqual("", out[0]["box"])
        self.assertEqual("Saved 2", out[0]["toast"])

    def test_a_success_card_of_any_verb_fades_and_hovering_holds_it(self):
        parked = {"ok": True, "say": "Birch Entry is parked", "outcome": "saved", "state": "completed"}
        out = self.run_js(("act", 0, PARK, "Parking Birch Entry…"), ("reply", 20, PARK, parked), ("hover", 21, 0),
                          ("tick", 30), ("leave", 31, 0), ("tick", 34), ("tick", 35.5))
        replied, hovered, held, left, still, gone = out[1:]
        self.assertIn('class="wk ok" data-i="0"', replied["box"])
        self.assertIn("Birch Entry is parked", held["box"])                   # past ACTION_TOAST, held by the pointer
        self.assertIn("Birch Entry is parked", still["box"])                  # off it, ACTION_TOAST more
        self.assertEqual("", gone["box"])
        refused = {"ok": False, "say": "Not done. A check refused it.", "outcome": "refused", "state": "failed"}
        out = self.run_js(("act", 0, PARK, "Parking Birch Entry…"), ("reply", 20, PARK, refused), ("tick", 60))
        self.assertIn("Not done. A check refused it.", out[-1]["box"])       # a failure stays until it is closed


# A record as operations.py reads it back for the page. Seconds, as time.time() gives them.
def record(op, state="running", at=999.0, **kw):
    base = {"op": op, "verb": "park", "zone": "Work", "state": state, "phase": "", "at": at, "done": None, "outcome": None,
            "say": None, "label": "Parking Birch Entry…"}
    base.update(kw)
    return base


def reply(*ops, **kw):
    return dict({"ok": True, "durable": True, "verbs": ["park", "wake", "todo-done", "todo-undo", "todo-date", "todo-add"],
                 "ops": list(ops), "lost": "No record of this action was found, so we do not know whether it went through. "
                                           "Run git log -1 in {zone}, then try again: it checks first."}, **kw)


SUCCESS = re.compile(r"\b(saved|parked|ticked|added|renamed|made|committed)\b", re.I)
OP = "a19f3c80b29f3c80"


@unittest.skipUnless(shutil.which("node"), "Node is not installed")
class TestWorkFromTheRecord(NodeCase):
    """The page's memory is a cache: the record in the jobs folder is read through
    {"verb": "operations"} and wins."""

    def no_success_in(self, html):
        text = re.sub(r"<[^>]+>", " ", html)
        for m in SUCCESS.finditer(text):                                      # "not committed" is a refusal; "committed" is a claim
            self.assertRegex(text[:m.start()], r"(?i)\b(not|no)\s+$", text)

    def test_the_page_asks_on_load_and_a_click_carries_its_op(self):
        out = self.run_js(("tick", 0), ("act", 1, PARK, "Parking Birch Entry…"))
        self.assertEqual(1, out[0]["asked"])                                  # on load, once
        sent = out[1]["sent"][0]["act"]
        self.assertRegex(sent["op"], r"^[0-9a-f]{8,32}$")
        self.assertEqual({"verb": "park", "zone": "Work", "file": "Birch Entry/Birch Entry.md"}, {k: v for k, v in sent.items() if k != "op"})
        self.assertIn("Parking Birch Entry…", out[1]["box"])                  # and it renders inside the click, not after the record

    def test_a_reload_with_nothing_remembered_finds_the_action_and_its_phase(self):
        out = self.run_js(("ops", 1, reply(record(OP, phase=""))), ("ops", 4, reply(record(OP, phase="checking"))),
                          ("tick", 5))
        first, second, third = out
        self.assertIn("Parking Birch Entry…", first["box"])
        self.assertIn('class="wspin"', first["box"])
        self.assertIn(">2 s<", first["box"])                                  # since the record began, not since the page did
        self.assertNotIn("wall check", first["box"])                          # no guess at ten seconds: the phase says
        self.assertIn("Committing: the wall check can take a minute.", second["box"])
        self.assertIn('.trow[data-z="Work"] button.tdate', first["hold"])     # and its zone is held
        self.assertTrue(first["ticking"])

    def test_it_asks_again_every_few_seconds_while_something_runs_and_never_otherwise(self):
        out = self.run_js(("tick", 0), ("act", 1, PARK, "Parking Birch Entry…"), ("tick", 2), ("tick", 4.5), ("tick", 5), ("tick", 8),
                          ("reply", 9, PARK, {"ok": True, "say": "Parked", "outcome": "saved", "state": "completed"}),
                          ("tick", 20), ("tick", 40))
        self.assertEqual([1, 1, 1, 2, 2, 3, 3, 3, 3], [o["asked"] for o in out])

    def test_a_result_that_landed_while_the_page_was_away_shows_and_is_dismissable_once(self):
        done = record(OP, state="failed", outcome="refused", done=1000.0,
                      say="Not done. Not committed, so nothing changed: the wall check refused.")
        out = self.run_js(("ops", 5, reply(done)), ("dismiss", 6, 0), ("ops", 9, reply(done)))
        shown, dismissed, again = out
        self.assertIn("Not done. Not committed, so nothing changed: the wall check refused.", shown["box"])
        self.assertIn('class="wk bad"', shown["box"])
        self.assertIn('data-wx="0"', shown["box"])
        self.assertNotIn("wspin", shown["box"])
        self.assertEqual("", dismissed["box"])
        self.assertEqual("", again["box"])                                    # dismissed: the record does not bring it back
        self.no_success_in(shown["box"])

    def test_a_saved_one_that_landed_while_away_is_the_only_one_that_reads_as_a_success(self):
        out = self.run_js(("ops", 5, reply(record(OP, state="completed", outcome="saved", done=1000.0, say="Birch Entry is parked"))))
        self.assertIn('class="wk ok"', out[0]["box"])
        self.assertIn("Birch Entry is parked", out[0]["box"])

    def test_a_reply_that_is_ok_is_not_a_save_unless_its_outcome_says_so(self):
        for outcome in ("refused", "crashed", "unknown", "lost"):
            out = self.run_js(("act", 0, PARK, "Parking Birch Entry…"),
                              ("reply", 30, PARK, {"ok": True, "say": "Not done. A check refused it.", "outcome": outcome, "state": "failed"}))
            self.assertIn('class="wk bad"', out[1]["box"], outcome)
            self.assertNotIn('class="wk ok"', out[1]["box"], outcome)
        out = self.run_js(("act", 0, PARK, "Parking Birch Entry…"),
                          ("reply", 30, PARK, {"ok": True, "say": "Birch Entry is parked", "outcome": "saved", "state": "completed"}))
        self.assertIn('class="wk ok"', out[1]["box"])

    def test_a_join_reply_is_one_toast_and_nothing_is_saved(self):
        join = {"ok": True, "say": "Already parking Birch Entry…", "op": OP, "state": "running"}
        out = self.run_js(("act", 0, PARK, "Parking Birch Entry…"), ("reply", 1, PARK, join), ("ops", 2, reply(record(OP))),
                          ("ops", 6, reply(record(OP, state="failed", outcome="refused", done=1005.0, say="Not done. A check refused it."))))
        joined, listed, ended = out[1:]
        self.assertEqual(1, joined["box"].count("wk"))                        # one toast, not two
        self.assertIn("Already parking Birch Entry…", joined["box"])
        self.assertIn("wspin", joined["box"])
        self.assertNotIn("data-wx", joined["box"])
        self.assertEqual(1, listed["box"].count("wspin"))
        self.assertIn('class="wk bad"', ended["box"])
        self.assertEqual(1, ended["box"].count("wk bad"))
        self.no_success_in(joined["box"].replace("Already parking Birch Entry…", ""))

    def test_a_page_entry_the_record_does_not_know_drops_to_lost_after_a_minute(self):
        out = self.run_js(("act", 0, PARK, "Parking Birch Entry…"), ("ops", 30, reply()), ("ops", 61, reply()))
        self.assertIn("wspin", out[1]["box"])                                 # young enough: the worker may not have written yet
        self.assertIn('class="wk bad"', out[2]["box"])
        self.assertIn("No record of this action was found", out[2]["box"])
        self.assertIn("git log -1 in Work", out[2]["box"])
        self.no_success_in(out[2]["box"])
        self.assertEqual("", self.run_js(("act", 0, PARK, "Parking Birch Entry…"), ("ops", 61, reply()), ("busy", 62, "Work"))[2]["r"])

    def test_an_action_the_record_does_not_keep_is_left_to_the_old_last_resort(self):
        out = self.run_js(("act", 0, ACME, "Making Acme…"), ("ops", 120, reply()), ("tick", 121))
        self.assertIn("wspin", out[1]["box"])                                 # new-project has no record; not lost at a minute
        out = self.run_js(("act", 0, ACME, "Making Acme…"), ("ops", 120, reply()), ("tick", status.ACTION_LOST + 1))
        self.assertIn("No reply after 16 min", out[2]["box"])

    def test_an_unreachable_record_is_said_once(self):
        gone = {"ok": False, "say": "unknown action"}
        out = self.run_js(("tick", 0), ("ops", 1, gone), ("act", 2, PARK, "Parking Birch Entry…"), ("ops", 3, gone), ("tick", 20))
        self.assertEqual(1, out[0]["asked"])
        self.assertIn("Actions are not recoverable here", out[1]["toast"])
        self.assertEqual(out[1]["toasts"], out[3]["toasts"])                  # not said a second time
        self.assertEqual(1, out[4]["asked"])                                  # and it stops asking
        self.assertIn("wspin", out[4]["box"])                                 # the click still shows, as in 0.26.0
        out = self.run_js(("ops", 1, {"ok": True, "durable": False, "verbs": [], "ops": []}))
        self.assertIn("Actions are not recoverable here", out[0]["toast"])

    def test_each_load_asks_once_and_a_rebuild_is_a_load(self):
        """The host rebuilds the page after every request it does, so each
        rebuild asks once more: that is the reattachment, and it cannot loop,
        because a host that is asked neither toasts nor rebuilds for it."""
        out = self.run_js(("ops", 1, reply()), ("reload", 3), ("tick", 3), ("reload", 40), ("tick", 40))
        self.assertEqual([1, 2, 3], [out[0]["asked"], out[2]["asked"], out[4]["asked"]])
        self.assertEqual(0, out[4]["posted"])                                 # and asking sends no request that acts

    def test_a_host_that_does_not_say_it_reads_is_never_asked(self):
        """An app or plugin from 0.26.0 toasts and rebuilds the page for every
        request it passes on, so asking it to read would do that every POLL
        seconds. It is not asked, and the page behaves as it did."""
        out = self.run_js(("tick", 0), ("act", 1, PARK, "Parking Birch Entry…"), ("tick", 2), ("tick", 12), ("tick", 60),
                          ("reload", 61), ("tick", status.ACTION_LOST + 2), reads=False)
        self.assertEqual([0] * 7, [o["asked"] for o in out])                  # nothing ever left the page
        self.assertEqual(0, out[0]["toasts"])
        self.assertEqual(1, out[1]["posted"])                                 # the request itself still went
        self.assertIn("Parking Birch Entry…", out[1]["box"])
        self.assertIn("Committing: the wall check can take a minute.", out[3]["box"])    # the ten-second guess, as before
        self.assertIn("Parking Birch Entry…", out[5]["box"])                  # a reload keeps it from sessionStorage alone
        self.assertNotIn("recoverable", "".join(o["toast"] for o in out))     # and is never told the record is missing
        self.assertIn("No reply after 16 min", out[6]["box"])                 # ACTION_LOST is still the fallback

    def test_a_host_that_says_so_after_the_page_loaded_is_asked_then(self):
        """The Obsidian plugin sets the flag on dom-ready, after this script ran."""
        out = self.run_js(("tick", 0), ("host", 1), ("ops", 2, reply(record(OP, phase="checking"))), reads=False)
        self.assertEqual(0, out[0]["asked"])
        self.assertEqual(1, out[1]["asked"])                                  # the flag's own kick asks
        self.assertIn("Parking Birch Entry…", out[2]["box"])                  # and reattaches, as on the app
        self.assertIn("Committing: the wall check can take a minute.", out[2]["box"])

    def test_a_reload_keeps_what_was_seen(self):
        done = record(OP, state="completed", outcome="saved", done=1000.0, say="Birch Entry is parked")
        out = self.run_js(("ops", 5, reply(done)), ("dismiss", 6, 0), ("reload", 7), ("ops", 8, reply(done)))
        self.assertEqual("", out[3]["box"])


class TestWorkOnThePage(StatusCase):
    def test_the_page_carries_it_after_the_dialogs(self):
        html = self.page()
        self.assertIn('<div id="work" role="status" hidden></div>', html)
        self.assertIn("<script>%s</script>" % status.WORK_JS, html)
        self.assertLess(html.index(status.MANAGE_JS), html.index(status.WORK_JS))   # it wraps the GarrickActed the others set
        self.assertIn("#work{position:fixed", html)
        self.assertIn("#toast{position:fixed;left:50%;bottom:calc(22px + var(--work-h,0px))", html)   # a toast sits above it
        self.assertIn("@media (prefers-reduced-motion:reduce){#work .wspin{animation:none", status.WORK_CSS)

    def test_the_timings(self):
        self.assertEqual(4, status.ACTION_TOAST)
        self.assertEqual(10, status.ACTION_WHY)
        self.assertIn("TOAST=4,WHY=10,LOST=%d," % status.ACTION_LOST, status.WORK_JS)
        self.assertNotIn("@", status.WORK_JS)                                # every constant filled in
        # No reply is given up only after every host's own wait and page_action.py's longest:
        # the lock, then scaffold.py's commit, then the new folder's.
        plugin = (HERE / "obsidian" / "main.js").read_text(encoding="utf-8")
        wait = int(re.search(r"cwd: this\.root\(\), timeout: (\d+) \}", plugin).group(1))
        self.assertLess(wait, status.ACTION_LOST * 1000)
        longest = page_action.LOCK_WAIT + page_action.COMMIT_TIMEOUT + page_action.GIT_TIMEOUT + page_action.COMMIT_TIMEOUT
        self.assertLess(longest, status.ACTION_LOST)

    def test_the_zone_verbs_are_the_ones_page_action_locks(self):
        # back, stack and unstack touch only the interruption stack, never a zone's git.
        # Ask something and the example's links act on no one zone (#175).
        # Stop, how far a copy or a move has got, and a work's own file opened (#189) take no zone's lock either.
        unzoned = {"run", "settings", "check-name", "back", "stack", "unstack", "ask-desktop", "example", "discover",
                   "files-stop", "files-progress", "work-file"}
        self.assertEqual(set(page_action.VERBS) - unzoned, set(status.ZONE_VERBS))
        self.assertIn('ZONED=["todo-done",', status.WORK_JS)

    def test_every_button_that_commits_goes_through_it(self):
        self.assertIn("if(window.GarrickHeld&&GarrickHeld(r))return;", status.JS)                     # Park, Wake
        self.assertIn("if(window.GarrickAct&&GarrickAct(r,x.dataset.say))return;host.postMessage({act:r})", status.JS)
        self.assertIn("if(!(window.GarrickAct&&GarrickAct(q,s))){host.postMessage({act:q});say(s)}", status.JS)   # + Add
        self.assertIn("if(window.GarrickAct&&GarrickAct(q,said))return;host.postMessage({act:q});say(said)}", status.TODO_JS)
        self.assertIn("if(!(window.GarrickTick&&GarrickTick({verb:verb,zone:r.dataset.z,file:r.dataset.f,key:r.dataset.k})))"
                      "{if(held(verb,r))return;send(verb,", status.TODO_JS)          # queued; without WORK_JS, as before
        self.assertIn("else if(!held('todo-date',r))open(r,b)", status.TODO_JS)
        self.assertIn("var busy=window.GarrickBusy&&GarrickBusy(dz);if(busy)", status.TADD_JS)
        self.assertIn("function send(q,said){if(window.GarrickAct&&GarrickAct(q,said))return;", status.MANAGE_JS)
        self.assertEqual(5, status.MANAGE_JS.count("if(busy(d,q.zone))return;"))   # new thread, new project, rename, park, delete


class TestWorkHosts(unittest.TestCase):
    def test_each_host_says_it_can_answer_a_request_that_reads(self):
        swift = (HERE / "app" / "Garrick.swift").read_text(encoding="utf-8")
        self.assertIn("window.GarrickReads=true;", swift)
        self.assertIn("injectionTime: .atDocumentStart", swift)               # before the page's own scripts
        self.assertIn('request["verb"] as? String == "operations"', swift)     # and it neither toasts nor rebuilds for it
        plugin = (HERE / "obsidian" / "main.js").read_text(encoding="utf-8")
        self.assertIn('"dom-ready"', plugin)
        self.assertIn('window.GarrickReads=true;window.GarrickReady&&window.GarrickReady()', plugin)
        self.assertIn('request.verb === "operations"', plugin)

    def test_the_app_hands_every_reply_to_the_page(self):
        swift = (HERE / "app" / "Garrick.swift").read_text(encoding="utf-8")
        act = swift[swift.index("	func act(_ request: [String: Any]) {"):swift.index("	func acted(")]
        self.assertIn('self.acted(request, said ?? ["ok": false, "say": "That did not work."])', act)
        self.assertIn('acted(request, ["ok": false, "say": "Cannot run \\(python)"])', act)
        self.assertNotIn("asyncAfter", act)                                  # no limit of its own on page_action.py

    @unittest.skipUnless(shutil.which("node"), "Node is not installed")
    def test_the_plugin_hands_every_reply_to_the_page(self):
        harness = textwrap.dedent(r"""
            const Module = require("module");
            const [plugin_path] = process.argv.slice(2);
            const replies = JSON.parse(process.env.REPLIES), ran = [];
            const stubs = {
              obsidian: { Plugin: class {}, ItemView: class {}, PluginSettingTab: class {}, Setting: class {}, Notice: class {}, addIcon: () => {} },
              electron: { shell: {}, clipboard: {} },
              child_process: { execFile: (cmd, args, opts, done) => { const [err, out] = replies.shift(); done(err, out); return { stdin: { end() {} } }; },
                               spawn: () => ({}) },
            };
            const load = Module._load;
            Module._load = function (req, ...rest) { return stubs[req] || load.call(this, req, ...rest); };
            const Plugin = require(plugin_path);
            const p = new Plugin();
            p.settings = { workspace: "/ws", python: "/usr/bin/python3", script: __filename, flags: "", hideParked: true };
            p.root = () => "/ws";
            p.rebuild = () => {};
            const view = { toast: (t) => ran.push(["toast", t]), web: { executeJavaScript: (s) => { ran.push(["page", s]); return Promise.resolve(); } } };
            require("fs").writeFileSync(require("path").join(require("path").dirname(__filename), "page_action.py"), "");
            for (let i = 0; i < 3; i++) p.act(view, { verb: "park", zone: "Work", file: "Birch Entry/Birch Entry.md" });
            process.stdout.write(JSON.stringify(ran));
        """)
        replies = [[None, '{"ok": true, "say": "Parked"}'], [{"code": 1}, "Traceback"], [{"killed": True}, ""]]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "harness.js"
            path.write_text(harness)
            done = subprocess.run(["node", str(path), str(HERE / "obsidian" / "main.js")], capture_output=True, text=True, timeout=30,
                                  env=dict(os.environ, REPLIES=json.dumps(replies)))
        self.assertEqual(0, done.returncode, done.stderr)
        ran = json.loads(done.stdout)
        self.assertEqual(["toast", "page"] * 3, [k for k, _ in ran])          # each reply reaches the page, a failed one too
        self.assertEqual("Parked", ran[0][1])
        self.assertEqual("That did not work.", ran[2][1])
        self.assertIn('"ok":false', ran[3][1])
        self.assertIn("fifteen minutes", ran[4][1])


if __name__ == "__main__":
    unittest.main()
