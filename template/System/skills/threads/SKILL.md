---
name: threads
description: >
  Open, list, wrap, finish and create work threads, by voice or typed. The
  procedure behind the spoken commands in System/rules.md. Use when the user
  says "open X", "pick up X", "resume X", "where was I on X", "where am I",
  "what's open", "what's open in Work", "close X", "wrap X", "wrap up", "wrap
  this", "save where I am", "close for the day", "I'm done for today", "finish
  X", "X is done", "close X for good", "park X", "put X aside", "wake X", "what's
  parked", "new project X for Acme", "new thread X in Acme", or "start a thread
  on X". Also use at the end of any session that
  produced a decision or a deliverable, so the thread can be resumed cold.
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
folder are working notes. Any path component starting with `_` (`_zone`,
`_project`, `_thread`) is a template: never list it, open it or wrap it.

A thread is **live** unless its frontmatter says `status: done`.

To list every thread with its status and last update:

```sh
for f in Zones/*/*/Threads/*/*.md; do
  case "$f" in */_*) continue;; esac
  [ "$(basename "$f" .md)" = "$(basename "$(dirname "$f")")" ] || continue
  printf '%s\t%s\t%s\n' "$(grep -m1 '^updated:' "$f" | cut -d' ' -f2)" \
    "$(grep -m1 '^status:' "$f" | cut -d' ' -f2)" "$f"
done | sort -r
```

A zone's own `AGENTS.md` adds to this skill and wins where it says so.

## Resolving a name

Every command that names a thread resolves the name first. Names arrive by
dictation, so resolve before acting, and never guess.

1. **Normalise what was heard.** Ignore case, punctuation, "the", and the words
   "thread" and "project". Treat "and" and "&" as the same.
2. **Look it up in Aliases** (`System/context.md`). A heard form listed there
   means what the table says it means.
