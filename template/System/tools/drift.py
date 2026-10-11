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
read it.

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
PROVIDER = re.compile(r"^(?:customXml/|docProps/)", re.I)
OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"          # an encrypted Office file is an OLE container, not a zip
ROW = re.compile(r"^\|\s*(\d{4}-\d{2}-\d{2})\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|([^|]*)\|\s*(\w+)\s*\|\s*$")
SAVED = ("System", "generated", "drift.json")


# --------------------------------------------------------------------------- the ledger


def ledger_rows(path: Path) -> Tuple[List[dict], List[str]]:
    """(rows, lines that look like rows but do not read) of a published.md."""
    rows, bad = [], []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return rows, bad
    for line in lines:
        s = line.strip()
        if not s.startswith("|") or re.match(r"^\|\s*(?:Date|-{3})", s, re.I):
            continue
        m = ROW.match(s)
        if not m:
            bad.append(s)
            continue
        rows.append({"date": m.group(1), "file": m.group(2), "destination": m.group(3),
                     "recipients": m.group(4).strip(), "authoritative": m.group(5).lower()})
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
    except (zipfile.BadZipFile, KeyError, ValueError) as exc:
        return "drifted", "one copy does not open as an Office file (%s)" % exc
    if fa == fb:
        return "same", ""
    parts = sorted(set(fa) ^ set(fb)) + sorted(k for k in set(fa) & set(fb) if fa[k] != fb[k])
    return "drifted", "%s differ%s" % (", ".join(parts[:4]) + (" and %d more" % (len(parts) - 4) if len(parts) > 4 else ""),
                                      "s" if len(parts) == 1 else "")


# --------------------------------------------------------------------------- the workspace


def projects(root: Path):
    zones = root / "Zones"
    for zone in sorted(z for z in (zones.iterdir() if zones.is_dir() else []) if z.is_dir() and not z.name.startswith((".", "_"))):
        for project in sorted(p for p in zone.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))):
            if project.joinpath(*LEDGER).is_file():
                yield zone, project


def survey(root: Path) -> List[dict]:
    out = []
    for zone, project in projects(root):
        hub = project / (project.name + ".md")
        value = parse_frontmatter(hub).get("shared") if hub.is_file() else None
        hub_shared = shared_root(zone, value) if value else None
        rows, bad = ledger_rows(project.joinpath(*LEDGER))
        for line in bad:
            out.append({"zone": zone.name, "project": project.name, "state": "unread", "file": "",
                        "say": "a row of published.md does not read as Date | `file` | `destination` | recipients | "
                               "authoritative: %s" % line[:80]})
        for row in rows:
            ours = project / "Deliverables" / row["file"]
            theirs = destination(zone, hub_shared, row["destination"])
            if theirs is None:
                state, say = "unchecked", ("the hub names no shared folder, `shared:`, through a link in %s/%s/"
                                           % (zone.name, LINKS) if ":" not in row["destination"]
                                           else "no link %s in %s/%s/" % (row["destination"].split(":")[0], zone.name, LINKS))
            else:
                state, say = compare(ours, theirs)
            out.append({"zone": zone.name, "project": project.name, "file": row["file"],
                        "destination": row["destination"], "authoritative": row["authoritative"],
                        "date": row["date"], "state": state, "say": say})
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
            print("%s, %s: %s%s%s" % (f["zone"], f["project"], f["file"] or "published.md",
                                      ": " + f["state"] if f["state"] != "same" else ": the same",
                                      " (%s)" % f["say"] if f["say"] else ""))
    return 1 if any(f["state"] in ("drifted", "missing", "unread") for f in found) else 0


if __name__ == "__main__":
    sys.exit(main())
