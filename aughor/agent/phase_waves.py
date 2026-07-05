"""P-A (deep path) — run the ADA middle phases as one parallel wave (flag `ada.parallel_phases`).

The temporal deep-analysis pipeline is baseline → decompose → dimensional → behavioral →
synthesize, each phase one plan-LLM → parallel-SQL → interpret-LLM cycle that BLOCKS the next —
the measured wall-clock driver of an ~8-minute investigation (the SQL inside a phase is already
parallel; the phases are not). The dependency map (verified against the planners):

  * baseline / decompose / dimensional all plan from the INTAKE data; the prior-phase summaries
    they inject (`_baseline_summary`, `_decomp_summary`) are soft context with shipped fallbacks
    ("Baseline established." / "") — flavour, not structure.
  * behavioral HARD-depends on dimensional (`_dimensional_passes` targets its queries), so it
    stays sequential after the wave.
  * the tier routers (route_after_baseline/decompose/dimensional) early-stop the chain.

So the wave runs baseline ∥ decompose ∥ dimensional concurrently (each on its own
`make_reader()` clone, in-process ContextThreadPoolExecutor so metering/budget contextvars
propagate — the same live-proven pattern as `ada_cross_section_multilens`), then applies the
SERIAL routers' decisions post-hoc: anything the serial path would never have run is DROPPED
from the report (its compute is the price of the wall-clock win; the P6 budget still governs).
Report semantics therefore match the serial path, with two flag-gated deviations, both honest:
a wave-phase planner sees the fallback prior-summary instead of the live one, and a baseline
premise-correction (`_ada_intake` update) can't retroactively re-scope the sibling phases.

Off (default) → the graph wires the classic serial chain, byte-identical.
"""
from __future__ import annotations

import logging
from concurrent.futures import as_completed

logger = logging.getLogger("aughor.agent.phase_waves")

# Serial order of the wave members — merges are ALWAYS in this order, never completion order.
_WAVE_ORDER = ("baseline", "decompose", "dimensional")


def _run_phase(fn, state, conn):
    """One phase on its own reader clone. Raising BudgetExceeded aborts the wave (caller)."""
    reader = conn.make_reader()
    return fn(state, conn=reader)


def ada_phase_wave(state, conn) -> dict:
    """Run baseline ∥ decompose ∥ dimensional; merge with serial-router semantics.

    Sets ``_wave_next`` ("ada_behavioral" | "ada_synthesize") for the graph edge — the same
    decision the serial routers would have made on the merged state.
    """
    from aughor.agent.investigate import (
        ada_baseline,
        ada_decompose,
        ada_dimensional,
        route_after_baseline,
        route_after_decompose,
        route_after_dimensional,
    )
    from aughor.kernel.concurrency import ContextThreadPoolExecutor
    from aughor.kernel.metering import BudgetExceeded
    from aughor.stats import bump

    fns = {"baseline": ada_baseline, "decompose": ada_decompose, "dimensional": ada_dimensional}
    base_phases = list(state.get("investigation_phases", []))
    base_n = len(base_phases)

    results: dict[str, dict] = {}
    try:
        with ContextThreadPoolExecutor(max_workers=len(_WAVE_ORDER)) as pool:
            futs = {pool.submit(_run_phase, fns[name], state, conn): name for name in _WAVE_ORDER}
            for fut in as_completed(futs):
                name = futs[fut]
                try:
                    results[name] = fut.result() or {}
                except BudgetExceeded:
                    raise  # budget abort — unwind the whole run, same as every parallel path
                except Exception as exc:
                    from aughor.kernel.errors import tolerate
                    tolerate(exc, f"ada phase wave '{name}' failed; phase skipped (the serial "
                                  f"path's own per-phase error handling would have degraded too)",
                             counter="ada.phase_wave_member")
                    results[name] = {}
    except BudgetExceeded:
        raise
    except Exception as exc:
        # Executor-level failure must never break the investigation — serial fallback.
        logger.warning("[ada] phase wave pool failed (%s) — serial fallback", exc, exc_info=True)
        for name in _WAVE_ORDER:
            if name not in results:
                try:
                    results[name] = fns[name](state, conn=conn) or {}
                except Exception:
                    results[name] = {}

    def _new_phases(update: dict) -> list:
        ph = update.get("investigation_phases", [])
        return ph[base_n:] if len(ph) > base_n else []

    # ── post-hoc serial routing: keep exactly what the serial chain would have run ──
    merged: dict = {}
    kept_phases: list = []
    sim = dict(state)

    def _adopt(name: str) -> None:
        upd = results.get(name) or {}
        kept_phases.extend(_new_phases(upd))
        for k, v in upd.items():
            if k != "investigation_phases":
                merged[k] = v
                sim[k] = v

    _adopt("baseline")
    nxt = "ada_synthesize"
    sim["investigation_phases"] = base_phases + kept_phases
    if route_after_baseline(sim) != "ada_synthesize":
        _adopt("decompose")
        sim["investigation_phases"] = base_phases + kept_phases
        if route_after_decompose(sim) != "ada_synthesize":
            _adopt("dimensional")
            sim["investigation_phases"] = base_phases + kept_phases
            nxt = route_after_dimensional(sim)

    dropped = [n for n in _WAVE_ORDER if _new_phases(results.get(n) or {}) and
               not any(p in kept_phases for p in _new_phases(results[n]))]
    if dropped:
        bump("ada.phase_wave_dropped", len(dropped))
        logger.info("[ada] phase wave: serial routers dropped %s (early-stop semantics kept)",
                    dropped)
    bump("ada.phase_wave_runs")

    merged["investigation_phases"] = base_phases + kept_phases
    merged["_wave_next"] = nxt if nxt in ("ada_behavioral", "ada_synthesize") else "ada_synthesize"
    return merged


def route_after_wave(state) -> str:
    return state.get("_wave_next") or "ada_synthesize"
