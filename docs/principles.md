# Principles

## Everything is folders on your disk

A Garrick workspace is Markdown files in folders, under git. No database, no app, no account. `System/context.md` is a table you can open and edit by hand. A thread's whole history is the commits in its zone's repository. If you can read a text file, you can read everything the assistant knows about your work. [Architecture](architecture.md) shows how the folders, rules and tools fit together.

## Harness independence, and a test for it

The entry point is `AGENTS.md`, a plain file, not a setting inside one vendor's app. Claude Code and Codex both read it. No rule, template or skill names either one; the only mention is a safety warning, in `AGENTS.md` and `check.py`, about the `CLAUDE.md` file that would stop Claude Code reading `AGENTS.md`.

The installer links the shared skills into `.claude/skills` and `.agents/skills` in every workspace repository. The rules, context and resume notes remain ordinary files whichever assistant opens them.

Try switching by opening the same workspace in another supported assistant and asking it to read the instructions, then resume a thread. The saved record and git history remain available. Account settings, permissions, private chat history and unsaved context are separate. There is no need to delete either assistant's settings to test portability.

## Garrick's rules, and yours

`System/rules.md` and the `AGENTS.md` at the root, in each zone and in each wiki are Garrick's, and stay exactly as it ships them. Your own rules and routing go in the local file beside each: `System/rules.local.md`, and an `AGENTS.local.md` beside an `AGENTS.md`. Garrick never ships, lists or changes those. Each of Garrick's files says near its top to read the local one next, and the local one adds to it and wins where the two differ.

