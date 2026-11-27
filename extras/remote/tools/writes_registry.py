"""writes_registry.py: the three write tools, prepare, execute and status, added to the MCP server.

Imports the SDK, so it runs in the extra's runtime only. The write tools are never marked read-only: a client
treats a prepare and an execute as writes and asks the owner before it runs one, while the status tool only reads.
"""

import sys

from mcp.server.mcpserver import Context

from . import common, manifest, writes

sys.dont_write_bytecode = True


def register(server, run, data):
    """Add prepare, execute and status. `run` is the registry's Runner.run. Returns the tool names."""
    from .registry import WRITE_EXECUTE, WRITE_PREPARE, WRITE_STATUS
    verbs = ", ".join(manifest.served_verbs(data))

    def tool(name, annotations, description):
        return server.tool(name=name, description=description, annotations=annotations)

    @tool("prepare", WRITE_PREPARE,
          "Prepare one change, and say what it would do. Nothing changes until execute. Verbs: %s. Each takes only its own fields: "
          "note-add (zone, project, thread, text, title), todo-add (zone, text, target, date), todo-done and todo-undo (zone, line), "
          "todo-date (zone, line, date), todo-edit (zone, line, text), todo-retire (zone, line, reason), park and wake (zone, project, thread), "
          "checkpoint (zone, project, thread, items, drop), "
          "wrap (zone, project, thread, resume with stands and all six rows, entry, message, todo, checkpoint). A wrap takes the words "
          "only: it never takes memory or lock. Returns an operation id." % verbs)
    async def prepare(ctx: Context, verb: str, zone: str, project: str | None = None, thread: str | None = None,
                      text: str | None = None, title: str | None = None, line: str | None = None, date: str | None = None,
                      target: str | None = None, reason: str | None = None, items: list[dict] | None = None,
                      drop: list[str] | None = None, operation_id: str | None = None, handle: str | None = None,
                      resume: dict | None = None, entry: str | None = None, message: str | None = None, todo: dict | None = None,
                      checkpoint: str | None = None, memory: dict | None = None, lock: str | None = None) -> dict:
        given = dict(project=project, thread=thread, text=text, title=title, line=line, date=date, target=target,
                     reason=reason, items=items, drop=drop)
        given.update({k: v for k, v in dict(resume=resume, entry=entry, message=message, todo=todo, checkpoint=checkpoint,
                                            memory=memory, lock=lock).items() if v is not None})
        return await run(ctx, "prepare", handle, lambda s: writes.Writes(s).prepare(verb, zone, operation_id, **given))

    @tool("execute", WRITE_EXECUTE,
          "Carry out a prepared change, once. It returns at once: ask for the status to see the receipt. Asking again with the same "
          "operation id never saves twice.")
    async def execute(ctx: Context, operation_id: str, handle: str | None = None) -> dict:
        return await run(ctx, "execute", handle, lambda s: writes.Writes(s).execute(operation_id))

    @tool("status", WRITE_STATUS, "The receipt of a change: whether it was saved, and what was saved. Safe to ask again.")
    async def status(ctx: Context, operation_id: str, handle: str | None = None) -> dict:
        return await run(ctx, "status", handle, lambda s: writes.Writes(s).status(operation_id))

    return ["prepare", "execute", "status"]
