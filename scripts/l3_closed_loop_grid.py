"""L3 — grade `closed_loop` on the 102-case corpus. ONE replicate per invocation.

Sized from the pilot, not from extrapolation off the 22-case suite:
  * 44.5s and 4.19 OPENROUTER requests per case (localhost traffic is a local model, free);
  * 102 cases x 2 cells x 1 replicate = 204 invocations ~= 854 requests, ~2.5h;
  * 2 replicates would need ~1,708 against a 1,000/day cap, so the second replicate is a
    SEPARATE DAY's run. Both are needed: with one run per cell there is no sampling floor,
    and since `7d78c4c` the promotion gate refuses a baseline supplied without floor evidence.

Run with REPLICATE=1 today and REPLICATE=2 tomorrow; scoring reads the suite's run history,
so the two days compose into one A/B without either run knowing about the other.

Records `chat.post_answer` per cell. The pilot log showed repeated upstream 429s from the
secondary enrichment model, tolerated as best-effort — which is correct for an answer and
WRONG to leave unmeasured in an experiment: if enrichment degrades at different rates across
cells, that is an uncontrolled variable sitting inside the delta. Counting it does not fix it,
but it makes the run able to say so instead of averaging it away.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time

SUITE = "9c1e13e458ff"
REPLICATE = int(os.environ.get("REPLICATE", "1"))
OUT = pathlib.Path(__file__).with_name(f"l3_grid_rep{REPLICATE}.json")

import httpx  # noqa: E402

_http: dict = {"total": 0, "by_host": {}}
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
from aughor.stats import stats  # noqa: E402


def _counters() -> dict:
    try:
        return dict(stats.snapshot() or {})
    except Exception:
        return {}


def main() -> int:
    n_cases = len(store.list_cases(SUITE, limit=500))
    print(f"suite {SUITE}: {n_cases} cases · replicate {REPLICATE} · conn=workspace · freeze=True",
          flush=True)
    est_req = n_cases * 2 * 4.19
    print(f"projected: {n_cases*2} invocations · ~{est_req:.0f} openrouter requests · "
          f"~{n_cases*2*44.5/3600:.1f}h", flush=True)

    cells = [
        Cell(label="closed_loop_off", flags={"closed_loop": False}),
        Cell(label="closed_loop_on", flags={"closed_loop": True}),
    ]

    before = _counters()
    t0 = time.monotonic()
    results = run_experiment(
        SUITE,
        lambda: ask_target("workspace", depth="quick"),
        cells,
        replicates=1,
        connection_id="workspace",
        freeze=True,
    )
    elapsed = time.monotonic() - t0
    after = _counters()

    out = {
        "suite_id": SUITE, "replicate": REPLICATE, "cases": n_cases,
        "elapsed_s": round(elapsed, 1),
        "http_by_host": _http["by_host"],
        "post_answer_failures_total": int(after.get("chat.post_answer", 0))
                                      - int(before.get("chat.post_answer", 0)),
        "cells": [],
    }

    print(f"\nwall {elapsed/60:.1f} min · http {_http['by_host']}", flush=True)
    for r in results:
        runs = [run.to_dict() for run in r.runs]
        out["cells"].append({
            "label": r.label, "error": r.error,
            "discrepancies": r.discrepancies, "warnings": r.warnings,
            "runs": [{"run_id": x.get("run_id"), "pass_rate": x.get("pass_rate"),
                      "total": x.get("total"), "errors": x.get("errors"),
                      "flaky": x.get("flaky")} for x in runs],
        })
        print(f"cell {r.label:18} error={r.error or '-'}", flush=True)
        for x in runs:
            print(f"    run {x.get('run_id')}  pass_rate={x.get('pass_rate')}  "
                  f"total={x.get('total')}  errors={x.get('errors')}  flaky={x.get('flaky')}",
                  flush=True)
        if r.discrepancies:
            print(f"    ⚠️ CELL DID NOT TAKE: {r.discrepancies}", flush=True)
        if r.warnings:
            print(f"    ⚠️ {r.warnings}", flush=True)

    print(f"\nchat.post_answer failures this run: {out['post_answer_failures_total']} "
          f"(across both cells; a large asymmetry would confound the delta)", flush=True)
    if REPLICATE == 1:
        print("\n⏭️ replicate 1 done. Run again TOMORROW with REPLICATE=2 for the noise floor;\n"
              "   only then can the delta be scored — a single run per cell has no floor.",
              flush=True)
    else:
        print("\n⏭️ both replicates present — score with fidelity.compare + evaluate_graduation,\n"
              "   or POST /evals/flags/closed_loop/graduate and let the route derive both.",
              flush=True)

    OUT.write_text(json.dumps(out, indent=2, default=str))
    print(f"wrote {OUT}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
