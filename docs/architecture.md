# Architecture

Garrick is a shell around Claude Code or Codex: you work through it, and the agent does the work underneath, in its desktop app or a terminal. It has four layers, and [the diagram page](architecture/overview.html) draws them ([as an image](architecture/overview.png)):

1. **Navigate and control: the Garrick App.** The control panel over your zones, projects and threads. It is not where the work happens.
2. **Where you work: the Claude or Codex desktop app, or cmux.** Alternatives: you use one or the other, on the same files.
3. **The record: Knowledge, Meetings and the threads.** Plain files you own. Mail, files and recordings are filed into it.
4. **Underneath: Claude or Codex as the model**, reading **the rules** first, with **the commit check** beside it.

The rules, the walls and the model act on the whole record, never on one box of it. The model reads across every zone and both wikis when a request needs it. The rules hold in every zone, project and wiki. The walls are declared once, in `System/context.md`, and hold wherever material is used. The commit check runs in each zone, and compares what is being committed with every meeting page and every project on the far side of a wall, wherever they sit.

The words on this page are defined in [Concepts](concepts.md). [How Garrick keeps context](context.md) follows what the record holds through four stages, from the inbox to the archive.

## Navigate and control

**The Garrick App** is the control panel over your zones, projects and threads: where each stands, what is due, and what is waiting on you. It is not where the work happens. It opens a piece of work in the app you work in, and the work is done there.

The Garrick App's home lists your work, most recent first, each with its next action. Continue opens Claude's desktop app on that piece of work, with Claude's answer already on screen. Ask something reaches across all of your work, and Needs you holds only the questions Garrick is waiting on you to answer. That is **the simple home**, which a new workspace opens on. See [The simple home](extras/simple-home.md).

*More*, or *Settings › Home*, opens **the full page**, in four tabs:

- **Overview**: every live thread, one column per zone, each with at most two chips, *todo* for its open actions and *check* for an error the page can explain and fix; open actions and the inboxes beside them; and *Explore*, the graph of the notes in one zone or one wiki at a time.
- **Todo**: each zone's `Todo.md`, to tick, date and add to. A workspace with no `Todo.md` has no Todo tab.
- **Status**: the machinery: what needs attention, the check, the scheduled jobs and the assistant's calls, and the state of each repository.
- **Guide**: these pages, as the release the workspace runs shipped them, in `System/garrick-docs/`.

The Garrick App is one HTML page, `System/generated/status.html`, built by `status.py` from the workspace's own files. It shows in **the Mac app**, *Garrick.app*, in **Obsidian** through its plugin, or in a browser. A workspace installed with this Garrick has it from the start: the installer puts the extra in `System/status/` and builds the page once, and "Set up Garrick" offers to build the Mac app. A workspace installed before the simple home keeps what it had. The code keeps its old name, `status.py` in `extras/status/`. See [The Garrick App](extras/status-page.md).

The layers below do not depend on it. Without the Garrick App, the same work is done by asking the assistant: "what's open", "park X", "process the inbox".

#### The Garrick App's actions

In the Mac app and in Obsidian, its buttons act: they tick, date and add Todo lines, park and wake threads, make, rename and delete projects and threads, answer a question in Needs you, and hand a piece of work to Claude. In a browser the page can change nothing, so there the buttons copy what to say instead.

Every action, from a button, the Ask box or a skill, goes through `page_action.py` in the status extra, and every one is declared in one table, `DECLARED` in `System/tools/operations.py`. A row per verb names the fields a request may carry, which of them say what the request is, what it may touch, whether it commits, whether a retry is safe, and what must still be true for it to run. Validation is closed: a request that carries a field its verb does not declare is refused, and the field is named. Park, wake and the four Todo verbs, the subset `OPS`, also keep a durable record in `operations.jsonl` in the jobs folder, so a reloaded page can find an action still running or learn how it ended, and so the same request sent again is recognised: joined or answered inside a double click's window, and past it, for as long as any client could still be waiting, asked about rather than done twice. That folder is outside the workspace, so the record is never committed; the notes and git stay the record of what changed. A launcher, such as *Open in Claude*, is reported the same honest way: the page says only that it is opening, and the Mac app or the Obsidian plugin, which alone knows how it went, says what opened. A Mac app built before that change says nothing back, so the opening line is all there is until it is rebuilt.

## Where you work

The work happens in your assistant's own app, on the same files whichever you choose:

