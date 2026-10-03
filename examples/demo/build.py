#!/usr/bin/env python3
"""Build the Garrick demo workspace: Sam Rivera's September 2026.

    python3 examples/demo/build.py --target DIR

Installs a fresh workspace from config.json, then replays four weeks of work on
top of it, one commit at a time, each dated in September 2026: projects and
threads created with the workspace's own scaffold script, meetings and sources
ingested, threads wrapped. The finished files come from content/, which mirrors
the workspace tree. One transcript is left, uncommitted, in the Meetings inbox,
and four mails in the Work zone's Inbox, so "process the inbox" can be shown live.

Standard library only. Deterministic: the same repository gives the same files
and the same commit hashes. Refuses a folder that is not empty.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
CONTENT = HERE / "content"
CONFIG = HERE / "config.json"
INSTALL = REPO / "install.py"

OWNER = "Sam Rivera"
EMAIL = "garrick@localhost"  # what install.py sets when git has no identity
TZ = "+01:00"
INSTALLED = "2026-09-01 09:00"
INBOX = "Wikis/Meetings/raw/inbox/Theo Marsh call 2026-09-28.vtt"
# Saved from Sam's mail program into the Work zone's Inbox. Zone inboxes are
# gitignored, so these never show as changes. A newsletter, which goes to the
# library; Dana's forecast, which files itself under Acme by its domain; Owen's
# quote, whose attachment goes into Acme Review; and Cobalt's notice, which
# copies both Acme and Birch, so the assistant has to ask.
MAIL = ("Zones/Work/Inbox/Freight Ledger Weekly.eml",
        "Zones/Work/Inbox/Pallet forecast by quarter.eml",
        "Zones/Work/Inbox/Second seal-kit quote.eml",
        "Zones/Work/Inbox/Northern lane winter booking window.eml")

# Files whose history is replayed line by line: a list item or table row that
# links to a page not yet written is left out until that page exists. So the
# wiki indexes, logs, concept and entity pages grow as the month goes on. A file
# the plan names more than once, such as a hub note, is written the same way.
LEDGER_DIRS = ("Wikis/Knowledge/wiki/concepts", "Wikis/Knowledge/wiki/entities")
LEDGER_FILES = ("Wikis/Meetings/wiki/index.md", "Wikis/Meetings/wiki/log.md", "Wikis/Knowledge/wiki/log.md")
# Rebuilt from the pages at every Knowledge commit, as the knowledge skill keeps it:
# every page, newest first, each dated the day it last changed.
KNOWLEDGE_INDEX = "Wikis/Knowledge/wiki/index.md"
KNOWLEDGE_KINDS = (("sources", "source"), ("concepts", "concept"), ("entities", "entity"))
UPDATED_RE = re.compile(r"(?m)^updated: \d{4}-\d{2}-\d{2}$")


def project(zone, name, party, thread):
    return ("project", zone, name, party, thread)


def thread(zone, proj, name):
    return ("thread", zone, proj, name)


def todo(*keys):
    """Add the to-do lines containing these words, still open."""
    return ("todo", keys)


def done(*keys):
    """Tick the to-do lines containing these words."""
    return ("done", keys)


def alias(heard, means):
    return ("alias", heard, means)


M = "Meetings/"
K = "Knowledge/"
ACME = "Acme Review/"
BIRCH = "Birch Entry/"
HOUSE = "House/"

# (when, repository, commit message, what the commit does). Paths are relative
# to the repository and copied from content/. Ledgers are restaged by the build.
PLAN = [
    ("2026-09-02 11:05", "Wikis", "Meetings: ingest 260902-acme-kick-off, Acme kick-off", [
        M + "raw/260902-acme-kick-off.txt", M + "wiki/sources/260902-acme-kick-off.md",
        M + "wiki/people/dana-whitlock.md", M + "wiki/people/owen-pike.md"]),
    ("2026-09-02 11:08", "Zones/Work", "New project Acme Review (acme), first thread Supplier Map", [
        project("Work", "Acme Review", "acme", "Supplier Map")]),
    ("2026-09-02 11:12", "Zones/Work", "Acme Review: new thread Freight Terms", [
        thread("Work", "Acme Review", "Freight Terms")]),
    ("2026-09-02 11:20", "Zones/Work", "Work: actions from Acme kick-off", [
        todo("Supplier map to Dana", "Freight options brief, first draft")]),
    ("2026-09-03 09:10", "Wikis", "Meetings: ingest 260903-acme-erp-export-call, Acme ERP export call", [
        M + "raw/260903-acme-erp-export-call.txt", M + "wiki/sources/260903-acme-erp-export-call.md"]),
    ("2026-09-04 12:30", "Wikis", "Meetings: ingest 260904-birch-kick-off, Birch kick-off", [
        M + "raw/260904-birch-kick-off.vtt", M + "wiki/sources/260904-birch-kick-off.md",
        M + "wiki/people/theo-marsh.md", M + "wiki/people/iris-bell.md"]),
    ("2026-09-04 12:34", "Zones/Work", "New project Birch Entry (birch), first thread Market Sizing", [
        project("Work", "Birch Entry", "birch", "Market Sizing")]),
    ("2026-09-04 12:40", "Zones/Work", "Work: actions from Birch kick-off", [
        todo("Market sizing memo")]),
    ("2026-09-04 16:10", "Zones/Work", "Acme Review: supplier list received from Owen", [
        ACME + "Sources/Acme supplier list.csv"]),
    ("2026-09-07 08:30", "Wikis", "Knowledge: ingested Freight Rate Outlook, Autumn 2026 (Pellow & Strand Research)", [
        K + "raw/pellow-strand-freight-rate-outlook-autumn-2026.txt",
        K + "wiki/sources/pellow-strand-freight-rate-outlook-autumn-2026.md",
        K + "wiki/concepts/freight-rate-indexation.md", K + "wiki/concepts/lane-capacity.md",
        K + "wiki/entities/pellow-strand-research.md"]),
    ("2026-09-07 11:10", "Wikis", "Meetings: ingest 260907-birch-distributor-contacts, Birch distributor contacts", [
        M + "raw/260907-birch-distributor-contacts.vtt", M + "wiki/sources/260907-birch-distributor-contacts.md"]),
    ("2026-09-08 08:20", "Wikis", "Knowledge: ingested Nordic Pump Market Review 2026 (Nordic Fluid Equipment Council)", [
        K + "raw/nfec-nordic-pump-market-review-2026.txt", K + "wiki/sources/nfec-nordic-pump-market-review-2026.md",
        K + "wiki/concepts/market-sizing.md", K + "wiki/concepts/distributor-led-entry.md",
        K + "wiki/entities/nordic-fluid-equipment-council.md"]),
    ("2026-09-08 13:15", "Wikis", "Meetings: ingest 260908-acme-pump-line-walk, Acme pump line walk", [
        M + "raw/260908-acme-pump-line-walk.txt", M + "wiki/sources/260908-acme-pump-line-walk.md",
        M + "wiki/people/hana-croft.md"]),
    ("2026-09-08 13:20", "Zones/Work", "Work: actions from Acme pump line walk", [
        todo("Stock cover on the supplier map")]),
    ("2026-09-08 19:30", "Zones/Personal", "New project House (lark), first thread Kitchen", [
        project("Personal", "House", "lark", "Kitchen")]),
    ("2026-09-09 20:10", "Wikis", "Meetings: ingest 260909-pell-kitchen-quote, Pell kitchen quote", [
        M + "raw/260909-pell-kitchen-quote.txt", M + "wiki/sources/260909-pell-kitchen-quote.md",
        M + "wiki/people/corin-pell.md"]),
    ("2026-09-10 11:40", "Wikis", "Meetings: ingest 260910-acme-freight-spend-baseline, Acme freight spend baseline", [
        M + "raw/260910-acme-freight-spend-baseline.vtt", M + "wiki/sources/260910-acme-freight-spend-baseline.md",
        M + "wiki/people/gil-thorne.md"]),
    ("2026-09-10 11:45", "Zones/Work", "Work: actions from Acme freight spend baseline", [
        todo("Freight baseline to Dana")]),
    ("2026-09-10 18:30", "Wikis", "Meetings: ingest 260910-kitchen-quote, Kitchen quote", [
        M + "raw/260910-kitchen-quote.txt", M + "wiki/sources/260910-kitchen-quote.md",
        M + "wiki/people/ray-lark.md"]),
    ("2026-09-10 18:34", "Zones/Personal", "Personal: actions from Kitchen quote", [
        todo("Choose the worktop")]),
    ("2026-09-10 18:40", "Zones/Personal", "House: new thread Roof Repair", [
        thread("Personal", "House", "Roof Repair")]),
    ("2026-09-11 12:10", "Wikis", "Meetings: ingest 260911-birch-sizing-assumptions, Birch sizing assumptions", [
        M + "raw/260911-birch-sizing-assumptions.txt", M + "wiki/sources/260911-birch-sizing-assumptions.md",
        M + "wiki/people/lena-moss.md"]),
    ("2026-09-11 12:15", "Zones/Work", "Work: actions from Birch sizing assumptions", [
        todo("Rerun the sizing")]),
    ("2026-09-11 16:45", "Zones/Work", "Acme Review, Supplier Map: supplier map sent to Dana", [
        ACME + "Deliverables/260911 - Supplier map.md", done("Supplier map to Dana", "Stock cover on the supplier map")]),
    ("2026-09-11 21:15", "Wikis", "Knowledge: ingested Before the Frost: A Roof Checklist (Homewright)", [
        K + "raw/homewright-before-the-frost-roof-checklist.txt",
        K + "wiki/sources/homewright-before-the-frost-roof-checklist.md",
        K + "wiki/concepts/wear-and-tear.md", K + "wiki/entities/homewright.md"]),
    ("2026-09-12 10:15", "Zones/Personal", "House, Kitchen: two quotes compared; Lark & Sons ahead", [
        HOUSE + "House.md", HOUSE + "Deliverables/260912 - Kitchen quotes.md",
        todo("Compare the two kitchen quotes"), done("Compare the two kitchen quotes")]),
    ("2026-09-12 10:25", "Zones/Personal", "House, Roof Repair: left with Ray; waiting on his quote", [
        HOUSE + "Threads/Roof Repair/Roof Repair.md", todo("Chase Ray for the roof quote")]),
    ("2026-09-14 08:45", "Wikis", "Knowledge: ingested Seeing the Whole Chain (Brindle Systems)", [
        K + "raw/brindle-seeing-the-whole-chain.txt", K + "wiki/sources/brindle-seeing-the-whole-chain.md",
        K + "wiki/concepts/supply-chain-visibility.md", K + "wiki/entities/brindle-systems.md"]),
    ("2026-09-14 20:05", "Zones/Personal", "Personal: home insurance renewal due", [
        todo("Renew the home insurance")]),
    ("2026-09-15 15:05", "Wikis", "Meetings: ingest 260915-cobalt-renewal-for-acme, Cobalt renewal for Acme", [
        M + "raw/260915-cobalt-renewal-for-acme.txt", M + "wiki/sources/260915-cobalt-renewal-for-acme.md",
        M + "wiki/people/marta-quill.md"]),
    ("2026-09-15 15:12", "", "Context: alias for Cobalt Freight, learned from dictation", [
        alias("cobalt fright, cobalt freighter", "Cobalt Freight")]),
    ("2026-09-16 08:35", "Wikis", "Knowledge: ingested Shippers push back on volume commitments (The Freight Ledger)", [
        K + "raw/freight-ledger-shippers-push-back-on-volume-commitments.txt",
        K + "wiki/sources/freight-ledger-shippers-push-back-on-volume-commitments.md",
        K + "wiki/concepts/volume-commitments.md", K + "wiki/entities/the-freight-ledger.md"]),
    ("2026-09-16 12:30", "Wikis", "Meetings: ingest 260916-birch-market-sizing-review, Birch market sizing review", [
        M + "raw/260916-birch-market-sizing-review.md", M + "wiki/sources/260916-birch-market-sizing-review.md"]),
    ("2026-09-16 12:40", "Zones/Work", "Birch Entry, Market Sizing: memo presented; Theo closed the sizing", [
        BIRCH + "Deliverables/260916 - Market sizing memo.md", done("Market sizing memo")]),
    ("2026-09-16 12:45", "Zones/Work", "Birch Entry: new thread Carrier Choice", [
        thread("Work", "Birch Entry", "Carrier Choice")]),
    ("2026-09-17 09:25", "Zones/Work", "Birch Entry: new thread Launch Plan", [
        thread("Work", "Birch Entry", "Launch Plan")]),
    ("2026-09-17 09:30", "Zones/Work", "Birch Entry, Market Sizing: finished; outcome recorded", [
        BIRCH + "Threads/Market Sizing/Market Sizing.md", BIRCH + "Birch Entry.md"]),
    ("2026-09-17 17:05", "Wikis", "Meetings: ingest 260917-acme-weekly-check-in, Acme weekly check-in", [
        M + "raw/260917-acme-weekly-check-in.txt", M + "wiki/sources/260917-acme-weekly-check-in.md"]),
    ("2026-09-18 11:50", "Wikis", "Meetings: ingest 260918-birch-carrier-requirements, Birch carrier requirements", [
        M + "raw/260918-birch-carrier-requirements.vtt", M + "wiki/sources/260918-birch-carrier-requirements.md",
        M + "wiki/people/arno-vale.md"]),
    ("2026-09-18 11:55", "Zones/Work", "Work: actions from Birch carrier requirements", [
        todo("Carrier requirements to Iris")]),
    ("2026-09-18 17:20", "Zones/Work", "Acme Review, Freight Terms: first draft of the options brief", [
        ACME + "Deliverables/260918 - Freight options brief.md", done("Freight options brief, first draft")]),
    ("2026-09-18 17:40", "Zones/Work", "Work: sizing invoiced to Birch; Acme's September invoice noted", [
        todo("Invoice Birch", "Invoice Acme"), done("Invoice Birch")]),
    ("2026-09-18 19:05", "Wikis", "Meetings: ingest 260918-kitchen-survey, Kitchen survey", [
        M + "raw/260918-kitchen-survey.txt", M + "wiki/sources/260918-kitchen-survey.md",
        M + "wiki/people/ned-lark.md"]),
    ("2026-09-18 19:10", "Zones/Personal", "Personal: actions from Kitchen survey", [
        todo("Tell Ray yes")]),
    ("2026-09-19 10:00", "Wikis", "Knowledge: ingested Worktops Compared (Homewright)", [
        K + "raw/homewright-worktops-compared.txt", K + "wiki/sources/homewright-worktops-compared.md",
        K + "wiki/concepts/kitchen-worktops.md"]),
    ("2026-09-20 17:30", "Wikis", "Knowledge: ingested Second Sources (Corbel Supply Institute)", [
        K + "raw/corbel-second-sources.txt", K + "wiki/sources/corbel-second-sources.md",
        K + "wiki/concepts/second-sourcing.md", K + "wiki/concepts/safety-stock.md",
        K + "wiki/entities/corbel-supply-institute.md"]),
    ("2026-09-21 08:40", "Wikis", "Knowledge: ingested Carriers race for Nordic capacity (The Freight Ledger)", [
        K + "raw/freight-ledger-carriers-race-for-nordic-capacity.txt",
        K + "wiki/sources/freight-ledger-carriers-race-for-nordic-capacity.md",
        K + "wiki/entities/cobalt-freight.md", K + "wiki/entities/fernway-logistics.md"]),
    ("2026-09-21 15:20", "Wikis", "Meetings: ingest 260921-acme-seal-kit-qualification, Acme seal-kit qualification", [
        M + "raw/260921-acme-seal-kit-qualification.md", M + "wiki/sources/260921-acme-seal-kit-qualification.md",
        M + "wiki/people/felix-rook.md"]),
    ("2026-09-21 19:00", "Wikis", "Meetings: ingest 260921-kitchen-go-ahead, Kitchen go-ahead", [
        M + "raw/260921-kitchen-go-ahead.txt", M + "wiki/sources/260921-kitchen-go-ahead.md"]),
    ("2026-09-21 19:10", "Zones/Personal", "House, Kitchen: Lark & Sons chosen; starts 5 October", [
        HOUSE + "Threads/Kitchen/Kitchen.md", todo("Clear the kitchen", "Pay Ray's deposit"), done("Tell Ray yes")]),
    ("2026-09-22 11:40", "Wikis", "Meetings: ingest 260922-cobalt-northern-lane-for-birch, Cobalt northern lane for Birch", [
        M + "raw/260922-cobalt-northern-lane-for-birch.vtt",
        M + "wiki/sources/260922-cobalt-northern-lane-for-birch.md"]),
    ("2026-09-22 11:44", "Zones/Work", "Work: actions from Cobalt northern lane for Birch", [
        todo("Volume forecast to Marta")]),
    ("2026-09-22 18:20", "Wikis", "Meetings: ingest 260922-home-insurance-renewal, Home insurance renewal", [
        M + "raw/260922-home-insurance-renewal.txt", M + "wiki/sources/260922-home-insurance-renewal.md",
        M + "wiki/people/mina-holt.md"]),
    ("2026-09-22 18:25", "Zones/Personal", "Personal: actions from Home insurance renewal", [
        todo("Tell Wrenfield")]),
    ("2026-09-23 08:30", "Wikis", "Knowledge: ingested Distribution Agreements in the Nordic Countries (Varne & Lisle)", [
        K + "raw/varne-lisle-distribution-agreements-in-the-nordics.txt",
        K + "wiki/sources/varne-lisle-distribution-agreements-in-the-nordics.md",
        K + "wiki/concepts/distribution-agreements.md", K + "wiki/entities/varne-and-lisle.md"]),
    ("2026-09-23 11:10", "Wikis", "Meetings: ingest 260923-birch-distributor-shortlist, Birch distributor shortlist", [
        M + "raw/260923-birch-distributor-shortlist.md", M + "wiki/sources/260923-birch-distributor-shortlist.md",
        M + "wiki/people/ruth-kemp.md"]),
    ("2026-09-23 11:15", "Zones/Work", "Work: actions from Birch distributor shortlist", [
        todo("Questions for the distributor agreement")]),
    ("2026-09-23 16:30", "Zones/Work", "Birch Entry, Carrier Choice: shortlist drafted; waiting on Iris's volumes", [
        BIRCH + "Deliverables/260923 - Carrier shortlist.md", BIRCH + "Threads/Carrier Choice/Carrier Choice.md",
        todo("Chase Fernway")]),
    ("2026-09-24 10:40", "Wikis", "Meetings: ingest 260924-acme-supplier-map-review, Acme supplier map review", [
        M + "raw/260924-acme-supplier-map-review.txt", M + "wiki/sources/260924-acme-supplier-map-review.md"]),
    ("2026-09-24 10:44", "Zones/Work", "Work: actions from Acme supplier map review", [
        todo("Freight options brief, final", "Supplier map, second version")]),
    ("2026-09-24 11:30", "Zones/Work", "Acme Review, Supplier Map: seal kits first; waiting on Owen's quote", [
        ACME + "Threads/Supplier Map/Supplier Map.md", ACME + "Acme Review.md"]),
    ("2026-09-25 10:20", "Wikis", "Meetings: ingest 260925-birch-board-paper-review, Birch board paper review", [
        M + "raw/260925-birch-board-paper-review.txt", M + "wiki/sources/260925-birch-board-paper-review.md"]),
    ("2026-09-25 10:25", "Zones/Work", "Work: actions from Birch board paper review", [
        todo("Board recommendation")]),
    ("2026-09-25 17:50", "Zones/Work", "Acme Review, Freight Terms: brief reworked; due to Dana 2 October", [
        ACME + "Threads/Freight Terms/Freight Terms.md", todo("Test the pallet commitment")]),
    ("2026-09-26 11:15", "Zones/Work", "Birch Entry, Launch Plan: outline drafted; waiting on the board", [
        BIRCH + "Threads/Launch Plan/Launch Plan.md", BIRCH + "Threads/Launch Plan/Outline.md",
        todo("Launch plan: timing and budget")]),
]


class BuildError(Exception):
    pass


# --------------------------------------------------------------------------- helpers


def stamp(when):
    return when.replace(" ", "T") + ":00" + TZ


def git_env(when):
    env = dict(os.environ)
    env.update({
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": OWNER, "GIT_AUTHOR_EMAIL": EMAIL,
        "GIT_COMMITTER_NAME": OWNER, "GIT_COMMITTER_EMAIL": EMAIL,
        "GIT_AUTHOR_DATE": stamp(when), "GIT_COMMITTER_DATE": stamp(when),
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    return env


def run(args, cwd, when, what):
    r = subprocess.run(args, cwd=str(cwd), env=git_env(when), capture_output=True, text=True)
    if r.returncode != 0:
        raise BuildError(f"{what} failed: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout


def present(root):
    """Every file in the workspace, as a lower-cased path without `.md`."""
    out = set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for name in filenames:
            rel = (Path(dirpath) / name).relative_to(root).as_posix().lower()
            out.add(rel[:-3] if rel.endswith(".md") else rel)
    return out


LINK_RE = re.compile(r"\[\[([^\[\]|#\\]+)")


def resolves(target, source_rel, files):
    target = target.strip()
    if target.startswith("../") or target.startswith("./"):
        path = os.path.normpath(os.path.join(os.path.dirname(source_rel), target)).lower()
        return path in files
    target = re.sub(r"\.md$", "", target.lower())
    return any(f == target or f.endswith("/" + target) for f in files)


def ledger_text(text, rel, files):
    """Drop list items and table rows that link to a page not written yet."""
    kept = []
    for line in text.splitlines():
        if line.lstrip().startswith(("- ", "|")):
            if not all(resolves(t, rel, files) for t in LINK_RE.findall(line)):
                continue
        kept.append(line)
    return "\n".join(kept) + "\n"


def is_ledger(rel):
    return rel in LEDGER_FILES or any(rel.startswith(d + "/") for d in LEDGER_DIRS)


def as_far_as(final, rel, files, before, date):
    """`final` as far as the month has got. A page not finished yet is dated the
    day it last changed: `updated:` moves to `date` only when the rest moved."""
    text = ledger_text(final, rel, files)
    if text == final:
        return final
    if before is not None and UPDATED_RE.sub("", before) == UPDATED_RE.sub("", text):
        return before
    return UPDATED_RE.sub("updated: " + date, text)


def knowledge_index(root):
    """The Knowledge wiki's index, from its pages: newest first, then sources,
    concepts and entities, each by name."""
    wiki = root / "Wikis" / "Knowledge" / "wiki"
    rows = []
    for order, (folder, kind) in enumerate(KNOWLEDGE_KINDS):
        for page in sorted((wiki / folder).glob("*.md")):
            text = page.read_text(encoding="utf-8")
            updated = re.search(r"(?m)^updated: (\S+)$", text).group(1)
            name = re.search(r"(?m)^# (.+)$", text).group(1).strip()
            rows.append((updated, order, name.lower(), "| [[wiki/%s/%s\\|%s]] | %s | %s |" % (folder, page.stem, name, kind, updated)))
    rows.sort(key=lambda r: (r[1], r[2]))
    rows.sort(key=lambda r: r[0], reverse=True)
    head = ["# Index", "", "Every page, newest first.", "", "| Page | Type | Updated |", "|---|---|---|"]
    return "\n".join(head + [r[3] for r in rows]) + "\n"


def plan_paths():
    """How many times the plan names each file, by its path in the workspace."""
    count = {}
    for _, repo, _, actions in PLAN:
        for action in actions:
            if isinstance(action, str):
                rel = (Path(repo) / action).as_posix() if repo else action
                count[rel] = count.get(rel, 0) + 1
    return count


# --------------------------------------------------------------------------- to-do lists


class TodoList:
    """Replays a zone's Todo.md: lines appear when the plan adds them, and move to
    Done when the plan ticks them. With every line added and ticked as in
    content/, the result is content/'s file exactly."""

    def __init__(self, text):
        lines = text.rstrip("\n").splitlines()
        i_inbox = lines.index("## Inbox")
        i_done = lines.index("## Done")
        self.head = lines[:i_inbox]
        self.open_items = [l for l in lines[i_inbox + 1:i_done] if l.startswith("- [")]
        self.done_items = [l for l in lines[i_done + 1:] if l.startswith("- [")]
        self.shown, self.ticked = set(), set()

    def _find(self, key):
        hits = [l for l in self.open_items + self.done_items if key in l]
        if len(hits) != 1:
            raise BuildError(f"to-do key {key!r} matches {len(hits)} lines")
        return hits[0]

    def show(self, key):
        self.shown.add(self._find(key))

    def tick(self, key):
        line = self._find(key)
        if line not in self.done_items:
            raise BuildError(f"{key!r} is not ticked in content/")
        self.ticked.add(line)

    def render(self):
        inbox = [l for l in self.open_items if l in self.shown]
        inbox += ["- [ ]" + l[5:] for l in self.done_items if l in self.shown and l not in self.ticked]
        done_ = [l for l in self.done_items if l in self.ticked]
        out = self.head + ["## Inbox", ""] + inbox + ([""] if inbox else []) + ["## Done", ""] + done_
        return "\n".join(out).rstrip("\n") + "\n"


