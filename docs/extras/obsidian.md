# Extra: Obsidian

Add it when you want to browse the notes yourself. It works with either the [desktop](../first-steps.md) or [terminal](../terminal-setup.md) route. A terminal assistant plus Obsidian needs no provider desktop app. Obsidian reads the files you open; it does not enforce Garrick's information boundaries.

A Garrick workspace is Markdown files with YAML frontmatter and `[[wikilinks]]` between them, which is exactly what Obsidian is built to read. Nothing in the install writes an `.obsidian/` folder or any Obsidian-specific configuration. The wikilinks are plain text and mean the same thing whether or not Obsidian ever opens the workspace: the assistant follows them, and `System/tools/check.py` resolves them the way Obsidian does when it audits the walls.

## How to use it

Open any folder in the workspace as its own vault, since Obsidian doesn't care about git boundaries. The three natural choices:

- The workspace root, if you want zones, wikis and system files in one browsing surface.
- Just `Wikis/`, if you mainly want to browse Meetings and Knowledge and keep zone work separate.
- A single zone folder, if that's the only side of your work you want visible day to day.

Wikilinks such as `[[wiki/people/dana-whitlock]]` resolve within whichever vault you opened, the same shortest-path rule Obsidian always uses. If you open the root as one vault, a link from a project note into `Wikis/Meetings/wiki/sources/` resolves normally, since it's all one vault as far as Obsidian is concerned. `check.py` resolves links the same way, to catch a project note that links to a meeting a wall should have kept out. It reports a link that leads nowhere only inside a thread's Resume here block, where a broken link is a broken resume point and many people never open Obsidian to see it; everywhere else, Obsidian shows those as unresolved.

## Making the graph readable

At first the graph shows every note as the same grey dot. A few settings make it show your projects and threads instead. They live in the vault's own `.obsidian/` folder, so each vault keeps its own.

- **Colour by level.** In the graph view, open Groups and add these in order, because the first match wins: `[type:project]` for project notes, `[type:thread]` for thread notes, then `path:Zones` for everything else filed in a zone, and `path:Wikis/Meetings` and `path:Wikis/Knowledge` for the two memories. The `path:` groups assume you opened the workspace root; in a vault over one zone, the first two groups are enough.
- **Leave out what is set aside.** Type `-[status:parked] -[status:done]` into the graph's search box to drop parked and finished threads from the picture. They keep their folders and links; Obsidian just stops drawing them. The file explorer has no equivalent setting, so parked threads stay listed there, and the [status page](status-page.md) is where they fold away.
- **Link notes rather than quoting their paths.** Obsidian draws a line only for a `[[wikilink]]`. A path in backticks, such as `` `Sources/brief.md` ``, is plain text to it, so a note your Resume here block names that way shows up unconnected. If you browse in Obsidian, ask your assistant to name notes as wikilinks and keep backticks for files that aren't notes, like spreadsheets and scripts.

Obsidian reads these settings when the vault opens. If you or your assistant change a file in `.obsidian/` while Obsidian is running, reopen the vault. Otherwise the change won't show, and Obsidian may save its own copy over it.

Opening a zone as a vault puts `.obsidian/` inside that zone's git repository. Obsidian rewrites `workspace.json` and `graph.json` all the time, even when you only pan or zoom, so add both to the zone's `.gitignore` if you don't want that churn in its history.

## What it adds

A graph and backlink view of how your projects, threads, people and meeting pages connect. A mobile app for reading and light editing when you're away from a terminal. Faster browsing than opening files one at a time in a plain editor.

## What you lose without it

Nothing structural. Any text editor, or an IDE, or `cat`, reads and writes the exact same files. The wikilinks are still just text, `check.py` still reads them for the wall audit, and the assistant still resolves them when following one. Obsidian is a nicer way to look at the workspace, not a part of what makes it work.
