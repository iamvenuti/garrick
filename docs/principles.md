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

> Each zone is either **walled** or **open**. What is in a walled zone stays in that zone; what is in an open zone may go anywhere. Knowledge and System reach every zone, and a conversation that touches two walled zones is split before it is filed.

Garrick keeps conversations together in `Wikis/Meetings/`. The walls apply where material is used, not where it is stored. Each Meetings page names its zone. The flag lives in one column of the Zones table in `System/context.md`. You meet the wall only as a refusal that names the fix: "leave the material out, or take the link out".

Different folders inside one zone do not make a wall; a walled zone does. To keep two clients apart, give each its own zone.

### The threat model

Two writers put text into a project: you and the assistant. Both mean well. The harm is one zone's material reaching a file that later leaves the machine. The way it gets there is a mistake: a link pasted from the wrong meeting, a name typed from memory, a paragraph copied across. The check catches what an honest writer writes by accident, in the forms an honest writer uses. A form that needs deliberate disguise to pass is not read, by design, just as a paraphrase is not. The rule the assistant follows is the protection; the check is the seat belt behind it.

A form is sorted by one question: could an honest writer produce it? If yes, the check reads it. If it needs disguise, it is by design. [SECURITY.md](../SECURITY.md#what-is-not-a-vulnerability) and [the known gaps](enforced.md#the-wall-checks-known-gaps) point here and do not restate it.

### What the check covers

The pre-commit hook checks staged files before a commit is saved, in each zone's repository, in `Wikis/` and in any git repository kept inside a project. `check.py --install-hooks` installs it, and the check warns about a repository with a remote and no hook. For a walled zone's material it reads three things:

- **A link that resolves.** A wikilink, a Markdown link, an embed, an HTML link attribute, an autolink or an `obsidian://open?file=` link to a file of another walled zone, resolved as Obsidian resolves it: by path, or by a note's name when it is unique.
- **An exact path.** A token that is the path of a file in the workspace, wikis included, from the top of the vault, from the note's own folder or absolute, with `.md` or without, wherever it is written. A glob, a folder, a bare word and a path with an escape in it resolve to nothing, so they are text.
- **A file copied whole.** A file that holds the same text as a file of another walled zone.

Left out by design: a name typed by hand, which no check matches; a paraphrase; wording moved rather than copied, which only git history shows; anything that does not resolve to a file, a glob included; Word, PowerPoint and PDF contents and other formats the text scan does not read; and a path to a folder. The hook does not stop an initial file write, a chat reply or anything sent. A clean result means the implemented checks found nothing, not that nothing crossed. Review work before you share it. [What is enforced, and what is asked](enforced.md) sets each check beside the rules that depend on the assistant.

The hook must be active in each zone. Git runs a repository's own hooks only while `core.hooksPath` is unset or names that folder. When it points anywhere else, every commit skips the wall check. The installer and the check warn about it, with the command that puts the hooks back.

### One decision for every point

Every point that enforces a wall asks the same three functions in `System/tools/garrick_lib.py`: `zone_of()` says which zone a file belongs to, `walled()` whether that zone is walled, and `may_flow()` whether material of one zone may go into another. The pre-commit check, Ask, Recall, the status page's actions, intake, Nurture and the scaffold tool all use them.

**The one rule.** Material of a walled zone goes only into that zone. Material of an open zone may go anywhere. A file's zone is its path: `Zones/<Zone>/...`. Nothing is derived from a hub, a thread or a sibling. A Meetings page carries one `zone:`; a page with none, or with two, belongs to no zone and flows nowhere.

**Parties stay as an index.** The Parties table routes mail by domain to a zone and holds the names that voice input is matched against. `party:` on a hub, a thread or a Meetings page is optional, so "what did Acme say" finds its pages. No check reads it as a wall.

**Two hats.** One company under two hats is two parties in two zones, and the zone wall holds them apart. Mail from such a company is always asked about.

**Mixed conversations.** A record that touches two walled zones is not filed whole. Intake stops and asks, and on your yes the transcript is cut in the inbox by zone, one file for each. A record already filed is never edited: an extract is a new raw file cut from it. The assistant proposes where a passage belongs; you decide.

**Changing a flag.** `scaffold.py zone --walled` or `--open` is the only way to flip one. Open to walled only restricts: the workspace is rechecked and commits are refused until each file in violation is fixed. Walled to open releases history at once, so the tool says how many files it releases and writes only on your yes. Git holds who changed what.

`tests/walls/cases.md` is the table of what each point must answer, and `check.py --walls-cases` runs it against your own Zones table.

### Filing incoming material

Mail is a conversation too, most of the time, so it goes to the same place. Each zone has an `Inbox/` folder for mail and any other file. Say "process the inbox" and the assistant sorts each item by the rules in the `intake` skill and `System/rules.md`. A mail exchange becomes a mail page in the Meetings wiki, with its zone like any meeting, and from then on the walls treat it exactly as they treat a call. A newsletter or an article goes to Knowledge, with no parties, and a mail filed there loses your own address. A client's document goes into its project's `Sources/` after the assistant applies the wall rules, and when it came attached to a mail, the mail is still filed in Meetings. The zone comes from the mail domains in the Parties table: a domain names a party and its zone only when you have said so, and personal webmail never does. When anything is unclear, the assistant asks and writes your answer down. The check recognises a mail's attachment in `Sources/` only as an exact copy; an edited one is the assistant's to stop.

Fetching and sorting are kept apart. Getting a mail into an inbox is code or a connector, and decides nothing. Deciding where it goes is a rule, and the assistant applies it. Core Garrick never connects to your mail account.

## Zone, project, thread

Three levels, fixed. A [zone](concepts.md#zone) is a side of your life or work, each its own folder and its own git repository. Separate histories make changes easier to scope; the assistant still has to follow the rules about using material across zones. A [project](concepts.md#project) is one client, customer, partner or internal undertaking inside a zone. A folder named `archive` in a zone is not a project: it holds what you retired, such as old to-do lists, and since it belongs to no project, it is checked as part of its zone. A [thread](concepts.md#thread) is one line of work inside a project, with one resume point.

The depth isn't configurable, and that's deliberate: a name you can say aloud only works if there's a fixed number of them to say. "Acme, pricing" tells the assistant exactly which thread you mean because there's nowhere else for a third word to point.

## One resume point per thread

Every thread has exactly one place that says where it stands: the [`### Resume here`](concepts.md#resume-here) block at the top of its `## State of play` section. It says what's live, how to rebuild it, the next single action (small enough to start in two minutes), what is only in your head (*Keep in mind*: the decision half made and why, a doubt, or nothing), who it's waiting on, and the deadline if there is one. Wrapping a thread means rewriting that block so it describes now, then adding a dated entry below it, never editing the old ones. Open the thread months later, cold, and that block is the only thing you need to read first. When something cuts in mid-thought, the same wrap saves your place: it asks one line first (what is only in your head), then runs in the background where the assistant can, and "back" resumes the thread whose note was written most recently. The note is the only record; there is nothing else to keep right. A thread you are not working on but not finished with can be [parked](concepts.md#status): "park X" sets `status: parked`, keeps the note and its block exactly as they are, and takes it out of "what's open" until "wake X". So `check.py` reads every live thread's block and warns when a link or a file path in it leads nowhere: a deliverable renamed or moved turns up in the next check, not in the next cold resume.

## Built to be spoken to

Zone, project and thread names have to survive being said aloud and heard back, which is not the same as giving up the names the work already has: Q4 Planning and ISO 27001 are names, and where the writing does not say how one is said, its note carries the form to hear for it. What is left out is what a folder could not hold or a transcript would mangle. Two siblings that sound alike get flagged before they're created. A table of aliases catches the names your dictation gets wrong and maps them back to what they mean. When you're listening rather than reading, answers come back in a few short sentences, no tables, no file paths, no numbers read out to three decimal places, and detail gets offered rather than dumped on you.

## You keep the decisions

Garrick's tools do not push to a remote or send messages. Its rules tell the assistant to obtain approval before sending, publishing or taking irreversible actions. The assistant's own permissions govern what it can execute; written rules are not a replacement for those controls.

The workspace record stays on your disk. Content an assistant reads is processed by its provider under your account's settings and terms. Local storage does not imply offline processing or control the provider's retention. Git records changes when they are committed; it does not preserve every unsaved step.
