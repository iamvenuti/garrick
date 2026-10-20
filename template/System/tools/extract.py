#!/usr/bin/env python3
"""extract.py: the text of a piece of work's Word, PowerPoint and Excel files, for an assistant to read.

    python3 System/tools/extract.py <folder>        the piece of work in that folder
    python3 System/tools/extract.py --work <id>     the piece of work discover.py proposed under that id

An assistant reads text, Markdown, PDF and transcripts on its own, but not
Word, PowerPoint or Excel, and the session that reads a piece of work may have
no shell to convert them. This takes their text out, with nothing but the
standard library (`zipfile` and `xml.etree`), into

    System/generated/extracts/<folder's key>/<path in the folder>.txt

beside the workspace, never committed. Word gives its paragraphs, headings,
lists, tables, footnotes and comments; PowerPoint its slides in order, with
their notes; Excel each sheet by name, its cells row by row, shared and
inline strings alike.

It reads only the files of the one piece of work it is given, as discover.py
counts them: the folder's own files and those of its stage and part folders
(Drafts, Proofs, Research, Photos), or for a group of names in a flat folder,
those files alone. It writes nothing under that folder, and an audit hook
refuses any attempt for the whole run. An extract is made again only when its
file's size or modification time has changed, and removed once its file is
gone. A damaged or password-protected file is reported and skipped; it never
stops the run. Everything else, PDF and text among it, is left to be read as
it is.

`--json` prints one JSON object, for the page. `--root` names the workspace
(default: the one this script is in). Standard library only, Python 3.9 or
later. Exits 1 when it refuses, and says why.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import posixpath
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import discover  # noqa: E402

EXTRACTS = ("System", "generated", "extracts")
MANIFEST = ".extracts.json"
KINDS = {
    ".docx": "word", ".docm": "word", ".dotx": "word", ".dotm": "word",
    ".pptx": "slides", ".pptm": "slides", ".potx": "slides", ".ppsx": "slides", ".ppsm": "slides",
    ".xlsx": "sheets", ".xlsm": "sheets", ".xltx": "sheets", ".xltm": "sheets",
}
SAID_KIND = {"word": "a Word document", "slides": "a PowerPoint presentation", "sheets": "an Excel workbook"}
PART_LIMIT = 64 * 1024 * 1024        # the most any one part of a file may unpack to
TEXT_LIMIT = 4 * 1024 * 1024         # the most text one extract holds
ROW_LIMIT, COLUMN_LIMIT = 20000, 256
OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"   # an encrypted Office file is this container, not a zip

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PR = "{http://schemas.openxmlformats.org/package/2006/relationships}"
MC_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"


class Refusal(Exception):
    """Something the tool will not do, said for the person who asked."""


class Unreadable(Exception):
    """A file whose text cannot be taken out, with why in plain words."""


# ---------------------------------------------------------------- reading the package

def part(z: zipfile.ZipFile, name: str, needed: bool = True) -> Optional[ET.Element]:
    """One XML part of the file, parsed, or None when an optional part is absent."""
    try:
        info = z.getinfo(name)
    except KeyError:
        if needed:
            raise Unreadable("it has no %s, so it is damaged" % name)
        return None
    if info.file_size > PART_LIMIT:
        raise Unreadable("it is too large to read")
    with z.open(info) as fh:
        data = fh.read(PART_LIMIT + 1)
    if len(data) > PART_LIMIT:
        raise Unreadable("it is too large to read")
    if b"<!DOCTYPE" in data[:4096] or b"<!ENTITY" in data:
        raise Unreadable("it holds markup an Office file never has")
    return ET.fromstring(data)


def rels(z: zipfile.ZipFile, source: str) -> Dict[str, Tuple[str, str]]:
    """{id: (type, target part)} for a part, its targets resolved from the part's own folder."""
    folder, name = posixpath.split(source)
    root = part(z, posixpath.join(folder, "_rels", name + ".rels"), needed=False)
    out = {}
    if root is None:
        return out
    for r in root.iter(PR + "Relationship"):
        target = r.get("Target") or ""
        if r.get("TargetMode") == "External":
            continue
        path = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join(folder, target))
        out[r.get("Id") or ""] = (r.get("Type") or "", path)
    return out


