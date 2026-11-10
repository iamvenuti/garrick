# Command reference

For everyday app use, follow [Desktop first steps](first-steps.md), then [Your first useful session](first-session.md). For a CLI workflow, start with [Terminal setup](terminal-setup.md). This page is the detailed reference for the installer and workspace tools; your assistant can run them for you.

Requires macOS, Python 3.9 or later, and git. If `git --version` fails, run `xcode-select --install` and wait for it to finish. You also need Claude Code or Codex. Claude Code reads `AGENTS.md` natively from version 2.1.277; `claude --version` tells you which one you have.

## Install

From the folder Garrick came in, `~/Downloads/garrick` for the download or `~/garrick-source` for a clone:

```sh
python3 install.py
```

This asks a few questions, one at a time: where the workspace should go (default `~/Garrick`; a folder name on its own, such as `Garrick-work`, goes in your home folder), your name and a one-line description of what you do, your zones (default `Work, Personal`) and what each holds, then who you work for or with, and last whether the assistant may run Garrick's own tools and git's commands that look at or save history without asking each time ([what that allows](first-steps.md#the-commands-it-asks-to-approve)). Press Enter to accept the default in brackets. Who you work for or with is one line of names separated by commas, and Enter skips it. Each name becomes a party, an organisation or person whose confidences you hold, with a tag taken from the name, such as `acme` for Acme Corp; the installer asks which zone it belongs to only when you have more than one. That is all it asks. Mail domains, walls, people and the aliases dictation needs come later, in your first session, where you can see what each one changes: say "interview me" and the assistant asks about them one at a time, or ask it to add a party or a wall. A wall is an explicit pair of tags whose material must not be used in each other's projects. Separate folders and different party tags do not create walls automatically, and the installer declares none. Zones added later follow [Another zone](#another-zone). Since a new workspace opens on the [simple home](extras/simple-home.md), the installer also puts the [Garrick App](extras/status-page.md) it is part of in `System/status/` and builds it once; "set up Garrick" offers its Mac app.

To skip the questions (for a demo, a test, or a guided session), pass a config file:

```sh
python3 install.py --config examples/acme.json --target ~/Garrick-acme
```

`examples/acme.json` is a complete fictional setup (an advisor with two clients, Acme Corp and Birch & Co, in a walled zone). Copy it and edit it as a starting point for your own config. Its keys are `owner`, `zones`, `parties`, `people`, `aliases`, and `allow-commands`, the last question, which is `true` unless the file says `false`, so a config run asks nothing. A config carries more than the questions do: each party's mail domains, a zone's `party` and `new-parties` (a zone is walled unless its `new-parties` is `open` and its party is open), and the people and aliases, all installed as written.

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
  retention.md          what keeps a wiki page in working memory, in plain words: Garrick's; yours goes in retention.local.md
  briefing.local.md     what a catch-up raises and what it leaves out, in plain words, if you want your own: it wins over what briefing.py holds
  garrick-settings.json your settings, and which of those allowed commands are Garrick's
  templates/            the zone, project and thread templates scaffold.py copies
  tools/                scaffold.py, check.py, correct.py, nurture.py, fade.py, recall.py, briefing.py, probe.py, release.py, and garrick_lib.py, which they share
  skills/               threads, intake, meetings, knowledge, todo, nurture, recall, interview, setup, update
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

A project always starts with its first thread. A party tag from the Parties table in `System/context.md` is optional: it is an index, not a wall. The commands below use `acme`, which exists in the demo workspace; on your own install, use one of your own tags. From the workspace root:

```sh
python3 System/tools/scaffold.py project --zone Work --name "Acme" --party acme --thread "Pricing"
```

This creates `Zones/Work/Acme/`, its hub note, `Sources/`, `Deliverables/`, and the first thread at `Zones/Work/Acme/Threads/Pricing/Pricing.md`, then lists the thread in the hub. A later thread in the same project:

```sh
python3 System/tools/scaffold.py thread --zone Work --project "Acme" --name "Supplier Audit"
```

The script checks names before it creates anything: letters and digits, spaces, hyphens, apostrophes, `&` and a full stop inside an acronym, nothing a folder could not hold or the spoken grammar already uses, and no name that already exists or sounds too close to a sibling. It refuses with a one-line reason rather than write something broken. A name that does not say how it is said, such as "Q4 Planning", is made and then asked about, so its note can carry the form to hear for it in `spoken:`; `--spoken "fourth quarter planning"` gives it straight away.

With the [Garrick App](extras/status-page.md) in place, the script then starts a build of its page in the background, so the new project or thread is on the Threads card within seconds; several commands in a row make one build.

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

A party carries no wall: its zone does. `party` takes `--name`, `--zone` and `--what` only. To put a party on a hub or thread note as an index, or take one off, use `label`:

```sh
python3 System/tools/scaffold.py label --zone Work --project Acme --add birch --yes
python3 System/tools/scaffold.py label --zone Work --project Acme --thread Pricing --remove birch --yes
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

A new zone is walled. `--open` makes it open, and `--walled` says so outright. To change the flag of a zone already in the table:

```sh
python3 System/tools/scaffold.py zone --name Garden --walled     # runs the workspace check and lists what now crosses
python3 System/tools/scaffold.py zone --name Garden --open       # says how many files it releases; writes only with --yes
```

With an assistant, just ask: "add a zone called Garden, for the house and the garden." A new zone has no parties yet. Add the ones its work needs to the Parties table, with the new zone in their Zone column.

## Opening and wrapping

Open a terminal in the workspace and start your assistant: `cd ~/Garrick`, then `claude` or `codex`. A zone or `Wikis/` works as a starting folder too; each is its own repository and carries the skill links.

- **"Open Acme pricing"** reads that thread's Resume here block and answers in two sentences: where it stands, and the next action.
- **"Wrap Acme pricing"** (or "close X", "wrap it", and when something cuts in "I'm being interrupted", "hold this" or "hold Acme pricing": all the same wrap) rewrites that block so it describes now, adds a dated entry below it, moves any open actions into the zone's `Todo.md`, and commits the change in that zone's repository. It ticks the lines the session finished as they were written, with their `✅` date and nothing added: what came of each goes in the dated entry, and work that was never on the list gets no line at all. Before it commits it runs `todo.py archive` for the zone, so a line ticked on an earlier day goes to the zone's `archive/` whether or not the nightly sweep reaches that zone.
- **"Close for the day"** (or "I'm done for today") has every session used today wrap its own thread, one at a time: cmux tabs, other sessions your assistant can reach, and this one. A session that is mid-turn or waiting on a question is skipped and named, and one that cannot be reached is listed with its folder so you wrap it there. You get one line per session: wrapped, with its thread and next action; skipped, with why; or not reachable. Nothing is quit: quitting cmux or an app stays your Cmd+Q.
- **"Start the day"** (or "restore my tabs") needs nothing run where cmux holds your tabs: open cmux, and each tab that ran an assistant comes back in its own session, resumed by cmux. A tab at a bare prompt means cmux never quit; check with `pgrep -l cmux`, quit it, and open it again.
- **One question, then the wrap in the background.** A wrap asks one line first, "Anything only in your head?", and Enter skips it. The answer goes into *Keep in mind*. Then, where your assistant can run work in the background (Claude Code can), the wrap runs there and you are free to leave; where it cannot, the wrap runs in front, as it always did. A second wrap of the same thread cannot start while one is running. "Close for the day" and the band's *Close* run in front and ask nothing, since they end the session once the wrap has finished.
- **"Back"** (or "where was I") resumes the thread whose note was written most recently and is not finished or parked, and reads its Resume here block back; **"back to Acme pricing"** opens that one. After two wraps, it is the later one. The note's own last write is the record: nothing else keeps your place, so a job or a checkout that touches a note can move it, for Back and for *While you wait* alike. With nothing to resume, it says so and offers the thread you worked on last.
- **"What's next"** (or "what should I do while I wait") offers one thing worth doing elsewhere, from plain rules and no model: the thread you left most recently today, a Todo line due today or late (a reply or a chase first), a chase that has come due, what waits in an Inbox, a parked thread to park or finish, a live one to wrap. It never offers the thread you are in and never quotes a meeting, and it only offers: nothing is opened or ticked until you say so. It runs `System/tools/next_up.py`, the same list the [Garrick band](../extras/mods/README.md#while-you-wait-a-preview-feature) shows while a long turn runs where its *While you wait* preview feature is switched on.
- **"Catch me up"** (or "catch me up on Acme", "catch me up on Acme, pricing since Monday", "catch me up on Work this week") says what changed while you were away, thread by thread: a short overview first, then for each thread that moved what changed and why it matters, the decisions with their reasons, what to look at before you carry on, its open actions, and where it stands now with its next action. Each statement links the note, the commit or the `Todo.md` it rests on, and a gap in the records is said as a gap. It covers one zone unless you name more, leaves out what did not change (a parked thread too, unless you name it), and takes the last day when you name no period, or the one `"catch-up"` in `System/garrick-settings.json` names (`day`, `week`, `7-days` or `14-days`; a named period always wins). It runs `System/tools/briefing.py`, which gathers each thread's commits, its Resume here block now and as it was, the dated entries added, a waiting checkpoint and its Todo lines, and carries what deserves attention in plain words; your own, in `System/briefing.local.md`, wins. A meeting appears only as a link the thread already holds, never quoted. It is shown and nothing is written; say "save that" to keep it. Typed or said in a session or in Ask, the prompt is the only way in: the page has no button for it. Listening, you hear the overview and are offered the rest. "Brief me for X" is still the brief for a meeting.
- **"Is there a thread on freight?"** (or "find freight") looks for the name before you start something: every project and thread in every zone, live, parked or finished, by name and spoken form. It answers with the live ones first and offers to wake a parked one; it never makes or opens anything on its own. The [Garrick App](extras/status-page.md) has the same search in a box on its Threads card.

A thread that was just created has no history, so opening it only tells you its Resume here block is still blank. Do some work, wrap it, and the next open has something to say.

While a wrap runs, it holds a small lock file in `System/generated/` (`wrap-<note path>.lock`), which the wrap removes when it ends; a lock older than ten minutes counts as gone. It is never committed.

The full procedure, including how it resolves a mangled or ambiguous name, is `System/skills/threads/SKILL.md`.

## What a project published

A deck or a workbook that leaves the workspace, copied to a shared cloud folder where colleagues read or edit it, gets one row in `Deliverables/published.md`, in its project: the date, the file, where it went, who received it, and which copy counts from now on (`share` when colleagues edit it there, `here` when they only read it). The `threads` skill adds the row when a wrap finishes such a deliverable, and asks who edits it next. A project that has no ledger yet gets one copied from `System/templates/published.md`, so every project's ledger opens with the same shipped explanation rather than one written fresh each time; two projects across a wall are then not quoting each other.

```markdown
| Date | File | Destination | Recipients | Authoritative |
|---|---|---|---|---|
| 2026-10-01 | `260930 - Pricing deck.pptx` | `Decks/Pricing deck.pptx` | Dana, Owen | share |
```

Only the first word of the last cell is read, so a clause may follow it: `share, Dana edits the wording there`. A row is never deleted, since it is the record of what left: when a copy comes off the share, or a newer version takes its place, its date cell becomes `withdrawn 2026-10-14` or `replaced 2026-10-14`, and a file that went out by mail, never onto a share, gets `sent 2026-10-14`. Such a row is history, never compared. A project with `layout: thread-first` keeps one ledger per thread, in `Threads/<Thread>/Deliverables/published.md`.

The file is a path under `Deliverables/`, or from the project's own folder when it is kept elsewhere, such as a thread's working folder (`Threads/Pricing/Shared Notes/Rates.xlsx`). The destination is relative to the folder the hub names in `shared: <link>/<path>`, through a link you make once in the zone's `.shared/` folder (`ln -s "<the provider's folder>" Zones/Work/.shared/team`), which the zone's `.gitignore` keeps out of its history; never write the provider's own path into a note, since it changes when an account or library is renamed. `<link>:<path>` reaches another linked folder, and a destination that is a folder (`Decks/`) holds a copy with the file's own name. `python3 System/tools/drift.py` then compares each file with its shared copy and reports only real differences: an Office file is compared by its content, not its bytes, which a shared library rewrites on every upload. A copy kept online only is never downloaded, only reported as unchecked. A second copy a sync conflict left beside a published file, such as `Terms (1).docx` or one with `conflicted copy` in its name, is reported by its name alone. A row ending in `here` whose copies differ has drifted: someone edited a copy nobody was meant to edit. A row ending in `share` whose copies differ is reported as `behind`, the project's copy behind the share, since that is what the ledger expects once colleagues save there; it is listed after the rest and does not make the command exit 1. With `--save` the Garrick App lists what drifted, and leaves out what is only behind. macOS keeps scheduled jobs out of cloud folders, so run it from a session or the app.

## The check

For app users, ask “Run the workspace check and explain any findings.” The command below does the same. A clean result covers the implemented checks, not a guarantee against every disclosure; see [coverage and limits](principles.md#what-the-check-covers).

```sh
python3 System/tools/check.py
```

Tests the workspace against every rule a machine can check. `python3 System/tools/check.py --walls-cases` instead runs the table of wall cases (`System/tools/walls-cases.md`) against your own Parties and Zones tables, with your tags in place of the fixture's roles, and says which case, if any, your tables answer wrongly. A project whose hub names no `party:` is an error, and the commit hook refuses any file in it until the hub names one (see [Principles](principles.md#one-decision-for-every-point)).

The check covers:

- a `CLAUDE.md` in or above the workspace, which stops Claude Code reading `AGENTS.md`;
- a missing `AGENTS.md` at the root or in a wiki, and instruction files that drift: an `AGENTS.md` or `AGENTS.local.md` past its word budget, `System/rules.md` past 8,000 characters, the same sentence copied into two instruction files, or a hand-written list of skills, or of a zone's projects, that no longer matches the folder, counting Garrick's file and the local one beside it together (warnings);
- one of Garrick's instruction files, `System/rules.md` or an `AGENTS.md`, that differs from what Garrick shipped: your own text belongs in the local file beside it. Also a local file Garrick's does not point to yet, and passages an update's split left to settle (warnings);
- installer placeholders left unfilled (an error: the install did not finish; files git ignores are skipped, and so is a Garrick checkout kept in a project, cloned or unpacked from a release, whose templates hold them by design);
- a person in `System/context.md` naming a tag that is not in Parties, or a mail domain that is webmail or listed for two parties, or no Aliases table (warnings);
- a learned entry that does not say where it came from: a memory entry, in the folder `memory` names in the check settings, with no `source:` or `created:`, or a Learned cell in `System/context.md` that does not read as `YYYY-MM-DD, source`; and one whose only source is inbound, a mail, a transcript or a page, which nobody has confirmed (warnings);
- a skill one of the assistants cannot find from the root, a zone or a wiki, through the repository's skill link or your own; two assistants that see different skills in one place; a `model` that names a version rather than a tier; a skill copied from elsewhere whose `VENDORED.md` names no source commit (warnings);
- a zone that is not its own git repository, or has no `AGENTS.md` or `Todo.md`, or no pre-commit wall check, or a pre-commit wall check with no `pre-merge-commit`, `post-merge` or `post-rewrite` beside it (a warning; `--install-hooks` puts it back), or no `Inbox/` (a warning); a git repository inside a project that has a remote and no wall check (a warning; `--install-hooks` adds it);
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
- meeting and mail pages missing a zone, or naming two walled zones together (a warning), or with a date not written YYYY-MM-DD;
- person pages without a known party (`party: none` is allowed), or repeating eight or more words from a meeting (a warning);
- in the Meetings wiki, two entity pages naming the same `party:`, subfolders included, or going by one name in their titles, `aliases:` or file names; a person page with no `organisation:` where it could have one, or one that is not exactly `[[wiki/entities/<slug>]]` or leads to no entity page (warnings); and an entity or people page whose sources sit in two walled zones (an error of the walls check, which the commit hook refuses too);
- anything committed from a zone's `Inbox/` (the zone's pre-commit hook refuses it too) or from `Wikis/Meetings/raw/inbox/`, a recording in either instead of its transcript, or a copy left behind after an item was filed;
- a file in a project's `Sources/` that came from mail with no finished page in Meetings: an attachment, found by its exact bytes, or a whole saved mail. A mail intake saved as material (`file-to-project --as-material`) carries its parties in an `X-Garrick-Parties` header instead, an index for mail routing only: no check reads it as a wall;
- a file that carries a walled zone's material into another zone: it links to, embeds or names the path of a file of another walled zone, or a Meetings page of one, or is a copy of one made whole. A link to a meeting page with no zone is an error whatever the walls. The finding names the file and the other zone, never the words that matched;
- a Knowledge page that links into Meetings, or carries `party`, `parties` or a `zone` (a warning);
- a raw record changed after it was filed, unless you accepted that change in the check settings (a rename that leaves its content as it was, or a move into `dormant/raw/` or `archive/raw/` when it fades, is no change);
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

The walls part also runs before every commit. The installer puts a git hook in each zone and in `Wikis/` that runs `check.py --staged --walls-only` on the files being committed, as they are staged, and refuses the commit with one line naming the file and the wall, and ending with the fix for that kind of refusal: usually take the material out and commit again. The first commit in a zone reads every meeting and project file, which on a large workspace takes a while; the hook keeps what it read in the zone's `.git` folder, so after that it reads only what is being committed and what changed since. When a file has one refusal, the line is the whole report for it; when it has several, the hook prints one line with the kind of each (`2 name, 1 link`) and a count. A line with the command that lets a refusal through, once, comes first, written to run from the folder the hook runs in, so the refusals stay the last lines. `check.py allow <path>` lists a file's refusals with their ids; `check.py --staged --walls-only --verbose`, run from the zone folder, prints every refusal on a line of its own. `check.py --changed <revisions>` is the same walls check, read only, over the files the named commits changed (`A..B` is what changed from A to B): the `post-merge` and `post-rewrite` hooks run it after a merge, a fast-forward, a rebase or an amend, and it reports and never refuses. `--after merge|rebase|amend` says what brought them in, which decides how its report says to undo it.

A refusal that is a false alarm can be let through once, with a record:

```sh
python3 System/tools/check.py allow Zones/Work/Acme/Notes.md          # lists the file's refusals, each with its id
python3 System/tools/check.py allow Zones/Work/Acme/Notes.md 3f9a1c2b7d
python3 System/tools/check.py allow --remove Zones/Work/Acme/Notes.md 3f9a1c2b7d
```

The allowance is written to `System/walls-allowed.json` and committed in the workspace's own repository, with the day and who wrote it. It holds for that one refusal in that one file, only while the file is as it was allowed: edit the file and the refusal comes back, and an allowance for one refusal does not cover another in the same file. It is written from a terminal you type in (not from a shell with no terminal, as an assistant's is), never by an assistant, and the status page has no button that writes one, only *Remove*: an assistant that meets a refusal names the files and this command, and stops. A refusal about something that could not be read, or a file waiting in an inbox, cannot be allowed. [Allow once](enforced.md#allow-once) has the file's format.

`git commit --no-verify` skips the check altogether; it exists for the rare deliberate case, it is yours alone, and your assistant is told never to use it unless you ask.

## Nurturing the context

The check reports and changes nothing, so its warnings pile up until nobody reads them, and the ones nobody reads are the ones that matter later: a meeting page with no parties can't be used in any project, and a link broken by a rename cuts a thread off from its history. Say "nurture the context", or name a scope: "nurture Work", "nurture Acme", "nurture the meetings". The `nurture` skill gathers every finding for that scope from the tools that already exist, and works through them with you, sorted by what a fix needs:

| Kind | Examples | What happens |
|---|---|---|
| Mechanical | a link broken by a rename, with exactly one candidate in the repository's history; a deliverable without its date prefix, dated from the commit that added it; a thread missing from its hub's `## Threads`; a status synonym (`paused` for `parked`); a note path written as code that leads to exactly one live note in its zone, and not into another walled zone, made a wikilink; a note inside `Threads/<Thread>/` with no `parent:`, given `parent: "[[<Thread>]]"` | Listed, then applied on one yes, one commit per repository |
| Attribution and category | a meeting page with no zone; a person under no party; a page in the wrong wiki or of the wrong `type`; a thread marked done with no outcome | One line each: a proposed answer and a question. Never a guess across a wall |
| Correction | a value written down wrong, which you correct as you go: "that's wrong, it's acmecorp.example" | Every live copy listed as one finding, then corrected on one yes, one commit per repository |
| Wall | a file that links to, embeds or names the path of a file of another walled zone | The file and the wall, never the material; taken out only on your yes |
| Judgment | a stale resume point, a drifted copy, an orphan page, two pages that disagree | Reported, with the page to open |
| Behind the share | a published file whose ledger row ends in `share`, and whose copy here differs from the shared one | Listed last, as low urgency; nothing to fix, and never in the morning digest |
| Fading | wiki pages old enough to leave working memory, or a faded page linked again | How many, per wiki, and what to say; see [Fading](#fading). Nothing moves without a written proposal and your yes |

Behind it is one tool, which adds no checks of its own: it runs `check.py --json`, `wiki_lint.py` for both wikis and `drift.py`, and sorts what they find.

```sh
python3 System/tools/nurture.py --scope "Zones/Work"          # list, change nothing
python3 System/tools/nurture.py fix --scope "Zones/Work"      # what the mechanical fixes would change
python3 System/tools/nurture.py fix --scope "Zones/Work" --yes
python3 System/tools/nurture.py correct --scope "Zones/Work" --old acme-corp.example --new acmecorp.example   # add --yes on your yes
```

A scope is a path from the workspace's top: a zone, a project, a thread, or `Wikis/Meetings` or `Wikis/Knowledge`; none means the whole workspace. `--ear` says the list in at most three sentences. `fix --yes` commits in each repository only the files it changed, named one by one, so what another session has not committed stays out of it, and it leaves alone any file that has changes not committed. Each commit goes through the repository's wall check; one it refuses is put back. Every run writes `System/generated/nurture/<YYYY-MM-DD>.md`: what was fixed, what was asked and answered, and what is left. The wikis' *Lint* is unchanged: "lint the meetings" still writes its own report and changes no page, and nurturing a wiki runs it. The lint also lists every line under an *Open* or *Open issues* heading on a page and, on one yes for the whole list, turns each line into a [question file](extras/status-page.md) with the page as its origin, carrying the page's own zone and parties. A page with no zone or parties gets no question, and the lint says why. A line already asked is not proposed again, and no page is changed.

A correction is the one kind no check finds: you give it, answering a finding or saying it outright during a pass. `nurture.py correct` hands it to the same tool as [Correcting a value](#correcting-a-value), so it finds and fixes every copy the same way, and records the copies, the commits and your yes in the day's report. With a scope, a copy in a file of another walled zone, or in one whose zone can't be told, is left out and left alone: the run says the sentence the rules give for a wall, once, and nothing else about it, no file, party or count. A copy in a file another session has changes in is held.

With the [scheduled jobs](extras/scheduled-jobs.md#nurturing-the-context-each-night) extra, the mechanical kind can also be applied every night, with nobody watching. Nothing of the other kinds changes until you are there, and a correction never runs at night.

### Context debt

Each finding a run leaves weighs by its kind, and the sum is the workspace's *context debt*: a wall 10, an attribution question or a correction 5, a judgment finding or a mechanical fix not yet made 1, and a copy behind the share nothing. A mechanical finding stops counting once it is fixed. The weights were set from Nurture's runs on a working workspace, and `nurture-weights` and `nurture-threshold` in the [check settings](#check-settings) change them. Each day's record, `System/generated/nurture/<YYYY-MM-DD>.json`, keeps the debt by kind and by scope, a zone, a wiki or System, so its trend can be read back without running anything: the [Garrick App](extras/status-page.md) shows it on its Checks card, with its last 30 days and the scopes carrying most. A run of the whole workspace measures it; a scoped run, "nurture Work", replaces only its own scope's part of what stood before. When the debt is over the threshold, 40 unless you set another, or has kept rising for a week, the nightly job's morning digest adds one line, such as `Context debt 42, up from 18 last week, mostly attribution in the Meetings wiki. Say "nurture the meetings".` A wall is in the digest whatever the total.

### Reviewing the context

Nurture runs every night, so the way to review the context is to answer what it leaves. Say "review the context with me", or "review the latest audit with me", and the assistant opens the status page's [Context tab](extras/status-page.md#the-context-tab), filtered to the scope you named. There an attribution finding is answered where it stands, *Later* puts a row off to a day, and a judgment finding has *Open in Claude* (and *Open in Codex*, where installed), which hands that one finding to a session. "Nurture the context" stays a spoken command, for a scope the nightly run does not cover or for a run during the day.

A record that an older release left, `System/nurture-review.md`, is read once: each row it deferred to a coming day becomes a *Later* row, and the file is removed in a commit of its own (`nurture.py import-review`, which the nightly run also does). Nothing keeps a record of decisions any more: the day's Nurture report holds each answer.

## Fading

Both wikis only grow, and every question starts by reading their index. So old pages fade out of working memory, by age, kind and use, and stay where a search can still find them. Nothing is deleted.

| Grade | Where, inside the wiki | Who reads it |
|---|---|---|
| Working | `wiki/...`, its raw record in `raw/...`, listed in `wiki/index.md` | every question, briefing and search |
| Dormant | `dormant/wiki/...` and `dormant/raw/...`, listed in `wiki/index-dormant.md` with its date, the day it went dormant and why | a search that reaches back, and says "from older notes" |
| Archived | `archive/wiki/...` and `archive/raw/...`, in no index | only when you ask: "search the archive", "what did we say about pricing in 2025" |

Say "fade the meetings", "fade the library" or "what would fade". The `nurture` skill writes the list of what would go dormant, go to the archive or come back, grouped, each with why, and moves nothing. The first fade on a wiki stops there: read the list, and where it is wrong, change `System/retention.local.md` or the settings. After that, one yes applies exactly what the written list holds and still qualifies. Say "keep X" to keep a page in working memory for good.

```sh
python3 System/tools/fade.py propose --wiki Meetings                   # writes System/generated/fade/Meetings.md; moves nothing
python3 System/tools/fade.py apply --wiki Meetings --id <id>           # the id is at the end of the written proposal
python3 System/tools/fade.py keep --page "Meetings/wiki/sources/260310-acme-kickoff.md"
python3 System/tools/fade.py counts                                    # what each grade holds, and what would move
python3 System/tools/fade.py list --wiki Meetings --grade archived     # every archived page, with its date
```

- **Age** counts from the page's own `date:` (a meeting) or `published:`, else `date:` (reading), or the date its file name starts with, never from when the file was last opened or changed, so filing a page again does not make it young. A date that gives only a month or a year counts from the end of it, and a page with no date never fades by age.
- **Kind** sets the pace. Meetings and mail go dormant at 6 months and to the archive at 18; newsletters and articles at 3 and 12; reports, standards and other reading at 24, and never to the archive. Reading that came by mail counts as a newsletter.
- **Use** pins a page: one linked from a live thread, from a live project's notes or from an open line in a `Todo.md`, or carrying `pinned: true`, never fades. A dormant page linked again from one of those, or linked afresh from a working page, is proposed to come back with the next fade, and comes back on your yes. Opening, reading or quoting a page brings nothing back. An archived page comes back only on "keep".
- **`superseded:`**, a link to the page that replaces it or a short reason, keeps a page out of working memory whatever links it, and it never comes back by use. The reason shows beside it in `index-dormant.md` and in `fade.py list`.
- **Person, entity and concept pages** never move. Each keeps an `## Earlier` section listing what faded, under two lines the assistant writes. A person page lists a meeting only when every party of the meeting is the person's own, and by its date alone, never its title, since a person page is read on both sides of every wall.
- **Pages that share one record**, the halves of a split call, move together or not at all.

Every grade change is a move, never an edit: the page and its raw record are renamed, content unchanged, and every link into them, from both wikis and every zone's notes, is pointed at the new path, so nothing breaks. A link written with a path keeps its spelling around `dormant/` or `archive/`; a bare `[[260310-acme-kickoff]]` gains the path and keeps what it showed. The proposal lists each page's derived copies: the pages that go with it, the notes and ticked actions whose links are pointed at its new path, what stays as written, and the person and entity pages that list it. A note another session is changing holds every move it links, with why. One commit per repository, the wiki's first; a refused one puts everything back.

Where a folder that holds a wiki is an Obsidian vault (the workspace, `Wikis/`, or the wiki itself), the fade adds `dormant/` and `archive/` to that vault's excluded files, after any you set, so faded pages leave the graph and the default search as well as the index. A vault opened later gets them with the next fade, or at once with `python3 System/tools/fade.py filters`.

The settings are `"memory"` in `System/garrick-settings.json`, and `fade.py settings` prints them merged over the defaults:

```json
"memory": {
  "wikis":  {"Meetings": true, "Knowledge": true},
  "kinds":  {"meetings": {"wiki": "Meetings", "types": ["meeting", "email"], "domains": [], "dormant": 6, "archived": 18}},
  "pins":   {"thread": true, "project": true, "todo": true, "pinned": true},
  "wake":   true,
  "reach":  "dormant",
  "nightly": {"on": true, "min": 10}
}
```

A kind names a wiki, the page `type`s and domains that belong to it (a page's own `domain:`, the folder its raw file is kept in under `raw/`, or `mail`), and its months; `null` means never, and a kind set to `null` is taken out. `wikis` switches fading off for one; `pins` switches each pin off; `wake` false leaves only "keep" to bring a page back; `reach` set to `working` keeps a search to working pages unless you ask for older ones. The judgment the numbers can't hold, such as "keep anything that sets a price", is in `System/retention.md`, shipped with Garrick, and your own in `System/retention.local.md`, which wins: the skill reads both when it proposes.

Nothing fades overnight. With the [scheduled jobs](extras/scheduled-jobs.md#nurturing-the-context-each-night) extra, the nightly nurture works out the list and, once a wiki's count reaches `nightly.min`, adds one line to the morning digest: "41 meeting pages would go dormant and 9 to the archive. Say "fade the meetings"."

## Correcting a value

When something written down turns out wrong (an address, an account, a name, a share path), say so: "that's wrong, it's acmecorp.example." The `threads` skill runs the correction, which fixes every live copy, not only the one in front of you. During a nurture pass, the `nurture` skill runs the same tool as one of its kinds:

```sh
python3 System/tools/correct.py --old acme-corp.example --new acmecorp.example            # lists every live copy; changes nothing
python3 System/tools/correct.py --old acme-corp.example --new acmecorp.example --apply --why "the domain has no hyphen"
```

It searches your assistant's memory entries (the folder `memory` names in the check settings), `System/context.md`, every hub and thread note, each zone's `Todo.md`, and the pages of both wikis. The listing gives each file and line, and changes nothing; `--json` gives it to another program. With `--apply`, your one yes, it writes the new value in place of the old in each of them, re-reading each file first, and commits once per repository, staging only the files it changed. A memory kept outside the workspace is changed and not committed. Before each commit the staged walls check (`check.py --staged --walls-only`) runs in that repository, a wiki or the root as much as a zone, hook or no hook. When it refuses, that repository's files are put back as they were and nothing there is committed; the run names the refusing check and the paths, and says when the cause is a page's form, a check that did not finish, or a file another session has staged there.

The old value is matched as written, never inside a longer word, and a hit that is right where it is, such as a misheard form in Aliases, is kept with `--leave <path>`. Live files show only the new value, with no "was" trail: git has the old one. A raw record is never edited. One that holds the old value is listed, and each wiki page resting on it gets `superseded:` in its frontmatter and a line at its end saying its record holds a value corrected since, and the right one. Then the Meetings index is rebuilt, and the Garrick App's page if you have it.

## Recall

Plain text search returns every line that matches, in no order, and a common word in your work matches thousands. Say "what did we decide about the retry flag", "when did we fix the export error" or "find where we talked about renewals", and the `recall` skill runs `System/tools/recall.py`, which searches an index and gives back the ten best files with a date, a source, a snippet and a path. The routing in `AGENTS.md` still comes first: "where did we land with X" goes to Meetings. A result is a pointer, and the assistant opens the file before it states a fact from it.

```sh
python3 System/tools/recall.py build                     # bring every index up to date; --rebuild makes them again
python3 System/tools/recall.py search "invoice export retry" [--scope S] [--after 2026-06-01] [--zone Work] [--wiki Meetings] [--sessions] [--archived] [--raw] [--limit 10]
python3 System/tools/recall.py read ID [--scope S]       # the text of a result, when its id is in your scope index
python3 System/tools/recall.py stats                     # your scope index, and how many files it holds
python3 System/tools/recall.py extract                   # write new Claude Code and Codex sessions to .sessions/
```

- **The command takes a scope, never a folder.** `search`, `read` and `stats` use the scope of the project, zone or root the process really runs in (symlinks followed). `--scope` may name that scope and no other; only a session at the root may name any. `--root` changes nothing about it. Where the environment names the folder the session was opened in (`CLAUDE_PROJECT_DIR`), the scope is the narrower of that and the current folder, and a folder outside it searches nothing. `GARRICK_RECALL_SCOPE` can only narrow a root session to another scope; it never widens a project session. A bare working folder at the root, in `System/` or at a zone's top is never the root scope: the root scope needs `CLAUDE_PROJECT_DIR` naming the root, as the harness sets it for a session opened there. A shell-capable assistant session can still read files directly or set its own environment, so this is a wall for what Recall returns, not for the session's own reads. A project whose hub names no party, a zone's top level and a place no zone owns hold no scope and read nothing.
- **One scope index per scope a session can hold**: one for the root scope, which is made in memory and never written to disk (a file of every zone's rows could be opened by any session), and one for each zone (`Zones/<Zone>/.recall.sqlite`). `build` removes any index file that is no current scope's and makes the others again from the files, so a file left over from before a flag changed does not keep walled rows. Each holds the notes of its zone and the Meetings and Knowledge rows that its scope may read, and none else; past sessions are read by the root scope only. They are caches, never committed: delete every one and `build` makes them again. An index never sits in a cloud-synced folder; one that would is kept in memory.
- **Nothing to install.** It uses the SQLite in Python's standard library. When that SQLite has no FTS5 the tool says so and searches plain text, which ranks less well.
- **The wall is at the store.** `zone_of()` says which zone a record belongs to and `may_flow()` says whether the scope may read it, the same two the commit hook asks; Recall has no wall test of its own. A scope index holds only the rows `may_flow()` admitted, so a walled row is not in the file and cannot rank, count, order or be quoted. Nothing is filtered after a search. A file that changes is admitted or dropped again before the next search, and an index that drops a file it still finds on disk is made again, so none of its text stays in the file. A record with no zone (a Meetings page without its `zone:`, a zone's `Todo.md` outside its own zone) is in no scope index but the root's. A Meetings page of another walled zone is not in a zone scope; the open zones are in every scope. Knowledge crosses every wall; a Knowledge page that names a zone is not published and is in no zone scope. A session at the workspace root or in `System/` reads the root scope, every zone. `read ID` answers only for an id in your scope index, and answers an id that is not there the same way whether it is unknown or walled. The count in the answer is what you may read.
- **Names and near spellings.** Before the query, a word or a run of up to three words that settles to a party, person or alias in `System/context.md` is searched in every spelling the tables give, with and without spaces (`acme corp`, `acmecorp`). A word the scope has no row for is widened to near spellings through a second FTS5 table with the `trigram` tokenizer, which the SQLite of macOS carries; where it does not, the tool does without it and does not fail.
- **Ranking.** The words become an OR of quoted words, ranked by BM25 on `unicode61` with accents folded and no stemmer, so it works in any language. A second pass over raw chunks of about 4,000 characters (raw records and session text) is merged in by reciprocal rank fusion (`k` 60, the raw list at half weight). A small bonus favours recent items, and a page with `superseded:` counts half.
- **Pages first, the raw record when no page answers.** A raw record, such as a full transcript, is indexed as chunks, but a search ranks pages only, since a page already holds what the call decided. When no page matches, the search goes to the raw chunks and marks each result "from the raw record". `--raw` puts the chunks back in the ranking for one search, and Ask's `search` has the same choice. A wiki sets its own default with `"recall": {"raw": "fallback" | "always" | "never"}` in `Wikis/<Wiki>/schema.json`, `fallback` unless it says otherwise: a library of frozen reports, whose raw record is the only copy of the text, can choose `always`. For the Knowledge wiki that file is also its layout declaration: a `schema.json` made only for `recall` makes `check.py` hold the wiki's source pages to the layout it declares, Garrick's default fields unless the file says otherwise, so expect the check to start reporting against them. Raw chunks are rows of the same scope index, so the walls apply to them as to a page, and `read` still reads them.
- **The grades of [Fading](#fading) hold.** Working pages are searched first. Dormant pages join when the working ones fall short, if the `reach` setting allows it, and the answer says "from older notes". Archived pages join only with `--archived`.
- **No scheduler.** Before each search the tool refreshes its scope index from the files changed since the last one, by modified time and size, and by what a file takes from another (a hub's party, the page that cites a raw record).
- **Past sessions.** Claude Code deletes its transcripts after 30 days unless `cleanupPeriodDays` says otherwise, and the `setup` skill offers to raise it. `recall.py extract` writes what the user said, what the assistant said and each command it ran, with its exit status as one short line after it, to `<YYMMDD> - <session id>.md` (it carries no project: what a session read can be known only from what it typed, and a command can reach another project in more ways than any reading of it can name; a workspace path that names no place drops the session) in the gitignored `.sessions/` folder of the zone the session was opened in. Tool output and everything loaded into the session (rules, context, memory index) are left out, and anything shaped like a key, a token or a password is masked. Past sessions are searched only from a session opened at the workspace root, never from a zone or a project, and a `project:` line in an older session file is not trusted. A session opened at the root or in `System/` goes to `System/.sessions/`. A session whose folder cannot be placed plainly goes nowhere. With the [scheduled jobs](extras/scheduled-jobs.md#the-nightly-job) extra, the nightly job extracts new sessions and builds the indexes.
- **The check** reports an index or a `.sessions/` file that is staged or committed.

## The two memories

`Wikis/Meetings/` and `Wikis/Knowledge/` are empty after install. Their schemas (what a page needs, where raw material goes, what must never cross between them) are in each folder's own `AGENTS.md`.

Everything comes in through an inbox. Drop a transcript from any recorder (a `.txt`, `.md` or `.vtt` file, not the audio) into `Wikis/Meetings/raw/inbox/`, and mail (a `.eml` file, or the message saved as `.txt` or `.md`) or any other file into a zone's `Inbox/`. Then say "process the inbox". The `intake` skill sorts each item by the *Ways in* rules in `System/rules.md`: a conversation goes to Meetings, through the `meetings` skill; something to read goes to Knowledge, through the `knowledge` skill; material for a project goes into that project's `Sources/`, with the mail it came in kept in Meetings. It asks for the zone, the parties or the project when they are not obvious, goes by the mail domains in the Parties table, and records any you teach it. Ways to fetch mail into an inbox without doing it by hand are in [ways in](extras/ways-in.md).

You can also hand over a link, a PDF or pasted text and say "read this": the `knowledge` skill freezes the original into `raw/` and writes the pages. "Prep me for Acme" and "what does my library say about X" read them back. Old pages [fade](#fading) out of working memory, and a question reaches back for them, saying so.
