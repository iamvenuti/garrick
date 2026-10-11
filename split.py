#!/usr/bin/env python3
"""Move your own text out of Garrick's instruction files, into the local file beside each.

    python3 install.py --update ~/Garrick --split                        say what would move; changes nothing
    python3 install.py --update ~/Garrick --split --apply                do it
    python3 install.py --update ~/Garrick --split --apply --only System/rules.md
    python3 install.py --update ~/Garrick --split --json                 the same report, for a program

Garrick's instruction files, `System/rules.md` and every `AGENTS.md`, stay as
Garrick ships them, and the workspace's own rules and routing live in the
local file beside each: `System/rules.local.md`, `AGENTS.local.md`. An
instruction file that holds text of its own, from before the split or edited
since, is brought back to that shape here. For each one, it finds the Garrick
version the file grew from, the base, compares the base, your file and this
Garrick's, and then:

- writes Garrick's file as this Garrick ships it;
- moves each passage you added into the local file, under the heading it sat
  under there, adding the heading when the local file lacks it;
- lists each passage where you changed or removed Garrick's own text, for you
  to settle one at a time. Those cannot be moved on their own. Your wording
  goes into the local file under "From your earlier <name>, to review", where
  it still holds until you settle it; Garrick's is named by its opening words.

A change Garrick made since the base, to text you left alone, is simply
taken. Nothing of yours is lost: every line of your file that is not
Garrick's text ends up in the local file, and a line that cannot be placed
goes under the review heading. The base is the Garrick version in the file's
history, or its `.new`'s, that your file is closest to. Without one, all that
differs from this Garrick's counts as yours, and the report says so.

A fenced code block is one passage throughout: compared, moved and settled
whole, its fences included, never split inside.

Nothing is written without --apply. Each repository gets one commit holding
Garrick's file, the local file, and the removal of a `.new` an earlier update
left beside it, so `git revert` undoes it. The version stamp then records
Garrick's file as written.

Python 3.9+, standard library only.
"""

import difflib
import json
import os
import re
import subprocess
import sys

sys.dont_write_bytecode = True

import update  # noqa: E402  (the update beside this file, from the same Garrick)

install = update.install
digest = update.digest
UpdateError = update.UpdateError

HEADING_RE = re.compile(r"^#{1,2}\s+\S")
FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
WORD_RE = re.compile(r"[A-Za-z0-9]+")
REVIEW = "## From your earlier %s, to review"
REVIEW_RE = re.compile(r"^## From your earlier .+, to review\s*$")
ITEM_RE = re.compile(r"^### (\d+)\. ")
LIKE = 0.5              # how alike two lines must be for one to count as the other, changed
HISTORY = 400           # commits read back, at most, for the base


# --------------------------------------------------------------------------- lines


def norm(line):
    return " ".join(line.split())


def substantial(line):
    """A line that says something: three words or more. Blank lines, fences,
    table rules and lone markers move with the passage around them."""
    return len(WORD_RE.findall(line)) >= 3


def is_heading(line):
    return bool(HEADING_RE.match(line))


def heading_name(heading):
    return heading.lstrip("#").strip() if heading else ""


def opening(line, words=8):
    """The first words of a line, without its Markdown, to name it by. A
    fenced block is named by the first line inside it that has words."""
    if "\n" in line:
        inner = line.split("\n")[1:-1]
        line = next((x for x in inner if WORD_RE.search(x)), "")
    text = line.replace("**", "").replace("`", "").replace('"', "'")
    text = re.sub(r"^\s*(?:[-*>]|\d+\.|\|)\s*", "", text)
    parts = text.split()
    if len(parts) > words:
        return " ".join(parts[:words]).rstrip(".,;:") + "…"
    return " ".join(parts).rstrip(".,;:")


