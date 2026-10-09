"""extras/status/agents_working.py: whether an assistant is mid-turn, from its transcripts."""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "extras" / "status"))
import agents_working as aw  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
