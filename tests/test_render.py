"""tools/render.py: browser discovery, the app refusal, file names and the pipe protocol.

No test starts a real browser or reads this Mac's caches: HOME and PATH point at temp folders,
and a small Python script stands in for the shell and speaks the pipe protocol.
"""
import base64
import importlib.util
import io
import os
import stat
import sys
import tempfile
import textwrap
import unittest
from contextlib import redirect_stderr
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("render_tool", REPO / "tools" / "render.py")
render = importlib.util.module_from_spec(spec)
spec.loader.exec_module(render)

PNG = base64.b64encode(b"\x89PNG fake").decode()

FAKE = textwrap.dedent('''\
    #!%s
    import json, os, sys
    log = open(os.environ["FAKE_LOG"], "a")
    log.write("start %%d %%s\\n" %% (os.getpid(), " ".join(sys.argv[1:])))
    log.flush()
    buf = b""
    while True:
        chunk = os.read(3, 65536)
        if not chunk:
            break
        buf += chunk
        while b"\\0" in buf:
            raw, buf = buf.split(b"\\0", 1)
            m = json.loads(raw)
            log.write(json.dumps([m["method"], m.get("params"), m.get("sessionId")]) + "\\n")
            log.flush()
            res = {}
            if m["method"] == "Target.createTarget":
                res = {"targetId": "T1"}
            elif m["method"] == "Target.attachToTarget":
                res = {"sessionId": "S1"}
            elif m["method"] == "Page.getLayoutMetrics":
                res = {"cssContentSize": {"width": 500, "height": 2000}}
            elif m["method"] == "Page.captureScreenshot":
                res = {"data": "%s"}
            out = {"id": m["id"], "result": res}
            if m.get("sessionId"):
                out["sessionId"] = m["sessionId"]
            os.write(4, json.dumps(out).encode() + b"\\0")
            if m["method"] == "Page.navigate":
                ev = {"method": "Page.loadEventFired", "params": {}, "sessionId": m["sessionId"]}
                os.write(4, json.dumps(ev).encode() + b"\\0")
''')