def units(text):
    """The lines of `text`, except that a fenced code block, its fences
    included, is one item, its lines joined: a block is compared, moved and
    settled whole, never split. A fence that never closes is an ordinary line."""
    lines = text.splitlines() if isinstance(text, str) else list(text)
    out, k = [], 0
    while k < len(lines):
        m = FENCE_RE.match(lines[k])
        if m:
            close = re.compile(r"^ {0,3}%s{%d,}\s*$" % (re.escape(m.group(1)[0]), len(m.group(1))))
            end = next((e for e in range(k + 1, len(lines)) if close.match(lines[e])), None)
            if end is not None:
                out.append("\n".join(lines[k:end + 1]))
                k = end + 1
                continue
        out.append(lines[k])
        k += 1
    return out


def lines_of(items):
    """`items` with each fenced block back in its lines."""
    return [x for item in items for x in item.split("\n")]


def fenced(lines):
    """For each of `lines`, whether it sits in a fenced code block, fences included."""
    out = []
    for item in units(lines):
        n = item.count("\n") + 1
        out += [n > 1] * n          # only a block spans lines
    return out


def trim(lines):
    """`lines` without the blank lines at either end."""
    start, end = 0, len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return lines[start:end]


# --------------------------------------------------------------------------- comparing


def split_text(user, base, shipped, known_base=True):
    """Compare your file with the Garrick version it grew from and with this
    Garrick's. Returns (additions, decisions): additions are [(heading or None,
    [lines])], passages of yours with the heading they sat under; decisions are
    dicts with `kind` ("changed", "both" or "removed"; "absent" in place of
    "removed" when no base is known, and `base` is this Garrick's), `section`,
    `garrick` (Garrick's lines at the base), `yours` (your lines), `newer`
    (this Garrick's lines like them, where Garrick has since changed them) and
    `rewritten` (Garrick has since changed them past recognising).

    A fenced code block is one item throughout (see units): an addition holds
    it whole, a decision's `yours` holds the whole block, fences included, and
    in `garrick` and `newer` it is one item, its lines joined."""
    U, B, S = units(user), units(base), units(shipped)
    Un, Bn, Sn = [norm(x) for x in U], [norm(x) for x in B], [norm(x) for x in S]
    in_user, in_shipped, in_base = set(Un), set(Sn), set(Bn)

    heads, current = [], None
    for line in U:
        if is_heading(line):
            current = None if line.startswith("# ") else line.strip()
        heads.append(current)
    base_heads, current = [], None
    for line in B:
        if is_heading(line):
            current = None if line.startswith("# ") else line.strip()
        base_heads.append(current)

    # What Garrick did since the base with each base line it no longer has as
    # it was: {line: (this Garrick's lines like it, whether anything took its place)}.
    since = {}
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, Bn, Sn, autojunk=False).get_opcodes():
        if tag in ("replace", "delete"):
            for i in range(i1, i2):
                since[i] = ([x for x in S[j1:j2] if substantial(x) and like(B[i], x)], j2 > j1)

    def newer(lines):
        return dedupe(x for i in lines for x in since[i][0])

    def rewritten(lines):
        return any(since[i][1] for i in lines) and not newer(lines)

    additions, decisions = [], []

    def add(j1, j2):
        """Your lines U[j1:j2], split where one of your own headings starts a section."""
        section = heads[j1 - 1] if j1 > 0 else None
        chunks, lines = [], []
        for j in range(j1, j2):
            if is_heading(U[j]):
                chunks.append((section, lines))
                section, lines = (None if U[j].startswith("# ") else U[j].strip()), []
                if section is None:
                    lines.append(U[j])
                continue
            if substantial(U[j]) and (Un[j] in in_shipped or Un[j] in in_base):
                continue            # Garrick's own text, moved: it is in Garrick's file already
            lines.append(U[j])
        chunks.append((section, lines))
        for section, lines in chunks:
            lines = trim(lines)
            if lines or (section and section not in Sn and section not in Bn):
                additions.append((section, lines))

    def removed(i1, i2):
        lines = [i for i in range(i1, i2) if substantial(B[i]) and Bn[i] not in in_user]
        kept = [i for i in lines if i not in since]                 # still in Garrick's file as it was
        reworded = [i for i in lines if i in since and since[i][1]]  # Garrick put its own in their place
        if kept or reworded:                                         # one Garrick dropped too is agreed
            decisions.append({"kind": "removed" if known_base else "absent",
                              "section": base_heads[i1] if i1 < len(B) else None,
                              "garrick": [B[i] for i in sorted(kept + reworded)], "yours": [],
                              "newer": newer(reworded), "rewritten": rewritten(reworded)})

    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, Bn, Un, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        if tag == "replace":
            # A heading of your own inside the passage starts a section of yours: that part is an addition.
            own = next((j for j in range(j1, j2) if is_heading(U[j]) and Un[j] not in in_shipped
                        and Un[j] not in in_base), None)
            if own is not None:
                add(own, j2)
                if own == j1:
                    removed(i1, i2)
                    continue
                j2 = own
        if tag == "insert":
            add(j1, j2)
        elif tag == "delete":
            removed(i1, i2)
        elif alike(B[i1:i2], U[j1:j2]):
            yours = trim(U[j1:j2])
            garrick = [B[i] for i in range(i1, i2) if substantial(B[i]) and Bn[i] not in in_user]
            changed = [i for i in range(i1, i2) if i in since and substantial(B[i])]
            decisions.append({"kind": "both" if changed else "changed",
                              "section": heads[j1 - 1] if j1 > 0 else None,
                              "garrick": garrick or [B[i] for i in range(i1, i2) if substantial(B[i])],
                              "yours": lines_of(yours), "newer": newer(changed), "rewritten": rewritten(changed),
                              "known_base": known_base})
        else:
            removed(i1, i2)
            add(j1, j2)
    return [(section, lines_of(block)) for section, block in additions], decisions


