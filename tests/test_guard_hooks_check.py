"""#685: the `guard-hooks` check warns when a guard hook an assistant's settings name is not this release's: another
version's bytes, a path inside the workspace, or a path that does not exist. Quiet when no guard is registered. A fake HOME
holds the settings and the kept download; this Mac's own are never read.

    cd tests && python3 -m unittest test_guard_hooks_check
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "template" / "System" / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
HOOKS = REPO / "extras" / "hooks"
MARKER = "marker-value-7f3a"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


import check  # noqa: E402


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name).resolve()
        self.home = base / "home"
        self.root = base / "ws"
        (self.home / ".claude").mkdir(parents=True)
        (self.root / "System").mkdir(parents=True)
        env = mock.patch.dict(os.environ, {"HOME": str(self.home), "GARRICK_MARKER": MARKER})
        env.start()
        self.addCleanup(env.stop)
        self.ws = check.Workspace(root=self.root, context={})

    def kept(self, data=None, name="kept", files=("zone_guard.py", "read_guard.py")):
        folder = self.home / name / "extras" / "hooks"
        folder.mkdir(parents=True, exist_ok=True)
        for f in files:
            (folder / f).write_bytes(data if data is not None else (HOOKS / f).read_bytes())
        return folder

    def name(self, *commands, codex=None):
        entry = {"hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": c} for c in commands]}]}}
        (self.home / ".claude" / "settings.json").write_text(json.dumps(entry))
        if codex is not None:
            (self.home / ".codex").mkdir(exist_ok=True)
            (self.home / ".codex" / "hooks.json").write_text(json.dumps(codex))

    def found(self):
        return check.check_guard_hooks(self.ws)


class TestGuardHooksCheck(Case):
    def test_a_kept_zone_guard_with_this_releases_bytes_has_no_finding(self):
        self.kept()
        self.name('python3 "$HOME/kept/extras/hooks/zone_guard.py"', 'python3 "$HOME/kept/extras/hooks/read_guard.py"')
        self.assertEqual([], self.found())

    def test_an_older_releases_bytes_give_one_warning_naming_the_hook_and_the_path(self):
        self.kept(b"# an older guard\n", files=("zone_guard.py",))
        self.name('python3 "$HOME/kept/extras/hooks/zone_guard.py"')
        (f,) = self.found()
        self.assertEqual(("warning", "guard-hooks"), (f.severity, f.check))
        self.assertIn("the zone guard", f.message)
        self.assertIn("~/kept/extras/hooks/zone_guard.py", f.message)
        self.assertIn("another version", f.message)
        self.assertIn(check.GUARD_FIX_REPLACE, f.message)
        self.assertNotIn(str(self.home), f.message + f.path + f.ear)

    def test_a_hook_inside_the_workspace_gives_one_warning_with_its_fix_line(self):
        inside = self.root / "System" / "garrick-copy" / "extras" / "hooks"
        inside.mkdir(parents=True)
        (inside / "zone_guard.py").write_bytes((HOOKS / "zone_guard.py").read_bytes())
        self.name("python3 %s" % (inside / "zone_guard.py"))
        (f,) = self.found()
        self.assertIn("inside the workspace", f.message)
        self.assertIn(check.GUARD_FIX_POINT, f.message)
        self.assertNotIn(check.GUARD_FIX_REPLACE, f.message)

    def test_a_hook_naming_a_path_that_does_not_exist_gives_one_warning(self):
        self.name('python3 "$HOME/gone/extras/hooks/read_guard.py"')
        (f,) = self.found()
        self.assertIn("the read guard", f.message)
        self.assertIn("does not exist", f.message)
        self.assertIn("~/gone/extras/hooks/read_guard.py", f.message)
        self.assertIn(check.GUARD_FIX_POINT, f.message)

    def test_a_word_that_is_not_a_full_path_has_its_own_wording(self):
        """C7: a relative path, or one through a variable the check cannot read, is not called missing."""
        os.environ.pop("CLAUDE_PROJECT_DIR", None)
        for written in ("python3 extras/hooks/zone_guard.py", 'python3 "$CLAUDE_PROJECT_DIR/extras/hooks/zone_guard.py"'):
            with self.subTest(written=written):
                self.name(written)
                (f,) = self.found()
                self.assertIn("is not a full path", f.message)
                self.assertNotIn("does not exist", f.message)
                self.assertIn(check.GUARD_FIX_POINT, f.message)

    def test_no_guard_hook_in_either_settings_file_has_no_finding(self):
        self.assertEqual([], self.found())                                   # no settings at all
        self.name("python3 ~/kept/extras/hooks/waiting_hook.py", codex={"hooks": {}})
        self.assertEqual([], self.found())                                   # settings, but no guard
        (self.home / ".claude" / "settings.json").write_text("not json")
        self.assertEqual([], self.found())

    def test_a_path_written_with_home_is_read_as_670_reads_it(self):
        self.kept()
        for written in ('python3 "$HOME/kept/extras/hooks/zone_guard.py"', 'python3 "${HOME}/kept/extras/hooks/zone_guard.py"',
                        "python3 ~/kept/extras/hooks/zone_guard.py",
                        "python3 %s" % (self.home / "kept" / "extras" / "hooks" / "zone_guard.py")):
            with self.subTest(written=written):
                self.name(written)
                self.assertEqual([], self.found())
        self.kept(b"# an older guard\n", files=("zone_guard.py",))
        self.name('python3 "${HOME}/kept/extras/hooks/zone_guard.py"')
        (f,) = self.found()
        self.assertIn("~/kept/extras/hooks/zone_guard.py", f.message)

    def test_the_codex_settings_are_read_too(self):
        self.kept(b"# an older guard\n", files=("read_guard.py",))
        self.name(codex={"hooks": {"PreToolUse": [{"hooks": [
            {"type": "command", "command": 'python3 "$HOME/kept/extras/hooks/read_guard.py"'}]}]}})
        (f,) = self.found()
        self.assertIn("the read guard", f.message)

    def test_no_value_of_an_environment_variable_reaches_the_finding(self):
        self.kept(b"# an older guard\n", files=("zone_guard.py",))
        with mock.patch.dict(os.environ, {"GARRICK_KEEP": str(self.home / "kept")}):
            self.name('python3 "$GARRICK_KEEP/extras/hooks/zone_guard.py"', 'python3 "$GARRICK_MARKER/zone_guard.py"')
            found = self.found()
        text = " ".join(f.message + f.path + f.ear for f in found)
        self.assertIn("$GARRICK_KEEP/extras/hooks/zone_guard.py", text)
        self.assertNotIn(str(self.home), text)
        self.assertNotIn(MARKER, text)

    def test_only_a_hook_command_names_a_hook_and_each_once(self):
        self.kept(b"# old\n", files=("zone_guard.py",))
        (self.home / ".claude" / "settings.json").write_text(json.dumps({
            "permissions": {"deny": ["Read(~/kept/extras/hooks/zone_guard.py)"]},
            "hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": "python3 ~/kept/extras/hooks/zone_guard.py"}]},
                                     {"hooks": [{"type": "command", "command": "python3 ~/kept/extras/hooks/zone_guard.py"}]}]}}))
        self.assertEqual(1, len(self.found()))


class TestNoSettingValueIsShown(Case):
    """#685's review (S1): a command that sets a variable before the guard shows only the guard's path."""

    def test_sh_c_with_a_token_names_only_the_path(self):
        self.name("sh -c 'GH_TOKEN=ghp_secret123 python3 ~/dl/garrick/extras/hooks/zone_guard.py'")
        (f,) = self.found()
        text = f.message + f.path + f.ear
        self.assertIn("~/dl/garrick/extras/hooks/zone_guard.py", text)
        self.assertNotIn("GH_TOKEN", text)
        self.assertNotIn("ghp_", text)
        self.assertEqual("~/dl/garrick/extras/hooks/zone_guard.py", f.path)

    def test_a_quoted_path_with_a_space_that_is_missing_is_named_whole(self):
        """N2: a folder name with a space is one path, and its file is said not to exist, never "not a full path"."""
        self.name('python3 "/x/My Folder/zone_guard.py"')
        (f,) = self.found()
        self.assertIn("/x/My Folder/zone_guard.py", f.message)
        self.assertIn("does not exist", f.message)
        self.assertNotIn("not a full path", f.message)

    def test_env_with_a_setting_names_only_the_path(self):
        self.kept(b"# old\n", files=("zone_guard.py",))
        self.name('env GH_TOKEN=ghp_secret123 python3 "$HOME/kept/extras/hooks/zone_guard.py"')
        (f,) = self.found()
        self.assertIn("~/kept/extras/hooks/zone_guard.py", f.message)
        self.assertNotIn("ghp_", f.message + f.path + f.ear)
        self.assertNotIn("GH_TOKEN", f.message + f.path + f.ear)

    def test_settings_and_the_update_show_no_value_either(self):
        import importlib.util as iu
        sg = load("sg_s1", REPO / "extras" / "status" / "settings_guard.py")
        self.name("sh -c 'GH_TOKEN=ghp_secret123 python3 ~/dl/garrick/extras/hooks/zone_guard.py'")
        shown = " ".join(w for w, _ in sg.named_hooks(str(self.home)))
        self.assertIn("~/dl/garrick/extras/hooks/zone_guard.py", shown)
        self.assertNotIn("ghp_", shown)
        sys.path.insert(0, str(REPO))
        up = load("up_s1", REPO / "update.py")
        words = [w for w, _ in up.hook_words(self.root)]
        self.assertEqual(["~/dl/garrick/extras/hooks/zone_guard.py"], words)


class TestTheCheckIsRegistered(unittest.TestCase):
    def test_it_runs_with_every_check_and_has_a_heading_and_a_spoken_group(self):
        self.assertIn(check.check_guard_hooks, check.ALL_CHECKS)
        self.assertIn("guard-hooks", dict(check.CHECKS))
        self.assertIn("guard-hooks", check.EAR_GROUP)

    def test_the_digests_are_this_releases_hook_files_and_settings_guards(self):
        for name, digest in check.GUARD_RELEASE.items():
            self.assertEqual(hashlib.sha256((HOOKS / name).read_bytes()).hexdigest(), digest,
                             "%s changed: put its new SHA-256 in GUARD_RELEASE in template/System/tools/check.py" % name)
        sg = load("sg_gh", REPO / "extras" / "status" / "settings_guard.py")
        self.assertEqual(sg.RELEASE_HOOKS, check.GUARD_RELEASE)


if __name__ == "__main__":
    unittest.main()
