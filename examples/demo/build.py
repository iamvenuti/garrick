#!/usr/bin/env python3
"""Build the Garrick demo workspace: a month of Sam Rivera's work, ending about now.

    python3 examples/demo/build.py --target DIR [--today YYYY-MM-DD]

Installs a fresh workspace from config.json, then replays four weeks of work on
top of it, one dated commit at a time: projects and threads created with the
workspace's own scaffold script, meetings and sources ingested, threads
wrapped. The finished files come from content/, which mirrors the workspace
tree. One transcript is left, uncommitted, in the Meetings inbox, and four
mails in the Work zone's Inbox, so "process the inbox" can be shown live.

content/ and the plan below are written as September 2026, ending on Monday
28 September. The build moves the whole month forward by whole weeks, so its
last day falls on the day it is built or in the six days before, the way
examples/example-work/build.py dates its story from the day it is built.
Whole weeks keep every "Friday" on a Friday. `--today` builds as if on another
day.

Standard library only. Deterministic: the same files in the repository and the
same build day give the same files and the same commit hashes, whatever its
commit and whether it has edits not committed. Refuses a folder that is not
empty.
"""

from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
CONTENT = HERE / "content"
CONFIG = HERE / "config.json"
INSTALL = REPO / "install.py"
EXAMPLE_BUILD = REPO / "examples" / "example-work" / "build.py"

