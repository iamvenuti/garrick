# Extra: Obsidian

Add it when you want to browse the notes yourself. It works with either the [desktop](../first-steps.md) or [terminal](../terminal-setup.md) route. A terminal assistant plus Obsidian needs no provider desktop app. Obsidian reads the files you open; it does not enforce Garrick's information boundaries.

A Garrick workspace is Markdown files with YAML frontmatter and `[[wikilinks]]` between them, which is exactly what Obsidian is built to read. Nothing in the install writes an `.obsidian/` folder or any Obsidian-specific configuration. The wikilinks are plain text and mean the same thing whether or not Obsidian ever opens the workspace: the assistant follows them, and `System/tools/check.py` resolves them the way Obsidian does when it audits the walls.

## How to use it

Open any folder in the workspace as its own vault, since Obsidian doesn't care about git boundaries. The three natural choices:

- The workspace root, if you want zones, wikis and system files in one browsing surface.
- Just `Wikis/`, if you mainly want to browse Meetings and Knowledge and keep zone work separate.
- A single zone folder, if that's the only side of your work you want visible day to day.

Wikilinks such as `[[wiki/people/dana-whitlock]]` resolve within whichever vault you opened, the same shortest-path rule Obsidian always uses. If you open the root as one vault, a link from a project note into `Wikis/Meetings/wiki/sources/` resolves normally, since it's all one vault as far as Obsidian is concerned. `check.py` resolves links the same way, to catch a project note that links to a meeting a wall should have kept out. It reports a link that leads nowhere only inside a thread's Resume here block, where a broken link is a broken resume point and many people never open Obsidian to see it; everywhere else, Obsidian shows those as unresolved.

## What it adds

A graph and backlink view of how your projects, threads, people and meeting pages connect. A mobile app for reading and light editing when you're away from a terminal. Faster browsing than opening files one at a time in a plain editor.

## What you lose without it

Nothing structural. Any text editor, or an IDE, or `cat`, reads and writes the exact same files. The wikilinks are still just text, `check.py` still reads them for the wall audit, and the assistant still resolves them when following one. Obsidian is a nicer way to look at the workspace, not a part of what makes it work.