def make_exe(path, text="#!/bin/sh\nexit 0\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.env = {"HOME": str(self.home), "PATH": str(self.bin)}
        self.addCleanup(self._tmp.cleanup)

    def shell(self, cache, rev, arch="mac-arm64"):
        return make_exe(self.home / cache / ("chromium_headless_shell-%s" % rev) /
                        ("chrome-headless-shell-" + arch) / "chrome-headless-shell")


class DiscoveryTest(Base):
    def test_env_override_wins(self):
        exe = make_exe(self.tmp / "mine" / "shell")
        self.shell("Library/Caches/ms-playwright", 1200)
        make_exe(self.bin / "chrome-headless-shell")
        self.env["GARRICK_HEADLESS_SHELL"] = str(exe)
        self.assertEqual(render.find_browser(self.env), str(exe))

    def test_cache_beats_path_and_newest_revision_wins(self):
        self.shell("Library/Caches/ms-playwright", 999)
        new = self.shell("Library/Caches/ms-playwright", 1243)
        make_exe(self.bin / "chrome-headless-shell")
        self.assertEqual(render.find_browser(self.env), str(new))

    def test_linux_cache(self):
        exe = self.shell(".cache/ms-playwright", 1100, "linux")
        self.assertEqual(render.find_browser(self.env), str(exe))

    def test_path_is_last(self):
        exe = make_exe(self.bin / "chrome-headless-shell")
        self.assertEqual(render.find_browser(self.env), str(exe))

    def test_nothing_found_gives_the_install_hint(self):
        with self.assertRaises(render.NoBrowser) as c:
            render.find_browser(self.env)
        self.assertIn("npx playwright install chromium-headless-shell", str(c.exception))

    def test_exit_code_and_hint(self):
        err = io.StringIO()
        with redirect_stderr(err):
            code = render.main([str(self.tmp / "p.html"), "--out", str(self.tmp / "o")], env=self.env)
        self.assertEqual(code, 2)
        self.assertIn("npx playwright install chromium-headless-shell", err.getvalue())
        self.assertFalse((self.tmp / "o").exists() and any((self.tmp / "o").iterdir()))

    def test_app_bundle_is_refused(self):
        app = make_exe(self.tmp / "Google Chrome.app" / "Contents" / "MacOS" / "Google Chrome")
        self.env["GARRICK_HEADLESS_SHELL"] = str(app)
        with self.assertRaises(render.NoBrowser) as c:
            render.find_browser(self.env)
        self.assertIn("app bundle", str(c.exception))

    def test_app_bundle_through_a_link_is_refused(self):
        app = make_exe(self.tmp / "X.app" / "Contents" / "shell")
        link = self.tmp / "link"
        link.symlink_to(app)
        self.env["GARRICK_HEADLESS_SHELL"] = str(link)
        with self.assertRaises(render.NoBrowser):
            render.find_browser(self.env)

    def test_app_on_path_is_skipped(self):
        app = make_exe(self.tmp / "Z.app" / "bin" / "chrome-headless-shell")
        (self.bin / "chrome-headless-shell").symlink_to(app)
        with self.assertRaises(render.NoBrowser):
            render.find_browser(self.env)


class NamingTest(unittest.TestCase):
    def test_names(self):
        self.assertEqual(render.shot_name("/a/b/index.html", 390, "dark"), "index-390-dark.png")
        self.assertEqual(render.shot_name("https://example.com/", 1280, "light"), "example.com-1280-light.png")
        self.assertEqual(render.shot_name("http://localhost:8765/status.html", 600, "light"),
                         "status-600-light.png")

    def test_file_becomes_a_file_url(self):
        self.assertTrue(render.page_url("some/page.html").startswith("file:///"))
        self.assertEqual(render.page_url("https://x.test/a"), "https://x.test/a")


class PipeTest(Base):
    def run_fake(self, **kw):
        self.log = self.tmp / "fake.log"
        self.env["FAKE_LOG"] = str(self.log)
        exe = make_exe(self.tmp / "fake-shell", FAKE % (sys.executable, PNG))
        self.env["GARRICK_HEADLESS_SHELL"] = str(exe)
        self.env["TMPDIR"] = str(self.tmp / "t")
        (self.tmp / "t").mkdir()
        page = self.tmp / "index.html"
        page.write_text("<p>hi</p>")
        return render.render([str(page)], self.tmp / "out", env=self.env, settle=0, **kw)

    def test_one_process_writes_every_shot(self):
        paths = self.run_fake(widths=(390, 1280), themes=("light", "dark"))
        self.assertEqual(sorted(p.name for p in paths), sorted(
            "index-%d-%s.png" % (w, t) for w in (390, 1280) for t in ("light", "dark")))
        for p in paths:
            self.assertEqual(p.read_bytes(), b"\x89PNG fake")
        lines = self.log.read_text().splitlines()
        starts = [l for l in lines if l.startswith("start ")]
        self.assertEqual(len(starts), 1)
        for flag in ("--remote-debugging-pipe", "--headless", "--user-data-dir="):
            self.assertIn(flag, starts[0])

    def test_commands_are_framed_and_ordered(self):
        self.run_fake(widths=(390,), themes=("dark",))
        import json
        cmds = [json.loads(l) for l in self.log.read_text().splitlines() if l.startswith("[")]
        self.assertEqual([c[0] for c in cmds], [
            "Target.createTarget", "Target.attachToTarget", "Page.enable",
            "Emulation.setDeviceMetricsOverride", "Emulation.setEmulatedMedia", "Page.navigate",
            "Page.captureScreenshot"])
        self.assertEqual(cmds[3][1]["width"], 390)
        self.assertEqual(cmds[4][1]["features"], [{"name": "prefers-color-scheme", "value": "dark"}])
        self.assertTrue(cmds[5][1]["url"].startswith("file://"))
        self.assertEqual(cmds[5][2], "S1")

    def test_full_page_captures_beyond_the_viewport(self):
        self.run_fake(widths=(390,), themes=("light",), full_page=True)
        import json
        cmds = [json.loads(l) for l in self.log.read_text().splitlines() if l.startswith("[")]
        shot = [c for c in cmds if c[0] == "Page.captureScreenshot"][0][1]
        self.assertTrue(shot["captureBeyondViewport"])
        self.assertEqual(shot["clip"]["height"], 2000)

    def test_profile_is_removed(self):
        self.run_fake(widths=(390,), themes=("light",))
        self.assertEqual(list((self.tmp / "t").iterdir()), [])

    def test_a_silent_browser_times_out_and_is_killed(self):
        exe = make_exe(self.tmp / "hang", "#!/bin/sh\nsleep 30\n")
        self.env["GARRICK_HEADLESS_SHELL"] = str(exe)
        self.env["TMPDIR"] = str(self.tmp)
        with self.assertRaises(render.RenderError):
            render.render(["about:blank"], self.tmp / "o", env=self.env, timeout=1)


if __name__ == "__main__":
    unittest.main()
