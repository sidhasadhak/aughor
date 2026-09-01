"""Entry point: ``python -m aughor.mcp [--http] [--host H] [--port P]``.

Default transport is stdio — the form Claude Desktop / Claude Code / Cursor launch. The
``--http`` form serves streamable-HTTP for HTTP MCP clients (on 127.0.0.1:8765 by default,
deliberately not the API's :8000).
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from aughor.mcp.server import mcp, register_automation_tools


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="aughor.mcp", description="Aughor governed-intelligence MCP server"
    )
    ap.add_argument(
        "--http", action="store_true",
        help="Serve over streamable-HTTP instead of stdio (for HTTP MCP clients).",
    )
    ap.add_argument("--host", default="127.0.0.1", help="HTTP host (with --http).")
    ap.add_argument("--port", type=int, default=8765, help="HTTP port (with --http; default 8765).")
    ap.add_argument(
        "--no-automations", action="store_true",
        help="Skip registering this deployment's exposed automations as tools (DS-14).",
    )
    args = ap.parse_args()

    # DS-14 — the eighteen static tools are this VERSION's; the automations are this
    # DEPLOYMENT's, so they are read once here, before the transport starts serving.
    #
    # Before rather than during: a client asks for the tool list immediately after
    # connecting, and a tool registered after that answer is a tool the client will not
    # see until it reconnects. Keeping the whole registration ahead of `run()` means the
    # first `tools/list` is already complete and honest.
    #
    # Never fatal. `register_automation_tools` swallows its own failures and returns what
    # it managed; a server that refused to start because the API was down would withhold
    # the very tools you would use to find out why.
    if not args.no_automations:
        added = asyncio.run(register_automation_tools())
        if added:
            print(f"[aughor.mcp] exposed {len(added)} automation(s) as tools: "
                  f"{', '.join(added)}", file=sys.stderr)

    if args.http:
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.run(transport="streamable-http")
    else:
        mcp.run()  # stdio — the default transport for Claude Desktop/Code/Cursor


if __name__ == "__main__":
    main()
