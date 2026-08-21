"""LangGraph StateGraph — the investigative loop."""
from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Any

import duckdb
from langgraph.graph import END, StateGraph

from aughor.agent.nodes import (
    answer_text_only,
    exploratory_scan,
    plan_queries,
    execute_planned_queries,
    replan,
    route_after_classify,
    route_after_replan,
    route_question,
    score_evidence,
    synthesize_report,
)
from aughor.agent.phase_waves import ada_phase_wave
from aughor.agent.investigate import (
    ada_intake,
    ada_baseline,
    deep_breakdown,
    ada_cross_section,
    ada_cross_section_multilens,
    ada_decompose,
    ada_dimensional,
    ada_behavioral,
    ada_synthesize,
    route_after_intake,
    route_after_intake_clarify,
    route_after_baseline,
    route_after_decompose,
    route_after_dimensional,
)
from aughor.agent.explore import (
    decompose_exploration,
    exploratory_scan_subq,
    plan_and_execute_subq,
    plan_and_execute_wave,
    reason_over_result,
    route_after_reason,
    route_after_wave,
    synthesize_exploration,
)
from aughor.agent.state import AgentState
from aughor.tools.schema import build_schema_context

from aughor.db.sqlite_util import resolve_db_path, tune

_CHECKPOINT_DB = resolve_db_path("AUGHOR_CHECKPOINTS_DB", Path(__file__).parent.parent.parent / "data" / "checkpoints.db")


def _checkpointer():
    # Deliberately NOT on the connect_store seam: this connection belongs to
    # LangGraph's SqliteSaver, whose internals speak to it directly — wrapping it
    # is unproven territory. The Postgres story for checkpoints is the library's
    # own PostgresSaver (a swap recorded in docs/VERCEL_PLATFORM_DESIGN_2026-08-05.md
    # §6 Q4), not SQL translation.
    import sqlite3
    from langgraph.checkpoint.sqlite import SqliteSaver
    conn = tune(sqlite3.connect(str(_CHECKPOINT_DB), check_same_thread=False))
    return SqliteSaver(conn)


def read_checkpoint_values(investigation_id: str) -> dict:
    """The persisted state values of a checkpointed run, without building the graph.

    A cheap read for callers that need one field off a paused run (e.g. the
    resume door re-activating the run's user-agent persona from ``agent_id``).
    Returns {} when the run has no checkpoint."""
    cp = _checkpointer().get({"configurable": {"thread_id": investigation_id}})
    return dict((cp or {}).get("channel_values") or {})


def read_checkpoint_state(investigation_id: str) -> dict:
    """State values PLUS what the checkpoint itself records about progress —
    still without building the graph (Wave CR5b).

    ``agent.get_state(config).next`` — the authoritative "which node runs
    next" — needs a compiled graph over an open warehouse connection, which a
    read-only phase view must not pay for (and cannot, once the connection is
    gone). What the checkpoint DOES store is served instead: the step counter
    and which nodes wrote last, honestly labelled so a consumer never mistakes
    them for the interrupt point. Returns ``{"exists": False}`` when the run
    has no checkpoint.
    """
    tup = _checkpointer().get_tuple({"configurable": {"thread_id": investigation_id}})
    if tup is None:
        return {"exists": False, "values": {}}
    meta = dict(tup.metadata or {})
    writes = meta.get("writes")
    return {
        "exists": True,
        "values": dict((tup.checkpoint or {}).get("channel_values") or {}),
        "step": meta.get("step"),
        "last_writers": sorted(writes) if isinstance(writes, dict) else [],
    }


def _explore_parallel_enabled() -> bool:
    """Concurrent explore sub-question waves, transport-derived (A1 ModelProfile) — the
    former `explore.parallel_subq` flag, deleted by flag endgame Wave 6. Any resolution
    error means 'serial' (the safe, byte-identical sequential path)."""
    from aughor.llm.profile import parallel_waves_enabled
    return parallel_waves_enabled()


