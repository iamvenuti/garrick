#!/usr/bin/env python3
"""Run one shard of the suite, as CI does: `python3 tests/shard.py 2/4`.

CI splits the test modules into shards that run side by side. This script
lists the modules the way `unittest discover` finds them, and deals them out by
the run times in `shard-times.json` beside it: the slowest module first, each to
the shard with the least time so far. A module with no recorded time still runs:
it goes to the lightest shard once the timed ones are placed. So every module
runs in exactly one shard, and a new one needs no list to edit.

    python3 tests/shard.py 2/4            run shard 2 of 4, then print each module's time
    python3 tests/shard.py --list 2/4     name the modules in shard 2 of 4
    python3 tests/shard.py --merge-times LOG...
                                          write the times a run printed into shard-times.json

`python3 -m unittest discover -s tests` still runs everything. Standard library only.
"""

import argparse
import json
import re
import statistics
import sys
import time
import traceback
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TIMES = HERE / "shard-times.json"
# What `unittest discover` loads with its default pattern, test*.py.
MODULE = re.compile(r"test\w*\.py$")
# The line a run prints for each module, and --merge-times reads back.
TIME_LINE = re.compile(r"shard-time (\w+) (\d+(?:\.\d+)?)")


def modules(folder=HERE):
    """The test modules unittest discover runs from this folder, by name."""
    return sorted(p.stem for p in folder.iterdir() if p.is_file() and MODULE.match(p.name))


def load_times(path=TIMES):
    try:
        return {name: float(sec) for name, sec in json.loads(path.read_text()).items()}
    except FileNotFoundError:
        return {}


def plan(names, times, count):
    """Deal the names into count shards, balanced by times; each name in one shard.

    Timed names go slowest first, each to the lightest shard. A name with no time
    then goes to the lightest shard too, counted at the median time, so that
    several new modules spread out rather than pile into one shard.
    """
    shards = [[] for _ in range(count)]
    load = [0.0] * count
    timed = sorted((n for n in names if n in times), key=lambda n: (-times[n], n))
    untimed = sorted(n for n in names if n not in times)
    guess = statistics.median([times[n] for n in timed]) if timed else 1.0
    for name in timed + untimed:
        lightest = min(range(count), key=lambda i: (load[i], i))
        shards[lightest].append(name)
        load[lightest] += times.get(name, guess)
    return [sorted(s) for s in shards]


def shard(spec, names=None, times=None):
    """The module names in shard spec, written "2/4": the second of four."""
    index, count = parse(spec)
    names = modules() if names is None else names
    times = load_times() if times is None else times
    return plan(names, times, count)[index - 1]


def parse(spec):
    match = re.fullmatch(r"(\d+)/(\d+)", spec)
    if not match or not 1 <= int(match.group(1)) <= int(match.group(2)):
        raise argparse.ArgumentTypeError(f"a shard is written K/N, such as 2/4, not {spec!r}")
    return int(match.group(1)), int(match.group(2))


class Timed:
    """The shard's modules, each run as a suite of its own and timed, fixtures included."""

    def __init__(self, names):
        self.names = names
        self.times = {}

    def __call__(self, result):
        loader = unittest.TestLoader()
        for name in self.names:
            start = time.perf_counter()
            try:
                suite = loader.loadTestsFromName(name)
            except Exception:
                suite = unittest.TestSuite([failed_import(name, traceback.format_exc())])
            suite(result)
            self.times[name] = time.perf_counter() - start
        return result


def failed_import(name, text):
    def load():
        raise ImportError(f"{name} did not load:\n{text}")
    return unittest.FunctionTestCase(load, description=name)


def run(names):
    sys.path.insert(0, str(HERE))
    timed = Timed(names)
    result = unittest.TextTestRunner().run(timed)
    print("\nModule times, slowest first (python3 tests/shard.py --merge-times reads these):")
    for name, sec in sorted(timed.times.items(), key=lambda kv: -kv[1]):
        print(f"shard-time {name} {sec:.1f}")
    return result.wasSuccessful()


def merge_times(logs, path=TIMES, names=None):
    """Take each module's time from the logs, the longest where it appears twice.

    A module the logs do not mention keeps its time; one no longer on disk loses it.
    """
    seen = {}
    for log in logs:
        for name, sec in TIME_LINE.findall(Path(log).read_text(errors="replace")):
            seen[name] = max(seen.get(name, 0.0), float(sec))
    names = set(modules() if names is None else names)
    times = {n: t for n, t in {**load_times(path), **seen}.items() if n in names}
    path.write_text(json.dumps({n: round(times[n], 1) for n in sorted(times)}, indent=2) + "\n")
    return seen


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("shard", nargs="?", help="K/N: run shard K of N")
    parser.add_argument("--list", action="store_true", help="name the shard's modules, run nothing")
    parser.add_argument("--merge-times", nargs="+", metavar="LOG",
                        help="read the times a run printed into shard-times.json")
    args = parser.parse_args(argv)
    if args.merge_times:
        seen = merge_times(args.merge_times)
        print(f"{len(seen)} module times read into {TIMES.name}.")
        return 0
    if not args.shard:
        parser.error("name a shard, such as 2/4")
    try:
        names = shard(args.shard)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    if args.list:
        print("\n".join(names))
        return 0
    return 0 if run(names) else 1


if __name__ == "__main__":
    sys.exit(main())
