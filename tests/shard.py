#!/usr/bin/env python3
"""Run one shard of the suite, as CI does: `python3 tests/shard.py 2/4`.

CI splits the test modules into shards that run side by side. This script
lists the modules the way `unittest discover` finds them, and deals them out by
the run times in `shard-times.json` beside it: the slowest module first, each to
the shard with the least time so far. A module with no recorded time still runs:
it goes to the lightest shard once the timed ones are placed. So every module
runs in exactly one shard, and a new one needs no list to edit.

    python3 tests/shard.py 2/4            run shard 2 of 4, then print each module's time
    python3 tests/shard.py 2/4 --jobs 3   the same, three modules at a time, each in a process
                                          of its own, as CI runs it
    python3 tests/shard.py --list 2/4     name the modules in shard 2 of 4
    python3 tests/shard.py --touched FILE...
                                          print the modules a pull request that changes FILE... runs, or ALL
    python3 tests/shard.py --touched-from BASE HEAD
                                          the same, for the files git diff BASE...HEAD names
    python3 tests/shard.py --run MODULE... --jobs 3
                                          run just those modules
    python3 tests/shard.py --should-rerun JOBS.json ATTEMPT
                                          exit 0 when the run's only failures are runners not acquired
    python3 tests/shard.py --merge-times LOG...
                                          write the times a run printed into shard-times.json

`python3 -m unittest discover -s tests` still runs everything. Standard library only.
"""

import argparse
import json
import re
import statistics
import subprocess
import sys
import threading
import time
import traceback
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
TIMES = HERE / "shard-times.json"
# What `unittest discover` loads with its default pattern, test*.py.
MODULE = re.compile(r"test\w*\.py$")
# The line a run prints for each module, and --merge-times reads back.
TIME_LINE = re.compile(r"shard-time (\w+) (\d+(?:\.\d+)?)")


# Which test modules a changed file runs on a branch pull request. A path ending in "/" is a
# folder. A source file also runs the modules named for its stem: x.py runs test_x and test_x_*.
# A changed test module runs itself. Any other changed file runs the full suite, so a file the
# map does not know fails closed. Release pull requests and main always run the full suite.
TOUCH_MAP = {
    # The wall check: a change to it runs every module that tests a wall, not only test_check*.
    "template/System/tools/check.py": ["test_wall_false_positives", "test_wall_forms", "test_wall_gaps",
                                       "test_wall_gaps_340", "test_wall_noise", "test_wall_cache",
                                       "test_walls_cases", "test_walls_deterministic", "test_staged_paths",
                                       "test_pathspec_commit", "test_no_party", "test_decide"],
    "tests/walls/cases.md": ["test_walls_cases"],
    "extras/status/questions_panel.py": ["test_questions_panel", "test_questions_panel_all",
                                         "test_panel_hardening", "test_decisions",
                                         "test_nurture_panel_actions", "test_question_transaction"],
    "extras/status/parties_panel.py": ["test_status", "test_page_action"],
    "template/System/tools/migrate_walls.py": ["test_update", "test_decide"],
    "extras/status/status.py": ["test_status", "test_status_find", "test_status_finder",
                                "test_status_graph_3d", "test_status_graph_ignored",
                                "test_status_more", "test_status_work"],
    "extras/status/app/": ["test_status_finder", "test_status_graph_3d", "test_status_more"],
    "tests/shard.py": ["test_shard"],
    "tests/shard-times.json": ["test_shard"],
    "docs/": ["test_docs"],
    "template/System/skills/": ["test_skills", "test_docs"],
    "tests/walls/": ["test_wall_form_files"],
}
# Modules no mapped path reaches: they check the whole repository, so only the full suite runs them.
FULL_ONLY = {
    "test_autonomy", "test_check_conventions", "test_check_rules", "test_cleanroom",
    "test_cleanroom_worktree", "test_demo", "test_example", "test_git_env", "test_install",
    "test_jobs", "test_onboarding", "test_public", "test_rules_map", "test_setup",
    "test_simple_home", "test_split", "test_update",
    "test_checkpoint", "test_cmux", "test_cmux_sidebar", "test_decide", "test_executor",
    "test_fetch", "test_knowledge_skill", "test_lib", "test_meetings", "test_memory_canary",
    "test_mod", "test_nested_checkout", "test_no_party", "test_obsidian", "test_open_sections",
    "test_pathspec_commit", "test_person_employer", "test_person_organisation", "test_reading",
    "test_staged_paths", "test_wall_cache", "test_wall_false_positives", "test_wall_forms",
    "test_wall_gaps", "test_wall_gaps_340", "test_wall_noise", "test_walls_cases",
    "test_walls_deterministic", "test_wiki_answers", "test_wrap",
}
# A change here can break anything: the full suite runs.
ALWAYS_FULL = (".github/", "tests/fixtures.py")
ALWAYS_FULL_NAMES = {"garrick_lib.py"}
RUNNER_LOST = "not acquired by runner"
# The jobs of tests.yml that run no tests.
NOT_TEST_JOBS = {"Plan", "Tests", "Rerun a lost runner"}


