"""registry.py: adds the tools to the MCP server.

This is the one module of the tools that imports the SDK. It runs in the extra's runtime only. A tool takes the
SDK's Context, hands it to `session_for` for the grant's Session, checks the handle if the request carries one,
runs the work off the event loop, and answers with a dict that holds a fresh handle. A refusal is a dict with an
`error` code and a plain `say`; it carries no handle.

The read tools carry the read-only annotation, so that a client can let them run without a prompt and treat them
apart from the writes. The write tools are separate tools (prepare, execute, status), never marked read-only.
"""

import logging
import sys
import time

import anyio
from mcp.server.mcpserver import Context
from mcp_types import ToolAnnotations

from . import common, manifest, reads

sys.dont_write_bytecode = True

LOG = logging.getLogger("garrick.remote.tools")
READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
WRITE_PREPARE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
WRITE_EXECUTE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
WRITE_STATUS = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)


class Runner:
    """What every tool does around its own work: the grant, the handle, the thread, the log line."""

    def __init__(self, session_for):
        self.session_for = session_for

    async def run(self, ctx, name, handle, work, with_handle=True):
        started = time.monotonic()
        grant, outcome = "", "refused"
        try:
            try:
                session = self.session_for(ctx)
            except Exception:
                return common.refusal("not_signed_in", "This connection is not signed in. Add the connector again.")
            grant = str(getattr(session, "grant_id", ""))
            bad = common.check_handle(session, handle)
            if bad is not None:
                return bad
            try:
                result = await anyio.to_thread.run_sync(work, session)
            except Exception:
                outcome = "failed"
                return common.refusal("failed", "That did not work.")
            if isinstance(result, dict) and "error" not in result:
                outcome = "ok"
                if with_handle:
                    result = dict(result, handle=session.new_handle())
            return result
        finally:
            LOG.info("tool=%s grant=%s outcome=%s ms=%d", name, grant, outcome, int((time.monotonic() - started) * 1000))


def register(server, session_for):
    """Add the five read tools and the write tools to `server`; the tool list is the manifest's served rows."""
    data = manifest.load()
    served = set(manifest.served_tools(data))
    run = Runner(session_for).run
    state = {"names": []}

    def add(name, annotations, description):
        state["names"].append(name)
        return server.tool(name=name, description=description, annotations=annotations)

    if "places" in served:
        @add("places", READ, "The projects and threads this connection may reach, with their status. Name a zone to list only that one.")
        async def places(ctx: Context, zone: str | None = None, handle: str | None = None) -> dict:
            return await run(ctx, "places", handle, lambda s: reads.Reads(s).places(zone))

    if "thread_state" in served:
        @add("thread_state", READ, "Where a thread or a project stands: its Resume here block, the next action, who it waits on. "
                                   "Name the place as Project, Project/Thread or Zone/Project/Thread.")
        async def thread_state(ctx: Context, place: str, offset: int | None = None, handle: str | None = None) -> dict:
            return await run(ctx, "thread_state", handle, lambda s: reads.Reads(s).thread_state(place, offset))

    if "search" in served:
        @add("search", READ, "Look for records: meetings, the library, threads and Garrick's docs. Returns ids, dates, sources and titles "
                             "with a snippet. Name a project or a thread in `place` to narrow it.")
        async def search(ctx: Context, words: str, place: str | None = None, kind: str | None = None, order: str | None = None,
                         limit: int | None = None, after: str | None = None, handle: str | None = None) -> dict:
            return await run(ctx, "search", handle, lambda s: reads.Reads(s).search(words, place, kind or "all", order, limit, after))

    if "read" in served:
        @add("read", READ, "The text of a record, by an id that search, thread_state or owed returned. A long record comes in parts: "
                           "the answer says the offset of the next one.")
        async def read(ctx: Context, id: str, offset: int | None = None, handle: str | None = None) -> dict:
            return await run(ctx, "read", handle, lambda s: reads.Reads(s).read(id, offset))

    if "owed" in served:
        @add("owed", READ, "What the owner owes or waits on: the Todo lines and the threads' next actions. Period is a date, "
                           "today, tomorrow, this week or this month.")
        async def owed(ctx: Context, period: str | None = None, party: str | None = None, waiting: bool | None = None,
                       handle: str | None = None) -> dict:
            return await run(ctx, "owed", handle, lambda s: reads.Reads(s).owed(period, party, waiting))

    return state["names"]
