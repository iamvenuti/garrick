# Changelog

What changed in each release. Dates are when the release was tagged. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [semantic versioning](https://semver.org/).

## [Unreleased]

### Added

- Scheduled jobs tell you where you choose: `GARRICK_NOTIFY_CMD` runs a command of yours with a title and a message, beside or instead of the macOS notification of `GARRICK_NOTIFY=1`. See [Being told](docs/extras/scheduled-jobs.md#being-told).
- A failing job notifies on its first failure and on any change of exit code, then at most hourly while the failure lasts (`GARRICK_ALERT_REPEAT`), and always once when it works again. The notice and the log say why in words: could not sign in, a connector missing, a spending cap, timed out, or the exit code and how long it ran.
- `GARRICK_QUIET_EXITS`: exit codes, such as a partial sweep's, that are logged and marked `quiet` in the heartbeat and the log line, never notify, and count as a working run.
- `job.py status` prints every job's state as JSON: whether a run holds its lock now, its last heartbeat, and whether it is failing or idle. The heartbeat adds `started`, `finished_ts`, `ok`, `quiet`, `reason`, `idle`, `agent` and `failing_since`; the lock records when it was taken. See [What the status page reads](docs/extras/scheduled-jobs.md#what-the-status-page-reads).
- `job.py notify <title> <message>` sends a job's own line, such as a digest, through the same notifier.
- `GARRICK_ENV_FILE`: settings read into a run from a file, such as a sign-in token on a Mac nobody logs in to. The log names them and never shows their values.
- `agent.py run --prompt` takes the prompt itself, and `--timeout` stops one call with exit 124 so a job keeps time for its own steps. `agent.py items <n>` and `agent.py items-from <file>` report a count from the shell, the second from an `ITEMS <n>` line in the assistant's answer.
- The assistant-call ledger names the model each call used.
- The cmux extra, `extras/cmux/`: the `desk` skill and command keep one cmux tab per thread, for Claude Code and Codex alike. "Open Pricing" opens the thread's tab, or brings it forward, and its session starts on "open Pricing". "Close Pricing" has that session wrap the thread, then closes the tab. "Close for the day" wraps each tab used today in its own session, runs the commands you list under `before_quit`, then quits cmux; "shut everything down" quits without wrapping; "start the day" brings the tabs back and resumes any that came back empty. Nothing is closed or quit under a session that is mid-turn. Settings in `System/desk.json`, all optional. See [cmux](docs/extras/cmux.md).
- `cmuxlib.sessions_by_folder()` in the cmux extra: which folders have a live session, and whether it is idle or working, read from cmux's records and each session's transcript, for the status page.
- Four status page actions in `extras/status/page_action.py`, available when the cmux extra sits beside it and cmux is installed: `open` and `close` a project's or thread's tab, `startup` and `shutdown`. `close` is refused while a session there is mid-turn; `shutdown` checks first and then goes on in the background.
- An Obsidian plugin for the status page, in `extras/status/obsidian/`. It shows the page in an Obsidian tab with the buttons the Mac app gives it: Copy, *Rebuild now*, Finder, cmux, Codex and Claude, and the preview `page-actions` through `page_action.py`. It finds the workspace at or above the vault, or as named in its settings, and hides parked projects and threads in the file explorer. See [In Obsidian](docs/extras/status-page.md#in-obsidian).
- The preview `ask`: the status app's panel field, and a box ⌘G opens, answer a request in plain words ("open Pricing in Claude", "park the launch video", "what's open") and act on it. `ask.py` keeps a warm assistant session on `GARRICK_HARNESS` and `GARRICK_ASK_TIER`, under the scheduled jobs' deny profile and caps. It sees only names and states, and what it proposes is checked and run through `page_action.py`. Off, the field opens your assistant, as before. See [Ask](docs/extras/status-page.md#ask).
- `page-actions.log` in the jobs folder: one line for every request the page's buttons make, done or refused, naming only the fields its verb reads.
- A `settings` request to `page_action.py`, which saves *Opening a thread* to `System/generated/status-settings.json`, so every viewer of the page can share it.
- Edit › Cut, Paste, Undo and Redo in the status app, so ⌘V works in the Todo list's *Add* field and the panel's field. Safari's Web Inspector can open the app's page.
- The status page's Todo tab (preview `todo-list`) is the full list: one zone at a time, grouped under `Todo.md`'s headings, then *In thread notes* and *Done today*; *All*, *Overdue* and *No date* filters; *A–Z* or *Due date* sorting; counts of the open, overdue and undated. With `page-actions` in the app, a ticked line reopens, the date menu offers Friday, Next Monday and In two weeks as well as any date, and a line being added shows greyed until the rebuild.
- Thread rows say *no resume block* when a live thread's note has no `### Resume here` block, and a thread's card gives the date the block gives itself.
- The page shows a scheduled job as *running now* while its lock is held; raises an idle job (`idle` in its heartbeat, or `GARRICK_IDLE_DAYS`) and a repository with a change left uncommitted for over a day under *Needs attention*; and treats quiet exits (`ok` or `quiet` in the heartbeat, `GARRICK_QUIET_EXITS` in the plist, `quiet` on the log line) as fine, saying a failure's own `reason`.
- *Assistant calls* gains a fourteen-day cost chart, average turns per call, the per-call budget (`GARRICK_MAX_CALL_USD`), and refused tools checked against the deny list in `headless-settings.json`: a forbidden tool, a missing deny list or a call stopped at its budget goes under *Needs attention*.
- The graph takes a zone's or wiki's colours and excluded files from its own Obsidian vault (`.obsidian/graph.json`, `.obsidian/app.json`) when it has them. Every note in a project offers the apps its card does.
- With the cmux extra installed, a dot on rows, cards and menu rows says a session is open (green waiting, blue working). With cmux and `page-actions` too, *Open in cmux* goes through the desk, cards offer *Close session*, and the top row *Start up* and *Shut down*.
- `status.py --settle SECONDS` builds only after a burst of requests has stopped. After *Park*, *Wake*, *Open in cmux* or *Close session*, the page asks for rebuilds until it shows the change.
- `status.py --also FOLDER` and `--moved OLD=NEW`, passed to `effort.py`.
- Launcher settings saved for every viewer, in `System/generated/status-settings.json`: inside the app the page prefers them, and closing Settings after a change sends them to `page_action.py` to save.
- The check reads more of the rules: a missing `AGENTS.md` at the root or in a wiki; a zone's hand-kept list of projects that no longer matches the folder; two parties with one name and no wall between them; no Aliases table; a skill an assistant cannot find from the root, a zone or a wiki, through the repository's link or your own; a skill pinned to a model version, or copied in with no source commit; a hub that does not link a thread, or lists a finished one outside `## Finished`; a hub or thread note renamed `-v2`; a thread naming an unknown party; a meeting page naming both sides of a wall; a page in the Meetings wiki written for one party, a person or an organisation in one of its roles, that cites a meeting across a wall; a link from one zone into another; the full path of a cloud-synced folder in a note; a link to a page name both wikis hold that does not say which.
- Checks on to-do lists: an action whose thread link leads nowhere, a date with text after it, an Inbox that grew by more than twenty in a week.
- A resume point left behind is reported: files added to a project more than two weeks after its resume point was last updated. A hub's own Resume here block is read like a thread's, and a project that is only ever one thread may keep its resume point in its hub.
- Hub keys the check reads: `layout: thread-first`, for a project that keeps everything inside its threads; `anonymous: true`, or a list of names, for a project whose deliverables name nobody, Word, Excel and PowerPoint files included; `share:`, for a project whose files also live on a shared drive.
- `System/garrick-checks.json`, optional, for rules only some workspaces keep: `parent:` links on every note, notes linked rather than named as code, a thread link on every action, word budgets, retired skills, accepted changes to raw records, and which of Garrick's files are never changed here. See [check settings](docs/getting-started.md#check-settings).
- A project about the workspace itself can live in `System/<Project>/`, in no zone, and is checked like any other.
- `check.py --quick`: every check but the comparison of wording with the meetings, the slow part on a large workspace.
- The check warns when one of Garrick's own tools in `System/tools/` was changed here, or the version stamp does not read.
- `job.py check-scripts <file>...` reads job scripts, or the plists that run them, for a line that runs `claude -p` or `codex exec` itself instead of going through `agent.py`, and exits 1 when it finds one.
- A job run with `--agent` that exits 0 having added no line to the ledger says so in its log and with `no_call` in its heartbeat: either it had nothing to ask, or it reaches the assistant around `agent.py`, where no cap or deny profile holds it.
- `zone_guard.py --check` says whether the zone guard is registered for Claude Code and Codex, on every event and editing tool, from a script that exists, and changes nothing. It exits 1 when an assistant found lacks it. See [the zone guard](extras/hooks/README.md#check-it).
- The status page's actions doc lists every verb `page_action.py` takes, and a test fails when the two differ, so a new verb is reviewed before it ships.

### Changed

- A year standing as a word of its own is now part of a speakable name: "Identiverse 2027" is said "twenty twenty-seven", so a recurring event can carry its year. Any other digit is still refused, by the scaffold and by `check.py`, and `System/rules.md` says so.
- The idle notice repeats every `GARRICK_IDLE_DAYS` days while a job stays idle, rather than on every run, and `GARRICK_IDLE_DAYS=0` turns the alarm off. `GARRICK_NOTIFY=1` follows the same throttle: a lasting failure no longer raises a notification on every run.
- A Claude call stopped by its own budget, `GARRICK_MAX_CALL_USD`, exits 8 like a spending cap.
- `agent.py` refuses a Claude call, with exit 64 and nothing called, when its deny profile has lost an entry in `CORE_DENY`: sending, replying to and forwarding mail, binning mail and Drive files, making and deleting calendar events, sharing a Drive file, editing or commenting on a Notion page, and `curl`, `git push` and `rm`. A test holds the shipped profile to the same set.
- The deny profile for unattended Claude calls adds publishing Claude documents, the remaining Notion writes, starting or messaging other agent sessions, and the browser and computer-use servers.
- `System/rules.md` says what "open X", "close X" and "close for the day" do where the desk skill is installed, and the `threads` skill hands those phrases to it.
- Deliverables are checked in each thread's `Deliverables/` and in `archive/` too. Build intermediates (`build/`, `render/`, `specs/`), scripts, a `README.md` and a folder of build output are not deliverables, and an undated folder of dated deliverables is read inside.
- The name check on walled files is faster: plain ASCII text skips the accent folding, and each file's words are read once for every party.
- The status page raises a deny profile that has lost one of its core entries, as agent.py refuses it, and says when a scheduled run called no assistant, without raising it.

### Fixed

- A sign-in check that does not answer within 90 seconds, as when the Mac sleeps in the middle of it, no longer stops an assistant job: only a definite "not signed in" does.
- A job's lock whose process has gone, as after a crash, is taken over at the next run instead of blocking it for up to an hour.
- A second click on a Todo row before the page rebuilt was refused: a date changes a line's key, and the row still carried the old one. `page_action.py` now follows a line it re-dated in the last hour, so a second date, a tick or an undo lands on it.
- *Run now* said a job was running when its last run still held the lock, and the new run only skipped. It now says the job is already running.
- `check.py` no longer reads a git repository of its own inside a project, such as code checked out beside the notes about it, as the zone's files: its templates are not an unfinished install and its wording crosses no wall.
- A placeholder a note quotes as code, inline or in a fenced block, is no longer reported as unfilled.
- A folder named `archive` in a zone, in any case, is no longer taken for a project, so the walls no longer refuse a commit of retired to-do lines for having no party to check their meeting links against (#23).
- An HTML page is compared by the text a reader sees: its styles, scripts, comments, tags and attributes no longer count as wording, so two pages built from one slide template are no longer reported as repeating each other (#24).
- The text of a link to a shared file, such as a Knowledge page's title, no longer counts as wording, so two notes that list the same Knowledge pages are no longer reported across a wall (#25).
- `check.py` no longer reads any `node_modules`, `.venv`, `__pycache__` or `dist` folder, and the walls, sources and placeholder checks skip what the workspace's repositories ignore: an installed package's README no longer names a walled party. The inbox checks still read the inboxes, which are ignored by design (#26).
- A scheduled job stopped mid-run, by `launchctl bootout`, a plist loaded again or a shutdown, now stops its command too, lets go of its locks and leaves a heartbeat saying it was stopped, with exit 143. Before, the command ran on with no watchdog and the next run started beside it. A command left running by a `job.py` killed outright still holds the job's lock and the shared assistant lock, and is stopped by the first fire after its time is up.
- A run caught by a closed lid no longer loses its lock when the Mac wakes past the lock's time: a lock stands while its `job.py` lives, so the overdue fire is skipped instead of running a second copy. A process number reused by another process no longer holds a lock.
- `job.py --timeout 0`, or less, is refused with exit 64 instead of timing out every run; `GARRICK_JOB_TIMEOUT=0` keeps the default, with a line in the log.
- Settings in `GARRICK_ENV_FILE`, such as `GARRICK_JOB_TIMEOUT`, `GARRICK_QUIET_EXITS` and `GARRICK_JOBS_DIR`, now take effect: the file is read before them, not after.
- A job's command killed by a signal exits 128 plus its number, as a shell reports it (137 for SIGKILL), and the reason names the signal. It exited 241 or the like before.
- A job's command that exits 4 or 124 itself reads "exited 4", not "could not sign in" or "timed out": those words now come only from `job.py`'s own sign-in check and watchdog.
- The zone guard follows links: a file reached through a link in the project to a folder in another zone is asked about, as that zone.
- The zone guard ignores case on a disk that does, as a Mac's does: `/users/...` or `zones/work/...` no longer slips past it, and the session's own project in another case is no longer asked about.
- desk checks each tab again the moment it sends a wrap. A tab that started a turn after the shutdown's first check, or stopped on a permission question, gets nothing typed into it, where before the wrap's Enter could answer the question. "Close for the day" wraps the rest, then stops with cmux running and names the tab; `close --wrap` leaves it open.
- "Start the day" types a resume command only into a tab it brought back itself, and only when a shell alone holds the tab. Before, it could type into a tab running an editor or a password prompt, resume with cmux already running, or give one session's folder to another tab of the same name. Its record of the last quit is used once, and ignored when cmux has started a session since.
- `desk close` no longer takes a part of a tab's name shorter than four letters, such as "it", or one two tabs share: it asks which tab.
- Text desk types into a tab is kept to one line, so a newline in a prompt or a folder's name cannot send it early.
- A Claude Code session whose turn ends with only a `stop_hook_summary` record, as a run with no terminal writes, no longer reads as working for ever; a turn a session starts itself, on a task's notice, reads as working until it ends.

## [0.14.0] - 2026-10-10

A mail you forward from your own account is read by the people inside it: Outlook's unmarked forwards are understood, and your own addresses, listed under *Me*, carry mail without deciding whose it is.

### Fixed

- A mail forwarded from Outlook is now read for the people inside it. Outlook opens a quoted message with its `From:`, `Sent:` and `To:` lines alone, with no *Forwarded message* line above them, and a plain-text copy loses even its rule; `intake` saw only whoever forwarded it, so their party was suggested and a wall between the people inside went unasked. Unmarked header blocks are read now, after a blank line or a rule, with bold labels (`**From:**`), `>` quoting, `;` between addresses and Outlook's `<a@x<mailto:a@x>>`.

### Added

- Your own addresses, written under *Me* in `System/context.md` (`My addresses: …`). They carry mail and no longer decide whose it is: a mail you forward from your work account is read by the people in it. Your own address's party, an employer say, is still added when no wall stands between it and them, or when nobody else is on the mail, and never in another zone's inbox. `intake.py parse` shows it under `suggested.own`.

## [0.13.0] - 2026-10-10

The status page's Mac app can keep its menu in a panel that slides out from a screen edge or down from under the notch, and the panel's field asks Garrick as well as finding a thread.

### Added

- *Shows as* in the status page app's Settings › Menu bar (preview `menu-bar`): the menu as a panel that slides out from the left or right edge of the screen, or down from under the notch, instead of an icon in the menu bar. The panel is fused to its edge, as the notch is to the top of the screen, and as tall as what it lists. It opens when the pointer rests on the top third of a side edge or on the notch, or with the hotkey. It holds what the menu holds, with each project's threads open under it. See [As a panel](docs/extras/status-page.md#as-a-panel).
- The panel's field finds a project or thread as you type, and offers what you typed as *Ask Garrick*: a click, or Return when nothing matches, opens your default assistant at the workspace root with your words. The panel answers nothing itself and calls no model.
- *Process the Inbox* names where items wait, such as "Work 4 · Meetings 1", in the panel; the page sends each inbox's count with the total.

### Changed

- Settings › Menu bar describes a menu kept at hand outside the window, an icon or a panel: *Show in the menu bar* is now *Show the menu*, and the hotkey opens either.

## [0.12.1] - 2026-10-09

The status page's Mac app builds again with an Xcode older than macOS 27's, and the zone guard no longer stops a session opened in `System/`.

### Changed

- The zone guard (`extras/hooks/zone_guard.py`) no longer stops a session opened in `System/`. `System/` governs every zone and wiki, so a session there works across them without asking, as one at the workspace root already did. `System/rules.md` says so.

### Fixed

- `make-app.sh` failed with an Xcode older than macOS 27's: 0.12.0 kept the menu's icons visible through an API those SDKs do not have. The app now sets it by name, so it builds with any SDK and the icons still show on macOS 27.

## [0.12.0] - 2026-10-09

The status page's Mac app gains Keep awake, Process the Inbox and app icons in its menu bar, and the Garrick band follows the session and works at every level of the workspace.

### Added

- *Process the Inbox* at the top of the status page's menu bar (preview `menu-bar`): how many items wait in the inboxes, and one click to open your default assistant at the workspace root with "process the inbox".
- *Keep awake* in the status page's menu bar (preview `menu-bar`): for an hour, three hours, until turned off, or while Claude Code or Codex is mid-turn, read from their transcripts by the new `extras/status/agents_working.py`. The display can stay on too. The app holds macOS's power assertions itself, so a quit or crash releases them, and the menu bar mark carries an amber dot while it holds the Mac awake.
- [A desktop toolkit](docs/extras/toolkit.md), a page among the extras: the Mac apps the author runs around a workspace, for opening Markdown files, dictating and watching usage, each as a slot any app can fill. It warns that a dictation app's cloud cleanup sends what you said to that model's provider. Garrick ships none of them.

### Changed

- The Garrick band's second line follows the session: once you send a prompt it shows that prompt's first line, and while the assistant works, the step it is on (`Editing register.tsx`, `Run the tests`). Before the first prompt, and after `/clear`, it shows the Resume here line as before.
- The band gains *Finder* (`f`) and *Obsidian* (`o`), which open the thread note. Obsidian is offered only where it is installed and the note sits in a vault. `/garrick finder` and `/garrick obsidian` do the same.
- The band's *Note* pane turns wikilinks and file paths into links a click opens, and offers *Open in Obsidian* and *Reveal in Finder* for the whole note.
- The band's own *Hide* button is gone: the `[-]` beside the band, which is Claude Code's, folds it. `/garrick hide` takes it away and `/garrick` brings it back.
- In the status page's Mac app, a card's ways to open a project or thread are the apps' icons, as in its menu bar: the note's app, Finder, cmux, Codex and Claude, the default on a tinted square, each named when you hover it. The app hands the page the icons, so a browser keeps the words.

### Fixed

- At a project whose resume points live in its threads, the Garrick band offered only *Clear*, because the hub has no Resume here block. It now names the live threads, *Resume* asks where each stands, *Note* shows each thread's block, and *Wrap* wraps the thread the session worked on.
- `/garrick resume` and `/garrick wrap` submitted their prompt from inside the command, which Claude Code refuses because the command holds the turn. They now submit it just after the command answers.
- Outside a thread (in `System/`, at the workspace root or in a wiki), the Garrick band offered only *Clear*. It now offers *Finder* on the folder too, and in a wiki *Obsidian* on its index.
- The Garrick band could lose its thread and show only *Clear*. It looked for the thread note from the shell's current folder, which moves whenever the assistant runs `cd` in a command, so after such a turn it found no note. It now looks from the folder the session started in.
- `/garrick` could leave the band hidden. It toggled the mod's own flag, which knew nothing of Claude Code's `[-]` fold, so after a fold it hid the band instead of showing it. Typed during a turn, it also waited for the turn to end. `/garrick` now always shows the band, `/garrick hide` hides it, and both answer at once.
- The graph's panel offered no *Open in Claude*, *Open in Codex*, *Open in cmux* or *Reveal in Finder* on any note, and no *Park* that acts; a thread's or a project's note there now offers what its card in the list does.

## [0.11.2] - 2026-10-09

The Garrick band resumes the thread, and wraps and clears it.

### Changed

- The Garrick band's *Resume here* button resumes the thread instead of only showing its block: it asks the assistant to read the Resume here block and say where the thread stands and what comes next. The band also gains *Wrap*, which rewrites the block and adds the day's entry, and *Clear*, which runs `/clear`. *Note* still shows the whole block in a pane without calling the model. Each button has a letter, and `/garrick resume`, `/garrick wrap` and `/garrick note` do the same from the prompt.

## [0.11.1] - 2026-10-09

The zone guard: the assistant checks with you before it edits outside the project you opened it in.

### Added

- The zone guard, a hook for Claude Code and Codex in `extras/hooks/zone_guard.py`. Before the assistant edits a file in another project, another zone, a wiki or `System/`, it stops once and names both places. Claude Code asks you in its permission prompt and remembers a place you allow for the rest of the session. Codex hooks can't ask, so the first edit there is refused with the same sentence and a second one goes through. Edits inside the session's project, in its zone's loose files such as `Todo.md`, or outside the workspace go ahead, and so does any session opened at the workspace root. Optional: [its README](extras/hooks/README.md) says how to load it, and the setup skill offers it.

### Changed

- `System/rules.md` adds writing outside the session's project to the things to stop and ask about first. It holds with or without the guard, and covers what the guard can't see, such as a shell command that writes a file.

## [0.11.0] - 2026-10-09

The Garrick band: a Claude Code mod that shows the thread you are in above the prompt.

### Added

- The Garrick band, a Claude Code mod in `extras/mods/garrick-band/` ([#20](https://github.com/iamvenuti/garrick/issues/20)). Above the prompt it draws the mark, the zone, project and thread you are in with its status, and the first line of its Resume here block, with a button for the whole block; `/garrick` hides it. In replies it turns file paths in backticks into links you can Cmd-click. It reads files only and never calls a model. Optional and Claude Code only: [its README](extras/mods/README.md) says how to load it, the setup skill offers it, and CI validates and tests it on Claude Code 2.1.295.

### Changed

- The README plays the walkthrough with the new mark.

## [0.10.0] - 2026-10-09

A new mark, and the Mac app takes Garrick's name.

### Changed

- A new mark: a cabinet of three compartments, a narrow spine on the left, the open one in blue and a closed one beneath it, for work kept in its own place and one thing open at a time. It replaces the *Gr* tile in `docs/assets/garrick-mark.svg`, with a version for dark grounds, a one-colour version, a small cut on the 16 px grid for favicons (`garrick-mark-favicon.svg`, which follows the browser's dark mode), a lockup with the wordmark in Baskervville and a macOS app icon. The blue stays `#3D73E0` on light grounds and takes the deck's lighter `#8EB1F5` on navy. [The mark's note](docs/assets/brand.md) lists the files and colours. The README, the deck, the social card, the adoption ladder, the walkthrough video and the status page all carry it: the page's heading mark follows its light or dark theme, and its tab icon follows the browser's.
- Garrick's Status.app is now **Garrick.app**, and the page it shows is headed *Garrick*. The app's icon is the mark on a navy tile. In the menu bar the mark is drawn in the menu bar's own colours, light or dark, with the open compartment in blue. `make-app.sh` builds `Garrick.app` from `Garrick.swift` and replaces a build of *Garrick's Status.app*; the app keeps its bundle identifier, so its settings, window place, menu and hotkey carry over. If it opened at login, switch *Open at login* off and on again in Settings › Menu bar. Rebuild the app with `make-app.sh` to get it.
- The walkthrough video carries the new mark and says "status page" where it named Garrick's Status; the architecture overview and the docs call it the status page too.

## [0.9.0] - 2026-10-08

Garrick's Status in the menu bar, as a preview: your projects and threads one click from any app.

### Added

- Garrick's Status in the menu bar, behind the `menu-bar` preview flag, in Garrick's Status.app. An icon lists the live projects of the zone the graph shows; pointing at one opens a line of app icons, the ways its card offers to open it, then its threads, each with its own icons. Clicking a project's or a thread's name opens it with the default from Settings, the same as clicking a thread's name in the window. The icon carries the *Status* tab's red dot. Settings › Menu bar switches the icon on, opens the app at login and records a hotkey that opens the menu from any app. With the icon on, closing the window leaves the app in the menu bar. Rebuild the app with `make-app.sh` to get it.

## [0.8.1] - 2026-10-08

Add an action from the status page's Todo list.

### Added

- *＋ Add* on the status page's Todo list, behind the `page-actions` preview flag, in Garrick's Status.app: a new line in a zone's `Todo.md`, with an optional project or thread picked from a tree of the zone and an optional date. Undated lines go to the Inbox; dated ones where a dated line belongs. `page_action.py` gains `todo-add`, and `todo_lines.py` gains `add()`.

## [0.8.0] - 2026-10-08

A cleaner status page: Overview shows the work and nothing else, one row at the top replaces the sidebar, threads fold under their projects, and a preview shows where the assistant's time and money go.

### Added

- *Time* and *Cost* on the status page's Threads card, behind the `effort` preview flag: the same rows show the assistant's active time or list-price cost over the last 30 days, largest first, read from Claude Code's own transcripts with no model call. A line under the columns accounts for what no row shows, so the figures add up. `effort.py --record`, run nightly, keeps each day's totals once the transcripts are cleaned up. Claude Code only for now. ([#17](https://github.com/iamvenuti/garrick/issues/17))

### Changed

- The status page's Threads card has a row per project, with a chevron that unfolds its threads; a project with no thread notes is a row of its own. The fold is remembered. ([#14](https://github.com/iamvenuti/garrick/issues/14))
- The status page's *Overview* is the work alone. The figures at the top (things needing attention, live threads, open actions, files waiting, the check or the assistant's calls) now lead the *Status* tab.
- The status page has no sidebar. One row pinned at the top holds the name, when the page was built, the tabs, rebuild, Settings and the theme, now three icons. A hidden card is listed in Settings › View until it is shown again.

## [0.7.2] - 2026-10-06

Three fixes found on the first update of an adopted workspace.

### Fixed

- An update no longer forgets that a workspace was adopted. A workspace laid out by hand in Garrick's shape and stamped `"from": "adopted"` kept that only until its first update, which replaced it with how the newer Garrick was fetched; the status page then stopped showing the release notes still to come on `main`. The stamp now keeps `adopted`, and each entry in its `updates` says how that Garrick came, as `via`. `check.py --version` names it. ([#10](https://github.com/iamvenuti/garrick/issues/10))
- `check.py` accepts `status: parked` on a project hub. A project with no thread notes is parked as a thread of its own, by saying "park X" or with the status page's *Park* button, and the check then reported an error. ([#11](https://github.com/iamvenuti/garrick/issues/11))
- When the Garrick an update runs from sits inside the workspace it would update, the refusal now says to move the newer Garrick out, unzipped or exported from a clone, instead of asking you to name the workspace you had already named. [Updating Garrick](docs/updating.md) and the `update` skill say the same. ([#12](https://github.com/iamvenuti/garrick/issues/12))

## [0.7.1] - 2026-10-06

The README plays its walkthrough once.

### Fixed

- The README showed the walkthrough twice: GitHub turns every link to an attached video into a player, and the GIF above the walkthrough linked to it. The GIF is gone, and the walkthrough plays once. Nothing in an installed workspace changes.

## [0.7.0] - 2026-10-06

Updates: a newer Garrick now reaches a workspace you have already installed, without losing what you changed. And a first-run setup that looks at your Mac before it asks you anything.

### Added

- `install.py --update ~/Garrick` brings an installed workspace up to the Garrick you run it from, without losing what you changed. It reports first and changes nothing until `--apply`. A file still exactly as some Garrick wrote it is replaced. A file you changed that Garrick has changed too gets Garrick's version beside it as `.new`, committed so a clean or a clone keeps it until you merge. Starting files you have filled in, such as a `Todo.md`, are left alone. `System/rules.md` is always merged, never replaced. Nothing is deleted, each repository gets one commit you can revert, and the version stamp changes last. [Updating Garrick](docs/updating.md) has the details.
- The `update` skill: say "update Garrick" and your assistant runs the update, then merges each `.new` file with you, keeping your changes and Garrick's together and asking about any passage you both changed.
- `check.py` warns while an update's `.new` file waits to be merged, and `check.py --version` says when the workspace was last updated, and from which Garrick.
- The `setup` skill and `System/tools/probe.py`: say "set up Garrick" in a new workspace and your assistant looks at what your Mac has (the assistant apps and commands, cmux, Obsidian, git's settings), asks only what it cannot find, and writes how you work to `System/setup.md`, so every later session knows which tools to suggest and which to leave alone. It offers to fix what is missing, then hands over to the interview. The probe is read-only and sends nothing. The installer's last line now says to start with it.
- The setup skill's *Fill in my resume points* walks you through each thread whose Resume here is still the template's, one question at a time, so the status page and every cold resume start from real answers. `check.py` warns about such threads until they are filled in.
- `release-hashes.json` records every file each release shipped, so an update recognises a file left by any earlier Garrick, even in a workspace installed before 0.4.0 or one where a fix was copied in by hand.

## [0.6.1] - 2026-10-05

A security fix in the intake and meetings skills, and a clearer count of changed files on the status page.

### Changed

- The status page's Repositories card counts changed files and says so: "12 changed files", not "12 uncommitted", which read as twelve commits. Its tooltip and a list under the tiles split them into staged, not staged, untracked and conflicted, and list the paths, with a button that copies the repository's folder. The card stays read-only: nothing on it commits. Untracked files in a new folder are counted one by one.
- `intake.py` lost `zone_of`, which nothing called.

### Fixed

- `todo_lines.py` closes the files it reads, so the tests no longer print `ResourceWarning`.
- The status page's Repositories card says a repository "could not be read" when `git status` fails or runs past 30 seconds, instead of showing it as all committed.

### Security

- The filing commands of the intake and meetings skills, and the meetings skill's person, index and log writes, check where a file will really land and refuse rather than file somewhere else. A symbolic link is followed only while it stays inside the folder that was checked, the project or the wiki; one that leads out of it, into another project or off the workspace, is refused. The file is then written relative to that folder, opened without following any link, so a link put on the way after the check makes the command refuse instead of writing through it. A mail refused partway through filing stays in its inbox, with no draft page left behind. Every such command has boundary tests. Details are in the security advisory published with this release.
- **Breaking for linked folders:** a workspace whose `Wikis/`, a wiki or a zone is a link to another disk or a synced folder outside the workspace can no longer file into it. Keep the workspace itself on that disk instead.

## [0.6.0] - 2026-10-05

The status page is reorganised around how it is used: *Overview* for your work, *Status* for the machinery, the graph one place at a time, and Settings for how a thread opens. Todo lines move to the Obsidian Tasks format, and two preview features, the Todo list and buttons that act, can be switched on.

### Added

- Preview feature `page-actions`: in Garrick's Status.app, tick and date a line of the Todo list, and park or wake a thread from its card. Each button changes one line or one `status:` field and commits it, as the skills do, and a commit the wall check refuses leaves the file as it was. `extras/status/page_action.py` does the work; a browser cannot reach it.
- With `page-actions` on, a scheduled job of the jobs extra gets *Run now*, which starts it through launchd so it keeps its own wrapper, lock and log.

### Changed

- The page has tabs. *Overview* is where your work stands: the tiles, the graph, the threads, open actions and inboxes. *Status* is the machinery behind it: scheduled jobs, assistant calls, the check, repositories and wikis, with a red dot on the tab when something there failed, and *Needs attention* at its top. The sidebar lists them in that order. Every tile on *Overview*, and the summary at the top of the sidebar, opens the card that explains it, in whichever tab it sits. A card's header has a button that moves it to the other tab, and *Reset view* puts every card back.
- *Settings* lists the ways to open a thread: the note's own link (*Open in Obsidian*, or *Open the note* without Obsidian), *Reveal in Finder*, cmux, Codex and Claude. Each has a checkbox, whether the cards offer it, and a radio button, what clicking a thread's name does; the note's link is the default. Settings closes with the × at its top right, and every change is kept as it is made.
- *Park* and *Wake* sit at the top right of a thread's card and the graph's panel, beside the name, rather than among the ways to open it. *Pause rotation* and *Fit* sit in the graph's bottom right corner. Closing Settings after a change rebuilds the page in the Mac app. The sidebar's *Problems only* became *Only what needs attention*, at the top of the *Status* tab, and acts on that tab alone.
- The graph shows one place at a time, Work first: a drop-down in its bar picks a zone, a wiki, or *All*, and the page remembers the pick. The graph's and the threads' counts sit under their legends rather than in the card headers, and the legends are shorter.
- The Todo list (preview `todo-list`) is a tab of its own beside the overview, as it is in the workspace it came from, with a red dot when something is overdue. A link in the sidebar opens the tab its section is in.
- The sidebar's top row holds Garrick's mark, the page's name and two icons: a circular arrow that rebuilds the page in the Mac app, or copies the command that does in a browser, and the cog for Settings. The build time sits below them across the sidebar. *Reset view* moved into Settings, and it no longer forgets which apps you chose to open projects in.
- The status page reads a project with no thread note as its own single thread, from its hub, so a workspace laid out before Garrick gave every project a `Threads/` folder shows every project. `dormant`, `paused` and `on-hold` read as parked, and `closed`, `archived` and `complete` as done.
- A zone's `Todo.md` uses Obsidian Tasks lines: each opens with its thread, `[[Thread]]: `, or its single-thread project, or else its party or person, and the dates go last as Tasks fields (`📅` due, `🛫` not before, `#waiting` and `⏳` the day to chase). Obsidian's Tasks plugin can then sort and filter them, and the status page's Todo list shows their dates. The meetings, threads and interview skills write it; the template's header explains it. A list in the older `· project, thread · date` form still counts on the page, without dates.

## [0.5.0] - 2026-10-05

The status page opens a project in Claude, Codex or cmux, shows the release notes of the Garrick you installed, and has preview features you can switch on.

### Added

- The status page opens a project or thread in Claude, Codex or cmux. Each build checks which of the three this Mac has. In *Settings*, under *Open projects in*, you switch each installed one on or off, and every app left on gets a button on the cards, in Garrick's Status.app only. Claude starts a session with "open Pricing" typed in for you to send. Codex and cmux open the folder with the phrase on the clipboard. Your choices are kept in the app's own storage.
- *Settings* shows the installed release's notes from `System/garrick-changelog.md`, which the installer now copies from `CHANGELOG.md`, so nothing is fetched. A workspace that follows `main` also sees what is coming next. An *Announcements* link leads to the release news on GitHub.
- Preview features: in Garrick's source but not yet released, off until switched on in `System/garrick-flags.json`, and listed in *Settings*. The first is `todo-list`, a card with every open action in the zones, overdue first, read from the notes and never written.

### Changed

- *Settings* opens from a cog beside the page's name, not from a sidebar button.
- Garrick's Status.app needs `make-app.sh` run again to open Claude and Codex. Until then it opens cmux as before, and its Claude and Codex buttons do nothing.

## [0.4.0] - 2026-10-04

Every install now records what Garrick wrote, so a later update can tell the user's edits from Garrick's own files; and the status page gains Settings, with About Garrick and the ways to report a problem.

### Added

- The version stamp, `System/garrick-version.json`, now lists every file Garrick wrote into the workspace, by path and SHA-256: the installer's files, and those of a zone `scaffold.py zone` adds later. A future update can then replace a file that is still as Garrick wrote it and leave one the user has changed for a merge. `System/context.md`, which holds the user's own answers, is never listed. A workspace installed before this has no list, so an update will treat all its files as the user's.
- `check.py --version` adds how many of those files have changed since, or are gone: counts only, since a path names a zone and a zone's name can be a client's. Still one line.
- The status page has *Settings*, and the Mac app has *Settings…* (⌘,). Under *About Garrick* it shows the installed version, as `check.py --version` says it. It also links to GitHub to report a bug (the form arrives with the version filled in), report a wrong refusal, suggest a change, ask a question, or see what's new. Without a GitHub account, you can copy a report to send instead. The links open in the browser. The page still loads nothing and sends nothing, and it never checks for updates. In the Mac app, the menu item arrives once `make-app.sh` is run again; the page's own Settings button works without that.

## [0.3.1] - 2026-10-04

New wording: Garrick as an AI chief of staff that remembers your work and knows whose confidences you hold, running on the agent you already use.

### Changed

- The README opens with "Garrick remembers your work and knows whose confidences you hold", then "An AI chief of staff for your knowledge work, running on the agent you already use. Everything stays in files you own." Claude Code or Codex is described as the agent underneath. The GitHub description, the social card and the deck's cover and claim slide say the same.
- The launch walkthrough is re-cut with that wording at the opening, in the first app scene and at the close. The rest of the walkthrough is unchanged; captions in `docs/assets/garrick-launch-video.srt`.

## [0.3.0] - 2026-10-04

The status page in a Mac app of its own, and a page that offers Obsidian and cmux only where the machine has them.

### Added

- *Garrick's Status.app*, in `extras/status/app/`: the status page in a window of its own, for the Dock and the app launcher, built on the user's Mac by `make-app.sh` from one Swift file. It rebuilds the page when it is more than 30 minutes old, reloads it when it is rewritten, turns the sidebar's button into *Rebuild now*, and sends links to the app macOS uses for them. `--check` tests it without a window.
- On the status page, inside the app and where cmux is installed, project and thread cards offer *Open in cmux*: a cmux tab in that folder, with "open [thread]" on the clipboard. It opens the folder as Finder would, with no access to cmux's controls. `--no-cmux` leaves it out.

### Changed

- The status page asks this machine what it has at every build. Links open a note in the Obsidian vault closest to it, read from Obsidian's own list of vaults, whether that is the workspace root or a zone or wiki opened on its own, and as a file otherwise; `--obsidian VAULT` still names the root vault, and `--no-obsidian` keeps file links. A workspace with no `Todo.md` gets no Open actions card, tile or sidebar line, and the tiles fill their row whatever their number.

## [0.2.0] - 2026-10-04

The release for the first invited users: guided onboarding for the desktop apps, parking, the status page, scheduled jobs, the interview skill, a stricter wall check, and a version stamp in every workspace.

### Added

- Garrick's mark: a white Gr on blue, set like an element tile, with a small "ai" in the full version (`docs/assets/garrick-mark.svg`, and `garrick-mark-favicon.svg` for small sizes). The letters are outlines of ANRT's Baskervville, under the SIL Open Font Licence. It sits beside the README's title, on the deck's cover and the social card, and in the status page's tab and heading; the deck, the social card and the adoption ladder take its blue as their accent. Display type is Baskerville, the face the mark is drawn in, across the deck, the social card, the adoption ladder and the status page.
- The README opens with the wall at work, as a GIF, and the launch walkthrough, remade in Garrick's brand and playing in the page; then an adoption ladder of four levels, each linking to its guides, whose third level now includes the status page.
- The `interview` skill: "interview me" opens with questions one at a time, including whose confidences you hold and which must never meet, keeps a record in `System/interviews/`, then proposes parties, walls, projects, threads and open actions and sets up only what you accept. Offered as an optional first step of the first session.
- `extras/jobs/`, optional and outside core: an assistant on a schedule. One runner for Claude or Codex, picked by `GARRICK_HARNESS`, with tiers instead of model names; a wrapper with log, heartbeat, lock, watchdog, sign-in check and idle alarm; a ledger of every call with daily, hourly and cost caps; for Claude, a permission mode that lets a job use only the tools it names, and a deny profile, loaded with user and project settings only, that refuses the sending, sharing, deleting and web tools it names and any edit to `System/`, without which no call is made; and an example job, a "what's open" brief per zone, with a launchd plist.
- `extras/status/`, optional and outside core: a status page, *Garrick's Status*. One self-contained HTML file with every live thread by zone and how long since it moved, what the check finds, open actions, what is waiting in the inboxes, the newest entry in each wiki's log, and, with the jobs extra, a fourteen-day strip per job and the spend against its caps. It shows names, tags, dates, counts, check findings and the targets of links, not what a note says; written to `System/generated/status.html`; links open the files, or Obsidian with `--obsidian VAULT`; nothing from the network. With a launchd plist for a nightly rebuild.
- The status page draws a graph of the workspace: every note in the zones and the wikis and the links between them, each zone and wiki starting in its own region, `AGENTS.md` and `Todo.md` left out. It rings threads that have gone quiet and opens a panel on click with the note's links, buttons to open it or its project, and the phrases to say. Parked projects stay off it until *Show parked*. It reads the targets of a note's links and nothing else from its body; `--no-graph` leaves it out. Every card can be dragged to another place or hidden, *Needs attention* excepted, and *Reset view* puts the page back as built. The arrangement is kept in the browser. The graph fills its card, keeps names clear of each other, stays quick on a large workspace and draws mail in its own colour.
- On the status page, hovering a thread in the list, or reaching it with the keyboard, opens a card with the same actions as the graph's panel. The list is sorted by name, and each zone's open actions have a link to its `Todo.md`.
- Parking a thread: "park X" sets it aside with `status: parked`, out of "what's open", the end-of-day wrap, the scheduled brief and the Resume-links check, with its note untouched; "wake X" brings it back and "what's parked" lists them. The status page folds parked threads into their own group, and its buttons copy the phrase to say ("open Pricing", "park Pricing", "wake Pricing") or the rebuild command.
- Notes of a call pasted into the conversation are filed like a dropped transcript: saved unedited to the Meetings inbox, then ingested. Asked to, prep saves its brief as a dated deliverable, after the same wall check, and commits it through the hook.
- `scaffold.py zone "<Zone>" --holds "<what it holds>"` adds a zone after install, made as the installer makes one; "add a zone called X" runs it.
- The wall check holds more: wording from a meeting page still missing its parties, and from a walled project's own files; person pages, which carry a known party and nothing said in a meeting; Knowledge pages, where `party` is refused like `parties` and wording shared with a meeting is flagged; the Meetings inbox, now ignored and checked like a zone's; thread and project statuses and dates. It warns when `core.hooksPath` sends commits past the hook.
- The demo is a fuller month: 21 filed meetings, 15 people, 9 published sources, working notes, deliverables and received files, so the status page's graph has 94 notes and 217 links.
- `System/generated/`, for pages a tool rebuilds. The installer's root `.gitignore` names it, and `check.py` reports a generated file that is committed or a `.gitignore` without the line.
- `check.py` warns when a link or a file path in a live thread's Resume here block leads nowhere, so a deliverable renamed or moved shows up in the next check, not in the next cold resume.
- Questions and feedback go to the repository's Discussions, linked from the issue chooser, the README and `CONTRIBUTING.md`. A bug report takes a desktop app's version as well as the command-line ones.
- A sixteenth slide in the introduction, for the status page.
- Every workspace records which Garrick it was installed from, in `System/garrick-version.json`: the commit and its date, and whether it came as a download or a clone. `python3 System/tools/check.py --version` says it in one line, and the bug form asks for that line. A download from GitHub carries its commit in `VERSION`, which git fills in.
- A table of what has been tested in Claude Code and in Codex, each with the version it was checked on, in the harnesses guide.

### Changed

- The wall check counts wording as common only when it also appears in a file every side reads by design: the instruction files, `System/rules.md`, `System/context.md`, the skills, templates and tools, and the Knowledge wiki. An interview record, a generated page or anything else in `System/` no longer exempts what it repeats.
- The installer refuses a target that is, holds or sits inside the folder it runs from, comparing folders rather than names: on a Mac, `~/garrick` and `~/Garrick` are one folder. A folder typed at the question goes in the home folder, the confirmation shows the full path, git is checked before the first question, the end of input stops it cleanly, and its last line suits either route.
- The docs clone into `~/garrick-source`, and every example workspace has a folder of its own.
- The workspace's `AGENTS.md` tells the assistant to search `Zones/` and `Wikis/` by path: the root's `.gitignore` leaves them out, so search tools started at the root skip them.
- The threads skill's listing works the same in zsh and bash, and prints nothing on a workspace with no threads yet.
- Open actions have one line format, `<action> · <project>, <thread> · <date>`. "What do I owe them" reads the zone's `Todo.md`, and prep reads it too, within the walls.
- Spoken phrases: "wrap it" wraps; "unpark X" wakes a thread as "wake X" does; "pick X up again" is gone, too close to "pick up X".
- First steps for a newcomer: the Command Line Tools dialog, the Downloads permission, and which commands the first session asks to approve and how to allow them once.
- The cmux guide gives each assistant's own resume command, and a section on switching between Claude and Codex: both read the same notes and skills, while each keeps its own conversation history.
- The zone template lives in `template/System/templates/zone/`, so an installed workspace can make new zones. The installer offers only tags it accepts, treats aliases as something to add later, and uses invented tags in its wall example.
- Scheduled jobs take their lock before touching a log, skip cleanly when another run holds the shared lock, accept one plain word as a job's name, rotate the Codex transcript, keep sixty days of ledger, and leave launchd a log of its own.
- The diagram shows the desktop app as the main way to talk to the assistant, and says what the walls are: declared, with limited checks before a commit.
- Separate desktop and terminal onboarding routes, with a shared first session that files one conversation, produces a brief and verifies resuming from a fresh chat.
- Guided setup brings real use and a fictional wall demonstration into the first session. Obsidian, cmux, mail fetching and phone access are optional follow-ons.
- Clarify declared pairwise walls, supported checks and their limits. Lead with continuity of work and local ownership instead of an absolute confidentiality claim.
- Document Codex remote voice on iPhone with its desktop host requirement, and Claude Code Remote Control from a terminal.
- The Obsidian guide shows how to make the graph readable: colour notes by level, leave parked and finished threads out, and link notes rather than quoting their paths, since Obsidian draws no line from a path in backticks.
- The installer's `.gitignore` files leave out Obsidian's `workspace.json` and `graph.json` in any folder opened as a vault, since Obsidian rewrites both on every pan and zoom. Obsidian's settings are still tracked.
- A scheduled job that only reads runs read-only under Codex too: no file written, the user's own Codex configuration ignored, and connectors, plugins, the browser and web search switched off. Checked against Codex 0.160.0. A job allowed to write keeps the write sandbox and its connectors.
- First steps name the git commands a session asks to approve by what they do (`status`, `diff`, `log`, `add`, `commit`), say to read the whole line, and keep Claude's "don't ask again" off a rule that stops at the folder.
- The walls' stated limits add wording moved rather than copied: cut from one party's note, pasted into another's and committed together, it passes, since only the history says where it came from.

### Fixed

- The status page: its right column no longer renders right-aligned; the Wikis card reads the logs as they are written; the Wikis repository appears under Repositories; a note's title can no longer break the page's embedded data; the rebuild command it copies runs from anywhere; a mistyped `--workspace` stops instead of creating folders; and it reads frontmatter as `check.py` does. It also builds without git, opens a symlinked note in Obsidian, reads schedules from any plist, monthly ones included, gives one attention line per capped job, and says a project name shared by two zones with its zone.
- The deck no longer says deleting the folder leaves nothing behind: the assistant's own chat history stays.
- The demo builder takes a relative target as relative to where you run it.
- The commit check reads what it is not committing as git holds it as well as from disk: a source edited or deleted without staging, in the same zone or in another repository, still counts, and a shared file counts as common only for the wording both versions hold. A project or thread whose party differs between disk and the staged copy is refused.
- The commit check refuses files at any depth in a zone's `Inbox/` or the Meetings inbox, not only those directly inside.
- The "what's open" job reads a thread's status with the workspace's own parser, so `status: parked # until next quarter` and `status: "done"` keep a thread out of the brief.

## [0.1.0] - 2026-09-30

First public release.

### Added

- `install.py`: asks one question at a time, or reads a config file; writes nothing outside its target; links the skills for Claude Code and Codex.
- The workspace template: root rules and context, zones as separate git repositories, projects and threads with one "Resume here" point each, and two memories, Meetings and Knowledge.
- `scaffold.py` for new projects and threads, and `check.py`, which checks the workspace against its own rules.
- The wall check: a pre-commit hook in every zone that refuses a walled party's names, links, or eight-word runs of its meeting wording.
- Four skills: `threads`, `intake`, `meetings` and `knowledge`.
- Ways in: every zone has an `Inbox/` folder for mail and any other file. The `intake` skill sorts it by rules in `System/rules.md`: a conversation into Meetings, something to read into Knowledge, material for a project into its `Sources/`, with the mail it came in kept in Meetings. Its helper only lists, parses and moves; parties are suggested from a new Domains column in `System/context.md`, and asked about whenever the addresses do not settle them. `check.py` holds the walls on mail pages and on attachments saved to a project, keeps parties off Knowledge pages, and keeps inboxes out of history. Fetching is separate and optional: your assistant's mail connector, a mail rule, or the IMAP script in `extras/fetch/`, which takes its password from the macOS Keychain.
- `extras/fetch/imap_fetch.py`, optional and outside core: saves one IMAP mailbox or label into one zone's `Inbox/` with no assistant involved, so the assistant's vendor sees only the mail you file. The password comes from the macOS Keychain only. Works with password sign-in (Gmail app passwords, iCloud Mail, Fastmail), not with Microsoft 365 or Outlook.com, which accept only OAuth.
- A demo workspace built by `examples/demo/build.py`: an invented advisor, four weeks in.
- Documentation, the extras (tools that pair with Garrick but are not part of it), and a fifteen-slide introduction.

[Unreleased]: https://github.com/iamvenuti/garrick/compare/v0.14.0...HEAD
[0.14.0]: https://github.com/iamvenuti/garrick/compare/v0.13.0...v0.14.0
[0.13.0]: https://github.com/iamvenuti/garrick/compare/v0.12.1...v0.13.0
[0.12.1]: https://github.com/iamvenuti/garrick/compare/v0.12.0...v0.12.1
[0.12.0]: https://github.com/iamvenuti/garrick/compare/v0.11.2...v0.12.0
[0.11.2]: https://github.com/iamvenuti/garrick/compare/v0.11.1...v0.11.2
[0.11.1]: https://github.com/iamvenuti/garrick/compare/v0.11.0...v0.11.1
[0.11.0]: https://github.com/iamvenuti/garrick/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/iamvenuti/garrick/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/iamvenuti/garrick/compare/v0.8.1...v0.9.0
[0.8.1]: https://github.com/iamvenuti/garrick/compare/v0.8.0...v0.8.1
[0.8.0]: https://github.com/iamvenuti/garrick/compare/v0.7.2...v0.8.0
[0.7.2]: https://github.com/iamvenuti/garrick/compare/v0.7.1...v0.7.2
[0.7.1]: https://github.com/iamvenuti/garrick/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/iamvenuti/garrick/compare/v0.6.1...v0.7.0
[0.6.1]: https://github.com/iamvenuti/garrick/compare/v0.6.0...v0.6.1
[0.6.0]: https://github.com/iamvenuti/garrick/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/iamvenuti/garrick/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/iamvenuti/garrick/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/iamvenuti/garrick/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/iamvenuti/garrick/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/iamvenuti/garrick/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/iamvenuti/garrick/releases/tag/v0.1.0
