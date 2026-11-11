# List, next, catch up, find and back

Read after `SKILL.md`: the dispatcher's *Resolving a name* and *Listening mode* apply. These requests only read and offer; opening a thread is `open.md`.

## The rules behind this request

These are the rules in `System/rules.md` that this request carries out, word for word.

- **"Where am I" or "what's open"**: name the live threads, most recent first; at most five when the user is listening.
- **"Back"** or **"where was I"** opens the thread whose note was written most recently and is not finished or parked; **"back to X"** opens X. Nothing to resume: say so, and offer the most recent thread.

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
answers in the conversation and writes nothing; "save that" is a separate
ask. "Brief me for X" is the `meetings` skill's.

1. **What it covers.** X is a zone, a project, a thread, or several joined by
   "and". Resolve each name as in *Resolving a name*. No X: the zone of the
   thread in focus, or of the folder the session started in; at the root with
   more than one zone, ask which in one line. One zone at a time, never a
   pick between zones.
2. **The period**, as `--since <day>` ("since Monday", the most recent one
   before today), `--days N` ("since yesterday" is 1), or `--period week` or
   `14-days`. Nothing said: leave all three out, and the tool takes the last
   day, or `"catch-up"` in `System/garrick-settings.json`.
3. **Gather**, with the folder names the names resolved to:
   ```sh
   python3 System/tools/briefing.py --zone Work --project "Birch Entry" --thread "Acme/Pricing" --since 2026-10-19
   ```
   It prints JSON and changes nothing: per thread that changed, newest first,
   its commits, its Resume here block now and as the period began, the dated
   entries added, a waiting checkpoint, its Todo lines (`added`, `ticked`,
   `open`) and the meeting pages its note links. `quiet` names the threads
   that did not change, `parked_left_out` counts the parked ones, `unmatched`
   names what found no thread: say it. `judgment` is what to raise, say in a
   line and leave out; `guidance` names `System/briefing.local.md`, when it
   exists, which wins.
4. **Write the briefing** from the JSON and nothing else: an overview of
   three sentences at most, then a section per thread in the order given.
   Each statement links its record (the thread note, a commit by its short
   hash, `Todo.md`). A meeting appears only as a link the note already
   holds, never opened, quoted or summarised, so the walls hold as for
   *Open*. A gap (commits with no dated entry, `history` false, a line
   marked `either`, a checkpoint that is `stale` or not `valid`) is said as
   a gap. Nothing changed: one line, with how many threads were quiet.

Spoken: the overview alone, then offer the detail.

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
