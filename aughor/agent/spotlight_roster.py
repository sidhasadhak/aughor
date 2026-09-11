"""SP-5 — the Spotlight roster, declared ONCE for every transport.

§3.11's first law is "one brain, many summons": palette, chat rail, Slack and the
MCP server are transports over ONE declared roster with one custody. The chat rail
and the palette already share it (both ride `/ask` → converse), and Slack does too
(the bot service drives the same `/ask` door). The MCP server was the transport
with its own hand-kept list — so the roster is now declared here, and every
consumer derives from this function:

* ``converse_tools`` concatenates it into the conversational roster (connection
  bound by closure, as always);
* the ``/spotlight/tools`` routes list and dispatch exactly it (the HTTP seam an
  out-of-process transport needs);
* the MCP server registers one tool per entry FROM that route at startup — same
  names, same descriptions, same bodies, one process writing the stores.

The parity ratchet (`test_spotlight_roster_parity.py`) diffs the transports
against this declaration and holds the diff at empty — a tool added to one side
without the others is a failing test, not a drift.
"""
from __future__ import annotations

from aughor.agent.tool_loop import ToolSpec


def spotlight_roster(connection_id: str, *, session_id: str = "") -> list[ToolSpec]:
    """Know + Act + Guide — the whole operator roster, in declaration order."""
    from aughor.agent.object_tools import object_tools
    from aughor.agent.spotlight_act import spotlight_act_tools
    from aughor.agent.spotlight_guide import spotlight_guide_tools
    from aughor.agent.spotlight_tools import spotlight_tools

    return (spotlight_tools(connection_id, session_id=session_id)
            + object_tools(connection_id, session_id=session_id)       # ON-3: one object, by type and key
            + spotlight_act_tools(connection_id, session_id=session_id)
            + spotlight_guide_tools(connection_id, session_id=session_id))
