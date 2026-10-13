"""An action that runs (#77): the status page shows a request that commits in a
zone running until its reply comes, holds that zone's buttons meanwhile, and
keeps a slow reply on screen until it is dismissed. WORK_JS is run in Node
against a stand-in for the page, and the hosts are read for what they hand it.

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
# the script again on the same storage, as a rebuilt page does.
HARNESS = textwrap.dedent(r"""
    const vm = require("vm");
    const [js, steps] = JSON.parse(process.argv[1]);
    const store = {}, posted = [], out = [];
    let clock = 1000000, ctx, box, toast, style, interval, chained = [];
    function load() {
      box = { innerHTML: "", hidden: true, offsetHeight: 40, listeners: {}, addEventListener(k, f) { this.listeners[k] = f; },
              // each running request's time, written back into the markup
              querySelectorAll(sel) {
                if (sel !== ".wt") return [];
                return [...this.innerHTML.matchAll(/data-t0="(\d+)"/g)].map((m) => ({ dataset: { t0: m[1] },
                  set textContent(v) { box.innerHTML = box.innerHTML.replace(new RegExp('(data-t0="' + m[1] + '"[^>]*>)[^<]*'), "$1" + v); } }));
              } };
      toast = { textContent: "", style: { opacity: 0 } };
      style = null;
      interval = null;
      const document = {
        getElementById: (id) => id === "work" ? box : id === "toast" ? toast : id === "work-hold" ? style : null,
        createElement: () => ({ textContent: "" }),
        head: { appendChild: (el) => { style = el; } },
        body: { style: { setProperty: () => {} } },
        querySelectorAll: () => [],
      };
      ctx = { JSON, String, Math, document, Date: { now: () => clock },
              sessionStorage: { getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); } },
              setInterval: (f) => { interval = f; return 1; }, clearInterval: () => { interval = null; },
              setTimeout: () => 0, clearTimeout: () => {} };
      ctx.window = ctx;                    // as in a browser, the page's globals are the window's
      ctx.webkit = { messageHandlers: { garrick: { postMessage: (m) => posted.push(m) } } };
      ctx.GarrickActed = (q, o) => chained.push(q.verb);
      vm.createContext(ctx);
      vm.runInContext(js, ctx);
    }
    load();
    for (const [what, at, a, b] of steps) {
      clock = 1000000 + at * 1000;
      let r = null;
      if (what === "act") r = ctx.window.GarrickAct(a, b);
      if (what === "reply") ctx.window.GarrickActed(a, b);
      if (what === "tick" && interval) interval();
      if (what === "reload") load();
      if (what === "dismiss") box.listeners.click({ target: { closest: () => ({ dataset: { wx: String(a) } }) } });
      if (what === "busy") r = ctx.window.GarrickBusy(a);
      out.push({ r, box: box.hidden ? "" : box.innerHTML, toast: toast.textContent, opacity: toast.style.opacity,
                 hold: style ? style.textContent : "", posted: posted.length, ticking: !!interval, chained: chained.slice() });
    }
    process.stdout.write(JSON.stringify(out));
