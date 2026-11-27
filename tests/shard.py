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
    "template/System/tools/check.py": ["test_walls_cases", "test_staged_paths", "test_pathspec_commit", "test_decide",
                                       "test_zones", "test_allow_ledger", "test_merge_hooks", "test_check_history",
                                       "test_check_concise", "test_wall_runs", "test_wall_common", "test_refusals"],
    "install.py": ["test_merge_hooks"],
    # The history mover (#502) and the guard behind "compact the meetings" (#479).
    "template/System/tools/history.py": ["test_history", "test_history_workspace", "test_nurture_history",
                                         "test_check_history", "test_briefing"],
    "template/System/skills/meetings/compact.py": ["test_meetings_compact"],
    "tests/walls/cases.md": ["test_walls_cases"],
    "extras/status/questions_panel.py": ["test_questions_panel", "test_decisions", "test_question_transaction",
                                         "test_status", "test_page_action", "test_context_card"],
    "extras/status/finding_queue.py": ["test_finding_queue", "test_context_card", "test_decisions", "test_page_action", "test_walls_page"],
    "update.py": ["test_update", "test_merge_hooks"],
    "extras/status/page_action.py": ["test_page_action", "test_finding_queue", "test_operations", "test_walls_page", "test_notes",
                                     "test_failure_words", "test_failures_plain", "test_page_route", "test_settings_actions", "test_settings_ui",
                                     "test_new_session"],
    "template/System/skills/intake/intake.py": ["test_intake", "test_notes", "test_notes_process", "test_inbox_run"],
    "template/System/skills/intake/process_notes.py": ["test_notes_process"],
    "extras/jobs/notes_job.py": ["test_notes_process", "test_jobs"],
    "extras/status/ask.py": ["test_ask", "test_failures_plain"],
    "extras/status/app/Garrick.swift": ["test_failures_plain", "test_failure_words"],
    "extras/status/channels.py": ["test_channels", "test_status", "test_page_action", "test_operations"],
    "extras/status/engine.py": ["test_channels", "test_ask", "test_ask_agent"],
    "extras/status/engine_guard.py": ["test_channels"],
    "extras/status/inbox_run.py": ["test_inbox_run", "test_page_action", "test_decisions"],
    "extras/status/inbox_guard.py": ["test_inbox_run"],
    "extras/status/engine_cmd.py": ["test_channels"],
    "extras/status/hold.py": ["test_channels"],
    "extras/status/hold_tools.py": ["test_channels"],
    "extras/status/channel_state.py": ["test_channels", "test_telegram"],
    "extras/status/exchanges.py": ["test_telegram"],
    "extras/status/dispatcher.py": ["test_telegram"],
    "extras/status/telegram_delivery.py": ["test_telegram"],
    "extras/fetch/telegram_receiver.py": ["test_telegram"],
    "extras/status/status.py": ["test_status", "test_finding_queue", "test_context_card", "test_status_find", "test_status_finder",
                                "test_status_graph_flat", "test_status_graph_ignored",
                                "test_status_more", "test_status_work", "test_waiting_card", "test_needs_you_rows", "test_threads_card", "test_todo_solo",
                                "test_overview_work", "test_status_look", "test_settings_ui",
                                "test_new_session", "test_view_model", "test_usage_counts"],
    "template/System/tools/view.py": ["test_view_model", "test_status", "test_status_more", "test_status_work", "test_overview_work",
                                      "test_todo_solo", "test_todo_skips", "test_outbox", "test_context_card", "test_threads_card", "test_needs_you_rows",
                                      "test_inbox_run", "test_knowledge_skill", "test_status_graph_ignored", "test_status_graph_flat", "test_status_look"],
    "template/System/tools/view_todo.py": ["test_view_model", "test_todo_skips", "test_status", "test_overview_work"],
    "tests/old_status_reads_0770.py": ["test_view_model"],
    "template/System/tools/usage.py": ["test_usage_report"],
    "extras/status/usage_counts.py": ["test_usage_counts"],
    "extras/status/settings_guard.py": ["test_settings_ui", "test_settings_actions"],
    "extras/status/settings_help.py": ["test_settings_ui"],
    "extras/status/agents_working.py": ["test_agents_working", "test_waiting_card"],
    "extras/status/app/": ["test_status_finder", "test_status_graph_flat", "test_status_more", "test_new_session"],
    "tests/shard.py": ["test_shard"],
    "tests/acceptance/": ["test_acceptance"],
    "tests/shard-times.json": ["test_shard"],
    "docs/": ["test_docs", "test_docs_limits"],
    "template/System/skills/": ["test_skills", "test_docs"],
    "tests/walls/": ["test_walls_cases"],
    # The concept check (#654) and the pages it reads.
    "tests/concept_gate.py": ["test_concept_gate"],
    "names_move.py": ["test_names"],
    "tests/test_names.py": ["test_names"],
    # The memory index and the parked pointers (#664).
    "extras/hooks/parked_hint.py": ["test_parked_hint"],
    "tests/test_parked_hint.py": ["test_parked_hint"],
    "tests/test_memory_pointer.py": ["test_memory_pointer", "test_memory_budget"],
    "tests/test_memory_budget.py": ["test_memory_budget"],
    "template/System/skills/threads/reference/lifecycle.md": ["test_memory_pointer"],
    "docs/concepts.md": ["test_concept_gate"],
    "docs/decisions/": ["test_concept_gate"],
    "extras/hooks/read_guard.py": ["test_read_guard", "test_connector_guard", "test_decisions", "test_zone_guard", "test_settings_actions", "test_settings_ui"],
    "tests/read_guard_case.py": ["test_read_guard", "test_connector_guard", "test_decisions"],
}
# nurture-0780 (#661): a held history move retries instead of asking.
for _key in ("template/System/tools/history.py", "extras/status/finding_queue.py", "template/System/tools/nurture.py",
             "extras/jobs/nurture_sweep.py"):
    TOUCH_MAP[_key] = TOUCH_MAP.get(_key, []) + ["test_history_hold"]
