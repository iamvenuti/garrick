"""The Telegram channel (#570): the receiver, the dispatcher, the exchange record and the delivery, against a fake Bot API.

    python3 -m unittest discover -s tests

The Bot API is a small server on localhost, started by each test: nothing here calls api.telegram.org. The assistant is a
stub that answers JSON, and the clock is a variable, so two hours and two days pass in no time.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import threading
import time
import unittest
from unittest import mock
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.dont_write_bytecode = True

from fixtures import write  # noqa: E402
from test_notes import NoteCase, REPO, git  # noqa: E402

STATUS = REPO / "extras" / "status"
PAIRED = 4242
HELP_OK = "--resume <id>  --allowedTools  --strict-mcp-config  Bash(git *) --effort <level>"


class FakeApi:
    """The Bot API's few calls on localhost. `pending` is what getUpdates holds until an offset confirms it."""

    def __init__(self):
        self.pending, self.sent, self.calls, self.next_id, self.webhook = [], [], [], 1000, ""
        self.rival = False                      # another poller: confirms every pending update between our reads
        self.fail_send = False
        api = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                method = self.path.rsplit("/", 1)[-1]
                api.calls.append(method)
                code, out = 200, {"ok": True, "result": None}
                if method == "getWebhookInfo":
                    out["result"] = {"url": api.webhook}
                elif method == "getUpdates":
                    if body.get("offset"):
                        api.pending = [u for u in api.pending if u["update_id"] >= body["offset"]]
                    out["result"] = list(api.pending)
                    if api.rival:
                        api.pending = []
                elif method == "sendMessage":
                    if api.fail_send:
                        code, out = 500, {"ok": False, "error_code": 500}
                    else:
                        api.next_id += 1
                        api.sent.append(dict(body, message_id=api.next_id))
                        out["result"] = {"message_id": api.next_id}
                data = json.dumps(out).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d" % self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.update_id = 0

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def say(self, text, chat=PAIRED, sender=None, kind="private", reply_to=None, date=1_700_000_000):
        self.update_id += 1
        self.next_id += 1
        msg = {"message_id": self.next_id, "chat": {"id": chat, "type": kind}, "from": {"id": sender if sender is not None else chat},
               "text": text, "date": date}
        if reply_to:
            msg["reply_to_message"] = {"message_id": reply_to}
        self.pending.append({"update_id": self.update_id, "message": msg})
        return msg["message_id"]


class Clock:
    def __init__(self):
        self.t = 1_700_000_000.0

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


class TelegramCase(NoteCase):
    def setUp(self):
        super().setUp()
        for name in ("channels", "hold", "exchanges", "dispatcher", "telegram_delivery", "channel_state", "engine", "engine_guard",
                     "hold_tools", "intake"):
            sys.modules.pop(name, None)
        spec = importlib.util.spec_from_file_location("garrick_test_receiver", str(REPO / "extras" / "fetch" / "telegram_receiver.py"))
        self.rcv = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.rcv)
        self.mods = self.rcv.load_modules(self.root)
        self.api = FakeApi()
        self.addCleanup(self.api.close)
        self.clock = Clock()
        self.calls = []
        self.sessions = 0
        self._harness = os.environ.get("GARRICK_HARNESS")
        os.environ["GARRICK_HARNESS"] = "claude"
        self.cap = self.mods["channels"].evaluate(self.root, HELP_OK, True)
        self.rx = self.make()

    def tearDown(self):
        for k in [k for k in os.environ if k.startswith("GARRICK_ENGINE")]:
            os.environ.pop(k)
        if self._harness is None:
            os.environ.pop("GARRICK_HARNESS", None)
        else:
            os.environ["GARRICK_HARNESS"] = self._harness
        super().tearDown()

    def assistant(self, answer="Fine.", tokens=1000, act=None):
        def run(cmd, tier, cwd, env):
            self.sessions += 1
            resumed = cmd[cmd.index("--resume") + 1] if "--resume" in cmd else None
            call = {"cmd": cmd, "env": env, "tier": tier, "resumed": resumed, "prompt": cmd[cmd.index("-p") + 1], "n": len(self.calls) + 1}
            self.calls.append(call)
            if act:
                act(cmd, env)
            text = answer(call) if callable(answer) else answer
            return 0, {"text": text, "session_id": resumed or "sess-%d" % self.sessions, "usage": {"input_tokens": tokens}, "cost_usd": 0.01}
        return run

    def make(self, runner=None, chat=PAIRED):
        bot = self.mods["telegram_delivery"].Bot("123:SECRET", self.api.url)
        rx = self.rcv.Receiver(self.root, bot, chat, self.mods, runner or self.assistant(), self.clock, lambda s: None)
        rx.cap = self.cap
        return rx

    def pump(self, rounds=1, quiet=11):
        """Receive, let the batching window pass, run what is due."""
        for _ in range(rounds):
            self.rx.poll_once(0)
            self.clock.advance(quiet)
            self.rx.flush()
            self.rx.beat()

    def texts(self):
        return [m["text"] for m in self.api.sent]

    def exchange_of(self, said):
        ex = self.mods["exchanges"].load()["exchanges"]
        return next(e for e in ex.values() if e.get("said") == said)


