"""drift.py: a project's ledger of what it published, compared with the
shared copies, Office files by their content rather than their bytes.

    python3 -m unittest discover -s tests
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import build_workspace, project_hub, write  # noqa: E402

import check  # noqa: E402  (fixtures puts the tools folder on sys.path)
import drift  # noqa: E402

DOC = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
       '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r>'
       '<w:t>%s</w:t></w:r></w:p></w:body></w:document>')


def docx(text="Pallet terms, version two.", provider=False, swap=False, saved_by="Jo"):
    """A small Word file. `provider` adds what a shared library stamps into
    every Office file it stores; `swap` writes the same relationships in
    another order, as Office does on a save."""
    rels = ['<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>',
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>']
    if swap:
        rels.reverse()
    types = ['<Default Extension="xml" ContentType="application/xml"/>',
             '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>']
    if provider:
        rels.append('<Relationship Id="rId9" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/customXml" Target="customXml/item1.xml"/>')
        types.append('<Override PartName="/customXml/itemProps1.xml" ContentType="application/vnd.openxmlformats-officedocument.customXmlProperties+xml"/>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">%s</Types>' % "".join(types))
        z.writestr("_rels/.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">%s</Relationships>' % "".join(rels))
        z.writestr("word/document.xml", DOC % text)
        z.writestr("docProps/core.xml", "<cp:coreProperties xmlns:cp=\"x\"><cp:lastModifiedBy>%s</cp:lastModifiedBy></cp:coreProperties>" % saved_by)
        if provider:
            z.writestr("customXml/item1.xml", "<b:Sources xmlns:b=\"y\"/>")
            z.writestr("customXml/itemProps1.xml", "<ds:datastoreItem xmlns:ds=\"z\" ds:itemID=\"{1}\"/>")
    return buf.getvalue()


class DriftBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name).resolve()
        self.home = base / "home"                                  # never this Mac's own machine.json
        self.home.mkdir()
        env = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        env.start()
        self.addCleanup(env.stop)
        self.root = base / "Workspace"
        build_workspace(self.root)
        self.work = self.root / "Zones" / "Work"
        self.acme = self.work / "Acme Review"
        hub = self.acme / "Acme Review.md"
        hub.write_text(hub.read_text().replace("party: acme", "party: acme\nshared: team/Acme", 1))
        self.share = base / "Cloud" / "Team library"
        (self.share / "Acme").mkdir(parents=True)
        (self.work / ".shared").mkdir()
        os.symlink(self.share, self.work / ".shared" / "team")
        self.ours = self.acme / "Deliverables" / "260930 - Terms.docx"
        self.ours.parent.mkdir(exist_ok=True)
        self.ours.write_bytes(docx())
        write(self.acme / "Deliverables" / "published.md",
              "# Published\n\n| Date | File | Destination | Recipients | Authoritative |\n|---|---|---|---|---|\n"
              "| 2026-10-01 | `260930 - Terms.docx` | `Terms.docx` | Dana | share |\n")

    def one(self):
        [found] = [f for f in drift.survey(self.root) if f["file"]]
        return found


class DriftTest(DriftBase):
    def test_the_providers_stamp_and_a_resave_are_not_drift(self):
        (self.share / "Acme" / "Terms.docx").write_bytes(docx(provider=True, swap=True, saved_by="Dana"))
        self.assertEqual("same", self.one()["state"])

    def test_an_edit_on_the_share_puts_a_share_row_behind_and_a_here_row_adrift(self):
        (self.share / "Acme" / "Terms.docx").write_bytes(docx("Pallet terms, version three.", provider=True))
        found = self.one()
        self.assertEqual("behind", found["state"])                              # what the ledger expects
        self.assertIn("the project's copy is behind the share", found["say"])
        self.assertIn("word/document.xml", found["say"])
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            self.assertEqual(0, drift.main(["--root", str(self.root)]))         # behind alone is nothing to look at
        ledger = self.acme / "Deliverables" / "published.md"
        ledger.write_text(ledger.read_text().replace("| Dana | share |", "| Dana | here |"))
        found = self.one()
        self.assertEqual("drifted", found["state"])
        self.assertIn("word/document.xml", found["say"])
        self.assertNotIn("behind", found["say"])
        with mock.patch("builtins.print"):
            self.assertEqual(1, drift.main(["--root", str(self.root)]))

    def test_each_row_names_both_copies_and_when_each_changed(self):
        """#323: the page says which copy changed and when, and Show both
        reveals the two, from what drift.json records: both paths, the shared
        one through the zone's link as the ledger names it, and their dates,
        read from the files' dates without opening the shared copy."""
        theirs = self.share / "Acme" / "Terms.docx"
        theirs.write_bytes(docx("Dana's wording."))
        ledger = self.acme / "Deliverables" / "published.md"
        ledger.write_text(ledger.read_text().replace("| Dana | share |", "| Dana | here |"))
        os.utime(self.ours, (1791331200, 1791331200))            # 7 October 2026
        os.utime(theirs, (1793232000, 1793232000))               # 30 October 2026
        real, reads = drift.Path.read_bytes, []
        with mock.patch.object(drift.Path, "read_bytes", lambda path: reads.append(path) or real(path)):
            found = self.one()
        self.assertEqual("drifted", found["state"])
        self.assertEqual("Zones/Work/Acme Review/Deliverables/260930 - Terms.docx", found["here"])
        self.assertEqual("Zones/Work/.shared/team/Acme/Terms.docx", found["shared"])        # through the link, as named
        day = lambda t: drift.datetime.datetime.fromtimestamp(t).date().isoformat()
        self.assertEqual((day(1791331200), day(1793232000), "shared"),
                         (found["here_changed"], found["shared_changed"], found["newer"]))
        self.assertEqual(2, len(reads))                                                    # the comparison's reads, no more
        os.utime(self.ours, (1793318400, 1793318400))            # the copy here moved last
        self.assertEqual("here", self.one()["newer"])
        theirs.unlink()
        gone = self.one()
        self.assertEqual("missing", gone["state"])
        self.assertNotIn("newer", gone)                                                     # one copy: no dates to set side by side

    def test_a_share_row_behind_is_listed_apart_from_a_here_row_that_drifted(self):
        (self.share / "Acme" / "Terms.docx").write_bytes(docx("Dana's wording."))
        (self.acme / "Deliverables" / "261001 - Rates.csv").write_bytes(b"rates")
        (self.share / "Acme" / "Rates.csv").write_bytes(b"rates, edited")
        ledger = self.acme / "Deliverables" / "published.md"
        ledger.write_text(ledger.read_text().replace("| 2026-10-01 |", "| 2026-10-02 | `261001 - Rates.csv` | `Rates.csv` | Dana | here |\n"
                                                     "| 2026-10-01 |", 1))
        self.assertEqual([("261001 - Rates.csv", "drifted"), ("260930 - Terms.docx", "behind")],
                         [(f["file"], f["state"]) for f in drift.survey(self.root)])
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            self.assertEqual(1, drift.main(["--root", str(self.root)]))
        lines = out.getvalue().splitlines()
        self.assertEqual(2, len(lines))
        self.assertIn("Rates.csv: drifted", lines[0])
        self.assertIn("Terms.docx: behind (the project's copy is behind the share:", lines[1])

    def test_an_empty_copy_is_a_fault_whichever_copy_counts(self):
        (self.share / "Acme" / "Terms.docx").write_bytes(b"")
        self.assertEqual("drifted", self.one()["state"])

    def test_online_only_encrypted_and_missing(self):
        target = self.share / "Acme" / "Terms.docx"
        target.write_bytes(docx())
        with mock.patch.object(drift, "online_only", return_value=True):
            self.assertEqual("unchecked", self.one()["state"])                    # never downloaded
        target.write_bytes(drift.OLE + b"\0" * 600)
        self.assertEqual("encrypted", self.one()["state"])
        target.write_bytes(b"XYZ" + b"\0" * 600)                                 # encrypted in place by a rights service
        found = self.one()
        self.assertEqual("encrypted", found["state"])
        self.assertIn("rights-management", found["say"])
        target.unlink()
        self.assertEqual("missing", self.one()["state"])

    def test_a_damaged_copy_is_reported_and_the_rest_still_checked(self):
        good = docx()
        damaged = good[:len(good) // 2] + b"\0" * 40 + good[len(good) // 2 + 40:]
        (self.share / "Acme" / "Terms.docx").write_bytes(damaged)
        self.assertEqual("drifted", self.one()["state"])

    def test_a_row_cannot_point_outside_its_folders(self):
        ledger = self.acme / "Deliverables" / "published.md"
        ledger.write_text(ledger.read_text().replace("`Terms.docx`", "`/etc/hosts`"))
        self.assertEqual("unchecked", self.one()["state"])
        ledger.write_text(ledger.read_text().replace("`260930 - Terms.docx`", "`../../Other/secret.docx`"))
        self.assertEqual("unread", self.one()["state"])

    def test_a_row_that_does_not_read_is_reported_and_saved_for_the_page(self):
        ledger = self.acme / "Deliverables" / "published.md"
        ledger.write_text(ledger.read_text() + "| last week | Terms.docx | somewhere | Dana | share |\n")
        found = [f for f in check.run_checks(self.root) if f.check == "deliverables" and "published.md" in f.path]
        self.assertEqual(1, len(found))
        self.assertIn("not watched for drift", found[0].message)
        with mock.patch("builtins.print"):
            self.assertEqual(1, drift.main(["--root", str(self.root), "--save"]))
        saved = json.loads((self.root / "System" / "generated" / "drift.json").read_text())
        self.assertIn("unread", [f["state"] for f in saved["files"]])

    def test_a_hub_with_no_shared_folder_leaves_the_row_unchecked(self):
        hub = self.acme / "Acme Review.md"
        hub.write_text(hub.read_text().replace("shared: team/Acme\n", "", 1))
        found = self.one()
        self.assertEqual("unchecked", found["state"])
        self.assertIn("shared:", found["say"])

    def test_a_history_row_is_read_never_compared_and_never_warned_about(self):
        ledger = self.acme / "Deliverables" / "published.md"
        ledger.write_text(ledger.read_text()
                          + "| withdrawn 2026-10-03 | `260901 - Old terms.docx` | `Old terms.docx` | Dana | share |\n"
                          + "| replaced 2026-10-04 | `260902 - Terms draft.docx` | `Terms.docx` | Dana | here, until the draft went |\n"
                          + "| sent 2026-10-05 | `260930 - Terms.docx` | email to Birch & Co | Theo | here |\n")
        (self.share / "Acme" / "Terms.docx").write_bytes(docx())
        found = drift.survey(self.root)
        self.assertEqual(["same", "withdrawn", "replaced", "sent"], [f["state"] for f in found])
        self.assertEqual("2026-10-03", found[1]["date"])
        self.assertEqual([], [f for f in check.run_checks(self.root) if f.check == "deliverables" and "published.md" in f.path])
        with mock.patch("builtins.print"):
            self.assertEqual(0, drift.main(["--root", str(self.root)]))           # history is nothing to look at

    def test_a_note_may_follow_share_or_here(self):
        ledger = self.acme / "Deliverables" / "published.md"
        ledger.write_text(ledger.read_text().replace("| Dana | share |", "| Dana | Share, Dana edits the wording there |"))
        (self.share / "Acme" / "Terms.docx").write_bytes(docx("Dana's wording."))
        found = self.one()
        self.assertEqual(("behind", "share"), (found["state"], found["authoritative"]))
        ledger.write_text(ledger.read_text().replace("| Share, Dana", "| shared by Dana"))
        self.assertEqual("unread", drift.survey(self.root)[0]["state"])           # a first word that is neither

    def test_only_the_table_under_the_date_header_is_the_ledger(self):
        ledger = self.acme / "Deliverables" / "published.md"
        ledger.write_text(ledger.read_text() + "\n## Amendments\n\n| Amendment | What moved |\n|---|---|\n| 2026-10-02 | two rows |\n")
        (self.share / "Acme" / "Terms.docx").write_bytes(docx())
        self.assertEqual(["same"], [f["state"] for f in drift.survey(self.root)])

    def test_a_thread_keeps_its_own_ledger(self):
        thread = self.acme / "Threads" / "Pricing"
        (thread / "Deliverables").mkdir(parents=True)
        (thread / "Deliverables" / "261001 - Rates.csv").write_bytes(b"rates")
        (self.share / "Acme" / "Rates.csv").write_bytes(b"rates, edited")
        write(thread / "Deliverables" / "published.md",
              "| Date | File | Destination | Recipients | Authoritative |\n|---|---|---|---|---|\n"
              "| 2026-10-02 | `261001 - Rates.csv` | `Rates.csv` | Dana | here |\n"
              "| last week | Rates | somewhere | Dana | here |\n")
        found = [f for f in drift.survey(self.root) if f.get("thread") == "Pricing"]
        self.assertEqual(["unread", "drifted"], [f["state"] for f in found])
        self.assertEqual("bytes", found[1]["say"].split()[-2])
        warned = [f for f in check.run_checks(self.root) if f.check == "deliverables" and "published.md" in f.path]
        self.assertEqual(["Zones/Work/Acme Review/Threads/Pricing/Deliverables/published.md"], [f.path for f in warned])

    def test_excels_trash_is_not_content(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(docx())) as src, zipfile.ZipFile(buf, "w") as z:
            for name in src.namelist():
                z.writestr(name, src.read(name))
            z.writestr("[trash]/0000.dat", b"what an incremental save left behind")
        (self.share / "Acme" / "Terms.docx").write_bytes(buf.getvalue())
        self.assertEqual("same", self.one()["state"])

    def test_the_zone_ignores_its_shared_links(self):
        import garrick_lib
        lines = garrick_lib.garrick_ignores(["Work"])
        self.assertIn(".shared/", lines["Zones/Work/.gitignore"].splitlines())
        self.assertIn(".shared/", lines["/".join(garrick_lib.ZONE_TEMPLATE + (".gitignore",))].splitlines())

    def test_a_destination_folder_holds_a_copy_with_the_files_name(self):
        ledger = self.acme / "Deliverables" / "published.md"
        (self.share / "Acme" / "Contracts").mkdir()
        (self.share / "Acme" / "Contracts" / "260930 - Terms.docx").write_bytes(docx())
        for dest in ("`Contracts/`", "`Contracts`", "`team:Acme/Contracts/`"):
            ledger.write_text(ledger.read_text().split("| 2026-10-01")[0]
                              + "| 2026-10-01 | `260930 - Terms.docx` | %s | Dana | share |\n" % dest)
            self.assertEqual("same", self.one()["state"], dest)

    def test_a_file_may_be_named_from_the_projects_folder(self):
        working = self.acme / "Threads" / "Pricing" / "Shared Notes"
        working.mkdir(parents=True)
        (working / "261001 - Rates.csv").write_bytes(b"rates")
        (self.share / "Acme" / "Rates.csv").write_bytes(b"rates")
        ledger = self.acme / "Deliverables" / "published.md"
        ledger.write_text(ledger.read_text().replace("`260930 - Terms.docx` | `Terms.docx`",
                                                     "`Threads/Pricing/Shared Notes/261001 - Rates.csv` | `Rates.csv`"))
        self.assertEqual("same", self.one()["state"])
        ledger.write_text(ledger.read_text().replace("`Threads/Pricing", "`../Acme Review/Threads/Pricing"))
        self.assertEqual("unread", self.one()["state"])                         # never out of the project

    def test_a_sync_conflict_beside_what_was_published_is_reported_by_name_alone(self):
        acme = self.share / "Acme"
        (acme / "Terms.docx").write_bytes(docx())
        (acme / "Old").mkdir()
        for name in ("Terms (1).docx", "Terms - Copy.docx", "Terms-v2.docx", "~$Terms.docx",
                     "Old/Rates (Dana's conflicted copy 2026-10-12).xlsx", "Old/Rates (1).xlsx"):
            (acme / name).write_bytes(b"x")
        (acme / "Terms (1).docx").chmod(0)                                    # never opened, only named
        self.addCleanup((acme / "Terms (1).docx").chmod, 0o644)
        found = {(f["file"], f["destination"]) for f in drift.survey(self.root) if f["state"] == "conflict"}
        self.assertEqual({("Terms (1).docx", ""), ("Rates (Dana's conflicted copy 2026-10-12).xlsx", "Old")}, found)
        with mock.patch("builtins.print"):
            self.assertEqual(1, drift.main(["--root", str(self.root), "--save"]))
        sys.path.insert(0, str(Path(drift.__file__).resolve().parents[3] / "extras" / "status"))
        import status
        self.assertIn("Acme Review: Terms (1).docx is a copy a sync conflict left on the share",
                      [f["text"] for f in status.drifted(self.root)])

    def test_the_status_page_lists_what_drifted_and_not_what_is_behind(self):
        sys.path.insert(0, str(Path(drift.__file__).resolve().parents[3] / "extras" / "status"))
        import status
        write(self.root / "System" / "generated" / "drift.json",
              json.dumps({"files": [{"project": "Acme Review", "file": "260930 - Terms.docx", "state": "drifted"},
                                    {"project": "Acme Review", "file": "261001 - Rates.csv", "state": "behind"},
                                    {"project": "Acme Review", "file": "x", "state": "same"}]}))
        self.assertEqual(["Acme Review: 260930 - Terms.docx has drifted from its shared copy"],
                         [f["text"] for f in status.drifted(self.root)])

    def test_the_status_page_says_which_copy_changed_and_when(self):
        """#323: with both copies' dates, the row says which changed, and when,
        the other way round when the copy here is the newer; a file in a
        thread leads to the thread's row."""
        sys.path.insert(0, str(Path(drift.__file__).resolve().parents[3] / "extras" / "status"))
        import status
        row = {"zone": "Work", "project": "Acme Review", "file": "261007 - Business case.xlsx", "state": "drifted",
               "here": "Zones/Work/Acme Review/Deliverables/261007 - Business case.xlsx",
               "shared": "Zones/Work/.shared/team/Acme/Business case.xlsx",
               "here_changed": "2026-10-07", "shared_changed": "2026-10-30", "newer": "shared"}
        mine = dict(row, here_changed="2026-10-30", shared_changed="2026-10-07", newer="here", thread="Pricing")
        kept = {"zone": "Work", "project": "Acme Review", "file": "Threads/Freight/Rates.csv", "state": "missing"}
        write(self.root / "System" / "generated" / "drift.json", json.dumps({"files": [row, mine, kept]}))
        found = status.drifted(self.root)
        self.assertEqual("Acme Review: 261007 - Business case.xlsx: the shared copy changed on 30 Oct, after the copy here (7 Oct)",
                         found[0]["text"])
        self.assertEqual("Acme Review, Pricing: 261007 - Business case.xlsx: the copy here changed on 30 Oct, "
                         "after the shared copy (7 Oct)", found[1]["text"])
        self.assertEqual(("", "Pricing", "Freight"), (found[0]["thread"], found[1]["thread"], found[2]["thread"]))
        self.assertEqual((True, True, False), tuple(f["both"] for f in found))      # Show both only with both copies named


class MachineTest(DriftBase):
    """A workspace on more than one machine (#612): a link that does not resolve here is one line, and a roaming
    machine hands what it found to the server through each zone's drop folder."""

    def role(self, role, **more):
        target = self.home / ".config" / "garrick" / "machine.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(dict(role=role, **more)))

    def cut_the_link(self):
        (self.work / ".shared" / "team").unlink()

    def run_drift(self, *args):
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            code = drift.main(["--root", str(self.root)] + list(args))
        return code, out.getvalue()

    def drops(self):
        return sorted((self.work / "Inbox" / ".machines").glob("drift-*.json"))

    # solo is v0.72.0

    def test_solo_still_fails_every_row_of_a_link_that_does_not_resolve(self):
        self.cut_the_link()
        [found] = [f for f in drift.survey(self.root) if f["file"]]
        self.assertEqual("unchecked", found["state"])
        self.assertNotIn("link", found)
        self.assertEqual(["unchecked"], [f["state"] for f in drift.survey(self.root)])
        self.role("solo")
        self.assertEqual(["unchecked"], [f["state"] for f in drift.survey(self.root)])

    # server

    def test_a_server_reports_a_link_that_does_not_resolve_once_and_no_row_fails(self):
        self.role("server", name="mini")
        ledger = self.acme / "Deliverables" / "published.md"
        ledger.write_text(ledger.read_text() + "| 2026-10-02 | `260930 - Terms.docx` | `Rates.docx` | Dana | share |\n")
        self.cut_the_link()
        code, said = self.run_drift()
        self.assertEqual(0, code)
        self.assertEqual("Work: team: not reachable here\n", said)
        states = [f["state"] for f in drift.survey(self.root, spread=True)]
        self.assertEqual(["unreachable"], states)

    def test_a_server_that_reaches_its_share_compares_as_before(self):
        self.role("server", name="mini")
        (self.share / "Acme" / "Terms.docx").write_bytes(docx("Pallet terms, version three.", provider=True))
        code, said = self.run_drift()
        self.assertEqual("behind", self.one_spread()["state"])
        self.assertEqual(0, code)
        self.assertNotIn("not reachable", said)

    def one_spread(self):
        [found] = [f for f in drift.survey(self.root, spread=True) if f["file"]]
        return found

    # roaming

    def test_roaming_hands_what_it_found_to_the_server_through_the_drop_folder(self):
        self.role("roaming", name="laptop")
        (self.share / "Acme" / "Terms.docx").write_bytes(docx("Dana's wording."))
        ledger = self.acme / "Deliverables" / "published.md"
        ledger.write_text(ledger.read_text().replace("| Dana | share |", "| Dana | here |"))
        code, _ = self.run_drift("--save")
        self.assertEqual(1, code)
        [drop] = self.drops()
        self.assertEqual("drift-laptop.json", drop.name)
        data = json.loads(drop.read_text())
        self.assertEqual(("Work", "laptop"), (data["zone"], data["machine"]))
        self.assertEqual(["drifted"], [f["state"] for f in data["files"]])
        self.assertFalse((self.root / "System" / "generated" / "drift.json").exists())      # the copy only receives

    def test_each_zone_gets_only_its_own_rows(self):
        self.role("roaming", name="laptop")
        personal = self.root / "Zones" / "Personal"
        write(personal / "Trip" / "Trip.md", "---\ntitle: Trip\ntype: project\nzone: Personal\nstatus: active\nshared: home/Trip\n---\n\n# Trip\n")
        write(personal / "Trip" / "Deliverables" / "260901 - Plan.docx", "x")
        write(personal / "Trip" / "Deliverables" / "published.md",
              "| Date | File | Destination | Recipients | Authoritative |\n|---|---|---|---|---|\n"
              "| 2026-09-01 | `260901 - Plan.docx` | `Plan.docx` | Jo | here |\n")
        (personal / ".shared").mkdir()
        os.symlink(self.share, personal / ".shared" / "home")
        self.run_drift("--save")
        mine = {p.parent.parent.parent.name: json.loads(p.read_text()) for p in
                self.root.glob("Zones/*/Inbox/.machines/drift-laptop.json")}
        self.assertEqual({"Work", "Personal"}, set(mine))
        for zone, data in mine.items():
            self.assertEqual({zone}, {f["zone"] for f in data["files"]})

    def test_roaming_does_not_hand_over_what_it_cannot_reach(self):
        self.role("roaming", name="laptop")
        self.cut_the_link()
        code, said = self.run_drift("--save")
        self.assertEqual((0, "Work: team: not reachable here\n"), (code, said))
        self.assertEqual([], self.drops())

    # server, reading the drop

    def hand_over(self, when=None, zone="Work", files=None):
        rows = files if files is not None else [{"zone": "Work", "project": "Acme Review", "file": "260930 - Terms.docx",
                                                 "destination": "Terms.docx", "state": "drifted", "link": "team",
                                                 "say": "the bytes differ"}]
        stamp = (when or drift.datetime.datetime.now()).isoformat(timespec="seconds")
        write(self.work / "Inbox" / ".machines" / "drift-laptop.json",
              json.dumps({"checked": stamp, "machine": "laptop", "zone": zone, "files": rows}))

    def test_the_server_puts_the_roaming_rows_in_drift_json_for_the_page(self):
        self.role("server", name="mini")
        self.cut_the_link()
        self.hand_over()
        code, said = self.run_drift("--save")
        self.assertEqual(1, code)                                                     # a drifted row is a fault, wherever it was found
        self.assertNotIn("not reachable", said)                                       # the roaming machine reached the link
        saved = json.loads((self.root / "System" / "generated" / "drift.json").read_text())["files"]
        self.assertEqual([("drifted", "laptop")], [(f["state"], f["machine"]) for f in saved])
        sys.path.insert(0, str(Path(drift.__file__).resolve().parents[3] / "extras" / "status"))
        import status
        self.assertEqual(["Acme Review: 260930 - Terms.docx has drifted from its shared copy"],
                         [f["text"] for f in status.drifted(self.root)])

    def test_a_link_the_roaming_machine_did_not_cover_stays_unreachable(self):
        self.role("server", name="mini")
        self.cut_the_link()
        self.hand_over(files=[{"zone": "Work", "project": "Acme Review", "file": "x", "destination": "x", "state": "same", "link": "other"}])
        code, said = self.run_drift()
        self.assertIn("Work: team: not reachable here", said)

    def test_an_old_or_foreign_or_broken_drop_is_not_read(self):
        self.role("server", name="mini")
        self.cut_the_link()
        old = drift.datetime.datetime.now() - drift.datetime.timedelta(days=20)
        self.hand_over(when=old)
        self.assertIn("not reachable here", self.run_drift()[1])
        self.hand_over(zone="Personal")                                              # a file that names another zone
        self.assertIn("not reachable here", self.run_drift()[1])
        (self.work / "Inbox" / ".machines" / "drift-laptop.json").write_text("{not json")
        self.assertIn("not reachable here", self.run_drift()[1])

    def test_a_solo_machine_never_reads_a_drop(self):
        self.hand_over()
        self.cut_the_link()
        saved = drift.survey(self.root)
        self.assertEqual(["unchecked"], [f["state"] for f in saved])


if __name__ == "__main__":
    unittest.main()
