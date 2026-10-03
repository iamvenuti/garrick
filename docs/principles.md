# Principles

## Everything is folders on your disk

A Garrick workspace is Markdown files in folders, under git. No database, no app, no account. `System/context.md` is a table you can open and edit by hand. A thread's whole history is the commits in its zone's repository. If you can read a text file, you can read everything the assistant knows about your work.

## Harness independence, and a test for it

The entry point is `AGENTS.md`, a plain file, not a setting inside one vendor's app. Claude Code and Codex both read it. No rule, template or skill names either one; the only mention is a safety warning, in `AGENTS.md` and `check.py`, about the `CLAUDE.md` file that would stop Claude Code reading `AGENTS.md`.

The installer links the shared skills into `.claude/skills` and `.agents/skills` in every workspace repository. The rules, context and resume notes remain ordinary files whichever assistant opens them.

Try switching by opening the same workspace in another supported assistant and asking it to read the instructions, then resume a thread. The saved record and git history remain available. Account settings, permissions, private chat history and unsaved context are separate. There is no need to delete either assistant's settings to test portability.

## One memory, walled use

Garrick keeps conversations together in `Wikis/Meetings/` so you can retrieve your own record from one place. Each page identifies its zone and parties. Projects carry a party tag, and the Walls table in `System/context.md` lists the pairs whose material must stay apart.

A wall exists only when you declare the pair. Different folders or party tags do not create one automatically. For example, internal projects Cedar and Maple at the same company can use tags `cedar` and `maple`, with a wall declared between them. Two projects sharing one party tag cannot be distinguished by that wall model.

Before using a conversation for a project, the assistant is instructed to compare the project's party with the conversation's parties. A declared wall means excluding that material, including paraphrases and summaries, and saying only that some material was held back. For a general lookup of your own record, you can ask the Meetings wiki directly. When drafting or preparing for someone else, name the destination project so the rule has a clear target.

This is a rule for an assistant with access to the shared memory, not access isolation between parties. The assistant can make a mistake. The files also carry limited deterministic checks to catch specific mistakes before they enter a zone's git history.

### What the check covers

The installed pre-commit hook checks staged project files before saving a commit. For declared walls, it can reject links to walled meeting pages, configured names and aliases from the other party, and matching runs of eight words with enough content words from walled meetings or transcripts. Common wording and certain ambiguous names are excluded. Wording counts as common when it also appears in a file every side reads by design: the instruction files, `System/rules.md` and `System/context.md`, the skills, templates and tools in `System/`, and the Knowledge wiki. Nothing else in `System/` counts. An interview record holds your answers in your own words, and a page a tool rebuilds into `System/generated/`, such as the status page, can gather every zone at once. Either can carry what one party said, so nothing they repeat counts as common. Project `Sources/` files are exempt from the name check because incoming documents can legitimately name other parties.

The text scan covers Markdown, plain text, CSV/TSV, HTML, JSON, YAML and VTT files up to 2 MB. It does not inspect the contents of generated Word, PowerPoint or PDF deliverables. A separate check can match an exact mail attachment copied into `Sources/`; that is a byte comparison, not a content scan of those formats.

A clean paraphrase, shorter copied passage or edited attachment can pass. The hook does not prevent an initial file write, chat reply or transmission, and it does not isolate the assistant from the shared memory. It also cannot infer a wall you have not declared. A successful check means those implemented checks found no issue; it is not a guarantee of confidentiality. Review work before sharing it, including any exported document.

The hook must be active in each zone. The installer warns if an existing `core.hooksPath` setting prevents its hook running; resolve that before relying on commit checks. Bypassing the hook skips this protection.

### Filing incoming material

Mail is a conversation too, most of the time, so it goes to the same place. Each zone has an `Inbox/` folder for mail and any other file. Say "process the inbox" and the assistant sorts each item by rules written in `System/rules.md`, not in code. A mail exchange becomes a mail page in the Meetings wiki, with its zone and parties like any meeting, and from then on the walls treat it exactly as they treat a call. A newsletter or an article goes to Knowledge, with no parties, and a mail filed there loses your own address on the way, from its headers, its footer and its unsubscribe link. A client's document goes into its project's `Sources/` after the assistant applies the wall rules, and when it came attached to a mail, the mail is still filed in Meetings. The parties come from the mail domains in the Parties table: a domain names a party only when you have said so, and personal webmail never does. When anything is unclear, the assistant asks rather than picks, and writes your answer down so the next mail from that domain files itself. The check before a commit recognises a mail's attachment in `Sources/` only as an exact copy: an edited copy gets past it, the same way a clean paraphrase does, and stopping that is the assistant's job.

Fetching and sorting are kept apart. Getting a mail into an inbox is code or a connector: you, a mail rule, an optional script, or your assistant's own mail connector. It decides nothing. Deciding where it goes is a rule, and the assistant applies it. Core Garrick never connects to your mail account.

## Zone, project, thread

Three levels, fixed. A zone is a side of your life or work, each its own folder and its own git repository. Separate histories make changes easier to scope; the assistant still has to follow the rules about using material across zones. A project is one client, customer, partner or internal undertaking inside a zone. A thread is one line of work inside a project, with one resume point.

The depth isn't configurable, and that's deliberate: a name you can say aloud only works if there's a fixed number of them to say. "Acme, pricing" tells the assistant exactly which thread you mean because there's nowhere else for a third word to point.

## One resume point per thread

Every thread has exactly one place that says where it stands: the `### Resume here` block at the top of its `## State of play` section. It says what's live, how to rebuild it, the next single action, who it's waiting on, and the deadline if there is one. Wrapping a thread means rewriting that block so it describes now, then adding a dated entry below it, never editing the old ones. Open the thread months later, cold, and that block is the only thing you need to read first. A thread you are not working on but not finished with can be parked: "park X" sets `status: parked`, keeps the note and its block exactly as they are, and takes it out of "what's open" until "wake X". So `check.py` reads every live thread's block and warns when a link or a file path in it leads nowhere: a deliverable renamed or moved turns up in the next check, not in the next cold resume.

## Built to be spoken to

Zone, project and thread names have to survive being said aloud and heard back: no digits, no codes, no punctuation that a transcript can mangle. Two siblings that sound alike get flagged before they're created. A table of aliases catches the names your dictation gets wrong and maps them back to what they mean. When you're listening rather than reading, answers come back in a few short sentences, no tables, no file paths, no numbers read out to three decimal places, and detail gets offered rather than dumped on you.

## You keep the decisions

Garrick's tools do not push to a remote or send messages. Its rules tell the assistant to obtain approval before sending, publishing or taking irreversible actions. The assistant's own permissions govern what it can execute; written rules are not a replacement for those controls.

The workspace record stays on your disk. Content an assistant reads is processed by its provider under your account's settings and terms. Local storage does not imply offline processing or control the provider's retention. Git records changes when they are committed; it does not preserve every unsaved step.
