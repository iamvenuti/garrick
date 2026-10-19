"""System/tools/extract.py: the text of a piece of work's Word, PowerPoint and Excel files (#182).

    python3 -m unittest discover -s tests -p test_extract.py

Every Office file here is built in the test with `zipfile`, in a temporary
folder, with invented names. The folder of the piece of work is compared
before and after every run, byte for byte, with its sizes, dates and folders.
"""

from __future__ import annotations

import datetime
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "template" / "System" / "tools"
TOOL = TOOLS / "extract.py"
DISCOVER = TOOLS / "discover.py"
BUILD = REPO / "examples" / "example-work" / "build.py"
_spec = importlib.util.spec_from_file_location("garrick_extract", str(TOOL))
ex = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ex)
ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
WHEN = datetime.datetime(2026, 10, 14, 10, 30).timestamp()

HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
NS_W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
NS_R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
NS_A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
NS_P = 'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
NS_S = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
NS_MC = 'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"'
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"


def rels(*items) -> str:
    return HEAD + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + "".join(
        '<Relationship Id="%s" Type="%s%s" Target="%s"/>' % (rid, REL, kind, target) for rid, kind, target in items
    ) + "</Relationships>"


def package(parts: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", HEAD + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
                   'content-types"><Default Extension="xml" ContentType="application/xml"/></Types>')
        for name, body in parts.items():
            z.writestr(name, body)
    return buf.getvalue()


def docx(extra: str = "") -> bytes:
    p = lambda text, style=None, num=False: (  # noqa: E731
        "<w:p><w:pPr>%s%s</w:pPr><w:r><w:t xml:space=\"preserve\">%s</w:t></w:r></w:p>"
        % ('<w:pStyle w:val="%s"/>' % style if style else "", "<w:numPr><w:ilvl w:val=\"0\"/></w:numPr>" if num else "",
           text))
    body = (
        p("Harbour fit-out brief", "Title")
        + p("Scope", "Heading1")
        + "<w:p><w:r><w:t>Three floors,</w:t></w:r><w:r><w:tab/><w:t>one lift.</w:t></w:r>"
          "<w:del><w:r><w:delText>Two lifts.</w:delText></w:r></w:del>"
          "<w:ins><w:r><w:t xml:space=\"preserve\"> Opens in March.</w:t></w:r></w:ins>"
          "<w:r><w:footnoteReference w:id=\"1\"/></w:r></w:p>"
        + p("Order the desks", num=True)
        + p("Book the movers", num=True)
        + "<w:tbl><w:tr><w:tc>%s</w:tc><w:tc>%s</w:tc></w:tr><w:tr><w:tc>%s</w:tc><w:tc>%s</w:tc></w:tr></w:tbl>"
          % (p("Floor"), p("Desks"), p("Second"), p("48"))
        + "<w:p><w:r><mc:AlternateContent><mc:Choice Requires=\"wps\"><w:drawing><w:txbxContent>"
          "<w:p><w:r><w:t>Callout: quiet room</w:t></w:r></w:p></w:txbxContent></w:drawing></mc:Choice>"
          "<mc:Fallback><w:pict><w:txbxContent><w:p><w:r><w:t>Callout: quiet room</w:t></w:r></w:p>"
          "</w:txbxContent></w:pict></mc:Fallback></mc:AlternateContent></w:r></w:p>"
        + "<w:sdt><w:sdtContent>%s</w:sdtContent></w:sdt>" % p("Signed off by Mara Quell")
        + (p(extra) if extra else "")
    )
    return package({
        "_rels/.rels": rels(("rId1", "officeDocument", "word/document.xml")),
        "word/document.xml": HEAD + "<w:document %s %s><w:body>%s<w:sectPr/></w:body></w:document>" % (NS_W, NS_MC, body),
        "word/_rels/document.xml.rels": rels(("rId1", "footnotes", "footnotes.xml"), ("rId2", "comments", "comments.xml")),
        "word/footnotes.xml": HEAD + "<w:footnotes %s><w:footnote w:type=\"separator\" w:id=\"-1\"><w:p><w:r>"
                              "<w:t>----</w:t></w:r></w:p></w:footnote><w:footnote w:id=\"1\">%s</w:footnote>"
                              "</w:footnotes>" % (NS_W, p("Lift contract signed in September.")),
        "word/comments.xml": HEAD + "<w:comments %s><w:comment w:id=\"0\" w:author=\"Owen Pell\">%s</w:comment>"
                             "</w:comments>" % (NS_W, p("Check the lift date")),
    })


