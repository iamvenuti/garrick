"""Tests for shard.py, which splits the suite into the shards CI runs side by side.

    python3 -m unittest discover -s tests
"""

import contextlib
import io
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import shard

WORKFLOW = shard.HERE.parent / ".github" / "workflows" / "tests.yml"


def discovered():
    """The modules unittest discover itself finds in tests/, by name."""
    names = set()

    def walk(suite):
        for test in suite:
            if isinstance(test, unittest.TestSuite):
                walk(test)
            else:
                names.add(type(test).__module__)

    walk(unittest.TestLoader().discover(str(shard.HERE)))
    return names


class EveryModuleOnce(unittest.TestCase):
    def test_the_module_list_is_what_discover_runs(self):
        found = discovered()
        found.discard("unittest.loader")  # a module discover could not import shows up as this
        self.assertEqual(found - set(shard.modules()), set(),
                         "discover runs modules the shards never would")
        # A module with no test in it is listed and runs as nothing: harmless.
        self.assertIn("test_shard", shard.modules())

    def test_every_module_lands_in_exactly_one_shard(self):
        names = shard.modules()
        times = shard.load_times()
        for count in (1, 2, 3, 4, 6):
            shards = shard.plan(names, times, count)
            self.assertEqual(len(shards), count)
            dealt = [n for s in shards for n in s]
            self.assertEqual(sorted(dealt), names, f"{count} shards: a module is missing or runs twice")
            self.assertEqual([shard.shard(f"{k}/{count}") for k in range(1, count + 1)], shards)

    def test_the_workflow_runs_every_shard_the_script_deals(self):
        text = WORKFLOW.read_text()
        listed = re.search(r"shard: \[([\d, ]+)\]", text)
        self.assertIsNotNone(listed, "tests.yml has no shard matrix")
        numbers = [int(n) for n in listed.group(1).split(",")]
        call = re.search(r"tests/shard\.py \$\{\{ matrix\.shard \}\}/(\d+)", text)
        self.assertIsNotNone(call, "tests.yml does not run tests/shard.py per shard")
        self.assertEqual(numbers, list(range(1, int(call.group(1)) + 1)))

    def test_a_module_with_no_time_still_runs_in_the_lightest_shard(self):
        times = {"test_slow": 300.0, "test_mid": 200.0, "test_quick": 50.0}
        names = sorted([*times, "test_new"])
        shards = shard.plan(names, times, 3)
        self.assertEqual(shards, [["test_slow"], ["test_mid"], ["test_new", "test_quick"]])

    def test_several_new_modules_spread_out(self):
        shards = shard.plan(["test_a", "test_b", "test_c", "test_d"], {}, 2)
        self.assertEqual(shards, [["test_a", "test_c"], ["test_b", "test_d"]])

    def test_a_time_for_a_module_gone_from_disk_is_ignored(self):
        shards = shard.plan(["test_a"], {"test_gone": 900.0}, 2)
        self.assertEqual(shards, [["test_a"], []])

    def test_shards_are_balanced_by_time(self):
        times = {"test_a": 9.0, "test_b": 8.0, "test_c": 4.0, "test_d": 4.0, "test_e": 1.0}
        shards = shard.plan(sorted(times), times, 2)
        loads = [sum(times[n] for n in s) for s in shards]
        self.assertEqual(sorted(loads), [13.0, 13.0])

    def test_a_shard_is_written_k_of_n(self):
        for bad in ("0/4", "5/4", "2", "two/four"):
            with self.assertRaises(SystemExit):
                with mock.patch("sys.stderr"):
                    shard.main([bad])


class Parallel(unittest.TestCase):
    """CI runs a shard with --jobs: a failure in any module must fail the shard."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        test = "import unittest\n\nclass T(unittest.TestCase):\n    def test_it(self):\n        {}\n"
        (self.dir / "test_fake_pass.py").write_text(test.format("pass"))
        (self.dir / "test_fake_fail.py").write_text(test.format("self.fail('meant to')"))
        path = os.pathsep.join(filter(None, [str(self.dir), os.environ.get("PYTHONPATH")]))
        patcher = mock.patch.dict(os.environ, {"PYTHONPATH": path})
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_parallel(self, names):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ok = shard.run_parallel(names, 2, {})
        return ok, out.getvalue()

    def test_a_failing_module_fails_the_shard(self):
        ok, out = self.run_parallel(["test_fake_pass", "test_fake_fail"])
        self.assertFalse(ok)
        self.assertIn("FAILED: test_fake_fail", out)
        self.assertIn("meant to", out)
        self.assertIn("Ran 2 tests in 2 modules", out)

    def test_a_module_that_does_not_load_fails_the_shard(self):
        ok, out = self.run_parallel(["test_fake_pass", "test_fake_missing"])
        self.assertFalse(ok)
        self.assertIn("FAILED: test_fake_missing", out)

    def test_passing_modules_pass(self):
        ok, out = self.run_parallel(["test_fake_pass"])
        self.assertTrue(ok)
        self.assertIn("shard-time test_fake_pass ", out)


class MergeTimes(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        self.times = self.dir / "shard-times.json"
        self.times.write_text('{"test_a": 5.0, "test_b": 7.0, "test_gone": 3.0}\n')

    def test_the_longest_time_a_log_shows_wins_and_the_rest_are_kept(self):
        one = self.dir / "one.log"
        two = self.dir / "two.log"
        # As GitHub writes a job's log: job, step and a timestamp before each line.
        one.write_text("macOS, Python system\tRun\t2026-11-01T10:00:00Z shard-time test_a 40.2\n")
        two.write_text("shard-time test_a 12.0\nshard-time test_c 1.5\n")
        seen = shard.merge_times([one, two], path=self.times, names=["test_a", "test_b", "test_c"])
        self.assertEqual(seen, {"test_a": 40.2, "test_c": 1.5})
        self.assertEqual(shard.load_times(self.times), {"test_a": 40.2, "test_b": 7.0, "test_c": 1.5})


if __name__ == "__main__":
    unittest.main()