class TestReceiving(TelegramCase):
    def test_only_the_paired_private_chat_is_heard(self):
        self.api.say("Acme Review, pricing: where do we stand?", chat=999, sender=999)
        self.api.say("Acme Review, pricing: where do we stand?", chat=PAIRED, kind="group")
        self.api.say("Acme Review, pricing: where do we stand?", chat=PAIRED, sender=777)
        self.api.say("Acme Review, pricing: where do we stand?", chat=-100500, sender=PAIRED, kind="supergroup")
        self.pump()
        self.assertEqual([], self.calls)
        self.assertEqual([], self.api.sent)
        data = self.rx.load()
        self.assertEqual(({}, 4), (data["messages"], data["ignored"]))

    def test_idle_makes_no_assistant_call(self):
        for _ in range(5):
            self.pump()
        self.assertEqual([], self.calls)
        self.assertEqual({"getUpdates"}, set(self.api.calls))      # the poll, and nothing else

    def test_a_message_is_saved_before_it_is_acknowledged(self):
        self.api.say("Acme Review, pricing: hello")
        self.rx.poll_once(0)
        saved = self.rx.load()
        self.assertEqual(1, len(saved["messages"]))
        self.assertEqual(self.api.update_id + 1, saved["offset"])

    def test_a_message_heard_twice_is_one(self):
        self.api.say("Acme Review, pricing: hello")
        self.rx.poll_once(0)
        self.api.pending = []
        self.api.update_id = 0
        self.api.say("Acme Review, pricing: hello")      # the same update id again, after a restart of the API's counter
        self.rx.poll_once(0)
        self.assertEqual(1, len(self.rx.load()["messages"]))


class TestNotesNeverReachTheAssistant(TelegramCase):
    def test_a_note_is_saved_under_the_contract_and_answered_by_code(self):
        self.api.say("note for Acme pricing: Dana hinted the floor could move to 450")
        self.pump()
        self.assertEqual([], self.calls)
        [f] = list((self.root / "Inbox").glob("telegram-*.md"))
        text = f.read_text()
        for line in ("kind: note", "via: telegram", "from-owner: true", 'destination: "Acme pricing"'):
            self.assertIn(line, text)
        self.assertTrue(text.rstrip().endswith("Dana hinted the floor could move to 450"))
        self.assertEqual(["Noted."], self.texts())
        [item] = self.mods["intake"].list_items(self.root)
        self.assertEqual("note", item["kind"])

    def test_note_with_a_colon_or_none_both_count(self):
        self.api.say("note: buy envelopes")
        self.api.say("Note remember to call Dana")
        self.api.say("notes on the call")                  # not the word note: an ordinary message
        self.pump()
        self.assertEqual(2, len(list((self.root / "Inbox").glob("telegram-*.md"))))

    def test_a_reply_to_the_bot_continues_its_exchange_even_when_it_starts_with_note(self):
        self.api.say("Acme Review, pricing: where do we stand?")
        self.pump()
        bot_message = self.api.sent[-1]["message_id"]
        self.api.say("note: the floor is 450", reply_to=bot_message)
        self.pump()
        self.assertEqual(2, len(self.calls))                # the second reached the assistant, as a turn
        self.assertEqual([], list((self.root / "Inbox").glob("telegram-*.md")))

    def test_a_note_in_the_inbox_without_the_owner_check_is_not_a_note(self):
        write(self.root / "Inbox" / "x.md", "---\nkind: note\nvia: telegram\n---\nhi\n")
        self.assertEqual("file", self.mods["intake"].list_items(self.root)[0]["kind"])


