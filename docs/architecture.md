# Architecture

Garrick is a shell around Claude Code or Codex: you work through it, and the agent does the work underneath, in its desktop app or a terminal. It has four layers, and [the diagram page](architecture/overview.html) draws them ([as an image](architecture/overview.png)):

1. **Navigate and control: the Garrick App.** The control panel over your zones, projects and threads. It is not where the work happens.
2. **Where you work: the Claude or Codex desktop app, or cmux.** Alternatives: you use one or the other, on the same files.
3. **The record: Knowledge, Meetings and the threads.** Plain files you own. Mail, files and recordings are filed into it.
4. **Underneath: Claude or Codex as the model**, reading **the rules** first, with **the commit check** beside it.

The rules, the walls and the model act on the whole record, never on one box of it. The model reads across every zone and both wikis when a request needs it. The rules hold in every zone, project and wiki. The walls are declared once, in `System/context.md`, and hold wherever material is used. The commit check runs in each zone, and compares what is being committed with the files of every other walled zone, wherever they sit.

The words on this page are defined in [Concepts](concepts.md). [How Garrick keeps context](context.md) follows what the record holds through four stages, from the inbox to the archive.

## Navigate and control

**The Garrick App** is the control panel over your zones, projects and threads: where each stands, what is due, and what is waiting on you. It is not where the work happens. It opens a piece of work in the app you work in, and the work is done there.

The Garrick App opens on your work, most recent first, each piece with its next action. *Claude* and *Codex* each open a new session in the desktop app, in the folder of that piece of work, with the request to open it typed in and not sent: you press Enter.

Below that is **the full page**, in tabs, fewer when a tab has nothing to show:

- **Overview**: every live thread, one column per zone, each with at most two chips, *todo* for its open actions and *check* for an error the page can explain and fix; open actions and the inboxes beside them; and *Explore*, the graph of the notes in one zone or one wiki at a time.
- **Todo**: each zone's `Todo.md`, to tick, date and add to. A workspace with no `Todo.md` has no Todo tab.
- **Status**: the machinery: the scheduled jobs and the assistant's calls, and the state of each repository.
- **Context**: one card of what needs you, a line for each zone or wiki that holds something. Each line opens a queue where the questions your wikis and Nurture raise are answered one at a time.
- **Guide**: these pages, as the release the workspace runs shipped them, in `System/garrick-docs/`.

The Garrick App is one HTML page, `System/generated/status.html`, built by `status.py` from the workspace's own files. It shows in **the Mac app**, *Garrick.app*, or in a browser. A workspace installed with this Garrick has it from the start: the installer puts the extra in `System/status/` and builds the page once, and "Set up Garrick" offers to build the Mac app. The code keeps its old name, `status.py` in `extras/status/`. See [The Garrick App](extras/status-page.md).

The layers below do not depend on it. Without the Garrick App, the same work is done by asking the assistant: "what's open", "park X", "process the inbox".

#### The Garrick App's actions

In the Mac app, its buttons act: they tick, date and add Todo lines, park and wake threads, make, rename and delete projects and threads, and open a piece of work in Claude, Codex or cmux. In a browser the page can change nothing, so there the buttons copy what to say instead.

Every action, from a button, the Ask box or a skill, goes through `page_action.py` in the status extra, and every one is declared in one table, `DECLARED` in `System/tools/operations.py`. A row per verb names the fields a request may carry, which of them say what the request is, what it may touch, whether it commits, whether a retry is safe, and what must still be true for it to run. Validation is closed: a request that carries a field its verb does not declare is refused, and the field is named. Park, wake and the four Todo verbs, the subset `OPS`, also keep a durable record in `operations.jsonl` in the jobs folder, so a reloaded page can find an action still running or learn how it ended, and so the same request sent again is recognised: joined or answered inside a double click's window, and past it, for as long as any client could still be waiting, asked about rather than done twice. That folder is outside the workspace, so the record is never committed; the notes and git stay the record of what changed. A launcher, such as *Claude*, is reported the same honest way: the page says only that it is opening, and the Mac app, which alone knows how it went, says what opened. A Mac app built before that change says nothing back, so the opening line is all there is until it is rebuilt.

#### The view model

The Garrick App does not read your notes to decide what a card means. The core does that, in `System/tools/view.py`, and builds one JSON document of the workspace: `view.build(root)`, also `garrick_lib.view`. `status.py` takes the document and draws it, so a change of wording or layout cannot change what is true, and what is true can be tested without a page. The module reads through `work.py`, the one reader of the piece of work, and offers each piece the verbs of `DECLARED` that apply to it. It writes nothing.

