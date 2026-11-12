"""Where a piece of work's files live (#189): left in place, a copy kept, or moved into Garrick.

    python3 -m unittest discover -s tests -p test_work_files.py

On the fictional drive test_your_work.py builds, a piece of work's page offers
Keep a copy and Move into Garrick. Every test compares the user's folder with
what it was before, by each file's checksum, size and modification time and
every folder: unchanged throughout while the files are left in place or
copied; during a move, nothing is removed until every file is copied and
checked; after Undo, every file is back as it was. The Claude Code CLI and
macOS's `open` are never run: stand-ins write down how they were called.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import write  # noqa: E402
from test_extract import manifest  # noqa: E402
from test_your_work import Case, Y, pa  # noqa: E402

F = pa.work_files_lib()
NOTE = "Catalogue 2027/Threads/Catalogue 2027/Catalogue 2027.md"

OPEN_STUB = r'''#!/usr/bin/env python3
import json, os, sys
with open(os.environ["OPEN_LOG"], "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\n")
'''


def files_only(rows):
    """A manifest's files, as they were: what Undo must give back exactly."""
    return [r for r in rows if r[0] == "file"]


def folders_only(rows):
    return sorted(r[1] for r in rows if r[0] == "dir")


class Stored(Case):
    """A piece of work said yes to and started, from Catalogue 2027 on the drive."""

    def setUp(self):
        super().setUp()
        self.folder = self.drive / "Marketing" / "Catalogue 2027"
        self.add()
        self.act(verb="start", zone="Work", file=NOTE)
        self.project = self.work / "Catalogue 2027"
        self.files = self.project / "Files"
        self.hub = self.project / "Catalogue 2027.md"
        self.settings = self.project / ".claude" / "settings.json"
        self.opened = self.base / "open.jsonl"
        stub = self.base / "bin" / "open"
        write(stub, OPEN_STUB)
        stub.chmod(0o755)
        env = mock.patch.dict(os.environ, {"GARRICK_OPEN": str(stub), "OPEN_LOG": str(self.opened)})
        env.start()
        self.addCleanup(env.stop)

    def files_act(self, do, today=None, **more):
        return pa.act(self.root, dict({"verb": "files", "zone": "Work", "file": NOTE, "do": do}, **more),
                      today=today or self.today)

    def changed(self):
        return set(filter(None, self.git("show", "--name-only", "--format=", "HEAD").splitlines()))

    def deny(self):
        return json.loads(self.settings.read_text())["permissions"]["deny"]

    def rule(self, path):
        return "Edit(/%s/**)" % os.path.realpath(str(path))

    def history(self, *args):
        return subprocess.run(["git", "-C", str(self.files)] + list(args), check=True, capture_output=True,
                              text=True).stdout

    def opens(self):
        try:
            return [json.loads(l) for l in self.opened.read_text().splitlines()]
        except FileNotFoundError:
            return []

    def card(self, html=None, where=False):
        html = html or self.page()
        wid = Y.work_id("Catalogue 2027", "Work/" + NOTE) + ("-where" if where else "")
        return html.split('id="%s"' % wid, 1)[1].split("</article>", 1)[0]

    def with_media(self):
        """A recording added to the folder, as the user would: the folder's new state is the one to keep."""
        rec = self.folder / "Proof review call.m4a"
        rec.write_bytes(b"\0" * 4096)
        self.before = manifest(self.drive)
        return rec


