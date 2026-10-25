# Concepts

The words Garrick uses, and what each one means. The rules, the skills and the other pages use them as defined here. For how the parts fit together, see [Architecture](architecture.md); for which protections are code and which are rules, see [What is enforced, and what is asked](enforced.md); for how what the workspace holds is taken in, kept true, used and let fade, see [How Garrick keeps context](context.md).

## The repository and your workspace

### The Garrick repository

The Garrick repository is what you download or clone: the installer, the template a workspace is made from, the extras, these pages and the tests. You do not work in it. You install from it, and later update from a newer copy of it.

### Your workspace

Your workspace is the folder the installer makes from that template, `~/Garrick` by default, and the one you open your assistant in. It holds your notes, your own rules and your own copy of Garrick's tools and skills. It records which Garrick it was made from in `System/garrick-version.json`, so an [update](#update) can tell what you changed from what Garrick wrote. See [What you get](commands.md#what-you-get).

## Where work lives

### Zone

A side of your life or work, such as Work or Personal, in `Zones/<Zone>/`. Each zone is its own git repository, with its own `Todo.md` and `Inbox/`. Nothing moves or is copied between zones unless you ask, and no note links into another zone. See [Zone, project, thread](principles.md#zone-project-thread).

### Project

One client, engagement or undertaking inside a zone, in `Zones/<Zone>/<Project>/`. It names its party, keeps material received in `Sources/` and what is made for it in `Deliverables/`, and holds its threads in `Threads/`. `scaffold.py project` makes one with its first thread: see [Your first project](commands.md#your-first-project).

### Thread

One line of work inside a project, in `Threads/<Thread>/`, with a note of the same name. Every piece of work belongs to a thread, even in a project that has only one, so there is one kind of resume point in one kind of place. You name a thread by the shortest name that is unique: "pricing", or "Acme, pricing" when two projects have one.

### Piece of work

The word the [simple home](#the-simple-home) uses for a thread, and the only unit it shows. Underneath, a piece of work is a project with one thread; a project with several live threads shows one row for each, as *Project, Thread*. "Thread" is the word in the rules and in these pages, for someone who splits a piece of work.

### Spoken form

The `spoken:` line in a hub or thread note's frontmatter: how a name that does not say how it is said is heard, such as `spoken: fourth quarter planning` for Q4 Planning. A request matches it as well as the name. `scaffold.py` asks for one when a project or thread name needs it, and refuses a zone name that cannot be said aloud, since a zone has no note to carry one. See [Voice](../template/System/rules.md#voice) in the rules.

### Hub note

The project's own note, named after it: `<Project>/<Project>.md`. It says what the project is and whose it is, in `party:`, and links every thread, under `## Threads` while it is live and `## Finished` once it is done. Its frontmatter can also change what the check reads in the project: see [Check settings](commands.md#check-settings).

## Picking a thread back up

### Resume here

The `### Resume here` block at the top of a thread note's `## State of play` section. It says where the thread stands, the live artifact and how to rebuild it, the next action, what to keep in mind, who it waits on and the deadline. "Open X" reads it back in two sentences; "wrap X" rewrites it so it describes now and adds a dated entry below it, leaving the older entries as they are. See [One resume point per thread](principles.md#one-resume-point-per-thread).

### Checkpoint

The `### Checkpoint` block a session writes under [Resume here](#resume-here) as the work happens, so a session that ends without a wrap can still be resumed. Three things fire one and nothing else: a file saved for the thread, a decision stated in words that decide, or the next action changing. It holds what was made, what was decided and in whose words, what is only being considered, what is left half done, and the actions to file; everything in it is **unconfirmed**, and only a wrap, a finish or an interrupt confirms anything. It never touches the Resume here block above it, never writes the zone's [`Todo.md`](#todomd), and carries no meeting material. "Open X" reads it back as unconfirmed beside the confirmed point; the next wrap folds it in and removes it. `scaffold.py checkpoint` is the one thing that writes it.

What a checkpoint does not cover, and nothing pretends otherwise:

- work done after the last checkpoint and before the session ended. "Open X" says the time the checkpoint covers, so the gap is visible rather than claimed;
- a session in which none of the three things happened: there is nothing to record and no block;
- an assistant that does not load the rule. It is asked, not enforced: see [What is enforced, and what is asked](enforced.md), and [Claude Code and Codex](harnesses.md#what-has-been-tested) for what has been checked in each;
- a workspace installed before the tool existed. The assistant says so once, and "wrap it" or "hold this" before you leave is what saves the place;
- another machine. The block is not committed and zones are not pushed, so it stays on the machine that wrote it.

No host's close event is used for any of it: none of them fires on a crash, a killed terminal or a closed lid, and none can hold a conversation, so none could supply what an item needs.

### Next action

The row of the Resume here block that names the single next thing, small enough to start in two minutes, and whose it is. Open actions live in the zone's [`Todo.md`](#todomd), and the `todo` skill sweeps each live thread's next action into it, so the two say the same thing.

### Keep in mind

The row for what is only in your head: a decision half made and why, a doubt, or nothing. It is what a cold resume would otherwise lose. "I'm being interrupted" fills it with its third question.

### Status

Every hub and thread note carries `status:` in its frontmatter, with one of three values. `active` is live work. `parked` is set aside and not finished: the note keeps its block and its links, and drops out of "what's open" until "wake X". `done` is finished: its Resume here block becomes `### Outcome`, and the hub lists it under `## Finished`. A parked project parks every thread in it, and the check reports any other value. See [Threads](../template/System/rules.md#threads) in the rules.

### The interruption stack

When something cuts in, "I'm being interrupted" or "hold this" asks three short questions, writes the answers into the thread's Resume here block with the time, and puts the thread on a stack. "Back" opens the thread on top, so the last one held comes back first, and "back to X" takes one from anywhere in it. The stack only keeps the order, in `System/generated/interrupted.json`, which the [Garrick App](#the-garrick-app)'s `page_action.py` keeps; without that extra, the answers are still saved and "back" offers the thread you worked on last. See [Opening and wrapping](commands.md#opening-and-wrapping).

### Catch up

"Catch me up": what changed in a zone's threads over a period, from their history, their notes and the Todo list, one section per thread that moved, each statement linked to the record it rests on. `System/tools/briefing.py` gathers it and decides nothing; the `threads` skill writes it. Shown, not saved, unless it covers one project and you say yes to saving it. See [Opening and wrapping](commands.md#opening-and-wrapping).

### `System/briefing.md`

What a catch-up raises first, says in a line, and leaves out, in plain words: "a decision, with who took it and why" comes first, a commit that only tidied the Todo list is left out. Garrick's, replaced by each update; yours goes in `System/briefing.local.md`, which wins.

### What's next

"What's next", or "what should I do while I wait": one thing worth doing elsewhere while a long turn runs. `System/tools/next_up.py` ranks it by plain rules, never the thread in focus: the top of the interruption stack, Todo lines due today or late, chases come due, what waits in an inbox, a thread parked for 30 days, a live one not wrapped for 14. The assistant reads the first pick and offers to open or tick it; it never acts on its own. [The Garrick band](#the-garrick-band) shows the same list while a turn runs.

## Parties and walls

### Party

An organisation or person whose confidences you hold. Each has a tag, one lowercase word, which a project or thread carries in `party:` and a meeting page in `parties:`. The tag is what the walls are checked against, so a project without one cannot draw on the Meetings wiki until it has one.

### Wall

A declared pair of parties whose material must not meet. With a wall between them, nothing from a meeting with one goes into the other's projects: not quoted, not paraphrased, not summarised. A wall exists only when you list the pair in the Walls table of `System/context.md`; separate folders and different tags do not make one. The assistant is asked to read the table before it uses a meeting, and the [wall check](#the-wall-check) refuses some crossings at commit. See [One memory, walled use](principles.md#one-memory-walled-use).

### The Parties table

The table in `System/context.md` that lists every party: its name, what it is, its zone, its tag and the mail domains that name it. A listed domain names its party when mail comes in, and personal webmail never names one. `scaffold.py party` adds a row and offers the tag itself.

### People

The table in `System/context.md` of the people who come up, one row per person and party. The wall check reads it to recognise a name from across a wall. Someone known on both sides of a wall can have a row under each party, and their name then no longer counts as crossing it, with one known gap described in [What is enforced](enforced.md#the-wall-checks-known-gaps).

### Aliases

The table in `System/context.md` that maps names your dictation gets wrong to what they mean. The assistant matches every proper noun against Parties, People and Aliases before acting on it, and adds a row when it had to ask what a heard name meant. See [Voice](../template/System/rules.md#voice) in the rules.

### `System/context.md`

Who you are and who you deal with: Me, Zones, Parties, Walls, People and Aliases. It is yours, filled in from your answers at install, and every session reads it.

### Learned entry

Something one session wrote down and later sessions read as fact: an entry in your assistant's own memory, or a row the assistant added to a table in `System/context.md`, such as an alias it had to ask about. Each says where it came from. A memory entry carries `source:` and `created:` in its frontmatter, at the top or under `metadata:` where an assistant keeps keys of its own; a row carries a Learned cell, `2026-10-16, user`. The source is `user` (you said it), `file:<path>` (a note in the workspace) or `inbound:<raw path>` (a mail, a transcript or a page). Rows you typed yourself have no Learned cell. What the assistant may write down without asking depends on what acting on it would do: a pointer or an alias goes ahead, a domain or a destination waits for your yes, and something that only a mail or a page said is never kept as a belief until you confirm it. See [Autonomy](../template/System/rules.md#autonomy) in the rules. The check warns about a learned entry with no origin, and one whose only source is inbound, once `memory` in the [check settings](commands.md#check-settings) names your assistant's memory folder.

### Correction

What "that's wrong, it's Y" does: `System/tools/correct.py` lists every live copy of the wrong value, in memory, `System/context.md`, hubs, thread notes, `Todo.md` and the wikis, and on your one yes fixes them all, one commit per repository. Live files then show only the right value; git keeps the old one. A raw record is never edited: the page that rests on it gets `superseded:` in its frontmatter and a line saying so. See [Correcting a value](commands.md#correcting-a-value).

## The two wikis

### The Meetings wiki

`Wikis/Meetings/`: every conversation and mail exchange, from every zone, one page each, with its zone and its parties. A page without both is unfinished, and nothing on it may be used in any project until it has them. It keeps everything in one place, and the walls decide where its material may be used. Its schema is in its [`AGENTS.md`](../template/Wikis/Meetings/AGENTS.md).

### The Knowledge wiki

`Wikis/Knowledge/`: published material you read, such as articles, reports and newsletters. Its pages carry no parties, because what they hold carries nobody's confidence, so it can be used in any project.

### `raw/`

Each wiki keeps the record as it arrived in `raw/`, such as a transcript, a mail or a frozen copy of a page, and writes its pages in `wiki/`. Nothing in `raw/` is edited, and the check reports a raw record changed after it was filed. A page that fades takes its raw record with it, renamed and unchanged.

### Fading

Old pages leave working memory by age, kind and use, and stay findable: *working* pages are in `wiki/` and its index; *dormant* ones in `dormant/wiki/`, listed in `wiki/index-dormant.md`, read when a search reaches back and says so; *archived* ones in `archive/wiki/`, read only when you ask. A page a live thread, a live project or an open action links, or one carrying `pinned: true`, which "keep X" writes, never fades; one carrying `superseded:` never comes back by use. "Fade the meetings" writes the list and moves nothing, and a yes moves exactly that list, rewriting every link so nothing breaks. Nothing is deleted. See [Fading](commands.md#fading).

### `System/retention.md`

The judgment about what to keep that the months in the settings can't hold, in plain words: "a meeting where a decision was taken outlives one that only exchanged updates". Garrick's, replaced by each update; yours goes in `System/retention.local.md`, which wins.

## Keeping the record true

### Nurture

"Nurture the context", or "nurture Work" for one scope: the `nurture` skill gathers what `check.py`, `wiki_lint.py` and `drift.py` found and sorts it by what a fix needs. Mechanical fixes, such as a link broken by a rename, are applied on one yes, one commit per repository; an attribution is asked one line at a time; a wall finding names the file and the wall, never the material; a judgment is left alone, with the page to open. It adds no checks of its own. See [Nurturing the context](commands.md#nurturing-the-context).

### Context debt

What a Nurture run leaves, weighed by kind: a wall finding 10, an attribution question or a correction 5, a judgment finding or a mechanical fix not yet made 1. A run of the whole workspace measures it, and a scoped run updates only its own scope's part. Each day's figure is kept in `System/generated/nurture/`, and the Garrick App's Checks card shows the last 30 days. Before the first run there is no figure at all. See [Context debt](commands.md#context-debt).

## What comes in

### Ways in

The routes material takes into the workspace: recordings, mail and files you drop in. Getting an item here is fetching, by hand, by a script or by your assistant's own connector, and it decides nothing. Where each item goes is decided by the [Ways in](../template/System/rules.md#ways-in) rules, one item at a time. See [Ways in](extras/ways-in.md).

### Inbox

Where everything lands first: a recording's transcript in `Wikis/Meetings/raw/inbox/`, and mail and any other file in a zone's `Inbox/`. An inbox is never a project, and nothing in one is committed: the pre-commit hook refuses it.

### Intake

The skill that empties the inboxes, started by "process the inbox". It files a conversation into Meetings, something to read into Knowledge and material for a project into that project's `Sources/`, and asks when the zone, a party or the project is unclear. See [The two memories](commands.md#the-two-memories).

### Brief

What "prep me for X" puts together before a meeting: the Meetings pages for that party or person, newest first, and what is still open with them in the zone's `Todo.md`, checked against the walls of the project it is for. It answers in the conversation and writes nothing, unless you say yes to saving it in the project's `Deliverables/`. The `meetings` skill makes it.

## Actions

### `Todo.md`

Each zone's one list of open actions, in Obsidian Tasks style. A line opens with its thread's link and ends with its dates: `📅` when it is due, or `#waiting` and `⏳` for the day to chase something you wait on. A thread note says where the work stands and is not a to-do list; the `todo` skill sweeps actions the records hold into the list's Inbox section and tidies the rest. The list holds actions, never records: a line is ticked as it was written, what came of it goes in the thread note's dated entry, and work that was never on the list gets no line. Lines ticked before today move to the zone's `archive/`, at the nightly sweep and at every wrap.

## Instructions

### Garrick's rules, and yours

`System/rules.md` is Garrick's: how the assistant behaves, as shipped, and each update replaces it. `System/rules.local.md` is yours: it adds to Garrick's and wins where the two differ, and no update touches it. See [Garrick's rules, and yours](principles.md#garricks-rules-and-yours).

### The `.local` files

Each of Garrick's instruction files has a local file beside it for your own text: `rules.local.md` beside `rules.md`, and `AGENTS.local.md` beside an `AGENTS.md`. Garrick never ships, lists or changes them, so an update never has to merge your words into its own. The check warns when one of Garrick's files differs from what it shipped, and the update's split moves your text across: see [Updating](updating.md#your-rules-and-garricks).

### `AGENTS.md`

The entry point any assistant reads, at the workspace root, in each zone, in `Wikis/` and in each wiki. The root one sends the assistant to `rules.md` and `context.md`, and each zone's or wiki's adds what holds only there. They are Garrick's, as shipped; never create a `CLAUDE.md` in the workspace, since Claude Code stops reading every `AGENTS.md` once one exists.

## Tools and assistants

### Skill

A procedure written in Markdown, `System/skills/<name>/SKILL.md`, which the assistant follows when a request matches it: `threads` for "open X" or "wrap it", `intake` for "process the inbox". Both supported assistants find the same skills, through links in `.claude/skills` and `.agents/skills`. See [the skills](architecture.md#the-skills).

### Tool

A Python script in `System/tools/`, standard library only, for what code does better than an assistant: `check.py`, `scaffold.py` and the others. Tools move, parse, check and list; they never choose where a thing goes. See [the tools](architecture.md#the-tools).

### Harness

The assistant program that runs the model and works on your files: Claude Code or Codex, in its desktop app or a terminal. No rule, template or skill names either one, so the same workspace opens in both. See [Assistant compatibility](harnesses.md).

### The interview

The `interview` skill, the opening move in a new workspace: "interview me". It asks about what you do, for whom and whose confidences you hold, one question at a time, keeping a record in `System/interviews/` as it goes. Then it proposes the first parties, walls, projects, threads and open actions, and sets them up only on your yes.

### Setup

The `setup` skill, the first run: "set up Garrick". It finds out what your Mac has and how you work, writes it to `System/setup.md` so every later session knows, fixes what is missing on a yes, then hands over to the interview, or fills in the resume points of the projects already there. "Add a rule" and "set up notifications" are its too.

### Listening mode

How the assistant answers when you are listening: when you say so, or the request came in by voice. The answer comes first, in three sentences at most, with no tables, code, file paths or links read out, and numbers rounded. The detail is offered rather than given. See [Voice](../template/System/rules.md#voice) in the rules.

## Checks and guards

### The check

`python3 System/tools/check.py`, which tests the workspace against every rule a machine can check and lists errors and warnings. Run by hand, it is a report: it changes nothing and stops nothing. See [The check](commands.md#the-check).

### The wall check

The part of the check about walls. Each zone's pre-commit hook runs it as `check.py --staged --walls-only` and refuses a commit whose project files link to, name or quote a party across a declared wall. It has limits and known gaps: see [What the check covers](principles.md#what-the-check-covers) and [What is enforced](enforced.md).

### `System/generated/`

The folder the tools write their pages into, such as the Garrick App's page, Nurture's daily reports and what Continue keeps of each session. It belongs to the tools: never edit a file there or file anything there, and never commit it. The next build replaces what is there, and the check reports a generated page that is committed.

### The zone guard

An optional hook for Claude Code and Codex. Before the assistant edits a file outside the project the session was opened in, it stops once so the assistant asks you. It is a reminder, not a gate, and a shell command that writes a file is not covered. See [the zone guard](../extras/hooks/README.md).

## Extras

### Extras

Optional tools the repository ships in `extras/` for a workspace to take on, such as the Garrick App, scheduled jobs, desk and the zone guard. Core Garrick never depends on any of them. The installer puts in one, the Garrick App's, in a workspace that opens on the simple home; the rest you add yourself. See [Extras](extras/index.md).

### The Garrick App

The control panel over your zones, projects and threads, and not where the work happens: it opens a piece of work in the app you work in. It is one HTML page, built by `status.py` into `System/generated/status.html`, shown in the Mac app, in Obsidian or in a browser. It opens on the [simple home](#the-simple-home) or on the full page, whose tabs are Overview, Todo, Status and the [Guide](#the-guide). Its buttons can also act, such as parking a thread or ticking a Todo line, each through one declared operation and committed in the zone; in a browser they copy what to say instead. Its code keeps the old name, the status page, in `extras/status/`. See [the Garrick App](extras/status-page.md).

### The Mac app

*Garrick.app*, which shows the Garrick App in a window of its own, in the Dock and the menu bar. It rebuilds the page when it is old, and its buttons act. `make-app.sh` builds it on your Mac, signed for that Mac only, and "Set up Garrick" offers to run it. See [A Mac app](extras/status-page.md#a-mac-app).

### The simple home

What a new workspace's Garrick App opens on: *Your work*, every live piece of work, most recent first, each with its next action; *Ask something*, one box for a question about any of your work; and *Needs you*, the questions Garrick is waiting on you to answer. Everything else is under *More*, and *Settings › Home* switches between *Simple* and *Full*. See [The simple home](extras/simple-home.md).

### Continue

The button on a piece of work in the simple home, and *Open in Claude* on the full page. It commits Garrick's own record of the work, asks Claude where the work stands without a window, and opens Claude's desktop app on that session with the answer already on screen. It needs the Claude Code command-line tool, signed in with the same account; in a browser it copies the words to say. *Ask something* works the same way, with your words. See [Continue](extras/simple-home.md#continue).

### Needs you

A question Garrick is waiting on you to answer, blocking one piece of work. Each is a file in that work's `Needs you/` folder, committed like any note, with its options as buttons on the home. An answer sets the work's next action and commits; *Not now* brings it back the next day. Warnings and check findings never go there. See [Needs you](extras/simple-home.md#needs-you).

### Stop using this

The button at the foot of a piece of work's page that puts Garrick's record of it away: its project moves into the zone's `archive/`, in one commit, and its folder of files is left as it was. *Bring it back* returns the record where it stood. Nothing is deleted. See [Your own work](extras/simple-home.md#your-own-work).

### The Guide

The Garrick App's fourth tab: these pages, as the release your workspace runs shipped them, in `System/garrick-docs/`, which each update replaces. A link between two pages stays in the tab, and a link into Garrick's own files opens on GitHub at that release. Your assistant answers "what is a wall" from the same copy. See [the Garrick App](extras/status-page.md#the-guide).

### The worked example

Robin Hale's made-up work at Quillfield Furniture, in a zone of its own called `Example`, for trying Garrick before your own work is in it. `install.py --example` adds it, its pieces of work are marked *Example*, and *Remove the example*, or `System/tools/example.py archive`, puts it away without touching anything of yours. See [The example](extras/simple-home.md#the-example).

### Desk

The skill that comes with the cmux extra: one cmux tab per thread, opened, wrapped and closed by voice or from the Garrick App, and brought back the next day. See [cmux](extras/cmux.md).

### The Garrick band

A Claude Code mod, optional: the current thread and the first paragraph of its Resume here block above the prompt, buttons that ask for *Resume* or *Wrap*, and file paths in replies you can Cmd-click. It shows what the notes already say and enforces nothing. See [the Garrick band](../extras/mods/README.md).

## Updates

### Update

Bringing your workspace up to a newer Garrick without losing what you changed. "Update Garrick", or `release.py update`, downloads the newest release and runs its `install.py --update`, which says what would change and changes it only with `--apply`. See [Updating](updating.md).

### A `.new` file

When you changed a file that Garrick has changed too, the update leaves yours as it is and puts Garrick's version beside it as `<name>.new`, committed, for you to merge. "Merge the update" does it with you, and the check warns while one waits. See [Merging a `.new` file](updating.md#merging-a-new-file).

## Deliverables

### Deliverable

Anything made for someone else: a deck, a workbook, a brief, a draft. It lives in a project's `Deliverables/`, or a thread's own in a project whose hub says `layout: thread-first`.

### The `YYMMDD -` prefix

A deliverable's name starts with the date it was first made, such as `260930 - Pricing deck.pptx`. The date never moves, so a folder sorts by when the work started. Build intermediates, scripts and a folder's `README.md` keep plain names, and the check warns about a deliverable without the prefix.