Every record carries its zone. A count is of one zone or one wiki, never two added together. `build(root, scope=["Work"])` holds that zone's records alone, and a zone folder that is a link, or an `Inbox` or a thread folder that leads out of its zone, is left out. What the page still reads for itself, because no core module owns it yet, is named in the document's `left` list.

The shape, with one piece of work and one inbox:

```json
{"api": 1,
 "zones": [{"name": "Work", "linked": false, "done": 0, "held": [],
            "projects": {"Acme": {"status": "live", "spoken": "", "own": false, "heading": false,
                                  "hub": "Zones/Work/Acme/Acme.md", "party": ["acme"],
                                  "files": 4, "layout": ["split"]}},
            "open_links": [["Pricing"]],
            "todo": {"file": "Zones/Work/Todo.md", "order": ["Inbox", "Soon"],
                     "tasks": [{"file": "Todo.md", "section": "Soon", "key": "0f3a9c21d4b7e855", "text": "Send the memo",
                                "thread": "Pricing", "target": "Pricing", "unsure": false, "due": "2026-11-25",
                                "scheduled": null, "priority": null, "tags": [], "waiting": false, "also": [], "src": null,
                                "line": "- [ ] [[Pricing]]: Send the memo 📅 2026-11-25",
                                "note": "Zones/Work/Acme/Threads/Pricing/Pricing.md", "label": "Pricing",
                                "project": "Acme", "tname": "Pricing"}],
                     "done": []},
            "questions": [{"file": "Acme/Needs you/fence.md", "zone": "Work", "ask": "Which fence?", "options": ["Cedar", "Pine"],
                           "asked": "2026-11-20", "own": "", "work": "Acme", "intake": false}],
            "work": [{"id": "Work/Acme/Pricing", "zone": "Work", "project": "Acme", "thread": "Pricing",
                      "shown": "row", "state": "active", "held": false,
                      "note": "Zones/Work/Acme/Threads/Pricing/Pricing.md", "rel": "Acme/Threads/Pricing/Pricing.md",
                      "hub": "Zones/Work/Acme/Acme.md", "party": ["acme"], "updated": "2026-11-02", "spoken": "",
                      "heading": false, "files": 3, "open": 1, "resume": true, "resumed": "2026-11-02", "checkpoint": null,
                      "touched": "2026-11-02",
                      "read": {"block": true, "date": "2026-11-02", "where": "Drafting.", "rows": {}, "entry": null, "about": ""},
                      "actions": ["park", "rename", "move", "delete", "continue", "open", "close"]}]}],
 "today": "2026-11-22",
 "queues": {"inbox": [{"place": "Work", "kind": "zone", "folder": "Zones/Work/Inbox", "count": 2}]},
 "wikis": [{"name": "Meetings", "folder": "Wikis/Meetings", "log": "Wikis/Meetings/wiki/log.md", "count": 12,
            "when": "2026-11-20", "title": "Weekly review", "markdown": false, "page": "wiki/sources/review.md",
            "unread": false}],
 "repos": [{"name": "Work", "folder": "Zones/Work", "dirty": 1, "changes": [["Acme/Acme.md", ["unstaged"]]],
            "unread": false, "since": "2026-11-21T09:12:00", "last": "2026-11-20T17:30:00"}],
 "graph": {"places": [{"name": "Work", "folder": "Zones/Work", "zone": true}],
           "notes": [{"place": "Work", "zone": true, "path": "Zones/Work/Acme/Acme.md", "rel": "Acme/Acme.md", "type": "project",
                      "status": "active", "updated": "2026-11-02", "party": ["acme"], "title": "Acme"}],
           "edges": []},
 "example": null,
 "system": [{"name": "Sys", "notes": ["System/Sys/Sys.md", "System/Sys/Threads/Job/Job.md"]}],
 "left": ["waiting sessions"]}
```

