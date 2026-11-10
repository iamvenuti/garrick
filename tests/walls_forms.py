"""The rows of the wall diff (wall_diff.py): one note for each link form and page kind, and each case of
`walls/forms/`, run through a wall check on a fixture workspace.

Northwind is a project for Acme, Harbour one for Birch & Co, both in the Work zone; neither folder is named like its
party. The rows were written for the party walls, where Northwind and Harbour were walled from each other. Under the
zone wall they are one zone, so a row that went from refused to passed is *inside one zone*; a Cedar zone named like a
party is a row of its own. Every workspace is built in a temporary folder with invented names only. This is a table
for the gate, not a test module: `tests/wall_diff.py` runs it through two checks.
"""

from __future__ import annotations

import itertools
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from fixtures import build_workspace, meeting_page, project_hub, thread_note, write  # noqa: E402

import check  # noqa: E402

KINDS = ("source", "person", "entity", "decision", "question", "answer", "raw")
GRADES = ("", "dormant", "archive")           # live, then the two that faded

# Two pages of each kind and grade, one for each side of the wall.
FAR, NEAR = "birch", "acme"
SLUGS = {FAR: ("harvest", "orchard", "meadow"), NEAR: ("quarry", "forge", "lantern")}
PEOPLE = {FAR: ("kai-ross", "lee-ross", "max-ross"), NEAR: ("jo-lane", "ana-lane", "tom-lane")}
ENTITIES = {FAR: ("harvest-co", "orchard-co", "meadow-co"), NEAR: ("quarry-ltd", "forge-ltd", "lantern-ltd")}
DECISION_BODY = ("\n# Pick a supplier\n\n## Decision\n\nGo.\n\n## Assumptions\n\nNone.\n\n"
                 "## Options turned down\n\nNone.\n\n## Revisit when\n\nNever.\n")


def meetings_home(root: Path, grade: str) -> Path:
    home = root / "Wikis" / "Meetings"
    return home / grade if grade else home


def page_files(root: Path, kind: str, grade: str, party: str, n: int):
    """(path, text) of each file one page of `kind` needs, the page first."""
    home = meetings_home(root, grade)
    slug = SLUGS[party][n]
    day = "26031%d" % (5 + n)
    if kind == "source":
        return [(home / "wiki" / "sources" / ("%s-%s.md" % (day, slug)),
                 meeting_page("Work", "[%s]" % party, slug.title()).replace(
                     "people:", "transcript: \"[[raw/%s-%s-call]]\"\npeople:" % (day, slug)))]
    if kind == "raw":
        return [(home / "raw" / ("%s-%s-call.txt" % (day, slug)), "Someone: we start Monday.\n")]
    if kind == "person":
        name = PEOPLE[party][n]
        return [(home / "wiki" / "people" / (name + ".md"),
                 "---\ntitle: %s\ntype: person\nparty: %s\n---\n\n# %s\n" % (name.replace("-", " ").title(), party, name))]
    if kind == "entity":
        name = ENTITIES[party][n]
        return [(home / "wiki" / "entities" / (name + ".md"),
                 "---\ntitle: %s\ntype: entity\nparty: %s\n---\n\n# %s\n" % (name, party, name))]
    if kind == "decision":
        text = ("---\ntitle: Pick a supplier\ntype: decision\nstatus: valid\nzone: Work\nparties: [%s]\n---\n" % party
                + DECISION_BODY)
        return [(home / "wiki" / "decisions" / ("%s - pick-%s.md" % (day, slug)), text)]
    if kind == "question":
        if grade:
            return []
        text = "---\ntitle: Which region\ntype: question\nzone: Work\nparties: [%s]\n---\n\n# Which region\n" % party
        return [(home / "questions" / ("%s - region-%s.md" % (day, slug)), text)]
    if kind == "answer":
        text = "---\ntitle: Which region\ntype: answer\nzone: Work\nparties: [%s]\n---\n\nThe north.\n" % party
        return [(home / "raw" / "answers" / ("%s - region-%s.md" % (day, slug)), text)]
    raise ValueError(kind)


