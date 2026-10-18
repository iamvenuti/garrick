#!/usr/bin/env python3
"""Put the worked example away, and bring it back.

    python3 System/tools/example.py status
    python3 System/tools/example.py archive
    python3 System/tools/example.py restore

The example is someone else's ordinary work, laid down so Garrick can be tried
on it: a zone of its own, its shared drive in the workspace's top folder, and
its party and people in System/context.md. The zone names all three in its
`.example.json`.

`archive` moves the zone, the drive and those rows of context.md into one
folder, `.archive/<Zone>/`, which no repository commits, and takes the zone's
files out of the version stamp. `restore` puts each back where it was, exactly.
Neither touches anything else: no other zone, no other row, no file of yours.
Each commits System/context.md and the stamp in the workspace's own
repository, unless either already had changes of yours not yet committed;
those are left for you to commit with your own.

`--json` prints the result as one JSON object, for the status page. Standard
library only. Exits 1 when it refuses, and says why.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from garrick_lib import ARCHIVE, EXAMPLE_MANIFEST, VERSION_STAMP, strip_tag  # noqa: E402

CONTEXT = ("System", "context.md")
ARCHIVED = "archived.json"
# The tables of context.md whose rows leave with the example, in the order they are read.
TABLES = ("Zones", "Parties", "People", "Walls", "Aliases")


class Refusal(Exception):
    """Something the tool will not do, said for the person who asked."""


# --------------------------------------------------------------------------- finding it


def read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def present(root: Path) -> Optional[Tuple[Path, dict]]:
    """The example's zone and its manifest, when the example is in the workspace."""
    zones = root / "Zones"
    for zone in sorted(zones.iterdir()) if zones.is_dir() else []:
        manifest = zone / EXAMPLE_MANIFEST
        if zone.is_dir() and manifest.is_file():
            data = read_json(manifest)
            if data.get("zone") == zone.name:
                return zone, data
    return None


def put_away(root: Path) -> Optional[Tuple[Path, dict]]:
    """The archive folder and what it records, when the example was archived."""
    archive = root / ARCHIVE
    for folder in sorted(archive.iterdir()) if archive.is_dir() else []:
        record = folder / ARCHIVED
        if folder.is_dir() and record.is_file():
            data = read_json(record)
            if data.get("zone") == folder.name:
                return folder, data
    return None


def drive_of(root: Path, manifest: dict) -> Optional[Path]:
    """The drive the manifest names: one folder of the workspace's top folder,
    never a zone, a wiki, System or anything above."""
    name = str(manifest.get("drive") or "").strip()
    if not name or "/" in name or "\\" in name or name in (".", "..") or name.startswith("."):
        return None
    if name.lower() in ("zones", "wikis", "system", "inbox"):
        return None
    return root / name


def status(root: Path) -> dict:
    here = present(root)
    if here:
        zone, manifest = here
        drive = drive_of(root, manifest)
        return {"state": "here", "name": manifest.get("name", ""), "zone": zone.name,
                "drive": drive.name if drive is not None and drive.is_dir() else ""}
    away = put_away(root)
    if away:
        folder, record = away
        return {"state": "archived", "name": record.get("name", ""), "zone": record["zone"],
                "drive": record.get("drive", ""), "archived": record.get("archived", ""),
                "where": folder.relative_to(root).as_posix()}
    return {"state": "none"}


# --------------------------------------------------------------------------- context.md rows


def split_row(line: str) -> List[str]:
    inner = line.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|"):
        inner = inner[:-1]
    return [c.strip() for c in inner.replace("\\|", "\0").split("|")]


def section_bounds(lines: List[str], heading: str) -> Optional[Tuple[int, int]]:
    """(the heading's line, the line where the next section starts)."""
    start = next((i for i, l in enumerate(lines) if l.strip().lower() == "## " + heading.lower()), None)
    if start is None:
        return None
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return start, end


