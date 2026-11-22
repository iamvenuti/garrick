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
or make the executor call first and the hand edit after. A wrap's own ticks
never go through this executor: the wrap tool ticks them.

**Check for it first**: `test -f System/status/page_action.py`. Where it is
there, use it for these verbs and do not also run `scaffold.py` or commit by
hand for them: it has done both. Where it is not there (no status page), each
section's steps below are the way, exactly as before: the scaffolding script
and a commit by hand. A wrap is neither: the wrap tool
writes and commits it, as *Wrap* says.

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

**You write the judgment; one command does the rest.** `System/tools/wrap.py`
takes your words as one JSON object and runs every step that needs none, in
order: the lock, the Resume here block, the dated entry, `updated:`, the
checkpoint's removal, the Todo ticks and new lines, the history mover, the
archive of lines ticked on an earlier day, staging by name, one commit in the
zone through its hooks, the finish record and the lock's end. It answers with
a receipt. The steps did not change; only who carries them out. Never do them
by hand, and never run `wrap_lock.py` yourself except as the request says.

Two of those steps are other tools' commands, which the wrap tool runs for you
and you never run for a wrap. The history mover keeps the note short; its
`history/` folder beside the note goes in the wrap's own commit:

```sh
python3 System/tools/history.py apply "Zones/<Zone>/<Project>/Threads/<Thread>/<Thread>.md"
```

The archive moves the lines ticked before today to the zone's `archive/`,
before the commit is staged:

```sh
python3 System/skills/todo/todo.py archive --zone <Zone>
```

**How it runs.** Resolve X first ("hold this" or no name at all: the thread in
focus, as under *No name given*). Then:

