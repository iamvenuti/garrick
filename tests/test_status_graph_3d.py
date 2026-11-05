"""Explore's graph in three dimensions (#372): the 3D button, the camera that maps a
point to the screen and back, turning by dragging, picking the nearest note, and
what a frame costs with 2,000 notes. The graph's script runs in Node with the page
stubbed; where Node is not installed the tests are skipped.

    python3 -m unittest tests.test_status_graph_3d
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
["graph-data", "gcv", "gpop", "gspin", "g3d", "gfit", "gpark", "gsum"].forEach(i => els[i] = el(i));
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
class TestGraph3D(unittest.TestCase):
    def run_js(self, script, count=60, **opts):
        opts.update(script=script)
        done = subprocess.run(["node", "-e", HARNESS, json.dumps([status.GRAPH_JS, sample(count), opts])],
                              capture_output=True, text=True, timeout=300)
        self.assertEqual(0, done.returncode, done.stderr)
        return json.loads(done.stdout)

    def test_2d_is_the_default_and_the_button_switches_both_ways(self):
        got = self.run_js("""({gg, els, store, run}) => {
          const first = [els.g3d.textContent, gg.cam.view()[0], els.g3d.attrs["aria-pressed"]];
          const ids = gg.cam.notes().map(n => n.i).join();
          els.g3d.onclick(); run(3);
          const on = [els.g3d.textContent, gg.cam.view()[0], store["garrick-graph-3d"]];
          els.g3d.onclick(); run(3);
          return {first, on, off: [els.g3d.textContent, gg.cam.view()[0], store["garrick-graph-3d"]],
                  same: ids === gg.cam.notes().map(n => n.i).join()};
        }""")
        self.assertEqual(["3D", False, "false"], got["first"])
        self.assertEqual(["2D", True, "1"], got["on"])
        self.assertEqual(["3D", False, "0"], got["off"])
        self.assertTrue(got["same"])

    def test_the_choice_is_kept_in_the_window(self):
        got = self.run_js("({gg, els}) => [gg.cam.view()[0], els.g3d.textContent]", store={"garrick-graph-3d": "1"})
        self.assertEqual([True, "2D"], got)

    def test_a_point_maps_to_the_screen_and_back(self):
        got = self.run_js("""({gg, els, pointer, run}) => {
          const worst = (three) => { let w = 0; for (const n of gg.cam.notes()) {
            const p = gg.cam.screen(n), b = gg.cam.world(p[0], p[1], p[2]);
            w = Math.max(w, Math.abs(b[0] - n.x), Math.abs(b[1] - n.y), three ? Math.abs(b[2] - n.zz) : 0) } return w };
          const out = {flat: worst(false)};
          els.g3d.onclick(); run(2);
          out.front = worst(true);
          pointer("pointerdown", 3, 3); pointer("pointermove", 140, 90); pointer("pointerup", 140, 90);   // turned and tilted
          out.turned = worst(true); out.view = gg.cam.view();
          return out;
        }""")
        self.assertLess(got["flat"], 1e-6)
        self.assertLess(got["front"], 1e-6)
        self.assertLess(got["turned"], 1e-6)
        self.assertNotEqual(0, got["view"][1])           # it did turn

    def test_dragging_empty_space_turns_and_shift_drag_moves(self):
        got = self.run_js("""({gg, els, pointer, run}) => {
          els.g3d.onclick(); run(2);
          const n = gg.cam.notes()[0], before = gg.cam.view(), p0 = gg.cam.screen(n);
          pointer("pointerdown", 2, 2); pointer("pointermove", 80, 2); pointer("pointerup", 80, 2);
          const turned = gg.cam.view(), p1 = gg.cam.screen(n);
          pointer("pointerdown", 2, 2, {shiftKey: true}); pointer("pointermove", 52, 22, {shiftKey: true}); pointer("pointerup", 52, 22, {shiftKey: true});
          const p2 = gg.cam.screen(n);
          return {yaw: [before[1], turned[1]], moved: [p1[0] - p0[0], p2[0] - p1[0], p2[1] - p1[1]], after: gg.cam.view()[1], sel: !els.gpop.hidden};
        }""")
        self.assertNotEqual(got["yaw"][0], got["yaw"][1])
        self.assertAlmostEqual(got["yaw"][1], got["after"])            # shift-drag does not turn it
        self.assertAlmostEqual(50, got["moved"][1], places=6)
        self.assertAlmostEqual(20, got["moved"][2], places=6)
        self.assertFalse(got["sel"])                                    # nothing was clicked

    def test_click_and_double_click_work_as_in_2d(self):
        got = self.run_js("""({gg, els, pointer, run, ctx}) => {
          const res = {};
          for (const three of [false, true]) {
            if (three) { els.g3d.onclick(); run(2) }
            const n = gg.cam.notes()[5], p = gg.cam.screen(n);
            els.gpop.hidden = true;
            pointer("pointerdown", p[0], p[1]); pointer("pointerup", p[0], p[1]);
            const opened = !els.gpop.hidden && els.gpop.innerHTML.indexOf(n.n) >= 0;
            ctx.location.href = ""; els.gcv.listeners.dblclick({clientX: p[0], clientY: p[1]});
            res[three ? "3d" : "2d"] = [opened, ctx.location.href === n.u];
          }
          return res;
        }""")
        self.assertEqual([True, True], got["2d"])
        self.assertEqual([True, True], got["3d"])

    def test_the_selection_and_the_notes_survive_the_switch(self):
        got = self.run_js("""({gg, els, pointer, run}) => {
          const n = gg.cam.notes()[7], p = gg.cam.screen(n);
          pointer("pointerdown", p[0], p[1]); pointer("pointerup", p[0], p[1]);
          const a = [els.gpop.hidden, gg.cam.notes().length];
          els.g3d.onclick(); run(2);
          els.g3d.onclick(); run(2);
          return [a, [els.gpop.hidden, gg.cam.notes().length], els.gpop.innerHTML.indexOf(n.n) >= 0];
        }""")
        self.assertEqual([[False, 60], [False, 60], True], got)

    def test_the_nearest_note_in_front_is_picked(self):
        got = self.run_js("""({gg, els, pointer, run}) => {
          els.g3d.onclick(); run(2);
          const [a, b] = gg.cam.notes(), pa = gg.cam.screen(a);
          const w = gg.cam.world(pa[0], pa[1], pa[2] + 150);    // straight behind a, on the same line of sight
          b.x = w[0]; b.y = w[1]; b.zz = w[2];
          const pb = gg.cam.screen(b);
          pointer("pointermove", pa[0], pa[1]);
          return [els.gcv.dataset.tip.indexOf(a.n + " ") === 0, Math.hypot(pa[0] - pb[0], pa[1] - pb[1]) < 1e-6, pb[2] > pa[2]];
        }""")
        self.assertEqual([True, True, True], got)

    def test_reduced_motion_keeps_3d_still_until_dragged(self):
        got = self.run_js("""({gg, els, pointer, run}) => {
          els.g3d.onclick(); run(400, 1000); const a = gg.cam.view();
          run(200, 400000); const b = gg.cam.view();
          pointer("pointerdown", 2, 2); pointer("pointermove", 60, 2); pointer("pointerup", 60, 2);
          return [a, b, gg.cam.view()];
        }""", reduce=True)
        self.assertEqual(got[0], got[1])
        self.assertNotEqual(got[1], got[2])

    def test_the_view_sways_round_the_vertical_axis_when_left_alone(self):
        got = self.run_js("""({gg, els, run}) => {
          els.g3d.onclick(); run(300, 1000); const a = gg.cam.view(); run(200, 300000); const b = gg.cam.view();
          return [a, b];
        }""")
        self.assertNotEqual(got[0][1], got[1][1])         # yaw moves
        self.assertEqual(got[0][2], got[1][2])            # the tilt does not

    def test_a_3d_frame_is_close_to_a_2d_frame_with_2000_notes(self):
        # Measured in Node with a canvas that draws nothing: the cost of the page's own code. A frame while the layout
        # settles and a frame once it has; both must stay within a few milliseconds of the flat one.
        got = self.run_js("""({gg, els, run, timed, median}) => {
          run(300, 1000);
          const flatStill = median(timed(40, 500000));
          els.g3d.onclick(); run(1, 600000); els.g3d.onclick();               // the layout moving again, flat
          const flatMoving = median(timed(10, 700000));
          els.g3d.onclick();                                                   // and in 3D
          const deepMoving = median(timed(10, 800000));
          run(400, 900000);
          const deepStill = median(timed(40, 1500000));
          return {flatStill, flatMoving, deepStill, deepMoving};
        }""", count=2000)
        print("\n2,000 notes, still: 2D %.2f ms, 3D %.2f ms; settling: 2D %.2f ms, 3D %.2f ms"
              % (got["flatStill"], got["deepStill"], got["flatMoving"], got["deepMoving"]), file=sys.stderr)
        if os.environ.get("CI") or got["flatStill"] > 6 or got["flatMoving"] > 14:
            # a quiet machine takes 2 to 3 ms for the flat frame and 9 to 10 ms while it settles; far above that, it is loaded
            self.skipTest("the machine is loaded (2D frame %.1f ms, %.1f ms settling): the timing means nothing here" % (got["flatStill"], got["flatMoving"]))
        self.assertLessEqual(got["deepStill"] - got["flatStill"], 6.0)
        self.assertLessEqual(got["deepMoving"] - got["flatMoving"], 6.0)


if __name__ == "__main__":
    unittest.main()
