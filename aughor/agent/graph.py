"""LangGraph StateGraph — the investigative loop."""
from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Any

import duckdb
from langgraph.graph import END, StateGraph

from aughor.agent.nodes import (
    answer_text_only,
    decompose_question,
    exploratory_scan,
    plan_and_execute,
    plan_queries,
    execute_planned_queries,
    replan,
    route_after_classify,
    route_after_replan,
    route_question,
    score_evidence,
    should_continue,
    synthesize_report,
)
from aughor.agent.investigate import (
    ada_intake,
    ada_baseline,
    ada_decompose,
    ada_dimensional,
    ada_behavioral,
    ada_synthesize,
    route_after_baseline,
    route_after_decompose,
    route_after_dimensional,
)
from aughor.agent.explore import (
    decompose_exploration,
    exploratory_scan_subq,
    plan_and_execute_subq,
    reason_over_result,
    route_after_reason,
    synthesize_exploration,
)
from aughor.agent.state import AgentState
from aughor.tools.schema import build_schema_context

_CHECKPOINT_DB = Path(__file__).parent.parent.parent / "data" / "checkpoints.db"


def _checkpointer():
    import sqlite3
    from langgraph.checkpoint.sqlite import SqliteSaver
    conn = sqlite3.connect(str(_CHECKPOINT_DB), check_same_thread=False)
    return SqliteSaver(conn)


def _compile(execute_node, scan_node, explore_execute_node, explore_scan_subq_node=None, ada_nodes: dict = None, hitl: bool = False):
    graph = StateGraph(AgentState)

    # ── Shared entry ──────────────────────────────────────────────────────────
    graph.add_node("route_question", route_question)
    graph.set_entry_point("route_question")

    # ── ADA Investigate branch ────────────────────────────────────────────────
    ada = ada_nodes or {}
    graph.add_node("exploratory_scan", scan_node)
    graph.add_node("ada_intake",      ada.get("intake",      ada_intake))
    graph.add_node("ada_baseline",    ada.get("baseline",    lambda s: {"investigation_phases": s.get("investigation_phases", [])}))
    graph.add_node("ada_decompose",   ada.get("decompose",   lambda s: {"investigation_phases": s.get("investigation_phases", [])}))
    graph.add_node("ada_dimensional", ada.get("dimensional", lambda s: {"investigation_phases": s.get("investigation_phases", [])}))
    graph.add_node("ada_behavioral",  ada.get("behavioral",  lambda s: {"investigation_phases": s.get("investigation_phases", [])}))
    graph.add_node("ada_synthesize",  ada_synthesize)

    graph.add_edge("exploratory_scan",  "ada_intake")
    graph.add_edge("ada_intake",        "ada_baseline")

    graph.add_conditional_edges(
        "ada_baseline",
        route_after_baseline,
        {"ada_decompose": "ada_decompose", "ada_synthesize": "ada_synthesize"},
    )
    graph.add_conditional_edges(
        "ada_decompose",
        route_after_decompose,
        {"ada_dimensional": "ada_dimensional", "ada_synthesize": "ada_synthesize"},
    )
    graph.add_conditional_edges(
        "ada_dimensional",
        route_after_dimensional,
        {"ada_behavioral": "ada_behavioral", "ada_synthesize": "ada_synthesize"},
    )

    graph.add_edge("ada_behavioral",    "ada_synthesize")
    graph.add_edge("ada_synthesize",    END)

    # ── Direct query branch (plan-then-SQL) ───────────────────────────────────
    graph.add_node("answer_text_only", answer_text_only)  # KB-only, no SQL
    graph.add_node("plan_queries", plan_queries)          # no conn — pure LLM planning
    graph.add_node("execute_planned_queries", execute_node)  # conn via partial
    graph.add_node("score_evidence", score_evidence)
    graph.add_node("replan", replan)
    graph.add_node("synthesize", synthesize_report)

    graph.add_edge("answer_text_only", END)
    graph.add_edge("plan_queries", "execute_planned_queries")
    graph.add_edge("execute_planned_queries", "score_evidence")
    graph.add_edge("score_evidence", "replan")
    graph.add_conditional_edges(
        "replan",
        route_after_replan,
        {"plan_queries": "plan_queries", "synthesize": "synthesize"},
    )
    graph.add_edge("synthesize", END)

    # ── Explore branch ────────────────────────────────────────────────────────
    graph.add_node("exploratory_scan_explore", scan_node)
    graph.add_node("decompose_exploration", decompose_exploration)
    graph.add_node("plan_and_execute_subq", explore_execute_node)  # real SQL planner/executor
    graph.add_node("reason_over_result", reason_over_result)
    graph.add_node("synthesize_exploration", synthesize_exploration)

    graph.add_edge("exploratory_scan_explore", "decompose_exploration")
    # Optional mid-chain discovery scan before the planner. When provided, it
    # produces the per-sub-question Data Portrait; otherwise we plan directly.
    if explore_scan_subq_node is not None:
        graph.add_node("exploratory_scan_subq", explore_scan_subq_node)
        graph.add_edge("decompose_exploration", "exploratory_scan_subq")
        graph.add_edge("exploratory_scan_subq", "plan_and_execute_subq")
    else:
        graph.add_edge("decompose_exploration", "plan_and_execute_subq")
    graph.add_edge("plan_and_execute_subq", "reason_over_result")
    graph.add_conditional_edges(
        "reason_over_result",
        route_after_reason,
        {"plan_and_execute_subq": "plan_and_execute_subq", "synthesize_exploration": "synthesize_exploration"},
    )
    graph.add_edge("synthesize_exploration", END)

    # ── Routing from entry ────────────────────────────────────────────────────
    graph.add_conditional_edges(
        "route_question",
        route_after_classify,
        {
            "exploratory_scan": "exploratory_scan",
            "exploratory_scan_explore": "exploratory_scan_explore",
            "plan_queries": "plan_queries",
            "answer_text_only": "answer_text_only",
        },
    )

    interrupt_before = ["ada_synthesize"] if hitl else []
    return graph.compile(checkpointer=_checkpointer(), interrupt_before=interrupt_before)


