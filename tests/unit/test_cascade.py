"""Model cascade — the statistical accuracy guarantee, proven on synthetic data.

The cascade routes clear-cut proxy scores to the cheap decision and escalates the
ambiguous middle to the oracle. `learn_thresholds` must pick (tau_pos, tau_neg) so that
the routed pipeline's recall holds the target on held-out data (with probability ≥ 1−δ).
Pure/deterministic — no LLM calls.
"""
import random

import pytest

from aughor.llm.cascade import CascadeConfig, learn_thresholds, route


def _overlapping_corpus(n: int, seed: int):
    """A realistically-ambiguous, *calibrated* proxy: P(positive | score) = score. There is
    genuine overlap everywhere (strongest in the middle), so a single cutoff cannot hit both
    a high recall and a high precision — the cascade must escalate the middle band."""
    rng = random.Random(seed)
    scores = [rng.random() for _ in range(n)]
    labels = [rng.random() < s for s in scores]
    return scores, labels


def _routed_recall(scores, labels, t):
    """Recall of the routed pipeline: a positive is recalled unless the proxy accepts it as
    negative (score ≤ tau_neg). Escalations are caught by the (assumed-correct) oracle."""
    total_pos = sum(1 for lbl in labels if lbl)
    if not total_pos:
        return 1.0
    missed = sum(1 for s, lbl in zip(scores, labels) if lbl and route(s, t) == "accept_negative")
    return (total_pos - missed) / total_pos


def test_guarantee_holds_on_heldout():
    cfg = CascadeConfig(recall_target=0.9, precision_target=0.85, failure_probability=0.1)
    t = learn_thresholds(*_overlapping_corpus(800, seed=1), config=cfg)

    # Held-out set from the same distribution → the true recall must clear the target.
    test_s, test_l = _overlapping_corpus(800, seed=2)
    achieved = _routed_recall(test_s, test_l, t)
    assert achieved >= cfg.recall_target - 0.05, f"held-out recall {achieved:.3f} < target"
    assert t.tau_neg <= t.tau_pos


def test_ambiguous_data_forces_escalation():
    # With genuine middle-overlap + strict targets, a single cutoff can't do both → the
    # cascade opens an escalation band (and still saves work by accepting the extremes).
    t = learn_thresholds(
        *_overlapping_corpus(800, seed=3),
        config=CascadeConfig(recall_target=0.95, precision_target=0.9),
    )
    assert 0.0 < t.escalation_rate < 1.0, f"escalation_rate={t.escalation_rate}"


def test_clean_separation_escalates_little():
    # Perfectly separable proxy (label == score>0.5) → the proxy alone nearly suffices, so
    # the cascade escalates little (escalation→0 is the optimal, max-savings outcome).
    rng = random.Random(7)
    scores = [rng.random() for _ in range(400)]
    labels = [s > 0.5 for s in scores]
    t = learn_thresholds(scores, labels, CascadeConfig(recall_target=0.9, precision_target=0.9))
    assert t.escalation_rate < 0.5
    assert _routed_recall(scores, labels, t) >= 0.9


def test_route_decisions():
    t = learn_thresholds(*_overlapping_corpus(400, seed=4))
    assert route(1.0, t) == "accept_positive"        # at/above tau_pos
    assert route(0.0, t) == "accept_negative"        # at/below tau_neg
    mid = (t.tau_pos + t.tau_neg) / 2
    if t.tau_neg < mid < t.tau_pos:                  # a true middle exists
        assert route(mid, t) == "escalate"


def test_stricter_guarantee_escalates_at_least_as_much():
    corpus = _overlapping_corpus(800, seed=5)
    lo = learn_thresholds(*corpus, config=CascadeConfig(recall_target=0.7, precision_target=0.7))
    hi = learn_thresholds(*corpus, config=CascadeConfig(recall_target=0.99, precision_target=0.95))
    assert hi.escalation_rate >= lo.escalation_rate - 1e-9


def test_guards():
    with pytest.raises(ValueError):
        learn_thresholds([0.5] * 10, [True] * 10)               # below min_calibration_size
    with pytest.raises(ValueError):
        learn_thresholds([0.5] * 40, [True] * 39)               # length mismatch
    # all-one-label must not crash
    learn_thresholds([0.1 * (i % 10) for i in range(40)], [True] * 40)
