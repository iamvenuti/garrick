#!/usr/bin/env python3
"""consent.py: the page where the owner lets an assistant in, with the code the Mac shows (preview).

The page sits on the service's own address. It shows the name the assistant gave itself, two choices (read, write) and one box for
the six-digit pairing code that Settings shows at the Mac. A code works once and lives five minutes. Five wrong codes lock the page for
fifteen minutes, and a locked page takes no code at all, the right one included.

The name on the page is the client's own word, so it is shown as text only, cut short, and never as markup. The page is never framed,
sends no referrer and is never cached. The words are plain: no path, no key, no command.

Runs in the extra's own runtime.
"""
from __future__ import annotations

import html
import sys
from typing import Callable
from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

sys.dont_write_bytecode = True

HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
           "X-Content-Type-Options": "nosniff"}
CSP = ("default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'; "
       "form-action 'self' https://claude.ai https://claude.com http://127.0.0.1:* http://localhost:*")
LOOK = ("body{font:16px/1.5 system-ui,sans-serif;max-width:30rem;margin:2rem auto;padding:0 1rem;color:#1a1a1a;background:#fff}"
        "@media(prefers-color-scheme:dark){body{color:#eee;background:#161616}input,button{color:#eee;background:#222;border-color:#666}}"
        "h1{font-size:1.3rem}label{display:block;margin:.5rem 0}input[type=text]{font-size:1.4rem;letter-spacing:.3em;width:8em;"
        "padding:.3rem;border:1px solid #888;border-radius:6px}button{font-size:1rem;padding:.5rem 1.2rem;border-radius:6px;"
        "border:1px solid #888;cursor:pointer}.say{border-left:4px solid #b00;padding-left:.7rem}.muted{color:#777}")


def page(body: str, status: int = 200) -> Response:
    text = ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>Connect an assistant</title><style>%s</style></head><body>%s</body></html>" % (LOOK, body))
    return HTMLResponse(text, status_code=status, headers=dict(HEADERS, **{"Content-Security-Policy": CSP}))


def minutes(seconds: int) -> str:
    n = max(1, (seconds + 59) // 60)
    return "%d minute%s" % (n, "" if n == 1 else "s")


def form(pid: str, name: str, say: str = "", ago: int = 0) -> str:
    note = '<p class="say">%s</p>' % html.escape(say) if say else ""
    return ('<h1>Connect an assistant</h1>%s<p>%s asks to connect to your Garrick workspace on this Mac.</p>'
            '<p>This sign-in was started %s. Go on only if you started it yourself a moment ago. If you did not, close this page.</p>'
            '<form method="post" action="/consent"><input type="hidden" name="p" value="%s">'
            '<p>What may it do?</p>'
            '<label><input type="checkbox" name="read" value="1" checked> Read what your open zones hold</label>'
            '<label><input type="checkbox" name="write" value="1"> Save notes and actions in them</label>'
            '<p>Type the six-digit code that Settings shows on your Mac.</p>'
            '<p><input type="text" name="code" inputmode="numeric" autocomplete="off" maxlength="6" pattern="[0-9]{6}" '
            'aria-label="Code from your Mac" required autofocus></p>'
            '<p><button type="submit">Connect</button></p></form>'
            '<p class="muted">Zones that are walled stay out of reach unless you turn them on in Settings.</p>'
            % (note, html.escape(name), ago_words(ago), html.escape(pid, quote=True)))


def ago_words(seconds: int) -> str:
    n = max(0, int(seconds)) // 60
    return "less than a minute ago" if n < 1 else ("%d minute%s ago" % (n, "" if n == 1 else "s"))


def age(row, now: float) -> int:
    return int(now - float(row.get("made") or now))


GONE = page('<h1>This link has run out</h1><p>Start again from your assistant.</p>', 400)


def locked(seconds: int) -> Response:
    return page('<h1>Try again later</h1><p class="say">Too many wrong codes were typed. This page takes a code again in about %s.</p>'
                % minutes(seconds), 429)


def routes(provider, store, clock: Callable[[], float], origin: str):
    """The two handlers of the consent page: (show, answer)."""

    async def show(request: Request) -> Response:
        pid = request.query_params.get("p", "")
        row = store.get_pending(pid, clock())
        if not row:
            return GONE
        wait = store.consent_locked(clock())
        return locked(wait) if wait else page(form(pid, row["name"], ago=age(row, clock())))

    async def answer(request: Request) -> Response:
        sent = request.headers.get("origin")
        if sent and sent.rstrip("/") != origin.rstrip("/") and urlsplit(sent).hostname not in ("127.0.0.1", "localhost"):
            return page("<h1>That did not come from this page</h1>", 403)
        data = await request.form()
        pid, code = str(data.get("p") or ""), str(data.get("code") or "")
        row = store.get_pending(pid, clock())
        if not row:
            return GONE
        wait = store.consent_locked(clock())
        if wait:
            return locked(wait)
        classes = [c for c in ("read", "write") if data.get(c)]
        if "read" not in classes:
            return page(form(pid, row["name"], "It needs to be allowed to read. Tick that box to connect.", age(row, clock())), 400)
        if not store.check_pairing_code(code, clock()):
            wait = store.consent_locked(clock())
            return locked(wait) if wait else page(form(pid, row["name"], "That code is not right, or it has run out.", age(row, clock())), 400)
        target = provider.finish(pid, classes)
        if target is None:
            return GONE
        return RedirectResponse(target, status_code=302, headers=HEADERS)

    return show, answer
