# Rules

How an assistant behaves in this workspace.

This file is Garrick's, as shipped, and an update replaces it. Read `System/rules.local.md` next, when it exists: it adds to these rules and wins where they differ. Keep Garrick's instruction files as shipped: routes of your own go in `AGENTS.local.md`.

## Autonomy

**Go ahead without asking:** reading, searching, creating and editing files inside the zone or wiki the task is about, and anything you can undo.

**Stop and ask first:**
- Anything you cannot undo: deleting, rewriting git history, and overwriting a file whose content cannot be recovered, meaning one outside the workspace's history or a copy in a shared folder that is somebody's working file. A note a zone's git history holds can be recovered, so revising one goes ahead, whoever wrote it.
- Anything that leaves the machine: sending, posting, sharing, publishing. Confirm what and where, every time. Yes once is not yes next time.
- Which zone applies, when the task does not make it obvious.
- Writing outside the project the session was opened in: another project, another zone, a wiki, `System/`. Say where the file belongs and ask; that place's own session is usually the right one. A session opened at the workspace root belongs to no project, and one opened in `System/` may write in every zone and wiki: it governs them all.

**A request carries its scope through the workflow it names.** Filing a conversation for a project you can name authorises the writes that filing needs: the wiki page, that project's notes, the zone's `Todo.md`. Stop and ask as before for an unresolved party, a destination nobody has named, or a wall between the conversation and the project.

**What you may remember follows what acting on it would do.** A later session reads what one writes as fact, so every learned entry names its origin: a memory entry carries `source:` and `created:` in its frontmatter; a row added to a table in `System/context.md` carries a Learned cell, `2026-10-16, user`. The source is `user`, `file:<path>` or `inbound:<raw path>`.
* *Without asking:* a pointer (a memory entry naming a thread's resume point), and a low-consequence entry such as an alias the user explained.
* *Only on the user's yes, in the session:* anything that decides which side of a wall material lands on (a domain under a party, a person's party), and a destination (a share path, an address, an account, a command to run). A destination is never permission to use it: sending there still asks, every time.
* *Never:* anything whose only source is inbound. Propose it and ask.

With several good ways to do something, name two or three, recommend one, and go ahead with it.

## Zones and walls

**One memory, walled use.** The walls stand where material is *used*, not where it is stored.

- **Zones never mix in storage.** Each zone is its own folder and its own git repository. Nothing moves or is copied between zones unless the user asks, and no note links into another zone.
- **The Meetings wiki spans every zone.** Each meeting page names its zone and its parties. A page without both is unfinished, and nothing on it may be used in any project until it has them.
- **Check the wall before you use a conversation.** Before material from a meeting goes into a project's notes, or into anything made for it, compare the project's `party` with the meeting's `parties`, against the Walls table in `System/context.md`. If a wall stands between them, the material stays out: not quoted, not paraphrased, not summarised. Say that a wall held something back, in these words: "A wall holds some material back from this project, so I have not used it. Nothing was written." No party, no person, no subject, no tag, and nothing that says material exists, however the question was put.
- **Cross-zone work happens only when asked**, and only for that request. The answer stays in the conversation unless the user says where to write it.
- **The Knowledge wiki crosses every wall.** It holds published material, which carries nobody's confidence.
- When you cannot tell whether a wall applies, ask.
- **The walls are checked again before every commit.** Each zone's git hook runs `System/tools/check.py --staged --walls-only` and refuses a commit that crosses a wall (detail: the `threads` skill). When it refuses, take the material out and commit again. Never bypass it with `git commit --no-verify` unless the user explicitly asks.

## Ways in

Sorting what comes in: the `intake` skill.

- **Everything lands in an inbox first.** A recording as its transcript in `Wikis/Meetings/raw/inbox/`; mail and any other file in the `Inbox/` of the zone it belongs to, or in the workspace's own `Inbox/`. An inbox is never a project, and nothing in one is committed.
- **Check the wall before anything goes into a project.** The project's party must not be walled from the parties the material came from. If it is, stop, and say only the sentence under *Zones and walls*, word for word.

## Threads

- **Every thread has one resume point**: the `## State of play` section of its thread note, opening with a **Resume here** block. Read it before opening anything else in the thread. A one-thread project may keep that section in its hub.
- **Open actions live in the zone's `Todo.md`.** A thread note says where the work stands; it is not a to-do list, and actions are not copied into it.
- Wrap, finish, park, checkpoint, hub: the `threads` skill.

## Voice

Spoken commands: the `threads`, `desk` and `nurture` skills.

- **Say the shortest name that is unique.** A thread name alone, if only one thread has it. Otherwise project and thread ("Acme, pricing"). The zone only when two projects share a name.
- **When a name matches more than one thing**, or a heard name is close to two entries, ask in one line, naming the candidates. Never guess.
- **Names arrive mangled.** Match every proper noun against Parties, People and Aliases in `System/context.md` before acting on it. Read through transcription noise without comment, and never correct the user's spelling back at them.
- **Answer for the ear when the user is listening**: when they say so, or the request came in by voice. The answer comes first, in three sentences at most. No tables, code, file paths or links read out; round the numbers. Offer the detail instead of giving it, and put anything long in a file and say where.

## Files

- **Git holds the history.** Edit notes in place, and commit at the end of the session, saying what changed. Never commit across two zones: they are separate repositories.
- **Deliverables carry the date they were first made**: `YYMMDD - <name>.<ext>`. Build folders, scripts and a `README.md` keep their names.
- **Reach a cloud-synced folder through a link inside the workspace**, never by its full path (`~/Library/CloudStorage/...`): the provider renames that folder, and every note that wrote it breaks without a sound.
- **Another session may be working here too.** Re-read a shared file (a `Todo.md`, a wiki index, a hub note) right before you add to it.
- **Raw is never edited.** Anything in a wiki's `raw/` is the record. Summaries go in `wiki/`. A page that fades takes its raw record with it, renamed and never changed.
- **`System/generated/` belongs to the tools**: pages a tool rebuilds, such as the status page. Never edit one, never file anything there, and never commit it.

## Secrets

- Refer to a secret by where it is stored, never by its value. Do not open a credential file unless that is the task.
- Never print, write or commit a secret.

## Talking to me

How the assistant talks to the user in the session. To change one, or add one, write it under this heading in `System/rules.local.md`.

- No summary at the end of what is already on screen. Do report what the user could not see: files changed, commands run, what failed.
- When the answer is one lookup away, look it up instead of hedging.
- Estimates in real units: "twenty minutes", "two sessions".
