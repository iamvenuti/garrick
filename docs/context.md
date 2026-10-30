# How Garrick keeps context

What the assistant knows about your work is spread over many places in Garrick: the wikis, the thread notes, `System/context.md`, each zone's `Todo.md` and the assistant's own memory. This page shows how they fit together, in four stages. Each stage says what happens, which file or tool does it, and where the detail is. It repeats none of that detail.

![Context is all you need. Articles and reports are ingested into Knowledge, a graph of what you read, linked by topic. Recordings and mail are ingested into Meetings, a graph of what was said, linked by who and what. Your files sit in a folder tree, what you're working on by subject: Work and Personal, projects inside, sources and deliverables inside a project. Your assistant draws on all three and starts already set up. Two graphs and a tree, so you never set up the same context twice.](assets/two-graphs-and-a-tree.png)

The content itself sits in two graphs and a tree. The two wikis are the graphs: what comes in is ingested into them, and their pages link to one another by topic, person and organisation. Your zones are the tree: folders by subject, a project inside a zone and a piece of work inside a project. The rest of this page is how the three are filled, kept true, used and let go.

All four stages work under one rule: [one memory, walled use](principles.md#one-memory-walled-use). Every conversation is kept in one place, so you can find your own record. The walls apply where material is *used*, not where it is stored. The zones, the parties and the declared walls in `System/context.md` are what each stage reads. They are not a stage of their own.

| Stage | What it does | What does it |
|---|---|---|
| [Take in](#take-in) | Everything lands in an inbox and is filed by who it came from | The inboxes, the `intake` skill, the two wikis' `raw/` folders, the Parties table |
| [Keep true](#keep-true) | What the workspace holds stays correct, and says where it came from | Learned entries and their origin, `correct.py`, `check.py`, `wiki_lint.py`, `drift.py`, Nurture, the wrap |
| [Use within walls](#use-within-walls) | The right context reaches the task, and a confidence stays on its own side | The Resume here block, question routing, briefs, the wall check at use and at commit |
| [Let fade](#let-fade) | What nobody uses steps back, and can be brought back | The todo sweep's archive, park and finish, memory pointers deleted with their thread, and graded oblivion in the wikis, `fade.py` |

## Take in

Recordings, mail and files you drop in all arrive in an inbox first. A recording's transcript goes to `Wikis/Meetings/raw/inbox/`, and mail and any other file go to a zone's `Inbox/`. Getting an item there is fetching, by hand, by a script or by your assistant's mail connector, and fetching decides nothing. Nothing waiting in an inbox can be committed: the pre-commit hook refuses it.

"Process the inbox" starts the [`intake`](concepts.md#intake) skill, which files each item by the [Ways in](../template/System/rules.md#ways-in) rules. A conversation goes to the Meetings wiki, with its zone and parties. Something to read goes to the Knowledge wiki, with no parties. Material for a project goes into that project's `Sources/`, after the wall between the project's party and the material's parties has been checked. The parties come from the mail addresses, through the domains in the Parties table. Personal webmail never names a party, and when the addresses do not settle it, the assistant asks.

Each wiki keeps the item as it arrived in [`raw/`](concepts.md#raw), and writes its pages in `wiki/`. A raw record is never edited. Everything later rests on it, a correction included.

Detail: [Material coming in](architecture.md#material-coming-in), [The two memories](commands.md#the-two-memories), [Filing incoming material](principles.md#filing-incoming-material), [Ways in](extras/ways-in.md).

## Keep true

What one session writes down, a later one reads as fact. So what the workspace holds has to stay correct, and has to say where it came from.

- **Origin.** A [learned entry](concepts.md#learned-entry), an entry in the assistant's own memory or a row it added to `System/context.md`, says where it came from: `user`, a note, or an inbound mail, transcript or page. What the assistant may write down without asking depends on what acting on it would do. A pointer or an alias goes ahead. A domain, a person's party or a destination waits for your yes. Something only a mail or a page said is never kept until you confirm it. `check.py` warns about an entry with no origin, and about one whose only source is inbound.
- **Correction.** "That's wrong, it's Y" runs `correct.py`, which lists every live copy of the wrong value and fixes them all on one yes. Live files then show only the new value, and git keeps the old one. A wiki page resting on a raw record that holds the old value is marked `superseded:`. See [Correction](concepts.md#correction).
- **Checks.** `check.py` tests the workspace against every rule a machine can check, `wiki_lint.py` finds orphan pages and broken links in a wiki, and `drift.py` compares a published deliverable with its shared copy. All three report and change nothing.
- **Nurture.** "Nurture the context" gathers what those three find for a scope and sorts it by what a fix needs. Mechanical fixes, such as a link broken by a rename, are applied on one yes. Attribution is asked one line at a time. A wall finding names the file and the wall, never the material. Judgment is reported with the page to open. "Review the context with me" works through what is left in a short session, and keeps a record so the next one goes on where it stopped. See [Nurturing the context](commands.md#nurturing-the-context).
- **The wrap.** "Wrap it" rewrites a thread's [Resume here](concepts.md#resume-here) block so it describes now, and adds a dated entry below it. `check.py` warns when a link or path in a live block leads nowhere.

## Use within walls

This stage gets the right part of the record to the task in front of you, and keeps each confidence on its own side.

- **Picking a thread back up.** "Open X" reads that thread's Resume here block and answers in two sentences: where it stands, and the next action. That block is the one thing a cold resume needs to read first. See [One resume point per thread](principles.md#one-resume-point-per-thread).
- **Questions go by subject.** "What did they say" goes to the Meetings wiki, "what does the research say" to the Knowledge wiki, "what do I owe them" to the zone's `Todo.md`, and "where am I on X" to the thread. A question that could belong to two zones is asked about. See [Where a question goes](../template/AGENTS.md#where-a-question-goes).
- **Briefs.** "Prep me for Acme" puts a brief together from the Meetings wiki. "What does my library say about X" answers from the Knowledge wiki.
- **The assistant's own memory holds pointers.** Where your assistant keeps a memory of its own, Garrick keeps one entry per live or parked thread there, naming where its resume point is and nothing else. The note stays the record, so there is no second account of where a thread stands to go stale. See [Threads](../template/System/rules.md#threads) in the rules.
- **The walls, at use.** Before material from a meeting goes into a project, the assistant compares the project's party with the meeting's parties against the Walls table. Walled material stays out, paraphrase and summary included, and the assistant says only that something was held back. This is a rule the assistant follows, not code. The Knowledge wiki crosses every wall, since what it holds is published.
- **The walls, at commit.** The pre-commit hook in each zone refuses a project file that links to a walled meeting, names a party from across the wall, or repeats eight words held only on the far side. It has known gaps: a clean paraphrase passes, and a chat reply or a mail sent is outside what it sees. See [What the check covers](principles.md#what-the-check-covers) and [What is enforced, and what is asked](enforced.md).

## Let fade

What nobody uses any more should stop getting in the way, without being lost. Nothing in this stage deletes anything: what steps back can be brought back, and git keeps it all.

- **Actions.** A line ticked before today moves from the zone's `Todo.md` to its `archive/`, at every wrap and at the nightly sweep. A line nobody triaged moves to the expired archive after `todo-expire-days`, 14 unless the [check settings](commands.md#check-settings) say otherwise.
- **Threads.** "Park X" sets a thread aside. It keeps its note and its Resume here block, drops out of "what's open", and comes back with "wake X". "Finish X" marks it `done`, turns its block into an outcome and lists it under the hub's `## Finished`. See [Status](concepts.md#status).
- **Memory.** The assistant's pointer to a thread is deleted when the thread finishes.
- **The wikis: graded oblivion** ([#108](https://github.com/iamvenuti/garrick/issues/108)). Old meetings and reading fade out of working memory by age, kind and use. A page moves from working to dormant to archived, in folders inside its own wiki, its raw record with it, and every link into it follows. Both leave the index and Obsidian's default search. A question reaches dormant pages only when working pages fall short, and says so; archived ones are read when you ask. A page a live thread, a live project or an open action links, or one marked `pinned: true`, never fades, and a dormant page linked again comes back unless it is marked `superseded:`. The wall check still reads every page. "Fade the meetings" writes the list and moves nothing; on a wiki's first fade it stops there, and a later yes moves exactly that list. Nothing fades overnight. See [Fading](commands.md#fading).

## What runs on its own, and what waits for you

Core Garrick runs nothing on a schedule. The pre-commit hook runs on every commit, refuses what it is built to refuse, and lets the rest through. With the [scheduled jobs](extras/scheduled-jobs.md) extra, two sweeps also run each night: the todo sweep, and [Nurture's mechanical fixes](extras/scheduled-jobs.md#nurturing-the-context-each-night), each committing only the files it changed, named one by one.

Everything else waits for you: anything that would cross a wall, a domain, party or destination to be remembered, anything whose only source is a mail, a transcript or a page, a correction, an attribution, a judgment, and anything that leaves the machine. See [Autonomy](../template/System/rules.md#autonomy) in the rules, and [What an unattended assistant may do](extras/scheduled-jobs.md#what-an-unattended-assistant-may-do).
