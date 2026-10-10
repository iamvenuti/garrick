# Rules

How an assistant behaves in this workspace. Harness-neutral: nothing here depends on one model or one tool. Change a rule here and nowhere else.

## Autonomy

**Go ahead without asking:** reading, searching, creating and editing files inside the zone or wiki the task is about, and anything else you can undo.

**Stop and ask first:**
- Anything you cannot undo: deleting, overwriting a file you did not create, rewriting git history.
- Anything that leaves the machine: sending, posting, sharing, publishing. Confirm what and where, every time. Yes once is not yes next time.
- Which zone applies, when the task does not make it obvious.
- Writing outside the project the session was opened in: another project, another zone, a wiki, `System/`. Say where the file belongs and ask; that place's own session is usually the right one. A session opened at the workspace root belongs to no project, and one opened in `System/` may write in every zone and wiki: it governs them all.

When there are several good ways to do something, name two or three, recommend one, and go ahead with it.

## Zones and walls

**One memory, walled use.** The user holds every conversation in one head, so the memory holds them in one place. The walls stand where material is *used*, not where it is stored.

- **Zones never mix in storage.** Each zone is its own folder and its own git repository. Nothing moves or is copied between zones unless the user asks.
- **The Meetings wiki spans every zone.** Each meeting page names its zone and its parties. A page without both is unfinished, and nothing on it may be used in any project until it has them.
- **Check the wall before you use a conversation.** Before material from a meeting goes into a project's notes, or into anything made for it, compare the project's `party` with the meeting's `parties`, against the Walls table in `System/context.md`. If a wall stands between them, the material stays out: not quoted, not paraphrased, not summarised. Say that a wall held something back. Do not say what.
- **Cross-zone work happens only when asked**, and only for that request. The answer stays in the conversation unless the user says where to write it.
- **The Knowledge wiki crosses every wall.** It holds published material, which carries nobody's confidence.
- When you cannot tell whether a wall applies, ask.
- **The walls are checked again before every commit.** Each zone's git hook runs `System/tools/check.py --staged --walls-only`, which refuses a commit whose project files link to, name or quote a party on the far side of a wall. When it refuses, take the material out and commit again. Never bypass it with `git commit --no-verify` unless the user explicitly asks. Git skips the hook when its `core.hooksPath` setting sends commits past it, and `check.py` warns when it does.

## Ways in

Recordings, mail and files you drop in. Getting them here is fetching, done by hand, by a script or by your assistant's own connector, and it decides nothing. Where each one goes is decided by these rules, one item at a time; the `intake` skill is the procedure.

