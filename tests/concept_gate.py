"""The concept check (#654): a pull request that adds a concept must link the decision behind it.

    python3 tests/concept_gate.py

CI runs it on a pull request, with the full history checked out. It reads the pull request's body
from the event payload ($GITHUB_EVENT_PATH) and compares docs/concepts.md at the pull request's base
and at its head. A heading that is new, or whose first sentence changed, needs a line in the body that
names the heading and links its decision: a comment on a Garrick issue, or a file under docs/decisions/
that the pull request adds or changes and whose `concept:` is the heading's text. Anything the check
cannot read fails it: no link, no merge. Outside a pull request it passes and says so.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parent.parent
CONCEPTS = "docs/concepts.md"
COMMENT = re.compile(r"https://github\.com/iamvenuti/garrick/issues/\d+#issuecomment-\d+(?![\w-])")
DECISION = re.compile(r"(?<![\w/.-])docs/decisions/([A-Za-z0-9][A-Za-z0-9._-]*\.md)(?![\w.-])")
SHA = re.compile(r"^[0-9a-fA-F]{7,64}$")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
ATX = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
SETEXT = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
HTML = re.compile(r"<h([1-6])\b[^>]*>(.*?)</h\1\s*>", re.I | re.S)
PREFIX = re.compile(r"^(?:\s{0,3}>|\s*[-*+]\s+|\s*\d+[.)]\s+)+")
SENTENCE_END = re.compile(r"(?<!\be\.g)(?<!\bi\.e)(?<!\betc)[.!?](?=\s+[A-Z`\[(\"'*_<])")


class Unreadable(Exception):
    """The check could not read what it needs. It fails, with this text."""


def plain(text: str) -> str:
    """A heading's text as compared: no backticks, no emphasis marks, no surrounding space, one space between words."""
    return " ".join(text.replace("`", "").replace("*", "").replace("_", " ").split()) if text else ""


def clean_line(line: str) -> str:
    """A line with the quote and list markers a heading can hide behind taken off."""
    return PREFIX.sub("", line, count=1) if PREFIX.match(line) else line