def table_of(lines: List[str], start: int, end: int) -> Tuple[List[str], List[int]]:
    """A section's table: its column names, lower case, and the lines of its data rows."""
    rows = [i for i in range(start + 1, end) if lines[i].lstrip().startswith("|")]
    if len(rows) < 2:
        return [], []
    header = [c.lower() for c in split_row(lines[rows[0]])]
    return header, rows[2:]


def cell(header: List[str], cells: List[str], *names: str) -> str:
    for name in names:
        if name in header and header.index(name) < len(cells):
            return cells[header.index(name)]
    return ""


def example_rows(lines: List[str], zone: str) -> List[int]:
    """The lines of context.md that belong to the example: its zone's row, its
    parties, their people and walls, and the aliases that mean any of them."""
    picked: List[int] = []
    tags, names = set(), set()
    for heading in TABLES:
        bounds = section_bounds(lines, heading)
        if bounds is None:
            continue
        header, rows = table_of(lines, *bounds)
        for i in rows:
            cells = split_row(lines[i])
            if heading == "Zones":
                hit = cell(header, cells, "zone") == zone
            elif heading == "Parties":
                hit = cell(header, cells, "zone") == zone
                if hit:
                    tags.add(strip_tag(cell(header, cells, "tag")))
                    names.add(cell(header, cells, "party").strip("*").lower())
            elif heading == "People":
                hit = strip_tag(cell(header, cells, "party")) in tags
                if hit:
                    names.add(cell(header, cells, "name").lower())
            elif heading == "Walls":
                hit = bool({strip_tag(cell(header, cells, "between")), strip_tag(cell(header, cells, "and"))} & tags)
            else:
                hit = cell(header, cells, "means").lower() in names
            if hit:
                picked.append(i)
    return picked


def take_rows(text: str, zone: str) -> Tuple[str, List[dict]]:
    """context.md without the example's rows, and each row with what stood above it."""
    lines = text.split("\n")
    picked = example_rows(lines, zone)
    taken = []
    for i in picked:
        heading = next(lines[j][3:].strip() for j in range(i, -1, -1) if lines[j].startswith("## "))
        taken.append({"section": heading, "line": lines[i], "after": lines[i - 1]})
    kept = [l for i, l in enumerate(lines) if i not in set(picked)]
    return "\n".join(kept), taken


def put_rows(text: str, rows: List[dict]) -> str:
    """context.md with the rows back: each after the line that stood above it
    when that line is still in its section, else at the end of the section's
    table. In the order they were taken, so a run of rows comes back as a run."""
    lines = text.split("\n")
    for row in rows:
        bounds = section_bounds(lines, row["section"])
        if bounds is None:
            lines += ["", "## " + row["section"], "", row["line"]]
            continue
        start, end = bounds
        at = next((i + 1 for i in range(start, end) if lines[i] == row["after"]), None)
        if at is None:
            table = [i for i in range(start + 1, end) if lines[i].lstrip().startswith("|")]
            at = table[-1] + 1 if table else end
        lines.insert(at, row["line"])
    return "\n".join(lines)


# --------------------------------------------------------------------------- the version stamp


def take_stamp(root: Path, zone: str) -> Tuple[Optional[str], Dict[str, str]]:
    """The stamp's text without the zone's files, and those files, or (None, {})."""
    path = root.joinpath(*VERSION_STAMP)
    stamp = read_json(path)
    files = stamp.get("files")
    if not isinstance(files, dict):
        return None, {}
    prefix = "Zones/%s/" % zone
    mine = {k: v for k, v in files.items() if k.startswith(prefix)}
    if not mine:
        return None, {}
    stamp["files"] = {k: v for k, v in files.items() if not k.startswith(prefix)}
    return json.dumps(stamp, indent=2) + "\n", mine


def put_stamp(root: Path, files: Dict[str, str]) -> Optional[str]:
    path = root.joinpath(*VERSION_STAMP)
    stamp = read_json(path)
    if not files or not isinstance(stamp.get("files"), dict):
        return None
    stamp["files"] = dict(sorted({**stamp["files"], **files}.items()))
    return json.dumps(stamp, indent=2) + "\n"


