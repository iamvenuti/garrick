#!/usr/bin/env python3
"""Check that splitting the threads skill moved text and rewrote none.

Not a test module and not run by CI: a one-off check for the release that
split `SKILL.md` into a dispatcher and one reference per request. It takes the
old text, `git show <ref>:template/System/skills/threads/SKILL.md`, and the
new folder, and reports

  * every sentence of the old text found nowhere in the new folder, and
  * every sentence found in more than one file, other than the repeats that
    are allowed: the sections each reference must carry to stand alone
    (`Running an action` and `The wall check`).

    python3 tests/threads_split_check.py [--ref v0.64.0] [--new template/System/skills/threads]

Exits 0 when nothing is unplaced and nothing is repeated outside the allowed
sections, 1 otherwise. Headings, and units of fewer than three words, are not
sentences and are left out. Standard library only.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD_PATH = "template/System/skills/threads/SKILL.md"
ALLOWED_REPEAT_SECTIONS = ("Running an action", "The wall check")
BULLET = re.compile(r"^\s*(?:[-*]|\d+\.)\s+")


def norm(text):
    return re.sub(r"\s+", " ", text).strip()


def units(text):
    """(section, unit) pairs: one per code line, table row, list item or paragraph."""
    out, section, para, fence = [], "", [], False

    def flush():
        if para:
            out.append((section, norm(" ".join(para))))
            para.clear()

    for line in text.split("\n"):
        if line.strip().startswith("```"):
            flush()
            fence = not fence
            continue
        if fence:
            out.append((section, norm(line)))
            continue
        if line.startswith("#"):
            flush()
            if line.startswith("## "):
                section = line[3:].strip()
            continue
        if not line.strip():
            flush()
            continue
        if line.lstrip().startswith("|"):
            flush()
            out.append((section, norm(line)))
            continue
        if BULLET.match(line):
            flush()
            line = BULLET.sub("", line)
        para.append(line)
    flush()
    return out


def sentences(unit):
    return [s for s in re.split(r"(?<=[.!?])\s+", unit) if len(s.split()) >= 3]


def sentence_sections(text):
    result = []
    for section, unit in units(text):
        for s in sentences(unit):
            result.append((section, s))
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ref", default="v0.64.0")
    ap.add_argument("--new", default="template/System/skills/threads")
    ap.add_argument("--old-file", help="read the old text from this file, not from git")
    a = ap.parse_args(argv)
    if a.old_file:
        old = Path(a.old_file).read_text(encoding="utf-8")
    else:
        old = subprocess.run(["git", "show", "%s:%s" % (a.ref, OLD_PATH)], cwd=str(ROOT), check=True,
                             capture_output=True, text=True).stdout
    folder = Path(a.new)
    if not folder.is_absolute():
        folder = ROOT / folder
    where = {}
    for f in sorted(folder.rglob("*.md")):
        for _, s in sentence_sections(f.read_text(encoding="utf-8")):
            where.setdefault(s, set()).add(str(f.relative_to(folder)))
    old_items = sentence_sections(old)
    unplaced = [(sec, s) for sec, s in old_items if s not in where]
    repeated = []
    seen = set()
    in_old = {}
    for sec, s in old_items:
        in_old[s] = in_old.get(s, 0) + 1
    for sec, s in old_items:
        if s in seen or len(s.split()) < 5:
            continue
        seen.add(s)
        if in_old[s] > 1:               # the old text repeats it itself: kept once in the dispatcher
            continue
        if len(where.get(s, ())) > 1 and not sec.startswith(ALLOWED_REPEAT_SECTIONS):
            repeated.append((sec, s, sorted(where[s])))
    print("old sentences: %d, unplaced: %d, repeated outside the allowed sections: %d"
          % (len(set(s for _, s in old_items)), len(unplaced), len(repeated)))
    for sec, s in unplaced:
        print("UNPLACED [%s] %s" % (sec, s))
    for sec, s, files in repeated:
        print("REPEATED [%s] in %s: %s" % (sec, ", ".join(files), s))
    return 1 if unplaced or repeated else 0


if __name__ == "__main__":
    sys.exit(main())