So an update never has to merge your words into Garrick's. It replaces Garrick's file and leaves yours alone. `check.py` warns when one of Garrick's differs from what it shipped, and the update's split moves what you wrote there into the local file: see [Updating](updating.md#your-rules-and-garricks).

## One memory, walled use

> Every party you deal with is either **walled** or **open**. A walled party's material goes only into work that names that party. An open party's material may go anywhere. A file belongs to the parties of its zone and of the note above it, the thread's or the project's. Nothing else to declare: a project is walled when one of its parties is, a conversation with two walled parties waits for you to say where it goes, and a record with no label is used nowhere.

Garrick keeps conversations together in `Wikis/Meetings/`. The walls apply where material is used, not where it is stored. Each Meetings page names its zone and parties. The flag lives in one column of the Parties table in `System/context.md`, and a zone's own party and its default for new parties in the Zones table. You meet the wall only as a refusal that names the fix: "name X in this project, or leave the material out".

Different folders do not make a wall; a walled party does. To keep two internal projects apart, give each its own walled party.

### The threat model

Two writers put text into a project: you and the assistant. Both mean well. The harm is one party's material reaching a file that later leaves the machine. The way it gets there is a mistake: a link pasted from the wrong meeting, a name typed from memory, a paragraph copied across. The check catches what an honest writer writes by accident, in the forms an honest writer uses. A form that needs deliberate disguise to pass is not read, by design, just as a paraphrase is not. The rule the assistant follows is the protection; the check is the seat belt behind it.

A form is sorted by one question: could an honest writer produce it? If yes, the check reads it. If it needs disguise, it is by design. [SECURITY.md](../SECURITY.md#what-is-not-a-vulnerability) and [the known gaps](enforced.md#the-wall-checks-known-gaps) point here and do not restate it.

### What the check covers

The pre-commit hook checks staged files before a commit is saved, in each zone's repository, in `Wikis/` and in any git repository kept inside a project. `check.py --install-hooks` installs it, and the check warns about a repository with a remote and no hook. For a walled party's material it reads four things:

- **A link that resolves.** A wikilink, a Markdown link, an embed, an HTML link attribute, an autolink or an `obsidian://open?file=` link to a file a project may not use, resolved as Obsidian resolves it: by path, or by a note's name when it is unique.
- **An exact path.** A token that is the path of a file in the workspace, wikis included, from the top of the vault, from the note's own folder or absolute, with `.md` or without, wherever it is written. A glob, a folder, a bare word and a path with an escape in it resolve to nothing, so they are text.
- **A name from the tables.** A party, person or alias from the Parties, People and Aliases tables, or from a project's walled party. Never the owner's own name or first name: a walled person who shares it is matched by full name only, and a walled tag that is an everyday word, not the party's name, only as a tag, not in prose. A People row with a one-word name (`Kit`) refuses only beside the party's name, another of its people, a second one-word person of the party, or as a link to the person's page; on its own it is a warning, and Nurture proposes the full name.
- **Eight shared words.** A run of eight words with enough content words that appears only in material the project may not use, such as a walled meeting page, its transcript, or a project that names a walled party this one does not. Wording every side reads by design, such as the skills, the templates in `System/templates/` and `System/templates.local/` (yours, where you put text on purpose; the check warns about a file there that names a party or carries a party key) and the Knowledge wiki, does not count.

Left out by design: a paraphrase; wording moved rather than copied, which only git history shows; anything that does not resolve to a file, a glob included; Word, PowerPoint and PDF contents and other formats the text scan does not read; and a path to a folder. The hook does not stop an initial file write, a chat reply or anything sent. A clean result means the implemented checks found nothing, not that nothing crossed. Review work before you share it. [What is enforced, and what is asked](enforced.md) sets each check beside the rules that depend on the assistant.

The hook must be active in each zone. Git runs a repository's own hooks only while `core.hooksPath` is unset or names that folder. When it points anywhere else, every commit skips the wall check. The installer and the check warn about it, with the command that puts the hooks back.

### One decision for every point

Every point that enforces a wall asks one function, `decide()` in `System/tools/garrick_lib.py`: the pre-commit check, Ask, Recall, the status page's actions, intake, Nurture and the scaffold tool. It answers `permit`, `deny` or `confirm`. `confirm` is a question for you: nothing goes on without your answer.

**The one rule.** Material may go into a record only when every walled party on the material is one of the record's parties. Open parties never block; walled parties protect. A project is walled when one of its parties is. That is derived, never set.

**Labels come from the nearest note.** A file's parties are its zone's and those of the note above it. A thread's file carries the thread note's parties and the hub's; any other file of the project carries the hub's. Nothing comes from sibling threads, so moving a thread moves its material with it. `party:` takes one tag or a list, and a thread adds parties, never removes one. A hub with no `party:` labels nothing, and nothing may be written into its project. A tag the Parties table lacks, and a record with no label, are used nowhere. A project put away in a zone's `archive/` keeps its hub's `party:`, so its files stay labelled. Any other file under a zone's `archive/`, or under a hidden folder, has no label by design, and a link to it from a project is refused. A file never carries fewer parties than the rule gives it: output that must carry fewer is written as new text in the narrower project, and if it quotes a walled source the check refuses it.

**Naming two walled parties on one note is the yes.** A project that names Maple and Harbour holds both, and adding the second through `scaffold.py` says so before it writes. The exception is one company under two hats: a note never names two parties that share a name, and mail from such a company is always asked about.

**Mixed conversations.** A record with two walled parties enters only a project naming both. Intake stops and asks, and on your yes the transcript is cut in the inbox by label set, one file for each. A record already filed is never edited: an extract is a new raw file cut from it, and the original keeps its full labels. The assistant proposes where a passage belongs; you decide.

**Changing a label.** `scaffold.py party --walled` or `--open` is the only way to flip a flag. Open to walled only restricts: the workspace is rechecked and commits are refused until each file in violation is fixed. Walled to open releases history at once, so the tool says how many files it releases and writes only on your yes. Git holds who changed what.

`tests/walls/cases.md` is the table of what each point must answer, and `check.py --walls-cases` runs it against your own tables, with your tags in place of the fixture's.

### Filing incoming material

Mail is a conversation too, most of the time, so it goes to the same place. Each zone has an `Inbox/` folder for mail and any other file. Say "process the inbox" and the assistant sorts each item by the rules in the `intake` skill and `System/rules.md`. A mail exchange becomes a mail page in the Meetings wiki, with its zone and parties like any meeting, and from then on the walls treat it exactly as they treat a call. A newsletter or an article goes to Knowledge, with no parties, and a mail filed there loses your own address. A client's document goes into its project's `Sources/` after the assistant applies the wall rules, and when it came attached to a mail, the mail is still filed in Meetings. The parties come from the mail domains in the Parties table: a domain names a party only when you have said so, and personal webmail never does. When anything is unclear, the assistant asks and writes your answer down. The check recognises a mail's attachment in `Sources/` only as an exact copy; an edited one is the assistant's to stop.

Fetching and sorting are kept apart. Getting a mail into an inbox is code or a connector, and decides nothing. Deciding where it goes is a rule, and the assistant applies it. Core Garrick never connects to your mail account.

## Zone, project, thread

Three levels, fixed. A [zone](concepts.md#zone) is a side of your life or work, each its own folder and its own git repository. Separate histories make changes easier to scope; the assistant still has to follow the rules about using material across zones. A [project](concepts.md#project) is one client, customer, partner or internal undertaking inside a zone. A folder named `archive` in a zone is not a project: it holds what you retired, such as old to-do lists, and since it belongs to no project, no party's walls are checked against it. A [thread](concepts.md#thread) is one line of work inside a project, with one resume point.

The depth isn't configurable, and that's deliberate: a name you can say aloud only works if there's a fixed number of them to say. "Acme, pricing" tells the assistant exactly which thread you mean because there's nowhere else for a third word to point.

## One resume point per thread

Every thread has exactly one place that says where it stands: the [`### Resume here`](concepts.md#resume-here) block at the top of its `## State of play` section. It says what's live, how to rebuild it, the next single action (small enough to start in two minutes), what is only in your head (*Keep in mind*: the decision half made and why, a doubt, or nothing), who it's waiting on, and the deadline if there is one. Wrapping a thread means rewriting that block so it describes now, then adding a dated entry below it, never editing the old ones. Open the thread months later, cold, and that block is the only thing you need to read first. When something cuts in mid-thought, the same wrap saves your place: it asks one line first (what is only in your head), then runs in the background where the assistant can, and "back" resumes the thread whose note was written most recently. The note is the only record; there is nothing else to keep right. A thread you are not working on but not finished with can be [parked](concepts.md#status): "park X" sets `status: parked`, keeps the note and its block exactly as they are, and takes it out of "what's open" until "wake X". So `check.py` reads every live thread's block and warns when a link or a file path in it leads nowhere: a deliverable renamed or moved turns up in the next check, not in the next cold resume.

## Built to be spoken to

Zone, project and thread names have to survive being said aloud and heard back, which is not the same as giving up the names the work already has: Q4 Planning and ISO 27001 are names, and where the writing does not say how one is said, its note carries the form to hear for it. What is left out is what a folder could not hold or a transcript would mangle. Two siblings that sound alike get flagged before they're created. A table of aliases catches the names your dictation gets wrong and maps them back to what they mean. When you're listening rather than reading, answers come back in a few short sentences, no tables, no file paths, no numbers read out to three decimal places, and detail gets offered rather than dumped on you.

## You keep the decisions

Garrick's tools do not push to a remote or send messages. Its rules tell the assistant to obtain approval before sending, publishing or taking irreversible actions. The assistant's own permissions govern what it can execute; written rules are not a replacement for those controls.

The workspace record stays on your disk. Content an assistant reads is processed by its provider under your account's settings and terms. Local storage does not imply offline processing or control the provider's retention. Git records changes when they are committed; it does not preserve every unsaved step.
