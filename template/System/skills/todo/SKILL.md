---
name: todo
description: >
  Keep each zone's Todo.md complete and short. Sweeps the actions the records
  hold but the list does not (Meetings pages, each live thread's Next action)
  into its Inbox, folds repeats into the line already there, then expires what
  nobody triaged, archives what is done and tidies the rest. Use when the user
  says "sweep my actions", "sweep the todo list", "tidy my todo list", "what
  do I owe people", or "what am I waiting on". The jobs extra can run it
  nightly.
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
   the lines ticked in the last 14 days and the rest of this batch. Two lines
   are the same action when they share the thread, the person and the thing
   to deliver, whatever the wording. A match is not added: the source goes on
   the line already there, as `(also in [[<slug>]])`, and that is the only
   change this skill makes to an existing line.
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
   unchanged and still open, so any can be pasted back; moves lines ticked before today to the
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
- **It never rewords, moves or ticks a line the user has triaged.**
- **It never writes a record.** A line is an action someone still has to
  take. Never add a line for work that is already done. Tick a line as it
  was written, `[x]` and its `✅` date and nothing more; the outcome goes in
  the thread note's dated entry, not on the line. `check.py` warns about a
  ticked line the zone's history never held open, and about a line longer
  than 200 characters.
- **It never deletes a line**, but for the example line a new list is started
  with, which step 6 takes out with the first real action. Expired and done
  lines go to `archive/`, where they can be read and pasted back.
- **It sends nothing.** A digest on the phone is not this skill's to send.
