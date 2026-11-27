"""The real tools, end to end (decision 12): the service on loopback, the SDK's own OAuth client, and a fixture workspace
that has the status extra installed, so that a write runs the workspace's real page_action.py with `--via remote`.

Register, pairing code, token, initialize, tools/list equal to the served rows plus the five reads, a read, a note through
prepare, execute and status, a retry that returns the first receipt, and a walled zone refused.

Uses the fixtures of the service's own tests (`remote_fixture.py`, `service_fixture.py`). Where `extras/remote/service.py` is
not in the tree (this module is built on a branch of its own) it skips, and the release gate checks that it ran on the merge.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
EXTRA = HERE.parent
if not (EXTRA / "service.py").is_file():
    raise unittest.SkipTest("extras/remote/service.py is not in this tree: the service's own branch is not merged yet")

sys.path.insert(0, str(HERE))
sys.path.insert(0, str(EXTRA.parents[1] / "tests"))

from remote_fixture import REPO, mod  # noqa: E402
from service_fixture import Memory, ServiceCase, sdk_client  # noqa: E402
from fixtures import project_hub, thread_note, write  # noqa: E402

sys.path.insert(0, str(EXTRA))
from tools import manifest  # noqa: E402

READS = ["places", "thread_state", "search", "read", "owed"]
WRITES = ["prepare", "execute", "status"]


def data_of(result):
    for block in result.content:
        if getattr(block, "text", None):
            try:
                return json.loads(block.text)
            except ValueError:
                return {"text": block.text}
    return getattr(result, "structured_content", None) or {}


def git(folder, *args):
    return subprocess.run(["git", "-C", str(folder), *args], capture_output=True, text=True, check=True).stdout


class RealTools(ServiceCase):
    def setUp(self):
        super().setUp()
        ws = self.ws
        tools = ws / "System" / "tools"
        tools.unlink()                                                   # a copy, so that nothing writes into the repository
        shutil.copytree(str(REPO / "template" / "System" / "tools"), str(tools), ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(str(REPO / "template" / "System" / "skills"), str(ws / "System" / "skills"), ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(str(REPO / "extras" / "status"), str(ws / "System" / "status"), ignore=shutil.ignore_patterns("__pycache__", "app"))
        write(ws / "System" / "rules.md", "# Rules\n")
        home = ws / "Zones" / "Home"
        write(home / "Todo.md", "# Home: open actions\n\n## Inbox\n\n- [ ] Cedar: book the plumber\n\n## Done\n")
        write(home / "Cedar" / "Cedar.md", project_hub("Home", "Cedar", "", ["Kitchen"]))
        write(home / "Cedar" / "Threads" / "Kitchen" / "Kitchen.md", thread_note("Cedar", "Kitchen", "", "Tiles are chosen. TILEMARK"))
        write(ws / "Zones" / "Work" / "Birch" / "Birch.md", project_hub("Work", "Birch", "", ["Pricing"]))
        write(ws / "Zones" / "Work" / "Birch" / "Threads" / "Pricing" / "Pricing.md", thread_note("Birch", "Pricing", "", "WORKMARK"))
        write(ws / "Zones" / "Work" / "Todo.md", "# Work\n\n## Inbox\n\n## Done\n")
        for zone in ("Home", "Work"):
            z = ws / "Zones" / zone
            (z / ".gitignore").write_text(".recall.sqlite*\n.sessions/\n")
            git(z, "init", "-q")
            git(z, "config", "user.name", "Test")
            git(z, "config", "user.email", "test@example.invalid")
            git(z, "config", "maintenance.auto", "false")
            git(z, "config", "gc.auto", "0")
            hook = z / ".git" / "hooks" / "pre-commit"
            hook.parent.mkdir(parents=True, exist_ok=True)
            hook.write_text("#!/bin/sh\n# Garrick wall check (a stand-in)\n")
            hook.chmod(0o755)
            git(z, "add", "-A")
            git(z, "commit", "-q", "-m", "start")

    def drive(self, mode):
        act = mod("settings_actions")
        storage = Memory()
        served = self.serve(None)                                     # the extra's own tools
        out = {}
        with served:
            client, _ = sdk_client(served, self.ws, act, storage, writes=True, mode=mode)

            async def call(name, args):
                return data_of(await client.call_tool(name, args))

            async def go():
                async with client:
                    out["names"] = sorted(t.name for t in (await client.list_tools()).tools)
                    out["places"] = await call("places", {})
                    out["state"] = await call("thread_state", {"place": "Kitchen"})
                    out["search"] = await call("search", {"words": "tiles"})
                    out["work_read"] = await call("places", {"zone": "Work"})
                    out["work_place"] = await call("thread_state", {"place": "Birch/Pricing"})
                    out["work_write"] = await call("prepare", {"verb": "note-add", "zone": "Work", "project": "Birch", "text": "x"})
                    out["wrap"] = await call("prepare", {"verb": "delete", "zone": "Home"})
                    made = await call("prepare", {"verb": "note-add", "zone": "Home", "project": "Cedar", "thread": "Kitchen",
                                                  "text": "The plumber comes on Tuesday. E2EMARK"})
                    out["made"] = made
                    first = await call("execute", {"operation_id": made["operation_id"]})
                    out["execute"] = first
                    end = time.time() + 90
                    while time.time() < end:
                        got = await call("status", {"operation_id": made["operation_id"]})
                        if got["state"] not in ("running", "prepared"):
                            break
                        await asyncio.sleep(0.3)
                    out["status"] = got
                    out["retry"] = await call("execute", {"operation_id": made["operation_id"]})
                    out["retry_prepare"] = await call("prepare", {"verb": "note-add", "zone": "Home", "project": "Cedar", "thread": "Kitchen",
                                                                  "text": "The plumber comes on Tuesday. E2EMARK", "operation_id": made["operation_id"]})

            asyncio.run(go())
        return out

    def check(self, mode):
        out = self.drive(mode)
        self.assertEqual(sorted(READS + WRITES), out["names"])
        self.assertEqual(sorted(READS), sorted(manifest.served_tools(manifest.load())))
        self.assertIn("Cedar", out["places"]["text"])
        self.assertNotIn("Birch", out["places"]["text"])
        self.assertIn("Resume here", out["state"]["text"])
        self.assertIn("handle", out["places"])
        self.assertIn("TILEMARK", json.dumps(out["search"]) + out["state"]["text"])
        self.assertEqual("new_context_required", out["work_read"]["error"])
        self.assertEqual("new_context_required", out["work_write"]["error"])
        self.assertEqual("No such place. places() lists the projects and threads.", out["work_place"]["text"])
        self.assertEqual("not_available", out["wrap"]["error"])
        self.assertEqual("prepared", out["made"]["state"])
        self.assertEqual("saved", out["status"]["state"], out["status"])
        self.assertEqual(out["status"]["say"], out["retry"]["say"])           # the first receipt
        self.assertEqual("saved", out["retry"]["state"])
        self.assertEqual(out["made"]["operation_id"], out["retry_prepare"]["operation_id"])
        notes = [p for p in (self.ws / "Zones" / "Home" / "Cedar").rglob("*.md") if "E2EMARK" in p.read_text()]
        self.assertEqual(1, len(notes))
        self.assertEqual("", git(self.ws / "Zones" / "Home", "status", "--porcelain").strip())
        self.assertNotIn("E2EMARK", "".join(p.read_text() for p in (self.ws / "Zones" / "Work").rglob("*.md")))
        self.assertEqual("", git(self.ws / "Zones" / "Work", "status", "--porcelain").strip())
        record = (self.state.home() / "operations" / (out["made"]["operation_id"] + ".json")).read_text()
        self.assertNotIn("E2EMARK", record)

    def test_the_whole_flow_on_the_handshake_revisions(self):
        self.check("legacy")

    def test_the_whole_flow_on_2026_07_28(self):
        self.check("2026-07-28")


if __name__ == "__main__":
    unittest.main()
