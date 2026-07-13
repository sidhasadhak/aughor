"""Recover what the agent actually did, from the task_history table (Rec 4 · L3).

The eval/forensics companion to a live run: instead of parsing logs or an MLflow
trace, SELECT over the queryable span spine (flag ``obs.task_table``). Point it at
a run's trace id to recover the generated SQL + per-node latency; or list recent
runs / the slowest tasks for a "why was it slow?" pass.

    # a specific run (the SSE `investigation_id` / trace_id)
    .venv/bin/python -m evals.task_recover --trace <trace_id>

    # what the platform has been doing lately
    .venv/bin/python -m evals.task_recover --recent

    # slowest task families (e.g. only SQL, or only briefings)
    .venv/bin/python -m evals.task_recover --slow --prefix sql.

Requires the run to have been recorded with ``AUGHOR_OBS_TASK_TABLE=1``; an empty
result means the flag was off for that run.
"""
from __future__ import annotations

import argparse
import json

from aughor.obs import task_history as th


def _print_run(trace_id: str) -> None:
    run = th.recover_run(trace_id)
    if not run.spans:
        print(f"[task_recover] no spans for trace {trace_id!r} "
              f"(was AUGHOR_OBS_TASK_TABLE=1 during the run?)")
        return
    print(f"trace {trace_id}  ·  {len(run.spans)} spans  ·  {run.total_ms} ms wall")
    print("\n— generated SQL (execution order) —")
    for i, sql in enumerate(run.sql_statements, 1):
        print(f"  [{i}] {sql}")
    if not run.sql_statements:
        print("  (none)")
    print("\n— latency by task —")
    for task, ms in sorted(run.latency_by_task().items(), key=lambda kv: kv[1], reverse=True):
        print(f"  {ms:>9.1f} ms  {task}")
    errs = run.errors()
    if errs:
        print("\n— errors —")
        for s in errs:
            print(f"  {s['task']}: {s['error_message']}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--trace", help="recover one run by trace id")
    g.add_argument("--recent", action="store_true", help="list recent runs")
    g.add_argument("--slow", action="store_true", help="rank the slowest task families")
    p.add_argument("--prefix", default=None, help="task family filter for --slow (e.g. sql.)")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    args = p.parse_args()

    if args.trace:
        if args.json:
            print(json.dumps(th.recover_run(args.trace).__dict__, default=str, indent=2))
        else:
            _print_run(args.trace)
    elif args.recent:
        runs = th.recent_runs(limit=args.limit)
        if args.json:
            print(json.dumps(runs, indent=2))
        else:
            print(f"{'started':26} {'spans':>5} {'sql':>4} {'err':>4} {'ms':>9}  trace")
            for r in runs:
                print(f"{str(r['started'] or ''):26} {r['spans']:>5} {r['sql']:>4} "
                      f"{r['errors']:>4} {r['total_ms']:>9.1f}  {r['trace_id']}")
            if not runs:
                print("(no runs recorded — flag off, or nothing has run)")
    elif args.slow:
        rows = th.slow_tasks(task_prefix=args.prefix, limit=args.limit)
        if args.json:
            print(json.dumps(rows, indent=2))
        else:
            print(f"{'mean_ms':>9} {'max_ms':>9} {'count':>6}  task")
            for r in rows:
                print(f"{r['mean_ms']:>9.1f} {r['max_ms']:>9.1f} {r['count']:>6}  {r['task']}")
            if not rows:
                print("(no spans recorded — flag off, or nothing has run)")


if __name__ == "__main__":
    main()
