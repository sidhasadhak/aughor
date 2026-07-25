"""Wave E4 loose end — the proxy-inversion audit.

An axis is the end task (`accuracy`) or a proxy for it (`pass_rate`, `robustness`). A proxy that
can improve while accuracy WORSENS must not be allowed to inflate a single composite score. The
audit classifies the axes and demotes any proxy caught inverting; `fidelity.assess` keeps demoted
axes out of the composite.
"""
from __future__ import annotations

import pytest

from aughor.evals.fidelity import assess
from aughor.evals.proxy_audit import (
    AXIS_KIND,
    GROUND_TRUTH_AXIS,
    audit_inversion,
    is_proxy,
    kind_of,
)


def test_the_axis_taxonomy():
    assert GROUND_TRUTH_AXIS == "accuracy"
    assert kind_of("accuracy") == "ground_truth"
    assert not is_proxy("accuracy")
    assert is_proxy("pass_rate") and is_proxy("robustness")
    # an unknown axis is a proxy by default — assuming an unknown axis is the end task is the
    # exact mistake the audit exists to prevent.
    assert is_proxy("some.new.axis")
    # every classified axis carries a stated reason, not a bare label.
    assert all(len(reason) > 10 for _, reason in AXIS_KIND.values())


def test_ground_truth_is_never_demoted_even_on_adversarial_data():
    # accuracy swinging wildly must not demote accuracy — it is the yardstick, not a candidate.
    runs = [{"accuracy": 1.0, "pass_rate": 0.5}, {"accuracy": 0.0, "pass_rate": 0.5},
            {"accuracy": 1.0, "pass_rate": 0.5}, {"accuracy": 0.0, "pass_rate": 0.5}]
    report = audit_inversion(runs)
    acc = next(a for a in report.axes if a.axis == "accuracy")
    assert acc.kind == "ground_truth" and acc.demoted is False
    assert "accuracy" not in report.demoted_axes()


def test_an_inverting_proxy_is_demoted():
    # pass_rate climbs 0.4→0.9 while accuracy falls 0.9→0.4: the proxy moved OPPOSITE to the end
    # task, repeatedly. That is the inversion the audit convicts on.
    runs = [
        {"pass_rate": 0.4, "accuracy": 0.9},
        {"pass_rate": 0.6, "accuracy": 0.7},
        {"pass_rate": 0.8, "accuracy": 0.5},
        {"pass_rate": 0.9, "accuracy": 0.4},
    ]
    report = audit_inversion(runs, min_pairs=3)
    pr = next(a for a in report.axes if a.axis == "pass_rate")
    assert pr.inverts is True
    assert pr.inversions == 3 and pr.pairs == 3
    assert pr.demoted is True
    assert "pass_rate" in report.demoted_axes()


def test_a_proxy_that_tracks_the_end_task_is_kept():
    runs = [
        {"pass_rate": 0.4, "accuracy": 0.4},
        {"pass_rate": 0.6, "accuracy": 0.6},
        {"pass_rate": 0.8, "accuracy": 0.8},
        {"pass_rate": 0.9, "accuracy": 0.9},
    ]
    report = audit_inversion(runs, min_pairs=3)
    pr = next(a for a in report.axes if a.axis == "pass_rate")
    assert pr.inverts is False and pr.demoted is False
    assert "pass_rate" not in report.demoted_axes()


def test_insufficient_evidence_is_not_a_conviction():
    runs = [{"pass_rate": 0.9, "accuracy": 0.4}, {"pass_rate": 0.4, "accuracy": 0.9}]  # 1 pair
    report = audit_inversion(runs, min_pairs=3)
    pr = next(a for a in report.axes if a.axis == "pass_rate")
    assert pr.inverts is None            # too little evidence to convict OR clear
    assert pr.demoted is False           # …so we do not demote by default

    # …but a caller wanting a purely task-anchored composite can demote unproven proxies.
    anchored = audit_inversion(runs, min_pairs=3, demote_unproven_proxies=True)
    assert next(a for a in anchored.axes if a.axis == "pass_rate").demoted is True


def test_jitter_below_epsilon_is_not_an_inversion():
    # both axes wobble by 0.005 in opposite directions — noise, not a reversal.
    runs = [{"pass_rate": 0.500, "accuracy": 0.900},
            {"pass_rate": 0.505, "accuracy": 0.895},
            {"pass_rate": 0.510, "accuracy": 0.890},
            {"pass_rate": 0.515, "accuracy": 0.885}]
    report = audit_inversion(runs, epsilon=0.01, min_pairs=3)
    pr = next(a for a in report.axes if a.axis == "pass_rate")
    assert pr.inversions == 0 and pr.inverts is False


def test_demotion_prevents_a_proxy_only_inflation_of_the_composite():
    """The whole point: a variant that only improves the PROXY must not score higher on the
    composite. Same cells, two assessments — with pass_rate demoted, the proxy-only gain
    disappears from the score."""
    cells = {
        "baseline": [{"pass_rate": 0.5, "accuracy": 0.9}, {"pass_rate": 0.5, "accuracy": 0.9}],
        "variant":  [{"pass_rate": 0.9, "accuracy": 0.9}, {"pass_rate": 0.9, "accuracy": 0.9}],
    }
    axes = ("pass_rate", "accuracy")

    naive = assess(cells, baseline="baseline", axes=axes)
    # Un-demoted, the proxy inflates the variant's composite above the baseline's…
    assert naive.composite["variant"] > naive.composite["baseline"]

    anchored = assess(cells, baseline="baseline", axes=axes, demote=["pass_rate"])
    # …demoted, the composite is accuracy-only and the proxy-only "win" is gone.
    assert anchored.composite["variant"] == pytest.approx(0.9)
    assert anchored.composite["baseline"] == pytest.approx(0.9)
    assert anchored.demoted == ["pass_rate"]
    # the demoted axis is still MEASURED and its delta still reported — a reader still sees it.
    assert any(d.axis == "pass_rate" for d in anchored.deltas)
    assert "demoted" in anchored.to_dict()


def test_assess_is_byte_identical_when_nothing_is_demoted():
    cells = {"b": [{"pass_rate": 0.6, "accuracy": 0.8}], "v": [{"pass_rate": 0.7, "accuracy": 0.8}]}
    r = assess(cells, baseline="b", axes=("pass_rate", "accuracy"))
    assert r.demoted == []
    # composite still uses both axes (the pre-audit behaviour).
    assert r.composite["b"] == pytest.approx(2 / (1 / 0.6 + 1 / 0.8))
