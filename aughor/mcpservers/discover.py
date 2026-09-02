"""VA-9d — asking an allowlisted server what it offers, and deciding what we may call.

One function does the interesting thing (`discover`), and the interesting thing is the
classification. Everything else is bookkeeping.

**Discovery is an outbound call, so it rides the seam like any other.** It is easy to think
of `tools/list` as metadata rather than work — it fetches no data and changes nothing — but
it opens a connection to a third party, spawns a process on the stdio path, and is exactly
the call an attacker would want unbudgeted and unlogged. `govern.outbound` sees it, caps it
and records it, the same as a Slack post.

**Availability is measured, not probed** — `_integration_components()`'s law, and the
reason a roster row can be honest without a live round trip. A server's health here is the
verdict of the last discovery we ran, carried with the time we ran it, so every surface can
say "this is what they said, and this is when" instead of implying a list is live. A
palette that spawned a subprocess per render would be paying a process for a picture.
"""
from __future__ import annotations

import logging
from typing import Optional

from aughor.mcpservers import store
from aughor.mcpservers.models import CALLABLE, McpServer, McpTool, classify, service_name
from aughor.mcpservers.session import McpUnreachable, list_tools

logger = logging.getLogger(__name__)

#: Refused rather than truncated — `integrations/call.py`'s `MAX_ITEMS` rule. A server
#: offering more tools than this is not a server whose roster we quietly halve: a palette
#: showing 200 of 900 tools is a palette that lies about what is available, and the reader
#: cannot tell which half they got. The number is generous; real servers ship tens.
MAX_TOOLS = 250


class TooManyTools(RuntimeError):
    """A server offered more tools than we will render. Refused whole, never halved."""


def discover(server: McpServer) -> tuple[list[McpTool], str]:
    """Read this server's tools, classify each, store the roster. Returns ``(tools, "")``.

    Raises :class:`~aughor.mcpservers.session.McpUnreachable` when the server did not
    answer — deliberately NOT swallowed into an empty roster, because "they are down" and
    "they offer nothing" are different sentences and a caller that cannot tell them apart
    will show a reader the wrong one. An empty roster is a real, different answer.
    """
    import uuid

    from aughor.govern.outbound import OutboundBlocked, external_call
    from aughor.telemetry import bind_trace, current_trace_id

    # 🔴 A trace, or the audit line is DROPPED. Found by driving this live: the call was
    # capped and spanned exactly as designed, and `session_log.emit` discarded it —
    # deliberately, because "an event with no trace at all is dropped rather than written
    # orphaned". A chain step inherits the run's trace (VA-4d made the run id the trace
    # id), so the step path recorded fine; a discovery pressed from a ROUTE has no ambient
    # trace and recorded nothing. That is the wrong way round: discovery is the most
    # audit-worthy act on this surface, because it is the one that first opens a connection
    # — or spawns a process — against a newly written-down destination.
    #
    # Binding here rather than at the route, because the route is not the only caller
    # (`health` is one, and an agent will be) and an audit line that depends on which
    # entry point was used is one somebody will lose.
    with bind_trace(current_trace_id() or f"mcpdisc_{uuid.uuid4().hex[:16]}"):
        try:
            with external_call(service_name(server), "tools/list",
                               attributes={"transport": server.transport}) as extra:
                raw = list_tools(server)
                extra["tool_count"] = len(raw)
        except OutboundBlocked as blocked:
            # Nothing was sent; the budget refused it. Legitimate again next window.
            raise McpUnreachable(f"refused by a usage cap: {blocked.reason}") from blocked

    if len(raw) > MAX_TOOLS:
        raise TooManyTools(
            f"{server.name or server.id} offers {len(raw)} tools, more than the {MAX_TOOLS} "
            f"this deployment will render. Refusing the whole roster rather than showing "
            f"part of it — a partial list is one a reader cannot tell is partial.")

    tools = [_classify_one(server.id, t) for t in raw]
    store.save_roster(server.id, tools)
    # A declaration that moved takes its grant with it, here, before any surface renders the
    # new roster — see `store.revoke_stale_grants` for why the door checks again anyway.
    dropped = store.revoke_stale_grants(server.id, tools)
    if dropped:
        logger.info("discovery revoked %d grant(s) on %s whose declaration changed: %s",
                    len(dropped), server.name or server.id,
                    ", ".join(sorted(g.tool_name for g in dropped)))
    return tools, ""


def _classify_one(server_id: str, tool) -> McpTool:
    """One SDK `Tool` as our record, with our verdict on it."""
    ann = getattr(tool, "annotations", None)
    read_only = getattr(ann, "readOnlyHint", None) if ann is not None else None
    destructive = getattr(ann, "destructiveHint", None) if ann is not None else None
    disposition, reason = classify(read_only, destructive)
    return McpTool(
        server_id=server_id,
        name=str(getattr(tool, "name", "") or ""),
        title=str(getattr(tool, "title", "") or ""),
        description=str(getattr(tool, "description", "") or ""),
        input_schema=dict(getattr(tool, "inputSchema", None) or {}),
        disposition=disposition,
        reason=reason,
        read_only_hint=read_only,
        destructive_hint=destructive,
    )


def health(server: McpServer) -> dict:
    """Can we reach this server right now, and what did it say?

    A LIVE probe, unlike the roster — because this is the button a person presses when they
    are asking exactly that question, and answering it from a cache would answer a
    different one. `/health`'s shape: a verdict plus a sentence a human can act on.
    """
    try:
        tools, _ = discover(server)
    except TooManyTools as exc:
        return {"ok": False, "reason": str(exc), "tool_count": 0, "callable_count": 0}
    except McpUnreachable as exc:
        return {"ok": False, "reason": str(exc), "tool_count": 0, "callable_count": 0}
    callable_n = sum(1 for t in tools if t.disposition == CALLABLE)
    return {
        "ok": True,
        "reason": "",
        "tool_count": len(tools),
        "callable_count": callable_n,
        # Said plainly, because it is the number that surprises people: a server can be
        # perfectly healthy and offer this deployment nothing it may call.
        "detail": (f"{len(tools)} tools, {callable_n} callable here"
                   if tools else "reachable, and it offers no tools"),
    }


def tool_named(server_id: str, tool_name: str) -> Optional[McpTool]:
    """One tool from the STORED roster, or None. The call door's lookup.

    From the roster rather than a fresh `tools/list`, and that is a real decision: a call
    that re-discovered first would let a server change a tool's declaration between the
    human reading "read-only" on the palette and the engine calling it. The roster is what
    was reviewed; a change to it must go through a discovery somebody ran.

    The write slice leans on exactly this property. A grant pins the declaration it was
    given for, and the door compares it against THIS row — so the comparison is against
    what a human could have read, never against whatever the server happens to say at the
    moment of the call.
    """
    tools, _ = store.get_roster(server_id)
    return next((t for t in tools if t.name == tool_name), None)
