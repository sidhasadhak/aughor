"""Hermetic CI gate for the wide-question routing eval (R9).

Pins the measure-before-trust contract: with the flag ON, broad landscape questions route
to the explore wave and neither causal investigations nor direct lookups are poached; with
the flag OFF, nothing routes to explore (byte-identical to pre-R9). Pure — imports ``run()``,
no DB, no model (the eval injects a benign classifier and forces the flag)."""
from __future__ import annotations

from evals.route_wide_eval import run


def test_wide_routing_contract():
    rep = run()

    # Flag ON: wide questions are fully captured; investigations + lookups are never poached.
    assert rep["on"]["wide"]["rate"] == 1.0
    assert rep["on"]["investigate"]["rate"] == 0.0
    assert rep["on"]["lookup"]["rate"] == 0.0

    # Flag OFF: R9 is inert — no question routes to explore.
    assert rep["off"]["wide"]["rate"] == 0.0
    assert rep["off"]["investigate"]["rate"] == 0.0
    assert rep["off"]["lookup"]["rate"] == 0.0
