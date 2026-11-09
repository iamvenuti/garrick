---
name: threads
description: >
  Open, list, wrap, park, finish and create work threads, catch the
  user up on what changed in them, and add zones, by voice or typed. The
  procedure behind the spoken commands in System/rules.md. Use when the
  user says "open X", "pick up X", "resume X",
  "where was I on X", "where am I", "what's open", "what's open in Work",
  "what's next", "what should I do while I wait",
  "catch me up", "catch me up on X", "catch me up on X since Monday",
  "catch me up this week",
  "I'm being interrupted", "hold this", "hold X", "back", "where was I",
  "back to X",
  "close X", "wrap X", "wrap it", "wrap up", "wrap this", "save where I am",
  "close for the day", "I'm done for today", "finish X", "X is done", "close
  X for good", "park X", "put X aside", "wake X", "unpark X", "what's
  parked", "is there a thread on X", "find X", "new project X for Acme", "new
  thread X in Acme", "start a thread on X", "rename X to Y", "move X to Y",
  "delete X", "add a zone called X", "new zone X", "that's wrong, it's Y", or "correct X to
  Y".
  Also use at the end of any
  session that produced a decision or a deliverable, so the thread can be
  resumed cold.
---

# Threads

A thread is one line of work with one resume point: the `### Resume here` block
at the top of `## State of play` in its thread note. This skill reads that block,
rewrites it, and retires it. It is how the user moves around the workspace
without looking at a folder.

Everything here works spoken or typed. Every reply has a **spoken form** and a
**written form**; which one to use is set out under *Listening mode*, and each
command below gives both.

## Where things are

All paths are relative to the workspace root.

| What | Path |
|---|---|
| Thread note | `Zones/<Zone>/<Project>/Threads/<Thread>/<Thread>.md` |
| Project hub | `Zones/<Zone>/<Project>/<Project>.md` |
| Open actions | `Zones/<Zone>/Todo.md` |
| Parties, Walls, People, Aliases | `System/context.md` |
| Meeting pages | `Wikis/Meetings/wiki/sources/`, people in `wiki/people/` |

A thread note is the `.md` file whose name matches its folder. Other files in the
folder are working notes. A folder whose name starts with `_` is not part of
the work: the scripts pass over it, and so does this skill. Never list, open
or wrap anything inside it.

A thread is **live** unless its frontmatter says `status: done` (finished) or
`status: parked` (set aside until it is woken).

To list every thread with its status and last update:

```sh
find Zones -mindepth 5 -maxdepth 5 -path 'Zones/*/*/Threads/*/*.md' | while IFS= read -r f; do
  case "$f" in */_*) continue;; esac
  [ "$(basename "$f" .md)" = "$(basename "$(dirname "$f")")" ] || continue
  printf '%s\t%s\t%s\n' "$(grep -m1 '^updated:' "$f" | cut -d' ' -f2)" \
    "$(grep -m1 '^status:' "$f" | cut -d' ' -f2)" "$f"
done | sort -r
```

It runs the same in zsh and bash, prints nothing when there are no threads
yet, and keeps the spaces in a name.

A zone's own `AGENTS.md` adds to this skill and wins where it says so.

Where the `desk` skill is installed (the cmux extra), "open X", "close X" and
"close for the day" go to it first: it opens, wraps or closes each thread in
its own tab, and the session in that tab runs this skill.

## The rules behind the commands

`System/rules.md` keeps one resume point per thread and open actions in
`Todo.md`, and leaves the rest to this skill. These are the rules it moved
here, word for word. The commands below carry them out.

**Threads**

- **Every thread has one resume point**: the `## State of play` section of its thread note, opening with a **Resume here** block. It says what is done, the live artifact, the next action, who it waits on and the deadline. Read it before opening anything else in the thread. A project that is only ever one thread may keep that section in its hub instead.
- **The hub is the project's index.** It links every thread: under `## Threads`, or under `## Finished` once it is done.
- **Rewrite the Resume here block at the end of any session that produced a decision or a deliverable**, so that it describes now. Add a dated entry below it; keep the old entries.
- **A finished thread** gets `status: done`, and its Resume here block becomes `### Outcome`: what was delivered or decided. The project hub lists it under `## Finished`.
- **A parked thread** gets `status: parked`: set aside, not finished. It keeps its folder, its Resume here block and its links, and drops out of "what's open" until it is woken. **A parked project** has `status: parked` on its hub, and every thread in it is parked with it, whatever its own note says.
- **Open actions live in the zone's `Todo.md`.** A thread note says where the work stands; it is not a to-do list, and actions are not copied into it. An action that opens with its thread's link keeps pointing at a live thread: when a thread is renamed, its lines follow. Dates go last on the line, where Obsidian Tasks reads them.
- **A checkpoint is the one exception.** As the work happens, a `### Checkpoint` block under Resume here records what this session made, decided and left half done, unconfirmed and never touching the block above it; its To file lines are held there, unfiled, until the next wrap files them and removes the block. Only a wrap or a finish confirms anything.
- **A deadline nobody gave says so.** The Deadline row reads "not given" where nobody has dated the work, and "none" only where somebody said there is none.
- **If your assistant has a memory of its own**, keep one entry per live or parked thread that says where its resume point is, and nothing else, with its `source:` and `created:`. No status: the note has it. Delete the entry when the thread is finished.

**Voice**

- **Names are the names the work already has.** Zones, projects and threads take letters and digits, spaces, hyphens, apostrophes, `&`, and a full stop inside an acronym: Q4 Planning, ISO 27001, Birch & Co. Nothing else, since the rest either cannot be stored as a folder or is a separator the spoken grammar uses, such as the comma in "Acme, pricing". Siblings must not sound alike.
- **A name that does not say how it is said carries a spoken form.** `spoken:` in the note's frontmatter is what is heard for it (Q4 Planning, `spoken: fourth quarter planning`), and a request matches it alongside the name itself. A year standing as a word of its own needs none: Summit 2027 is said "twenty twenty-seven". A zone has no note, so a zone name has to say how it is said.
- **"Open X"**: read that thread's Resume here block and answer in two sentences: where it stands, and the next action.
- **"Close X" or "wrap X"**, or **"wrap it"** for the thread in hand: rewrite its Resume here block and add the dated entry. **"Close for the day"**: do that for every thread worked on today.
- **"I'm being interrupted"**, **"hold this"** and **"hold X"** run the wrap, as "wrap it" does. **"Back"** or **"where was I"** opens the thread whose note was written most recently and is not finished or parked; **"back to X"** opens X. Nothing to resume: say so, and offer the most recent thread.
- **"Finish X" or "X is done"**: close the thread for good (see Threads).
- **"Park X"**: set the thread aside without finishing it. **"Wake X"** or **"unpark X"**: bring it back; so does "open X" on a parked thread. **"What's parked"**: name the parked threads. **"Rename X to Y"** moves the note and every link to it; **"delete X"**, for what should never have existed, lists what would go and acts only on the name said again.
- **"Where am I" or "what's open"**: name the live threads, most recent first; at most five when the user is listening.
- **Learn the aliases.** When you had to ask what a name meant, add the heard form to the Aliases table, with its Learned cell.
- **"That's wrong, it's Y"** stops the old value everywhere, not only where it was heard. `System/tools/correct.py` lists every live copy, in memory, `System/context.md`, hubs, thread notes, `Todo.md` and the wikis, and on one yes fixes them all, one commit per repository. Live files keep only the new value, with no trail of the old: git holds it. A raw record is never edited; the page resting on it says it was superseded.

**Files**

- **Deliverables carry the date they were first made**: `YYMMDD - <name>.<ext>`. The date never moves, so a folder sorts by when the work started. Build intermediates (`build/`, `render/`, `specs/`), scripts and a folder's `README.md` are not deliverables and keep their names.
- **A hub can change two things about its project.** `layout: thread-first` keeps everything inside the threads, each with its own `Sources/` and `Deliverables/`, and nothing at the project's top but `Threads/`. `anonymous: true` makes a project whose deliverables name no other party of its zone, nor any of their people; it can be a list of further names to keep out instead.
- **Instruction files point, they do not restate.** An `AGENTS.md` routes to the file that owns a fact; it never copies it, holds status, or keeps a hand-written list of projects or skills.
- **Garrick's instruction files stay as shipped.** This file and every `AGENTS.md` are Garrick's. A rule or a route of the workspace's own goes in the local file beside it, `System/rules.local.md` or an `AGENTS.local.md`, which Garrick never ships or changes. `check.py` warns when one of Garrick's differs from what it shipped.
- **Run the check.** `python3 System/tools/check.py` tests the workspace against these rules and exits non-zero on a problem. Add `--ear` for a three-sentence answer to read aloud. Rules that only this workspace keeps are switched on in `System/garrick-checks.json`.
- **A page that fades takes its raw record with it**, into the wiki's `dormant/raw/` or `archive/raw/`, renamed and never changed.

