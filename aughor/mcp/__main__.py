"""Entry point: ``python -m aughor.mcp [--http] [--host H] [--port P]``.

Default transport is stdio — the form Claude Desktop / Claude Code / Cursor launch. The
``--http`` form serves streamable-HTTP for HTTP MCP clients (on 127.0.0.1:8765 by default,
deliberately not the API's :8000). It needs ``AUGHOR_MCP_TOKEN`` (DE-2a): every HTTP
client presents it as ``Authorization: Bearer …``, because the tools behind it call the API
with this process's own key and principal.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

from aughor.mcp.server import mcp, register_automation_tools, register_spotlight_tools, serve_http

_TOKEN_HELP = (
    "[aughor.mcp] --http needs AUGHOR_MCP_TOKEN. Every HTTP client presents it as "
    "`Authorization: Bearer <token>`; without one, anyone who reaches the port calls the API as this "
    "process. Make one with:  python -c \"import secrets; print(secrets.token_urlsafe(32))\""
)


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
    ap.add_argument(
        "--no-spotlight", action="store_true",
        help="Skip registering the Spotlight platform roster as tools (SP-5).",
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

    # SP-5 — the Spotlight roster is the arc's ONE declaration, served to every
    # transport; this transport registers from the API's listing under the same
    # never-fatal posture as the automations above.
    if not args.no_spotlight:
        added_sp = asyncio.run(register_spotlight_tools())
        if added_sp:
            print(f"[aughor.mcp] exposed the Spotlight roster ({len(added_sp)} tools)",
                  file=sys.stderr)

    if args.http:
        # DE-2a — a door on the HTTP transport, and the transport security built for the host actually served
        # (FastMCP fixed a loopback-only allowlist at import, so `--host 0.0.0.0` answered a remote client 421).
        token = os.environ.get("AUGHOR_MCP_TOKEN", "").strip()
        if not token:
            sys.exit(_TOKEN_HELP)
        serve_http(args.host, args.port, token)
    else:
        mcp.run()  # stdio — the default transport for Claude Desktop/Code/Cursor


if __name__ == "__main__":
    main()
