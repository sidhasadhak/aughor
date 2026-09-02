"""VA-9d — THE door. Every call to a foreign MCP tool passes through here.

One door, deliberately, and it is the same argument `integrations/call.py` makes for its
own: the allowlist check, the read-only gate, the outbound cap, the span and the audit line
all live at one address, so a second consumer inherits every one of them by construction
rather than by remembering. `session.py` can technically call a tool; that it is one layer
DOWN from this rather than a second way through is the thing a review has to protect.

**Five gates, in this order, and the order is the design.** The FOURTH is the write slice's,
and where it sits is the point: after the server's word has already failed to open the door,
and before anything reaches the wire.

1. **The server is on the allowlist and switched on.** Not "does the id look right" — the
   row is read. An empty allowlist refuses everything, which is this wave's off state.
2. **The tool is on the roster somebody discovered.** A name the roster does not carry is
   refused rather than passed through hopefully: forwarding an unknown name would make this
   an arbitrary-tool-call surface against a server, which is the URL-field shape §3.4
   refuses for `connection_call`.
3. **The tool is `callable`** — the server declared it read-only, and by the protocol's own
   defaults everything else (including silence) means it may modify. This is the ONLY gate
   that takes the counterparty's word, and it takes it for reads alone.
4. **Or a human granted it by name.** A tool that fails gate 3 is not refused outright any
   more: it runs if somebody ratified it, and only for the declaration they ratified. A
   grant whose pinned declaration no longer matches the roster is refused AND dropped here,
   because the door is the authority even though discovery revokes eagerly too. No grant at
   all is still the roster's own sentence, never a new wording.
5. **`govern.outbound`** — the cap before the work, the span around it, the `EXTERNAL_CALL`
   event after it on every path, now carrying `writes` so an auditor never has to join
   against the roster to learn which kind of call this was.

**Three outcomes, never flattened into two**, which is `integrations/call.py`'s discipline
and worth restating because it is subtle: `blocked` means nothing was sent (a budget
refused it, and the same call is legitimate next window); `failed` means the server
answered badly; `refused` means WE declined, and no amount of retrying changes it. A caller
that could not tell them apart would retry a refusal forever and give up on a cap.

**`uncertain` is the fifth outcome, and the write slice is why.** The read-only slice said
its absence was load-bearing and that the day writes landed it would come with them — this
is that day. A transport failure on a granted (mutating) call is not a failure to mutate:
the request may have arrived and been executed with only the answer lost, and reporting
that as `failed` invites a retry that performs the mutation twice. A failed READ is still
simply a failed read, so the status depends on which gate let the call through.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from aughor.mcpservers import store
from aughor.mcpservers.discover import tool_named
from aughor.mcpservers.models import (
    CALLABLE, GRANT_ACTIVE, GRANT_STALE, grant_verdict, service_name,
)
from aughor.mcpservers.session import McpUnreachable, call_tool

logger = logging.getLogger(__name__)

#: What comes back from a tool, capped. A foreign server's response is unbounded text and
#: this lands in a chain context that is stored, spanned and shown; refusing is not an
#: option for a read (the caller asked, and a truncated answer is still an answer), so this
#: TRUNCATES and says so in the same breath — the one place this module's "refuse, never
#: truncate" sibling rule does not apply, because the alternative is discarding work
#: already done by somebody else's machine.
MAX_RESULT_CHARS = 20_000


@dataclass
class McpCallResult:
    """``executed`` | ``refused`` | ``blocked`` | ``failed`` | ``uncertain`` — module docstring."""

    status: str
    message: str = ""
    #: True only for a call the grant plane authorized as mutating. Carried on the result so
    #: a dispatcher writing a step's outcome can tell a failed READ (safe to retry) from a
    #: failed WRITE (see `uncertain`) without re-reading the roster.
    writes: bool = False
    #: The tool's textual output, capped. Empty on every non-executed status.
    text: str = ""
    #: Whether `text` was cut. Carried rather than implied, so a reader is never shown a
    #: half answer that looks whole.
    truncated: bool = False
    data: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "executed"


def call(server_id: str, tool_name: str, arguments: Optional[dict] = None) -> McpCallResult:
    """Run one tool on one allowlisted server. Never raises.

    Never raises because every caller of this is a dispatcher deciding what to write on a
    step's outcome, and an exception there becomes a chain crash where a status was wanted.
    Every refusal above is a *status*, including the two the grant plane adds.
    """
    server = store.get_server(server_id)
    if server is None:
        return McpCallResult("refused", (
            f"No MCP server '{server_id}' is registered on this deployment. A server has to "
            f"be written down before anything here can reach it."))
    if not server.enabled:
        return McpCallResult("refused", (
            f"'{server.name or server.id}' is switched off. Turn it on to let this run."))

    tool = tool_named(server_id, tool_name)
    if tool is None:
        return McpCallResult("refused", (
            f"'{server.name or server.id}' has no discovered tool called '{tool_name}'. "
            f"Re-discover the server if it has changed — an undiscovered name is not "
            f"forwarded on the chance it exists."))
    if tool.disposition == CALLABLE:
        # The server's own word, believed for READS only — which is the whole of what the
        # read-only slice ever claimed, and is unchanged by the write slice.
        return _send(server, tool_name, arguments or {}, writes=False)

    # Not callable on the server's word. So it runs on a HUMAN's — or not at all.
    state, why = grant_verdict(tool, store.get_grant(server_id, tool_name))
    if state == GRANT_ACTIVE:
        return _send(server, tool_name, arguments or {}, writes=True)
    if state == GRANT_STALE:
        # Discovery revokes eagerly, but the door is the authority: a grant is never
        # honoured against a declaration nobody read, even if that pass did not run. Drop
        # it here too, so the refusal a caller sees and the state a surface renders cannot
        # disagree about whether the permission still exists.
        store.delete_grant(server_id, tool_name,
                           reason="declaration changed since the grant")
        return McpCallResult("refused", why)
    # The roster's own sentence, verbatim. Three wordings of one refusal is how a reader
    # learns the product has three opinions about it.
    return McpCallResult("refused", tool.reason)


def _send(server, tool_name: str, arguments: dict, *, writes: bool) -> McpCallResult:
    """The call itself, through the one outbound seam.

    `writes` is passed rather than re-derived from the roster, because the decision about
    whether this call may modify anything was already made by the four gates above and
    re-deriving it here would create a second place that could reach a different answer.
    """
    import uuid

    from aughor.govern.outbound import OutboundBlocked, external_call
    from aughor.telemetry import bind_trace, current_trace_id

    # A trace, or `session_log.emit` drops the audit line — see `discover()`'s note, which
    # is where this was found. A chain step already carries the run's trace (VA-4d), so
    # `current_trace_id()` is almost always set here and this only covers the caller that
    # is not a chain: a route, a script, or the agent when that slice lands. A call to a
    # third party that leaves no record is the one thing this door exists to prevent.
    with bind_trace(current_trace_id() or f"mcpcall_{uuid.uuid4().hex[:16]}"):
        return _through_the_seam(server, tool_name, arguments, external_call, OutboundBlocked,
                                 writes=writes)


def _through_the_seam(server, tool_name: str, arguments: dict,
                      external_call, OutboundBlocked, *, writes: bool) -> McpCallResult:
    try:
        with external_call(service_name(server), f"tools/call:{tool_name}",
                           attributes={"transport": server.transport,
                                       "tool": tool_name,
                                       "writes": writes}) as extra:
            # 🔴 On the EXTRA, not only in `attributes`. `external_call` puts `attributes`
            # on the mlflow span and emits `payload={"operation", **extra}` — two different
            # destinations — so a `writes` flag passed only above rides the span and never
            # reaches the ledger. The operation string is `tools/call:<name>` for reads and
            # writes alike, which means without this line the audit trail this slice is
            # accountable to cannot tell a granted mutation from a read. Same class of gap
            # as the missing trace in `discover()`: capped and spanned, and unrecorded.
            extra["writes"] = writes
            result = call_tool(server, tool_name, arguments)
            extra["is_error"] = bool(getattr(result, "isError", False))
    except OutboundBlocked as blocked:
        return McpCallResult("blocked", blocked.reason, writes=writes)
    except McpUnreachable as exc:
        if writes:
            # 🔑 The status this module's docstring promised the write slice would bring.
            # A transport failure on a WRITE is not a failure to write: the request may have
            # arrived and been executed, and only the answer lost. Reporting that as `failed`
            # invites a retry that performs the mutation twice, which is the one outcome a
            # write gate exists to prevent. `integrations/call.py` carries the same state for
            # the same reason.
            return McpCallResult("uncertain", (
                f"{server.name or server.id} did not answer: {exc}. This tool may modify "
                f"data, so it is NOT known whether the call took effect — check the server "
                f"before running it again."), writes=True)
        # A read that did not arrive is simply a failed read.
        return McpCallResult("failed", f"{server.name or server.id} was unreachable: {exc}")

    text, truncated = _text_of(result)
    if getattr(result, "isError", False):
        # The protocol's own in-band failure: a 200-shaped response carrying an error. Read
        # as success it would be `slackbots/post.py`'s bug — a message reported as sent that
        # never was — one plane over.
        return McpCallResult("failed", text or "the tool reported an error", writes=writes)
    return McpCallResult("executed", "", text=text, truncated=truncated, writes=writes,
                         data={"tool": tool_name, "server_id": server.id})


def _text_of(result: Any) -> tuple[str, bool]:
    """A tool result as text, capped. Returns ``(text, truncated)``.

    Only the text blocks, joined. A tool may also return images and embedded resources, and
    this slice does not carry them rather than pretending: a base64 image flattened into a
    chain context is a megabyte of noise no downstream step can read, and quietly dropping
    it while returning the surrounding text would make a partial answer look complete. When
    a consumer for those exists, they arrive typed.
    """
    parts: list[str] = []
    for block in (getattr(result, "content", None) or []):
        text = getattr(block, "text", None)
        if text:
            parts.append(str(text))
    joined = "\n".join(parts)
    if len(joined) > MAX_RESULT_CHARS:
        return joined[:MAX_RESULT_CHARS], True
    return joined, False
