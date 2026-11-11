# Open

Read after `SKILL.md`: the dispatcher's *Resolving a name* and *Listening mode* apply. Waking a parked thread follows the Park section's second half in `lifecycle.md`, with the executor under its *Running an action*.

## The rules behind this request

These are the rules in `System/rules.md` that this request carries out, word for word.

- **Every thread has one resume point**: the `## State of play` section of its thread note, opening with a **Resume here** block. It says what is done, the live artifact, the next action, who it waits on and the deadline. Read it before opening anything else in the thread. A project that is only ever one thread may keep that section in its hub instead.
- **"Open X"**: read that thread's Resume here block and answer in two sentences: where it stands, and the next action.

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
