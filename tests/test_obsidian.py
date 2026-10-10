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


if __name__ == "__main__":
    unittest.main()
