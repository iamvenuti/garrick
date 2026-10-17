---
name: threads
description: >
  Open, list, wrap, hold, park, finish and create work threads, and add
  zones, by voice or typed. The procedure behind the spoken commands in
  System/rules.md. Use when the user says "open X", "pick up X", "resume X",
  "where was I on X", "where am I", "what's open", "what's open in Work",
  "what's next", "what should I do while I wait",
  "I'm being interrupted", "hold this", "hold X", "back", "where was I",
  "back to X",
  "close X", "wrap X", "wrap it", "wrap up", "wrap this", "save where I am",
  "close for the day", "I'm done for today", "finish X", "X is done", "close
  X for good", "park X", "put X aside", "wake X", "unpark X", "what's
  parked", "is there a thread on X", "find X", "new project X for Acme", "new
  thread X in Acme", "start a thread on X", "rename X to Y", "delete X", "add
  a zone called X", or "new zone X".
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
   to the Aliases table once the user answers. Re-read `System/context.md`
   right before editing it.

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

Not a clock, not every turn, and not because the user asked: "wrap it" and
"hold this" stay their commands. Write it at the end of the turn where the
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
that checkpoints are not available here, and that "wrap it" or "hold this"
before leaving is what saves the place.

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
turn runs, from the same script, so the answer here is the band's first pick:

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
status page can switch off or move: the top of the interruption stack (only
with the status extra, which keeps it), Todo lines due today or late with a
reply or a chase first, chases that have come due, what waits in an Inbox, a
parked thread left alone for 30 days ("park or finish?"), and a live thread
not wrapped for 14 ("wrap?"). It never offers the thread in focus. It covers
every zone unless *Same zone only* is switched on there.

Spoken: the pick and the offer. "Reply on the renewal dates, in Birch, due
today. Want me to open it?"

Written: the first pick's line, then the next two, each on its own line.

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

## Wrap: "close X", "wrap X"

Wrapping makes the thread resumable cold, by anyone, months from now. One thread
per wrap: the one named, and nothing else.

1. **Resolve X.** When this wrap is part of closing the day (yours, or a
   cmux tab told "Shutting down for the day") and X is on the interruption
   stack, stop here and say it is still held: its block holds what the user
   said when they were cut off, and it stays on the stack.
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
   session, not from the files; `nothing` is a valid answer, and the usual
   one for a thread that is simply waiting. When the user is listening, ask
   for it: "Anything that's only in your head right now?" A block written
   before this row existed is still whole; the row is added at its next wrap.
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
   written to yet holds one, in `<angle brackets>`, to show the shape; delete
   it in the same edit that writes the first real line. It is a task like any
   other, so anything that counts open actions counts it.
   Tick the lines this session finished, whether they name this thread or
   only a party or person. Touch no line that names another thread.
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
    else: no status, no date, no summary.
    ```
    Acme, Pricing (Work zone). Resume from
    Zones/Work/Acme/Threads/Pricing/Pricing.md, the Resume here block. Read it
    before anything else in the thread.
    ```
    Create it if missing, leave it if present. No memory, no step.
12. **Commit in the zone's repository.** Stage by name only what this wrap
    touched and this thread's own changed files: the thread folder, the hub if
    edited, `Todo.md` if edited, and any `Deliverables/` or `Sources/` file this
    session made for the thread. Never `git add -A`.
    ```sh
    git -C "Zones/<Zone>" log -1 --format='%h %an %s'   # did someone commit meanwhile?
    git -C "Zones/<Zone>" add -- "<path>" "<path>"
    git -C "Zones/<Zone>" diff --cached --stat          # only what you meant
    git -C "Zones/<Zone>" commit -m "Acme, Pricing: second draft sent; waiting on Dana's volumes"
    ```
    The message says what changed. One zone per commit. Never push: that leaves
    the machine and needs the user's yes.
13. **Take it off the interruption stack** with `unstack`: a wrapped thread
    is not waiting for "back". Not on it, nothing changes.

Spoken: "Acme pricing wrapped. Next is the second draft once Dana sends
volumes, due Friday." Add a third sentence only for something the user must
know: a wall held material back, a meeting page was unfinished, a commit
failed.

Written: the same, plus the files changed and the commit hash.

## Interrupted: "I'm being interrupted", "hold this", "hold X"

Something has cut in, and the user has to leave the thread mid-thought.
Someone is usually waiting, so the whole thing takes under thirty seconds:
three short answers, one write, one sentence back. Skip everything else a
wrap does.

