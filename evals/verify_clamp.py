#!/usr/bin/env python3
"""Verify the WCH-DS coverage-clamp fix on REAL post-fix code (tested-first).

A post-fix-timestamped investigation (8fa5673c, 2026-06-11) still showed the
baseline filtering `order_date >= CURRENT_DATE - 13 months` → 0 rows on 2023-2024
data. But the live server was a STALE pre-fix process until just now, so that run
may have used pre-fix code. This runs the ADA graph from CURRENT code (fix live)
and dumps each phase's SQL + row counts so we can SEE whether the baseline now
fits the data window (2023-2024) or still uses CURRENT_DATE-relative (→ 0 rows).
"""
from __future__ import annotations
import sys, os
from pathlib import Path
_R = Path(__file__).parent.parent
sys.path.insert(0, str(_R))
try:
    from dotenv import load_dotenv; load_dotenv(_R / ".env")
except ImportError:
    pass
os.environ.setdefault("AUGHOR_FALLBACK_DISABLED", "1")

CONN = sys.argv[1] if len(sys.argv) > 1 else "workspace"
Q = sys.argv[2] if len(sys.argv) > 2 else "How did average order value trend over the last 12 months?"


def main():
    from aughor.db.connection import open_connection_for
    from aughor.routers.investigations import _get_schema_cached
    from aughor.agent.graph import build_graph_generic

    db = open_connection_for(CONN)
    full = _get_schema_cached(CONN, db)
    agent = build_graph_generic(db, hitl=False)
    inv = f"verify-clamp"
    state = {
        "question": Q, "connection_id": CONN, "investigation_id": inv, "trace_id": inv,
        "schema_context": full, "unresolved_tensions": [], "scan_context": "", "events_context": "",
        "hypotheses": [], "current_hypothesis_idx": 0, "query_history": [], "evidence_scores": [],
        "pitfalls": [], "prior_analyses": [], "iteration": 0, "max_iterations": 6,
        "report": None, "hitl_enabled": False, "human_feedback": None,
        "query_mode": None, "route_reasoning": None, "route_confidence": None, "replan_decision": None,
        "sub_questions": [], "current_subq_idx": 0, "subq_answers": [], "explore_report": None,
        "investigation_phases": [], "ada_report": None, "_ada_intake": None,
        "canvas_id": None, "canvas_schema_context": "", "data_catalog": "",
        "subq_data_portrait": {}, "final_text_answer": "",
    }
    print(f"=== verify clamp: conn={CONN} ===\nQ: {Q}\n" + "-" * 70)
    merged = dict(state)
    ran = []
    for event in agent.stream(state, config={"configurable": {"thread_id": inv}}):
        node = next(iter(event)); merged = {**merged, **event[node]}
        ran.append(node)
        if node == "route_question":
            print(f"[route] query_mode={merged.get('query_mode')} reason={(merged.get('route_reasoning') or '')[:60]}")
        # show the intake window the clamp produced
        if node == "ada_intake":
            ik = merged.get("_ada_intake") or {}
            print(f"[intake] metric={ik.get('metric_label')} table={ik.get('metric_table')} "
                  f"date_col={ik.get('date_column')}")
            print(f"[intake] observation = {ik.get('observation_start')} → {ik.get('observation_end')}  "
                  f"({ik.get('observation_label')})")
            print(f"[intake] comparison  = {ik.get('comparison_start')} → {ik.get('comparison_end')}")

    print("-" * 70)
    bad = 0
    for ph in merged.get("investigation_phases", []):
        for f in ph.get("findings", []):
            sql = (f.get("sql") or "").strip()
            if not sql:
                continue
            rc = f.get("row_count")
            uses_currentdate = "current_date" in sql.lower() or "now()" in sql.lower()
            flag = ""
            if uses_currentdate:
                flag += " ⚠CURRENT_DATE"
            if rc == 0 and not f.get("error"):
                flag += " ⚠0-ROWS"
            if flag:
                bad += 1
            print(f"\n[{ph.get('phase_id')}] rows={rc} err={bool(f.get('error'))}{flag}")
            print("  " + sql.replace("\n", "\n  ")[:600])
    print("\n" + "=" * 70)
    print(f"path: {' → '.join(ran)}")
    ada_ran = any(n.startswith("ada_") for n in ran)
    if not ada_ran:
        print("VERDICT: VACUOUS — investigate/baseline path did NOT run (routed elsewhere); test did not exercise the clamp.")
    else:
        print(f"VERDICT: {'BUG REPRODUCES' if bad else 'CLEAN (clamp held)'} — {bad} query(ies) flagged "
              f"(CURRENT_DATE-relative and/or 0-rows-without-error).")


if __name__ == "__main__":
    main()
