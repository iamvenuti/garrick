#!/usr/bin/env python3
"""What a project published, and whether the shared copy has drifted from it.

    python3 System/tools/drift.py                 every project's ledger, compared
    python3 System/tools/drift.py --json          the same, as JSON
    python3 System/tools/drift.py --save          ... and kept in System/generated/drift.json for the status page

A file that leaves the workspace, a deck or a workbook copied to a shared
cloud folder, is one row in its project's `Deliverables/published.md`:

    | Date | File | Destination | Recipients | Authoritative |
    |---|---|---|---|---|
    | 2026-10-01 | `260930 - Pricing deck.pptx` | `Decks/Pricing deck.pptx` | Dana, Owen | share |

`File` is the project's copy, under `Deliverables/`. `Destination` is the
shared copy, relative to the folder the hub names in its `shared:` key, or
`<link>:<path>` for another folder linked under the zone's `.shared/`. The
hub's key names its folder the same way, `<link>/<path>`, through a link in
`Zones/<Zone>/.shared/`: never by the provider's own path, which changes
when an account or library is renamed. `Authoritative` says which copy wins
from now on: `share` when colleagues edit it there, `here` when they only
read it. Only its first word is read, so a note may follow: `share,
colleagues edit the wording there`.

A row stays as the record of what left. When a copy is taken off the share,
or a newer version takes its place, its date cell becomes `withdrawn
YYYY-MM-DD` or `replaced YYYY-MM-DD`, the day it happened; a copy sent by
mail rather than placed on a share is `sent YYYY-MM-DD`. Such a row is
history: read, never compared. Only the table whose first column is `Date`
is the ledger; another table in the same file is left alone.

A thread-first project (`layout: thread-first` on its hub) keeps one ledger
per thread, `Threads/<Thread>/Deliverables/published.md`, its files under
that thread's `Deliverables/`. Both places are read in every project.

Drift is a real difference. A file is compared byte for byte, except an
Office file (.docx, .xlsx, .pptx), which a shared library rewrites on every
upload and Office on every save: its parts are compared as a set of names,
its relationships as a set of what points to what, and its XML in canonical
form, leaving out the provider's own parts (customXml/, and the properties
in docProps/, which record who saved it when). A copy the provider keeps
online only, with no bytes on this Mac, is never downloaded: it is reported
as unchecked. An Office file saved with a password is reported apart.

macOS keeps a scheduled job out of ~/Library/CloudStorage, so this runs
from a session or the app, never from launchd. It changes nothing but
System/generated/drift.json, and only with --save.

Standard library only, Python 3.9 or later.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import sys
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from garrick_lib import parse_frontmatter, workspace_root  # noqa: E402

LEDGER = ("Deliverables", "published.md")
LINKS = ".shared"
OFFICE = {".docx", ".xlsx", ".pptx", ".docm", ".xlsm", ".pptm"}
PROVIDER = re.compile(r"^(?:customXml/|docProps/|\[trash\]/)", re.I)   # the provider's parts, and what Excel leaves after a save
OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"          # an encrypted Office file is an OLE container, not a zip
ROW = re.compile(r"^\|\s*(\d{4}-\d{2}-\d{2})\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|([^|]*)\|\s*(share|here)\b([^|]*)\|\s*$", re.I)
HISTORY = re.compile(r"^\|\s*(withdrawn|replaced|sent)\s+(\d{4}-\d{2}-\d{2})\s*\|", re.I)
HEADER = re.compile(r"^\|\s*Date\s*\|", re.I)
RULE = re.compile(r"^\|[\s:|-]+\|$")
SAVED = ("System", "generated", "drift.json")
HISTORY_WORDS = ("withdrawn", "replaced", "sent")


# --------------------------------------------------------------------------- the ledger


def ledger_rows(path: Path) -> Tuple[List[dict], List[str]]:
    """(rows, lines that look like rows but do not read) of a published.md.
    Only the table under a `| Date |` header is read; a history row comes
    back with `history` set to its word and is never compared."""
    rows, bad = [], []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return rows, bad
    headed = any(HEADER.match(line.strip()) for line in lines)
    in_ledger = not headed                           # with no `| Date |` header, every table is read, as before
    for line in lines:
        s = line.strip()
        if not s.startswith("|"):
            in_ledger = not headed                   # a table ends at its first line that is not a row
            continue
        if HEADER.match(s):
            in_ledger = True
            continue
        if not in_ledger or RULE.match(s):
            continue
        h = HISTORY.match(s)
        if h:
            cells = [c.strip() for c in s.strip("|").split("|")]
            rows.append({"date": h.group(2), "history": h.group(1).lower(), "file": cells[1].strip("`") if len(cells) > 1 else "",
                         "destination": cells[2].strip("`") if len(cells) > 2 else "",
                         "recipients": cells[3] if len(cells) > 3 else "",
                         "authoritative": cells[4].split(None, 1)[0].strip(",;.:").lower() if len(cells) > 4 and cells[4] else ""})
            continue
        m = ROW.match(s)
        if not m:
            bad.append(s)
            continue
        rows.append({"date": m.group(1), "file": m.group(2), "destination": m.group(3),
                     "recipients": m.group(4).strip(), "authoritative": m.group(5).lower(),
                     "note": m.group(6).strip(" ,;:—–-")})
    return rows, bad


def shared_root(zone: Path, value: str) -> Optional[Path]:
    """The folder a `<link>/<path>` names, through Zones/<Zone>/.shared/<link>.
    None when the link is missing or the value climbs out."""
    parts = [p for p in str(value or "").strip().strip("/").split("/") if p]
    if not parts or any(p in ("..", ".") for p in parts):
        return None
    link = zone / LINKS / parts[0]
    if not link.exists():
        return None
    return link.joinpath(*parts[1:])


def destination(zone: Path, hub_shared: Optional[Path], value: str) -> Optional[Path]:
    if value.startswith(("/", "~")) or "\\" in value:
        return None                                  # only ever inside a linked shared folder
    if ":" in value:
        link, _, rest = value.partition(":")
        base = shared_root(zone, link)
        return base / rest if base is not None and ".." not in Path(rest).parts else None
    if hub_shared is None or ".." in Path(value).parts:
        return None
    return hub_shared / value


# --------------------------------------------------------------------------- comparing


def online_only(path: Path) -> bool:
    """A cloud copy with no bytes on this Mac: reading it would download it."""
    try:
        st = path.stat()
    except OSError:
        return False
    return st.st_size > 0 and getattr(st, "st_blocks", 1) == 0


def _canonical(data: bytes) -> bytes:
    try:
        return ET.canonicalize(data.decode("utf-8", errors="replace"), strip_text=True).encode("utf-8")
    except ET.ParseError:
        return data


def _relationships(data: bytes) -> frozenset:
    try:
        tree = ET.fromstring(data)
    except ET.ParseError:
        return frozenset([data])
    return frozenset((el.get("Type"), el.get("Target"), el.get("TargetMode"))
                     for el in tree if not PROVIDER.match((el.get("Target") or "").lstrip("/").replace("../", "")))


def _content_types(data: bytes) -> frozenset:
    try:
        tree = ET.fromstring(data)
    except ET.ParseError:
        return frozenset([data])
    return frozenset((el.tag.rsplit("}", 1)[-1], el.get("PartName") or el.get("Extension"), el.get("ContentType"))
                     for el in tree if not PROVIDER.match((el.get("PartName") or "").lstrip("/")))


def office_form(data: bytes) -> Dict[str, object]:
    """An Office file as what a save leaves unchanged: each part but the
    provider's, XML in canonical form, relationships and content types as sets."""
    import io
    out: Dict[str, object] = {}
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in z.namelist():
            if name.endswith("/") or PROVIDER.match(name):
                continue
            raw = z.read(name)
            if name.endswith(".rels"):
                out[name] = _relationships(raw)
            elif name == "[Content_Types].xml":
                out[name] = _content_types(raw)
            elif name.endswith(".xml"):
                out[name] = _canonical(raw)
            else:
                out[name] = hashlib.sha256(raw).hexdigest()
    return out


