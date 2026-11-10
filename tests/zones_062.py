"""A workspace as Garrick 0.62 left it: a flag on each party, a party and a default on each zone.

Invented names only. Work is the employer-like zone: its party Emerald Corp (`emp`) is walled. Advisory holds
several clients (Acme, Birch & Co) and has no zone party, but its default for a new party is walled. Home's
party Jo (`jo`) is walled. Projects holds Cedar Ltd, a published venture: its default is open. Two Meetings
pages draw from Work and from Advisory (the mixed entity), and one call carried both.
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

| Zone | Holds | Party | New parties |
|---|---|---|---|
| Work | The employer | `emp` | open |
| Advisory | Clients | | walled |
| Home | Everything else | `jo` | walled |
| Projects | Own ventures | | open |

## Parties

| Party | What it is | Zone | Tag | Walled | Domains |
|---|---|---|---|---|---|
| Emerald Corp | The employer | Work | `emp` | yes | emeraldcorp.example |
| Acme Corp | Client | Advisory | `acme` | yes | acmecorp.example |
| Birch & Co | Client | Advisory | `birch` | yes | birchco.example |
| Mint Ltd | Partner | Work | `mint` | no | mintltd.example |
| Cedar Ltd | Own venture, published | Projects | `cedar` | no | |
| Jo Example | Private matters | Home | `jo` | yes | |

## People

| Name | Party | Role |
|---|---|---|
| Dana Whitlock | `acme` | Head of procurement |
| Dana Whitlock | `emp` | Head of procurement |

## Aliases

| Heard | Means |
|---|---|
| dana whitlaw | Dana Whitlock |
"""

# the zone flags the proposal gives this context
FLAGS = {"Work": True, "Advisory": True, "Home": True, "Projects": False}

# the Zones and Parties tables after the yes
ZONES_AFTER = """\
| Zone | Holds | Walled |
|---|---|---|
| Work | The employer | yes |
| Advisory | Clients | yes |
| Home | Everything else | yes |
| Projects | Own ventures | no |
"""

PARTIES_AFTER = """\
| Party | What it is | Zone | Tag | Domains |
|---|---|---|---|---|
| Emerald Corp | The employer | Work | `emp` | emeraldcorp.example |
| Acme Corp | Client | Advisory | `acme` | acmecorp.example |
| Birch & Co | Client | Advisory | `birch` | birchco.example |
| Mint Ltd | Partner | Work | `mint` | mintltd.example |
| Cedar Ltd | Own venture, published | Projects | `cedar` | |
| Jo Example | Private matters | Home | `jo` | |
"""


def build(root: Path) -> Path:
    """Put the 0.62 context and the projects into a workspace; the caller commits."""
    root = Path(root)
    write(root / "System" / "context.md", CONTEXT)
    zones = root / "Zones"
    for zone, project, party, thread in (
            ("Work", "Northwind", "emp", "Pricing"), ("Advisory", "AcmeAdv", "acme", "Review"),
            ("Advisory", "BirchAdv", "birch", "Entry"), ("Projects", "Venture", "cedar", "Notes"),
            ("Home", "Garden", "jo", "Beds")):
        write(zones / zone / project / (project + ".md"), project_hub(zone, project, party, [thread]))
        write(zones / zone / project / "Threads" / thread / (thread + ".md"), thread_note(project, thread, party))
    pages = root / "Wikis" / "Meetings" / "wiki"
    write(pages / "sources" / "260310-acme-kickoff.md", meeting_page("Advisory", "[acme]", "Acme kick-off"))
    write(pages / "sources" / "260312-emp-sync.md", meeting_page("Work", "[emp]", "Emerald sync"))
    write(pages / "sources" / "260313-cedar-note.md", meeting_page("Projects", "[cedar]", "Cedar note"))
    write(pages / "entities" / "dana-whitlock.md",
          "---\ntitle: Dana Whitlock\ntype: entity\nparty: acme\nsources:\n"
          "  - \"[[wiki/sources/260310-acme-kickoff]]\"\n  - \"[[wiki/sources/260312-emp-sync]]\"\n---\n\n# Dana Whitlock\n")
    write(pages / "entities" / "cedar.md",
          "---\ntitle: Cedar\ntype: entity\nparty: cedar\nsources:\n"
          "  - \"[[wiki/sources/260313-cedar-note]]\"\n  - \"[[wiki/sources/260310-acme-kickoff]]\"\n---\n\n# Cedar\n")
    return root
