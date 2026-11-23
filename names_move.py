#!/usr/bin/env python3
"""Move People and Aliases out of System/context.md, into System/names.md (#653).

    python3 install.py --update ~/Garrick --names                say what would move; changes nothing
    python3 install.py --update ~/Garrick --names --apply        do it, after the user's yes
    python3 install.py --update ~/Garrick --names --json         the same report, for a program

System/context.md is loaded into every session. Most of its length, in a workspace used for a few months, is the
People and Aliases tables, and a session needs only the rows for the names its prompt holds. They go to
System/names.md, with the same columns, and a pointer line takes their place.

The move happens once, and only when both tables are found whole: each is a section under its own heading, with
one Markdown table in it, and no row has more cells than the header. A row with fewer cells is shown by Markdown with
its last cells empty, and the move writes it that way, padded to the header's count. Anything else stays where it is, and the
report says so in one sentence. Every line of both sections is carried over as it was, byte for byte, the prose
above a table included, but for a row with fewer cells than its header, which is padded with empty cells; a row the move did not parse is never lost, since it is not moved. Before anything is
written the move checks that every row of the two tables is in names.md once, and none is left in context.md.
Both files go into one commit of the workspace's own repository. A second run finds nothing to move.

Without --apply nothing is written. This is a held step, like --split: the update skill asks first, and it never
runs on its own.

Python 3.9+, standard library only.
"""

import json
import re
import sys

sys.dont_write_bytecode = True

import update  # noqa: E402  (the update beside this file, from the same Garrick)

install = update.install
UpdateError = update.UpdateError

HEADINGS = ("People", "Aliases")
POINTER = ("## People and Aliases\n\n"
           "The people you deal with, and the names that arrive mangled by dictation, are in `System/names.md`, so "
           "that this file stays short. Read it before acting on a name you cannot place, and match every proper "
           "noun against it and the Parties above.\n")
OPENING = ("# Names\n\nWho you deal with, and how their names arrive by dictation. Read this before acting on a name "
           "you cannot place. Parties and zones are in `System/context.md`.\n")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
SEPARATOR = re.compile(r"^:?-{1,}:?$")


