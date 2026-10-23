# Command reference

For everyday app use, follow [Desktop first steps](first-steps.md), then [Your first useful session](first-session.md). For a CLI workflow, start with [Terminal setup](terminal-setup.md). This page is the detailed reference for the installer and workspace tools; your assistant can run them for you.

Requires macOS, Python 3.9 or later, and git. If `git --version` fails, run `xcode-select --install` and wait for it to finish. You also need Claude Code or Codex. Claude Code reads `AGENTS.md` natively from version 2.1.277; `claude --version` tells you which one you have.

## Install

From the folder Garrick came in, `~/Downloads/garrick` for the download or `~/garrick-source` for a clone:

```sh
python3 install.py
```

This asks a few questions, one at a time: where the workspace should go (default `~/Garrick`; a folder name on its own, such as `Garrick-work`, goes in your home folder), your name and a one-line description of what you do, your zones (default `Work, Personal`) and what each holds, then who you work for or with, and last whether the assistant may run Garrick's own tools and git's commands that look at or save history without asking each time ([what that allows](first-steps.md#the-commands-it-asks-to-approve)). Press Enter to accept the default in brackets. Who you work for or with is one line of names separated by commas, and Enter skips it. Each name becomes a party, an organisation or person whose confidences you hold, with a tag taken from the name, such as `acme` for Acme Corp; the installer asks which zone it belongs to only when you have more than one. That is all it asks. Mail domains, walls, people and the aliases dictation needs come later, in your first session, where you can see what each one changes: say "interview me" and the assistant asks about them one at a time, or ask it to add a party or a wall. A wall is an explicit pair of tags whose material must not be used in each other's projects. Separate folders and different party tags do not create walls automatically, and the installer declares none. Zones added later follow [Another zone](#another-zone).

To skip the questions (for a demo, a test, or a guided session), pass a config file:

```sh
python3 install.py --config examples/acme.json --target ~/Garrick-acme
```

`examples/acme.json` is a complete fictional setup (an advisor with two clients, Acme Corp and Birch & Co, walled from each other). Copy it and edit it as a starting point for your own config. Its keys are `owner`, `zones`, `parties`, `walls`, `people`, `aliases`, and `allow-commands`, the last question, which is `true` unless the file says `false`, so a config run asks nothing. A config carries more than the questions do: each party's mail domains, and the walls, people and aliases, all installed as written.

To allow those commands in a workspace already installed, because you answered no or installed before Garrick asked, run this from the folder Garrick came in. It writes the same rules and changes nothing else, and it overwrites neither file:

```sh
python3 install.py --allowlist ~/Garrick
```

To start with something to try Garrick on, add `--example` to either form of the install. It adds [the example](example.md), Robin Hale's work at an invented furniture maker, as a zone of its own, Example, with its files in `Quillfield Shared/` in the workspace's top folder. `python3 System/tools/example.py archive` puts it away again, and `restore` brings it back.

The installer writes only inside the target folder. It refuses a target that is your home folder, sits under `~/Documents`, `~/Desktop`, `~/Downloads` or `~/Library` (macOS blocks scheduled jobs from reading those), overlaps the folder Garrick came in (that folder, one inside it, or one holding it), or already has files in it. It compares the folders themselves, not their names: on a Mac, `~/garrick` and `~/Garrick` are the same folder. `--force` lets it install next to files that are already there, but it still stops if the folder holds an `AGENTS.md`, `System`, `Zones`, `Wikis`, `.git`, `.gitignore`, `.claude` or `.agents`.

## What you get

```
AGENTS.md               entry point for any assistant
.claude/skills          link to System/skills, for Claude Code
.claude/settings.json   the commands you allowed at install, if you did, for Claude Code
.agents/skills          link to System/skills, for Codex
System/
  rules.md              how the assistant behaves: Garrick's, replaced by each update
  rules.local.md        your own rules, which win over Garrick's; no update touches it
  context.md            who you are and who you deal with, filled in from your answers
  garrick-settings.json your settings, and which of those allowed commands are Garrick's
  templates/            the zone, project and thread templates scaffold.py copies
  tools/                scaffold.py, check.py, correct.py, nurture.py, probe.py, release.py, and garrick_lib.py, which they share
  skills/               threads, intake, meetings, knowledge, todo, nurture, interview, setup, update
Wikis/                  its own git repository
  Meetings/             every conversation, empty until you feed it
  Knowledge/            published material you study, empty until you feed it
Zones/<Zone>/           one folder and one git repository per zone you named
  AGENTS.md
  Todo.md
  Inbox/                mail and files waiting to be sorted; never committed here
```

The root, `Wikis/`, and each zone are separate git repositories, each with a first commit already made. `System/skills` is symlinked into `.claude/skills` and `.agents/skills` in every one of those repositories, so Claude Code and Codex both find the skills wherever a session starts.

If git had no name or email set on your machine, the installer sets your name and the address `garrick@localhost` in these new repositories only. Nothing needs changing. To use your own address instead, run this in the workspace folder. It sets the address in the root, in `Wikis` and in every zone, and wins over any global git setting:

```sh
for repo in . Wikis Zones/*; do git -C "$repo" config user.email "you@example.com"; done
```

## Your first project

A project always starts with its first thread, and both need a party tag from the Parties table in `System/context.md`. The commands below use `acme`, which exists in the demo workspace; on your own install, use one of your own tags. From the workspace root:

```sh
python3 System/tools/scaffold.py project --zone Work --name "Acme" --party acme --thread "Pricing"
```

This creates `Zones/Work/Acme/`, its hub note, `Sources/`, `Deliverables/`, and the first thread at `Zones/Work/Acme/Threads/Pricing/Pricing.md`, then lists the thread in the hub. A later thread in the same project:

```sh
python3 System/tools/scaffold.py thread --zone Work --project "Acme" --name "Supplier Audit"
```

The script checks names before it creates anything: letters and digits, spaces, hyphens, apostrophes, `&` and a full stop inside an acronym, nothing a folder could not hold or the spoken grammar already uses, and no name that already exists or sounds too close to a sibling. It refuses with a one-line reason rather than write something broken. A name that does not say how it is said, such as "Q4 Planning", is made and then asked about, so its note can carry the form to hear for it in `spoken:`; `--spoken "fourth quarter planning"` gives it straight away.

The script does not commit. Each zone is its own git repository, so commit there:

```sh
git -C Zones/Work add Acme
git -C Zones/Work commit -m "New project Acme"
```

For a party that is not in the table yet, one command adds it and picks the tag itself, so you never have to invent one:

```sh
python3 System/tools/scaffold.py party --name "Cobalt Freight" --zone Work --what "Supplier"
```

With `--check` it writes nothing and answers in one line: that the party is new and what its tag would be, that it is already there with its tag, its zone and any project that names it, or, where two of your parties share the name, which two they are. A party row goes in `System/context.md`, which belongs to the workspace's own repository, while a project goes in its zone's, so the row is committed on its own first and the project is refused until it is there:

```sh
git add System/context.md
git commit -m "Cobalt Freight added as a party (cobalt)"
```

Working with an assistant instead of the command line, just ask: "new project Acme for acme in Work, first thread pricing." The `threads` skill resolves the request, runs the script and commits for you. If the party doesn't exist yet, it offers to add a row to `System/context.md` first, and asks whether a wall belongs between it and any existing party.

## Another zone

The installer makes the zones you name at the start. To add one later, run this from the workspace root:

```sh
python3 System/tools/scaffold.py zone "Garden" --holds "The house and the garden"
```

It makes the zone the way the installer does. It copies the zone template in `System/templates/zone/` to `Zones/Garden/`, with its `AGENTS.md`, `Todo.md` and `Inbox/`. The new folder is its own git repository, with a first commit under the same name and address as the rest of the workspace, the skill links for both assistants, and the wall check before every commit. The words after `--holds` go into a new row of the Zones table in `System/context.md`.

The script checks the name first, as it does for a project: it refuses one that can't be said aloud, or that already exists or sounds too close to another zone. It commits the new zone, but not the change to `System/context.md`, which belongs to the workspace's own repository. Commit that from the workspace root:

```sh
git add System/context.md
git commit -m "Zone Garden"
```

With an assistant, just ask: "add a zone called Garden, for the house and the garden." A new zone has no parties yet. Add the ones its work needs to the Parties table, with the new zone in their Zone column, before its first project.

## Opening and wrapping

Open a terminal in the workspace and start your assistant: `cd ~/Garrick`, then `claude` or `codex`. A zone or `Wikis/` works as a starting folder too; each is its own repository and carries the skill links.

- **"Open Acme pricing"** reads that thread's Resume here block and answers in two sentences: where it stands, and the next action.
- **"Wrap Acme pricing"** (or "close X") rewrites that block so it describes now, adds a dated entry below it, moves any open actions into the zone's `Todo.md`, and commits the change in that zone's repository. It ticks the lines the session finished as they were written, with their `✅` date and nothing added: what came of each goes in the dated entry, and work that was never on the list gets no line at all. Before it commits it runs `todo.py archive` for the zone, so a line ticked on an earlier day goes to the zone's `archive/` whether or not the nightly sweep reaches that zone.
- **"Close for the day"** does this for every thread touched today, one commit each, and names any thread still held (below), which it leaves held.
- **"I'm being interrupted"** (or "hold this", "hold Acme pricing") is the thirty-second version, for when something cuts in. It asks three short questions, one at a time: where you are exactly, the very next step, and anything only in your head, which you can skip. The answers go into the Resume here block, stamped with the time, the zone commits, and the thread goes on a stack of held threads. The thread stays active.
- **"Back"** (or "where was I") opens the thread on top of that stack and reads the three answers back; **"back to Acme pricing"** takes that one from anywhere in it. Interruptions nest, so the last one held comes back first. With nothing held, it says so and offers the thread you worked on last. Wrapping, parking or finishing a thread takes it off the stack.
- **"What's next"** (or "what should I do while I wait") offers one thing worth doing elsewhere, from plain rules and no model: the thread on top of the stack, a Todo line due today or late (a reply or a chase first), a chase that has come due, what waits in an Inbox, a parked thread to park or finish, a live one to wrap. It never offers the thread you are in and never quotes a meeting, and it only offers: nothing is opened or ticked until you say so. It runs `System/tools/next_up.py`, the same list the [Garrick band](../extras/mods/README.md#while-you-wait) shows while a long turn runs.
- **"Is there a thread on freight?"** (or "find freight") looks for the name before you start something: every project and thread in every zone, live, parked or finished, by name and spoken form. It answers with the live ones first and offers to wake a parked one; it never makes or opens anything on its own. The [status page](extras/status-page.md) has the same search in a box on its Threads card.

A thread that was just created has no history, so opening it only tells you its Resume here block is still blank. Do some work, wrap it, and the next open has something to say.

The stack is kept by the [status page](extras/status-page.md)'s `page_action.py`, in `System/generated/interrupted.json`, which is never committed: losing it loses only the order, since the answers are in the thread notes. Without that extra, "I'm being interrupted" still saves the three answers, and "back" offers the thread you worked on last.

The full procedure, including how it resolves a mangled or ambiguous name, is `System/skills/threads/SKILL.md`.

## What a project published

A deck or a workbook that leaves the workspace, copied to a shared cloud folder where colleagues read or edit it, gets one row in `Deliverables/published.md`, in its project: the date, the file, where it went, who received it, and which copy counts from now on (`share` when colleagues edit it there, `here` when they only read it). The `threads` skill adds the row when a wrap finishes such a deliverable, and asks who edits it next. A project that has no ledger yet gets one copied from `System/templates/published.md`, so every project's ledger opens with the same shipped explanation rather than one written fresh each time; two projects across a wall are then not quoting each other.

```markdown
| Date | File | Destination | Recipients | Authoritative |
|---|---|---|---|---|
| 2026-10-01 | `260930 - Pricing deck.pptx` | `Decks/Pricing deck.pptx` | Dana, Owen | share |
```

Only the first word of the last cell is read, so a clause may follow it: `share, Dana edits the wording there`. A row is never deleted, since it is the record of what left: when a copy comes off the share, or a newer version takes its place, its date cell becomes `withdrawn 2026-10-14` or `replaced 2026-10-14`, and a file that went out by mail, never onto a share, gets `sent 2026-10-14`. Such a row is history, never compared. A project with `layout: thread-first` keeps one ledger per thread, in `Threads/<Thread>/Deliverables/published.md`.

The file is a path under `Deliverables/`, or from the project's own folder when it is kept elsewhere, such as a thread's working folder (`Threads/Pricing/Shared Notes/Rates.xlsx`). The destination is relative to the folder the hub names in `shared: <link>/<path>`, through a link you make once in the zone's `.shared/` folder (`ln -s "<the provider's folder>" Zones/Work/.shared/team`), which the zone's `.gitignore` keeps out of its history; never write the provider's own path into a note, since it changes when an account or library is renamed. `<link>:<path>` reaches another linked folder, and a destination that is a folder (`Decks/`) holds a copy with the file's own name. `python3 System/tools/drift.py` then compares each file with its shared copy and reports only real differences: an Office file is compared by its content, not its bytes, which a shared library rewrites on every upload. A copy kept online only is never downloaded, only reported as unchecked. A second copy a sync conflict left beside a published file, such as `Terms (1).docx` or one with `conflicted copy` in its name, is reported by its name alone. A row ending in `here` whose copies differ has drifted: someone edited a copy nobody was meant to edit. A row ending in `share` whose copies differ is reported as `behind`, the project's copy behind the share, since that is what the ledger expects once colleagues save there; it is listed after the rest and does not make the command exit 1. With `--save` the status page lists what drifted, and leaves out what is only behind. macOS keeps scheduled jobs out of cloud folders, so run it from a session or the app.

## The check

For app users, ask “Run the workspace check and explain any findings.” The command below does the same. A clean result covers the implemented checks, not a guarantee against every disclosure; see [coverage and limits](principles.md#what-the-check-covers).

```sh
python3 System/tools/check.py
```

Tests the workspace against every rule a machine can check:

- a `CLAUDE.md` in or above the workspace, which stops Claude Code reading `AGENTS.md`;
- a missing `AGENTS.md` at the root or in a wiki, and instruction files that drift: an `AGENTS.md` or `AGENTS.local.md` past its word budget, the same sentence copied into two instruction files, or a hand-written list of skills, or of a zone's projects, that no longer matches the folder, counting Garrick's file and the local one beside it together (warnings);
- one of Garrick's instruction files, `System/rules.md` or an `AGENTS.md`, that differs from what Garrick shipped: your own text belongs in the local file beside it. Also a local file Garrick's does not point to yet, and passages an update's split left to settle (warnings);
- installer placeholders left unfilled (an error: the install did not finish; files git ignores are skipped, and so is a Garrick checkout kept in a project, cloned or unpacked from a release, whose templates hold them by design);
- a wall or a person in `System/context.md` naming a tag that is not in Parties, or a mail domain that is personal webmail or listed for two parties, two parties with the same name and no wall between them, or no Aliases table (warnings);
- a learned entry that does not say where it came from: a memory entry, in the folder `memory` names in the check settings, with no `source:` or `created:`, or a Learned cell in `System/context.md` that does not read as `YYYY-MM-DD, source`; and one whose only source is inbound, a mail, a transcript or a page, which nobody has confirmed (warnings);
- a skill one of the assistants cannot find from the root, a zone or a wiki, through the repository's skill link or your own; two assistants that see different skills in one place; a `model` that names a version rather than a tier; a skill copied from elsewhere whose `VENDORED.md` names no source commit (warnings);
- a zone that is not its own git repository, or has no `AGENTS.md` or `Todo.md`, or no pre-commit wall check (a warning; `--install-hooks` puts it back), or no `Inbox/` (a warning); a git repository inside a project that has a remote and no wall check (a warning; `--install-hooks` adds it);
- a zone or the Wikis repository whose own hooks git skips, because `core.hooksPath` points somewhere else (a warning);
- names that will not work as names, a name that does not say how it is said and whose note gives no `spoken:` form (a warning), or siblings that sound alike;
- project and thread notes missing their frontmatter or required sections, or naming a party that is not in `System/context.md`, or with a status no tool reads (active, parked or done), or a `created` or `updated` date not written YYYY-MM-DD; a hub or thread note renamed `-v2`;
- a hub that does not link one of its threads, or lists a finished one outside `## Finished`, and a thread-first project with a folder outside its threads (warnings);
- deliverables without a date prefix, in a project's `Deliverables/`, a thread's own, or their `archive/` (build intermediates, scripts and a `README.md` are left alone);
- a deliverable of an anonymous project that names another party of its zone, one of their people, or a name its hub keeps out, Word, Excel and PowerPoint files included (a warning);
- a link or a path in a live Resume here block, a thread's or a hub's, that leads nowhere (a file in code checked out inside the project counts as there, and a path under `System/generated/` is not checked), or a block still holding the template's prompts, or files added to a project more than two weeks after its resume point was last updated (warnings; parked threads are skipped);
- in a zone's `Todo.md`, an action whose thread link leads nowhere, a date with text after it, the example action the list was started with still there under real ones, an Inbox that grew by more than twenty in a week, a ticked line the zone's history never held open, which is a record of work done or an outcome written onto the tick, or a line longer than 200 characters as Obsidian shows it (warnings; a zone with no history of its list is not asked about ticks);
- a link from one zone into another (an error), a note that writes the full path of a cloud-synced folder, and a link to a page name both wikis hold that does not say which (warnings);
- a page in `System/generated/` that is committed (an error), or a root `.gitignore` that does not name that folder (a warning);
- meeting and mail pages missing a zone or parties, or naming both sides of a wall (a warning), or with a date not written YYYY-MM-DD; a page in the Meetings wiki written for one party, with `party` in its frontmatter as a person page has, that cites a meeting across a wall (a warning);
- person pages without a known party (`party: none` is allowed), or repeating eight or more words from a meeting (a warning);
- anything committed from a zone's `Inbox/` (the zone's pre-commit hook refuses it too) or from `Wikis/Meetings/raw/inbox/`, a recording in either instead of its transcript, or a copy left behind after an item was filed;
- a file in a project's `Sources/` that came from mail with no finished page in Meetings: an attachment, found by its exact bytes, or a whole saved mail. A mail intake saved as material (`file-to-project --as-material`) carries its parties in an `X-Garrick-Parties` header instead, and is checked against the walls by those;
- a project file that crosses a wall: it links to a meeting page the wall should have kept out, names a party, person or alias from the far side (files in `Sources/`, which came from the party itself, are exempt from this one), repeats eight or more words in a row held only across the wall, in a walled meeting page or its raw transcript or in a file of a project on the far side (files in `Sources/` are compared with meetings only), or is an attachment of a mail from the far side. A link to, or eight words from, a meeting page with no zone or parties is an error whatever the walls. The finding names the file and the walled party, never the words that matched;
- a Knowledge page that links into Meetings, or carries `party`, `parties` or a `zone`, or a Knowledge page or raw record that shares eight or more words with a meeting (a warning);
- a raw record changed after it was filed, unless you accepted that change in the check settings;
- a `.new` file an update left beside one of yours, waiting to be merged, a version stamp that does not read, or one of Garrick's own tools in `System/tools/` changed here (warnings).

It reports two kinds of finding. An error breaks a rule; a warning is something to look at, such as a deliverable without its date or a project without a party. Plain text by default, grouped by check; add `--ear` for a three-sentence version meant to be read aloud, or `--json` for another program to consume. The exit code is 0 when there is no error, warnings included, 1 when there is at least one, and 2 when no workspace is found.

`--quick` runs every check but one part: the comparison of wording, whether a project file, a person page or a Knowledge page repeats a meeting. That part reads every meeting and project file, and on a workspace with a few hundred meetings it is most of the time a check takes. The commit hook still compares the wording of whatever is committed.

### Check settings

A hub's frontmatter can change what is checked in its project:

| Key | Means |
|---|---|
| `layout: thread-first` | Everything sits inside the threads, each with its own `Sources/` and `Deliverables/`; nothing but `Threads/` at the project's top |
| `anonymous: true` | The project makes things that name nobody: its deliverables are read for the other parties of its zone, their people, aliases and domains. A list, such as `anonymous: [Cedar Labs]`, adds names to keep out |
| `share: <folder>` | The project's files also live on a shared drive. A path in its resume points that is not here is not reported |

A project about the workspace itself can live in `System/<Project>/`, with `type: project` and no zone or party.

`System/garrick-checks.json` holds the rest. It is optional, and so is every key in it:

```json
{
  "parent-links": ["Work"],
  "note-links": ["Work"],
  "todo-labels": ["Work"],
  "word-budgets": {"root": 1000, "other": 1200},
  "retired-skills": {"old-wrap": "threads"},
  "raw-accepted": {"Wikis/Meetings/raw/260310-acme-kickoff.txt": "4f2a91c"},
  "as-shipped": ["System/tools/"],
  "todo-expire-days": {"Work": 14, "Personal": 30},
  "todo-inbox-order": "thread",
  "todo-chase-days": 0,
  "memory": "~/.claude/projects/-Users-sam-Garrick/memory",
  "nurture-weights": {"judgment": 2},
  "nurture-threshold": 60
}
```

- `parent-links`: zones where every note in a project, other than its hub and its `Deliverables/published.md`, carries `parent:`, a link to its thread note or hub, so Obsidian's graph attaches it to the project.
- `note-links`: zones where hub and thread notes name another note as a wikilink, never as a path in backticks, which draws no link in the graph.

[Nurturing the context](#nurturing-the-context) fixes two of these on a yes: a path in backticks that leads to exactly one live note becomes `[[<path>]]`, and a note inside a thread's folder gets `parent: "[[<Thread>]]"`. A note at the project's own level could belong to the hub or to any thread, so it waits for you, as does anything under `Deliverables/` or `Sources/`.
- `todo-labels`: zones where every open action in `Todo.md` opens with its thread's link.
- `word-budgets`: the most words the root `AGENTS.md` (`root`) and the others (`other`) may hold; 800 and 1000 otherwise. Each `AGENTS.local.md` has the same budget as the `AGENTS.md` beside it, counted on its own.
- `retired-skills`: a skill you retired, and the one that does its job now. The check reports the old one if its folder comes back, a link to it stays, or an instruction still names it.
- `raw-accepted`: a raw record you changed on purpose, and the commit of that change. Only a later change is reported.
- `as-shipped`: the files Garrick ships that you never change here, by the start of their path; `System/tools/` otherwise. A change to one belongs in Garrick, or the next update leaves its version beside yours.
- `todo-expire-days`: the days an untriaged line waits in a zone's `Todo.md` before the `todo` skill moves it to the expired archive; 14 otherwise. A number, or one per zone.
- `todo-chase-days`: how many days ahead the `todo` skill's sweep sets `⏳`, the day to chase, on a Waiting on line whose source gives none; 7 otherwise. `0` writes none: the line stays untriaged until you date it, and expires after the zone's days if you never do. A number, or one per zone.
- `todo-inbox-order`: how the `todo` skill orders the Inbox. `first-seen` keeps each thread's lines together where the thread first appears; `thread` sorts them by the thread's name, as a Tasks query sorted by description shows them. A word, or one per zone.

- `memory`: the folder where your assistant keeps a memory of its own, or a list of them: absolute, from your home (`~/`), or from the workspace. Garrick does not guess where a harness keeps it. For Claude Code it is the `memory` folder under `~/.claude/projects/`, in the folder named for the workspace's path with each `/` written `-`. Without it, the check reads no memory, and `correct.py` searches none. Every Markdown file in it is an entry, but for an index the harness keeps beside them (`MEMORY.md`, `index.md` or `README.md`).

- `nurture-weights`: what each kind of finding weighs in the [context debt](#context-debt), by kind: `wall` 10, `attribution` 5, `correction` 5, `judgment` 1 and `mechanical` 1 otherwise; a copy behind the share and a page that would fade weigh 0, and a kind not named weighs 1. Name only the kinds you want to change. A weight that is not a number of zero or more is left as shipped.
- `nurture-threshold`: the context debt above which the nightly digest says so; 40 otherwise.

The check reports a settings file that does not read, a key it does not know, a zone it names that does not exist, and a memory folder that is not there.

The walls part also runs before every commit. The installer puts a git hook in each zone that runs `check.py --staged --walls-only` on the files being committed, as they are staged, and refuses the commit with one line naming the file and the wall. Take the material out and commit again. The first commit in a zone reads every meeting and project file, which on a large workspace takes a while; the hook keeps what it read in the zone's `.git` folder, so after that it reads only what is being committed and what changed since. `git commit --no-verify` skips the check; it exists for the rare deliberate case, and your assistant is told never to use it unless you ask.

## Nurturing the context

The check reports and changes nothing, so its warnings pile up until nobody reads them, and the ones nobody reads are the ones that matter later: a meeting page with no parties can't be used in any project, and a link broken by a rename cuts a thread off from its history. Say "nurture the context", or name a scope: "nurture Work", "nurture Acme", "nurture the meetings". The `nurture` skill gathers every finding for that scope from the tools that already exist, and works through them with you, sorted by what a fix needs:

| Kind | Examples | What happens |
|---|---|---|
| Mechanical | a link broken by a rename, with exactly one candidate in the repository's history; a deliverable without its date prefix, dated from the commit that added it; a thread missing from its hub's `## Threads`; a status synonym (`paused` for `parked`); a note path written as code that leads to exactly one live note in its zone, made a wikilink; a note inside `Threads/<Thread>/` with no `parent:`, given `parent: "[[<Thread>]]"` | Listed, then applied on one yes, one commit per repository |
| Attribution and category | a meeting page with no zone or parties; a person under no party; a page in the wrong wiki or of the wrong `type`; a thread marked done with no outcome | One line each: a proposed answer and a question. Never a guess across a wall |
| Correction | a value written down wrong, which you correct as you go: "that's wrong, it's acmecorp.example" | Every live copy listed as one finding, then corrected on one yes, one commit per repository |
| Wall | a project file that names, links or quotes a party across a wall | The file and the wall, never the material; taken out only on your yes |
| Judgment | a stale resume point, a drifted copy, an orphan page, two pages that disagree | Reported, with the page to open |
| Behind the share | a published file whose ledger row ends in `share`, and whose copy here differs from the shared one | Listed last, as low urgency; nothing to fix, and never in the morning digest |

Behind it is one tool, which adds no checks of its own: it runs `check.py --json`, `wiki_lint.py` for both wikis and `drift.py`, and sorts what they find.

```sh
python3 System/tools/nurture.py --scope "Zones/Work"          # list, change nothing
python3 System/tools/nurture.py fix --scope "Zones/Work"      # what the mechanical fixes would change
python3 System/tools/nurture.py fix --scope "Zones/Work" --yes
python3 System/tools/nurture.py correct --scope "Zones/Work" --old acme-corp.example --new acmecorp.example   # add --yes on your yes
```

A scope is a path from the workspace's top: a zone, a project, a thread, or `Wikis/Meetings` or `Wikis/Knowledge`; none means the whole workspace. `--ear` says the list in at most three sentences. `fix --yes` commits in each repository only the files it changed, named one by one, so what another session has not committed stays out of it, and it leaves alone any file that has changes not committed. Each commit goes through the repository's wall check; one it refuses is put back. Every run writes `System/generated/nurture/<YYYY-MM-DD>.md`: what was fixed, what was asked and answered, and what is left. The wikis' *Lint* is unchanged: "lint the meetings" still writes its own report and changes nothing, and nurturing a wiki runs it.

A correction is the one kind no check finds: you give it, answering a finding or saying it outright during a pass. `nurture.py correct` hands it to the same tool as [Correcting a value](#correcting-a-value), so it finds and fixes every copy the same way, and records the copies, the commits and your yes in the day's report. With a scope, a copy in a file across a wall from it, or in one whose parties can't be told, is left out and left alone: the run says the sentence the rules give for a wall, once, and nothing else about it, no file, party or count. A copy in a file another session has changes in is held.

With the [scheduled jobs](extras/scheduled-jobs.md#nurturing-the-context-each-night) extra, the mechanical kind can also be applied every night, with nobody watching. Nothing of the other kinds changes until you are there, and a correction never runs at night.

### Context debt

Each finding a run leaves weighs by its kind, and the sum is the workspace's *context debt*: a wall 10, an attribution question or a correction 5, a judgment finding or a mechanical fix not yet made 1, and a copy behind the share nothing. A mechanical finding stops counting once it is fixed. The weights were set from Nurture's runs on a working workspace, and `nurture-weights` and `nurture-threshold` in the [check settings](#check-settings) change them. Each day's record, `System/generated/nurture/<YYYY-MM-DD>.json`, keeps the debt by kind and by scope, a zone, a wiki or System, so its trend can be read back without running anything: the [status page](extras/status-page.md) shows it on its Checks card, with its last 30 days and the scopes carrying most. A run of the whole workspace measures it; a scoped run, "nurture Work", replaces only its own scope's part of what stood before. When the debt is over the threshold, 40 unless you set another, or has kept rising for a week, the nightly job's morning digest adds one line, such as `Context debt 42, up from 18 last week, mostly attribution in the Meetings wiki. Say "nurture the meetings".` A wall is in the digest whatever the total.

## Correcting a value

When something written down turns out wrong (an address, an account, a name, a share path), say so: "that's wrong, it's acmecorp.example." The `threads` skill runs the correction, which fixes every live copy, not only the one in front of you. During a nurture pass, the `nurture` skill runs the same tool as one of its kinds:

```sh
python3 System/tools/correct.py --old acme-corp.example --new acmecorp.example            # lists every live copy; changes nothing
python3 System/tools/correct.py --old acme-corp.example --new acmecorp.example --apply --why "the domain has no hyphen"
```

It searches your assistant's memory entries (the folder `memory` names in the check settings), `System/context.md`, every hub and thread note, each zone's `Todo.md`, and the pages of both wikis. The listing gives each file and line, and changes nothing; `--json` gives it to another program. With `--apply`, your one yes, it writes the new value in place of the old in each of them, re-reading each file first, and commits once per repository, staging only the files it changed. A memory kept outside the workspace is changed and not committed. A zone's wall check still runs on its commit.

The old value is matched as written, never inside a longer word, and a hit that is right where it is, such as a misheard form in Aliases, is kept with `--leave <path>`. Live files show only the new value, with no "was" trail: git has the old one. A raw record is never edited. One that holds the old value is listed, and each wiki page resting on it gets `superseded:` in its frontmatter and a line at its end saying its record holds a value corrected since, and the right one. Then the Meetings index is rebuilt, and the status page if you have it.

## The two memories

`Wikis/Meetings/` and `Wikis/Knowledge/` are empty after install. Their schemas (what a page needs, where raw material goes, what must never cross between them) are in each folder's own `AGENTS.md`.

Everything comes in through an inbox. Drop a transcript from any recorder (a `.txt`, `.md` or `.vtt` file, not the audio) into `Wikis/Meetings/raw/inbox/`, and mail (a `.eml` file, or the message saved as `.txt` or `.md`) or any other file into a zone's `Inbox/`. Then say "process the inbox". The `intake` skill sorts each item by the *Ways in* rules in `System/rules.md`: a conversation goes to Meetings, through the `meetings` skill; something to read goes to Knowledge, through the `knowledge` skill; material for a project goes into that project's `Sources/`, with the mail it came in kept in Meetings. It asks for the zone, the parties or the project when they are not obvious, goes by the mail domains in the Parties table, and records any you teach it. Ways to fetch mail into an inbox without doing it by hand are in [ways in](extras/ways-in.md).

You can also hand over a link, a PDF or pasted text and say "read this": the `knowledge` skill freezes the original into `raw/` and writes the pages. "Prep me for Acme" and "what does my library say about X" read them back.