class TestOneChatManyThreads(TelegramCase):
    def test_two_named_threads_do_not_mix_their_context_or_destinations(self):
        self.api.say("Acme Review, pricing: where do we stand?")
        self.pump()
        self.api.say("Birch Entry, market sizing: what is open?")
        self.pump()
        self.assertEqual(["Work", "Work"], [c["env"]["GARRICK_ENGINE_ZONE"] for c in self.calls])
        self.assertNotEqual(self.calls[0]["env"]["GARRICK_ENGINE_EXCHANGE"], self.calls[1]["env"]["GARRICK_ENGINE_EXCHANGE"])
        self.assertNotIn("Birch", self.calls[0]["prompt"])
        self.assertNotIn("Acme", self.calls[1]["prompt"])
        self.assertIsNone(self.calls[1]["resumed"])         # a new subject starts its own session
        self.assertTrue(self.texts()[0].startswith("Acme Review, Pricing: "))
        self.assertTrue(self.texts()[1].startswith("Birch Entry, Market Sizing: "))
        ex = self.mods["exchanges"].load()["exchanges"]
        self.assertEqual({"switched", None}, {e["closed"] for e in ex.values()})

    def test_the_zone_of_each_exchange_is_its_threads(self):
        self.api.say("Home Move, boxes: what is left?")
        self.pump()
        self.assertEqual("Personal", self.calls[0]["env"]["GARRICK_ENGINE_ZONE"])
        self.assertNotIn("Zones/Work", " ".join(self.calls[0]["cmd"]))

    def test_a_reply_to_an_older_question_reaches_its_exchange_after_a_switch(self):
        self.rx.runner = self.assistant(lambda c: "Which forecast do you mean?" if c["n"] == 1 else "Noted.")
        self.api.say("Acme Review, pricing: use the revised forecast")
        self.pump()
        question = self.api.sent[-1]["message_id"]
        first = self.calls[0]["env"]["GARRICK_ENGINE_EXCHANGE"]
        self.api.say("Birch Entry, market sizing: what is open?")
        self.pump()
        self.api.say("The September one", reply_to=question)
        self.pump()
        self.assertEqual(first, self.calls[2]["env"]["GARRICK_ENGINE_EXCHANGE"])
        self.assertIsNone(self.calls[2]["resumed"])                  # it was closed by the switch: a new session ...
        self.assertIn("Which forecast do you mean?", self.calls[2]["prompt"])      # ... from what was saved
        self.assertNotIn("Birch", self.calls[2]["prompt"])

    def test_an_ambiguous_subject_is_asked_about_before_anything_is_read(self):
        self.api.say("pricing: where do we stand?")
        self.pump()
        self.assertEqual([], self.calls)
        [q] = self.texts()
        self.assertIn("Acme Review, Pricing", q)
        self.assertIn("Acme Retail, Pricing", q)
        self.api.say("Acme Review", reply_to=self.api.sent[-1]["message_id"])
        self.pump()
        self.assertEqual(1, len(self.calls))
        self.assertEqual("Work", self.calls[0]["env"]["GARRICK_ENGINE_ZONE"])
        self.assertIn("pricing: where do we stand?", self.calls[0]["prompt"])
        self.assertTrue(self.texts()[-1].startswith("Acme Review, Pricing: "))

    def test_a_message_that_names_no_thread_continues_the_open_exchange(self):
        self.api.say("Acme Review, pricing: where do we stand?")
        self.pump()
        self.api.say("and what did Dana say?")
        self.pump()
        self.assertEqual(2, len(self.calls))
        self.assertEqual(self.calls[0]["env"]["GARRICK_ENGINE_EXCHANGE"], self.calls[1]["env"]["GARRICK_ENGINE_EXCHANGE"])
        self.assertEqual("sess-1", self.calls[1]["resumed"])

    def test_with_no_open_session_the_same_message_gets_which_thread(self):
        self.api.say("and what did Dana say?")
        self.pump()
        self.assertEqual([], self.calls)
        self.assertEqual(["Which thread?"], self.texts())
        self.api.say("Acme Review, pricing: where do we stand?")
        self.pump()
        self.api.say("done")
        self.pump()
        self.api.say("and what did Dana say?")
        self.pump()
        self.assertEqual("Which thread?", self.texts()[-1])

    def test_one_message_that_could_answer_two_questions_is_asked_about(self):
        self.rx.runner = self.assistant("Which date?")
        self.api.say("Acme Review, pricing: move it")
        self.pump()
        self.api.say("Birch Entry, market sizing: move that too")
        self.pump()
        before = len(self.calls)
        self.api.say("Friday")
        self.pump()
        self.assertEqual(before, len(self.calls))
        self.assertIn("Two questions are waiting", self.texts()[-1])


