#!/usr/bin/env python3
"""Model bake-off probe — WCH-13 latency lever (Lever A).

The ADA phase chain's wall-clock is ~10 sequential LLM calls to ONE slow cloud
model (every phase = a coder `plan` call + a fast `interpret` call, both currently
`qwen3-coder-next:cloud`). The cheapest, lowest-risk latency lever is to point the
`fast`/`coder` tiers at a genuinely faster model — but "smaller" is not "faster"
when local-vs-cloud and Mac inference are in play, so this is MEASURED, not guessed.

This probe does two things the full golden eval can't do cheaply:
  1. Reachability — a `:cloud` model that isn't being served 404s and would score 0
     in the golden eval, masquerading as "terrible quality". We surface that here.
  2. First latency read — median wall-clock of a REPRESENTATIVE structured call
     (the SQL-plan shape the coder tier actually runs, and the interpret shape the
     fast tier runs) so we can eliminate obviously-slower models before spending a
     full eval on them.

Quality is decided separately by `run_golden.py` (the sharp SQL instrument); this
only answers "does it respond, and how fast?".

Usage:
    .venv/bin/python evals/model_bakeoff.py
    .venv/bin/python evals/model_bakeoff.py --models gemma4:31b-cloud qwen2.5-coder:14b --runs 3
"""
from __future__ import annotations

import argparse
import os
import statistics
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

from pydantic import BaseModel, Field

# Candidates available on this backend (from `ollama list`). The first is the
# incumbent both tiers currently use — it is the baseline every other is judged against.
_DEFAULT_CANDIDATES = [
    "qwen3-coder-next:cloud",   # incumbent (coder + narrator + fast all point here)
    "gemma4:31b-cloud",         # different cloud model, mid-size
    "qwen2.5-coder:14b",        # local 9GB coder
    "kimi-k2.6:cloud",          # large MoE — likely slower, included for completeness
]

# A representative SCHEMA the coder plan call sees — small but realistic shape.
_SCHEMA = """TABLE: ecommerce.orders
  - order_id (BIGINT)
  - customer_id (BIGINT)
  - channel (VARCHAR)        -- web | mobile | store
  - status (VARCHAR)         -- placed | shipped | cancelled
  - total_amount (DECIMAL)
  - order_ts (TIMESTAMP)
TABLE: ecommerce.customers
  - customer_id (BIGINT)
  - region (VARCHAR)
  - segment (VARCHAR)        -- new | returning | vip
"""


class _PlanProbe(BaseModel):
    """Coder-tier shape: a short list of analysis SQL queries (what every ADA phase
    plans before executing)."""
    queries: list[str] = Field(description="3 contribution-analysis SQL queries")


class _InterpretProbe(BaseModel):
    """Fast-tier shape: a couple of prose findings over already-computed results."""
    phase_summary: str
    findings: list[str]


_PLAN_USER = (
    "Revenue (SUM(total_amount) on ecommerce.orders, status<>'cancelled') fell 18% in "
    "May vs April. Write 3 contribution-analysis SQL queries that break the change down "
    "by channel, by customer region, and by customer segment.\n\nSCHEMA:\n" + _SCHEMA
)

_INTERPRET_USER = (
    "Results: channel=mobile dropped 41% MoM (was 62% of the decline); web flat; store "
    "+3%. region=west -22%, others flat. segment=returning -29%, new +5%.\n\n"
    "Summarise where the revenue decline concentrated and list the 2 strongest findings."
)


