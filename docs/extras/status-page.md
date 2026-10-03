# Extra: a status page

One page that answers two questions before you open anything: is anything wrong, and where was I? It is a single HTML file you open in a browser. It needs no server, no account and no network, and it works whether or not you use Obsidian.

## What it shows

- **A graph of the workspace**: every note in your zones and wikis, and the links between them. Each zone and wiki starts in its own region, so a wall reads as open space. Threads that have gone quiet carry an amber or red ring, parked ones are faded. Click a note for its links, a button to open it or its project, and, on a thread, the phrase to say ("open Carrier Choice"). Double-click opens it. It turns slowly when left alone; a hover, a drag, an open panel or your system's reduced-motion setting stops it. *Projects and threads* and *Everything* switch how much it shows.
- **Threads**, one column per zone: every live thread with its project, its party and how long since its note was updated, oldest first. The bar fills toward sixty days and turns amber after two weeks, red after six. Threads you have parked ("park X") sit in a folded *Parked* group at the foot of their zone, out of the counts.
- **Checks**: what `System/tools/check.py` finds, run as the page is built, grouped by check.
- **Open actions**: the unticked items in each zone's `Todo.md`.
- **Inboxes**: what is waiting to be filed in each zone's `Inbox/` and in the Meetings inbox.
- **Scheduled jobs and assistant calls**, when you use the [scheduled jobs](scheduled-jobs.md) extra: a fourteen-day strip per job, one cell per day, and the spend against its caps.
- **Repositories and wikis**: what is not yet committed, and the newest entry in each wiki's log.

![The graph on the demo workspace, with a thread selected](../assets/status-graph.png)

A sidebar holds the overall state, a *problems only* switch that hides everything healthy, and a light, dark or automatic theme. Every section folds. Every card except *Needs attention* can be dragged by the grip in its header to another place on the page, or hidden with its ×; a hidden card is dimmed in the sidebar, and clicking it there brings it back. *Reset view* puts everything back as built and keeps your theme. The page remembers all of this in your browser and nowhere else, so each browser keeps its own.

## What it never does

**It never shows what a note says.** Names, party tags, dates and counts only, the same frontmatter that "what's open" reads. The graph reads one thing more from a note: the targets of its `[[links]]`, which it draws as lines. The words around a link never reach the page. Pass `--no-graph` and the page reads frontmatter alone. The page is the one place that shows every zone at once, and it holds nothing a wall would have to stop.

**It stores nothing.** It reads files the workspace and the jobs extra already keep, and writes only itself. Delete it and nothing is lost.

**It lives in `System/generated/status.html`**, the workspace's folder for pages a tool rebuilds. Two rules keep that folder harmless, and `check.py` holds both. It never enters git history: the root `.gitignore` names it, and the check reports a generated file that is committed, or a `.gitignore` that has lost the line. And it never counts as shared wording. The wall check lets a run of words through when it also appears in material every side reads, such as `System/` or the Knowledge wiki; `System/generated/` is left out of that, so whatever the page repeats can never be copied across a wall unnoticed. You can write the page elsewhere with `--out`; inside the workspace, anywhere but `System/generated/` earns a warning.

## Set it up

1. **Copy `extras/status/` into your workspace as `System/status/`**, next to `System/jobs/` if you have it, and commit it in the workspace root's repository. A workspace installed before this extra existed needs one line added to its root `.gitignore`: `System/generated/`. The check tells you if it is missing.
2. **Build it and open it:**
   ```sh
   python3 System/status/status.py --workspace ~/Garrick --open
   ```
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

The page is a file, and a file cannot act on your workspace, so its buttons copy instead. Hover a thread for *Open* and *Park*, or a parked one for *Wake*: each copies the phrase to say, "open Pricing" or "park Acme Review, Pricing", with the name in the shortest form that is unique, the way the threads skill says it. Paste it to your assistant. The sidebar copies the command that rebuilds the page.

Nothing on the page can change a file, and nothing it copies runs until you paste it somewhere yourself.

## Reading the job strips

Each cell is one day, coloured by how the day *ended*: red when its last run failed or most of its runs did, amber when a run failed and the job recovered, green when every run was clean, grey when nothing ran. A day is not painted red for one failure among many runs; a page that is always red gets ignored as surely as one that is never red. Hover a cell for its runs and their exit codes.

## What you lose without it

Nothing. Every number on the page comes from a file you can open, a command you can run, or a question you can ask: "what's open", `check.py`, `agent.py ledger`. The page puts them in one place, so the first thing you see is what needs you.
