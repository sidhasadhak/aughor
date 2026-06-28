"""Reliability-banding & held-out splitting for trustworthy NL2SQL measurement.

Cloud reasoning models are non-deterministic even at temperature 0, so a single run's pass/fail is
noisy and small aggregate deltas (±2 pts) are indistinguishable from churn. Two retired Spider2
experiments (formula-grounding "net 0" on 20 instances, faithful-EK "net -2" on 13) were judged at a
±~14pt floor on single runs — i.e. *unmeasured, not disproven*. This module is the fix:

  * run each instance N times,
  * classify each instance reliably-pass (≥ pass_hi) / reliably-fail (≤ pass_lo) / unstable,
  * compute the TRUE effect of a change as the net reliable pass↔fail flips, ignoring all
    unstable-band churn (that churn is the noise), with a McNemar exact p-value on the paired flips.

Plus a deterministic held-out split (by instance_id hash) so changes are tuned on dev and reported
on never-tuned held-out — guarding the small-slice overfit risk.

Pure functions, no model calls — fully unit-testable offline; the harness feeds it run outcomes.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass


# ── deterministic held-out split ──────────────────────────────────────────────

def _hash_unit(instance_id: str, salt: str) -> float:
    """Stable [0,1) hash of an id (so the split is reproducible across machines/runs)."""
    h = hashlib.sha1(f"{salt}:{instance_id}".encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def holdout_split(instance_ids, frac: float = 0.2, salt: str = "spider2") -> tuple[list[str], list[str]]:
    """Split ids into (dev, holdout). `holdout` gets ~`frac` of ids, chosen deterministically by
    hash (not by order/time), so the same ids always land in the same partition."""
    frac = min(max(frac, 0.0), 1.0)
    dev, holdout = [], []
    for iid in instance_ids:
        (holdout if _hash_unit(iid, salt) < frac else dev).append(iid)
    return dev, holdout


# ── reliability banding ───────────────────────────────────────────────────────

@dataclass
class Band:
    instance_id: str
    passes: int
    runs: int
    rate: float
    band: str   # "reliably_pass" | "reliably_fail" | "unstable"


def reliability_bands(outcomes: dict, *, pass_hi: float = 0.8, pass_lo: float = 0.2) -> dict:
    """outcomes: {instance_id: [bool, ...]} across N runs → {instance_id: Band}.

    reliably_pass when pass-rate ≥ pass_hi, reliably_fail when ≤ pass_lo, else unstable. The default
    0.8/0.2 thresholds mean ≥4/5 and ≤1/5 are "reliable"; 2–3/5 is noise."""
    bands: dict = {}
    for iid, runs in outcomes.items():
        n = len(runs)
        p = sum(1 for r in runs if r)
        rate = (p / n) if n else 0.0
        band = "reliably_pass" if rate >= pass_hi else "reliably_fail" if rate <= pass_lo else "unstable"
        bands[iid] = Band(iid, p, n, rate, band)
    return bands


def _mcnemar_p(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value on discordant pairs (b = fail→pass, c = pass→fail).
    Exact binomial test against p=0.5 on the b+c discordants. 1.0 when there are none."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    # two-sided exact binomial: 2 * sum_{i=0}^{k} C(n,i) (0.5)^n, capped at 1.0
    tail = sum(math.comb(n, i) for i in range(k + 1)) * (0.5 ** n)
    return min(1.0, 2.0 * tail)


@dataclass
class EffectReport:
    reliable_gain: int       # fail→pass on the reliable bands (true wins)
    reliable_loss: int       # pass→fail on the reliable bands (true regressions)
    net: int                 # reliable_gain - reliable_loss
    unstable_churn: int      # flips that touched the unstable band (noise — excluded from net)
    p_value: float           # McNemar exact on the reliable discordant flips
    detail: dict


def compare_runs(before: dict, after: dict, *, pass_hi: float = 0.8, pass_lo: float = 0.2) -> EffectReport:
    """Compare two {instance_id: [bool,...]} mappings and report the TRUE effect: net reliable
    pass↔fail flips, with unstable-band churn excluded (that's the noise). A change is real only if
    `net` is positive AND `p_value` is small."""
    ba, aa = reliability_bands(before, pass_hi=pass_hi, pass_lo=pass_lo), \
             reliability_bands(after, pass_hi=pass_hi, pass_lo=pass_lo)
    shared = set(ba) & set(aa)
    gain = loss = churn = 0
    gained, lost = [], []
    for iid in shared:
        x, y = ba[iid].band, aa[iid].band
        if x == "unstable" or y == "unstable":
            if x != y:
                churn += 1
            continue
        if x == "reliably_fail" and y == "reliably_pass":
            gain += 1; gained.append(iid)
        elif x == "reliably_pass" and y == "reliably_fail":
            loss += 1; lost.append(iid)
    return EffectReport(
        reliable_gain=gain, reliable_loss=loss, net=gain - loss, unstable_churn=churn,
        p_value=_mcnemar_p(gain, loss),
        detail={"gained": sorted(gained), "lost": sorted(lost), "n_compared": len(shared)})
