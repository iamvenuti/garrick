#!/usr/bin/env python3
"""The part of a wiki's lint a script can do: pages cut off from the rest,
and links to pages that do not exist. It changes nothing.

    python3 System/tools/wiki_lint.py --wiki Meetings
    python3 System/tools/wiki_lint.py --wiki Knowledge --json

The rest of a lint needs reading: two pages that contradict each other, a
claim a later source superseded, a "consensus" only vendors state, a name
that turns up across many pages with no page of its own. The `meetings` and
`knowledge` skills' *Lint* section does that part, starting from this list,
and writes the report.

An orphan is a page under wiki/ that links to no other page and that no
other page links to; the index and the log do not count, since they list
everything. A missing page is a link target no file answers, with the
pages that link to it. Links into raw/ are checked against raw/. A link to
any other kind of file, such as a diagram exported beside the page that shows
it, is found as Obsidian finds it: from the linking page's folder, from the
wiki's top, or by its name when only one file has it. Such a file is not a
page, so it counts toward no orphan.

A page that faded lives under dormant/ or archive/, as `dormant/wiki/...`
with its raw file at `dormant/raw/...`; the dormant ones are listed in
`wiki/index-dormant.md`, a list like the index. Faded pages are not working
pages: none is counted, an orphan, or read for its links. A link into one
still lands, written with its path or by its name when no working page has
that name, so it is not a missing page; like a link to a file, it counts
toward no orphan.

Standard library only, Python 3.9 or later.
"""

from __future__ import annotations

import argparse
import json
import posixpath
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from garrick_lib import workspace_root  # noqa: E402

LINK = re.compile(r"!?\[\[([^\[\]|#\n]+)(?:#[^\[\]|\n]*)?(?:\|[^\[\]\n]*)?\]\]")
LISTS = {"index", "log", "index-dormant"}
FADED = ("dormant", "archive")


def pages(wiki: Path) -> List[Path]:
    """Every page under wiki/, but the index, the log and lint reports."""
    top = wiki / "wiki"
    return sorted(p for p in top.rglob("*.md")
                  if not any(part.startswith(".") for part in p.relative_to(top).parts)
                  and p.relative_to(top).parts[0] != "lint"
                  and not (p.parent == top and p.stem in LISTS))


def visible(folder: Path) -> List[Path]:
    """Every file under `folder` but hidden ones; none when it is not there."""
    return [p for p in folder.rglob("*") if p.is_file()
            and not any(part.startswith(".") for part in p.relative_to(folder).parts)] if folder.is_dir() else []


