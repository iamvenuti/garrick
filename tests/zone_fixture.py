"""The fixture workspace of the zone wall cases (walls/cases.md): invented names only.

`Work` and `Home` are walled zones, `Ventures` an open one. Northwind (hub `acme`) and Harbour (hub `birch`) are
projects of Work, Garden of Home, Orchard of Ventures. Each zone has a Meetings page of its own, with its own
`zone:`; no folder is named after a party. The Zones table has the Walled column, so the context is not pending.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True

from fixtures import meeting_page, project_hub, thread_note, write  # noqa: E402

CONTEXT = """\
# Context

## Me

Jo Example. Independent advisor.

## Zones

| Zone | Holds | Walled |
|---|---|---|
| Work | Client work | yes |
| Home | Everything else | yes |
| Ventures | Published work | no |

## Parties

| Party | What it is | Zone | Tag | Domains | Learned |
|---|---|---|---|---|---|
| Acme Corp | Client. Supply-chain review | Work | `acme` | acmecorp.example | |
| Birch & Co | Client. Market-entry advice | Work | `birch` | birchco.example | |
| Own affairs | Personal matters | Home | `jo` | | |
| Cedar Ltd | Own venture | Ventures | `cedar` | | |

## People

| Name | Party | Role |
|---|---|---|
| Dana Whitlock | `acme` | Head of procurement |
| Theo Marsh | `birch` | Managing partner |

## Aliases

| Heard | Means |
|---|---|
| dana whitlaw | Dana Whitlock |
"""

HOME_SAYS = "The cedar fence replacement is scheduled for the second week of March after the frost breaks."
UNZONED_SAYS = "The northern depot lease transfer requires board approval before the end of the quarter."
PLAN = "Garden plan: the beds go along the south wall, spaced a metre apart, with a path between.\n"


def cite(stem: str) -> str:
    return 'transcript: "[[raw/%s]]"\npeople:' % stem


def build(root: Path) -> Path:
    root = Path(root)
    write(root / "AGENTS.md", "# Workspace\n")
    write(root / "System" / "rules.md", "# Rules\n")
    write(root / "System" / "context.md", CONTEXT)
    for zone in ("Work", "Home", "Ventures"):
        z = root / "Zones" / zone
        write(z / "AGENTS.md", "# %s zone\n" % zone)
        write(z / "Todo.md", "# %s: open actions\n\n## Inbox\n\n## Done\n" % zone)
        write(z / "Inbox" / ".gitkeep")
    for zone, project, party, thread in (("Work", "Northwind", "acme", "Pricing"), ("Work", "Harbour", "birch", "Sizing"),
                                         ("Home", "Garden", "jo", "Beds"), ("Ventures", "Orchard", "cedar", "Drafts")):
        base = root / "Zones" / zone / project
        write(base / (project + ".md"), project_hub(zone, project, party, [thread]))
        write(base / "Threads" / thread / (thread + ".md"), thread_note(project, thread, party))
        write(base / "Threads" / thread / "Notes.md", "# Notes\n\nPlain notes of %s.\n" % project)
    write(root / "Zones" / "Home" / "Garden" / "Threads" / "Beds" / "Plan.md", PLAN)
    write(root / "Zones" / "Ventures" / "Orchard" / "Threads" / "Drafts" / "Plan.md", "Orchard plan: the trees go in rows, one row for each variety.\n")
    write(root / "Zones" / "Work" / "Harbour" / "Threads" / "Sizing" / "Plan.md", "Harbour plan: the quay works come first, then the sheds.\n")

    write(root / "System" / "templates" / "zone" / "Todo.md", "# {{ZONE}}: open actions\n\n## Inbox\n\n## Done\n")
    meetings = root / "Wikis" / "Meetings"
    write(meetings / "AGENTS.md", "# Meetings\n")
    write(meetings / "wiki" / "index.md", "# Index\n")
    sources = meetings / "wiki" / "sources"
    write(sources / "260310-work-call.md", meeting_page("Work", "[acme]", "Work call").replace("people:", cite("260310-work-call")))
    write(sources / "260311-home-call.md", meeting_page("Home", "[jo]", "Home call").replace("people:", cite("260311-home-call")).replace("Decisions.", HOME_SAYS))
    write(sources / "260312-ventures-call.md", meeting_page("Ventures", "[cedar]", "Ventures call").replace("people:", cite("260312-ventures-call")))
    write(meetings / "raw" / "260312-ventures-call.txt", "Cedar: the stall opens on Saturday, and the first crates arrive at six.\n")
    write(sources / "260313-unzoned-call.md", meeting_page(None, "[acme]", "Unzoned call").replace("Decisions.", UNZONED_SAYS))
    write(sources / "260314-two-zones-call.md", meeting_page("[Work, Home]", "[acme]", "Two zones call"))
    write(sources / "260315-both-a.md", meeting_page("Work", "[acme]", "Both A").replace("people:", cite("260315-both-call")))
    write(sources / "260315-both-b.md", meeting_page("Home", "[jo]", "Both B").replace("people:", cite("260315-both-call")))
    write(meetings / "raw" / "260310-work-call.txt", "Dana: we start Monday at the depot, and the crew meets at seven.\n")
    write(meetings / "raw" / "260311-home-call.txt", "Jo: the beds are marked.\n")
    write(meetings / "raw" / "260315-both-call.txt", "Both: one recording.\n")
    write(meetings / "raw" / "260319-orphan-call.txt", "Nobody cites this.\n")
    people = meetings / "wiki" / "people"
    write(people / "dana-whitlock.md", "---\ntitle: Dana Whitlock\ntype: person\nzone: Work\nparty: acme\n---\n\n# Dana Whitlock\n")
    write(people / "jo-lane.md", "---\ntitle: Jo Lane\ntype: person\nzone: Home\nparty: jo\n---\n\n# Jo Lane\n")
    ents = meetings / "wiki" / "entities"
    write(ents / "acme-corp.md", "---\ntitle: Acme Corp\ntype: entity\nzone: Work\nparty: acme\n---\n\n# Acme Corp\n\nSee [[260310-work-call]].\n")
    write(ents / "mixed.md", "---\ntitle: Mixed\ntype: entity\n---\n\n# Mixed\n\nSee [[260310-work-call]] and [[260311-home-call]].\n")
    write(ents / "mixed-open.md", "---\ntitle: Mixed open\ntype: entity\nzone: Work\n---\n\n# Mixed open\n\nSee [[260310-work-call]] and [[260312-ventures-call]].\n")
    write(ents / "open-and-walled.md", "---\ntitle: Open and walled\ntype: entity\n---\n\n# Open and walled\n\nSee [[260310-work-call]] and [[260312-ventures-call]].\n")
    write(ents / "whole.md", "---\ntitle: Whole\ntype: entity\nzone: Work\n---\n\n# Whole\n\nSee [[260310-work-call]].\n")
    write(ents / "bare.md", "---\ntitle: Bare\ntype: entity\n---\n\n# Bare\n")
    write(ents / "party-only.md", "---\ntitle: Party only\ntype: entity\nparty: jo\n---\n\n# Party only\n")
    write(people / "pat.md", "---\ntitle: Pat\ntype: person\nparty: jo\n---\n\n# Pat\n")
    write(meetings / "raw" / "inbox" / ".gitkeep")

    knowledge = root / "Wikis" / "Knowledge"
    write(knowledge / "AGENTS.md", "# Knowledge\n")
    write(knowledge / "wiki" / "index.md", "# Index\n")
    write(knowledge / "wiki" / "concepts" / "resilience.md", "# Resilience\n")
    return root
