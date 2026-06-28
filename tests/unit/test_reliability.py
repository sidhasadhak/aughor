"""Tests for the reliability-banding measurement protocol (evals/reliability.py).

Pure logic — proves the protocol that makes sub-2-pt effects distinguishable from temp-0 cloud
noise and retired verdicts re-judgeable: deterministic held-out split, pass-rate banding, and a
true-effect comparison that ignores unstable-band churn with a McNemar p-value.
"""
from __future__ import annotations

from evals.reliability import (holdout_split, reliability_bands, compare_runs, _mcnemar_p)


def test_holdout_split_is_deterministic_and_partitions():
    ids = [f"local{i:03d}" for i in range(135)]
    d1, h1 = holdout_split(ids, frac=0.2)
    d2, h2 = holdout_split(ids, frac=0.2)
    assert (d1, h1) == (d2, h2)                      # reproducible
    assert set(d1) & set(h1) == set()                # disjoint
    assert set(d1) | set(h1) == set(ids)             # covers all
    assert 0.10 < len(h1) / len(ids) < 0.30          # ~20% held out


def test_reliability_bands_thresholds():
    out = {
        "all_pass":  [True] * 5,
        "all_fail":  [False] * 5,
        "mostly":    [True, True, True, True, False],   # 4/5 ⇒ reliable pass
        "barely":    [True, False, False, False, False],# 1/5 ⇒ reliable fail
        "coinflip":  [True, True, True, False, False],  # 3/5 ⇒ unstable
    }
    b = reliability_bands(out)
    assert b["all_pass"].band == "reliably_pass"
    assert b["all_fail"].band == "reliably_fail"
    assert b["mostly"].band == "reliably_pass"
    assert b["barely"].band == "reliably_fail"
    assert b["coinflip"].band == "unstable"


def test_compare_runs_counts_only_reliable_flips():
    before = {"a": [False]*5, "b": [True]*5, "c": [True]*5}
    after  = {"a": [True]*5,  "b": [False]*5, "c": [True]*5}
    rep = compare_runs(before, after)
    assert rep.reliable_gain == 1 and rep.reliable_loss == 1 and rep.net == 0
    assert rep.detail["gained"] == ["a"] and rep.detail["lost"] == ["b"]


def test_unstable_churn_excluded_from_net():
    # 'x' goes reliable-fail → unstable: that is NOISE, not a regression.
    before = {"x": [False]*5, "y": [False]*5}
    after  = {"x": [True, True, True, False, False], "y": [True]*5}   # x unstable, y true gain
    rep = compare_runs(before, after)
    assert rep.reliable_gain == 1 and rep.reliable_loss == 0 and rep.net == 1
    assert rep.unstable_churn == 1                     # x counted as churn, not loss


def test_mcnemar_significance():
    assert _mcnemar_p(0, 0) == 1.0                      # no discordant pairs
    assert _mcnemar_p(5, 5) > 0.5                       # balanced ⇒ not significant
    assert _mcnemar_p(8, 0) < 0.01                      # one-sided 8/0 ⇒ significant


def test_net_positive_change_is_significant():
    """A genuine win: 6 reliable fail→pass, 0 regressions ⇒ net +6, small p."""
    before = {f"i{k}": [False]*5 for k in range(10)}
    after = dict(before)
    for k in range(6):
        after[f"i{k}"] = [True]*5
    rep = compare_runs(before, after)
    assert rep.net == 6 and rep.reliable_loss == 0 and rep.p_value < 0.05
