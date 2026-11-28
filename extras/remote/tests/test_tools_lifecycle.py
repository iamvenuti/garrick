"""The six lifecycle verbs (#724): check-name, new-project, new-thread, rename, move and undo, as prepare, execute and status.

Each runs the workspace's real page_action.py as a process, as a click runs it, in a fixture workspace with a real git repository for each zone
(Work, which the grant reaches, and Personal, which it does not). A rename and a move are shown before they run, and run only on the confirmation
of that one preview. Every test drives the tools in this process, or the MCP server on loopback; nothing reaches this Mac, a tunnel or a phone.

Run with the extra's runtime:  python -m unittest discover -s extras/remote/tests -p "test_tools_lifecycle.py"
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

import tools_support as support  # noqa: E402
from test_tools_writes import WritesCase, git  # noqa: E402
from tools import common, lifecycle, manifest, run_op, writes  # noqa: E402

REPO = support.REPO
OTHER_ZONE = ("Personal", "Birch Entry", "Market Sizing", "birch", "BIRCHTHREAD71")      # names of the zone the grant does not reach


def load_page_action(ws):
    """The workspace's own page_action.py, as the app's bridge loads it: the page's route, in this process."""
    spec = importlib.util.spec_from_file_location("garrick_life_page_%x" % abs(hash(str(ws))), str(Path(ws) / "System" / "status" / "page_action.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class LifeCase(WritesCase):
    def setUp(self):
        super().setUp()
        shutil.copytree(str(REPO / "template" / "System" / "templates"), str(self.root / "System" / "templates"), dirs_exist_ok=True)
        self.personal = self.root / "Zones" / "Personal"
        self.jobs = Path(self._tmp.name) / "life-jobs"
        self._saved_jobs = os.environ.get("GARRICK_JOBS_DIR")
        os.environ["GARRICK_JOBS_DIR"] = str(self.jobs)
        self.addCleanup(self._restore_jobs)
        self.scaffold("project", "--zone", "Work", "--name", "Cedar", "--party", "acme", "--thread", "Kickoff")
        self.scaffold("thread", "--zone", "Work", "--project", "Acme Review", "--name", "Freight")      # a thread nothing at the top names
        note = self.work / "Acme Review" / "Threads" / "Pricing" / "Pricing.md"
        note.write_text(note.read_text() + "\nSee [[Cedar/Threads/Kickoff/Kickoff|Kickoff]] and [[Pricing]] again.\n")
        freight = self.work / "Acme Review" / "Threads" / "Freight" / "Freight.md"
        freight.write_text(freight.read_text() + "\nThe lanes are in [[Freight]], see [[Acme Review/Threads/Freight/Freight|Freight]].\n")
        todo = self.work / "Todo.md"
        todo.write_text(todo.read_text().replace("## Inbox\n", "## Inbox\n\n- [ ] [[Kickoff]]: send the plan\n", 1))
        self.save("projects for the lifecycle")
        self.s = self.session(readable=("Work", "Knowledge", "docs"), writable=("Work",))
        self.w = writes.Writes(self.s)

    def _restore_jobs(self):
        if self._saved_jobs is None:
            os.environ.pop("GARRICK_JOBS_DIR", None)
        else:
            os.environ["GARRICK_JOBS_DIR"] = self._saved_jobs

    def scaffold(self, *args):
        done = subprocess.run([sys.executable, str(self.root / "System" / "tools" / "scaffold.py"), "--root", str(self.root), *args],
                              capture_output=True, text=True)
        self.assertEqual(0, done.returncode, done.stderr)
        return done.stdout

    def save(self, message):
        git(self.work, "add", "-A")
        subprocess.run(["git", "-C", str(self.work), "commit", "-q", "--allow-empty", "-m", message], capture_output=True, check=True)

    def head(self, zone=None):
        return git(zone or self.work, "rev-parse", "HEAD").strip()

    def state(self, zone=None):
        """What a write would leave behind anywhere in the repository: HEAD, the index and the work tree."""
        zone = zone or self.work
        return self.head(zone), git(zone, "status", "--porcelain", "--ignored")

    def contents(self, folder):
        """Every file under a folder, with its bytes or its link: what a write through a link would change."""
        return {p.relative_to(folder).as_posix(): (os.readlink(str(p)) if p.is_symlink() else p.read_bytes() if p.is_file() else None)
                for p in sorted(Path(folder).rglob("*")) if ".git" not in p.parts}

    def prep(self, verb, **fields):
        made = self.w.prepare(verb, "Work", **fields)
        self.assertEqual("prepared", made.get("state"), made)
        return made

    def run_it(self, verb, **fields):
        """Prepare, confirm where the verb asks for it, execute and wait: (the preview, the receipt)."""
        made = self.prep(verb, **fields)
        out = self.w.execute(made["operation_id"], made.get("confirmation"))
        self.assertEqual("running", out.get("state"), out)
        return made, self.wait(made["operation_id"])

    # ---------------------------------------------------------------- the App's own path, in a copy of the workspace

    def twin(self):
        """A copy of the workspace as it is now, and the App's page_action.py loaded from it."""
        copy = Path(self._tmp.name) / ("twin-%d" % time.monotonic_ns())
        shutil.copytree(str(self.root), str(copy), symlinks=True)
        return copy, load_page_action(copy)

    def app(self, twin, req, via="page"):
        """The App's path: perform() as the page's bridge calls it. The reply, as the page reads it."""
        ws, pa = twin
        out, _, _ = pa.perform(ws, req, pa.ops_lib(ws), via=via)
        return out

    def changed(self, repo, rev="HEAD"):
        return git(repo, "show", "--name-status", "--format=", rev).strip().splitlines()

    def same_commit(self, twin, ours=None):
        """The App's commit and ours: the same tree, the same files changed, the same subject and the same count of commits."""
        copy = twin[0] / "Zones" / "Work"
        self.assertEqual(git(copy, "rev-parse", "HEAD^{tree}").strip(), git(self.work, "rev-parse", "HEAD^{tree}").strip())
        self.assertEqual(self.changed(copy), self.changed(self.work))
        self.assertEqual(git(copy, "log", "-1", "--format=%s").strip(), git(self.work, "log", "-1", "--format=%s").strip())
        self.assertEqual(len(git(copy, "log", "--oneline").splitlines()), self.commits())


class TestCheckName(LifeCase):
    KINDS = (
        ("project", dict(name="Maple")), ("project", dict(name="Cedar")), ("thread", dict(project="Cedar", name="Budget")),
        ("thread", dict(project="Cedar", name="Kickoff")), ("rename", dict(project="Acme Review", thread="Pricing", to="Rates")),
        ("rename", dict(project="Acme Review", thread="Pricing", to="Pricing")), ("move", dict(project="Acme Review", thread="Pricing", to="Cedar")),
        ("move", dict(project="Acme Review", thread="Pricing", to="Nowhere")),
    )

    def test_it_answers_in_the_apps_words_whether_a_name_is_free(self):
        twin = self.twin()
        free = []
        for kind, fields in self.KINDS:
            with self.subTest(kind=kind, fields=fields):
                ours = self.w.prepare("check-name", "Work", kind=kind, **fields)
                theirs = self.app(twin, dict(verb="check-name", zone="Work", kind=kind, **fields))
                self.assertEqual("checked", ours["state"], ours)
                self.assertEqual(theirs["ok"], ours["free"])
                self.assertEqual(theirs["say"], ours["say"])
                free.append(ours["free"])
        self.assertIn(True, free)
        self.assertIn(False, free)

    def test_it_writes_nothing_and_prepares_nothing_that_can_be_executed(self):
        before, kept = self.state(), list(self.w.store.all())
        os_before = sorted(p.name for p in (self.root / "Zones" / "Work").rglob("*") if ".git" not in p.parts)
        for kind, fields in self.KINDS:
            out = self.w.prepare("check-name", "Work", kind=kind, **fields)
            self.assertNotIn("operation_id", out)
        self.assertEqual(before, self.state())
        self.assertEqual(kept, list(self.w.store.all()))
        self.assertEqual(os_before, sorted(p.name for p in (self.root / "Zones" / "Work").rglob("*") if ".git" not in p.parts))
        self.assertEqual({"error": "not_found", "say": writes.NOT_FOUND}, {k: self.w.execute("0" * 16)[k] for k in ("error", "say")})

    def test_a_zone_outside_the_reach_is_refused_and_names_nothing_in_it(self):
        out = self.w.prepare("check-name", "Personal", kind="thread", project="Birch Entry", name="Market Sizing")
        self.assertEqual(common.NEW_REACH, out["error"])
        for name in OTHER_ZONE:
            self.assertNotIn(name, json.dumps(out))

    def test_a_kind_needs_its_own_fields_and_takes_no_other(self):
        for kind, fields, said in (("project", dict(), "needs name"), ("thread", dict(name="x"), "needs project"),
                                   ("rename", dict(project="Cedar"), "needs to"), ("move", dict(project="Cedar", to="x"), "needs thread"),
                                   ("project", dict(name="x", to="y"), "does not take to"), ("sideways", dict(name="x"), "kind is one of")):
            out = self.w.prepare("check-name", "Work", kind=kind, **fields)
            self.assertEqual("not_prepared", out["error"], (kind, fields))
            self.assertIn(said, out["say"])
        self.assertEqual("not_prepared", self.w.prepare("check-name", "Work")["error"])


class TestNewProjectAndThread(LifeCase):
    def test_a_project_is_made_as_the_app_makes_it(self):
        twin = self.twin()
        theirs = self.app(twin, dict(verb="new-project", zone="Work", name="Maple", party="acme", thread="Budget"))
        made, out = self.run_it("new-project", name="Maple", party="acme", thread="Budget")
        self.assertTrue(theirs["ok"], theirs)
        self.assertEqual("saved", out["state"], out)
        self.assertEqual(theirs["say"], out["say"])
        self.same_commit(twin)
        self.assertTrue((self.work / "Maple" / "Threads" / "Budget" / "Budget.md").is_file())
        self.assertEqual("", git(self.work, "status", "--porcelain").strip())
        self.assertRegex(out["commit"], r"^[0-9a-f]{7,40}$")
        self.assertEqual(self.head(), git(self.work, "rev-parse", out["commit"]).strip())

    def test_a_thread_is_made_as_the_app_makes_it(self):
        twin = self.twin()
        theirs = self.app(twin, dict(verb="new-thread", zone="Work", project="Cedar", name="Budget"))
        made, out = self.run_it("new-thread", project="Cedar", name="Budget")
        self.assertEqual("saved", out["state"], out)
        self.assertEqual(theirs["say"], out["say"])
        self.same_commit(twin)
        self.assertIn("Budget", (self.work / "Cedar" / "Cedar.md").read_text())
        self.assertRegex(out["commit"], r"^[0-9a-f]{7,40}$")

    def test_what_the_app_refuses_is_refused_in_its_words_before_anything_is_prepared(self):
        twin = self.twin()
        for verb, fields in (("new-project", dict(name="Cedar")), ("new-thread", dict(project="Cedar", name="Kickoff")),
                             ("new-thread", dict(project="Nowhere", name="Budget")), ("new-project", dict(name="Inbox")),
                             ("new-project", dict(name="Maple", thread="Budget Plan 4"))):
            with self.subTest(verb=verb, fields=fields):
                theirs = self.app(twin, dict(verb=verb, zone="Work", **fields))
                ours = self.w.prepare(verb, "Work", **fields)
                if theirs["ok"]:
                    self.assertEqual("prepared", ours["state"])
                    continue
                self.assertEqual("not_prepared", ours["error"], ours)
                self.assertEqual(theirs["say"], ours["say"])
        self.assertEqual([], list(self.w.store.all()))

    def test_a_party_that_is_not_in_the_parties_table_is_refused_and_no_party_of_another_zone_is_named(self):
        twin = self.twin()
        before = self.state()
        for party in ("nobody", "birch"):                              # not there at all; and a party of the zone the grant does not reach
            theirs = self.app(twin, dict(verb="new-project", zone="Work", name="Maple", party=party))
            self.assertFalse(theirs["ok"], theirs)
            ours = self.w.prepare("new-project", "Work", name="Maple", party=party)
            self.assertEqual("not_prepared", ours["error"], ours)
            self.assertEqual(run_op.PARTY_SAY, ours["say"])
            for name in OTHER_ZONE:
                self.assertNotIn(name.lower(), json.dumps(ours).lower())
        self.assertIn("The tags are", self.app(twin, dict(verb="new-project", zone="Work", name="Maple", party="nobody"))["say"])
        self.assertEqual(before, self.state())
        self.assertEqual([], list(self.w.store.all()))

    def test_a_party_of_the_zone_is_taken_and_a_new_party_is_never_added_from_here(self):
        self.assertEqual("prepared", self.w.prepare("new-project", "Work", name="Maple", party="acme")["state"])
        for field in ("new_party", "party_what", "heading", "papers", "spoken"):
            out = self.w.prepare("new-project", "Work", name="Maple", **{field: "x"})
            self.assertEqual("not_prepared", out["error"], field)
        out = self.w.prepare("new-project-party", "Work", name="Maple")
        self.assertEqual("not_available", out["error"])
        self.assertIn("approves", out["say"])

    def test_a_name_that_must_be_asked_how_it_is_said_is_not_prepared(self):
        out = self.w.prepare("new-project", "Work", name="Q4 Planning")
        self.assertEqual("not_prepared", out["error"], out)
        self.assertIn("spoken form", out["say"])


class TestRenameAndMove(LifeCase):
    RENAME = dict(project="Acme Review", thread="Pricing", to="Rates")

    def test_the_preview_says_what_would_change_and_changes_nothing(self):
        before, commits = self.state(), self.commits()
        made = self.prep("rename", **self.RENAME)
        self.assertEqual(before, self.state())
        self.assertEqual(commits, self.commits())
        self.assertTrue(made["needs_confirmation"])
        self.assertRegex(made["confirmation"], r"^[0-9a-f]{20}$")
        preview = made["preview"]
        self.assertEqual({"from": "Acme Review/Threads/Pricing", "to": "Acme Review/Threads/Rates"}, preview["paths"][0])
        listed = {f["path"]: f for f in preview["files"]}
        self.assertIn("Todo.md", listed)
        self.assertIn("[[Pricing]]", json.dumps(listed["Todo.md"]["edits"]))
        self.assertIn("[[Rates]]", json.dumps(listed["Todo.md"]["edits"]))
        self.assertIn("Rates", made["would"])

    def test_the_preview_lists_the_notes_the_rename_then_changes(self):
        made = self.prep("rename", **self.RENAME)
        listed = {f["path"] for f in made["preview"]["files"]}
        self.w.execute(made["operation_id"], made["confirmation"])
        self.assertEqual("saved", self.wait(made["operation_id"])["state"])
        done = {p for p in git(self.work, "show", "--name-only", "--format=", "HEAD").splitlines() if p.endswith(".md")}
        self.assertEqual(listed, done)

    def test_a_move_is_previewed_with_its_hubs_and_runs_on_its_confirmation(self):
        made = self.prep("move", project="Acme Review", thread="Freight", to="Cedar")
        self.assertEqual({"leaves": "Acme Review/Acme Review.md", "enters": "Cedar/Cedar.md"}, made["preview"]["hubs"])
        self.assertEqual("Acme Review/Threads/Freight", made["preview"]["paths"][0]["from"])
        self.w.execute(made["operation_id"], made["confirmation"])
        out = self.wait(made["operation_id"])
        self.assertEqual("saved", out["state"], out)
        self.assertTrue((self.work / "Cedar" / "Threads" / "Freight" / "Freight.md").is_file())
        self.assertFalse((self.work / "Acme Review" / "Threads" / "Freight").exists())

    def test_a_rename_without_the_confirming_message_writes_nothing(self):
        made = self.prep("rename", **self.RENAME)
        before, commits = self.state(), self.commits()
        for given in (None, ""):
            out = self.w.execute(made["operation_id"], given)
            self.assertEqual("needs_confirmation", out["error"], given)
        self.assertEqual("not_confirmed", self.w.execute(made["operation_id"], "   ")["error"])
        self.assertEqual(before, self.state())
        self.assertEqual(commits, self.commits())
        self.assertEqual("prepared", self.w.status(made["operation_id"])["state"])
        self.assertTrue((self.work / "Acme Review" / "Threads" / "Pricing").is_dir())
        # and the preview can still be confirmed after a try without it
        self.w.execute(made["operation_id"], made["confirmation"])
        self.assertEqual("saved", self.wait(made["operation_id"])["state"])

    def test_a_confirmation_after_the_preview_has_expired_writes_nothing(self):
        made = self.prep("rename", **self.RENAME)
        rec = self.w.store.read(made["operation_id"])
        rec["created"] = time.time() - writes.PREPARED_KEEP - 5
        self.w.store.write(made["operation_id"], rec)
        before, commits = self.state(), self.commits()
        out = self.w.execute(made["operation_id"], made["confirmation"])
        self.assertEqual("refused", out["state"], out)                            # N4: its own sentence, not "no such operation"
        self.assertEqual(lifecycle.EXPIRED, out["say"])
        self.assertNotIn("no such operation", out["say"].lower())
        self.assertEqual(before, self.state())
        self.assertEqual(commits, self.commits())
        again = self.w.execute(made["operation_id"], made["confirmation"])
        self.assertEqual(lifecycle.EXPIRED, again["say"])
        self.assertEqual(commits, self.commits())

    def test_an_expired_preview_says_so_at_status_and_an_id_never_issued_is_still_not_found(self):
        made = self.prep("rename", **self.RENAME)
        rec = self.w.store.read(made["operation_id"])
        rec["created"] = time.time() - writes.PREPARED_KEEP - 5
        self.w.store.write(made["operation_id"], rec)
        said = self.w.status(made["operation_id"])
        self.assertEqual(("refused", lifecycle.EXPIRED), (said["state"], said["say"]))
        self.assertNotIn("confirmation", said)
        for call in (self.w.status, lambda op: self.w.execute(op, "x")):
            out = call("0123456789abcdef")
            self.assertEqual("not_found", out["error"])
            self.assertEqual(writes.NOT_FOUND, out["say"])

    def test_an_expired_preview_is_kept_as_a_receipt_and_swept_with_the_receipts(self):
        made = self.prep("rename", **self.RENAME)
        rec = self.w.store.read(made["operation_id"])
        rec["created"] = time.time() - writes.PREPARED_KEEP - 5
        self.w.store.write(made["operation_id"], rec)
        self.w.store.tidy()
        self.assertTrue(self.w.store.exists(made["operation_id"]))
        self.w.store.tidy(now=time.time() + writes.DONE_KEEP + 60)
        self.assertFalse(self.w.store.exists(made["operation_id"]))
        self.assertEqual("not_found", self.w.status(made["operation_id"])["error"])

    def test_a_confirmation_used_twice_runs_once(self):
        made = self.prep("rename", **self.RENAME)
        commits = self.commits()
        first = self.w.execute(made["operation_id"], made["confirmation"])
        second = self.w.execute(made["operation_id"], made["confirmation"])
        self.assertEqual("running", first["state"])
        self.assertIn(second["state"], ("running", "saved"))
        done = self.wait(made["operation_id"])
        third = self.w.execute(made["operation_id"], made["confirmation"])
        self.assertEqual("saved", done["state"])
        self.assertEqual(done["say"], third["say"])
        self.assertEqual(commits + 1, self.commits())

    def test_a_confirmation_for_a_payload_that_has_changed_is_refused_and_writes_nothing(self):
        made = self.prep("rename", **self.RENAME)
        note = self.work / "Cedar" / "Threads" / "Kickoff" / "Kickoff.md"                 # a link to the thread, saved since the preview
        note.write_text(note.read_text() + "\nAnd [[Pricing]] once more.\n")
        self.save("a new link")
        before, commits = self.state(), self.commits()
        out = self.w.execute(made["operation_id"], made["confirmation"])
        self.assertEqual("refused", out["state"], out)
        self.assertIn("not what the preview showed", out["say"])
        self.assertEqual(before, self.state())
        self.assertEqual(commits, self.commits())
        self.assertTrue((self.work / "Acme Review" / "Threads" / "Pricing").is_dir())
        self.assertEqual("refused", self.w.execute(made["operation_id"], made["confirmation"])["state"])

    def test_a_thread_renamed_since_the_preview_is_not_carried_along(self):
        made = self.prep("rename", **self.RENAME)
        self.scaffold("rename", "--zone", "Work", "--project", "Acme Review", "--thread", "Pricing", "--to", "Terms")
        commits = self.commits()
        out = self.w.execute(made["operation_id"], made["confirmation"])
        self.assertEqual("refused", out["state"], out)
        self.assertIn("no thread called Pricing", out["say"])
        self.assertEqual(commits, self.commits())

    def test_the_same_request_prepared_again_after_a_change_gets_a_new_preview_and_the_old_token_is_dead(self):
        first = self.prep("rename", **self.RENAME)
        note = self.work / "Cedar" / "Threads" / "Kickoff" / "Kickoff.md"
        note.write_text(note.read_text() + "\nAnd [[Pricing]] once more.\n")
        self.save("a new link")
        second = self.prep("rename", **self.RENAME)
        self.assertNotEqual(first["operation_id"], second["operation_id"])
        self.assertNotEqual(first["confirmation"], second["confirmation"])
        self.assertEqual("refused", self.w.status(first["operation_id"])["state"])
        self.assertEqual("refused", self.w.execute(first["operation_id"], first["confirmation"])["state"])
        same = self.prep("rename", **self.RENAME)                                          # and unchanged, it is the same operation
        self.assertEqual(second["operation_id"], same["operation_id"])
        self.assertEqual(second["confirmation"], same["confirmation"])

    def test_a_confirmation_of_another_operation_or_made_up_is_refused_and_the_preview_stays(self):
        a = self.prep("rename", **self.RENAME)
        b = self.prep("rename", project="Cedar", to="Maple")
        commits = self.commits()
        for given in (b["confirmation"], "0" * 20, a["operation_id"], a["confirmation"][:-1] + ("0" if a["confirmation"][-1] != "0" else "1"),
                      "../../x", 12345, {"a": 1}):
            out = self.w.execute(a["operation_id"], given)
            self.assertEqual("not_confirmed", out["error"], given)
        self.assertEqual(commits, self.commits())
        self.assertEqual("prepared", self.w.status(a["operation_id"])["state"])
        self.assertEqual("prepared", self.w.status(b["operation_id"])["state"])
        self.assertEqual("not_confirmed", self.w.execute(b["operation_id"], a["confirmation"])["error"])

    def test_another_grants_confirmation_is_no_good(self):
        a = self.prep("rename", **self.RENAME)
        other = writes.Writes(self.session(readable=("Work",), writable=("Work",), grant_id="grant-two"))
        self.assertEqual("not_found", other.execute(a["operation_id"], a["confirmation"])["error"])
        self.assertEqual("prepared", self.w.status(a["operation_id"])["state"])

    def test_a_rename_and_a_move_are_done_as_the_app_does_them(self):
        for verb, fields in (("rename", dict(project="Acme Review", thread="Pricing", to="Rates")),
                             ("rename", dict(project="Cedar", to="Cedar Works")),
                             ("move", dict(project="Acme Review", thread="Freight", to="Cedar"))):
            with self.subTest(verb=verb, fields=fields):
                twin = self.twin()
                theirs = self.app(twin, dict(verb=verb, zone="Work", **fields))
                made, out = self.run_it(verb, **fields)
                self.assertTrue(theirs["ok"], theirs)
                self.assertEqual("saved", out["state"], out)
                self.assertEqual(theirs["say"], out["say"])
                self.same_commit(twin)
                self.assertEqual(git(twin[0] / "Zones" / "Work", "rev-parse", "--short", "HEAD").strip(), theirs["commit"])      # the page's is short
                self.assertEqual(40, len(out["commit"]))
                self.assertEqual(self.head(), out["commit"])
                self.assertEqual("", git(self.work, "status", "--porcelain").strip())
                git(self.work, "reset", "--hard", "HEAD~1")                                 # for the next one, from the same start

    def test_what_the_app_refuses_is_refused_in_its_words_at_the_preview(self):
        twin = self.twin()
        (self.work / "Cedar" / "Cedar.md").write_text("changed, not saved\n")
        cases = (("rename", dict(project="Acme Review", thread="Pricing", to="Pricing")),
                 ("rename", dict(project="Acme Review", thread="Pricing", to="Pricing 2.0?")),
                 ("rename", dict(project="Acme Review", thread="Nowhere", to="Rates")),
                 ("rename", dict(project="Cedar", to="Cedar Works")),
                 ("move", dict(project="Acme Review", thread="Freight", to="Nowhere")),
                 ("move", dict(project="Acme Review", thread="Freight", to="Cedar")),
                 ("move", dict(project="Acme Review", thread="Freight", to="Acme Review")))
        refused = 0
        for verb, fields in cases:
            with self.subTest(verb=verb, fields=fields):
                shutil.copy2(str(self.work / "Cedar" / "Cedar.md"), str(twin[0] / "Zones" / "Work" / "Cedar" / "Cedar.md"))
                theirs = self.app(twin, dict(verb=verb, zone="Work", **fields))
                ours = self.w.prepare(verb, "Work", **fields)
                self.assertFalse(theirs["ok"], theirs)
                self.assertEqual("not_prepared", ours["error"], ours)
                self.assertEqual(theirs["say"], ours["say"])
                refused += 1
        self.assertEqual(len(cases), refused)
        self.assertEqual([], list(self.w.store.all()))

    def test_a_wrap_that_is_running_on_the_thread_stops_it_at_the_desk_and_nothing_is_written(self):
        made = self.prep("rename", **self.RENAME)
        lock = self.root / "System" / "tools" / "wrap_lock.py"
        lock.write_text("import sys\nprint('wrapping')\n")
        commits = self.commits()
        out = self.w.execute(made["operation_id"], made["confirmation"])
        self.assertEqual("refused", out["state"], out)
        self.assertIn("wrap is running", out["say"])
        self.assertEqual(commits, self.commits())

    def test_a_project_that_has_changes_not_saved_is_refused_when_it_is_confirmed(self):
        made = self.prep("rename", **self.RENAME)
        note = self.work / "Acme Review" / "Threads" / "Pricing" / "Pricing.md"
        note.write_text(note.read_text() + "\nA line typed at the desk.\n")
        commits = self.commits()
        out = self.w.execute(made["operation_id"], made["confirmation"])
        self.assertEqual("refused", out["state"], out)
        self.assertIn("not saved to its history yet", out["say"])
        self.assertEqual(commits, self.commits())
        self.assertIn("A line typed at the desk.", note.read_text())


class TestTheReach(LifeCase):
    def test_a_zone_the_connection_does_not_reach_is_neither_the_source_nor_the_target(self):
        before = self.contents(self.personal)
        for verb, fields in (("rename", dict(project="Birch Entry", thread="Market Sizing", to="Sizing")),
                             ("rename", dict(project="Birch Entry", to="Birch Works")),
                             ("move", dict(project="Birch Entry", thread="Market Sizing", to="Cedar")),
                             ("new-project", dict(name="Maple")), ("new-thread", dict(project="Birch Entry", name="Budget")),
                             ("undo", dict(commit="abcdef1")), ("check-name", dict(kind="project", name="Maple"))):
            for zone in ("Personal", "personal"):
                with self.subTest(verb=verb, zone=zone):
                    out = self.w.prepare(verb, zone, **fields)
                    self.assertEqual(common.NEW_REACH, out["error"], out)
                    text = json.dumps(out)
                    for name in OTHER_ZONE:
                        self.assertNotIn(name, text)
        self.assertEqual(before, self.contents(self.personal))
        self.assertEqual([], list(self.w.store.all()))

    def test_a_move_into_a_project_of_a_zone_that_is_not_reached_says_what_it_says_for_a_name_that_is_nowhere(self):
        a = self.w.prepare("move", "Work", project="Acme Review", thread="Pricing", to="Birch Entry")
        b = self.w.prepare("move", "Work", project="Acme Review", thread="Pricing", to="Nowhere Entry")
        self.assertEqual("not_prepared", a["error"])
        self.assertEqual(a["say"].replace("Birch Entry", "X"), b["say"].replace("Nowhere Entry", "X"))
        for name in ("Personal", "Market Sizing", "BIRCHTHREAD71", "birch"):
            self.assertNotIn(name, json.dumps(a))

    def test_the_reach_changed_after_the_preview_stops_the_confirmation(self):
        made = self.prep("rename", project="Acme Review", thread="Pricing", to="Rates")
        self.s.change_reach(writable=())
        commits = self.commits()
        out = self.w.execute(made["operation_id"], made["confirmation"])
        self.assertEqual(common.NEW_REACH, out["error"])
        self.assertEqual(commits, self.commits())

    def test_a_read_only_grant_prepares_none_of_them(self):
        w = writes.Writes(self.session(readable=("Work",), writable=()))
        for verb, fields in (("check-name", dict(kind="project", name="Maple")), ("new-project", dict(name="Maple")),
                             ("rename", dict(project="Cedar", to="Maple")), ("undo", dict(commit="abcdef1"))):
            self.assertEqual(common.NEW_REACH, w.prepare(verb, "Work", **fields)["error"], verb)

    def test_no_name_is_a_path(self):
        for bad in ("../Personal", "..", ".", "/etc", "/Users/x/Zones/Personal", "a/b", "a\\b", ".hidden", "_x", "~", "Threads", "x\ny", "x\0y", " x", "x ",
                    "", "a" * 121, 7, ["x"]):
            for verb, fields in (("rename", dict(project="Cedar", to=bad)), ("rename", dict(project=bad, to="Maple")),
                                 ("move", dict(project="Acme Review", thread=bad, to="Cedar")), ("move", dict(project="Acme Review", thread="Pricing", to=bad)),
                                 ("new-project", dict(name=bad)), ("new-thread", dict(project="Cedar", name=bad)),
                                 ("new-project", dict(name="Maple", thread=bad)), ("check-name", dict(kind="project", name=bad))):
                if bad == "":
                    continue                                                     # an empty field is a field that was not sent: "needs"
                with self.subTest(verb=verb, bad=bad):
                    out = self.w.prepare(verb, "Work", **fields)
                    self.assertEqual("not_prepared", out["error"], (verb, bad, out))
        self.assertEqual([], list(self.w.store.all()))

    def test_a_link_in_the_zone_that_leads_elsewhere_is_never_written_through(self):
        outside = self.personal / "Birch Entry"
        before = self.contents(self.personal)
        (self.work / "Linked").symlink_to(outside)                                  # a project that is a link to another zone's
        (self.work / "Cedar" / "Threads" / "Ghost").symlink_to(outside / "Threads" / "Market Sizing")
        self.save("two links")
        for verb, fields in (("rename", dict(project="Linked", to="Maple")), ("rename", dict(project="Cedar", thread="Ghost", to="Maple")),
                             ("move", dict(project="Cedar", thread="Ghost", to="Acme Review")), ("move", dict(project="Cedar", thread="Kickoff", to="Linked")),
                             ("new-thread", dict(project="Linked", name="Budget")), ("check-name", dict(kind="thread", project="Linked", name="Budget"))):
            with self.subTest(verb=verb, fields=fields):
                out = self.w.prepare(verb, "Work", **fields)
                self.assertEqual("not_prepared", out["error"], out)
                self.assertEqual(lifecycle.NOT_A_PLACE, out["say"])
        self.assertEqual(before, self.contents(self.personal))
        self.assertEqual([], list(self.w.store.all()))

    def test_a_note_that_is_a_link_is_refused_and_so_is_a_link_made_after_the_preview(self):
        made = self.prep("rename", project="Acme Review", thread="Pricing", to="Rates")
        note = self.work / "Acme Review" / "Threads" / "Pricing" / "Pricing.md"
        target = self.personal / "Birch Entry" / "Birch Entry.md"
        original = target.read_text()
        note.unlink()
        note.symlink_to(target)                                                      # the thread's note, now a link out of the zone
        commits = self.commits()
        out = self.w.execute(made["operation_id"], made["confirmation"])
        self.assertEqual("refused", out["state"], out)
        self.assertEqual(lifecycle.NOT_A_PLACE, out["say"])
        self.assertEqual(commits, self.commits())
        self.assertEqual(original, target.read_text())
        self.assertEqual("not_prepared", self.w.prepare("rename", "Work", project="Acme Review", thread="Pricing", to="Terms")["error"])

    def test_a_zone_that_is_a_link_is_not_a_zone_of_the_connection(self):
        (self.root / "Zones" / "Linked").symlink_to(self.personal)
        w = writes.Writes(self.session(readable=("Work", "Linked"), writable=("Work", "Linked")))
        self.assertEqual(lifecycle.NOT_A_PLACE, w.prepare("rename", "Linked", project="Birch Entry", to="Maple")["say"])
        self.assertEqual("not_prepared", w.prepare("new-project", "Linked", name="Maple")["error"])


class TestWhatAPreviewHoldsStaysInTheReach(LifeCase):
    """A preview carries lines of the zone's notes: it goes only to a grant that reads and writes the zone, and stops with the reach."""

    NOTE_LINES = ("Send the revised terms", "Rates", "[[Pricing]]", "Todo.md", "Pricing.md", "Acme Review/Threads")

    def test_a_grant_that_may_write_a_zone_and_not_read_it_gets_no_preview_of_a_rename_or_a_move(self):
        w = writes.Writes(self.session(readable=("Knowledge", "docs"), writable=("Work",)))
        for verb, fields in (("rename", dict(project="Acme Review", thread="Pricing", to="Rates")),
                             ("move", dict(project="Acme Review", thread="Freight", to="Cedar")),
                             ("rename", dict(project="Cedar", to="Cedar Works"))):
            out = w.prepare(verb, "Work", **fields)
            self.assertEqual("not_prepared", out["error"], out)
            self.assertEqual(lifecycle.NEEDS_READ, out["say"])
            text = json.dumps(out)
            for line in self.NOTE_LINES:
                self.assertNotIn(line, text)
        for kind, fields in (("rename", dict(project="Acme Review", thread="Pricing", to="Pricing")),
                             ("move", dict(project="Acme Review", thread="Pricing", to="Cedar"))):     # the check says the same, and no more
            out = w.prepare("check-name", "Work", kind=kind, **fields)
            self.assertEqual("not_prepared", out["error"], out)
            self.assertEqual(lifecycle.NEEDS_READ, out["say"])
        self.assertEqual([], list(w.store.all()))
        self.assertEqual("prepared", w.prepare("new-thread", "Work", project="Cedar", name="Budget")["state"])   # the others need no read

    def test_a_read_that_goes_after_the_preview_stops_it_and_the_confirmation(self):
        made = self.prep("rename", project="Acme Review", thread="Pricing", to="Rates")
        self.assertIn("preview", made)
        self.s.change_reach(readable=("Knowledge", "docs"))
        for out in (self.w.status(made["operation_id"]), self.w.prepare("rename", "Work", operation_id=made["operation_id"],
                                                                         project="Acme Review", thread="Pricing", to="Rates")):
            self.assertNotIn("preview", out)
            self.assertNotIn("confirmation", out)
            self.assertNotIn("would", out)
            for line in self.NOTE_LINES[:3] + ("3 notes",):
                self.assertNotIn(line, json.dumps(out).replace("Rates", "").replace("Pricing", ""))
        commits = self.commits()
        out = self.w.execute(made["operation_id"], made["confirmation"])
        self.assertEqual("refused", out["state"], out)
        self.assertEqual(commits, self.commits())

    def test_a_write_that_goes_after_the_preview_leaves_no_preview_to_read_back(self):
        made = self.prep("rename", project="Acme Review", thread="Pricing", to="Rates")
        self.s.change_reach(writable=())
        out = self.w.status(made["operation_id"])
        self.assertNotIn("preview", out)
        self.assertNotIn("confirmation", out)


class TestUndo(LifeCase):
    def test_undo_after_a_rename_puts_the_old_paths_and_links_back_in_one_commit(self):
        before = git(self.work, "ls-files", "-s").strip()
        todo = (self.work / "Todo.md").read_text()
        commits = self.commits()
        self.run_it("rename", project="Acme Review", thread="Pricing", to="Rates")
        self.assertEqual(commits + 1, self.commits())
        self.assertNotIn("[[Pricing]]", (self.work / "Todo.md").read_text())
        receipt = [r for r in self.w.store.all() if r["verb"] == "rename"][0]["receipt"]
        made, out = self.run_it("undo", commit=receipt["commit"])
        self.assertEqual("saved", out["state"], out)
        self.assertEqual(commits + 2, self.commits())
        self.assertEqual(before, git(self.work, "ls-files", "-s").strip())
        self.assertEqual(todo, (self.work / "Todo.md").read_text())
        self.assertTrue((self.work / "Acme Review" / "Threads" / "Pricing" / "Pricing.md").is_file())
        self.assertFalse((self.work / "Acme Review" / "Threads" / "Rates").exists())
        self.assertEqual("", git(self.work, "status", "--porcelain").strip())

    def test_undo_takes_back_a_move_a_new_project_and_a_new_thread(self):
        for verb, fields in (("move", dict(project="Acme Review", thread="Freight", to="Cedar")),
                             ("new-project", dict(name="Maple", thread="Budget")), ("new-thread", dict(project="Cedar", name="Budget"))):
            with self.subTest(verb=verb):
                tree = git(self.work, "rev-parse", "HEAD^{tree}").strip()
                made, out = self.run_it(verb, **fields)
                self.assertEqual("saved", out["state"], out)
                again, undone = self.run_it("undo", commit=out["commit"])
                self.assertEqual("saved", undone["state"], undone)
                self.assertEqual(tree, git(self.work, "rev-parse", "HEAD^{tree}").strip())

    def test_undo_is_done_as_the_app_does_it(self):
        self.run_it("rename", project="Acme Review", thread="Pricing", to="Rates")
        commit = git(self.work, "rev-parse", "--short", "HEAD").strip()
        twin = self.twin()
        theirs = self.app(twin, dict(verb="undo", zone="Work", commit=commit))
        made, out = self.run_it("undo", commit=commit)
        self.assertTrue(theirs["ok"], theirs)
        self.assertEqual("saved", out["state"], out)
        self.assertEqual(theirs["say"], out["say"])
        self.same_commit(twin)

    def test_only_what_this_connection_made_can_be_undone_from_here(self):
        self.save("a commit the connection did not make")
        head = git(self.work, "rev-parse", "--short", "HEAD").strip()
        out = self.w.prepare("undo", "Work", commit=head)
        self.assertEqual("not_prepared", out["error"], out)
        self.assertEqual(lifecycle.NOT_YOURS, out["say"])
        pa = load_page_action(self.root)               # a rename made at the desk, through the App: not this connection's receipt
        self.app((self.root, pa), dict(verb="rename", zone="Work", project="Cedar", to="Cedar Works"))
        desk = git(self.work, "rev-parse", "--short", "HEAD").strip()
        self.assertEqual(lifecycle.NOT_YOURS, self.w.prepare("undo", "Work", commit=desk)["say"])
        mine = self.run_it("rename", project="Acme Review", thread="Pricing", to="Rates")[1]
        other = writes.Writes(self.session(readable=("Work",), writable=("Work",), grant_id="grant-two"))
        self.assertEqual(lifecycle.NOT_YOURS, other.prepare("undo", "Work", commit=mine["commit"])["say"])
        self.assertEqual("prepared", self.w.prepare("undo", "Work", commit=mine["commit"])["state"])
        for verb in ("park", "todo-add"):                     # a receipt of a verb that is not one of the four is not an undo's
            self.run_it(verb, **(dict(project="Cedar") if verb == "park" else dict(text="Call Dana")))
            last = [r for r in self.w.store.all() if r["verb"] == verb][0]["receipt"].get("commit")
            if last:
                self.assertEqual(lifecycle.NOT_YOURS, self.w.prepare("undo", "Work", commit=last)["say"])

    def test_it_is_refused_once_something_else_was_saved_after_it_and_says_so_in_the_apps_words(self):
        self.run_it("rename", project="Acme Review", thread="Pricing", to="Rates")
        commit = [r for r in self.w.store.all() if r["verb"] == "rename"][0]["receipt"]["commit"]
        todo = self.work / "Todo.md"
        todo.write_text(todo.read_text() + "- [ ] One more line\n")
        self.save("later")
        made = self.prep("undo", commit=commit)
        self.w.execute(made["operation_id"])
        out = self.wait(made["operation_id"])
        self.assertEqual("refused", out["state"], out)
        self.assertIn("is no longer the last commit", out["say"])

    def test_the_receipt_holds_the_whole_id_and_a_forged_long_one_is_refused(self):
        self.run_it("rename", project="Acme Review", thread="Pricing", to="Rates")
        commit = [r for r in self.w.store.all() if r["verb"] == "rename"][0]["receipt"]["commit"]
        self.assertEqual(40, len(commit))
        forged = commit[:7] + "0" * 33
        self.assertEqual(lifecycle.NOT_YOURS, self.w.prepare("undo", "Work", commit=forged)["say"])
        self.assertEqual("prepared", self.w.prepare("undo", "Work", commit=commit[:7])["state"])
        self.assertEqual("prepared", self.w.prepare("undo", "Work", commit=commit)["state"])

    def test_a_commit_that_is_not_a_commit_is_not_prepared(self):
        for bad in ("zzzzzzz", "abc", "HEAD", "HEAD~1", "--all", "abcdef1; rm", "a" * 41):
            self.assertEqual("not_prepared", self.w.prepare("undo", "Work", commit=bad)["error"], bad)


class TestOneOperationOneCommit(LifeCase):
    def test_a_retry_with_the_same_operation_id_returns_the_first_receipt_and_makes_one_commit(self):
        for verb, fields in (("new-project", dict(name="Maple", thread="Budget")), ("new-thread", dict(project="Cedar", name="Budget")),
                             ("rename", dict(project="Acme Review", thread="Pricing", to="Rates")),
                             ("move", dict(project="Cedar", thread="Kickoff", to="Acme Review"))):
            with self.subTest(verb=verb):
                commits = self.commits()
                made = self.prep(verb, **fields)
                op, token = made["operation_id"], made.get("confirmation")
                self.w.execute(op, token)
                again = self.w.execute(op, token)                              # during it
                self.assertIn(again["state"], ("running", "saved"))
                done = self.wait(op)
                self.assertEqual("saved", done["state"], done)
                self.assertEqual(done["say"], self.w.execute(op, token)["say"])      # after it
                restarted = writes.Writes(self.s, store=writes.Store(self.w.store.root.parent))
                self.assertEqual(done["say"], restarted.execute(op, token)["say"])   # across a restart of the service
                self.assertEqual(done["say"], restarted.status(op)["say"])
                back = restarted.prepare(verb, "Work", operation_id=op, **fields)    # and the retry of the prepare, after the change was made
                self.assertEqual(op, back["operation_id"])
                self.assertEqual("saved", back["state"])
                self.assertEqual(done["commit"], back["commit"])
                time.sleep(0.3)
                self.assertEqual(commits + 1, self.commits())

    def test_the_same_request_with_a_new_operation_id_is_a_new_operation_the_app_would_refuse_as_done(self):
        self.run_it("new-thread", project="Cedar", name="Budget")
        out = self.w.prepare("new-thread", "Work", project="Cedar", name="Budget")
        self.assertEqual("not_prepared", out["error"])
        self.assertIn("already has a thread called Budget", out["say"])

    def test_an_operation_id_of_another_request_is_refused(self):
        made = self.prep("new-thread", project="Cedar", name="Budget")
        out = self.w.prepare("new-thread", "Work", project="Cedar", name="Other", operation_id=made["operation_id"])
        self.assertEqual("changed", out["error"])
        self.assertEqual("not_found", self.w.prepare("new-thread", "Work", project="Cedar", name="Budget", operation_id="0" * 16)["error"])

    def test_a_worker_that_stopped_after_the_commit_is_settled_from_git_as_saved(self):
        made, out = self.run_it("rename", project="Acme Review", thread="Pricing", to="Rates")
        rec = self.w.store.read(made["operation_id"])
        rec.update({"state": "running", "started": time.time() - 600, "receipt": None, "finished": None})
        self.w.store.write(made["operation_id"], rec)
        commits = self.commits()
        got = self.w.status(made["operation_id"])
        self.assertEqual("saved", got["state"], got)
        self.assertTrue(got["commit"].startswith(out["commit"]), (out["commit"], got["commit"]))
        self.assertEqual(got["say"], self.w.execute(made["operation_id"], made["confirmation"])["say"])
        self.assertEqual(commits, self.commits())

    def test_a_worker_that_stopped_before_the_commit_is_settled_from_git_as_not_saved_and_never_run_again(self):
        made = self.prep("rename", project="Acme Review", thread="Pricing", to="Rates")
        spec = importlib.util.spec_from_file_location("ops_life", str(self.root / "System" / "tools" / "operations.py"))
        ops = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ops)
        req = {"verb": "rename", "zone": "Work", "op": made["operation_id"], "project": "Acme Review", "thread": "Pricing", "to": "Rates"}
        ops.prepare(self.work, "rename", req, op=made["operation_id"], via="remote", workspace=str(self.root))     # the record, and no commit
        rec = self.w.store.read(made["operation_id"])
        rec.update({"state": "running", "started": time.time() - 600})
        self.w.store.write(made["operation_id"], rec)
        commits = self.commits()
        got = self.w.status(made["operation_id"])
        self.assertIn(got["state"], ("refused", "unknown"), got)
        self.assertFalse(got["saved"])
        self.w.execute(made["operation_id"], made["confirmation"])
        time.sleep(0.5)
        self.assertEqual(commits, self.commits())


class TestWhatIsSentAndKept(LifeCase):
    def stand_in(self):
        fake = self.root / "System" / "status" / "page_action.py"
        seen = Path(self._tmp.name) / "life-seen.jsonl"
        # Only a run as a program is a request. The status build that a scaffold run in set-up leaves behind imports this file a few seconds
        # later (on a slow machine, in the middle of a test), and an import is no request: it must not be counted as one.
        fake.write_text(
            "import json, sys\n"
            "if __name__ == '__main__':\n"
            "    open(%r, 'a').write(json.dumps({'argv': sys.argv[1:], 'stdin': sys.stdin.read()}) + '\\n')\n"
            "    print(json.dumps({'ok': True, 'say': 'Done.', 'plan': {'paths': [], 'count': 0, 'files': [], 'digest': 'd1'}}))\n" % str(seen))
        return seen

    def test_the_request_is_built_from_the_fields_of_the_verb_and_names_the_remote_caller(self):
        seen = self.stand_in()
        made = self.prep("rename", project="Acme Review", thread="Pricing", to="Rates")
        self.w.execute(made["operation_id"], made["confirmation"])
        self.wait(made["operation_id"])
        rows = [json.loads(line) for line in seen.read_text().splitlines()]
        # The check with its plan, the plan again at the confirmation, and the change. A check is a read and may be asked more than once;
        # the change is one request, and it is the only one that carries an operation id.
        self.assertGreaterEqual(len(rows), 3)
        for row in rows:
            self.assertEqual("remote", row["argv"][row["argv"].index("--via") + 1])
        sent = [json.loads(r["stdin"]) for r in rows]
        changes = [r for r in sent if "op" in r]
        checks = [r for r in sent if "op" not in r]
        self.assertEqual(1, len(changes))
        self.assertGreaterEqual(len(checks), 2)
        want = dict(verb="check-name", zone="Work", kind="rename", project="Acme Review", thread="Pricing", to="Rates", plan=True)
        for check in checks:
            self.assertEqual(want, check)
        change = changes[0]
        self.assertEqual("rename", change["verb"])
        self.assertEqual({"verb", "zone", "op", "project", "thread", "to"}, set(change))
        self.assertEqual(made["operation_id"], change["op"])
        self.assertEqual(sent[-1], change)                                   # and it comes last
        for row in rows:
            for never in ("confirm", "destination", '"key"', '"file"', "heading", "new_party"):
                self.assertNotIn(never, row["stdin"])

    def test_the_words_of_the_preview_are_not_kept_after_the_receipt(self):
        made, out = self.run_it("rename", project="Acme Review", thread="Pricing", to="Rates")
        kept = json.dumps(self.w.store.read(made["operation_id"]))
        for gone in ("Pricing", "Rates", "_preview", "_plan", "edits"):
            self.assertNotIn(gone, kept.replace("Renamed Pricing to Rates.", ""), gone)
        self.assertEqual("saved", self.w.store.read(made["operation_id"])["state"])

    def test_the_service_log_holds_no_text_of_a_lifecycle_request(self):
        with self.assertLogs("garrick.remote.tools", level="INFO") as logs:
            from mcp.server.mcpserver import MCPServer
            from tools import register
            server = MCPServer("t")
            register(server, lambda ctx: self.s)

            def call(name, args):
                return json.loads(asyncio.run(server.call_tool(name, args)).content[0].text)

            check = call("prepare", {"verb": "check-name", "zone": "Work", "kind": "project", "name": "LOGSECRETONE"})
            self.assertEqual("checked", check["state"], check)
            made = call("prepare", {"verb": "rename", "zone": "Work", "project": "Cedar", "to": "LOGSECRETTWO"})
            self.assertEqual("prepared", made["state"], made)
            call("execute", {"operation_id": made["operation_id"], "confirmation": made["confirmation"]})
            self.wait(made["operation_id"])
            call("status", {"operation_id": made["operation_id"]})
            call("prepare", {"verb": "new-project", "zone": "Work", "name": "LOGSECRETTHREE", "party": "nobody"})
        text = "\n".join(logs.output)
        for secret in ("LOGSECRET", "Cedar", "nobody"):
            self.assertNotIn(secret, text)
        self.assertIn("tool=prepare", text)

    def test_the_tools_take_the_new_fields_and_the_confirmation_and_no_other_way_to_say_yes(self):
        from mcp.server.mcpserver import MCPServer
        from tools import register
        server = MCPServer("t")
        register(server, lambda ctx: self.s)
        listed = {t.name: t for t in asyncio.run(server.list_tools())}
        self.assertTrue({"name", "to", "party", "kind", "commit"} <= set(listed["prepare"].input_schema["properties"]))
        self.assertIn("confirmation", set(listed["execute"].input_schema["properties"]))
        self.assertFalse(set(listed["prepare"].input_schema["properties"]) & {"confirm", "confirmation", "plan", "heading", "new_party"})
        self.assertFalse(set(listed["status"].input_schema["properties"]) & {"confirm", "confirmation"})

    def test_the_manifest_serves_the_six_and_keeps_delete_for_the_owner(self):
        data = manifest.load()
        served = manifest.served_verbs(data)
        for verb in lifecycle.VERBS:
            self.assertIn(verb, served)
        row = manifest.row_for(data, "delete")
        self.assertEqual("owner-approval", row["disposition"])
        self.assertIn("approval at the Mac", row["reason"])
        self.assertEqual("not_available", self.w.prepare("delete", "Work", project="Cedar")["error"])
        self.assertIn("approves", self.w.prepare("delete", "Work", project="Cedar")["say"])
        self.assertEqual("not_available", self.w.prepare("layout", "Work", project="Cedar")["error"])


if __name__ == "__main__":
    unittest.main()
