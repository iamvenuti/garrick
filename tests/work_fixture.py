"""Invented workspaces for the reader of the piece of work (test_work_reader): one project per shape."""

from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True

BLOCK = "\n## State of play\n\n### Resume here\n\n**Where it stands, 1 March 2026.** Going.\n\n| | |\n|---|---|\n| Next action | send the draft |\n"
OUTCOME = "\n## State of play\n\n### Outcome\n\nDelivered.\n"


def hub(name: str, status: str = "active", layout: str = "", typed: bool = True, body: str = "") -> str:
    front = ["title: %s" % name] + (["type: project"] if typed else []) + ["status: %s" % status]
    if layout:
        front.append("layout: %s" % layout)
    return "---\n%s\n---\n\n# %s\n%s" % ("\n".join(front), name, body)


def thread(name: str, status: str = "active") -> str:
    return ("---\ntitle: %s\ntype: thread\nstatus: %s\nupdated: 2026-03-01\n---\n\n# %s\n" % (name, status, name)
            + (OUTCOME if status == "done" else BLOCK))


def put(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build(root: Path) -> Path:
    """One zone, Work, with a project for each shape the readers have to agree about."""
    z = Path(root) / "Zones" / "Work"

    def project(name, hub_text=None, threads=(), empty_threads=(), **kw):
        if hub_text is not None:
            put(z / name / (name + ".md"), hub_text)
        else:
            (z / name).mkdir(parents=True, exist_ok=True)
        for t, status in threads:
            put(z / name / "Threads" / t / (t + ".md"), thread(t, status))
        for t in empty_threads:
            (z / name / "Threads" / t).mkdir(parents=True, exist_ok=True)

    project("Single", hub("Single", body=BLOCK))                                    # one hub, its own thread
    project("SingleBare", hub("SingleBare"))                                         # one hub, no resume block
    project("Untyped", hub("Untyped", typed=False, body=BLOCK))                      # a hub with no type:
    project("Heading", hub("Heading", layout="thread-first"))                        # an empty heading
    project("HeadingThreads", hub("HeadingThreads", layout="thread-first"), [("Alpha", "active"), ("Beta", "active")])
    project("HeadingBlock", hub("HeadingBlock", layout="thread-first", body=BLOCK), [("Gamma", "active")])
    project("Mixed", hub("Mixed", body=BLOCK), [("Delta", "active"), ("Epsilon", "done")])   # hub keeps resume beside threads
    project("Plain", hub("Plain"), [("Zeta", "active"), ("Eta", "active")])          # threads, hub holds nothing
    project("Outcome", hub("Outcome", body=OUTCOME), [("Theta", "active")])          # an Outcome ends the hub's block
    project("Parked", hub("Parked", status="parked", body=BLOCK), [("Iota", "active"), ("Kappa", "done")])
    project("ParkedBare", hub("ParkedBare", status="parked"), [("Lambda", "active")])
    project("Done", hub("Done", status="done", body=BLOCK), [("Mu", "active")])
    project("Threads", None, [("Nu", "parked"), ("Xi", "done"), ("Omicron", "active")])       # no hub at all
    project("OneThread", hub("OneThread"), [("Pi", "active")])                       # one thread, no resume block on the hub
    project("EmptyDir", hub("EmptyDir", body=BLOCK), empty_threads=["Rho"])          # a thread folder with no note
    project("EmptyDirBare", hub("EmptyDirBare"), empty_threads=["Sigma"])
    project("Ragged", hub("Ragged"), [("Real", "active")], empty_threads=["Bare"])   # one thread with a note, one folder without
    project("Spaced", hub("Spaced", body="\n###   Resume here\n\nGoing.\n"), [("Tau", "active")])
    project("Odd", hub("Odd", status="dormant"), [("Upsilon", "active")])           # a status the rules do not allow
    # Not projects.
    put(z / "archive" / "Old" / "Old.md", hub("Old"))
    put(z / "Inbox" / "Inbox.md", hub("Inbox"))
    put(z / "_template" / "_template.md", hub("_template"))
    # A project kept in System/ is no part of a zone.
    put(Path(root) / "System" / "Sys" / "Sys.md", hub("Sys", body=BLOCK))
    return Path(root)