class TestSessions(TelegramCase):
    def test_two_messages_an_hour_apart_resume_one_session(self):
        self.api.say("Acme Review, pricing: where do we stand?")
        self.pump()
        self.clock.advance(3600)
        self.api.say("and the volumes?")
        self.pump()
        self.assertEqual([None, "sess-1"], [c["resumed"] for c in self.calls])
        self.assertNotIn("<saved-state>", self.calls[1]["prompt"])      # no discovery again

    def test_done_saves_and_closes_and_returning_starts_a_new_session_from_saved_state(self):
        self.api.say("Acme Review, pricing: the floor is now 450")
        self.pump()
        old = self.api.sent[-1]["message_id"]
        self.api.say("done")
        self.pump()
        ex = self.exchange_of("Acme Review, Pricing")
        self.assertEqual(("done", None), (ex["closed"], ex["session"]))
        self.api.say("one more thing", reply_to=old)
        self.pump()
        again = self.calls[-1]
        self.assertIsNone(again["resumed"])
        self.assertIn("the floor is now 450", again["prompt"])          # the saved turn, not the chat
        self.assertEqual(ex["id"], again["env"]["GARRICK_ENGINE_EXCHANGE"])

    def test_at_two_hours_the_session_expires_between_turns_with_no_model_call(self):
        self.api.say("Acme Review, pricing: where do we stand?")
        self.pump()
        self.clock.advance(2 * 3600 + 60)
        for _ in range(3):
            self.pump()
        self.assertEqual(1, len(self.calls))                   # nothing called to expire or refresh it
        self.api.say("and the volumes?", date=1)
        self.rx.poll_once(0)                                    # an open exchange is gone: no session to continue
        self.assertEqual("Which thread?", self.texts()[-1])
        # a reply to its message, though, resolves to it and starts a new session from saved state
        self.api.say("and the volumes?", reply_to=self.api.sent[0]["message_id"])
        self.pump()
        self.assertIsNone(self.calls[1]["resumed"])
        self.assertIn("<saved-state>", self.calls[1]["prompt"])

    def test_the_limit_is_an_age_from_the_start_not_an_idle_timer(self):
        self.api.say("Acme Review, pricing: one")
        self.pump()
        for minutes in (50, 50):                              # inside two hours of the first, each after a long quiet
            self.clock.advance(minutes * 60)
            self.api.say("another")
            self.pump()
        self.clock.advance(30 * 60)                           # now two hours and more since the session began, though only 30 idle
        self.api.say("and another", reply_to=self.api.sent[0]["message_id"])
        self.pump()
        self.assertEqual([None, "sess-1", "sess-1", None], [c["resumed"] for c in self.calls])

    def test_a_context_limit_ends_a_session_early_and_keeps_decisions_and_questions(self):
        limit = self.mods["exchanges"].CONTEXT_TOKEN_LIMIT
        self.rx.runner = self.assistant(lambda c: "Which date?" if c["n"] == 1 else "Done.", tokens=limit + 1)
        self.api.say("Acme Review, pricing: use the revised forecast")
        self.pump()
        self.api.say("Friday")
        self.pump()
        second = self.calls[1]
        self.assertIsNone(second["resumed"])                   # refreshed
        self.assertIn("use the revised forecast", second["prompt"])
        self.assertIn("Which date?", second["prompt"])         # the unanswered question survived

    def test_a_conversation_resumed_two_days_later_keeps_its_saved_state(self):
        self.rx.runner = self.assistant(lambda c: "Which date?" if c["n"] == 1 else "Noted.")
        self.api.say("Acme Review, pricing: use the revised forecast")
        self.pump()
        question = self.api.sent[-1]["message_id"]
        self.clock.advance(2 * 86400)
        self.api.say("Friday", reply_to=question)
        self.pump()
        self.assertIsNone(self.calls[1]["resumed"])
        self.assertIn("use the revised forecast", self.calls[1]["prompt"])
        self.assertIn("Which date?", self.calls[1]["prompt"])

    def test_after_a_hundred_unrelated_messages_the_same_question_reads_none_of_them(self):
        self.api.say("Acme Review, pricing: what is the floor?")
        self.pump()
        for n in range(100):
            self.api.say("note: unrelated thought %d" % n)
        self.pump(quiet=1)
        self.api.say("and what is the floor now?")
        self.pump()
        prompt = self.calls[-1]["prompt"]
        self.assertNotIn("unrelated thought", prompt)
        self.assertLess(len(prompt), 2000)
        self.assertLess(self.mods["exchanges"].CONTEXT_TOKEN_LIMIT, 200_000)

    def test_turns_are_recorded_first_and_resumed_apart(self):
        self.api.say("Acme Review, pricing: one")
        self.pump()
        self.api.say("two")
        self.pump()
        turns = self.rx.load()["turns"]
        self.assertEqual([False, True], [t["resumed"] for t in turns])
        self.assertTrue(all("input_tokens" in t and "cost" in t for t in turns))


