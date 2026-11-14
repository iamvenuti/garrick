#!/usr/bin/env python3
"""hold_tools.py: the one tool an engine session at Act has in place of every tool that sends, shares or deletes (#571).

An MCP server over stdio, started by the engine for one exchange:

    GARRICK_ENGINE_CHANNEL=ask GARRICK_ENGINE_ZONE=Work GARRICK_ENGINE_EXCHANGE=<id> python3 hold_tools.py

`hold` queues the action with what it would do and where (hold.py) and returns a line saying that nothing was done:
the owner decides, in a dialog or in the chat. The session cannot run the action itself, since the tool is not in it,
and cannot answer for the owner: a queued action runs only when the owner says yes. This server has no other tool, and
no tool that sends to Telegram: code delivers, and only to the paired private chat.

Standard library only, Python 3.9 or later.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import hold  # noqa: E402

SERVER = "garrick_hold"
TOOL = "hold"
SCHEMA = {"name": TOOL,
          "description": ("Queue an action that sends, shares or deletes, or writes under a shared folder, for the owner to "
                          "approve. Nothing is done now: the owner sees what it would do and where, and says yes or no. "
                          "Give `what` (one sentence: what it would do), `where` (its destination: an address, a folder, "
                          "a person), and either `tool` and `args` (the connector tool and its arguments) or, for a "
                          "write under a shared folder, `write` (its path inside the zone) and `text`."),
          "inputSchema": {"type": "object", "properties": {
              "what": {"type": "string"}, "where": {"type": "string"}, "tool": {"type": "string"},
              "args": {"type": "object"}, "write": {"type": "string"}, "text": {"type": "string"}},
              "required": ["what", "where"]}}


def call(args: dict) -> tuple:
    """(the text, whether it is an error)."""
    channel = os.environ.get("GARRICK_ENGINE_CHANNEL") or "ask"
    zone = os.environ.get("GARRICK_ENGINE_ZONE") or ""
    exchange = os.environ.get("GARRICK_ENGINE_EXCHANGE") or ""
    if not isinstance(args, dict) or not str(args.get("what") or "").strip():
        return "hold takes what the action would do and where.", True
    request = {}
    if args.get("write") is not None:
        request = {"write": str(args["write"]), "text": str(args.get("text") or "")}
    elif args.get("tool"):
        request = {"tool": str(args["tool"]), "args": args.get("args") if isinstance(args.get("args"), dict) else {}}
    else:
        return "hold takes a tool and its arguments, or a path under a shared folder and its text.", True
    try:
        entry = hold.add(channel, zone, exchange, args["what"], args.get("where") or "", request)
    except ValueError as e:
        return "Not queued: %s." % e, True
    return ("Queued as %s. Nothing has been done: the owner decides, and the action runs only after their yes." % entry["id"]), False


def handle(msg: dict):
    mid, method = msg.get("id"), msg.get("method")
    params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
    if mid is None:
        return None
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": params.get("protocolVersion") or "2024-11-05",
                                                        "capabilities": {"tools": {}}, "serverInfo": {"name": SERVER, "version": "1"}}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": [SCHEMA]}}
    if method == "tools/call":
        if params.get("name") != TOOL:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "unknown tool"}}
        text, bad = call(params.get("arguments") or {})
        return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}], "isError": bad}}
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found"}}


def serve(stdin=None, stdout=None) -> None:
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    for raw in stdin:
        text = raw.strip()
        try:
            msg = json.loads(text) if text else None
        except ValueError:
            msg = None
        out = handle(msg) if isinstance(msg, dict) else None
        if out is not None:
            stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
            stdout.flush()


if __name__ == "__main__":
    serve()
