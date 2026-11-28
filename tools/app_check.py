#!/usr/bin/env python3
"""The app cases: the Mac app's window, in real WebKit, on a fixture workspace.

    python3 tools/app_check.py                  # build a scratch app, run every case
    python3 tools/app_check.py --only edit      # one case, by a word of its name
    python3 tools/app_check.py --list           # the cases

What it does, and does not do. It installs a fixture workspace from this repository into a temporary folder, with a
home folder of its own, and builds a scratch app (make-app.sh --scratch) beside it. The scratch app has an identity
of its own, so it never answers for the app that is installed, and it starts with --drive, which shows no Dock icon,
opens no port and needs no permission: the case writes one JSON command per line to the app's stdin and reads one
answer per line from its stdout. Nothing here starts the installed app or a browser, and nothing reads this Mac's own
workspace. The window it opens is shown without taking the keys from the app in front.

The cases are in CASES. Each starts an app of its own on the fixture, and each is read from the page as the user
would see it: what is in the field, what is on the screen, how often the page loaded, and what reached the bridge.
It exits 0 where every case it ran passed, 1 where one failed, and 2 where it could not run (no Mac, no compiler).
"""
import argparse
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from queue import Empty, Queue

ROOT = Path(__file__).resolve().parent.parent
MAKE_APP = ROOT / "extras" / "status" / "app" / "make-app.sh"
GENERATION_META = '<meta name="garrick-generation" content="%s">'
GENERATION_RE = re.compile(r'<meta name="garrick-generation" content="(\d+)">')
WAITING = "A newer page is waiting"      # the window's subtitle while a reload is held (Garrick.swift)
SETTLE = 2.5                              # the app waits half a second before it loads a page it was told of
BATCH = 2.5                               # the page waits two seconds after a tick before it sends it


class Cannot(Exception):
    """The case could not run: that is neither a pass nor a failure of the app."""


def refuse_unless_scratch(app: Path) -> None:
    """A case starts only an app with a scratch identity: its bundle identifier ends in .scratch."""
    try:
        with open(app / "Contents" / "Info.plist", "rb") as f:
            ident = plistlib.load(f).get("CFBundleIdentifier", "")
    except (OSError, ValueError):
        raise Cannot("%s is not an app bundle." % app)
    if not str(ident).endswith(".scratch"):
        raise Cannot("%s is not a scratch build, so no case starts it (make-app.sh --scratch makes one)." % app)


def run(cmd, env, cwd=None, timeout=900):
    r = subprocess.run(cmd, env=env, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise Cannot("%s failed:\n%s%s" % (" ".join(map(str, cmd[:3])), r.stdout[-800:], r.stderr[-1500:]))
    return r.stdout


class Fixture:
    """A workspace installed from this repository into a folder of its own, a home folder of its own, and its page."""

    def __init__(self, base: Path):
        self.base = base
        self.home = base / "home"
        self.ws = base / "ws"
        self.home.mkdir(parents=True)
        self.env = dict(os.environ, HOME=str(self.home), GARRICK_JOBS_DIR=str(self.home / "jobs"),
                        GIT_CONFIG_GLOBAL=str(self.home / ".gitconfig"))
        for k in ("GARRICK_WORKSPACE", "GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0"):
            self.env.pop(k, None)
        (self.home / ".gitconfig").write_text("[user]\n\tname = Fixture\n\temail = fixture@acme.example\n", encoding="utf-8")

    def install(self):
        run([sys.executable, str(ROOT / "install.py"), "--config", str(ROOT / "examples" / "acme.json"), "--example",
             "--target", str(self.ws)], self.env)
        self.build_page()

    @property
    def page(self) -> Path:
        return self.ws / "System" / "generated" / "status.html"

    def build_page(self) -> str:
        run([sys.executable, str(self.ws / "System" / "status" / "status.py"), "--workspace", str(self.ws)], self.env)
        return self.page.read_text(encoding="utf-8")

    def build_app(self, dest: Path) -> Path:
        env = dict(self.env, GARRICK_SWIFT_OPT="-Onone")
        run(["bash", str(MAKE_APP), "--scratch", "--dest", str(dest), "--workspace", str(self.ws)], env)
        return dest / "Garrick.app"

    def put(self, text: str) -> None:
        """Put a page in place whole, as a build does: a temporary file beside it, renamed over it."""
        tmp = self.page.with_name("status.html.case%d" % time.monotonic_ns())
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, self.page)