def build_graph(conn: duckdb.DuckDBPyConnection):
    """Convenience builder for the CLI (raw DuckDB connection)."""
    from aughor.db.connection import DuckDBConnection
    db = DuckDBConnection.__new__(DuckDBConnection)
    db._conn = conn
    db._path = None
    db._connection_id = "cli"
    ada_nodes = {
        "baseline":   partial(ada_baseline,   conn=db),
        "decompose":  partial(ada_decompose,  conn=db),
        "dimensional": partial(ada_dimensional, conn=db),
        "behavioral": partial(ada_behavioral,  conn=db),
    }
    return _compile(
        partial(execute_planned_queries, conn=db),
        partial(exploratory_scan, conn=db),
        partial(plan_and_execute_subq, conn=db),   # real per-sub-question SQL planner
        partial(exploratory_scan_subq, conn=db),   # mid-chain discovery scan
        ada_nodes=ada_nodes,
    )


def build_graph_generic(db, hitl: bool = False):
    """Build the graph bound to any DatabaseConnection instance."""
    ada_nodes = {
        "baseline":    partial(ada_baseline,    conn=db),
        "decompose":   partial(ada_decompose,   conn=db),
        "dimensional": partial(ada_dimensional, conn=db),
        "behavioral":  partial(ada_behavioral,  conn=db),
    }
    return _compile(
        partial(execute_planned_queries, conn=db),
        partial(exploratory_scan, conn=db),
        partial(plan_and_execute_subq, conn=db),   # real per-sub-question SQL planner
        partial(exploratory_scan_subq, conn=db),   # mid-chain discovery scan
        ada_nodes=ada_nodes,
        hitl=hitl,
    )


def run_investigation(
    question: str,
    conn: duckdb.DuckDBPyConnection,
    on_node: Any = None,
) -> AgentState:
    from aughor.db.connection import DuckDBConnection
    db = DuckDBConnection.__new__(DuckDBConnection)
    db._conn = conn
    db._path = None
    db._connection_id = "cli"

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
        "prior_analyses": [],
        "scan_context": "",
        "events_context": "",
        "iteration": 0,
        "max_iterations": int(__import__("os").getenv("AUGHOR_MAX_ITER", "6")),
        "report": None,
        "hitl_enabled": False,
        "human_feedback": None,
        "query_mode": None,
        "unresolved_tensions": [],
        "connection_id": "",
        "trace_id": "",
        "route_reasoning": None,
        "route_confidence": None,
        "replan_decision": None,
        "sub_questions": [],
        "current_subq_idx": 0,
        "subq_answers": [],
        "explore_report": None,
        "investigation_phases": [],
        "ada_report": None,
        "_ada_intake": None,
        "current_plan": None,
        "data_catalog": "",
        "subq_data_portrait": {},
        "final_text_answer": "",
    }

    final_state = initial_state.copy()
    for event in agent.stream(initial_state):
        node_name = next(iter(event))
        partial_state = event[node_name]
        final_state = {**final_state, **partial_state}
        if on_node:
            on_node(node_name, final_state)

    return final_state
