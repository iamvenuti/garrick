# {{ZONE}} zone

Part of the workspace above. Before anything else, read `../../AGENTS.md`, `../../System/rules.md` and `../../System/context.md`: an assistant started in this folder may not load them on its own. This zone is its own git repository: a commit never spans it and another zone.

## Structure

Three levels, always. Start a project or a thread by asking the assistant, or with `python3 ../../System/tools/scaffold.py project --zone {{ZONE}} --name <Project> --party <tag> --thread <Thread>` and `python3 ../../System/tools/scaffold.py thread --zone {{ZONE}} --project <Project> --name <Thread>`. Do not copy folders by hand: the script checks the name and the party.

    {{ZONE}}/
      Todo.md                 the only list of open actions in this zone
      Inbox/                  mail and files waiting to be sorted; never a project
      <Project>/
        <Project>.md          hub note: what it is, who it is for, its threads
        Sources/              material received
        Deliverables/         what is made for the project, `YYMMDD - <name>.<ext>`
        Threads/
          <Thread>/
            <Thread>.md       thread note, with the resume point
            (working notes for this thread)

Every piece of work belongs to a thread, even when a project has only one. That keeps one kind of resume point in one kind of place.

## Parties

A project hub names its `party` in the frontmatter, as a tag from the Parties table in `System/context.md`. That tag is what the walls are checked against, so a project without one cannot draw on the Meetings wiki until it has one.

## Inbox

Drop anything for this zone into `Inbox/`: mail as a `.eml` file (or saved as `.txt` or `.md`), a document, a data file, an article. A script or your assistant's mail connector may put mail there too. Say "process the inbox" and the `intake` skill moves each item out, to where the *Ways in* rules in `System/rules.md` send it. `Inbox/` is left out of this zone's history.
