"""Size a grid from MEASUREMENT before committing hours to it.

Defaults to the L3 (`closed_loop`) cells; point FLAG/SUITE at any other A/B.

Two things nobody has measured on the wide (102-case) suite:
  * per-case wall time — L2's ~1 min/case came from a 22-case suite whose questions may be
    shorter than the 102-case corpus L5 widened into;
  * requests per case — the binding constraint is the 1,000/day free allowance, and a grid
    that exhausts it mid-run produces a half-null result that looks like a finding.

Counted at `httpx.Client.send`, one layer below the lowest thing we own. Counting at the
pacer once proved the gate correct while the SDK made 2 of every 3 requests invisibly; the
SDK retry default is 0 now, so provider-level and HTTP-level counts SHOULD agree — this
prints both so "should" is checked rather than assumed.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time

PILOT_CASES = int(os.environ.get("PILOT_CASES", "8"))
WIDE_SUITE = os.environ.get("SUITE", "9c1e13e458ff")
FLAG = os.environ.get("FLAG", "explore.route_wide")
PILOT_SUITE_NAME = f"grid sizing pilot — {FLAG} ({PILOT_CASES} cases)"
#: CWD (or `GRID_OUT_DIR`), never beside the script — a run artifact written into `scripts/`
#: shows up as untracked source and invites being committed.
OUT = (pathlib.Path(os.environ.get("GRID_OUT_DIR") or ".")
       / f"grid_pilot_{FLAG.replace('.', '_')}.json")

# ── count real HTTP requests to the model provider ───────────────────────────────
import httpx  # noqa: E402

_http = {"total": 0, "by_host": {}}
_orig_send = httpx.Client.send


def _counting_send(self, request, **kw):
    try:
        host = request.url.host or "?"
        _http["total"] += 1
        _http["by_host"][host] = _http["by_host"].get(host, 0) + 1
    except Exception:
        pass
    return _orig_send(self, request, **kw)


httpx.Client.send = _counting_send

from aughor.evals import store  # noqa: E402
from aughor.evals.experiments import Cell  # noqa: E402
from aughor.evals.runner import run_experiment  # noqa: E402
from aughor.evals.targets import ask_target  # noqa: E402


def pilot_suite() -> str:
    """A small suite carved from the wide corpus — same questions, fewer of them."""
    existing = next((s for s in store.list_suites(200) if s["name"] == PILOT_SUITE_NAME), None)
    if existing is None:
        existing = store.create_suite(
            PILOT_SUITE_NAME,
            description=("Sizing pilot for the L3 grid: the first N cases of the 102-case "
                         "consistency corpus, run through both closed_loop cells to measure "
                         "per-case latency and requests-per-case before committing hours."),
            target="reference", connection_id="workspace")
    sid = existing["id"]
    if not store.list_cases(sid):
        wide = store.list_cases(WIDE_SUITE, limit=500)[:PILOT_CASES]
        store.add_cases(sid, [
            {"question": c.get("question", ""), "artifact": c.get("artifact", ""),
             "expected": c.get("expected") or {}, "tags": ["l3", "pilot"]}
            for c in wide
        ])
    return sid


def main() -> int:
    suite_id = pilot_suite()
    n_cases = len(store.list_cases(suite_id))
    print(f"pilot suite {suite_id}: {n_cases} cases (from the {WIDE_SUITE} corpus)")
    print(f"cells: {FLAG} off | on   ·   replicates=1   ·   freeze=True   ·   conn=workspace")
    print()

    cells = [
        Cell(label=f"{FLAG}_off", flags={FLAG: False}),
        Cell(label=f"{FLAG}_on", flags={FLAG: True}),
    ]

    t0 = time.monotonic()
    http_start = _http["total"]
    results = run_experiment(
        suite_id,
        lambda: ask_target("workspace", depth="quick"),
        cells,
        replicates=1,
        connection_id="workspace",
        freeze=True,
    )
    elapsed = time.monotonic() - t0
    http_used = _http["total"] - http_start

    invocations = 0
    out = {"suite_id": suite_id, "cases": n_cases, "elapsed_s": round(elapsed, 1), "cells": []}
    for r in results:
        d = r.to_dict()
        runs = [run.to_dict() for run in r.runs]
        invocations += sum(int(run.get("total", 0)) for run in runs)
        out["cells"].append({
            "label": r.label,
            "error": r.error,
            "discrepancies": r.discrepancies,
            "warnings": r.warnings,
            "runs": [{"run_id": run.get("run_id"), "pass_rate": run.get("pass_rate"),
                      "total": run.get("total"), "errors": run.get("errors"),
                      "flaky": run.get("flaky")} for run in runs],
        })
        print(f"cell {r.label:18} error={r.error or '-'}")
        for run in runs:
            print(f"    run {run.get('run_id')}  total={run.get('total')}  "
                  f"pass_rate={run.get('pass_rate')}  errors={run.get('errors')}  "
                  f"flaky={run.get('flaky')}")
        if r.discrepancies:
            print(f"    ⚠️ DISCREPANCIES (the cell did not take): {r.discrepancies}")
        if r.warnings:
            print(f"    ⚠️ {r.warnings}")
        _ = d

    per_case_s = elapsed / max(1, invocations)
    per_case_req = http_used / max(1, invocations)
    out.update({
        "invocations": invocations,
        "http_requests": http_used,
        "http_by_host": _http["by_host"],
        "per_case_s": round(per_case_s, 1),
        "per_case_requests": round(per_case_req, 2),
    })

    print()
    print(f"wall time        {elapsed/60:.1f} min for {invocations} answer-path invocations")
    print(f"per case         {per_case_s:.1f}s  ·  {per_case_req:.2f} HTTP requests")
    print(f"HTTP by host     {_http['by_host']}")
    print()
    print("── extrapolated to the full 102-case grid ──")
    for label, cells_n, reps in (("1 replicate  (2 runs)", 2, 1), ("2 replicates (4 runs)", 2, 2)):
        inv = 102 * cells_n * reps
        print(f"  {label}: {inv:4d} invocations  ·  {inv*per_case_s/3600:5.1f} h  "
              f"·  {inv*per_case_req:6.0f} requests")
    print("  (free allowance is 1,000 requests/day)")

    OUT.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