def build(root: Path):
    """The workspace: the base fixture, Northwind (Acme), Harbour (Birch & Co) and every page of every kind and
    grade for each party. Returns {(kind, grade, party): page path}."""
    build_workspace(root)
    work = root / "Zones" / "Work"
    for name, party, thread in (("Northwind", NEAR, "Freight"), ("Harbour", FAR, "Tender")):
        write(work / name / (name + ".md"), project_hub("Work", name, party, [thread]))
        write(work / name / "Threads" / thread / (thread + ".md"), thread_note(name, thread, party))
    write(work / "Harbour" / "Sources" / "brief.docx", "far brief\n")
    write(work / "Northwind" / "Sources" / "brief.docx", "near brief\n")
    pages = {}
    for kind, grade, party in itertools.product(KINDS, GRADES, (FAR, NEAR)):
        files = page_files(root, kind, grade, party, GRADES.index(grade))
        for path, text in files:
            write(path, text)
        if files:
            pages[(kind, grade, party)] = files[0][0]
    return pages


# --- The reviewers' case files -------------------------------------------------------------------------------------

FORMS = Path(__file__).resolve().parent / "walls" / "forms"
NAMES = {
    FAR: dict(person="wiki/people/kai-ross", pname="kai-ross", pesc="kai\\-ross", punder="kai_ross", pspace="kai ross",
              pstar="kai-ro*", ptail="ross", entity="wiki/entities/harvest-co", source="wiki/sources/260315-harvest",
              sname="260315-harvest", dec="wiki/decisions/260315 - pick-harvest", project="Harbour"),
    NEAR: dict(person="wiki/people/jo-lane", pname="jo-lane", pesc="jo\\-lane", punder="jo_lane", pspace="jo lane",
               pstar="jo-la*", ptail="lane", entity="wiki/entities/quarry-ltd", source="wiki/sources/260315-quarry",
               sname="260315-quarry", dec="wiki/decisions/260315 - pick-quarry", project="Northwind"),
}


def fill(text: str, party: str, root: str = "") -> str:
    names = dict(NAMES[party], long="x " * 600, root=root)
    harness = "Zones/Work/%s/.claude/harbour-ledger.md" % names["project"]
    names.update(harness=harness, abspath="%s/%s" % (root, harness), harnessuri=harness.replace("/", "%2F"))
    text = re.sub(r"<U\+([0-9A-Fa-f]{4,6})>", lambda m: chr(int(m.group(1), 16)), text)
    return re.sub(r"\{(\w+)\}", lambda m: names[m.group(1)], text)


def load(path: Path):
    """[(case name, far verdict, near verdict, template)] of one round's file."""
    cases, name, meta, body, fenced = [], None, {}, [], False
    for line in path.read_text(encoding="utf-8").splitlines():
        if fenced:
            if line.startswith("~~~~~"):
                cases.append((name, meta.get("far"), meta.get("near"), "\n".join(body) + "\n"))
                name, meta, body, fenced = None, {}, [], False
            else:
                body.append(line)
        elif line.startswith("~~~~~"):
            fenced = True
        elif line.startswith("### "):
            name, meta = line[4:].strip(), {}
        elif name and re.match(r"(far|near):", line):
            key, _, value = line.partition(":")
            meta[key] = value.strip()
    return cases


def all_cases():
    out = []
    for path in sorted(FORMS.glob("*.md")):
        if path.name != "README.md":
            out += [(path.stem, n) + case for n, case in enumerate(load(path), 1)]
    return out


# --- The end-to-end rows -------------------------------------------------------------------------------------------