""")

ACME = {"verb": "new-project", "zone": "Work", "name": "Acme", "party": "acme", "thread": "Pricing"}
# The same request as the host hands it back: Swift's JSON does not keep the keys' order.
ACME_BACK = {"thread": "Pricing", "zone": "Work", "party": "acme", "name": "Acme", "verb": "new-project"}
PARK = {"verb": "park", "zone": "Work", "file": "Birch Entry/Birch Entry.md"}
HOME = {"verb": "todo-add", "zone": "Personal", "target": "-", "date": "-", "text": "Book the car service"}


@unittest.skipUnless(shutil.which("node"), "Node is not installed")
class TestWorkUnderNode(unittest.TestCase):
    def run_js(self, *steps):
        done = subprocess.run(["node", "-e", HARNESS, json.dumps([status.WORK_JS, [list(s) for s in steps]])],
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(0, done.returncode, done.stderr)
        return json.loads(done.stdout)

    def test_a_slow_new_project_shows_it_is_working_until_its_reply_and_the_reply_stays(self):
        out = self.run_js(("act", 0, ACME, "Making Acme…"), ("tick", 5), ("tick", 12), ("tick", 75),
                          ("reload", 80), ("reply", 81, ACME_BACK, {"ok": True, "say": "Made Acme, first thread Pricing"}),
                          ("reload", 83), ("dismiss", 200, 0))
        sent, five, twelve, late, reloaded, replied, rebuilt, dismissed = out
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
        self.assertIn('data-wx="0"', replied["box"])                         # and stays until dismissed
        self.assertNotIn("wspin", replied["box"])
        self.assertEqual(0, replied["opacity"])                              # the host's own toast steps aside
        self.assertFalse(replied["ticking"])
        self.assertEqual(["new-project"], replied["chained"])                # the hooks set before it still run
        self.assertIn("Made Acme, first thread Pricing", rebuilt["box"])     # the rebuild after the reply keeps it
        self.assertEqual("", dismissed["box"])

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

    def test_the_zone_is_held_and_the_others_are_not(self):
        out = self.run_js(("act", 0, ACME, "Making Acme…"), ("act", 3, PARK, "Parking Birch Entry…"),
                          ("act", 4, HOME, "Adding to Personal: Book the car service…"),
                          ("act", 5, {"verb": "settings", "launchers": ["note"]}, "Saving…"),
                          ("busy", 6, "Work"), ("busy", 6, "Personal"),
                          ("reply", 40, ACME, {"ok": True, "say": "Made Acme"}), ("busy", 41, "Work"),
                          ("act", 42, PARK, "Parking Birch Entry…"))
        first, again, other, unzoned, work, home, replied, free, after = out
        for sel in ('.trow[data-z="Work"] button.tick', '.trow[data-z="Work"] button.tdate', '.tadd-open[data-zone="Work"]',
                    'button[data-mg^="[\\"Work\\","]', 'button[data-act*="\\"verb\\":\\"park\\""][data-act*="\\"zone\\":\\"Work\\""]',
                    'button[data-act*="\\"verb\\":\\"wake\\""][data-act*="\\"zone\\":\\"Work\\""]'):
            self.assertIn(sel, first["hold"])
        self.assertIn("pointer-events:none", first["hold"])
        self.assertTrue(again["r"])                                          # taken, and refused
        self.assertEqual(1, again["posted"])                                 # nothing sent
        self.assertEqual("Work is still busy: Making Acme…", again["toast"])
        self.assertEqual(2, other["posted"])                                 # another zone goes ahead
        self.assertIn('.trow[data-z="Personal"] button.tick', other["hold"])
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

    def test_a_browser_gets_none_of_it(self):
        done = subprocess.run(["node", "-e", "const vm=require('vm');const c={window:{}};vm.createContext(c);"
                               "vm.runInContext(process.argv[1],c);process.stdout.write(String(typeof c.window.GarrickAct))",
                               status.WORK_JS], capture_output=True, text=True, timeout=30)
        self.assertEqual("undefined", done.stdout, done.stderr)


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
        unzoned = {"run", "settings", "check-name", "back", "stack", "unstack"}
        self.assertEqual(set(page_action.VERBS) - unzoned, set(status.ZONE_VERBS))
        self.assertIn('ZONED=["todo-done",', status.WORK_JS)

    def test_every_button_that_commits_goes_through_it(self):
        self.assertIn("if(window.GarrickHeld&&GarrickHeld(r))return;", status.JS)                     # Park, Wake
        self.assertIn("if(window.GarrickAct&&GarrickAct(r,x.dataset.say))return;host.postMessage({act:r})", status.JS)
        self.assertIn("if(!(window.GarrickAct&&GarrickAct(q,s))){host.postMessage({act:q});say(s)}", status.JS)   # + Add
        self.assertIn("if(window.GarrickAct&&GarrickAct(q,said))return;host.postMessage({act:q});say(said)}", status.TODO_JS)
        self.assertIn("held('todo-done',r)", status.TODO_JS)
        self.assertIn("else if(!held('todo-date',r))open(r,b)", status.TODO_JS)
        self.assertIn("var busy=window.GarrickBusy&&GarrickBusy(dz);if(busy)", status.TADD_JS)
        self.assertIn("function send(q,said){if(window.GarrickAct&&GarrickAct(q,said))return;", status.MANAGE_JS)
        self.assertEqual(5, status.MANAGE_JS.count("if(busy(d,q.zone))return;"))   # new thread, new project, rename, park, delete


class TestWorkHosts(unittest.TestCase):
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