- **The Claude or Codex desktop app.** Claude's desktop app, in its Code tab, is where the Garrick App's *Continue* and *Ask something* open, through the Claude Code command-line tool. Codex works in its own desktop app, without the home's Continue: the full page's *Open in Codex* opens the folder there and puts "open Pricing" on the clipboard. See [Desktop first steps](first-steps.md).
- **cmux**, a Mac terminal with one tab per thread. Its extra adds the `desk` skill: "open X" opens or brings forward that thread's tab, "close X" wraps it and closes the tab, and "start the day" brings the tabs back. The Garrick App's *Open in cmux* goes through the same desk. See [cmux](extras/cmux.md).

A terminal on its own works too, with Claude Code or Codex CLI: see [Terminal setup](terminal-setup.md). Wherever you work, you name a thread and the assistant reads its resume point, as [A working day](#a-working-day) follows below. Two extras sit here: **the Garrick band**, a Claude Code mod that shows the current thread, its status and how full the context is above the prompt, with buttons to wrap and clear ([the Garrick band](../extras/mods/README.md)), and **phone access**, through the assistants' own remote features ([Phone access](extras/phone-access.md)).

## The record

Behind the home, Garrick holds three things in one place: what you're working on, in your files; what was said, in a record of your meetings; and what you read, in a library of what you've studied. It files what comes in, such as mail, transcripts and documents, into the right one.

**The record** is a folder of Markdown files under git, `~/Garrick` by default, made by the installer from the repository's `template/`. Its parts, each its own git repository or part of one:

- **The threads**, in **zones**: `Zones/<Zone>/`, one repository each. A zone holds its **projects**, each project its **work threads**, and each thread one note with its **Resume here** block: what is done, the next action and what was only in your head. The zone's `Todo.md` is its list of open actions, and its `Inbox/` is where mail and files wait to be sorted.
- **Meetings** and **Knowledge**, the two wikis, in `Wikis/`, one repository between them. **Meetings** holds every conversation from every zone, each page with its zone and parties. **Knowledge** holds published material you read, with no parties. Each keeps the record as it arrived in `raw/` and its pages in `wiki/`; old pages fade into `dormant/` and `archive/` folders beside them, still findable.
- **`System/`**, in the workspace root's own repository: the rules, `context.md`, the skills, the tools, the templates and Garrick's docs. `System/generated/` holds pages a tool rebuilds, the Garrick App's among them, and is never committed.

The root's `.gitignore` leaves `Zones/` and `Wikis/` out, so each repository has one history and a commit never spans two of them.

**Mail, files and recordings** are filed into the record by the `intake` skill, from an inbox: see [Material coming in](#material-coming-in).

Your folders stay as they are. A project can point at a folder you already keep, with `folder:` in its hub, and Garrick reads it and writes nothing there unless you ask it to move the files in: see [Your own work](extras/simple-home.md#your-own-work). Garrick's own record is plain Markdown in folders on your Mac, and updates keep your edits.

## Underneath

Claude does the work underneath. Codex works too, in its app or a terminal, without the home's Continue. Garrick has no model of its own: **the model** reads the files, follows **the rules** and **the skills**, runs **the tools** and writes the notes. Beside it, **the commit check** refuses some of what the rules forbid, whatever the model intended.

### The assistant

**Your assistant** is Claude Code or Codex, in its desktop app or a terminal. Garrick asks it to read `AGENTS.md` and the rules before anything else, to ask before anything leaves the machine or cannot be undone, to check the Walls table before it uses a meeting, and never to skip the wall check with `git commit --no-verify`. The assistant's own permissions decide what it can run; the installer can allow Garrick's own tools and git's read and save commands, and nothing that pushes. See [Assistant compatibility](harnesses.md).

### The rules

**The rules** are plain files the assistant reads first. They say what goes where and who never mixes:

- `AGENTS.md` at the root is the entry point. It sends the assistant to `System/rules.md` and `System/context.md`, and routes each question by its subject. Each zone, `Wikis/` and each wiki has its own `AGENTS.md`, which adds what holds only there.
- `System/rules.md` says how the assistant behaves: what it may do without asking, the walls, the ways in, threads, voice and files. It is Garrick's, as shipped.
- `System/context.md` says who you are and who you deal with: zones, parties, walls, people and aliases. It is yours.
- `System/rules.local.md`, and an `AGENTS.local.md` beside any `AGENTS.md`, hold your own rules and routing.

Where two say different things, the local file wins over the Garrick file beside it, and a zone's or a wiki's `AGENTS.md` wins over the root's where it says so. An update replaces Garrick's files and never touches yours. See [Garrick's rules, and yours](principles.md#garricks-rules-and-yours).

### The skills

**The skills** are the procedures, one `SKILL.md` each in `System/skills/`, linked into `.claude/skills` and `.agents/skills` so both assistants find them. The assistant picks one when a request matches it:

| Skill | What it does | Started by |
|---|---|---|
| `threads` | Opens, wraps, holds, parks, finishes, renames and creates threads, catches you up on what changed, and adds zones | "open X", "wrap it", "close for the day", "I'm being interrupted", "back", "park X", "what's open", "what's next", "catch me up", "new project X for Acme" |
| `intake` | Sorts the inboxes, one item at a time, by the Ways in rules | "process the inbox", "file my mail", "file this" |
| `meetings` | Files a conversation as a Meetings page, and briefs for a meeting | "file this transcript", "log this call", "prep me for X" |
| `knowledge` | Freezes published material into the Knowledge wiki, and answers from it | "read this", "add this to knowledge", "what does my library say about X" |
| `todo` | Sweeps actions the records hold into each zone's `Todo.md`, and tidies it | "sweep my actions", "what do I owe people", "what am I waiting on" |
| `nurture` | Sorts what the checks found by what a fix needs, applies the mechanical fixes on one yes, and proposes which wiki pages fade | "nurture the context", "nurture Work", "review the context with me", "fade the meetings", "what would fade", "keep X" |
| `interview` | Asks about your work one question at a time, then proposes parties, walls, projects and threads | "interview me", "help me set up my workspace" |
| `setup` | Finds out what your Mac has and how you work, and writes it down | "set up Garrick", "check my setup", "add a rule", "set up notifications" |
| `update` | Brings the workspace up to a newer Garrick, and merges what it leaves | "update Garrick", "merge the update", "split my rules" |

The cmux extra adds a tenth, `desk`, under [Where you work](#where-you-work).

### The tools

**The tools** are Python scripts, standard library only, for what code does better than an assistant. They move, parse, check and list; they never choose where a thing goes.

- `check.py` tests the workspace against every rule a machine can check. Run by hand it reports; run by the pre-commit hook as `--staged --walls-only` it refuses. See [The check](commands.md#the-check).
- `scaffold.py` makes zones, parties, projects and threads, and parks, wakes, renames and deletes them. It checks a name and a party before it writes anything. See [Your first project](commands.md#your-first-project).
- `garrick_lib.py` is what the other tools share: reading frontmatter and `context.md`, the naming and tag rules, and writing the wall hook into a repository.
- `operations.py` declares every action the Garrick App can ask for, in one table, `DECLARED`, and keeps a durable record of six of them.
- `install.py`, in the repository and not in the workspace, makes a workspace. `install.py --update` runs `update.py` beside it, which brings a workspace up to that Garrick.
- `release.py` asks GitHub whether a newer Garrick is out and runs the update from it, only when asked or switched on.
- `notifications.py` is the one way Garrick tells you something: every notice goes through it, to this Mac, or to a session's own tab in cmux, as the Garrick App's Settings › Notifications says. It installs the hooks that let a Claude Code or Codex session say it needs you or has finished. It never reaches the network.
- `correct.py` stops a wrong value everywhere: it lists every live copy, in memory, `System/context.md`, hubs, thread notes, `Todo.md` and the wikis, and on a yes fixes them all, one commit per repository, marking a page whose raw record holds the old value as superseded. See [Correcting a value](commands.md#correcting-a-value).
- `briefing.py` gathers what changed in a zone's threads over a period, for "catch me up", and decides nothing; `next_up.py` ranks one thing worth doing while a long turn runs, for "what's next" and for the band's *While you wait*, a preview feature that is off unless you switch it on.
- `discover.py` proposes the pieces of work in a folder you keep, from names and dates alone, and `extract.py` takes the text out of their Word, PowerPoint and Excel files; neither writes in that folder. `example.py` puts the worked example away and brings it back.
- `probe.py` lists what the Mac has, for the setup skill; `drift.py` compares a published deliverable with its shared copy; `wiki_lint.py` finds orphan pages and broken links in a wiki; `nurture.py` sorts what those find by what a fix needs, and applies the mechanical ones on a yes; `fade.py` proposes which wiki pages leave working memory, by age, kind and use, and moves them, links and all, on a yes. See [Fading](commands.md#fading).

### The commit check, and the zone guard

**The guards** are the code that stops something rather than reporting it:

- **The pre-commit wall check.** The installer writes a git hook into each zone, and `check.py --install-hooks` into any git repository inside a project too, that runs `check.py --staged --walls-only` on what is being committed. A project file that links to, names or quotes a party across a declared wall is refused with one line naming the file and the wall, and so is anything from an inbox. It catches specific signs of a crossing, not every crossing: see [the known gaps](enforced.md#the-wall-checks-known-gaps). The wikis' own repository has no hook. `check.py --install-hooks` puts a zone's hook back, and the check warns when git's `core.hooksPath` setting sends commits past it.
- **The zone guard**, optional. A hook for Claude Code and Codex that stops the assistant once before it edits a file outside the project the session was opened in, so that it asks you. It covers the file-editing tools, not shell commands, and records nothing about your answer. See [the zone guard](../extras/hooks/README.md).

[What is enforced, and what is asked](enforced.md) lists every guard beside the rules that depend on the assistant alone.

## The extras

**The extras** are optional, in the repository's `extras/`, and core Garrick never depends on any of them. The installer puts in one, the Garrick App's, because a new workspace opens on its simple home; the rest you add when they solve a problem you have. See [Extras](extras/index.md).

| Extra | Layer |
|---|---|
| [The Garrick App](extras/status-page.md), with its Mac app and Obsidian plugin | Navigate and control |
| [cmux](extras/cmux.md) and its `desk` skill, [the Garrick band](../extras/mods/README.md), [phone access](extras/phone-access.md) | Where you work |
| [Obsidian](extras/obsidian.md), to browse the record as a linked vault; [ways in](extras/ways-in.md) and [a meeting recorder](extras/meeting-recorder.md), to feed it | The record |
| [Scheduled jobs](extras/scheduled-jobs.md), which run the check, a script or an assistant on a schedule under a deny profile and spend caps; [the zone guard](../extras/hooks/README.md) | Underneath |

## The flows

### Material coming in

**Recordings**, **mail** and **files you drop in** arrive by one of the [ways in](extras/ways-in.md): by hand, by a script or by your assistant's mail connector. Each lands in an inbox first: a transcript in `Wikis/Meetings/raw/inbox/`, mail and other files in a zone's `Inbox/`. "Process the inbox" starts the `intake` skill, which looks at each item and **files it where it belongs** by the Ways in rules. A recording is always a conversation, filed in Meetings. A mail exchange is filed in Meetings too, with its zone and parties; something to read goes to Knowledge; material for a project goes into its `Sources/`, after the wall between the project's party and the material's parties is checked. When the zone, a party or the project is unclear, the assistant asks.

### A working day

You press Continue on the Garrick App's home, or open a session in your app or terminal and say "open Acme pricing". The assistant reads the thread's Resume here block and answers in two sentences: where it stands, and the next action. You work, and what the session writes is committed in the zone's repository, where the wall check runs on every commit. If something cuts in, "I'm being interrupted" saves your place in the block and puts the thread on the interruption stack, and "back" brings it back. At the end, "wrap it" rewrites the Resume here block so it describes now, adds a dated entry below it, puts open actions in the zone's `Todo.md` and commits. "Close for the day" does that for every thread touched today. The next session, in either assistant, starts from that block.

### The walls

Walls are declared in one place, the Walls table of `System/context.md`, and every project and meeting carries the party tags they are checked against. They are read by the assistant: before it uses a meeting in a project, the rules ask it to compare the project's party with the meeting's parties and leave walled material out, saying only that something was held back. They are enforced, in part, by code: the pre-commit hook in each zone refuses a project file that links to a walled meeting, names a party or person from across the wall, or repeats eight words held only on the far side. A clean paraphrase, a chat reply and anything sent are outside what the hook can see, and the check has known gaps. See [What the check covers](principles.md#what-the-check-covers) and [What is enforced, and what is asked](enforced.md).

### An update

Garrick publishes a release. "Update Garrick", or `python3 System/tools/release.py update`, downloads it into a temporary folder outside the workspace and runs that release's own `install.py --update`, which compares every file it would write with yours and with the fingerprint recorded when Garrick last wrote it. It reports first: a file you never changed is replaced, a new one is added, and a file you changed that Garrick changed too gets Garrick's version beside it as a `.new`. Your rules, your `context.md`, your notes and the local files are never replaced. With `--apply` it writes the files and makes one commit in each repository it touched, which `git revert` undoes. "Merge the update" then goes through each `.new` with you, and the check warns while one waits. See [Updating](updating.md).
