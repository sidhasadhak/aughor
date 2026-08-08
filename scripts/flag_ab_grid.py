"""A/B one flag over an eval suite — with the two guards this session paid to learn.

    FLAG=explore.route_wide SUITE=9c1e13e458ff DEPTH=quick TEMPERATURE=0 REPLICATE=1 \
      AUGHOR_FALLBACK_DISABLED=1 \
      AUGHOR_LLM_RPM=16 AUGHOR_LLM_MAX_CONCURRENCY=2 \
      .venv/bin/python -u scripts/flag_ab_grid.py

**Guard 1 — refuse to grid an INERT flag.** Before spending anything, the same question is
rendered under the flag off and on and the two grounding contributions compared. If the flag
changes the prompt for too few cases, the grid is refused and says which. L3 spent 2.5 hours
and 868 requests to measure `closed_loop` across a corpus where it was a **no-op on 90% of
cases** — `retrieve_trusted` has no flag gate, so the trusted block was present in both cells.
L6 would have been worse: `ada.evidence_stubs` (since deleted, 2026-08-01) gated `_format_full_evidence`, whose only caller
is the ADA graph's `synthesize_report`, so at `DEPTH=quick` it is unreachable — inert on
**100%** of the corpus. Both are seconds to detect and hours to discover the expensive way.

Note the check covers PLAN-TIME grounding, which is where retrieval-shaped flags live. A flag
that acts later in the run (mid-synthesis, as evidence_stubs did) is invisible to it, so a
clean pre-check is necessary, not sufficient — set `ALLOW_INERT=1` only when you have
established by another route that the flag actually engages on this path.

**Guard 2 — temperature is PINNED by default.** Measured on the L3 grid: 92 cases whose prompt
was byte-identical between cells still disagreed **12 times** — a **13% run-to-run flip rate at
default temperature**, symmetric (7 one way, 5 the other), i.e. pure sampling noise. Any
default-temperature A/B on this corpus must clear ~0.13 to be attributable, which makes all but
enormous effects invisible. Pinning to 0 removes that noise so the per-case diff becomes the
evidence.

⚠️ **A temp-0 floor is NOT a sampling floor.** At temperature 0 replicates measure DETERMINISM,
so a band of ~0.000 makes any single-case flip look "attributable". Read the per-case diff, not
the band. For a genuine sampling floor, run `TEMPERATURE=` (empty, provider default) with two
or more replicates — see the arc doc's "the honest design".
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time

FLAG = os.environ.get("FLAG", "explore.route_wide")
SUITE = os.environ.get("SUITE", "9c1e13e458ff")
DEPTH = os.environ.get("DEPTH", "quick")
CONN = os.environ.get("CONNECTION_ID", "workspace")
REPLICATE = int(os.environ.get("REPLICATE", "1"))
ALLOW_INERT = os.environ.get("ALLOW_INERT", "") not in ("", "0", "false", "no")
#: Fraction of cases whose prompt must actually change for the grid to be worth running.
MIN_SENSITIVE = float(os.environ.get("MIN_SENSITIVE", "0.25"))
_temp_raw = os.environ.get("TEMPERATURE", "0")
TEMPERATURE = float(_temp_raw) if _temp_raw.strip() != "" else None

#: Result lands in the CWD (or `GRID_OUT_DIR`), never beside the script — a run artifact
#: written into `scripts/` shows up as untracked source and invites being committed.
OUT = (pathlib.Path(os.environ.get("GRID_OUT_DIR") or ".")
       / f"{FLAG.replace('.', '_')}_grid_rep{REPLICATE}.json")

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
from aughor.kernel.flags import flag_overrides  # noqa: E402
from aughor.stats import stats  # noqa: E402


def _grounding_for(question: str) -> str:
    """The plan-time grounding this question would receive, as one string."""
    from aughor.agent.grounding import correction_priors, trusted_templates
    return trusted_templates(question, CONN) + correction_priors(question, CONN)


def inertness_report(questions: list[str]) -> dict:
    """How many cases the flag actually changes the prompt for. No LLM spend."""
    sensitive = 0
    for q in questions:
        with flag_overrides({FLAG: False}):
            off = _grounding_for(q)
        with flag_overrides({FLAG: True}):
            on = _grounding_for(q)
        if off != on:
            sensitive += 1
    n = max(1, len(questions))
    return {"cases": len(questions), "sensitive": sensitive,
            "fraction": round(sensitive / n, 4)}


def _counters() -> dict:
    try:
        return dict(stats.snapshot() or {})
    except Exception:
        return {}


def main() -> int:
    cases = store.list_cases(SUITE, limit=500)
    questions = [c.get("question", "") for c in cases]
    print(f"flag={FLAG} suite={SUITE} depth={DEPTH} conn={CONN} "
          f"temperature={'PINNED ' + str(TEMPERATURE) if TEMPERATURE is not None else 'provider default'} "
          f"replicate={REPLICATE}", flush=True)

    if not questions:
        # Distinct from "the flag is inert": a suite with no cases proves nothing either way,
        # and reporting it as 0% sensitive would read as a finding about the flag. The usual
        # cause is CWD — the eval store resolves `data/evals.db` RELATIVELY, so running from
        # another directory silently opens an empty one.
        print(f"\n⛔ suite {SUITE!r} has NO CASES — nothing to compare.\n"
              f"   Run from the repo root, or set AUGHOR_EVALS_DB to the store holding it.",
              flush=True)
        return 3

    inert = inertness_report(questions)
    print(f"\npre-check: the flag changes the prompt for {inert['sensitive']}/{inert['cases']} "
          f"cases ({inert['fraction']*100:.0f}%)", flush=True)
    if inert["fraction"] < MIN_SENSITIVE and not ALLOW_INERT:
        print(f"\n⛔ REFUSING to run: below the {MIN_SENSITIVE*100:.0f}% threshold.\n"
              f"   {inert['cases'] - inert['sensitive']} of {inert['cases']} cases would run an\n"
              f"   IDENTICAL prompt in both cells, so most of the budget would measure sampling\n"
              f"   noise rather than the flag. Either pick a corpus this flag engages with, or\n"
              f"   establish by another route that it acts outside plan-time grounding and\n"
              f"   re-run with ALLOW_INERT=1.", flush=True)
        OUT.write_text(json.dumps({"refused": True, "inertness": inert, "flag": FLAG},
                                  indent=2))
        return 2
    if inert["fraction"] < MIN_SENSITIVE:
        print("   ⚠️ ALLOW_INERT set — proceeding over the inertness guard.", flush=True)

    cells = [Cell(label=f"{FLAG}_off", flags={FLAG: False}, temperature=TEMPERATURE),
             Cell(label=f"{FLAG}_on", flags={FLAG: True}, temperature=TEMPERATURE)]

    before = _counters()
    t0 = time.monotonic()
    results = run_experiment(
        SUITE, lambda: ask_target(CONN, depth=DEPTH), cells,
        replicates=1, connection_id=CONN, freeze=True,
    )
    elapsed = time.monotonic() - t0
    after = _counters()

    out = {"flag": FLAG, "suite_id": SUITE, "replicate": REPLICATE, "depth": DEPTH,
           "temperature": TEMPERATURE, "inertness": inert,
           "elapsed_s": round(elapsed, 1), "http_by_host": _http["by_host"],
           "post_answer_failures_total": int(after.get("chat.post_answer", 0))
                                         - int(before.get("chat.post_answer", 0)),
           "cells": []}

    print(f"\nwall {elapsed/60:.1f} min · http {_http['by_host']}", flush=True)
    for r in results:
        runs = [run.to_dict() for run in r.runs]
        out["cells"].append({"label": r.label, "error": r.error,
                             "discrepancies": r.discrepancies, "warnings": r.warnings,
                             "runs": [{"run_id": x.get("run_id"), "pass_rate": x.get("pass_rate"),
                                       "total": x.get("total"), "errors": x.get("errors"),
                                       "flaky": x.get("flaky")} for x in runs]})
        print(f"cell {r.label:24} error={r.error or '-'}", flush=True)
        for x in runs:
            print(f"    run {x.get('run_id')}  pass_rate={x.get('pass_rate')}  "
                  f"errors={x.get('errors')}  flaky={x.get('flaky')}", flush=True)
        if r.discrepancies:
            print(f"    ⚠️ CELL DID NOT TAKE: {r.discrepancies}", flush=True)
        if r.warnings:
            print(f"    ⚠️ {r.warnings}", flush=True)

    if TEMPERATURE == 0:
        print("\n⚠️ temperature pinned to 0: replicates here measure DETERMINISM, not sampling.\n"
              "   Read the per-case diff, not the band — a ~0.000 band makes any single-case\n"
              "   flip look 'attributable'.", flush=True)
    OUT.write_text(json.dumps(out, indent=2, default=str))
    print(f"wrote {OUT}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
