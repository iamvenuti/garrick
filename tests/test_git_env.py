"""Garrick's own commits act on the zone's own repository, with the zone's own
hooks, whatever git variables the calling process has set.

    python3 -m unittest discover -s tests

A process with GIT_DIR, GIT_WORK_TREE or git settings in its environment
(GIT_CONFIG_COUNT with core.hooksPath, say) would otherwise send a commit to
another repository, or past the zone's wall check. The status page's actions
and the scaffold tool run git with those variables removed, and refuse to
commit in a zone whose repository is not the folder `.git` in it.
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

import fixtures  # noqa: E402
import test_page_action as tpa  # noqa: E402
import test_scaffold_manage as tsm  # noqa: E402
from fixtures import write  # noqa: E402

pa = tpa.pa


def hook_text(marker: Path) -> str:
    return "#!/bin/sh\necho ran > '%s'\necho 'refused by the zone hook' >&2\nexit 1\n" % marker


def elsewhere(base: Path) -> Path:
    """Another repository, with a commit, that a stray GIT_DIR would point at."""
    other = base / "elsewhere"
    other.mkdir()
    fixtures.git_init(other)
    write(other / "readme.md", "# Elsewhere\n")
    fixtures.commit_all(other, "start")
    return other


class TestExecutor(tpa.ActionCase):
    def setUp(self):
        super().setUp()
        self.marker = Path(self._tmp.name) / "hook-ran"
        hook = self.work / ".git" / "hooks" / "pre-commit"
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text(hook_text(self.marker))
        hook.chmod(0o755)
        self.other = elsewhere(Path(self._tmp.name))
        self.todo = (self.work / "Todo.md").read_bytes()

    def tick(self):
        return self.act(verb="todo-done", zone="Work", file="Todo.md", key=self.key("Invoice"))

    def refused_and_hooked(self, extra):
        head = tpa.git(self.other, "rev-parse", "HEAD")
        with mock.patch.dict(os.environ, extra):
            with self.assertRaises(pa.Refused):
                self.tick()
        self.assertTrue(self.marker.exists(), "the zone's hook did not run")
        self.assertEqual(head, tpa.git(self.other, "rev-parse", "HEAD"))
        self.assertEqual(self.todo, (self.work / "Todo.md").read_bytes())

    def test_git_dir_and_work_tree_from_the_caller_do_not_send_the_commit_elsewhere(self):
        self.refused_and_hooked({"GIT_DIR": str(self.other / ".git"), "GIT_WORK_TREE": str(self.other)})

    def test_an_index_file_from_the_caller_is_not_used(self):
        self.refused_and_hooked({"GIT_INDEX_FILE": str(self.other / ".git" / "index")})

    def test_git_settings_in_the_environment_do_not_move_the_hooks(self):
        empty = Path(self._tmp.name) / "no-hooks"
        empty.mkdir()
        self.refused_and_hooked({"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.hooksPath",
                                 "GIT_CONFIG_VALUE_0": str(empty)})

    def test_git_config_parameters_do_not_move_the_hooks(self):
        empty = Path(self._tmp.name) / "no-hooks"
        empty.mkdir()
        self.refused_and_hooked({"GIT_CONFIG_PARAMETERS": "'core.hooksPath=%s'" % empty})

    def test_a_zone_whose_git_is_not_its_own_folder_is_refused(self):
        import shutil
        shutil.rmtree(self.work / ".git")
        (self.work / ".git").write_text("gitdir: %s\n" % (self.other / ".git"))
        head = tpa.git(self.other, "rev-parse", "HEAD")
        with self.assertRaisesRegex(pa.Refused, "no git repository of its own"):
            self.tick()
        self.assertEqual(head, tpa.git(self.other, "rev-parse", "HEAD"))
        self.assertEqual(self.todo, (self.work / "Todo.md").read_bytes())


class TestScaffold(tsm.ManageCase):
    def setUp(self):
        super().setUp()
        self.marker = self.base / "hook-ran"
        hook = self.work / ".git" / "hooks" / "pre-commit"
        hook.write_text(hook_text(self.marker))
        hook.chmod(0o755)
        self.other = elsewhere(self.base)

    def rename(self, extra):
        env = dict(self.env, **extra)
        return subprocess.run([sys.executable, str(self.root / "System" / "tools" / "scaffold.py"), "rename", "--zone", "Work",
                               "--project", "Acme", "--thread", "Freight", "--to", "Haulage"],
                              capture_output=True, text=True, env=env, cwd=str(self.root))

    def check(self, extra):
        head = tpa.git(self.other, "rev-parse", "HEAD")
        r = self.rename(extra)
        self.assertEqual(1, r.returncode, r.stdout + r.stderr)
        self.assertTrue(self.marker.exists(), "the zone's hook did not run")
        self.assertEqual(head, tpa.git(self.other, "rev-parse", "HEAD"))

    def test_git_dir_from_the_caller_does_not_send_a_scaffold_commit_elsewhere(self):
        self.check({"GIT_DIR": str(self.other / ".git"), "GIT_WORK_TREE": str(self.other)})

    def test_git_settings_in_the_environment_do_not_move_the_hooks_of_a_scaffold_commit(self):
        empty = self.base / "no-hooks"
        empty.mkdir()
        self.check({"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.hooksPath", "GIT_CONFIG_VALUE_0": str(empty)})

    def test_a_zone_whose_git_is_not_its_own_folder_is_refused(self):
        import shutil
        shutil.rmtree(self.work / ".git")
        (self.work / ".git").write_text("gitdir: %s\n" % (self.other / ".git"))
        head = tpa.git(self.other, "rev-parse", "HEAD")
        r = self.rename({})
        self.assertNotEqual(0, r.returncode)
        self.assertEqual(head, tpa.git(self.other, "rev-parse", "HEAD"))


if __name__ == "__main__":
    unittest.main()