def lint(wiki: Path) -> dict:
    top = wiki / "wiki"
    all_pages = pages(wiki)
    files = {p.relative_to(wiki).with_suffix("").as_posix(): p for p in all_pages}
    raws: Set[str] = set()
    for raw in [wiki / "raw"] + [wiki / grade / "raw" for grade in FADED]:
        for p in visible(raw):
            raws |= {p.relative_to(wiki).with_suffix("").as_posix(), p.relative_to(wiki).as_posix()}
    by_stem: Dict[str, List[str]] = {}
    for key in files:
        by_stem.setdefault(key.rsplit("/", 1)[-1].lower(), []).append(key)
    others = {p.relative_to(wiki).as_posix() for p in visible(top) if p.suffix != ".md"}
    # What faded, where a link may still land: pages, and the other files beside them.
    faded: Set[str] = set()
    faded_others: Set[str] = set()
    for grade in FADED:
        for p in visible(wiki / grade / "wiki"):
            if p.suffix == ".md":
                faded.add(p.relative_to(wiki).with_suffix("").as_posix())
            else:
                faded_others.add(p.relative_to(wiki).as_posix())
    faded_by_stem: Dict[str, List[str]] = {}
    for key in sorted(faded):
        faded_by_stem.setdefault(key.rsplit("/", 1)[-1].lower(), []).append(key)

    lists = {"wiki/" + n for n in LISTS}

    def resolve(target: str, here: str) -> Optional[str]:
        t = target.strip().rstrip("\\").strip()          # a table writes [[a\|b]]: the backslash is not the name's
        for prefix in ("Wikis/%s/" % wiki.name, "%s/" % wiki.name):
            if t.startswith(prefix):
                t = t[len(prefix):]
        t = t[:-3] if t.endswith(".md") else t
        if t in lists or t in LISTS:
            return t
        if t in files or t in raws or t in faded or t in faded_others:
            return t
        if t.startswith(("raw/",) + tuple("%s/%s/" % (g, kind) for g in FADED for kind in ("wiki", "raw"))):
            return None
        for prefix in ("wiki/", ""):
            if prefix + t in files:
                return prefix + t
        hits = [k for k in files if k.endswith("/" + t)]
        if hits:
            return hits[0]
        hits = by_stem.get(t.rsplit("/", 1)[-1].lower(), [])
        if hits:
            return hits[0]
        # A page that faded, when no working page answers the link.
        hits = sorted(k for k in faded if k.endswith("/" + t)) or faded_by_stem.get(t.rsplit("/", 1)[-1].lower(), [])
        if hits:
            return hits[0]
        return other(t, here) if posixpath.splitext(t)[1] else None

    def other(t: str, here: str) -> Optional[str]:
        """A file that is not a page, such as `diagram.html` or an embedded
        `diagram.png`: from the linking page's folder, `../` included, then
        from the wiki's top, then by name when only one file has it."""
        near = posixpath.normpath(posixpath.join(here, t))
        if near in others or near in raws or near in faded_others:
            return near
        for prefix in ("wiki/", ""):
            if prefix + t in others or prefix + t in faded_others:
                return prefix + t
        for pool in (others, faded_others):          # a working file first, then one that faded with its page
            hits = [k for k in pool if k.lower().endswith("/" + t.lower())]
            if hits:
                return hits[0] if len(hits) == 1 else None
        return None

    out_links: Dict[str, Set[str]] = {k: set() for k in files}
    in_links: Dict[str, Set[str]] = {k: set() for k in files}
    missing: Dict[str, Set[str]] = {}
    sources = list(files.items()) + [(name, top / (name + ".md")) for name in LISTS if (top / (name + ".md")).is_file()]
    for key, path in sources:
        text = path.read_text(encoding="utf-8", errors="replace")
        text = re.sub(r"```.*?```|`[^`\n]*`", "", text, flags=re.S)
        for m in LINK.finditer(text):
            target = m.group(1).strip()
            if not target or "://" in target:
                continue
            found = resolve(target, path.parent.relative_to(wiki).as_posix())
            if found is None:
                missing.setdefault(target, set()).add(key)
            elif found in files and found != key and key in files:
                out_links[key].add(found)
                in_links[found].add(key)
    orphans = sorted(k for k in files if not out_links[k] and not in_links[k])
    return {
        "wiki": wiki.name,
        "pages": len(files),
        "orphans": orphans,
        "missing": [{"target": t, "linked_from": sorted(s)} for t, s in sorted(missing.items(), key=lambda kv: (-len(kv[1]), kv[0]))],
    }


def say(found: dict) -> str:
    lines = ["%s: %d pages, %d orphans, %d missing pages." % (found["wiki"], found["pages"], len(found["orphans"]),
                                                             len(found["missing"]))]
    if found["orphans"]:
        lines.append("Orphans, linking nowhere and linked from nowhere:")
        lines += ["  %s" % o for o in found["orphans"]]
    if found["missing"]:
        lines.append("Missing pages, linked but not there:")
        lines += ["  [[%s]], from %s" % (m["target"], ", ".join(m["linked_from"][:3])
                                         + (" and %d more" % (len(m["linked_from"]) - 3) if len(m["linked_from"]) > 3 else ""))
                  for m in found["missing"]]
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Orphans and missing pages in a wiki. Changes nothing.")
    ap.add_argument("--root", help="the workspace (default: the one this script sits in)")
    ap.add_argument("--wiki", required=True, help="Meetings or Knowledge")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        root = Path(a.root).expanduser().resolve() if a.root else workspace_root(HERE)
    except FileNotFoundError:
        print("wiki_lint: not inside a Garrick workspace", file=sys.stderr)
        return 2
    wiki = root / "Wikis" / a.wiki
    if not (wiki / "wiki").is_dir():
        print("wiki_lint: %s has no wiki/ folder" % wiki, file=sys.stderr)
        return 2
    found = lint(wiki)
    print(json.dumps(found, indent=1) if a.json else say(found))
    return 0


if __name__ == "__main__":
    sys.exit(main())