OWNER = "Sam Rivera"
EMAIL = "garrick@localhost"  # what install.py sets when git has no identity
TZ = "+01:00"
# Every date below and in content/ is as written, in September 2026; build() moves
# them all by the same whole number of weeks (see *Dates*).
INSTALLED = "2026-09-01 09:00"
# Which Garrick the demo says it was installed from. The installer records the
# source's own commit, its date and whether it has edits not committed; the
# demo records this instead, so a commit or an edit in the source between two
# builds does not change the workspace's first commit (#209).
VERSION_STAMP = "System/garrick-version.json"
DEMO_VERSION = {"commit": "demo", "date": INSTALLED.split(" ")[0]}
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
    ("2026-09-03 16:20", "Zones/Work", "Acme Review: scope and plan sent to Dana", [
        ACME + "Deliverables/260903 - Scope and plan.md"]),
    ("2026-09-04 12:30", "Wikis", "Meetings: ingest 260904-birch-kick-off, Birch kick-off", [
        M + "raw/260904-birch-kick-off.vtt", M + "wiki/sources/260904-birch-kick-off.md",
        M + "wiki/people/theo-marsh.md", M + "wiki/people/iris-bell.md"]),
    ("2026-09-04 12:34", "Zones/Work", "New project Birch Entry (birch), first thread Market Sizing", [
        project("Work", "Birch Entry", "birch", "Market Sizing")]),
    ("2026-09-04 12:40", "Zones/Work", "Work: actions from Birch kick-off", [
        todo("Market sizing memo", "Sizing assumptions to Iris")]),
    ("2026-09-04 16:10", "Zones/Work", "Acme Review: supplier list received from Owen", [
        ACME + "Sources/Acme supplier list.csv"]),
    ("2026-09-07 08:30", "Wikis", "Knowledge: ingested Freight Rate Outlook, Autumn 2026 (Pellow & Strand Research)", [
        K + "raw/pellow-strand-freight-rate-outlook-autumn-2026.txt",
        K + "wiki/sources/pellow-strand-freight-rate-outlook-autumn-2026.md",
        K + "wiki/concepts/freight-rate-indexation.md", K + "wiki/concepts/lane-capacity.md",
        K + "wiki/entities/pellow-strand-research.md"]),
    ("2026-09-07 11:10", "Wikis", "Meetings: ingest 260907-birch-distributor-contacts, Birch distributor contacts", [
        M + "raw/260907-birch-distributor-contacts.vtt", M + "wiki/sources/260907-birch-distributor-contacts.md"]),
    ("2026-09-07 11:30", "Zones/Work", "Birch Entry: distributor contacts received from Iris", [
        BIRCH + "Sources/Birch distributor contacts.csv"]),
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
    ("2026-09-10 15:30", "Zones/Work", "Acme Review: line stoppage log received from Owen", [
        ACME + "Sources/Pump line stoppages.csv"]),
    ("2026-09-10 17:00", "Zones/Work", "Birch Entry, Market Sizing: assumptions sent to Iris for Friday", [
        BIRCH + "Deliverables/260910 - Sizing assumptions.md",
        done("Sizing assumptions to Iris")]),
    ("2026-09-10 18:30", "Wikis", "Meetings: ingest 260910-kitchen-quote, Kitchen quote", [
        M + "raw/260910-kitchen-quote.txt", M + "wiki/sources/260910-kitchen-quote.md",
        M + "wiki/people/ray-lark.md"]),
    ("2026-09-10 18:34", "Zones/Personal", "Personal: actions from Kitchen quote", [
        todo("Choose the worktop", "Compare the two kitchen quotes")]),
    ("2026-09-10 18:40", "Zones/Personal", "House: new thread Roof Repair", [
        thread("Personal", "House", "Roof Repair")]),
    ("2026-09-11 12:10", "Wikis", "Meetings: ingest 260911-birch-sizing-assumptions, Birch sizing assumptions", [
        M + "raw/260911-birch-sizing-assumptions.txt", M + "wiki/sources/260911-birch-sizing-assumptions.md",
        M + "wiki/people/lena-moss.md"]),
    ("2026-09-11 12:15", "Zones/Work", "Work: actions from Birch sizing assumptions", [
        todo("Rerun the sizing")]),
    ("2026-09-11 14:05", "Zones/Work", "Acme Review: last year's freight spend received from Gil", [
        ACME + "Sources/Acme freight spend 2025.csv"]),
    ("2026-09-11 16:45", "Zones/Work", "Acme Review, Supplier Map: supplier map sent to Dana", [
        ACME + "Deliverables/260911 - Supplier map.md", done("Supplier map to Dana", "Stock cover on the supplier map")]),
    ("2026-09-11 21:15", "Wikis", "Knowledge: ingested Before the Frost: A Roof Checklist (Homewright)", [
        K + "raw/homewright-before-the-frost-roof-checklist.txt",
        K + "wiki/sources/homewright-before-the-frost-roof-checklist.md",
        K + "wiki/concepts/wear-and-tear.md", K + "wiki/entities/homewright.md"]),
    ("2026-09-12 10:15", "Zones/Personal", "House, Kitchen: two quotes compared; Lark & Sons ahead", [
        HOUSE + "House.md", HOUSE + "Deliverables/260912 - Kitchen quotes.md",
        done("Compare the two kitchen quotes")]),
    ("2026-09-12 10:25", "Zones/Personal", "House, Roof Repair: left with Ray; waiting on his quote", [
        HOUSE + "Threads/Roof Repair/Roof Repair.md", HOUSE + "Threads/Roof Repair/Questions for Ray.md",
        todo("Chase Ray for the roof quote")]),
    ("2026-09-14 08:45", "Wikis", "Knowledge: ingested Seeing the Whole Chain (Brindle Systems)", [
        K + "raw/brindle-seeing-the-whole-chain.txt", K + "wiki/sources/brindle-seeing-the-whole-chain.md",
        K + "wiki/concepts/supply-chain-visibility.md", K + "wiki/entities/brindle-systems.md"]),
    ("2026-09-14 10:30", "Zones/Work", "Birch Entry, Market Sizing: export price list in; sizing rerun", [
        BIRCH + "Sources/Birch export price list.csv", done("Rerun the sizing")]),
    ("2026-09-14 15:40", "Zones/Work", "Acme Review, Freight Terms: baseline to Dana; questions for the renewal call", [
        ACME + "Deliverables/260914 - Freight baseline.md", ACME + "Threads/Freight Terms/Renewal call questions.md",
        done("Freight baseline to Dana")]),
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
        BIRCH + "Deliverables/260916 - Market sizing memo.md", BIRCH + "Threads/Market Sizing/Sizing model.md",
        done("Market sizing memo")]),
    ("2026-09-16 12:45", "Zones/Work", "Birch Entry: new thread Carrier Choice", [
        thread("Work", "Birch Entry", "Carrier Choice")]),
    ("2026-09-17 09:25", "Zones/Work", "Birch Entry: new thread Launch Plan", [
        thread("Work", "Birch Entry", "Launch Plan")]),
    ("2026-09-17 09:30", "Zones/Work", "Birch Entry, Market Sizing: finished; outcome recorded", [
        BIRCH + "Threads/Market Sizing/Market Sizing.md", BIRCH + "Birch Entry.md", todo("Invoice Birch")]),
    ("2026-09-17 17:05", "Wikis", "Meetings: ingest 260917-acme-weekly-check-in, Acme weekly check-in", [
        M + "raw/260917-acme-weekly-check-in.txt", M + "wiki/sources/260917-acme-weekly-check-in.md"]),
    ("2026-09-18 11:50", "Wikis", "Meetings: ingest 260918-birch-carrier-requirements, Birch carrier requirements", [
        M + "raw/260918-birch-carrier-requirements.vtt", M + "wiki/sources/260918-birch-carrier-requirements.md",
        M + "wiki/people/arno-vale.md"]),
    ("2026-09-18 11:55", "Zones/Work", "Work: actions from Birch carrier requirements", [
        todo("Carrier requirements to Iris")]),
    ("2026-09-18 15:10", "Zones/Work", "Birch Entry, Carrier Choice: requirements sent to Iris and Arno", [
        BIRCH + "Deliverables/260918 - Carrier requirements.md", done("Carrier requirements to Iris")]),
    ("2026-09-18 17:20", "Zones/Work", "Acme Review, Freight Terms: first draft of the options brief", [
        ACME + "Deliverables/260918 - Freight options brief.md", done("Freight options brief, first draft")]),
    ("2026-09-18 17:40", "Zones/Work", "Work: sizing invoiced to Birch; Acme's September invoice noted", [
        todo("Invoice Acme"), done("Invoice Birch")]),
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
        HOUSE + "Threads/Kitchen/Kitchen.md", HOUSE + "Threads/Kitchen/Worktop options.md", HOUSE + "House.md",
        todo("Clear the kitchen", "Pay Ray's deposit"), done("Tell Ray yes")]),
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
        BIRCH + "Threads/Carrier Choice/Volume forecast.md", todo("Chase Fernway")]),
    ("2026-09-24 10:40", "Wikis", "Meetings: ingest 260924-acme-supplier-map-review, Acme supplier map review", [
        M + "raw/260924-acme-supplier-map-review.txt", M + "wiki/sources/260924-acme-supplier-map-review.md"]),
    ("2026-09-24 10:44", "Zones/Work", "Work: actions from Acme supplier map review", [
        todo("Freight options brief, final", "Supplier map, second version")]),
    ("2026-09-24 11:30", "Zones/Work", "Acme Review, Supplier Map: seal kits first; waiting on Owen's quote", [
        ACME + "Threads/Supplier Map/Supplier Map.md", ACME + "Threads/Supplier Map/Single-source parts.md",
        ACME + "Acme Review.md"]),
    ("2026-09-25 10:20", "Wikis", "Meetings: ingest 260925-birch-board-paper-review, Birch board paper review", [
        M + "raw/260925-birch-board-paper-review.txt", M + "wiki/sources/260925-birch-board-paper-review.md"]),
    ("2026-09-25 10:25", "Zones/Work", "Work: actions from Birch board paper review", [
        todo("Board recommendation")]),
    ("2026-09-25 16:10", "Zones/Work", "Birch Entry, Launch Plan: one-page recommendation to Iris for the board", [
        BIRCH + "Deliverables/260925 - Board recommendation.md", done("Board recommendation")]),
    ("2026-09-25 17:50", "Zones/Work", "Acme Review, Freight Terms: brief reworked; due to Dana 2 October", [
        ACME + "Threads/Freight Terms/Freight Terms.md", ACME + "Threads/Freight Terms/Cost model.md",
        todo("Test the pallet commitment")]),
    ("2026-09-26 11:15", "Zones/Work", "Birch Entry, Launch Plan: outline drafted; waiting on the board", [
        BIRCH + "Threads/Launch Plan/Launch Plan.md", BIRCH + "Threads/Launch Plan/Outline.md",
        BIRCH + "Threads/Launch Plan/Distributor terms.md", BIRCH + "Birch Entry.md",
        todo("Launch plan: timing and budget")]),
]