class TestBatching(TelegramCase):
    def test_a_burst_for_one_exchange_is_one_request(self):
        self.api.say("Acme Review, pricing: first")
        self.rx.poll_once(0)
        self.clock.advance(4)
        self.api.say("second")
        self.api.say("third")
        self.rx.poll_once(0)
        self.clock.advance(4)
        self.assertEqual(0, self.rx.flush())                     # still inside the ten-second window
        self.clock.advance(7)
        self.assertEqual(1, self.rx.flush())
        self.assertEqual(1, len(self.calls))
        for word in ("first", "second", "third"):
            self.assertIn(word, self.calls[0]["prompt"])

    def test_the_wait_is_thirty_seconds_at_most(self):
        self.api.say("Acme Review, pricing: first")
        self.rx.poll_once(0)
        for _ in range(4):
            self.clock.advance(9)                                # a message every nine seconds keeps the window open
            self.api.say("more")
            self.rx.poll_once(0)
        self.assertEqual(1, self.rx.flush())                     # thirty-six seconds from the first
        self.assertEqual(1, len(self.calls))

    def test_different_exchanges_stay_apart(self):
        self.api.say("Acme Review, pricing: alpha")
        self.api.say("Birch Entry, market sizing: beta")
        self.pump()
        self.assertEqual(2, len(self.calls))
        self.assertEqual(1, sum("alpha" in c["prompt"] for c in self.calls))
        self.assertEqual(1, sum("beta" in c["prompt"] for c in self.calls))

    def test_a_running_request_queues_its_followups(self):
        self.api.say("Acme Review, pricing: one")
        self.rx.poll_once(0)
        eid = self.rx.load()["messages"][str(self.api.update_id)]["exchange"]
        self.rx.running.add(eid)
        self.clock.advance(60)
        self.assertEqual([], self.rx.due(self.clock()))
        self.rx.running.discard(eid)
        self.assertEqual([eid], self.rx.due(self.clock()))


class TestDelivery(TelegramCase):
    def test_the_owner_gets_the_answer_as_a_reply_with_the_thread_named(self):
        mid = self.api.say("Acme Review, pricing: where do we stand?")
        self.pump()
        [sent] = self.api.sent
        self.assertEqual(PAIRED, sent["chat_id"])
        self.assertEqual(mid, sent["reply_parameters"]["message_id"])
        self.assertEqual("Acme Review, Pricing: Fine.", sent["text"])

    def test_delivery_to_any_other_chat_is_refused(self):
        td = self.mods["telegram_delivery"]
        with self.assertRaises(td.Refused):
            td.deliver(self.rx.bot, PAIRED, 31337, None, "hello")
        with self.assertRaises(td.Refused):
            td.deliver(self.rx.bot, PAIRED, PAIRED, {"chat": 31337}, "hello")
        with self.assertRaises(td.Refused):
            td.deliver(self.rx.bot, 0, 0, None, "hello")
        self.assertEqual([], self.api.sent)

    def test_the_assistant_has_no_tool_that_sends_to_telegram(self):
        self.api.say("Acme Review, pricing: where do we stand?")
        self.pump()
        tools = self.calls[0]["cmd"][self.calls[0]["cmd"].index("--allowedTools") + 1:]
        self.assertFalse([t for t in tools if "telegram" in t.lower() or "api.telegram" in t])
        servers = json.loads((Path(os.environ["GARRICK_JOBS_DIR"]) / "engine" / self.calls[0]["env"]["GARRICK_ENGINE_EXCHANGE"] / "mcp.json").read_text())
        self.assertEqual({"garrick", "garrick_hold"}, set(servers["mcpServers"]))

    def test_a_send_that_fails_is_uncertain_and_the_work_is_not_run_again(self):
        self.api.fail_send = True
        self.api.say("Acme Review, pricing: where do we stand?")
        self.pump()
        self.assertEqual(1, len(self.calls))
        [rec] = self.rx.load()["messages"].values()
        self.assertEqual(("completed", "uncertain"), (rec["state"], rec["delivery"]))
        self.pump(rounds=3)
        self.assertEqual(1, len(self.calls))

    def test_the_token_is_in_no_error(self):
        self.api.fail_send = True
        bot = self.mods["telegram_delivery"].Bot("123:SECRET", self.api.url)
        with self.assertRaises(self.mods["telegram_delivery"].ApiError) as caught:
            bot.send(PAIRED, "x")
        self.assertNotIn("SECRET", str(caught.exception))
        self.assertNotIn("123:SECRET", self.mods["telegram_delivery"].deliver(bot, PAIRED, PAIRED, None, "x")["why"])