# --------------------------------------------------------------------------- the build


def check_target(target):
    if target.exists():
        if not target.is_dir():
            raise BuildError(f"{target} is a file, not a folder.")
        if [p for p in target.iterdir() if p.name != ".DS_Store"]:
            raise BuildError(f"{target} is not empty. Pick an empty or new folder.")


def scaffold(root, when, args):
    """Run the workspace's own scaffold script, then give what it wrote the plan's date.

    The script stamps today's date and has no option to set another, so the
    `created:` and `updated:` lines of the files it wrote or changed are rewritten.
    """
    zone = root / "Zones" / args[args.index("--zone") + 1]
    before = {p: p.read_bytes() for p in zone.rglob("*.md")}
    run([sys.executable, str(root / "System" / "tools" / "scaffold.py")] + args, root, when, "scaffold")
    stamp_re = re.compile(r"(?m)^(created|updated): \d{4}-\d{2}-\d{2}$")
    date = when.split(" ")[0]
    for path in zone.rglob("*.md"):
        if before.get(path) == path.read_bytes():
            continue
        text = path.read_text(encoding="utf-8")
        if path in before:  # the hub: only `updated` moves
            text = re.sub(r"(?m)^updated: \d{4}-\d{2}-\d{2}$", "updated: " + date, text)
        else:
            text = stamp_re.sub(lambda m: m.group(1) + ": " + date, text)
        path.write_text(text, encoding="utf-8")


