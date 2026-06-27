"""Trust economy (Bet 4) — autonomy is earned from human verdicts, not configured.

A specialist's rope is governed by its track record (the 0-V verdict store), calibrated
against EXTERNAL signal (human acceptance), never self-grading. New/weak experts run in
shadow (propose-only); proven ones earn routing weight and autonomy. Pure functions over a
verdict-stats dict ({counts, total, acceptance_rate}); the live read is verify.verdict_stats.
"""
from __future__ import annotations

# Tiers, least → most rope.
SHADOW = "shadow"        # propose-only; never routes live, never acts
ASSISTED = "assisted"    # routes live + proposes; a human approves actions
TRUSTED = "trusted"      # may act autonomously on reversible work

_MIN_SAMPLE = 5          # below this, there isn't enough evidence to grant any rope


def autonomy_tier(stats: dict) -> str:
    """Earned tier from the verdict record. Conservative: insufficient sample → shadow."""
    total = int((stats or {}).get("total", 0) or 0)
    acc = (stats or {}).get("acceptance_rate")
    if total < _MIN_SAMPLE or acc is None:
        return SHADOW
    if acc >= 0.8 and total >= 20:
        return TRUSTED
    if acc >= 0.6:
        return ASSISTED
    return SHADOW


def routing_weight(stats: dict) -> float:
    """A multiplier on a pack's routing score (Bet 3 uses it to prefer trusted experts).
    Ranges ~0.5 (poor track record) to ~1.5 (strong); 1.0 when there's no evidence yet."""
    total = int((stats or {}).get("total", 0) or 0)
    acc = (stats or {}).get("acceptance_rate")
    if total < _MIN_SAMPLE or acc is None:
        return 1.0
    # centre on acceptance 0.7; ±0.5 swing, gently scaled by how much evidence we have.
    confidence = min(total / 50.0, 1.0)
    return round(1.0 + (acc - 0.7) * confidence, 3)


def tier_allows(tier: str, action: str) -> bool:
    """Does `tier` permit `action` in {'route','propose','act'}?"""
    if action == "propose":
        return tier in (SHADOW, ASSISTED, TRUSTED)
    if action == "route":
        return tier in (ASSISTED, TRUSTED)
    if action == "act":
        return tier == TRUSTED
    return False