def compare(ours: Path, theirs: Path) -> Tuple[str, str]:
    """(state, what differs): same, drifted, unchecked, missing, encrypted."""
    if not ours.is_file():
        return "missing", "the project's copy, %s, is not there" % ours.name
    if not theirs.exists():
        return "missing", "the shared copy is not there"
    if online_only(theirs):
        return "unchecked", "the shared copy is online only; open it once to keep a copy on this Mac"
    try:
        a, b = ours.read_bytes(), theirs.read_bytes()
    except OSError as exc:
        return "unchecked", "the shared copy could not be read: %s" % (exc.strerror or exc)
    if a == b:
        return "same", ""
    if ours.suffix.lower() not in OFFICE:
        return "drifted", "the bytes differ"
    if b.startswith(OLE) or a.startswith(OLE):
        return "encrypted", "one copy is saved with a password, so its content cannot be compared"
    try:
        fa, fb = office_form(a), office_form(b)
    except Exception as exc:      # a half-synced or damaged file: zip, zlib, EOF and parse errors alike
        return "drifted", "one copy does not open as an Office file (%s)" % (str(exc)[:80] or type(exc).__name__)
    if fa == fb:
        return "same", ""
    parts = sorted(set(fa) ^ set(fb)) + sorted(k for k in set(fa) & set(fb) if fa[k] != fb[k])
    return "drifted", "%s differ%s" % (", ".join(parts[:4]) + (" and %d more" % (len(parts) - 4) if len(parts) > 4 else ""),
                                      "s" if len(parts) == 1 else "")


