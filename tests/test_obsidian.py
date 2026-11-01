"""The status page's Obsidian plugin, extras/status/obsidian/, read from Python,
and run under Node with Obsidian and Electron stood in for, where Node is
installed. Nothing here opens Obsidian; docs/extras/status-page.md has the
check to make by hand.

    python3 -m unittest discover -s tests

The plugin gives the page the bridge Garrick.app gives it, so every kind of
message the page posts must have an answer in the plugin.
"""

from __future__ import annotations

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

from fixtures import thread_note, write  # noqa: E402
from test_page_action import ActionCase  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
PLUGIN = REPO / "extras" / "status" / "obsidian"
STATUS = REPO / "extras" / "status" / "status.py"
MAIN = (PLUGIN / "main.js").read_text(encoding="utf-8")
# The first of the launchers a Codex app may carry, as main.js lists them.
CODEX_CLI_REL = json.loads(re.search(r"const CODEX_CLI = (\[[^\]]*\]);", MAIN).group(1))[0]


def kinds_posted() -> set:
    """Every top-level key the page sends through window.webkit.messageHandlers.garrick."""
    src = STATUS.read_text(encoding="utf-8")
    found = set(re.findall(r"postMessage\(\{(\w+):", src))
    # An Open in … button builds its message first, and adds the keys an older app reads.
    found.update(re.findall(r"\bm\.(\w+)=m\.\w+", src))
    return found