def touched(files, names=None):
    """The modules to run for the changed files, sorted; or None for the full suite."""
    names = modules() if names is None else list(names)
    run = set()
    for f in files:
        f = f.strip()
        if not f:
            continue
        base = f.rsplit("/", 1)[-1]
        if f.startswith(ALWAYS_FULL) or base in ALWAYS_FULL_NAMES:
            return None
        known = False
        if f.startswith("tests/") and f.count("/") == 1 and MODULE.match(base):
            run.add(base[:-3])
            known = True
        stem = base[:-3] if base.endswith(".py") else None
        if stem and not f.startswith("tests/"):
            for n in names:
                if n == f"test_{stem}" or n.startswith(f"test_{stem}_"):
                    run.add(n)
                    known = True
        for key, mods in TOUCH_MAP.items():
            if f == key or (key.endswith("/") and f.startswith(key)):
                run.update(mods)
                known = True
        if not known:
            return None
    return sorted(n for n in run if n in names)


def changed_files(base, head):
    out = subprocess.run(["git", "diff", "--name-only", f"{base}...{head}"], cwd=HERE.parent,
                         stdout=subprocess.PIPE, text=True, check=True).stdout
    return out.split("\n")


def should_rerun(jobs, attempt):
    """True when the run's failures are all runners that were not acquired, on the first attempt.

    jobs is the "jobs" list of the API's run-jobs answer. A job counts as a runner failure when
    its "message" says so. The workflow adds that message to each failed job from its check-run
    annotations. A test failure is never rerun.
    """
    if int(attempt) != 1:
        return False
    # The plan, the gate and this job itself fail only because a test job did: they say nothing of
    # why, so they are left out, and the test jobs alone decide.
    failed = [j for j in jobs if j.get("conclusion") in ("failure", "timed_out", "cancelled")
              and j.get("name") not in NOT_TEST_JOBS]
    if not failed:
        return False
    return all(RUNNER_LOST in str(j.get("message", "")).lower() for j in failed)


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
    """Run the modules one after another in this process, as discover does."""
    sys.path.insert(0, str(HERE))
    timed = Timed(names)
    result = unittest.TextTestRunner().run(timed)
    print_times(timed.times)
    return result.wasSuccessful()


def run_parallel(names, jobs, times):
    """Run the modules jobs at a time, each in a process of its own, slowest first.

    Each module's output is printed whole when it ends, so two never interleave.
    """
    lock = threading.Lock()
    took, failed, ran = {}, [], []

    def one(name):
        start = time.perf_counter()
        proc = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--only", name],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, errors="replace")
        took[name] = time.perf_counter() - start
        with lock:
            print(f"\n=== {name}: {'ok' if proc.returncode == 0 else 'FAILED'} in {took[name]:.1f}s", flush=True)
            print(proc.stdout.rstrip(), flush=True)
            ran.extend(int(n) for n in re.findall(r"^\S+ (\d+) tests? in ", proc.stdout, re.MULTILINE))
            if proc.returncode:
                failed.append(name)

    order = sorted(names, key=lambda n: (-times.get(n, 0.0), n))
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        list(pool.map(one, order))
    print_times(took)
    print(f"\nRan {sum(ran)} tests in {len(names)} modules, {jobs} at a time.")
    if failed:
        print(f"FAILED: {', '.join(sorted(failed))}")
    else:
        print("OK")
    return not failed


def print_times(times):
    print("\nModule times, slowest first (python3 tests/shard.py --merge-times reads these):")
    for name, sec in sorted(times.items(), key=lambda kv: -kv[1]):
        print(f"shard-time {name} {sec:.1f}")


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
    parser.add_argument("--jobs", type=int, default=1, metavar="N",
                        help="run N modules at a time, each in a process of its own")
    parser.add_argument("--touched", nargs="*", metavar="FILE", help="the modules these changed files run")
    parser.add_argument("--touched-from", nargs=2, metavar=("BASE", "HEAD"),
                        help="the modules the files changed from BASE to HEAD run")
    parser.add_argument("--should-rerun", nargs=2, metavar=("JOBS_JSON", "ATTEMPT"),
                        help="exit 0 when every failed job is a runner not acquired, on attempt 1")
    parser.add_argument("--run", nargs="+", metavar="MODULE",
                        help="run just these modules, --jobs at a time (a branch pull request)")
    parser.add_argument("--only", nargs="+", metavar="MODULE", help=argparse.SUPPRESS)
    parser.add_argument("--merge-times", nargs="+", metavar="LOG",
                        help="read the times a run printed into shard-times.json")
    args = parser.parse_args(argv)
    if args.touched is not None or args.touched_from:
        files = args.touched if args.touched is not None else changed_files(*args.touched_from)
        picked = touched(files)
        print("ALL" if picked is None else "\n".join(picked))
        return 0
    if args.should_rerun:
        jobs = json.loads(Path(args.should_rerun[0]).read_text())
        return 0 if should_rerun(jobs, args.should_rerun[1]) else 1
    if args.merge_times:
        seen = merge_times(args.merge_times)
        print(f"{len(seen)} module times read into {TIMES.name}.")
        return 0
    if args.run:
        if args.jobs > 1:
            return 0 if run_parallel(args.run, args.jobs, load_times()) else 1
        return 0 if run(args.run) else 1
    if args.only:
        sys.path.insert(0, str(HERE))
        result = unittest.TextTestRunner().run(Timed(args.only))
        return 0 if result.wasSuccessful() else 1
    if not args.shard:
        parser.error("name a shard, such as 2/4")
    try:
        names = shard(args.shard)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    if args.list:
        print("\n".join(names))
        return 0
    if args.jobs > 1:
        return 0 if run_parallel(names, args.jobs, load_times()) else 1
    return 0 if run(names) else 1


if __name__ == "__main__":
    sys.exit(main())