class BuildError(Exception):
    pass


# --------------------------------------------------------------------------- dates


def _example_work():
    """examples/example-work/build.py, whose month names, weekday names and
    ordinals the demo writes its dates with."""
    spec = importlib.util.spec_from_file_location("garrick_example_build_for_demo", EXAMPLE_BUILD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_EW = _example_work()
MONTHS, WEEKDAYS, nth = _EW.MONTHS, _EW.WEEKDAYS, _EW.nth
DAY = _EW.DAY

# The demo's last day as written: Theo's call and the four mails, Monday 28 September.
LAST_DAY = datetime.date(2026, 9, 28)
# The story's months, September to December 2026. A date in them moves; one
# before them (a stoppage last year, a report published in August) is
# background and stays where it is, and so do month names outside them
# ("launch in March", the forecast's March to August, "from January 2027").
STORY = (datetime.date(2026, 9, 1), datetime.date(2026, 12, 31))

ORDINALS = ("first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth "
            "fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth twentieth").split()
ORDINALS += ["twenty-" + w for w in ORDINALS[:9]] + ["thirtieth", "thirty-first"]
ABBREVIATIONS = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "Jun": 6, "Jul": 7, "Aug": 8, "Sep": 9, "Sept": 9,
                 "Oct": 10, "Nov": 11, "Dec": 12}