## Running an action: one executor, where the status page is installed

Park, wake, a new project or thread, a rename, a deletion and ticking a
`Todo.md` line each have one executor, `System/status/page_action.py`, which
the status page extra installs. A page button, the Ask box and a session run
the same code through it: the edit, the stale check, the commit with the wall
check, the record in the log, and one request for the
page to rebuild, so the page shows the change within seconds. From a session,
give it the verb and its options, from the workspace root:

```sh
python3 System/status/page_action.py park --zone Work --project Acme --thread Pricing
python3 System/status/page_action.py todo-done --zone Work --line "Send the revised terms"
```

It prints one sentence and exits 0, or prints why it refused and exits 1; a
refusal writes nothing. The verbs are `park`, `wake`, `new-project`,
`new-thread`, `rename`, `delete`, `undo`, `todo-add`, `todo-done`,
`todo-undo` and `todo-date`; `--help` lists their options. Its other verbs
take JSON on standard input, with `--via session` after `--workspace .`.

**Pending hand edits go first.** The executor commits the whole file it
edits: the thread note for park and wake, `Todo.md` for a Todo verb. An edit of
your own still waiting in that file would be swept into its commit under the
wrong message. Before the call, look: `git -C "Zones/<Zone>" status --porcelain
-- <that file>`. If it lists the file, commit your edit first, staging by name;
or, as Wrap step 8 does for ticks, make the executor call first and the hand
edit after.

**Check for it first**: `test -f System/status/page_action.py`. Where it is
there, use it for these verbs and do not also run `scaffold.py` or commit by
hand for them: it has done both. Where it is not there (no status page), each
section's steps below are the way, exactly as before: the scaffolding script
and a commit by hand. Everything else a wrap
writes is by hand either way.

## Resolving a name

Every command that names a thread resolves the name first. Names arrive by
dictation, so resolve before acting, and never guess.

1. **Normalise what was heard.** Ignore case, punctuation, "the", and the words
   "thread" and "project". Treat "and" and "&" as the same.
2. **Look it up in Aliases** (`System/context.md`). A heard form listed there
   means what the table says it means.
