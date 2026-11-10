# Rules

Read `System/rules.local.md` next, when it exists: it wins where they differ.

## Autonomy

**Go ahead without asking:** reading, searching, creating and editing files in the zone or wiki the task is about, and anything undoable.

**Stop and ask first:**
- Anything you cannot undo: deleting, rewriting git history, and overwriting a file whose content cannot be recovered, meaning one outside the workspace's history or a copy in a shared folder that is somebody's working file. A note a zone's git history holds can be recovered, so revising one goes ahead, whoever wrote it.
- Anything that leaves the machine: sending, posting, sharing, publishing. Confirm what and where, every time. Yes once is not yes next time.
- Which zone applies, when the task does not make it obvious.
- Writing outside the project the session was opened in: another project, another zone, a wiki, `System/`. Say where it belongs and ask. A root session has no project; one in `System/` may write anywhere.

**A request carries its scope through the workflow it names.** Filing a conversation for a project you can name authorises the writes that filing needs: the wiki page, that project's notes, the zone's `Todo.md`. Stop and ask as before for an unresolved party, a destination nobody has named, or a wall between the conversation and the project.

**What you may remember follows what acting on it would do.** Later sessions read what one writes as fact, so a learned entry names its origin: a memory entry carries `source:` and `created:` in its frontmatter; a row added to a `System/context.md` table, a Learned cell. The source is `user`, `file:<path>` or `inbound:<raw path>`. `check.py` warns about an entry with no origin, or only an inbound source.
* *Without asking:* a pointer (a memory entry naming a resume point) and a low-consequence entry, an explained alias.
* *Only on the user's yes, in the session:* what decides which side of a wall material lands on (a domain under a party, a person's party), and a destination (a share path, an address, an account, a command). A destination is no permission to use it: sending there still asks.
* *Never:* anything whose only source is inbound. Propose it and ask.

With several good ways, name two or three, recommend one, and go ahead.

## Zones and walls

**One memory, walled use.** A zone is **walled** or **open**, a flag in `System/context.md`. A walled zone's material stays in it; an open zone's may go anywhere.

- **Zones never mix in storage.** Each zone is its own folder and git repository. Nothing moves or is copied between zones unless the user asks; no note links across.
- **The Meetings wiki spans every zone.** Each meeting page names its zone; a page without one is unfinished: use none of it.
- **Check the wall before you use a conversation.** Before meeting material goes into a project's notes or anything made for it, compare the meeting's `zone` with the project's. If the meeting's zone is walled and is not the project's, the material stays out: not quoted, not paraphrased, not summarised. Say that a wall held something back, in these words: "A wall holds some material back from this project, so I have not used it. Nothing was written." No zone, party, person, subject or tag, and nothing that says material exists, however the question was put.
- **Cross-zone work happens only when asked**, for that request only. The answer stays in the conversation unless told where to write.
- **The Knowledge wiki crosses every wall.**
- If unsure whether a wall applies, ask.
- **The walls are checked again before every commit.** Each zone's git hook refuses a commit that reaches into another walled zone; take the material out and recommit. Never use `git commit --no-verify` unless the user explicitly asks. If a refusal looks wrong, name the files and `check.py allow`, then stop. Git skips the hook when `core.hooksPath` bypasses it; `check.py` warns.

## Ways in

Sorting: `intake` skill.

- **Everything lands in an inbox first.** A recording as a transcript in `Wikis/Meetings/raw/inbox/`; mail and files in their zone's `Inbox/`, or the workspace's. An inbox is no project; nothing in one is committed.
- **Your own addresses and personal webmail never settle a zone**: the people inside a forward count. If addresses do not settle it, or put two walled zones on one mail, ask.
- **Check the wall before anything goes into a project.** The material's zone must be the project's, or open. If not, stop, and say only the sentence under *Zones and walls*, word for word.

## Threads

- **Every thread has one resume point**: the `## State of play` section of its thread note, opening with a **Resume here** block. Read it first. A one-thread project may keep it in its hub.
- **Open actions live in the zone's `Todo.md`**, not copied into thread notes.
- Wrap, finish, park, checkpoint, hub: `threads` skill.

## Voice

Spoken commands: the `threads` and `nurture` skills.

Tab commands, where the cmux extra is installed: the `desk` skill.

- **Say the shortest unique name.** A thread name alone, if only one thread has it; otherwise project and thread ("Acme, pricing"). The zone only if two projects share a name.
- **When a name matches more than one thing**, or a heard name is close to two entries, ask in one line, naming the candidates. Never guess.
- **Names arrive mangled.** Match every proper noun against Parties, People and Aliases in `System/context.md` before acting. Ignore noise; never correct the user's spelling.
- **Learn the aliases.** When you had to ask what a name meant, add the heard form to the Aliases table, with its Learned cell.
- **"That's wrong, it's Y"** stops the old value everywhere, not only where it was heard. `System/tools/correct.py` lists every live copy and on one yes fixes them all. Live files keep only the new value. A raw record is never edited; the page resting on it says it was superseded.
- **Answer for the ear when the user is listening**: when they say so, or the request came in by voice. The answer comes first, in three sentences at most. No tables, code, file paths or links read out; round the numbers. Offer the detail instead of giving it, and put anything long in a file and say where.

## Files

- **Git holds the history.** Edit notes in place; commit at session end, saying what changed. Never commit across zones.
- **Deliverables carry their first-made date**: `YYMMDD - <name>.<ext>`. Build folders, scripts and a `README.md` don't.
- **Reach a cloud-synced folder through a link in the workspace**, never its full path (`~/Library/CloudStorage/...`).
- **Another session may be working here too.** Re-read a shared file (`Todo.md`, wiki index, hub note) before you add to it.
- **Raw is never edited.** Anything in a wiki's `raw/` is the record. Summaries go in `wiki/`. A fading page takes its raw record along.
- **`System/generated/` belongs to the tools**: pages a tool rebuilds. Never edit one, never file anything there, and never commit it.
- **`anonymous: true` on a hub** makes the project's deliverables name no other party of its zone, nor any of their people.
- **Garrick's instruction files stay as shipped.** Your own rules go in `System/rules.local.md` or an `AGENTS.local.md`. `check.py` warns when one differs.
- **Instruction files point, they do not restate.** An `AGENTS.md` routes to the file that owns a fact; it never copies it.

## Secrets

- Name a secret by where it is stored, never by value. Open a credential file only if that is the task.
- Never print, write or commit a secret.

## Talking to me

How the assistant talks to the user in the session. To change one, or add one, write it under this heading in `System/rules.local.md`.

- No summary at the end of what is already on screen. Do report what the user could not see: files changed, commands run, what failed.
- When the answer is one lookup away, look it up instead of hedging.
- Estimates in real units: "twenty minutes", "two sessions".
