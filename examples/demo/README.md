# The demo workspace

A made-up advisor's workspace, about four weeks into real use. We film the three-minute demo on it, and it's what you open at the start of a guided session when there's nothing of the client's in the workspace yet. Every name in it is invented.

## The world

Sam Rivera is an independent advisor with two zones, Work and Personal.

- **Acme Corp** (`acme`) hired Sam for a supply-chain review. Dana Whitlock sponsors it; Owen Pike runs logistics. Project *Acme Review*, with threads *Supplier Map* and *Freight Terms*.
- **Birch & Co** (`birch`) hired Sam for advice on entering the Nordics. Theo Marsh decides; Iris Bell runs the work. Project *Birch Entry*, with threads *Carrier Choice*, *Launch Plan*, and *Market Sizing*, which is finished. Birch competes with Acme, so a wall stands between `acme` and `birch`.
- **Cobalt Freight** (`cobalt`) is a carrier that deals with both clients, separately. Marta Quill handles both accounts. Sam met her once for Acme (15 September, a contract renewal) and once for Birch (22 September, a new northern lane). That pair of calls is what the demo turns on.
- **Lark & Sons** (`lark`) is Sam's builder. Project *House* in Personal, with threads *Kitchen* and *Roof Repair*.

The Meetings wiki holds seven filed calls from September, one of them a Personal call with the builder. An eighth, Theo's call on 28 September, is waiting unprocessed in `Wikis/Meetings/raw/inbox/`. Four mails from the same day wait in the Work zone's `Inbox/`: The Freight Ledger's weekly newsletter, which goes to the library; Dana's pallet forecast, which files itself under Acme by its domain; Owen's second seal-kit quote, whose attached sheet goes into Acme Review's sources while the mail itself is filed under Acme; and a Cobalt notice that copies both Acme and Birch, so the assistant has to ask. The Knowledge wiki holds three invented published sources: an analyst note on freight rates, a vendor white paper, and a trade press article, with their concept and entity pages.

## The moment it exists for

"Prep me for Cobalt", asked while a Birch thread is open, has to brief from the Birch-side call and leave the Acme-side call out entirely, saying only that a wall kept something back. No Birch file links, names or quotes the Acme call. If one ever did, `check.py` would fail and the Work zone's pre-commit hook would refuse the commit, and `tests/test_demo.py` checks both.

## Build it

    python3 examples/demo/build.py --target ~/Garrick-demo

The script installs a fresh workspace from `config.json` with the real installer, then replays September on top of it, one dated commit at a time. Projects and threads come from the workspace's own scaffold script, and the finished files come from `content/`, which mirrors the workspace tree. Every zone ends up with a history that reads like the wraps and ingests that made it. The target has to be empty or new. Two builds from the same repository produce the same files and the same commit hashes. The last transcript is left in the inbox, uncommitted, the way a recorder leaves it, and the four mails sit in the Work zone's `Inbox/`, which is never committed.

When the build finishes, `python3 System/tools/check.py` inside the workspace reports no problems.

## Files

| Path | Holds |
|---|---|
| `config.json` | The installer's answers for Sam: zones, parties, the wall, people, aliases |
| `content/` | The workspace's files as they stand on 26 September, plus the transcript and the four mails waiting to be filed |
| `build.py` | Installs, lays `content/` down in dated commits, and leaves the inbox files |
| `video-script.md` | The shot list for the three-minute voice demo, and how to capture it |

To change the story, edit the files in `content/` and the `PLAN` list at the top of `build.py`, which says what each commit adds and on what date. The build stops with an error if a file in `content/` isn't committed as written, or if a commit leaves something behind. Then run `python3 -m unittest discover -s tests`.