def topology_flags() -> dict:
    """The topology variants, resolved NOW — the public read for surfaces that render
    the graph a run would take (Wave CR5b). Since flag endgame Wave 6 all three follow
    ONE transport-derived decision (A1 ModelProfile); the dict keeps its per-variant
    shape because the CR surfaces render them as separate graph forks."""
    return {
        "ada_parallel_lenses": _ada_parallel_lenses_enabled(),
        "ada_parallel_phases": _ada_parallel_phases_enabled(),
        "explore_parallel": _explore_parallel_enabled(),
    }


def _ada_parallel_lenses_enabled() -> bool:
    """Concurrent deep-analysis lenses, transport-derived (A1 ModelProfile) — the former
    `deep_analysis.parallel_lenses` flag, deleted by flag endgame Wave 6. → serial on any error."""
    from aughor.llm.profile import parallel_waves_enabled
    return parallel_waves_enabled()


def _ada_parallel_phases_enabled() -> bool:
    """Concurrent deep-analysis middle phases, transport-derived (A1 ModelProfile) — the former
    `deep_analysis.parallel_phases` flag, deleted by flag endgame Wave 6. → serial on any error."""
    from aughor.llm.profile import parallel_waves_enabled
    return parallel_waves_enabled()


def _compile(execute_node, scan_node, explore_execute_node, explore_scan_subq_node=None,
             explore_wave_node=None, ada_nodes: dict = None, hitl: bool = False, plan_gate: bool = False,
             clarify_gate: bool = False):
    graph = StateGraph(AgentState)

    # ── Shared entry ──────────────────────────────────────────────────────────
    graph.add_node("route_question", route_question)
    graph.set_entry_point("route_question")

    # ── ADA Investigate branch ────────────────────────────────────────────────
    ada = ada_nodes or {}
    graph.add_node("exploratory_scan", scan_node)
    graph.add_node("ada_intake",      ada.get("intake",      ada_intake))
    graph.add_node("ada_baseline",    ada.get("baseline",    lambda s: {"investigation_phases": s.get("investigation_phases", [])}))
    graph.add_node("deep_breakdown",   ada.get("breakdown",   lambda s: {"investigation_phases": s.get("investigation_phases", [])}))
    graph.add_node("ada_cross_section", ada.get("cross_section", lambda s: {"investigation_phases": s.get("investigation_phases", [])}))
    graph.add_node("ada_decompose",   ada.get("decompose",   lambda s: {"investigation_phases": s.get("investigation_phases", [])}))
    graph.add_node("ada_dimensional", ada.get("dimensional", lambda s: {"investigation_phases": s.get("investigation_phases", [])}))
    graph.add_node("ada_behavioral",  ada.get("behavioral",  lambda s: {"investigation_phases": s.get("investigation_phases", [])}))
    graph.add_node("ada_synthesize",  ada_synthesize)

    # Parallel multi-lens cross-section (transport-derived, A1 ModelProfile) — a cross-sectional
    # "why" question runs independent lenses (segment/where ∥ mechanism/why) concurrently instead of
    # one bundled scan. route_after_intake still returns "ada_cross_section"; we just repoint that
    # target to the multilens node when the transport allows waves. Serial → the single scan.
    _xsec_node = ada.get("cross_section_multilens")
    _xsec_target = "ada_cross_section"
    if _xsec_node is not None and _ada_parallel_lenses_enabled():
        graph.add_node("ada_cross_section_multilens", _xsec_node)
        graph.add_edge("ada_cross_section_multilens", "ada_synthesize")
        _xsec_target = "ada_cross_section_multilens"

    # Parallel phase wave (transport-derived, A1 ModelProfile) — the temporal chain's middle
    # phases (baseline ∥ decompose ∥ dimensional) run as ONE wave node; the serial tier-routers'
    # early-stop semantics are applied post-hoc inside it (phase_waves.py). Behavioral stays
    # sequential (it hard-depends on the dimensional dominant finding). Serial transport →
    # the classic serial chain below, byte-identical.
    _wave_node = ada.get("phase_wave")
    _baseline_target = "ada_baseline"
    if _wave_node is not None and _ada_parallel_phases_enabled():
        from aughor.agent.phase_waves import route_after_wave as route_after_phase_wave
        graph.add_node("ada_phase_wave", _wave_node)
        graph.add_conditional_edges(
            "ada_phase_wave",
            route_after_phase_wave,
            {"ada_behavioral": "ada_behavioral", "ada_synthesize": "ada_synthesize"},
        )
        _baseline_target = "ada_phase_wave"

    # A breakdown answers in one phase — there is no tier to escalate to, because
    # nothing here was found wanting.
    graph.add_edge("deep_breakdown", "ada_synthesize")

    graph.add_edge("exploratory_scan",  "ada_intake")
    # P4 clarify_gate: a single-fire pause AFTER intake, BEFORE the scan fan-out — reached ONLY when
    # ada_intake stashed a material metric-reading ambiguity (`_clarify_pending`). A no-op passthrough
    # (mirrors plan_gate): the NODE is added unconditionally so a paused run can reconnect its checkpoint
    # on resume, but the INTERRUPT is armed only when `clarify_gate` is on (below). `route_after_intake_clarify`
    # is byte-identical to `route_after_intake` when nothing is pending, so with the flag off the run never
    # touches the gate and behaviour is unchanged. On resume the passthrough runs once and route_after_intake
    # picks the real branch from the (now user-bound) intake.
    graph.add_node("clarify_gate", lambda s: {})
    graph.add_conditional_edges(
        "ada_intake",
        route_after_intake_clarify,
        {"clarify_gate": "clarify_gate", "ada_cross_section": _xsec_target,
         "ada_baseline": _baseline_target, "deep_breakdown": "deep_breakdown"},
    )
    graph.add_conditional_edges(
        "clarify_gate",
        route_after_intake,
        {"ada_cross_section": _xsec_target, "ada_baseline": _baseline_target,
         "deep_breakdown": "deep_breakdown"},
    )

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

    graph.add_edge("ada_cross_section", "ada_synthesize")
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
    graph.add_node("synthesize_exploration", synthesize_exploration)
    # Plan gate (P3): a single-fire pause point AFTER decomposition and BEFORE the
    # expensive fan-out, so the user can review/edit the sub-question plan before it
    # runs (and a mis-scoped plan is corrected for $0). A no-op passthrough; the
    # interrupt is armed only when `plan_gate` is on. It sits here — not on
    # plan_and_execute_subq — because that node runs once PER sub-question in a loop,
    # so interrupting it would pause on every question instead of once up front.
    graph.add_node("plan_gate", lambda s: {})
    graph.add_edge("exploratory_scan_explore", "decompose_exploration")
    graph.add_edge("decompose_exploration", "plan_gate")

    # Parallel wave executor (transport-derived, A1 ModelProfile) — after the plan gate, independent
    # sub-questions run concurrently in dependency-respecting waves (one node folds in the
    # per-sub-question discovery scan + plan + execute + reason and fans out over
    # ContextThreadPoolExecutor; the router loops it until the chain is exhausted). Serial
    # transport → the byte-identical sequential chain below. See docs/PARALLEL_MULTIAGENT_GROUNDWORK.md.
    if explore_wave_node is not None and _explore_parallel_enabled():
        graph.add_node("plan_and_execute_wave", explore_wave_node)
        graph.add_edge("plan_gate", "plan_and_execute_wave")
        graph.add_conditional_edges(
            "plan_and_execute_wave",
            route_after_wave,
            {"plan_and_execute_wave": "plan_and_execute_wave",
             "synthesize_exploration": "synthesize_exploration"},
        )
    else:
        graph.add_node("plan_and_execute_subq", explore_execute_node)  # real SQL planner/executor
        graph.add_node("reason_over_result", reason_over_result)
        # Optional mid-chain discovery scan before the planner. When provided, it
        # produces the per-sub-question Data Portrait; otherwise we plan directly.
        if explore_scan_subq_node is not None:
            graph.add_node("exploratory_scan_subq", explore_scan_subq_node)
            graph.add_edge("plan_gate", "exploratory_scan_subq")
            graph.add_edge("exploratory_scan_subq", "plan_and_execute_subq")
        else:
            graph.add_edge("plan_gate", "plan_and_execute_subq")
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

    interrupt_before = (["ada_synthesize"] if hitl else []) + (["plan_gate"] if plan_gate else []) \
        + (["clarify_gate"] if clarify_gate else [])
    return graph.compile(checkpointer=_checkpointer(), interrupt_before=interrupt_before)


