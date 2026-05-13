"""LangGraph StateGraph — the investigative loop."""
from __future__ import annotations

from functools import partial
from typing import Any

import duckdb
from langgraph.graph import END, StateGraph

from hermes.agent.nodes import (
    decompose_question,
    plan_and_execute,
    score_evidence,
    should_continue,
    synthesize_report,
)
from hermes.agent.state import AgentState
from hermes.tools.schema import build_schema_context


def _compile(execute_node):
    graph = StateGraph(AgentState)
    graph.add_node("decompose", decompose_question)
    graph.add_node("plan_and_execute", execute_node)
    graph.add_node("score_evidence", score_evidence)
    graph.add_node("synthesize", synthesize_report)
    graph.set_entry_point("decompose")
    graph.add_edge("decompose", "plan_and_execute")
    graph.add_edge("plan_and_execute", "score_evidence")
    graph.add_conditional_edges(
        "score_evidence",
        should_continue,
        {"plan_and_execute": "plan_and_execute", "synthesize": "synthesize"},
    )
    graph.add_edge("synthesize", END)
    return graph.compile()


def build_graph(conn: duckdb.DuckDBPyConnection):
    """Convenience builder for the CLI (raw DuckDB connection)."""
    from hermes.db.connection import DuckDBConnection
    db = DuckDBConnection.__new__(DuckDBConnection)
    db._conn = conn
    db._path = None
    return _compile(partial(plan_and_execute, conn=db))


def build_graph_generic(db):
    """Build the graph bound to any DatabaseConnection instance."""
    return _compile(partial(plan_and_execute, conn=db))


def run_investigation(
    question: str,
    conn: duckdb.DuckDBPyConnection,
    on_node: Any = None,
) -> AgentState:
    from hermes.db.connection import DuckDBConnection
    db = DuckDBConnection.__new__(DuckDBConnection)
    db._conn = conn
    db._path = None

    schema = build_schema_context(conn)
    agent = build_graph_generic(db)

    initial_state: AgentState = {
        "question": question,
        "schema_context": schema,
        "hypotheses": [],
        "current_hypothesis_idx": 0,
        "query_history": [],
        "evidence_scores": [],
        "pitfalls": [],
        "iteration": 0,
        "max_iterations": int(__import__("os").getenv("HERMES_MAX_ITER", "6")),
        "report": None,
    }

    final_state = initial_state.copy()
    for event in agent.stream(initial_state):
        node_name = next(iter(event))
        partial_state = event[node_name]
        final_state = {**final_state, **partial_state}
        if on_node:
            on_node(node_name, final_state)

    return final_state