def main_part(z: zipfile.ZipFile, fallback: str) -> str:
    for kind, target in rels(z, "").values():
        if kind.endswith("/officeDocument"):
            return target
    return fallback


# ---------------------------------------------------------------- Word

def runs_text(el: ET.Element) -> str:
    """The text of an element in document order: tabs and breaks kept, a paragraph inside it (a text box) on a
    line of its own, deleted text and the fallback copy of a drawing left out."""
    out: List[str] = []

    def visit(node: ET.Element, top: bool) -> None:
        if node.tag == MC_FALLBACK:
            return
        if node.tag == W + "p" and not top:
            out.append("\n")
        if node.tag == W + "t":
            out.append(node.text or "")
        elif node.tag == W + "tab":
            out.append("\t")
        elif node.tag in (W + "br", W + "cr"):
            out.append("\n")
        elif node.tag == W + "noBreakHyphen":
            out.append("-")
        for child in node:
            visit(child, False)
    visit(el, True)
    return re.sub(r"\n{2,}", "\n", "".join(out)).strip()


def paragraph(p: ET.Element) -> str:
    text = runs_text(p)
    if not text:
        return ""
    ppr = p.find(W + "pPr")
    style = ""
    if ppr is not None:
        st = ppr.find(W + "pStyle")
        style = (st.get(W + "val") or "") if st is not None else ""
        if ppr.find(W + "numPr") is not None:
            return "- " + text
    m = re.fullmatch(r"(?i)heading ?([1-6])", style)
    if m:
        return "#" * int(m.group(1)) + " " + text
    if style.lower() == "title":
        return "# " + text
    return text


def block(el: ET.Element, out: List[str]) -> None:
    """Paragraphs and tables, in order, from a body, a cell or a content control."""
    for child in el:
        if child.tag == W + "p":
            text = paragraph(child)
            if text:
                out.append(text)
        elif child.tag == W + "tbl":
            for row in child.iter(W + "tr"):
                cells = []
                for cell in row.findall(W + "tc"):
                    inner: List[str] = []
                    block(cell, inner)
                    cells.append(" ".join(inner))
                if any(cells):
                    out.append(" | ".join(cells))
        elif child.tag in (W + "sdt", W + "sdtContent", W + "customXml", W + "ins", W + "smartTag"):
            block(child, out)


def word(z: zipfile.ZipFile) -> str:
    main = main_part(z, "word/document.xml")
    doc = part(z, main)
    body = doc.find(W + "body")
    out: List[str] = []
    if body is not None:
        block(body, out)
    found = rels(z, main)
    for kind, title, tag in (("/footnotes", "Footnotes", "footnote"), ("/endnotes", "Endnotes", "endnote")):
        target = next((t for k, t in found.values() if k.endswith(kind)), None)
        notes = part(z, target, needed=False) if target else None
        if notes is None:
            continue
        lines = []
        for note in notes.iter(W + tag):
            if note.get(W + "type") in ("separator", "continuationSeparator", "continuationNotice"):
                continue
            inner: List[str] = []
            block(note, inner)
            if inner:
                lines.append("- " + " ".join(inner))
        if lines:
            out += ["## " + title] + lines
    target = next((t for k, t in found.values() if k.endswith("/comments")), None)
    comments = part(z, target, needed=False) if target else None
    if comments is not None:
        lines = []
        for c in comments.iter(W + "comment"):
            inner = []
            block(c, inner)
            if inner:
                who = c.get(W + "author") or "someone"
                lines.append("- %s: %s" % (who, " ".join(inner)))
        if lines:
            out += ["## Comments"] + lines
    return "\n\n".join(out)


# ---------------------------------------------------------------- PowerPoint