`files`, `open`, `layout` and `open_links` are what the Rename, Move and Delete dialogs say: the files a delete would take, the open lines of the zone's `Todo.md` that link a note, and the layout change a project offers; `open_links` holds only the names of the notes a line links, never its words. `shown` says where the page draws a piece: `row` (live), `parked`, `done` or `hub` (a hub's own resume point beside its threads). A done piece carries no resume fields, as its note is not read. `todo` is the zone's open actions, as the Todo tab draws them: every open line of the zone's notes with the note it names (`note`) and the project and thread of that note, the `## ` headings of its `Todo.md` in order, and the lines ticked on `today`, the day the build counts from. The view model decides which note a line names; the page decides what late means and how a row sorts. A zone folder that is a link has no `todo`, and a note that is a link into another zone or a wiki gives that zone none of the lines it leads to. `questions` is what Garrick asked and waits on, the open files in the `Needs you` folders of the zone, its projects and its threads, oldest first; one put off to a day that has not come is left out, and a project, thread or file that is a link into another zone or a wiki is not read. `wikis` is each wiki's log: how many entries it holds and the newest one, with the page it names, taken from the wiki's own folder; a log that is a link into another zone or a wiki is not read, and a wiki belongs to no zone, so a build limited to some zones holds none. `repos` is what each repository has uncommitted: the root, each zone, the wikis, and a wiki with one of its own; a repository git could not read is `unread`, never clean, a zone folder that is a link has none here, and a build limited to some zones holds those zones' repositories alone. `graph` is what Explore draws: every note of the zones and of the wikis with its place, kind, status, date, parties and title, and the links between notes as pairs of indexes, each pair once. Notes in an `Inbox`, in an archive or raw folder, hidden notes, instructions and what the vault excludes are left out, and so are a zone folder that is a link and a note that is a link into another zone or a wiki; a build limited to some zones holds those zones' notes and no wiki. `example` names the zone the worked example is in, by the `.example.json` marker that zone holds, or is null. `system` lists the projects kept in `System/`, which belong to no zone: the hub note and each thread note, by path, so the page can match a Todo line's link to one; a build limited to some zones holds none of it. The field names are stable: the page, the tests and any later reader build on them.

Settings has a document of its own: `view.settings(root)`, from `System/tools/view_settings.py`. It is not part of `build()`, because Settings is the page's and not a zone's, and it names every zone's walled flag, so it never rides in a document built for one zone. It reads the files the page used to read for itself and writes nothing: the choices in `System/garrick-settings.json`, the fade settings, the notice switches, the channels, the read guard's state and log, the flags, and this computer's role. `status.py` draws it. A reader that cannot read its source leaves its field empty or `null`, and the section is drawn as it is when that source is missing. `view.settings(root, only=("flags",))` reads the parts named and no others.

```json
{"api": 1,
 "desk_agent": "claude",
 "flags": {"effort": false},
 "release": {"number": "0.79.0", "installed": "Garrick 0.79.0 ...", "notice_on": false, "notice_every": 1, "stale": []},
 "usage_counts": true,
 "walls": {"flags": {"Work": true, "Personal": true}, "pending": false},
 "notifications": {"settings": {"tell": {"needs-you": true}, "after": 10, "quiet": {"on": false, "from": "22:00", "to": "07:00"}},
                   "tell": [["needs-you", "a session needs me"]], "after_max": 120, "own_way": {}},
 "channels": {"settings": {"ask": {"tier": "sonnet", "effort": "medium", "autonomy": "read"}},
              "capability": {"ok": true}, "names": ["ask", "telegram"], "tiers": ["haiku", "sonnet", "opus"],
              "efforts": ["low", "medium", "high"], "levels": {"ask": ["read", "act", "full"], "telegram": ["read", "act"]},
              "telegram": {"state": "off", "said": "Telegram is not set up.", "last": ""}, "held": []},
 "memory": {"age_said": "...", "wake_said": "...", "error": null, "settings": {"wikis": {}, "kinds": {}, "pins": {}},
            "counts": {"Meetings": {"working": 12, "dormant": 0}}, "full_list": {}},
 "machine": {"role": "solo", "name": "", "server": ""},
 "read_guard": {"state": {"registered": false, "mode": "off", "cross": "deny", "tools": [], "skip": [], "problem": "", "would": {}}, "codex": false}}
```

What stays with the page, because it is this Mac's and no workspace's: which apps are installed, this Mac's launchd agents (the page hands them in, so a notice row can say who sends it), and whether cmux is here. A zone's colour and icon, and each kind of note's colour in Explore, are read for the cards too, so the page reads them once for both.

#### What the App reads on this Mac

Some of what the page shows is this Mac's and no workspace's: the jobs the scheduler runs, and the files the App keeps under `System/`. None of it is in `build()`, so a document built for one zone holds nothing from it. Each has a reader of its own in the core, reached through `view.py`, that reads the same files the page used to read, writes nothing, starts no process and gives its empty value for a file that is missing or does not read, never a path or the text of an error. `status.py` keeps what a state means (late, idle, failed), the words of a row and how it is drawn.