3. **Match, in this order, and stop at the first step that finds anything:**
   - a thread name (`pricing` → Acme's Pricing thread);
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
6. **None: say so, and name the nearest live threads.** "No thread called
   roofing. The closest is roof repair, in House."
7. **Learn it.** When you had to ask what a heard name meant, add the heard form
   to the Aliases table once the user answers. Re-read `System/context.md`
   right before editing it.

The **short name** is the one to say back: the thread name alone if no other
thread has it; otherwise "project, thread"; the zone as well only when two
projects share a name.

**No name given** ("wrap this", "wrap up"): use the thread opened in this
session, or the thread whose folder the session started in. If the session
touched several, ask which, naming them.

## Open: "open X"

1. Resolve X.
2. Read that thread's `### Resume here` block. Nothing else: not the hub, not
   the working notes, not the dated entries, unless the user asks.
3. Reply in two sentences: **where it stands**, then **the next action**. Fold
   in who it is waiting on when it is blocked, and the deadline when it is
   close.
4. That thread is now the one in focus for this session: a later "wrap" with no
   name means it.

Spoken: "Acme pricing: the price sheet went to Dana on Tuesday and we're waiting
on her volumes. Next is the second draft once she replies, due Friday the 3rd."

Written: the same two sentences, then the Resume here table as it stands in the
note, and the note's path.

**If the thread is done**, say so with its outcome in one sentence and ask
whether to reopen it. Reopening sets `status: active` and writes a new Resume
here block above the outcome paragraph.

**If the thread is parked**, say so, give where it stood in one sentence, and
ask whether to wake it. Waking is the Park section's second half.

**If X names a zone** ("open Work"), treat it as "what's open in Work".

## List: "where am I", "what's open"

1. List the live threads, most recently updated first (`updated:` in the
   frontmatter; where two tie, the later commit to the note). Parked threads are
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

## Wrap: "close X", "wrap X"

Wrapping makes the thread resumable cold, by anyone, months from now. One thread
per wrap: the one named, and nothing else.

1. **Resolve X.**
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
5. **Rewrite the Resume here block** so it describes now. Replace it; do not
   append to it.
   ```markdown
   ### Resume here

   **Where it stands, 27 September 2026.** <What is done, what is not, whether
   it is blocked. Two or three sentences.>

   | | |
   |---|---|
   | Live artifact | <path, relative to the project, and what it is> |
   | Rebuild with | <how to make it again, and from what> |
   | Next action | <the single next thing, and whose it is> |
   | Waiting on | <who, or nobody> |
   | Deadline | <date, and what breaks if it slips; or none> |
   ```
   Keep all five rows; a row that does not apply says "none" or "nobody". The
   next action is one action. Anything more goes to `Todo.md` (step 7).
   **Rebuild with** earns its place: an artifact nobody can regenerate is a dead
   end the moment it needs a change. Every path and link in the block must lead
   to something that exists now; `check.py` warns about one that does not.
6. **Add a dated entry** directly below the `---` rule, above the earlier
   entries, so the newest is first:
   ```markdown
   **27 September 2026.** <One line on what the session did.> <What was decided
   and by whom, quoting where the wording was the point. What you decided that
   they did not, marked as yours. What was left out on purpose, and why.>
   ```
   Never edit or compress earlier entries. They are the record.
7. **Actions go to the zone's `Todo.md`**, not the note. Re-read it right
   before editing. Append new actions for this thread under `## Inbox` as
   `- [ ] <action> · <project or person> · <date>`; tick the ones this session
   finished. Touch no other thread's lines.
8. **Set `updated:`** in the note's frontmatter to today.
9. **Update the hub's `## Threads` line** only if the thread's purpose changed.
   Re-read the hub first; change that one line.
10. **Memory pointer.** If you, the assistant, keep a memory of your own, keep
    one entry for this thread that says where its resume point is and nothing
    else: no status, no date, no summary.
    ```
    Acme, Pricing (Work zone). Resume from
    Zones/Work/Acme/Threads/Pricing/Pricing.md, the Resume here block. Read it
    before anything else in the thread.
    ```
    Create it if missing, leave it if present. No memory, no step.
11. **Commit in the zone's repository.** Stage by name only what this wrap
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

Spoken: "Acme pricing wrapped. Next is the second draft once Dana sends
volumes, due Friday." Add a third sentence only for something the user must
know: a wall held material back, a meeting page was unfinished, a commit
failed.

Written: the same, plus the files changed and the commit hash.

## Close for the day: "close for the day", "I'm done for today"

Wrap every thread worked on today, then give one summary.

1. **Find today's threads.** For each zone folder under `Zones/` (skip `_zone`):
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
   - a path starting with `_` → a template; ignore it.

   Add any thread this conversation worked on that left no file behind. Skip
   threads marked done. Skip a thread already wrapped in this session with
   nothing changed since that wrap; name it in the summary as already wrapped.

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
4. **One summary.**

Spoken, three sentences at most: "Wrapped three: Acme pricing, Birch launch plan
and roof repair. First thing tomorrow is the Acme second draft, due Friday. Roof
repair I could only log from its files, so check its note when you open it."

Written: one line per thread (short name, next action, commit hash), then
anything that failed or was held back.

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
6. **Open actions:** if `Todo.md` still has lines for this thread, name them and
   ask whether to tick, keep or drop them. Do not decide for the user.
7. **Last thread in the project?** Ask whether the project is finished too. If
   yes, set `status: done` in the hub.
8. **Delete the memory pointer**, if there is one. A pointer that outlives its
   thread keeps announcing work that no longer exists.
9. **Commit** in the zone's repository: "Acme, Pricing: finished; outcome
   recorded".

Spoken: "Acme pricing is closed. Two actions still point at it: tick them, keep
them, or drop them?"

Written: the outcome paragraph, the files changed, the commit hash.

## Park: "park X", "put X aside"; wake: "wake X", "pick X up again"

Parking sets a thread aside without finishing it, so the lists stay short. It
moves nothing: the folder, the Resume here block, the links and the history
stay exactly where they are.

1. **Resolve X.** Parked threads resolve like any other.
2. **Re-read the thread note now.**
3. **Set `status: parked`** to park, or `status: active` to wake, and `updated:`
   today, in the note's frontmatter. Leave the Resume here block as it is: it
   still says where the work stood.
4. **Add a dated entry** below the `---`: "Parked." or "Woken.", with the reason
   if the user gave one.
5. **Commit** in the zone's repository: "Acme, Pricing: parked".
6. **Keep the memory pointer**, if there is one. A parked thread is not closed.

Spoken: "Acme pricing is parked. Say wake Acme pricing to bring it back."

Written: the same, then the note's path and the commit hash.

## New: "new project X for P in Z", "new thread X in P"

Creation goes through the scaffolding script, which checks names. Run it from
the workspace root.

```sh
python3 System/tools/scaffold.py project --zone <Zone> --name "<Project>" --party <tag> --thread "<Thread>"
python3 System/tools/scaffold.py thread --zone <Zone> --project "<Project>" --name "<Thread>"
```

1. **Resolve the parts.** The zone against the folders under `Zones/`; the
   project against existing projects; the party against Parties and Aliases,
   giving its tag. The zone may be left out when the party's row in Parties
   names it, or the project already exists.
2. **A new project needs its first thread.** If none was given, ask: "What's
   the first thread called?" Every piece of work belongs to a thread.
3. **A new party:** offer to add it to Parties before scaffolding, and ask
   whether a wall applies: "Birch isn't a party yet. Add it to the Work zone,
   and should anyone be walled off from it?" With the answer, re-read
   `System/context.md`, add the Parties row (name, what it is, zone, tag) and
   any Walls rows, then scaffold. Never scaffold with a made-up tag.
4. **Run the script.** When it refuses, it prints a one-line reason. Relay it
   in plain words and suggest a fix:
   - a name that cannot be said (digits, dates, codes, punctuation): offer a
     spoken version, "Q3 pricing" → "autumn pricing";
   - a sibling that sounds alike: say which, and offer a distinct name, or ask
     whether the user meant the existing one and wants it opened;
   - an unknown party: step 3;
   - an unknown zone: name the zones that exist. Creating a zone is not this
     skill's job.
5. **Fill in what you were told.** If the user gave the purpose, write it into
   the one-line description in the hub and the thread note. Otherwise leave the
   angle-bracket fields and mention them once.
6. **Commit**, if the script has not: check
   `git -C "Zones/<Zone>" status --porcelain`, stage the new folder by name, and
   commit "New project Birch (birch), first thread Launch plan". Adding Parties
   or Walls rows is a change outside the zone: commit it separately in the
   workspace root's repository, if it has one.

The new thread is now in focus, as if opened.

Spoken: "Birch is set up in Work with a launch plan thread. What's it for, in a
sentence?" or, on a refusal: "Can't name it Q3 pricing: names can't have
digits. Autumn pricing?"

Written: the paths created and the commit hash.

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
7. **Say that a wall held something back, and nothing more.** "A wall kept some
   meeting material out of this note." No title, date, party, person or count,
   even if asked in the same breath. A question put straight to the Meetings
   wiki ("what did Theo say?") is a different request; its answer stays in the
   conversation and is never written here.
8. **Material the user dictates** into a thread that belongs to a walled party:
   ask once before writing it. "That sounds like Birch material, and Birch is
   walled off from Acme. Write it anyway?"
9. **Can't tell** whether a wall applies: ask.

**The same check runs again before every commit, and it does not rely on you.**
Each zone's pre-commit hook runs `System/tools/check.py --staged --walls-only`
on the files being committed. A link to a walled meeting, the name of a party,
person or alias on the far side of a wall, or eight words in a row lifted from
a walled meeting page or its transcript stops the commit, with one line naming
the file and the wall. When it refuses:

- **Take the material out** of that file and commit again. Tell the user a wall
  held something back, as in step 7, and nothing more.
- **Never commit with `--no-verify`** unless the user explicitly asks for it,
  in this request. Yes once is not yes next time.
- **If the refusal looks wrong** (a walled party named in a published context,
  say), tell the user which file and which wall, and let them decide.

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
  one thread's note, one hub line, that thread's `Todo.md` lines and that
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
- **It does not create zones** or change the workspace layout. Projects and
  threads come from the scaffolding script, and nowhere else.
