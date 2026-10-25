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
import html as htmllib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import write  # noqa: E402
from test_extract import manifest  # noqa: E402
from test_your_work import PAGE_HARNESS, Case, H, Y, pa, status  # noqa: E402

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

    def test_media_stays_out_until_the_switch_brings_it_in(self):
        rec = self.with_media()
        self.files_act("copy")
        self.assertFalse((self.files / rec.name).exists())
        card = self.card()
        self.assertIn('role="switch" aria-checked="false"', card)
        self.assertIn("left out of the copy", card)
        self.assertIn("Bring in recordings and video? That downloads 1 file, 4 KB, from Shared Drive", card)
        out = self.files_act("media-in")
        self.assertEqual("Recordings and video are in Garrick's copy now: 1 file, 4 KB", out["say"])
        self.assertTrue((self.files / rec.name).is_file())
        self.assertIn("media: in", self.hub.read_text())
        out = self.files_act("media-out")
        self.assertIn("The versions already kept stay", out["say"])
        self.assertFalse((self.files / rec.name).exists())
        self.assertIn(rec.name, F.history_of(self.files))                                  # kept in its history
        self.assertNotIn("media:", self.hub.read_text())

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
                                                  "names Birch & Co (`birch`); a wall stands between acme and birch")])
        write(hook, "#!/bin/sh\ncat >&2 <<'EOF'\n%s\nEOF\nexit 1\n" % line).chmod(0o755)
        self.git("config", "core.hooksPath", str(hook.parent))
        with self.assertRaises(pa.Refused) as said:
            self.files_act("copy")
        self.assertEqual(pa.wall_refusal(self.root), str(said.exception))
        self.assertFalse(self.files.exists())
        self.assertEqual(head, self.git("rev-parse", "HEAD"))
        self.assertEqual("", self.git("status", "--porcelain"))

    def test_back_to_left_in_place_keeps_or_deletes_the_copy(self):
        self.files_act("copy")
        out = self.files_act("keep-copy")
        self.assertIn("Its copy is kept, and no longer refreshed", out["say"])
        self.assertNotIn("storage:", self.hub.read_text())
        self.assertTrue(self.files.is_dir())
        self.assertIn(self.rule(self.files), self.deny())                                 # still out of Claude's reach
        self.assertIn("An old copy is kept, with 1 version, and is no longer refreshed.", self.card())
        out = self.files_act("delete-copy")
        self.assertEqual("Garrick's copy is deleted, with its version. Your folder is as it was", out["say"])
        self.assertFalse(self.files.exists())
        self.assertEqual([self.rule(self.folder)], self.deny())
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

    def test_moved_files_open_from_the_page_and_finder_shows_only_their_folder(self):
        self.moved()
        card = self.card()
        req = {"verb": "work-file", "zone": "Work", "file": NOTE, "do": "open", "path": "Printer quote.pdf"}
        self.assertIn(htmllib.escape(json.dumps(req)), card)
        self.assertIn("Show them in Finder", card)
        self.assertIn("All 5 files are in Garrick now.", card)
        self.assertIn("Undo the move", card)
        pa.act(self.root, req)
        pa.act(self.root, {"verb": "work-file", "zone": "Work", "file": NOTE, "do": "finder"})
        self.assertEqual([[str((self.files / "Printer quote.pdf").resolve())], [str(self.files)]], self.opens())
        with self.assertRaisesRegex(pa.Refused, "not one of this work's"):
            pa.act(self.root, dict(req, path="../Catalogue 2027.md"))

    def test_a_session_on_moved_work_reads_and_may_edit_them_and_an_edit_can_be_undone(self):
        self.moved()
        quote = self.files / "Printer quote.pdf"
        quote.write_bytes(b"%PDF-1.4 edited in a session\n")                                 # as Claude would
        pa.act(self.root, {"verb": "continue", "zone": "Work", "file": NOTE})
        prime = [c for c in self.calls() if "-p" in c["args"]][-1]["args"]
        dirs = [prime[i + 1] for i, a in enumerate(prime) if a == "--add-dir"]
        self.assertEqual(str(self.files), dirs[0])
        self.assertNotIn("--settings", prime)
        self.assertNotIn(self.rule(self.files), self.deny())
        versions = F.history_of(self.files)["Printer quote.pdf"]
        self.assertEqual(2, len(versions))
        self.assertEqual(b"%PDF-1.4 a quote\n", F.history_blob(self.files, versions[1][0], "Printer quote.pdf"))
        self.assertIn("2 versions", self.card())

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


