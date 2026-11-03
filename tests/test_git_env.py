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
    return "#!/bin/sh\n# Garrick wall check (a stand-in)\necho ran > '%s'\necho 'refused by the zone hook' >&2\nexit 1\n" % marker


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


class TestHooksFromConfig(TestExecutor):
    """The hook git will run, from any layer of config, must be Garrick's wall check:
    the commit is refused, and nothing is written, when it is not."""

    def cfg(self, name, body):
        p = Path(self._tmp.name) / name
        p.write_text(body)
        return p

    def hooks_path_cfg(self):
        empty = Path(self._tmp.name) / "no-hooks"
        empty.mkdir(exist_ok=True)
        return empty, "[core]\n\thooksPath = %s\n" % empty

    def refused_not_hooked(self, extra, before=None):
        if before:
            before()
        head = tpa.git(self.work, "rev-parse", "HEAD")
        with mock.patch.dict(os.environ, extra):
            with self.assertRaisesRegex(pa.Refused, "wall check"):
                self.tick()
        self.assertEqual(head, tpa.git(self.work, "rev-parse", "HEAD"))
        self.assertEqual(self.todo, (self.work / "Todo.md").read_bytes())

    def test_a_global_config_that_moves_the_hooks_is_refused(self):
        _, body = self.hooks_path_cfg()
        self.refused_not_hooked({"GIT_CONFIG_GLOBAL": str(self.cfg("global", body))})

    def test_a_system_config_that_moves_the_hooks_is_refused(self):
        _, body = self.hooks_path_cfg()
        self.refused_not_hooked({"GIT_CONFIG_SYSTEM": str(self.cfg("system", body))})

    def test_a_home_gitconfig_that_moves_the_hooks_is_refused(self):
        _, body = self.hooks_path_cfg()
        home = Path(self._tmp.name) / "home"
        home.mkdir()
        (home / ".gitconfig").write_text(body)
        self.refused_not_hooked({"HOME": str(home)})

    def test_an_xdg_config_that_moves_the_hooks_is_refused(self):
        _, body = self.hooks_path_cfg()
        xdg = Path(self._tmp.name) / "xdg"
        (xdg / "git").mkdir(parents=True)
        (xdg / "git" / "config").write_text(body)
        self.refused_not_hooked({"XDG_CONFIG_HOME": str(xdg), "HOME": str(Path(self._tmp.name) / "nohome")})

    def test_the_zones_own_hooks_path_is_refused(self):
        empty, _ = self.hooks_path_cfg()
        self.refused_not_hooked({}, lambda: tpa.git(self.work, "config", "core.hooksPath", str(empty)))

    def test_a_zone_with_no_wall_hook_is_refused(self):
        self.refused_not_hooked({}, lambda: (self.work / ".git" / "hooks" / "pre-commit").write_text("#!/bin/sh\nexit 0\n"))

    def test_a_shared_hooks_folder_that_holds_the_wall_check_is_accepted(self):
        shared = Path(self._tmp.name) / "shared-hooks"
        shared.mkdir()
        (self.work / ".git" / "hooks" / "pre-commit").rename(shared / "pre-commit")
        tpa.git(self.work, "config", "core.hooksPath", str(shared))
        with self.assertRaises(pa.Refused):               # the stand-in hook refuses, so it ran
            self.tick()
        self.assertTrue(self.marker.exists())


class TestJobs(unittest.TestCase):
    """The scheduled jobs and the wiki tools clean their environment too."""

    def setUp(self):
        import importlib.util
        jobs = tpa.REPO / "extras" / "jobs"
        sys.path.insert(0, str(jobs))
        try:
            import agent
        finally:
            sys.path.pop(0)
        self.agent = agent
        spec = importlib.util.spec_from_file_location("work_files_for_env", tpa.REPO / "extras" / "status" / "work_files.py")
        self.work_files = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.work_files)
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name).resolve()
        self.zone = self.base / "Zones" / "Work"
        self.zone.mkdir(parents=True)
        fixtures.git_init(self.zone)
        write(self.zone / "Todo.md", "# Work\n")
        fixtures.commit_all(self.zone)

    def tearDown(self):
        self._tmp.cleanup()

    def test_the_job_environment_has_no_repository_variables_or_git_settings(self):
        stray = {"GIT_DIR": "/x", "GIT_WORK_TREE": "/y", "GIT_INDEX_FILE": "/z", "GIT_CONFIG_COUNT": "1",
                 "GIT_CONFIG_KEY_0": "core.hooksPath", "GIT_CONFIG_VALUE_0": "/e", "GIT_CONFIG_PARAMETERS": "'a=b'"}
        with mock.patch.dict(os.environ, dict(stray, GIT_CONFIG_GLOBAL="/keep")):
            env = self.agent.own_repo_env()
        self.assertEqual([], [k for k in stray if k in env])
        self.assertEqual("/keep", env["GIT_CONFIG_GLOBAL"])
        listed = self.work_files._REPO_VARS
        self.assertTrue({"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS"} <= set(listed))

    def test_a_job_refuses_a_zone_whose_hooks_are_not_the_wall_check(self):
        self.assertIn("wall check", self.agent.wall_hook_problem(self.zone))          # no hook at all
        hook = self.zone / ".git" / "hooks" / "pre-commit"
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text("#!/bin/sh\n# Garrick wall check (a stand-in)\nexit 0\n")
        hook.chmod(0o755)
        self.assertIsNone(self.agent.wall_hook_problem(self.zone))
        empty = self.base / "no-hooks"
        empty.mkdir()
        cfg = self.base / "cfg"
        cfg.write_text("[core]\n\thooksPath = %s\n" % empty)
        with mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": str(cfg)}):
            self.assertIn(str(empty), self.agent.wall_hook_problem(self.zone))

    def test_the_todo_sweep_refuses_to_commit_past_the_zones_hook(self):
        sys.path.insert(0, str(tpa.REPO / "extras" / "jobs"))
        try:
            import todo_sweep
        finally:
            sys.path.pop(0)
        other = elsewhere(self.base)
        write(self.zone / "Todo.md", "# Work\n\n- [ ] Call Jo\n")
        head = tpa.git(other, "rev-parse", "HEAD")
        with mock.patch.dict(os.environ, {"GIT_DIR": str(other / ".git"), "GIT_WORK_TREE": str(other)}):
            r = todo_sweep.git(self.zone, "status", "--porcelain")
        self.assertIn("Todo.md", r.stdout)                         # git looked at the zone, not at the other repository
        self.assertEqual(head, tpa.git(other, "rev-parse", "HEAD"))


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

    def test_a_global_config_that_moves_the_hooks_refuses_a_scaffold_commit(self):
        empty = self.base / "no-hooks"
        empty.mkdir()
        cfg = self.base / "moved"
        cfg.write_text("[user]\n\tname = T\n\temail = t@example.invalid\n[core]\n\thooksPath = %s\n" % empty)
        head = tpa.git(self.work, "rev-parse", "HEAD")
        r = self.rename({"GIT_CONFIG_GLOBAL": str(cfg)})
        self.assertEqual(1, r.returncode, r.stdout + r.stderr)
        self.assertIn("wall check", r.stderr)
        self.assertEqual(head, tpa.git(self.work, "rev-parse", "HEAD"))

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