def like(a, b):
    """Whether line `b` reads as line `a`, changed."""
    m = difflib.SequenceMatcher(None, norm(a), norm(b), autojunk=False)
    return m.real_quick_ratio() >= LIKE and m.quick_ratio() >= LIKE and m.ratio() >= LIKE


def alike(old, new):
    """Whether any line of `new` is a changed line of `old`, rather than one of
    your own beside a removal."""
    old = [x for x in old if substantial(x)]
    new = [x for x in new if substantial(x)]
    return any(like(a, b) for a in old for b in new)


def dedupe(lines):
    out = []
    for line in lines:
        if line.strip() and line not in out:
            out.append(line)
    return out


# --------------------------------------------------------------------------- the local file


def starter(path, shipped):
    """The local file as a split starts it, when there is none yet."""
    local = install.lib().local_file(path)
    if local == install.lib().LOCAL_RULES:
        return (update.TEMPLATE / local).read_text(encoding="utf-8")
    title = next((heading_name(x) for x in shipped.splitlines() if x.startswith("# ")), "Instructions")
    return "# %s, this workspace's own\n\n%s\n" % (title, install.lib().LOCAL_HEADER)


def section_end(lines, start):
    """The index where the section opened at `start` ends: the next heading of
    its level or higher, or the end. A line in a code block is never a heading."""
    heads = headings(lines)
    return next((k for k in range(start + 1, len(lines)) if heads[k]), len(lines))


def headings(lines):
    """For each of `lines`, whether it is a heading: one outside every code block."""
    return [is_heading(x) and not inside for x, inside in zip(lines, fenced(lines))]


def insert_block(lines, at, block):
    """Put `block` at `at`, with one blank line on each side."""
    before = lines[:at]
    while before and not before[-1].strip():
        before.pop()
    after = lines[at:]
    while after and not after[0].strip():
        after.pop(0)
    return before + [""] + block + ([""] + after if after else [])