class TestThePage(Stored):
    def test_left_in_place_says_so_with_change_and_the_three_choices(self):
        card = self.card()
        self.assertIn("Where these files live: <b>left in place</b>, in Catalogue 2027. Garrick only reads them.", card)
        wid = Y.work_id("Catalogue 2027", "Work/" + NOTE)
        self.assertIn('data-w-open="%s-where">Change</button>' % wid, card)
        page = self.card(where=True)
        for title in ("Leave in place", "Keep a copy", "Move into Garrick"):
            self.assertIn(title, page)
        self.assertEqual(1, page.count('<span class="sh-tag">Now</span>'))
        self.assertIn('class="sh-opt sh-cur"', page)
        for row in ("What happens", "Space and download", "Who else is affected"):
            self.assertEqual(2, page.count("<dt>%s</dt>" % row))                  # Keep a copy's and Move's previews
        size = F.said_size(sum(s.st_size for s in F.listing(self.folder).values()))
        self.assertIn("Downloads all 5 files, %s" % size, page)
        self.assertIn("Anyone else who uses the folder will no longer see these files.", page)
        self.assertIn("Hana Royle and Owen Tarrant are named in this work", page)
        self.assertIn("data-busy=", page)
        self.assertNotIn(str(self.drive), page)

    def test_a_copy_shows_when_it_was_refreshed_its_versions_and_refresh_now(self):
        self.files_act("copy")
        card = self.card()
        self.assertIn("Left in place, with a copy kept in Garrick.", card)
        self.assertIn("when you chose Keep a copy", card)
        self.assertIn("<dt>Versions</dt><dd>1, the first copy", card)
        self.assertIn("Refresh now", card)
        self.assertIn("Garrick refreshes its copy from your folder first", card)
        plan = self.folder / "Catalogue 2027 page plan.xlsx"
        plan.write_bytes(plan.read_bytes() + b"more")
        self.before = manifest(self.drive)
        self.files_act("refresh")
        card = self.card()
        found = re.search(r'data-vers="([^"]+)">2 versions<', card)
        data = json.loads(htmllib.unescape(found.group(1)))
        self.assertEqual("Catalogue 2027 page plan: 2 versions", data["t"])
        self.assertEqual("Same as your folder now", data["v"][0]["n"])
        self.assertEqual("The first copy", data["v"][1]["n"])
        page = self.card(where=True)
        self.assertIn("Leave in place, keep the copy", page)
        self.assertIn("Leave in place, delete the copy", page)

    def test_the_first_copy_says_what_it_copied(self):
        self.files_act("copy")
        card = self.card()
        self.assertRegex(card, r"<dt>Last refreshed</dt><dd>Today, \d\d:\d\d, when you chose Keep a copy: 5 files copied\.</dd>")
        self.assertNotIn("had changed", card)

    def test_a_file_changed_in_the_folder_is_changed_not_new(self):
        """Before any Continue, a file that moved lately counted as new; the copy's history says it was there."""
        note = self.note()
        note.write_text(re.sub(r"(?m)^updated: .*$", "updated: %s" % (self.today - dt.timedelta(days=5)).isoformat(),
                               note.read_text(), count=1))
        self.git("commit", "-q", "-am", "an older note")
        self.files_act("copy")
        plan = self.folder / "Catalogue 2027 page plan.xlsx"
        plan.write_bytes(plan.read_bytes() + b"more")
        self.before = manifest(self.drive)
        card = self.card()
        self.assertIn('Catalogue 2027 page plan.xlsx <span class="sh-tag">changed</span>', card)     # in the folder, not refreshed yet
        self.files_act("refresh")
        card = self.card()
        self.assertIn('Catalogue 2027 page plan.xlsx <span class="sh-tag">changed</span>', card)
        self.assertNotIn('<span class="sh-tag">new</span>', card)
        self.assertIn("1 changed since it last moved", card)

    def test_your_work_and_needs_you_are_the_same_wherever_the_files_live(self):
        def home():
            html = self.page()
            return html.split('id="tab-home"', 1)[1].split("</section>", 1)[0]
        left = home()
        self.files_act("copy")
        self.assertEqual(left.count("Catalogue 2027"), home().count("Catalogue 2027"))
        self.files_act("move")
        self.before = None
        moved = home()
        self.assertEqual(left.count("Catalogue 2027"), moved.count("Catalogue 2027"))
        self.assertIn("is this your next step?", moved)
        self.files_act("undo")
        self.before = manifest(self.drive)