def _probe_one(model: str, runs: int) -> dict:
    """Build a provider pinned to `model` (bypassing the role cache) and time a
    plan-shaped and an interpret-shaped structured call `runs` times each."""
    from aughor.llm.provider import LLMProvider

    # Pin every role to this model so LLMProvider(_model_for_role) resolves to it,
    # whichever role we construct.
    for var in ("AUGHOR_CODER_MODEL", "AUGHOR_NARRATOR_MODEL", "AUGHOR_FAST_NARRATOR_MODEL", "AUGHOR_MODEL"):
        os.environ[var] = model
    # No silent Anthropic swap mid-probe — we want THIS model's truth or a loud error.
    os.environ["AUGHOR_FALLBACK_DISABLED"] = "1"

    backend = os.getenv("AUGHOR_BACKEND", "ollama")
    out: dict = {"model": model, "plan_ms": [], "interpret_ms": [], "error": None,
                 "plan_ok": 0, "interpret_ok": 0}
    try:
        coder = LLMProvider(backend=backend, role="coder")
        fast = LLMProvider(backend=backend, role="fast")
    except Exception as e:
        out["error"] = f"client build failed: {e}"
        return out

    for _ in range(runs):
        # Plan-shaped (coder) call
        t0 = time.monotonic()
        try:
            r = coder.complete(
                system="Write contribution-analysis SQL. Return only the queries.",
                user=_PLAN_USER, response_model=_PlanProbe)
            if r and r.queries:
                out["plan_ok"] += 1
            out["plan_ms"].append((time.monotonic() - t0) * 1000)
        except Exception as e:
            out["error"] = f"plan call failed: {str(e)[:160]}"
            return out  # a hard failure (404/unreachable) — stop, report loudly

        # Interpret-shaped (fast) call
        t0 = time.monotonic()
        try:
            r = fast.complete(
                system="Interpret contribution-analysis results into findings.",
                user=_INTERPRET_USER, response_model=_InterpretProbe)
            if r and r.findings:
                out["interpret_ok"] += 1
            out["interpret_ms"].append((time.monotonic() - t0) * 1000)
        except Exception as e:
            out["error"] = f"interpret call failed: {str(e)[:160]}"
            return out
    return out


def _med(xs: list[float]) -> float:
    return statistics.median(xs) if xs else float("nan")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="*", default=_DEFAULT_CANDIDATES)
    parser.add_argument("--runs", type=int, default=2,
                        help="timed repetitions per shape (median reported)")
    args = parser.parse_args()

    print(f"Model bake-off — {args.runs} run(s)/shape, backend={os.getenv('AUGHOR_BACKEND','ollama')}")
    print("Representative structured calls: plan(coder) + interpret(fast)\n")
    print(f"{'model':28} {'plan med':>10} {'intp med':>10} {'phase~2call':>12}  status")
    print("-" * 78)

    rows = []
    for m in args.models:
        res = _probe_one(m, args.runs)
        rows.append(res)
        if res["error"]:
            print(f"{m:28} {'—':>10} {'—':>10} {'—':>12}  ✗ {res['error']}")
            continue
        pm, im = _med(res["plan_ms"]), _med(res["interpret_ms"])
        phase = pm + im  # a phase ≈ one plan + one interpret call (SQL exec already parallel)
        ok = f"plan {res['plan_ok']}/{args.runs}, intp {res['interpret_ok']}/{args.runs}"
        print(f"{m:28} {pm:>8.0f}ms {im:>8.0f}ms {phase:>10.0f}ms  ✓ {ok}")

    # Honest read-out: a phase is ~2 calls; the chain is ~5 phases. Project the chain.
    base = next((r for r in rows if r["model"] == _DEFAULT_CANDIDATES[0] and not r["error"]), None)
    print("\nProjected 5-phase chain (5 × (plan+interpret), SQL exec already parallel):")
    for r in rows:
        if r["error"]:
            continue
        phase = _med(r["plan_ms"]) + _med(r["interpret_ms"])
        chain_s = phase * 5 / 1000
        delta = ""
        if base and not base["error"] and r["model"] != base["model"]:
            base_chain = (_med(base["plan_ms"]) + _med(base["interpret_ms"])) * 5 / 1000
            if base_chain > 0:
                delta = f"  ({(chain_s - base_chain) / base_chain * 100:+.0f}% vs incumbent)"
        print(f"  {r['model']:28} ~{chain_s:5.1f}s{delta}")


if __name__ == "__main__":
    main()