- **Ask nothing.** The wrap starts at once, with no question first. What the
   user said with the request ("hold this, I was leaning towards the lower
   tier") goes into *Keep in mind* as said; with nothing said, *Keep in mind*
   is written from the session, or `nothing`. When the wrap is part of closing
   the day, or for the band's *Close*, which waits for the note before it ends
   the session, do not run in the background: the wrap runs in the foreground,
   each thread in turn.
- **The lock is the tool's.** It takes the lock first, so a second wrap of
   this thread cannot start while one is running and the band can show it, and
   releases it last, whatever happened. Where the request says the band has
   taken the lock already, or tells you to take it, send `"lock": "held"`:
   the tool then does not start it, and still releases it. A lock older than
   ten minutes counts as gone.
- **If `System/tools/wrap.py` is not there**, say that the workspace needs an
   update and stop. There is no wrap by hand.
- **In the background**, where the assistant can start a background subagent,
   start one for the work and return to the user at once: "Acme pricing is
   being wrapped. Say back when you're done." Brief the subagent with
   everything the conversation holds that the work needs, since it has not
   seen it: the thread note's path, what this session did and decided, the
   files it touched, the actions to file and the lines to tick, any
   deliverable that left the workspace and who edits it next, and what the
   user said with the request, word for word. The brief carries the walls too,
   since a cold run knows none: the project's zone and whether it is walled
   (the Walled column of the Zones table in `System/context.md`), and any
   material in this session that a wall held back, named only as "held back"
   with no content, no party and no subject. Tell it to do the wall check
   (*The wall check*, below) before it writes anything, and to write nothing
   it cannot place. Tell it to touch nothing outside this thread and to end
   with the call to `wrap.py`. The foreground run needs none of this: it has
   the session.

**What you decide, in order.**

1. **Resolve X** (done above) and stop if the thread is finished or parked:
   say so and offer to open or wake it. The tool refuses one too.
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
   That includes meeting material read earlier in this session. The questions
   are yours and come before the call; the commit runs the same hook as any
   commit, so its verdict is the same.
5. **Fold in the checkpoint**, if the note has one. Read it with
   `{"verb": "checkpoint", "read": true, ...}`, then carry it into the words
   below:
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
   Then send `"checkpoint": "folded"`: the tool removes the block, heading and
   markers, in the same edit and in the same commit as the `Todo.md` lines it files, and refuses a note that holds one when the word
   is missing. A checkpoint the reply calls stale or invalid is read and never
   resumed from: show its items and ask in one line whether any still hold.
   Made and Decided items carry their sources and fold without a question; a
   Next action that differs from the confirmed one is asked about.
   **Read the notes made since the last wrap**: `python3
   System/skills/intake/intake.py notes --project Zones/<Zone>/<Project>
   --thread <Thread>` lists them (a note to yourself, in the thread's
   `Notes/`). Read each, and offer to fold in whatever it settles, in one
   line each; a note stays as it is, and only the user's yes changes the
   Resume here block. When the user settles a note marked `review: pending`,
   delete that line from the note.
6. **Write the Resume here block** so it describes now. It replaces the old
   one; it is not appended to. The input's `resume` holds `stands`, two or
   three sentences on what is done, what is not and whether it is blocked,
   and one line for each of the six rows. The tool writes the heading, the
   date and the table.

   | Row | What it says |
   |---|---|
   | Live artifact | the path, relative to the project, and what it is |
   | Rebuild with | how to make it again, and from what |
   | Next action | the single next thing, small enough to start in two minutes, and whose it is |
   | Keep in mind | what is only in your head: a decision half made and why, a doubt; or `nothing` |
   | Waiting on | who, or `nobody` |
   | Deadline | the date and what breaks if it slips; `none`; or `not given` |

   All six rows, each one line; a row that does not apply says "none" or
   "nobody". **Deadline has a third answer**: "not given", for a thread
   nobody has dated. "None" claims there is no deadline, and nobody said
   that. The next action is one action: "draft the pricing section" fails,
   "open the pricing sheet and fill in the tier-two volume" passes. Anything
   more goes to `Todo.md` (step 8). **Keep in mind** holds what no file can
   tell a cold resume: the decision half made and which way you were leaning
   and why, a doubt about a figure, a thing noticed and not yet acted on.
   Write it from what was said in this session and from what the user said
   with the request, not from the files; `nothing` is a valid answer, and the
   usual one for a thread that is simply waiting. **Rebuild with** earns its
   place: an artifact nobody can regenerate is a dead end the moment it needs
   a change. Every path and link in the block must lead to something that
   exists now; `check.py` warns about one that does not.
   **Keep the block short.** `python3 System/tools/history.py resume "<note>"`
   prints the limit (`resume-max-words`, 400), the `resume-trim` setting and
   the target as JSON. If your block would be over the limit, what happens
   depends on `"trim"`: with `"auto"`, write it at the target, 75% of the
   limit, and say so in the reply; with `"ask"`, the default and what any other
   value counts as, write the block you want and offer the shrink in one line
   after the receipt: "The Resume block is 920 words, over its 400. Want a
   shorter one?" On a yes, show the proposed block as a diff before writing
   it, as a wrap of its own. The rules for a trim: *Where it stands* says now,
   *Keep in mind* loses what is settled or has shipped, a durable fact moves
   to a working note with a link left in its place, the one Next action stays
   word for word, and every boundary, confidence, trap and do-not-rebuild
   warning stays, shortened if it must be. Under `GARRICK_HEADLESS=1` it is
   always `"ask"`, and a shrink is never run overnight.
7. **Write the dated entry**, as `entry`, without its date: the tool puts
   today's date in front and the entry directly below the `---` rule, above
   the earlier entries, so the newest is first. One line on what the session
   did. What was decided and by whom, quoting where the wording was the
   point. What you decided that they did not, marked as yours. What was left
   out on purpose, and why. Never edit or compress earlier entries: they are
   the record. The history mover moves old ones whole.
8. **Decide the actions.** They go to the zone's `Todo.md`, not the note, and
   never an action for work that is already done: `Todo.md` holds what is
   still to do, and what this session did is the dated entry's.
   - **New lines** go in `todo.add`, each written as
     `- [ ] [[<Thread>]]: <action> 📅 <YYYY-MM-DD>`, in the format the list's
     header gives, the dates last (the leading `- [ ] ` may be left out). Open
     the line with this thread's link, or its path,
     `[[<Project>/Threads/<Thread>/<Thread>|<Thread>]]`, when another project
     has a thread of the same name: that is how a later wrap or finish finds
     its lines. A project in `System/` has no list of its own: it is not
     wrapped by this tool yet, so say so and stop.
     **The example line goes with the first real action.** A list nobody has
     written to yet may hold one, in `<angle brackets>`, to show the shape;
     whoever writes the first real action must delete it in the same edit
     that writes the first real line, and the tool does. A line the list
     already says is not added twice.
   - **Ticks** go in `todo.tick`: the words of an open line, enough to be the
     only one that says it. Tick the lines this session finished, whether
     they name this thread or only a party or person. Touch no line that names
     another thread. **Tick a line as it was written; the outcome goes in the
     dated entry, not on the line.** `[ ]` becomes `[x]` and
     `✅ <YYYY-MM-DD>`, today, goes last, as Obsidian Tasks writes it, and
     nothing else on the line changes: "file the drafts" stays "file the
     drafts", and the issue numbers they were filed as go in step 7's entry.
     **Never add a line for work that is already done.** `Todo.md` holds what
     is still to do; what this session did is the dated entry's, where it
     already is. `check.py` warns about a ticked line the zone's history never
     held open, and about a line longer than 200 characters, which the tool
     refuses.
   - **Rewording, merging or retiring** an open line is Distil's (the `todo`
     skill's *Distil*), run for this thread **before** the call: it edits
     `Todo.md` and `archive/` and commits nothing, and the tool's commit takes
     what it changed. Its four questions (what is done, what changed, what is
     new, what no longer holds) decide the lines; say its counts in the reply
     ("Distilled Acme, pricing: one added, two merged, one retired."). A line
     the user moved to another section is changed only on their yes, shown as
     before and after; with nobody to ask it is proposed and left as it is.
     When the session names no thread plainly, Distil writes
     `<Party>: ` first and changes no other line.
   - **A deliverable that left the workspace** in this session, copied to a
     shared folder: ask who edits it next. Colleagues who edit it: the shared
     copy counts from now on (`share`); nobody, or colleagues who only read
     it: the copy here does (`here`). The ledger is not the tool's to write:
     re-read `Deliverables/published.md` (when there is none, copy
     `System/templates/published.md` to it unchanged, and never write the
     explanation yourself: every project's ledger opens with the same shipped
     words, so the wall check reads them as common wording rather than one
     project quoting another), append one row,
     `| YYYY-MM-DD | `<file>` | `<destination>` | <recipients> | share or here |`,
     the destination relative to the folder the hub names in `shared:`, or the
     folder it went into (`Decks/`) when it kept its name, and commit that
     file by name, `git -C "Zones/<Zone>" add -- <path>` and a plain
     `git commit`, **before** the call. A clause may follow `share` or
     `here`, such as who edits it there. Say so in the Live artifact row when
     the shared copy is the one that counts. `python3 System/tools/drift.py`
     compares them from then on. In a thread-first project the ledger is the
     thread's own, `Threads/<Thread>/Deliverables/published.md`.
     **When this machine cannot reach the share.** `python3
     System/tools/machine.py` says the machine's role. When it says `server`
     and the link the hub's `shared:` names, under `Zones/<Zone>/.shared/`,
     does not lead anywhere here, the copy cannot be made from this machine,
     and nothing here reads through the link. Record the `published.md` row
     as above, then add one line to the zone's `Todo.md`, through `todo.add`, for the machine that does reach
     the share, usually the laptop: `[[<Thread>]]: copy `<file>` to
     `<link>/<destination>`, from the machine that reaches the share 📅 <today>`.
     A copy to a share is a send, so it asks first when it is made. Say in
     the Live artifact row that the copy waits. On any other role this
     paragraph does not apply.
     **A copy that stopped counting** in this session is never deleted from the
     ledger: the row is the record of what left. Change its date cell to
     `withdrawn YYYY-MM-DD` when the copy came off the share, or `replaced
     YYYY-MM-DD` when a newer one took its place, the day it happened, and add
     the newer one's row beside it. A file sent by mail rather than placed on
     a share gets a row too, dated `sent YYYY-MM-DD`. drift.py reads such a
     row and never compares it.
9. **The hub's `## Threads` line** changes only if the thread's purpose
   changed. Re-read the hub, change that one line, and commit that file by
   name before the call, as the ledger is.
10. **Memory pointer.** If you, the assistant, keep a memory of your own, send
    `memory`: the path of this thread's entry in your memory folder, and the
    text, which says where its resume point is and nothing else: no status, no
    summary, and it names the note's path, which the tool checks for. The tool
    writes `source:` (the note) and `created:` (today) in its frontmatter, as
    every learned entry's has (*Autonomy* in `System/rules.md`); it creates the
    entry if missing, leaves it if present, and adds the two keys to one that has
    neither. It writes nowhere else: a path that is not an entry file of a
    folder called `memory` or `memories` under the home folder fails the wrap.
    ```
    Acme, Pricing (Work zone). Resume from
    Zones/Work/Acme/Threads/Pricing/Pricing.md, the Resume here block. Read it
    before anything else in the thread.
    ```
    No memory, no key.
11. **Make the one call**, from the workspace root:
    ```sh
    python3 System/tools/wrap.py <<'EOF'
    {"zone": "Work", "project": "Acme", "thread": "Pricing",
     "resume": {"stands": "The second draft is out; Dana's volumes are the only gap.",
                "rows": {"Live artifact": "`Deliverables/260927 - Price sheet.xlsx`, the price sheet",
                         "Rebuild with": "the sizing memo for the numbers",
                         "Next action": "open the price sheet and fill in the tier-two volume",
                         "Keep in mind": "leaning towards the lower tier; not decided",
                         "Waiting on": "Dana, for the volumes",
                         "Deadline": "2026-10-09; the quote lapses"}},
     "entry": "Sent the second draft to Dana. She owes the volumes; the tier-two rate stands as drafted.",
     "todo": {"add": ["[[Pricing]]: fill in the tier-two volume 📅 2026-09-30"], "tick": ["send the second draft"]},
     "checkpoint": "folded",
     "memory": {"path": "<the entry file in your memory folder>", "text": "Acme, Pricing (Work zone). Resume from Zones/Work/Acme/Threads/Pricing/Pricing.md, the Resume here block."},
     "message": "Acme, Pricing: second draft sent; waiting on Dana's volumes"}
    EOF
    ```
    `thread` is left out for a project that keeps its resume point in its hub;
    `todo`, `checkpoint`, `memory` and `lock` are left out when there is
    nothing to say. A key it does not know, or a row missing, fails the wrap
    with nothing written. Add `--json` for the receipt as an object.

**The receipt** is one of four. Say it in the reply, and do the thing it asks.

- **saved**: the commit was made, or there was nothing to commit because the
  note was already current. The finish record is written, the lock is gone.
  Say the next action.
- **refused**, with the zone's hook sentence: the wall check stopped the
  commit. The tool put every file back, so nothing is written. Tell the user a
  wall held something back, as in the wall check's step 7, and nothing more.
  Take the material out of your words and call again. Never commit with
  `--no-verify` unless the user explicitly asks for it, in this request. If
  the refusal looks wrong, tell the user which file and which wall, name
  the command that lets that one refusal through once, and stop (*The wall
  check*, below).
- **conflict**: another session moved the zone's repository, or the note,
  while the wrap ran. Nothing was committed and the files are back as they
  were. Re-read the note, fold in what the other session did, and call again.
- **failed**, with the reason in plain words: nothing was committed. Say what
  failed, in the reply, and stop. Do not do the steps by hand. A wrap that
  failed or was refused releases the lock and writes no finish record, so
  the band still offers *Wrap*.

A wrap killed between its writes and its commit leaves the lock, which
expires after ten minutes, and the files it wrote, which `git status` shows;
`python3 System/tools/wrap_lock.py end --abandon "<note>"` releases the lock
at once.

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
  one thread's note (or its hub), the `Todo.md` lines its input names and that
  thread's memory pointer. Other threads are not read, judged or refreshed,
  even when something about them looks stale. The one exception is the tool's
  archive, which moves every line ticked before today, whichever thread it
  names: a done line is done, and it is kept in `archive/`.
- **A wrap is not a sweep.** It does not expire, reorder or tidy `Todo.md`
  beyond that archive, audit memories, check other threads, or ingest
  meetings. "Close for the day" asks each session used
  today to wrap its own thread, and no others.