1. **Resolve X.** "Hold this" or no name at all: the thread in focus, as
   under *No name given*.
2. **Ask three questions, one at a time**, each answered in one line:
   "Where are you, exactly?", "What's the very next step?", then "Anything
   only in your head?" The third can be skipped: "no", "skip" or silence
   leaves it out. Take each answer as said, and never ask a follow-up. An
   answer the user gave already ("hold this, I'm on row 14") is not asked
   again. When they say what cut in ("the Birch renewal call"), keep it as
   *by*.
3. **Save it**, through the status page's `page_action.py`:
   ```sh
   python3 System/status/page_action.py --workspace . <<'EOF'
   {"verb": "interrupt", "zone": "Work", "project": "Acme", "thread": "Pricing", "where": "<answer>", "next": "<answer>", "keep": "<answer, or leave the key out>", "by": "<what cut in, or leave the key out>"}
   EOF
   ```
   It overwrites the *Where it stands* line with `**Interrupted 14:32, 13
   October 2026.** <where>`, sets the `Next action` and `Keep in mind` rows
   (a skipped Keep in mind stays as it was, or says `nothing` where the
   row was missing), leaves the other rows alone, sets `updated:`, adds the
   dated entry "Interrupted at 14:32, by <by>.", commits in the zone, and
   puts the thread on top of the interruption stack (below). A checkpoint
   under the block is rebased onto what was just written, its items and its
   time untouched, so a hold never makes one stale. The thread
   stays `status: active`: an interruption is not parking. When the zone's
   wall check refuses the commit, nothing is written; say so.
   **Without the status page extra** (no `System/status/page_action.py`),
   make the same edit by hand and commit it as Wrap step 12 does. There is
   no stack then, so "back" offers the most recent thread instead.
4. **Reply in one sentence**: "Acme pricing held. Say back when you're
   done." If what cut in is a thread of its own ("Birch renewal"), offer to
   open it: "Open Birch renewal?"

## Back: "back", "where was I", "back to X"

1. **Which thread.** "Back" or "where was I", with no thread named: the top
   of the stack. "Back to X": resolve X; it comes out of the stack wherever
   it is, and the rest stay in order. "Where was I on X" names a thread, so
   it is Open, not Back.
2. **Take it off the stack:**
   ```sh
   python3 System/status/page_action.py --workspace . <<'EOF'
   {"verb": "back"}
   EOF
   ```
   or with `"zone"`, `"project"` and `"thread"` for "back to X". The reply
   gives the thread's `name`, its note's `path`, the three saved lines
   (`where`, `next`, `keep`) and how many are still held (`left`). It writes
   nothing.
3. **Open it as Open does.** Where the `desk` skill is installed, that is its
   tab: `desk open "<the thread's folder>" --prompt "open <short name>"`, and
   the session there answers. Otherwise it is the thread in focus here.
4. **Read the three lines back**, as the context to carry on from: where the
   user was, the next step, and Keep in mind when it says more than nothing.
   Where the reply carries a `checkpoint`, add one clause: "There's also an
   unwrapped checkpoint from 14:32." Then name the next one still held, if
   any.

Spoken: "Back to Acme pricing. You were halfway through the tier-two volumes,
and next is row 14. You weren't sure about the tier-two rate. Birch launch is
still held."

**Nothing on the stack:** say so in one line, and offer the most recent live
thread, which the reply names as `offer` (without the status page extra,
the first line of the listing under *Where things are*): "Nothing's held. The last thread
you worked on is Acme pricing. Open it?" Never answer with silence: it reads
as a fault. **X is not on the stack:** treat "back to X" as "open X".

## The interruption stack

The threads held and not yet come back to, across zones, last in, first out,
because interruptions nest: finish C, back to B, then A. It is
`System/generated/interrupted.json`, kept by `page_action.py` and never
committed: what each thread was doing is in its note, so losing the file
loses only the order. A thread held again moves to the top, never twice.
`{"verb": "stack"}` lists it, top first, and changes nothing;
`{"verb": "unstack", "zone", "project", "thread"}` takes a thread off without
reading it back, or with no thread, every thread of the project. The stack is
not a to-do list, and nothing from it goes into `Todo.md`.

Wrapping, parking, finishing or deleting a thread takes it off; each of
those sections says at which step. Without the status page extra there is no stack, and those
steps fall away.

## Close for the day: "close for the day", "I'm done for today"

Wrap every thread worked on today, then give one summary.