class TestHeldSends(TelegramCase):
    def asking(self, cmd, env):
        os.environ.update({k: v for k, v in env.items() if k.startswith("GARRICK_ENGINE")})
        wanted = {"what": "Send the price sheet", "where": "dana@example.com",
                  "tool": "mcp__mail__send_message", "args": {}}
        msg = {"params": {"arguments": wanted, "name": "hold"}, "method": "tools/call"}
        msg.update(id=1, jsonrpc="2.0")
        self.mods["engine"].channels  # noqa: B018  (the engine is loaded)
        spec = importlib.util.spec_from_file_location("hold_tools", str(Path(self.root) / "System" / "status" / "hold_tools.py"))
        tools = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tools)
        tools.handle(msg)

    def test_a_held_send_runs_on_a_yes_reply_and_stays_held_without_one(self):
        self.rx.runner = self.assistant("I queued it.", act=lambda c, e: self.asking(c, e) if len(self.calls) == 1 else None)
        self.api.say("Acme Review, pricing: send the price sheet to Dana")
        self.pump()
        asked = self.api.sent[-1]
        self.assertIn("Send the price sheet", asked["text"])
        self.assertIn("Reply yes", asked["text"])
        hold = self.mods["hold"]
        [entry] = hold.pending()
        self.assertEqual("held", entry["state"])
        self.api.say("yes")                                     # not a reply: runs nothing
        self.pump()
        self.assertEqual("held", hold.get(entry["id"])["state"])
        self.api.say("yes", reply_to=self.api.sent[0]["message_id"])     # a reply, but to another message
        self.pump()
        self.assertEqual("held", hold.get(entry["id"])["state"])
        ran = []
        self.rx.runner = lambda cmd, tier, cwd, env: ran.append(cmd) or (0, {"text": "Sent.", "session_id": None, "usage": {}})
        self.api.say("yes", reply_to=asked["message_id"])
        self.pump()
        self.assertEqual("done", hold.get(entry["id"])["state"])
        self.assertEqual(1, len(ran))
        self.assertEqual("Sent.", self.texts()[-1].split(": ", 1)[-1])


class TestBesideTheDesk(TelegramCase):
    def test_the_assistant_is_told_to_leave_other_sessions_work_alone(self):
        brief = (STATUS / "engine-brief.md").read_text()
        for phrase in ("Re-read a file right before you change", "someone else's work in progress", "Commit only the files you changed, by name",
                       "never use `git add -A`"):
            self.assertIn(phrase, brief)

    def test_a_note_is_a_new_file_so_it_never_collides_with_a_desk_edit(self):
        write(self.work / "Acme Review" / "Threads" / "Pricing" / "Pricing.md", "an edit made at the desk, not committed\n")
        self.api.say("note for Acme pricing: the floor moved")
        self.pump()
        self.assertEqual("an edit made at the desk, not committed\n", (self.work / "Acme Review" / "Threads" / "Pricing" / "Pricing.md").read_text())
        self.assertEqual(1, len(list((self.root / "Inbox").glob("telegram-*.md"))))


