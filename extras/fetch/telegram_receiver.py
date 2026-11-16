#!/usr/bin/env python3
"""telegram_receiver.py: Garrick's one receiver for a private Telegram bot (#570). An always-on service.

    python3 telegram_receiver.py setup  --config ~/.config/garrick/telegram.json --workspace ~/Garrick
    python3 telegram_receiver.py check  --config ...        is another program reading this bot?
    python3 telegram_receiver.py run    --config ...        the service: what the launchd plist starts
    python3 telegram_receiver.py status --config ...        what the status page shows

**What it does.** It long-polls the Bot API, so a message is heard within seconds and the ten-second batching window and
thirty-second wait are reachable. It accepts a message only from the paired owner's private chat: another sender, a group
or a channel is ignored, and nothing of it is kept. It saves each accepted message to its own record *before* it
acknowledges the update, so a restart loses nothing and repeats nothing it already committed. Idle, it makes no model call
and no network call but the poll.

**What it decides, in code** (dispatcher.py): a message that starts with `note` is saved as a note under #569's contract
(a Markdown file in the workspace's `Inbox/` with `kind: note`, `from-owner: true`, the chat's fixed id being the check),
and never reaches an assistant; a reply to one of the bot's messages continues that message's exchange, whatever its first
word, and `yes` to a held-action message runs that action and nothing else does, while `no`, `cancel` or `stop` alone cancels it for good; a message that names a thread binds to it
(one question when the name is ambiguous); a message that names none continues the open exchange, or gets "Which thread?".

**What the assistant does.** Work for an exchange goes to the engine (engine.py) at the Telegram channel's level, in the
thread's zone, with a session that resumes between turns. The assistant writes its answer; this file sends it, to the
paired chat only (telegram_delivery.py). It has no tool that sends to Telegram, and a message cannot name a destination.
Messages for one exchange are batched, ten seconds from the last, thirty from the first at most; messages for different
exchanges stay apart; a request already running queues its follow-ups.

**One receiver for the bot.** Two programs confirming updates for one bot lose messages to each other, and Telegram answers
409 only for a webhook or two concurrent long polls, so the check cannot rely on that error. Before the first poll the
receiver asks `getWebhookInfo` (a webhook set means another consumer) and calls `getUpdates` with `timeout=0` twice a few
seconds apart: pending updates that disappear between the two calls, without this program confirming them, mean another
poller. Either one: it does not start, says which, and the status page shows it. A workspace that runs its own poller for the
same bot retires it when this ships.

**Walls.** Every zone may answer in full once the channel is on. Bot chats are not end-to-end encrypted: an answer from a
walled zone is held on Telegram's servers. Setup says so and asks the owner to accept it.

**The token** is in the macOS Keychain (see telegram_delivery.py), never an argument, a file or a log.

Standard library only, Python 3.9 or later.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import secrets
import sys
import threading
import time
from pathlib import Path
from typing import Callable, List, Optional

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent

BATCH_WINDOW = 10           # seconds with no further message before an exchange's batch is sent to the assistant
BATCH_MAX = 30              # seconds from the first message of a batch, at most
POLL_WAIT = 25              # seconds of one long poll
CHECK_GAP = 4               # seconds between the two getUpdates calls of the second-consumer check
STATE_FILE = "telegram-state.json"
EXPOSURE = ("Bot chats on Telegram are not end-to-end encrypted. An answer from a walled zone, sent here, is held on "
            "Telegram's servers. Every zone may answer in full once this channel is on; by pairing your chat you accept that.")
SELF_STATUS = ("queued", "running", "waiting", "completed", "failed")


def status_dir(ws: Path) -> Path:
    for place in (Path(ws) / "System" / "status", HERE.parent / "status"):
        if (place / "engine.py").is_file():
            return place
    raise SystemExit("telegram_receiver: no status extra found in %s; install it first" % ws)


def load_modules(ws: Path) -> dict:
    """The workspace's own status modules and intake script: engine, hold, exchanges, dispatcher, delivery, state."""
    folder = status_dir(ws)
    sys.path.insert(0, str(folder))
    mods = {}
    for name in ("channels", "hold", "exchanges", "dispatcher", "telegram_delivery", "channel_state", "engine"):
        spec = importlib.util.spec_from_file_location(name, str(folder / (name + ".py")))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        mods[name] = mod
    src = Path(ws) / "System" / "skills" / "intake" / "intake.py"
    if not src.is_file():
        src = HERE.parent.parent / "template" / "System" / "skills" / "intake" / "intake.py"
    sys.modules.pop("intake", None)
    sys.path.insert(0, str(src.parent))
    spec = importlib.util.spec_from_file_location("intake", str(src))
    intake = importlib.util.module_from_spec(spec)
    sys.modules["intake"] = intake
    spec.loader.exec_module(intake)
    mods["intake"] = intake
    return mods