def add_alias(root, heard, means):
    path = root / "System" / "context.md"
    lines = path.read_text(encoding="utf-8").splitlines()
    start = lines.index("## Aliases")
    end = start + 1
    while end < len(lines) and not lines[end].startswith("## "):
        end += 1
    rows = [i for i in range(start, end) if lines[i].startswith("|")]
    lines.insert(rows[-1] + 1, f"| {heard} | {means} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build(target):
    # Absolute before anything runs: install.py runs from the source folder, so a
    # relative target would otherwise land, or be refused, there instead of here.
    target = Path(os.path.abspath(Path(target).expanduser()))
    check_target(target)
    if not CONTENT.is_dir():
        raise BuildError(f"{CONTENT} is missing.")
    run([sys.executable, str(INSTALL), "--config", str(CONFIG), "--target", str(target)], REPO, INSTALLED, "install.py")
    root = target.resolve()

    todos = {z: TodoList((CONTENT / "Zones" / z / "Todo.md").read_text(encoding="utf-8")) for z in ("Work", "Personal")}
    named = plan_paths()
    copied = set()
    for when, repo, message, actions in PLAN:
        repo_dir = root / repo if repo else root
        date = when.split(" ")[0]
        touched = set()
        for action in actions:
            if isinstance(action, str):
                rel = (Path(repo) / action).as_posix() if repo else action
                src = CONTENT / rel
                if not src.is_file():
                    raise BuildError(f"the plan names {rel}, which is not in content/")
                dst = root / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                if named[rel] > 1:  # finished at its last naming; until then, as far as the month has got
                    before = dst.read_text(encoding="utf-8") if dst.is_file() else None
                    dst.write_text(as_far_as(src.read_text(encoding="utf-8"), rel, present(root), before, date),
                                   encoding="utf-8")
                else:
                    shutil.copyfile(src, dst)
                copied.add(rel)
                touched.add(rel)
            elif action[0] == "project":
                _, zone, name, party, first = action
                scaffold(root, when, ["project", "--zone", zone, "--name", name, "--party", party, "--thread", first])
            elif action[0] == "thread":
                _, zone, proj, name = action
                scaffold(root, when, ["thread", "--zone", zone, "--project", proj, "--name", name])
            elif action[0] in ("todo", "done"):
                todo_list = todos[repo.split("/")[-1]]
                for key in action[1]:
                    (todo_list.show if action[0] == "todo" else todo_list.tick)(key)
                (repo_dir / "Todo.md").write_text(todo_list.render(), encoding="utf-8")
                copied.add(f"{repo}/Todo.md")
            elif action[0] == "alias":
                add_alias(root, action[1], action[2])
            else:
                raise BuildError(f"unknown action {action!r}")

        # Restage the ledgers of the wiki this commit wrote to, as far as the month has got.
        files = present(root)
        for wiki in ("Wikis/Meetings/", "Wikis/Knowledge/"):
            if not any(t.startswith(wiki) for t in touched):
                continue
            for src in sorted(CONTENT.rglob("*.md")):
                rel = src.relative_to(CONTENT).as_posix()
                if rel.startswith(wiki) and is_ledger(rel) and (rel in LEDGER_FILES or (root / rel).exists()):
                    path = root / rel
                    before = path.read_text(encoding="utf-8") if path.is_file() else None
                    path.write_text(as_far_as(src.read_text(encoding="utf-8"), rel, files, before, date), encoding="utf-8")
                    copied.add(rel)
            if wiki == "Wikis/Knowledge/":
                (root / KNOWLEDGE_INDEX).write_text(knowledge_index(root), encoding="utf-8")
                copied.add(KNOWLEDGE_INDEX)

        run(["git", "add", "-A"], repo_dir, when, f"staging for {message!r}")
        run(["git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", message], repo_dir, when, f"commit {message!r}")

    # The one transcript still waiting in the inbox: dropped by the recorder, not committed.
    shutil.copyfile(CONTENT / INBOX, root / INBOX)
    copied.add(INBOX)
    for rel in MAIL:
        shutil.copyfile(CONTENT / rel, root / rel)
        copied.add(rel)

    # Every file in content/ must now be in place, exactly, and every repository clean.
    for src in sorted(p for p in CONTENT.rglob("*") if p.is_file() and p.name != ".DS_Store"):
        rel = src.relative_to(CONTENT).as_posix()
        dst = root / rel
        if not dst.is_file() or dst.read_bytes() != src.read_bytes():
            raise BuildError(f"{rel} did not end up as it is in content/; check the plan in build.py")
    for repo in ("", "Wikis", "Zones/Work", "Zones/Personal"):
        status = run(["git", "status", "--porcelain", "--untracked-files=all"], root / repo if repo else root, INSTALLED, "git status")
        stray = [l for l in status.splitlines() if Path(INBOX).name not in l]
        if stray:
            raise BuildError(f"{repo or 'the root'} has changes the plan did not commit: {stray}")
    return root


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build the Garrick demo workspace (Sam Rivera, September 2026).")
    ap.add_argument("--target", required=True, help="an empty or new folder")
    args = ap.parse_args(argv)
    try:
        root = build(args.target)
    except BuildError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"Demo workspace built at {root}")
    print(f"  {len(PLAN)} commits after the install, 1 to 26 September 2026.")
    print(f"  One transcript waiting in the inbox: {Path(INBOX).name}")
    print(f"  {len(MAIL)} mails waiting in the Work zone's Inbox.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