def variant(text: str, mark: str, generation=None) -> str:
    """The page as a build would have made it, told apart by a mark on the body, and with a generation where given."""
    out = text.replace("<body ", '<body data-check="%s" ' % mark, 1)
    if generation is not None:
        meta = GENERATION_META % generation
        if GENERATION_RE.search(out):
            out = GENERATION_RE.sub(meta, out, 1)
        else:
            out = out.replace('<title>', meta + "<title>", 1)
    return out


class Drive:
    """One scratch app, started with --drive, and the lines it answers."""

    def __init__(self, app: Path, fx: Fixture, log: Path):
        refuse_unless_scratch(app)
        self.fx = fx
        self.n = 0
        self.lines: "Queue[dict]" = Queue()
        self.events = []
        self.log = open(log, "w")
        self.proc = subprocess.Popen([str(app / "Contents" / "MacOS" / "Garrick"), "--drive", str(fx.base)], env=fx.env,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log, text=True, cwd=str(fx.ws))
        threading.Thread(target=self._read, daemon=True).start()
        if not self._wait(lambda m: m.get("ready"), 60):
            raise Cannot("the scratch app did not start (see %s)" % log)
        self.wait(lambda: self.js("document.readyState") == "complete" and self.loads() >= 1, 60, "the page to load")

    def _read(self):
        for line in self.proc.stdout:
            if line.startswith("@drive "):
                try:
                    self.lines.put(json.loads(line[7:]))
                except ValueError:
                    pass

    def _wait(self, want, seconds):
        end = time.time() + seconds
        while time.time() < end:
            try:
                m = self.lines.get(timeout=0.2)
            except Empty:
                continue
            if want(m):
                return m
            self.events.append(m)
        return None

    def ask(self, op, **kw):
        self.n += 1
        n = self.n
        try:
            self.proc.stdin.write(json.dumps(dict(kw, op=op, id=n)) + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError):
            raise AssertionError("the app quit while the case ran (%s)" % self.log.name)
        m = self._wait(lambda m: m.get("id") == n, 30)
        if m is None:
            raise Cannot("the app did not answer %s" % op)
        return m

    def js(self, code):
        m = self.ask("js", code=code)
        if m.get("error"):
            raise Cannot("the page's script failed: %s" % m["error"])
        return m.get("result")

    def state(self):
        return self.ask("state")

    def loads(self):
        return self.state()["loads"]

    def bridge(self, clear=False):
        return self.ask("bridge", clear=clear)["messages"]

    def wait(self, test, seconds, what):
        end = time.time() + seconds
        while time.time() < end:
            if test():
                return
            time.sleep(0.2)
        raise AssertionError("gave up waiting for %s" % what)

    def close(self):
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()
        self.log.close()


# What the page reads and does, as the user's hands would.
TYPE = ("(function(){document.querySelector('[data-tab=\"overview\"]').click();var f=document.getElementById('tfind');f.focus();f.value='';"
        "document.execCommand('insertText',false,'harbour deal');return f.value+'|'+f.selectionStart+'|'+(document.activeElement===f)})()")
FIELD = "(function(){var f=document.getElementById('tfind');return f.value+'|'+f.selectionStart+'|'+(document.activeElement===f)})()"
CLEAR = "(function(){var f=document.getElementById('tfind');f.value='';f.dispatchEvent(new Event('input',{bubbles:true}));f.blur()})()"
MARK = "document.body.getAttribute('data-check')||''"


def generation_of(base: str) -> int:
    """The generation the fixture's own page carries; one a long way back where it carries none."""
    m = GENERATION_RE.search(base)
    return int(m.group(1)) if m else 10 ** 18