NOTE = "# Notes\n\nSee %s now.\n"
# One for each way a note links or writes a path that the vault resolves.
LINKS = {
    "wikilink-name": lambda r: NOTE % ("[[%s]]" % r["name"]),
    "wikilink-path": lambda r: NOTE % ("[[%s]]" % r["path"]),
    "markdown-link": lambda r: NOTE % ("[the page](<%s>)" % r["path"]),
    "embed": lambda r: NOTE % ("![[%s]]" % r["name"]),
    "code-path": lambda r: NOTE % ("`%s`" % r["path"]),
    "frontmatter": lambda r: "---\nrelated: %s\n---\n\nx\n" % r["path"],
    "html-link": lambda r: NOTE % ('<a href="%s">x</a>' % r["path"]),
    "autolink": lambda r: NOTE % ("<file://%s>" % r["abs"]),
    "obsidian-uri": lambda r: NOTE % ("[x](obsidian://open?vault=Workspace&file=%s)"
                                      % r["path"].replace("/", "%2F").replace(" ", "%20")),
}


def named(root: Path, page: Path) -> dict:
    """How the forms of `LINKS` write a page: its name, its path from the top of the vault, its absolute path."""
    path = page.relative_to(root).as_posix()
    return {"name": page.name if page.suffix != ".md" else page.stem, "path": path, "abs": str(page)}


def rows(root: Path, pages: dict, party: str):
    """(label, text) for each row that points at a page of `party`: every kind and grade, in every form."""
    out = []
    for (kind, grade, owner), page in sorted(pages.items()):
        if owner != party:
            continue
        how = named(root, page)
        for form, write_it in LINKS.items():
            if " " in how["path"] and form in ("code-path", "frontmatter", "html-link", "autolink"):
                continue                       # a name with spaces is written in a link, not bare
            if grade and form not in ("wikilink-name", "wikilink-path", "embed"):
                continue                       # a faded page is reached by its name or by its path
            out.append(("%s/%s/%s" % (kind, grade or "live", form), write_it(how)))
    return out


