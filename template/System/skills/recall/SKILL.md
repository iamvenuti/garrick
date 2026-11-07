---
name: recall
description: >
  Search the notes, the wikis and past sessions by keyword, ranked, with the
  walls built into what it searches. Use when the user says "what did we decide about X",
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

Run it from the folder the session was opened in. The tool takes the scope of
that folder, and finds the workspace above it. From a project folder the
tool is three levels up (`../../../System/tools/recall.py`); from a thread
folder, five; from a zone folder, two. The installer allows `search`, `read`
and `stats` at those depths, so they run without a question. Never change
folder first (no `cd` to the root, then the tool). The scope comes only from
the folder the process really runs in, with symlinks followed; never from an
argument that names a folder. A bare working folder at the root or in `System/`
is refused: the root scope, which may read every zone, is for a session the
harness opened at the root (`CLAUDE_PROJECT_DIR` names the root). This is a
wall for what Recall returns, not for your own reads: a session that can run a
shell can open files directly, and the user has to trust it not to. Where the environment names
the folder the session was opened in (Claude Code sets `CLAUDE_PROJECT_DIR`;
Codex sets nothing the tool reads), the scope is the narrower of that folder
and the current one, and a current folder outside the session's folder
searches nothing. A folder outside the workspace given by `--root` searches
nothing.

```sh
python3 ../../../System/tools/recall.py search "invoice export retry"
python3 ../../../System/tools/recall.py search "pricing" --after 2026-06-01 --limit 5
python3 ../../../System/tools/recall.py search "retry flag" --sessions
python3 ../../../System/tools/recall.py read "Meetings:Wikis/Meetings/wiki/sources/260310-kickoff.md"
```

- `--sessions` adds the sessions extracted for this zone. A session opened at
  the workspace root or in `System/` can read every zone's.
- `--wiki Meetings` or `--wiki Knowledge` searches that wiki alone (with `--sessions`, the sessions too, and no notes).
- `--zone Z` narrows to one zone's notes. A session of a zone can name its own
  zone and no other; a search never reaches past the session's scope. For work
  across zones, the user opens a session at the workspace root.
- `--archived` adds archived pages after the rest. Use it only when the user
  asks to look in the archive. Pages that are dormant join by themselves, when
  the working ones fall short, and the answer says "from older notes".
- `read ID` prints a file by the `id` of a result, only if it is in your scope.
  An id that is not there prints nothing, whether it is unknown or behind a wall.
- `--scope S` may name the session's own scope and no other (a session at the
  root may name any). There is no `--project`: the scope is never a folder you choose.
- `stats` shows your scope's index and how many files it holds.
- A word that is a party, a person or a heard alias in `System/context.md` is
  searched in every spelling, with and without spaces; a near misspelling of a
  word the notes have is found too.

## Where the session was opened

Only the workspace root and `System/` read as a root session. A session opened
in a project or a thread of a project reads the scope of that project's hub. A
zone's top level, a project whose hub names no party, and a place no zone owns
(inside `Wikis/`, `Zones/` itself, outside the workspace) hold no scope the
walls can be checked against, so the tool searches nothing and says so. Open
the session in a project with a party, or at the root.

A `party:` or `parties:` that holds anything but tags from the Parties table
(`birch, acme`, `acme and birch`) cannot be placed: a Meetings page like that
is in no scope, and a project whose hub is like that holds no scope. A
Knowledge page that names a zone or a party is not published and is in no
zone scope.

## A result is a pointer

Open the file before you state a fact from it. A snippet is the part of the
text that matched, not the answer; the date shows how old it is. If two
results disagree, say so and read both. If a page says it is superseded,
read what superseded it.

## The walls

The tool searches an index that holds only the rows your scope may read: a
walled row is not in the file. The count in the header is what you may read,
nothing more.
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
