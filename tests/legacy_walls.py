"""A workspace as Garrick 0.59 left it: a Walls table of pairs, no flags, no zone party.

Invented names only. Acme and Birch & Co are clients, each walled from Jo (the
Personal zone's own affairs) and not from each other; Lumen has two hats; Cedar
Ltd is a published venture of the Projects zone that the pairs wall from both
clients; Mint is a partner that no pair names. `build()` writes the context and
the projects and records the migration's diff is run over.
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
| Work | Client work |
| Personal | Everything else |
| Projects | Own ventures |

## Parties

| Party | What it is | Zone | Tag | Domains |
|---|---|---|---|---|
| Acme Corp | Client | Work | `acme` | acmecorp.example |
| Birch & Co | Client | Work | `birch` | birchco.example |
| Lumen Group | Partner | Work | `lumen` | |
| Lumen Group | Adviser to its board | Work | `lumen-adv` | |
| Mint Ltd | Partner | Work | `mint` | mintltd.example |
| Cedar Ltd | Own venture, published | Projects | `cedar` | |
| Jo Example | Own affairs | Personal | `jo` | |

## Walls

| Between | And | Why |
|---|---|---|
| `lumen` | `lumen-adv` | Two hats, one company |
| `acme` | `jo` | Outside work |
| `birch` | `jo` | Outside work |
| `lumen` | `jo` | Outside work |
| `lumen-adv` | `jo` | Outside work |
| `cedar` | `acme` | Public |
| `cedar` | `birch` | Public |

## People

| Name | Party | Role |
|---|---|---|
| Dana Whitlock | `acme` | Head of procurement |

## Aliases

| Heard | Means |
|---|---|
| dana whitlaw | Dana Whitlock |
"""

FLAGS = {"acme": "yes", "birch": "yes", "lumen": "yes", "lumen-adv": "yes", "jo": "yes", "cedar": "no", "mint": "no"}


def build(root: Path) -> Path:
    """Put the 0.59 context and the projects into a workspace; the caller commits."""
    root = Path(root)
    write(root / "System" / "context.md", CONTEXT)
    zones = root / "Zones"
    for zone, project, party, thread in (
            ("Work", "Northwind", "acme", "Pricing"), ("Work", "Harbour", "birch", "Sizing"),
            ("Work", "Partners", "mint", "Intro"), ("Projects", "Venture", "cedar", "Notes"),
            ("Personal", "Garden", "mint", "Beds")):
        write(zones / zone / project / (project + ".md"), project_hub(zone, project, party, [thread]))
        write(zones / zone / project / "Threads" / thread / (thread + ".md"), thread_note(project, thread, party))
    # one project that names two parties a wall keeps apart
    write(zones / "Personal" / "Joint" / "Joint.md", project_hub("Personal", "Joint", "[acme, jo]", ["Both"]))
    write(zones / "Personal" / "Joint" / "Threads" / "Both" / "Both.md", thread_note("Joint", "Both", "[acme, jo]"))
    pages = root / "Wikis" / "Meetings" / "wiki" / "sources"
    write(pages / "260310-acme-kickoff.md", meeting_page("Work", "[acme]", "Acme kick-off"))
    write(pages / "260311-mixed.md", meeting_page("Work", "[acme, jo]", "A call that carried both"))
    return root
