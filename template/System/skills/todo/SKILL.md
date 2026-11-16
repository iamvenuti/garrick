---
name: todo
description: >
  Keep each zone's Todo.md complete and short. Sweeps the actions the records
  hold but the list does not (Meetings pages, each live thread's Next action)
  into its Inbox, folds repeats into the line already there, then expires what
  nobody triaged, archives what is done and tidies the rest. Use when the user
  says "sweep my actions", "sweep the todo list", "tidy my todo list", "what
  do I owe people", or "what am I waiting on". Also Distil, which the wrap and
  the meetings skill run for one thread, and "apply the todo proposals". The
  jobs extra can run the sweep nightly.
---

# Todo

An action reaches a zone's `Todo.md` only when a skill writes it: the
`meetings` skill when it files a call, the `threads` skill at a wrap. Nothing
goes back over the records afterwards, and nothing takes a line off but a
tick. So an action filed by hand never arrives, a commitment that comes up at
every call arrives five times, and an Inbox nobody reads grows until the good
lines are lost among the weak. This skill closes those three gaps, one zone at
a time. The list's own header says how a line is written; this skill writes
to that, and never against it.

## Where things are

| What | Where |
|---|---|
| The list, per zone | `Zones/<Zone>/Todo.md` |
| When each Inbox and Waiting on line was first seen | `Zones/<Zone>/.todo-seen.json`, never committed |
| What expired, still open | `Zones/<Zone>/archive/Todo-expired-<YYYY>.md` |
| What was done | `Zones/<Zone>/archive/Todo-<YYYY>.md` |
| Changes proposed to lines the user moved, never committed | `Zones/<Zone>/.todo-proposals.json` |
| The script for the steps that need no reading | `System/skills/todo/todo.py` |

A project about the workspace itself lives in `System/`, in no zone, so it
has no list of its own. Its actions go in the `Todo.md` of the zone the user
works from most, each opening with its thread's link, as
`- [ ] [[Setup]]: rotate the backup key`. Where a zone's list already holds
lines for that project, keep to that zone; otherwise ask which, once. The
check and the status page find the thread in `System/`.

## Sweep: "sweep my actions"

1. **Which zone.** The one named, or the one the session is in. Never two in
   one pass: each zone is its own list and its own repository.
2. **Re-read `Todo.md` now.** Another session may be writing to it.
3. **Read what may hold actions**, in this zone only:
   - the Meetings pages whose `zone` is this one, from the last 30 days
     (`Wikis/Meetings/wiki/sources/`), each one's actions table;
   - each live thread's `Next action` row, in its Resume here block. Never
     the `### Checkpoint` block beside it: what is in there is unconfirmed,
     including its own next action and its To file lines, and the wrap that
     folds it in is what files them.
4. **Keep only what someone can act on**: one named owner and a concrete
   verb. A row owned by "the team" or by nobody, or one that restates a
   decision, stays on its page.
   - The user owns it: a line for `## Inbox`.
   - A named person owes the user something: a line for `## Waiting on`,
     with `#waiting` and `⏳` a day to chase (a week out when the page
     gives none, or the days `todo-chase-days` in `System/garrick-checks.json`
     sets; `0` writes none, and the line waits for the user's own).
5. **Fold repeats.** Before adding a line, compare it with every open line,
   the lines ticked in the last 14 days and the rest of this batch, by the
   test Distil uses (*One line, one commitment*, below): two lines are the
   same commitment when they share the thread, the person and the deliverable,
   whatever the wording. The sweep adds only what neither caller wrote: a
   step that belongs to a line already open is folded, never a line of its own. A match is not added: the source goes on
   the line already there, as `(also in [<short title>](../../Wikis/Meetings/wiki/sources/<slug>.md))`,
   the link `ingest.py link` prints (the `meetings` skill's step 8), and that
   is the only change this skill makes to an existing line. A source is a
   relative link to the page's file, never an `obsidian:` link; one
   written before as `[[<slug>]]` or `obsidian:` stays as it is.
6. **Append only, and only under `## Inbox`** (and `## Waiting on` for step
   4's second kind), each line opening with its thread as the `meetings`
   skill's step 8 says. A line the user moved to another section is never
   reworded, moved or ticked.
   **The example line goes with the first real action.** A list nobody has
   written to yet may hold one, in `<angle brackets>`, to show the shape; delete
   it in the same edit that writes the first real line. It is a task like any
   other, so anything that counts open actions counts it, and `check.py`
   warns while a real action and the example sit in one list.
7. **Expire, archive, tidy**:
   ```sh
   python3 System/skills/todo/todo.py all --zone <Zone>
   ```
   It moves Inbox lines nobody triaged in 14 days (or the days the zone sets
   as `todo-expire-days` in `System/garrick-checks.json`), and `Waiting on`
   lines left as long with no day to chase, to the expired archive,
   still open, so any can be pasted back: a relative source link in a
   moved line is written again from `archive/`, so it still leads to its
   page, and a line pasted back into `Todo.md` takes one `../` off it; moves lines ticked before today to the
   year's archive; and moves dates written mid-line to the end, keeping the
   Inbox in thread order: each thread where it first appears, or by the
   thread's name when `todo-inbox-order` is `thread`.
8. **Commit**, in the zone's repository, `Todo.md` and `archive/` by name:
   ```sh
   git -C "Zones/<Zone>" add -- Todo.md archive/
   git -C "Zones/<Zone>" commit -m "<Zone>: actions swept; 3 added, 2 folded, 4 expired"
   ```
   The wall check runs on it as on every commit in the zone.

Spoken: "Work's list: three new actions from this week's calls, two repeats
folded, four old ones set aside. Nothing is due today." Written: each added
line, each fold, and the counts.

## Tick, reopen, date or add one line: "tick X", "that's done"

A single line is not a sweep. Where `System/status/page_action.py` exists
(the status page is installed), change it through that and edit nothing by
hand: the same code the page's buttons and the Ask box run, so the edit, the
commit with the wall check and the page's rebuild happen the same way
wherever the request started.

```sh
python3 System/status/page_action.py todo-done --zone <Zone> --line "<the line's text, or enough of it to be the only one>"
python3 System/status/page_action.py todo-undo --zone <Zone> --line "<text>"
python3 System/status/page_action.py todo-date --zone <Zone> --line "<text>" --date <YYYY-MM-DD, or ->
python3 System/status/page_action.py todo-add  --zone <Zone> --text "<action>" [--target "<Project>/<Thread>"] [--date <YYYY-MM-DD>]
```

Two more change a line's words or take it off the list, and Distil uses them:

```sh
python3 System/status/page_action.py todo-edit   --zone <Zone> --line "<text>" --text "<the whole new description>"
python3 System/status/page_action.py todo-retire --zone <Zone> --line "<text>" --reason "[<short title>](<link>)"
```

`todo-edit` keeps the line's thread, tags, sources and dates, and refuses words
another open line of the thread already has. `todo-retire` moves the line, still
open, to the expired archive with `superseded by` and the source at the end; it
deletes nothing. Each is one commit through the wall check, as a tick is.

The executor commits the whole `Todo.md`. A hand edit of your own still
waiting in it would go into that commit under the tick's message, so before
the call run `git -C "Zones/<Zone>" status --porcelain -- Todo.md`: if it lists
the file, commit your edit first (stage by name), or make the call first and
the edit after.

It prints one sentence. A line that is not there, or that two lines say, is
refused in one line and nothing is written: give more of the line. `todo-undo`
reopens a line ticked today. Without the status page, edit the line by hand as
the header says and commit `Todo.md` with the wall check, as a sweep does in
step 8. A sweep itself (steps 1 to 8) is unchanged, and keeps writing by hand:
it is many lines and one commit, and the page picks it up at the next rebuild.

## Distil: one thread, after a wrap or a filed meeting

The `threads` skill's wrap (step 8) and the `meetings` skill (step 8) run this
in place of appending. It takes **one thread**, its open lines in `Todo.md`,
and the new material: the session, or the filed meeting page. It answers four
questions, in this order.

1. **What is now done?** Tick it. A meeting that settled something ticks its
   line, and the run report names the page as the reason.
2. **What changed?** When the material changes a line's scope, date or person,
   rewrite that line. Never add a second line for the same commitment. The
   line keeps its sources and gains the new one.
3. **What is new?** Add a line only for a new commitment. A step towards a
   commitment already listed folds into that line's text, or goes in the
   thread note.
4. **What no longer holds?** A line the material drops or replaces moves to
   `archive/Todo-expired-<YYYY>.md`, still open, with `superseded by [<short
   title>](…)` at the end. Nothing is deleted, and it can be pasted back as
   any expired line can.

### One line, one commitment

- **One line is something a named person will check was done, or a
  deliverable the user owes.** The steps of one deliverable are one line:
  "Bring the price list structure and the royalty framework to the 20
  November call", not three preparation lines.
- **The same commitment** is the test the sweep's fold uses too: the same
  thread, the same person, the same deliverable, whatever the wording.
- **A task of a few minutes gets a line only when someone waits on it and a
  date is set.** Otherwise it folds into a larger line, or stays on the
  meeting page.
- **`Waiting on` only when it blocks a line of the user's.** The line names
  that line's commitment (` — blocks: <its words>`). Other promises stay on the
  meeting page, where `meeting-prep` finds them.
- **A soft cap of five open lines per thread** (`todo-thread-cap` in
  `System/garrick-checks.json`, `0` for none, a number or one per zone).
  Above it, merge before you add, and say so in the report. The cap warns; it
  never drops a line.

### Who may change what

- **`## Inbox` lines of this thread:** Distil applies all four answers itself.
- **Lines the user moved to another section:** Distil proposes. In an attended
  wrap or filing, show each change as a before and after and apply it on the
  user's yes. In a run with nobody to ask (the nightly intake, any headless
  run), the proposal goes to `Zones/<Zone>/.todo-proposals.json`, never
  committed, the line stays as it is, and the zone's digest lists it under
  *Proposed changes*.
- **Lines of another thread:** never. Not read for a change, not reworded, not
  ticked, not retired.
- **Choosing a line's section or date** stays the user's. Distil writes a date
  only when the material gives one.

### The steps

1. Re-read `Todo.md`. Name the thread plainly: the one the user names, or the
   only live thread of the only project whose `party` is among the page's
   parties, as the filing step says. When the material names no thread
   plainly, there is no thread: Distil writes as the append did, opening the
   line with `<Party>: `, and changes no other line.
2. List the thread's open lines (`## Inbox` and the others, by its link).
   Answer the four questions from the new material against them. Write the
   answers as JSON:
   ```json
   {"thread": "Pricing", "name": "Acme, pricing",
    "source": "[<short title>](../../Wikis/Meetings/wiki/sources/<slug>.md)",
    "done": ["<words of a line>"],
    "changed": [{"line": "<words>", "text": "<the whole new description>", "merge": false}],
    "new": [{"text": "<action>", "date": "YYYY-MM-DD", "waiting": false, "blocks": "<words of the user's line it blocks>"}],
    "retired": [{"line": "<words>", "reason": "<source link, else the call's source>"}]}
   ```
   `thread` is the link label as step 8 writes it (`Pricing`, or
   `Acme/Threads/Pricing/Pricing|Pricing` when two projects share a name); with
   no thread, give `"party"` instead. `merge: true` marks a rewrite that folds
   a step into a line, so the report counts it as merged.
3. **Attended, show before you apply.** Run it as a dry run first, show the
   user the before and after of every line they moved, and wait for the yes:
   ```sh
   python3 System/skills/todo/todo.py distil --zone <Zone> --changes plan.json --dry-run
   ```
   A dry run writes nothing. Inbox lines need no yes.
4. **Apply.** Add `--yes` only when the user has said yes to the moved lines
   shown; without it, or in a headless run (`GARRICK_HEADLESS=1`, with or
   without `--yes`), a moved line is proposed and never changed:
   ```sh
   python3 System/skills/todo/todo.py distil --zone <Zone> --changes plan.json [--yes]
   ```
   It edits `Todo.md` and `archive/` and leaves the commit to the caller,
   whose commit already names both (the wrap's step 12, the meetings skill's
   step 9). It prints the spoken report and any line it could not place: a
   line that no open line of the thread says, or that two say, is skipped and
   named, never guessed.
5. **Report in the counts**, spoken as the script says it: "Distilled Acme,
   pricing: one added, two merged, one retired." When the thread is over its
   cap, say that you merged before adding.

### "Apply the todo proposals"

```sh
python3 System/skills/todo/todo.py proposals --zone <Zone>
```

lists what waits, each as its line and what would change, and marks one whose
line has gone. Show the list. On the user's yes, apply each through
`page_action.py` (`todo-edit`, `todo-retire` or `todo-done`, above), so each is
one commit with the wall check, then take it off the list:

```sh
python3 System/skills/todo/todo.py proposals --zone <Zone> --drop <id>
```

A proposal the user declines is dropped the same way. Without the status page,
edit the line by hand as its header says, commit `Todo.md` and `archive/` with
the wall check, and drop the proposal.

## "What do I owe people", "what am I waiting on"

Read the zone's `Todo.md` and answer from it: the open `## Inbox` and
`## This week` lines for what the user owes, by person or thread; the
`## Waiting on` lines, oldest chase date first, for what others owe. Offer a
sweep when the list was last swept more than a week ago.

## Listening mode

As the `threads` skill's: the answer first, three sentences at most, no
paths, round numbers.

## What this skill does not do

- **It never reads another zone's pages** for this zone's list, and never
  writes one zone's actions into another's.
- **It never rewords, moves or ticks a line the user has triaged**, except as
  Distil allows: on the user's yes, in a session they are in.
- **It never writes a record.** A line is an action someone still has to
  take. Never add a line for work that is already done. Tick a line as it
  was written, `[x]` and its `✅` date and nothing more; the outcome goes in
  the thread note's dated entry, not on the line. `check.py` warns about a
  ticked line the zone's history never held open, about a line longer than
  200 characters, about a thread over its cap, and about a `Waiting on` line
  that names no open line of the user's in its thread.
- **It never deletes a line**, but for the example line a new list is started
  with, which step 6 takes out with the first real action. Expired and done
  lines go to `archive/`, where they can be read and pasted back.
- **It sends nothing.** A digest on the phone is not this skill's to send.