def load_config(path: Path) -> dict:
    try:
        cfg = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise SystemExit("telegram_receiver: cannot read the config %s" % path)
    if not isinstance(cfg, dict) or not cfg.get("workspace"):
        raise SystemExit("telegram_receiver: the config names no workspace")
    return cfg


def yaml_quote(value: str) -> str:
    """A value as one double-quoted YAML line: whitespace and line breaks collapse to single spaces first, so a value
    cannot end the line and start a key of its own."""
    return '"%s"' % " ".join(str(value).split()).replace("\\", "\\\\").replace('"', '\\"')


class Receiver:
    """The receiver's whole state and behaviour, with the clock and the sleeper injectable so a test needs no waiting."""

    def __init__(self, ws: Path, bot, chat_id: int, mods: dict, runner: Optional[Callable] = None, now: Callable = time.time,
                 sleep: Callable = time.sleep):
        self.ws, self.bot, self.chat, self.m = Path(ws).resolve(), bot, int(chat_id), mods
        self.runner, self.now, self.sleep = runner, now, sleep
        self.lock = threading.RLock()
        self.running = set()                         # exchanges with a request under way: their follow-ups queue
        self.cap = None

    # ---------------------------------------------------------------- the record

    def state_path(self) -> Path:
        return self.m["hold"].jobs_dir() / STATE_FILE

    def load(self) -> dict:
        try:
            data = json.loads(self.state_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        data = data if isinstance(data, dict) else {}
        return {"offset": int(data.get("offset") or 0), "messages": data.get("messages") if isinstance(data.get("messages"), dict) else {},
                "turns": data.get("turns") if isinstance(data.get("turns"), list) else [], "ignored": int(data.get("ignored") or 0)}

    def save(self, data: dict) -> None:
        p = self.state_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".new")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(str(tmp), str(p))

    def set_message(self, uid, **fields) -> None:
        with self.lock:
            data = self.load()
            rec = data["messages"].get(str(uid))
            if rec is not None:
                rec.update(fields)
                self.save(data)

    # ---------------------------------------------------------------- the one-receiver check

    def consumers(self) -> Optional[str]:
        """None when nothing else reads this bot, else the reason. A webhook is another consumer; so is a poller whose
        confirmations make pending updates vanish between two reads of ours, which confirm nothing."""
        ApiError = self.m["telegram_delivery"].ApiError
        try:
            url = self.bot.webhook_url()
            if url:
                return "A webhook is set for this bot, so another program receives its messages. Remove the webhook, or use a bot of your own."
            first = self.bot.updates(timeout=0, limit=100)
            self.sleep(CHECK_GAP)
            second = self.bot.updates(timeout=0, limit=100)
        except ApiError as e:
            if e.code == 409:
                return "Telegram says another program is already reading this bot's messages."
            if getattr(e, "certificate", False):
                return self.bot.scrub(str(e))
            return "The bot could not be reached to check for another reader: %s" % self.bot.scrub(str(e))
        ids1, ids2 = [u["update_id"] for u in first], [u["update_id"] for u in second]
        if ids1 and (not ids2 or min(ids2) > min(ids1)):
            return ("Another program is confirming this bot's messages: pending updates disappeared between two reads that "
                    "confirmed nothing. Stop the other poller before Garrick's receiver takes over.")
        return None

    # ---------------------------------------------------------------- receiving

    def accept(self, update: dict) -> Optional[dict]:
        """The message an update holds when it is from the paired owner's private chat, else None."""
        msg = update.get("message")
        if not isinstance(msg, dict):
            return None
        chat, sender = msg.get("chat") or {}, msg.get("from") or {}
        if chat.get("type") != "private" or chat.get("id") != self.chat or sender.get("id") != self.chat or sender.get("is_bot"):
            return None
        text = msg.get("text")
        if not isinstance(text, str) or not text.strip():
            return None                               # text only: a voice file, a photo or a sticker is not handled here
        reply = msg.get("reply_to_message") if isinstance(msg.get("reply_to_message"), dict) else {}
        return {"message_id": int(msg.get("message_id") or 0), "text": text[:8000], "reply_to": reply.get("message_id"),
                "date": int(msg.get("date") or 0)}

    def poll_once(self, timeout: int = 0) -> int:
        """One getUpdates: each accepted message is saved to the record first, then the offset moves past the update.
        Returns the number of messages accepted."""
        with self.lock:
            data = self.load()
        updates = self.bot.updates(offset=data["offset"] or None, timeout=timeout)
        fresh = []
        for update in updates:
            uid = update["update_id"]
            with self.lock:
                data = self.load()
                if str(uid) not in data["messages"] and uid >= data["offset"]:
                    msg = self.accept(update)
                    if msg is None:
                        data["ignored"] += 1
                    else:
                        msg.update(id=uid, state="received", at=self.now(), exchange=None)
                        data["messages"][str(uid)] = msg
                        fresh.append(uid)
                data["offset"] = max(data["offset"], uid + 1)      # only once the message is in the record saved just below
                self.save(data)
        for uid in fresh:
            self.m["channel_state"].write(last_received=self.now(), state="running")
            self.arrive_safe(uid)
        return len(fresh)

    # ---------------------------------------------------------------- deciding, in code

    def name_of(self, ex: Optional[dict]) -> str:
        return (ex or {}).get("said") or ""

    def say(self, text: str, ex: Optional[dict] = None, reply_to: Optional[int] = None) -> dict:
        """A reply by code (a receipt, a question), through the one delivery path."""
        link = (lambda mid: self.m["exchanges"].link(ex["id"], mid, self.now())) if ex else None
        return self.m["telegram_delivery"].deliver(self.bot, self.chat, self.chat, ex, text, reply_to, self.name_of(ex), link)

    def arrive_safe(self, uid) -> None:
        """`arrive`, with a fault caught: the message is marked failed, and the owner is told in one line to send it
        again. A fault here must not end the service loop and leave a saved message that nothing will ever look at."""
        try:
            self.arrive(uid)
        except Exception as e:
            self.set_message(uid, state="failed", why=type(e).__name__)
            try:
                self.say("I could not read that; send it again.", None, (self.load()["messages"].get(str(uid)) or {}).get("message_id"))
            except Exception:
                pass

    def arrive(self, uid) -> None:
        """Decide what one saved message is, the moment it is saved: no assistant is asked."""
        data = self.load()
        msg = data["messages"][str(uid)]
        disp, ex_mod, hold, intake = self.m["dispatcher"], self.m["exchanges"], self.m["hold"], self.m["intake"]
        decision = disp.route(intake, self.ws, msg, hold.by_message, self.now(), hold.cancelled_by_message)
        do = decision["do"]
        if do == "note":
            self.file_note(msg, decision)
        elif do == "yes":
            self.run_held(msg, decision["held"])
        elif do in ("no", "gone"):
            self.cancel_held(msg, decision["held"])
        elif do == "done":
            ex = decision["exchange"]
            ex_mod.close(ex["id"], "done", self.now())
            self.set_message(uid, state="completed", exchange=ex["id"])
            self.say("Closed. Saved for later.", ex, msg["message_id"])
        elif do == "ask":
            self.ask_subject(msg, decision)
        else:
            if do == "bind":
                ex = self.bind(decision["place"])
                if decision.get("answer_to"):
                    ex_mod.close(decision["answer_to"], "answered", self.now())
            else:
                ex = decision["exchange"]
                if ex.get("closed"):
                    ex_mod.reopen(ex["id"])             # a reply to an old message: the same exchange, a new session
            ex_mod.link(ex["id"], msg["message_id"], self.now())
            self.set_message(uid, state="queued", exchange=ex["id"], text=decision.get("text", msg["text"]))

    def bind(self, place: dict) -> dict:
        """A new exchange bound to a place. A subject switch saves and closes the one open before it."""
        ex_mod = self.m["exchanges"]
        old = ex_mod.open_session(self.now())
        if old is not None and (old["zone"], old["project"], old["thread"]) != (place["zone"], place["project"], place["thread"]):
            ex_mod.close(old["id"], "switched", self.now())
        return ex_mod.new(place["zone"], place["project"], place["thread"], place["said"], self.now())

    def ask_subject(self, msg: dict, decision: dict) -> None:
        """One short question before any project content is read or changed. The question's message id leads back to a
        record that holds the message it is about, so an answer is read together with it."""
        if decision.get("kind") in ("which-subject", "nothing"):      # a question to say, not one to wait on: none is added
            self.set_message(msg["id"], state="waiting")
            return self.say(decision["question"], None, msg["message_id"])
        if decision.get("answer_to"):                       # asked again: the old question is settled, never counted twice
            self.m["exchanges"].close(decision["answer_to"], "answered", self.now())
        ex = self.m["exchanges"].new(None, None, None, "", self.now(),
                                     pending_subject={"text": decision["text"], "offer": decision.get("offer") or []})
        self.m["exchanges"].link(ex["id"], msg["message_id"], self.now())
        sent = self.say(decision["question"], ex, msg["message_id"])
        self.set_message(msg["id"], state="waiting", exchange=ex["id"])
        return sent

    def file_note(self, msg: dict, decision: dict) -> None:
        """Save a note under #569's contract. The fetcher's check was the chat's fixed id."""
        inbox = self.ws / "Inbox"
        inbox.mkdir(exist_ok=True)
        when = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(msg.get("date") or self.now()))
        head = ["---", "kind: note", "via: telegram", "from-owner: true"]
        if decision.get("destination"):
            head.append("destination: %s" % yaml_quote(decision["destination"]))
        head += ["date: %s" % yaml_quote(when), "---", ""]
        data = ("\n".join(head) + decision["text"] + "\n").encode("utf-8")
        for n in range(1, 1000):
            path = inbox / ("telegram-%s.md" % msg["id"] if n == 1 else "telegram-%s-%d.md" % (msg["id"], n))
            try:
                with open(str(path), "xb") as f:                         # exclusive: a file already there is never written over
                    f.write(data)
            except FileExistsError:
                try:
                    same = path.read_bytes() == data                     # a retry after a crash between the write and the record
                except OSError:
                    same = False
                if not same:
                    continue                                             # another file at this name: this note takes the next one
            self.m["intake"].record_note(self.ws, path, msg["id"])      # the ledger is what proves the note is ours (#584)
            break
        else:
            raise OSError("no free name for the note in the inbox")
        self.set_message(msg["id"], state="completed")
        self.say("Noted.", None, msg["message_id"])

    def run_held(self, msg: dict, held: dict) -> None:
        """The owner's yes, as a reply to the message that asked: run that one action, once."""
        eng, hold = self.m["engine"], self.m["hold"]
        said = hold.run(held["id"], self.ws, lambda w, rec: eng.execute_held(w, rec, self.runner))
        ex = self.m["exchanges"].get(held.get("exchange"))
        self.set_message(msg["id"], state="completed", exchange=held.get("exchange"))
        self.say(said, ex, msg["message_id"])

    def cancel_held(self, msg: dict, held: dict) -> None:
        """The owner's no, or a yes to an action already cancelled, as a reply to the message that asked: that action is
        cancelled (or stays so), nothing runs, and the answer says so (#585)."""
        said = "That action was cancelled. Nothing was done." if held.get("state") == "cancelled" \
            else self.m["hold"].cancel(held["id"])
        ex = self.m["exchanges"].get(held.get("exchange"))
        self.set_message(msg["id"], state="completed", exchange=held.get("exchange"))
        self.say(said, ex, msg["message_id"])

    # ---------------------------------------------------------------- the work

    def due(self, now: float) -> List[str]:
        """The exchanges whose queued messages are ready to go: ten seconds quiet, or thirty from the first. One
        request at a time per exchange: a running one holds its follow-ups."""
        data = self.load()
        by: dict = {}
        for rec in data["messages"].values():
            if rec["state"] == "queued" and rec.get("exchange") and rec["exchange"] not in self.running:
                by.setdefault(rec["exchange"], []).append(rec)
        ready = []
        for eid, recs in by.items():
            first, last = min(r["at"] for r in recs), max(r["at"] for r in recs)
            if now - last >= BATCH_WINDOW or now - first >= BATCH_MAX:
                ready.append(eid)
        return ready

    def work(self, eid: str) -> None:
        """One batch for one exchange: a turn of the assistant, its answer sent by code, the turn saved."""
        ex_mod, eng, hold, ch = self.m["exchanges"], self.m["engine"], self.m["hold"], self.m["channels"]
        with self.lock:
            data = self.load()
            batch = sorted((r for r in data["messages"].values() if r["state"] == "queued" and r.get("exchange") == eid), key=lambda r: r["at"])
            if not batch or eid in self.running:
                return
            self.running.add(eid)
            for r in batch:
                r["state"] = "running"
            self.save(data)
        ex, told = None, False
        try:
            ex = ex_mod.get(eid)
            if ex_mod.expired(ex, self.now()):          # between turns, by the clock: no model call to expire a session
                ex_mod.end_session(eid, self.now())
                ex = ex_mod.get(eid)
            fresh = not ex.get("session")
            context = ex_mod.resume_context(ex) if fresh and (ex.get("recent") or ex.get("pending")) else ""
            text = "\n\n".join(r["text"] for r in batch)
            if ex.get("project") and not ex.get("thread") and fresh:      # a project alone: answered from its hub and threads
                text = ("This is about the project %s. Answer from its hub note's Resume block and its threads' Next actions."
                        "\n\n%s" % (ex["project"], text))
            self.cap = self.cap or ch.capability(self.ws)
            got = eng.run(self.ws, "telegram", text, ex["zone"], {"id": eid, "session": ex.get("session")}, self.runner, self.cap,
                          fresh=fresh, context=context)
            usage = got.get("usage") or {}
            tokens = sum(int(usage.get(k) or 0) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
            answer = got["say"]
            pending = {"question": answer.strip().splitlines()[-1][:300]} if answer.strip().endswith("?") else None
            last = batch[-1]["message_id"]
            sent = self.say(answer, ex, last)
            told = True
            if pending and sent.get("ids"):
                pending["message_id"] = sent["ids"][-1]
            ex_mod.record_turn(eid, text, answer, got.get("session"), tokens, pending, self.now(), fresh)
            if not got.get("ok") and not str(got.get("say", "")).startswith("Not run:") and ex.get("session"):
                ex_mod.end_session(eid, self.now())      # a failed resume must not stick: the next turn starts from the saved state
            for e in got.get("held") or []:
                asked = self.say("%s Reply yes to run it, or no to cancel it." % hold.say(e), ex, last)
                if asked.get("ids"):
                    hold.note_message(e["id"], asked["ids"][-1])
            self.log_turn(eid, fresh, tokens, got)
            ended = "completed" if got.get("ok") else ("waiting" if str(got.get("say", "")).startswith("Not run:") else "failed")
            for r in batch:
                self.set_message(r["id"], state=ended, delivery=sent.get("state"))
        except Exception as e:                           # a fault is recorded, never retried on its own: no repeated calls
            for r in batch:
                self.set_message(r["id"], state="failed", why=type(e).__name__)
            try:
                if ex and ex.get("session"):
                    ex_mod.end_session(eid, self.now())
                if not told:
                    self.say("That did not work. Nothing more was done; send it again.", ex, batch[-1]["message_id"])
            except Exception:
                pass
        finally:
            with self.lock:
                self.running.discard(eid)

    def log_turn(self, eid: str, fresh: bool, tokens: int, got: dict) -> None:
        """Input and cost of each turn, first and resumed apart, so a release can compare them. Nothing of any text."""
        with self.lock:
            data = self.load()
            data["turns"] = (data["turns"] + [{"exchange": eid, "resumed": not fresh, "input_tokens": tokens, "cost": got.get("cost"),
                                               "at": self.now()}])[-200:]
            self.save(data)

    def flush(self) -> int:
        """Run what is due. Returns the number of batches run."""
        n = 0
        for eid in self.due(self.now()):
            self.work(eid)
            n += 1
        return n

    def recover(self) -> int:
        """After a restart: a request that was running is not run again (what it did may be committed already): its owner
        is told once. Queued messages stay queued. A message saved but never decided (no exchange) is decided now, once:
        a second restart with it still undecided marks it failed. Exchanges untouched for a month are dropped."""
        n, again = 0, []
        with self.lock:
            data = self.load()
            for uid, rec in data["messages"].items():
                if rec["state"] == "running":
                    rec["state"] = "interrupted"
                    n += 1
                elif rec["state"] == "received":
                    if rec.get("exchange"):
                        rec["state"] = "queued"
                    elif rec.get("retried"):
                        rec["state"] = "failed"
                        rec["why"] = "NotDecided"
                    else:
                        rec["retried"] = True
                        again.append(uid)
            self.save(data)
        try:
            self.m["exchanges"].sweep(self.now())
        except Exception:
            pass
        for uid in again:
            self.arrive_safe(uid)
        if n:
            try:
                self.say("A request was interrupted when Garrick restarted. Whatever it had already committed is saved; send it again if it did not finish.")
            except Exception:
                pass
        return n

    def counts(self) -> dict:
        out = {k: 0 for k in SELF_STATUS}
        for rec in self.load()["messages"].values():
            if rec["state"] in out:
                out[rec["state"]] += 1
        return out

    def beat(self) -> None:
        c = self.counts()
        self.m["channel_state"].write(state="running", queued=c["queued"], running=c["running"], waiting=c["waiting"])

    def step(self) -> int:
        """One round: poll without waiting, run what is due. What the service loop does, without the waiting."""
        self.poll_once(0)
        self.beat()
        return self.flush()


def serve(rx: Receiver, stop: Optional[threading.Event] = None) -> None:
    """The service: a worker thread runs due batches while this thread long-polls. A crash ends the process; the service
    manager starts it again, and `recover()` leaves nothing repeated."""
    stop = stop or threading.Event()
    problem = rx.consumers()
    if problem:
        rx.m["channel_state"].write(state="conflict", why=problem)
        print("telegram_receiver: %s" % problem, file=sys.stderr)
        raise SystemExit(3)
    rx.recover()
    rx.m["channel_state"].write(state="running", why="")

    def worker():
        while not stop.is_set():
            try:
                rx.flush()
                rx.beat()
            except Exception:
                pass
            stop.wait(1.0)
    t = threading.Thread(target=worker, daemon=True)
    t.start()
    ApiError = rx.m["telegram_delivery"].ApiError
    while not stop.is_set():
        try:
            rx.poll_once(POLL_WAIT)
        except ApiError as e:
            if e.code == 409:
                rx.m["channel_state"].write(state="conflict", why="Telegram says another program is reading this bot's messages.")
                raise SystemExit(3)
            rx.m["channel_state"].write(state="running", why=rx.bot.scrub(str(e)))
            stop.wait(5.0)


# ---------------------------------------------------------------- setup, pairing, the command line


def pair(rx: Receiver, code: str, wait: int = 120) -> Optional[int]:
    """Wait for the one-time code, sent to the bot from a private chat, and return that chat's id."""
    deadline = time.time() + wait
    offset = None
    while time.time() < deadline:
        for update in rx.bot.updates(offset=offset, timeout=10):
            offset = update["update_id"] + 1
            msg = update.get("message") or {}
            chat = msg.get("chat") or {}
            if chat.get("type") == "private" and (msg.get("text") or "").strip() == code and chat.get("id") == (msg.get("from") or {}).get("id"):
                return int(chat["id"])
    return None


def build(cfg: dict, runner: Optional[Callable] = None):
    ws = Path(cfg["workspace"]).expanduser().resolve()
    mods = load_modules(ws)
    td = mods["telegram_delivery"]
    token = td.keychain_token(*(cfg.get("keychain") or td.KEYCHAIN))
    if not token:
        raise SystemExit("telegram_receiver: no bot token in the Keychain (service %s, account %s). Store it with: "
                         "security add-generic-password -s %s -a %s -w" % (tuple(td.KEYCHAIN) * 2))
    bot = td.Bot(token, cfg.get("api_base") or td.API)
    return Receiver(ws, bot, int(cfg.get("chat_id") or 0), mods, runner)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Garrick's one receiver for a private Telegram bot.")
    ap.add_argument("op", choices=("setup", "check", "run", "status"))
    ap.add_argument("--config", required=True, help="the JSON config: workspace, chat_id, and optionally api_base")
    ap.add_argument("--workspace", help="setup: the workspace to pair this bot with")
    ap.add_argument("--yes", action="store_true", help="setup: accept the exposure note without asking")
    args = ap.parse_args(argv)
    cfg_path = Path(args.config).expanduser()
    if args.op == "setup":
        cfg = {"workspace": args.workspace or ""}
        if cfg_path.is_file():
            cfg = dict(load_config(cfg_path), **({"workspace": args.workspace} if args.workspace else {}))
        if not cfg.get("workspace"):
            raise SystemExit("telegram_receiver: say which workspace, with --workspace")
        print(EXPOSURE)
        if not args.yes and input("Accept that, and pair your private chat? [y/N] ").strip().lower() != "y":
            print("Nothing was set up.")
            return 1
        print("If you run a poller of your own for this bot, retire it now: two programs reading one bot lose messages to each other.")
        cfg.setdefault("chat_id", 0)
        rx = build(dict(cfg, chat_id=cfg.get("chat_id") or 0))
        problem = rx.consumers()
        if problem:
            print("Not set up: %s" % problem)
            return 3
        code = secrets.token_hex(3)
        print("Send this code to your bot, from your private chat with it, within two minutes: %s" % code)
        chat = pair(rx, code)
        if not chat:
            print("No message with that code arrived. Nothing was paired.")
            return 1
        cfg["chat_id"] = chat
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(json.dumps(cfg, indent=1), encoding="utf-8")
        os.chmod(str(cfg_path), 0o600)
        print("Paired. Copy extras/jobs/launchd/garrick.gr-telegram.plist to ~/Library/LaunchAgents/, edit it, and load it.")
        return 0
    cfg = load_config(cfg_path)
    if args.op == "status":
        mods = load_modules(Path(cfg["workspace"]).expanduser())
        print(json.dumps(mods["channel_state"].row()))
        return 0
    rx = build(cfg)
    if args.op == "check":
        problem = rx.consumers()
        print(problem or "No other program is reading this bot.")
        return 3 if problem else 0
    if not rx.chat:
        raise SystemExit("telegram_receiver: no chat is paired; run setup first")
    serve(rx)
    return 0


if __name__ == "__main__":
    sys.exit(main())
