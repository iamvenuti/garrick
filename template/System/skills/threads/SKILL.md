---
name: threads
description: >
  Open, list, wrap, park, finish and create work threads, catch the
  user up on what changed in them, and add zones, by voice or typed. The
  procedure behind the spoken commands in System/rules.md. Use when the
  user says "open X", "pick up X", "resume X",
  "where was I on X", "where am I", "what's open", "what's open in Work",
  "what's next",
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
its own tab, and the session in that tab runs this skill. "Close for the day"
has every session used today wrap its own thread (see its section).

## The rules behind the commands

`System/rules.md` keeps one resume point per thread and open actions in
`Todo.md`, and leaves the rest to this skill. These are the rules it moved
here, word for word. The commands below carry them out.

**Threads**, **Voice** and **Files** are the groups the rules come in. Each rule is kept in the reference whose request it governs, under *The rules behind this request*, so a request reads only its own.

## Which reference to read

Read this file, then only the one reference that carries out the request. Each
reference stands alone for its requests and is named here once.

| Request | Reference |
|---|---|
| Open | `reference/open.md` |
| Wrap, Checkpoint, Close for the day | `reference/wrap.md` |
| Finish, Park, New, Rename, Move, Delete, New zone | `reference/lifecycle.md` |
| Correct | `reference/correct.md` |
| List, Next, Catch up, Find, Back | `reference/catch-up.md` |
| The wall check | `reference/wall-check.md` |

Wrap, Finish and New run the wall check as part of their own reference, which
repeats it.

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
