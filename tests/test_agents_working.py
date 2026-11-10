"""extras/status/agents_working.py: whether an assistant is mid-turn, from its transcripts."""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "extras" / "status"))
import agents_working as aw  # noqa: E402

HOOK = Path(__file__).resolve().parent.parent / "extras" / "hooks" / "waiting_hook.py"
SECRET = "Should we tell Birch & Co about the 40 percent discount?"


def write(path: Path, records, age=0):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    t = time.time() - age
    os.utime(path, (t, t))


PROMPT = {"type": "user", "message": {"content": "Fix the table"}}
RESULT = {"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}}
DONE = {"type": "system", "subtype": "turn_duration"}


class AgentsWorking(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.claude = self.home / ".claude" / "projects" / "-x"

    def test_claude_mid_turn_is_working(self):
        write(self.claude / "a.jsonl", [PROMPT, DONE, PROMPT, RESULT])
        self.assertEqual(aw.check(self.home)[0], 0)

    def test_claude_after_its_turn_is_idle(self):
        write(self.claude / "a.jsonl", [PROMPT, RESULT, DONE])
        self.assertEqual(aw.check(self.home)[0], 1)

    def test_an_interrupted_turn_is_idle(self):
        write(self.claude / "a.jsonl", [PROMPT, {"type": "user", "message": {"content": "[Request interrupted by user]"}}])
        self.assertEqual(aw.check(self.home)[0], 1)

    def test_codex_turns(self):
        codex = self.home / ".codex" / "sessions" / "2026" / "10" / "09" / "rollout.jsonl"
        write(codex, [{"type": "event_msg", "payload": {"type": "task_started"}}])
        self.assertEqual(aw.check(self.home)[0], 0)
        write(codex, [{"type": "event_msg", "payload": {"type": "task_started"}}, {"type": "event_msg", "payload": {"type": "task_complete"}}])
        self.assertEqual(aw.check(self.home)[0], 1)

    def test_a_transcript_quiet_for_half_an_hour_does_not_count(self):
        write(self.claude / "a.jsonl", [PROMPT], age=31 * 60)
        self.assertEqual(aw.check(self.home)[0], 1)

    def test_a_long_transcript_is_read_from_its_end(self):
        filler = [{"type": "assistant", "message": {"content": "x" * 1000}}] * 400
        write(self.claude / "a.jsonl", [PROMPT, DONE] + filler + [PROMPT])
        self.assertGreater((self.claude / "a.jsonl").stat().st_size, aw.TAIL)
        self.assertEqual(aw.check(self.home)[0], 0)

    def test_no_transcripts_cannot_tell(self):
        self.assertEqual(aw.check(self.home)[0], 2)


def ask(tool="AskUserQuestion", use="toolu_1", at="2026-11-10T09:00:00Z", cwd=None):
    """A Claude Code record of a tool call whose input holds a question's text."""
    rec = {"type": "assistant", "timestamp": at, "message": {"content": [
        {"type": "tool_use", "id": use, "name": tool, "input": {"questions": [{"question": SECRET}], "plan": SECRET}}]}}
    if cwd:
        rec["cwd"] = cwd
    return rec


def answer(use="toolu_1"):
    return {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": use, "content": "Yes"}]}}


class Waiting(unittest.TestCase):
    """The third state: a session stopped on something only the user can answer."""

    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.claude = self.home / ".claude" / "projects" / "-x"
        self.ws = self.home / "Garrick"
        self.thread = self.ws / "Zones" / "Work" / "Acme Review" / "Threads" / "Pricing"
        self.thread.mkdir(parents=True)

    def row(self, **kw):
        found = {r["id"]: r for r in aw.rows_json(self.home, self.ws, in_cmux=kw.get("in_cmux", set()))}
        return found[kw.get("id", "a")]

    def test_a_question_with_no_answer_is_waiting_and_an_answer_ends_it(self):
        write(self.claude / "a.jsonl", [PROMPT, ask(cwd=str(self.thread))])
        r = self.row()
        self.assertEqual(("waiting", "a question", "2026-11-10T09:00:00Z"), (r["state"], r["waiting_for"], r["since"]))
        self.assertEqual("Acme Review, Pricing", r["thread"])
        write(self.claude / "a.jsonl", [PROMPT, ask(cwd=str(self.thread)), answer()])
        self.assertEqual("working", self.row()["state"])
        write(self.claude / "a.jsonl", [PROMPT, ask(), answer(), DONE])
        self.assertEqual("idle", self.row()["state"])

    def test_a_plan_waiting_for_approval_is_waiting(self):
        write(self.claude / "a.jsonl", [PROMPT, ask("ExitPlanMode")])
        self.assertEqual(("waiting", "an approval for the plan"), (self.row()["state"], self.row()["waiting_for"]))

    def test_other_tool_calls_are_working_and_a_new_prompt_clears_an_old_question(self):
        write(self.claude / "a.jsonl", [PROMPT, ask("Bash")])
        self.assertEqual("working", self.row()["state"])
        write(self.claude / "a.jsonl", [PROMPT, ask(), PROMPT])
        self.assertEqual("working", self.row()["state"])

    def mark(self, session="a", kind="permission_prompt", tool="Bash", since=None):
        folder = self.home / aw.MARKERS
        folder.mkdir(exist_ok=True)
        (folder / (session + ".json")).write_text(json.dumps({"kind": kind, "tool": tool, "since": since or time.time()}))

    def test_a_permission_prompt_marker_makes_a_session_wait_until_the_transcript_moves(self):
        write(self.claude / "a.jsonl", [PROMPT, ask("Bash")], age=30)
        self.mark(since=time.time() - 20)
        r = self.row()
        self.assertEqual(("waiting", "an approval for Bash"), (r["state"], r["waiting_for"]))
        self.assertTrue(r["since"].endswith("Z"))
        write(self.claude / "a.jsonl", [PROMPT, ask("Bash"), answer()])        # the tool's result came back: written after the marker
        self.assertEqual("working", self.row()["state"])

    def test_an_idle_prompt_is_not_a_wait_and_a_stale_marker_is_ignored(self):
        write(self.claude / "a.jsonl", [PROMPT, DONE], age=30)
        self.mark(kind="idle_prompt", since=time.time() - 20)
        self.assertEqual("idle", self.row()["state"])
        write(self.claude / "a.jsonl", [PROMPT], age=30)
        self.mark(since=time.time() - 3 * 86400)
        self.assertEqual("working", self.row()["state"])

    def test_a_marker_for_another_session_or_an_unsafe_id_is_ignored(self):
        write(self.claude / "a.jsonl", [PROMPT], age=30)
        self.mark(session="b", since=time.time() - 20)
        self.assertEqual("working", self.row()["state"])
        self.assertIsNone(aw.marker_for(self.home, "../a"))

    def codex(self, rows):
        path = self.home / ".codex" / "sessions" / "2026" / "11" / "10" / "rollout-1.jsonl"
        write(path, rows)
        return "rollout-1"

    def test_codex_waits_where_its_rollout_records_an_approval_request(self):
        sid = self.codex([event("task_started"), event("exec_approval_request", ts="2026-11-10T10:00:00Z")])
        r = self.row(id=sid)
        self.assertEqual(("waiting", "an approval for Bash", "2026-11-10T10:00:00Z"), (r["state"], r["waiting_for"], r["since"]))
        sid = self.codex([event("task_started"), event("apply_patch_approval_request"), event("patch_apply_end")])
        self.assertEqual("working", self.row(id=sid)["state"])
        sid = self.codex([event("task_started"), event("exec_approval_request"), event("task_complete")])
        self.assertEqual("idle", self.row(id=sid)["state"])

    def test_a_codex_rollout_with_no_approval_record_is_working_or_idle_only(self):
        sid = self.codex([event("task_started"), event("exec_command_begin"), event("token_count")])
        self.assertEqual("working", self.row(id=sid)["state"])

    def test_where_it_runs_and_who_can_be_brought_forward(self):
        write(self.claude / "a.jsonl", [PROMPT, dict(ask(), entrypoint="claude-desktop")])
        write(self.claude / "b.jsonl", [PROMPT, ask(use="t2")])
        write(self.claude / "c.jsonl", [PROMPT, ask(use="t3")])
        rows = {r["id"]: r for r in aw.rows_json(self.home, self.ws, in_cmux={"c"})}
        self.assertEqual(("desktop", "terminal", "cmux"), (rows["a"]["where"], rows["b"]["where"], rows["c"]["where"]))

    def test_the_text_of_a_question_never_reaches_the_json(self):
        write(self.claude / "a.jsonl", [PROMPT, ask(cwd=str(self.thread))])
        self.mark(session="a", tool="Bash")
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"GARRICK_HOME": str(self.home)}), contextlib.redirect_stdout(out):
            code = aw.main(["--json", "--workspace", str(self.ws)])
        self.assertEqual(0, code)
        self.assertNotIn("Birch", out.getvalue())
        self.assertNotIn("discount", out.getvalue())
        data = json.loads(out.getvalue())
        self.assertEqual(["a"], [r["id"] for r in data["sessions"]])
        self.assertEqual({"id", "agent", "folder", "thread", "state", "waiting_for", "since", "where"}, set(data["sessions"][0]))

    def test_json_lists_the_waiting_first_oldest_first_and_exit_codes_stay(self):
        write(self.claude / "w1.jsonl", [PROMPT, ask(at="2026-11-10T09:30:00Z")])
        write(self.claude / "w2.jsonl", [PROMPT, ask(at="2026-11-10T09:00:00Z")])
        write(self.claude / "i.jsonl", [PROMPT, DONE])
        rows = aw.rows_json(self.home, self.ws, in_cmux=set())
        self.assertEqual(["w2", "w1", "i"], [r["id"] for r in rows])
        self.assertEqual(1, aw.check(self.home)[0])           # waiting is not mid-turn: the Mac may sleep

    def test_a_long_transcript_is_still_read_from_its_last_256_kb(self):
        filler = [{"type": "assistant", "message": {"content": "x" * 1000}}] * 400
        write(self.claude / "a.jsonl", [PROMPT, ask("Bash")] + filler + [PROMPT, ask()])
        self.assertGreater((self.claude / "a.jsonl").stat().st_size, aw.TAIL)
        self.assertEqual("waiting", self.row()["state"])

    def test_a_folder_that_is_no_thread_reads_by_its_own_name(self):
        self.assertEqual("Acme Review", aw.thread_of(str(self.ws / "Zones" / "Work" / "Acme Review"), self.ws))
        self.assertEqual("scratch", aw.thread_of("/tmp/scratch", self.ws))
        self.assertEqual("", aw.thread_of("", self.ws))


def event(kind, ts=""):
    return {"type": "event_msg", "timestamp": ts, "payload": {"type": kind}}


if __name__ == "__main__":
    unittest.main()
