---
name: nurture
description: >
  Context Nurture: gather every finding the workspace's checks hold for a
  scope, sort them by what a fix needs, apply the mechanical ones on one yes,
  ask about attribution one line at a time, name each wall without repeating
  it, and report the rest. Use when the user says "nurture the context",
  "nurture Work", "nurture Acme", "nurture the meetings", "nurture the
  library", or "what needs nurturing", and when, during one, the user corrects a
  value written down. The jobs extra can apply the mechanical kind nightly.
---

# Context Nurture

The context is what makes the assistant useful here: who is who, which party
a meeting belongs to, where each thread stands, what links to what. Every
part of it has a check, and every check only reports, so repair is left to
the user one finding at a time, and the warnings nobody reads are the ones
that matter later. This skill works through them with the user, sorted by
what a fix needs rather than by which tool found it. It adds no checks of its
own: a new kind of problem gets a check in `check.py` first.

## Where things are

| What | Where |
|---|---|
| The tool behind this skill | `System/tools/nurture.py` |
| What it reads | `check.py --json`, `wiki_lint.py --json` for each wiki, `drift.py --json` |
| A correction | `System/tools/correct.py`, the `threads` skill's own, which `nurture.py correct` calls |
| Each day's report | `System/generated/nurture/<YYYY-MM-DD>.md`, never committed |
| Parties, Walls, People, Aliases | `System/context.md` |

## The kinds

| Kind | Examples | What this skill does |
|---|---|---|
| Mechanical | a link broken by a rename with exactly one candidate; a deliverable without its date prefix; a thread missing from its hub's `## Threads`; a status synonym (`paused` for `parked`) | Lists them, and applies them all on one yes, one commit per repository |
| Correction | a value written down wrong, an address, an account, a name, which the user corrects | Lists every live copy as one finding, and corrects them all on one yes, one commit per repository |
| Attribution and category | a meeting page with no zone or parties; a person under no party; a page in the wrong wiki or of the wrong `type`; a thread marked done with no outcome; an open action naming a thread that is not there | Proposes an answer and asks in one line. Never guesses across a wall |
| Wall | a project file that names, links or quotes a party across a wall | Says which file and which wall, never the material, and offers to take it out |
| Judgment | a stale resume point, a published file drifted from its shared copy, an orphan page, two pages that disagree | Leaves the text alone and names the page to open |

A fix the tool could make but holds back, because the file has changes not
committed, a date sits inside a name, or no repository could undo it, stays
in the report with its reason, as judgment.

## Nurture: "nurture X"

1. **The scope.** "The context" is the whole workspace. Otherwise resolve
   the name as the `threads` skill's *Resolving a name* does, against zones,
   projects, threads, the two wikis ("the meetings", "the library") and the
   Parties table. A party is every project whose `party` is its tag. Two
   candidates mean one question; never pick one.
2. **Gather**, changing nothing:
   ```sh
   python3 System/tools/nurture.py --scope "Zones/<Zone>/<Project>"
   ```
   One `--scope` per path, none for the workspace. For a wiki's scope, run
   that wiki's *Lint* as its skill says, reading pass included (`meetings`
   for the Meetings wiki, `knowledge` for Knowledge): what its reading
   finds is judgment, and its report stays where the *Lint* writes it. For
   the workspace, offer the reading pass rather than running it unasked.
3. **Mechanical.** Say how many, of what kinds, and ask once: "Apply all
   five?" On a yes:
   ```sh
   python3 System/tools/nurture.py fix --scope "<path>" --yes
   ```
   It applies them all, one commit per repository, naming only the files it
   changed, through each repository's wall check. Relay the commits, and any
   fix it held with the reason. A no leaves them for the report.