The scheduled jobs are `view.jobs_reader()`, from `System/tools/view_jobs.py`. Each reader takes the folder it reads as its first argument (the jobs folder, or the launch agents folder), as the page's own functions did, and follows no link or `..` that they did not. It does not load the jobs extra: the extra's own lock rule stays with the page, which has it loaded or not.

```json
{"agents": {"brief": {"agent": true, "env": {"GARRICK_ABOUT": "A morning brief"}, "label": "garrick.brief",
                      "about": "A morning brief", "plist": "/Users/jo/Library/LaunchAgents/garrick.brief.plist",
                      "mtime": 1763000000.0, "timing": {"StartCalendarInterval": {"Hour": 6}}}},
 "heartbeats": [{"name": "brief", "heartbeat": {"job": "brief", "finished": "2026-11-20 09:00:00", "exit": 0}}],
 "runs": [["2026-11-19 09:00:00", 0, false]],
 "steps": [{"step": "effort", "exit": 1}],
 "lock": {"dir": true, "until": "1763000600 4242 1763000000", "mtime": 1763000000.0}}
```

`agents` is the plists that run `job.py`, by job name, with the keys the schedule is read from; `heartbeats`, `runs`, `steps` and `lock` are what one job's files say, each from the file the job's name gives. The page works out the schedule in words and how long before a run is late from `timing`.

The App's own files are `view.app_reader()`, from `System/tools/view_app.py`: what drift.py last found, the installer's version stamp, what the last run of Process the Inbox left, the release notes, the check's kept result, Nurture's record of a day, the check settings and a zone's follow-up records. Each reader takes the folder or the file the page's own reader took. A file the page both reads and writes has its read here and its write in `status.py`: the page still writes the check's kept result, and only reads it through the core.

```json
{"drift": {"files": [{"state": "drifted", "project": "Acme", "file": "Threads/Pricing/memo.docx", "zone": "Work",
                      "here_changed": "2026-11-01", "shared_changed": "2026-11-05", "newer": "shared", "here": "a", "shared": "b"}]},
 "stamp": {"from": "release", "tag": "v0.80.0", "commit": "abc1234"},
 "inbox": {"at": "2026-11-20T09:00:00", "state": "done", "say": "Filed 2 items.", "places": {"Work": {"needs": 1}}},
 "check": {"workspace": "/Users/jo/Garrick", "at": 1763000000.0, "result": {"errors": 0, "warnings": 2}},
 "report": {"standing": [{"kind": "wall", "path": "Zones/Work/a.md:3", "line": "x", "check": "wall"}]},
 "settings": {"todo-chase-days": {"Work": 3}},
 "follow_ups": {"3f0a": {"found": "answered"}}}
```

`inbox`, `check` and `report` are `null` where there is no such file. Whether a kept check result is this workspace's, whether a run of Process the Inbox is recent or still going, and what a record means are the page's. The release notes are read as text.