def render(existing, name, additions, decisions):
    """The local file's text: `existing` with each addition under its heading,
    and each decision under the review heading."""
    lines = existing.splitlines()

    def review_at():
        heads = headings(lines)
        return next((k for k, x in enumerate(lines) if heads[k] and REVIEW_RE.match(x)), None)

    for section, block in additions:
        heads = headings(lines)
        if section is None:
            at = next((k for k, x in enumerate(lines) if heads[k] and not x.startswith("# ")), len(lines))
            lines = insert_block(lines, at, block)
            continue
        found = next((k for k, x in enumerate(lines) if heads[k] and norm(x) == norm(section)), None)
        if found is not None:
            lines = insert_block(lines, section_end(lines, found), block) if block else lines
        else:
            at = review_at()
            lines = insert_block(lines, len(lines) if at is None else at, [section, ""] + block if block else [section])

    if decisions:
        at = review_at()
        if at is None:
            lines = insert_block(lines, len(lines), [
                REVIEW % name, "",
                "The split could not place these on its own. Until you settle one, what it says here holds. Take "
                "them one at a time: keep yours and move it under its heading above, take Garrick's and delete "
                "the passage here, or write it afresh. Then delete this section."])
            at = review_at()
        end = section_end(lines, at)
        numbers = [int(m.group(1)) for x in lines[at:end] for m in [ITEM_RE.match(x)] if m]
        n = max(numbers or [0])
        for d in decisions:
            n += 1
            lines = insert_block(lines, section_end(lines, at), say_decision(n, d, name))
    # One blank line at most between passages; a code block keeps its own as they are.
    inside = fenced(lines)
    lines = [x for k, x in enumerate(lines) if x or inside[k] or k == 0 or lines[k - 1]]
    return "\n".join(lines).rstrip("\n") + "\n"


def where(section):
    return "under %s" % heading_name(section) if section else "at the top"


def named(lines):
    """Lines named by their opening words: "A…", "B…" and "C…"."""
    quoted = ['"%s"' % opening(x) for x in lines]
    return quoted[0] if len(quoted) == 1 else ", ".join(quoted[:-1]) + " and " + quoted[-1]


def say_decision(n, d, name):
    """One decision, as the review section holds it."""
    if d["kind"] == "unplaced":
        return ["### %d. Not placed" % n, "", "Lines of your earlier %s the split found no place for. They hold here "
                "until you settle them:" % name, ""] + d["yours"]
    one = len(d["garrick"]) == 1
    noun = "code block" if all("\n" in x for x in d["garrick"]) else "line"
    garrick = "Garrick's %s%s beginning %s" % (noun, "" if one else "s", named(d["garrick"]))
    if d["kind"] in ("removed", "absent"):
        if d["kind"] == "absent":
            body = "Your earlier %s had nothing like %s, which %s in `%s` now." % (
                name, garrick, "stands" if one else "stand", name)
        elif d["newer"]:
            body = "You had removed %s. Garrick has since reworded %s, as %s, and that stands in `%s`." % (
                garrick, "it" if one else "them", named(d["newer"]), name)
        elif d.get("rewritten"):
            body = "You had removed %s. Garrick has since rewritten that passage, and its wording stands in `%s`." % (
                garrick, name)
        else:
            body = "You had removed %s. %s in `%s` again." % (garrick, "It stands" if one else "They stand", name)
        body += " If %s must not hold here, say so in this file; if %s may, delete this passage." % (
            "it" if one else "they", "it" if one else "they")
        return ["### %d. %s, %s" % (n, "Not in yours" if d["kind"] == "absent" else "Removed", where(d["section"])),
                "", body]
    if d["kind"] == "both":
        if d["newer"]:
            now = "Garrick has since changed it too: it now reads %s." % named(d["newer"])
        elif d.get("rewritten"):
            now = "Garrick has since rewritten that passage too."
        else:
            now = "Garrick has since removed it."
        head = "### %d. Changed on both sides, %s" % (n, where(d["section"]))
        body = "You changed %s. %s Yours, which holds here until you settle it:" % (garrick, now)
    else:
        head = "### %d. Changed, %s" % (n, where(d["section"]))
        if d.get("known_base", True):
            body = "You changed %s, which stands in `%s` as it was. Yours, which holds here until you settle it:" % (
                garrick, name)
        else:
            body = "Yours reads like %s, which stands in `%s`. Yours holds here until you settle it:" % (garrick, name)
    return [head, "", body, ""] + d["yours"]


def unplaced(user, base, shipped, local):
    """Lines of your file found neither in Garrick's file nor in the local
    file, and not Garrick's own wording that it has since dropped."""
    have = {norm(x) for x in shipped.splitlines()} | {norm(x) for x in local.splitlines()}
    dropped = {norm(x) for x in base.splitlines()} - {norm(x) for x in shipped.splitlines()}
    out = []
    for line in user.splitlines():
        n = norm(line)
        if n and n not in have and n not in dropped and line not in out:
            out.append(line)
    return out


