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


class DriftTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name).resolve()
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

    def test_the_providers_stamp_and_a_resave_are_not_drift(self):
        (self.share / "Acme" / "Terms.docx").write_bytes(docx(provider=True, swap=True, saved_by="Dana"))
        self.assertEqual("same", self.one()["state"])

    def test_an_edit_is(self):
        (self.share / "Acme" / "Terms.docx").write_bytes(docx("Pallet terms, version three.", provider=True))
        found = self.one()
        self.assertEqual("drifted", found["state"])
        self.assertIn("word/document.xml", found["say"])

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
        self.assertEqual(("drifted", "share"), (found["state"], found["authoritative"]))
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
        self.assertIn("Acme Review: Terms (1).docx is a copy a sync conflict left on the share", status.drifted(self.root))

    def test_the_status_page_lists_what_drifted(self):
        sys.path.insert(0, str(Path(drift.__file__).resolve().parents[3] / "extras" / "status"))
        import status
        write(self.root / "System" / "generated" / "drift.json",
              json.dumps({"files": [{"project": "Acme Review", "file": "260930 - Terms.docx", "state": "drifted"},
                                    {"project": "Acme Review", "file": "x", "state": "same"}]}))
        self.assertEqual(["Acme Review: 260930 - Terms.docx has drifted from its shared copy"], status.drifted(self.root))


if __name__ == "__main__":
    unittest.main()
