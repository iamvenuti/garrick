"""A small fictional workspace, built by hand for the checker's tests.

Two invented clients with a wall between them: Acme Corp (`acme`) and
Birch & Co (`birch`). Nothing here depends on the installer.
"""

from __future__ import annotations
import sys
sys.dont_write_bytecode = True  # keep the repo free of __pycache__

import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "template" / "System" / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from garrick_lib import (  # noqa: E402
    checkpoint_item_line,
    install_wall_hook,
    place_checkpoint,
    render_checkpoint,
    resume_hash,
)

HAVE_GIT = shutil.which("git") is not None

GIT_ENV = dict(
    os.environ,
    GIT_CONFIG_GLOBAL=os.devnull,
    GIT_CONFIG_NOSYSTEM="1",
    GIT_AUTHOR_NAME="Test",
    GIT_AUTHOR_EMAIL="test@example.invalid",
    GIT_COMMITTER_NAME="Test",
    GIT_COMMITTER_EMAIL="test@example.invalid",
    # A commit can start background maintenance, whose lock file races a test deleting .git.
    GIT_CONFIG_COUNT="2",
    GIT_CONFIG_KEY_0="maintenance.auto",
    GIT_CONFIG_VALUE_0="false",
    GIT_CONFIG_KEY_1="gc.auto",
    GIT_CONFIG_VALUE_1="0",
)

CONTEXT = """\
# Context

## Me

Jo Example. Independent advisor.

## Zones

| Zone | Holds |
|---|---|
| Work | Client work |
| Personal | Everything else |

## Parties

| Party | What it is | Zone | Tag | Domains |
|---|---|---|---|---|
| Acme Corp | Client. Supply-chain review | Work | `acme` | acmecorp.example |
| Birch & Co | Client. Market-entry advice; competes with Acme | Work | `birch` | birchco.example, mail.birchco.example |

## Walls

| Between | And | Why |
|---|---|---|
| `acme` | `birch` | Competitors, and both are clients |

## People

| Name | Party | Role |
|---|---|---|
| Dana Whitlock | `acme` | Head of procurement |
| Theo Marsh | `birch` | Managing partner |

## Aliases

| Heard | Means |
|---|---|
| birch and co, birchen co | Birch & Co |
| dana whitlaw | Dana Whitlock |
"""


