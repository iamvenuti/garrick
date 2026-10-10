# Extra: a status page

One page that answers two questions before you open anything: is anything wrong, and where was I? It is a single HTML file you open in a browser, or in a small [Mac app](#a-mac-app) of its own. It needs no server, no account and no network, and it works whether or not you use Obsidian or cmux: each time it is built, it checks which of them this machine has and offers only what will work.

## What it shows

- **A graph of the workspace**: every note in your zones and wikis, and the links between them, laid out to fill its card. *Projects and threads* and *Everything* switch how much it shows. Click a note for its links and the same actions a thread's card offers; double-click opens it. [Reading the graph](#reading-the-graph) says what it draws and what it leaves out.
- **Threads**, one column per zone: a row per project, by name, with a chevron that unfolds its threads, each with its party and how long since its note was updated. The project's row shows its most recent thread, and a project with no thread notes is a row of its own. The bar fills toward sixty days and turns amber after 14 days, red after 45. Threads you have parked ("park X") sit in a folded *Parked* group at the foot of their zone, grouped the same way, out of the counts. A live thread whose note has no `### Resume here` block, the block the threads skill resumes from, says *no resume block*, and its project's row counts them; its card gives the date the block gives itself, from its *Where it stands* line. With the [cmux extra](cmux.md) installed, a dot after a name says a session is open there: green while it waits, blue while it works. A project counts its threads' sessions. Hover a project or a thread for its card. With `effort` switched on, *Updated*, *Time* and *Cost* above the columns switch what the bars and figures show (see [Preview features](#preview-features)).
- **Checks**: what `System/tools/check.py --quick` finds, run as the page is built, grouped by check. The quick run leaves out the comparison of wording with the meetings, the slow part on a large workspace; the commit hook still makes it, and a full `check.py` on a schedule covers the rest.
- **Open actions**: the unticked items in each zone's `Todo.md`, counted by section, with an *Open* link to the list. A zone without a `Todo.md` is left out, and with none at all so is the card; the check reports the missing file.
- **Inboxes**: what is waiting to be filed in each zone's `Inbox/` and in the Meetings inbox.
- **Scheduled jobs and assistant calls**, when you use the [scheduled jobs](scheduled-jobs.md) extra: a fourteen-day strip per job, one cell per day, and the spend against its caps. The caps are the ones the jobs run under: the `GARRICK_CAP_*` values in the launchd plists of the jobs that call the assistant, with the default for any a plist leaves out and the lowest where jobs differ. With no such plist, the page shows the caps it was built with, and the card says which it used. A cap set to 0 shows as *no cap*. A job the cap stopped gets one line in *Needs attention*, however many calls it lost, and so does a call stopped at its per-call budget (`GARRICK_MAX_CALL_USD`, shown under the meters). A job whose lock is held says *running now*, and offers no *Run now*. An exit job.py calls quiet (its heartbeat's `ok` or `quiet`, or a code the plist lists in `GARRICK_QUIET_EXITS`) is fine, and a failure says the heartbeat's own reason. A job idle for as long as its plist allows (`GARRICK_IDLE_DAYS`, 7) goes under *Needs attention* as a warning. Once three days have calls, a chart shows the cost of each of the last fourteen days. The table gives each job's calls, cost, turns per call on average, and the tools it was refused: red for a tool the deny list in `System/jobs/headless-settings.json` forbids, which also goes under *Needs attention*, amber for one the job was only not allowed. A missing or unreadable deny list goes there too.
- **Repositories and wikis**: how many files have changed since the last commit in the workspace, each zone and the wikis, split into staged, not staged, untracked and conflicted, with their paths to read; and the date and title of the newest entry in each wiki's log. The card counts files, not commits, and never commits anything: another session may be halfway through that work. A repository with a change left uncommitted for more than a day turns amber and goes under *Needs attention*.

![The graph on the demo workspace, with a thread selected](../assets/status-graph.png)

The page has two tabs, three with the Todo list switched on. **Overview** shows where your work stands, and nothing about the machinery: the graph, the threads, open actions, and what is waiting in the inboxes. **Status** shows the machinery behind it: the figures first (how many things need attention, live threads, open actions, files waiting, and the check or the assistant's calls), then *Needs attention*, the scheduled jobs and assistant calls when you run the jobs extra, the check, the repositories and the wikis. A red dot on the *Status* tab means something there failed. Each figure opens the card that explains it, switching tab if it has to.

One row stays pinned at the top while the page scrolls: Garrick's mark, the page's name and when it was built, the tabs, a circular arrow that rebuilds the page (in the Mac app; in a browser it copies the command that does), the cog for [Settings](#settings), and three icons for an automatic, light or dark theme. There is no sidebar: the tabs move between the work and the machinery, and the cards are open on the page. At the top of the *Status* tab, *Only what needs attention* hides everything there that is healthy. Every section folds. Every card except *Needs attention* can be dragged by the grip in its header to another place on its tab, moved to the other tab with the arrows beside the grip, or hidden with its ×. A hidden card is listed in Settings, under *View*, and clicking it there brings it back. *Reset view*, in Settings, puts everything back as built, parked notes hidden again, and keeps your theme and the apps you chose to open projects in. The page remembers all of this in your browser and nowhere else, so each browser keeps its own.

## Settings

The cog beside the page's name opens *Settings*. In the Mac app, *Settings…* in the app menu (⌘,) opens it too.

**Opening a thread** lists the ways a project or thread can be opened: the note's own link (*Open in Obsidian*, or *Open the note* where Obsidian is not installed), *Reveal in Finder*, *Open in cmux*, *Open in Codex* and *Open in Claude*. Each build checks which of the apps this Mac has, and one that is not installed is greyed out. Each row has two controls:

- **A checkbox:** whether project and thread cards offer it. The apps work in the [Mac app](#a-mac-app) only.
- **A radio button:** what clicking a thread's name in the Threads list does. The note's own link is the default. An app chosen here takes over the click in the Mac app; in a browser the name still opens the note.

*Open in Claude* starts a new session in the thread's folder with "open Pricing" already typed in; press Send to resume the thread. *Open in Codex* and *Open in cmux* open the folder and put "open Pricing" on the clipboard. *Reveal in Finder* shows the folder. Your choices are kept in the window's own storage as you make them. In the Mac app, closing Settings after a change also saves them for every viewer of the page, in `System/generated/status-settings.json`, through `page_action.py`; each build carries that file into the page, and inside the app it comes before what a window remembers. A browser keeps its own. Close Settings with the × at its top right, or Escape.

**About Garrick** says which Garrick the workspace was installed from, in the same words as `python3 System/tools/check.py --version`. *Copy version* copies that line. *What's new* shows the notes of that release, read from the copy of the changelog the installer put in `System/garrick-changelog.md`. A workspace installed from a clone of `main` also sees *Coming next*, which is what is waiting for the next release. Below that are the ways to reach Garrick's maintainers:

- *Report a bug* opens the bug form on GitHub with *Which Garrick* already filled in.
- *Report a wrong refusal* opens the form for a refusal by the wall check that should have passed.
- *Suggest a change* and *Ask a question* open a new discussion under Ideas or Q&A.
- *Announcements* is where each release is announced. Watch it on GitHub to hear of the next one.
- *All releases* lists every release with what it changed.

Each one opens in your browser, and nothing is sent until you submit it there yourself. If you have no GitHub account, *Copy a report* copies an outline with your version in it. Fill it in and send it to whoever set Garrick up for you. Use invented names (Acme, Birch) in anything you report, never a real client's. A way to get past the wall check goes in a private report, not an issue: the dialog links to it.

The page never checks for a newer Garrick. It would have to ask GitHub every time it rebuilt, and the page loads nothing from the network. To see whether there is one, compare *All releases* with your version.

## Preview features

Some features are in Garrick's source before they are in a release. They are off until you switch them on in `System/garrick-flags.json`, and *Settings* lists each one and whether it is on. To switch one on, write its name there and rebuild the page:

```json
{"todo-list": true}
```

- **`todo-list`**: a *Todo* tab with every open action in the zones, one zone at a time, picked above the list (Work first, when you have it). Actions are grouped as `Todo.md` groups them, under its headings in their order; then *In thread notes*, the actions written in a thread's own notes; then *Done today*, what was ticked today. An empty heading is left out, but an empty Inbox says *Inbox clear*. Each action shows its thread, linked to the thread's note, its priority when high, and its date as Obsidian Tasks writes it: a due date with `📅`, a day to chase a `#waiting` line with `⏳`, red once it is overdue or due a chase. A line above the groups counts what is open, overdue and undated. *All*, *Overdue* and *No date* filter the list; *A–Z* sorts by thread, then by the action, and *Due date* puts dated actions first, soonest first. The page remembers the zone, the filter and the sort. It reads the notes and changes nothing. A zone's *Open the list* on the Overview opens the tab on that zone.

- **`page-actions`**: buttons that change your notes, in the Garrick app only. On the Todo tab, a box ticks an action, and ticking one under *Done today* again reopens it. Its date opens a menu: *Today*, *Tomorrow*, *Friday*, *Next Monday*, *In a week*, *In two weeks*, any other date, or *Clear the date*; a dated Inbox line says where it moves. The row changes at once and waits, greyed, for the rebuild. *＋ Add* above each zone's list writes a new one, which shows greyed in its section until the rebuild: the text, optionally a project or thread picked from a tree of the zone's projects with their threads folded under them, and optionally a date. The line goes to the top of the Inbox in the zone's `Todo.md`, opening with `[[Thread]]: ` when you picked one; with a date it goes where a dated line belongs, *This week* within seven days, *Soon* after that, *Waiting on* for a `#waiting` line. A line already in the list is refused. On a thread's card, *Park* and *Wake* replace the phrases to copy. Each button changes one line or one `status:` field, the same way the skills would: ticking adds Obsidian Tasks' `✅` date, and parking sets `status: parked`, moves `updated:` and adds a dated "Parked." entry. Each change is then committed in the zone's repository, through its wall check. If the wall check refuses the commit, the file is put back as it was, unless you edited it meanwhile, in Obsidian say: then your edit is kept and the reply says so. The flag is read at every click, so switching it off stops the buttons at once, even on a page built while it was on. The app runs `page_action.py` from the same folder as `status.py`, so copy both. A browser has no way to reach it, so there the buttons stay hidden; the [Obsidian plugin](#in-obsidian) reaches it as the app does. See [What the actions keep](#what-the-actions-keep).

- **`effort`**: *Time* and *Cost* on the Threads card. The same rows show the assistant's active time, or its list-price cost, over the last 30 days instead of how long since each note moved, largest first; *Updated* puts them back by name, and the page remembers the choice. A project's row counts all of its work, its threads and what it did in no thread; each thread shows its own. A line under the columns gives the total and whatever no row shows: sessions outside the zones (in `System/`, a wiki or the workspace root), sessions started in a zone's own folder, and threads finished or renamed since, so the figures add up. Hover a figure for its raw tokens and sessions. It reads Claude Code's own transcripts in `~/.claude/projects/`, with no model call, through `effort.py` beside `status.py`, so copy both:
  - *Which thread.* The folder a session ran in gives the zone and project; a thread's own folder gives the thread. Otherwise the thread is the one whose `Threads/<X>/` notes the session wrote or edited most, and a project with no thread notes is its own thread. Anything left counts as the project's own work rather than a guess. A session started above the zones is placed by the notes it wrote.
  - *Time* is active time: the gaps between messages, with any gap over five minutes left out as idle.
  - *Cost* is the list price of the tokens, the measure *Assistant calls* uses. It comes out a little under Claude Code's own count, which also prices small background calls the transcripts do not record. Cache reads dominate the raw token counts, which is why the card shows cost and time, not tokens.
  - *Scheduled jobs* are left out: a headless run is already in *Assistant calls*.
  - *Moved and renamed folders.* `--also OLD` reads a folder the whole workspace used to live in as the workspace, and `--moved OLD=NEW` counts a renamed project or a moved wiki under its present name (`--moved "Zones/Work/Acme Old=Zones/Work/Acme Review"`). Both can be given more than once, to `effort.py --record` and to `status.py` alike, so the page and the nightly record count the same way; in the Mac app, give them to `make-app.sh` after `--`.
  - *History.* Claude Code deletes transcripts after 30 days by default, the same span the card shows. To keep the days anyway, run `python3 System/status/effort.py --workspace <your workspace> --record` nightly, for example as a [job](scheduled-jobs.md): each day's totals per thread go to `effort.jsonl` beside the jobs ledger, and the page reads that file as well as the transcripts.
  - Codex keeps its sessions elsewhere, in another format, and is not counted yet; the card says so.
  - Only names, durations and figures reach the page, never a line of a transcript.

- **`menu-bar`**: Garrick in the menu bar, in the Garrick app only. See [In the menu bar](#in-the-menu-bar).

- **`ask`**: the panel's field, and a box that ⌘G opens, answer a request in plain words and act on it, in the Garrick app only. See [Ask](#ask).

A preview feature may still change. When one is released it is switched on for everyone and its flag goes away.

## Thread cards

Hover a thread in the list, or move to it with the keyboard, and a card opens under it. It shows the thread's name, zone and project, its party, and how long since its note was updated, or that it is parked. Then come the actions:

- *Open* opens the thread note, and *Open project* its project's hub note.
- *Copy "open Pricing"* copies the phrase that resumes the thread.
- *Park*, at the top right beside the thread's name, copies "park Pricing", the phrase that sets it aside; on a parked thread it is *Wake*. With the preview `page-actions` on, in the Mac app, it parks or wakes the thread itself.
- *Open in Claude*, *Open in Codex* and *Open in cmux*, only in the [Mac app](#a-mac-app), one for each of those apps that is installed and switched on in [Settings](#settings). Claude starts a session in the thread's folder with "open Pricing" typed in. Codex and [cmux](cmux.md) open the folder with "open Pricing" on the clipboard. A project gets the same buttons for its own folder.
- With the [cmux extra](cmux.md) installed, cmux on the Mac and the preview `page-actions` on, *Open in cmux* goes through the desk instead: a tab for the thread, resumed. A card whose project or thread has a session open says so, and offers *Close session* beside *Park*. The top row gains *Start up*, which brings back the day's tabs, and *Shut down*, which asks for a second click, then wraps each session and quits cmux.
- The card also says when the thread's resume point is dated, or that its note has no Resume here block.

After *Park*, *Wake*, *Open in cmux* or *Close session*, the page keeps asking the app for a rebuild, every two seconds for up to thirty, until it shows what you asked for: a session can take a few seconds to open or close. The page keeps its place on each reload.

In the Mac app, *Open* and the app buttons are drawn as the apps' icons, the same line its [menu bar](#in-the-menu-bar) shows: the note's app first, then Finder, cmux, Codex and Claude. The one a click on the thread's name runs sits on a tinted square. Hover an icon for its name. A browser shows the words.

The graph's panel offers the same actions under the same labels, the app buttons included, for a thread's note as for a project's hub. On a project's hub note it also offers "open Acme Review", unless a thread has the same name. Names are said in the shortest form that is unique, the way the threads skill says them: "Pricing", or "Acme Review, Pricing" when two projects have a thread called Pricing, and "Work, House, Kitchen" when projects called House in two zones both have a Kitchen thread. Escape closes the card, and moving the pointer away does too.

## What it shows, and what it leaves out

**It shows names, tags, dates, counts, check findings and the targets of links.** From each note it reads the frontmatter, as "what's open" does, using the workspace's own parser, `System/tools/garrick_lib.py`, when it is there. From a thread's note it also reads whether it has a `### Resume here` block and the date on that block's first lines, and nothing else of it. From each `Todo.md` it reads the section headings and counts the unticked lines under them. From each wiki log it takes the newest entry's date and title. The check's findings appear as `check.py` words them, so they can quote a link's target, a party's name or an alias. The graph reads the targets of each note's `[[links]]` and draws them as lines. It names every note it draws, meeting titles included. The rest of a note's body never reaches the page. Pass `--no-graph` and no note is read for its links.

**It stores nothing.** It reads files the workspace and the jobs extra already keep, and writes only itself (with `--settle`, also a one-line mark beside itself, `status.html.settle`). Delete it and nothing is lost.

**It lives in `System/generated/status.html`**, the workspace's folder for pages a tool rebuilds. The page is the one place that shows every zone at once, so two rules keep that folder harmless, and `check.py` holds both. It never enters git history: the root `.gitignore` names it, and the check reports a generated file that is committed, or a `.gitignore` that has lost the line. And it never counts as shared wording. The wall check lets a run of words through when it also appears in material every side reads. That material is a fixed list: the `AGENTS.md` files at the root, in `Wikis/` and in `Wikis/Meetings/`, `System/rules.md`, `System/context.md`, `System/skills/`, `System/templates/`, `System/tools/` and the Knowledge wiki. Nothing else under `System/` is on it, `System/generated/` included, so a page that gathers every zone can never make wording count as shared. You can write the page elsewhere with `--out`; inside the workspace, anywhere but `System/generated/` earns a warning.

## Set it up

1. **Copy `extras/status/` into your workspace as `System/status/`**, next to `System/jobs/` if you have it, and commit it in the workspace root's repository. The previews' scripts (`page_action.py`, `ask.py` and `ask-brief.md`) go with it, and `obsidian/` holds the [Obsidian plugin](#in-obsidian). A workspace installed before this extra existed needs one line added to its root `.gitignore`: `System/generated/`. The check tells you if it is missing.
2. **Build it and open it:**
   ```sh
   python3 System/status/status.py --workspace ~/Garrick --open
   ```
   The folder you name must hold `System/rules.md` and `Zones/`. A mistyped path stops with a message and creates nothing.
3. **Links open your notes where you read them.** Each build reads [Obsidian](obsidian.md)'s own list of vaults. A note in a vault Obsidian knows, whether that is the workspace root or a zone or wiki you opened on its own, opens there, in the vault closest to it. Any other note opens as a file, in whatever app opens Markdown on your machine. Nothing needs setting: open a folder as a vault in Obsidian and the next build links into it. To name the root vault yourself, pass `--obsidian Garrick`; to keep every link a file link, pass `--no-obsidian`.
4. **Keep it current on a schedule**, if you like, through the jobs wrapper. It calls no assistant, so it needs no `--agent`:
   ```sh
   python3 System/jobs/job.py status --cwd ~/Garrick -- \
     python3 System/status/status.py --workspace ~/Garrick
   ```
   `extras/status/garrick.status.plist` runs that every evening at 23:30. Where several things may ask for a build at once, such as a hook at the end of each session, add `--settle 10`: each request waits ten seconds and builds only if no later one came meanwhile, so a burst makes one page.

The page says how old it is, and turns its banner red when it is more than a day and a half old, so a schedule that stopped is not mistaken for a quiet week.

## A Mac app

*Garrick.app* shows the page in a window of its own, so it sits in the Dock and the app launcher instead of a browser tab. It is a viewer for the one file and nothing more, so the page is still built by `status.py` alone. What it adds:

- **It keeps the page current.** When the page is more than 30 minutes old, the app rebuilds it at launch and again whenever you bring the app forward, and it reloads the page whenever it is rewritten, by itself, a schedule or a terminal. The window's subtitle says *Rebuilding…* meanwhile, and the last build stays on screen.
- **Its buttons do what they say.** The top row's circular arrow becomes *Rebuild now*. *Copy* puts the phrase on the clipboard, as in a browser. Project and thread cards, and the graph's panel, gain *Open in Claude*, *Open in Codex* and *Open in cmux*, for the ones that are installed and switched on in [Settings](#settings), and show every way to open a note as its app's icon. The app menu's *Settings…* (⌘-comma) opens Settings.
- **Links go where your Mac sends them**: a note to Obsidian or your Markdown app, a log to its viewer.
- **The Edit menu works in its fields.** ⌘V pastes into the Todo list's *Add* field and the panel's field, with Cut, Copy, Undo and Redo beside it.
- **Safari can inspect it.** With Safari's *Develop* menu on, *Develop › your Mac › Garrick* opens the Web Inspector on the page, for its console and what it keeps in storage. The app names itself `GarrickApp` in its user agent.

Build it once, from the workspace:

```sh
System/status/app/make-app.sh
```

It compiles `Garrick.swift` with the Xcode command line tools, which a Mac that runs `git` and `python3` already has, and puts the app in `~/Applications`, signed for this Mac only. It downloads nothing. The app reads the workspace's place, the `python3` that built it and any flags you give after `--` (`make-app.sh -- --no-graph`) from its own settings, so build it again after moving the workspace or changing those. `--dest` puts it elsewhere. It will not replace another app of the same name, and it replaces a build from before 0.10.0, when the app was called *Garrick's Status*, keeping its settings. Drag it to the Dock to keep it there. To test it, `~/Applications/Garrick.app/Contents/MacOS/Garrick --check` loads the page without a window, presses one card's buttons without acting on them, prints what it found and quits.

### In the menu bar

With the preview `menu-bar` on, Settings gains a *Menu bar* section, in the app only, with four settings that the app keeps itself:

- **Show the menu** keeps Garrick's menu at hand outside the window: by default as Garrick's mark in the menu bar, drawn in the menu bar's own colours, or as a panel (see *Shows as*). Closing the window then leaves the app there, without a Dock icon, and *Open Garrick* in its menu, or the app's icon in Finder, brings the window back. A red dot on the mark, or *Something failed* in the panel, means the same as the red dot on the *Status* tab: something failed.
- **Shows as** picks where the menu lives: *Menu bar icon*, or a panel that slides out from the left or right edge of the screen, or down from the top. See [As a panel](#as-a-panel).
- **Open at login** starts the app when you log in, as a login item. It opens the way you left it: in the menu bar alone if its window was closed. It needs macOS 13 or later; macOS may ask you to allow it under *Login Items* in System Settings.
- **Hotkey** opens the menu, or the panel, from any app. With the preview `ask` on and the menu as an icon, it opens the Ask box instead. Click the field and press the keys, with ⌘, ⌃ or ⌥; *Clear*, or Delete in the field, takes it away. A shortcut another app already holds is refused. It needs no Accessibility permission.

The menu lists the live projects of the zone the graph shows, as last picked in the window, by name. With *All* picked it lists every zone, and with a wiki picked it lists Work. Point at a project and its submenu opens: a line of app icons, the ways its card offers to open it (the note, *Reveal in Finder*, Claude, Codex, cmux, as switched on in Settings), then its live threads. Point at a thread for its own line of icons. Click an icon to open the project or thread in that app; hover one for its name. Click a project's or a thread's name itself and it opens the way clicking a thread's name does in the window: the default chosen under *Opening a thread*, which sits on a tinted square in the line of icons. Nothing else is listed: no bars, no figures, no parked threads. At the foot are *Open Garrick's Status* and *Quit*. The keyboard moves through the menu and opens a submenu, but Return on a name does nothing; click it, or pick its icon.

**Process the Inbox** opens the menu, when an assistant is switched on in Settings. It says how many items wait in the inboxes, each zone's and the Meetings inbox, as the page counts them, or *empty*. Clicking it opens the default assistant for clicking a thread at the workspace root with "process the inbox". If that default is the note or Finder, it uses the first of Claude, Codex and cmux that is switched on. Claude gets the phrase typed in, so you press Send; Codex and cmux get it on the clipboard. The `intake` skill then reads each item and decides what it is, a conversation for Meetings, something to read for Knowledge, or material for a project, so mail and recordings need no separate buttons.

**Keep awake**, above *Open Garrick's Status*, stops your Mac going to sleep on its own, the way the `caffeinate` command does. Pick *For 1 Hour*, *For 3 Hours*, *Until Turned Off*, or *While an Agent Is Working*, and *Off* to stop. The row's title says what is on and, for a timed choice, how long is left. While it holds the Mac awake, its cup is filled and the mark carries an amber dot at its bottom right. *Display Stays On Too* keeps the screen lit as well; without it, the screen still dims and sleeps.

*While an Agent Is Working* checks once a minute whether Claude Code or Codex is in the middle of a turn, and keeps the Mac awake only then. It reads their transcripts on this Mac, through `agents_working.py` beside `status.py`, and calls no model. A transcript not written for 30 minutes no longer counts, so a session that crashed mid-turn lets the Mac sleep, and so does a single command that runs longer than that without output. Run `python3 System/status/agents_working.py --verbose` to see what it sees. This choice is the only one remembered when the app restarts. A forgotten *Until Turned Off* should not come back at login.

The app holds the Mac awake itself, so quitting it, or a crash, lets the Mac sleep again. Taking the icon out of the menu bar, or the panel off its edge, turns Keep awake off. A MacBook with its lid closed and no external display sleeps anyway: only an administrator's `pmset` setting can change that, and Garrick doesn't try.

#### As a panel

With *Shows as* set to a panel, the icon leaves the menu bar and the same list lives in a panel at the edge you picked. Rest the pointer against that edge for a quarter of a second and the panel slides out; move away and it slides back. The hotkey opens it too, with the cursor in its field: type part of a name and Return opens the first thread that matches.

The same field asks. Whatever you type also shows as *Ask Garrick* at the top of the list; click it, or press Return when no project or thread matches, and the default assistant for clicking a thread opens at the workspace root with your words, as *Process the Inbox* opens with its phrase. Claude gets them typed in for you to send; Codex and cmux get them on the clipboard. The panel itself answers nothing and calls no model, unless the preview `ask` is on: then it answers in place (see [Ask](#ask)). A click in another app closes it, and so does Escape when the panel has the keyboard. The panel never brings Garrick forward, so the app you were in stays in front.

The panel shows every project of the zone with its threads already open under it; the chevron beside a project folds them. Point at a row for its app icons, as in the menu's submenu, and click its name to open it the default way. *Process the Inbox* is at the top, and *Keep awake*, *Open Garrick* and *Quit* at the foot. A red *Something failed* in its header means what the red dot on the mark means.

*From the top* grows down out of the notch on a MacBook that has one, black like the notch, and opens when the pointer rests on the notch itself, where the menu bar has no items. On a display without a notch it hangs from the middle of the menu bar, and the middle 200 points of the top edge open it. On the left or right, only the top third of the edge opens it, and the panel hangs from the top of the screen over it, so other apps that live on that edge keep the rest. Only an outer edge of the screen counts: an edge where the pointer can carry on to another display never opens it.

Three edges can collide with macOS. On the left, Stage Manager shows its strip of recent apps there, and a Dock placed on the left lives there too. At the top, *Automatically hide and show the menu bar* shows the menu bar when the pointer rests there. The right edge collides with neither: Notification Center opens with a trackpad swipe, not by resting the pointer there.

Seeing where the pointer is needs no permission in macOS; only reading keys typed in other apps would, and the panel never does.

The menu is filled from the page, so it holds what the last build found. Opening it rebuilds a page more than 30 minutes old, and the app checks every hour, so the dot is never a day behind. Rebuild the app with `make-app.sh` after updating Garrick to get the icon; the flag alone does not add it to an app built before.

### Ask

With the preview `ask` on, the panel's field answers you itself. Type "open Pricing in Claude", "park the launch video", "add call Dana to Acme for Friday" or "what's open", then click *Ask Garrick* or press Return when no project or thread matches. The answer shows under the field, one sentence and what was done, and the panel stays open for a follow-up such as "no, the other one". When the request opened something, the panel closes and that app comes forward. ⌘G in the app, and the hotkey when the menu is an icon rather than a panel, open a box of its own that does the same. With the preview off, the field opens your assistant with the words, as before.

`ask.py`, beside `status.py`, does the asking. It keeps one assistant session warm, so a request answers in a second or two; it is replaced every three hours, and stops when nothing has been asked for three hours. The session sees the names and states of your projects and threads, read from their frontmatter, and nothing from inside a note. It proposes actions, and `ask.py` checks each one against that list before anything runs:

- *open* a project or a thread, in the app you named (Claude, Codex, cmux or Finder) or your default for clicking a thread. The app opens it as a row's icon does.
- *park* or *wake* a thread, or a project with no threads, and *add* a line to a zone's Todo list. These run through `page_action.py`, as the page's buttons do: committed in the zone's repository, logged in `page-actions.log`. They need the preview `page-actions` on as well; without it, Ask still opens things but changes nothing.

An app you name must be switched on under *Opening a thread* in Settings, as on the page; one switched off is refused, and the panel stays open to say so.

It does nothing else. It does not tick lines, run jobs, change settings, read notes or send anything, and says so when asked.

It runs as the [scheduled jobs](scheduled-jobs.md) do, so it needs `agent.py` from that extra in `System/jobs/`:

- **The assistant** is `GARRICK_HARNESS`: Claude, by default, or Codex. Claude keeps one `claude -p` session open with no tools, no MCP servers and no transcript on disk. Codex has no warm session, so each request is one read-only `codex exec`, given the last six exchanges again, and takes longer.
- **The tier** is `GARRICK_ASK_TIER`: `haiku` by default, or `sonnet` or `opus`. It names a tier, never a model.
- **The limits** are the jobs' own. The session loads `headless-settings.json`, the deny profile. Each request is one call against `GARRICK_CAP_CALLS_HOUR`, `GARRICK_CAP_CALLS_DAY` and `GARRICK_CAP_COST_DAY`, and one line in the ledger as job `ask`, so the *Assistant calls* card counts it. A request past a cap is refused and calls nothing. A Claude session as a whole stops at `GARRICK_MAX_CALL_USD`: that request says so, and the next one starts a new session. The app passes on the environment it started with. Opened from the Dock or at login, that is only what `launchctl setenv` has set, so the defaults hold unless you set these there.
- **The record** is one line per request in `ask.log` in the jobs folder: the request, the answer, what was done, how long it took and the tokens.
- **One server per workspace.** A lock beside its socket in the jobs folder keeps a second from starting. A request that hears nothing for two and a half minutes says so and stops waiting; the app gives up after three.

To try it from a terminal: `python3 System/status/ask.py --workspace ~/Garrick ask "what's open"`. `--list` prints what the session is given, and `stop` stops it.

## In Obsidian

`extras/status/obsidian/` is an Obsidian plugin that shows the page in an Obsidian tab, with the buttons the Mac app gives it. Desktop Obsidian only.

1. Copy the folder into a vault inside your workspace, as `.obsidian/plugins/garrick-status/`: `main.js` and `manifest.json`. The vault can be the workspace root, a zone or a wiki.
2. In Obsidian, *Settings › Community plugins*, switch on *Garrick*.
3. Click Garrick's mark in the ribbon, or run *Garrick: Open* from the command palette.

The plugin finds the workspace as the first folder at or above the vault that holds `System/rules.md` and `Zones/`. If your vault sits elsewhere, name the workspace in *Settings › Garrick*, which also takes the Python to run, where `status.py` is, and flags for it.

What it adds, as the Mac app does:

- **The page in a tab**, rebuilt when it is more than 30 minutes old, as the tab opens and each hour while it is open, and reloaded whenever it is rewritten. *Rebuild* and *Open in browser* sit at the tab's top right.
- **Its buttons.** Copy, *Rebuild now*, *Reveal in Finder*, *Open in cmux*, *Open in Codex* and *Open in Claude* work as in the app, and so do the buttons of the preview `page-actions`, through `page_action.py`. Each says what it did in the page's own toast. The app's menu bar settings do nothing here.
- **Links.** A note in this vault opens in a new tab beside the page. Anything else goes to macOS, as from a browser.
- **Parked work out of the file list.** A thread whose note says `status: parked` is hidden in the file explorer, and so is a project whose hub says it or whose threads are all parked. It follows your notes as they change. Switch it off in *Settings › Garrick*.

The page itself only knows how to reach the Mac app. So the plugin shows a copy of it, `status-obsidian.html` beside `status.html`, with a few lines at the top that give it the same bridge, and pass each message out through the web view's console under a word chosen at random when the plugin starts. Like the page, the copy is rebuilt output in `System/generated/`, never committed.

To check it by hand after installing or updating: open the tab and click *Rebuild now*; the toast says *Rebuilding…* and the page's age resets. Copy a thread's phrase and paste it somewhere. Click a thread's note link and it opens in a tab. With `page-actions` on, tick a Todo line and untick it: each says what it did, and `page-actions.log` has two lines. Park a thread from its card and its folder leaves the file explorer; wake it and it comes back.

## What the actions keep

The buttons that change something (the preview `page-actions`) all go through `page_action.py`, from the Mac app, the [Obsidian plugin](#in-obsidian) or [Ask](#ask).

Each request names one verb, and `page_action.py` takes these and no others. A new verb is a new way for the page to change your workspace, so the test suite fails until it is listed here, where a reviewer sees it.

| Verb | What it does |
|---|---|
| `todo-done` | Ticks a Todo line, with Obsidian Tasks' `✅` date |
| `todo-undo` | Reopens a line ticked from the page |
| `todo-date` | Sets or clears a line's date: `📅`, or `⏳` on a `#waiting` line |
| `todo-add` | Writes a new line in a zone's `Todo.md`, and refuses one already there |
| `park` | Sets a thread's `status:` to `parked`, with a dated entry |
| `wake` | Sets it back to `active`, with a dated entry |
| `run` | Starts a scheduled job now, through launchd, unless it holds its lock |
| `settings` | Saves how a thread opens, for every viewer of the page |
| `open` | With the [cmux extra](cmux.md): a tab for a thread or project, resumed |
| `close` | With the cmux extra: closes its tabs, unless one is mid-turn |
| `startup` | With the cmux extra: starts cmux and brings back the day's tabs |
| `shutdown` | With the cmux extra: wraps each session, then quits cmux |

- **A log.** Every request, done or refused, is one line in `page-actions.log` in the jobs folder: `~/Library/Logs/garrick-jobs/` on a Mac, or `GARRICK_JOBS_DIR`, the folder the [scheduled jobs](scheduled-jobs.md) use. A line holds the time, the verb, the fields that verb reads (the zone, the note, the line's key, the date, the job) and what came of it. The text of a new Todo line is cut to 60 characters, and nothing else a request carries is written. A request from Ask ends `(ask)`.
- **A second click finds its line.** A line is named by a hash of its exact text, and giving it a date changes the text. Until the page rebuilds, a second click on the same row still carries the old name. For an hour, `page_action.py` remembers which old name became which new one, note by note, in `todo-rekeys.json` beside the log, so a second date, a tick or an undo lands on the line you meant. A line changed any other way is still refused, and the page rebuilds.
- **One at a time per zone.** Each click is its own process, so two quick clicks, or a click and a request to Ask, can arrive together. Each takes the zone's lock first, `page-action-<zone>.lock` in the jobs folder, and holds it from reading the note to committing it, so the second waits for the first rather than undoing it. A request that waits 45 seconds is refused, and you can click again.
- **Git gets a minute.** A wall check that hangs, or a signing key waiting for its passphrase, is stopped after 60 seconds, and the request is refused as if the check had said no. Any other fault is still answered, in one line of JSON, and logged.
- **Run now waits for a running job.** *Run now* on a job's strip starts the job through launchd. If the job still holds its lock, the folder `<job>.lock` that `job.py` keeps in the jobs folder, it is already running, and the button says so instead. Whether the lock still stands is `job.py`'s own call, read from the jobs extra beside the page: a run whose `job.py` is still alive holds it whatever the clock says, as after the Mac slept. Without that extra, a lock past the time its `until` file names belongs to a run that died, and the job starts.
- **One file for how a thread opens.** `{"verb": "settings", "launchers": ["note", "cmux"], "default": "cmux"}` saves *Opening a thread* to `System/generated/status-settings.json`, so the Mac app and Obsidian agree: every way to open a thread with `true` or `false`, and the default for clicking a thread's name. The names are `note`, `finder`, `cmux`, `codex` and `claude`, and the default must be one switched on, or `note`. Like the page, the file is rebuilt output and is never committed.

The app, or the plugin, rebuilds the page after every request.

## Buttons that copy, not act

In a browser the page is a file, and a file cannot act on your workspace, so its buttons copy instead. Paste what a card copies to your assistant. The top row's circular arrow copies the command that rebuilds the page. It is absolute and quoted, so it runs from any folder, and it carries the flags the page was built with.

Nothing on the page can change a file, and nothing it copies runs until you paste it somewhere yourself. That holds in the Mac app and in Obsidian too, unless you switch on the [preview](#preview-features) `page-actions`, whose buttons tick, date, park and wake, or `ask`. There it can rebuild the page, which writes only the page, and open a cmux tab in a folder of your workspace, which writes nothing. Without the [cmux extra](cmux.md), it hands the folder to cmux the way Finder's *Open With* does, so it needs no access to cmux's controls and types nothing into the tab. With the extra and `page-actions` on, *Open in cmux*, *Close session*, *Start up* and *Shut down* go through its desk, which drives cmux through its own controls and types the phrase that resumes a thread into the new tab.

## Reading the graph

The graph shows one place at a time: Work when you have it, or another zone or wiki picked from the drop-down above it, or *All*. The page remembers the pick. The line under the legend counts what is drawn.

With *All*, each zone and wiki has its own spot on the card: a few sit in a row, more go round an ellipse in the card's proportions, and places that link to each other sit side by side. A zone reads as a cluster, and the notes fill the card in either view.

Each kind of note has its own colour: projects, threads, meetings, mail filed in the Meetings wiki, people, Knowledge pages and other notes. The legend lists only the kinds the view draws. A zone or wiki inside an Obsidian vault with colour groups of its own (*Groups* in Obsidian's graph settings, kept in the vault's `.obsidian/graph.json`) is coloured as Obsidian colours it instead, and a note no group takes is grey. The page reads groups written as `[key]`, `[key:value]`, `file:`, `path:` and `tag:`, joined by `OR`; any other term matches nothing, since the page reads no note's text to test it. The vault's *Excluded files* (`.obsidian/app.json`) stay off the graph too. A thread that has gone quiet carries an amber or red ring. Parked threads, with the notes in their folders, are hidden, and so is any project with no live thread left; *Show parked* draws them, faded.

Click any note in a project and its panel offers the same apps a card does, opening its thread's folder, or its project's.

Some notes stay off the graph: each zone's `Todo.md`, which has its own card; every `AGENTS.md`, which holds instructions for assistants rather than notes; the zones' inboxes; and any folder of raw records, old versions or generated pages (`raw`, `archive`, `generated`). A project or thread is drawn whatever it is called.

Projects and threads are named. Hover or click a note and its linked notes are named too; zoom in and the rest are. Names are placed in order: the note in focus, its links, projects, then threads. A name with no room under its note moves above or beside it, or waits until you zoom in or hover, so one name never covers another. The exception is a project's name or the selected note's, which always shows, even on a graph too crowded to leave it room.

The graph sways a few degrees back and forth when left alone. A hover, a drag, an open panel or your system's reduced-motion setting stops it, and once nothing moves it stops drawing. *Fit* brings back the whole graph after you zoom in or move it.

## Reading the job strips

Each cell is one day, coloured by how the day *ended*: red when its last run failed or most of its runs did, amber when a run failed and the job recovered, green when every run was clean, grey when nothing ran. A day is not painted red for one failure among many runs; a page that is always red gets ignored as surely as one that is never red. Hover a cell for its runs and their exit codes.

## The mark

The mark is a cabinet of three compartments: a narrow spine, the open one in Garrick's blue and a closed one beneath, for each party's work in its own place and one thing open at a time. It follows the page's theme: navy `#1E2833` and blue `#3D73E0` in the light theme, cream `#F5F0E6` and the lighter `#8EB1F5` in the dark one, where `#3D73E0` would fall to 3.4 to 1. The tab icon is the small cut, drawn on the 16-pixel grid so its walls stay a pixel wide, and follows your browser's light or dark setting. The Mac app's icon is the mark on a navy tile. `#3D73E0` is also the page's accent in the light theme. The dark theme's accent is a lighter blue of the same hue, `#6590E6`, with a contrast of at least 4.5 to 1 against every dark surface. [The mark's note](../assets/brand.md) has the files and colours.

## What you lose without it

Nothing. Every number on the page comes from a file you can open, a command you can run, or a question you can ask: "what's open", `check.py`, `agent.py ledger`. The page puts them in one place, so the first thing you see is what needs you.