def build_graph(conn: duckdb.DuckDBPyConnection):
    """Convenience builder for the CLI (raw DuckDB connection)."""
    from aughor.db.connection import DuckDBConnection
    db = DuckDBConnection.__new__(DuckDBConnection)
    db._conn = conn
    db._path = None
    db._connection_id = "cli"
    ada_nodes = {
        "intake":     partial(ada_intake,     conn=db),
        "baseline":   partial(ada_baseline,   conn=db),
        "breakdown":  partial(deep_breakdown,  conn=db),
        "cross_section": partial(ada_cross_section, conn=db),
        "cross_section_multilens": partial(ada_cross_section_multilens, conn=db),
        "phase_wave":  partial(ada_phase_wave, conn=db),
        "decompose":  partial(ada_decompose,  conn=db),
        "dimensional": partial(ada_dimensional, conn=db),
        "behavioral": partial(ada_behavioral,  conn=db),
    }
    return _compile(
        partial(execute_planned_queries, conn=db),
        partial(exploratory_scan, conn=db),
        partial(plan_and_execute_subq, conn=db),   # real per-sub-question SQL planner
        partial(exploratory_scan_subq, conn=db),   # mid-chain discovery scan
        explore_wave_node=partial(plan_and_execute_wave, conn=db),  # parallel wave (transport-gated)
        ada_nodes=ada_nodes,
    )