def cells(line):
    """The cells of a table row: split at a `|` that is not escaped, the outer bars off."""
    inner = line.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|") and not inner.endswith("\\|"):
        inner = inner[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", inner)]


def pad(line, count):
    """A row with fewer cells than `count`, closed and given empty cells up to it, as Markdown shows it. A row with
    enough cells is returned as it was. A carriage return at the end of the line stays at the end."""
    have = 0 if not line.replace("|", "").strip() else len(cells(line))      # a row of bars alone has no cells
    if have >= count:
        return line
    tail = "\r" if line.endswith("\r") else ""
    body = line[:-1] if tail else line
    body = body.rstrip() if have else "|"
    if not body.endswith("|") or body.endswith("\\|"):
        body += " |"
    return body + " |" * (count - have) + tail


def sections(lines):
    """[(heading text, first line, one past the last line)] of every `## ` section outside a code fence."""
    marks, fence = [], None
    for i, line in enumerate(lines):
        m = FENCE.match(line)
        if fence:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                fence = None
            continue
        if m:
            fence = m.group(1)
            continue
        if line.startswith("## "):
            marks.append((line[3:].strip(), i))
    return [(h, i, marks[k + 1][1] if k + 1 < len(marks) else len(lines)) for k, (h, i) in enumerate(marks)]


def named(lines):
    """{"People": (first line, one past the last), "Aliases": ...} for the two sections, whatever their case; a
    heading found twice is None, since the move cannot tell which table is meant."""
    out = {}
    for h, s, e in sections(lines):
        canon = {"people": "People", "aliases": "Aliases"}.get(h.lower())
        if canon:
            if canon in out:
                return None
            out[canon] = (s, e)
    return out


def whole(lines, start, end):
    """The data rows of the one table in lines[start+1:end] as [line], or None when it is not found whole: no table,
    two tables, a table with a gap in it, no separator row, or a row with another number of cells than the header."""
    bars = [i for i in range(start + 1, end) if lines[i].lstrip().startswith("|")]
    if len(bars) < 2 or bars[-1] - bars[0] != len(bars) - 1:
        return None
    if any(FENCE.match(lines[i]) for i in range(start + 1, end)):
        return None
    header = cells(lines[bars[0]])
    sep = cells(lines[bars[1]])
    if len(sep) != len(header) or not all(SEPARATOR.match(c) for c in sep) or not any(header):
        return None
    rows = bars[2:]
    if any(len(cells(lines[i])) > len(header) for i in rows):
        return None
    return [pad(lines[i], len(header)) for i in rows]


def refusal(table, lines, start, end):
    """The sentence for a table with a row of more cells than its header, or "" when that is not why it is refused.
    It gives the table, the line number (from 1) and the two counts, and never the text of the row."""
    bars = [i for i in range(start + 1, end) if lines[i].lstrip().startswith("|")]
    if len(bars) < 2:
        return ""
    count = len(cells(lines[bars[0]]))
    for i in bars[2:]:
        if len(cells(lines[i])) > count:
            return ("The %s table in System/context.md could not be read: line %d has %d cells and the header has %d."
                    % (table, i + 1, len(cells(lines[i])), count))
    return ""


def tools_read_names(root):
    """Whether the workspace's own System/tools/garrick_lib.py reads names.md. A move made while the tools are older
    leaves them reading no people and no aliases, and the checks that use them then see nobody."""
    try:
        return "def names_path" in (root / "System" / "tools" / "garrick_lib.py").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def study(root, tools_follow=False):
    """What the move would do, read only (`tools_follow`: this run's update writes the new tools first): {"state", "people", "aliases", "said"} with state one of `none` (nothing
    to move: already moved, or no tables), `waiting` (both tables are whole and in context.md), `unreadable` (a
    table is not whole, so it stays), `both` (names.md already holds one of them)."""
    context = root / "System" / "context.md"
    names = root / "System" / "names.md"
    try:
        text = context.read_bytes().decode("utf-8")      # as written: a line ending is part of what is carried over
    except (OSError, UnicodeDecodeError):
        return {"state": "none", "people": 0, "aliases": 0, "said": ""}
    lines = text.split("\n")
    found = named(lines)
    if found is None:
        return {"state": "unreadable", "people": 0, "aliases": 0,
                "said": "System/context.md has a People or Aliases heading twice, so they stay where they are."}
    if not found:
        return {"state": "none", "people": 0, "aliases": 0, "said": ""}
    if len(found) < 2:
        gone = [h for h in HEADINGS if h not in found]
        return {"state": "unreadable", "people": 0, "aliases": 0,
                "said": "System/context.md has no %s section, so People and Aliases stay where they are." % gone[0]}
    rows = {h: whole(lines, *span) for h, span in found.items()}
    bad = [h for h in HEADINGS if rows[h] is None]
    if bad:
        why = refusal(bad[0], lines, *found[bad[0]])
        if why:
            return {"state": "unreadable", "people": 0, "aliases": 0, "said": why + " People and Aliases stay where they are."}
        return {"state": "unreadable", "people": 0, "aliases": 0,
                "said": "The %s table in System/context.md could not be read as one whole table, so People and "
                        "Aliases stay where they are." % bad[0]}
    if names.is_file():
        try:
            filled = bool(names.read_text(encoding="utf-8", errors="replace").strip())
        except OSError:
            filled = True
        if filled:       # a file of your own is never written over, whatever it holds
            return {"state": "both", "people": len(rows["People"]), "aliases": len(rows["Aliases"]),
                    "said": "System/names.md already holds text, so nothing moves; "
                            "both files are read together."}
    if not tools_read_names(root) and not tools_follow:
        return {"state": "tools", "people": len(rows["People"]), "aliases": len(rows["Aliases"]),
                "said": "This workspace's tools do not read System/names.md yet, so People and Aliases stay where they "
                        "are. Update the tools first, then ask again."}
    return {"state": "waiting", "after_update": not tools_read_names(root), "people": len(rows["People"]), "aliases": len(rows["Aliases"]),
            "said": "People (%d rows) and Aliases (%d rows) are still in System/context.md, which every session loads. "
                    "With your yes the update moves them to System/names.md." % (len(rows["People"]), len(rows["Aliases"]))}


def moved_text(text):
    """(context.md's new text, names.md's text), or None when the tables are not found whole."""
    lines = text.split("\n")
    found = named(lines)
    if not found or set(found) != set(HEADINGS) or any(whole(lines, *found[h]) is None for h in HEADINGS):
        return None
    body = {}
    for h, (s, e) in found.items():
        part = list(lines[s:e])
        bars = [i for i in range(len(part)) if part[i].lstrip().startswith("|")]
        for i in bars[2:]:
            part[i] = pad(part[i], len(cells(part[bars[0]])))   # every row of names.md has the header's cells
        while part and not part[-1].strip():
            part.pop()
        body[h] = part
    eol = "\r\n" if "\r\n" in text else "\n"
    first = min(found["People"][0], found["Aliases"][0])
    drop = set()
    for h in HEADINGS:
        drop |= set(range(*found[h]))
    kept = []
    for i, line in enumerate(lines):
        if i == first:
            kept += POINTER.replace("\n", eol).split("\n")   # ends with an empty string: one blank line after it
        if i not in drop:
            kept.append(line)
    new_context = "\n".join(kept)
    # A line keeps the ending it had. A file written with Windows line endings is carried with them.
    def block(part):
        return eol.join(l[:-1] if l.endswith("\r") else l for l in part)

    names = (OPENING.replace("\n", eol) + eol + block(body["People"]) + eol + eol + block(body["Aliases"]) + eol)
    return new_context, names


def rows_in(text):
    """Every data row of the People and Aliases tables in a text, as lines, in order."""
    lines = text.split("\n")
    out = []
    for s, e in (named(lines) or {}).values():
        out += whole(lines, s, e) or []
    return out


def apply_move(root):
    """Do the move. Returns (said, ok). Nothing is written unless the check of every row holds."""
    context = root / "System" / "context.md"
    names = root / "System" / "names.md"
    state = study(root)
    if state["state"] != "waiting":
        # Nothing to move, or a reason it stays: said, and not an error.
        return state["said"] or "People and Aliases are not in System/context.md: nothing to move.", True
    text = context.read_bytes().decode("utf-8")
    result = moved_text(text)
    if result is None:
        return "The tables could not be read as whole tables, so nothing was moved.", False
    new_context, new_names = result
    before = rows_in(text)
    after = rows_in(new_names)
    if sorted(before) != sorted(after) or rows_in(new_context):
        return "A row would have been lost or repeated, so nothing was moved.", False
    why = update.commit_files(root, {
        "System/context.md": (new_context.encode("utf-8"), context.stat().st_mode & 0o777),
        "System/names.md": (new_names.encode("utf-8"), 0o644)},
        "Garrick: People and Aliases move to System/names.md")
    if why:
        return "Nothing was written: %s." % why, False
    return ("Moved People (%d rows) and Aliases (%d rows) to System/names.md, and left a pointer line in "
            "System/context.md. One commit; git revert undoes it." % (state["people"], state["aliases"])), True


def main(root, apply, as_json):
    state = study(root)
    if not apply:
        said = state["said"] or "People and Aliases are not in System/context.md: nothing to move."
        if state["state"] == "waiting":
            said += " Nothing has been changed. To make the change, run the same command with --apply."
        out = dict(state, said=said)
        print(json.dumps(out, indent=2) if as_json else said)
        return 0
    said, ok = apply_move(root)
    if as_json:
        print(json.dumps({"state": study(root)["state"], "moved": ok and state["state"] == "waiting", "said": said},
                         indent=2))
    else:
        print(said)
    return 0 if ok else 1
