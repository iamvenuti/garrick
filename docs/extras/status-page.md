# Extra: a status page

One page, Garrick's Status, that answers two questions before you open anything: is anything wrong, and where was I? It is a single HTML file you open in a browser. It needs no server, no account and no network, and it works whether or not you use Obsidian.

## What it shows

- **A graph of the workspace**: every note in your zones and wikis, and the links between them. Each zone and wiki has its own spot, laid along the card: a few in a row, more round an ellipse in the card's proportions, with places that link to each other placed side by side. So a zone reads as a cluster, and the notes fill the card in either view. Threads that have gone quiet carry an amber or red ring. Parked threads, with the notes in their folders, are hidden, and so is any project with no live thread left. Press *Show parked* to draw them, faded. Each zone's `Todo.md` stays out, since it has its own card, and so does every `AGENTS.md`, which holds instructions for assistants rather than notes. So do the zones' inboxes and any folder of raw records, old versions or generated pages (`raw`, `archive`, `generated`), but a project or thread is drawn whatever it is called. The legend lists only the kinds of note the view draws. Projects and threads are named; hover or click a note and its linked notes are named too, and zooming in names the rest. Names never sit on top of each other: the note in focus, its links, projects and then threads are placed first, and a name with no room under its note moves above or beside it, or waits until you zoom in or hover. A project's name and the selected note's always show. Click a note for its links and the same actions a thread's card offers. Double-click opens it. It sways a few degrees back and forth when left alone; a hover, a drag, an open panel or your system's reduced-motion setting stops it. *Fit* brings it back to the whole graph after you zoom or move it. *Projects and threads* and *Everything* switch how much it shows.
- **Threads**, one column per zone: every live thread, by name, with its project, its party and how long since its note was updated. The bar fills toward sixty days and turns amber after 14 days, red after 45. Threads you have parked ("park X") sit in a folded *Parked* group at the foot of their zone, also by name, out of the counts. Hover a thread for its card.
- **Checks**: what `System/tools/check.py` finds, run as the page is built, grouped by check.
- **Open actions**: the unticked items in each zone's `Todo.md`, counted by section, with an *Open* link to the list.
- **Inboxes**: what is waiting to be filed in each zone's `Inbox/` and in the Meetings inbox.
- **Scheduled jobs and assistant calls**, when you use the [scheduled jobs](scheduled-jobs.md) extra: a fourteen-day strip per job, one cell per day, and the spend against its caps. A job's caps are the `GARRICK_CAP_*` values in its launchd plist, so that is where the page reads them, from the plists of the jobs that call the assistant, the lowest where they differ; a cap a plist leaves out is the default. With no such plist the caps are the ones the page was built with, and the card says which. A cap set to 0 shows as *no cap*. A job the cap stopped is one line in *Needs attention*, however many calls it lost.
- **Repositories and wikis**: what is not yet committed in the workspace, each zone and the wikis, and the date and title of the newest entry in each wiki's log.

![The graph on the demo workspace, with a thread selected](../assets/status-graph.png)

A sidebar holds Garrick's mark, the overall state, a *problems only* switch that hides everything healthy, and a light, dark or automatic theme. Every section folds. Every card except *Needs attention* can be dragged by the grip in its header to another place on the page, or hidden with its ×; a hidden card is dimmed in the sidebar, and clicking it there brings it back. *Reset view* puts everything back as built, parked notes hidden again, and keeps your theme. The page remembers all of this in your browser and nowhere else, so each browser keeps its own.

## Thread cards

Hover a thread in the list, or move to it with the keyboard, and a card opens under it. It shows the thread's name, zone and project, its party, and how long since its note was updated, or that it is parked. Then come the actions:

- *Open* opens the thread note, and *Open project* its project's hub note.
- *Copy "open Pricing"* copies the phrase that resumes the thread.
- *Copy "park Pricing"* copies the phrase that sets it aside. On a parked thread it is *Copy "wake Pricing"*.

The graph's panel offers the same actions under the same labels. On a project's hub note it also offers "open Acme Review", unless a thread has the same name. Names are said in the shortest form that is unique, the way the threads skill says them: "Pricing", or "Acme Review, Pricing" when two projects have a thread called Pricing. Escape closes the card, and moving the pointer away does too.