3. **Match, in this order, and stop at the first step that finds anything:**
   - a thread name, or the `spoken:` form in its note where the name does not
     say how it is said (`pricing` → Acme's Pricing thread; `fourth quarter
     planning` → Q4 Planning);
   - "project, thread" (`acme pricing`, `acme, pricing`);
   - a project name: if it has one live thread, that thread; if several, ask;
   - a party or a person, through Parties and People: the projects whose hub
     `party` is that tag, then as for a project name (`dana whitlaw` → Dana
     Whitlock → `acme` → the Acme project);
   - a near match: a name that sounds or is spelt close to the heard one.
4. **One match: act on it**, and start the reply with its short name, so a wrong
   match is heard at once ("Acme pricing: …").
5. **More than one: ask in one line, naming the candidates.** "Pricing is in
   Acme and in Birch. Which one?" Never pick, and never pick between zones.
   Two threads heard the same way, by name or by `spoken:` form, are the same
   question.
6. **None: say so, and name the nearest live threads.** "No thread called
   roofing. The closest is roof repair, in House."
7. **Learn it.** When you had to ask what a heard name meant, add the heard form
   to the Aliases table once the user answers, with a Learned cell saying
   when and from whom: `| dana whitlaw | Dana Whitlock | 2026-10-16, user |`.
   Where the table has no Learned column yet, add it to the header and the
   separator and leave the rows typed by hand as they are. Re-read
   `System/context.md` right before editing it.

The **short name** is the one to say back: the thread name alone if no other
thread has it; otherwise "project, thread"; the zone as well only when two
projects share a name.

**No name given** ("wrap it", "wrap this", "wrap up"): use the thread opened
in this session, or the thread whose folder the session started in. If the
session touched several, ask which, naming them.

## Open: "open X"

1. Resolve X.
2. Read that thread's `### Resume here` block. Nothing else: not the hub, not
   the working notes, not the dated entries, unless the user asks.
3. **Read the checkpoint beside it**, the `### Checkpoint` block under Resume
   here, with the tool rather than by eye, so both hashes are in hand from the
   start:
   ```sh
   echo '{"verb": "checkpoint", "read": true, "zone": "Work", "project": "Acme", "thread": "Pricing"}' \
     | python3 System/tools/scaffold.py checkpoint
   ```
   The reply gives `base`, `key`, the items with their ids, and one line to
   say. There is usually none, and then there is nothing to add.
4. Reply in two sentences: **where it stands**, then **the next action**. Fold
   in who it is waiting on when it is blocked, and the deadline when it is
   close. When **Keep in mind** says more than nothing, add it as a third
   sentence: it is what the user had in their head when they left.
   **A checkpoint adds one more sentence**, said as unconfirmed: what it
   records has not been wrapped, and only what it has under Decided was
   decided. Where the reply says it is stale or cannot be read, say that
   instead and resume from Resume here: "a checkpoint from 14:32 predates the
   last wrap; read it, don't resume from it."
5. That thread is now the one in focus for this session: a later "wrap" with no
   name means it.

Spoken: "Acme pricing: the price sheet went to Dana on Tuesday and we're waiting
on her volumes. Next is the second draft once she replies, due Friday the 3rd."
With a checkpoint: "Acme pricing: confirmed on Tuesday, waiting on Dana's
volumes. Since then, not yet wrapped: the price sheet was saved at 14:20 and
the next step is row 14 of the tier-two volumes."

Written: the same two sentences, then the Resume here table as it stands in the
note, then the checkpoint's own lines under its heading, and the note's path.

**If the thread is done**, say so with its outcome in one sentence and ask
whether to reopen it. Reopening sets `status: active` and writes a new Resume
here block above the outcome paragraph.

**If the thread is parked**, wake it first: someone who opens a thread means
to work on it. Waking is the Park section's second half, steps 2 to 5
(`status: active`, `updated:`, a dated "Woken." entry, a commit). When the
thread is parked because its project is, wake the project's hub instead, which
brings back every thread that was live before; say so. Then answer as for any
live thread, opening with a few words that say what changed: "Pricing was
parked; it's active again." A question that only looks at a thread ("where
did Pricing stand", "what's parked") reads it and leaves it parked.

**If X names a zone** ("open Work"), treat it as "what's open in Work".

## Checkpoint: as the work happens

A wrap makes a thread resumable, and nothing but "wrap it" starts one. Most
sessions end another way: a call, a closed lid, a crash, a context that ran
out. A checkpoint is the small record written while the work is happening, so
what the session produced survives either way. It sits in the thread note as a
`### Checkpoint` block directly under Resume here, which it never touches, and
the next wrap folds it in and removes it.

**Three things fire one, and nothing else:**

1. A file saved under the project's `Deliverables/`, or at the path the Live
   artifact row names, in this session.
2. The user stating a decision in words that decide: "we go with", "send it as
   is", "drop tier three". A question, a "maybe" or a "let's see" is
   *Considering*, which never becomes a decision on its own.
3. The next action changing, by the user's words or because something saved
   finished the old one.

Not a clock, not every turn, and not because the user asked: "wrap it" stays
its own command. Write it at the end of the turn where the
event happened; one turn with three events makes one write. A long discussion
with none of the three makes no checkpoint.

**Write it with the tool**, which keeps the shape, the sources and the repeat
test out of habit's hands. Send `base` and `prev` as the last read gave them:

```sh
python3 System/tools/scaffold.py checkpoint <<'EOF'
{"verb": "checkpoint", "zone": "Work", "project": "Acme", "thread": "Pricing",
 "base": "<base>", "prev": "<key, or leave the key out for the first>",
 "items": [{"kind": "made", "path": "Deliverables/261015 - Price sheet.xlsx", "at": "14:20"},
           {"kind": "decided", "said": "Go with the tier-two rate as drafted", "by": "user", "at": "14:25"},
           {"kind": "considering", "text": "dropping tier three"},
           {"kind": "next", "text": "fill in the tier-two volume on row 14", "by": "user"},
           {"kind": "action", "text": "send Dana the price sheet", "said": "I'll send Dana the sheet"},
           {"kind": "incomplete", "text": "the tier-three tab is half filled"}]}
EOF
```

One item a thing, each with the source its kind needs: a `made` item its path,
a `decided` item the words it was decided in and who said them, an `action` or
a `deadline` an ISO date **only** where somebody gave one, and nothing where
nobody did. An item is changed by sending its `id` again, and removed only
under `drop`, so a second session cannot lose the first one's work. The tool
refuses anything else in one line, which is the line to read: it never writes
Resume here, never writes `Todo.md`, never commits, and carries no meeting
material.

**What the user sees**: typed, one closing line, "Checkpoint: Acme pricing,
14:32." Spoken, nothing at all, because a sentence after every saved file gets
in the way. Open and "where am I" mention it; the wrap settles it.

**Where the tool is not there** (a workspace installed before it), say once
that checkpoints are not available here, and that "wrap it" before leaving is
what saves the place.

## List: "where am I", "what's open"

1. List the live threads, most recently updated first (`updated:` in the
   frontmatter, or an unwrapped checkpoint's own time where that is later;
   where two tie, the later commit to the note). Parked threads are
   not live: leave them out, and end with how many are parked, if any.
   "What's parked" lists them instead, oldest first.
2. "What's open in Work", "what's open for Acme": narrow to that zone, project
   or party first.
3. "Where am I": if a thread is in focus this session, say which first.

Spoken: at most five short names, then how many more. "Seven open. Most recent:
Acme pricing, Birch launch plan, roof repair, supplier audit and the tax
return, plus two more." For "where am I", open with "You're in Acme pricing."

Written: every live thread, one line each: short name, zone, `updated` date,
and the Next action row.

Listing reads frontmatter only. It never opens a Resume here block.

## Next: "what's next", "what should I do while I wait"

One thing worth doing elsewhere while a long turn runs, or at any moment
between two pieces of work. It is the same list the Garrick band shows while a
turn runs when its `while-you-wait` preview is on, from the same script, so the
answer here is the band's first pick:

```sh
python3 System/tools/next_up.py --zone <the session's zone> --exclude <the thread note in focus>
```

Leave out `--zone` when the session is in no zone (the workspace root,
`System/`, a wiki), and `--exclude` when no thread is in focus. It prints JSON,
best first, and changes nothing; `--say` prints only the first pick's line.

1. **Read the first pick's `say`**, word for word. It names a thread and an
   action in a few words and never quotes a meeting: do not add to it from the
   thread note, the Todo line or a meeting page.
2. **Offer, never act.** "Want me to open it?" for a thread, "Want me to tick
   it?" for a Todo line, which carries the request in `tick` for
   `page_action.py` when the status extra is there. Nothing is opened, ticked
   or sent into another session until the user says so. A tick in the zone
   this session is working in waits until the work in hand is done, so the two
   commits never meet.
3. **"Next" again** gives the following pick, not a new reading of the list.
4. **Nothing in the list:** "Nothing is waiting."

The order is six plain rules, each a source Settings › While you wait on the
status page can switch off or move: the thread whose note was
written most recently today, Todo lines due today or late with a
reply or a chase first, chases that have come due, what waits in an Inbox, a
parked thread left alone for 30 days ("park or finish?"), and a live thread
not wrapped for 14 ("wrap?"). It never offers the thread in focus. It covers
every zone unless *Same zone only* is switched on there.

Spoken: the pick and the offer. "Reply on the renewal dates, in Birch, due
today. Want me to open it?"

Written: the first pick's line, then the next two, each on its own line.

## Catch up: "catch me up", "catch me up on X", "since Monday", "this week"

What changed while the user was away, thread by thread, from the records
alone: the zone's history, the thread notes and the Todo list. Read-only: it
answers in the conversation and writes a file only on a yes to saving it
(step 7). It runs when asked and at no other time. "Brief me for X" is the
`meetings` skill's, a brief for a meeting; this is not that.

1. **What it covers.** X is a zone, a project, a thread, or several joined by
   "and": "catch me up on Acme, pricing and Birch launch". Resolve each name
   as in *Resolving a name*, and a zone by its name. No X: the zone of the
   thread in focus, or of the folder the session started in; at the workspace
   root, with more than one zone, ask which in one line. One zone at a time;
   more only when the user names them. Never pick between zones.
2. **The period.** "Since Monday", "since the 19th": from that day, the most
   recent one before today, as `--since`. "Since yesterday": `--days 1`.
   "This week": `--period week`, since Monday. "The last five days":
   `--days 5`. "The last two weeks": `--period 14-days`. Nothing said: leave
   all three out, and the tool takes the last day, or the period
   `"catch-up"` in `System/garrick-settings.json` names.
3. **Gather**, with the folder names the names resolved to:
   ```sh
   python3 System/tools/briefing.py --zone Work --project "Birch Entry" --thread "Acme/Pricing" --since 2026-10-19
   ```
   It prints JSON and changes nothing: per thread that changed, newest first,
   its commits with their messages, its Resume here block now (`resume.now`,
   its rows in `resume.rows`) and as it stood when the period began
   (`resume.before`), the dated entries added, a waiting checkpoint, its Todo
   lines split into `added`, `ticked` and `open`, and the meeting pages its
   note links (`meetings`). `quiet` names the live threads that did not
   change; `parked_left_out` counts the parked ones nobody named; `unmatched`
   names what the tool found no thread for, which you say.
4. **Read the judgment** before writing: `System/briefing.md`, then
   `System/briefing.local.md`, which wins. `guidance` in the JSON names the
   ones there are. They say what to raise, what to say in a line and what to
   leave out.
5. **Write the briefing** from the JSON and nothing else.
   - **An overview first**: what changed, how many threads, the one or two
     things that need the user, and how many were quiet. Three sentences at
     most.
   - **Then one section per thread listed**, in the order given: what changed
     and why it matters; the decisions, with their reasons, and the questions
     still open; what to look at before continuing; its open actions, the
     overdue first, then what was added and what was ticked; and where it
     stands now, with its Next action.
   - **Each statement links the record it rests on**: the thread note, a
     commit by its short hash, the zone's `Todo.md`. A meeting page appears
     only as a link the note already holds, never quoted, summarised or
     opened for this. Nothing is read from the Meetings wiki for a catch-up,
     so the walls hold exactly as they do for *Open*.
   - **A gap is said as a gap**: commits with no dated entry to say why,
     `history` false (no record of what changed, only what is there now),
     `resume.changed` null, a line marked `either` (it could be another
     thread's of the same name), a checkpoint that is `stale` or not `valid`.
     A checkpoint is said as unconfirmed, as *Open* says it.
   - **Nothing changed**: say so in one line, with how many threads were
     quiet. "Nothing moved in Work since yesterday; six threads are quiet."
6. **Offer to save it, only when it covers one project**: end with one
   question, "Save it in Acme's deliverables?" A catch-up across several
   projects or a whole zone offers nothing: there is no one project to hold
   it.
7. **Save it only on a yes**, as the `meetings` skill's *Prep*, step 7, saves
   a brief: `Zones/<Zone>/<Project>/Deliverables/YYMMDD - Catch-up since
   <D Month>.md`, dated the day it was first made; with a thread of that
   project in focus, add the file to its Live artifact row beside what the
   row names; commit it in the zone's repository so the pre-commit hook runs
   the wall check, and never with `--no-verify`. Saving is not sending.

Spoken: the overview alone, then offer the detail, "Want it thread by
thread?" For one project the save offer takes that place, since the saved
file holds the detail. "Since yesterday in Work, two threads moved. Acme
pricing: the sheet went to Dana and tier two stays; chasing her volumes is
next, and sending the sheet is eight days late. Birch launch has one new
action. Save it in Acme's deliverables?"

Written: the overview, then a section per thread, each statement with its
link, and the save offer, where there is one, as the last line.

## Find: "is there a thread on X", "find X"

The question to ask before starting something: does it exist already,
anywhere. Unlike *List*, it covers every zone and every status, finished
threads included, and it reads names only.

1. **Normalise what was heard** as in *Resolving a name*, step 1, and drop the
   question around it ("is there a thread on", "do I have anything for").
2. **Match every name in the workspace:** each project (a folder under
   `Zones/<Zone>/`, not `Inbox/`) and each thread, with the `spoken:` form in
   its note. The listing under *Where things are* prints every thread with its
   status, finished ones too. A name matches when every heard word is the
   start of a word in the thread's name, its project's or its zone's, or in a
   spoken form, ignoring case and accents (`freight` finds Freight Terms,
   `fourth quarter` finds Q4 Planning), or when it sounds like the heard one,
   the near match of *Resolving a name*. Read frontmatter only, never a
   note's body.
3. **Answer live ones first, then parked, then finished**, by short name, each
   with its project and zone where the short name leaves them out, and its
   status when it is not live.
4. **Offer, never act.** A parked match: offer to wake it. A finished one:
   offer to open it, which reads its `### Outcome`. Nothing is opened, woken
   or made until the user says so.

Spoken: "Two. Freight terms in Birch, live, and Acme's Freight Terms, parked.
A third is finished, in House. Want me to wake Acme's?" None: "Nothing called
freight, in any zone."

Written: one line each: the name, its project, zone and status.

## Wrap: "close X", "wrap X", "I'm being interrupted", "hold this", "hold X"

Wrapping makes the thread resumable cold, by anyone, months from now. It is
the one way to save a thread's place: "wrap it", the band's *Wrap*, and the
spoken "I'm being interrupted", "hold this" and "hold X" all run it. One
thread per wrap: the one named, and nothing else.

**How it runs.** Resolve X first ("hold this" or no name at all: the thread in
focus, as under *No name given*). Then:

- **Ask the one question, in the foreground, before anything starts**:
   "Anything only in your head?" Enter, "no", "skip" or silence skips it. Take
   the answer as said and never ask a follow-up. What the user already said
   ("hold this, I was leaning towards the lower tier") is the answer, and is not
   asked again. The answer goes into *Keep in mind*; a skipped question leaves
   *Keep in mind* as the session knows it, or `nothing`. When the wrap is part of
   closing the day, or for the band's *Close*, which waits for the note before
   it ends the session, do not ask and do not run in the background: the wrap
   runs in the foreground, each thread in turn.
- **Take the lock**, unless the request says the band has taken it already,
   so a second wrap of this thread cannot start while one is running, and so
   the band can show it:
   ```sh
   python3 System/tools/wrap_lock.py start "Zones/<Zone>/<Project>/Threads/<Thread>/<Thread>.md"
   ```
   It prints `locked` and exits 0, or says that a wrap of this thread is
   already running and exits 1: then say so and stop. The lock is a file in
   `System/generated/`; a lock older than ten minutes counts as gone.
- **Run the steps below**, 1 to 12. Where the assistant can start a
   background subagent, start one for them and
   return to the user at once: "Acme pricing is being wrapped. Say back when
   you're done." Brief the subagent with everything the conversation holds that
   the steps need, since it has not seen it: the thread note's path, what this
   session did and decided, the files it touched, the actions to file and the
   lines to tick, any deliverable that left the workspace and who edits it
   next, and the answer to the question word for word. The brief carries the
   walls too, since a cold run knows none: the project's `party` (from its
   hub), the walled parties it does not name (from the Walled column of the Parties table in
   `System/context.md`), and any material in this session that a wall held
   back, named only as "held back" with no content, no party and no subject.
   Tell it to do the wall check (*The wall check*, step 4 above) before it
   writes anything, and to write nothing it cannot place. Tell it to follow the
   steps to the letter, to touch nothing outside this thread, and to end with
   step 13. The foreground run needs none of this: it has the session. Where the assistant has no background run, do the steps yourself,
   in the foreground, as a wrap always was.
- **The last act of the wrap, success or failure,** is step 13: remove the
   lock. A wrap that died leaves the lock behind, and it expires by itself.

**The steps:**

1. **Resolve X** (done above) and stop if the thread is finished or parked:
   say so and offer to open or wake it.
2. **Re-read the thread note now.** Another session may have changed it since
   you last looked.
3. **Gather what happened**, from this session's conversation and the thread's
   files:
   ```sh
   git -C "Zones/<Zone>" status --porcelain --untracked-files=all -- "<Project>/"
   git -C "Zones/<Zone>" log --since=midnight --name-only --format='%h %s' -- "<Project>/"
   ```
4. **Run the wall check** (below) on anything from the Meetings wiki that the
   wrap would write into the note: quoted, paraphrased, summarised, or linked.
   That includes meeting material read earlier in this session.
5. **Fold in the checkpoint**, if the note has one. Read it with
   `{"verb": "checkpoint", "read": true, ...}`, then, in the one edit that
   rewrites Resume here below, and in the same commit as the `Todo.md` lines
   it files:
   - **Made** items go to the Live artifact row where they are the artifact,
     and into the dated entry either way;
   - **Decided** items go into the dated entry with their quotes, said to
     come from the checkpoint of 14:32;
   - **Considering** items go to Keep in mind, as "leaning towards …, not
     decided". Nothing promotes one: a decision carries its own words;
   - the **Next action** becomes the row's, unless the user has since said
     otherwise;
   - **Incomplete** goes to Keep in mind, never to Where it stands as though
     it were finished;
   - **To file** items are the actions for step 8, word for word, each
     compared with the list as that step compares any line; one nobody
     dated goes on the list with no 📅, because no date is not a date;
   - a **Deadline** goes to the Deadline row.
   Then **remove the block**, heading and markers, in that same edit. A
   checkpoint the reply calls stale or invalid is read and never resumed from:
   show its items and ask in one line whether any still hold. Made and Decided
   items carry their sources and fold without a question; a Next action that
   differs from the confirmed one is asked about.
6. **Rewrite the Resume here block** so it describes now. Replace it; do not
   append to it.
   ```markdown
   ### Resume here

   **Where it stands, 27 September 2026.** <What is done, what is not, whether
   it is blocked. Two or three sentences.>

   | | |
   |---|---|
   | Live artifact | <path, relative to the project, and what it is> |
   | Rebuild with | <how to make it again, and from what> |
   | Next action | <the single next thing, small enough to start in two minutes, and whose it is> |
   | Keep in mind | <what is only in your head: a decision half made and why, a doubt; or nothing> |
   | Waiting on | <who, or nobody> |
   | Deadline | <date, and what breaks if it slips; none; or not given> |
   ```
   Keep all six rows; a row that does not apply says "none" or "nobody".
   **Deadline has a third answer**: "not given", for a thread nobody has dated.
   "None" claims there is no deadline, and nobody said that. The
   next action is one action, small enough to start in two minutes: "draft
   the pricing section" fails, "open the pricing sheet and fill in the
   tier-two volume" passes. Anything more goes to `Todo.md` (step 8).
   **Keep in mind** holds what no file can tell a cold resume: the decision
   half made and which way you were leaning and why, a doubt about a figure,
   a thing noticed and not yet acted on. Write it from what was said in this
   session and from the answer to the question, not from the files; `nothing`
   is a valid answer, and the usual one for a thread that is simply waiting.
   A block written before this row existed is still whole; the row is added at
   its next wrap.
   **Rebuild with** earns its place: an artifact nobody can regenerate is a dead
   end the moment it needs a change. Every path and link in the block must lead
   to something that exists now; `check.py` warns about one that does not.
7. **Add a dated entry** directly below the `---` rule, above the earlier
   entries, so the newest is first:
   ```markdown
   **27 September 2026.** <One line on what the session did.> <What was decided
   and by whom, quoting where the wording was the point. What you decided that
   they did not, marked as yours. What was left out on purpose, and why.>
   ```
   Never edit or compress earlier entries. They are the record.
8. **Actions go to the zone's `Todo.md`**, not the note. Re-read it right
   before editing. Append new actions for this thread under `## Inbox` as
   `- [ ] [[<Thread>]]: <action> 📅 <YYYY-MM-DD>`, in the format the list's
   header gives, the dates last. Open the line with this thread's link, or
   its path, `[[<Project>/Threads/<Thread>/<Thread>|<Thread>]]`, when another
   project has a thread of the same name: that is how a later wrap or finish
   finds its lines. A project in `System/` has no list of its own: its
   actions go in the `Todo.md` of the zone the user works from most, as the
   `todo` skill says.
   **The example line goes with the first real action.** A list nobody has
   written to yet may hold one, in `<angle brackets>`, to show the shape; delete
   it in the same edit that writes the first real line. It is a task like any
   other, so anything that counts open actions counts it.
   Tick the lines this session finished, whether they name this thread or
   only a party or person. Touch no line that names another thread.
   **Where `System/status/page_action.py` exists, tick through it, before
   appending anything** (*Running an action*): `python3 System/status/page_action.py
   todo-done --zone <Zone> --line "<the line's text, or enough of it to be the
   only one>"`. It ticks the line as written, commits `Todo.md`, and asks for
   the page to be rebuilt; it refuses a line that is not there or that two
   lines say, and writes nothing. Without the status page, edit the line by
   hand and let step 12 commit it.
   **Tick a line as it was written; the outcome goes in the dated entry, not
   on the line.** `[ ]` becomes `[x]` and `✅ <YYYY-MM-DD>`, today, goes last,
   as Obsidian Tasks writes it, and nothing else on the line changes: "file
   the drafts" stays "file the drafts", and the issue numbers they were filed
   as go in step 7's entry. **Never add a line for work that is already
   done.** `Todo.md` holds what is still to do; what this session did is the
   dated entry's, where it already is. `check.py` warns about a ticked line
   the zone's history never held open, and about a line longer than 200
   characters.
   **A deliverable that left the workspace** in this session, copied to a
   shared folder: ask who edits it next. Colleagues who edit it: the shared
   copy counts from now on (`share`); nobody, or colleagues who only read
   it: the copy here does (`here`). Re-read `Deliverables/published.md`
   (when there is none, copy `System/templates/published.md` to it unchanged,
   and never write the explanation yourself: every project's ledger opens with
   the same shipped words, so the wall check reads them as common wording
   rather than one project quoting another) and append one row,
   `| YYYY-MM-DD | `<file>` | `<destination>` | <recipients> | share or here |`,
   the destination relative to the folder the hub names in `shared:`, or the
   folder it went into (`Decks/`) when it kept its name. The file is a path
   under `Deliverables/`, or from the project's folder when it lives
   elsewhere. A clause may follow `share` or `here`, such as who edits it there. Say
   so in the Live artifact row when the shared copy is the one that counts.
   `python3 System/tools/drift.py` compares them from then on. In a
   thread-first project the ledger is the thread's own,
   `Threads/<Thread>/Deliverables/published.md`.
   **A copy that stopped counting** in this session is never deleted from the
   ledger: the row is the record of what left. Change its date cell to
   `withdrawn YYYY-MM-DD` when the copy came off the share, or `replaced
   YYYY-MM-DD` when a newer one took its place, the day it happened, and add
   the newer one's row beside it. A file sent by mail rather than placed on
   a share gets a row too, dated `sent YYYY-MM-DD`. drift.py reads such a
   row and never compares it.
9. **Set `updated:`** in the note's frontmatter to today.
10. **Update the hub's `## Threads` line** only if the thread's purpose changed.
    Re-read the hub first; change that one line.
11. **Memory pointer.** If you, the assistant, keep a memory of your own, keep
    one entry for this thread that says where its resume point is and nothing
    else: no status, no summary. Its frontmatter says where it came from, as
    every learned entry's does (*Autonomy* in `System/rules.md`): `source:`
    is the note it points at, `created:` the day it was made. Both may sit
    under `metadata:` instead, where an assistant keeps keys of its own.
    ```
    ---
    source: file:Zones/Work/Acme/Threads/Pricing/Pricing.md
    created: 2026-09-27
    ---
    Acme, Pricing (Work zone). Resume from
    Zones/Work/Acme/Threads/Pricing/Pricing.md, the Resume here block. Read it
    before anything else in the thread.
    ```
    Create it if missing, leave it if present, and add the two keys to one
    that has neither. No memory, no step.
12. **Commit in the zone's repository.** First move the lines ticked before
    today out of the list:
    ```sh
    python3 System/skills/todo/todo.py archive --zone <Zone>
    ```
    It moves them, whichever thread they name, to `archive/Todo-<YYYY>.md`,
    where they can be read and pasted back, and leaves the lines ticked today
    for the status page's *Done today*. The nightly sweep does the same, so in
    a zone it reaches this usually moves nothing; in one it does not reach, or
    a workspace without the jobs extra, it is the only thing that does. A
    project in `System/` archives the zone whose list step 8 wrote to, and
    commits that list there; with no list touched, there is nothing to
    archive.
    Then stage by name only what this wrap touched and this thread's own
    changed files: the thread folder, the hub if edited, `Todo.md` if edited
    or archived, `archive/` when the archive moved a line, and any
    `Deliverables/` or `Sources/` file this session made for the thread.
    Never `git add -A`.
    ```sh
    git -C "Zones/<Zone>" log -1 --format='%h %an %s'   # did someone commit meanwhile?
    git -C "Zones/<Zone>" add -- "<path>" "<path>"
    git -C "Zones/<Zone>" diff --cached --stat          # only what you meant
    git -C "Zones/<Zone>" commit -m "Acme, Pricing: second draft sent; waiting on Dana's volumes"
    ```
    The message says what changed. One zone per commit. Never push: that leaves
    the machine and needs the user's yes.
13. **Remove the lock**, whatever happened above:
    ```sh
    python3 System/tools/wrap_lock.py end "Zones/<Zone>/<Project>/Threads/<Thread>/<Thread>.md"
    ```
    The note's last write is the record that the wrap landed: "back" and the
    band read the time of that write, and nothing else.

Spoken, when the wrap runs in the background: "Acme pricing is being wrapped.
Say back when you're done." When it runs in the foreground, or when the
background wrap reports back: "Acme pricing wrapped. Next is the second draft
once Dana sends volumes, due Friday." Add a third sentence only for something
the user must know: a wall held material back, a meeting page was unfinished,
a commit failed.

Written: the same, plus the files changed and the commit hash.

## Back: "back", "where was I", "back to X"

The record is the thread note: a wrap, a finish or an edit sets its
modification time, and nothing else keeps a place.

1. **Which thread.** "Back" or "where was I", with no thread named: the live
   thread whose note was written most recently. A finished or parked thread is
   never the answer. "Back to X": resolve X, and open it. "Where was I on X"
   names a thread, so it is Open, not Back.
   ```sh
   find Zones -mindepth 5 -maxdepth 5 -path 'Zones/*/*/Threads/*/*.md' | while IFS= read -r f; do
     case "$f" in */_*) continue;; esac
     [ "$(basename "$f" .md)" = "$(basename "$(dirname "$f")")" ] || continue
     case "$(grep -m1 '^status:' "$f" | cut -d' ' -f2)" in done|parked) continue;; esac
     printf '%s\t%s\n' "$(stat -f %m "$f" 2>/dev/null || stat -c %Y "$f")" "$f"
   done | sort -rn | head -3
   ```
   The first line is the thread. After two wraps it is the later one. A wrap
   still running (`System/generated/wrap-*.lock`, less than ten minutes old)
   writes the note at its end: say that it has not landed yet, and open the
   thread from the block as it stands.
2. **Open it as Open does.** Where the `desk` skill is installed, that is its
   tab: `desk open "<the thread's folder>" --prompt "open <short name>"`, and
   the session there answers. Otherwise it is the thread in focus here.
3. **Read the block back**: where the user was, the next step, and Keep in
   mind when it says more than nothing. Where there is a `checkpoint`, add one
   clause: "There's also an unwrapped checkpoint from 14:32."

Spoken: "Back to Acme pricing. You were halfway through the tier-two volumes,
and next is row 14. You weren't sure about the tier-two rate."

**Nothing to resume:** no live thread has a note. Say so in one line and name
the most recent thread of any status: "Nothing to resume. The last thread you
worked on is Acme pricing, which is finished. Open it?" Never answer with
silence: it reads as a fault. **X is not a thread:** treat "back to X" as "open X".

## Close for the day: "close for the day", "I'm done for today"

Every session used today wraps its own thread, one at a time, wherever the
session runs. This session runs the procedure: it asks the others and waits.
It quits nothing: quitting cmux or an app stays the user's Cmd+Q. Never type
into an app's window, and never use computer use to reach a session.

1. **Find every live session used today**, merged by session id. Each source
   adds to the list and never replaces another.
   - **cmux tabs**, where the `desk` skill is installed:
     `desk status --today --json` gives each tab's session id, assistant,
     folder, state and thread note.
   - **Claude sessions outside cmux**, the Claude desktop app's included:
     the `ListAgents` tool lists the peer sessions, and `SendMessage` reaches
     one. A peer whose session id is already on the list is the same session.
     The peer list has left out cmux tabs, so it is never the only source.
   - **Codex app sessions** have no channel Garrick can rely on: the app
     answers on its own socket, and Garrick has found no way to ask it to wrap
     and to know when it has. They are listed, not reached, by folder:
     ```sh
     find ~/.codex/sessions -name 'rollout-*.jsonl' -newermt "$(date +%Y-%m-%d)" -exec sh -c 'head -n1 "$1"' _ {} \;
     ```
     Each first line holds `payload.id`, `payload.cwd` and `payload.originator`.
     Keep those whose `originator` is `Codex Desktop` and whose id is not on
     the list already. The Codex tabs in cmux are `desk`'s.
   - **This session**, if it worked on a thread today.
2. **Say the list before asking**, in one line: "Four today: two tabs, one
   Claude app session, this one; one Codex session I cannot reach." Go ahead
   unless the user stops you.
3. **Ask each one to wrap, one at a time**, and wait until its wrap has
   finished before the next, because two wraps at once collide on `Todo.md`
   and the hub. Finished means the wrap lock is gone and
   `System/generated/wrap-<note>.done` is newer than the request.
   - A cmux tab: `desk wrap --session <id> --yes` asks it, waits, and says
     whether the record was written. Exit 3 means the tab was mid-turn or
     waiting on a question: it was typed nothing.
   - A Claude peer: `SendMessage` with "Wrap it: close for the day, no
     question; this session stays open", then wait for the record.
   - A session that is mid-turn or waiting on a question is skipped and
     named. Do not ask it twice.
   - This session last, as Wrap does it, for the thread it worked on.
   - A thread that is done or parked is not wrapped.
4. **Report one line per session**: wrapped, with its thread and its next
   action (read from the thread note's Resume here block); skipped, with why;
   or not reachable, with its app and folder, so the user wraps it by hand.
   Then anything that failed. A thread with files changed today and no
   session on the list is named, not wrapped from the day's changes: its
   session is the one that knows.

Spoken, three sentences at most: "Wrapped three: Acme pricing, Birch launch
plan and roof repair. One Codex session in Birch is not reachable; wrap it
there. First thing tomorrow is the Acme second draft, due Friday."

Written: one line per session, as step 4 says.

## Finish: "finish X", "X is done"

Closes a thread for good.

1. **Resolve X.** "X is done" can mean a task inside a thread; if it could,
   ask in one line: "Close Acme pricing for good?"
2. **Set `status: done`** and `updated:` today in the note's frontmatter.
3. **Replace the Resume here block** (heading and table) with an outcome:
   ```markdown
   ### Outcome

   **Finished 27 September 2026.** <What it produced, where the final artifact
   is, what was decided and by whom.>
   ```
4. **Add a dated entry** below the `---`: "Finished." plus anything decided at
   the close. Keep the earlier entries.
5. **Hub:** re-read it, move the thread's line from `## Threads` to a
   `## Finished` section directly below it (create the section if missing),
   ending the line with the outcome in a few words.
6. **A checkpoint nobody folded in:** if the note still has a `### Checkpoint`
   block, read it and ask in one line what to do with it, before the outcome is
   written. Finishing over it would leave its To file actions on no list at
   all. Fold what still holds into the outcome and the dated entry as Wrap step
   5 does, then remove the block; drop the rest on the user's word.
7. **Open actions:** if `Todo.md` still has unticked lines that name this
   thread (`Acme, Pricing`), name them and ask whether to tick, keep or drop
   them. Do not decide for the user. Tick a line as it was written, as Wrap
   step 8 does, through the executor where it is there, after committing or
   leaving out any hand edit of your own pending in `Todo.md` (*Running an
   action*); the outcome goes in step 3's outcome and step 4's entry, not
   on the line. Never add a line for work that is already done.
8. **Last thread in the project?** Ask whether the project is finished too. If
   yes, set `status: done` in the hub.
9. **Delete the memory pointer**, if there is one. A pointer that outlives its
   thread keeps announcing work that no longer exists.
10. **Commit** in the zone's repository: "Acme, Pricing: finished; outcome
   recorded".

Spoken: "Acme pricing is closed. Two actions still point at it: tick them, keep
them, or drop them?"

Written: the outcome paragraph, the files changed, the commit hash.

## Park: "park X", "put X aside"; wake: "wake X", "unpark X"

Parking sets a thread aside without finishing it, so the lists stay short. It
moves nothing: the folder, the Resume here block, the links and the history
stay exactly where they are.

1. **Resolve X.** Parked threads resolve like any other.
2. **Run the executor** (*Running an action*), from the workspace root. It
   sets `status: parked`, or `status: active` for `wake`, and `updated:`
   today, adds the dated entry, "Parked." or "Woken.", and leaves the Resume
   here block as it is: it still says where the work stood. It commits the
   note ("Acme, Pricing: parked") and asks for the page to be rebuilt.
   ```sh
   python3 System/status/page_action.py park --zone Work --project Acme --thread Pricing
   ```
   A thread already set aside, or an active one asked to wake, is refused in
   one line and nothing is written, so read what it says rather than running
   it twice. Then step 3 if there is a reason, and step 5; step 4 is done.
   **Without the status page** (no `System/status/page_action.py`), run the
   scaffolding script instead. It writes that one note and commits nothing:
   ```sh
   python3 System/tools/scaffold.py park --zone Work --project Acme --thread Pricing
   ```
3. **If the user gave a reason**, add it to that dated entry. Where the
   executor ran, the note is already committed: commit this one line by hand,
   "Acme, Pricing: reason for parking".
4. **Commit** in the zone's repository: "Acme, Pricing: parked". Only without
   the status page; the executor has committed.
5. **Keep the memory pointer**, if there is one. A parked thread is not
   finished. **A checkpoint is kept too**, exactly as it is: parking sets work
   aside, and what the last session recorded is part of where it stood. The
   check says nothing about it while the thread is parked, and waking the
   thread brings it back to be read and wrapped.

**When X is a whole project** ("park Acme", where Acme has threads), leave
`--thread` out: the executor (or the script) parks the hub note, with the dated entry under its
`## State of play` if it has one, and the commit is "Acme: parked". Its thread
notes are left alone: every thread in it counts as parked while the hub says
so, and waking the project brings back exactly what was live before. Parking
the project parks all its threads with it. If X could be
the project or one of its threads, ask which.

Spoken: "Acme pricing is parked. Say wake Acme pricing to bring it back."

Written: the same, then the note's path and the commit hash.

## New: "new project X for P in Z", "new thread X in P"

Creation goes through the executor (*Running an action*), which runs the
scaffolding script, whose checks are the same, and commits. Run it from the
workspace root.

```sh
python3 System/status/page_action.py new-project --zone <Zone> --name "<Project>" --party <tag> --thread "<Thread>" [--spoken "<how it is said>"] [--thread-spoken "<how the thread is said>"]
python3 System/status/page_action.py new-thread --zone <Zone> --project "<Project>" --name "<Thread>" [--spoken "<how it is said>"]
```

**Ask how a name is said first.** Run the same line with
`python3 System/tools/scaffold.py project ... --check` (or `thread ... --check`),
which writes nothing: when it asks for a spoken form, put that question to the
user, and pass the answer as `--spoken`. The executor makes nothing for a name
that says nothing of how it is said, and returns the question instead. A party
must be one of the zone's own in `System/context.md`; it is refused otherwise.

**Without the status page** (no `System/status/page_action.py`), run the
scaffolding script directly, as step 4 and step 6 then say:

```sh
python3 System/tools/scaffold.py project --zone <Zone> --name "<Project>" --party <tag> --thread "<Thread>"
python3 System/tools/scaffold.py thread --zone <Zone> --project "<Project>" --name "<Thread>" [--spoken "<how it is said>"]
```

1. **Resolve the parts.** The zone against the folders under `Zones/`; the
   project against existing projects; the party against Parties and Aliases,
   giving its tag. The zone may be left out when the party's row in Parties
   names it, or the project already exists.
2. **A new project needs its first thread.** If none was given, ask: "What's
   the first thread called?" Every piece of work belongs to a thread.
   **Look for the name first**, as *Find* does: a project or thread with the
   same name, or one heard as it, in any project, zone or status. If there is
   one, say so in one line before making anything: "There's already a Freight
   Terms in Acme, parked. Wake that, or make a new one here?" It is a warning,
   not a refusal: two projects can each have a Pricing thread, so a new one is
   made if the user still wants it.
3. **A new party:** offer to add it to Parties before scaffolding, and ask
   whether it is walled: "Birch isn't a party yet. Add it to the Work zone,
   walled, so only a project that names it holds its material, or open?" With the answer, re-read
   `System/context.md`, then run
   `python3 System/tools/scaffold.py party --name "<Party>" --zone <Zone> --what "<what it is>"`,
   which writes the row and offers the tag itself, with `--walled` or `--open`
   for the flag; commit `System/context.md` on its own before the project, which
   is refused until the row is there. Never scaffold with a made-up tag. Where
   the user did not ask for a project at all but for help with a piece of work,
   the short route sets up the party, the project and the thread on one
   question instead: the `meetings` skill's *Nothing there yet*.
4. **Run the executor or the script.** When it refuses, it prints a one-line reason. Relay it
   in plain words and suggest a fix:
   - a name that will not work (an underscore, a comma, a slash, a full stop
     outside an acronym): say what is in the way and offer the name without it;
   - a sibling that sounds alike, or one already stored under that folder name:
     the refusal ends in a question, so put it to the user. Never choose
     between opening the one that exists and naming a new one;
   - an unknown party: step 3;
   - an unknown zone: name the zones that exist, and offer to add it
     (*New zone*, below).
5. **Fill in what you were told.** If the user gave the purpose, write it into
   the one-line description in the hub and the thread note. Otherwise leave the
   angle-bracket fields and mention them once. A name that does not say how it
   is said (Q4 Planning, ISO 27001) is a good name, and the script asks for the
   form to hear for it: ask the user in one line and write their answer into the
   note's frontmatter as `spoken:`, or pass it as `--spoken` next time.
6. **Commit**, what nothing has: the executor has committed the new folder
   and its hub line; the script has not. Any edit made after the executor
   (step 5's purpose line, a `spoken:` added by hand) is not in that commit:
   stage it by name and commit it, "Birch: purpose of Launch plan". Without the
   status page, check
   `git -C "Zones/<Zone>" status --porcelain`, stage the new folder by name, and
   commit "New project Birch (birch), first thread Launch plan". Adding Parties
   or Walls rows is a change outside the zone: commit it separately in the
   workspace root's repository, if it has one.

The new thread is now in focus, as if opened.

Spoken: "Birch is set up in Work with a launch plan thread. What's it for, in a
sentence?" or, where the name needs a spoken form: "Birch is set up with a Q4
planning thread. Should I hear that as fourth quarter planning?"

Written: the paths created and the commit hash.

## Rename: "rename X to Y"

The executor renames (*Running an action*), through the scaffolding script, so
the folder, the note and every link to it in the zone move together, in one
commit:

```sh
python3 System/status/page_action.py rename --zone <Zone> --project "<Project>" [--thread "<Thread>"] --to "<New name>"
```

It also commits the old name as a heard alias in `System/context.md`, and asks for the page to be rebuilt.
**Without the status page**, run the script itself, and do those by hand:

```sh
python3 System/tools/scaffold.py rename --zone <Zone> --project "<Project>" [--thread "<Thread>"] --to "<New name>"
```

1. **Resolve X.** If it could be the project or one of its threads, ask which.
2. **One match goes ahead**, and the reply says what moved: the instruction
   named it, so do not ask it back. A name close to one that already exists
   may mean that one: ask, naming it.
3. **Run the script.** It refuses a name that will not work, that sounds
   like a sibling or is taken, and a rename while the files it would change
   have changes not committed, while its folder holds a file the zone's
   history does not, or while a session is mid-turn there; relay the reason
   as under *New*. Finder's `.DS_Store` and the other files a machine makes
   on its own refuse nothing: the script clears them. It moves the folder and
   the note with git, renames the title and heading, rewrites every link to
   it in the zone (the hub's list, `Todo.md`, `project:` frontmatter, the
   notes between) and every link to a file inside its folder, and adds the
   dated entry "Renamed from <old>.", all in one commit in the zone. It adds
   the old name as a heard alias in `System/context.md`: the executor commits
   that; run by hand, commit it in the workspace root's repository.
4. **The memory pointer**, if you keep one: point it at the new note.
5. What it lists and leaves alone, mentions in the Meetings wiki, say once.

Moving a thread to another zone is not a rename: zones never mix. Say so,
and stop. Moving it to another project of its zone is *Move*, below.

Spoken: "Pricing is Renewal now, and its links follow. The old name still
finds it."

Written: the script's report, and the commit hash.

## Move: "move X to Y"

X is a thread and Y a project of the same zone. The executor moves it, through
the scaffolding script, so the folder, the note and every link to it in the
zone follow together, in one commit:

```sh
python3 System/status/page_action.py move --zone <Zone> --project "<From project>" --thread "<Thread>" --to "<To project>"
```

The script moves the effort record with it, and `undo` of the move puts it
back; the executor also asks for the page to be rebuilt. **Without the status
page**, run the script itself, which does the same for the effort record:

```sh
python3 System/tools/scaffold.py move --zone <Zone> --project "<From project>" --thread "<Thread>" --to "<To project>"
```

1. **Resolve X and Y.** X must be one thread; its project is the project it is
   in. If a name could be a thread or a project, or two threads share it, ask
   which. A project is never moved, and Y in another zone is not a move.
2. **One match goes ahead**: the instruction named it, so do not ask it back.
3. **Run the script.** It checks the thread's `party:` and the new project's
   `party:` against the Walled column of the Parties table in `System/context.md` first, and the
   old project's party, and the parties of the Meetings pages and other
   projects' files its notes link. If a walled party is not named by the new project, or any party
   cannot be read plainly, nothing moves:
   for a wall, say the sentence from *Zones and walls* and nothing more. It
   also refuses another zone, a thread of that name already in the new project,
   a new project that is parked or finished (and a parked one as the source),
   files of the thread that sit outside its folder, changes not committed, and
   a session mid-turn there; relay the reason as under *New*. Then it moves the
   folder with git, takes the thread's line out of the old hub and puts it
   with its description under the same heading in the new one (it refuses if
   that line cannot be found plainly), sets `project:` and `parent:`,
   rewrites every link to it and to the files inside its folder (the hubs,
   `Todo.md`, the notes between; wiki links and Markdown links alike, and it
   lists any it could not resolve plainly), moves its rows in
   `Deliverables/published.md` to the new project's, and adds the dated entry
   "Moved from <old> to <new>.", all in one commit in the zone. The commit
   goes through the zone's wall check, never around it; `undo` reverts it
   while it is the zone's last commit.
4. **The memory pointer**, if you keep one, and a desk tab open on the thread:
   point them at the new path. The report says so.
5. What it lists and leaves alone, mentions in the Meetings wiki, say once.

Spoken: "Pricing is in Birch now, and its links follow."

Written: the script's report, and the commit hash.

## Delete: "delete X"

For what should never have existed: a duplicate, a test, a thread opened in
the wrong project. Real work is finished or parked, never deleted: offer those
first.

```sh
python3 System/status/page_action.py delete --zone <Zone> --project "<Project>" [--thread "<Thread>"]
python3 System/status/page_action.py delete --zone <Zone> --project "<Project>" [--thread "<Thread>"] --confirm "<Name>"
```

**Without the status page**, the script's two forms, and step 5 by hand:

```sh
python3 System/tools/scaffold.py delete --zone <Zone> --project "<Project>" [--thread "<Thread>"]
python3 System/tools/scaffold.py delete --zone <Zone> --project "<Project>" [--thread "<Thread>"] --confirm "<Name>"
```

1. **Resolve X**, and run the first form: it changes nothing and lists what
   would go: the folder and its files, the hub's line, the open `Todo.md`
   lines naming it, and for a project every thread in it.
2. **Read that back** in three sentences at most, then ask: "Finish it,
   park it, or delete it?" Act on deletion only on "yes, delete <X>", with
   the name said again; a plain "yes" is not enough.
3. **Run the second form.** One commit in the zone; the reply gives the
   commit to revert. Meetings pages stay.
4. **The memory pointer**, if you keep one: delete it.

Spoken: "Deleted the test thread and its one open action. Say undo to bring
it back." On undo, `python3 System/status/page_action.py undo --zone <Zone>
--commit <commit>` (without the status page, `python3 System/tools/scaffold.py
undo` with the same options), which refuses once anything else has been
committed in the zone. A rename is undone the same way.

Written: the script's report, and the commit hash.

## Correct: "that's wrong, it's Y"

A wrong value is seldom in one place. An address, an account, a name or a
path one session wrote down, the next ones read as fact: in a memory entry,
in `System/context.md`, a Resume here block, a `Todo.md` line, a meeting
page. Fixing the copy in front of you leaves the others to be read again
tomorrow. When the user says "that's wrong, it's Y", "no, it's Y" or
"correct X to Y", about something written down:

1. **Settle the two values**: the wrong one as it is written, and the right
   one as the user gave it. A heard name is resolved first, as under
   *Resolving a name*. When it is not clear which written value they mean,
   ask.
2. **List every live copy**, which changes nothing:
   ```sh
   python3 System/tools/correct.py --old "<X>" --new "<Y>"
   ```
   It searches the memory entries in the folders `memory` names in
   `System/garrick-checks.json`, `System/context.md`, every hub and thread
   note, each zone's `Todo.md` and the pages of both wikis, and lists each
   file and line. A raw record that holds the old value is listed too, with
   the pages that rest on it.
3. **Say what it found, and ask once.** "Five places have the old address:
   two memory entries, the Acme pricing note, a Todo line and a meeting
   page. Fix them all?" A hit that is right where it is, such as a heard form
   in Aliases, which is meant to be misspelt, is named and left out with
   `--leave <path>`.
4. **On the yes, apply**, with the reason in a few words when the user gave
   one:
   ```sh
   python3 System/tools/correct.py --old "<X>" --new "<Y>" --apply --why "<why>"
   ```
   It writes Y in place of X in every file listed, re-reading each first;
   marks each page that rests on a raw record holding X with `superseded:`
   and one line at its end, since the record itself is never edited;
   rebuilds the Meetings index, and the status page where there is one; and
   commits once per repository, the files it changed and nothing else. A
   memory entry outside the workspace is changed and not committed.
5. **A memory entry whose only source was inbound** now rests on the user's
   word: add `user` to its `source:`.
6. **Report** how many files changed and each commit, and anything left
   uncommitted or refused. The walls check runs on each repository's change
   before it is committed, hook or no hook; where it refused one, that
   repository's files were put back as they were, and nothing there
   changed. The refusal names the check and the paths, and says which
   cause it was: the correction would have crossed a wall; a page's
   frontmatter is not plain key: value lines, or the page is a symbolic
   link, which is its form and no wall; the check did not finish, so run
   it again later; or a file another session has staged there failed the
   check, not this correction. Say the cause it gave, and only the wall
   sentence for a wall.

Never leave a trail of the old value: no "was X", no "not X". Live files
say what is true now, and git holds what was.

The `nurture` skill shares this tool: a correction given during a nurture
pass goes through `nurture.py correct`, which calls `correct.py` and records
it in the day's report.

Spoken: "Fixed in five places, three commits. The meeting page now says its
record has been corrected."

Written: the files changed, the commits, and anything left over.

## New zone: "add a zone called X", "new zone X"

A zone is one side of life or work, kept apart from the others. The
scaffolding script makes one as the installer does: the folder with its
`AGENTS.md`, `Todo.md` and `Inbox/`, its own git repository with the wall
hook, and its row in the Zones table of `System/context.md`. Run it from the
workspace root.

```sh
python3 System/tools/scaffold.py zone "<Zone>" --holds "<what it holds>"
```

1. **A name and what it holds is enough to go ahead**: the instruction said
   both, so do not ask them back. If the user did not say what it holds,
   ask. A heard name close to a zone that exists may mean that one: ask,
   naming it.
2. **Run the script.** When it refuses, relay the one-line reason in plain
   words and suggest a fix: a zone has no note to carry a spoken form, so its
   name has to say how it is said; offer a spoken version of one that does
   not, or a distinct name for one that sounds like a zone already there.
3. **Commit what the script left uncommitted.** Check
   `git status --porcelain` in the workspace root and in `Zones/<Zone>`.
   Stage by name, never `git add -A`, and commit each repository on its own:
   "New zone Health". The Zones row in `System/context.md` belongs to the
   root's repository.
4. **Run the check**: `python3 System/tools/check.py`. It reports a zone
   missing from the Zones table, without its wall hook, or not its own
   repository. Explain any problem in plain words.

The new zone holds nothing yet. Offer to start its first project (*New*).

Spoken: "Health is set up as a zone of its own. What's the first project in
it?" or, on a refusal: "Can't add Works: it sounds too much like Work.
Another name?"

Written: the zone's path, what it holds, and the commit hashes.

## The wall check

Run this whenever a wrap, a finish or a new thread would put anything from the
Meetings wiki into a thread note, a hub or a deliverable: quoted, paraphrased,
summarised, counted or linked. Material from earlier in the session counts. The
Knowledge wiki needs no check: it carries nobody's confidence.

1. **The project's party.** Read `party` from the hub's frontmatter. Missing,
   empty or still a placeholder: no meeting material goes in. Say so, and offer
   to set it.
2. **Each meeting page's frontmatter.** Read `zone` and `parties`. Either
   missing or empty: the page is unfinished and stays out. Say that a meeting
   page is missing its zone or parties, and offer to fill it in with the user.
   A tag not in the Parties table: cannot be checked, so it stays out; ask what
   it is.
3. **Zone.** The meeting's `zone` differs from the thread's zone: it stays out,
   unless the user asked for that meeting in this thread in this request.
4. **Walls.** For every tag in the meeting's `parties`, look for a Walls row
   pairing it with the project's party, in either column. One row found and the
   whole meeting stays out: not quoted, not paraphrased, not summarised, not
   linked, not mentioned as having happened. A wall holds for the whole page,
   even when the walled party said little.
5. **People.** A person page used on its own gets the same check: its party
   against the project's party.
6. **What passes** goes in as the least that serves: link the meeting page, and
   quote only where the wording is the point.
7. **Say that a wall held something back, in the words the rule gives, and
   nothing more.** "A wall holds some material back from this project, so I
   have not used it. Nothing was written." No title, date, party, person,
   subject or count, even if asked in the same breath. A question put straight
   to the Meetings wiki ("what did Theo say?") is a different request; its
   answer stays in the conversation and is never written here.
8. **Material the user dictates** into a thread that belongs to a walled party:
   ask once before writing it. "That sounds like Birch material, and Birch is
   walled off from Acme. Write it anyway?"
9. **Can't tell** whether a wall applies: ask.

**The same check runs again before every commit, whenever git runs the
hook.** Each zone's pre-commit hook runs
`System/tools/check.py --staged --walls-only` on the files being committed. A
link to a walled meeting, the name of a walled party, person or alias the project does not
name, or eight words in a row lifted from a walled meeting page,
its transcript, a meeting page still missing its parties, or a walled
project's own files stops the commit, with one line naming the file and the
wall.
When it refuses:

- **Take the material out** of that file and commit again. Tell the user a wall
  held something back, as in step 7, and nothing more.
- **Never commit with `--no-verify`** unless the user explicitly asks for it,
  in this request. Yes once is not yes next time.
- **If the refusal looks wrong** (a walled party named in a published context,
  say), tell the user which file and which wall, and let them decide.

Git skips the hook when its `core.hooksPath` setting sends commits past it,
and then nothing checks the walls at commit time. `check.py` warns when that
is so: tell the user what it says, and until it is fixed treat this
procedure as the only check.

The wall is between parties, not between the user and their own memory. It
decides what is written into a project, never what the user may know.

## Listening mode

**Use the spoken form when** the user said they are listening, or the request
arrived by voice: dictation marks such as mangled names, missing punctuation or
run-on phrasing. **Use the written form when** the user typed, asks to "show
me", "give me the detail" or "the full list", or the reply has to carry a path,
a table or a hash.

Spoken form, always:

- The answer first, in three sentences at most.
- Short names, never paths, tables, links, code or commit hashes.
- Numbers rounded, dates said as a day and a date ("Friday the 3rd").
- Offer the detail instead of giving it: "Want the full list?" Anything long
  goes in a file, and you say where in words ("it's in the Acme notes").

Written form: the spoken answer on top, then the detail each command lists.

## What this skill does not do

- **It never touches a thread it was not asked about.** A wrap reads and writes
  one thread's note, one hub line, the `Todo.md` lines step 8 allows and that
  thread's memory pointer. Other threads are not read, judged or refreshed,
  even when something about them looks stale. The one exception is step 12's
  archive, which moves every line ticked before today, whichever thread it
  names: a done line is done, and it is kept in `archive/`.
- **A wrap is not a sweep.** It does not expire, reorder or tidy `Todo.md`
  beyond that archive, audit memories, check other threads, or ingest
  meetings. "Close for the day" wraps the threads that
  changed today and no others.
- **It never crosses zones** unless the user asks, and then only for that
  request. It never commits two zones together.
- **It never guesses a name.** Two candidates means one question.
- **It never pushes, sends or shares.** Everything it does stays on the machine
  and can be undone from git.
- **It never edits `raw/`**, and never writes status into `System/context.md`
  or into a memory pointer. A correction that reaches a raw record marks the
  page resting on it instead.
- **It changes the layout only through the scaffolding script.** Zones,
  projects and threads come from `scaffold.py`, and nowhere else: never a
  folder made or copied by hand.
