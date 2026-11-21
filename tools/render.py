#!/usr/bin/env python3
"""Look-check screenshots of an HTML page, through a headless shell and never the Chrome app.

    python3 tools/render.py PAGE --out DIR [--width 390 1280] [--theme light dark]
                            [--height 900] [--full-page] [--timeout 60] [--profile-dir DIR]

PAGE is a URL or a file path. One PNG per width and theme is written to DIR as
`<name>-<width>-<theme>.png`. One browser process serves the whole list, over the Chrome
DevTools Protocol on a pipe (file descriptors 3 and 4). It uses a throwaway profile and is
killed when the time is up or anything fails, so nothing is left running.

The browser is a headless shell, never an app bundle: the full Chrome app bounces its Dock icon
once per screenshot and leaves crash dumps in the user's Chrome folder. Order: the
GARRICK_HEADLESS_SHELL environment variable, Playwright's cache, `chrome-headless-shell` on PATH.
To install one: npx playwright install chromium-headless-shell

This is a development tool of this repository. It is not shipped, and uses only the standard library.
"""
import argparse
import base64
import json
import os
import re
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

HINT = ("No headless shell found. Install one with: npx playwright install chromium-headless-shell\n"
        "or set GARRICK_HEADLESS_SHELL to a chrome-headless-shell binary. "
        "The Chrome app is never used: it bounces in the Dock and leaves crash dumps.")
CACHES = ("Library/Caches/ms-playwright", ".cache/ms-playwright")
SETTLE = 0.3
FLAGS = ["--headless", "--no-first-run", "--disable-gpu", "--hide-scrollbars",
         "--disable-crash-reporter", "--disable-breakpad", "--no-default-browser-check"]


class RenderError(Exception):
    pass


class NoBrowser(RenderError):
    pass


def inside_app(path):
    """True when the path, or the path it points to, runs inside a `.app` bundle."""
    for p in (Path(path), Path(os.path.realpath(path))):
        if any(part.lower().endswith(".app") for part in p.parts):
            return True
    return False


def _revision(path):
    nums = re.findall(r"\d+", Path(path).name)
    return int(nums[-1]) if nums else 0


def find_browser(env=None):
    """The headless shell to run, or NoBrowser. Reads only `env` and the cache folders under its HOME."""
    env = os.environ if env is None else env
    given = env.get("GARRICK_HEADLESS_SHELL")
    if given:
        if inside_app(given):
            raise NoBrowser("%s is inside an app bundle. Point GARRICK_HEADLESS_SHELL at a "
                            "chrome-headless-shell binary instead." % given)
        if not (os.path.isfile(given) and os.access(given, os.X_OK)):
            raise NoBrowser("GARRICK_HEADLESS_SHELL is not an executable file: %s" % given)
        return given
    home = env.get("HOME")
    for cache in CACHES if home else ():
        root = Path(home) / cache
        for shell_dir in sorted(root.glob("chromium_headless_shell-*"), key=_revision, reverse=True):
            for exe in sorted(shell_dir.glob("chrome-headless-shell-*/chrome-headless-shell"),
                              key=lambda p: p.parent.name, reverse=True):
                if exe.is_file() and os.access(exe, os.X_OK) and not inside_app(exe):
                    return str(exe)
    found = shutil.which("chrome-headless-shell", path=env.get("PATH", ""))
    if found and not inside_app(found):
        return found
    raise NoBrowser(HINT)


def page_url(page):
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", page) or page.startswith(("about:", "data:")):
        return page
    return Path(page).resolve().as_uri()


def page_name(page):
    u = urlparse(page_url(page))
    stem = Path(u.path).stem if u.path.strip("/") else ""
    name = stem or u.netloc or "page"
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or "page"


def shot_name(page, width, theme):
    return "%s-%d-%s.png" % (page_name(page), width, theme)