def weeks_for(today):
    """The whole weeks to move the month by, so its last day is `today` or one
    of the six days before it."""
    return (today - LAST_DAY).days // 7


_MONTH = "|".join(MONTHS)
_ABBR = "|".join(sorted(ABBREVIATIONS, key=len, reverse=True))
_ORD = "|".join(sorted(ORDINALS, key=len, reverse=True))
_WEEKDAY = "|".join(WEEKDAYS)
_ORD_CI = "(?:%s)" % "|".join("[%s%s]%s" % (w[0], w[0].upper(), re.escape(w[1:])) for w in
                              sorted(ORDINALS, key=len, reverse=True))
NOT_OF_MONTH = r"(?! of (?:%s)\b)" % _MONTH
DATE_RE = re.compile("|".join([
    # 2026-09-28, in frontmatter, to-do lines, file names and commit dates.
    r"(?P<iso>\b(?P<iso_y>\d{4})-(?P<iso_m>\d{2})-(?P<iso_d>\d{2})\b)",
    # 20260928070000, a mail's Message-ID.
    r"(?P<stamp>\b(?P<st_y>\d{4})(?P<st_m>\d{2})(?P<st_d>\d{2})(?=\d{6}\.))",
    # 260928, the date a meeting id or a deliverable's name starts with.
    r"(?P<yymmdd>\b(?P<ym_y>2\d)(?P<ym_m>[01]\d)(?P<ym_d>[0-3]\d)\b)",
    # 28 September 2026, 28 September, 28 Sep 2026.
    r"(?P<dm>\b(?P<dm_d>\d{1,2}) (?P<dm_m>%s|%s)\b(?: (?P<dm_y>\d{4})\b)?)" % (_MONTH, _ABBR),
    # the fifth of October, First of October.
    r"(?P<of>\b(?P<of_o>%s) of (?P<of_m>%s)\b)" % (_ORD_CI, _MONTH),
    # Friday the ninth, Monday, the fifth, Friday. The fourth, Friday the 2nd.
    r"(?P<wd>\b(?P<wd_w>%s)(?P<wd_sep>[.,]? [Tt]he )(?P<wd_o>%s|\d{1,2}(?:st|nd|rd|th))\b%s)"
    % (_WEEKDAY, _ORD, NOT_OF_MONTH),
    # on the 11th, by the 30th.
    r"(?P<num>\bthe (?P<num_n>\d{1,2})(?:st|nd|rd|th)\b%s)" % NOT_OF_MONTH,
    # by the eleventh. on the tenth, before the fifteenth? (never "before the first frosts").
    r"(?P<by>\b(?P<by_p>(?:[Bb]y|[Oo]n|[Bb]efore) the )(?P<by_o>%s)(?=[.,?!\"']|$))" % _ORD,
    # The eleventh works. The thirtieth, yes. The ninth is fine. (never "The second thing").
    r"(?P<the>\bThe (?P<the_o>%s)(?=[.,]| (?:is|works)\b))" % _ORD,
    # mid-September, the first week of October, August's, Published August 2026.
    r"(?P<month>\b(?P<mo_m>%s)\b(?: (?P<mo_y>\d{4})\b)?)" % _MONTH,
]), re.M)
# A past tense earlier in the sentence: "sent on the eleventh" looks back, "meets on the twenty-eighth" ahead.
PAST_RE = re.compile(r"\b(?:went|sent|received|priced|was|were)\b[^.!?:]*$")
FRONTMATTER_DATE_RE = re.compile(r"(?m)^date: (\d{4}-\d{2}-\d{2})$")


