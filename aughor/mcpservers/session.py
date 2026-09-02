"""VA-9d — opening a session to a foreign MCP server, and closing it again.

The transport layer, and nothing else: no policy, no governance, no classification. Those
live one layer up in `discover.py` and `call.py` so that a second caller cannot acquire a
connection without them — the `integrations/call.py` shape, where being the ONE door is
what makes refresh, the scope check, the cap, the span and the audit line impossible to
forget.

**Async under a sync caller.** The MCP SDK is async to its bones (`ClientSession`,
`stdio_client` and `streamablehttp_client` are all async context managers), while the
engine, the palette and the registry that consume this are sync. `asyncio.run` is not an
option: it is correct in a threadpool worker and a crash inside a running event loop, and
this code is reachable from both — the same trap `components/registry.py` documents when it
declines to call FastMCP's coroutine `list_tools()`. So every public entry here is a plain
sync function that runs its coroutine on a PRIVATE loop in a dedicated thread, which is
correct from either side and owns its own teardown.

**Timeouts are the whole safety story of a transport.** A stdio server that never speaks
would otherwise hold a worker forever, and an http server that accepts a connection and
stalls is the same hang wearing a different coat. Every call here is bounded, and the bound
is short: discovery and health are interactive operations, and a person waiting on a
spinner is better served by "it did not answer in 20 seconds" than by a truthful answer
they have already walked away from.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from contextlib import asynccontextmanager
from typing import Any, Optional

from aughor.mcpservers.models import McpServer

logger = logging.getLogger(__name__)

#: How long any single exchange with a foreign server may take. See the docstring: this is
#: an interactive bound, not a batch one.
DEFAULT_TIMEOUT_S = 20.0


class McpUnreachable(RuntimeError):
    """The server could not be reached, or did not answer in time.

    A distinct type because the surfaces above must tell "their server is down" apart from
    "we refused this" — the first sends a reader to somebody else's machine, the second is
    ours to explain, and a single exception class would make the two indistinguishable at
    exactly the moment a reader needs them separated.
    """


@asynccontextmanager
async def _open(server: McpServer, timeout_s: float):
    """An initialized `ClientSession` for this server, whichever transport it declares."""
    from mcp import ClientSession

    if server.transport == "stdio":
        from mcp.client.stdio import StdioServerParameters, stdio_client

        # `command` and `args` stay APART all the way down — no shell, ever. A single
        # command string would invite `shell=True` somewhere later, and a shell is how an
        # argument becomes a second command.
        params = StdioServerParameters(
            command=server.command, args=list(server.args or []),
            env=dict(server.env or {}) or None)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session
        return

    from mcp.client.streamable_http import streamablehttp_client

    headers = {"Authorization": server.auth_header} if server.auth_header else None
    async with streamablehttp_client(server.url, headers=headers, timeout=timeout_s) as (
            read, write, _get_session_id):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


def _run(coro_factory, timeout_s: float) -> Any:
    """Run one coroutine on a private loop in its own thread, bounded by ``timeout_s``.

    A private loop rather than `asyncio.run`, and a thread rather than the caller's:
    `asyncio.run` raises inside a running loop, and this module is called from sync engine
    code that may be a threadpool worker (no loop) or a FastAPI sync handler (a loop on
    another thread). One shape that is correct from both is worth the thread.
    """
    def _target():
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(asyncio.wait_for(coro_factory(), timeout_s))
        finally:
            # Cancel whatever the timeout left running before closing, or the loop closes
            # with pending tasks and the transport's subprocess is never reaped.
            try:
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True))
            except Exception as exc:  # noqa: BLE001 — teardown must not mask the result
                from aughor.kernel.errors import tolerate
                tolerate(exc, "mcp session teardown is best-effort; the loop closes either "
                              "way and the caller's result or error is what matters",
                         counter="mcpservers.teardown")
            loop.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_target)
        try:
            # A slightly longer outer bound than the inner one: the inner `wait_for` is the
            # real timeout and gives a clean cancellation, and this only catches a thread
            # that failed to honour it at all.
            return future.result(timeout=timeout_s + 10.0)
        except concurrent.futures.TimeoutError as exc:
            raise McpUnreachable("the server did not answer, and did not stop when asked") from exc


def list_tools(server: McpServer, *, timeout_s: float = DEFAULT_TIMEOUT_S) -> list:
    """Ask a server what it offers. Returns the SDK's `Tool` objects, unclassified.

    Raises :class:`McpUnreachable` for anything that is the server's fault or the
    network's. Classification is `discover.py`'s job and governance is `call.py`'s; this
    returns exactly what was said.
    """
    async def _go():
        async with _open(server, timeout_s) as session:
            return list((await session.list_tools()).tools)

    return _guarded(_go, timeout_s, server)


def call_tool(server: McpServer, name: str, arguments: Optional[dict] = None, *,
              timeout_s: float = DEFAULT_TIMEOUT_S):
    """Invoke one tool. Returns the SDK's `CallToolResult`, uninterpreted.

    Deliberately NOT the place that decides whether this tool may be called — `call.py`
    holds that, along with the cap, the span and the audit line, and a second caller
    reaching this directly is the thing a code review has to catch. It is one layer down
    from the door, not a second door.
    """
    async def _go():
        async with _open(server, timeout_s) as session:
            return await session.call_tool(name, arguments or {})

    return _guarded(_go, timeout_s, server)


def _guarded(coro_factory, timeout_s: float, server: McpServer):
    try:
        return _run(coro_factory, timeout_s)
    except McpUnreachable:
        raise
    except asyncio.TimeoutError as exc:
        raise McpUnreachable(f"no answer within {timeout_s:.0f}s") from exc
    except Exception as exc:  # noqa: BLE001 — every transport failure is one verdict here
        # The message, not the type: a reader debugging "why can't Aughor reach my server"
        # needs "No such file or directory: 'npx'", and `FileNotFoundError` alone sends
        # them looking in the wrong place. The type name rides along for the log.
        logger.warning("mcp server %s (%s) unreachable: %s: %s",
                       server.id, server.name, type(exc).__name__, exc)
        raise McpUnreachable(f"{type(exc).__name__}: {exc}") from exc