# nurture-0780 (#662): wall findings that look like an old note template.
for _key in ("template/System/tools/check.py", "template/System/tools/nurture.py", "extras/status/finding_queue.py"):
    TOUCH_MAP[_key] = TOUCH_MAP.get(_key, []) + ["test_template_hint"]
# guard-0790 (#670, #671, #672): the guard hooks, found as the assistants name them.
for _key, _mods in (("extras/status/settings_guard.py", ["test_guard_hooks", "test_hook_path"]),
                    ("extras/hooks/read_guard.py", ["test_guard_hooks", "test_hook_path"]),
                    ("extras/status/page_action.py", ["test_guard_hooks"]),
                    ("update.py", ["test_guard_update", "test_hook_path"]),
                    ("docs/context.md", ["test_start_small"]),
                    ("README.md", ["test_start_small", "test_docs", "test_docs_limits"]),
                    ("template/System/tools/check.py", ["test_start_small"]),
                    ("template/System/tools/garrick_lib.py", ["test_start_small"]),
                    ("template/System/tools/history.py", ["test_start_small"])):
    TOUCH_MAP[_key] = TOUCH_MAP.get(_key, []) + _mods
# docs-0830 (#709, #710): the retired-claims check reads every current page.
for _key in ("README.md", "install.py", "docs/", "docs/assets/adoption-ladder.html"):
    TOUCH_MAP[_key] = TOUCH_MAP.get(_key, []) + ["test_retired_claims"]
for _key in ("docs/", "docs/using-the-app.md", "extras/status/guide.py", "install.py"):
    TOUCH_MAP[_key] = TOUCH_MAP.get(_key, []) + ["test_using_the_app"]
# settings-0790 (#650): Settings' data has a reader in the core.
for _key, _mods in (("template/System/tools/view_settings.py", ["test_view_settings", "test_view_model", "test_status", "test_settings_ui"]),
                    ("tests/test_view_settings.py", ["test_view_settings"])):
    TOUCH_MAP[_key] = TOUCH_MAP.get(_key, []) + _mods
for _key in ("template/System/tools/view.py", "extras/status/status.py"):
    TOUCH_MAP[_key] = TOUCH_MAP.get(_key, []) + ["test_view_settings"]
# settings-0790 (#673, #674, #675): Settings as one grid, the read guard's list, plain words.
for _key in ("extras/status/status.py", "extras/status/settings_help.py", "extras/status/settings_guard.py", "extras/status/settings_readguard.py"):
    TOUCH_MAP[_key] = TOUCH_MAP.get(_key, []) + ["test_settings_layout", "test_read_guard_list"]
for _key in ("extras/hooks/read_guard.py", "tests/read_guard_case.py"):
    TOUCH_MAP[_key] = TOUCH_MAP.get(_key, []) + ["test_read_guard_list"]
TOUCH_MAP["tests/test_settings_layout.py"] = ["test_settings_layout"]
TOUCH_MAP["tests/test_read_guard_list.py"] = ["test_read_guard_list"]
# fixes-0800 (#685): the guard hooks check, and its fourth copy of the hook path reader.
for _key in ("template/System/tools/check.py", "extras/status/settings_guard.py", "extras/hooks/zone_guard.py",
             "extras/hooks/read_guard.py", "tests/test_guard_hooks_check.py", "update.py"):
    TOUCH_MAP[_key] = TOUCH_MAP.get(_key, []) + ["test_guard_hooks_check"]
TOUCH_MAP["template/System/tools/check.py"] = TOUCH_MAP["template/System/tools/check.py"] + ["test_hook_path"]

# mornings-0800 (#686): one morning brief across the zones, from the band's ranking, sent by the todo sweep.
for _key, _mods in (("template/System/tools/next_up.py", ["test_morning_brief"]),
                    ("template/System/tools/notifications.py", ["test_morning_brief"]),
                    ("extras/jobs/todo_sweep.py", ["test_morning_brief", "test_todo"]),
                    ("install.py", ["test_morning_brief"]),
                    ("tests/test_next_up.py", ["test_morning_brief"])):
    TOUCH_MAP[_key] = TOUCH_MAP.get(_key, []) + _mods
