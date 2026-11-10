"""The Questions panel's fixture: Work and Personal, the Meetings wiki as its own repository.

    from panel_case import PanelCase, commit_all, snap
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from fixtures import CONTEXT, git, write  # noqa: E402
from test_page_action import ActionCase  # noqa: E402

SENTENCE = "A wall holds some material back from this project, so I have not used it. Nothing was written."
TOOLS = Path(__file__).resolve().parent.parent / "template" / "System" / "tools"


def commit_all(repo: Path, message: str = "start") -> None:
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=T", "-c", "user.email=t@example.com", "commit", "-qm", message)


def snap(root: Path) -> dict:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*"))
            if p.is_file() and ".git" not in p.parts and "generated" not in p.parts}


class PanelCase(ActionCase):
    """Work and Personal; the Meetings wiki is its own repository, with the tools an installed workspace has."""

    def setUp(self):
        super().setUp()
        for f in TOOLS.glob("*.py"):
            shutil.copy2(f, self.root / "System" / "tools" / f.name)
        write(self.root / "System" / "context.md", CONTEXT)
        self.meetings = self.root / "Wikis" / "Meetings"
        shutil.rmtree(self.meetings / ".git", ignore_errors=True)
        git(self.meetings, "init", "-q")
        git(self.meetings, "config", "maintenance.auto", "false")
        git(self.meetings, "config", "gc.auto", "0")
        commit_all(self.meetings)