def write(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


def git(cwd: Path, *args: str) -> str:
    res = subprocess.run(["git", *args], cwd=str(cwd), env=GIT_ENV, capture_output=True, text=True, check=True)
    return res.stdout


def git_init(folder: Path) -> None:
    if HAVE_GIT:
        git(folder, "init", "-q")
    else:
        (folder / ".git").mkdir(parents=True, exist_ok=True)


def commit_all(folder: Path, message: str = "snapshot") -> None:
    git(folder, "add", "-A")
    git(folder, "-c", "commit.gpgsign=false", "-c", "core.hooksPath=" + os.devnull,
        "commit", "-q", "--allow-empty", "-m", message)


def project_hub(zone: str, project: str, party: str = "acme", threads=()) -> str:
    party_line = "party: %s\n" % party if party else ""
    listed = "".join("- [[%s/Threads/%s/%s|%s]]: a thread\n" % (project, t, t, t) for t in threads)
    return (
        "---\ntitle: %s\ntype: project\nzone: %s\n%sstatus: active\ncreated: 2026-03-01\nupdated: 2026-03-01\n---\n\n"
        "# %s\n\nA fictional project.\n" % (project, zone, party_line, project)
        + ("\n## Threads\n\n" + listed if listed else "")
    )


def thread_note(project: str, thread: str, party: str = "acme", body: str = "", status: str = "active") -> str:
    closing = (
        "### Outcome\n\nDelivered and accepted.\n"
        if status == "done"
        else "### Resume here\n\n**Where it stands, 1 March 2026.** Drafting.\n"
    )
    return (
        "---\ntitle: %s\ntype: thread\nproject: \"[[%s]]\"\nparty: %s\nstatus: %s\ncreated: 2026-03-01\nupdated: 2026-03-01\n---\n\n"
        "# %s\n\n%s\n\n## State of play\n\n%s" % (thread, project, party, status, thread, body, closing)
    )


CHECKPOINT_AT = "2026-03-14T14:32:10+01:00"
# What a checkpoint holds in the tests that only need one to be there: a file
# this session made, a decision in the words it was made in, something still
# only being considered, the next step, an action nobody dated, and the work
# left half done.
CHECKPOINT_ITEMS = (
    ("made", "`Deliverables/260301 - Pricing memo.md`, saved 14:20", "m1"),
    ("decided", '"Go with the tier-two rate as drafted", the user at 14:25', "d1"),
    ("considering", "dropping tier three; not decided", "c1"),
    ("next", "fill in the tier-two volume on row 14, the user's", "n"),
    ("action", "send Dana the price sheet, no date given", "a1"),
    ("incomplete", "the tier-three tab is half filled", "i"),
)


def checkpoint(text: str, at: str = CHECKPOINT_AT, items=CHECKPOINT_ITEMS, base: str = None) -> str:
    """A note with a valid `### Checkpoint` block under its Resume here block,
    written the way `scaffold.py checkpoint` writes one: the markers, the
    comment line carrying `at`, `base` and `key`, and one line an item. `base`
    is the note's own resume point unless a test gives another, which is how a
    stale block is made."""
    lines = [{"line": checkpoint_item_line(kind, body, item_id)} for kind, body, item_id in items]
    body, _ = render_checkpoint(at, base if base is not None else resume_hash(text), lines)
    placed = place_checkpoint(text, body)
    assert placed is not None, "the note has no Resume here block to put a checkpoint under"
    return placed


def meeting_page(zone: str = "Work", parties: str = "[acme]", title: str = "Kick-off") -> str:
    lines = ["---", "title: %s" % title, "type: meeting", "date: 2026-03-10"]
    if zone is not None:
        lines.append("zone: %s" % zone)
    if parties is not None:
        lines.append("parties: %s      # from the Parties table" % parties)
    lines += ["people: [\"[[wiki/people/dana-whitlock]]\"]", "---", "", "# %s" % title, "", "Decisions."]
    return "\n".join(lines) + "\n"


# A stand-in for System/tools/fade.py, graded oblivion's (#108), which the
# status page's Settings › Memory and page_action.py build against: the
# contract, and counts worked out from the settings alone, so a test can see
# them follow a change. Never the real tool, which ships with its own tests.
FADE_STUB = textwrap.dedent('''\
    import json
    from pathlib import Path

    DEFAULTS = {
        "wikis": {"Meetings": True, "Knowledge": True},
        "kinds": {
            "meetings": {"wiki": "Meetings", "types": ["meeting", "email"], "domains": [], "dormant": 6, "archived": 18},
            "reading": {"wiki": "Knowledge", "types": ["newsletter", "article"], "domains": [], "dormant": 3, "archived": 12},
            "reference": {"wiki": "Knowledge", "types": ["report", "standard"], "domains": [], "dormant": 24, "archived": None},
        },
        "pins": {"thread": True, "project": True, "todo": True, "pinned": True},
        "wake": True,
        "reach": "dormant",
        "nightly": {"on": True, "min": 10},
    }


    def settings(root):
        try:
            stored = json.loads(Path(root, "System", "garrick-settings.json").read_text()).get("memory") or {}
        except (OSError, ValueError):
            stored = {}
        out = json.loads(json.dumps(DEFAULTS))
        for key, value in stored.items():
            out[key] = dict(out[key], **value) if isinstance(out.get(key), dict) and key != "kinds" else value
        return out


    def counts(root, memory=None):
        m = memory if memory is not None else settings(root)
        out = {}
        for wiki in ("Meetings", "Knowledge"):
            on = bool(m["wikis"].get(wiki, True))
            kinds = [k for k in m["kinds"].values() if k["wiki"] == wiki]
            out[wiki] = {"on": on, "working": 40, "dormant": 12, "archived": 5,
                         "to_dormant": sum(24 // k["dormant"] for k in kinds) if on else 0,
                         "to_archive": sum(48 // k["archived"] for k in kinds if k["archived"]) if on else 0,
                         "to_wake": 1 if on and m["wake"] else 0}
        return out
''')


def write_fade_stub(root: Path) -> Path:
    return write(Path(root) / "System" / "tools" / "fade.py", FADE_STUB)


def build_workspace(root: Path) -> Path:
    """A clean workspace: the checker should find nothing wrong with it."""
    root = Path(root)
    write(root / "AGENTS.md", "# Workspace\n")
    write(root / "System" / "rules.md", "# Rules\n")
    write(root / "System" / "context.md", CONTEXT)

    for zone in ("Work", "Personal"):
        z = root / "Zones" / zone
        (z / ".git").mkdir(parents=True)  # the check only needs it to exist; real git is slow per test
        install_wall_hook(z)
        write(z / "AGENTS.md", "# %s zone\n" % zone)
        write(z / "Todo.md", "# %s: open actions\n\n## Inbox\n\n## Done\n" % zone)
        write(z / "Inbox" / ".gitkeep")

    work = root / "Zones" / "Work"
    acme = work / "Acme Review"
    write(acme / "Acme Review.md", project_hub("Work", "Acme Review", "acme", ["Pricing"]))
    write(acme / "Threads" / "Pricing" / "Pricing.md",
          thread_note("Acme Review", "Pricing", "acme", "Draws on [[260310-acme-kickoff]]."))
    write(acme / "Sources" / ".gitkeep")
    write(acme / "Deliverables" / "260301 - Pricing memo.md", "# Pricing memo\n")

    birch = work / "Birch Entry"
    write(birch / "Birch Entry.md", project_hub("Work", "Birch Entry", "birch", ["Market Sizing"]))
    write(birch / "Threads" / "Market Sizing" / "Market Sizing.md",
          thread_note("Birch Entry", "Market Sizing", "birch"))

    meetings = root / "Wikis" / "Meetings"
    write(meetings / "AGENTS.md", "# Meetings\n")
    write(meetings / "wiki" / "index.md", "# Index\n")
    write(meetings / "wiki" / "sources" / "260310-acme-kickoff.md", meeting_page("Work", "[acme]", "Acme kick-off"))
    write(meetings / "wiki" / "sources" / "260312-birch-kickoff.md", meeting_page("Work", "[birch]", "Birch kick-off"))
    write(meetings / "wiki" / "people" / "dana-whitlock.md",
          "---\ntitle: Dana Whitlock\ntype: person\nparty: acme\ncreated: 2026-03-10\nupdated: 2026-03-10\n---\n\n"
          "# Dana Whitlock\n\nHead of procurement at Acme Corp.\n")
    write(meetings / "raw" / "inbox" / ".gitkeep")
    write(meetings / "raw" / "260310-acme-kickoff.txt", "Dana: we start Monday.\n")

    knowledge = root / "Wikis" / "Knowledge"
    write(knowledge / "AGENTS.md", "# Knowledge\n")
    write(knowledge / "wiki" / "index.md", "# Index\n\n[[wiki/sources/supply-chain-report]]\n")
    write(knowledge / "wiki" / "sources" / "supply-chain-report.md",
          "---\ntitle: Supply chains\ntype: source\nconfidence: medium\n---\n\nSee [[resilience]].\n")
    write(knowledge / "wiki" / "concepts" / "resilience.md", "# Resilience\n")
    write(knowledge / "raw" / "supply-chain-report.txt", "Frozen text.\n")
    return root
