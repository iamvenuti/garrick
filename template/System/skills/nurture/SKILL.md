---
name: nurture
description: >
  Context Nurture: gather every finding the workspace's checks hold for a
  scope, sort them by what a fix needs, apply the mechanical ones on one yes,
  ask about attribution one line at a time, name each wall without repeating
  it, and report the rest. Use when the user says "nurture the context",
  "nurture Work", "nurture Acme", "nurture the meetings", "nurture the
  library", or "what needs nurturing", and when, during one, the user corrects a
  value written down. Also a guided review in a short session, which goes on
  where the last one stopped: "review the context with me", "review the
  latest audit with me". Also graded oblivion, old pages fading out of working
  memory: "fade the meetings", "fade the library", "what would fade", and
  "keep X" for a wiki page. The jobs extra can apply the mechanical kind
  nightly; nothing ever fades overnight.
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
| The review record | `System/nurture-review.md`, committed in the workspace root's repository |
| The shared-file comparison last saved | `System/generated/drift.json`, from `drift.py --save` |
| What would fade, and why | `System/tools/fade.py`; its proposal in `System/generated/fade/<Wiki>.md` |
| The judgment the numbers can't hold | `System/retention.md`, and `System/retention.local.md`, which wins |
| How fast each kind fades | `"memory"` in `System/garrick-settings.json`: `python3 System/tools/fade.py settings` prints it |
| Parties, Walls, People, Aliases | `System/context.md` |

## The kinds

| Kind | Examples | What this skill does |
|---|---|---|
| Mechanical | a link broken by a rename with exactly one candidate; a deliverable without its date prefix; a thread missing from its hub's `## Threads`; a status synonym (`paused` for `parked`); a note path written as code that leads to exactly one live note, made a wikilink; a note in a thread's folder with no `parent:`, given its thread's; a person page in Meetings with no link to the entity page of its party, given `organisation:` | Lists them, and applies them all on one yes, one commit per repository. The organisation link never goes in overnight: it writes into a page written by hand |
| Correction | a value written down wrong, an address, an account, a name, which the user corrects | Lists every live copy as one finding, and corrects them all on one yes, one commit per repository |
| Attribution and category | a meeting page with no zone or parties; a person under no party; a page in the wrong wiki or of the wrong `type`; a thread marked done with no outcome; an open action naming a thread that is not there | Proposes an answer and asks in one line. Never guesses across a wall |
| Wall | a project file that names, links or quotes a party across a wall | Says which file and which wall, never the material, and offers to take it out |
| Judgment | a stale resume point, a published file drifted from its shared copy, an orphan page, two pages that disagree | Leaves the text alone and names the page to open |
| Behind the share | a published file whose ledger row ends in `share`, and whose copy here differs from the shared one: colleagues edit it there, so the copy here is a snapshot | Names it last, as low urgency, and changes nothing |
| Fading | meeting pages or reading old enough to leave working memory, or a faded page linked again | Says how many, per wiki, and what to say: "fade the meetings". Nothing moves without a written proposal and a yes on it; see *Fading* below |

A fix the tool could make but holds back, because the file has changes not
committed, a date sits inside a name, or no repository could undo it, stays
in the report with its reason, as judgment. So does a path written as code
that leads to no note or to several, and a note with no `parent:` at the
project's own level, under a `Deliverables/` or `Sources/` folder, or in a
thread whose name another note shares.

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
   **Behind the share** comes after it, apart: the shared copy is the one
   that counts, so say how many and which files, and fix nothing. Never
   call one drift.
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

## Review: "review the context with me", "review the latest audit with me"

A short, regular session through what the checks left for a person. It uses
the kinds and the steps above, sets their order, stops at a limit the user
chooses, and keeps a record, so the next session goes on where this one
stopped. A weekly review is a use of this procedure: nothing schedules it,
and it needs no job of its own.

### The review record

One file for the workspace, `System/nurture-review.md`. It must survive
between sessions, so it is outside `System/generated/`, which the tools
rebuild and nobody commits. It is committed in the workspace root's
repository, on its own. The request to review is the yes to write it.

```markdown
---
type: nurture-review
status: open
started: 2026-03-14
last_completed: 2026-03-07
limit: 15 minutes
fixed: 0
answered: 1
deferred: 1
---
# Context review

| Id | Source | Decision | Reason | Date |
|---|---|---|---|---|
| 3f2a9c1d0b4e | check.py | answered | | 2026-03-14 |
| 9b07e4a2c6d1 | wiki_lint.py | skipped | not now | 2026-03-14 |
| c4d8e0f1a2b3 | check.py | deferred to 2026-03-21 | another session holds the file | 2026-03-14 |
| drift.py | drift.py | source failed | source did not run | 2026-03-14 |
```

