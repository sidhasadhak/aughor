"""Aughor MCP server — exposes Aughor's GOVERNED intelligence as Model Context Protocol
tools (ask · deep_analysis · get_metric · list_findings · get_briefing · explore · jobs),
so any MCP client (Claude Desktop / Claude Code / Cursor) can ask Aughor a question and get
a verified answer with a Trust Receipt — not raw SQL.

The differentiator vs a generic text-to-SQL MCP: these tools return *governed* results.
Aughor writes and runs the SQL, grounds every number in real rows, enforces registered
metric definitions, and attaches the guards that fired. MotherDuck makes the *client*
smart; Aughor makes the *tool* smart.

Run it::

    python -m aughor.mcp           # stdio   (Claude Desktop/Code/Cursor)
    python -m aughor.mcp --http    # streamable-HTTP on 127.0.0.1:8765

It is a thin client over the running Aughor REST API (``AUGHOR_API_URL``, default
``http://127.0.0.1:8000``; ``AUGHOR_API_KEY`` optional), so every tool runs the exact
governed path the web app runs. Start the API first.
"""
from aughor.mcp.server import mcp

__all__ = ["mcp"]
