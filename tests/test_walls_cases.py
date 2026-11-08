"""The cases table, run against each enforcement point on a fixture workspace.

    cd tests && python3 -m unittest test_walls_cases

`walls/cases.md` is the one table of what the points must answer. Its first
table is run against decide() in test_decide; its third is run here, row by
row, against the pre-commit check, Ask, intake and the scaffold tool. A row of
the table with no handler here fails the test, so a new case is run before it
is merged. Recall is not on `main`: its rows run against decide() alone.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import HAVE_GIT, commit_all, git, project_hub, write  # noqa: E402
from walls_fixture import build  # noqa: E402

import check  # noqa: E402
import garrick_lib as lib  # noqa: E402
import scaffold  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
CASES = Path(__file__).resolve().parent / "walls" / "cases.md"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


intake = load("garrick_intake_cases", REPO / "template" / "System" / "skills" / "intake" / "intake.py")
ask_scope = load("garrick_ask_scope_cases", REPO / "extras" / "status" / "ask_scope.py")


STAMPED = (b"X-Garrick-Parties: acme birch\nFrom: Dana <dana@acmecorp.example>\nTo: Theo <theo@birchco.example>\n"
           b"Subject: Hi\nDate: Tue, 10 Mar 2026 10:00:00 +0000\nMessage-ID: <1@x>\n\nA mail body naming both firms.\n")


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class EnforcementPoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name).resolve() / "Workspace"
        build(cls.root)
        cls.work = cls.root / "Zones" / "Work"
        shutil.rmtree(cls.work / ".git", ignore_errors=True)
        git(cls.work, "init", "-q")
        cls.env = mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
        cls.env.start()
        commit_all(cls.work, "start")
        cls.ctx = lib.load_context(cls.root)
        cls.lib = ask_scope.lib(REPO)

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        cls._tmp.cleanup()

    # -- the points -----------------------------------------------------------

    def note(self, project, thread, text):
        path = self.work / project / "Threads" / thread / "CaseNote.md"
        write(path, text)
        self.addCleanup(lambda: path.exists() and path.unlink())
        return path

    def check_note(self, project, thread, text):
        path = self.note(project, thread, text)
        where = path.relative_to(self.root).as_posix()
        found = [f for f in check.run_checks(self.root, walls_only=True) if f.path == where]
        return "refused" if any(f.severity == "error" for f in found) else "permitted"

    def staged(self, path, text):
        write(path, text)
        self.addCleanup(lambda: path.exists() and path.unlink())
        git(self.work, "add", "-A")
        self.addCleanup(lambda: git(self.work, "reset", "-q"))
        where = path.relative_to(self.root).as_posix()
        found = [f for f in check.run_checks(self.root, staged=self.work) if f.path == where]
        return "refused" if any(f.severity == "error" for f in found) else "permitted"

    def asked(self, held, parties_of, extra=None):
        """Ask: may a process holding `held` be given the record of a place or page?"""
        record = {"parties": sorted(parties_of)}
        if extra:
            record.update(extra)
        chosen, _ = ask_scope.pick([record], set(held), self.ctx, self.lib)
        return "permitted" if chosen else "refused"

    def place(self, project, thread):
        return ask_scope.place_parties(self.root, "Work", project, thread, self.lib)

    def inbox_item(self):
        path = self.work / "Inbox" / "case-item.md"
        write(path, "# Item\n")
        self.addCleanup(lambda: path.exists() and path.unlink())
        return path

    def filed(self, project, tags):
        try:
            dest = intake.file_to_project(self.root, self.inbox_item(), "Zones/Work/" + project, tags)
        except intake.Refusal:
            return "refused"
        self.addCleanup(lambda: dest.exists() and dest.unlink())
        return "permitted"

    def utf16_note(self):
        path = self.work / "Northwind" / "Threads" / "Pricing" / "utf16.md"
        path.write_bytes("Ask Theo Marsh".encode("utf-16"))
        git(self.work, "add", "-A")
        found = check.run_checks(self.root, staged=self.work)
        return "refused" if any(f.severity == "error" and f.path.endswith("utf16.md") for f in found) else "permitted"

    def renamed_folder(self):
        import os
        os.rename(self.work / "Harbour", self.work / "Harbour-tmp")
        os.rename(self.work / "Harbour-tmp", self.work / "harbour")
        self.addCleanup(lambda: (self.work / "harbour").exists() and os.rename(self.work / "harbour", self.work / "Harbour-b")
                        and os.rename(self.work / "Harbour-b", self.work / "Harbour"))
        write(self.work / "harbour" / "Threads" / "Sizing" / "Leak.md", "# n\n\nAsk Dana Whitlock of Acme Corp.\n")
        git(self.work, "add", "-A")
        found = check.run_checks(self.root, staged=self.work)
        return "refused" if any(f.severity == "error" and f.path.lower().endswith("leak.md") for f in found) else "permitted"

    def staged_bytes(self, rel, data):
        path = self.work / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        git(self.work, "add", "-A")
        found = check.run_checks(self.root, staged=self.work)
        return "refused" if any(f.severity == "error" and f.path.endswith(Path(rel).name) for f in found) else "permitted"

    def thread_parties(self):
        note = self.work / "Northwind" / "Threads" / "Pricing" / "Pricing.md"
        note.write_text(note.read_text(encoding="utf-8").replace("party: acme", "parties: [acme]"), encoding="utf-8")
        git(self.work, "add", "-A")
        found = check.run_checks(self.root, staged=self.work)
        return "refused" if any(f.severity == "error" and f.path.endswith("Pricing.md") for f in found) else "permitted"

    def knowledge_party_key(self):
        page = self.root / "Wikis" / "Knowledge" / "wiki" / "concepts" / "case-key.md"
        write(page, "---\ntitle: K\nParties: [acme]\n---\n\n# K\n")
        self.addCleanup(lambda: page.exists() and page.unlink())
        labels = lib.labels(self.root, page, self.ctx)
        return "refused" if lib.decide({"birch"}, labels, "read", self.ctx) == "deny" else "permitted"

    def reserved_row(self, tag):
        context = self.root / "System" / "context.md"
        before = context.read_text(encoding="utf-8")
        context.write_text(before.replace("| Cedar Ltd |", "| Nobody | None | Work | `%s` | yes | |\n| Cedar Ltd |" % tag), encoding="utf-8")
        try:
            write(self.work / "Northwind" / "Threads" / "Pricing" / "CaseNote.md", "# N\n\nPlain.\n")
            git(self.work, "add", "-A")
            found = check.run_checks(self.root, staged=self.work)
            return "refused" if any(f.severity == "error" and f.path.endswith("context.md") for f in found) else "permitted"
        finally:
            context.write_text(before, encoding="utf-8")

    def hats_refused(self):
        try:
            scaffold.check_party(self.root, "lumen,lumen-adv", "Work")
        except scaffold.Refusal:
            return "refused"
        return "permitted"

    def scaffold_none(self):
        args = type("A", (), dict(name="None", zone="Work", what="x", also=None, walled=False, open=False,
                                  check=False, spoken=None))()
        try:
            scaffold.cmd_party(self.root, args, "2026-11-06")
        except scaffold.Refusal:
            return "refused"
        return "permitted"

    def binary(self, project):
        path = self.work / project / "blob.bin"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x00\x01plain weather\x00")
        self.addCleanup(lambda: path.exists() and path.unlink())
        git(self.work, "add", "-A")
        self.addCleanup(lambda: git(self.work, "reset", "-q"))
        found = check.run_checks(self.root, staged=self.work)
        return "refused" if any(f.severity == "error" and f.path.endswith("blob.bin") for f in found) else "permitted"

    def mail(self, **kw):
        m = lib.parse_mail_bytes(b"", ".txt")
        for key, addrs in kw.items():
            m[key] = [("", a) for a in addrs]
        return intake.suggest(self.ctx, "Work", m)

    def restore(self):
        git(self.work, "reset", "-q", "--hard", "HEAD")
        git(self.work, "clean", "-fdq")

    def flip_to_open(self):
        self.addCleanup(self.restore)
        for rel in ("Northwind/Northwind.md", "Northwind/Threads/Pricing/Pricing.md"):
            path = self.work / rel
            path.write_text(path.read_text(encoding="utf-8").replace("party: acme", "party: cedar"), encoding="utf-8")
        git(self.work, "add", "-A")
        found = check.run_checks(self.root, staged=self.work)
        return "refused" if any(f.severity == "error" and f.path.endswith("Deal.md") for f in found) else "permitted"

    def hub_party_none(self):
        self.addCleanup(self.restore)
        path = self.work / "Orchard" / "Orchard.md"
        path.write_text(path.read_text(encoding="utf-8").replace("status: active", "party: none\nstatus: active"), encoding="utf-8")
        return self.staged(self.work / "Orchard" / "Threads" / "Drafts" / "CaseNote.md", "# N\n\nPlain.\n")

    def mail_filed(self, text, **kw):
        path = self.work / "Inbox" / "case.eml"
        write(path, text)
        self.addCleanup(lambda: path.exists() and path.unlink())
        try:
            dest = intake.file_to_project(self.root, path, "Zones/Work/Northwind", ["acme"], as_material=True, **kw)
        except intake.Confirm:
            return "asked"
        except intake.Refusal:
            return "refused"
        self.addCleanup(lambda: dest.exists() and dest.unlink())
        return "permitted"

    def nurture_from(self, source):
        import nurture
        ctx = nurture.Ctx(self.root)
        return "refused" if nurture.across_wall(ctx, source, "Zones/Work/Northwind/Threads/Pricing/Notes.md") else "permitted"

    def knowledge_link(self):
        page = self.root / "Wikis" / "Knowledge" / "wiki" / "concepts" / "case-link.md"
        write(page, "---\ntitle: K\nParties: [acme]\n---\n\n# K\n")
        self.addCleanup(lambda: page.exists() and page.unlink())
        return self.check_note("Northwind", "Pricing", "# N\n\nSee [[case-link]].\n")

    def nurture_across(self):
        import nurture
        ctx = nurture.Ctx(self.root)
        return "refused" if nurture.across_wall(ctx, "Zones/Work/Orchard/x.md",
                                                "Zones/Work/Northwind/Threads/Pricing/Notes.md") else "permitted"

    # -- one handler per row ---------------------------------------------------

    def handlers(self):
        recall = lambda scope, labels: "Recall's" if lib.decide(scope, labels, "read", self.ctx) == "deny" else "WRONG"  # noqa: E731
        return {
            "e01": lambda: self.check_note("Northwind", "Pricing", "# N\n\nSee [[260312-birch-kickoff]].\n"),
            "e02": lambda: self.check_note("Northwind", "Pricing", "# N\n\nAsk Theo Marsh.\n"),
            "e03": lambda: self.check_note("Northwind", "Pricing", "# N\n\nSee [[260310-acme-kickoff]].\n"),
            "e04": lambda: self.staged(self.work / "Orchard" / "Threads" / "Drafts" / "CaseNote.md",
                                       "# N\n\nSee [[260310-acme-kickoff]].\n"),
            "e05": lambda: self.staged(self.work / "Orchard" / "Threads" / "Drafts" / "CaseNote.md", "# N\n\nPlain.\n"),
            "e06": lambda: self.check_note("Reed", "Notes", "# N\n\nAsk Dana Whitlock.\n"),
            "e07": lambda: self.check_note("Reed", "Notes", "# N\n\nSee [[resilience]].\n"),
            "e08": lambda: self.check_note("Reed", "Notes", "# N\n\nSee [[260310-acme-kickoff]].\n"),
            "e09": lambda: self.staged(self.work / "Todo.md", "# Work: open actions\n\n## Inbox\n\n- [ ] call Jo\n\n## Done\n"),
            "e10": lambda: self.asked({"acme"}, self.place("Harbour", "Sizing")),
            "e11": lambda: self.asked({"acme"}, self.place("Northwind", "Pricing")),
            "e12": lambda: self.asked({"acme"}, self.place("Orchard", "Drafts")),
            "e13": lambda: self.asked({"acme"}, ask_scope.page_parties(
                lib.parse_frontmatter(self.root / "Wikis" / "Meetings" / "wiki" / "sources" / "260315-split.md"),
                self.ctx, self.lib)),
            "e14": lambda: self.asked({"birch"}, self.place("Reed", "Notes")),
            "e15": lambda: self.filed("Northwind", ["birch"]),
            "e16": lambda: "asked" if self.mail(**{"from": ["kai@birchco.example"], "cc": ["dana@acmecorp.example"],
                                                  "to": ["jo@example.invalid"]})["confirm"] else "permitted",
            "e17": lambda: "asked" if self.mail(**{"from": ["jo+lumen@elsewhere.example"]})["confirm"] else "permitted",
            "e18": lambda: self.filed("Orchard", ["acme"]),
            "e19": lambda: "refused" if scaffold.wall_between(self.ctx, {"birch"}, {"acme"}) else "permitted",
            "e24": self.flip_to_open,
            "e25": lambda: self.binary("Orchard"),
            "e26": lambda: self.staged(self.work / "Northwind" / "tool.py", "# Ask Theo Marsh at Birch & Co\n"),
            "e27": lambda: self.check_note("Northwind", "Pricing", "# N\n\nSee [[Todo]].\n"),
            "e28": lambda: self.check_note("Northwind", "Pricing", "# N\n\nSee [[260319-orphan-call]].\n"),
            "e29": lambda: self.check_note("Northwind", "Pricing", "# N\n\nSee [[260315-split]].\n"),
            "e30": lambda: self.asked(set(), self.place("Northwind", "Pricing")),
            "e31": lambda: self.asked({"none"}, self.place("Northwind", "Pricing")),
            "e32": lambda: self.mail_filed("From: Kai <kai@cedarltd.example>\nSubject: Hi\n\nHello.\n"),
            "e33": lambda: self.mail_filed("X-Garrick-Parties: acme\nFrom: Kai <kai@birchco.example>\nSubject: Hi\n\nHello.\n",
                                           confirmed=True),
            "e35": lambda: self.check_note("Reed", "Notes", "# N\n\nAsk Da\u200bna Whitlock.\n"),
            "e36": self.nurture_across,
            "e37": self.hub_party_none,
            "e38": lambda: (write(self.work / ".Quay" / "x.md", "# x\n\nAsk Theo Marsh.\n"),
                            self.check_note("Northwind", "Pricing", "# N\n\n![[.Quay/x]]\n"))[1],
            "e39": self.utf16_note,
            "e40": self.renamed_folder,
            "e41": lambda: self.check_note("Northwind", "Pricing", "# N\n\nSee [[Orchard/Threads/Drafts/Note]].\n")
            if write(self.work / "Orchard" / "Threads" / "Drafts" / "Note.md", "# n\n") else None,
            "e42": lambda: self.staged_bytes("Cedarwork/Sources/m.eml", STAMPED),
            "e43": lambda: self.staged(self.work / "Reed" / "Sources" / "c.md", "Dana Whitlock agreed.\n"),
            "e44": self.thread_parties,
            "e45": self.knowledge_party_key,
            "e46": lambda: self.reserved_row("none"),
            "e47": self.scaffold_none,
            "e48": lambda: self.check_note("Northwind", "Pricing", "# N\n\nSee [[Dis/Threads/T/Memo]].\n"),
            "e49": lambda: self.nurture_from("Zones/Work/Orchard/Threads/Drafts/x.md"),
            "e50": lambda: self.filed("Dis", ["acme"]),
            "e51": lambda: "permitted" if ask_scope.admits(self.ctx, {"acme"}, {lib.KNOWLEDGE}, self.lib) else "refused",
            "e52": self.knowledge_link,
            "e53": lambda: self.check_note("Both", "T", "# N\n\nSee [[260310-acme-kickoff]] and [[260312-birch-kickoff]].\n"),
            "e54": lambda: self.asked({"acme", "birch"}, self.place("Both", "T")),
            "e55": lambda: self.filed("Both", ["acme", "birch"]),
            "e56": lambda: "refused" if scaffold.wall_between(self.ctx, {"acme", "birch"}, {"acme", "birch"}) else "permitted",
            "e57": lambda: "refused" if __import__("nurture").across_wall(
                __import__("nurture").Ctx(self.root), "Zones/Work/Both/Threads/T/Notes.md",
                "Wikis/Meetings/wiki/sources/260312-birch-kickoff.md") else "permitted",
            "e58": self.hats_refused,
            "e59": lambda: "asked" if scaffold.meet_sentence(self.ctx, ["acme", "birch"]) else "permitted",
            "e20": lambda: recall(set(), {"acme"}),
            "e21": lambda: recall(set(), {"acme", "birch"}),
            "e22": lambda: recall({"acme"}, {"birch"}),
            "e23": lambda: "refused" if lib.decide({"acme"}, set(), "read", self.ctx) == "deny" else "permitted",
        }

    def test_every_row_runs_against_its_point(self):
        rows = lib.wall_cases(CASES.read_text(encoding="utf-8"))["Enforcement points"]
        handlers = self.handlers()
        self.assertEqual(sorted(r[0] for r in rows), sorted(handlers), "a row has no handler, or a handler no row")
        for ident, point, item, expect, source in rows:
            with self.subTest(case=ident, point=point, item=item):
                try:
                    got = handlers[ident]()
                finally:
                    self.restore()          # one row never leaves its changes to the next
                self.assertEqual(expect, got, source)

    def test_the_points_agree_with_decide(self):
        """A point's verdict is decide()'s: the same two labels, the same answer."""
        ours, theirs = self.place("Northwind", "Pricing"), self.place("Harbour", "Sizing")
        self.assertEqual("deny", lib.decide(ours, theirs, "read", self.ctx))
        self.assertEqual("deny", lib.decide(ours, theirs, "file", self.ctx))
        self.assertEqual("deny", lib.decide(ours, theirs, "write", self.ctx))

    def test_check_derives_the_labels_labels_does(self):
        ws = check.discover(self.root)
        for project, thread in (("Northwind", "Pricing"), ("Harbour", "Sizing"), ("Northwind", "Odd"), ("Hubnote", "T")):
            folder = self.work / project
            path = folder / "Threads" / thread / "Notes.md"
            self.assertEqual(set(lib.labels(self.root, path, self.ctx)), check.project_file_tags(ws, folder, path))

    def test_intake_refuses_a_project_whose_party_is_none_or_a_ghost_and_files_nothing_on_confirm(self):
        for name, party in (("Pnone", "none"), ("Pghost", "ghost"), ("Pempty", "")):
            write(self.work / name / (name + ".md"), project_hub("Work", name, party))
            self.addCleanup(shutil.rmtree, self.work / name, True)
            with self.assertRaises(intake.Refusal, msg=name):
                intake.file_to_project(self.root, self.inbox_item(), "Zones/Work/" + name, ["acme"])
        write(self.work / "Third" / "Third.md", project_hub("Work", "Third", "lumen"))
        self.addCleanup(shutil.rmtree, self.work / "Third", True)
        self.assertEqual("asked", self.filed_or_asked("Third", ["lumen"]))
        self.assertEqual("refused", self.filed_or_asked("Third", ["lumen-adv"]))
        self.assertEqual([], list((self.work / "Third").glob("Sources/case-item*")))

    def filed_or_asked(self, project, tags):
        try:
            intake.file_to_project(self.root, self.inbox_item(), "Zones/Work/" + project, tags)
        except intake.Confirm:
            return "asked"
        except intake.Refusal:
            return "refused"
        return "filed"

    def test_walls_cases_runs_the_table_against_the_workspaces_own_tags(self):
        roles = lib.wall_roles(self.ctx)
        self.assertEqual({"near": "acme", "far": "birch", "other": "cedar", "hat": "lumen", "hat2": "lumen-adv", "zone": "jo"},
                         {k: v for k, v in roles.items() if k in ("near", "far", "other", "hat", "hat2", "zone")})
        ran, skipped, failed = lib.run_wall_cases(self.ctx, CASES.read_text(encoding="utf-8"))
        self.assertEqual(([], []), (skipped, failed))
        self.assertGreaterEqual(ran, 45)
        self.assertEqual(0, check.walls_cases(self.root))

    def test_ask_takes_a_place_from_labels_and_reads_nothing_where_there_are_none(self):
        write(self.work / "Twice" / "Twice.md", project_hub("Work", "Twice", "acme").replace("party: acme", "party: acme\nparties: [birch]"))
        write(self.work / "Twice" / "Threads" / "T" / "Secret.md", "# s\n\nharbour pelican\n")
        self.addCleanup(shutil.rmtree, self.work / "Twice", True)
        self.assertEqual(frozenset(), self.place("Twice", "T"))
        self.assertEqual(frozenset({"acme"}), self.place("Hubnote", "T"))
        from types import SimpleNamespace as NS
        with self.assertRaises(ask_scope.Refused):
            ask_scope.scope(self.root, {"route": "thread", "zone": "Work", "project": "Twice", "thread": "T",
                                        "words": ["pelican"]}, NS(places=[], parties=set()),
                            {"Work": {"Twice": {"status": "active", "threads": {"T": "active"}}}}, self.ctx, self.lib)

    def test_the_status_pages_actions_read_a_page_as_labels_does(self):
        sys.path.insert(0, str(REPO / "extras" / "status"))
        import page_action as pa
        lib_ = pa.prefs().lib(self.root)
        people = self.root / "Wikis" / "Meetings" / "wiki" / "people"
        for fm, near in (("party: acme\n", True), ("parties: [acme]\n", False), ("party: acme\nparties: [cedar]\n", False),
                         ("party: acme\nparties: [acme]\n", False)):
            page = write(people / "t-case.md", "---\ntitle: X\ntype: person\n%s---\n\n# X\n" % fm)
            self.addCleanup(lambda: page.exists() and page.unlink())
            got = lib_.labels(self.root, page, self.ctx)
            self.assertEqual(got is not None and lib_.decide({"acme"}, got, "write", self.ctx) == "permit",
                             near, fm)
            self.assertEqual(near, pa.page_party_tags(lib_, self.root, page) is not None, fm)

    def test_walls_cases_exits_non_zero_when_no_wall_row_could_run(self):
        import io
        from contextlib import redirect_stdout
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "W"
            build(root)
            context = root / "System" / "context.md"
            text = context.read_text(encoding="utf-8")
            context.write_text(text.replace("| `acme` | yes |", "| `acme` | no |").replace("| `birch` | yes |", "| `birch` | no |")
                               .replace("| `jo` | yes |", "| `jo` | no |").replace("| `lumen` | yes |", "| `lumen` | no |")
                               .replace("| `lumen-adv` | yes |", "| `lumen-adv` | no |"), encoding="utf-8")
            out = io.StringIO()
            with redirect_stdout(out):
                code = check.walls_cases(root)
        self.assertEqual(1, code)
        self.assertIn("skipped d01 (no near)", out.getvalue())
        self.assertIn("no wall row ran", out.getvalue())

    def test_a_decision_that_lets_a_wall_through_fails_the_table(self):
        with mock.patch.object(lib, "decide", return_value="permit"):
            ran, skipped, failed = lib.run_wall_cases(self.ctx, CASES.read_text(encoding="utf-8"))
        self.assertGreater(len(failed), 10)
        self.assertTrue(any(line.startswith("d01") for line in failed), failed)

    def test_no_enforcement_point_holds_a_wall_test_of_its_own(self):
        """is_walled() is garrick_lib's, under decide() and blocked(). Recall asks decide() and labels() too, and holds none."""
        import re
        own = []
        for top in ("template", "extras"):
            for path in sorted((REPO / top).rglob("*.py")):
                if path.name == "garrick_lib.py" or "__pycache__" in path.parts:
                    continue
                if re.search(r"\b(?:walled|crossings)\(", path.read_text(encoding="utf-8")):
                    own.append(path.relative_to(REPO).as_posix())
        self.assertEqual([], own)

    def test_the_shipped_table_is_the_tests_table(self):
        shipped = REPO / "template" / "System" / "tools" / "walls-cases.md"
        self.assertEqual(CASES.read_text(encoding="utf-8"), shipped.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
