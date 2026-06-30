"""Harness logic for the ITS-outcome run (evals/its_structural.py).

Tests the seed + divergence + scoring deterministically with an INJECTED generator (no LLM): a
default-reading generator must fail every divergent task, and an intent-aware one must pass — which is
exactly the gap the live run measured (0/3 default → 3/3 asked).
"""
from __future__ import annotations

from evals.its_structural import run


def _generate(ctx: str) -> str:
    """Fake model: bare question → the DEFAULT (revenue/spend) reading; clarified → the intended one."""
    c = ctx.lower()
    asked = "(" in ctx                      # the clarification is appended in parentheses
    if "product" in c:
        col, intended = "product", "SUM(quantity)"
    elif "customer" in c:
        col, intended = "customer", "COUNT(*)"
    else:
        col, intended = "channel", "COUNT(*)"
    measure = intended if asked else "SUM(amount)"
    return f"SELECT {col} FROM orders GROUP BY {col} ORDER BY {measure} DESC LIMIT 1"


def test_default_reading_fails_every_divergent_task():
    r = run(generate=_generate)
    assert r["default_rate"] == 0.0 and r["n"] == 3


def test_clarified_reading_recovers_every_task():
    r = run(generate=_generate)
    assert r["asked_rate"] == 1.0