def _date(y, m, d):
    try:
        return datetime.date(int(y), int(m), int(d))
    except ValueError:
        return None


def _in_story(day):
    return day is not None and STORY[0] <= day <= STORY[1]


def _ordinal_day(word):
    word = word.lower()
    return int(word[:-2]) if word[:1].isdigit() else ORDINALS.index(word) + 1


def _ordinal_like(word, day):
    """`day` as an ordinal written the way `word` was: 2nd, second or Second."""
    if word[:1].isdigit():
        return nth(day)
    out = ORDINALS[day - 1]
    return out[:1].upper() + out[1:] if word[:1].isupper() else out


def _resolve(day_of_month, ref, weekday=None, past=False):
    """The date a day of the month without its month means, seen from `ref`:
    on that weekday when one is given, the nearest; otherwise the next one, or
    the last one when the sentence looks back."""
    span = [ref + k * DAY for k in range(-45, 46)]
    hits = [d for d in span if d.day == day_of_month and (weekday is None or d.weekday() == weekday)]
    if weekday is not None:
        return min(hits, key=lambda d: (abs((d - ref).days), d < ref)) if hits else None
    if past:
        hits = [d for d in hits if d <= ref]
        return hits[-1] if hits else None
    hits = [d for d in hits if d >= ref]
    return hits[0] if hits else None


def shift_text(text, days, ref=LAST_DAY):
    """`text` with every date of the story moved `days` days, each written as it
    was. A day of the month without its month ("by the eleventh") is read
    against the latest full date before it, such as a note's dated entry or a
    transcript's first line, or `ref` before there is one."""
    if not days:
        return text
    delta = days * DAY
    m = FRONTMATTER_DATE_RE.search(text)
    state = {"ref": _date(*m.group(1).split("-")) if m else ref}

    def one(m):
        g = m.groupdict()
        whole = m.group(0)
        if g["iso"]:
            day = _date(g["iso_y"], g["iso_m"], g["iso_d"])
            return (day + delta).isoformat() if _in_story(day) else whole
        if g["stamp"]:
            day = _date(g["st_y"], g["st_m"], g["st_d"])
            return (day + delta).strftime("%Y%m%d") if _in_story(day) else whole
        if g["yymmdd"]:
            day = _date("20" + g["ym_y"], g["ym_m"], g["ym_d"])
            return (day + delta).strftime("%y%m%d") if _in_story(day) else whole
        if g["dm"]:
            name = g["dm_m"]
            month = ABBREVIATIONS.get(name) or MONTHS.index(name) + 1
            day = _date(g["dm_y"] or 2026, month, g["dm_d"])
            if not _in_story(day):
                return whole
            if g["dm_y"]:
                state["ref"] = day
            new = day + delta
            if name in ABBREVIATIONS:
                written = "Sept" if name == "Sept" and new.month == 9 else MONTHS[new.month - 1][:3]
            else:
                written = MONTHS[new.month - 1]
            out = "%d %s" % (new.day, written)
            return out + (" %d" % new.year if g["dm_y"] else "")
        if g["of"]:
            day = _date(2026, MONTHS.index(g["of_m"]) + 1, _ordinal_day(g["of_o"]))
            if not _in_story(day):
                return whole
            new = day + delta
            return "%s of %s" % (_ordinal_like(g["of_o"], new.day), MONTHS[new.month - 1])
        if g["month"]:
            day = _date(g["mo_y"] or 2026, MONTHS.index(g["mo_m"]) + 1, 15)   # a month stands for its middle
            if not _in_story(day):
                return whole
            new = day + delta
            return MONTHS[new.month - 1] + (" %d" % new.year if g["mo_y"] else "")
        # A day of the month alone.
        if g["wd"]:
            word, weekday = g["wd_o"], WEEKDAYS.index(g["wd_w"])
            day = _resolve(_ordinal_day(word), state["ref"], weekday=weekday)
            render = lambda new: g["wd_w"] + g["wd_sep"] + _ordinal_like(word, new.day)
        else:
            word = g["num_n"] + "th" if g["num"] else g["by_o"] or g["the_o"]
            past = bool(PAST_RE.search(text[text.rfind("\n", 0, m.start()) + 1:m.start()]))
            day = _resolve(_ordinal_day(word), state["ref"], past=past)
            prefix = "the " if g["num"] else g["by_p"] or "The "
            render = lambda new: prefix + _ordinal_like(word, new.day)
        if not _in_story(day):
            return whole
        return render(day + delta)

    return DATE_RE.sub(one, text)