1. **Find today's threads.** For each zone folder under `Zones/` (skip one
   whose name starts with `_`):
   ```sh
   git -C "Zones/<Zone>" log --since=midnight --name-only --format=
   git -C "Zones/<Zone>" status --porcelain --untracked-files=all
   ```
   The first lists files committed today, the second files changed and not yet
   committed (drop the two status characters and the space; strip the double
   quotes git puts round a path with spaces, as every dated deliverable has;
   for a rename, take the path after `->`). Map each path, which is relative
   to the zone:
   - `<Project>/Threads/<Thread>/…` → that thread;
   - `<Project>/<Project>.md`, `<Project>/Deliverables/…`, `<Project>/Sources/…`
     → the project's live thread if it has one; if it has several, ask which,
     once, for all such files together;
   - `Todo.md` → no thread;
   - a path through a folder whose name starts with `_` → not part of the
     work; ignore it.

   Add any thread this conversation worked on that left no file behind. Skip
   threads marked done or parked: neither is live, and a wrap would rewrite
   what finishing or parking left in place. Skip a thread on the
   interruption stack (`stack`): its block holds what the user said when
   they were cut off, and a reconstruction would overwrite it. Skip a thread already wrapped in
   this session with nothing changed since that wrap; name it in the summary
   as already wrapped.

   A zone that is not a git repository: fall back to
   `find "Zones/<Zone>" -type f -newermt "$(date +%Y-%m-%d)"`, and say that is
   where the list came from.
2. **Say the list before wrapping**, in one line: "Three today: Acme pricing,
   Birch launch plan, roof repair. Wrapping them." Go ahead unless the user
   stops you.
3. **Wrap each thread** as above, one at a time, one commit per thread.
   For a thread this session did not work on, the day's changes are the only
   evidence. Write what they show and nothing more: no decisions, no status the
   files do not bear out. Mark the dated entry "reconstructed from the day's
   changes". Where the evidence is too thin to rewrite the Resume here block
   truthfully, add the dated entry listing what changed, leave the block as it
   is, and say so. If another session is still open on a thread, that session
   should wrap it; tell the user.
4. **One summary**, ending with what is still on the interruption stack,
   top first. It stays there: closing the day does not empty it, and those
   are the threads to come back to first.

Spoken, three sentences at most: "Wrapped three: Acme pricing, Birch launch plan
and roof repair. First thing tomorrow is the Acme second draft, due Friday.
Still held: supplier audit."

Written: one line per thread (short name, next action, commit hash), then
anything that failed or was held back, then the stack, one line per thread.

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
   them. Do not decide for the user.
8. **Last thread in the project?** Ask whether the project is finished too. If
   yes, set `status: done` in the hub.
9. **Delete the memory pointer**, if there is one. A pointer that outlives its
   thread keeps announcing work that no longer exists.
10. **Commit** in the zone's repository: "Acme, Pricing: finished; outcome
   recorded".
11. **Take it off the interruption stack** with `unstack`.

Spoken: "Acme pricing is closed. Two actions still point at it: tick them, keep
them, or drop them?"

Written: the outcome paragraph, the files changed, the commit hash.

## Park: "park X", "put X aside"; wake: "wake X", "unpark X"

Parking sets a thread aside without finishing it, so the lists stay short. It
moves nothing: the folder, the Resume here block, the links and the history
stay exactly where they are.

1. **Resolve X.** Parked threads resolve like any other.
2. **Run the scaffolding script**, from the workspace root. It sets
   `status: parked`, or `status: active` for `wake`, and `updated:` today,
   adds the dated entry, "Parked." or "Woken.", and leaves the Resume here
   block as it is: it still says where the work stood.
   ```sh
   python3 System/tools/scaffold.py park --zone Work --project Acme --thread Pricing
   ```
   It writes that one note and commits nothing. A thread already set aside,
   or an active one asked to wake, is refused in one line and nothing is
   written, so read what it says rather than running it twice.
3. **If the user gave a reason**, add it to that dated entry.
4. **Commit** in the zone's repository: "Acme, Pricing: parked".
5. **Keep the memory pointer**, if there is one. A parked thread is not
   finished. **A checkpoint is kept too**, exactly as it is: parking sets work
   aside, and what the last session recorded is part of where it stood. The
   check says nothing about it while the thread is parked, and waking the
   thread brings it back to be read and wrapped.
6. **Parking takes it off the interruption stack**: run `unstack`. Waking
   puts nothing back.

