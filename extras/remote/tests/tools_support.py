"""Shared set-up for the tools' tests: a stub Session with the contract's names, and a fixture workspace.

The stub lives here and never in `context.py`: `extras/remote/context.py` is the service's. The workspace is the
one the repository's own Ask tests build (two walled zones, Work with Acme Corp and Personal with Birch & Co,
a published report and one meeting page on each side), with the status extra and the core's tools copied in as an
installed workspace has them, so that Ask's read server runs as it does in a real one.

Nothing here reads this Mac: the state folder is a temporary one (GARRICK_REMOTE_HOME) and the jobs folder is the
fixture's own.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO / "extras" / "remote"))

import test_ask_scope as scoped  # noqa: E402


class HandleRefused(Exception):
    """What a Session raises for a handle that is made up, expired or from an older reach."""


class StubSession:
    """The contract's Session, as the tools are built against it: `grant_id`, `workspace`, `classes`, `readable`,
    `writable`, `new_handle()`, `check_handle(h)` and `zone_allowed(zone, write=False)`."""

    def __init__(self, workspace, readable=("Work", "Knowledge", "docs"), writable=(), grant_id="grant-one"):
        self.grant_id = grant_id
        self.workspace = str(workspace)
        self.readable = frozenset(readable)
        self.writable = frozenset(writable)
        self.classes = frozenset(("read",) + (("write",) if writable else ()))
        self.issued = set()
        self.handle_count = 0

    def new_handle(self):
        self.handle_count += 1
        h = "h%d-%s" % (self.handle_count, self.grant_id)
        self.issued.add(h)
        return h

    def check_handle(self, h):
        if h not in self.issued:
            raise HandleRefused("This chat is out of date. Please start a new chat.")

    def zone_allowed(self, zone, write=False):
        if write and "write" not in self.classes:
            return False
        return zone in (self.writable if write else self.readable)

    def change_reach(self, readable=None, writable=None):
        """The owner changes the reach at the Mac: every handle issued before stops."""
        if readable is not None:
            self.readable = frozenset(readable)
        if writable is not None:
            self.writable = frozenset(writable)
        self.issued = set()


class ToolsCase(scoped.AnswerCase):
    """A fixture workspace, installed as a workspace is: System/status and System/tools next to the zones."""

    def setUp(self):
        super().setUp()
        status = self.root / "System" / "status"
        status.mkdir(parents=True, exist_ok=True)
        for src in sorted((REPO / "extras" / "status").glob("*.py")):
            shutil.copy2(str(src), str(status / src.name))
        for src in sorted((REPO / "template" / "System" / "tools").glob("*.py")):
            shutil.copy2(str(src), str(self.root / "System" / "tools" / src.name))
        shutil.copytree(str(REPO / "template" / "System" / "skills"), str(self.root / "System" / "skills"),
                        ignore=shutil.ignore_patterns("__pycache__"), dirs_exist_ok=True)
        for zone in ("Work", "Personal"):
            if (self.root / "Zones" / zone).is_dir():
                (self.root / "Zones" / zone / ".gitignore").write_text(".recall.sqlite*\n.sessions/\n")
        self.remote = Path(self._tmp.name) / "remote-home"
        self._saved_home = os.environ.get("GARRICK_REMOTE_HOME")
        os.environ["GARRICK_REMOTE_HOME"] = str(self.remote)
        self.addCleanup(self._restore_home)

    def _restore_home(self):
        if self._saved_home is None:
            os.environ.pop("GARRICK_REMOTE_HOME", None)
        else:
            os.environ["GARRICK_REMOTE_HOME"] = self._saved_home

    def session(self, **kw):
        return StubSession(self.root, **kw)
