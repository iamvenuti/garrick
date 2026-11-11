# Wrap, checkpoint and close for the day

Read after `SKILL.md`: the dispatcher's *Resolving a name* and *Listening mode* apply. This reference repeats what it depends on: the executor under *Running an action*, and the wall check. Where it says *Wrap*, *Park* or *Open* for another request, that request's steps are in `wrap.md`, `lifecycle.md` or `open.md`.

## The rules behind this request

These are the rules in `System/rules.md` that this request carries out, word for word.

- **Rewrite the Resume here block at the end of any session that produced a decision or a deliverable**, so that it describes now. Add a dated entry below it; keep the old entries.
- **Open actions live in the zone's `Todo.md`.** A thread note says where the work stands; it is not a to-do list, and actions are not copied into it. An action that opens with its thread's link keeps pointing at a live thread: when a thread is renamed, its lines follow. Dates go last on the line, where Obsidian Tasks reads them.
- **A checkpoint is the one exception.** As the work happens, a `### Checkpoint` block under Resume here records what this session made, decided and left half done, unconfirmed and never touching the block above it; its To file lines are held there, unfiled, until the next wrap files them and removes the block. Only a wrap or a finish confirms anything.
- **A deadline nobody gave says so.** The Deadline row reads "not given" where nobody has dated the work, and "none" only where somebody said there is none.
- **If your assistant has a memory of its own**, keep one entry per live or parked thread that says where its resume point is, and nothing else, with its `source:` and `created:`. No status: the note has it. Delete the entry when the thread is finished.
- **"I'm being interrupted"**, **"hold this"** and **"hold X"** run the wrap, as "wrap it" does.
- **"Close X" or "wrap X"**, or **"wrap it"** for the thread in hand: rewrite its Resume here block and add the dated entry. **"Close for the day"**: every session used today wraps its own thread, one at a time.
- **Deliverables carry the date they were first made**: `YYMMDD - <name>.<ext>`. The date never moves, so a folder sorts by when the work started. Build intermediates (`build/`, `render/`, `specs/`), scripts and a folder's `README.md` are not deliverables and keep their names.

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

## Wrap: "close X", "wrap X", "I'm being interrupted", "hold this", "hold X"

Wrapping makes the thread resumable cold, by anyone, months from now. It is
the one way to save a thread's place: "wrap it", the band's *Wrap*, and the
spoken "I'm being interrupted", "hold this" and "hold X" all run it. One
thread per wrap: the one named, and nothing else.

**How it runs.** Resolve X first ("hold this" or no name at all: the thread in
focus, as under *No name given*). Then:

- **Ask nothing.** The wrap starts at once, with no question first. What the
   user said with the request ("hold this, I was leaning towards the lower
   tier") goes into *Keep in mind* as said; with nothing said, *Keep in mind*
   is written from the session, or `nothing`. When the wrap is part of closing
   the day, or for the band's *Close*, which waits for the note before it ends
   the session, do not run in the background: the wrap runs in the foreground,
   each thread in turn.
- **Take the lock**, unless the request says the band has taken it already,
   so a second wrap of this thread cannot start while one is running, and so
   the band can show it:
   ```sh
   python3 System/tools/wrap_lock.py start "Zones/<Zone>/<Project>/Threads/<Thread>/<Thread>.md"
   ```
   Name the note that holds the Resume here block: the thread note, or the
   hub (`Zones/<Zone>/<Project>/<Project>.md`) for a project that keeps its
   resume point there. The band reads the record of that note.
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
   next, and what the user said with the request, word for word. The brief carries the
   walls too, since a cold run knows none: the project's zone and whether
   it is walled (the Walled column of the Zones table in
   `System/context.md`), and any material in this session that a wall held
   back, named only as "held back" with no content, no party and no subject.
   Tell it to do the wall check (*The wall check*, step 4 above) before it
   writes anything, and to write nothing it cannot place. Tell it to follow the
   steps to the letter, to touch nothing outside this thread, and to end with
   step 13. The foreground run needs none of this: it has the session. Where the assistant has no background run, do the steps yourself,
   in the foreground, as a wrap always was.
- **The last act of the wrap, success or failure,** is step 13: release the
   lock. A wrap that died leaves the lock behind, and it expires by itself.
   Releasing the lock and recording that the wrap finished are two things:
   the record is written only after step 12's commit has succeeded.

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
   session and from what the user said with the request, not from the files; `nothing`
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
   Never edit or compress earlier entries. They are the record. A wrap never
   moves one by hand: step 12 hands the old ones to `history.py`, which moves
   them whole.
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
12. **Commit in the zone's repository.** First keep the note short. Run
    the history mover on the note the wrap wrote, after the new dated entry
    and `updated:` are in:
    ```sh
    python3 System/tools/history.py apply "Zones/<Zone>/<Project>/Threads/<Thread>/<Thread>.md"
    ```
    It moves each dated entry older than `history-months` (6), and then the
    oldest ones until the note is under `note-max-words` (4,000), to
    `history/<Note> history <YYYY>-Q<n>.md` beside the note, unchanged, and
    leaves one line under the last entry that links them. The newest five
    entries always stay. It checks that every line it removed is in a history
    file before it says it is done, and puts the note back if one is not. It
    changes nothing for a note with nothing to move, and nothing for one it
    cannot read for certain, which it reports in a line: say that line in the
    reply and carry on. The files it wrote go in this wrap's commit below, with
    the thread's own files: the `history/` folder beside the note. Then run
    `python3 System/tools/history.py resume "<note>"`, which prints the
    block's words and the limit as JSON; if it says `"over": true` (the block is
    over `resume-max-words`, 400), offer the shrink in
    one line after the wrap: "The Resume block is 920 words, over its 400.
    Want a shorter one?" On a yes, show the proposed block as a diff before
    writing it: *Where it stands* says now, *Keep in mind* loses what is
    settled or has shipped, a durable fact moves to a working note with a link
    left in its place, and a section that has grown into working material moves
    to a working note with a link. Nothing changes without the yes, and a
    shrink is never run overnight. The dated entry for it says what moved where.
    Then move the lines ticked before today out of the list:
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
    changed files: the thread folder, with its `history/` folder, the hub if
    edited, `Todo.md` if edited or archived, `archive/` when the archive moved a line, and any
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
13. **Release the lock**, whatever happened above. Which call it is depends
    on how step 12 ended. The note is the same as the lock's in the first step,
    hub included.
    - **The commit succeeded:** `end` removes the lock and writes the time the
      wrap finished (`wrap-<note>.done`).
      ```sh
      python3 System/tools/wrap_lock.py end "Zones/<Zone>/<Project>/Threads/<Thread>/<Thread>.md"
      ```
    - **Anything else:** the commit was refused or failed, the wrap stopped
      before it, or it was interrupted. `end --abandon` removes the lock and
      writes no record, and leaves an earlier record as it was.
      ```sh
      python3 System/tools/wrap_lock.py end --abandon "Zones/<Zone>/<Project>/Threads/<Thread>/<Thread>.md"
      ```
    That record, not the note's last write and not the release of the lock, is
    what says a wrap landed: the band and Close read it. A failed wrap leaves
    no new record, so the band still offers Wrap. Never use `end` to clean up
    after a failure, and never take the removal of the lock as proof that the
    wrap succeeded.

Spoken, when the wrap runs in the background: "Acme pricing is being wrapped.
Say back when you're done." When it runs in the foreground, or when the
background wrap reports back: "Acme pricing wrapped. Next is the second draft
once Dana sends volumes, due Friday." Add a third sentence only for something
the user must know: a wall held material back, a meeting page was unfinished,
a commit failed.

Written: the same, plus the files changed and the commit hash.

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
   - **Peer sessions outside cmux**, a desktop app's included, where this
     assistant can list its peer sessions and send one a message. A peer
     whose session id is already on the list is the same session. A peer list
     can leave out cmux tabs, so it is never the only source.
   - **Sessions of an app with no channel** to ask them: listed, not reached,
     by folder, from the app's own session files where `docs/extras/cmux.md`
     names them. Keep those whose id is not on the list already.
   - **This session**, if it worked on a thread today.
2. **Say the list before asking**, in one line: "Four today: two tabs, one
   app session, this one; one session I cannot reach." Go ahead unless the
   user stops you.
3. **Ask each one to wrap, one at a time**, and wait until its wrap has
   finished before the next, because two wraps at once collide on `Todo.md`
   and the hub. Finished means the wrap lock is gone and
   `System/generated/wrap-<note>.done` is newer than the request.
   - A cmux tab: `desk wrap --session <id> --yes` asks it, waits, and says
     whether the record was written. Exit 3 means the tab was mid-turn or
     waiting on a question: it was typed nothing.
   - A peer session: send it "Wrap it: close for the day, no question; this
     session stays open", then wait for the record.
   - A session that is mid-turn or waiting on a question is skipped and
     named. Do not ask it twice.
   - This session last, as Wrap does it, for the thread it worked on.
   - Skip threads marked done or parked: neither is live, and a wrap would
     rewrite what finishing or parking left in place.
