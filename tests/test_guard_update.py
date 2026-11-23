"""What an update says and does about the guard hooks the assistants' settings name (#670, #672): a path written with `$HOME`,
`${HOME}` or `~` is read as the shell reads it, the report shows it as written, and a kept download's hook files are refreshed
on a yes. A fake HOME holds the settings and the kept download; this Mac's own are never read or written.

    cd tests && python3 -m unittest test_guard_update
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

import test_update as tu  # noqa: E402

update = tu.update
REPO = tu.REPO
MARKER = "marker-value-7f3a"


class GuardCase(tu.ExtrasCase):
    def setUp(self):
        super().setUp()
        env = mock.patch.dict(os.environ, {"GARRICK_MARKER": MARKER})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("UNSET_VAR", None)
        self.home = self.base / "home"
        (self.home / ".claude").mkdir(parents=True, exist_ok=True)

    def kept(self, text="# an older guard\n", name="kept", files=("zone_guard.py", "read_guard.py")):
        folder = self.home / name / "extras" / "hooks"
        folder.mkdir(parents=True, exist_ok=True)
        for f in files:
            (folder / f).write_text(text)
        return folder

    def name(self, *commands, codex=None):
        entry = {"hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": c} for c in commands]}]}}
        (self.home / ".claude" / "settings.json").write_text(json.dumps(entry))
        if codex is not None:
            (self.home / ".codex").mkdir(exist_ok=True)
            (self.home / ".codex" / "hooks.json").write_text(json.dumps(codex))

    def report(self):
        p = self.plan()
        p["then"] = [what for what, _ in update.next_steps(self.root, p)]
        return update.report(p)


class TestAGuardNamedThroughAVariable(GuardCase):
    def test_a_zone_guard_of_another_version_is_named_however_the_settings_write_the_path(self):
        self.kept()
        for written in ('python3 "$HOME/kept/extras/hooks/zone_guard.py"', 'python3 "${HOME}/kept/extras/hooks/zone_guard.py"',
                        "python3 ~/kept/extras/hooks/zone_guard.py"):
            with self.subTest(written=written):
                self.name(written)
                said = self.report()
                self.assertIn("The zone guard runs from ~/kept/extras/hooks/zone_guard.py, which differs from this Garrick's", said)
                self.assertNotIn(str(self.home), said)

    def test_a_read_guard_of_another_version_is_named_through_home_too(self):
        self.kept()
        self.name('python3 "$HOME/kept/extras/hooks/read_guard.py"')
        self.assertIn("The read guard runs from ~/kept/extras/hooks/read_guard.py, which differs", self.report())

    def test_a_guard_that_is_this_releases_is_not_named(self):
        folder = self.kept()
        (folder / "zone_guard.py").write_bytes((REPO / "extras/hooks/zone_guard.py").read_bytes())
        self.name('python3 "$HOME/kept/extras/hooks/zone_guard.py"')
        self.assertNotIn("zone guard", self.report())

    def test_a_variable_that_is_not_set_is_dropped_with_no_error(self):
        self.name('python3 "$UNSET_VAR/zone_guard.py"', 'python3 "$GARRICK_MARKER/zone_guard.py"')
        said = self.report()
        self.assertNotIn("zone guard", said)
        self.assertNotIn(MARKER, said)

    def test_no_value_of_an_environment_variable_reaches_the_report(self):
        self.kept(name="kept")
        with mock.patch.dict(os.environ, {"GARRICK_KEEP": str(self.home / "kept")}):
            self.name('python3 "$GARRICK_KEEP/extras/hooks/zone_guard.py"')
            said = self.report()
        self.assertIn("The zone guard runs from $GARRICK_KEEP/extras/hooks/zone_guard.py", said)
        self.assertNotIn(str(self.home / "kept"), said)


class TestRefreshingTheKeptHooks(GuardCase):
    """#672: the settings name a kept download's extras/hooks/; the update offers to copy this Garrick's own hook files over it."""

    HOOKS = ("zone_guard.py", "read_guard.py", "parked_hint.py", "waiting_hook.py", "README.md")

    def setUp(self):
        super().setUp()
        self.folder = self.kept()
        self.settings = self.home / ".claude" / "settings.json"
        self.name('python3 "$HOME/kept/extras/hooks/zone_guard.py"')

    def steps(self):
        p = self.plan()
        return [(w, fn) for w, fn in update.next_steps(self.root, p) if "kept hooks" in w.lower() or "zone guard" in w.lower()]

    def matches(self):
        return all((self.folder / n).read_bytes() == (REPO / "extras" / "hooks" / n).read_bytes() for n in self.HOOKS)

    def test_the_report_names_the_guard_as_another_versions_and_offers_the_refresh_writing_nothing(self):
        before = self.settings.read_bytes()
        said = self.report()
        self.assertIn("The zone guard runs from ~/kept/extras/hooks/zone_guard.py, which differs from this Garrick's", said)
        self.assertIn("another version's hook files", said)
        self.assertIn("Refresh the kept hooks at ~/kept/extras/hooks", said)
        for name in self.HOOKS:
            self.assertIn(name, said)
        self.assertEqual("# an older guard\n", (self.folder / "zone_guard.py").read_text())
        self.assertEqual(before, self.settings.read_bytes())

    def test_after_a_yes_the_folder_matches_this_release_and_settings_registers_the_read_guard(self):
        ((what, fn),) = self.steps()
        with mock.patch.object(sys, "stdin") as stdin, mock.patch.object(sys, "stdout") as out, \
                mock.patch("builtins.input", return_value="y"):
            stdin.isatty.return_value = True
            out.isatty.return_value = True
            said = fn()
        self.assertIn("now holds this Garrick's", said)
        self.assertTrue(self.matches())
        import importlib.util
        spec = importlib.util.spec_from_file_location("sg_up", str(REPO / "extras" / "status" / "settings_guard.py"))
        sg = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sg)
        with mock.patch.object(sg, "HERE", self.base / "installed" / "status"):
            self.assertIn(self.folder, sg.hook_folders(str(self.home)))
        self.assertEqual([], self.steps())                     # nothing is left to offer

    def test_the_settings_file_is_not_touched(self):
        before = self.settings.read_bytes()
        ((what, fn),) = self.steps()
        with mock.patch.object(sys, "stdin") as stdin, mock.patch.object(sys, "stdout") as out, \
                mock.patch("builtins.input", return_value="yes"):
            stdin.isatty.return_value = True
            out.isatty.return_value = True
            fn()
        self.assertEqual(before, self.settings.read_bytes())

    def test_with_nobody_to_ask_nothing_is_copied_and_the_step_is_named(self):
        ((what, fn),) = self.steps()
        for stdin in (None, mock.Mock(isatty=mock.Mock(return_value=False)), mock.Mock(isatty=mock.Mock(side_effect=ValueError))):
            with self.subTest(stdin=stdin), mock.patch.object(sys, "stdin", stdin):
                said = fn()
                self.assertIn("Nothing was copied to the kept hooks at ~/kept/extras/hooks", said)
                self.assertIn("nobody could be asked", said)
                self.assertIn("zone_guard.py", said)
        self.assertEqual("# an older guard\n", (self.folder / "zone_guard.py").read_text())
        self.assertEqual(["read_guard.py", "zone_guard.py"], sorted(p.name for p in self.folder.iterdir()))

    def test_a_no_and_a_closed_input_copy_nothing(self):
        ((what, fn),) = self.steps()
        for answer in ("n", "", EOFError()):
            with self.subTest(answer=answer), mock.patch.object(sys, "stdin") as stdin, mock.patch.object(sys, "stdout") as out, \
                    mock.patch("builtins.input", side_effect=[answer] if isinstance(answer, EOFError) else None,
                               return_value=answer if not isinstance(answer, EOFError) else None):
                stdin.isatty.return_value = True
                out.isatty.return_value = True
                self.assertIn("Nothing was copied", fn())
        self.assertEqual("# an older guard\n", (self.folder / "zone_guard.py").read_text())

    def yes(self, fn):
        with mock.patch.object(sys, "stdin") as stdin, mock.patch.object(sys, "stdout") as out, \
                mock.patch("builtins.input", return_value="y"):
            stdin.isatty.return_value = True
            out.isatty.return_value = True
            return fn()

    def test_a_file_of_another_name_is_never_touched(self):
        (self.folder / "mine.py").write_text("# mine\n")
        (self.folder / "notes.md").write_text("mine too\n")
        ((what, fn),) = self.steps()
        self.yes(fn)
        self.assertEqual("# mine\n", (self.folder / "mine.py").read_text())
        self.assertEqual("mine too\n", (self.folder / "notes.md").read_text())
        self.assertEqual({*self.HOOKS, "mine.py", "notes.md"}, {p.name for p in self.folder.iterdir()})

    def test_a_failed_copy_puts_every_file_back(self):
        ((what, fn),) = self.steps()
        real = Path.write_bytes
        calls = []

        def write(path, data):
            calls.append(path.name)
            if path.name == "parked_hint.py":
                raise OSError("disk full")
            return real(path, data)
        with mock.patch.object(Path, "write_bytes", write):
            said = self.yes(fn)
        self.assertIn("were not refreshed: disk full", said)
        self.assertEqual("# an older guard\n", (self.folder / "zone_guard.py").read_text())
        self.assertEqual("# an older guard\n", (self.folder / "read_guard.py").read_text())
        self.assertFalse((self.folder / "parked_hint.py").exists())

    def test_a_folder_in_the_workspace_is_named_and_not_offered(self):
        inside = self.root / "System" / "garrick-copy" / "extras" / "hooks"
        inside.mkdir(parents=True)
        (inside / "zone_guard.py").write_text("# an older guard\n")
        with mock.patch.dict(os.environ, {"HOME": str(self.base)}):
            (self.base / ".claude").mkdir(exist_ok=True)
            (self.base / ".claude" / "settings.json").write_text(json.dumps({"hooks": {"PreToolUse": [{"hooks": [
                {"type": "command", "command": "python3 %s" % (inside / "zone_guard.py")}]}]}}))
            said = self.report()
            p = self.plan()
            fns = [fn for w, fn in update.next_steps(self.root, p) if fn and "kept hooks" in w.lower()]
        self.assertIn("The zone guard runs from", said)
        self.assertIn("garrick-copy/extras/hooks/zone_guard.py", said)
        self.assertNotIn("Refresh the kept hooks", said)
        self.assertEqual([], fns)
        self.assertEqual("# an older guard\n", (inside / "zone_guard.py").read_text())

    def test_a_clone_a_link_and_a_folder_outside_the_home_folder_are_named_and_not_offered(self):
        (self.home / "kept" / ".git").mkdir()
        self.assertIsNone(update.hook_refresh(self.folder, self.root))
        (self.home / "kept" / ".git").rmdir()
        self.assertIsNotNone(update.hook_refresh(self.folder, self.root))
        # a link: the folder's parent is a link
        real = self.home / "real" / "extras" / "hooks"
        real.mkdir(parents=True)
        (real / "zone_guard.py").write_text("# old\n")
        (self.home / "link").symlink_to(self.home / "real")
        self.assertIsNone(update.hook_refresh(self.home / "link" / "extras" / "hooks", self.root))
        # a link: one hook file is a link
        (self.folder / "read_guard.py").unlink()
        (self.folder / "read_guard.py").symlink_to(self.home / "real" / "extras" / "hooks" / "zone_guard.py")
        self.assertIsNone(update.hook_refresh(self.folder, self.root))
        # outside the home folder
        outside = self.base / "elsewhere" / "extras" / "hooks"
        outside.mkdir(parents=True)
        (outside / "zone_guard.py").write_text("# old\n")
        self.assertIsNone(update.hook_refresh(outside, self.root))
        # a folder that is not extras/hooks
        other = self.home / "plain"
        other.mkdir()
        (other / "zone_guard.py").write_text("# old\n")
        self.assertIsNone(update.hook_refresh(other, self.root))
        self.assertEqual("# old\n", (outside / "zone_guard.py").read_text())

    def test_a_link_met_at_the_run_is_refused_even_when_the_offer_was_made(self):
        ((what, fn),) = self.steps()
        (self.folder / "parked_hint.py").symlink_to(self.home / "kept" / "extras" / "hooks" / "zone_guard.py")
        said = self.yes(fn)
        self.assertIn("left as they are", said)
        self.assertEqual("# an older guard\n", (self.folder / "zone_guard.py").read_text())

    def test_the_running_garrick_is_never_refreshed_over_itself(self):
        self.assertIsNone(update.hook_refresh(REPO / "extras" / "hooks", self.root))

    def test_a_folder_the_settings_name_with_another_variable_shows_the_variable_never_its_value(self):
        with mock.patch.dict(os.environ, {"GARRICK_KEEP": str(self.home / "kept")}):
            self.name('python3 "$GARRICK_KEEP/extras/hooks/zone_guard.py"')
            said = self.report()
            ((what, fn),) = self.steps()
            result = fn()
        self.assertIn("Refresh the kept hooks at $GARRICK_KEEP/extras/hooks", said)
        self.assertIn("$GARRICK_KEEP/extras/hooks", result)
        for text in (said, result, what):
            self.assertNotIn(str(self.home / "kept"), text)
            self.assertNotIn("~/kept", text)

    def test_a_folder_where_only_another_hook_file_differs_is_offered_too(self):
        for name in ("zone_guard.py", "read_guard.py"):
            (self.folder / name).write_bytes((REPO / "extras" / "hooks" / name).read_bytes())
        (self.folder / "parked_hint.py").write_text("# old hint\n")
        said = self.report()
        self.assertIn("The kept hooks at ~/kept/extras/hooks differ from this Garrick's in", said)
        self.assertIn("parked_hint.py", said)


if __name__ == "__main__":
    unittest.main()
