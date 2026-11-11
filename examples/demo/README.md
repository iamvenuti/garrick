# The demo workspace

A made-up advisor's workspace, about four weeks into real use. The 54-second walkthrough that Garrick's README links to is recorded on it. `video-script.md` is the shot list for a separate, longer demo on this workspace: three minutes, by voice. It's also what you open at the start of a guided session when there's nothing of the client's in the workspace yet. Every name in it is invented.

## The world

Sam Rivera is an independent advisor with three zones, Work, Birch and Personal. Each is walled: what is in one stays in it. Acme sits in Work and Birch in a zone of its own, because the two compete.

- **Acme Corp** (`acme`) hired Sam for a supply-chain review. Dana Whitlock sponsors it; Owen Pike runs logistics. Hana Croft runs the pump line, Gil Thorne is the financial controller and Felix Rook approves new suppliers. Project *Acme Review*, with threads *Supplier Map* and *Freight Terms*.
- **Birch & Co** (`birch`) hired Sam for advice on entering the Nordics. Theo Marsh decides; Iris Bell runs the work, with Lena Moss in finance, Arno Vale in operations and Ruth Kemp in export sales. Project *Birch Entry*, in the Birch zone, with threads *Carrier Choice*, *Launch Plan*, and *Market Sizing*, which is finished. Birch competes with Acme, so a wall stands between `acme` and `birch`.
- **Cobalt Freight** (`cobalt`) is a carrier that deals with both clients, separately. Marta Quill handles both accounts. Sam met her once for Acme (15 September as written, a contract renewal) and once for Birch (22 September, a new northern lane). That pair of calls is what the demo turns on.
- **Lark & Sons** (`lark`) is Sam's builder: Ray Lark, and his son Ned, the electrician. Project *House* in Personal, with threads *Kitchen* and *Roof Repair*. **Pell Joinery** (`pell`) gave the other kitchen quote, and **Wrenfield Mutual** (`wrenfield`) insures the house.

The Meetings wiki holds twenty-one filed calls from the month: eight with Acme and eight with Birch, the two Cobalt calls among them, and five on the Personal side, with the builder, the joiner and the insurer. Each has its date, zone, parties, the people in it and an actions table, and each person has a page that says who they are and nothing they said. One more, Theo's call on the month's last day, is waiting unprocessed in `Wikis/Meetings/raw/inbox/`. Four mails from the same day wait in the Work zone's `Inbox/`: The Freight Ledger's weekly newsletter, which goes to the library; Dana's pallet forecast, which files itself under Acme by its domain; Owen's second seal-kit quote, whose attached sheet goes into Acme Review's sources while the mail itself is filed under Acme; and a Cobalt notice that copies both Acme and Birch, so the assistant has to ask. The Knowledge wiki holds nine invented published sources: an analyst note on freight rates, trade statistics on the Nordic pump market, a practice guide on second sources, a law firm's briefing on distribution agreements, a vendor white paper, two trade press articles and two magazine pieces for the house, with the eleven concept and nine entity pages they touch. In the zones, threads keep working notes beside their thread notes, and projects keep dated deliverables and the files they were sent. Each zone's `Todo.md` holds the month's actions, open and done, each naming its thread, or its party when it has none.

## The moment it exists for

"Prep me for Cobalt", asked while a Birch thread is open, has to brief from the Birch-side call and leave the Acme-side call out entirely, saying only that a wall kept something back. No file of the Birch zone links to, embeds or copies the Acme call. `check.py` catches a Birch file that links a Meetings page of the Work zone, or a file of it, or copies a file whole, and the Birch zone's pre-commit hook refuses to commit it. A name typed by hand is not caught. `tests/test_demo.py` checks that the link is caught, by the check and by the hook.

## Build it

    python3 examples/demo/build.py --target ~/Garrick-demo

The script installs a fresh workspace from `config.json` with the real installer, then replays the month on top of it, one dated commit at a time. Projects and threads come from the workspace's own scaffold script, and the finished files come from `content/`, which mirrors the workspace tree. Every zone ends up with a history that reads like the wraps and ingests that made it. The target has to be empty or new. Two builds from the same repository on the same day produce the same files and the same commit hashes. The last transcript is left in the inbox, uncommitted, the way a recorder leaves it, and the four mails sit in the Work zone's `Inbox/`, which is never committed.

When the build finishes, `python3 System/tools/check.py` inside the workspace reports no problems.

The build ends by building the status page of the finished workspace, `System/generated/status.html` in the target, which is the page the Garrick app opens on that folder. It shows the demo's live threads and actions and the waiting transcript and mails. It is built with an empty jobs folder and no assistant sessions, so nothing of the machine the demo was built on, no scheduled job and no open session, appears on it.

### Its dates

`content/` and the plan are written as September 2026: installed on Tuesday 1 September, the last commit on Saturday 26 September, Theo's call and the mails on Monday 28 September. The build moves all of it forward by whole weeks, so the 28th lands on the day you build or in the six days before it, and an assistant opened on the demo reads it as last week's work, not as work abandoned a month ago. Whole weeks keep each weekday true: Friday 2 October becomes another Friday. Every date of the story moves, in whatever form it is written, file names and links included. What is background stays as written: dates before September 2026, month names outside the story, years in titles, and the seasons, so the story reads best built in the autumn. To build as if on another day, for a recording planned for tomorrow, add `--today YYYY-MM-DD`. The dates in this README are the ones `content/` is written with.

## Files

| Path | Holds |
|---|---|
| `config.json` | The installer's answers for Sam: zones, parties, people, aliases |
| `content/` | The workspace's files as they stand at the end of the month (written as 26 September 2026), plus the transcript and the four mails waiting to be filed |
| `build.py` | Installs, lays `content/` down in dated commits, and leaves the inbox files |
| `video-script.md` | The shot list for the three-minute voice demo, and how to capture it |

To change the story, edit the files in `content/` and the `PLAN` list at the top of `build.py`, which says what each commit adds and on what date, all as September 2026; the build moves them. A file in `content/` is its finished form. The wiki indexes, logs, concept and entity pages, and any file the plan names more than once, such as a hub note, are written at each step as far as the month has got: a list line that links to a page not written yet waits until that page exists, and `updated:` moves only when the page does. The build stops with an error if a file in `content/` isn't committed as written, or if a commit leaves something behind. Then run `python3 -m unittest discover -s tests`.