# tools-0820 (#702): the remote access manifest is held against the declared verbs and the shipped skills.
for _key in ("extras/remote/manifest.json", "extras/remote/tools/manifest.py", "template/System/tools/operations.py",
             "docs/extras/remote-access.md"):
    TOUCH_MAP[_key] = TOUCH_MAP.get(_key, []) + ["test_remote_manifest"]
# ops-0840 (#716): the commit record is settled from git, and every committing verb is held to it.
for _key in ("extras/status/page_action.py", "template/System/tools/operations.py"):
    TOUCH_MAP[_key] = TOUCH_MAP.get(_key, []) + ["test_op_record", "test_op_record_perform", "test_op_record_scaffold"]
TOUCH_MAP["template/System/tools/scaffold.py"] = TOUCH_MAP.get("template/System/tools/scaffold.py", []) + ["test_op_record_scaffold"]
# fixes-0850 (#722): a git lock is waited out and gets its own words.
for _key in ("extras/status/page_action.py", "template/System/tools/operations.py"):
    TOUCH_MAP[_key] = TOUCH_MAP.get(_key, []) + ["test_git_lock"]
# fixes-0850 (#721): a filesystem path is not wording in the repeated-wording check.
TOUCH_MAP["template/System/tools/check.py"] = TOUCH_MAP["template/System/tools/check.py"] + ["test_wall_paths"]
# Modules no mapped path reaches: they check the whole repository, so only the full suite runs them.
FULL_ONLY = {
    "test_autonomy", "test_check_conventions", "test_check_rules", "test_cleanroom",
    "test_cleanroom_worktree", "test_demo", "test_example", "test_git_env", "test_install",
    "test_jobs", "test_onboarding", "test_rules_map", "test_setup",
    "test_layout", "test_layout_control",
    "test_party_flags", "test_checkpoint", "test_cmux", "test_cmux_sidebar", "test_decide", "test_executor",
    "test_fetch", "test_knowledge_skill", "test_lib", "test_meetings", "test_memory_canary",
    "test_mod", "test_nested_checkout", "test_open_sections",
    "test_pathspec_commit", "test_reading", "test_refusals",
    "test_staged_paths", "test_walls_cases", "test_wiki_answers", "test_wrap",
}
# A change here can break anything: the full suite runs.
ALWAYS_FULL = (".github/", "tests/fixtures.py")
ALWAYS_FULL_NAMES = {"garrick_lib.py"}
RUNNER_LOST = "not acquired by runner"
# The jobs of tests.yml that run no tests.
NOT_TEST_JOBS = {"Plan", "Tests", "Rerun a lost runner"}
# viewmodel-0810 (#650): the jobs folder and the launchd agents have a reader in the core.
for _key, _mods in (("template/System/tools/view_jobs.py", ["test_view_rest", "test_view_model", "test_status", "test_status_more", "test_jobs"]),
                    ("tests/test_view_rest.py", ["test_view_rest"]),
                    ("tests/old_status_reads_0800.py", ["test_view_rest"])):
    TOUCH_MAP[_key] = TOUCH_MAP.get(_key, []) + _mods
for _key in ("template/System/tools/view.py", "extras/status/status.py", "docs/architecture.md"):
    TOUCH_MAP[_key] = TOUCH_MAP.get(_key, []) + ["test_view_rest"]
TOUCH_MAP["extras/status/workspace_find.py"] = ["test_view_rest", "test_status", "test_status_find", "test_status_finder", "test_threads_card"]
TOUCH_MAP["template/System/tools/view_app.py"] = ["test_view_rest", "test_view_model", "test_status", "test_status_more", "test_status_work",
                                                 "test_overview_work", "test_context_card", "test_inbox_run", "test_finding_queue"]

# core-0820 (#701): the remote caller and the durable record of a note, a reworded line and a retired one.
for _key in ("extras/status/page_action.py", "template/System/tools/operations.py", "extras/status/outbox.py"):
    TOUCH_MAP[_key] = TOUCH_MAP.get(_key, []) + ["test_remote_caller", "test_remote_verb", "test_remote_record"]
# remote-0820 (#695, #696, #697, #698): remote access (preview), an extra with its own runtime. A change to the extra runs the core modules that
# read it on the Python macOS ships; the extra's own tests need its runtime and have a job of their own (tests.yml, "Remote access extra").
TOUCH_MAP["extras/remote/"] = ["test_remote_state", "test_remote_runtime", "test_remote_address", "test_remote_imports", "test_remote_context",
                               "test_remote_settings", "test_remote_notice"]
for _key in ("extras/status/settings_remote.py", "template/System/tools/view_settings.py"):
    TOUCH_MAP[_key] = TOUCH_MAP.get(_key, []) + ["test_remote_settings", "test_remote_imports"]
for _key in ("extras/status/status.py",):
    TOUCH_MAP[_key] = TOUCH_MAP.get(_key, []) + ["test_remote_settings"]
# app-0830 (#711): empty states and counts, on the built page.
for _key in ("extras/status/status.py", "tests/test_empty_states.py"):
    TOUCH_MAP[_key] = TOUCH_MAP.get(_key, []) + ["test_empty_states"]


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