## What it shows, and what it leaves out

**It shows names, tags, dates, counts, check findings and the targets of links.** From each note it reads the frontmatter, as "what's open" does, using the workspace's own parser, `System/tools/garrick_lib.py`, when it is there. From each `Todo.md` it reads the section headings and counts the unticked lines under them. From each wiki log it takes the newest entry's date and title. The check's findings appear as `check.py` words them, so they can quote a link's target, a party's name or an alias. The graph reads the targets of each note's `[[links]]` and draws them as lines. It names every note it draws, meeting titles included. The rest of a note's body never reaches the page. Pass `--no-graph` and no note is read for its links.

**It stores nothing.** It reads files the workspace and the jobs extra already keep, and writes only itself. Delete it and nothing is lost.

**It lives in `System/generated/status.html`**, the workspace's folder for pages a tool rebuilds. The page is the one place that shows every zone at once, so two rules keep that folder harmless, and `check.py` holds both. It never enters git history: the root `.gitignore` names it, and the check reports a generated file that is committed, or a `.gitignore` that has lost the line. And it never counts as shared wording. The wall check lets a run of words through when it also appears in material every side reads. That material is a fixed list: the `AGENTS.md` files at the root, in `Wikis/` and in `Wikis/Meetings/`, `System/rules.md`, `System/context.md`, `System/skills/`, `System/templates/`, `System/tools/` and the Knowledge wiki. Nothing else under `System/` is on it, `System/generated/` included, so a page that gathers every zone can never make wording count as shared. You can write the page elsewhere with `--out`; inside the workspace, anywhere but `System/generated/` earns a warning.

## Set it up

1. **Copy `extras/status/` into your workspace as `System/status/`**, next to `System/jobs/` if you have it, and commit it in the workspace root's repository. A workspace installed before this extra existed needs one line added to its root `.gitignore`: `System/generated/`. The check tells you if it is missing.
2. **Build it and open it:**
   ```sh
   python3 System/status/status.py --workspace ~/Garrick --open
   ```
   The folder you name must hold `System/rules.md` and `Zones/`. A mistyped path stops with a message and creates nothing.
3. **Links open the files themselves**, in whatever app opens Markdown on your machine. If you opened the workspace root in [Obsidian](obsidian.md) as a vault, pass its name and the links open there instead:
   ```sh
   python3 System/status/status.py --workspace ~/Garrick --obsidian Garrick --open
   ```
4. **Keep it current on a schedule**, if you like, through the jobs wrapper. It calls no assistant, so it needs no `--agent`:
   ```sh
   python3 System/jobs/job.py status --cwd ~/Garrick -- \
     python3 System/status/status.py --workspace ~/Garrick
   ```
   `extras/status/garrick.status.plist` runs that every evening at 23:30.

The page says how old it is, and turns its banner red when it is more than a day and a half old, so a schedule that stopped is not mistaken for a quiet week.

## Buttons that copy, not act

The page is a file, and a file cannot act on your workspace, so its buttons copy instead. Paste what a card copies to your assistant. The sidebar copies the command that rebuilds the page. It is absolute and quoted, so it runs from any folder, and it carries the flags the page was built with.

Nothing on the page can change a file, and nothing it copies runs until you paste it somewhere yourself.

## Reading the job strips

Each cell is one day, coloured by how the day *ended*: red when its last run failed or most of its runs did, amber when a run failed and the job recovered, green when every run was clean, grey when nothing ran. A day is not painted red for one failure among many runs; a page that is always red gets ignored as surely as one that is never red. Hover a cell for its runs and their exit codes.

## The mark

The mark is a white *Gr* on Garrick's blue, `#3D73E0`, like a tile in the periodic table, with a small *ai* in its corner. The tab icon is the same tile with *Gr* alone, since the *ai* cannot be read at that size. The letters are outlines of Baskervville, a Baskerville revival under the SIL Open Font License, carried in the page itself. The blue is also the page's accent in the light theme. The dark theme uses a lighter blue of the same hue, `#6590E6`, with a contrast of at least 4.5 to 1 against every dark surface.

## What you lose without it

Nothing. Every number on the page comes from a file you can open, a command you can run, or a question you can ask: "what's open", `check.py`, `agent.py ledger`. The page puts them in one place, so the first thing you see is what needs you.