def shape_text(root: ET.Element, skip_placeholders=()) -> List[str]:
    """Each paragraph of text in a slide or its notes, in order, leaving out the placeholders named."""
    out = []

    def visit(node: ET.Element) -> None:
        if node.tag == MC_FALLBACK:
            return
        if node.tag == P + "sp" and skip_placeholders:
            ph = node.find("%snvSpPr/%snvPr/%sph" % (P, P, P))
            if ph is not None and ph.get("type") in skip_placeholders:
                return
        if node.tag == A + "p":
            bits = []
            for el in node.iter():
                if el.tag == A + "t":
                    bits.append(el.text or "")
                elif el.tag == A + "br":
                    bits.append("\n")
            text = "".join(bits).strip()
            if text:
                out.append(text)
            return
        for child in node:
            visit(child)
    visit(root)
    return out


def slides(z: zipfile.ZipFile) -> str:
    main = main_part(z, "ppt/presentation.xml")
    pres = part(z, main)
    found = rels(z, main)
    order = []
    lst = pres.find(P + "sldIdLst")
    for sid in (lst if lst is not None else []):
        rid = sid.get(R + "id")
        if rid in found:
            order.append(found[rid][1])
    out = []
    for n, target in enumerate(order, 1):
        slide = part(z, target, needed=False)
        if slide is None:
            continue
        hidden = " (hidden)" if slide.get("show") == "0" else ""
        lines = ["## Slide %d%s" % (n, hidden)] + shape_text(slide)
        notes_target = next((t for k, t in rels(z, target).values() if k.endswith("/notesSlide")), None)
        notes = part(z, notes_target, needed=False) if notes_target else None
        if notes is not None:
            said = shape_text(notes, ("sldImg", "sldNum", "hdr", "ftr", "dt"))
            if said:
                lines.append("Notes: " + "\n".join(said))
        out.append("\n".join(lines))
    return "\n\n".join(out)


# ---------------------------------------------------------------- Excel

def column(ref: str) -> Optional[int]:
    m = re.match(r"([A-Z]+)", ref or "")
    if not m:
        return None
    n = 0
    for ch in m.group(1):
        n = n * 26 + ord(ch) - 64
    return n - 1


def string_item(si: ET.Element) -> str:
    """The text of a shared or inline string: its runs, without phonetic readings."""
    bits = []

    def visit(node: ET.Element) -> None:
        if node.tag == S + "rPh":
            return
        if node.tag == S + "t":
            bits.append(node.text or "")
        for child in node:
            visit(child)
    visit(si)
    return "".join(bits)


def sheets(z: zipfile.ZipFile) -> str:
    main = main_part(z, "xl/workbook.xml")
    book = part(z, main)
    found = rels(z, main)
    shared: List[str] = []
    target = next((t for k, t in found.values() if k.endswith("/sharedStrings")), None)
    sst = part(z, target, needed=False) if target else None
    if sst is not None:
        shared = [string_item(si) for si in sst.findall(S + "si")]
    out = []
    listed = book.find(S + "sheets")
    for sh in (listed if listed is not None else []):
        name = sh.get("name") or "Sheet"
        kind, path = found.get(sh.get(R + "id") or "", ("", ""))
        if not kind.endswith("/worksheet"):
            continue
        ws = part(z, path, needed=False)
        if ws is None:
            continue
        state = " (hidden)" if sh.get("state") in ("hidden", "veryHidden") else ""
        lines = ["## Sheet: %s%s" % (name, state)]
        data = ws.find(S + "sheetData")
        rows = 0
        for row in (data if data is not None else []):
            if row.tag != S + "row":
                continue
            rows += 1
            if rows > ROW_LIMIT:
                lines.append("(more rows, not taken out)")
                break
            cells: Dict[int, str] = {}
            nxt = 0
            for c in row.findall(S + "c"):
                col = column(c.get("r") or "")
                col = nxt if col is None else col
                nxt = col + 1
                if col >= COLUMN_LIMIT:
                    continue
                kind_c = c.get("t") or "n"
                v = c.find(S + "v")
                raw = v.text if v is not None and v.text is not None else ""
                if kind_c == "s":
                    try:
                        value = shared[int(raw)]
                    except (ValueError, IndexError):
                        value = ""
                elif kind_c == "inlineStr":
                    is_ = c.find(S + "is")
                    value = string_item(is_) if is_ is not None else ""
                elif kind_c == "b":
                    value = "TRUE" if raw == "1" else "FALSE" if raw == "0" else raw
                else:
                    value = raw
                value = value.replace("\t", " ").replace("\r", " ").replace("\n", " ").strip()
                if value:
                    cells[col] = value
            if cells:
                width = max(cells) + 1
                lines.append("\t".join(cells.get(i, "") for i in range(width)))
        out.append("\n".join(lines))
    return "\n\n".join(out)


