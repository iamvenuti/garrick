# Wikis

The workspace's two memories. Before anything else, read `../AGENTS.md`, `../System/rules.md` and `../System/context.md`: an assistant started in this folder may not load them on its own. Then the workspace's own additions, where they exist: `../AGENTS.local.md`, `../System/rules.local.md` and `AGENTS.local.md` here. Each adds to the Garrick file it sits beside and wins where the two differ. This folder is its own git repository.

- `Meetings/`: every conversation, from every zone. Its `AGENTS.md` is the schema.
- `Knowledge/`: published material. Its `AGENTS.md` is the schema.

Nothing is copied between the two. A conversation never goes into Knowledge, where the walls cannot see it.

A page name both wikis hold, such as `wiki/people/<name>`, resolves to either one in Obsidian. Link it from outside its own wiki with the wiki's name in front: `[[Meetings/wiki/people/<name>]]`.
