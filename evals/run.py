#!/usr/bin/env python3
"""Braintrust experiment runner for Aughor investigation quality evals.

Runs the agent graph DIRECTLY — no running server needed. Each golden Q&A
is fed into build_graph_generic() and the resulting AnalysisReport is scored
by the three custom scorers.

Usage:
    # Dry-run: run agent, print scores, no Braintrust push
    uv run python evals/run.py --dry-run

    # Full run: push results to Braintrust project 'aughor-investigations'
    BRAINTRUST_API_KEY=... uv run python evals/run.py

    # CI gate: fail if any metric regresses >5% vs last experiment
    uv run python evals/run.py --fail-on-regression 0.05

    # Limit to first N items (useful for smoke tests)
    uv run python evals/run.py --dry-run --limit 3
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

# Ensure repo root is on path so `aughor` and `evals` are importable
_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


# ── AgentState builder ────────────────────────────────────────────────────────

def _build_initial_state(
    question: str,
    connection_id: str,
    inv_id: str,
    schema: str,
) -> dict:
    """Return a fully-populated AgentState dict with safe defaults."""
    return {
        "question": question,
        "connection_id": connection_id,
        "investigation_id": inv_id,
        "trace_id": "",
        "schema_context": schema,
        "canvas_id": None,
        "canvas_schema_context": "",
        "hypotheses": [],
        "current_hypothesis_idx": 0,
        "query_history": [],
        "evidence_scores": [],
        "pitfalls": [],
        "prior_analyses": [],
        "iteration": 0,
        "max_iterations": int(os.getenv("AUGHOR_MAX_ITER", "6")),
        "report": None,
        "hitl_enabled": False,
        "human_feedback": None,
        "query_mode": None,
        "route_reasoning": None,
        "route_confidence": None,
        "replan_decision": None,
        "unresolved_tensions": [],
        "scan_context": "",
        "events_context": "",
        "sub_questions": [],
        "current_subq_idx": 0,
        "subq_answers": [],
        "explore_report": None,
        "investigation_phases": [],
        "ada_report": None,
        "_ada_intake": None,
        "current_plan": None,
        "_baseline_summary": None,
        "_baseline_passes": None,
        "_baseline_significant": None,
        "_baseline_sigma": None,
        "_decomp_summary": None,
        "_decomp_passes": None,
        "_dimensional_summary": None,
        "_dimensional_passes": None,
        "_behavioral_summary": None,
    }


# ── Single eval run ───────────────────────────────────────────────────────────

def run_single(record: dict) -> tuple[dict | None, dict]:
    """Run one golden record through the agent graph.

    Returns (report_dict, metadata) where metadata carries query_count and
    query_mode for the efficiency scorer.
    """
    from aughor.agent.graph import build_graph_generic
    from aughor.db.connection import open_connection_for

    question = record["question"]
    conn_id = record["connection_id"]
    inv_id = f"eval-{record['id']}"

    try:
        db = open_connection_for(conn_id)
    except Exception as exc:
        logger.error("Could not open connection %s: %s", conn_id, exc)
        return None, {"error": str(exc), "query_count": 0}

    try:
        schema = db.get_schema()
        agent = build_graph_generic(db, hitl=False)
        initial_state = _build_initial_state(question, conn_id, inv_id, schema)

        final_state = initial_state.copy()
        for event in agent.stream(
            initial_state,
            config={"configurable": {"thread_id": inv_id}},
        ):
            node_name = next(iter(event))
            final_state = {**final_state, **event[node_name]}

    except Exception as exc:
        logger.warning("Agent stream error for %s: %s", inv_id, exc)
        return None, {
            "error": str(exc),
            "query_count": len(final_state.get("query_history") or []),  # type: ignore[union-attr]
        }
    finally:
        db.close()

    report = final_state.get("report")
    if report is None:
        # explore_report or ada_report — normalise to a common dict shape
        ada = final_state.get("ada_report")
        explore = final_state.get("explore_report")
        if ada:
            report_dict = ada if isinstance(ada, dict) else {}
        elif explore:
            raw = explore.model_dump() if hasattr(explore, "model_dump") else explore
            report_dict = {
                "headline": raw.get("headline", ""),
                "verdict": raw.get("conclusion", ""),
                "key_findings": [],
                "what_is_not_the_cause": [],
                "data_quality_notes": raw.get("data_quality_notes", []),
                "risks": [],
                "recommended_actions": raw.get("recommended_actions", []),
            }
        else:
            report_dict = {}
    else:
        report_dict = report.model_dump() if hasattr(report, "model_dump") else dict(report)

    query_count = len(final_state.get("query_history") or [])
    return report_dict, {
        "query_count": query_count,
        "query_mode": final_state.get("query_mode"),
    }


# ── Scoring ───────────────────────────────────────────────────────────────────

def score_result(report_dict: dict | None, record: dict, meta: dict) -> dict:
    from evals.scorers import hallucination_rate, query_efficiency, verdict_accuracy

    scores: dict[str, float] = {}
    for scorer in (verdict_accuracy, hallucination_rate):
        r = scorer(report_dict, record)
        scores[r["name"]] = r["score"]
    r = query_efficiency(report_dict, record, metadata=meta)
    scores[r["name"]] = r["score"]
    return scores


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Aughor LLM Evals — Braintrust experiment runner"
    )
    parser.add_argument(
        "--dataset",
        default=str(Path(__file__).parent / "golden.jsonl"),
        help="Path to golden JSONL dataset",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the agent and print scores but do NOT push to Braintrust",
    )
    parser.add_argument(
        "--fail-on-regression",
        type=float,
        default=None,
        metavar="DELTA",
        help="Exit 1 if any metric regresses by more than DELTA vs last experiment (e.g. 0.05)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only evaluate the first N items (useful for smoke tests)",
    )
    args = parser.parse_args()

    # Load dataset
    records: list[dict] = []
    with open(args.dataset) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    if args.limit:
        records = records[: args.limit]

    print(f"Aughor LLM Evals — {len(records)} items", flush=True)
    if args.dry_run:
        print("(dry-run — results will NOT be pushed to Braintrust)\n", flush=True)

    # Init Braintrust experiment (unless dry-run)
    experiment = None
    if not args.dry_run:
        try:
            import braintrust  # type: ignore[import]
        except ImportError:
            print(
                "ERROR: braintrust not installed.\n"
                "  Install with:  pip install 'aughor[evals]'\n"
                "  Or use --dry-run to skip Braintrust push."
            )
            sys.exit(1)
        experiment = braintrust.init(project="aughor-investigations")

    all_scores: list[dict] = []

    for record in records:
        label = f"[{record['id']}]"
        print(f"  {label} {record['question'][:70]}...", flush=True)

        report_dict, meta = run_single(record)
        scores = score_result(report_dict, record, meta)
        all_scores.append(scores)

        score_str = "  ".join(f"{k}={v:.2f}" for k, v in scores.items())
        qmode = meta.get("query_mode") or "?"
        print(
            f"         {score_str}  "
            f"queries={meta.get('query_count', '?')}  mode={qmode}",
            flush=True,
        )

        if experiment is not None:
            experiment.log(
                input={
                    "question": record["question"],
                    "connection_id": record["connection_id"],
                },
                output=report_dict,
                expected=record,
                scores=scores,
                metadata=meta,
                id=record["id"],
            )

    # Summary table
    print("\n── Summary ──────────────────────────────")
    for metric in ("verdict_accuracy", "query_efficiency", "hallucination_rate"):
        vals = [s.get(metric, 0.0) for s in all_scores]
        avg = sum(vals) / len(vals) if vals else 0.0
        bar = "█" * int(avg * 20) + "░" * (20 - int(avg * 20))
        print(f"  {metric:<22} {bar}  {avg:.3f}")
    print()

    if experiment is not None:
        result = experiment.summarize()
        print(f"Braintrust experiment: {result.experiment_url}\n")

        if args.fail_on_regression is not None:
            deltas = result.score_deltas or {}
            regressions = [
                m
                for m, delta in deltas.items()
                if delta is not None and delta < -args.fail_on_regression
            ]
            if regressions:
                threshold_pct = args.fail_on_regression * 100
                print(
                    f"FAILED — regressions >{threshold_pct:.0f}% detected on: "
                    f"{', '.join(regressions)}"
                )
                sys.exit(1)
            print("No regressions detected ✓")


if __name__ == "__main__":
    main()
