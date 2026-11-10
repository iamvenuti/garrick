#!/usr/bin/env python3
"""compact.py: the counting and the guard behind "compact the meetings". It rewrites nothing.

    python3 System/skills/meetings/compact.py plan                  what would change: pages, words, the largest first
    python3 System/skills/meetings/compact.py plan --pilot          and the ten pages a pilot would take
    python3 System/skills/meetings/compact.py plan --limit 600 --json
    python3 System/skills/meetings/compact.py verify "Wikis/Meetings/wiki/sources/260310-acme-call.md"

`plan` reads the working pages of the Meetings wiki, `wiki/sources/`, and lists
those whose body is over the limit (`meeting-max-words` in
System/garrick-settings.json, 450 by default; `--limit` overrides it). It skips
a page with `pinned: true` unless `--include-pinned`, a page marked
`superseded:`, a page with no frontmatter, and every page in `dormant/` and
`archive/`. It says how many pages and words would change and how many words
they would hold at the target of 350 each. With `--pilot`, it also proposes
about ten pages for the user to approve first, spread over the zones and over
the years rather than the largest ten.

`verify PAGE` compares a rewritten page with its last committed version, in the
wiki's own repository, and names what the new page lacks: a number, a quoted
phrase, a link, a row of a table, and any change to the frontmatter. It exits 1
when it names anything. It judges nothing about the prose; the rewrite is the
assistant's, and the user approves the pilot.

Standard library only. Exit codes: 0; 1 when `verify` names something; 2 for a
usage error.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
TOOLS = HERE.parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import garrick_lib as gl  # noqa: E402

LIMIT = 450
TARGET = 350
PILOT = 10
SOURCES = ("Wikis", "Meetings", "wiki", "sources")


def limit_of(root: Path) -> int:
    value = gl.read_settings(root).get("meeting-max-words")
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else LIMIT


def split(text: str) -> Tuple[str, str]:
    """(frontmatter, body): the frontmatter with its two rules, and the rest."""
    lines = text.split("\n")
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i] in ("---", "..."):
                return "\n".join(lines[:i + 1]), "\n".join(lines[i + 1:])
    return "", text


def words(text: str) -> int:
    return len(text.split())


def pages(root: Path, include_pinned: bool = False, limit: Optional[int] = None) -> List[dict]:
    """The working pages over the limit, the largest first."""
    limit = limit if limit is not None else limit_of(root)
    out = []
    folder = root.joinpath(*SOURCES)
    for path in sorted(folder.rglob("*.md")) if folder.is_dir() else []:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        front, body = split(text)
        fm = gl.parse_frontmatter_text(text)
        if not front or fm.get("superseded"):
            continue
        if str(fm.get("pinned") or "").lower() == "true" and not include_pinned:
            continue
        n = words(body)
        if n > limit:
            out.append({"page": path.relative_to(root).as_posix(), "words": n, "zone": str(fm.get("zone") or ""),
                        "date": str(fm.get("date") or "")})
    return sorted(out, key=lambda p: (-p["words"], p["page"]))


def pilot(found: List[dict], n: int = PILOT) -> List[dict]:
    """About `n` pages spread over the zones, and within a zone over its dates: one zone after another, each time
    the page at the next even step of that zone's pages in date order."""
    zones: Dict[str, List[dict]] = {}
    for p in sorted(found, key=lambda p: (p["date"], p["page"])):
        zones.setdefault(p["zone"], []).append(p)
    chosen: List[dict] = []
    picks = {z: [] for z in zones}
    for z, items in zones.items():
        want = min(len(items), max(1, -(-n // max(1, len(zones)))))
        picks[z] = [items[int(i * len(items) / want)] for i in range(want)]
    while len(chosen) < n and any(picks.values()):
        for z in sorted(picks):
            if picks[z] and len(chosen) < n:
                chosen.append(picks[z].pop(0))
    return chosen


def plan(root: Path, include_pinned: bool = False, limit: Optional[int] = None, with_pilot: bool = False) -> dict:
    limit = limit if limit is not None else limit_of(root)
    found = pages(root, include_pinned, limit)
    total = sum(p["words"] for p in found)
    after = sum(min(p["words"], TARGET) for p in found)
    out = {"limit": limit, "target": TARGET, "pages": len(found), "words": total, "words_after": after,
           "largest": found[:10], "all": found}
    if with_pilot:
        out["pilot"] = pilot(found)
    return out


# ---------------------------------------------------------------------------
# verify

NUMBER_RE = re.compile(r"\b\d[\d.,:/%]*\d\b|\b\d\b")
QUOTE_RE = re.compile(r"“([^”\n]{3,})”|\"([^\"\n]{3,})\"")
LINK_RE = re.compile(r"\[\[([^\]|#]+)|\]\(\s*<?([^)\s>]+)")


TIMESTAMP_RE = re.compile(r"[\[(]?\b\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?\b[\])]?(?:\s*-->\s*[\[(]?\d{1,2}:\d{2}(?::\d{2})?[\])]?)?")


def numbers(text: str) -> set:
    """The numbers of `text`, without the timestamps a compact page drops."""
    return {m.group(0).strip(".,:") for m in NUMBER_RE.finditer(TIMESTAMP_RE.sub(" ", text))}


def quotes(text: str) -> set:
    return {a or b for a, b in QUOTE_RE.findall(text)}


def links(text: str) -> set:
    return {(a or b).strip() for a, b in LINK_RE.findall(text)}


def rows(text: str) -> List[str]:
    return [l for l in text.split("\n") if l.lstrip().startswith("|") and not set(l.strip()) <= set("|-: ")]


def committed(root: Path, page: Path) -> Optional[str]:
    """The page as the wiki's repository last committed it, or None."""
    repo = root / "Wikis"
    try:
        rel = page.resolve().relative_to(repo.resolve()).as_posix()
        r = subprocess.run(["git", "show", "HEAD:%s" % rel], cwd=str(repo), capture_output=True, text=True,
                           env=gl.own_repo_env())
    except (OSError, ValueError):
        return None
    return r.stdout if r.returncode == 0 else None


def verify_text(old: str, new: str) -> List[str]:
    """What `new` lacks of `old`, one line each."""
    out: List[str] = []
    of, ob = split(old)
    nf, nb = split(new)
    if of != nf:
        out.append("the frontmatter changed")
    for n in sorted(numbers(ob) - numbers(nb)):
        out.append("a number is gone: %s" % n)
    for q in sorted(quotes(ob) - quotes(nb)):
        out.append("a quoted phrase is gone: “%s”" % q[:60])
    for l in sorted(links(old) - links(new)):
        out.append("a link is gone: %s" % l)
    if len(rows(nb)) < len(rows(ob)):
        out.append("the table has %d rows, it had %d" % (len(rows(nb)), len(rows(ob))))
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="compact.py", description=__doc__.split("\n")[0])
    ap.add_argument("--root", help="the workspace (default: the one this script sits in)")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--limit", type=int)
    p.add_argument("--pilot", action="store_true")
    p.add_argument("--include-pinned", action="store_true")
    p.add_argument("--json", action="store_true")
    v = sub.add_parser("verify")
    v.add_argument("page")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else HERE.parents[2]
    if args.command == "plan":
        res = plan(root, args.include_pinned, args.limit, args.pilot)
        if args.json:
            print(json.dumps(res, indent=2))
            return 0
        print("%d pages are over %d words: %d words in all, about %d at %d each." % (
            res["pages"], res["limit"], res["words"], res["words_after"], res["target"]))
        for page in (res["pilot"] if args.pilot else res["largest"]):
            print("  %5d  %s" % (page["words"], page["page"]))
        if args.pilot:
            print("The pilot: %d pages, spread over the zones and the years." % len(res["pilot"]))
        return 0
    page = (root / args.page) if not Path(args.page).is_absolute() else Path(args.page)
    if not page.is_file():
        print("No such page: %s" % args.page, file=sys.stderr)
        return 2
    old = committed(root, page)
    if old is None:
        print("The page has no committed version to compare with.", file=sys.stderr)
        return 2
    problems = verify_text(old, page.read_text(encoding="utf-8"))
    for line in problems:
        print(line)
    if not problems:
        print("Nothing is missing: the frontmatter, every number, quote and link, and the table rows are all there.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