class Table:
    """The rows and the reviewers' cases, run against one check module in one process."""

    def __init__(self, tools=check, root: Path = None):
        self.check = tools
        self.root = root
        self.pages = build(root)
        ctx = root / "System" / "context.md"       # a walled party named like its zone: the case 0.60.1's gate missed
        text = ctx.read_text(encoding="utf-8").replace("| Work | Client work | | walled |", "| Work | Client work | | walled |\n| Cedar | Its own affairs | | walled |")
        text = text.replace("| Acme Corp |", "| Cedar | The company itself | Cedar | `cedar` | yes | |\n| Acme Corp |", 1)
        ctx.write_text(text, encoding="utf-8")
        write(root / "Zones" / "Cedar" / "Todo.md", "# Todo\n")
        # one walled zone and one open zone beside Work, each with a party and a page of its own: the rows across a
        # zone wall are refused by both checks, the row into an open zone passes in both
        text = ctx.read_text(encoding="utf-8").replace("| Personal | Everything else | | walled |", "| Personal | Everything else | | walled |\n| Ventures | Published work | | open |")
        text = text.replace("| Acme Corp |", "| Own affairs | His own | Personal | `jo` | yes | |\n| Maple | Own venture | Ventures | `maple` | no | |\n| Acme Corp |", 1)
        ctx.write_text(text, encoding="utf-8")
        write(root / "Wikis" / "Meetings" / "wiki" / "entities" / "unplaced.md", "---\ntitle: Unplaced\ntype: entity\n---\n\n# Unplaced\n")
        meetings = root / "Wikis" / "Meetings" / "wiki" / "sources"
        write(meetings / "260320-garden-call.md", meeting_page("Personal", "[jo]", "Garden call"))
        write(meetings / "260321-orchard-call.md", meeting_page("Ventures", "[maple]", "Orchard call"))
        write(root / "Zones" / "Personal" / "Garden" / "Garden.md", project_hub("Personal", "Garden", "jo", ["Beds"]))
        write(root / "Zones" / "Personal" / "Garden" / "Threads" / "Beds" / "Beds.md", thread_note("Garden", "Beds", "jo"))
        write(root / "Zones" / "Ventures" / "Orchard" / "Orchard.md", project_hub("Ventures", "Orchard", "maple", ["Rows"]))
        write(root / "Zones" / "Ventures" / "Orchard" / "Threads" / "Rows" / "Rows.md", thread_note("Orchard", "Rows", "maple"))
        for project in ("Harbour", "Northwind"):
            write(root / "Zones" / "Work" / project / ".claude" / "harbour-ledger.md", "{}\n")
        self.ws = tools.discover(root)
        self.ws.quick = True            # the wording comparison is not the subject here
        self.notes = {}
        for name, party, thread in (("Northwind", NEAR, "Freight"), ("Harbour", FAR, "Tender")):
            project = root / "Zones" / "Work" / name
            self.notes[name] = (project, {party}, project / "Threads" / thread / "Notes.md")

    def verdict(self, project_name: str, text: str) -> str:
        project, ptags, note = self.notes[project_name]
        if hasattr(self.check, "zone_findings_for_file"):       # the zone wall
            found = self.check.zone_findings_for_file(self.ws, note, text)
        else:                                                    # a release before it
            found = self.check.walls_for_file(self.ws, project, ptags, note, text)
        walls = [f for f in found if f.check == "walls"]
        if any(f.severity == "error" for f in walls):
            return "refused"
        return "warned" if walls else "passed"

    OTHER_ZONE_ROWS = {("jo", "other-zone/source-link"): "# Notes\n\nSee [[260320-garden-call]].\n",
                       ("jo", "other-zone/source-path"): "# Notes\n\nSee `Wikis/Meetings/wiki/sources/260320-garden-call.md`.\n",
                       ("jo", "other-zone/project-file"): "# Notes\n\nSee [[Zones/Personal/Garden/Garden]].\n",
                       ("maple", "open-zone/source-link"): "# Notes\n\nSee [[260321-orchard-call]].\n",
                       ("none", "unplaced-entity/final"): "# Notes\n\nSee [[unplaced]].\n",
                       ("maple", "open-zone/project-file"): "# Notes\n\nSee [[Zones/Ventures/Orchard/Orchard]].\n"}
    ZONE_ROWS = {"cedar-zone/prose": "# Notes\n\nCedar asked for the figures.\n",
                 "cedar-zone/zone-key": "---\nzone: Cedar\ntype: note\n---\n\nx\n"}

    def expected(self):
        """{(project, party, label): what the tree owes}: refused across the wall, or by design (text) there too."""
        want = {}
        for project_name, own in (("Northwind", NEAR), ("Harbour", FAR)):
            for party in (FAR, NEAR):
                for label, _ in rows(self.root, self.pages, party):
                    want[(project_name, party, label)] = "refused" if party != own else "passed"
        want[("Northwind", "cedar", "cedar-zone/prose")] = "refused"
        want[("Northwind", "cedar", "cedar-zone/zone-key")] = "by design"       # #465: the `zone:` key is structure
        for rnd, n, name, far, near, _ in all_cases():
            want[("Northwind", FAR, "form/%s/%d %s" % (rnd, n, name))] = "refused" if far == "refused" else "by design"
            want[("Northwind", NEAR, "form/%s/%d %s" % (rnd, n, name))] = "passed"
        return want

    def run(self, full: bool = False):
        """{(project, party, label): verdict}: Northwind reads the pages of both parties, Harbour reads them back, and
        Northwind reads each case of the case files, naming a page of each party."""
        out = {}
        for project_name in ("Northwind", "Harbour"):
            for party in (FAR, NEAR):
                for label, text in rows(self.root, self.pages, party):
                    out[(project_name, party, label)] = self.verdict(project_name, text)
        for label, text in self.ZONE_ROWS.items():
            out[("Northwind", "cedar", label)] = self.verdict("Northwind", text)
        for (party, label), text in self.OTHER_ZONE_ROWS.items():
            out[("Northwind", party, label)] = self.verdict("Northwind", text)
        for rnd, n, name, far, near, template in all_cases():
            for party in (FAR, NEAR):
                out[("Northwind", party, "form/%s/%d %s" % (rnd, n, name))] = self.verdict(
                    "Northwind", fill(template, party, str(self.root)))
        return out