def settle_page(d: Drive, fx: Fixture, base: str, mark: str, generation=None):
    """Publish the page as a build that started after the one on show: a number past it, unless the case names one."""
    fx.later = getattr(fx, "later", 0) + 1
    fx.put(variant(base, mark, generation if generation is not None else generation_of(base) + 1000 * fx.later))


def case_edit_survives_a_build(d, fx, base):
    """Text typed in a field stays, with its caret, when a build lands; it loads once the field is empty."""
    typed = d.js(TYPE)
    assert typed == "harbour deal|12|true", "the field did not take the text: %r" % typed
    before = d.loads()
    settle_page(d, fx, base, "b")
    time.sleep(SETTLE)
    assert d.js(FIELD) == typed, "the text or the caret moved: %r" % d.js(FIELD)
    assert d.loads() == before and d.js(MARK) == "", "the page loaded under the text"
    d.js(CLEAR)
    d.wait(lambda: d.js(MARK) == "b", 8, "the newer page, once the field was empty")
    assert d.loads() == before + 1, "more than one load"


def case_edit_survives_a_loss_of_focus(d, fx, base):
    """The hold stays when the app is left, and when it is brought back."""
    typed = d.js(TYPE)
    before = d.loads()
    d.ask("leave")
    settle_page(d, fx, base, "b")
    time.sleep(SETTLE)
    assert d.loads() == before and d.js(MARK) == "", "the page loaded while the app was left"
    d.ask("back")
    time.sleep(1)
    assert d.js(FIELD) == typed and d.loads() == before, "the text did not survive the return"


def case_one_click_one_request(d, fx, base):
    """One click on a line's box sends one request over the bridge, however long the page waits."""
    d.bridge(clear=True)
    d.js("document.querySelector('.trow .tick').click();0")
    time.sleep(BATCH + 1.5)
    # The page also reads the record of what is running ("operations"), which changes nothing: only a request that acts counts.
    acts = [m for m in d.bridge() if "act" in m and m["act"].get("verb") != "operations"]
    assert len(acts) == 1, "%d requests at the bridge, not one: %r" % (len(acts), acts)
    assert acts[0]["act"].get("verb") in ("todo-done", "todo-undo"), acts[0]


def case_an_older_build_that_finishes_last_loses(d, fx, base):
    """Two builds, the second started later and published first: the window keeps the newer page."""
    g1, g2 = generation_of(base) + 5, generation_of(base) + 10
    settle_page(d, fx, base, "g2", g2)
    d.wait(lambda: d.js(MARK) == "g2", 10, "the newer page")
    shown = d.loads()
    settle_page(d, fx, base, "g1", g1)
    time.sleep(SETTLE)
    assert d.js(MARK) == "g2" and d.loads() == shown, "the older page replaced the newer: %r" % d.js(MARK)


def case_a_dialog_holds_the_page(d, fx, base):
    """An open dialog stays open while a build lands, and the page loads once it is closed."""
    d.js("document.getElementById('tadd').showModal();0")
    before = d.loads()
    settle_page(d, fx, base, "b")
    time.sleep(SETTLE)
    assert d.js("document.getElementById('tadd').open") is True and d.loads() == before, "the dialog was lost"
    d.js("document.getElementById('tadd').close();0")
    d.wait(lambda: d.js(MARK) == "b", 8, "the newer page, once the dialog closed")


def case_a_drag_holds_the_page(d, fx, base):
    """A drag under way holds the page, and its end lets the newer one in."""
    d.js("document.querySelector('.grip').dispatchEvent(new Event('dragstart',{bubbles:true}));0")
    before = d.loads()
    settle_page(d, fx, base, "b")
    time.sleep(SETTLE)
    assert d.loads() == before and d.js(MARK) == "", "the page loaded during the drag"
    d.js("document.querySelector('.grip').dispatchEvent(new Event('dragend',{bubbles:true}));0")
    d.wait(lambda: d.js(MARK) == "b", 8, "the newer page, once the drag ended")


