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
whats_open = _load("garrick_whats_open", JOBS / "whats_open.py")

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
    result = os.environ.get("FAKE_RESULT", "# Brief\n- Pricing: send the draft\nEND OF BRIEF")
    print("a warning line before the JSON")
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "num_turns": 2,
                      "result": result, "total_cost_usd": 0.25,
                      "permission_denials": [{"tool_name": "Bash"}]}))
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
                    "GARRICK_ITEMS_FILE", "FAKE_RESULT", "FAKE_LOGGED_IN"):
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
                     "Bash(rm:*)", "Edit(System/**)", "Write(**/.git/**)"):
            self.assertIn(tool, deny, tool)

    def test_claude_command(self):
        cmd = agent.claude_command("sonnet", "Do the sweep.", ["Read", "Grep"], 5)
        self.assertEqual(["claude", "-p", "Do the sweep.", "--model", "sonnet"], cmd[:5])
        self.assertEqual(str(agent.PROFILE), cmd[cmd.index("--settings") + 1])
        self.assertEqual("user,project", cmd[cmd.index("--setting-sources") + 1])
        self.assertEqual("json", cmd[cmd.index("--output-format") + 1])
        self.assertEqual("5", cmd[cmd.index("--max-budget-usd") + 1])
        self.assertEqual(["--allowedTools", "Read", "Grep"], cmd[-3:])
        self.assertNotIn("--max-budget-usd", agent.claude_command("haiku", "x", [], 0))

    def test_codex_command_takes_its_model_from_the_tier(self):
        with mock.patch.dict(os.environ, {"GARRICK_CODEX_MODEL_SONNET": "some-model"}):
            cmd = agent.codex_command("sonnet", "Do it.", Path("/tmp/last.txt"))
        self.assertEqual(["codex", "exec", "-m", "some-model"], cmd[:4])
        self.assertIn("workspace-write", cmd)
        self.assertEqual("Do it.", cmd[-1])
        self.assertNotIn("--allowedTools", cmd)

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
        self.assertEqual("Codex answer\nSWEEP_COMPLETE\n", text)
        self.assertIn("the whole run", (self.jobs / "manual.transcript.log").read_text())
        line = self.ledger()[0]
        self.assertIsNone(line["turns"])
        self.assertIsNone(line["cost_usd"])

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
        r = self.job("tidy", "--", sys.executable, "-c", "print('ran')")
        self.assertEqual(75, r.returncode)
        self.assertNotIn("ran", (self.jobs / "tidy.log").read_text())

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

    def test_an_answer_without_its_closing_line_writes_nothing(self):
        os.environ["FAKE_RESULT"] = "# Brief, cut short"
        code = whats_open.main(["--workspace", str(self.ws), "--zone", "Work", "--out", str(self.out)])
        self.assertEqual(whats_open.EXIT_INCOMPLETE, code)
        self.assertFalse(self.out.exists())

    def test_unknown_zone(self):
        self.assertEqual(agent.EXIT_USAGE, whats_open.main(["--workspace", str(self.ws), "--zone", "Garden"]))


if __name__ == "__main__":
    unittest.main()
