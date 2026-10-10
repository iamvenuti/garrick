"""The optional scheduled-jobs extra, extras/jobs/, against fake assistants.

    python3 -m unittest discover -s tests

No assistant is ever called: a fake `claude` and a fake `codex` on PATH record
what they were asked and answer like the real ones. Invented names only.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import plistlib
import re
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import build_workspace, thread_note, write  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
JOBS = REPO / "extras" / "jobs"
sys.path.insert(0, str(JOBS))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


agent = _load("agent", JOBS / "agent.py")
job = _load("garrick_job", JOBS / "job.py")
whats_open = _load("garrick_whats_open", JOBS / "whats_open.py")

# How the status page reads a run from a job's log: a run's last line, or a skip.
LOGLINE = re.compile(r"^===== (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)  (\S+)  (?:exit (-?\d+)  \((\d+)s\)|skipped)", re.M)

SAMPLE = {
    "type": "result", "subtype": "success", "is_error": False, "num_turns": 3,
    "result": "Filed two mails.\nSWEEP_COMPLETE", "total_cost_usd": 0.42,
    "permission_denials": [{"tool_name": "Bash", "tool_input": {"command": "python3 -c 'print(1)'"}}],
}

FAKE_CLAUDE = r'''
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps(args) + "\n")
if args[:2] == ["auth", "status"]:
    print(json.dumps({"loggedIn": os.environ.get("FAKE_LOGGED_IN", "1") == "1"}))
elif args[:2] == ["mcp", "list"]:
    print("Checking MCP server health...\n\nclaude.ai Gmail: https://example.invalid/mcp - Connected")
else:
    import time
    time.sleep(float(os.environ.get("FAKE_SLEEP", "0")))
    result = os.environ.get("FAKE_RESULT", "# Brief\n- Pricing: send the draft\nEND OF BRIEF")
    print("a warning line before the JSON")
    print(json.dumps({"type": "result", "subtype": os.environ.get("FAKE_SUBTYPE", "success"), "is_error": False,
                      "num_turns": 2, "result": result, "total_cost_usd": 0.25,
                      "modelUsage": {"sonnet-test": {}}, "permission_denials": [{"tool_name": "Bash"}]}))
'''

FAKE_CODEX = r'''
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps(args) + "\n")
if args[:2] == ["login", "status"]:
    print("Logged in using ChatGPT")
elif "-o" in args:
    open(args[args.index("-o") + 1], "w").write("Codex answer\nSWEEP_COMPLETE\n")
    print("the whole run, prompt included")
'''


class FakeAssistants(unittest.TestCase):
    """A temporary jobs folder and fake assistants first on PATH."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        for name, body in (("claude", FAKE_CLAUDE), ("codex", FAKE_CODEX)):
            exe = self.bin / name
            exe.write_text("#!%s\n%s" % (sys.executable, body), encoding="utf-8")
            exe.chmod(0o755)
        self.log = self.tmp / "calls.jsonl"
        self.jobs = self.tmp / "jobs"
        env = {"PATH": "%s%s%s" % (self.bin, os.pathsep, os.environ.get("PATH", "")),
               "FAKE_LOG": str(self.log), "GARRICK_JOBS_DIR": str(self.jobs), "GARRICK_HARNESS": "claude",
               "GARRICK_LOGIN_RETRY_AFTER": "0"}
        self.env = mock.patch.dict(os.environ, env)
        self.env.start()
        # The extra reports to stdout and stderr; keep the suite's output to its own.
        self.quiet = [mock.patch("sys.stdout", new_callable=io.StringIO),
                      mock.patch("sys.stderr", new_callable=io.StringIO)]
        for q in self.quiet:
            q.start()
        for key in ("GARRICK_CAP_CALLS_DAY", "GARRICK_CAP_CALLS_HOUR", "GARRICK_CAP_COST_DAY", "GARRICK_JOB",
                    "GARRICK_ITEMS_FILE", "FAKE_RESULT", "FAKE_LOGGED_IN", "FAKE_SLEEP", "FAKE_SUBTYPE",
                    "GARRICK_NOTIFY", "GARRICK_NOTIFY_CMD", "GARRICK_QUIET_EXITS", "GARRICK_ALERT_REPEAT",
                    "GARRICK_IDLE_DAYS", "GARRICK_ENV_FILE", "GARRICK_JOB_TIMEOUT"):
            os.environ.pop(key, None)

    def tearDown(self):
        for q in self.quiet:
            q.stop()
        self.env.stop()
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def calls(self):
        if not self.log.exists():
            return []
        return [json.loads(l) for l in self.log.read_text().splitlines()]

    def ledger(self):
        path = self.jobs / "ledger.jsonl"
        return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []


class ParseTest(unittest.TestCase):
    def test_result_and_numbers_from_the_json(self):
        out = agent.parse_claude_output("a warning\n" + json.dumps(SAMPLE) + "\n")
        self.assertEqual("Filed two mails.\nSWEEP_COMPLETE", out["text"])
        self.assertEqual((3, 0.42, ["Bash"], "success"), (out["turns"], out["cost_usd"], out["denied"], out["subtype"]))
        self.assertTrue(out["parsed"])

    def test_not_json_passes_through_with_unknown_numbers(self):
        out = agent.parse_claude_output("Not logged in. Please run /login\n")
        self.assertEqual("Not logged in. Please run /login\n", out["text"])
        self.assertIsNone(out["turns"])
        self.assertIsNone(out["cost_usd"])
        self.assertFalse(out["parsed"])


