"""Model cascade — route the easy LLM judgments to a cheap *proxy* model and escalate
only the ambiguous ones to the expensive *oracle*, with a statistical guarantee that the
proxy-accepted decisions match the oracle at a target recall/precision (failure-prob δ).

The proxy emits a score in ``[0, 1]`` where the **extremes are clear-cut** and the
**middle is ambiguous**:

    score >= tau_pos          -> accept the cheap POSITIVE decision  (no oracle call)
    score <= tau_neg          -> accept the cheap NEGATIVE decision   (no oracle call)
    tau_neg < score < tau_pos -> ESCALATE to the oracle

``(tau_pos, tau_neg)`` are learned offline from a calibration sample of
``(proxy_score, oracle_label)`` pairs. The recall/precision targets are enforced with
Hoeffding confidence bounds, so the *true* recall/precision of the routing hold with
probability ≥ 1 − δ (not merely on the sample). This is the standard cost-with-guarantee
cascade from the LLM-data-processing literature, ported generically so it works for any
binary/graded judgment surface (hypothesis scoring, finding-trust, LLM-judge, …).

This module is pure + deterministic — no LLM calls, no I/O — so the guarantee is unit-
testable on synthetic data. The proxy/oracle wiring lives at each call site.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

Decision = Literal["accept_positive", "accept_negative", "escalate"]


@dataclass(frozen=True)
class CascadeConfig:
    """Targets for the proxy→oracle routing.

    recall_target / precision_target — the accuracy floor the proxy-accepted decisions
    must hold *relative to the oracle* (the "gold algorithm"). failure_probability (δ) —
    the allowed probability the true recall/precision falls below target. Smaller δ ⇒ more
    conservative thresholds ⇒ more escalation.
    """

    recall_target: float = 0.9
    precision_target: float = 0.9
    failure_probability: float = 0.1
    min_calibration_size: int = 30


@dataclass(frozen=True)
class CascadeThresholds:
    tau_pos: float
    tau_neg: float
    n_calibration: int
    sample_recall: float
    sample_precision: float
    escalation_rate: float  # fraction of calibration items that land in the escalate band

    def to_dict(self) -> dict:
        return {
            "tau_pos": self.tau_pos,
            "tau_neg": self.tau_neg,
            "n_calibration": self.n_calibration,
            "sample_recall": self.sample_recall,
            "sample_precision": self.sample_precision,
            "escalation_rate": self.escalation_rate,
        }


# ── Hoeffding one-sided confidence bounds ─────────────────────────────────────

def _ub(mean: float, std: float, n: int, delta: float) -> float:
    if n <= 0:
        return mean
    return mean + (std / math.sqrt(n)) * math.sqrt(2 * math.log(1 / delta))


def _lb(mean: float, std: float, n: int, delta: float) -> float:
    if n <= 0:
        return mean
    return mean - (std / math.sqrt(n)) * math.sqrt(2 * math.log(1 / delta))


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _std(xs: list[float]) -> float:
    if not xs:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))


# ── Threshold learning ────────────────────────────────────────────────────────

# A (score, label, weight) triple. weight is the importance-sampling correction
# factor; for a fully-labelled calibration corpus it is 1.0 for every row.
_Triple = tuple[float, bool, float]


def _recall(tau_pos: float, tau_neg: float, pairs: list[_Triple]) -> float:
    """Recall of the *routed* pipeline. A truly-positive item is recalled if the proxy
    accepts it as positive (score ≥ tau_pos) OR it escalates (the oracle then catches it).
    Recall is only lost when the proxy accepts a NEGATIVE (score ≤ tau_neg) for a truly-
    positive item."""
    total_pos = sum(lbl * w for _, lbl, w in pairs)
    if total_pos <= 0:
        return 0.0
    accepted_pos = sum(1 for s, lbl, _ in pairs if s >= tau_pos and lbl)
    escalated_pos = sum(lbl * w for s, lbl, w in pairs if tau_neg < s < tau_pos)
    return (accepted_pos + escalated_pos) / total_pos


def _precision(tau_pos: float, tau_neg: float, pairs: list[_Triple]) -> float:
    """Precision of the routed pipeline: of everything ultimately called positive
    (proxy-accepted positives + oracle-confirmed escalations), the fraction truly positive."""
    escalated = [(s, lbl) for s, lbl, _ in pairs if tau_neg < s < tau_pos]
    oracle_pos = sum(1 for _, lbl in escalated if lbl)
    tp = sum(1 for s, lbl, _ in pairs if s >= tau_pos and lbl) + oracle_pos
    predicted_pos = sum(1 for s, _, _ in pairs if s >= tau_pos) + oracle_pos
    return tp / predicted_pos if predicted_pos > 0 else 0.0


def _tau_neg_for_recall(pairs: list[_Triple], tau_pos: float, recall_target: float) -> float:
    """Highest tau_neg whose recall still clears the target (scan low→high score)."""
    return max(
        (s for s, _, _ in reversed(pairs) if _recall(tau_pos, s, pairs) >= recall_target),
        default=0.0,
    )


def learn_thresholds(
    proxy_scores: list[float],
    oracle_labels: list[bool],
    config: CascadeConfig = CascadeConfig(),
    correction_factors: list[float] | None = None,
) -> CascadeThresholds:
    """Learn ``(tau_pos, tau_neg)`` from a calibration corpus of proxy scores + oracle labels.

    Returns thresholds whose routing meets ``recall_target``/``precision_target`` with
    probability ≥ 1 − ``failure_probability``. ``correction_factors`` defaults to 1.0 per
    row (a fully-labelled corpus); pass importance-sampling weights for partially-labelled
    corpora.
    """
    n = len(proxy_scores)
    if n != len(oracle_labels):
        raise ValueError("proxy_scores and oracle_labels must be the same length")
    if n < config.min_calibration_size:
        raise ValueError(
            f"need >= {config.min_calibration_size} calibration pairs to learn a guaranteed "
            f"threshold, got {n}"
        )
    cf = correction_factors if correction_factors is not None else [1.0] * n
    pairs: list[_Triple] = sorted(zip(proxy_scores, oracle_labels, cf), key=lambda x: x[0], reverse=True)
    delta = config.failure_probability

    # 1) tau_neg from the recall target (with a Hoeffding correction so the *true* recall holds).
    tau_pos = 1.0
    tau_neg = _tau_neg_for_recall(pairs, tau_pos, config.recall_target)

    z1 = [int(lbl) * w for s, lbl, w in pairs if s >= tau_neg]   # positives kept on the accept side
    z2 = [int(lbl) * w for s, lbl, w in pairs if s < tau_neg]    # positives lost below tau_neg
    ub_z1 = _ub(_mean(z1), _std(z1), n, delta / 2)
    lb_z2 = _lb(_mean(z2), _std(z2), n, delta / 2)
    corrected_recall = 1.0 if (ub_z1 + lb_z2) == 0 else min(1.0, ub_z1 / (ub_z1 + lb_z2))
    tau_neg = _tau_neg_for_recall(pairs, tau_pos, corrected_recall)

    # 2) tau_pos from the precision target (lowest cutoff whose lower-bounded precision clears it).
    candidates = [1.0]
    for s, _, _ in pairs:
        kept = [int(lbl) for sc, lbl, _ in pairs if sc >= s]
        p_lb = _lb(_mean([float(x) for x in kept]), _std([float(x) for x in kept]), len(kept), delta / n)
        if p_lb > config.precision_target:
            candidates.append(s)
    tau_pos = max(tau_neg, min(candidates))

    return CascadeThresholds(
        tau_pos=tau_pos,
        tau_neg=tau_neg,
        n_calibration=n,
        sample_recall=_recall(tau_pos, tau_neg, [(s, lbl, 1.0) for s, lbl, _ in pairs]),
        sample_precision=_precision(tau_pos, tau_neg, [(s, lbl, 1.0) for s, lbl, _ in pairs]),
        escalation_rate=sum(1 for s, _, _ in pairs if tau_neg < s < tau_pos) / n,
    )


def default_thresholds(tau_pos: float = 0.85, tau_neg: float = 0.15) -> CascadeThresholds:
    """Conservative, *uncalibrated* thresholds (no learned guarantee): accept only very
    clear-cut proxy scores, escalate the broad middle. Use as a safe default until a real
    calibration corpus is available to feed ``learn_thresholds``."""
    return CascadeThresholds(
        tau_pos=tau_pos, tau_neg=tau_neg, n_calibration=0,
        sample_recall=float("nan"), sample_precision=float("nan"), escalation_rate=float("nan"),
    )


# ── Runtime routing ────────────────────────────────────────────────────────────

def route(score: float, thresholds: CascadeThresholds) -> Decision:
    """Route a single proxy score: accept the cheap decision at the extremes, escalate the
    ambiguous middle."""
    if score >= thresholds.tau_pos:
        return "accept_positive"
    if score <= thresholds.tau_neg:
        return "accept_negative"
    return "escalate"
