"""A workspace as Garrick 0.59 left it: a Walls table of pairs, no flags, no zone party.

Invented names only. Work is the employer-like zone: most of its hubs name Emerald Corp (`emp`), which is paired
with the clients and with the venture but not with the Lumen hats of another zone. Advisory holds several
clients (Acme, Birch & Co, and Lumen under two hats) that no pair keeps apart. Personal's hubs name Jo (`jo`),
who has no pair at all. Cedar Ltd is a published venture of the Projects zone; Mint is a partner no pair names.
`build()` writes the context and the projects the migration's diff is run over.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True

from fixtures import meeting_page, project_hub, thread_note, write  # noqa: E402

CONTEXT = """\
# Context

## Me

Sam Rivera. Independent advisor.

## Zones

| Zone | Holds |
|---|---|
| Work | The employer |
| Advisory | Clients |
| Personal | Everything else |
| Projects | Own ventures |

## Parties

| Party | What it is | Zone | Tag | Domains |
|---|---|---|---|---|
| Emerald Corp | The employer | Work | `emp` | emeraldcorp.example |
| Acme Corp | Client | Advisory | `acme` | acmecorp.example |
| Birch & Co | Client | Advisory | `birch` | birchco.example |
| Lumen Group | Client | Advisory | `lumen` | |
| Lumen Group | Adviser to its board | Advisory | `lumen-adv` | |
| Mint Ltd | Partner | Work | `mint` | mintltd.example |
| Cedar Ltd | Own venture, published | Projects | `cedar` | |
| Jo Example | Own affairs | Personal | `jo` | |

## Walls

| Between | And | Why |
|---|---|---|
| `lumen` | `lumen-adv` | Two hats, one company |
| `emp` | `acme` | Outside work |
| `emp` | `birch` | Outside work |
| `cedar` | `emp` | Public |
| `cedar` | `acme` | Public |

## People

| Name | Party | Role |
|---|---|---|
| Dana Whitlock | `acme` | Head of procurement |

## Aliases

| Heard | Means |
|---|---|
| dana whitlaw | Dana Whitlock |
"""

FLAGS = {"emp": "yes", "acme": "yes", "birch": "yes", "lumen": "yes", "lumen-adv": "yes", "jo": "yes", "cedar": "no", "mint": "no"}


def build(root: Path) -> Path:
    """Put the 0.59 context and the projects into a workspace; the caller commits."""
    root = Path(root)
    write(root / "System" / "context.md", CONTEXT)
    zones = root / "Zones"
    for zone, project, party, thread in (
            ("Work", "Northwind", "emp", "Pricing"), ("Work", "Harbour", "emp", "Sizing"),
            ("Work", "Partners", "mint", "Intro"), ("Advisory", "AcmeAdv", "acme", "Review"),
            ("Advisory", "BirchAdv", "birch", "Entry"), ("Projects", "Venture", "cedar", "Notes"),
            ("Personal", "Garden", "jo", "Beds")):
        write(zones / zone / project / (project + ".md"), project_hub(zone, project, party, [thread]))
        write(zones / zone / project / "Threads" / thread / (thread + ".md"), thread_note(project, thread, party))
    # one project that names two parties a pair keeps apart
    write(zones / "Work" / "Joint" / "Joint.md", project_hub("Work", "Joint", "[emp, acme]", ["Both"]))
    write(zones / "Work" / "Joint" / "Threads" / "Both" / "Both.md", thread_note("Joint", "Both", "[emp, acme]"))
    pages = root / "Wikis" / "Meetings" / "wiki" / "sources"
    write(pages / "260310-acme-kickoff.md", meeting_page("Advisory", "[acme]", "Acme kick-off"))
    write(pages / "260312-cedar-note.md", meeting_page("Work", "[cedar]", "Cedar note"))
    write(pages / "260311-mixed.md", meeting_page("Work", "[emp, acme]", "A call that carried both"))
    return root