def sections(text: str) -> dict:
    """{heading text: [first block under it, ...]}, a heading met more than once keeping every first block.

    Code blocks hold no heading. ATX headings of any level, Setext headings, and HTML headings count, in a
    quote or a list too, so a concept cannot hide a level down or in markup. Windows line endings read as Unix.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: dict = {}
    current = None            # the key whose first block is being read
    block: list = []          # its first block so far
    state = {"done": True}

    def start(heading):
        nonlocal current, block
        finish()
        current, block = plain(heading), []
        state["done"] = False
        out.setdefault(current, [])
        out[current].append("")

    def finish():
        if current is not None and out.get(current):
            out[current][-1] = " ".join(" ".join(block).split())

    fence = None
    previous = ""             # the line before, for a Setext underline
    for raw in lines:
        m = FENCE.match(raw)
        if fence:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) and not raw.strip().strip(m.group(1)[0]):
                fence = None
            if current is not None and not state["done"]:
                block.append(raw)
            previous = ""
            continue
        if m:
            fence = m.group(1)
            if current is not None and not state["done"]:
                block.append(raw)
            previous = ""
            continue
        line = clean_line(raw)
        h = ATX.match(line)
        if h:
            start(h.group(2) or "")
            previous = ""
            continue
        s = SETEXT.match(raw)
        if s and previous.strip() and not PREFIX.match(previous) and not ATX.match(previous):
            # the line above was the heading: it was read as body, so take it back
            if current is not None and block and block[-1] == previous:
                block.pop()
            start(previous)
            previous = ""
            continue
        found = HTML.findall(line)
        for _, inner in found:
            start(re.sub(r"<[^>]+>", "", inner))
        if found:
            previous = ""
            continue
        if current is not None and not state["done"]:
            if raw.strip():
                block.append(raw.strip())
            elif block:
                state["done"] = True
        previous = raw
    finish()
    return out


def first_sentence(block: str) -> str:
    """The first sentence of a block of text. A block that opens with a code block or a table is its own sentence."""
    m = SENTENCE_END.search(block)
    return block[:m.end()] if m else block


def triggered(base: str, head: str) -> list:
    """The headings of `head` that are new, or whose first sentence changed, against `base`, in order."""
    before = {k: {first_sentence(b) for b in v} for k, v in sections(base).items()}
    out = []
    for key, blocks in sections(head).items():
        if key not in before or any(first_sentence(b) not in before[key] for b in blocks):
            out.append(key)
    return out


def git(*args: str, cwd: Path = REPO) -> str:
    done = subprocess.run(["git", *args], cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if done.returncode:
        raise Unreadable("git %s failed: %s" % (" ".join(args[:2]), done.stderr.decode("utf-8", "replace").strip()))
    return done.stdout.decode("utf-8", "replace")


def show(sha: str, path: str, cwd: Path = REPO) -> str:
    if not SHA.match(sha):
        raise Unreadable("The pull request's commit %r is not a commit name." % sha)
    return git("show", "%s:%s" % (sha, path), cwd=cwd)


def concept_of(note: str) -> str:
    """The `concept:` of a decision note's frontmatter, as a heading's text is compared. Empty when it has none."""
    lines = note.replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        return ""
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, _, value = line.partition(":")
        if key.strip() == "concept":
            value = value.strip()
            if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            return plain(value)
    return ""


def satisfied(heading: str, body: str, others: list, base: str, head: str, cwd: Path = REPO) -> bool:
    """Whether the pull request's body links a decision for `heading`.

    Only a line that names the heading counts. A comment link counts when the line names no other heading
    that needs a decision (a heading inside a longer one's text aside); a decision file counts when it is
    added or changed by the pull request, exists at its head, and has this heading as its `concept:`.
    """
    want = heading.lower()
    for line in body.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        text = plain(line).lower()
        if want not in text:
            continue
        if COMMENT.search(line):
            named = [o for o in others if o.lower() in text]
            # a heading whose text sits inside another named heading's text is not named on its own
            alone = [o for o in named if not any(o != p and o.lower() in p.lower() for p in named)]
            if alone == [heading]:
                return True
        for name in DECISION.findall(line):
            path = "docs/decisions/" + name
            try:
                new = show(head, path, cwd)
            except Unreadable:
                continue
            try:
                old = show(base, path, cwd)
            except Unreadable:
                old = None
            if old != new and concept_of(new) == heading:
                return True
    return False


def check(event_name: str, event_path: str, cwd: Path = REPO) -> tuple:
    """(passed, message). Outside a pull request it passes; inside one, anything unreadable fails."""
    if event_name != "pull_request":
        return True, "Not a pull request: nothing to check."
    try:
        try:
            event = json.loads(Path(event_path).read_text(encoding="utf-8"))
            pr = event["pull_request"]
            base, head = pr["base"]["sha"], pr["head"]["sha"]
            body = pr.get("body") or ""
        except (OSError, ValueError, KeyError, TypeError) as err:
            raise Unreadable("The pull request's details could not be read (%s: %s)." % (type(err).__name__, err))
        if not isinstance(body, str) or not isinstance(base, str) or not isinstance(head, str):
            raise Unreadable("The pull request's details are not text.")
        need = triggered(show(base, CONCEPTS, cwd), show(head, CONCEPTS, cwd))
    except Unreadable as err:
        return False, "Concept check failed: %s" % err
    missing = [h for h in need if not satisfied(h, body, need, base, head, cwd)]
    if not missing:
        return True, "Concept check passed: %d heading(s) needed a decision, each has one." % len(need) if need else \
            "Concept check passed: no new concept."
    return False, ("Concept check failed. Each of these headings in docs/concepts.md is new, or has a new first "
                   "sentence, and the pull request description links no decision for it:\n%s\n"
                   "Write one line per heading in the description, such as `- <heading>: docs/decisions/<n>-<name>.md`, "
                   "or `- <heading>: <link to an issue comment>`. See CONTRIBUTING.md, \"A decision note\"."
                   % "\n".join("  - " + h for h in missing))


def main() -> int:
    ok, message = check(os.environ.get("GITHUB_EVENT_NAME", ""), os.environ.get("GITHUB_EVENT_PATH", ""))
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
