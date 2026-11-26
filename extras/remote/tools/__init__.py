"""The tools the remote service offers a connected assistant.

`register(server, session_for)` is the one call the service makes. It adds the
five read tools and the write tools (prepare, execute, status) to the MCP
server, and nothing else. This file imports no third-party package, so the
manifest and the docs table can be read with the Python that macOS ships.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True


def register(server, session_for):
    """Add every tool to `server`. `session_for(ctx)` returns the Session of the grant that made
    the call, or raises."""
    from . import registry
    return registry.register(server, session_for)
