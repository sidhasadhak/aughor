"""Entry point: ``python -m aughor.mcp [--http] [--host H] [--port P]``.

Default transport is stdio — the form Claude Desktop / Claude Code / Cursor launch. The
``--http`` form serves streamable-HTTP for HTTP MCP clients (on 127.0.0.1:8765 by default,
deliberately not the API's :8000).
"""
from __future__ import annotations

import argparse

from aughor.mcp.server import mcp


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
    args = ap.parse_args()

    if args.http:
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.run(transport="streamable-http")
    else:
        mcp.run()  # stdio — the default transport for Claude Desktop/Code/Cursor


if __name__ == "__main__":
    main()
