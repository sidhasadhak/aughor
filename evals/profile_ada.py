#!/usr/bin/env python3
"""Authoritative end-to-end ADA profile (SYNCHRONOUS driver).

Where do the seconds ACTUALLY go on a big warehouse? Three latency assumptions have
already fallen to measurement (faster model = slower; smaller schema = no help;
"8-15min" = ~1min in every ledger span). But node-spans only cover the graph's ada_*
nodes — they START at route_question, AFTER the heavy pre-graph setup (schema-link,
build_data_catalog which PROFILES every table on a 1.4M-row warehouse) and they SKIP
exploratory_scan. That invisible work is the prime suspect.

This replicates _stream_investigation's setup with per-step timing, then drives the
graph with a PLAIN SYNC loop (LangGraph's .stream() is synchronous — the router only
wraps it in _aiter_sync to bridge into async; that bridge has a StopIteration-into-
Future bug we sidestep here). Result: a full timeline of setup steps + per-node graph
timing + total, with nothing hidden.

Usage:  .venv/bin/python -u evals/profile_ada.py f809a5c6 "Why did catalog sales revenue fall?"
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
try:
    from dotenv import load_dotenv
    load_dotenv(_REPO_ROOT / ".env")
except ImportError:
    pass


def _t(label, fn):
    t0 = time.monotonic()
    try:
        out = fn()
        dt = time.monotonic() - t0
        print(f"  {label:34} {dt:7.1f}s")
        return out, dt
    except Exception as e:
        dt = time.monotonic() - t0
        print(f"  {label:34} {dt:7.1f}s  ERROR {str(e)[:60]}")
        return None, dt


def main(conn_id: str, question: str):
    import os
    os.environ.setdefault("AUGHOR_FALLBACK_DISABLED", "1")
    from aughor.db.connection import open_connection_for
    from aughor.routers.investigations import _get_schema_cached

    print(f"\n=== ADA profile (sync): conn={conn_id} ===\n{question}\n" + "-" * 66)
    start = time.monotonic()
    setup = {}

    db = open_connection_for(conn_id)
    full_schema, setup["schema"] = _t("schema fetch (_get_schema_cached)",
                                      lambda: _get_schema_cached(conn_id, db))
    full_schema = full_schema or ""
    schema = full_schema

    def _link():
        from aughor.tools.schema_linker import link_schema
        return link_schema(question, schema, top_k_tables=4, top_k_cols=8, connection_id=conn_id)
    linked_schema, setup["link"] = _t("schema_linker.link_schema", _link)
    schema = linked_schema or schema

    data_catalog = ""

    def _catalog():
        from aughor.tools.data_catalog import build_data_catalog
        from aughor.tools.schema import _parse_schema_tables, fk_neighbor_expand, temporal_dimension_tables
        linked_tables = list(_parse_schema_tables(schema).keys())
        if not linked_tables:
            return ""
        for _dt in temporal_dimension_tables(full_schema, linked_tables, question):
            if _dt not in linked_tables:
                linked_tables.append(_dt)
        linked_tables = fk_neighbor_expand(full_schema, linked_tables, cap=10)
        print(f"    (catalog profiling {len(linked_tables)} tables)")
        return build_data_catalog(db, linked_tables)
    data_catalog, setup["catalog"] = _t("build_data_catalog (table profiling)", _catalog)
    data_catalog = data_catalog or ""

    schema_for_agent = data_catalog if data_catalog else schema

    def _canon():
        from aughor.semantic.canonical import canonical_metrics_block
        # Mirror the patched router: pass the already-fetched schema so the metric
        # schema-filter doesn't re-introspect (the fix under test).
        return canonical_metrics_block(conn_id, None, schema_text=full_schema)
    canon, setup["canon"] = _t("canonical_metrics_block", _canon)
    if canon:
        schema_for_agent = f"{schema_for_agent}\n\n{canon}"

    setup_total = time.monotonic() - start
    print(f"  {'— SETUP SUBTOTAL —':34} {setup_total:7.1f}s   (schema_for_agent={len(schema_for_agent)} chars)")

    # ── Build graph + initial state, then drive the stream synchronously ──────────
    from aughor.agent.graph import build_graph_generic
    agent = build_graph_generic(db, hitl=False)
    inv_id = f"profile-{int(start)}"
    initial_state = {
        "question": question, "connection_id": conn_id, "investigation_id": inv_id,
        "trace_id": inv_id,
        "schema_context": schema_for_agent, "unresolved_tensions": [], "scan_context": "", "events_context": "",
        "hypotheses": [], "current_hypothesis_idx": 0, "query_history": [], "evidence_scores": [],
        "pitfalls": [], "prior_analyses": [], "iteration": 0,
        "max_iterations": int(os.getenv("AUGHOR_MAX_ITER", "6")),
        "report": None, "hitl_enabled": False, "human_feedback": None,
        "query_mode": None, "route_reasoning": None, "route_confidence": None, "replan_decision": None,
        "sub_questions": [], "current_subq_idx": 0, "subq_answers": [], "explore_report": None,
        "investigation_phases": [], "ada_report": None, "_ada_intake": None,
        "canvas_id": None, "canvas_schema_context": "",
        "data_catalog": data_catalog or "",
        "subq_data_portrait": {}, "final_text_answer": "",
    }

    print("\n  graph nodes (wall-clock between emitted events):")
    print(f"  {'node':28} {'Δ (s)':>8} {'t (s)':>8}")
    prev = time.monotonic()
    g0 = prev
    last_node = "(graph start)"
    for event in agent.stream(initial_state, config={"configurable": {"thread_id": inv_id}}):
        now = time.monotonic()
        node = next(iter(event))
        print(f"  {node:28} {now-prev:8.1f} {now-g0:8.1f}")
        prev = now
        last_node = node
    graph_total = time.monotonic() - g0

    total = time.monotonic() - start
    print("-" * 66)
    print(f"  setup   : {setup_total:7.1f}s   ({', '.join(f'{k}={v:.0f}s' for k,v in setup.items())})")
    print(f"  graph   : {graph_total:7.1f}s   (last node: {last_node})")
    print(f"  TOTAL   : {total:7.1f}s")


if __name__ == "__main__":
    conn = sys.argv[1] if len(sys.argv) > 1 else "f809a5c6"
    q = sys.argv[2] if len(sys.argv) > 2 else "Why did catalog sales revenue fall in the latest period compared to the prior period?"
    main(conn, q)