class TestKeepACopy(Stored):
    def test_a_copy_is_made_with_its_own_history_and_the_folder_is_untouched(self):
        out = self.files_act("copy")
        self.assertEqual("Garrick keeps a copy now. Your folder is as it was", out["say"])
        self.assertTrue((self.files / ".git" / F.HISTORY_MARK).is_file())
        theirs = {r: s.st_size for r, s in F.listing(self.folder).items()}
        self.assertEqual(theirs, {r: s.st_size for r, s in F.listing(self.files).items()})
        self.assertEqual("1", self.history("rev-list", "--count", "HEAD").strip())
        self.assertIn("storage: copy", self.hub.read_text())
        self.assertIn("/Files/", (self.project / ".gitignore").read_text())
        self.assertEqual({"Catalogue 2027/Catalogue 2027.md", "Catalogue 2027/.gitignore",
                          "Catalogue 2027/.claude/settings.json"}, self.changed())       # committed by name
        self.assertEqual("", self.git("status", "--porcelain"))                         # the zone ignores the copy
        self.assertEqual([self.rule(self.folder), self.rule(self.files)], self.deny())  # Claude edits neither

    def test_a_changed_file_is_a_new_version_and_an_unchanged_one_takes_no_space(self):
        self.files_act("copy")
        plan = self.folder / "Catalogue 2027 page plan.xlsx"
        plan.write_bytes(plan.read_bytes() + b"more")
        self.before = manifest(self.drive)
        out = self.files_act("refresh")
        self.assertIn("1 file had changed in your folder: Catalogue 2027 page plan", out["say"])
        self.assertEqual("2", self.history("rev-list", "--count", "HEAD").strip())
        quote = "Printer quote.pdf"
        self.assertEqual(self.history("rev-parse", "HEAD:" + quote), self.history("rev-parse", "HEAD~1:" + quote))
        self.assertNotEqual(self.history("rev-parse", "HEAD:Catalogue 2027 page plan.xlsx"),
                            self.history("rev-parse", "HEAD~1:Catalogue 2027 page plan.xlsx"))
        again = self.files_act("refresh")
        self.assertIn("Nothing had changed since the last refresh", again["say"])
        self.assertEqual("2", self.history("rev-list", "--count", "HEAD").strip())

    def test_a_file_gone_from_the_folder_leaves_the_copy_and_its_history_keeps_it(self):
        self.files_act("copy")
        (self.folder / "Printer quote.pdf").unlink()
        self.before = manifest(self.drive)
        self.files_act("refresh")
        self.assertFalse((self.files / "Printer quote.pdf").exists())
        self.assertIn("Printer quote.pdf", F.history_of(self.files))

    def test_continue_refreshes_first_and_claude_reads_the_folder_and_edits_neither(self):
        self.files_act("copy")
        out = pa.act(self.root, {"verb": "continue", "zone": "Work", "file": NOTE})
        self.assertIn("Garrick refreshed its copy first. Nothing had changed since the last refresh", out)
        prime = [c for c in self.calls() if "-p" in c["args"]][-1]["args"]
        dirs = [prime[i + 1] for i, a in enumerate(prime) if a == "--add-dir"]
        self.assertEqual(os.path.realpath(str(self.folder)), dirs[0])                      # the original, as before
        guard = json.loads(prime[prime.index("--settings") + 1])["permissions"]["deny"]
        self.assertEqual([self.rule(self.folder), self.rule(self.files)], guard)
        self.assertEqual("continue", F.state(self.root)["Work/" + NOTE]["via"])
        self.assertEqual("", self.git("status", "--porcelain"))

    def test_stop_while_copying_leaves_nothing_behind(self):
        head = self.git("rev-parse", "HEAD")
        real = F.copy_checked

        def stop_on_first(src, dst, tick=None):
            (self.root / "System" / "generated" / "work-files" / (F.key_hash("Work/" + NOTE) + ".stop")).write_text("stop")
            return real(src, dst, tick)
        with mock.patch.object(F, "copy_checked", stop_on_first):
            out = self.files_act("copy")
        self.assertTrue(out["stopped"])
        self.assertEqual("Stopped. Garrick kept nothing, and your folder is as it was", out["say"])
        self.assertFalse(self.files.exists())
        self.assertEqual(head, self.git("rev-parse", "HEAD"))
        self.assertEqual("", self.git("status", "--porcelain"))
        self.assertNotIn("storage:", self.hub.read_text())

    def test_a_copy_the_wall_check_refuses_leaves_nothing_behind(self):
        import check
        head = self.git("rev-parse", "HEAD")
        hook = self.base / "hooks" / "pre-commit"
        line = check.report_staged([check.Finding(check.ERROR, "walls", "Catalogue 2027/Catalogue 2027.md",
                                                  "names Birch & Co (`birch`); birch is walled and this project does not name it")])
        write(hook, "#!/bin/sh\n# Garrick wall check (a stand-in)\ncat >&2 <<'EOF'\n%s\nEOF\nexit 1\n" % line).chmod(0o755)
        self.git("config", "core.hooksPath", str(hook.parent))
        with self.assertRaises(pa.Refused) as said:
            self.files_act("copy")
        self.assertEqual(pa.wall_refusal(self.root), str(said.exception))
        self.assertFalse(self.files.exists())
        self.assertEqual(head, self.git("rev-parse", "HEAD"))
        self.assertEqual("", self.git("status", "--porcelain"))

    def test_a_version_is_opened_to_read_or_saved_as_a_separate_file_never_restored(self):
        self.files_act("copy")
        plan = self.folder / "Catalogue 2027 page plan.xlsx"
        first = plan.read_bytes()
        plan.write_bytes(first + b"more")
        self.before = manifest(self.drive)
        self.files_act("refresh")
        rel = "Catalogue 2027 page plan.xlsx"
        older = F.history_of(self.files)[rel][1][0]
        said = pa.act(self.root, {"verb": "work-file", "zone": "Work", "file": NOTE, "do": "version-open", "path": rel,
                                  "version": older})
        self.assertIn("to read. Nothing was changed", said)
        (opened,) = self.opens()
        self.assertEqual(first, Path(opened[0]).read_bytes())
        self.assertTrue(opened[0].startswith(str(self.root / "System" / "generated" / "versions")))
        self.assertRegex(Path(opened[0]).name, r"^Catalogue 2027 page plan, today\.xlsx$")
        out = self.base / "Saved"
        out.mkdir()
        pa.act(self.root, {"verb": "work-file", "zone": "Work", "file": NOTE, "do": "version-save", "path": rel,
                           "version": older, "to": str(out / "Plan, before.xlsx")})
        self.assertEqual(first, (out / "Plan, before.xlsx").read_bytes())
        self.assertEqual(first + b"more", (self.files / rel).read_bytes())                # nothing put back
        for inside in (self.folder / "x.xlsx", self.files / "x.xlsx"):
            with self.assertRaisesRegex(pa.Refused, "Garrick never writes there"):
                pa.act(self.root, {"verb": "work-file", "zone": "Work", "file": NOTE, "do": "version-save", "path": rel,
                                   "version": older, "to": str(inside)})
        with self.assertRaisesRegex(pa.Refused, "not one of this work's"):
            pa.act(self.root, {"verb": "work-file", "zone": "Work", "file": NOTE, "do": "version-open",
                               "path": "../Catalogue 2027.md", "version": older})

    def test_the_checks_find_nothing_wrong_with_a_copy(self):
        self.files_act("copy")
        r = subprocess.run([sys.executable, str(self.root / "System" / "tools" / "check.py"), "--root", str(self.root),
                            "--json"], capture_output=True, text=True)
        found = [f for f in json.loads(r.stdout)["findings"] if "Catalogue 2027" in f["path"]]
        self.assertEqual([], found)


