"""A fictional workspace and a runner for the read guard (extras/hooks/read_guard.py), shared by
test_read_guard.py and test_connector_guard.py.

Three zones: Work (walled, holds Acme), Personal (walled, holds Birch & Co) and Ventures (open, holds Cedar).
Every test runs the hook as a subprocess with a fake HOME and the guard's folder under it, so nothing here
reads this machine's settings or logs.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parent.parent
GUARD = REPO / "extras" / "hooks" / "read_guard.py"
SENTENCE = "A wall holds some material back from this project, so I have not used it. Nothing was written."

CONTEXT = """\
# Context

## Me

Jo Example. Works alone.

My addresses: jo@home.example

## Zones

| Zone | Holds | Walled |
|---|---|---|
| Work | Client work | yes |
| Personal | Everything else | yes |
| Ventures | Own ventures | no |

## Parties

| Party | What it is | Zone | Tag | Domains |
|---|---|---|---|---|
| Acme Corp | Client | Work | `acme` | acme.example |
| Birch & Co | Client | Personal | `birch` | birch.example |
| Cedar Ltd | Own venture | Ventures | `cedar` | cedar.example |
| Maple Inc | Client, work hat | Work | `maple` | |
| Maple Inc | Same company, personal hat | Personal | `maple-p` | maple.example |

## People

| Name | Party | Role |
|---|---|---|
| Dana Whitlock | `acme` | Head of procurement |

## Aliases

| Heard | Means |
|---|---|
"""


def put(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def page(zone, title):
    head = ["---", "title: %s" % title, "type: meeting", "date: 2026-03-10"]
    if zone:
        head.append("zone: %s" % zone)
    return "\n".join(head + ["---", "", "# %s" % title, "", "Decisions."]) + "\n"


class GuardCase(unittest.TestCase):
    session = "s1"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(os.path.realpath(self.tmp.name))
        self.root = base / "workspace"
        self.home = base / "home"
        self.state = base / "garrick-read-guard"       # next to GARRICK_JOBS_DIR's folder
        self.home.mkdir()
        put(self.root / "System" / "rules.md", "# Rules\n")
        put(self.root / "System" / "context.md", CONTEXT)
        (self.root / "System" / "tools").symlink_to(REPO / "template" / "System" / "tools")
        (self.root / "System" / "skills").symlink_to(REPO / "template" / "System" / "skills")
        put(self.root / "Zones/Work/Acme/Acme.md", "---\ntitle: Acme\nparty: acme\n---\n# Acme\n")
        put(self.root / "Zones/Work/Acme/Threads/Kickoff/Kickoff.md", "# Kickoff\n")
        put(self.root / "Zones/Work/Todo.md", "# Todo\n")
        put(self.root / "Zones/Work/AGENTS.md", "# Work\n")
        put(self.root / "Zones/Personal/Birch/Birch.md", "---\ntitle: Birch\nparty: birch\n---\n# Birch\n")
        put(self.root / "Zones/Personal/Birch/Notes/secret.md", "# Birch notes\n")
        put(self.root / "Zones/Ventures/Cedar/Cedar.md", "---\ntitle: Cedar\nparty: cedar\n---\n# Cedar\n")
        put(self.root / "Wikis/Meetings/AGENTS.md", "# Meetings\n")
        put(self.root / "Wikis/Meetings/wiki/acme-kickoff.md", page("Work", "Acme kickoff"))
        put(self.root / "Wikis/Meetings/wiki/birch-pricing.md", page("Personal", "Birch pricing"))
        put(self.root / "Wikis/Meetings/wiki/cedar-garden.md", page("Ventures", "Cedar garden"))
        put(self.root / "Wikis/Meetings/wiki/loose.md", page(None, "Loose page"))
        put(self.root / "Wikis/Meetings/wiki/index.md", "# Index\n")
        put(self.root / "Wikis/Knowledge/wiki/standard.md", "---\ntitle: A standard\n---\n# A standard\n")
        put(self.root / "Wikis/Knowledge/wiki/owned.md", "---\ntitle: Owned\nzone: Work\n---\n# Owned\n")
        put(self.root / "System/notes.md", "# Notes\n")
        self.acme = self.root / "Zones/Work/Acme"
        self.birch = self.root / "Zones/Personal/Birch"
        self.cedar = self.root / "Zones/Ventures/Cedar"

    def tearDown(self):
        self.tmp.cleanup()

    # -- settings

    def settings(self, **keys):
        put(self.root / "System" / "garrick-settings.json", json.dumps(keys))

    # -- running the hook

    def env(self, project_dir=None, headless=False, **more):
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PROJECT_DIR", "GARRICK_HEADLESS")}
        env.update(HOME=str(self.home), GARRICK_JOBS_DIR=str(self.state.parent / "jobs"))
        if project_dir is not None:
            env["CLAUDE_PROJECT_DIR"] = str(project_dir)
        if headless:
            env["GARRICK_HEADLESS"] = "1"
        env.update(more)
        return env

    def run_hook(self, event, project_dir=None, headless=False, raw=None):
        done = subprocess.run([sys.executable, str(GUARD)], input=raw if raw is not None else json.dumps(event),
                              capture_output=True, text=True, env=self.env(project_dir, headless), timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stderr, "")
        return json.loads(done.stdout) if done.stdout.strip() else None

    def start(self, home):
        return self.run_hook({"session_id": self.session, "hook_event_name": "SessionStart", "cwd": str(home),
                              "source": "startup"}, project_dir=home)

    def call(self, tool, given, home=None, cwd=None):
        home = self.acme if home is None else home
        return self.run_hook({"session_id": self.session, "hook_event_name": "PreToolUse", "tool_name": tool,
                              "cwd": str(cwd or home), "tool_input": given}, project_dir=home)

    def read(self, path, home=None):
        return self.call("Read", {"file_path": str(path)}, home)

    def decision(self, reply):
        self.assertIsNotNone(reply)
        out = reply["hookSpecificOutput"]
        self.assertEqual("PreToolUse", out["hookEventName"])
        return out["permissionDecision"], out["permissionDecisionReason"]

    # -- the log

    def log_lines(self):
        path = self.state / "read-guard.log"
        if not path.is_file():
            return []
        return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]

    def log_text(self):
        path = self.state / "read-guard.log"
        return path.read_text(encoding="utf-8") if path.is_file() else ""