class Pipe:
    """The DevTools protocol over a pipe: JSON messages, each ended by a NUL byte."""

    def __init__(self, write_fd, read_fd, deadline):
        self.w, self.r, self.deadline = write_fd, read_fd, deadline
        self.buf = b""
        self.next_id = 0
        self.events = []

    def send(self, method, params=None, session=None):
        self.next_id += 1
        msg = {"id": self.next_id, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        data = json.dumps(msg).encode() + b"\0"
        while data:
            data = data[os.write(self.w, data):]
        return self.next_id

    def _message(self):
        while b"\0" not in self.buf:
            left = self.deadline - time.monotonic()
            if left <= 0:
                raise RenderError("Timed out waiting for the browser.")
            if not select.select([self.r], [], [], left)[0]:
                continue
            chunk = os.read(self.r, 65536)
            if not chunk:
                raise RenderError("The browser closed the pipe.")
            self.buf += chunk
        raw, self.buf = self.buf.split(b"\0", 1)
        return json.loads(raw)

    def call(self, method, params=None, session=None):
        want = self.send(method, params, session)
        while True:
            msg = self._message()
            if msg.get("id") == want:
                if "error" in msg:
                    raise RenderError("%s failed: %s" % (method, msg["error"].get("message", msg["error"])))
                return msg.get("result", {})
            if "method" in msg:
                self.events.append(msg)

    def wait_event(self, method, session=None):
        while True:
            for i, e in enumerate(self.events):
                if e["method"] == method and e.get("sessionId") == session:
                    del self.events[i]
                    return e
            msg = self._message()
            if "method" in msg:
                self.events.append(msg)


def render(pages, out_dir, widths=(390, 1280), themes=("light", "dark"), height=900,
           full_page=False, timeout=60.0, profile_dir=None, env=None, settle=SETTLE):
    """Write one PNG per page, width and theme with one browser process. Returns the paths."""
    exe = find_browser(env)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    own_profile = profile_dir is None
    profile = Path(tempfile.mkdtemp(prefix="garrick-render-")) if own_profile else Path(profile_dir)
    profile.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    to_child_r, to_child_w = os.pipe()
    from_child_r, from_child_w = os.pipe()

    def wire():  # runs in the child: the protocol is on descriptors 3 and 4
        os.dup2(to_child_r, 3)
        os.dup2(from_child_w, 4)

    proc = None
    written = []
    try:
        proc = subprocess.Popen([exe, *FLAGS, "--remote-debugging-pipe", "--user-data-dir=" + str(profile),
                                 "about:blank"],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                pass_fds=(3, 4), preexec_fn=wire, start_new_session=True,
                                env=dict(os.environ if env is None else env))
        os.close(to_child_r)
        os.close(from_child_w)
        to_child_r = from_child_w = -1
        cdp = Pipe(to_child_w, from_child_r, deadline)
        target = cdp.call("Target.createTarget", {"url": "about:blank"})["targetId"]
        session = cdp.call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
        cdp.call("Page.enable", session=session)
        for page in pages:
            url = page_url(page)
            for width in widths:
                for theme in themes:
                    cdp.call("Emulation.setDeviceMetricsOverride",
                             {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False},
                             session)
                    cdp.call("Emulation.setEmulatedMedia",
                             {"features": [{"name": "prefers-color-scheme", "value": theme}]}, session)
                    cdp.events.clear()
                    cdp.call("Page.navigate", {"url": url}, session)
                    cdp.wait_event("Page.loadEventFired", session)
                    time.sleep(settle)
                    shot = {"format": "png"}
                    if full_page:
                        size = cdp.call("Page.getLayoutMetrics", session=session)
                        box = size.get("cssContentSize") or size.get("contentSize") or {}
                        shot.update(captureBeyondViewport=True, clip={
                            "x": 0, "y": 0, "width": box.get("width", width),
                            "height": max(box.get("height", height), height), "scale": 1})
                    data = cdp.call("Page.captureScreenshot", shot, session)["data"]
                    path = out_dir / shot_name(page, width, theme)
                    path.write_bytes(base64.b64decode(data))
                    written.append(path)
        return written
    finally:
        for fd in (to_child_r, to_child_w, from_child_r, from_child_w):
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
        if proc is not None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            proc.wait()
        if own_profile:
            shutil.rmtree(profile, ignore_errors=True)


def main(argv=None, env=None):
    ap = argparse.ArgumentParser(description="Screenshots of a page in a headless shell.")
    ap.add_argument("page", nargs="+", help="a URL or a file path")
    ap.add_argument("--out", required=True, help="folder for the PNG files")
    ap.add_argument("--width", nargs="+", type=int, default=[1280])
    ap.add_argument("--theme", nargs="+", choices=["light", "dark"], default=["light"])
    ap.add_argument("--height", type=int, default=900)
    ap.add_argument("--full-page", action="store_true", help="capture the whole page, not one screen")
    ap.add_argument("--timeout", type=float, default=60, help="seconds for the whole run")
    ap.add_argument("--profile-dir", help="profile folder to use; it is not deleted")
    a = ap.parse_args(argv)
    try:
        paths = render(a.page, a.out, a.width, a.theme, a.height, a.full_page, a.timeout,
                       a.profile_dir, env)
    except NoBrowser as e:
        print(e, file=sys.stderr)
        return 2
    except RenderError as e:
        print("render: %s" % e, file=sys.stderr)
        return 1
    for p in paths:
        print(p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