def slide(texts, show=True) -> str:
    shapes = "".join('<p:sp><p:txBody><a:p><a:r><a:t>%s</a:t></a:r></a:p></p:txBody></p:sp>' % t for t in texts)
    return HEAD + '<p:sld %s %s%s><p:cSld><p:spTree>%s</p:spTree></p:cSld></p:sld>' % (
        NS_A, NS_P, "" if show else ' show="0"', shapes)


def pptx() -> bytes:
    notes = (HEAD + '<p:notes %s %s><p:cSld><p:spTree>'
             '<p:sp><p:nvSpPr><p:cNvPr id="2" name="Image"/><p:cNvSpPr/><p:nvPr><p:ph type="sldImg"/></p:nvPr>'
             '</p:nvSpPr></p:sp>'
             '<p:sp><p:nvSpPr><p:cNvPr id="3" name="Notes"/><p:cNvSpPr/><p:nvPr><p:ph type="body"/></p:nvPr>'
             '</p:nvSpPr><p:txBody><a:p><a:r><a:t>Say the budget twice</a:t></a:r></a:p></p:txBody></p:sp>'
             '<p:sp><p:nvSpPr><p:cNvPr id="4" name="Number"/><p:cNvSpPr/><p:nvPr><p:ph type="sldNum"/></p:nvPr>'
             '</p:nvSpPr><p:txBody><a:p><a:r><a:t>7</a:t></a:r></a:p></p:txBody></p:sp>'
             '</p:spTree></p:cSld></p:notes>') % (NS_A, NS_P)
    return package({
        "_rels/.rels": rels(("rId1", "officeDocument", "ppt/presentation.xml")),
        "ppt/presentation.xml": HEAD + '<p:presentation %s %s %s><p:sldIdLst><p:sldId id="256" r:id="rId3"/>'
                                '<p:sldId id="257" r:id="rId2"/><p:sldId id="258" r:id="rId4"/></p:sldIdLst>'
                                '</p:presentation>' % (NS_A, NS_P, NS_R),
        "ppt/_rels/presentation.xml.rels": rels(("rId2", "slide", "slides/slide1.xml"),
                                                ("rId3", "slide", "slides/slide2.xml"),
                                                ("rId4", "slide", "slides/slide3.xml")),
        "ppt/slides/slide1.xml": slide(["Budget", "Desks and lift"]),
        "ppt/slides/slide2.xml": slide(["Harbour fit-out", "Steering, 14 October"]),
        "ppt/slides/slide3.xml": slide(["Spare ideas"], show=False),
        "ppt/slides/_rels/slide1.xml.rels": rels(("rId1", "notesSlide", "../notesSlides/notesSlide1.xml")),
        "ppt/notesSlides/notesSlide1.xml": notes,
    })


def xlsx() -> bytes:
    shared = (HEAD + '<sst %s count="3" uniqueCount="3"><si><t>Item</t></si>'
              '<si><r><t>Desk </t></r><r><rPr><b/></rPr><t>units</t></r></si>'
              '<si><t>東京</t><rPh sb="0" eb="2"><t>トウキョウ</t></rPh></si></sst>') % NS_S
    sheet1 = (HEAD + '<worksheet %s><sheetData>'
              '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="C1" t="inlineStr"><is><t>Cost</t></is></c></row>'
              '<row r="2"><c r="A2" t="s"><v>1</v></c><c r="B2"><v>48</v></c><c r="C2"><v>12500.5</v></c></row>'
              '<row r="3"><c r="A3" t="s"><v>2</v></c><c r="B3" t="b"><v>1</v></c>'
              '<c r="C3" t="str"><f>A3&amp;"!"</f><v>Office!</v></c></row>'
              '<row r="4"/>'
              '</sheetData></worksheet>') % NS_S
    sheet2 = HEAD + '<worksheet %s><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>Draft only</t></is></c></row>' \
                    '</sheetData></worksheet>' % NS_S
    return package({
        "_rels/.rels": rels(("rId1", "officeDocument", "xl/workbook.xml")),
        "xl/workbook.xml": HEAD + '<workbook %s %s><sheets><sheet name="Budget" sheetId="1" r:id="rId1"/>'
                           '<sheet name="Scratch" sheetId="2" state="hidden" r:id="rId2"/></sheets></workbook>'
                           % (NS_S, NS_R),
        "xl/_rels/workbook.xml.rels": rels(("rId1", "worksheet", "worksheets/sheet1.xml"),
                                           ("rId2", "worksheet", "/xl/worksheets/sheet2.xml"),
                                           ("rId3", "sharedStrings", "sharedStrings.xml")),
        "xl/sharedStrings.xml": shared,
        "xl/worksheets/sheet1.xml": sheet1,
        "xl/worksheets/sheet2.xml": sheet2,
    })


