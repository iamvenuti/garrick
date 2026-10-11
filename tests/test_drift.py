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
        target.unlink()
        self.assertEqual("missing", self.one()["state"])

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

    def test_the_status_page_lists_what_drifted(self):
        sys.path.insert(0, str(Path(drift.__file__).resolve().parents[3] / "extras" / "status"))
        import status
        write(self.root / "System" / "generated" / "drift.json",
              json.dumps({"files": [{"project": "Acme Review", "file": "260930 - Terms.docx", "state": "drifted"},
                                    {"project": "Acme Review", "file": "x", "state": "same"}]}))
        self.assertEqual(["Acme Review: 260930 - Terms.docx has drifted from its shared copy"], status.drifted(self.root))


if __name__ == "__main__":
    unittest.main()