class TestMoveIntoGarrick(Stored):
    def moved(self):
        before = manifest(self.drive)
        out = self.files_act("move")
        self.before = None
        return before, out

    def tearDown(self):
        if self.before is None:
            self._tmp.cleanup()
        else:
            super().tearDown()

    def test_every_file_is_copied_and_checked_then_removed_and_the_folder_kept(self):
        rec = self.with_media()
        n = len(F.listing(self.folder))
        before, out = self.moved()
        self.assertEqual("Moved. All %d files are in Garrick" % n, out["say"])
        self.assertTrue(self.folder.is_dir())
        self.assertEqual({}, F.listing(self.folder))                                        # emptied
        self.assertTrue((self.folder / "Proofs").is_dir())                                  # and nothing written into it
        self.assertEqual(sorted(os.listdir(self.folder)), ["Proofs"])
        self.assertTrue((self.files / rec.name).is_file())                                   # media comes too
        self.assertIn("storage: moved", self.hub.read_text())
        self.assertIn("moved: %s" % self.today.isoformat(), self.hub.read_text())
        self.assertEqual([self.rule(self.folder)], self.deny())                               # Claude may edit the files
        self.assertEqual({"Catalogue 2027/Catalogue 2027.md", "Catalogue 2027/.gitignore"}, self.changed())
        self.assertEqual("", self.git("status", "--porcelain"))
        for row in files_only(before):
            rel = row[1].split("Catalogue 2027/", 1)[1] if "Marketing/Catalogue 2027/" in row[1] else None
            if rel:
                self.assertEqual(row[2], F.digest(self.files / rel))

    def test_the_day_it_moved_is_the_day_given_not_the_clock(self):
        """#212: a run that crossed midnight wrote one day and expected another."""
        self.files_act("move", today=dt.date(2027, 1, 1))
        self.before = None
        self.assertIn("moved: 2027-01-01", self.hub.read_text())

    def test_a_copy_that_becomes_a_move_keeps_its_versions(self):
        self.with_media()                                                                    # out of the copy, in the move
        self.files_act("copy")
        self.assertIn(self.rule(self.files), self.deny())
        self.moved()
        self.assertEqual("2", self.history("rev-list", "--count", "HEAD").strip())
        self.assertIn("The first copy", self.history("log", "--format=%s"))
        self.assertEqual([self.rule(self.folder)], self.deny())                              # the rule on the copy comes off
        self.assertIn("Catalogue 2027/.claude/settings.json", self.changed())

    def test_nothing_is_removed_until_every_file_is_checked(self):
        """A copy that does not match its original, found while checking: nothing leaves the folder."""
        before = manifest(self.drive)
        real = F.digest
        calls = []

        def bad(path):
            calls.append(path)
            return "0" * 64 if Path(path).name == "Printer quote.pdf" and self.files in Path(path).parents else real(path)
        with mock.patch.object(F, "digest", bad):
            with self.assertRaisesRegex(pa.Refused, "did not match its original, so nothing left the folder"):
                self.files_act("move")
        self.assertEqual(before, manifest(self.drive))
        self.assertFalse(self.files.exists())
        self.assertNotIn("storage:", self.hub.read_text())

    def test_stop_while_checking_leaves_the_folder_and_the_workspace_as_they_were(self):
        before, head = manifest(self.drive), self.git("rev-parse", "HEAD")
        flag = self.root / "System" / "generated" / "work-files" / (F.key_hash("Work/" + NOTE) + ".stop")
        real = F.digest

        def stop(path):
            flag.write_text("stop")
            return real(path)
        with mock.patch.object(F, "digest", stop):
            out = self.files_act("move")
        self.assertEqual("Stopped. Every file is still in your folder, and Garrick kept nothing of the move", out["say"])
        self.assertEqual(before, manifest(self.drive))
        self.assertFalse(self.files.exists())
        self.assertEqual(head, self.git("rev-parse", "HEAD"))
        self.assertEqual("", self.git("status", "--porcelain"))

    def test_stop_is_refused_once_files_start_leaving(self):
        job = F.Job(self.root, "Work/" + NOTE, "move")
        job.phase("removing", 5)
        try:
            with self.assertRaisesRegex(pa.Refused, "already leaving the folder"):
                pa.act(self.root, {"verb": "files-stop", "zone": "Work", "file": NOTE})
            job.phase("checking", 5)
            self.assertEqual("Stopping: Garrick takes back what it copied",
                             pa.act(self.root, {"verb": "files-stop", "zone": "Work", "file": NOTE}))
            with self.assertRaises(F.Stopped):
                job.check()
            progress = pa.act(self.root, {"verb": "files-progress", "zone": "Work", "file": NOTE})
            self.assertEqual("checking", progress["progress"]["phase"])
        finally:
            job.end()
        with self.assertRaisesRegex(pa.Refused, "Nothing is being copied or moved"):
            pa.act(self.root, {"verb": "files-stop", "zone": "Work", "file": NOTE})

    def test_undo_puts_back_every_file_and_never_overwrites(self):
        before, _ = self.moved()
        clash = self.folder / "Printer quote.pdf"
        clash.write_bytes(b"a new quote, put there by someone else")
        out = self.files_act("undo")
        self.assertIn("are back in Catalogue 2027", out["say"])
        self.assertIn("A file of the same name was in the folder already, so Garrick's went back beside it: "
                      "Printer quote (from Garrick).pdf", out["say"])
        self.assertEqual(b"a new quote, put there by someone else", clash.read_bytes())       # two files, never one
        ours = self.folder / "Printer quote (from Garrick).pdf"
        self.assertEqual(b"%PDF-1.4 a quote\n", ours.read_bytes())
        clash.unlink()
        ours.rename(clash)
        os.utime(str(clash), ns=(os.stat(str(self.files / "Printer quote.pdf")).st_atime_ns,
                                 os.stat(str(self.files / "Printer quote.pdf")).st_mtime_ns))
        self.assertEqual(files_only(before), files_only(manifest(self.drive)))               # every file, as it was
        self.assertEqual(folders_only(before), folders_only(manifest(self.drive)))
        self.assertNotIn("storage:", self.hub.read_text())
        self.assertIn(self.rule(self.files), self.deny())                                   # the old copy out of reach again
        self.assertEqual("", self.git("status", "--porcelain"))

    def test_stop_using_this_puts_the_files_back_first_and_keeps_the_copy(self):
        before, _ = self.moved()
        said = pa.act(self.root, {"verb": "stop-using", "zone": "Work", "file": NOTE})
        self.assertIn("Catalogue 2027 is put away. All 5 files are back in Catalogue 2027 first", said)
        self.assertEqual(files_only(before), files_only(manifest(self.drive)))
        away = self.work / "archive" / "Catalogue 2027"
        self.assertTrue((away / "Files" / ".git" / F.HISTORY_MARK).is_file())             # recoverable, nothing deleted
        self.assertEqual("", self.git("status", "--porcelain"))
        pa.act(self.root, {"verb": "bring-back", "zone": "Work", "project": "Catalogue 2027"})
        self.assertTrue((self.files / ".git").is_dir())


if __name__ == "__main__":
    unittest.main()