- **`status:`** is `open` while a review has items with no decision, and
  `done` once every item has one. **`started:`** is the day the review
  started, **`last_completed:`** the day the last one was done, and empty
  until then. **`limit:`** is the one the user chose. **`fixed:`**,
  **`answered:`** and **`deferred:`** count the items this review has
  given each decision so far, whole numbers and nothing else: the status
  page shows them.
- **An item** is one finding. Its **Id** is the finding's `key`, as
  `nurture.py --json` gives it: twelve hex digits that say nothing of the
  file, the check or the material. Two findings on one file have two keys,
  and the same finding has the same key in the next session. A source that
  did not run is an item of its own, and its Id is the tool's name, such as
  `drift.py`. An item that only an audit report holds has no key and gets no
  row: the next audit names it again while it stands.
- **Source** names the tools that found it: `check.py`, `wiki_lint.py`,
  `drift.py`, `fade.py`, and `audit` for the audit report, with a comma
  between two.
- **Decision** is one of: `fixed` and the commit, `answered`, `deferred to`
  a date, `skipped`, or `source failed`. It never holds the answer. An
  answer goes into the files it changes, never into the record.
- **Reason** is empty, or one of these, the nearest to what the user said:
  "another session holds the file", "waiting on someone", "needs the user's
  own records", "source did not run", "not now". Never the user's own words.
  **Date** is the day of the decision.
- **Each session finds an item again by its key.** The record names no
  file, so run *Gather* and match each item's `key` to an Id. An Id that
  Gather no longer gives is a finding that is gone.
- **What is settled stays settled.** An item `fixed` or `answered` is never
  asked again while Gather gives its key. A `deferred` item waits until its
  date. A `skipped` item comes back in the next review.
- **A wall item is never settled.** It is asked in every review while its
  finding stands. Its only decisions are `fixed` and the commit, or
  `deferred to` a date; never `answered`, never `skipped`.
- **It holds decisions, never material.** No path, no quote, no answer, no
  question as it was asked. A wall item names no wall. The record sits in
  the root repository, which no wall hook checks, and `check.py` warns about
  a row outside this form, by its number. The status page reads only the
  frontmatter: the date of the last review completed, and whether one is
  unfinished.
- **It stays short.** When a review is done, take out each row whose key
  Gather no longer gives. Git holds the rows taken out.

### The review

1. **Open the record.** When its status is `open`, say so and go on from it:
   "The review from Saturday is unfinished. Go on with it?" Otherwise start
   a new one: `status: open`, `started:` today, and `fixed:`, `answered:`
   and `deferred:` at 0.
2. **Prepare from the current record**, changing nothing:
   - Run Nurture's *Gather* for the whole workspace, or for the scope the
     user named. It runs `check.py`, `wiki_lint.py` for each wiki and
     `drift.py` now. Offer each wiki's reading pass; do not run it unasked.
   - When `drift.py` cannot read a share, it is a source that failed. Read
     the comparison it last saved, `System/generated/drift.json`, and say its
     date: what it holds is an older observation, not a current finding.
   - **The latest audit report**, when the workspace keeps one: a report
     about the workspace that a job of its own or a person wrote, where
     `System/rules.local.md` or an `AGENTS.local.md` says it is kept. Read
     the newest one, and say its date and where it came from. "Review the
     latest audit with me" starts from it; with none found, say so and ask
     where it is, in one line.
   - **Recheck before you propose.** Each finding from a report, the audit
     or an earlier Nurture report, is a lead: read the file now. Only a
     finding that still stands is proposed. One that no longer stands is
     named as gone, once, and never proposed.
   - **One finding, one item.** The same file and the same problem from two
     sources is one item, with both sources named. It has a row for each
     key, all with the same decision.
   - **Three groups, never mixed:** current findings, older observations
     that no recheck confirmed, and sources that failed. For a source that
     failed, say what it covers: the review cannot vouch for that part.
   - Match each finding's `key` to the record's Ids. Leave out every item
     the record has settled, and each deferred item whose date has not
     come. A wall item is settled only by its fix.
