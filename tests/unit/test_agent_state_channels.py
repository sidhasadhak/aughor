"""Every private channel a graph node READS must be DECLARED on AgentState — CA-0.

LangGraph filters each node's output dict to the keys declared on the state schema
(`langgraph/graph/state.py`: `[(k, v) for k, v in input.items() if k in output_keys]`).
A key a node writes but the schema does not declare is dropped at the node boundary,
and the downstream `state.get("_key")` reads None forever — silently. That is how
`_orchestration_plan` was null on 144 of 144 stored deep reports while the code that
built it ran on every one of them.

This is a rot guard, not a behaviour test: it scans the agent package for
`state.get("_…")` / `state["_…"]` reads and asserts each name is an AgentState
annotation. The next undeclared channel fails here instead of in a customer's PDF.
"""
from __future__ import annotations

import re
from pathlib import Path

from aughor.agent.state import AgentState

_AGENT_DIR = Path(__file__).resolve().parents[2] / "aughor" / "agent"
_READ_RE = re.compile(r'state(?:\.get\(|\[)\s*"(_[a-z][a-z0-9_]*)"')


def _private_channels_read() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for path in sorted(_AGENT_DIR.glob("*.py")):
        for name in _READ_RE.findall(path.read_text(errors="ignore")):
            found.setdefault(name, set()).add(path.name)
    return found


def test_every_private_channel_read_is_declared_on_agent_state():
    declared = set(AgentState.__annotations__)
    read = _private_channels_read()
    assert read, "scan found no private-channel reads — the regex rotted, not the code"
    undeclared = {k: sorted(v) for k, v in read.items() if k not in declared}
    assert not undeclared, (
        "private channels read from state but NOT declared on AgentState — LangGraph drops "
        f"the writes, so these reads are always None: {undeclared}"
    )


def test_the_channels_that_were_dead_are_now_declared():
    # The four found by the 2026-08-19 deep dive; listed by name so a refactor that
    # renames them has to come here and say so.
    for name in ("_orchestration_plan", "_baseline_rel_change", "_cross_section_summary", "_degenerate_seed"):
        assert name in AgentState.__annotations__, name


def test_compiled_graph_carries_the_plan_channel():
    """The annotation is the claim; the compiled graph's channel table is the proof.
    This is what LangGraph actually filters node output against."""
    import duckdb
    from aughor.agent.graph import build_graph

    graph = build_graph(duckdb.connect())
    channels = set(getattr(graph, "channels", {}).keys())
    assert channels, "compiled graph exposes no channel table — API changed; re-derive the proof"
    for name in ("_orchestration_plan", "_baseline_rel_change", "_cross_section_summary"):
        assert name in channels, f"{name} declared on AgentState but absent from the compiled graph"