def build_graph_generic(db, hitl: bool = False, plan_gate: bool = False, clarify_gate: bool = False):
    """Build the graph bound to any DatabaseConnection instance."""
    ada_nodes = {
        "intake":      partial(ada_intake,      conn=db),
        "baseline":    partial(ada_baseline,    conn=db),
        "breakdown":  partial(deep_breakdown,  conn=db),
        "cross_section": partial(ada_cross_section, conn=db),
        "cross_section_multilens": partial(ada_cross_section_multilens, conn=db),
        "phase_wave":  partial(ada_phase_wave, conn=db),
        "decompose":   partial(ada_decompose,   conn=db),
        "dimensional": partial(ada_dimensional, conn=db),
        "behavioral":  partial(ada_behavioral,  conn=db),
    }
    return _compile(
        partial(execute_planned_queries, conn=db),
        partial(exploratory_scan, conn=db),
        partial(plan_and_execute_subq, conn=db),   # real per-sub-question SQL planner
        partial(exploratory_scan_subq, conn=db),   # mid-chain discovery scan
        explore_wave_node=partial(plan_and_execute_wave, conn=db),  # parallel wave (transport-gated)
        ada_nodes=ada_nodes,
        hitl=hitl,
        plan_gate=plan_gate,
        clarify_gate=clarify_gate,
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
        "answer_report": None,
        "_ada_intake": None,
        "current_plan": None,
        "data_catalog": "",
        "subq_data_portrait": {},
        "final_text_answer": "",
    }

    final_state = initial_state.copy()
    import uuid
    config = {"configurable": {"thread_id": f"cli-{uuid.uuid4().hex[:12]}"}}
    for event in agent.stream(initial_state, config=config):
        node_name = next(iter(event))
        partial_state = event[node_name]
        final_state = {**final_state, **partial_state}
        if on_node:
            on_node(node_name, final_state)

    return final_state