# --------------------------------------------------------------------------- the base


def git_bytes(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    return r.stdout if r.returncode == 0 else None


# The subjects of the commits in which Garrick itself writes a file: the
# installer's, an update's, a zone scaffold.py adds, and the split's.
GARRICK_COMMIT_RE = re.compile(r"^Garrick: (workspace created|update to |.+ created$|.+ as shipped, your text in )")


def garrick_versions(root, path, known):
    """Garrick's versions of `path` in the history of the repository that holds
    it, newest first: [(commit, text)]. Only what a commit wrote counts, and
    only when it is Garrick's: a fingerprint Garrick shipped, the `.new` an
    update wrote beside the file, or a write in one of Garrick's own commits."""
    repo = update.repo_of(root, path)
    rel = update.path_in_repo(root, path)
    names = (rel, rel + update.NEW_SUFFIX)
    log = git_bytes(repo, "log", "-n", str(HISTORY), "--no-renames", "--format=%x00%H %s", "--name-only", "--",
                    *names)
    out, seen = [], set()
    for record in (log or b"").decode("utf-8", "replace").split("\0")[1:]:
        lines = record.strip("\n").splitlines()
        if not lines:
            continue
        commit, _, subject = lines[0].partition(" ")
        for name in names:
            if name not in lines[1:]:
                continue                            # this commit did not write it
            data = git_bytes(repo, "show", "%s:%s" % (commit, name))
            if data is None:
                continue                            # it removed it
            h = digest(data)
            if h in seen:
                continue
            if h in known or name.endswith(update.NEW_SUFFIX) or GARRICK_COMMIT_RE.match(subject):
                seen.add(h)
                out.append((commit[:7], data.decode("utf-8", "replace")))
    return out


def closest(user, versions):
    """The version `user` is most like, the newest of equals: (commit, text), or None."""
    best, score = None, -1.0
    lines = user.splitlines()
    for commit, text in versions:
        ratio = difflib.SequenceMatcher(None, text.splitlines(), lines, autojunk=False).ratio()
        if ratio > score:
            best, score = (commit, text), ratio
    return best


# --------------------------------------------------------------------------- the plan


def plan(root, p, only=None):
    """What the split would do to each instruction file the update found
    changed: [{path, local, base, additions, decisions, garrick, text, ...}]."""
    lib = install.lib()
    known = update.known_hashes(update.zones_of(root, lib.read_version(root)))
    paths = list(p["actions"]["split"])
    if only:
        unknown = sorted(set(only) - set(paths))
        if unknown:
            raise UpdateError("Not an instruction file of Garrick's that you changed: %s. Name files as the "
                              "report lists them." % ", ".join(unknown))
        paths = [x for x in paths if x in only]
    out = []
    for path in paths:
        data, mode = p["files"][path]
        shipped = data.decode("utf-8")
        user = (root / path).read_text(encoding="utf-8", errors="replace")
        local = lib.local_file(path)
        name = path.rpartition("/")[2]
        ok = set(known.get(path, ())) | {digest(data)}
        if isinstance(p["recorded"].get(path), str):
            ok.add(p["recorded"][path])
        found = closest(user, garrick_versions(root, path, ok))
        base = found[1] if found else shipped
        additions, decisions = split_text(user, base, shipped, known_base=found is not None)
        existing = (root / local).read_text(encoding="utf-8", errors="replace") if (root / local).is_file() else None
        text = render(existing if existing is not None else starter(path, shipped), name, additions, decisions)
        left = unplaced(user, base, shipped, text)
        if left:
            text = render(text, name, [], [{"kind": "unplaced", "section": None, "garrick": [], "yours": left,
                                            "newer": []}])
        out.append({"path": path, "local": local, "base": found[0] if found else None, "additions": additions,
                    "decisions": decisions, "unplaced": left, "garrick": data, "mode": mode, "text": text,
                    "creates": existing is None, "new": stale_new(root, path, ok)})
    return out


def stale_new(root, path, ok):
    """The `.new` an earlier update left beside `path`, when it is still as
    Garrick wrote it and committed: the split takes its place."""
    new = path + update.NEW_SUFFIX
    data = update.read(root / new)
    if data is None or update.uncommitted(update.repo_of(root, new), update.path_in_repo(root, new)):
        return None
    repo = update.repo_of(root, new)
    subject = git_bytes(repo, "log", "-1", "--format=%s", "--", update.path_in_repo(root, new)) or b""
    return new if digest(data) in ok or subject.startswith(b"Garrick: ") else None


# --------------------------------------------------------------------------- saying it


def say_lines(lines, indent):
    return [indent + x for x in lines]


def report(root, items, applied=False):
    lines = ["Garrick split for %s: Garrick's instruction files back as shipped, your text in the local file "
             "beside each." % root]
    if not items:
        lines.append("Nothing to split: every instruction file of Garrick's is as Garrick shipped it.")
        return "\n".join(lines)
    if not applied:
        lines.append("Nothing has been changed. To make these changes, run the same command with --apply.")
    for it in items:
        lines += ["", "%s: Garrick's as shipped, yours to %s%s." % (
            it["path"], it["local"], ", a new file" if it["creates"] else "")]
        lines.append("  Base: %s." % ("Garrick's version from commit %s, the one your file is closest to" % it["base"]
                                     if it["base"] else
                                     "no Garrick version in its history, so all that differs from this Garrick's "
                                     "counts as yours; some of it may be an older Garrick's wording"))
        if it["additions"]:
            counts = {}
            for section, block in it["additions"]:
                key = heading_name(section) or "the top"
                counts[key] = counts.get(key, 0) + sum(1 for x in block if x.strip())
            lines.append("  Moves what you added: %s." % ", ".join("%s (%d line%s)" % (k, v, "" if v == 1 else "s")
                                                               for k, v in counts.items()))
        if it["decisions"]:
            lines.append("  To settle with you, one at a time; until then they wait under \"%s\" in %s:" % (
                (REVIEW % it["path"].rpartition("/")[2])[3:], it["local"]))
            for n, d in enumerate(it["decisions"], 1):
                lines.append("    %d. %s, %s." % (n, {"changed": "Changed", "both": "Changed on both sides",
                                                      "removed": "Removed", "absent": "Not in yours"}[d["kind"]],
                                                     where(d["section"])))
                lines += say_lines(lines_of(d["garrick"]), "         Garrick's: ")
                lines += say_lines(lines_of(d["newer"]), "         Garrick's now: ")
                lines += say_lines([x for x in d["yours"] if x.strip()], "         Yours: ")
        if it["unplaced"]:
            lines.append("  %d line%s could not be placed and go under the review heading as they are." % (
                len(it["unplaced"]), "" if len(it["unplaced"]) == 1 else "s"))
        if it["new"]:
            lines.append("  %s, Garrick's version an earlier update left, goes: Garrick's file is as shipped now."
                         % it["new"])
    return "\n".join(lines)


def as_json(items):
    return [{k: v for k, v in it.items() if k not in ("garrick", "mode")} for it in items]


# --------------------------------------------------------------------------- doing it


def apply(root, items, today=None):
    """Write each item: Garrick's file, the local file, the removal of a stale
    `.new`, one commit per repository; then the version stamp. Returns
    {"done": [paths], "skipped": [(path, why)], "commits": [...]}."""
    lib = install.lib()
    done, skipped, commits = [], [], []
    by_repo = {}
    for it in items:
        paths = [it["path"], it["local"]] + ([it["new"]] if it["new"] else [])
        if any(lib.link_on_the_way(root, root / x) is not None for x in paths):
            skipped.append((it["path"], "a symbolic link stands on the way to it"))
            continue
        busy = [x for x in paths if update.uncommitted(update.repo_of(root, x), update.path_in_repo(root, x))]
        if busy:
            skipped.append((it["path"], "%s %s changes not committed; commit or discard them, then run again" % (
                " and ".join(busy), "has" if len(busy) == 1 else "have")))
            continue
        if len({update.repo_of(root, x) for x in paths}) != 1:
            skipped.append((it["path"], "its local file would sit in another repository"))
            continue
        by_repo.setdefault(update.repo_of(root, it["path"]), []).append(it)

    for repo, group in sorted(by_repo.items()):
        before, rels = {}, []
        try:
            for it in group:
                for x in [it["path"], it["local"]] + ([it["new"]] if it["new"] else []):
                    target = root / x
                    before[x] = ((target.read_bytes(), target.stat().st_mode & 0o777, None) if target.exists()
                                 else (None, None, update.first_missing(root, target)))
                    rels.append(update.path_in_repo(root, x))
                update.write_bytes(root / it["path"], it["garrick"], it["mode"])
                update.write_bytes(root / it["local"], it["text"].encode("utf-8"), 0o644)
                if it["new"]:
                    (root / it["new"]).unlink()
            update.git(repo, "add", "-A", "--", *rels)
            update.git(repo, "commit", "-q", "-m", commit_message(group), "--", *rels)
        except (UpdateError, OSError) as exc:
            update.git(repo, "reset", "-q", "--", *rels, check=False)
            stuck = update.put_back(root, before)
            for it in group:
                skipped.append((it["path"], "the commit was refused, so it was put back: %s" % exc if not stuck else
                                "the commit was refused, and it could not be put back: restore it with git checkout"))
            continue
        commits.append(update.git(repo, "rev-parse", "--short", "HEAD").stdout.strip() + " in " + (
            os.path.relpath(repo, root) if repo != root else "the workspace"))
        done += [it["path"] for it in group]

    stamped = False
    if done:
        stamped = restamp(root, {it["path"]: digest(it["garrick"]) for it in items if it["path"] in done})
    return {"done": done, "skipped": skipped, "commits": commits, "stamped": stamped}


def commit_message(group):
    if len(group) == 1:
        it = group[0]
        return "Garrick: %s as shipped, your text in %s" % (it["path"], it["local"])
    return "Garrick: %d instruction files as shipped, your text in the local file beside each" % len(group)


def restamp(root, written):
    """Record Garrick's files as written in the version stamp's list, and commit it."""
    lib = install.lib()
    stamp = lib.read_version(root)
    if not isinstance(stamp.get("files"), dict):
        return False
    files = dict(stamp["files"])
    files.update(written)
    if files == stamp["files"]:
        return False
    stamp["files"] = dict(sorted(files.items()))
    rel = "/".join(lib.VERSION_STAMP)
    target = root / rel
    before = {rel: (target.read_bytes(), target.stat().st_mode & 0o777, None)}
    try:
        update.write_bytes(target, (json.dumps(stamp, indent=2) + "\n").encode("utf-8"), 0o644)
        update.git(root, "add", "--", rel)
        update.git(root, "commit", "-q", "-m", "Garrick: version stamp after the split", "--", rel)
    except (UpdateError, OSError):
        update.git(root, "reset", "-q", "--", rel, check=False)
        update.put_back(root, before)
        return False
    return True


def say_applied(items, result):
    lines = []
    for path in result["done"]:
        it = next(x for x in items if x["path"] == path)
        waiting = len(it["decisions"]) + (1 if it["unplaced"] else 0)
        lines.append("%s is Garrick's as shipped; your text is in %s%s." % (
            path, it["local"], ", with %d passage%s to settle under its review heading" % (
                waiting, "" if waiting == 1 else "s") if waiting else ""))
    if result["commits"]:
        lines.append("Committed as %s." % ", ".join(result["commits"]))
    for path, why in result["skipped"]:
        lines.append("Skipped %s: %s." % (path, why))
    if result["stamped"]:
        lines.append("System/garrick-version.json records Garrick's files as written.")
    return "\n".join(lines) or "Nothing to split."


def main(root, p, apply_it=False, only=None, as_json_out=False):
    items = plan(root, p, only)
    if not apply_it:
        print(json.dumps(as_json(items), indent=2) if as_json_out else report(root, items))
        return 0
    result = apply(root, items)
    if as_json_out:
        print(json.dumps(result, indent=2))
    else:
        print(say_applied(items, result))
    return 1 if result["skipped"] else 0
