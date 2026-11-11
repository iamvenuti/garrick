# Finish, park, wake, new, rename, move, delete and new zone

Read after `SKILL.md`: the dispatcher's *Resolving a name* and *Listening mode* apply. This reference repeats what it depends on: the executor under *Running an action*, and the wall check. Where it says *Wrap*, *Park* or *Open* for another request, that request's steps are in `wrap.md`, `lifecycle.md` or `open.md`.

## The rules behind this request

These are the rules in `System/rules.md` that this request carries out, word for word.

- **The hub is the project's index.** It links every thread: under `## Threads`, or under `## Finished` once it is done.
- **A finished thread** gets `status: done`, and its Resume here block becomes `### Outcome`: what was delivered or decided. The project hub lists it under `## Finished`.
- **A parked thread** gets `status: parked`: set aside, not finished. It keeps its folder, its Resume here block and its links, and drops out of "what's open" until it is woken. **A parked project** has `status: parked` on its hub, and every thread in it is parked with it, whatever its own note says.
- **Names are the names the work already has.** Zones, projects and threads take letters and digits, spaces, hyphens, apostrophes, `&`, and a full stop inside an acronym: Q4 Planning, ISO 27001, Birch & Co. Nothing else, since the rest either cannot be stored as a folder or is a separator the spoken grammar uses, such as the comma in "Acme, pricing". Siblings must not sound alike.
- **A name that does not say how it is said carries a spoken form.** `spoken:` in the note's frontmatter is what is heard for it (Q4 Planning, `spoken: fourth quarter planning`), and a request matches it alongside the name itself. A year standing as a word of its own needs none: Summit 2027 is said "twenty twenty-seven". A zone has no note, so a zone name has to say how it is said.
- **"Finish X" or "X is done"**: close the thread for good (see Threads).
- **"Park X"**: set the thread aside without finishing it. **"Wake X"** or **"unpark X"**: bring it back; so does "open X" on a parked thread. **"What's parked"**: name the parked threads. **"Rename X to Y"** moves the note and every link to it; **"delete X"**, for what should never have existed, lists what would go and acts only on the name said again.
- **Learn the aliases.** When you had to ask what a name meant, add the heard form to the Aliases table, with its Learned cell.
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
moves nothing but the oldest dated entries, which go to history files beside
the note, unchanged (step 2): the folder, the Resume here block and the links
stay exactly where they are.

1. **Resolve X.** Parked threads resolve like any other.
2. **Move the old entries first**, so a parked note is short when it is
   woken. From the workspace root:
   ```sh
   python3 System/tools/history.py apply "Zones/Work/Acme/Threads/Pricing/Pricing.md" --commit "Acme, Pricing: older entries moved to history"
   ```
   It is the wrap's move (*Wrap*, step 12): entries older than `history-months`,
   then the oldest until the note fits `note-max-words`, the newest five kept,
   committed on its own through the wall check. The Resume here block stays as
   it is. A note with nothing to move, or one it cannot read for certain,
   changes nothing: say its line and park anyway. For a whole project, name
   the hub note (`Zones/<Zone>/<Project>/<Project>.md`).
   **Run the executor** (*Running an action*), from the workspace root. It
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
   or zone flags is a change outside the zone: commit it separately in the
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
3. **Run the script.** A move stays inside one zone, so no wall stands in its
   way; a party is an index and decides nothing. It refuses another zone, a thread of that name already in the new project,
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

The wall is between parties, not between the user and their own memory. It
decides what is written into a project, never what the user may know.