READERS = {"word": word, "slides": slides, "sheets": sheets}


def text_of(path: str, kind: str) -> str:
    """The text of one file, or Unreadable saying why not."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(8)
    except OSError:
        raise Unreadable("it could not be opened")
    if head == OLE:
        raise Unreadable("it is protected by a password, or saved in an older format")
    try:
        with zipfile.ZipFile(path) as z:
            text = READERS[kind](z)
    except Unreadable:
        raise
    except (zipfile.BadZipFile, zipfile.LargeZipFile, ET.ParseError, KeyError, ValueError, EOFError,
            NotImplementedError, RuntimeError, OSError, IndexError, AttributeError, TypeError):
        raise Unreadable("it is damaged, or not the kind of file its name says")
    if len(text) > TEXT_LIMIT:
        text = text[:TEXT_LIMIT] + "\n\n(The rest of the text is not taken out: the file is very long.)"
    return text


# ---------------------------------------------------------------- the extracts

def extracts_dir(root: Path, key: str) -> Path:
    return root.joinpath(*EXTRACTS) / key


def read_manifest(folder: Path) -> dict:
    try:
        data = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) and isinstance(data.get("files"), dict) else {}


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(".%s.%d.tmp" % (path.name, os.getpid()))
    tmp.write_text(text, encoding="utf-8")
    os.replace(str(tmp), str(path))


def prune(folder: Path, start: Path) -> None:
    """Remove the empty folders from `start` up to, not including, `folder`."""
    here = start
    while here != folder and folder in here.parents:
        try:
            here.rmdir()
        except OSError:
            return
        here = here.parent


def run(root: Path, source: str, files: Optional[List[str]] = None, key: Optional[str] = None,
        today: Optional[str] = None) -> dict:
    """Bring the extracts of one piece of work up to date. `files`, paths in `source`, narrows it to a group
    of names; without it, the piece of work is the folder as discover.py counts it."""
    real = os.path.realpath(os.path.expanduser(source))
    if not os.path.isdir(real):
        raise Refusal("There is no folder at %s." % source)
    ws = os.path.realpath(str(root))
    if discover._within(ws, real):
        raise Refusal("That folder holds Garrick itself, so its text cannot be taken out beside it.")
    key = key or discover.folder_key(real)
    if not re.fullmatch(r"[\w .&'-]+", key) or key.startswith("."):
        raise Refusal("%s cannot name a folder of extracts." % key)
    out_dir = extracts_dir(root, key)
    with discover.guard(real, reads=False):
        if files is None:
            listed = sorted(f.rel for f in discover.work_files(real))
        else:
            listed = []
            for rel in files:
                parts = Path(rel).parts
                path = os.path.join(real, rel)
                if os.path.isabs(rel) or ".." in parts or not parts:
                    raise Refusal("%s is not a file of that folder." % rel)
                if os.path.isfile(path) and not os.path.islink(path) and not discover.is_junk(os.path.basename(rel)):
                    listed.append(Path(rel).as_posix())
            listed.sort()
        manifest = read_manifest(out_dir)
        known: Dict[str, dict] = manifest.get("files", {}) if manifest else {}
        result = {"folder": real, "key": key, "extracts": "/".join(EXTRACTS + (key,)),
                  "made": [], "kept": [], "removed": [], "unreadable": [], "others": []}
        now: Dict[str, dict] = {}
        for rel in listed:
            kind = KINDS.get(os.path.splitext(rel)[1].lower())
            if not kind:
                result["others"].append(rel)
                continue
            path = os.path.join(real, rel)
            try:
                st = os.stat(path, follow_symlinks=False)
            except OSError:
                continue
            seen = {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "kind": kind}
            before = known.get(rel)
            target = out_dir / (rel + ".txt")
            same = before is not None and before.get("size") == st.st_size and before.get("mtime_ns") == st.st_mtime_ns
            if same and (before.get("why") or target.is_file()):
                now[rel] = before
                if before.get("why"):
                    result["unreadable"].append({"file": rel, "why": before["why"]})
                else:
                    result["kept"].append(rel)
                continue
            try:
                text = text_of(path, kind)
            except Unreadable as exc:
                seen["why"] = str(exc)
                now[rel] = seen
                result["unreadable"].append({"file": rel, "why": str(exc)})
                if target.is_file():
                    target.unlink()
                    prune(out_dir, target.parent)
                continue
            saved = datetime.datetime.fromtimestamp(st.st_mtime).date().isoformat()
            head = "The text of %s, %s saved %s, taken out by Garrick. The file itself is the record.\n\n" % (
                rel, SAID_KIND[kind], saved)
            write_text(target, head + text + "\n")
            now[rel] = seen
            result["made"].append(rel)
        for rel in sorted(set(known) - set(now)):
            target = out_dir / (rel + ".txt")
            if target.is_file():
                target.unlink()
                prune(out_dir, target.parent)
            result["removed"].append(rel)
        if now or out_dir.is_dir():
            out_dir.mkdir(parents=True, exist_ok=True)
            write_text(out_dir / MANIFEST, json.dumps({"folder": real, "files": now, "updated": today or
                                                       datetime.date.today().isoformat()},
                                                      indent=1, ensure_ascii=False, sort_keys=True) + "\n")
    result["said"] = say(result)
    return result


def work(root: Path, pid: str) -> Tuple[str, Optional[List[str]], str]:
    """(folder, files or None, key) for a piece of work discover.py recorded under `pid`."""
    data = discover.load(root)
    for real, entry in data["folders"].items():
        found = [p for p in entry.get("top", []) + entry.get("more", []) + entry.get("confirmed", [])
                 if p.get("id") == pid]
        found += [dict(a, id=pid) for i, a in entry.get("answers", {}).items() if i == pid and a.get("path")]
        if found:
            p = found[0]
            if p.get("kind") == "names":
                return real, list(p.get("members") or []), "%s-%s" % (discover.folder_key(real), pid)
            return p.get("path") or real, None, discover.folder_key(p.get("path") or real)
    raise Refusal("No piece of work has the id %s. discover.py list shows them." % pid)


def say(result: dict) -> str:
    made, kept, gone, bad = result["made"], result["kept"], result["removed"], result["unreadable"]
    if not (made or kept or gone or bad):
        return "There is no Word, PowerPoint or Excel file here; the rest can be read as it is."
    parts = []
    if made:
        parts.append("%d taken out" % len(made))
    if kept:
        parts.append("%d unchanged" % len(kept))
    if gone:
        parts.append("%d removed, their files gone" % len(gone))
    lines = ["Text of the Word, PowerPoint and Excel files: " + ", ".join(parts) + "." if parts
             else "No Word, PowerPoint or Excel file could be read."]
    for b in bad:
        lines.append("Not read: %s, because %s." % (b["file"], b["why"]))
    if result["others"]:
        lines.append("%d other files can be read as they are." % len(result["others"]))
    if made or kept:
        lines.append("The text is in %s/." % result["extracts"])
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Take the text out of a piece of work's Word, PowerPoint and Excel files.")
    ap.add_argument("folder", nargs="?", help="the folder of the piece of work")
    ap.add_argument("--work", help="the id discover.py gave the piece of work, instead of a folder")
    ap.add_argument("--root", help="the workspace folder (default: the one this script is in)")
    ap.add_argument("--json", action="store_true", help="print the result as JSON")
    args = ap.parse_args(argv)
    root = Path(args.root).expanduser().resolve() if args.root else Path(__file__).resolve().parents[2]
    try:
        if bool(args.folder) == bool(args.work):
            raise Refusal("Name the folder of the piece of work, or its id with --work, not both.")
        if args.work:
            folder, files, key = work(root, args.work)
            out = run(root, folder, files, key)
        else:
            out = run(root, args.folder)
    except Refusal as exc:
        if args.json:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        else:
            print(exc, file=sys.stderr)
        return 1
    print(json.dumps(out, ensure_ascii=False, indent=1) if args.json else out["said"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
