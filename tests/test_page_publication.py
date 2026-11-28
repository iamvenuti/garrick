"""The status page is published in order (reload-0860, V2).

    cd tests && python3 -m unittest test_page_publication

A page build takes a generation number when it starts and writes it into the page in one meta element. The page
goes in place only if it is newer than the one there. The tests that matter run builds as separate processes:
`test_two_writers_overlap_and_the_first_is_slowed` and `test_two_writers_that_finish_together_leave_one_whole_page`.
"""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

from fixtures import build_workspace  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
STATUS = REPO / "extras" / "status" / "status.py"


def _load():
    spec = importlib.util.spec_from_file_location("garrick_status_publication", str(STATUS))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


status = _load()


def env_for(**more):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GARRICK_")}
    env.update(more)
    return env


class Workspace(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = build_workspace(Path(self.tmp.name) / "ws")
        self.out = self.ws / "System" / "generated" / "status.html"

    def start(self, hold=None):
        env = env_for(**({status.PUBLISH_HOLD: str(hold)} if hold else {}))
        return subprocess.Popen([sys.executable, str(STATUS), "--workspace", str(self.ws), "--no-graph", "--no-cmux"],
                                env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def counter(self):
        try:
            return int(self.out.with_name(self.out.name + ".generation").read_text().strip())
        except (OSError, ValueError):
            return None

    def wait_for_counter(self, beyond, seconds=60):
        end = time.time() + seconds
        while time.time() < end:
            c = self.counter()
            if c is not None and (beyond is None or c > beyond):
                return c
            time.sleep(0.05)
        self.fail("a build never took a generation")

    def assert_whole(self):
        text = self.out.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("<!doctype html>") and text.rstrip().endswith("</html>"))
        self.assertEqual(1, text.count("<!doctype html>"))
        self.assertEqual(1, text.count('<meta name="garrick-generation"'))
        return text

    def leftovers(self):
        kept = {"status.html", "status.check.json", "status.flags.json", "status.html.generation"}
        return sorted(p.name for p in self.out.parent.iterdir() if p.name.startswith("status.html.") and p.name not in kept)


class TwoWritersAsSeparateProcesses(Workspace):
    def test_two_writers_overlap_and_the_first_is_slowed(self):
        slow = self.start(hold=6)
        first = self.wait_for_counter(None)                  # the slow one has started its build
        fast = self.start()
        out, err = fast.communicate(timeout=120)
        self.assertEqual(0, fast.returncode, err)
        second = self.counter()
        self.assertGreater(second, first, "the later build took the later number")
        self.assertEqual(second, status.page_generation(self.out), "the second's page is in place")
        slow.communicate(timeout=120)
        self.assertEqual(0, slow.returncode)
        self.assertEqual(second, status.page_generation(self.out), "the first finished last and left the second's page")
        self.assert_whole()
        self.assertEqual([], self.leftovers())

    def test_two_writers_that_finish_together_leave_one_whole_page(self):
        writers = [self.start(hold=3) for _ in range(3)]
        for w in writers:
            w.communicate(timeout=180)
            self.assertEqual(0, w.returncode)
        self.assertEqual(self.counter(), status.page_generation(self.out), "the newest build's page is the one in place")
        self.assert_whole()
        self.assertEqual([], self.leftovers())


class Publication(Workspace):
    def page(self, generation, body="x"):
        return '<!doctype html><html><head>%s</head><body>%s</body></html>' % (status.generation_meta(generation), body)

    def test_a_newer_page_goes_in_and_an_older_or_equal_one_does_not(self):
        self.out.parent.mkdir(parents=True, exist_ok=True)
        self.assertTrue(status.publish_page(self.out, self.page(5, "five"), 5))
        self.assertFalse(status.publish_page(self.out, self.page(4, "four"), 4))
        self.assertFalse(status.publish_page(self.out, self.page(5, "again"), 5))
        self.assertIn("five", self.out.read_text())
        self.assertTrue(status.publish_page(self.out, self.page(6, "six"), 6))
        self.assertIn("six", self.out.read_text())
        self.assertEqual([], self.leftovers())

    def test_a_page_in_place_with_no_generation_is_older_than_any_page_with_one(self):
        self.out.parent.mkdir(parents=True, exist_ok=True)
        self.out.write_text(self.page(None, "old builder"))
        self.assertIsNone(status.page_generation(self.out))
        self.assertTrue(status.publish_page(self.out, self.page(1, "new"), 1))
        self.assertIn("new", self.out.read_text())

    def test_a_build_with_no_generation_carries_no_meta_and_loads_as_it_did(self):
        page = status.build(self.ws, show_graph=False)
        self.assertNotIn(status.GENERATION_NAME, page)
        again = status.build(self.ws, show_graph=False, generation=77)
        self.assertEqual(1, again.count('<meta name="garrick-generation" content="77">'))
        self.assertEqual(page.replace('<meta name="viewport" content="width=device-width,initial-scale=1">',
                                      '<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="garrick-generation" content="77">'
                                      ).count("garrick-generation"), 1)

    def test_the_generation_is_in_the_first_bytes_of_the_page(self):
        self.out.parent.mkdir(parents=True, exist_ok=True)
        status.publish_page(self.out, status.build(self.ws, show_graph=False, generation=123), 123)
        self.assertLess(self.out.read_text().index("garrick-generation"), 2000)
        self.assertEqual(123, status.page_generation(self.out))

    def test_generations_only_rise_across_threads(self):
        self.out.parent.mkdir(parents=True, exist_ok=True)
        taken = []

        def take():
            taken.extend(status.next_generation(self.out) for _ in range(30))

        threads = [threading.Thread(target=take) for _ in range(4)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(len(taken), len(set(taken)), "no two builds took the same number")

    def test_the_kept_check_result_and_the_flags_keep_their_writer(self):
        src = STATUS.read_text(encoding="utf-8")
        self.assertIn("publish_page(out, page, generation)", src)
        self.assertIn("write_page(flags_file(out)", src)
        self.assertRegex(src, r'write_page\(store, json\.dumps\(\{"workspace"')


if __name__ == "__main__":
    unittest.main()