def case_ticks_waiting_hold_the_page(d, fx, base):
    """A tick not yet sent holds the page; once it is sent the newer page loads."""
    d.js("document.querySelector('.trow .tick').click();0")
    before = d.loads()
    settle_page(d, fx, base, "b")
    time.sleep(1.2)
    assert d.loads() == before and d.js(MARK) == "", "the page loaded with a tick waiting"
    d.wait(lambda: d.js(MARK) == "b", 12, "the newer page, once the tick was sent")


def case_three_builds_make_one_load(d, fx, base):
    """Three builds during one hold end in one load, of the newest."""
    d.js(TYPE)
    before = d.loads()
    for i, mark in enumerate(("b1", "b2", "b3")):
        settle_page(d, fx, base, mark, generation_of(base) + 100 + i)
        time.sleep(0.8)
    time.sleep(SETTLE)
    assert d.loads() == before, "the page loaded during the hold"
    assert WAITING in d.state()["subtitle"], "the window did not say a page is waiting: %r" % d.state()["subtitle"]
    d.js(CLEAR)
    d.wait(lambda: d.js(MARK) == "b3", 8, "the newest page")
    time.sleep(SETTLE)
    assert d.loads() == before + 1, "%d loads for one hold" % (d.loads() - before)
    assert d.state()["subtitle"] == "", "the subtitle stayed after the load"


def case_nothing_to_lose_loads_as_before(d, fx, base):
    """With nothing to lose, a new page loads at once."""
    before = d.loads()
    settle_page(d, fx, base, "b")
    d.wait(lambda: d.js(MARK) == "b", 8, "the page, which has nothing to lose")
    assert d.loads() == before + 1


CASES = [("edit survives a build", case_edit_survives_a_build),
         ("it survives a loss of focus", case_edit_survives_a_loss_of_focus),
         ("one click sends one request", case_one_click_one_request),
         ("an older build that finishes last loses", case_an_older_build_that_finishes_last_loses),
         ("a dialog holds the page", case_a_dialog_holds_the_page),
         ("a drag holds the page", case_a_drag_holds_the_page),
         ("ticks waiting hold the page", case_ticks_waiting_hold_the_page),
         ("three builds make one load", case_three_builds_make_one_load),
         ("nothing to lose loads as before", case_nothing_to_lose_loads_as_before)]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run the app cases on a scratch app and a fixture workspace.")
    ap.add_argument("--only", action="append", default=[], metavar="WORD", help="run the cases whose name has this word (repeatable)")
    ap.add_argument("--list", action="store_true", help="name the cases and stop")
    ap.add_argument("--keep", action="store_true", help="leave the fixture and the app where they are, and say where")
    args = ap.parse_args(argv)
    if args.list:
        for name, _ in CASES:
            print(name)
        return 0
    chosen = [(n, f) for n, f in CASES if not args.only or any(w.lower() in n.lower() for w in args.only)]
    if sys.platform != "darwin":
        print("app_check: the cases run in the Mac app's own web view; nothing run here.", file=sys.stderr)
        return 2
    base = Path(tempfile.mkdtemp(prefix="garrick-app-check-"))
    failed = 0
    try:
        fx = Fixture(base)
        fx.install()
        app = fx.build_app(base / "app")
        refuse_unless_scratch(app)
        original = fx.page.read_text(encoding="utf-8")
        for n, (name, case) in enumerate(chosen):
            fx.put(original)
            d = None
            try:
                d = Drive(app, fx, base / ("app-%d.log" % n))
                case(d, fx, original)
                print("pass  %s" % name)
            except AssertionError as e:
                failed += 1
                print("FAIL  %s: %s" % (name, e))
            finally:
                if d:
                    d.close()
    except Cannot as e:
        print("app_check: %s" % e, file=sys.stderr)
        return 2
    finally:
        if args.keep:
            print("kept: %s" % base)
        else:
            shutil.rmtree(base, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
