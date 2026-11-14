#!/usr/bin/env python3
"""telegram_delivery.py: the Bot API client, and the only way a reply reaches Telegram (#570).

**Code sends, the assistant writes.** The assistant writes its answer into the exchange record; this file sends it. It
checks, every time, that the destination is the paired private chat and that the exchange belongs to that chat, and it
refuses any other destination. The assistant has no tool that sends to Telegram, so it cannot choose one, and nothing in
a message's text can: `deliver()` takes the chat from the pairing, never from the text.

**Text only.** A reply opens with its thread's name, so a wrong guess about the thread is seen at once.

**The token** is read from the macOS Keychain (`security find-generic-password -s garrick-telegram -a bot -w`, which prints
the secret to this process's pipe and nowhere else): it is never an argument of a Garrick process, never written to a
file, a log or the status page, and `Bot` scrubs it from every error it raises. Store it once, by piping it in:
`security add-generic-password -s garrick-telegram -a bot -w` and typing it at the prompt.

**Delivery is tracked apart from the work.** A send that fails or times out is recorded as `uncertain`, and the work that
made the reply is never run again for it: Garrick records the uncertainty rather than promising exactly-once delivery.

Standard library only, Python 3.9 or later.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, List, Optional

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

API = "https://api.telegram.org"
KEYCHAIN = ("garrick-telegram", "bot")
CHUNK = 3800                    # characters of one message; Telegram's own limit is 4096
TIMEOUT = 40                    # seconds a call waits (a long poll adds its own wait)


class Refused(Exception):
    """A delivery this file will not make."""


class ApiError(Exception):
    """The Bot API said no, or could not be reached. Never carries the token."""

    def __init__(self, message: str, code: Optional[int] = None):
        super().__init__(message)
        self.code = code


def keychain_token(service: str = KEYCHAIN[0], account: str = KEYCHAIN[1]) -> Optional[str]:
    """The bot's token from the macOS Keychain, or None. The secret comes back on a pipe, never in an argument."""
    try:
        r = subprocess.run(["security", "find-generic-password", "-s", service, "-a", account, "-w"], capture_output=True, text=True,
                           timeout=20, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    token = r.stdout.strip() if r.returncode == 0 else ""
    return token or None


class Bot:
    """A small Bot API client over urllib. `base` is the API's address: Telegram's, or a fake on localhost in a test."""

    def __init__(self, token: str, base: str = API):
        if not token:
            raise ApiError("no token")
        self._token, self.base = token, base.rstrip("/")

    def scrub(self, text: str) -> str:
        return str(text).replace(self._token, "<token>")

    def call(self, method: str, params: Optional[dict] = None, wait: float = 0) -> object:
        url = "%s/bot%s/%s" % (self.base, self._token, method)
        data = json.dumps(params or {}).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT + wait) as r:
                body = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise ApiError("the Bot API answered %d to %s" % (e.code, method), e.code) from None
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise ApiError("the Bot API could not be reached for %s (%s)" % (method, type(e).__name__)) from None
        if not isinstance(body, dict) or not body.get("ok"):
            code = body.get("error_code") if isinstance(body, dict) else None
            raise ApiError("the Bot API refused %s" % method, code)
        return body.get("result")

    def updates(self, offset: Optional[int] = None, timeout: int = 0, limit: int = 100) -> List[dict]:
        params = {"timeout": timeout, "limit": limit, "allowed_updates": ["message"]}
        if offset is not None:
            params["offset"] = offset
        return self.call("getUpdates", params, wait=timeout) or []

    def webhook_url(self) -> str:
        info = self.call("getWebhookInfo") or {}
        return str(info.get("url") or "") if isinstance(info, dict) else ""

    def send(self, chat_id: int, text: str, reply_to: Optional[int] = None) -> int:
        params = {"chat_id": chat_id, "text": text}
        if reply_to:
            params["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
        got = self.call("sendMessage", params)
        return int(got["message_id"]) if isinstance(got, dict) and "message_id" in got else 0


def chunks(text: str) -> List[str]:
    text = text.strip() or "Done."
    out = []
    while len(text) > CHUNK:
        cut = text.rfind("\n", 0, CHUNK)
        cut = cut if cut > CHUNK // 2 else text.rfind(" ", 0, CHUNK)
        cut = cut if cut > CHUNK // 2 else CHUNK
        out.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    return out + [text]


def opening(name: str, text: str) -> str:
    """The reply as sent: it opens with its thread's name."""
    text = text.strip()
    return "%s: %s" % (name, text) if name else text


def deliver(bot: Bot, paired_chat: int, chat_id: int, exchange: Optional[dict], text: str, reply_to: Optional[int] = None,
            name: str = "", link: Optional[Callable[[int], None]] = None) -> dict:
    """Send `text` to the paired private chat, as a reply to the message that started the work. Refuses any other chat,
    and an exchange that belongs to any other: the destination is the pairing's, never the text's or the assistant's.
    Returns {"state": "sent"|"uncertain", "ids": [...]}; `link(id)` is called for each message sent, so a reply to it
    resolves to the exchange."""
    if not paired_chat or int(chat_id) != int(paired_chat):
        raise Refused("that is not the paired chat")
    if exchange is not None and exchange.get("chat") not in (None, int(paired_chat)):
        raise Refused("that exchange does not belong to the paired chat")
    ids = []
    try:
        for n, part in enumerate(chunks(opening(name, text))):
            mid = bot.send(int(paired_chat), part, reply_to if n == 0 else None)
            ids.append(mid)
            if link and mid:
                link(mid)
    except ApiError as e:
        return {"state": "uncertain", "ids": ids, "why": bot.scrub(str(e))}
    return {"state": "sent", "ids": ids}