# --------------------------------------------------------------------------- the workspace


def _visible(folder: Path) -> List[Path]:
    return sorted(p for p in (folder.iterdir() if folder.is_dir() else []) if p.is_dir() and not p.name.startswith((".", "_")))


def ledgers(project: Path) -> List[Tuple[Optional[str], Path]]:
    """(thread or None, its Deliverables/ folder) for every ledger of a
    project: its own, and one per thread, as a thread-first project keeps them."""
    out = [(None, project / LEDGER[0])] + [(t.name, t / LEDGER[0]) for t in _visible(project / "Threads")]
    return [(t, d) for t, d in out if (d / LEDGER[1]).is_file()]


def projects(root: Path):
    for zone in _visible(root / "Zones"):
        for project in _visible(zone):
            for thread, folder in ledgers(project):
                yield zone, project, thread, folder


def survey(root: Path) -> List[dict]:
    out = []
    for zone, project, thread, folder in projects(root):
        hub = project / (project.name + ".md")
        value = parse_frontmatter(hub).get("shared") if hub.is_file() else None
        hub_shared = shared_root(zone, value) if value else None
        rows, bad = ledger_rows(folder / LEDGER[1])
        where = {"zone": zone.name, "project": project.name}
        if thread:
            where["thread"] = thread
        for line in bad:
            out.append(dict(where, state="unread", file="",
                            say="a row of published.md does not read as Date | `file` | `destination` | recipients | "
                                "share or here: %s" % line[:80]))
        for row in rows:
            if row.get("history"):
                out.append(dict(where, file=row["file"], destination=row["destination"], date=row["date"],
                                state=row["history"], say=""))
                continue
            ours = folder / row["file"]
            if row["file"].startswith(("/", "~")) or ".." in Path(row["file"]).parts:
                out.append(dict(where, file=row["file"], state="unread", say="the file must be a path under Deliverables/"))
                continue
            theirs = destination(zone, hub_shared, row["destination"])
            if theirs is None:
                state, say = "unchecked", ("the hub names no shared folder, `shared:`, through a link in %s/%s/"
                                           % (zone.name, LINKS) if ":" not in row["destination"]
                                           else "no link %s in %s/%s/" % (row["destination"].split(":")[0], zone.name, LINKS))
            else:
                state, say = compare(ours, theirs)
            out.append(dict(where, file=row["file"], destination=row["destination"], authoritative=row["authoritative"],
                            date=row["date"], state=state, say=say))
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Compare what each project published with its shared copy.")
    ap.add_argument("--root", help="the workspace (default: the one this script sits in)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--save", action="store_true", help="keep the result in System/generated/drift.json")
    a = ap.parse_args(argv)
    try:
        root = Path(a.root).expanduser().resolve() if a.root else workspace_root(HERE)
    except FileNotFoundError:
        print("drift: not inside a Garrick workspace", file=sys.stderr)
        return 2
    found = survey(root)
    if a.save:
        target = root.joinpath(*SAVED)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"checked": datetime.datetime.now().isoformat(timespec="seconds"), "files": found},
                                  indent=1) + "\n", encoding="utf-8")
        os.replace(tmp, target)
    if a.json:
        print(json.dumps(found, indent=1))
    else:
        if not found:
            print("No project has published anything yet.")
        for f in found:
            if f["state"] in HISTORY_WORDS:
                continue                                 # the record of what left, not something to look at
            print("%s, %s: %s%s%s" % (f["zone"], f["project"] + (", " + f["thread"] if f.get("thread") else ""),
                                      f["file"] or "published.md",
                                      ": " + f["state"] if f["state"] != "same" else ": the same",
                                      " (%s)" % f["say"] if f["say"] else ""))
    return 1 if any(f["state"] in ("drifted", "missing", "unread") for f in found) else 0


if __name__ == "__main__":
    sys.exit(main())