def manifest(root: Path) -> list:
    rows = []
    for dp, dns, fns in os.walk(str(root)):
        for d in dns:
            p = os.path.join(dp, d)
            rows.append(("dir", os.path.relpath(p, str(root)), os.lstat(p).st_mtime_ns))
        for f in fns:
            p = os.path.join(dp, f)
            st = os.lstat(p)
            with open(p, "rb") as fh:
                rows.append(("file", os.path.relpath(p, str(root)), hashlib.sha256(fh.read()).hexdigest(),
                             st.st_size, st.st_mtime_ns))
    rows.append(("root", os.lstat(str(root)).st_mtime_ns))
    return sorted(rows, key=repr)


def put(path: Path, data: bytes, when: float = WHEN) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    os.utime(str(path), (when, when))


class ExtractTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()
        self.root = base / "ws"
        (self.root / "System").mkdir(parents=True)
        (self.root / "System" / "rules.md").write_text("# Rules\n", encoding="utf-8")
        self.work = base / "Drive" / "Harbour fit-out"
        put(self.work / "Brief.docx", docx())
        put(self.work / "Steering deck.pptx", pptx())
        put(self.work / "Costs.xlsx", xlsx())
        put(self.work / "Drafts" / "Brief v1.docx", docx())            # a stage folder: part of the work
        put(self.work / "Archive" / "Old brief.docx", docx())          # left out, as discovery leaves it out
        put(self.work / "Phase two" / "Scope.docx", docx())            # a piece of work of its own
        put(self.work / "Plan.pdf", b"%PDF-1.4\n")
        put(self.work / "Notes.md", b"# Notes\n")
        put(self.work / "~$Brief.docx", b"lock")
        put(self.work / "Broken.docx", b"PK\x03\x04 not really a zip at all")
        put(self.work / "Locked.xlsx", ex.OLE + b"\x00" * 504)
        put(self.work / "Partial.pptx", package({"_rels/.rels": rels(("rId1", "officeDocument", "ppt/presentation.xml"))}))
        self.before = manifest(self.work)

    def tearDown(self):
        self.tmp.cleanup()

    def tool(self, *args, ok=True):
        res = subprocess.run([sys.executable, "-B", str(TOOL), "--root", str(self.root), "--json"] + [str(a) for a in args],
                             capture_output=True, text=True, env=ENV)
        self.assertEqual(self.before, manifest(self.work), "the folder changed")
        self.assertEqual(0 if ok else 1, res.returncode, res.stderr + res.stdout)
        return json.loads(res.stdout)

    def out_dir(self) -> Path:
        return self.root / "System" / "generated" / "extracts" / ex.discover.folder_key(self.work)

    def text(self, rel: str) -> str:
        return (self.out_dir() / (rel + ".txt")).read_text(encoding="utf-8")

    def test_word_powerpoint_and_excel_text_comes_out(self):
        out = self.tool(self.work)
        self.assertEqual(["Brief.docx", "Costs.xlsx", "Drafts/Brief v1.docx", "Steering deck.pptx"], out["made"])
        word = self.text("Brief.docx")
        self.assertTrue(word.startswith("The text of Brief.docx, a Word document saved 2026-10-14, taken out by "
                                        "Garrick."), word)
        for line in ("# Harbour fit-out brief", "# Scope", "Three floors,\tone lift. Opens in March.",
                     "- Order the desks", "- Book the movers", "Floor | Desks", "Second | 48",
                     "Signed off by Mara Quell", "## Footnotes", "- Lift contract signed in September.",
                     "## Comments", "- Owen Pell: Check the lift date"):
            self.assertIn(line, word)
        self.assertNotIn("Two lifts", word)                          # deleted text stays out
        self.assertEqual(1, word.count("Callout: quiet room"))      # the drawing's fallback copy is not read twice
        self.assertNotIn("----", word)                               # nor the footnote separator
        deck = self.text("Steering deck.pptx")
        self.assertLess(deck.index("## Slide 1\nHarbour fit-out\nSteering, 14 October"), deck.index("## Slide 2\nBudget"))
        self.assertIn("Notes: Say the budget twice", deck)
        self.assertNotIn("\n7", deck)                                # the slide number placeholder stays out
        self.assertIn("## Slide 3 (hidden)\nSpare ideas", deck)
        sheet = self.text("Costs.xlsx")
        self.assertIn("## Sheet: Budget\nItem\t\tCost\nDesk units\t48\t12500.5\n東京\tTRUE\tOffice!", sheet)
        self.assertNotIn("トウキョウ", sheet)                          # phonetic readings stay out
        self.assertIn("## Sheet: Scratch (hidden)\nDraft only", sheet)
        self.assertIn("Drafts/Brief v1.docx", out["made"])

    def test_only_the_files_of_the_piece_of_work_and_only_office_files(self):
        out = self.tool(self.work)
        every = out["made"] + out["kept"] + [u["file"] for u in out["unreadable"]] + out["others"]
        self.assertFalse([f for f in every if f.startswith(("Archive/", "Phase two/")) or f.startswith("~$")], every)
        self.assertEqual(["Notes.md", "Plan.pdf"], out["others"])
        written = sorted(p.relative_to(self.out_dir()).as_posix() for p in self.out_dir().rglob("*") if p.is_file())
        self.assertEqual([".extracts.json", "Brief.docx.txt", "Costs.xlsx.txt", "Drafts/Brief v1.docx.txt",
                          "Steering deck.pptx.txt"], written)

    def test_a_damaged_or_locked_file_is_reported_and_skipped(self):
        out = self.tool(self.work)
        why = {u["file"]: u["why"] for u in out["unreadable"]}
        self.assertEqual({"Broken.docx", "Locked.xlsx", "Partial.pptx"}, set(why))
        self.assertIn("password", why["Locked.xlsx"])
        self.assertIn("damaged", why["Broken.docx"])
        self.assertIn("damaged", why["Partial.pptx"])
        res = subprocess.run([sys.executable, "-B", str(TOOL), "--root", str(self.root), str(self.work)],
                             capture_output=True, text=True, env=ENV)
        self.assertEqual(0, res.returncode, res.stderr)
        self.assertIn("Not read: Locked.xlsx, because it is protected by a password", res.stdout)
        self.assertIn("2 other files can be read as they are.", res.stdout)

    def test_rebuilt_only_when_a_file_changes_and_removed_when_it_is_gone(self):
        self.tool(self.work)
        stamp = (self.out_dir() / "Brief.docx.txt").stat().st_mtime_ns
        again = self.tool(self.work)
        self.assertEqual([], again["made"])
        self.assertEqual(["Brief.docx", "Costs.xlsx", "Drafts/Brief v1.docx", "Steering deck.pptx"], again["kept"])
        self.assertEqual(stamp, (self.out_dir() / "Brief.docx.txt").stat().st_mtime_ns)
        self.assertEqual({"Broken.docx", "Locked.xlsx", "Partial.pptx"}, {u["file"] for u in again["unreadable"]})
        # A new date alone; a new size alone; a file that no longer reads; a file gone.
        os.utime(str(self.work / "Costs.xlsx"), (WHEN + 60, WHEN + 60))
        put(self.work / "Brief.docx", docx("Added after the walk-round."), WHEN)
        put(self.work / "Steering deck.pptx", b"PK\x03\x04 overwritten", WHEN)
        (self.work / "Drafts" / "Brief v1.docx").unlink()
        self.before = manifest(self.work)
        third = self.tool(self.work)
        self.assertEqual(["Brief.docx", "Costs.xlsx"], third["made"])
        self.assertIn("Added after the walk-round.", self.text("Brief.docx"))
        self.assertIn("Steering deck.pptx", {u["file"] for u in third["unreadable"]})
        self.assertFalse((self.out_dir() / "Steering deck.pptx.txt").exists())
        self.assertEqual(["Drafts/Brief v1.docx"], third["removed"])
        self.assertFalse((self.out_dir() / "Drafts").exists())
        put(self.work / "Steering deck.pptx", pptx(), WHEN + 120)
        self.before = manifest(self.work)
        fourth = self.tool(self.work)
        self.assertEqual(["Steering deck.pptx"], fourth["made"])
        self.assertEqual(["Brief.docx", "Costs.xlsx"], fourth["kept"])

    def test_nothing_is_ever_written_under_the_folder(self):
        """Pointed at the folder itself, the writing is refused by the guard, and the folder is as it was."""
        real = ex.extracts_dir
        ex.extracts_dir = lambda root, key: self.work / "extracts"
        try:
            with self.assertRaises(PermissionError):
                ex.run(self.root, str(self.work))
        finally:
            ex.extracts_dir = real
        self.assertEqual(self.before, manifest(self.work))
        refused = subprocess.run([sys.executable, "-B", str(TOOL), "--root", str(self.root), "--json",
                                  str(self.root.parent)], capture_output=True, text=True, env=ENV)
        self.assertEqual(1, refused.returncode)
        self.assertIn("holds Garrick itself", json.loads(refused.stdout)["error"])

    def test_refusals(self):
        self.assertIn("There is no folder", self.tool(self.work / "Nowhere", ok=False)["error"])
        self.assertIn("No piece of work has the id", self.tool("--work", "deadbeef", ok=False)["error"])
        self.assertIn("not both", self.tool(self.work, "--work", "deadbeef", ok=False)["error"])

    def test_a_piece_of_work_by_its_discovery_id(self):
        def discover(*args):
            res = subprocess.run([sys.executable, "-B", str(DISCOVER), "--root", str(self.root), "--json",
                                  "--today", "2026-10-15"] + [str(a) for a in args], capture_output=True, text=True,
                                 env=ENV)
            self.assertEqual(0, res.returncode, res.stderr)
            return json.loads(res.stdout)
        found = discover("scan", self.work.parent)
        by = {p["name"]: p for p in found["top"] + found["more"]}
        out = self.tool("--work", by["Harbour fit-out"]["id"])
        self.assertEqual(ex.discover.folder_key(self.work), out["key"])
        self.assertEqual(["Brief.docx", "Costs.xlsx", "Drafts/Brief v1.docx", "Steering deck.pptx"], out["made"])
        # A group of names in a flat folder: its files alone.
        flat = Path(self.tmp.name).resolve() / "Loose"
        for name in ("Quayside lease terms.docx", "Quayside lease costs.xlsx", "Quayside lease plan.pptx",
                     "Holiday list.xlsx", "Team lunch.docx"):
            put(flat / name, {".docx": docx(), ".xlsx": xlsx(), ".pptx": pptx()}[Path(name).suffix])
        found = discover("scan", flat)
        self.assertTrue(found["flat"])
        group = next(p for p in found["top"] if "Quayside" in p["label"])
        res = subprocess.run([sys.executable, "-B", str(TOOL), "--root", str(self.root), "--json", "--work", group["id"]],
                             capture_output=True, text=True, env=ENV)
        out = json.loads(res.stdout)
        self.assertEqual(["Quayside lease costs.xlsx", "Quayside lease plan.pptx", "Quayside lease terms.docx"],
                         out["made"])
        self.assertTrue(out["key"].endswith(group["id"]))

    def test_the_worked_examples_word_files(self):
        spec = importlib.util.spec_from_file_location("garrick_example_build_extract", str(BUILD))
        build = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(build)
        d = build.dates(datetime.date(2026, 10, 20))
        drive = Path(self.tmp.name).resolve() / "Quillfield Shared"
        build.lay_drive(drive, build.fields(d), d)
        folder = drive / "Marketing" / "Kestle chair launch"
        before = manifest(drive)
        out = ex.run(self.root, str(folder))
        self.assertEqual(before, manifest(drive))
        self.assertIn("Kestle chair launch brief.docx", out["made"])
        text = (ex.extracts_dir(self.root, out["key"]) / "Kestle chair launch brief.docx.txt").read_text(encoding="utf-8")
        self.assertIn("Kestle chair: launch brief", text)
        self.assertIn("Launch email draft.txt", out["others"])


if __name__ == "__main__":
    unittest.main()
