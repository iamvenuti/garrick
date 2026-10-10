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

The installed pre-commit hook checks staged project files before saving a commit. For declared walls, it can reject links to walled meeting pages, configured names and aliases from the other party, and runs of eight words with enough content words that are held only across a wall: in a walled meeting page or its transcript, or in any text file of a project on the far side, its `Sources/` included. A link to a meeting page that has no zone or parties yet, or eight words from one, is refused whatever the walls, since nothing on an unfinished page may be used. The finding names the file and the walled party, never the words that matched.

At commit time the hook reads everything it is not committing, the meetings and the other projects, as git holds it as well as from disk: from the index in the repository being committed, from the last commit in every other. Taking a sentence out of a meeting page or another project's note without saving that change in git does not hide where the sentence came from. If a project or thread note names a different party on disk from the one staged, the commit is refused until you stage that change or undo it, so the walls are checked against the party the commit records.

Some matches are not evidence, and are left out. Wording counts as common when it also appears in a file every side reads by design: the instruction files, `System/rules.md` and `System/context.md`, the skills, templates and tools in `System/`, and the Knowledge wiki. Nothing else in `System/` counts. An interview record holds your answers in your own words, and a page a tool rebuilds into `System/generated/`, such as the status page, can gather every zone at once. Either can carry what one party said, so nothing they repeat counts as common. Wording also held on your side of the wall passes too: in a meeting your party was in, in another project's file on your side, or in your project's own `Sources/`. Notes in the same project never vouch for each other, so a leak copied twice is still caught. Where a link points is not wording, and no run of words crosses a Markdown heading. The text of a link to a shared file, such as a Knowledge page's title, is common wording too, so two notes that list the same Knowledge pages do not match. Dates do not count as content words, so two notes wrapped on the same day do not match by chance. Certain ambiguous first names are not matched alone.

Project `Sources/` files hold what a party sent, which can name other parties or repeat what another party sent, such as a supplier's standard terms. They are exempt from the name check and from the comparison with other projects' files: their wording is compared with meetings only. When the same words sit in notes on both sides of a wall and nowhere else, the check cannot tell which came first, so it names both files. Wording you reuse on purpose for every client, such as a disclaimer, belongs in a template under `System/templates/`, where it counts as common.

The full check also covers the pages every side reads. A person page in `Wikis/Meetings/wiki/people/` needs a known party, or `party: none`, and is warned about when it repeats eight words from a meeting. A Knowledge page must not carry `party`, `parties` or `zone`, or link into Meetings, and is warned about when it or its raw record shares eight words with a meeting: its wording counts as common everywhere, so a conversation copied there would cross every wall. Nothing waiting in an inbox, a zone's `Inbox/` or `Wikis/Meetings/raw/inbox/`, may be committed, however deep in a folder it sits.

The text scan covers Markdown, plain text, CSV/TSV, HTML, JSON, YAML and VTT files up to 2 MB. An HTML page is read as the text a browser shows: its styles, scripts, comments, tags and attributes are left out, so two pages built from one template do not match on their code. Files a zone's repository ignores are not read, since they never enter its history, and nor is anything in a folder named `node_modules`, `.venv`, `__pycache__` or `dist`. The walls do not inspect the contents of generated Word, PowerPoint or PDF deliverables; only a project marked `anonymous` has the text of its Word, Excel and PowerPoint deliverables read, for names. A separate check can match an exact mail attachment copied into `Sources/`; that is a byte comparison, not a content scan of those formats.

A clean paraphrase, shorter copied passage or edited attachment can pass, and so can a document copied by hand into a project's `Sources/`. So can wording moved rather than copied: cut a passage from one party's note, paste it into another's and commit both, and only the git history still shows where it came from. The check does not read history. The hook does not prevent an initial file write, chat reply or transmission, and it does not isolate the assistant from the shared memory. It also cannot infer a wall you have not declared. A successful check means those implemented checks found no issue; it is not a guarantee of confidentiality. Review work before sharing it, including any exported document.

