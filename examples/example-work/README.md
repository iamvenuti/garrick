# The worked example

One person's ordinary work, for a first look at Garrick: one employer, five pieces of work across marketing, sales and customers, two call transcripts, and one question Garrick is waiting on. It is the example a new workspace can start with, and it is removed in one step when you are done. Every name in it is invented.

The advisor demo in [`../demo/`](../demo/README.md) is the other one: two clients who compete, and a wall between them. Try that one once you have a second party of your own.

## The world

**Quillfield Furniture** (`quillfield`, `quillfield.example`) makes office furniture and sells it to businesses, universities and hotels, mostly through dealers. **Robin Hale** is its product marketing manager, and the person whose work this is: you stand in for Robin.

| Person | Role |
|---|---|
| Robin Hale | Product marketing manager |
| Ines Calder | Designer of the Kestle chair; brand and product photography |
| Leo Brandt | Sales lead for education |
| Nadia Fenn | Finance; owns pricing and dealer margins |
| Tom Ashby | Customer service and deliveries |
| Carla Mendes | Facilities manager at Brannock Hotels, a customer |

One employer, one confidence: every piece of work carries `quillfield`, and there is no wall. Brannock Hotels and Ellisford University are customers, not parties.

## The five pieces of work

Each is a project with one thread, most recent first.

| Piece of work | Thread | Where it stands |
|---|---|---|
| Kestle chair launch | Launch campaign | The launch email was half written yesterday and stops before its pricing section. One owed: the draft to Leo and Ines, due Friday |
| Brannock delivery problem | Replacement desks | Forty damaged desks. In the call with Carla, Tom said one date and Robin another, so the one question in Needs you asks which was promised |
| Ellisford University tender | Pitch | After the prep call with Leo, the sustainability page of the deck is Robin's to write |
| Dealer price list (next year's) | New prices | Waiting on Nadia to sign off the margins; the launch email's pricing waits on it too |
| Spring trade show | Stand | Booked, and quiet for three weeks |

The question is a file in the Brannock thread, `Threads/Replacement desks/Needs you/<YYMMDD> - brannock-date.md`, with two answers, each the next action it leads to. The to-do list holds four owed lines, three of them dated this week.

## Where its files are

Robin's files are in a shared drive, `Quillfield Shared/`, in the workspace's top folder: outside every zone and wiki, read and never written, and never committed (the workspace's `.gitignore` keeps it out). Each project's hub points at its folder there with `folder:`. The drive is messier than the work: `Misc`, `Old - do not use`, a `Brand assets` folder that belongs to no piece of work, and `Dealer one-pager Final_v3.docx` beside `Final_v3 (1).docx`. The two transcripts are in it too, as a download leaves them, and the Meetings and Knowledge wikis stay empty.

It sits inside the workspace rather than beside it so that a session opened there reads it without asking for a folder outside, and so the example comes and goes as one.

## Sealed and removable

The example is a zone of its own, **Example**, with its own repository, so nothing of yours links into it. Its party and people go into `System/context.md` with Example as their zone. Then:

    python3 System/tools/example.py status
    python3 System/tools/example.py archive
    python3 System/tools/example.py restore

`archive` moves the zone, the drive and those rows into `.archive/Example/`, which no repository commits, and `restore` puts each back exactly where it was. Neither touches your own zones, rows or files. Nothing made in the example carries over into your own work.

## Build it

    python3 examples/example-work/build.py --target ~/Garrick-example

builds a new workspace with the example in it, and

    python3 install.py --example

adds it to a workspace as it is installed. For a workspace you already have, `python3 examples/example-work/build.py --add ~/Garrick` adds it there, once the workspace is on this Garrick. `--today YYYY-MM-DD` builds it as if on another day.

When it is built, `python3 System/tools/check.py` inside the workspace reports no problems.

## Dates are relative

"Yesterday" has to be true on first open, so every date comes from the day the example is built: Robin's last session is the previous working day, the call with Carla two working days before that, and the prep call with Leo a week before it. The zone's history is a month of dated commits leading up to yesterday, and each file in the drive carries the date it was last saved. Next year's price list is named for next year. So two builds on different days differ, and the tests check structure and wording, never commit hashes.

## Files

| Path | Holds |
|---|---|
| `example.json` | The zone, the drive, the party and the people |
| `config.json` | The installer's answers for a workspace of Robin's own, for `--target` |
| `content/Zones/Example/` | The zone's notes as they stand at the end, with `{name}` for each date |
| `drive/Quillfield Shared/` | The drive's files. A `.docx.txt`, `.pdf.txt` or `.png.txt` is made into that kind of file |
| `build.py` | Lays the drive down, makes the zone with the workspace's own scaffold script, and replays the month in `PLAN` |

To change the story, edit the files and the `PLAN` list at the top of `build.py`. A `{name}` the build does not fill stops it with an error; `fields()` in `build.py` lists the names. Then run `python3 -m unittest discover -s tests -p test_example.py`.
