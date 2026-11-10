"""The fixtures that a Nurture panel test shares: a context, an entity page and a person page.

The tests of the person-to-entity link went with the check that read it (zone walls: no party is read as a wall).

Was: a Meetings person page links the entity page of its party (#319).

    cd tests && python3 -m unittest test_person_organisation

An entity page in Meetings names the party it stands for, `party: acme`, and
a person page of that party links it as `organisation:`. ingest.py writes the
link on a new page, check.py warns where it is missing, wrong or doubled,
and nurture.py offers it for pages written before, on a yes, never with
nobody watching. A person page is read on every side of a wall, so the link
carries identity alone, and a name the People table places on both sides of
a wall gets none. Every workspace here is built in a temporary folder.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

sys.dont_write_bytecode = True

import fixtures  # noqa: E402  (puts the tools folder on sys.path)
from fixtures import GIT_ENV, HAVE_GIT, build_workspace, git, write  # noqa: E402

import check  # noqa: E402
import garrick_lib  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "template" / "System" / "tools"
INGEST = REPO / "template" / "System" / "skills" / "meetings" / "ingest.py"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ingest = load("garrick_meetings_ingest_319", INGEST)
nurture = load("garrick_nurture_319", TOOLS / "nurture.py")

# Cedar is a party no wall divides from Acme; Acme and Birch are walled, as in
# the shared fixture. Rowan Blake is known under both Acme and Birch: one
# name, two hats, one person page between them.
CONTEXT = fixtures.CONTEXT.replace(
    "| Birch & Co | Client.",
    "| Cedar Ltd | Supplier to Acme | Work | `cedar` | no | cedarltd.example |\n| Birch & Co | Client.",
).replace(
    "| Theo Marsh | `birch` | Managing partner |",
    "| Theo Marsh | `birch` | Managing partner |\n"
    "| Rowan Blake | `acme` | Adviser |\n"
    "| Rowan Blake | `birch` | Adviser |\n"
    "| Ines Varga | `acme` | Buyer |\n"
    "| Ines Varga | `cedar` | Account lead |\n"
    "| Aurélien Moreau | `acme` | Counsel |\n"
    "| Aurélien Moreau | `birch` | Counsel |\n"
    "| Søren Kjær | `acme` | Engineer |\n"
    "| Søren Kjær | `birch` | Engineer; signs as S. K. Lund |\n"
    "| Kit \"Kestrel\" Avery | `acme` | Analyst |\n"
    "| Kit \"Kestrel\" Avery | `birch` | Analyst |\n",
).replace("| dana whitlaw | Dana Whitlock |", "| dana whitlaw | Dana Whitlock |\n| ro blake, rowie | Rowan Blake |")


def entity(party: str, title: str = "Acme Corp", extra: str = "") -> str:
    party_line = "party: %s\n" % party if party else ""
    return ("---\ntitle: %s\ntype: entity\n%s%screated: 2026-03-10\nupdated: 2026-03-10\n---\n\n# %s\n\nAn organisation.\n"
            % (title, party_line, extra, title))


def person(name: str, party: str, organisation: str = "") -> str:
    org = 'organisation: "%s"\n' % organisation if organisation else ""
    return ("---\ntitle: %s\ntype: person\nparty: %s\n%screated: 2026-03-10\nupdated: 2026-03-10\n---\n\n# %s\n\n"
            "Someone at a party.\n" % (name, party, org, name))