@unittest.skipUnless(shutil.which("node"), "Node is not installed")
class TestThePageScript(Stored):
    """The page's own buttons for where files live, driven as a person would."""

    def drive_page(self, *steps, kept=None, flags=None):
        html = self.page()
        js = "window.setInterval=function(){return 0};window.clearInterval=function(){};" + status.SIMPLE_JS + status.WHERE_JS
        if flags:
            js = "".join("window.%s=true;" % f for f in flags) + js
        done = subprocess.run(["node", "-e", PAGE_HARNESS, json.dumps([html, js, list(steps), kept])],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(0, done.returncode, done.stderr)
        return json.loads(done.stdout)

    def wid(self):
        return Y.work_id("Catalogue 2027", "Work/" + NOTE)

    def test_keep_a_copy_shows_the_busy_screen_and_stop_asks_to_stop(self):
        sel = '#%s-where button[data-busy]' % self.wid()
        out = self.drive_page({"do": "click", "sel": sel}, {"do": "click", "sel": "button[data-files-stop]"})
        q = {"verb": "files", "zone": "Work", "file": NOTE, "do": "copy"}
        self.assertEqual([{"act": q}, {"act": {"verb": "files-stop", "zone": "Work", "file": NOTE}}], out["posted"])
        busy = json.loads(out["store"]["garrick-files-busy"])
        self.assertEqual("Making the first copy", busy["d"]["t"])
        self.assertEqual(1, busy["stopping"])

    def test_the_media_switch_asks_before_it_brings_media_in(self):
        self.with_media()
        self.files_act("copy")
        out = self.drive_page({"do": "click", "sel": "button[data-media]"})
        self.assertEqual([], out["posted"])                                     # asks first
        out = self.drive_page({"do": "click", "sel": "button[data-media]"}, {"do": "click", "sel": "[data-media-yes]"})
        self.assertEqual([{"act": {"verb": "files", "zone": "Work", "file": NOTE, "do": "media-in"}}], out["posted"])

    def test_a_version_is_saved_through_the_apps_save_panel_or_into_downloads(self):
        self.files_act("copy")
        plan = self.folder / "Catalogue 2027 page plan.xlsx"
        plan.write_bytes(plan.read_bytes() + b"more")
        self.before = manifest(self.drive)
        self.files_act("refresh")
        steps = ({"do": "click", "sel": "button[data-vers]"}, {"do": "click", "sel": "button[data-vsave]", "nth": 1})
        older = F.history_of(self.files)["Catalogue 2027 page plan.xlsx"][1][0]
        q = {"verb": "work-file", "zone": "Work", "file": NOTE, "do": "version-save", "path": "Catalogue 2027 page plan.xlsx",
             "version": older}
        out = self.drive_page(*steps, flags=["GarrickSaves"])
        self.assertEqual([{"save": {"act": q, "name": "Catalogue 2027 page plan, today.xlsx"}}], out["posted"])
        self.assertEqual([{"act": q}], self.drive_page(*steps)["posted"])
        opened = self.drive_page({"do": "click", "sel": "button[data-vers]"}, {"do": "click", "sel": "button[data-vopen]"})
        self.assertEqual("version-open", opened["posted"][0]["act"]["do"])


class TestTheApp(unittest.TestCase):
    def test_the_app_answers_save_and_reads_progress_without_a_toast(self):
        swift = (Path(status.__file__).parent / "app" / "Garrick.swift").read_text(encoding="utf-8")
        self.assertIn('if let save = body["save"] as? [String: Any] { return saveVersion(save) }', swift)
        self.assertIn("NSSavePanel()", swift)
        self.assertIn('"files-progress"', swift[swift.index("func reading("):][:300])
        self.assertIn("window.GarrickReadsFiles=true;window.GarrickSaves=true;", swift)
        plugin = (Path(status.__file__).parent / "obsidian" / "main.js").read_text(encoding="utf-8")
        self.assertIn('"files-progress"', plugin[plugin.index("reading(request) {"):][:300])


if __name__ == "__main__":
    unittest.main()