4. **Walls.** For each, say the file and the wall ("the Pricing notes, the
   wall between Acme and Birch") and nothing of what matched: not quoted,
   not paraphrased, not summarised. Offer to take it out. On a yes, edit that
   file alone, remove the material, and commit it in its repository through
   the hook. Never move it anywhere else, and never decide alone.
5. **Attribution**, one at a time. Each finding carries its question, and a
   proposal when the context file settles one. An answer that says a value
   written down is wrong is a correction: see *A correction* below. Add your
   own from the page's
   addresses, the People table and the page's text, as the `intake` skill
   reads them; when the evidence points to both sides of a wall, propose
   nothing and ask. Ask in one line: "260310 Kick-off: Work, Acme?" On an
   answer, make the edit, commit it in its repository, and record it:
   ```sh
   python3 System/tools/nurture.py answered --path "<file>" --asked "<question>" --answer "<answer>"
   ```
   "Skip" leaves it in the report. Never guess.
6. **Judgment.** Name each with the page to open, and change nothing,
   unless the user answers one with the right value: that is a correction.
7. **The report.** The tool wrote `System/generated/nurture/<date>.md`:
   what was fixed, what was asked and answered, and what is left. Say where
   it is.

Spoken: "In Work: four fixes ready, two questions and one wall. Apply the
four?" Then, after them: "Done, in two commits. The wall is in the Pricing
notes, between Acme and Birch: take it out?"

Written: the spoken answer on top, then the tool's list by kind, and the
commit hashes.

## A correction: "that's wrong, it's Y"

No check finds a wrong value; the user says the right one. It comes in two
ways: as the answer to an attribution or judgment finding ("that's wrong,
the domain is acmecorp.example"), or said outright during a pass ("Acme's
domain is acmecorp.example, not acme-corp.example"). It is one finding, and
it goes through the same tool the `threads` skill uses for *Correct*, so a
value is found and replaced one way only.

1. **Settle the two values**, as the `threads` skill's *Correct* does: the wrong one as it is
   written, the right one as the user gave it. When it is not clear which
   written value they mean, ask.
2. **List every live copy**, which changes nothing:
   ```sh
   python3 System/tools/nurture.py correct --old "<X>" --new "<Y>" --scope "<path>" --path "<the finding's file>"
   ```
   The scope is the pass's, none for the workspace. It lists what
   `correct.py` finds, by file and line, as one finding. With a scope, a
   copy in a file across a wall from it, or in one whose parties cannot be
   told, is left out and left alone, and the tool prints the sentence
   *Zones and walls* in `System/rules.md` gives. Say that sentence, word for
   word, and nothing else about it: no file, no party, no count, not that a
   copy exists. A copy in a file another session has changes in is held. A
   raw record is listed and never edited.
3. **Ask once**: "Five places have the old domain. Fix them all?" A hit
   that is right where it is, such as a heard form in Aliases, is named and
   kept out with `--leave <path>`.
4. **On the yes**, the same line with `--yes`, and `--why "<why>"` when the
   user gave a reason. `correct.py` writes each copy, marks the pages
   resting on a raw record as superseded, and commits once per repository,
   only the files it changed. The day's report records the copies fixed,
   each commit, and the yes. Relay the commits, and anything held or
   refused, as *Correct* does.

A correction never runs overnight: it needs a person to say the right value,
and `correct --yes` is refused with nobody watching.

## Overnight

The jobs extra's nightly run, `nurture_sweep.py`, applies the mechanical
kind with nobody watching, and nothing else: attribution, wall and judgment
findings, and corrections, never change headless. It commits only the files
it changed, by name, never `-a` or `git add .`, and leaves alone any file
another session has changes in, since another session may have uncommitted
work in the same repository. Its line in the morning digest says what was fixed first, then
what waits. When the user asks what changed overnight, read the day's report.

## Listening mode

As the `threads` skill's: the answer first, three sentences at most, no
paths, round numbers. A wall is said as its two parties and the file's short
name.

## What this skill does not do

- **It adds no checks.** It sorts what `check.py`, `wiki_lint.py` and
  `drift.py` find. A new kind of problem gets a check first.
- **It never replaces the wikis' *Lint*.** "Lint the meetings" and "lint the
  library" work as they always have, and change nothing.
- **It never repeats walled material**, in the conversation, the report or
  a commit message.
- **It never guesses** a zone, a party or a wiki, and never applies an
  attribution the user did not give.
- **It never commits two repositories together**, never stages what it did
  not change, and never pushes.
- **It keeps no score.** It counts findings by kind, and weighs none.