class LedgerTest(unittest.TestCase):
    def entry(self, ago, cost=0.1, refused=""):
        e = {"ts": self.now - ago, "job": "sweep", "cost_usd": cost}
        if refused:
            e["refused"] = refused
        return e

    def setUp(self):
        self.now = 1_800_000_000.0
        self.limits = {"calls_day": 5, "calls_hour": 2, "cost_day": 1.0}

    def test_read_skips_bad_lines_and_old_entries(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "ledger.jsonl"
            path.write_text("\n".join([json.dumps(self.entry(60)), "{half a line", "[1, 2]",
                                       json.dumps(self.entry(90000)), json.dumps({"ts": "soon"})]) + "\n")
            self.assertEqual(1, len(agent.read_ledger(path, self.now)))
            self.assertEqual([], agent.read_ledger(Path(d) / "missing.jsonl", self.now))

    def test_the_ledger_keeps_sixty_days(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "ledger.jsonl"
            now = time.time()
            old = [{"ts": now - days * 86400, "job": "sweep"} for days in (90, 61.5)]
            recent = [{"ts": now - days * 86400, "job": "sweep"} for days in (30, 0.1)]
            path.write_text("".join(json.dumps(e) + "\n" for e in old + recent) + "{half a line\n")
            agent.append_ledger(path, {"ts": now, "job": "sweep"})
            self.assertEqual([e["ts"] for e in recent] + [now],
                             [json.loads(line)["ts"] for line in path.read_text().splitlines()])
            self.assertEqual(["ledger.jsonl"], [p.name for p in Path(d).iterdir()])

    def test_the_ledger_is_rewritten_once_a_day_at_most(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "ledger.jsonl"
            now = time.time()
            path.write_text(json.dumps({"ts": now - 60.5 * 86400, "job": "sweep"}) + "\n")
            agent.append_ledger(path, {"ts": now, "job": "sweep"})
            self.assertEqual(2, len(path.read_text().splitlines()))   # half a day past: left for now

    def test_under_every_cap(self):
        self.assertIsNone(agent.cap_reason([self.entry(7200), self.entry(30)], self.now, self.limits))

    def test_hour_cap(self):
        reason = agent.cap_reason([self.entry(60), self.entry(120)], self.now, self.limits)
        self.assertIn("last hour", reason)

    def test_day_cap(self):
        entries = [self.entry(4000 * i, cost=0) for i in range(1, 6)]
        self.assertIn("last 24 hours", agent.cap_reason(entries, self.now, self.limits))

    def test_cost_cap(self):
        entries = [self.entry(5000, cost=0.6), self.entry(9000, cost=0.5)]
        self.assertIn("$1.10", agent.cap_reason(entries, self.now, self.limits))

    def test_refusals_do_not_count(self):
        entries = [self.entry(60, cost=0, refused="cap"), self.entry(90, cost=0, refused="cap")]
        self.assertIsNone(agent.cap_reason(entries, self.now, self.limits))

    def test_zero_removes_a_cap(self):
        entries = [self.entry(60), self.entry(120), self.entry(180)]
        self.assertIsNone(agent.cap_reason(entries, self.now, {"calls_day": 0, "calls_hour": 0, "cost_day": 0}))


class ProfileTest(unittest.TestCase):
    def test_profile_denies_sending_sharing_and_deleting(self):
        deny = set(json.loads((JOBS / "headless-settings.json").read_text())["permissions"]["deny"])
        for tool in ("mcp__claude_ai_Gmail__send_message", "mcp__claude_ai_Gmail__reply",
                     "mcp__claude_ai_Gmail__forward", "mcp__claude_ai_Gmail__trash_thread",
                     "mcp__claude_ai_Google_Drive__share_file", "mcp__claude_ai_Google_Calendar__create_event",
                     "mcp__claude_ai_Notion__notion-create-comment", "Bash(git push:*)", "Bash(curl:*)",
                     "Bash(rm:*)", "Edit(System/**)", "Write(**/.git/**)",
                     # Publishing a document, starting another agent, and driving a browser or the screen.
                     "mcp__claude_ai_Claude_Docs__create", "mcp__claude_ai_Notion__notion-spawn-session",
                     "mcp__claude-in-chrome", "mcp__cmux-cua",
                     # A user-level allow would otherwise reach a job: the web is denied outright.
                     "WebFetch", "WebSearch"):
            self.assertIn(tool, deny, tool)

    def test_profile_keeps_the_core_set(self):
        # The entries agent.py refuses to run without: an edit that drops one stops every Claude job.
        deny = json.loads((JOBS / "headless-settings.json").read_text())["permissions"]["deny"]
        self.assertEqual([], [t for t in agent.CORE_DENY if t not in deny])
        self.assertIsNone(agent.profile_problem(JOBS / "headless-settings.json"))
        for core in ("mcp__claude_ai_Gmail__send_message", "mcp__claude_ai_Google_Drive__share_file",
                     "Bash(git push:*)", "Bash(rm:*)"):
            self.assertIn(core, agent.CORE_DENY)

    def test_claude_command(self):
        cmd = agent.claude_command("sonnet", "Do the sweep.", ["Read", "Grep"], 5)
        self.assertEqual(["claude", "-p", "Do the sweep.", "--model", "sonnet"], cmd[:5])
        # The allow list is the whole truth: no mode that accepts edits it does not name.
        self.assertEqual("default", cmd[cmd.index("--permission-mode") + 1])
        self.assertNotIn("acceptEdits", cmd)
        self.assertEqual(str(agent.PROFILE), cmd[cmd.index("--settings") + 1])
        self.assertEqual("user,project", cmd[cmd.index("--setting-sources") + 1])
        self.assertEqual("json", cmd[cmd.index("--output-format") + 1])
        self.assertEqual("5", cmd[cmd.index("--max-budget-usd") + 1])
        self.assertEqual(["--allowedTools", "Read", "Grep"], cmd[-3:])
        self.assertNotIn("--max-budget-usd", agent.claude_command("haiku", "x", [], 0))

    def test_codex_command_takes_its_model_from_the_tier(self):
        with mock.patch.dict(os.environ, {"GARRICK_CODEX_MODEL_SONNET": "some-model"}):
            cmd = agent.codex_command("sonnet", "Do it.", Path("/tmp/last.txt"), ["Read", "Edit"])
        self.assertEqual(["codex", "exec", "-m", "some-model"], cmd[:4])
        self.assertEqual("workspace-write", cmd[cmd.index("--sandbox") + 1])
        self.assertEqual("Do it.", cmd[-1])
        self.assertNotIn("--allowedTools", cmd)
        self.assertNotIn("--ignore-user-config", cmd)        # a job that writes may need its connectors

    def test_a_codex_job_that_only_reads_cannot_write_or_reach_out(self):
        # Checked by hand against Codex 0.160.0: run this way, a shell command
        # writing a file failed with "operation not permitted", and the run had
        # no web search, browser, app or connector tools; run with the
        # workspace-write command above, the file was written and those tools
        # were there.
        for allow in ([], ["Read"], ["Read", "Grep", "Glob"]):
            cmd = agent.codex_command("sonnet", "Brief.", Path("/tmp/last.txt"), allow)
            self.assertEqual("read-only", cmd[cmd.index("--sandbox") + 1], allow)
            for flag in ("--ignore-user-config", "--ephemeral", 'web_search="disabled"', 'approval_policy="never"'):
                self.assertIn(flag, cmd)
            disabled = {cmd[i + 1] for i, c in enumerate(cmd) if c == "--disable"}
            self.assertTrue({"apps", "plugins", "browser_use", "computer_use"} <= disabled)
        for allow in (["Edit"], ["Write"], ["Bash"], ["mcp__gmail__search"]):
            cmd = agent.codex_command("sonnet", "Sweep.", Path("/tmp/last.txt"), allow)
            self.assertEqual("workspace-write", cmd[cmd.index("--sandbox") + 1], allow)

    def test_connector_listing(self):
        listing = ("Checking MCP server health...\n\nclaude.ai Gmail: https://x.invalid - Connected\n"
                   "claude.ai Notion: https://y.invalid - Failed to connect\nrecorder: npx rec - Connected\n")
        self.assertEqual([], agent.connectors_available(["gmail", "recorder"], listing))
        self.assertEqual(["notion"], agent.connectors_available(["gmail", "notion"], listing))
        table = "Name    Command   Status\nmail    mail-mcp  enabled\n"
        self.assertEqual([], agent.connectors_available(["mail"], table))

    def test_launchd_example_is_a_valid_plist(self):
        plist = plistlib.loads((JOBS / "launchd" / "garrick.whats-open.plist").read_bytes())
        args = plist["ProgramArguments"]
        self.assertTrue(args[1].endswith("System/jobs/job.py"))
        self.assertIn("--agent", args)
        self.assertIn("--", args)
        # What job.py cannot log itself lands beside the jobs' logs, never in the log job.py rotates.
        for key in ("StandardOutPath", "StandardErrorPath"):
            self.assertEqual("/Users/<you>/Library/Logs/garrick-jobs/whats-open.launchd.log", plist[key])


class RunTest(FakeAssistants):
    def test_claude_prints_only_the_answer_and_logs_the_call(self):
        os.environ["GARRICK_JOB"] = "sweep"
        code, text = agent.run("sonnet", "Sweep.", allow=["Read"])
        self.assertEqual(0, code)
        self.assertTrue(text.endswith("END OF BRIEF"))
        self.assertNotIn("warning", text)
        (line,) = self.ledger()
        self.assertEqual(("sweep", "claude", "sonnet", 2, 0.25, 0, ["Bash"]),
                         (line["job"], line["harness"], line["tier"], line["turns"], line["cost_usd"],
                          line["exit"], line["denied"]))
        call = self.calls()[0]
        self.assertIn("--setting-sources", call)
        self.assertEqual("default", call[call.index("--permission-mode") + 1])
        self.assertNotIn("acceptEdits", call)
        self.assertEqual(["--allowedTools", "Read"], call[-2:])

    def test_a_cap_refuses_without_calling(self):
        os.environ["GARRICK_CAP_CALLS_HOUR"] = "1"
        self.assertEqual(0, agent.run("haiku", "One.")[0])
        code, text = agent.run("haiku", "Two.")
        self.assertEqual(agent.EXIT_CAP, code)
        self.assertEqual("", text)
        self.assertEqual(1, len(self.calls()))
        self.assertIn("refused", self.ledger()[-1])

    def test_codex_returns_the_last_message_and_keeps_the_transcript(self):
        os.environ["GARRICK_HARNESS"] = "codex"
        code, text = agent.run("sonnet", "Sweep.", allow=["Read"])
        self.assertEqual(0, code)
        call = self.calls()[0]
        self.assertEqual("read-only", call[call.index("--sandbox") + 1])   # the allow list reaches Codex
        self.assertEqual("Codex answer\nSWEEP_COMPLETE\n", text)
        self.assertIn("the whole run", (self.jobs / "manual.transcript.log").read_text())
        line = self.ledger()[0]
        self.assertIsNone(line["turns"])
        self.assertIsNone(line["cost_usd"])

    def test_no_deny_profile_no_call(self):
        broken = self.tmp / "headless-settings.json"
        broken.write_text('{"permissions": {"deny": ["WebFetch",]}}')     # a trailing comma
        for profile in (self.tmp / "nowhere" / "headless-settings.json", broken):
            with mock.patch.object(agent, "PROFILE", profile):
                self.assertEqual((agent.EXIT_USAGE, ""), agent.run("sonnet", "Sweep.", allow=["Read"]))
        self.assertEqual([], self.calls())
        self.assertEqual([], self.ledger())
        self.assertIn("deny profile", sys.stderr.getvalue())
        os.environ["GARRICK_HARNESS"] = "codex"                          # Codex loads no profile
        with mock.patch.object(agent, "PROFILE", self.tmp / "nowhere" / "headless-settings.json"):
            self.assertEqual(0, agent.run("sonnet", "Sweep.")[0])

    def test_a_profile_that_lost_a_core_entry_no_call(self):
        trimmed = self.tmp / "headless-settings.json"
        deny = [t for t in agent.CORE_DENY if t != "mcp__claude_ai_Gmail__forward"] + ["WebFetch"]
        trimmed.write_text(json.dumps({"permissions": {"deny": deny}}))
        with mock.patch.object(agent, "PROFILE", trimmed):
            self.assertEqual((agent.EXIT_USAGE, ""), agent.run("sonnet", "Sweep.", allow=["Read"]))
        self.assertIn("no longer denies mcp__claude_ai_Gmail__forward", sys.stderr.getvalue())
        for broken in ({"permissions": {}}, {"permissions": {"deny": "WebFetch"}}, ["WebFetch"]):
            trimmed.write_text(json.dumps(broken))
            with mock.patch.object(agent, "PROFILE", trimmed):
                self.assertEqual(agent.EXIT_USAGE, agent.run("sonnet", "Sweep.")[0], broken)
        self.assertEqual([], self.calls())
        self.assertEqual([], self.ledger())
        trimmed.write_text(json.dumps({"permissions": {"deny": list(agent.CORE_DENY)}}))
        with mock.patch.object(agent, "PROFILE", trimmed):              # the core set alone is enough
            self.assertEqual(0, agent.run("sonnet", "Sweep.")[0])

    def test_a_job_name_is_one_plain_word(self):
        for name in ("../escape", "two words", "agent"):
            self.assertEqual(agent.EXIT_USAGE, agent.run("sonnet", "Sweep.", job=name)[0], name)
        self.assertEqual([], self.calls())
        self.assertEqual(0, agent.run("sonnet", "Sweep.", job="whats-open_2")[0])

    def test_the_codex_transcript_is_rotated_like_the_log(self):
        os.environ["GARRICK_HARNESS"] = "codex"
        self.jobs.mkdir(parents=True)
        transcript = self.jobs / "manual.transcript.log"
        transcript.write_text("x" * (agent.MAX_LOG_BYTES + 1))
        self.assertEqual(0, agent.run("sonnet", "Sweep.")[0])
        self.assertEqual(agent.MAX_LOG_BYTES + 1, (self.jobs / "manual.transcript.log.1").stat().st_size)
        self.assertEqual("the whole run, prompt included\n", transcript.read_text())

    def test_unknown_harness_and_tier(self):
        os.environ["GARRICK_HARNESS"] = "other"
        self.assertEqual(agent.EXIT_USAGE, agent.run("sonnet", "x")[0])
        os.environ["GARRICK_HARNESS"] = "claude"
        self.assertEqual(agent.EXIT_USAGE, agent.run("claude-model-id", "x")[0])

    def test_login_and_requires(self):
        self.assertTrue(agent.login_ok(self.tmp))
        os.environ["FAKE_LOGGED_IN"] = "0"
        self.assertFalse(agent.login_ok(self.tmp))
        self.assertEqual(0, agent.requires(["gmail"], self.tmp))
        self.assertEqual(agent.EXIT_CONNECTOR, agent.requires(["calendar"], self.tmp))


class JobTest(FakeAssistants):
    def job(self, *args, env=None):
        return subprocess.run([sys.executable, str(JOBS / "job.py")] + list(args),
                              env=dict(os.environ, **(env or {})), capture_output=True, text=True)

    def beat(self, name):
        return json.loads((self.jobs / ("%s.heartbeat.json" % name)).read_text())

    def test_a_run_leaves_a_log_and_a_heartbeat(self):
        script = "import os; open(os.environ['GARRICK_ITEMS_FILE'], 'w').write('3')"
        r = self.job("tidy", "--cwd", str(self.tmp), "--", sys.executable, "-c", script)
        self.assertEqual(0, r.returncode, r.stderr)
        beat = self.beat("tidy")
        self.assertEqual((0, 3, 0), (beat["exit"], beat["items"], beat["idle_days"]))
        self.assertIn("tidy  exit 0", (self.jobs / "tidy.log").read_text())

    def test_a_held_lock_skips_the_run(self):
        self.jobs.mkdir(parents=True)
        (self.jobs / "tidy.lock").mkdir()
        running = "x" * (1024 * 1024 + 1)                  # the running job's log, due for rotation
        (self.jobs / "tidy.log").write_text(running)
        (self.jobs / "tidy.items").write_text("4\n")
        r = self.job("tidy", "--", sys.executable, "-c", "print('ran')")
        self.assertEqual(75, r.returncode)
        log = (self.jobs / "tidy.log").read_text()
        self.assertNotIn("ran", log)
        self.assertTrue(log.startswith(running))           # a skipped fire neither rotates its log
        self.assertFalse((self.jobs / "tidy.log.1").exists())
        self.assertEqual("4\n", (self.jobs / "tidy.items").read_text())  # nor deletes its count

    def test_waiting_out_the_shared_lock_skips_the_run(self):
        self.jobs.mkdir(parents=True)
        (self.jobs / "agent.lock").mkdir()                     # another assistant job, still going
        started = time.time()
        r = self.job("sweep", "--agent", "--timeout", "1", "--cwd", str(self.tmp), "--",
                     sys.executable, "-c", "print('ran')")
        self.assertEqual(75, r.returncode)
        self.assertLess(time.time() - started, 10)
        log = (self.jobs / "sweep.log").read_text()
        self.assertNotIn("ran", log)
        self.assertEqual([("sweep", None)], [(m.group(2), m.group(3)) for m in LOGLINE.finditer(log)])
        self.assertEqual([], self.calls())                     # not even the sign-in check
        self.assertTrue((self.jobs / "agent.lock").exists())   # not this run's to remove
        self.assertFalse((self.jobs / "sweep.lock").exists())
        self.assertFalse((self.jobs / "sweep.heartbeat.json").exists())

    def test_a_lock_stands_as_long_as_its_holder_said(self):
        self.jobs.mkdir(parents=True)
        lock = self.jobs / "tidy.lock"
        lock.mkdir()
        (lock / "until").write_text("%d 1\n" % (time.time() + 3600))
        long_ago = time.time() - 7200
        os.utime(lock, (long_ago, long_ago))                   # older than this run's own limit allows
        tidy = ("tidy", "--timeout", "1", "--", sys.executable, "-c", "print('ran')")
        self.assertEqual(75, self.job(*tidy).returncode)
        (lock / "until").write_text("%d 1\n" % (time.time() - 1))   # the holder's time is up
        self.assertEqual(0, self.job(*tidy).returncode)
        self.assertIn("ran", (self.jobs / "tidy.log").read_text())
        self.assertFalse(lock.exists())

    def test_a_lock_without_a_record_goes_stale_by_its_age(self):
        self.jobs.mkdir(parents=True)
        lock = self.jobs / "tidy.lock"
        lock.mkdir()
        long_ago = time.time() - 7200
        os.utime(lock, (long_ago, long_ago))
        self.assertEqual(0, self.job("tidy", "--timeout", "1", "--", sys.executable, "-c", "pass").returncode)

    def test_the_locks_cover_the_wait_the_retry_and_the_run(self):
        script = ("import os; d = os.environ['GARRICK_JOBS_DIR']; "
                  "print(*(open(os.path.join(d, n, 'until')).read().split()[0] for n in ('tidy.lock', 'agent.lock')))")
        before = time.time()
        r = self.job("tidy", "--agent", "--timeout", "100", "--cwd", str(self.tmp), "--", sys.executable, "-c", script,
                     env={"GARRICK_LOGIN_RETRY_AFTER": "300"})
        self.assertEqual(0, r.returncode, r.stderr)
        until = re.search(r"^(\d+) (\d+)$", (self.jobs / "tidy.log").read_text(), re.M)
        job_until, agent_until = float(until.group(1)), float(until.group(2))
        self.assertGreaterEqual(job_until - before, 2 * 100 + 300)   # the wait for the shared lock, the retry, the run
        self.assertGreaterEqual(agent_until - before, 100 + 300)     # the retry and the run
        self.assertFalse((self.jobs / "tidy.lock").exists())
        self.assertFalse((self.jobs / "agent.lock").exists())

    def test_a_run_removes_only_its_own_lock(self):
        self.jobs.mkdir(parents=True)
        lock = self.jobs / "tidy.lock"
        self.assertTrue(job.take_lock(lock, 60))
        self.assertFalse(job.take_lock(lock, 60))
        (lock / "until").write_text("%d 1\n" % (time.time() + 60))   # since taken over by another run
        job.release(lock)
        self.assertTrue(lock.exists())
        (lock / "until").write_text("%d %d\n" % (time.time() + 60, os.getpid()))
        job.release(lock)
        self.assertFalse(lock.exists())

    def test_a_name_that_is_not_one_plain_word_is_refused(self):
        for name in ("../escape", "two words", "Agent"):
            r = self.job(name, "--", sys.executable, "-c", "print('ran')")
            self.assertEqual(agent.EXIT_USAGE, r.returncode, name)
            self.assertIn("job.py:", r.stderr)
        self.assertFalse(self.jobs.exists())                   # nothing written, inside the folder or out
        self.assertEqual([], list(self.tmp.glob("escape*")))
        self.assertEqual(0, self.job("whats-open_2", "--", sys.executable, "-c", "pass").returncode)

    def test_the_watchdog_stops_a_run(self):
        started = time.time()
        r = self.job("slow", "--timeout", "1", "--", sys.executable, "-c", "import time; time.sleep(30)")
        self.assertEqual(124, r.returncode)
        self.assertLess(time.time() - started, 20)

    def test_agent_job_that_cannot_sign_in_does_not_run(self):
        r = self.job("sweep", "--agent", "--cwd", str(self.tmp), "--", sys.executable, "-c", "print('ran')",
                     env={"FAKE_LOGGED_IN": "0"})
        self.assertEqual(4, r.returncode)
        self.assertNotIn("ran", (self.jobs / "sweep.log").read_text())
        self.assertFalse((self.jobs / "agent.lock").exists())

    def test_idle_after_days_of_nothing(self):
        self.jobs.mkdir(parents=True)
        (self.jobs / "sweep.lastwork").write_text("%d\n" % (time.time() - 9 * 86400))
        script = "import os; open(os.environ['GARRICK_ITEMS_FILE'], 'w').write('0')"
        self.job("sweep", "--", sys.executable, "-c", script)
        self.assertEqual(9, self.beat("sweep")["idle_days"])
        self.assertIn("idle", (self.jobs / "sweep.log").read_text())

    def test_a_setting_that_is_not_a_number_falls_back(self):
        self.jobs.mkdir(parents=True)
        (self.jobs / "sweep.lastwork").write_text("%d\n" % (time.time() - 9 * 86400))
        script = "import os; open(os.environ['GARRICK_ITEMS_FILE'], 'w').write('0')"
        r = self.job("sweep", "--agent", "--cwd", str(self.tmp), "--", sys.executable, "-c", script,
                     env={"GARRICK_JOB_TIMEOUT": "half an hour", "GARRICK_LOGIN_RETRY_AFTER": "soon",
                          "GARRICK_IDLE_DAYS": "seven"})
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual(9, self.beat("sweep")["idle_days"])       # the run finished and left its heartbeat
        log = (self.jobs / "sweep.log").read_text()
        for name in ("GARRICK_JOB_TIMEOUT", "GARRICK_LOGIN_RETRY_AFTER", "GARRICK_IDLE_DAYS"):
            self.assertIn("job: %s is " % name, log)
        self.assertIn("job: idle", log)                             # seven days, the default, still applied


class RunnerExtrasTest(FakeAssistants):
    def test_a_call_past_its_timeout_is_stopped(self):
        os.environ["FAKE_SLEEP"] = "30"
        started = time.time()
        code, _ = agent.run("sonnet", "Sweep.", timeout=1)
        self.assertEqual(agent.EXIT_TIMEOUT, code)
        self.assertLess(time.time() - started, 20)
        self.assertEqual(124, self.ledger()[-1]["exit"])
        self.assertIn("--timeout", sys.stderr.getvalue())

    def test_a_call_stopped_by_its_budget_exits_as_a_cap(self):
        os.environ["FAKE_SUBTYPE"] = "error_max_budget_usd"
        code, _ = agent.run("sonnet", "Sweep.")
        self.assertEqual(agent.EXIT_CAP, code)
        line = self.ledger()[-1]
        self.assertEqual((8, "error_max_budget_usd", "sonnet-test"), (line["exit"], line["subtype"], line["model"]))

    def test_the_prompt_as_an_argument(self):
        self.assertEqual(0, agent.main(["run", "--tier", "haiku", "--prompt", "Say hello.", "--allow", "Read"]))
        call = self.calls()[0]
        self.assertEqual("Say hello.", call[call.index("-p") + 1])
        self.assertTrue(sys.stdout.getvalue().endswith("END OF BRIEF\n"))

    def test_items_from_an_answer(self):
        self.assertEqual(4, agent.items_from("Filed four.\nITEMS 2\nmore\nITEMS 4\n"))
        self.assertIsNone(agent.items_from("I handled ITEMS 3 of them"))   # a line of its own, or nothing
        self.assertIsNone(agent.items_from(""))

    def test_items_from_the_shell(self):
        items = self.tmp / "sweep.items"
        os.environ["GARRICK_ITEMS_FILE"] = str(items)
        answer = self.tmp / "answer.txt"
        answer.write_text("Swept.\nSWEEP_COMPLETE\n")
        self.assertEqual(0, agent.main(["items-from", str(answer)]))
        self.assertFalse(items.exists())                          # no line, no report: not zero
        answer.write_text("Swept.\nITEMS 7\nSWEEP_COMPLETE\n")
        self.assertEqual(0, agent.main(["items-from", str(answer)]))
        self.assertEqual("7\n", items.read_text())
        self.assertEqual(0, agent.main(["items", "0"]))
        self.assertEqual("0\n", items.read_text())
        self.assertEqual(0, agent.main(["items-from", str(self.tmp / "missing.txt")]))

    def test_a_sign_in_check_that_does_not_answer_is_not_a_no(self):
        with mock.patch.object(agent.subprocess, "run", side_effect=subprocess.TimeoutExpired("claude", 90)):
            self.assertIsNone(agent.login_state(self.tmp))
            self.assertTrue(agent.login_ok(self.tmp))
            self.assertEqual(0, agent.main(["login"]))
        os.environ["FAKE_LOGGED_IN"] = "0"
        self.assertIs(False, agent.login_state(self.tmp))
        self.assertEqual(1, agent.main(["login"]))


NOTIFIER = r'''
import json, os, sys
with open(os.environ["NOTICES"], "a") as f:
    f.write(json.dumps({"title": sys.argv[1], "message": sys.argv[2], "kind": os.environ["GARRICK_NOTIFY_KIND"],
                        "job": os.environ["GARRICK_JOB"], "exit": os.environ["GARRICK_EXIT"]}) + "\n")
sys.exit(int(os.environ.get("NOTIFIER_EXIT", "0")))
'''


class NoticeTest(FakeAssistants):
    """job.py's notices, through a notifier command that records what it was given."""

    def setUp(self):
        super().setUp()
        self.notices_file = self.tmp / "notices.jsonl"
        notifier = self.tmp / "notifier.py"
        notifier.write_text(NOTIFIER, encoding="utf-8")
        os.environ["GARRICK_NOTIFY_CMD"] = "%s %s" % (sys.executable, notifier)
        os.environ["NOTICES"] = str(self.notices_file)

    def job(self, name, code=0, items=None, *flags, env=None):
        script = "import os, sys\n"
        if items is not None:
            script += "open(os.environ['GARRICK_ITEMS_FILE'], 'w').write('%d')\n" % items
        script += "sys.exit(%d)\n" % code
        return subprocess.run([sys.executable, str(JOBS / "job.py"), name] + list(flags)
                              + ["--", sys.executable, "-c", script],
                              env=dict(os.environ, **(env or {})), capture_output=True, text=True)

    def notices(self):
        if not self.notices_file.exists():
            return []
        return [json.loads(l) for l in self.notices_file.read_text().splitlines()]

    def beat(self, name):
        return json.loads((self.jobs / ("%s.heartbeat.json" % name)).read_text())

    def test_first_failure_change_of_code_and_recovery(self):
        self.assertEqual(3, self.job("sweep", 3).returncode)
        (first,) = self.notices()
        self.assertEqual(("failed", "Job failed", "sweep", "3"),
                         (first["kind"], first["title"], first["job"], first["exit"]))
        self.assertIn("sweep exited 3 after", first["message"])
        self.assertIn(str(self.jobs / "sweep.log"), first["message"])
        self.job("sweep", 3)
        self.assertEqual(1, len(self.notices()))                       # the same failure, within the hour
        self.job("sweep", 6)
        self.assertEqual(2, len(self.notices()))                       # a new code is news
        self.assertIn("needs a connector claude does not have", self.notices()[-1]["message"])
        state = json.loads((self.jobs / "sweep.alert.json").read_text())
        self.assertEqual(6, state["exit"])
        beat = self.beat("sweep")
        self.assertEqual((False, False, "needs a connector claude does not have; see the log"),
                         (beat["ok"], beat["quiet"], beat["reason"]))
        self.assertTrue(beat["failing_since"])
        self.assertEqual(0, self.job("sweep", 0).returncode)
        last = self.notices()[-1]
        self.assertEqual(("recovered", "0"), (last["kind"], last["exit"]))
        self.assertIn("working again", last["message"])
        self.assertFalse((self.jobs / "sweep.alert.json").exists())
        beat = self.beat("sweep")
        self.assertEqual((True, None, None), (beat["ok"], beat["reason"], beat["failing_since"]))
        self.job("sweep", 0)
        self.assertEqual(3, len(self.notices()))                       # working stays quiet

    def test_a_lasting_failure_repeats_at_its_interval(self):
        self.job("sweep", 3, env={"GARRICK_ALERT_REPEAT": "0"})
        self.job("sweep", 3, env={"GARRICK_ALERT_REPEAT": "0"})
        self.assertEqual(2, len(self.notices()))
        self.assertIn("Still failing", self.notices()[-1]["message"])
        self.assertNotIn("Still failing", self.notices()[0]["message"])

    def test_the_failure_began_when_it_first_failed(self):
        self.jobs.mkdir(parents=True)
        began = time.time() - 7200
        (self.jobs / "sweep.alert.json").write_text(json.dumps({"exit": 3, "since": began, "alerted": began}))
        self.job("sweep", 3)
        self.assertEqual(1, len(self.notices()))                       # an hour gone: once more
        state = json.loads((self.jobs / "sweep.alert.json").read_text())
        self.assertEqual(began, state["since"])
        self.assertEqual(job.stamp(began), self.beat("sweep")["failing_since"])

    def test_quiet_exits_never_notify_and_count_as_working(self):
        self.jobs.mkdir(parents=True)
        (self.jobs / "sweep.lastwork").write_text("%d\n" % (time.time() - 2 * 86400))
        r = self.job("sweep", 5, 0, env={"GARRICK_QUIET_EXITS": "5, 9"})
        self.assertEqual(5, r.returncode)
        self.assertEqual([], self.notices())
        beat = self.beat("sweep")
        self.assertEqual((5, True, True, 0, 2), (beat["exit"], beat["ok"], beat["quiet"], beat["items"],
                                                 beat["idle_days"]))
        log = (self.jobs / "sweep.log").read_text()
        self.assertIn("exit 5  (", log)
        self.assertRegex(log, r"exit 5  \(\d+s\)  quiet =====")
        self.assertEqual([("sweep", "5")], [(m.group(2), m.group(3)) for m in LOGLINE.finditer(log)])
        self.assertFalse((self.jobs / "sweep.alert.json").exists())
        self.job("sweep", 3)
        self.job("sweep", 5, 1, env={"GARRICK_QUIET_EXITS": "5"})
        self.assertEqual(["failed", "recovered"], [n["kind"] for n in self.notices()])   # quiet is working

    def test_a_quiet_exit_that_is_not_a_number_is_left_out(self):
        r = self.job("sweep", 5, env={"GARRICK_QUIET_EXITS": "five 5 300"})
        self.assertEqual([], self.notices())
        log = (self.jobs / "sweep.log").read_text()
        self.assertIn("'five'", log)
        self.assertIn("'300'", log)
        self.assertEqual(5, r.returncode)

    def test_reasons_in_words(self):
        with mock.patch.dict(os.environ, {"GARRICK_HARNESS": "codex"}):
            self.assertEqual("could not sign in to codex, twice", job.describe(4, 3, 1500, "login"))
            self.assertEqual("needs a connector codex does not have; see the log", job.describe(6, 3, 1500))
        self.assertIn("spending cap", job.describe(8, 3, 1500))
        self.assertEqual("timed out and was stopped after 1500s", job.describe(124, 1500, 1500, "timeout"))
        self.assertIn("could not start", job.describe(127, 0, 1500, "start"))
        self.assertEqual("exited 2 after 41s", job.describe(2, 41.4, 1500))
        self.assertEqual("was stopped by SIGKILL after 3s (exit 137)", job.describe(137, 3, 1500, "signal"))

    def test_a_commands_own_exit_is_not_the_wrappers(self):
        # A job that exits 4 or 124 itself did not fail job.py's sign-in check or meet its watchdog.
        for code in (4, 124, 127):
            self.assertEqual(code, self.job("sweep%d" % code, code).returncode)
            self.assertRegex(self.beat("sweep%d" % code)["reason"], r"^exited %d after \d+s$" % code)
            self.assertIn("sweep%d exited %d after" % (code, code), self.notices()[-1]["message"])

    def test_a_command_killed_by_a_signal_exits_as_a_shell_says(self):
        r = subprocess.run([sys.executable, str(JOBS / "job.py"), "sweep", "--",
                            sys.executable, "-c", "import os, signal; os.kill(os.getpid(), signal.SIGKILL)"],
                           env=dict(os.environ), capture_output=True, text=True)
        self.assertEqual(137, r.returncode)
        beat = self.beat("sweep")
        self.assertEqual(137, beat["exit"])
        self.assertIn("was stopped by SIGKILL", beat["reason"])
        self.assertIn("exit 137  (", (self.jobs / "sweep.log").read_text())

    def test_a_timeout_says_so(self):
        r = subprocess.run([sys.executable, str(JOBS / "job.py"), "slow", "--timeout", "1", "--",
                            sys.executable, "-c", "import time; time.sleep(30)"],
                           env=dict(os.environ), capture_output=True, text=True)
        self.assertEqual(124, r.returncode)
        self.assertIn("timed out and was stopped after 1s", self.notices()[0]["message"])
        self.assertIn("job: slow timed out", (self.jobs / "slow.log").read_text())

    def test_the_idle_notice_repeats_every_idle_period(self):
        self.jobs.mkdir(parents=True)
        (self.jobs / "sweep.lastwork").write_text("%d\n" % (time.time() - 9 * 86400))
        self.job("sweep", 0, 0)
        (idle,) = self.notices()
        self.assertEqual(("idle", "Job idle"), (idle["kind"], idle["title"]))
        self.assertIn("9 days", idle["message"])
        self.assertTrue(self.beat("sweep")["idle"])
        self.job("sweep", 0, 0)
        self.assertEqual(1, len(self.notices()))                       # once a week, not every run
        (self.jobs / "sweep.idle-alert").write_text("%d\n" % (time.time() - 8 * 86400))
        self.job("sweep", 0, 0)
        self.assertEqual(2, len(self.notices()))                       # a week on, and still idle
        self.job("sweep", 0, 2)
        self.assertFalse((self.jobs / "sweep.idle-alert").exists())    # it worked: the clock starts again
        self.assertFalse(self.beat("sweep")["idle"])

    def test_zero_idle_days_turns_the_alarm_off(self):
        self.jobs.mkdir(parents=True)
        (self.jobs / "sweep.lastwork").write_text("%d\n" % (time.time() - 30 * 86400))
        self.job("sweep", 0, 0, env={"GARRICK_IDLE_DAYS": "0"})
        self.assertEqual([], self.notices())
        self.assertFalse(self.beat("sweep")["idle"])

    def test_a_failing_notifier_costs_a_line_not_the_run(self):
        r = self.job("sweep", 3, env={"NOTIFIER_EXIT": "2"})
        self.assertEqual(3, r.returncode)
        self.assertIn("job: the notifier exited 2", (self.jobs / "sweep.log").read_text())
        r = self.job("other", 3, env={"GARRICK_NOTIFY_CMD": str(self.tmp / "no-such-notifier")})
        self.assertEqual(3, r.returncode)
        self.assertIn("job: the notifier could not start", (self.jobs / "other.log").read_text())
        self.assertTrue((self.jobs / "other.heartbeat.json").exists())

    def test_a_job_sends_its_own_line(self):
        r = subprocess.run([sys.executable, str(JOBS / "job.py"), "notify", "Digest", "Three open, one due today."],
                           env=dict(os.environ, GARRICK_JOB="digest"), capture_output=True, text=True)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual([{"title": "Digest", "message": "Three open, one due today.", "kind": "message",
                           "job": "digest", "exit": ""}], self.notices())
        env = dict(os.environ)
        env.pop("GARRICK_NOTIFY_CMD")
        r = subprocess.run([sys.executable, str(JOBS / "job.py"), "notify", "Digest", "x"], env=env,
                           capture_output=True, text=True)
        self.assertEqual(0, r.returncode)
        self.assertIn("no notifier is set", r.stderr)


class JobExtrasTest(FakeAssistants):
    def job(self, *args, env=None):
        return subprocess.run([sys.executable, str(JOBS / "job.py")] + list(args),
                              env=dict(os.environ, **(env or {})), capture_output=True, text=True)

    def test_the_heartbeat_holds_what_the_page_shows(self):
        r = self.job("tidy", "--agent", "--cwd", str(self.tmp), "--", sys.executable, "-c", "pass")
        self.assertEqual(0, r.returncode, r.stderr)
        beat = json.loads((self.jobs / "tidy.heartbeat.json").read_text())
        self.assertEqual({"agent", "exit", "failing_since", "finished", "finished_ts", "idle", "idle_days", "items",
                          "job", "no_call", "ok", "quiet", "reason", "seconds", "started"}, set(beat))
        self.assertEqual((True, 0, True, False, None), (beat["agent"], beat["exit"], beat["ok"], beat["quiet"],
                                                        beat["reason"]))
        self.assertLessEqual(beat["started"], beat["finished"])

    def test_an_agent_job_that_recorded_no_call_says_so(self):
        r = self.job("tidy", "--agent", "--cwd", str(self.tmp), "--", sys.executable, "-c", "pass")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertTrue(json.loads((self.jobs / "tidy.heartbeat.json").read_text())["no_call"])
        self.assertIn("tidy exited 0 and recorded no assistant call", (self.jobs / "tidy.log").read_text())
        # Through agent.py, the ledger gains a line under the job's name and nothing is said.
        r = self.job("sweep", "--agent", "--cwd", str(self.tmp), "--", sys.executable, str(JOBS / "agent.py"),
                     "run", "--tier", "haiku", "--prompt", "Say hello.")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual(["sweep"], [e["job"] for e in self.ledger()])
        self.assertFalse(json.loads((self.jobs / "sweep.heartbeat.json").read_text())["no_call"])
        self.assertNotIn("no assistant call", (self.jobs / "sweep.log").read_text())
        # A line another job wrote during the run does not count for this one.
        other = ("import sys; sys.path.insert(0, %r); import agent; agent.run('haiku', 'Hi.', job='other')"
                 % str(JOBS))
        self.job("brief", "--agent", "--cwd", str(self.tmp), "--", sys.executable, "-c", other)
        self.assertEqual(["sweep", "other"], [e["job"] for e in self.ledger()])
        self.assertTrue(json.loads((self.jobs / "brief.heartbeat.json").read_text())["no_call"])
        # A job without --agent, and one that failed, are not asked.
        self.job("plain", "--", sys.executable, "-c", "pass")
        self.assertFalse(json.loads((self.jobs / "plain.heartbeat.json").read_text())["no_call"])
        self.job("broke", "--agent", "--cwd", str(self.tmp), "--", sys.executable, "-c", "import sys; sys.exit(3)")
        self.assertFalse(json.loads((self.jobs / "broke.heartbeat.json").read_text())["no_call"])

    def test_check_scripts_finds_a_direct_call(self):
        direct = self.tmp / "sweep.sh"
        direct.write_text('#!/bin/sh\n# claude -p in a comment is fine\nout="$(claude -p "$(cat p.md)")"\n')
        listed = self.tmp / "brief.py"
        listed.write_text('import subprocess\nsubprocess.run(["codex", "exec", prompt])\n')
        clean = self.tmp / "tidy.sh"
        clean.write_text('#!/bin/sh\npython3 agent.py run --tier haiku --prompt-file p.md  # not claude -p\n'
                         'claude mcp list\n')
        r = self.job("check-scripts", str(direct), str(listed), str(clean), str(JOBS / "agent.py"))
        self.assertEqual(1, r.returncode, r.stderr)
        self.assertEqual(["%s:3: runs claude directly; call agent.py run instead" % direct,
                          "%s:2: runs codex directly; call agent.py run instead" % listed], r.stdout.splitlines())
        r = self.job("check-scripts", str(clean), *(str(JOBS / n) for n in ("agent.py", "job.py", "whats_open.py")))
        self.assertEqual(0, r.returncode, r.stdout)
        self.assertIn("4 files checked", r.stdout)
        # A plist is read for the scripts it runs, and for a command line that is itself the call.
        plist = self.tmp / "garrick.sweep.plist"
        plist.write_bytes(plistlib.dumps({"ProgramArguments": ["/usr/bin/python3", str(JOBS / "job.py"), "sweep",
                                                              "--agent", "--", "/bin/sh", str(direct)]}))
        bare = self.tmp / "garrick.bare.plist"
        bare.write_bytes(plistlib.dumps({"ProgramArguments": ["/usr/local/bin/claude", "-p", "Sweep."]}))
        r = self.job("check-scripts", str(plist), str(bare), str(self.tmp / "missing.sh"))
        self.assertEqual(1, r.returncode)
        self.assertIn("%s:3: runs claude directly" % direct, r.stdout)
        self.assertIn("%s: runs an assistant itself" % bare, r.stdout)
        self.assertIn("missing.sh: could not be read", r.stdout)       # unread is not clean
        self.assertEqual(agent.EXIT_USAGE, self.job("check-scripts").returncode)
        self.assertEqual(0, self.job("check-scripts", str(JOBS / "launchd" / "garrick.whats-open.plist")).returncode)

    def test_status_says_which_jobs_are_running(self):
        self.job("tidy", "--", sys.executable, "-c", "import sys; sys.exit(3)")
        lock = self.jobs / "sweep.lock"
        lock.mkdir()
        (lock / "until").write_text("%d %d %d\n" % (time.time() + 600, os.getpid(), time.time()))
        r = self.job("status")
        self.assertEqual(0, r.returncode, r.stderr)
        got = json.loads(r.stdout)
        self.assertEqual(str(self.jobs), got["folder"])
        self.assertIsNone(got["assistant_lock"])
        by = {j["job"]: j for j in got["jobs"]}
        self.assertEqual(["sweep", "tidy"], sorted(by))
        self.assertTrue(by["sweep"]["running"])
        self.assertEqual(os.getpid(), by["sweep"]["lock"]["pid"])
        self.assertFalse(by["tidy"]["running"])
        self.assertEqual(3, by["tidy"]["heartbeat"]["exit"])
        self.assertEqual(3, by["tidy"]["failing"]["exit"])
        self.assertEqual(["tidy"], [j["job"] for j in json.loads(self.job("status", "tidy").stdout)["jobs"]])
        self.assertEqual(agent.EXIT_USAGE, self.job("status", "../x").returncode)

    def test_a_lock_whose_holder_has_gone_is_taken_over(self):
        gone = subprocess.Popen([sys.executable, "-c", "pass"])
        gone.wait()
        self.jobs.mkdir(parents=True)
        lock = self.jobs / "tidy.lock"
        lock.mkdir()
        (lock / "until").write_text("%d %d %d\n" % (time.time() + 3600, gone.pid, time.time()))
        self.assertIsNone(job.lock_state(lock))
        self.assertEqual(0, self.job("tidy", "--", sys.executable, "-c", "print('ran')").returncode)
        self.assertIn("ran", (self.jobs / "tidy.log").read_text())

    def test_an_env_file_reaches_the_job_but_not_the_log(self):
        envfile = self.tmp / "jobs.env"
        envfile.write_text("# for the jobs\nexport GREETING='hello there'\nPLAIN=yes\nnot a setting\n")
        envfile.chmod(0o600)
        script = "import os; print('got', os.environ['GREETING'], os.environ['PLAIN'])"
        r = self.job("tidy", "--", sys.executable, "-c", script, env={"GARRICK_ENV_FILE": str(envfile)})
        self.assertEqual(0, r.returncode, r.stderr)
        log = (self.jobs / "tidy.log").read_text()
        self.assertIn("job: read GREETING, PLAIN from", log)
        self.assertIn("got hello there yes", log)                       # the job's own output, not job.py's
        self.assertEqual(1, log.count("hello there"))
        self.assertNotIn("other users", log)
        envfile.chmod(0o644)
        self.job("tidy", "--", sys.executable, "-c", "pass", env={"GARRICK_ENV_FILE": str(envfile)})
        self.assertIn("other users", (self.jobs / "tidy.log").read_text())
        r = self.job("tidy", "--", sys.executable, "-c", "pass", env={"GARRICK_ENV_FILE": str(self.tmp / "none")})
        self.assertEqual(0, r.returncode)
        self.assertIn("could not be read", (self.jobs / "tidy.log").read_text())

    def test_a_sign_in_check_without_an_answer_runs_the_job(self):
        out = self.tmp / "ran.txt"
        with mock.patch.object(job.agent, "login_state", return_value=None):
            code = job.main(["tidy", "--agent", "--cwd", str(self.tmp), "--", sys.executable, "-c",
                             "open(%r, 'w').write('ran')" % str(out)])
        self.assertEqual(0, code)
        self.assertTrue(out.exists())
        self.assertIn("did not answer the sign-in check", (self.jobs / "tidy.log").read_text())


# A command that starts a process of its own, says both pids in a file, and waits.
SLEEPER = r'''
import os, subprocess, sys, time
kid = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
with open(sys.argv[1] + ".tmp", "w") as f:
    f.write("%d %d" % (os.getpid(), kid.pid))
os.rename(sys.argv[1] + ".tmp", sys.argv[1])
time.sleep(120)
'''


def gone(pid, within=10.0):
    """Whether `pid` has gone, waiting up to `within` seconds for it to."""
    deadline = time.time() + within
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return True
        time.sleep(0.1)
    return False


class StopAndLockTest(FakeAssistants):
    """job.py stopped mid-run, killed outright, or caught by a sleeping Mac."""

    def job(self, *args, env=None):
        return subprocess.run([sys.executable, str(JOBS / "job.py")] + list(args),
                              env=dict(os.environ, **(env or {})), capture_output=True, text=True)

    def start_sleeper(self, name, *flags):
        """job.py running SLEEPER, and the pids of its command and the command's own child."""
        script = self.tmp / "sleeper.py"
        script.write_text(SLEEPER, encoding="utf-8")
        pids = self.tmp / ("%s.pids" % name)
        proc = subprocess.Popen([sys.executable, str(JOBS / "job.py"), name] + list(flags)
                                + ["--cwd", str(self.tmp), "--", sys.executable, str(script), str(pids)],
                                env=dict(os.environ), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        deadline = time.time() + 30
        while not pids.exists():
            self.assertLess(time.time(), deadline, "the command never started")
            time.sleep(0.1)
        command, child = (int(w) for w in pids.read_text().split())
        self.addCleanup(self.kill_group, command)
        self.addCleanup(self.kill_pid, child)
        return proc, command, child

    @staticmethod
    def kill_group(group):
        try:
            os.killpg(group, 9)
        except OSError:
            pass

    @staticmethod
    def kill_pid(pid):
        try:
            os.kill(pid, 9)
        except OSError:
            pass

    def live_process(self, new_group=False):
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"],
                                start_new_session=new_group)
        self.addCleanup(lambda: (proc.kill(), proc.wait()))
        return proc

    def dead_pid(self):
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait()
        return proc.pid

    def test_a_stopped_run_stops_its_command_and_lets_go(self):
        # launchctl bootout sends SIGTERM to job.py alone: the command, in a session of its own, must go too.
        proc, command, child = self.start_sleeper("sweep", "--agent")
        self.assertTrue((self.jobs / "agent.lock").exists())
        proc.send_signal(signal.SIGTERM)
        self.assertEqual(143, proc.wait(timeout=30))
        self.assertTrue(gone(command), "the command outlived job.py")
        self.assertTrue(gone(child), "the command's own child outlived job.py")
        self.assertFalse((self.jobs / "sweep.lock").exists())
        self.assertFalse((self.jobs / "agent.lock").exists())
        beat = json.loads((self.jobs / "sweep.heartbeat.json").read_text())
        self.assertEqual((143, False), (beat["exit"], beat["ok"]))
        self.assertIn("was stopped by SIGTERM", beat["reason"])
        self.assertEqual([("sweep", "143")], [(m.group(2), m.group(3))
                                              for m in LOGLINE.finditer((self.jobs / "sweep.log").read_text())])
        self.assertFalse((self.jobs / "sweep.alert.json").exists())     # a stop is no failure to notify

    def brief_run(self, name, *flags, ignore_hup=False):
        """job.py running a command that says it has started, then ends well
        after two seconds; with `ignore_hup`, started as `nohup` starts it."""
        started = self.tmp / ("%s.started" % name)
        script = ("import os, time; open(%r, 'w').write(str(os.getsid(0))); time.sleep(2)" % str(started))
        argv = [sys.executable, str(JOBS / "job.py"), name] + list(flags) + ["--cwd", str(self.tmp), "--", sys.executable, "-c", script]
        hup = (lambda: signal.signal(signal.SIGHUP, signal.SIG_IGN)) if ignore_hup else None
        proc = subprocess.Popen(argv, env=dict(os.environ), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=hup)
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        return proc, started

    def wait_for(self, path, within=30):
        deadline = time.time() + within
        while not path.exists() or not path.read_text():
            self.assertLess(time.time(), deadline, "%s never came" % path.name)
            time.sleep(0.05)

    def test_a_run_under_nohup_outlives_a_hangup(self):
        # A session hook starts a job with nohup; the hook's end sends SIGHUP, which nohup ignores and so must job.py.
        proc, started = self.brief_run("sweep", ignore_hup=True)
        self.wait_for(started)
        proc.send_signal(signal.SIGHUP)
        self.assertEqual(0, proc.wait(timeout=30))
        beat = json.loads((self.jobs / "sweep.heartbeat.json").read_text())
        self.assertEqual((0, True, None), (beat["exit"], beat["ok"], beat["reason"]))
        self.assertEqual([("sweep", "0")], [(m.group(2), m.group(3)) for m in LOGLINE.finditer((self.jobs / "sweep.log").read_text())])

    def test_a_hangup_still_stops_a_run_that_heeds_it(self):
        proc, started = self.brief_run("sweep")
        self.wait_for(started)
        proc.send_signal(signal.SIGHUP)
        self.assertEqual(129, proc.wait(timeout=30))
        self.assertIn("was stopped by SIGHUP", json.loads((self.jobs / "sweep.heartbeat.json").read_text())["reason"])

    def test_detach_runs_on_in_a_session_of_its_own(self):
        r = subprocess.run([sys.executable, str(JOBS / "job.py"), "sweep", "--detach", "--cwd", str(self.tmp), "--",
                            sys.executable, "-c", "import os; open('session', 'w').write(str(os.getsid(0)))"],
                           env=dict(os.environ), capture_output=True, text=True, timeout=30)
        self.assertEqual((0, ""), (r.returncode, r.stderr))                    # back at once, nothing said
        beat = self.jobs / "sweep.heartbeat.json"
        self.wait_for(beat)
        self.assertEqual(0, json.loads(beat.read_text())["exit"])
        self.assertNotEqual(os.getsid(0), int((self.tmp / "session").read_text()))   # not the starter's session
        self.assertNotIn("--detach", (self.jobs / "sweep.log").read_text())
        self.assertEqual(64, self.job("bad name!", "--detach", "--", "true").returncode)   # a mistake is said before it goes

    def test_a_command_left_behind_by_a_killed_job_py_still_holds_the_lock(self):
        proc, command, child = self.start_sleeper("sweep", "--agent")
        proc.kill()                                                    # no handler runs for SIGKILL
        proc.wait(timeout=30)
        self.assertFalse(gone(command, within=0.5))                    # the command runs on, with no watchdog
        r = self.job("sweep", "--", sys.executable, "-c", "print('second copy')")
        self.assertEqual(75, r.returncode)
        log = (self.jobs / "sweep.log").read_text()
        self.assertNotIn("second copy", log)
        self.assertIn("skipped: the previous run's command, process group %d, is still going" % command, log)
        # The shared lock stands as well: no second assistant beside the one still running.
        r = self.job("brief", "--agent", "--timeout", "1", "--cwd", str(self.tmp), "--",
                     sys.executable, "-c", "print('second assistant')")
        self.assertEqual(75, r.returncode)
        self.assertTrue(json.loads(self.job("status", "sweep").stdout)["jobs"][0]["running"])
        self.kill_group(command)
        self.kill_pid(child)
        self.assertTrue(gone(command))
        self.assertEqual(0, self.job("sweep", "--", sys.executable, "-c", "pass").returncode)

    def test_a_command_left_behind_past_its_time_is_stopped(self):
        left = self.live_process(new_group=True)
        self.jobs.mkdir(parents=True)
        lock = self.jobs / "tidy.lock"
        lock.mkdir()
        now = time.time()
        (lock / "until").write_text("%d %d %d %d %d\n" % (now - 60, self.dead_pid(), now - 3600, left.pid, now))
        r = self.job("tidy", "--", sys.executable, "-c", "print('ran')")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIsNotNone(left.poll())
        log = (self.jobs / "tidy.log").read_text()
        self.assertIn("stopped process group %d" % left.pid, log)
        self.assertIn("ran", log)

    def test_a_lock_outlives_its_time_while_its_holder_lives(self):
        # The Mac slept through the run: the clock says the lock is old, but the run that holds it is still going.
        holder = self.live_process()
        self.jobs.mkdir(parents=True)
        lock = self.jobs / "tidy.lock"
        lock.mkdir()
        (lock / "until").write_text("%d %d %d\n" % (time.time() - 3600, holder.pid, time.time()))
        r = self.job("tidy", "--", sys.executable, "-c", "print('ran')")
        self.assertEqual(75, r.returncode)
        self.assertNotIn("ran", (self.jobs / "tidy.log").read_text())
        self.assertIsNotNone(job.lock_state(lock))

    def test_a_pid_now_used_by_another_process_holds_nothing(self):
        later = self.live_process()                                     # started after the lock's record says
        self.jobs.mkdir(parents=True)
        lock = self.jobs / "tidy.lock"
        lock.mkdir()
        (lock / "until").write_text("%d %d %d\n" % (time.time() + 3600, later.pid, time.time() - 3600))
        self.assertIsNone(job.lock_state(lock))
        self.assertEqual(0, self.job("tidy", "--", sys.executable, "-c", "pass").returncode)
        self.assertIsNone(later.poll())                                 # and is left alone

    def test_a_timeout_of_zero_or_less(self):
        for given in ("0", "-5", "nan"):
            r = self.job("tidy", "--timeout", given, "--", sys.executable, "-c", "print('ran')")
            self.assertEqual(agent.EXIT_USAGE, r.returncode, given)
            self.assertIn("--timeout", r.stderr)
        self.assertFalse((self.jobs / "tidy.log").exists())
        r = self.job("tidy", "--", sys.executable, "-c", "print('ran')", env={"GARRICK_JOB_TIMEOUT": "0"})
        self.assertEqual(0, r.returncode, r.stderr)
        log = (self.jobs / "tidy.log").read_text()
        self.assertIn("job: GARRICK_JOB_TIMEOUT is '0', not a number of seconds above zero; using 1500", log)
        self.assertIn("ran", log)

    def test_the_env_file_can_hold_every_setting(self):
        elsewhere = self.tmp / "other-jobs"
        envfile = self.tmp / "jobs.env"
        envfile.write_text("GARRICK_JOBS_DIR=%s\nGARRICK_QUIET_EXITS=5\nGARRICK_JOB_TIMEOUT=1\n" % elsewhere)
        envfile.chmod(0o600)
        r = self.job("tidy", "--", sys.executable, "-c", "import sys; sys.exit(5)",
                     env={"GARRICK_ENV_FILE": str(envfile)})
        self.assertEqual(5, r.returncode)
        beat = json.loads((elsewhere / "tidy.heartbeat.json").read_text())
        self.assertTrue(beat["quiet"])
        self.assertIn("job: read GARRICK_JOBS_DIR, GARRICK_JOB_TIMEOUT, GARRICK_QUIET_EXITS from",
                      (elsewhere / "tidy.log").read_text())
        self.assertFalse((self.jobs / "tidy.log").exists())
        started = time.time()
        r = self.job("slow", "--", sys.executable, "-c", "import time; time.sleep(30)",
                     env={"GARRICK_ENV_FILE": str(envfile)})
        self.assertEqual(124, r.returncode)
        self.assertLess(time.time() - started, 20)


class WhatsOpenTest(FakeAssistants):
    def setUp(self):
        super().setUp()
        self.ws = build_workspace(self.tmp / "ws")
        write(self.ws / "Zones" / "Personal" / "House" / "Threads" / "Roof Repair" / "Roof Repair.md",
              thread_note("House", "Roof Repair", "acme"))
        write(self.ws / "Zones" / "Work" / "Acme Review" / "Threads" / "Old Audit" / "Old Audit.md",
              thread_note("Acme Review", "Old Audit", "acme", status="done"))
        self.out = self.tmp / "briefs"

    def test_one_call_per_zone_and_no_zone_sees_another(self):
        code = whats_open.main(["--workspace", str(self.ws), "--zone", "Work", "--zone", "personal",
                                "--out", str(self.out)])
        self.assertEqual(0, code)
        prompts = [c[c.index("-p") + 1] for c in self.calls() if "-p" in c]
        self.assertEqual(2, len(prompts))
        work, personal = prompts
        self.assertIn("Pricing", work)
        self.assertIn("Market Sizing", work)
        self.assertNotIn("Old Audit", work)
        self.assertNotIn("Roof Repair", work)
        self.assertIn("Roof Repair", personal)
        self.assertNotIn("Acme Review", personal)
        briefs = sorted(p.name for p in self.out.iterdir())
        self.assertEqual(2, len(briefs))
        self.assertTrue(all(b.startswith("whats-open-") for b in briefs))
        self.assertNotIn("END OF BRIEF", (self.out / briefs[0]).read_text())
        self.assertEqual([], [p for p in self.ws.rglob("whats-open-*")])

    def test_an_empty_zone_costs_no_call(self):
        for note in (self.ws / "Zones" / "Personal").rglob("Roof Repair.md"):
            note.unlink()
        self.assertEqual(0, whats_open.main(["--workspace", str(self.ws), "--zone", "Personal",
                                             "--out", str(self.out)]))
        self.assertEqual([], self.calls())
        self.assertIn("Nothing open", next(self.out.iterdir()).read_text())

    def test_parked_threads_are_not_open(self):
        roof = self.ws / "Zones" / "Personal" / "House" / "Threads" / "Roof Repair" / "Roof Repair.md"
        roof.write_text(thread_note("House", "Roof Repair", "acme", status="parked"))
        write(self.ws / "Zones" / "Work" / "Acme Review" / "Threads" / "Logistics" / "Logistics.md",
              thread_note("Acme Review", "Logistics", "acme", status="Parked"))
        labels = [label for label, _ in whats_open.live_threads(self.ws / "Zones" / "Work")]
        self.assertEqual(["Acme Review, Pricing", "Birch Entry, Market Sizing"], sorted(labels))
        self.assertEqual([], whats_open.live_threads(self.ws / "Zones" / "Personal"))
        code = whats_open.main(["--workspace", str(self.ws), "--zone", "Work", "--zone", "Personal",
                                "--out", str(self.out)])
        self.assertEqual(0, code)
        prompts = [c[c.index("-p") + 1] for c in self.calls() if "-p" in c]
        self.assertEqual(1, len(prompts))  # Personal holds only a parked thread: no call for it
        self.assertIn("Pricing", prompts[0])
        self.assertNotIn("Logistics", prompts[0])
        personal = [p for p in self.out.iterdir() if p.name.startswith("whats-open-personal-")]
        self.assertEqual(1, len(personal))
        self.assertIn("Nothing open", personal[0].read_text())

    def test_a_status_reads_as_the_workspace_reads_it(self):
        # The status line as people write it: with a comment, quoted, or both.
        threads = self.ws / "Zones" / "Work" / "Acme Review" / "Threads"
        for name, status in (("Freight", "parked # until next quarter"), ("Customs", '"parked"'),
                             ("Audit Prep", "'done'   # signed off"), ("Rates", "active # this week")):
            write(threads / name / (name + ".md"), thread_note("Acme Review", name, "acme", status=status))
        labels = sorted(label for label, _ in whats_open.live_threads(self.ws / "Zones" / "Work"))
        self.assertEqual(["Acme Review, Pricing", "Acme Review, Rates", "Birch Entry, Market Sizing"], labels)

    def test_an_answer_without_its_closing_line_writes_nothing(self):
        os.environ["FAKE_RESULT"] = "# Brief, cut short"
        code = whats_open.main(["--workspace", str(self.ws), "--zone", "Work", "--out", str(self.out)])
        self.assertEqual(whats_open.EXIT_INCOMPLETE, code)
        self.assertFalse(self.out.exists())

    def test_unknown_zone(self):
        self.assertEqual(agent.EXIT_USAGE, whats_open.main(["--workspace", str(self.ws), "--zone", "Garden"]))


if __name__ == "__main__":
    unittest.main()