The hook must be active in each zone. Git runs a repository's own hooks only while `core.hooksPath` is unset or names that folder. When it points anywhere else, whether set for the repository, for your user or for the whole machine, every commit skips the wall check. The installer warns about it, and the check warns for each zone and for the Wikis repository, with the command that puts the hooks back. Bypassing the hook skips this protection.

### Filing incoming material

Mail is a conversation too, most of the time, so it goes to the same place. Each zone has an `Inbox/` folder for mail and any other file. Say "process the inbox" and the assistant sorts each item by rules written in `System/rules.md`, not in code. A mail exchange becomes a mail page in the Meetings wiki, with its zone and parties like any meeting, and from then on the walls treat it exactly as they treat a call. A newsletter or an article goes to Knowledge, with no parties, and a mail filed there loses your own address on the way, from its headers, its footer and its unsubscribe link. A client's document goes into its project's `Sources/` after the assistant applies the wall rules, and when it came attached to a mail, the mail is still filed in Meetings. The parties come from the mail domains in the Parties table: a domain names a party only when you have said so, and personal webmail never does. When anything is unclear, the assistant asks rather than picks, and writes your answer down so the next mail from that domain files itself. The check before a commit recognises a mail's attachment in `Sources/` only as an exact copy: an edited copy gets past it, the same way a clean paraphrase does, and stopping that is the assistant's job.

Fetching and sorting are kept apart. Getting a mail into an inbox is code or a connector: you, a mail rule, an optional script, or your assistant's own mail connector. It decides nothing. Deciding where it goes is a rule, and the assistant applies it. Core Garrick never connects to your mail account.

## Zone, project, thread

Three levels, fixed. A zone is a side of your life or work, each its own folder and its own git repository. Separate histories make changes easier to scope; the assistant still has to follow the rules about using material across zones. A project is one client, customer, partner or internal undertaking inside a zone. A folder named `archive` in a zone is not a project: it holds what you retired, such as old to-do lists, and since it belongs to no project, no party's walls are checked against it. A thread is one line of work inside a project, with one resume point.

The depth isn't configurable, and that's deliberate: a name you can say aloud only works if there's a fixed number of them to say. "Acme, pricing" tells the assistant exactly which thread you mean because there's nowhere else for a third word to point.

## One resume point per thread

Every thread has exactly one place that says where it stands: the `### Resume here` block at the top of its `## State of play` section. It says what's live, how to rebuild it, the next single action, who it's waiting on, and the deadline if there is one. Wrapping a thread means rewriting that block so it describes now, then adding a dated entry below it, never editing the old ones. Open the thread months later, cold, and that block is the only thing you need to read first. A thread you are not working on but not finished with can be parked: "park X" sets `status: parked`, keeps the note and its block exactly as they are, and takes it out of "what's open" until "wake X". So `check.py` reads every live thread's block and warns when a link or a file path in it leads nowhere: a deliverable renamed or moved turns up in the next check, not in the next cold resume.

## Built to be spoken to

Zone, project and thread names have to survive being said aloud and heard back: no codes, no digits but a year said as a word of its own, no punctuation that a transcript can mangle. Two siblings that sound alike get flagged before they're created. A table of aliases catches the names your dictation gets wrong and maps them back to what they mean. When you're listening rather than reading, answers come back in a few short sentences, no tables, no file paths, no numbers read out to three decimal places, and detail gets offered rather than dumped on you.

## You keep the decisions

Garrick's tools do not push to a remote or send messages. Its rules tell the assistant to obtain approval before sending, publishing or taking irreversible actions. The assistant's own permissions govern what it can execute; written rules are not a replacement for those controls.

The workspace record stays on your disk. Content an assistant reads is processed by its provider under your account's settings and terms. Local storage does not imply offline processing or control the provider's retention. Git records changes when they are committed; it does not preserve every unsaved step.
