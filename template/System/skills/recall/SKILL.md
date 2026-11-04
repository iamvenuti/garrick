---
name: recall
description: >
  Search the notes, the wikis and past sessions by keyword, ranked, with the
  walls already applied. Use when the user says "what did we decide about X",
  "when did we fix Y", "find where we talked about Z", "search my notes for
  X", "search past sessions for X", or asks about earlier work that the
  routing in AGENTS.md does not already send to a wiki or a thread note.
---

# Recall

Plain text search returns every matching line in no order, and a common word
in your work matches thousands of them. `System/tools/recall.py` searches an
index instead and gives back the ten best files, each with its date, its
source, a short snippet and its path. It also finds what was said in earlier
sessions, which the harness deletes after a while.

## The routing in AGENTS.md comes first

Recall does not replace it. "Where did we land with X" goes to
`Wikis/Meetings/`, "what do I owe them" to the zone's `Todo.md`, "where am I
on X" to the thread's *Resume here* block, "what is X" to `Wikis/Knowledge/`.
Use Recall for what those routes do not answer: *when did we fix that error*,
*why did option B lose*, *where did I say that*.

## Search

Run it from the folder the session was opened in. The tool takes that folder
as the project, and finds the workspace above it. From a project folder the
tool is three levels up (`../../../System/tools/recall.py`); from a zone
folder, two. Never change folder first: from the workspace root or `System/`
the tool reads as a root session, which may read every zone.

```sh
python3 ../../../System/tools/recall.py search "invoice export retry"
python3 ../../../System/tools/recall.py search "pricing" --after 2026-06-01 --limit 5
python3 ../../../System/tools/recall.py search "retry flag" --sessions
```

- `--sessions` adds the sessions extracted for this zone. A session opened at
  the workspace root or in `System/` can read every zone's.
- `--wiki Meetings` or `--wiki Knowledge` searches that wiki alone (with `--sessions`, the sessions too, and no notes).
- `--zone Z` adds another zone. Do it only when the user asks for work across
  zones, and only for that request.
- `--archived` adds archived pages after the rest. Use it only when the user
  asks to look in the archive. Pages that are dormant join by themselves, when
  the working ones fall short, and the answer says "from older notes".
- `--project DIR` names the project when the session was not opened in it.
- `stats` lists the indexes and how many files you may read in each.

## Where the session was opened

Only the workspace root and `System/` read as a root session. A session opened
in a zone folder or below it reads that zone as a zone-level or project session.
A session opened anywhere else (inside `Wikis/`, in `Zones/` itself, outside
the workspace) has no place the walls can be checked against, so the tool
searches nothing and says so. Open the session in a project, or pass
`--project DIR`.

A `party:` or `parties:` that holds anything but tags from the Parties table
(`birch, acme`, `acme and birch`) cannot be placed: a Meetings page like that is
left out, and a project whose hub is like that is treated as having no party. A
Knowledge page that names a zone or a party follows the Meetings rule.

## A result is a pointer

Open the file before you state a fact from it. A snippet is the part of the
text that matched, not the answer; the date shows how old it is. If two
results disagree, say so and read both. If a page says it is superseded,
read what superseded it.

## The walls

The tool drops every row that is walled from the project's party, a Meetings
page without its zone or its parties, and another zone's rows, **before** it
ranks anything. The count in the header is what you may read, nothing more.
Do not work around it: never grep a wiki or `.sessions/` folder to find what a
search did not return. If the user asks why something is missing, say
that a result list holds only what this project may read, and name nothing
else.

## When the index looks wrong

An index is a cache. `recall.py build --rebuild` makes
every index again from the files; nothing is lost. The nightly job extracts
new sessions and builds the indexes (`recall.py nightly`). Without FTS5 in the
Python's SQLite the tool says so and searches plain text, which ranks less
well.

## What this skill does not do

- It does not search mail or connectors. Intake files them; Recall finds what
  was filed.
- It does not summarise. It finds, and you read.
- It does not write: the indexes and the `.sessions/` folders are not
  committed and are not notes.