# --------------------------------------------------------------------------- git


def git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)


def clean(root: Path, rels: List[str]) -> Dict[str, bool]:
    """Whether each file is as the workspace's repository last committed it."""
    if not (root / ".git").exists():
        return {r: False for r in rels}
    out = {}
    for r in rels:
        res = git(root, "status", "--porcelain", "--", r)
        out[r] = res.returncode == 0 and not res.stdout.strip()
    return out


def commit(root: Path, rels: List[str], was_clean: Dict[str, bool], message: str) -> str:
    """Commit the files the tool changed, by name, when none had changes of
    yours; otherwise say what is left to commit."""
    changed = [r for r in rels if git(root, "status", "--porcelain", "--", r).stdout.strip()]
    if not changed:
        return ""
    if not (root / ".git").exists():
        return "The workspace's top folder is not a git repository, so nothing was committed."
    if not all(was_clean.get(r) for r in changed):
        return ("%s had changes of yours not yet committed, so this change is left beside them: commit them "
                "together in the workspace's own repository." % " and ".join(changed))
    res = git(root, "-c", "commit.gpgsign=false", "commit", "-q", "-m", message, "--", *changed)
    if res.returncode != 0:
        return "The change to %s is made but could not be committed: %s" % (
            " and ".join(changed), " ".join((res.stderr or res.stdout).split()))
    return ""


# --------------------------------------------------------------------------- archive and restore