class TestOneReceiver(TelegramCase):
    def test_a_webhook_is_another_consumer(self):
        self.api.webhook = "https://example.com/hook"
        self.assertIn("webhook", self.rx.consumers())

    def test_another_poller_is_found_by_updates_that_vanish(self):
        self.api.say("pending one")
        self.api.rival = True
        self.assertIn("Another program is confirming", self.rx.consumers())

    def test_nothing_else_reading_passes(self):
        self.assertIsNone(self.rx.consumers())
        self.api.say("a message waiting")
        self.assertIsNone(self.rx.consumers())                  # still there on the second read: nobody took it

    def test_the_service_does_not_start_while_another_consumer_reads_and_says_which(self):
        self.api.webhook = "https://example.com/hook"
        with self.assertRaises(SystemExit) as stop:
            self.rcv.serve(self.rx)
        self.assertEqual(3, stop.exception.code)
        row = self.mods["channel_state"].row(self.clock())
        self.assertEqual("conflict", row["state"])
        self.assertIn("webhook", row["said"])
        self.assertEqual([], [c for c in self.api.calls if c == "getUpdates"])      # never started polling

    def test_the_status_row_is_running_then_down_when_the_beats_stop(self):
        cs = self.mods["channel_state"]
        self.assertEqual("off", cs.row(self.clock())["state"])
        self.api.say("Acme Review, pricing: hi")
        self.rx.poll_once(0)
        cs.write(state="running")
        now = time.time()
        row = cs.row(now)
        self.assertEqual("running", row["state"])
        self.assertIn("Last message", row["said"])
        self.assertEqual("down", cs.row(now + cs.STALE + 5)["state"])        # a crash shows as down: the beat stopped

    def test_the_plist_is_a_keepalive_service_and_holds_no_secret(self):
        import plistlib
        raw = (REPO / "extras" / "jobs" / "launchd" / "garrick.gr-telegram.plist").read_bytes()
        plist = plistlib.loads(raw)
        self.assertEqual((True, True, "garrick.gr-telegram"), (plist["KeepAlive"], plist["RunAtLoad"], plist["Label"]))
        self.assertNotRegex(raw.decode().replace("telegram_receiver", ""), r"\d{6,}:[A-Za-z0-9_-]{20,}")        # no bot token
        self.assertNotIn("GARRICK_TELEGRAM_TOKEN", raw.decode())


