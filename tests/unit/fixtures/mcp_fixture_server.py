"""A real MCP server for VA-9d's suite — one tool of each annotation shape.

A file rather than an in-process object because stdio is the transport being proven: an
in-memory session would exercise our classification and none of our plumbing. It is the
`test_mcp_server.py` "real-path layer" idea pointed outward.

The three tools are the three cases `classify()` must tell apart, and the third is the one
that matters: it declares NOTHING, which is what most real MCP tools do.
"""
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

mcp = FastMCP("VA-9d fixture")


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def read_the_weather(city: str) -> str:
    """Declared read-only, so Aughor may call it."""
    return f"It is bright and 21C in {city}."


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
def delete_everything(target: str) -> str:
    """Declared mutating, so Aughor lists it and refuses it."""
    return f"deleted {target}"


@mcp.tool()
def unannotated_thing(x: str) -> str:
    """Declares nothing — the majority case. The protocol reads silence as 'may modify'."""
    return f"did something with {x}"


if __name__ == "__main__":
    mcp.run()