def move(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    os.rename(str(src), str(dst))


def archive(root: Path, today: str) -> dict:
    here = present(root)
    if not here:
        if put_away(root):
            raise Refusal("The example is already put away. To bring it back: example.py restore.")
        raise Refusal("There is no example in this workspace.")
    zone, manifest = here
    drive = drive_of(root, manifest)
    folder = root / ARCHIVE / zone.name
    if folder.exists():
        raise Refusal("%s is already there, from an earlier archive. Move it aside first." % folder.relative_to(root))

    context_path = root.joinpath(*CONTEXT)
    context = context_path.read_text(encoding="utf-8") if context_path.is_file() else None
    stamp_text, stamp_files = take_stamp(root, zone.name)
    rels = ["/".join(CONTEXT), "/".join(VERSION_STAMP)]
    was_clean = clean(root, rels)
    new_context, rows = take_rows(context, zone.name) if context is not None else (None, [])

    record = {"name": manifest.get("name", ""), "zone": zone.name, "archived": today,
              "drive": drive.name if drive is not None and drive.is_dir() else "",
              "rows": rows, "stamp": stamp_files}
    folder.mkdir(parents=True)
    moved: List[Tuple[Path, Path]] = []
    try:
        (folder / ARCHIVED).write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        targets = [(zone, folder / "Zones" / zone.name)]
        if record["drive"]:
            targets.append((drive, folder / drive.name))
        for src, dst in targets:
            move(src, dst)
            moved.append((src, dst))
    except OSError as exc:
        for src, dst in reversed(moved):
            os.rename(str(dst), str(src))
        shutil.rmtree(str(folder), ignore_errors=True)  # only the folder made just above
        raise Refusal("The example could not be put away, so everything is where it was: %s" % exc) from None
    if new_context is not None and rows:
        context_path.write_text(new_context, encoding="utf-8")
    if stamp_text is not None:
        root.joinpath(*VERSION_STAMP).write_text(stamp_text, encoding="utf-8")
    left = commit(root, rels, was_clean, "Example: %s put away" % (record["name"] or zone.name))
    said = ["The example is put away: the %s zone%s and %d rows of System/context.md, in %s."
            % (zone.name, ", its drive %s" % record["drive"] if record["drive"] else "", len(rows),
               folder.relative_to(root).as_posix() + "/"),
            "Nothing else was touched. To bring it back: example.py restore."]
    if left:
        said.append(left)
    return {"state": "archived", "zone": zone.name, "drive": record["drive"], "rows": len(rows),
            "where": folder.relative_to(root).as_posix(), "said": " ".join(said)}


def restore(root: Path) -> dict:
    away = put_away(root)
    if not away:
        if present(root):
            raise Refusal("The example is already here.")
        raise Refusal("There is no example put away in this workspace.")
    folder, record = away
    zone = root / "Zones" / record["zone"]
    drive = root / record["drive"] if record.get("drive") else None
    for target in [zone] + ([drive] if drive is not None else []):
        if target.exists():
            raise Refusal("%s is there already, so the example cannot come back over it. Move it aside first."
                          % target.relative_to(root))
    sources = [(folder / "Zones" / zone.name, zone)]
    if drive is not None:
        sources.append((folder / drive.name, drive))
    for src, _ in sources:
        if not src.exists():
            raise Refusal("%s is missing from the archive, so nothing was brought back." % src.relative_to(root))

    rels = ["/".join(CONTEXT), "/".join(VERSION_STAMP)]
    was_clean = clean(root, rels)
    moved: List[Tuple[Path, Path]] = []
    try:
        for src, dst in sources:
            move(src, dst)
            moved.append((src, dst))
    except OSError as exc:
        for src, dst in reversed(moved):
            os.rename(str(dst), str(src))
        raise Refusal("The example could not be brought back, so it is still put away: %s" % exc) from None
    context_path = root.joinpath(*CONTEXT)
    if record.get("rows") and context_path.is_file():
        context_path.write_text(put_rows(context_path.read_text(encoding="utf-8"), record["rows"]), encoding="utf-8")
    stamp_text = put_stamp(root, record.get("stamp") or {})
    if stamp_text is not None:
        root.joinpath(*VERSION_STAMP).write_text(stamp_text, encoding="utf-8")
    (folder / ARCHIVED).unlink()
    for empty in (folder / "Zones", folder, root / ARCHIVE):
        try:
            empty.rmdir()
        except OSError:
            break
    left = commit(root, rels, was_clean, "Example: %s brought back" % (record.get("name") or zone.name))
    said = ["The example is back: the %s zone%s and its rows of System/context.md, as they were."
            % (zone.name, ", its drive %s" % drive.name if drive is not None else "")]
    if left:
        said.append(left)
    return {"state": "here", "zone": zone.name, "drive": drive.name if drive is not None else "",
            "said": " ".join(said)}


# --------------------------------------------------------------------------- main


def say_status(s: dict) -> str:
    if s["state"] == "here":
        return "The example, %s, is here: the %s zone%s." % (
            s["name"] or s["zone"], s["zone"], " and its drive %s" % s["drive"] if s["drive"] else "")
    if s["state"] == "archived":
        return "The example, %s, is put away in %s/, since %s. To bring it back: example.py restore." % (
            s["name"] or s["zone"], s["where"], s["archived"] or "an earlier day")
    return "There is no example in this workspace."


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Put the worked example away, or bring it back.")
    ap.add_argument("--root", help="workspace folder (default: the one this script is in)")
    ap.add_argument("--json", action="store_true", help="print the result as JSON")
    ap.add_argument("--today", help="YYYY-MM-DD to record instead of today")
    ap.add_argument("action", choices=("status", "archive", "restore"))
    args = ap.parse_args(argv)
    root = Path(args.root).expanduser().resolve() if args.root else Path(__file__).resolve().parents[2]
    today = args.today or datetime.date.today().isoformat()
    try:
        if args.action == "status":
            out = status(root)
            out["said"] = say_status(out)
        elif args.action == "archive":
            out = archive(root, today)
        else:
            out = restore(root)
    except Refusal as exc:
        if args.json:
            print(json.dumps({"error": str(exc)}))
        else:
            print(exc, file=sys.stderr)
        return 1
    print(json.dumps(out) if args.json else out["said"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