What stays with the page, and why. The sessions that wait for you (`waiting_rows`): they are read from this Mac's assistant transcripts by `agents_working.py`, the extra's own reader, which the Mac app also uses to keep the Mac awake; it reads no folder of the workspace, and a core module cannot import an extra, so the view model names it in `left`. Where the workspace is, and the zone names the page lists while the core's tools are older than the page (`workspace_find.py`): these run before any view model exists and must work when it is missing, so they are the extra's, by design, not the core's. The module sits in the same folder as `status.py`, updates with it, and loads nothing from a folder before that folder is known to be a workspace. What the page writes and reads back itself stays with it: the page, the flags it was built with, and the check's kept result (its read is the core's). Beside `status.py`, the extra's other modules still read zones, wikis and notes, each for its own job and none for the view model: `questions_panel.py` and `finding_queue.py` (the Context card: the wikis' open questions, the file a finding names), `page_action.py` (the notes and `Todo.md` an action edits), `todo_lines.py` (the lines of a zone's notes, for ticking and editing), `outbox.py` (a roaming machine's queued Todo requests), `your_work.py` (where a new piece of work may go: the zones, the worked example's marker, the hubs put away), `work_files.py` (a folder of your own that a piece of work points at), `inbox_run.py` (the inboxes, and the links in `Zones/.shared`), `ask.py`, `ask_tools.py` and `ask_scope.py` (what an answer in Ask may read), `engine.py` and `hold.py` (the folder an exchange is bound to, and the target of a held write), `channels.py` (the zone names), and `effort.py` and `handoff.py` (session transcripts, and the working folders in them). `guide.py` reads Garrick's own docs. `status.py` reads no zone, wiki or note itself; it still resolves the path of a wiki page it links to and of a thread's folder it compares with the open sessions, which lists nothing and opens no file. The jobs extra's own files (its agent module, its ledger and its deny list) and the check's own program are read by the code that owns them.

#### What the App counts

The App counts which cards are opened, in `System/garrick-usage.json`: a card id, a day and a count, written by the status extra (`status.py` owns the file, through `page_action.py`'s `count-card`) and never committed. `System/tools/usage.py` reads it, with the operations journal and the App's action log, and prints the report. The setting `usage-counts` in `System/garrick-settings.json` turns it off. See [Counting which cards you open](extras/status-page.md#counting-which-cards-you-open).

## Where you work

The work happens in your assistant's own app, on the same files whichever you choose:

- **The Claude or Codex desktop app.** Claude's desktop app, in its Code tab, is where the Garrick App's *Claude* opens a new session, through the app's own link, and where *Ask something* opens, through the Claude Code command-line tool. Codex works in its own desktop app: the full page's *Codex* opens a new session there with "open Pricing" typed in, through its link. See [Desktop first steps](first-steps.md).
- **cmux**, a Mac terminal with one tab per thread. Its extra adds the `desk` skill: "open X" opens or brings forward that thread's tab, "close X" wraps it and closes the tab. The Garrick App's *Open in cmux* goes through the same desk. See [cmux](extras/cmux.md).

A terminal on its own works too, with Claude Code or Codex CLI: see [Terminal setup](terminal-setup.md). Wherever you work, you name a thread and the assistant reads its resume point, as [A working day](#a-working-day) follows below. Two extras sit here: **the Garrick band**, a Claude Code mod that shows the current thread, its status and how full the context is above the prompt, with buttons to wrap and clear ([the Garrick band](../extras/mods/README.md)), and **phone access**, through the assistants' own remote features ([Phone access](extras/phone-access.md)).

## The record

Behind the home, Garrick holds three things in one place: what you're working on, in your files; what was said, in a record of your meetings; and what you read, in a library of what you've studied. It files what comes in, such as mail, transcripts and documents, into the right one.

**The record** is a folder of Markdown files under git, `~/Garrick` by default, made by the installer from the repository's `template/`. Its parts, each its own git repository or part of one:

- **The threads**, in **zones**: `Zones/<Zone>/`, one repository each. A zone holds its **projects**, each project its **work threads**, and each thread one note with its **Resume here** block: what is done, the next action and what was only in your head. The zone's `Todo.md` is its list of open actions, and its `Inbox/` is where mail and files wait to be sorted.
- **Meetings** and **Knowledge**, the two wikis, in `Wikis/`, one repository between them. **Meetings** holds every conversation from every zone, each page with its zone and parties. **Knowledge** holds published material you read, with no parties. Each keeps the record as it arrived in `raw/` and its pages in `wiki/`; old pages fade into `dormant/` and `archive/` folders beside them, still findable.
- **`System/`**, in the workspace root's own repository: the rules, `context.md`, the skills, the tools, the templates and Garrick's docs. `System/generated/` holds pages a tool rebuilds, the Garrick App's among them, and is never committed.

The root's `.gitignore` leaves `Zones/` and `Wikis/` out, so each repository has one history and a commit never spans two of them.

**Mail, files and recordings** are filed into the record by the `intake` skill, from an inbox: see [Material coming in](#material-coming-in).

Your folders stay as they are. A project can point at a folder you already keep, with `folder:` in its hub, and Garrick reads it and writes nothing there unless you ask it to. Garrick's own record is plain Markdown in folders on your Mac, and updates keep your edits.

### How an action is recorded and settled

Every action that makes a commit (a park, a rename, a Todo tick, a note, a wrap, a write from a remote assistant) has its own record, and that record is written before the commit and closed after it. The Garrick App, a session and the remote access extra all go through the same code in `System/tools/operations.py`, so they leave the same record.

**What the record holds.** An operation id, the verb, the zone, a hash of what was asked, the commit the zone was at when the action began, who sent it, the times and where it got to. It holds none of your words: no note text and no Todo line text. It sits in the git folder of the repository the action changes, `.git/garrick-ops/`: the zone's own, or, for an answer to a finding, the zone's or wiki's the page is in. It travels with that repository and is never committed. A call names one repository, so an action in one zone never reads another zone's records, and the page alone settles and reports what a stopped action left (`operations`); a session, the ask box or a remote assistant gets nothing from it and marks nothing. A copy of the action's id and hash also goes into the commit's message as two last lines, `Garrick-Op` and `Garrick-Payload`, for every commit Garrick's page makes itself and for a rename, a move, a layout change and a deletion. A commit another tool makes on the action's behalf carries no such lines: Garrick then trusts it only while it is still in the history. Git's own history is the proof of whether the commit was made. A commit someone made by hand with the two lines is taken as the action's own.

**What happens in each case.** When an action ends, Garrick settles its record from git: one commit carries this id and this hash, so it is done, and the record names that commit; or none does and the zone is where it was, so it is not done. If Garrick was stopped in the middle (the Mac slept, the process was killed, the power went), the next run, or the next time the page asks what is running, does the same reading from git and says what it found, once:

- the commit is there: it was done, with that commit named;
- the commit is not there and nothing else changed: it was not done, and you can do it again;
- anything else, such as a commit with that id but another hash, two commits with it, a zone that something else changed in the meantime, or a repository Garrick cannot read: Garrick says it cannot tell, names the commit it found, and runs nothing.

**One action, one commit.** Sending the same action again with the same id gives back the first answer and makes no second commit. The same id with different words is refused. Git decides, not the file: before an action runs, Garrick reads the repository's history for a commit that already carries its id, so a record edited back to its start, or deleted, cannot make a done action run again when its commit carries the id. A few commits carry no id (the answer to a finding, an undo, a wall allowance); for those the record is the only evidence. A record that is damaged or in the wrong place no longer matches its seal and nothing runs on it. The seal catches that, not a record written on purpose.

**What you see.** If Garrick stopped in the middle of something, the page, when it asks what is running, gets a plain sentence for it, and shows it for the actions it keeps a list for: it went through, it did not and nothing changed, or it cannot tell and which commit to look at. Software older or newer than this one on the same workspace keeps working: the side that lacks the record carries on as before, without it.

## Underneath

Claude does the work underneath. Codex works too, in its app or a terminal, without the home's Continue. Garrick has no model of its own: **the model** reads the files, follows **the rules** and **the skills**, runs **the tools** and writes the notes. Beside it, **the commit check** refuses some of what the rules forbid, whatever the model intended.

### The assistant

**Your assistant** is Claude Code or Codex, in its desktop app or a terminal. Garrick asks it to read `AGENTS.md` and the rules before anything else, to ask before anything leaves the machine or cannot be undone, to check a meeting's zone against the project's before it uses it, and never to skip the wall check with `git commit --no-verify`. The assistant's own permissions decide what it can run; the installer can allow Garrick's own tools and git's read and save commands, and nothing that pushes. See [Assistant compatibility](harnesses.md).

### The rules

**The rules** are plain files the assistant reads first. They say what goes where and who never mixes:

- `AGENTS.md` at the root is the entry point. It sends the assistant to `System/rules.md` and `System/context.md`, and routes each question by its subject. Each zone, `Wikis/` and each wiki has its own `AGENTS.md`, which adds what holds only there.
- `System/rules.md` says how the assistant behaves: what it may do without asking, the walls, what lands in an inbox first, the resume point, how it answers and which files it never edits. It is Garrick's, as shipped, and it stays under 8,000 characters because every session loads it: the procedures live in the skills (`intake`, `threads`, `desk`, `nurture`), which load only when they run.
- `System/context.md` says who you are and who you deal with: you, the zones with the flag that says which are walled, the parties, the tags and the boundaries that are easy to get wrong. The people and the aliases are in `System/names.md`. Both are yours.
- `System/rules.local.md`, and an `AGENTS.local.md` beside any `AGENTS.md`, hold your own rules and routing.

Where two say different things, the local file wins over the Garrick file beside it, and a zone's or a wiki's `AGENTS.md` wins over the root's where it says so. An update replaces Garrick's files and never touches yours. See [Garrick's rules, and yours](principles.md#garricks-rules-and-yours).

### The skills

**The skills** are the procedures, one `SKILL.md` each in `System/skills/`, linked into `.claude/skills` and `.agents/skills` so both assistants find them. The assistant picks one when a request matches it:

| Skill | What it does | Started by |
|---|---|---|
| `threads` | Opens, wraps, parks, finishes, renames and creates threads, and adds zones | "open X", "wrap it", "close for the day", "I'm being interrupted", "park X", "what's open", "new project X for Acme" |
| `intake` | Sorts the inboxes, one item at a time, by the Ways in rules | "process the inbox", "file my mail", "file this" |
| `meetings` | Files a conversation as a Meetings page, and briefs for a meeting | "file this transcript", "log this call", "prep me for X" |
| `knowledge` | Freezes published material into the Knowledge wiki, and answers from it | "read this", "add this to knowledge", "what does my library say about X" |
| `todo` | Sweeps actions the records hold into each zone's `Todo.md`, and tidies it | "sweep my actions", "what do I owe people", "what am I waiting on" |
| `nurture` | Sorts what the checks found by what a fix needs, applies the mechanical fixes on one yes, and proposes which wiki pages fade | "nurture the context", "nurture Work", "review the context with me", "fade the meetings", "what would fade", "keep X" |
| `interview` | Asks about your work one question at a time, then proposes parties, which zones are walled, projects and threads | "interview me", "help me set up my workspace" |
| `setup` | Finds out what your Mac has and how you work, and writes it down | "set up Garrick", "check my setup", "add a rule", "set up notifications" |
| `update` | Brings the workspace up to a newer Garrick, and merges what it leaves | "update Garrick", "merge the update", "split my rules" |

The cmux extra adds a tenth, `desk`, under [Where you work](#where-you-work).

### The tools

**The tools** are Python scripts, standard library only, for what code does better than an assistant. They move, parse, check and list; they never choose where a thing goes.

- `check.py` tests the workspace against every rule a machine can check. Run by hand it reports; run by the pre-commit hook as `--staged --walls-only` it refuses. See [The check](commands.md#the-check).
- `scaffold.py` makes zones, parties, projects and threads, and parks, wakes, renames and deletes them. It checks a name and a party before it writes anything. See [Your first project](commands.md#your-first-project).
- `garrick_lib.py` is what the other tools share: reading frontmatter and `context.md`, the naming and tag rules, and writing the wall hook into a repository.
- `view.py` builds the view model, the one document the Garrick App draws: your pieces of work, what each may do, and the queues that wait. It reads and never writes. `view_settings.py`, loaded through it, does the same for Settings, `view_jobs.py` for the scheduled jobs, and `view_app.py` for the App's own files under `System/` and the check's kept result.
- `usage.py` prints what the Garrick App is used for: card opens, wraps started from the App and Ask actions, from records that already exist. It names each source and what it cannot see. It reads and never writes.
- `operations.py` declares every action the Garrick App can ask for, in one table, `DECLARED`, and keeps a durable record of six of them.
- `install.py`, in the repository and not in the workspace, makes a workspace. `install.py --update` runs `update.py` beside it, which brings a workspace up to that Garrick.
- `release.py` asks GitHub whether a newer Garrick is out and runs the update from it, only when asked or switched on.
- `notifications.py` is the one way Garrick tells you something: every notice goes through it, to this Mac, or to a session's own tab in cmux, as the Garrick App's Settings › Notifications says. It installs the hooks that let a Claude Code or Codex session say it needs you or has finished. It never reaches the network.
- `correct.py` stops a wrong value everywhere: it lists every live copy, in memory, `System/context.md`, hubs, thread notes, `Todo.md` and the wikis, and on a yes fixes them all, one commit per repository, marking a page whose raw record holds the old value as corrected, or as superseded where its own text could not be fixed. See [Correcting a value](commands.md#correcting-a-value).
- `briefing.py` gathers what changed in a zone's threads over a period, and decides nothing; `next_up.py` ranks one thing worth doing next, by six fixed rules, for the threads skill.
- `discover.py` proposes the pieces of work in a folder you keep, from names and dates alone, and `extract.py` takes the text out of their Word, PowerPoint and Excel files; neither writes in that folder. `example.py` puts the worked example away and brings it back.
- `probe.py` lists what the Mac has, for the setup skill; `drift.py` compares a published deliverable with its shared copy; `wiki_lint.py` finds orphan pages and broken links in a wiki; `nurture.py` sorts what those find by what a fix needs, and applies the mechanical ones on a yes; `fade.py` proposes which wiki pages leave working memory, by age, kind and use, and moves them, links and all, on a yes. See [Fading](commands.md#fading).

### The commit check, and the zone guard

**The guards** are the code that stops something rather than reporting it:

- **The pre-commit wall check.** The installer writes a git hook into each zone and into `Wikis/`, and `check.py --install-hooks` into any git repository inside a project too, and into a wiki installed before without one, that runs `check.py --staged --walls-only` on what is being committed. A file that links to, embeds or names the path of a file in another walled zone is refused with one line naming the file and the wall, and so is anything from an inbox. It catches specific signs of a crossing, not every crossing: see [the known gaps](enforced.md#the-wall-checks-known-gaps). `check.py --install-hooks` puts a zone's or a wiki's hook back, and the check warns when git's `core.hooksPath` setting sends commits past it.
- **The zone guard**, optional. A hook for Claude Code and Codex that stops the assistant once before it edits a file outside the project the session was opened in, so that it asks you. It covers the file-editing tools, not shell commands, and records nothing about your answer. See [the zone guard](../extras/hooks/README.md).

[What is enforced, and what is asked](enforced.md) lists every guard beside the rules that depend on the assistant alone.

## The extras

**The extras** are optional, in the repository's `extras/`, and core Garrick never depends on any of them. The installer puts in one, the Garrick App's, because a new workspace opens on it; the rest you add when they solve a problem you have. See [Extras](extras/index.md).

| Extra | Layer |
|---|---|
| [The Garrick App](extras/status-page.md), with its Mac app | Navigate and control |
| [cmux](extras/cmux.md) and its `desk` skill, [the Garrick band](../extras/mods/README.md), [phone access](extras/phone-access.md) | Where you work |
| [Obsidian](extras/obsidian.md), to browse the record as a linked vault; [ways in](extras/ways-in.md) and [a meeting recorder](extras/meeting-recorder.md), to feed it | The record |
| [Scheduled jobs](extras/scheduled-jobs.md), which run the check, a script or an assistant on a schedule under a deny profile and spend caps; [the zone guard](../extras/hooks/README.md) | Underneath |

## The flows

### Material coming in

**Recordings**, **mail** and **files you drop in** arrive by one of the [ways in](extras/ways-in.md): by hand, by a script or by your assistant's mail connector. Each lands in an inbox first: a transcript in `Wikis/Meetings/raw/inbox/`, mail and other files in a zone's `Inbox/`. "Process the inbox" starts the `intake` skill, which looks at each item and **files it where it belongs** by the Ways in rules. A recording is always a conversation, filed in Meetings. A mail exchange is filed in Meetings too, with its zone and parties; something to read goes to Knowledge; material for a project goes into its `Sources/`, after the wall between the project's party and the material's parties is checked. When the zone, a party or the project is unclear, the assistant asks.

### A working day

You press Continue on the Garrick App's home, or open a session in your app or terminal and say "open Acme pricing". The assistant reads the thread's Resume here block and answers in two sentences: where it stands, and the next action. You work, and what the session writes is committed in the zone's repository, where the wall check runs on every commit. If something cuts in, or at the end, "wrap it" (or "I'm being interrupted") asks nothing and rewrites the Resume here block so it describes now, adds a dated entry below it, puts open actions in the zone's `Todo.md` and commits. "Close for the day" does that for every thread touched today. The next session, in either assistant, starts from that block.

### The walls

A zone is walled or open, a flag in the Zones table of `System/context.md`, and every Meetings page carries the zone it is checked against. They are read by the assistant: before it uses a meeting in a project, the rules ask it to compare the meeting's zone with the project's and leave a walled zone's material out of any other zone, saying only that something was held back. They are enforced, in part, by code: the pre-commit hook in each zone refuses a file that links to, embeds or names the path of a file of another walled zone, or copies one whole. A clean paraphrase, a chat reply and anything sent are outside what the hook can see, and the check has known gaps. See [What the check covers](principles.md#what-the-check-covers) and [What is enforced, and what is asked](enforced.md).

### An update

Garrick publishes a release. "Update Garrick", or `python3 System/tools/release.py update`, downloads it into a temporary folder outside the workspace and runs that release's own `install.py --update`, which compares every file it would write with yours and with the fingerprint recorded when Garrick last wrote it. It reports first: a file you never changed is replaced, a new one is added, and a file you changed that Garrick changed too gets Garrick's version beside it as a `.new`. Your rules, your `context.md`, your notes and the local files are never replaced. With `--apply` it writes the files and makes one commit in each repository it touched, which `git revert` undoes. "Merge the update" then goes through each `.new` with you, and the check warns while one waits. See [Updating](updating.md).
