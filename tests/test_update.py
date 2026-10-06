"""Tests for update.py, `install.py --update`.

    python3 -m unittest discover -s tests

Every workspace is a real install in a temporary folder, with HOME and git's
global config pointed at temporary files. An older Garrick is simulated by
rewriting a file and its fingerprint as an older release would have left them;
one test installs the v0.6.0 tag itself, when this clone has it.
"""

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parent.parent
INSTALL = REPO / "install.py"
EXAMPLE = REPO / "examples" / "acme.json"
sys.path.insert(0, str(REPO))
import update  # noqa: E402

STAMP = "System/garrick-version.json"
OLDER = "0000000"          # the commit an older Garrick's stamp records


def sha(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode("utf-8")).hexdigest()


class Case(unittest.TestCase):
    """A fresh install of the example workspace, made once per test."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()
        (base / "home").mkdir()
        gitconfig = base / "gitconfig"
        gitconfig.write_text("[user]\n\tname = Test Runner\n\temail = test@example.invalid\n"
                             "[commit]\n\tgpgsign = false\n")
        self.env = dict(os.environ, HOME=str(base / "home"), GIT_CONFIG_GLOBAL=str(gitconfig),
                        GIT_CONFIG_NOSYSTEM="1", PYTHONDONTWRITEBYTECODE="1")
        self.patch = mock.patch.dict(os.environ, self.env)
        self.patch.start()
        self.base = base
        self.root = base / "ws"
        r = subprocess.run([sys.executable, str(INSTALL), "--config", str(EXAMPLE), "--target", str(self.root)],
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(0, r.returncode, r.stderr)

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    # helpers
    def git(self, repo, *args):
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True).stdout.strip()

    def stamp(self):
        return json.loads((self.root / STAMP).read_text())

    def set_stamp(self, stamp):
        (self.root / STAMP).write_text(json.dumps(stamp, indent=2) + "\n")
        self.commit(self.root, "stamp")

    def commit(self, repo, message):
        self.git(repo, "add", "-A")
        subprocess.run(["git", "-C", str(repo), "commit", "-q", "--no-verify", "-m", message], capture_output=True)

    def as_if_older(self, path, old_text, user_text=None):
        """Make `path` look as an older Garrick wrote it (`old_text`), and then,
        when given, as the user changed it since (`user_text`)."""
        stamp = self.stamp()
        stamp["commit"] = OLDER
        stamp["files"][path] = sha(old_text)
        (self.root / path).write_text(user_text if user_text is not None else old_text)
        repo = update.repo_of(self.root, path)
        self.commit(repo, "older " + path)
        self.set_stamp(stamp)

    def plan(self):
        return update.plan(self.root)

    def apply(self, **kw):
        return update.apply(self.root, self.plan(), **kw)

    def head(self, repo):
        return self.git(repo, "rev-parse", "HEAD")


class TestWhatGarrickShips(Case):
    def test_shipped_is_exactly_what_the_installer_wrote(self):
        files = self.stamp()["files"]
        new = update.shipped(update.zones_of(self.root, self.stamp()))
        self.assertEqual(sorted(files), sorted(new))
        for path, (data, _) in new.items():
            self.assertEqual(files[path], sha(data), path)

    def test_a_fresh_install_is_up_to_date_and_apply_changes_nothing(self):
        p = self.plan()
        self.assertEqual({k: [] for k in update.KINDS}, p["actions"])
        self.assertIn("Up to date", update.report(p))
        heads = {r: self.head(r) for r in (self.root, self.root / "Zones" / "Work")}
        result = self.apply()
        self.assertFalse(result["stamped"])
        self.assertEqual(heads, {r: self.head(r) for r in heads})


class TestSorting(Case):
    def test_an_untouched_older_file_is_replaced_and_committed(self):
        path = "System/tools/scaffold.py"
        new = (self.root / path).read_bytes()
        self.as_if_older(path, "# an older scaffold\n")
        self.assertEqual([path], self.plan()["actions"]["replace"])
        result = self.apply(today="2026-10-06")
        self.assertEqual([path], result["done"]["replace"])
        self.assertEqual(new, (self.root / path).read_bytes())
        self.assertEqual("Garrick: update to %s, 1 file" % update.install.source_version()["commit"],
                         self.git(self.root, "log", "-2", "--format=%s").splitlines()[1])
        self.assertEqual("", self.git(self.root, "status", "--porcelain"))
        stamp = self.stamp()
        self.assertEqual(sha(new), stamp["files"][path])
        self.assertEqual("2026-10-06", stamp["updates"][-1]["on"])
        self.assertTrue(result["stamped"])

    def test_a_changed_file_gets_a_new_beside_it(self):
        path = "System/skills/threads/SKILL.md"
        new = (self.root / path).read_bytes()
        self.as_if_older(path, "older wording\n", "older wording\nmy own line\n")
        p = self.plan()
        self.assertEqual([path], p["actions"]["merge"])
        head = self.head(self.root)
        self.apply()
        self.assertEqual("older wording\nmy own line\n", (self.root / path).read_text())
        self.assertEqual(new, (self.root / (path + ".new")).read_bytes())
        self.assertEqual("", self.git(self.root, "status", "--porcelain"))      # the .new is committed
        self.assertEqual(sha(new), self.stamp()["files"][path])         # offered: Garrick's newest
        subjects = self.git(self.root, "log", "--format=%s", head + "..").splitlines()
        self.assertEqual(2, len(subjects))
        self.assertTrue(subjects[0].startswith("Garrick: version stamp"))
        self.assertTrue(subjects[1].startswith("Garrick: update to"))
        self.assertEqual(path + ".new", self.git(self.root, "show", "--format=", "--name-only", "HEAD~1"))

    def test_a_new_file_survives_a_clean_until_it_is_merged(self):
        path = "System/skills/threads/SKILL.md"
        self.as_if_older(path, "older wording\n", "older wording\nmy own line\n")
        self.apply()
        self.git(self.root, "clean", "-fdq")
        self.assertTrue((self.root / (path + ".new")).is_file())
        self.assertEqual([], [x for k in update.KINDS for x in self.plan()["actions"][k]])

    def test_the_merge_base_is_garricks_version_the_file_last_took_in(self):
        # The skill's recipe: the later of Garrick's last write of the file and the last removal of its .new.
        path = "System/skills/threads/SKILL.md"
        self.as_if_older(path, "older wording\n", "older wording\nmy own line\n")
        self.apply()
        newer = (self.root / (path + ".new")).read_text()
        written = self.git(self.root, "log", "-1", "--format=%H", "-E",
                           "--grep=^Garrick: (workspace created|update to |.+ created$)", "--", path)
        self.assertEqual("", self.git(self.root, "log", "-1", "--format=%H", "--diff-filter=D", "--", path + ".new"))
        self.assertTrue(written)                      # before the merge, the base is Garrick's own write
        (self.root / path).write_text(newer + "my own line\n")
        self.git(self.root, "rm", "-q", path + ".new")
        self.git(self.root, "commit", "-q", "--no-verify", "-m", "Merged Garrick's update into " + path)
        removed = self.git(self.root, "log", "-1", "--format=%H", "--diff-filter=D", "--", path + ".new")
        later = subprocess.run(["git", "-C", str(self.root), "merge-base", "--is-ancestor", written, removed])
        self.assertEqual(0, later.returncode)
        self.assertEqual(newer, self.git(self.root, "show", "%s^:%s.new" % (removed, path)) + "\n")

    def test_a_merged_file_is_not_offered_again(self):
        path = "System/skills/threads/SKILL.md"
        self.as_if_older(path, "older wording\n", "older wording\nmy own line\n")
        self.apply()
        merged = (self.root / (path + ".new")).read_text() + "my own line\n"
        (self.root / path).write_text(merged)
        (self.root / (path + ".new")).unlink()
        self.commit(self.root, "Merged Garrick's update into " + path)
        p = self.plan()
        self.assertEqual([], [x for k in update.KINDS for x in p["actions"][k]])
        self.assertEqual([path], p["kept"])
        head = self.head(self.root)
        self.assertFalse(self.apply()["stamped"])
        self.assertFalse((self.root / (path + ".new")).exists())
        self.assertEqual(head, self.head(self.root))

    def test_a_file_only_you_changed_is_left_and_not_listed(self):
        path = "System/skills/threads/SKILL.md"
        (self.root / path).write_text("mine now\n")
        self.commit(self.root, "mine")
        p = self.plan()
        self.assertEqual([], [x for k in update.KINDS for x in p["actions"][k]])
        self.assertEqual([path], p["kept"])

    def test_rules_are_always_merged_never_replaced(self):
        path = "System/rules.md"
        self.as_if_older(path, "# Rules, older\n")
        self.assertEqual([path], self.plan()["actions"]["merge"])
        self.apply()
        self.assertEqual("# Rules, older\n", (self.root / path).read_text())
        self.assertTrue((self.root / (path + ".new")).is_file())

    def test_a_filled_in_seed_is_yours_and_an_untouched_one_is_replaced(self):
        work, personal = "Zones/Work/Todo.md", "Zones/Personal/Todo.md"
        self.as_if_older(work, "# Todo, older\n", "# Todo, older\n- [ ] Call Dana\n")
        self.as_if_older(personal, "# Todo, older\n")
        p = self.plan()
        self.assertEqual([work], p["actions"]["yours"])
        self.assertEqual([personal], p["actions"]["replace"])
        self.apply()
        self.assertFalse((self.root / (work + ".new")).exists())
        self.assertIn("Call Dana", (self.root / work).read_text())

    def test_a_file_any_release_shipped_counts_as_garricks(self):
        # A fix copied in by hand: the file matches a release, not the stamp.
        path = "System/tools/scaffold.py"
        stamp = self.stamp()
        stamp["files"][path] = sha("something else\n")
        self.set_stamp(stamp)
        with mock.patch.object(update, "known_hashes", return_value={path: [sha("# from a release\n")]}):
            (self.root / path).write_text("# from a release\n")
            self.commit(self.root, "hand copy")
            self.assertEqual([path], self.plan()["actions"]["replace"])

    def test_new_removed_and_retired(self):
        stamp = self.stamp()
        added = "System/skills/threads/SKILL.md"
        del stamp["files"][added]
        (self.root / added).unlink()
        removed = "Wikis/Knowledge/raw/.gitkeep"
        (self.root / removed).unlink()
        retired = "System/tools/old-helper.py"
        (self.root / retired).write_text("print('old')\n")
        stamp["files"][retired] = sha("print('old')\n")
        self.commit(self.root / "Wikis", "rm")
        self.set_stamp(stamp)
        p = self.plan()
        self.assertEqual([added], p["actions"]["add"])
        self.assertEqual([removed], p["actions"]["restore"])
        self.assertEqual([retired], p["actions"]["retired"])
        result = self.apply()
        self.assertTrue((self.root / added).is_file())
        self.assertFalse((self.root / removed).exists())          # put back only when named
        self.assertTrue((self.root / retired).is_file())          # never deleted
        self.assertNotIn(retired, self.stamp()["files"])
        self.assertTrue(result["stamped"])
        update.apply(self.root, self.plan(), only=[removed])
        self.assertTrue((self.root / removed).is_file())
        self.assertEqual("", self.git(self.root / "Wikis", "status", "--porcelain"))

    def test_a_stamp_without_a_list_still_knows_what_you_removed(self):
        # Installed before 0.4.0: the stamp lists no files, so git history says what was there.
        stamp = self.stamp()
        del stamp["files"]
        stamp["commit"] = OLDER
        self.set_stamp(stamp)
        removed = "System/skills/threads/SKILL.md"
        self.git(self.root, "rm", "-q", removed)
        self.commit(self.root, "not for me")
        p = self.plan()
        self.assertEqual([removed], p["actions"]["restore"])
        self.assertEqual([], p["actions"]["add"])
        self.apply()
        self.assertFalse((self.root / removed).exists())
        self.assertIn(removed, self.stamp()["files"])                # listed now, so it stays removed
        self.assertEqual([removed], self.plan()["actions"]["restore"])

    def test_a_stamp_without_a_list_gets_one_with_every_file_there(self):
        stamp = self.stamp()
        del stamp["files"]
        stamp["commit"] = OLDER
        self.set_stamp(stamp)
        todo = "Zones/Work/Todo.md"
        (self.root / todo).write_text("# Todo, older\n- [ ] Call Dana\n")
        self.commit(self.root / "Zones" / "Work", "my todo")
        self.assertEqual([todo], self.plan()["actions"]["yours"])
        self.apply()
        files = self.stamp()["files"]
        self.assertIn(todo, files)
        self.assertIsNone(files[todo])                   # there, but what Garrick gave it is unknown
        self.assertEqual(sorted(update.shipped(update.zones_of(self.root, self.stamp()))), sorted(files))
        (self.root / todo).unlink()
        self.commit(self.root / "Zones" / "Work", "no todo for me")
        p = self.plan()
        self.assertEqual([todo], p["actions"]["restore"])
        self.assertEqual([], p["actions"]["add"])

    def test_a_stamp_without_a_list_reads_each_repository_once(self):
        stamp = self.stamp()
        del stamp["files"]
        self.set_stamp(stamp)
        gone = ["System/skills/threads/SKILL.md", "System/tools/scaffold.py", "System/tools/check.py"]
        for path in gone:
            (self.root / path).unlink()
        self.commit(self.root, "gone")
        real, calls = update.git, []

        def counting(repo, *args, **kw):
            calls.append(args[0])
            return real(repo, *args, **kw)

        with mock.patch.object(update, "git", counting):
            p = self.plan()
        self.assertEqual(sorted(gone), p["actions"]["restore"])
        self.assertEqual(["log", "ls-files"], calls)


class TestSafety(Case):
    def test_a_removed_zone_is_not_put_back(self):
        shutil.rmtree(self.root / "Zones" / "Personal")
        p = self.plan()
        self.assertEqual([], [x for k in update.KINDS for x in p["actions"][k] if x.startswith("Zones/Personal/")])
        self.apply()
        self.assertFalse((self.root / "Zones" / "Personal").exists())

    def test_context_is_never_touched(self):
        context = (self.root / "System" / "context.md").read_bytes()
        self.as_if_older("System/tools/scaffold.py", "# older\n")
        self.apply()
        self.assertEqual(context, (self.root / "System" / "context.md").read_bytes())
        self.assertNotIn("System/context.md", self.stamp()["files"])

    def test_uncommitted_changes_are_skipped_never_committed(self):
        path = "System/tools/scaffold.py"
        self.as_if_older(path, "# older\n")
        stamp = self.stamp()
        (self.root / path).write_text("# older\n")      # same as Garrick's, but staged by another session
        stamp_hash = stamp["files"][path]
        self.git(self.root, "rm", "-q", "--cached", path)
        result = self.apply()
        self.assertEqual([], result["done"]["replace"])
        self.assertIn(path, [p for p, _ in result["skipped"]])
        self.assertEqual("# older\n", (self.root / path).read_text())
        self.assertEqual(stamp_hash, self.stamp()["files"][path])
        self.assertIn(path, self.stamp()["left"])

    def test_never_writes_through_a_link(self):
        path = "System/skills/threads/SKILL.md"
        self.as_if_older(path, "older\n")
        elsewhere = self.base / "elsewhere"
        elsewhere.mkdir()
        threads = self.root / "System" / "skills" / "threads"
        shutil.move(str(threads), str(elsewhere / "threads"))
        os.symlink(str(elsewhere / "threads"), str(threads))
        result = self.apply()
        self.assertIn(path, [p for p, why in result["skipped"] if "link" in why])
        self.assertEqual("older\n", (elsewhere / "threads" / "SKILL.md").read_text())

    def test_a_refused_commit_puts_the_files_back(self):
        path = "Zones/Work/AGENTS.md"
        self.as_if_older(path, "# Work, older\n")
        hook = self.root / "Zones" / "Work" / ".git" / "hooks" / "commit-msg"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        result = self.apply()
        self.assertIn(path, [p for p, why in result["skipped"] if "refused" in why])
        self.assertEqual("# Work, older\n", (self.root / path).read_text())
        self.assertEqual("", self.git(self.root / "Zones" / "Work", "status", "--porcelain"))

    def test_a_refused_commit_removes_the_folders_it_made(self):
        files = update.shipped(update.zones_of(self.root, self.stamp()))
        path = next(x for x in sorted(files) if x.startswith("System/skills/") and x.count("/") == 3
                    and len(list((self.root / x).parent.iterdir())) == 1)
        folder = (self.root / path).parent
        shutil.rmtree(folder)
        stamp = self.stamp()
        del stamp["files"][path]
        self.set_stamp(stamp)
        self.assertEqual([path], self.plan()["actions"]["add"])
        hook = self.root / ".git" / "hooks" / "commit-msg"
        hook.write_text("#!/bin/sh\ngrep -q '^Garrick: update to' \"$1\" && exit 1\nexit 0\n")
        hook.chmod(0o755)
        result = self.apply()
        self.assertIn(path, [p for p, why in result["skipped"] if "refused" in why])
        self.assertFalse(folder.exists())

    def test_a_refused_stamp_is_put_back(self):
        self.as_if_older("System/tools/scaffold.py", "# older\n")
        before = (self.root / STAMP).read_bytes()
        hook = self.root / ".git" / "hooks" / "commit-msg"
        hook.write_text("#!/bin/sh\ngrep -q '^Garrick: version stamp' \"$1\" && exit 1\nexit 0\n")
        hook.chmod(0o755)
        result = self.apply()
        self.assertFalse(result["stamped"])
        self.assertIn("put back", result["unstamped"])
        self.assertEqual(before, (self.root / STAMP).read_bytes())
        self.assertEqual("", self.git(self.root, "status", "--porcelain"))
        self.assertIn("is unchanged", update.say_applied(self.plan(), result))
        hook.unlink()
        self.assertTrue(self.apply()["stamped"])

    def test_a_new_that_cannot_be_written_leaves_nothing_behind(self):
        path = "System/rules.md"
        self.as_if_older(path, "# Rules, older\n")
        real = os.chmod

        def failing(target, mode, *a, **kw):
            if str(target).endswith(".new.garrick-tmp"):
                raise OSError(28, "No space left on device", str(target))
            return real(target, mode, *a, **kw)

        with mock.patch.object(update.os, "chmod", failing):
            result = self.apply()
        self.assertIn(path, [p for p, why in result["skipped"] if "put back" in why])
        self.assertEqual([], result["done"]["merge"])
        self.assertEqual([], [x.name for x in (self.root / "System").iterdir() if x.name.startswith("rules.md.")])
        self.assertEqual("", self.git(self.root, "status", "--porcelain"))

    def test_an_update_between_copies_with_no_commit_is_recorded(self):
        self.as_if_older("System/tools/scaffold.py", "# older\n")
        stamp = self.stamp()
        stamp["commit"] = "unknown"
        self.set_stamp(stamp)
        copy = {"commit": "unknown", "date": "", "from": "copy"}
        with mock.patch.object(update.install, "source_version", return_value=copy):
            self.assertTrue(self.apply(today="2026-10-06")["stamped"])
            self.assertFalse(self.apply(today="2026-10-06")["stamped"])
        self.assertEqual([{"from": "unknown", "to": "unknown", "on": "2026-10-06"}], self.stamp()["updates"])

    def test_a_write_that_fails_puts_the_others_back(self):
        first, second = "System/tools/scaffold.py", "System/tools/garrick_lib.py"
        self.as_if_older(first, "# older scaffold\n")
        self.as_if_older(second, "# older lib\n")
        real = update.write_bytes

        def failing(path, data, mode):
            if path.name == "garrick_lib.py":
                raise PermissionError(13, "Permission denied", str(path))
            real(path, data, mode)

        head = self.head(self.root)
        with mock.patch.object(update, "write_bytes", failing):
            result = self.apply()
        self.assertEqual([], result["done"]["replace"])
        self.assertEqual({first, second}, {p for p, why in result["skipped"] if "put back" in why})
        self.assertEqual("# older scaffold\n", (self.root / first).read_text())
        self.assertEqual("# older lib\n", (self.root / second).read_text())
        self.assertEqual("", self.git(self.root, "status", "--porcelain"))
        self.assertEqual([], [m for m in self.git(self.root, "log", "--format=%s", head + "..").splitlines()
                              if m.startswith("Garrick: update to")])
        self.assertEqual(sorted([first, second]), self.stamp()["left"])

    def test_a_file_left_behind_does_not_restamp_every_run(self):
        path = "System/tools/scaffold.py"
        self.as_if_older(path, "# older\n")
        self.as_if_older("System/tools/garrick_lib.py", "# older lib\n")
        self.git(self.root, "rm", "-q", "--cached", path)          # another session's change, not committed
        self.assertTrue(self.apply(today="2026-10-06")["stamped"])
        head = self.head(self.root)
        for _ in range(2):
            result = self.apply(today="2026-10-07")
            self.assertIn(path, [p for p, _ in result["skipped"]])
            self.assertFalse(result["stamped"])
        self.assertEqual(head, self.head(self.root))
        self.assertEqual([{"from": OLDER, "to": update.install.source_version()["commit"], "on": "2026-10-06"}],
                         self.stamp()["updates"])
        self.assertEqual([path], self.stamp()["left"])

    def test_an_older_wall_check_is_refreshed(self):
        hook = self.root / "Zones" / "Work" / ".git" / "hooks" / "pre-commit"
        hook.write_text(hook.read_text().replace("refuse a commit", "refuse, in older words, a commit"))
        p = self.plan()
        self.assertEqual(["Work"], p["hooks"])
        self.apply()
        self.assertEqual(update.install.lib().WALL_HOOK, hook.read_text())
        self.assertEqual([], self.plan()["hooks"])

    def test_someone_elses_hook_is_left_alone(self):
        hook = self.root / "Zones" / "Work" / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\necho mine\n")
        self.assertEqual([], self.plan()["hooks"])

    def test_running_twice_changes_nothing_the_second_time(self):
        self.as_if_older("System/tools/scaffold.py", "# older\n")
        self.as_if_older("System/rules.md", "# Rules, older\n")
        self.apply()
        heads = {r: self.head(r) for r in (self.root, self.root / "Wikis", self.root / "Zones" / "Work")}
        result = self.apply()
        self.assertFalse(result["stamped"])
        self.assertEqual(heads, {r: self.head(r) for r in heads})

    def test_unknown_paths_are_refused(self):
        with self.assertRaises(update.UpdateError):
            self.apply(only=["System/nowhere.md"])


class TestCommandLine(Case):
    def run_update(self, *args):
        return subprocess.run([sys.executable, str(INSTALL), "--update", str(self.root), *args],
                              capture_output=True, text=True, env=self.env)

    def test_report_changes_nothing_and_apply_does(self):
        self.as_if_older("System/tools/scaffold.py", "# older\n")
        before = (self.root / "System/tools/scaffold.py").read_text()
        r = self.run_update()
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("Replace, 1 file Garrick wrote that you have not changed", r.stdout)
        self.assertIn("  System/tools/scaffold.py", r.stdout)
        self.assertEqual(before, (self.root / "System/tools/scaffold.py").read_text())
        data = json.loads(self.run_update("--json").stdout)
        self.assertEqual(["System/tools/scaffold.py"], data["actions"]["replace"])
        r = self.run_update("--apply")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("Updated 1 file.", r.stdout)
        self.assertIn("Committed as", r.stdout)
        self.assertIn("now records", r.stdout)

    def test_refuses_a_folder_that_is_not_a_workspace(self):
        r = subprocess.run([sys.executable, str(INSTALL), "--update", str(self.base)],
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(1, r.returncode)
        self.assertIn("not a Garrick workspace", r.stderr)
        r = subprocess.run([sys.executable, str(INSTALL), "--update", str(REPO)],
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(1, r.returncode)

    def test_the_check_warns_until_a_new_file_is_merged(self):
        self.as_if_older("System/rules.md", "# Rules, older\n")
        self.run_update("--apply")
        r = subprocess.run([sys.executable, str(self.root / "System/tools/check.py"), "--root", str(self.root),
                            "--json"], capture_output=True, text=True, env=self.env)
        found = [f for f in json.loads(r.stdout)["findings"] if f["check"] == "updates"]
        self.assertEqual(["System/rules.md.new"], [f["path"] for f in found])
        (self.root / "System/rules.md.new").unlink()
        r = subprocess.run([sys.executable, str(self.root / "System/tools/check.py"), "--root", str(self.root),
                            "--json"], capture_output=True, text=True, env=self.env)
        self.assertEqual([], [f for f in json.loads(r.stdout)["findings"] if f["check"] == "updates"])

    def test_the_check_finds_a_new_file_the_stamp_does_not_list(self):
        stamp = self.stamp()
        del stamp["files"]
        self.set_stamp(stamp)
        (self.root / "Zones/Work/AGENTS.md.new").write_text("newer\n")
        (self.root / "Zones/Work/notes.new").write_text("mine, with no file beside it\n")
        r = subprocess.run([sys.executable, str(self.root / "System/tools/check.py"), "--root", str(self.root),
                            "--json"], capture_output=True, text=True, env=self.env)
        found = [f["path"] for f in json.loads(r.stdout)["findings"] if f["check"] == "updates"]
        self.assertEqual(["Zones/Work/AGENTS.md.new"], found)

    def test_the_check_ignores_a_new_file_beside_one_garrick_does_not_ship(self):
        raw = self.root / "Wikis/Meetings/raw"
        raw.mkdir(parents=True, exist_ok=True)
        (raw / "contract.docx").write_text("an attachment\n")
        (raw / "contract.docx.new").write_text("another\n")
        (self.root / "System/rules.md.new").write_text("newer\n")
        r = subprocess.run([sys.executable, str(self.root / "System/tools/check.py"), "--root", str(self.root),
                            "--json"], capture_output=True, text=True, env=self.env)
        found = [f["path"] for f in json.loads(r.stdout)["findings"] if f["check"] == "updates"]
        self.assertEqual(["System/rules.md.new"], found)

    def test_version_says_it_was_updated(self):
        self.as_if_older("System/tools/scaffold.py", "# older\n")
        self.run_update("--apply", "--today", "2026-10-06")
        r = subprocess.run([sys.executable, str(self.root / "System/tools/check.py"), "--root", str(self.root),
                            "--version"], capture_output=True, text=True, env=self.env)
        self.assertIn("Updated on 6 October 2026 from", r.stdout)


def has_tag(tag):
    r = subprocess.run(["git", "-C", str(REPO), "rev-parse", "-q", "--verify", "refs/tags/" + tag],
                       capture_output=True, text=True)
    return r.returncode == 0


class TestReleases(unittest.TestCase):
    def test_tags_sort_as_versions(self):
        tags = ["v0.10.0", "v0.7.0", "v0.7.0-rc10", "v0.7.0-rc2", "v0.6.1", "vnext"]
        self.assertEqual(["v0.6.1", "v0.7.0-rc2", "v0.7.0-rc10", "v0.7.0", "v0.10.0"],
                         sorted((t for t in tags if update.version_key(t)), key=update.version_key))

    @unittest.skipUnless(shutil.which("git"), "needs git")
    def test_release_hashes_reads_0_1_0s_zone_template_and_a_pre_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="T", GIT_AUTHOR_EMAIL="t@example.invalid",
                       GIT_COMMITTER_NAME="T", GIT_COMMITTER_EMAIL="t@example.invalid")

            def git(*args):
                subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false",
                                *args], check=True, capture_output=True, env=env)

            git("init", "-q")
            todo = repo / "template" / "Zones" / "_zone" / "Todo.md"
            todo.parent.mkdir(parents=True)
            todo.write_text("# {{ZONE}}: the first todo\n")
            git("add", "-A")
            git("commit", "-q", "-m", "one")
            git("tag", "v0.1.0")
            todo.write_text("# {{ZONE}}: a candidate\n")
            git("commit", "-q", "-am", "two")
            git("tag", "v0.1.1-rc1")
            data = update.release_hashes(repo)
        self.assertEqual(["v0.1.0", "v0.1.1-rc1"], data["releases"])
        self.assertEqual({}, data["paths"])
        self.assertEqual({"Todo.md": ["# {{ZONE}}: the first todo\n", "# {{ZONE}}: a candidate\n"]}, data["zone"])

    @unittest.skipUnless(shutil.which("git") and has_tag("v0.6.0"), "needs the release tags")
    def test_release_hashes_are_current(self):
        self.assertEqual(update.release_hashes(), json.loads(update.RELEASE_HASHES.read_text()),
                         "run python3 update.py --release-hashes and commit release-hashes.json")

    @unittest.skipUnless(shutil.which("git") and has_tag("v0.6.0"), "needs the release tags")
    def test_a_real_0_6_0_workspace_updates_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            (base / "home").mkdir()
            (base / "gitconfig").write_text("[user]\n\tname = T\n\temail = t@example.invalid\n[commit]\n\tgpgsign = false\n")
            env = dict(os.environ, HOME=str(base / "home"), GIT_CONFIG_GLOBAL=str(base / "gitconfig"),
                       GIT_CONFIG_NOSYSTEM="1", PYTHONDONTWRITEBYTECODE="1")
            old = base / "old"
            old.mkdir()
            archive = subprocess.run(["git", "-C", str(REPO), "archive", "v0.6.0"], capture_output=True, check=True)
            subprocess.run(["tar", "-x", "-C", str(old)], input=archive.stdout, check=True)
            ws = base / "ws"
            r = subprocess.run([sys.executable, str(old / "install.py"), "--config", str(EXAMPLE), "--target", str(ws)],
                               capture_output=True, text=True, env=env)
            self.assertEqual(0, r.returncode, r.stderr)
            r = subprocess.run([sys.executable, str(INSTALL), "--update", str(ws), "--apply"],
                               capture_output=True, text=True, env=env)
            self.assertEqual(0, r.returncode, r.stdout + r.stderr)
            r = subprocess.run([sys.executable, str(INSTALL), "--update", str(ws)], capture_output=True, text=True, env=env)
            self.assertIn("Up to date", r.stdout)
            r = subprocess.run([sys.executable, str(ws / "System/tools/check.py"), "--root", str(ws), "--json"],
                               capture_output=True, text=True, env=env)
            self.assertEqual([], [f for f in json.loads(r.stdout)["findings"] if f["severity"] == "error"])


if __name__ == "__main__":
    unittest.main()