def path_day(rel):
    """The date a content path carries, the day its text is read against."""
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", rel) or re.search(r"\b(2\d)([01]\d)([0-3]\d)\b", rel)
    if not m:
        return LAST_DAY
    y = m.group(1) if len(m.group(1)) == 4 else "20" + m.group(1)
    return _date(y, m.group(2), m.group(3)) or LAST_DAY


class Dated:
    """content/ and the plan, moved by `days` days: the files under the paths
    they get, their text, and every date and name the plan writes."""

    def __init__(self, days):
        self.days = days
        self.sources = {}
        for src in sorted(p for p in CONTENT.rglob("*") if p.is_file() and p.name != ".DS_Store"):
            rel = src.relative_to(CONTENT).as_posix()
            self.sources[self.text(rel)] = src

    def text(self, s, ref=LAST_DAY):
        return shift_text(s, self.days, ref)

    def source(self, rel):
        return self.sources.get(rel)

    def read(self, rel):
        """The bytes of content/'s file that lands at `rel`, its dates moved.
        Read and written as bytes, so a mail's CRLF line ends stay as they are."""
        src = self.sources[rel]
        data = src.read_bytes()
        if not self.days:
            return data
        orig = src.relative_to(CONTENT).as_posix()
        return self.text(data.decode("utf-8"), path_day(orig)).encode("utf-8")

    def plan(self):
        out = []
        for when, repo, message, actions in PLAN:
            moved = [self.text(a) if isinstance(a, str) else a for a in actions]
            out.append((self.text(when), repo, self.text(message), moved))
        return out


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
        # scaffold.py would start a page build after each project and thread,
        # which outlives this script and writes into the workspace it built (#243).
        "GARRICK_CALLER_BUILDS_PAGE": "1",
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


def plan_paths(plan):
    """How many times the plan names each file, by its path in the workspace."""
    count = {}
    for _, repo, _, actions in plan:
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
        # A line done later is still open here: unticked, and without its ✅ date.
        inbox += [re.sub(r" ✅ \d{4}-\d{2}-\d{2}$", "", "- [ ]" + l[5:]) for l in self.done_items if l in self.shown and l not in self.ticked]
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
    """Run the workspace's own scaffold script on the plan's day, never the clock's."""
    run([sys.executable, str(root / "System" / "tools" / "scaffold.py"), "--today", when.split(" ")[0]] + args,
        root, when, "scaffold")


def pin_version(root, dated):
    """Record DEMO_VERSION in place of the source's commit, date and edits, in
    the installer's own first commit, which is the root's only one so far."""
    path = root / VERSION_STAMP
    stamp = json.loads(path.read_text(encoding="utf-8"))
    for key in ("commit", "date", "from", "modified"):
        stamp.pop(key, None)
    version = dict(DEMO_VERSION, date=dated.text(DEMO_VERSION["date"]))
    path.write_text(json.dumps(dict(version, **stamp), indent=2) + "\n", encoding="utf-8")
    installed = dated.text(INSTALLED)
    run(["git", "add", "--", VERSION_STAMP], root, installed, "staging the version stamp")
    run(["git", "-c", "commit.gpgsign=false", "commit", "-q", "--amend", "--no-edit"], root, installed,
        "recording the demo's version")


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