**When X is a whole project** ("park Acme", where Acme has threads), leave
`--thread` out: the script parks the hub note, with the dated entry under its
`## State of play` if it has one, and the commit is "Acme: parked". Its thread
notes are left alone: every thread in it counts as parked while the hub says
so, and waking the project brings back exactly what was live before. `unstack`
with the project alone takes all its threads off the stack. If X could be
the project or one of its threads, ask which.

Spoken: "Acme pricing is parked. Say wake Acme pricing to bring it back."

Written: the same, then the note's path and the commit hash.

## New: "new project X for P in Z", "new thread X in P"

Creation goes through the scaffolding script, which checks names. Run it from
the workspace root.

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
   whether a wall applies: "Birch isn't a party yet. Add it to the Work zone,
   and should anyone be walled off from it?" With the answer, re-read
   `System/context.md`, then run
   `python3 System/tools/scaffold.py party --name "<Party>" --zone <Zone> --what "<what it is>"`,
   which writes the row and offers the tag itself, with `--walled-from <tag>`
   for a wall; commit `System/context.md` on its own before the project, which
   is refused until the row is there. Never scaffold with a made-up tag. Where
   the user did not ask for a project at all but for help with a piece of work,
   the short route sets up the party, the project and the thread on one
   question instead: the `meetings` skill's *Nothing there yet*.
4. **Run the script.** When it refuses, it prints a one-line reason. Relay it
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
6. **Commit**, if the script has not: check
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

The scaffolding script renames, so the folder, the note and every link to it
in the zone move together, in one commit:

```sh
python3 System/tools/scaffold.py rename --zone <Zone> --project "<Project>" [--thread "<Thread>"] --to "<New name>"
```

1. **Resolve X.** If it could be the project or one of its threads, ask which.
2. **One match goes ahead**, and the reply says what moved: the instruction
   named it, so do not ask it back. A name close to one that already exists
   may mean that one: ask, naming it.
3. **Run the script.** It refuses a name that will not work, that sounds
   like a sibling or is taken, and a rename while the files it would change
   have changes not committed, or while a session is mid-turn there; relay
   the reason as under *New*. It moves the folder and the note with git,
   renames the title and heading, rewrites every link to it in the zone (the
   hub's list, `Todo.md`, `project:` frontmatter, the notes between) and adds
   the dated entry "Renamed from <old>.", all in one commit in the zone. It
   adds the old name as a heard alias in `System/context.md`: commit that in
   the workspace root's repository.
4. **The memory pointer**, if you keep one: point it at the new note.
5. What it lists and leaves alone, mentions in the Meetings wiki, say once.

When the thread, or a thread of the project, is on the interruption stack,
run the rename through `page_action.py` instead, `{"verb": "rename", "zone",
"project", "thread", "to"}`: it runs this same script and moves the entry on
the stack to the new name, where it keeps its place.

Moving a thread to another project or zone is not a rename: it crosses
parties and walls. Say so, and stop.

Spoken: "Pricing is Renewal now, and its links follow. The old name still
finds it."

Written: the script's report, and the commit hash.

## Delete: "delete X"

For what should never have existed: a duplicate, a test, a thread opened in
the wrong project. Real work is finished or parked, never deleted: offer those
first.

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
5. **Take it off the interruption stack** with `unstack`, every thread of
   the project when it was a project.

Spoken: "Deleted the test thread and its one open action. Say undo to bring
it back." On undo, `python3 System/tools/scaffold.py undo --zone <Zone>
--commit <commit>`, which refuses once anything else has been committed in
the zone. A rename is undone the same way.

Written: the script's report, and the commit hash.

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
link to a walled meeting, the name of a party, person or alias on the far
side of a wall, or eight words in a row lifted from a walled meeting page,
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
  one thread's note, one hub line, the `Todo.md` lines step 7 allows and that
  thread's memory pointer. Other threads are not read, judged or refreshed,
  even when something about them looks stale.
- **A wrap is not a sweep.** It does not tidy `Todo.md`, audit memories, check
  other threads, or ingest meetings. "Close for the day" wraps the threads that
  changed today and no others.
- **It never crosses zones** unless the user asks, and then only for that
  request. It never commits two zones together.
- **It never guesses a name.** Two candidates means one question.
- **It never pushes, sends or shares.** Everything it does stays on the machine
  and can be undone from git.
- **It never edits `raw/`**, and never writes status into `System/context.md`
  or into a memory pointer.
- **It changes the layout only through the scaffolding script.** Zones,
  projects and threads come from `scaffold.py`, and nowhere else: never a
  folder made or copied by hand.
