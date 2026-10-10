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

from garrick_lib import install_wall_hook  # noqa: E402

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


def meeting_page(zone: str = "Work", parties: str = "[acme]", title: str = "Kick-off") -> str:
    lines = ["---", "title: %s" % title, "type: meeting", "date: 2026-03-10"]
    if zone is not None:
        lines.append("zone: %s" % zone)
    if parties is not None:
        lines.append("parties: %s      # from the Parties table" % parties)
    lines += ["people: [\"[[wiki/people/dana-whitlock]]\"]", "---", "", "# %s" % title, "", "Decisions."]
    return "\n".join(lines) + "\n"


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