3. **The limit.** Once the items are gathered, ask once: "Fifteen minutes
   or ten questions?" No answer is the default, fifteen minutes or ten
   questions, whichever comes first. Write it in `limit:`. The mechanical
   batch counts as one question. At the limit, finish the item in hand and
   go to step 6.
4. **The order.**
   1. **Walls**, as *Nurture* step 4, and **what failed**: a source that did
      not run, and a scheduled job whose last run failed, as the status
      page's *Scheduled jobs* card shows it. Those first, since they decide
      how far the rest can be trusted.
   2. **One batch of mechanical fixes**, as *Nurture* step 3: say how many,
      of what kinds, and ask once.
   3. **Attribution, corrections and judgment**, one decision at a time. Give
      the evidence (the file, the line, what the check says, which source),
      a proposed answer when the record supports one, and the files that
      answer would change. Do not ask what you can settle from the record:
      look it up, as *Nurture* step 5 does, and propose it.
   4. **Behind the share** last, as *Nurture* step 6: named, and never
      fixed.

   The user can say "skip" or "later", and why: write the nearest reason
   from the record's list. "Later" asks for a date, with next week as the
   default. A wall is fixed or deferred, never skipped. Write each decision
   in the record as it is made, not at the end, as its key and the fixed
   words above.
5. **Apply through the owning procedures.** Each answer goes through the
   step above that owns its kind: a correction through *A correction*, a
   wiki page through its wiki's skill, each commit through its repository's
   wall check.
   - **An audit report alone never allows an edit.** Only a finding rechecked
     now, and the user's yes on it.
   - **A raw record is never edited.**
   - **A file another session has changes in is held**, as `nurture.py`
     holds it. Defer the item, with the reason "another session holds the
     file".
   - **Nothing crosses a wall.** Never move, merge or quote material from
     one side of a wall into a file on the other. When an answer would need
     it, change nothing, and say the sentence *Zones and walls* in
     `System/rules.md` gives, word for word: "A wall holds some material back
     from this project, so I have not used it. Nothing was written." Nothing
     else about it.
   - **A shared-file difference never causes an overwrite**, in either
     direction. Name it, and change nothing.
   - **A finding never becomes a Needs you question.** Technical findings
     stay on the Checks card. The questions a wiki keeps in its
     `questions/` folder are not part of this review yet; a check's finding
     about one is.
6. **Show what remains.** Run *Gather* again, so the count is the one after
   the changes. Update the record: each decision made, each source that
   failed, and the three counts. When every item has a decision, set
   `status: done` and `last_completed:` today, and take out the rows whose
   key Gather no longer gives.
   Commit the record alone:
   ```sh
   git add -- System/nurture-review.md
   git commit -m "Nurture: context review, <done or unfinished>"
   ```
   Then say what was fixed, with the commits; what was answered; what was
   deferred, and why; and what is left, by kind, with its source. Never say
   the context is right because the count fell: a check finds only what it
   looks for.

Spoken: "Two things first: one wall, and the shared files did not read.
Then six fixes ready and four questions. Fifteen minutes or ten questions?"
At the end: "Stopped at the limit. Six fixed, three answered, two deferred.
Five left for next time."

## Fading: "fade the meetings", "fade the library", "what would fade"

Graded oblivion. Both wikis only grow, and every routing, briefing and
search starts by reading their index, so last week's call ends up read
through a year of calls nobody will ask about again. Pages fade instead, by
age, kind and use, and stay findable. Nothing is deleted.

| Grade | Where | Who reads it |
|---|---|---|
| Working | `wiki/...`, listed in `wiki/index.md` | every routing, briefing and search |
| Dormant | `dormant/wiki/...`, listed in `wiki/index-dormant.md` with its date and why | a search that reaches back, and says so |
| Archived | `archive/wiki/...`, in no index | only "search the archive", or a question about a past year |

Age counts from the page's own `date:` or `published:`, never from the file.
A page linked from a live thread, a live project's notes or an open action
in a `Todo.md`, or carrying `pinned: true`, never fades. A page carrying
`superseded:` fades whatever links it, and never wakes. Person, entity and
concept pages never move: each keeps a short `## Earlier` section listing
what faded.

1. **The wiki.** "Fade the meetings" is Meetings, "fade the library" is
   Knowledge, "what would fade" is both. Nothing else fades.
2. **Read the judgment first**: `System/retention.md`, then
   `System/retention.local.md`, which wins.
