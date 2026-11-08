"""The fixture workspace of the wall cases (walls/cases.md): invented names only.

Northwind is a project of Acme (`acme`), Harbour one of Birch & Co (`birch`),
Orchard one whose hub names no party, Reed one of Cedar Ltd (`cedar`), an open
party. Acme, Birch & Co, Jo (`jo`, the party the Personal zone names) and the
two Lumen hats are walled; no folder is named after its party.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from fixtures import build_workspace, project_hub, thread_note, write, meeting_page  # noqa: E402

PAGE = "---\ntitle: %s\ntype: %s\n%s---\n\n# %s\n\nSee %s.\n"


def build(root: Path) -> Path:
    """build_workspace's two projects renamed out of the way, plus the cases' own."""
    root = Path(root)
    build_workspace(root)
    # one company under two hats, a wall between the hats: mail from either is asked about
    context = root / "System" / "context.md"
    text = context.read_text(encoding="utf-8")
    text = text.replace("| Birch & Co | Client. Market-entry advice; competes with Acme | Work | `birch` | yes | birchco.example, mail.birchco.example |\n",
                        "| Birch & Co | Client. Market-entry advice; competes with Acme | Work | `birch` | yes | birchco.example, mail.birchco.example |\n"
                        "| Lumen Group | Partner | Work | `lumen` | yes | |\n| Lumen Group | Adviser to its board | Work | `lumen-adv` | yes | |\n"
                        "| Cedar Ltd | Supplier | Work | `cedar` | no | cedarltd.example |\n"
                        "| Jo Example | Own affairs | Personal | `jo` | yes | |\n")
    text = text.replace("| Personal | Everything else | | walled |", "| Personal | Everything else | `jo` | walled |")
    context.write_text(text, encoding="utf-8")
    work = root / "Zones" / "Work"
    for name in ("Acme Review", "Birch Entry"):
        shutil.rmtree(work / name)
    meetings = root / "Wikis" / "Meetings"
    for project, party, thread in (("Northwind", "acme", "Pricing"), ("Harbour", "birch", "Sizing"),
                                   ("Reed", "cedar", "Notes")):
        write(work / project / (project + ".md"), project_hub("Work", project, party, [thread]))
        write(work / project / "Threads" / thread / (thread + ".md"), thread_note(project, thread, party))
    write(work / "Orchard" / "Orchard.md", project_hub("Work", "Orchard", "", ["Drafts"]))
    write(work / "Orchard" / "Threads" / "Drafts" / "Drafts.md", thread_note("Orchard", "Drafts", "acme"))
    write(meetings / "wiki" / "sources" / "260315-split.md",
          meeting_page("Work", "[acme]", "Split").replace("parties:", "party: birch\nparties:"))
    # raw records: one cited by a page of each side, one by one page, one by nobody
    cite = lambda stem: "transcript: \"[[raw/%s]]\"\npeople:" % stem
    write(meetings / "wiki" / "sources" / "260317-both-a.md",
          meeting_page("Work", "[acme]", "Both A").replace("people:", cite("260317-both-call")))
    write(meetings / "wiki" / "sources" / "260317-both-b.md",
          meeting_page("Work", "[birch]", "Both B").replace("people:", cite("260317-both-call")))
    write(meetings / "raw" / "260317-both-call.txt", "Someone: we start Monday.\n")
    write(meetings / "raw" / "260319-orphan-call.txt", "Nobody cites this.\n")
    write(meetings / "wiki" / "sources" / "260318-unfinished.md", meeting_page(None, "[acme]", "Unfinished"))
    write(work / "Harbour" / "Threads" / "Sizing" / "Notes.md", "# Notes\n")
    # a hub whose party: and parties: disagree: labels() reads it as neither
    write(work / "Dis" / "Dis.md", project_hub("Work", "Dis", "acme", ["T"]).replace("party: acme", "party: acme\nparties: [cedar]"))
    write(work / "Dis" / "Threads" / "T" / "T.md", thread_note("Dis", "T", "acme"))
    write(work / "Dis" / "Threads" / "T" / "Memo.md", "# memo\n")
    write(work / "Cedarwork" / "Cedarwork.md", project_hub("Work", "Cedarwork", "cedar", ["T"]))
    write(work / "Cedarwork" / "Threads" / "T" / "T.md", thread_note("Cedarwork", "T", "cedar"))
    write(work / "Cedarwork" / "Sources" / ".gitkeep")
    write(work / "Reed" / "Sources" / ".gitkeep")
    # one company under two hats, hub and thread: they never meet in one record
    write(work / "Hats" / "Hats.md", project_hub("Work", "Hats", "lumen-adv", ["T"]))
    write(work / "Hats" / "Threads" / "T" / "T.md", thread_note("Hats", "T", "lumen"))
    write(work / "Hats" / "Threads" / "T" / "x.md", "# x\n")
    # a thread folder spelt in lower case
    write(work / "Low" / "Low.md", project_hub("Work", "Low", "acme"))
    write(work / "Low" / "threads" / "T" / "T.md", thread_note("Low", "T", "birch"))
    write(work / "Low" / "threads" / "T" / "x.md", "# x\n")
    # a project that names two walled parties on purpose: their material may meet there
    write(work / "Both" / "Both.md", project_hub("Work", "Both", "[acme, birch]", ["T"]))
    write(work / "Both" / "Threads" / "T" / "T.md", thread_note("Both", "T", "[acme, birch]"))
    write(work / "Both" / "Threads" / "T" / "Notes.md", "# Notes\n")
    # a project of the Personal zone, which names `jo`: its files carry `jo` and the hub's open party
    home = root / "Zones" / "Personal"
    write(home / "Garden" / "Garden.md", project_hub("Personal", "Garden", "cedar", ["Beds"]))
    write(home / "Garden" / "Threads" / "Beds" / "Beds.md", thread_note("Garden", "Beds", "cedar"))
    write(home / "Garden" / "Threads" / "Beds" / "Plan.md", "# Plan\n")
    # a hub whose type is not `project`: the hook and labels() both find it as the note named after its folder
    write(work / "Hubnote" / "Hubnote.md", project_hub("Work", "Hubnote", "acme").replace("type: project", "type: note"))
    write(work / "Hubnote" / "Threads" / "T" / "x.md", "# x\n")
    write(work / "Northwind" / "Threads" / "Pricing" / "Deal.md",
          "# Deal\n\nDana Whitlock of Acme Corp agreed; see [[260310-acme-kickoff]].\n")
    write(work / "Northwind" / "Threads" / "Pricing" / "Notes.md", "# Notes\n")
    # a Northwind thread written for the far side: the thread note and the hub disagree
    write(work / "Northwind" / "Threads" / "Odd" / "Odd.md", thread_note("Northwind", "Odd", "birch"))
    write(work / "Northwind" / "Threads" / "Odd" / "Notes.md", "# Notes\n")
    write(work / "Reed" / "Threads" / "Notes" / "Notes.md", thread_note("Reed", "Notes", "cedar"))
    return root