class TestFaultsAndLimits(TelegramCase):
    def test_a_failed_resume_ends_the_session_and_the_next_turn_starts_from_saved_state(self):
        self.api.say("Acme Review, pricing: the floor is now 450")
        self.pump()
        self.rx.runner = lambda cmd, tier, cwd, env: (1, {"text": ""})
        self.api.say("and the volumes?")
        self.pump()
        ex = self.exchange_of("Acme Review, Pricing")
        self.assertIsNone(ex["session"])
        self.assertIn("did not work", self.texts()[-1])
        self.rx.runner = self.assistant()
        self.api.say("try again")
        self.pump()
        self.assertIsNone(self.calls[-1]["resumed"])
        self.assertIn("the floor is now 450", self.calls[-1]["prompt"])

    def test_a_cap_refusal_keeps_the_session(self):
        self.api.say("Acme Review, pricing: one")
        self.pump()
        self.rx.runner = lambda cmd, tier, cwd, env: (8, {"text": "", "refused": "the hourly limit is reached"})
        self.api.say("two")
        self.pump()
        self.assertEqual("sess-1", self.exchange_of("Acme Review, Pricing")["session"])

    def test_a_new_session_id_on_a_resumed_turn_does_not_move_the_start(self):
        seq = []

        def runner(cmd, tier, cwd, env):
            seq.append(1)
            return 0, {"text": "Fine.", "session_id": "other-%d" % len(seq), "usage": {"input_tokens": 10}, "cost_usd": 0.01}
        self.rx.runner = runner
        self.api.say("Acme Review, pricing: one")
        self.pump()
        started = self.exchange_of("Acme Review, Pricing")["started"]
        for _ in range(3):
            self.clock.advance(1800)
            self.api.say("another")
            self.pump()
        ex = self.exchange_of("Acme Review, Pricing")
        self.assertEqual(started, ex["started"])
        self.assertEqual("other-4", ex["session"])
        self.clock.advance(1800)
        self.assertTrue(self.mods["exchanges"].expired(ex, self.clock()))     # more than two hours after the start

    def test_a_fault_deciding_a_message_marks_it_failed_and_tells_the_owner(self):
        self.api.say("Acme Review, pricing: one")
        with mock.patch.object(self.mods["dispatcher"], "route", side_effect=RuntimeError("boom")):
            self.rx.poll_once(0)                                  # does not raise
        [rec] = self.rx.load()["messages"].values()
        self.assertEqual(("failed", "RuntimeError"), (rec["state"], rec["why"]))
        self.assertEqual("I could not read that; send it again.", self.texts()[-1])

    def test_a_saved_message_nobody_decided_is_decided_after_a_restart_once(self):
        self.api.say("Acme Review, pricing: one")
        with mock.patch.object(self.rx, "arrive", side_effect=SystemExit):
            with self.assertRaises(SystemExit):
                self.rx.poll_once(0)
        [rec] = self.rx.load()["messages"].values()
        self.assertEqual(("received", None), (rec["state"], rec["exchange"]))
        fresh = self.make()
        fresh.recover()
        [rec] = fresh.load()["messages"].values()
        self.assertEqual(("queued", True), (rec["state"], bool(rec["exchange"])))
        self.clock.advance(11)
        fresh.flush()
        self.assertEqual(1, len(self.calls))
        # one that is still undecided at a second restart is failed, not looped on
        self.api.say("Birch Entry, market sizing: two")
        with mock.patch.object(self.rx, "arrive", side_effect=SystemExit):
            with self.assertRaises(SystemExit):
                self.rx.poll_once(0)
        again = self.make()
        with mock.patch.object(again, "arrive", side_effect=SystemExit):
            with self.assertRaises(SystemExit):
                again.recover()
        again.recover()
        self.assertIn("failed", {r["state"] for r in again.load()["messages"].values()})

    def test_a_fault_in_a_turn_sends_one_short_reply_and_ends_the_session(self):
        self.api.say("Acme Review, pricing: one")
        self.pump()
        def boom(*a):
            raise RuntimeError("down")
        self.rx.runner = boom
        self.api.say("two")
        self.pump()
        self.assertIn("That did not work", self.texts()[-1])
        self.assertIsNone(self.exchange_of("Acme Review, Pricing")["session"])
        self.assertEqual(1, len([t for t in self.texts() if "That did not work" in t]))

    def test_recover_sweeps_old_exchanges(self):
        ex_mod = self.mods["exchanges"]
        old = ex_mod.new("Work", "Acme Review", "Pricing", "Old", self.clock() - 40 * 86400)
        self.rx.recover()
        self.assertIsNone(ex_mod.get(old["id"]))

    def test_a_value_in_a_note_header_cannot_end_its_line(self):
        self.assertEqual('"Acme, pricing key: injected"', self.rcv.yaml_quote("Acme, pricing\nkey: injected"))
        self.assertEqual('"a \\"b\\" c"', self.rcv.yaml_quote('a "b"\r\n c'))

    def test_exchange_writes_from_two_threads_are_all_kept(self):
        import threading
        ex_mod = self.mods["exchanges"]
        threads = [threading.Thread(target=lambda: ex_mod.new("Work", "Acme Review", "Pricing", "x")) for _ in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(12, len(ex_mod.load()["exchanges"]))


class TestRestart(TelegramCase):
    def test_a_request_that_was_running_is_not_run_again_and_a_queued_one_is_kept(self):
        self.api.say("Acme Review, pricing: one")
        self.rx.poll_once(0)
        uid = str(self.api.update_id)
        self.rx.set_message(uid, state="running")
        self.api.say("Birch Entry, market sizing: two")
        self.rx.poll_once(0)
        fresh = self.make()
        self.assertEqual(1, fresh.recover())
        states = {r["text"][:5]: r["state"] for r in fresh.load()["messages"].values()}
        self.assertEqual({"Acme ": "interrupted", "Birch": "queued"}, states)
        self.assertIn("interrupted", self.texts()[-1])
        self.clock.advance(11)
        fresh.flush()
        self.assertEqual(1, len(self.calls))
        self.assertIn("two", self.calls[0]["prompt"])

    def test_a_held_cap_leaves_the_request_waiting_and_calls_nothing_again(self):
        self.rx.runner = lambda cmd, tier, cwd, env: (8, {"text": "", "refused": "the hourly limit is reached"})
        self.api.say("Acme Review, pricing: one")
        self.pump()
        [rec] = self.rx.load()["messages"].values()
        self.assertEqual("waiting", rec["state"])
        self.assertIn("Not run: the hourly limit is reached", self.texts()[-1])
        count = len(self.api.sent)
        self.pump(rounds=3)
        self.assertEqual(count, len(self.api.sent))


if __name__ == "__main__":
    unittest.main()
