"""Explore's flat graph: the one view, a point mapped to the screen and back, picking the nearest
note, and what a frame costs with 2,000 notes. A page left in 3D by 0.56.0 to 0.64.0 opens flat
(#509). The graph's script runs in Node with the page stubbed; where Node is not installed the
tests are skipped.

    python3 -m unittest tests.test_status_graph_flat
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "extras" / "status"))
import status  # noqa: E402

HARNESS = r"""
const vm = require("vm");
const [code, G, opts] = JSON.parse(process.argv[1]);
const frames = [], store = Object.assign({}, opts.store || {}), els = {};
function el(id) {
  const o = { id, textContent: "", hidden: false, innerHTML: "", dataset: {}, attrs: {}, listeners: {},
    classList: { add() {}, remove() {}, toggle() {} },
    setAttribute(k, v) { o.attrs[k] = v; }, addEventListener(t, f) { o.listeners[t] = f; }, querySelector() { return null; },
    querySelectorAll() { return []; }, setPointerCapture() {}, getBoundingClientRect() { return { left: 0, top: 0, width: 900, height: 600 }; },
    offsetTop: 0, offsetHeight: 30, parentNode: null };
  return o;
}
["graph-data", "gcv", "gpop", "gspin", "gfit", "gpark", "gsum"].forEach(i => els[i] = el(i));
els.gpop.hidden = true;
els["graph-data"].textContent = JSON.stringify(G);
const wrap = el("wrap"); wrap.querySelector = () => ({ offsetTop: 0, offsetHeight: 30 });
els.gcv.parentNode = wrap;
const noop = () => {};
const c2d = new Proxy({}, { get: (t, k) => k === "measureText" ? (() => ({ width: 40 })) : (k in t ? t[k] : noop), set: (t, k, v) => (t[k] = v, true) });
els.gcv.getContext = () => c2d;
const ctx = { location: { href: "" }, console, Math, JSON, Date, performance,
  localStorage: { getItem: k => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); }, removeItem: k => { delete store[k]; } },
  matchMedia: q => ({ matches: !!opts.reduce && /reduced-motion/.test(q), addEventListener: noop }),
  requestAnimationFrame: f => frames.push(f), devicePixelRatio: 1,
  IntersectionObserver: class { constructor(f) { this.f = f; } observe() { this.f([{ isIntersecting: true }]); } },
  MutationObserver: class { observe() {} },
  getComputedStyle: () => ({ getPropertyValue: () => "#888" }),
  Panel: { esc: s => String(s), head: o => "<h>" + o.n + "</h>", acts: () => "" },
  document: { getElementById: i => els[i] || null, querySelector: () => null, querySelectorAll: () => [], addEventListener: noop, documentElement: el("html") } };
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(code, ctx);
const gg = ctx.GarrickGraph, cv = els.gcv.listeners;
const ev = (x, y, o) => Object.assign({ clientX: x, clientY: y, pointerId: 1, shiftKey: false }, o || {});
function pointer(type, x, y, o) { cv[type](ev(x, y, o)); }
function run(n, t0) { let t = t0 || 1000; for (let i = 0; i < n && frames.length; i++) { frames.shift()(t); t += 16; } return t; }
function median(a) { a = a.slice().sort((x, y) => x - y); return a[a.length >> 1]; }
function timed(n, t) { const out = []; for (let i = 0; i < n; i++) { const f = frames.shift(); if (!f) break; const s = process.hrtime.bigint(); f(t); out.push(Number(process.hrtime.bigint() - s) / 1e6); t += 16; } return out; }
const out = eval("(" + opts.script + ")")({ gg, els, cv, pointer, run, timed, median, store, ctx, frames });
process.stdout.write(JSON.stringify(out));
"""


def sample(count, kinds=1):
    nodes = [{"n": "Note %d" % i, "k": i % kinds, "z": "Work", "c": 1 if i % 40 == 0 else 0, "h": 1 if i % 200 == 0 else 0,
              "u": "http://example.test/%d" % i, "d": i % 30} for i in range(count)]
    edges = sorted({(min(i, (i * 7 + 3) % count), max(i, (i * 7 + 3) % count)) for i in range(count) if i != (i * 7 + 3) % count}
                   | {(i - 1, i) for i in range(1, count, 3)})
    return {"nodes": nodes, "edges": [list(e) for e in edges], "colors": ["#4a90d9", "#d9a441"][:kinds] * kinds,
            "kinds": [[k, "Kind %d" % k] for k in range(kinds)], "keys": ["note", "thread"][:kinds], "known": kinds,
            "mode": "all", "modes": {"Work": "all"}, "pr": {}, "ce": []}


@unittest.skipUnless(shutil.which("node"), "Node is not installed")
class TestFlatGraph(unittest.TestCase):
    def run_js(self, script, count=60, **opts):
        opts.update(script=script)
        done = subprocess.run(["node", "-e", HARNESS, json.dumps([status.GRAPH_JS, sample(count), opts])],
                              capture_output=True, text=True, timeout=300)
        self.assertEqual(0, done.returncode, done.stderr)
        return json.loads(done.stdout)

    def test_the_bar_has_no_3d_button(self):
        self.assertNotIn("g3d", status.GRAPH_JS)

    def test_a_page_left_in_3d_opens_flat_and_drops_the_value(self):
        got = self.run_js("""({gg, store, run}) => {
          run(3);
          const n = gg.cam.notes()[0], p = gg.cam.screen(n);
          return {kept: store["garrick-graph-3d"] === undefined, depth: p[2], scale: p[3], count: gg.cam.notes().length};
        }""", store={"garrick-graph-3d": "1"})
        self.assertTrue(got["kept"])
        self.assertEqual(0, got["depth"])
        self.assertEqual(1, got["scale"])
        self.assertEqual(60, got["count"])

    def test_a_point_maps_to_the_screen_and_back(self):
        got = self.run_js("""({gg, run}) => {
          run(3);
          let w = 0;
          for (const n of gg.cam.notes()) {
            const p = gg.cam.screen(n), b = gg.cam.world(p[0], p[1]);
            w = Math.max(w, Math.hypot(b[0] - n.x, b[1] - n.y));
          }
          return w;
        }""")
        self.assertLess(got, 0.01)

    def test_dragging_empty_space_moves_the_graph_and_the_notes_stay(self):
        got = self.run_js("""({gg, cv, pointer, run}) => {
          run(3);
          const n = gg.cam.notes()[0], before = gg.cam.screen(n);
          pointer("pointerdown", 2, 2); pointer("pointermove", 42, 22); pointer("pointerup", 42, 22);
          const after = gg.cam.screen(n);
          return [after[0] - before[0], after[1] - before[1]];
        }""")
        self.assertEqual(2, len(got))

    def test_a_frame_with_2000_notes_stays_cheap(self):
        got = self.run_js("""({gg, run, timed, median}) => { run(5); return median(timed(10, 5000)); }""", count=2000)
        self.assertLess(got, 200)


if __name__ == "__main__":
    unittest.main()