3. **Propose**, which moves nothing:
   ```sh
   python3 System/tools/fade.py propose --wiki Meetings
   ```
   It writes `System/generated/fade/Meetings.md`: what would go dormant, be
   archived or wake, grouped by grade and kind, each with why, and its
   derived copies: the pages that go with it, the notes and ticked actions
   whose links are pointed at its new path, what stays as written, and the
   person and entity pages that list it under Earlier. A page superseded
   and still linked from a live note is named apart, since a link somewhere
   still points at the old version.
4. **Weigh it against the judgment.** Read the titles, and any page the
   retention files speak to. A page they say to keep, propose again with
   `--leave "<page>"`, once for each, and say why. Never leave out a page the
   numbers move without a reason from those files or from the user.
5. **The first fade on a wiki only proposes.** When the tool says it is the
   first, stop there: say how many would move, that nothing has moved, and
   where the list is. The user reads it, and changes `retention.local.md` or
   the settings where it is wrong. The tool keeps the command that applies
   it only in the written proposal. A later "yes", or "apply the fade", runs
   that command as the proposal gives it.
6. **Any later fade** asks once: "Forty meeting pages would go dormant and
   nine to the archive. Fade them?" On a yes:
   ```sh
   python3 System/tools/fade.py apply --wiki Meetings --id <id>
   ```
   It moves only what that written proposal listed and still qualifies, one
   commit per repository, the wiki's first, and points every link at the new
   path. A page whose note another session is changing is held, with why.
   Relay the commits and anything held.
7. **Write the Earlier lines.** For each person or entity page the apply
   added lines to, write two lines at the top of its `## Earlier` section,
   above the list: what the relationship was over those pages, in a
   sentence or two, from those pages alone. On a person page, only what any
   reader may see: who they met and when, never a figure or a position,
   since a person page is read on both sides of every wall. Commit it in the
   Wikis repository.

Spoken: "Forty meeting pages would go dormant and nine to the archive.
Nothing has moved; the list is in the proposal." After a yes: "Done, in two
commits. Two pages were held: another session is changing a note that
links them."

### Keep: "keep X"

For a page the user wants in working memory for good:

```sh
python3 System/tools/fade.py keep --page "<page>"
```

It writes `pinned: true` and commits it. A page that has faded is then
proposed to wake, on its own: ask once, "It's in the archive. Bring it
back?", and apply on a yes. "Keep" is the word, never "wake", "back",
"open" or "restore": those are thread and desk commands.

### Waking

A dormant page linked again, from a live thread, a live project's notes, an
open action, or a working page that links it afresh, is proposed to wake
with the next fade, and moves back on the same yes. An archived page wakes
only on "keep". A page carrying `superseded:` never wakes, whatever links it.

## Overnight

The jobs extra's nightly job, `gr-nightly`, applies the mechanical
kind with nobody watching, and nothing else: attribution, wall and judgment
findings, and corrections, never change headless. Nor does a person page's
`organisation:` link, though it is mechanical: it waits for the yes, and the
digest counts it among the fixes held. It commits only the files
it changed, by name, never `-a` or `git add .`, and leaves alone any file
another session has changes in, since another session may have uncommitted
work in the same repository. Its line in the morning digest says what was fixed first, then
what waits. Pages that would fade add a line of their own, once a wiki's
count reaches the setting's minimum: "41 meeting pages would go dormant and
9 to the archive. Say "fade the meetings"." Nothing fades overnight. When
the user asks what changed overnight, read the day's report.

## Listening mode

As the `threads` skill's: the answer first, three sentences at most, no
paths, round numbers. A wall is said as its two parties and the file's short
name.

## What this skill does not do

- **It adds no checks.** It sorts what `check.py`, `wiki_lint.py` and
  `drift.py` find. A new kind of problem gets a check first.
- **It never replaces the wikis' *Lint*.** "Lint the meetings" and "lint the
  library" work as they always have, and change no page: what only the
  user can settle becomes a question file.
- **It never repeats walled material**, in the conversation, the report or
  a commit message.
- **It never guesses** a zone, a party or a wiki, and never applies an
  attribution the user did not give.
- **It never commits two repositories together**, never stages what it did
  not change, and never pushes.
- **It keeps no score.** It counts findings by kind, and weighs none.
- **A review is not a job.** It runs only when the user asks, and nothing of
  it runs overnight. A report it reads is a lead, never permission to edit.
- **It never fades a page on its own**, and never without a written
  proposal the user could read. It never deletes a page, never edits a raw
  record, and never moves a page anywhere but its own wiki's `dormant/` or
  `archive/`.
