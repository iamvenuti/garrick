# Extra: a status page

One page that answers two questions before you open anything: is anything wrong, and where was I? It is a single HTML file you open in a browser. It needs no server, no account and no network, and it works whether or not you use Obsidian.

## What it shows

- **Threads**, one column per zone: every live thread with its project, its party and how long since its note was updated, oldest first. The bar fills toward sixty days and turns amber after two weeks, red after six.
- **Checks**: what `System/tools/check.py` finds, run as the page is built, grouped by check.
- **Open actions**: the unticked items in each zone's `Todo.md`.
- **Inboxes**: what is waiting to be filed in each zone's `Inbox/` and in the Meetings inbox.
- **Scheduled jobs and assistant calls**, when you use the [scheduled jobs](scheduled-jobs.md) extra: a fourteen-day strip per job, one cell per day, and the spend against its caps.
- **Repositories and wikis**: what is not yet committed, and the newest entry in each wiki's log.

A sidebar holds the overall state, a *problems only* switch that hides everything healthy, and a light, dark or automatic theme. Every section folds, and the page remembers which ones you folded. That preference is kept in your browser and nowhere else.

## What it never does

**It never shows what a note says.** Names, party tags, dates and counts only, the same frontmatter that "what's open" reads. The page is the one place that shows every zone at once, and it holds nothing a wall would have to stop.

**It stores nothing.** It reads files the workspace and the jobs extra already keep, and writes only itself. Delete it and nothing is lost.

**It lives outside the workspace**, beside the job logs: `~/Library/Logs/garrick-jobs/status.html` on a Mac, `~/.local/state/garrick-jobs/status.html` elsewhere, or wherever `GARRICK_JOBS_DIR` points. So it is never committed with a zone, never synced with one, and never part of the shared material the wall check compares against. You can write it somewhere else with `--out`, but keep it out of every repository.

## Set it up

1. **Copy `extras/status/` into your workspace as `System/status/`**, next to `System/jobs/` if you have it, and commit it in the workspace root's repository.
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

## Reading the job strips

Each cell is one day, coloured by how the day *ended*: red when its last run failed or most of its runs did, amber when a run failed and the job recovered, green when every run was clean, grey when nothing ran. A day is not painted red for one failure among many runs; a page that is always red gets ignored as surely as one that is never red. Hover a cell for its runs and their exit codes.

## What you lose without it

Nothing. Every number on the page comes from a file you can open, a command you can run, or a question you can ask: "what's open", `check.py`, `agent.py ledger`. The page puts them in one place, so the first thing you see is what needs you.
