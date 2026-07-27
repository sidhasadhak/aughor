"""The graduation route derives its own A/B evidence — Wave L2 follow-up.

Demanding floor evidence fixed the gate but moved the burden onto the caller, and a
caller-supplied `baseline_pass_rate` is a scalar with no provenance: nothing about it
says which runs produced it or whether they agree with themselves. The runs are already
on disk, stamped with the cell that produced them, so the server can just look.
"""
from __future__ import annotations

import json

from aughor.routers import evals as R


def _run(cell: str, flag_on: bool, pass_rate: float, flag: str = "graph.readback",
         status: str = "succeeded") -> dict:
    return {
        "id": f"{cell}-{pass_rate}", "status": status,
        "config": json.dumps({"cell": cell,
                              "cell_requested": {"label": cell, "flags": {flag: flag_on}}}),
        "summary": {"pass_rate": pass_rate, "total": 22},
    }


def _install(monkeypatch, runs):
    monkeypatch.setattr(R.store, "list_runs", lambda suite_id, limit=24: runs)


def test_baseline_and_floor_are_derived_from_the_suites_own_runs(monkeypatch):
    _install(monkeypatch, [
        _run("off", False, 0.70), _run("off", False, 0.71),
        _run("on", True, 0.90), _run("on", True, 0.91),
    ])
    baseline, delta = R._ab_evidence("s1", "graph.readback")
    assert baseline == 0.705
    assert delta is not None and delta.attributable is True


def test_the_real_l2_history_yields_a_refusal(monkeypatch):
    """The actual numbers: a 0.182 self-disagreement swallows a +0.023 delta."""
    _install(monkeypatch, [
        _run("off", False, 0.8636), _run("off", False, 0.6818),
        _run("on", True, 0.7727), _run("on", True, 0.8182),
    ])
    _, delta = R._ab_evidence("s1", "graph.readback")
    assert delta.attributable is False


def test_cells_are_classified_by_what_they_RAN_not_by_their_label(monkeypatch):
    """A cell named 'control' that actually ran with the flag ON must not be read as
    the baseline — the label is a human convenience, the recorded flags are the fact."""
    _install(monkeypatch, [
        _run("control", True, 0.90), _run("control", True, 0.91),   # mislabelled!
        _run("variant", False, 0.70), _run("variant", False, 0.71),
    ])
    baseline, delta = R._ab_evidence("s1", "graph.readback")
    assert baseline == 0.705          # the flag-OFF pair, despite being named "variant"
    assert delta.variant_mean > delta.baseline_mean


def test_one_replicate_per_side_cannot_establish_a_floor(monkeypatch):
    _install(monkeypatch, [_run("off", False, 0.70), _run("on", True, 0.90)])
    assert R._ab_evidence("s1", "graph.readback") == (None, None)


def test_runs_for_a_different_flag_are_ignored(monkeypatch):
    _install(monkeypatch, [
        _run("off", False, 0.70, flag="other.flag"),
        _run("off", False, 0.71, flag="other.flag"),
        _run("on", True, 0.90, flag="other.flag"),
    ])
    assert R._ab_evidence("s1", "graph.readback") == (None, None)


def test_unfinished_runs_are_not_evidence(monkeypatch):
    _install(monkeypatch, [
        _run("off", False, 0.70), _run("off", False, 0.71, status="running"),
        _run("on", True, 0.90),
    ])
    assert R._ab_evidence("s1", "graph.readback") == (None, None)