4. **Report one line per session**: wrapped, with its thread and its next
   action (read from the thread note's Resume here block); skipped, with why;
   or not reachable, with its app and folder, so the user wraps it by hand.
   Then anything that failed. A thread with files changed today and no
   session on the list is named, not wrapped from the day's changes: its
   session is the one that knows.

Spoken, three sentences at most: "Wrapped three: Acme pricing, Birch launch
plan and roof repair. One app session in Birch is not reachable; wrap it
there. First thing tomorrow is the Acme second draft, due Friday."

Written: one line per session, as step 4 says.

## The wall check

Run this whenever a wrap, a finish or a new thread would put anything from the
Meetings wiki into a thread note, a hub or a deliverable: quoted, paraphrased,
summarised, counted or linked. Material from earlier in the session counts. The
Knowledge wiki needs no check: it carries nobody's confidence.

1. **The project's zone.** The thread's zone is its folder under `Zones/`.
2. **Each meeting page's frontmatter.** Read `zone`. Missing, unknown or more
   than one: the page is unfinished and stays out. Say that a meeting page is
   missing its zone, and offer to fill it in with the user. `parties` is an
   index and is never asked for.
3. **Zone.** The meeting's `zone` differs from the thread's zone and is a
   walled zone: it stays out, unless the user asked for that meeting in this
   thread in this request. An open zone's pages may be used.
4. **Walls.** A meeting of another walled zone stays out entirely: not quoted, not paraphrased, not summarised, not
   linked, not mentioned as having happened. A wall holds for the whole page,
   even when the other zone said little.
5. **People.** A person page used on its own gets the same check: its zone
   against the project's zone.
6. **What passes** goes in as the least that serves: link the meeting page, and
   quote only where the wording is the point.
7. **Say that a wall held something back, in the words the rule gives, and
   nothing more.** "A wall holds some material back from this project, so I
   have not used it. Nothing was written." No title, date, party, person,
   subject or count, even if asked in the same breath. A question put straight
   to the Meetings wiki ("what did Theo say?") is a different request; its
   answer stays in the conversation and is never written here.
8. **Material the user dictates** into a thread that belongs to another walled
   zone: ask once before writing it. "That sounds like Home material, and Home
   is walled off from Work. Write it anyway?"
9. **Can't tell** whether a wall applies: ask.

**The same check runs again before every commit, whenever git runs the
hook.** Each zone's pre-commit hook runs
`System/tools/check.py --staged --walls-only` on the files being committed. A
link, embed or path to a file of another walled zone, a link to a Meetings
page of another walled zone, or a whole file copied from one, stops the commit, with one line naming the file and the
wall.
When it refuses:

- **Take the material out** of that file and commit again. Tell the user a wall
  held something back, as in step 7, and nothing more.
- **Never commit with `--no-verify`** unless the user explicitly asks for it,
  in this request. Yes once is not yes next time.
- **If the refusal looks wrong** (a link to a file of an open zone,
  say), tell the user which file and which wall, name the command that lets
  that one refusal through once (`python3 System/tools/check.py allow <path>
  <id>`; run without an id it lists them; the report prints that command first), and stop. Only the user
  writes an allowance, in a terminal. Never write
  one yourself, and never touch `System/walls-allowed.json`.

Git skips the hook when its `core.hooksPath` setting sends commits past it,
and then nothing checks the walls at commit time. `check.py` warns when that
is so: tell the user what it says, and until it is fixed treat this
procedure as the only check.

The wall is between zones, not between the user and their own memory. It
decides what is written into a project, never what the user may know.

## What a wrap does not do

- **It never touches a thread it was not asked about.** A wrap reads and writes
  one thread's note, one hub line, the `Todo.md` lines step 8 allows and that
  thread's memory pointer. Other threads are not read, judged or refreshed,
  even when something about them looks stale. The one exception is step 12's
  archive, which moves every line ticked before today, whichever thread it
  names: a done line is done, and it is kept in `archive/`.
- **A wrap is not a sweep.** It does not expire, reorder or tidy `Todo.md`
  beyond that archive, audit memories, check other threads, or ingest
  meetings. "Close for the day" asks each session used
  today to wrap its own thread, and no others.
