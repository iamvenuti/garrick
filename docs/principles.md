# Principles

## Everything is folders on your disk

A Garrick workspace is Markdown files in folders, under git. No database, no app, no account. `System/context.md` is a table you can open and edit by hand. A thread's whole history is the commits in its zone's repository. If you can read a text file, you can read everything the assistant knows about your work.

## Harness independence, and a test for it

The entry point is `AGENTS.md`, a plain file, not a setting inside one vendor's app. Claude Code and Codex both read it. No rule, template or skill names either one; the only mention is a safety warning, in `AGENTS.md` and `check.py`, about the `CLAUDE.md` file that would stop Claude Code reading `AGENTS.md`.

Here's the test: delete the assistant's settings. Not the workspace, its settings, `~/.claude` or `~/.codex` or whatever your harness keeps for itself. What did you lose? Preferences, maybe a theme, cached credentials. Nothing about your zones, your parties, your walls, or a single thread's resume point, because none of that ever lived there. It lives in the workspace, which is why a Garrick install carries `.claude/skills` and `.agents/skills` as symlinks back to one shared `System/skills` folder: whichever assistant you open, it finds the same rules and the same skills, because they were never its own to begin with.

Switch assistants and you lose nothing but the muscle memory of a different interface.

## One memory, walled use

You hold every conversation you've had in one head, so the workspace holds them in one place: `Wikis/Meetings/`, one wiki across every zone. The separation you need isn't a second copy locked in a different vault; it's a rule about when a conversation may be used. Before anything from a meeting goes into a project's notes, the assistant checks that project's party (the client or organisation it is for, named by a tag from `System/context.md`) against the meeting's parties, using the Walls table in the same file: pairs of parties whose material must never meet. A wall between them means the material stays out entirely, not quoted, not paraphrased, not summarized, and the assistant says only that a wall held something back, never what. The wall governs what gets written into a project, not what you may know: ask the Meetings wiki directly what someone said, and you get the answer in the conversation, where it stays.

That's the working line: *it remembers who told you what, and never repeats it to the wrong party.* The wall sits at the point of use, not the point of storage, because that's the only place a rule can actually do the job. The assistant applies that rule as it writes, and a model following a rule is a matter of probability, so a deterministic check sits underneath it. Before every commit, each zone runs `check.py` on what is about to enter its history, and refuses a project file that links to a meeting on the far side of a wall, names a party or person from there, or repeats eight or more words in a row from one of its meetings. The check catches the named and the quoted. A clean paraphrase gets past it, and stopping that is still the assistant's job.

Mail is a conversation too, most of the time, so it goes to the same place. Each zone has an `Inbox/` folder for mail and any other file. Say "process the inbox" and the assistant sorts each item by rules written in `System/rules.md`, not in code. A mail exchange becomes a mail page in the Meetings wiki, with its zone and parties like any meeting, and from then on the walls treat it exactly as they treat a call. A newsletter or an article goes to Knowledge, with no parties, and a mail filed there loses your own address on the way, from its headers, its footer and its unsubscribe link. A client's document goes into its project's `Sources/`, but only after the wall check, and when it came attached to a mail, the mail is still filed in Meetings. The parties come from the mail domains in the Parties table: a domain names a party only when you have said so, and personal webmail never does. When anything is unclear, the assistant asks rather than picks, and writes your answer down so the next mail from that domain files itself. The check before a commit recognises a mail's attachment in `Sources/` only as an exact copy: an edited copy gets past it, the same way a clean paraphrase does, and stopping that is the assistant's job.

Fetching and sorting are kept apart. Getting a mail into an inbox is code or a connector: you, a mail rule, an optional script, or your assistant's own mail connector. It decides nothing. Deciding where it goes is a rule, and the assistant applies it. Core Garrick never connects to your mail account.

## Zone, project, thread

Three levels, fixed. A zone is a side of your life or work, each its own folder and its own git repository, so Work and Personal never mix by accident. A project is one client or one undertaking inside a zone. A thread is one line of work inside a project, with one resume point.

The depth isn't configurable, and that's deliberate: a name you can say aloud only works if there's a fixed number of them to say. "Acme, pricing" tells the assistant exactly which thread you mean because there's nowhere else for a third word to point.

## One resume point per thread

Every thread has exactly one place that says where it stands: the `### Resume here` block at the top of its `## State of play` section. It says what's live, how to rebuild it, the next single action, who it's waiting on, and the deadline if there is one. Wrapping a thread means rewriting that block so it describes now, then adding a dated entry below it, never editing the old ones. Open the thread months later, cold, and that block is the only thing you need to read first.

## Built to be spoken to

Zone, project and thread names have to survive being said aloud and heard back: no digits, no codes, no punctuation that a transcript can mangle. Two siblings that sound alike get flagged before they're created. A table of aliases catches the names your dictation gets wrong and maps them back to what they mean. When you're listening rather than reading, answers come back in a few short sentences, no tables, no file paths, no numbers read out to three decimal places, and detail gets offered rather than dumped on you.

## You keep the decisions

Nothing here pushes to a remote, sends an email, or acts on a hunch about what you'd want. The assistant asks before anything irreversible and before anything that leaves the machine, every time, because yes once isn't yes next time. Git holds the history of every change, in full, on your disk. Garrick writes the rules and the shape; you're still the one who decides what happens next.