class TestBridge(unittest.TestCase):
    def test_every_message_the_page_posts_is_answered(self):
        posted = kinds_posted()
        self.assertTrue({"act", "copy", "launch", "rebuild", "menu", "app", "cmux"} <= posted, posted)
        kinds = set(json.loads(re.search(r"const KINDS = (\[[^\]]*\]);", MAIN).group(1).replace("'", '"')))
        self.assertEqual(posted, kinds, "status.py posts a kind of message main.js's KINDS does not list, or the reverse")
        handler = MAIN[MAIN.index("\thandle(view, body) {"):MAIN.index("\t// A folder of this workspace")]
        for kind in kinds:
            self.assertIn("body.%s" % kind, handler, kind)

    def test_the_bridge_is_the_apps(self):
        bridge = re.search(r"const BRIDGE = `(.*?)`;", MAIN, re.S).group(1)
        self.assertIn("window.webkit={messageHandlers:{garrick:{postMessage:", bridge)
        page = STATUS.read_text(encoding="utf-8")
        self.assertIn("window.webkit&&window.webkit.messageHandlers&&window.webkit.messageHandlers.garrick", page)

    def test_the_mark_is_garricks(self):
        svg = (REPO / "docs" / "assets" / "garrick-mark-favicon.svg").read_text(encoding="utf-8")
        walls = re.search(r'class="i" d="([^"]+)"', svg).group(1)
        open_ = re.search(r'class="a" d="([^"]+)"', svg).group(1)
        self.assertIn('const MARK_WALLS = "%s";' % walls, MAIN)
        self.assertIn('const MARK_OPEN = "%s";' % open_, MAIN)

    def test_the_manifest(self):
        m = json.loads((PLUGIN / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual("garrick-status", m["id"])
        self.assertTrue(m["isDesktopOnly"])
        for k in ("name", "version", "minAppVersion", "description", "author"):
            self.assertTrue(m.get(k), k)

    def test_no_root_two_levels_up(self):
        self.assertNotIn('"..", ".."', MAIN)
        self.assertIn("isWorkspace(d)", MAIN)


# Stands in for Obsidian and Electron, loads the plugin, and drives it: finds
# the workspace from a vault inside it, writes the page's copy with the
# bridge, runs the bridge as the page would, and answers what it posts.
HARNESS = textwrap.dedent(r"""
    const Module = require("module");
    const vm = require("vm");
    const fs = require("fs");
    const [plugin_path, vault, out_path] = process.argv.slice(2);
    const seen = { clipboard: [], external: [], notices: [], rebuilds: 0, icon: "" };
    class Notice { constructor(t) { seen.notices.push(t); } hide() {} }
    const stubs = {
      obsidian: { Plugin: class { async loadData() { return null; } registerView() {} addRibbonIcon() {} addCommand() {}
                                   addSettingTab() {} registerEvent() {} registerInterval() {} },
                  ItemView: class {}, PluginSettingTab: class {}, Setting: class {}, Notice,
                  addIcon: (name, svg) => { seen.icon = svg; } },
      electron: { shell: { openPath: (p) => seen.external.push(p), openExternal: (u) => seen.external.push(u) },
                  clipboard: { writeText: (t) => seen.clipboard.push(t) } },
    };
    const load = Module._load;
    Module._load = function (req, ...rest) { return stubs[req] || load.call(this, req, ...rest); };
    const Plugin = require(plugin_path);
    (async () => {
    const files = JSON.parse(process.env.FILES);
    global.window = { setInterval: () => 0 };
    const p = new Plugin();
    p.app = { workspace: { onLayoutReady: () => {} }, metadataCache: { on: () => ({}) }, vault: { on: () => ({}) } };
    await p.onload();
    p.settings = { workspace: "", python: process.env.PYTHON, script: process.env.SCRIPT, flags: "", hideParked: true };
    p.nonce = "garrick-test:";             // onload chose a random one
    p.app = { vault: { adapter: { getBasePath: () => vault }, getName: () => "Work",
                       getMarkdownFiles: () => files.map((f) => ({ path: f[0], basename: f[0].split("/").pop().replace(/\.md$/, "") })) },
              metadataCache: { getFileCache: (f) => ({ frontmatter: Object.fromEntries(files.filter((x) => x[0] === f.path).map((x) => ["status", x[1]])) }) } };
    p.rebuild = () => { seen.rebuilds += 1; return Promise.resolve(); };
    const result = { root: p.root(), parked: p.parkedFolders() };
    const copy = p.copyPage();
    const html = fs.readFileSync(copy, "utf8");
    result.copy = copy;
    result.head = html.slice(0, 400);
    // The page's world: run the bridge, then post what the page's buttons post.
    const logged = [];
    const listeners = {};
    const win = { addEventListener: (k, f) => { listeners[k] = f; } };
    const ctx = vm.createContext({ window: win, console: { log: (s) => logged.push(s) }, JSON });
    vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], ctx);
    const view = new Plugin.StatusView(null, p);       // no web view: its toast is a Notice
    const post = (m) => vm.runInContext("window.webkit.messageHandlers.garrick.postMessage(" + JSON.stringify(m) + ")", ctx);
    post({ copy: "open Pricing" });
    post({ menu: null });
    post({ act: JSON.parse(process.env.ACT) });
    // a link the page did not handle itself
    listeners.click({ defaultPrevented: false, button: 0, preventDefault() {}, target: { closest: () => ({ getAttribute: () => "https://example.com/x", href: "https://example.com/x" }) } });
    logged.push("an ordinary line the page logs");
    logged.forEach((line) => view.heard(line));
    result.logged = logged;
    const started = Date.now();                 // page_action.py answers in its own time
    const wait = setInterval(() => {
      if (!seen.rebuilds && Date.now() - started < 30000) return;
      clearInterval(wait);
      result.seen = seen;
      fs.writeFileSync(out_path, JSON.stringify(result));
    }, 100);
    })().catch((e) => { console.error(e); process.exit(1); });
""")


@unittest.skipUnless(shutil.which("node"), "Node is not installed")
class TestUnderNode(ActionCase):
    def test_the_plugin_answers_the_page(self):
        write(self.root / "System" / "generated" / "status.html",
              "<!doctype html><html><head><meta charset=utf-8><title>Garrick</title></head><body><div id=toast></div></body></html>")
        write(self.work / "Birch Entry" / "Threads" / "Market Sizing" / "Market Sizing.md",
              thread_note("Birch Entry", "Market Sizing", status="parked"))
        files = [["Acme Review/Acme Review.md", "active"], ["Acme Review/Threads/Pricing/Pricing.md", "active"],
                 ["Acme Review/Threads/Launch/Launch.md", "parked"],
                 ["Birch Entry/Birch Entry.md", "active"], ["Birch Entry/Threads/Market Sizing/Market Sizing.md", "parked"],
                 ["Cedar/Cedar.md", "parked"], ["Notes/Loose.md", "parked"]]
        key = self.key("Invoice")
        with tempfile.TemporaryDirectory() as tmp:
            harness, out = Path(tmp) / "harness.js", Path(tmp) / "out.json"
            harness.write_text(HARNESS)
            env = dict(os.environ, FILES=json.dumps(files), PYTHON=sys.executable, SCRIPT=str(STATUS),
                       ACT=json.dumps({"verb": "todo-done", "zone": "Work", "file": "Todo.md", "key": key}))
            done = subprocess.run(["node", str(harness), str(PLUGIN / "main.js"), str(self.work), str(out)],
                                  capture_output=True, text=True, env=env, timeout=60)
            self.assertEqual(0, done.returncode, done.stderr)
            result = json.loads(out.read_text())
        self.assertEqual(str(self.root), result["root"])                     # found from the vault, at any depth
        self.assertEqual(str(self.root / "System" / "generated" / "status-obsidian.html"), result["copy"])
        self.assertRegex(result["head"], r"<head><script>\(function\(\)\{var tag=\"garrick-test:\";")
        self.assertEqual(["Acme Review/Threads/Launch", "Birch Entry", "Birch Entry/Threads/Market Sizing", "Cedar"],
                         result["parked"])
        seen = result["seen"]
        self.assertEqual(["open Pricing"], seen["clipboard"])
        self.assertEqual(["Done: Acme Corp: Invoice for September"], seen["notices"])  # page_action.py ran, and said so
        self.assertEqual(1, seen["rebuilds"])
        self.assertEqual(["https://example.com/x"], seen["external"])
        self.assertIn("fill:#3D73E0", seen["icon"])
        self.assertIn("- [x] Acme Corp: Invoice for September", (self.work / "Todo.md").read_text())


# The plugin's launch() alone, with child_process stood in for: what it would
# run for each message, and nothing run at all.
ROUTES = textwrap.dedent(r"""
    const Module = require("module");
    const fs = require("fs");
    const [plugin_path, root, out_path] = process.argv.slice(2);
    const ran = [];
    const stubs = {
      obsidian: { Plugin: class {}, ItemView: class {}, PluginSettingTab: class {}, Setting: class {}, Notice: class {}, addIcon: () => {} },
      electron: { shell: {}, clipboard: { writeText: (t) => ran.push(["clipboard", t]) } },
      child_process: {
        execFile: (cmd, args, opts, done) => {
          const child = { stdin: { end: (s) => ran.push(["stdin", JSON.parse(s)]) } };
          ran.push(["exec", cmd, args]);
          return child;
        },
        spawn: (cmd, args) => { ran.push(["spawn", cmd, args]); return { on() {}, unref() {} }; },
      },
    };
    const load = Module._load;
    Module._load = function (req, ...rest) { return stubs[req] || load.call(this, req, ...rest); };
    const Plugin = require(plugin_path);
    const p = new Plugin();
    p.settings = { workspace: root, python: "/usr/bin/python3", script: "", flags: "", hideParked: true };
    p.rebuild = () => Promise.resolve();
    const view = { toast: (t) => ran.push(["toast", t]) };
    const out = {};
    for (const [name, body] of JSON.parse(process.env.MESSAGES)) {
      ran.length = 0;
      p.handle(view, body);
      out[name] = ran.slice();
    }
    fs.writeFileSync(out_path, JSON.stringify(out));
""")


@unittest.skipUnless(shutil.which("node"), "Node is not installed")
class TestDeskRoute(ActionCase):
    def test_cmux_goes_through_the_desk_when_the_message_says_it_is_ready(self):
        pricing = str(self.work / "Acme Review" / "Threads" / "Pricing")
        messages = [["inbox", {"launch": "cmux", "folder": str(self.root), "phrase": "process the inbox", "dk": 1}],
                    ["thread", {"launch": "cmux", "folder": pricing, "phrase": "open Pricing", "dk": 1}],
                    ["plain", {"launch": "cmux", "folder": pricing, "phrase": "open Pricing"}],
                    ["claude", {"launch": "claude", "folder": str(self.root), "phrase": "process the inbox", "dk": 1}],
                    ["outside", {"launch": "cmux", "folder": str(self.root.parent), "phrase": "x", "dk": 1}]]
        write(self.root / "System" / "status" / "page_action.py", "")           # only looked for, never run
        with tempfile.TemporaryDirectory() as tmp:
            harness, out = Path(tmp) / "routes.js", Path(tmp) / "out.json"
            harness.write_text(ROUTES)
            done = subprocess.run(["node", str(harness), str(PLUGIN / "main.js"), str(self.root), str(out)],
                                  capture_output=True, text=True, env=dict(os.environ, MESSAGES=json.dumps(messages)), timeout=60)
            self.assertEqual(0, done.returncode, done.stderr)
            ran = json.loads(out.read_text())
        self.assertEqual(["stdin", {"verb": "open", "folder": str(self.root), "prompt": "process the inbox"}], ran["inbox"][-1])
        self.assertEqual(["stdin", {"verb": "open", "folder": pricing, "prompt": "open Pricing"}], ran["thread"][-1])
        for name in ("inbox", "thread"):
            self.assertNotIn("clipboard", [r[0] for r in ran[name]])             # the tab starts on it: nothing to paste
            self.assertFalse([r for r in ran[name] if r[0] == "exec" and r[1] == "open"])
        # A plain cmux looks the app up first, as Garrick.swift does, and copies
        # nothing until it has opened; this stub never answers, so neither follows here.
        self.assertEqual([["exec", "mdfind", ["kMDItemCFBundleIdentifier == 'com.cmuxterm.app'"]]], ran["plain"])
        self.assertEqual([["exec", "mdfind", ["kMDItemCFBundleIdentifier == 'com.anthropic.claudefordesktop'"]]],
                         ran["claude"])                                         # Claude is looked up, then asked if it is running
        self.assertEqual("toast", ran["outside"][0][0])                          # not in the workspace: nothing runs
        self.assertEqual(1, len(ran["outside"]))


# The plugin's launch() with every child process answered, so a whole route
# runs: what it ran, what it copied and what it said, in order. ANSWERS is a
# list of {match, out, err, append}: the first whose `match` is in the command
# line answers it, and `append` writes a line to a file first, which is how
# Claude's log gets its window-is-up mark part way through a wait.
LAUNCHES = textwrap.dedent(r"""
    const Module = require("module");
    const fs = require("fs");
    const [plugin_path, root, out_path] = process.argv.slice(2);
    const ran = [];
    const answers = JSON.parse(process.env.ANSWERS || "[]");
    function reply(cmd, args) {
      const line = cmd + " " + (args || []).join(" ");
      return answers.find((a) => line.includes(a.match)) || {};
    }
    const stubs = {
      obsidian: { Plugin: class {}, ItemView: class {}, PluginSettingTab: class {}, Setting: class {}, Notice: class {}, addIcon: () => {} },
      electron: { shell: {}, clipboard: { writeText: (t) => ran.push(["clipboard", t]) } },
      child_process: {
        execFile: (cmd, args, opts, done) => {
          if (typeof opts === "function") { done = opts; opts = {}; }
          ran.push(["exec", cmd, args]);
          const a = reply(cmd, args);
          if (a.append) fs.appendFileSync(a.append[0], a.append[1]);
          if (done) setTimeout(() => done(a.err ? new Error(a.err) : null, a.out || ""), 0);
          return { stdin: { end: (s) => ran.push(["stdin", JSON.parse(s)]) } };
        },
        spawn: (cmd, args) => {
          ran.push(["spawn", cmd, args]);
          const a = reply(cmd, args);
          return { on(ev, cb) { if (ev === (a.err ? "error" : "spawn")) setTimeout(cb, 0); }, unref() {} };
        },
      },
    };
    const load = Module._load;
    Module._load = function (req, ...rest) { return stubs[req] || load.call(this, req, ...rest); };
    const Plugin = require(plugin_path);
    const p = new Plugin();
    p.settings = { workspace: root, python: "/usr/bin/python3", script: "", flags: "", hideParked: true };
    p.rebuild = () => { ran.push(["rebuild"]); return Promise.resolve(); };
    p.claudeLogPath = () => process.env.CLAUDE_LOG;
    if (process.env.NO_APP) p.appPath = (bundle, names, done) => done(null);   // nothing installed anywhere
    p.waitTimes = () => ({ poll: 20, ceiling: 300, settle: 10, fallback: 60 });
    const view = { toast: (t) => ran.push(["toast", t]) };
    (async () => {
      const out = {};
      for (const [name, body] of JSON.parse(process.env.MESSAGES)) {
        ran.length = 0;
        p.handle(view, body);
        await (p.launching || Promise.resolve());
        out[name] = ran.slice();
      }
      fs.writeFileSync(out_path, JSON.stringify(out));
    })();
""")


@unittest.skipUnless(shutil.which("node"), "Node is not installed")
class TestWhatALaunchSays(ActionCase):
    """Issue #104: a cold Claude is started and waited for, the clipboard is
    never replaced without the user being told in the same breath, and every
    launcher says what it achieved. Garrick.app says the same words; the
    sentences are held against each other in tests/test_status_more.py."""

    def fake_app(self, name, cli=None):
        """An app bundle of this test's own, so what the plugin finds does not
        depend on what this Mac has installed."""
        app = Path(self._tmp.name) / "Applications" / (name + ".app")
        (app / "Contents").mkdir(parents=True, exist_ok=True)
        if cli:
            (app / cli).parent.mkdir(parents=True, exist_ok=True)
            (app / cli).write_text("#!/bin/sh\n")
            (app / cli).chmod(0o755)
        return str(app)

    def run_routes(self, messages, answers, log=None, no_app=False):
        with tempfile.TemporaryDirectory() as tmp:
            harness, out = Path(tmp) / "launches.js", Path(tmp) / "out.json"
            harness.write_text(LAUNCHES)
            env = dict(os.environ, MESSAGES=json.dumps(messages), ANSWERS=json.dumps(answers),
                       CLAUDE_LOG=str(log if log is not None else Path(tmp) / "no-such.log"))
            if no_app:
                env["NO_APP"] = "1"
            done = subprocess.run(["node", str(harness), str(PLUGIN / "main.js"), str(self.root), str(out)],
                                  capture_output=True, text=True, env=env, timeout=120)
            self.assertEqual(0, done.returncode, done.stderr)
            return json.loads(out.read_text())

    def pricing(self):
        return str(self.work / "Acme Review" / "Threads" / "Pricing")

    def claude_message(self):
        return {"launch": "claude", "folder": self.pricing(), "phrase": "open Pricing"}

    OPENED = "Opened Claude in Pricing with “open Pricing” typed in. Press Enter to send it."

    def found(self, name="Claude", cli=None):
        return {"match": "mdfind", "out": self.fake_app(name, cli) + "\n"}

    def test_a_running_claude_gets_the_link_at_once(self):
        claude = self.found()
        ran = self.run_routes([["warm", self.claude_message()]],
                              [claude, {"match": "pgrep", "out": "4213\n"}])["warm"]
        self.assertEqual(["exec", "mdfind", ["kMDItemCFBundleIdentifier == 'com.anthropic.claudefordesktop'"]], ran[0])
        # Asked by its own executable, so an app called "Usage for Claude" is not taken for Claude.
        self.assertEqual(["exec", "pgrep", ["-f", claude["out"].strip() + "/Contents/MacOS/"]], ran[1])
        self.assertEqual("open", ran[2][1])                 # straight to the link: nothing started, nothing waited for
        self.assertIn("q=open%20Pricing", ran[2][2][0])
        self.assertEqual(["toast", self.OPENED], ran[3])
        self.assertEqual(4, len(ran))
        self.assertNotIn("clipboard", [r[0] for r in ran])  # the phrase is in the session, not on the clipboard

    def test_a_cold_claude_is_started_and_the_link_waits_for_its_window(self):
        log = Path(self._tmp.name) / "claude-main.log"
        log.write_text("2026-10-14 16:40:12 [info] starting\n")
        answers = [self.found(), {"match": "pgrep", "out": ""},      # nothing running
                   # starting it writes the line its window-is-up mark sits on
                   {"match": "open -b com.anthropic",
                    "append": [str(log), "[info] mainView backgroundThrottling restored (boot: done)\n"]}]
        ran = self.run_routes([["cold", self.claude_message()]], answers, log=log)["cold"]
        said = [r for r in ran if r[0] == "toast"]
        self.assertEqual(["toast", "Starting Claude, then opening Pricing. This takes a few seconds."], said[0])
        self.assertEqual(["exec", "open", ["-b", "com.anthropic.claudefordesktop"]], ran[3])
        link = [r for r in ran if r[0] == "exec" and r[1] == "open" and r[2][0].startswith("claude://")]
        self.assertEqual(1, len(link))
        self.assertIn("q=open%20Pricing", link[0][2][0])
        self.assertLess(ran.index(said[0]), ran.index(link[0]))       # it said so before the gap, not after
        self.assertEqual(["toast", self.OPENED], said[-1])

    def test_a_window_that_never_reports_still_gets_the_link_and_says_so(self):
        log = Path(self._tmp.name) / "silent.log"
        log.write_text("[info] starting\n")
        ran = self.run_routes([["late", self.claude_message()]],
                              [self.found(), {"match": "pgrep", "out": ""}], log=log)["late"]
        self.assertTrue([r for r in ran if r[0] == "exec" and r[1] == "open" and r[2][0].startswith("claude://")])
        self.assertEqual(["toast", "Claude did not say its window was ready within forty seconds. Opened Pricing "
                                   "anyway; if the session came up empty, the phrase that resumes it is "
                                   "“open Pricing”."],
                         [r for r in ran if r[0] == "toast"][-1])
        self.assertNotIn("clipboard", [r[0] for r in ran])           # nothing replaced: the phrase is in the message

    def test_a_log_that_cannot_be_read_falls_back_to_the_fixed_delay(self):
        ran = self.run_routes([["nolog", self.claude_message()]],
                              [self.found(), {"match": "pgrep", "out": ""}])["nolog"]   # CLAUDE_LOG is not there
        self.assertTrue([r for r in ran if r[0] == "exec" and r[1] == "open" and r[2][0].startswith("claude://")])
        self.assertEqual(["toast", self.OPENED], [r for r in ran if r[0] == "toast"][-1])

    def test_claude_not_installed_rebuilds_the_page_instead_of_opening(self):
        ran = self.run_routes([["gone", self.claude_message()]], [], no_app=True)["gone"]
        self.assertEqual(["toast", "Claude is not installed here any more. Rebuilding the page without it."], ran[0])
        self.assertEqual(["rebuild"], ran[1])
        self.assertFalse([r for r in ran if r[0] == "exec" and r[1] == "open"])

    def test_codex_and_cmux_copy_only_once_they_have_opened_and_say_so(self):
        folder = self.pricing()
        messages = [["codex", {"launch": "codex", "folder": folder, "phrase": "open Pricing"}],
                    ["cmux", {"launch": "cmux", "folder": folder, "phrase": "open Pricing"}],
                    ["finder", {"launch": "finder", "folder": folder, "phrase": "open Pricing"}]]
        ran = self.run_routes(messages, [self.found("Codex", cli=CODEX_CLI_REL)])
        codex = ran["codex"]
        self.assertEqual("spawn", codex[1][0])
        self.assertEqual(["clipboard", "open Pricing"], codex[2])    # after it started, never before
        self.assertEqual(["toast", "Opened Codex in Pricing. The clipboard now holds “open Pricing”; "
                                   "paste it to resume."], codex[3])
        cmux = ran["cmux"]
        self.assertEqual(["exec", "open", ["-b", "com.cmuxterm.app", folder]], cmux[1])
        self.assertEqual(["clipboard", "open Pricing"], cmux[2])
        self.assertEqual(["toast", "Opened cmux in Pricing. The clipboard now holds “open Pricing”; "
                                   "paste it to resume."], cmux[3])
        finder = ran["finder"]
        self.assertEqual(["exec", "open", ["-R", folder]], finder[0])
        self.assertEqual(["toast", "Showed Pricing in Finder. Nothing was copied; the phrase that resumes it is "
                                   "“open Pricing”."], finder[1])
        self.assertNotIn("clipboard", [r[0] for r in finder])        # Finder takes neither: nothing is replaced

    def test_a_launch_never_replaces_the_clipboard_twice(self):
        # The page sends the phrase as `copy` as well, for a host older than this
        # one. Here the launcher owns the clipboard, so only the launcher copies.
        folder = self.pricing()
        ran = self.run_routes([["both", {"launch": "cmux", "folder": folder, "phrase": "open Pricing",
                                         "cmux": folder, "copy": "open Pricing"}]],
                              [self.found("cmux")])["both"]
        self.assertEqual(1, len([r for r in ran if r[0] == "clipboard"]))
        self.assertEqual(["exec", "mdfind", ["kMDItemCFBundleIdentifier == 'com.cmuxterm.app'"]], ran[0])

    def test_a_failure_names_the_phrase_and_leaves_the_clipboard_alone(self):
        folder = self.pricing()
        messages = [["codex", {"launch": "codex", "folder": folder, "phrase": "open Pricing"}],
                    ["cmux", {"launch": "cmux", "folder": folder, "phrase": "open Pricing"}]]
        answers = [self.found("Codex", cli=CODEX_CLI_REL),
                   {"match": "codex app", "err": "no such thing"},
                   {"match": "open -b com.cmuxterm", "err": "cannot open"}]
        ran = self.run_routes(messages, answers)
        self.assertEqual(["toast", "Codex did not open Pricing. The phrase that resumes it is "
                                   "“open Pricing”."],
                         [r for r in ran["codex"] if r[0] == "toast"][-1])
        self.assertEqual(["toast", "cmux did not open Pricing. The phrase that resumes it is "
                                   "“open Pricing”."],
                         [r for r in ran["cmux"] if r[0] == "toast"][-1])
        for name in ("codex", "cmux"):
            self.assertNotIn("clipboard", [r[0] for r in ran[name]], name)


# The plugin's follow() alone, with Obsidian and Electron's shell stood in for:
# what a link on the page would open, and how.
FOLLOW = textwrap.dedent(r"""
    const Module = require("module");
    const fs = require("fs");
    const [plugin_path, root, out_path] = process.argv.slice(2);
    const ran = [];
    const stubs = {
      obsidian: { Plugin: class {}, ItemView: class {}, PluginSettingTab: class {}, Setting: class {},
                  Notice: class { constructor(t) { ran.push(["notice", t]); } }, addIcon: () => {} },
      electron: { shell: { openPath: (p) => ran.push(["openPath", p]), showItemInFolder: (p) => ran.push(["finder", p]),
                           openExternal: (u) => ran.push(["web", u]) }, clipboard: {} },
    };
    const load = Module._load;
    Module._load = function (req, ...rest) { return stubs[req] || load.call(this, req, ...rest); };
    const Plugin = require(plugin_path);
    const p = new Plugin();
    p.settings = { workspace: root, python: "/usr/bin/python3", script: "", flags: "", hideParked: true };
    p.app = { vault: { getName: () => "Workspace", adapter: { getBasePath: () => root },
                       getAbstractFileByPath: (rel) => rel.endsWith(".md") ? {} : null },
              workspace: { openLinkText: (rel) => ran.push(["obsidian", rel]) } };
    const out = {};
    for (const [name, url] of JSON.parse(process.env.LINKS)) {
      ran.length = 0;
      p.last = null;
      p.follow(url);
      out[name] = ran.slice();
    }
    fs.writeFileSync(out_path, JSON.stringify(out));
""")


@unittest.skipUnless(shutil.which("node"), "Node is not installed")
class TestFollowAsTheAppDoes(ActionCase):
    """#318: in Obsidian's tab a link on the page follows the app's rules: a
    file of the workspace only, no symlink anywhere below its folder, a file
    that could run something shown in Finder, and the web, http and https only."""

    def test_a_link_opens_only_what_the_app_would(self):
        base = Path(self._tmp.name).resolve()
        outside = base / "Elsewhere"
        write(outside / "secret.md", "x\n")
        acme = self.work / "Acme Review"
        write(acme / "data.json", "{}\n")
        write(acme / "run.command", "echo hi\n")
        write(acme / "tool.bin", "x\n")
        (acme / "tool.bin").chmod(0o755)
        (acme / "alias.txt").write_bytes(b"book\x00\x00\x00\x00mark\x00\x00\x00\x00rest")
        os.symlink(str(outside / "secret.md"), str(acme / "Linked.md"))
        os.symlink(str(acme), str(self.work / "Shortcut"))
        jobs = base / "jobs"
        write(jobs / "brief.log", "ran\n")
        links = [["note", (acme / "Acme Review.md").as_uri()], ["json", (acme / "data.json").as_uri()],
                 ["folder", (self.work / "Inbox").as_uri()], ["command", (acme / "run.command").as_uri()],
                 ["executable", (acme / "tool.bin").as_uri()], ["alias", (acme / "alias.txt").as_uri()],
                 ["outside", (outside / "secret.md").as_uri()], ["linked", (acme / "Linked.md").as_uri()],
                 ["through", (self.work / "Shortcut" / "Acme Review.md").as_uri()],
                 ["climb", (self.work / "Acme Review").as_uri() + "/../../../Elsewhere/secret.md"],
                 ["log", (jobs / "brief.log").as_uri()], ["web", "https://example.com/a"],
                 ["app", "file:///System/Applications/Calculator.app"], ["script", "javascript:alert(1)"],
                 ["mail", "mailto:a@example.com"]]
        with tempfile.TemporaryDirectory() as tmp:
            harness, out = Path(tmp) / "follow.js", Path(tmp) / "out.json"
            harness.write_text(FOLLOW)
            done = subprocess.run(["node", str(harness), str(PLUGIN / "main.js"), str(self.root), str(out)], capture_output=True,
                                  text=True, env=dict(os.environ, LINKS=json.dumps(links), GARRICK_JOBS_DIR=str(jobs)), timeout=60)
            self.assertEqual(0, done.returncode, done.stderr)
            ran = json.loads(out.read_text())
        rel = lambda p: p.relative_to(self.root).as_posix()
        self.assertEqual([["obsidian", rel(acme / "Acme Review.md")]], ran["note"])           # a note of the vault, here
        self.assertEqual([["openPath", str(acme / "data.json")]], ran["json"])
        self.assertEqual([["openPath", str(self.work / "Inbox")]], ran["folder"])
        for name, path in (("command", acme / "run.command"), ("executable", acme / "tool.bin"), ("alias", acme / "alias.txt")):
            self.assertEqual("finder", ran[name][-1][0], name)                                     # shown, never run
            self.assertEqual(str(path), ran[name][-1][1], name)
        for name in ("outside", "linked", "through", "climb", "app"):
            self.assertEqual([["notice", "That link leads outside this workspace, so nothing was opened."]], ran[name], name)
        self.assertEqual([["openPath", str(jobs / "brief.log")]], ran["log"])
        self.assertEqual([["web", "https://example.com/a"]], ran["web"])
        self.assertEqual([], ran["script"])
        self.assertEqual([], ran["mail"])


if __name__ == "__main__":
    unittest.main()