def build(target, today=None):
    """Build the demo at `target`, its month moved to end on `today` (the
    clock's day when not given) or in the six days before it."""
    # Absolute before anything runs: install.py runs from the source folder, so a
    # relative target would otherwise land, or be refused, there instead of here.
    target = Path(os.path.abspath(Path(target).expanduser()))
    check_target(target)
    if not CONTENT.is_dir():
        raise BuildError(f"{CONTENT} is missing.")
    dated = Dated(7 * weeks_for(today or datetime.date.today()))
    installed, inbox = dated.text(INSTALLED), dated.text(INBOX)
    run([sys.executable, str(INSTALL), "--config", str(CONFIG), "--target", str(target)], REPO, installed, "install.py")
    root = target.resolve()
    pin_version(root, dated)

    todos = {z: TodoList(dated.read(f"Zones/{z}/Todo.md").decode("utf-8")) for z in ("Work", "Personal")}
    plan = dated.plan()
    named = plan_paths(plan)
    copied = set()
    for when, repo, message, actions in plan:
        repo_dir = root / repo if repo else root
        date = when.split(" ")[0]
        touched = set()
        for action in actions:
            if isinstance(action, str):
                rel = (Path(repo) / action).as_posix() if repo else action
                if dated.source(rel) is None:
                    raise BuildError(f"the plan names {rel}, which is not in content/")
                dst = root / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                if named[rel] > 1:  # finished at its last naming; until then, as far as the month has got
                    before = dst.read_text(encoding="utf-8") if dst.is_file() else None
                    dst.write_text(as_far_as(dated.read(rel).decode("utf-8"), rel, present(root), before, date),
                                   encoding="utf-8")
                else:
                    dst.write_bytes(dated.read(rel))
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
            for rel in sorted(r for r in dated.sources if r.endswith(".md")):
                if rel.startswith(wiki) and is_ledger(rel) and (rel in LEDGER_FILES or (root / rel).exists()):
                    path = root / rel
                    before = path.read_text(encoding="utf-8") if path.is_file() else None
                    path.write_text(as_far_as(dated.read(rel).decode("utf-8"), rel, files, before, date),
                                    encoding="utf-8")
                    copied.add(rel)
            if wiki == "Wikis/Knowledge/":
                (root / KNOWLEDGE_INDEX).write_text(knowledge_index(root), encoding="utf-8")
                copied.add(KNOWLEDGE_INDEX)

        run(["git", "add", "-A"], repo_dir, when, f"staging for {message!r}")
        run(["git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", message], repo_dir, when, f"commit {message!r}")

    # The one transcript still waiting in the inbox: dropped by the recorder, not committed.
    for rel in (inbox,) + tuple(dated.text(m) for m in MAIL):
        (root / rel).write_bytes(dated.read(rel))
        copied.add(rel)

    # Every file in content/ must now be in place, exactly, and every repository clean.
    for rel in sorted(dated.sources):
        dst = root / rel
        if not dst.is_file() or dst.read_bytes() != dated.read(rel):
            raise BuildError(f"{rel} did not end up as it is in content/; check the plan in build.py")
    for repo in ("", "Wikis", "Zones/Work", "Zones/Personal"):
        status = run(["git", "status", "--porcelain", "--untracked-files=all"], root / repo if repo else root,
                     installed, "git status")
        stray = [l for l in status.splitlines() if Path(inbox).name not in l]
        if stray:
            raise BuildError(f"{repo or 'the root'} has changes the plan did not commit: {stray}")
    return root


def said_day(day):
    return "%s %d %s %d" % (WEEKDAYS[day.weekday()], day.day, MONTHS[day.month - 1], day.year)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build the Garrick demo workspace: a month of Sam Rivera's work, "
                                             "ending on the day it is built or in the six days before.")
    ap.add_argument("--target", required=True, help="an empty or new folder")
    ap.add_argument("--today", help="YYYY-MM-DD to build as if on, instead of today")
    args = ap.parse_args(argv)
    try:
        today = datetime.date.fromisoformat(args.today) if args.today else datetime.date.today()
        root = build(args.target, today)
    except (BuildError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1
    moved = 7 * weeks_for(today) * DAY
    first = datetime.date.fromisoformat(INSTALLED.split(" ")[0]) + moved
    print(f"Demo workspace built at {root}")
    print(f"  Installed {said_day(first)}; {len(PLAN)} commits after it, the last on "
          f"{said_day(datetime.date.fromisoformat(PLAN[-1][0].split(' ')[0]) + moved)}.")
    print(f"  One transcript waiting in the inbox, from {said_day(LAST_DAY + moved)}: "
          f"{Path(shift_text(INBOX, moved.days)).name}")
    print(f"  {len(MAIL)} mails waiting in the Work zone's Inbox.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
