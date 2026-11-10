"""The wall check at a merge and after one (#497): `pre-merge-commit` refuses what `pre-commit` would, `post-merge`
and `post-rewrite` report a crossing that is already in, and none of the three writes anywhere but `.git/`.

Invented zones only: Work and Personal, both walled, as in fixtures.py. A branch holds a note of Work that links a
file of Personal, made with the hook off, as a commit from a clone without the hook would be.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from fixtures import GIT_ENV, HAVE_GIT, TOOLS, build_workspace, commit_all, git, write

import check  # noqa: E402  (fixtures puts the tools folder on sys.path)
import garrick_lib as lib  # noqa: E402

ENV = dict(GIT_ENV, PYTHONDONTWRITEBYTECODE="1")
CROSS = "Acme Review/Threads/Pricing/Cross.md"
CALM = "Acme Review/Threads/Pricing/Calm.md"


def run(args, cwd):
    return subprocess.run([str(a) for a in args], cwd=str(cwd), env=ENV, capture_output=True, text=True)


def tree(root: Path):
    """Every file under the workspace outside .git, with its bytes."""
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*"))
            if p.is_file() and ".git" not in p.relative_to(root).parts}


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class MergeHooks(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve() / "Workspace"
        build_workspace(self.root)
        tools = self.root / "System" / "tools"
        tools.mkdir(parents=True, exist_ok=True)
        for name in ("check.py", "garrick_lib.py"):
            shutil.copy2(TOOLS / name, tools / name)
        write(self.root / "Zones/Personal/Quince/Quince.md", "---\ntitle: Quince\ntype: project\nzone: Personal\nstatus: active\n---\n\n# Quince\n")
        write(self.root / "Zones/Personal/Quince/Threads/Rows/Rows.md", "---\ntitle: Rows\ntype: thread\nstatus: active\n---\n\n# Rows\n")
        self.zone = self.root / "Zones" / "Work"
        shutil.rmtree(self.zone / ".git")
        git(self.zone, "init", "-q")
        lib.install_wall_hook(self.zone)
        commit_all(self.zone, "start")
        self.main = git(self.zone, "branch", "--show-current").strip()

    def tearDown(self):
        check._committing(None)
        self._tmp.cleanup()

    def branch(self, name, path, text):
        """A branch from the start with one commit made with the hooks off, back on the first branch after."""
        git(self.zone, "checkout", "-q", "-b", name)
        write(self.zone / path, text)
        commit_all(self.zone, name)
        git(self.zone, "checkout", "-q", self.main)

    def diverge(self):
        write(self.zone / "Todo.md", "# Work: open actions\n\n## Inbox\n\n- [ ] one more\n\n## Done\n")
        commit_all(self.zone, "main moves on")

    def crossing(self, name="side"):
        self.branch(name, CROSS, "# Cross\n\nSee [[Zones/Personal/Quince/Threads/Rows/Rows]].\n")

    def test_a_clean_merge_of_a_branch_that_crosses_a_wall_is_refused(self):
        self.crossing()
        self.diverge()
        before = git(self.zone, "rev-parse", "HEAD")
        r = run(["git", "merge", "--no-edit", "side"], self.zone)
        self.assertNotEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertIn("Commit refused", r.stderr)
        self.assertIn("Cross.md", r.stderr)
        self.assertEqual(before, git(self.zone, "rev-parse", "HEAD"))              # no merge commit was made
        self.assertEqual(1, len(git(self.zone, "rev-list", "--parents", "-n1", "HEAD").split()) - 1)

    def test_the_merge_hook_refuses_what_a_commit_of_the_same_changes_is_refused(self):
        self.crossing()
        self.diverge()
        git(self.zone, "merge", "--no-commit", "--no-ff", "side")
        merge = run([self.zone / ".git/hooks/pre-merge-commit"], self.zone)
        pre = run([self.zone / ".git/hooks/pre-commit"], self.zone)
        self.assertEqual((1, pre.stderr), (merge.returncode, merge.stderr))

    def test_a_fast_forward_passes_and_reports_and_changes_nothing_else(self):
        self.crossing()
        before = tree(self.root)
        refs = git(self.zone, "for-each-ref", "--format=%(refname)")
        side = git(self.zone, "rev-parse", "side")
        r = run(["git", "merge", "--ff-only", "side"], self.zone)
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertEqual(side, git(self.zone, "rev-parse", "HEAD"))            # the commits are in
        self.assertIn("Cross.md", r.stderr)
        self.assertIn("already in", r.stderr)
        self.assertIn("git reset --hard ORIG_HEAD", r.stderr)
        self.assertEqual(refs, git(self.zone, "for-each-ref", "--format=%(refname)"))
        self.assertEqual("", git(self.zone, "status", "--porcelain").strip())
        after = tree(self.root)
        self.assertEqual({"Zones/Work/" + CROSS}, set(after) - set(before))     # only the file the merge brought
        self.assertEqual({}, {k: v for k, v in before.items() if after.get(k) != v})
        self.assertFalse((self.root / "System" / "generated").exists())
        self.assertEqual([], list(self.root.rglob("__pycache__")))

    def test_the_report_is_only_a_report(self):
        """What it says to run is not run: ORIG_HEAD, the branch and the work tree stay where the merge left them."""
        self.crossing()
        start = git(self.zone, "rev-parse", "HEAD")
        run(["git", "merge", "--ff-only", "side"], self.zone)
        self.assertEqual(start, git(self.zone, "rev-parse", "ORIG_HEAD"))
        self.assertTrue((self.zone / CROSS).is_file())

    def test_a_merge_that_crosses_nothing_passes_in_silence(self):
        self.branch("calm", CALM, "# Calm\n\nNothing here points anywhere.\n")
        self.diverge()
        r = run(["git", "merge", "--no-edit", "calm"], self.zone)
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertEqual("", r.stderr)
        self.assertTrue((self.zone / CALM).is_file())

    def test_a_fast_forward_that_crosses_nothing_is_silent_too(self):
        self.branch("calm", CALM, "# Calm\n")
        r = run(["git", "merge", "--ff-only", "calm"], self.zone)
        self.assertEqual((0, ""), (r.returncode, r.stderr))

    def test_a_rebase_reports_the_commits_it_brought_in(self):
        self.crossing()
        self.diverge()
        git(self.zone, "checkout", "-q", "side")
        r = run(["git", "rebase", self.main], self.zone)
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertIn("Cross.md", r.stderr)
        self.assertIn("git reset --hard ORIG_HEAD", r.stderr)
        self.assertNotIn("Todo.md", r.stderr)                                   # only what the rewritten commits changed

    def test_an_amend_says_how_to_undo_an_amend_not_orig_head(self):
        """An amend sets no ORIG_HEAD, so `reset --hard ORIG_HEAD` would go to whatever an older operation left."""
        write(self.zone / CROSS, "# Cross\n\nSee [[Zones/Personal/Quince/Threads/Rows/Rows]].\n")
        git(self.zone, "add", "-A")
        git(self.zone, "-c", "core.hooksPath=" + os.devnull, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "crossing")
        r = run(["git", "commit", "--amend", "--no-verify", "-q", "-m", "reworded"], self.zone)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("Cross.md", r.stderr)
        self.assertIn("git reset --soft HEAD@{1}", r.stderr)
        self.assertNotIn("ORIG_HEAD", r.stderr)

    def test_a_pull_with_rebase_reports_what_upstream_brought_in(self):
        upstream = Path(self._tmp.name) / "upstream.git"
        git(self.zone, "init", "-q", "--bare", str(upstream))
        git(self.zone, "remote", "add", "origin", str(upstream))
        git(self.zone, "push", "-q", "origin", self.main)
        git(self.zone, "branch", "--set-upstream-to=origin/" + self.main)
        clone = Path(self._tmp.name) / "other"
        git(self.zone, "clone", "-q", str(upstream), str(clone))
        write(clone / CROSS, "# Cross\n\nSee [[Zones/Personal/Quince/Threads/Rows/Rows]].\n")
        commit_all(clone, "from elsewhere")
        git(clone, "push", "-q", "origin", "HEAD:" + self.main)
        self.diverge()                                                          # a local commit, so the pull rebases
        r = run(["git", "pull", "--rebase", "-q"], self.zone)
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertIn("Cross.md", r.stderr)
        self.assertIn("git reset --hard ORIG_HEAD", r.stderr)

    def test_a_squash_merge_is_silent_and_never_names_a_stale_orig_head(self):
        self.crossing()
        r = run(["git", "merge", "--squash", "side"], self.zone)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertNotIn("ORIG_HEAD", r.stderr)

    def test_a_foreign_hook_is_named_with_the_line_it_needs_and_install_hooks_still_succeeds(self):
        hooks = self.zone / ".git/hooks"
        (hooks / "post-merge").write_text("#!/bin/sh\necho mine\n")
        (hooks / "post-merge").chmod(0o755)
        (hooks / "post-rewrite").unlink()
        ws = check.discover(self.root)
        found = [f for f in check.check_zones(ws) if f.path == "Zones/Work"]
        self.assertEqual(1, len(found))
        self.assertIn("--changed ORIG_HEAD..HEAD", found[0].message)
        self.assertIn(lib.WALL_HOOK_MARK, found[0].message)
        r = run(["python3", self.root / "System/tools/check.py", "--root", self.root, "--install-hooks"], self.root)
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)                  # pre-commit was written, only a hook was left
        self.assertIn("post-merge", r.stdout)
        self.assertIn("--changed ORIG_HEAD..HEAD", r.stdout)
        self.assertEqual("#!/bin/sh\necho mine\n", (hooks / "post-merge").read_text())
        self.assertTrue((hooks / "post-rewrite").is_file())                    # the others were written

    def test_a_link_or_a_folder_in_a_hook_slot_is_left_alone_and_never_written_through(self):
        hooks = self.zone / ".git/hooks"
        target = Path(self._tmp.name) / "elsewhere.sh"
        (hooks / "post-merge").unlink()
        (hooks / "post-merge").symlink_to(target)                               # a dangling link
        (hooks / "pre-merge-commit").unlink()
        (hooks / "pre-merge-commit").mkdir()                                    # not a file
        with self.assertRaises(lib.MergeHookNotGarricks) as why:
            lib.install_wall_hook(self.zone)
        self.assertEqual(["pre-merge-commit", "post-merge"], sorted(why.exception.names, reverse=True))
        self.assertFalse(target.exists())
        self.assertTrue((hooks / "pre-merge-commit").is_dir())

    def test_the_post_hooks_never_fail_a_merge(self):
        self.crossing()
        (self.root / "System" / "tools" / "check.py").unlink()
        for name in lib.POST_HOOKS:
            r = run([self.zone / ".git/hooks" / name], self.zone)
            self.assertEqual(0, r.returncode, name + r.stderr)
        r = run([self.zone / ".git/hooks/pre-merge-commit"], self.zone)
        self.assertEqual(1, r.returncode)                                       # the one that can refuse still does

    def test_the_post_hooks_hold_no_refusal_and_no_reset(self):
        for name in lib.POST_HOOKS:
            text = lib.wall_hook_texts()[name]
            self.assertNotIn("exit 1", text)
            self.assertNotIn("reset", text)
            self.assertNotIn("Commit refused", text)
            self.assertIn("PYTHONDONTWRITEBYTECODE=1", text)
        for kwargs in ({"nested": True}, {"wiki": True, "root": "/x"}):
            for name in lib.POST_HOOKS:
                text = lib.wall_hook_texts(**kwargs)[name]
                self.assertNotIn("exit 1", text)
                self.assertNotIn("Commit refused", text)

    def test_every_hook_text_is_a_script_the_shell_reads(self):
        for kwargs in ({}, {"nested": True}, {"wiki": True, "root": "/x y"}):
            for name, text in lib.wall_hook_texts(**kwargs).items():
                r = subprocess.run(["sh", "-n"], input=text, capture_output=True, text=True)
                self.assertEqual(0, r.returncode, "%s %s: %s" % (kwargs, name, r.stderr))
                self.assertIn(lib.WALL_HOOK_MARK, text)

    def test_install_hooks_twice_changes_nothing_the_second_time(self):
        hooks = [self.zone / ".git/hooks" / n for n in lib.WALL_HOOKS]
        r = run(["python3", self.root / "System/tools/check.py", "--root", self.root, "--install-hooks"], self.root)
        self.assertEqual(0, r.returncode, r.stderr)
        first = [(h.read_bytes(), h.stat().st_mtime_ns, h.stat().st_mode) for h in hooks]
        self.assertTrue(all(h.is_file() and os.access(h, os.X_OK) for h in hooks))
        r = run(["python3", self.root / "System/tools/check.py", "--root", self.root, "--install-hooks"], self.root)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual(first, [(h.read_bytes(), h.stat().st_mtime_ns, h.stat().st_mode) for h in hooks])

    def test_a_merge_hook_that_is_not_garricks_is_left_alone_and_named(self):
        mine = self.zone / ".git/hooks/post-merge"
        mine.write_text("#!/bin/sh\necho mine\n")
        mine.chmod(0o755)
        with self.assertRaises(FileExistsError) as why:
            lib.install_wall_hook(self.zone)
        self.assertIn("post-merge", str(why.exception))
        self.assertEqual("#!/bin/sh\necho mine\n", mine.read_text())
        self.assertTrue(lib.has_wall_hook(self.zone))
        self.assertIn("pre-merge-commit", [n for n in lib.WALL_HOOKS if (self.zone / ".git/hooks" / n).is_file()])

    def test_a_pre_commit_that_is_not_garricks_writes_nothing(self):
        other = self.root / "Elsewhere"
        (other / ".git").mkdir(parents=True)
        hook = other / ".git/hooks/pre-commit"
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text("#!/bin/sh\necho theirs\n")
        with self.assertRaises(FileExistsError):
            lib.install_wall_hook(other)
        self.assertEqual([], [n for n in lib.WALL_HOOKS[1:] if (other / ".git/hooks" / n).exists()])

    def warnings(self, name="zones"):
        ws = check.discover(self.root)
        found = check.check_zones(ws) + check.check_hooks(ws)
        return [f for f in found if f.path == "Zones/Work" and "pre-merge-commit" in f.message]

    def test_a_zone_with_pre_commit_and_no_merge_hook_is_warned_about(self):
        self.assertEqual([], self.warnings())
        (self.zone / ".git/hooks/pre-merge-commit").unlink()
        found = self.warnings()
        self.assertEqual(1, len(found))
        self.assertEqual(check.WARNING, found[0].severity)
        self.assertIn("--install-hooks", found[0].message)

    def test_a_zone_without_the_post_hooks_is_warned_about_them(self):
        (self.zone / ".git/hooks/post-rewrite").unlink()
        ws = check.discover(self.root)
        found = [f for f in check.check_zones(ws) if f.path == "Zones/Work"]
        self.assertTrue(any("post-rewrite" in f.message and "--install-hooks" in f.message for f in found), found)

    def test_a_zone_with_no_wall_hook_at_all_gets_the_old_warning_only(self):
        for n in lib.WALL_HOOKS:
            (self.zone / ".git/hooks" / n).unlink()
        ws = check.discover(self.root)
        found = [f for f in check.check_zones(ws) if f.path == "Zones/Work"]
        self.assertEqual(1, len(found))
        self.assertIn("no pre-commit wall check", found[0].message)


if __name__ == "__main__":
    unittest.main()