- **Everything lands in an inbox first.** A recording as its transcript in `Wikis/Meetings/raw/inbox/`; mail and any other file in the `Inbox/` of the zone it belongs to. An inbox is never a project, and nothing in one is committed.
- **A recording is always a conversation**, filed in Meetings.
- **Mail and files go where they belong:**
  - a conversation (a mail exchange with people, notes of a call) is filed in Meetings, with its zone and parties;
  - something to read (a newsletter, an article, a report) is filed in Knowledge, with no parties. If it comes from a party's domain, ask before treating it as published;
  - material for a project (a client's document, a contract, a data file) goes into that project's `Sources/`. If it came by mail, the mail is filed in Meetings as a conversation too, and only the attachment goes to the project.
- **Parties come from the addresses, confirmed.** A domain in the Domains column of Parties names its party, and a plus tag (`you+acme@`) is a strong hint. Personal webmail never names anyone, and neither do your own addresses (listed under Me in `System/context.md`): they carry what you forward, and the people inside the forward are the ones who count. When the addresses do not settle it, or put both sides of a wall on one mail, ask.
- **Check the wall before anything goes into a project.** The project's party must not be walled from the parties the material came from. If it is, stop, and say only that a wall held something back.
- **Unsure of the kind, the zone, a party or the project: ask**, in one short line. Never guess across a wall.
- **Code moves, parses and lists; it never chooses where a thing goes.**

## Threads

- **Every thread has one resume point**: the `## State of play` section of its thread note, opening with a **Resume here** block. It says what is done, the live artifact, the next action, who it waits on and the deadline. Read it before opening anything else in the thread.
- **Rewrite the Resume here block at the end of any session that produced a decision or a deliverable**, so that it describes now. Add a dated entry below it; keep the old entries.
- **A finished thread** gets `status: done`, and its Resume here block becomes `### Outcome`: what was delivered or decided. The project hub lists it under `## Finished`.
- **A parked thread** gets `status: parked`: set aside, not finished. It keeps its folder, its Resume here block and its links, and drops out of "what's open" until it is woken.
- **Open actions live in the zone's `Todo.md`.** A thread note says where the work stands; it is not a to-do list, and actions are not copied into it.
- **If your assistant has a memory of its own**, keep one entry per live or parked thread that says where its resume point is, and nothing else. No status: the note has it. Delete the entry when the thread is finished.

## Voice

Much of this workspace is driven by speaking and listening. Every name, request and reply has to survive that.

- **Names are speakable.** Zones, projects and threads get names a person can say: no dates, codes or punctuation. Siblings must not sound alike.
- **Say the shortest name that is unique.** A thread name alone, if only one thread has it. Otherwise project and thread ("Acme, pricing"). The zone only when two projects share a name.
- **When a name matches more than one thing**, ask in one line, naming the candidates. Never guess.
- **"Open X"**: read that thread's Resume here block and answer in two sentences: where it stands, and the next action.
- **"Close X" or "wrap X"**, or **"wrap it"** for the thread in hand: rewrite its Resume here block and add the dated entry. **"Close for the day"**: do that for every thread worked on today.
- **"Finish X" or "X is done"**: close the thread for good (see Threads).
- **"Park X"**: set the thread aside without finishing it. **"Wake X"** or **"unpark X"**: bring it back. **"What's parked"**: name the parked threads.
- **"Where am I" or "what's open"**: name the live threads, most recent first; at most five when the user is listening.
- **Names arrive mangled.** Match every proper noun against Parties, People and Aliases in `System/context.md` before acting on it. If a heard name is close to two entries, ask. Read through ordinary transcription noise without comment, and never correct the user's spelling back at them.
- **Learn the aliases.** When you had to ask what a name meant, add the heard form to the Aliases table.
- **Answer for the ear when the user is listening**: when they say so, or the request came in by voice. The answer comes first, in three sentences at most. No tables, code, file paths or links read out; round the numbers. Offer the detail instead of giving it, and put anything long in a file and say where.

## Files

- **Git holds the history.** Edit notes in place, and commit at the end of the session with a message that says what changed. Never commit across two zones in one go: they are separate repositories.
- **Deliverables carry the date they were first made**: `YYMMDD - <name>.<ext>`. The date never moves, so a folder sorts by when the work started.
- **Another session may be working here too.** Re-read a shared file (a `Todo.md`, a wiki index, a hub note) right before you add to it, not once at the start.
- **Instruction files point, they do not restate.** An `AGENTS.md` routes to the file that owns a fact; it never copies it, holds status, or keeps a hand-written list of projects or skills.
- **Run the check.** `python3 System/tools/check.py` tests the workspace against these rules and exits non-zero on a problem. Add `--ear` for a three-sentence answer to read aloud.
- **Raw is never edited.** Anything in a wiki's `raw/` folder is the record. Summaries go in `wiki/`.
- **`System/generated/` belongs to the tools**: pages a tool rebuilds, such as the status page. Never edit one, never file anything there, and never commit it. The next build replaces what is there, and `check.py` reports a generated page that is committed.

## Secrets

- Refer to a secret by where it is stored, never by its value. Do not open a credential file unless that is the task.
- Never print, write or commit a secret.

## Talking to me

How the assistant talks to the user in the session. Edit to taste.

- No summary at the end of what is already on screen. Do report what the user could not see: files changed, commands run, what failed.
- When the answer is one lookup away, look it up instead of hedging.
- Estimates in real units: "twenty minutes", "two sessions".
