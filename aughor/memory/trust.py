"""Earned autonomy — the trust → L0–L3 ladder.

A connection EARNS autonomy from its track record, not a setting. The signals come from
`memory.record_run` (persisted per finished investigation): a run is "clean" when it was
**grounded** (its numbers traced to result cells) AND **read-only**. A connection with enough
clean, high-confidence runs climbs the ladder; at **L2 (supervised)** a strong run
auto-crystallizes into a learned skill (still EXPLAIN-gated), below it everything is a
UI-confirmed candidate. Conservative by design — L0 is the safe floor and the thresholds need a
real sample, so a connection can't accidentally earn auto-execution.

Replaces the inert stubs (contracts unchanged: `routers/ontology.py` `/ontology/autonomy` +
the skill-use endpoint, and `memory.skills._autonomy_level`).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_LEVELS = {0: "manual", 1: "assisted", 2: "supervised", 3: "autonomous"}

# Conservative ladder, evaluated high → low (first match wins):
#   (level, min_clean_runs, min_clean_rate, min_mean_confidence)
# A "clean" run is grounded AND read-only; mean-confidence is only enforced where recorded.
_RUNGS = (
    (3, 50, 0.95, 0.80),
    (2, 20, 0.90, 0.00),
    (1, 5, 0.80, 0.00),
)


def _runs_for(connection_id: str) -> list:
    """All recorded run signals for this connection (from data/agent_runs.json)."""
    try:
        from aughor.memory.paths import agent_runs_path
        from aughor.util.json_store import KeyedJsonStore
        allruns = KeyedJsonStore(agent_runs_path(), max_entries=2000).load() or {}
    except Exception as exc:
        logger.debug("autonomy: runs store read failed: %s", exc)
        return []
    return [r for r in allruns.values() if isinstance(r, dict) and r.get("connection_id") == connection_id]


def _signals(runs: list) -> dict:
    n = len(runs)
    clean = [r for r in runs if r.get("grounded") and r.get("read_only", True)]
    confs = [float(r["confidence"]) for r in runs if isinstance(r.get("confidence"), (int, float))]
    return {
        "runs": n,
        "clean": len(clean),
        "clean_rate": round(len(clean) / n, 3) if n else 0.0,
        "mean_confidence": round(sum(confs) / len(confs), 3) if confs else None,
    }


def _level_from_signals(s: dict) -> int:
    clean, rate, mc = s["clean"], s["clean_rate"], s["mean_confidence"]
    for level, min_clean, min_rate, min_mc in _RUNGS:
        if clean >= min_clean and rate >= min_rate and (mc is None or mc >= min_mc):
            return level
    return 0


def autonomy_level(connection_id: str) -> dict:
    """The connection's earned L0–L3 autonomy, computed from its recorded run signals.
    Fail-safe: any error floors to L0 (manual)."""
    try:
        s = _signals(_runs_for(connection_id))
        level = _level_from_signals(s)
        reason = (
            f"{s['clean']}/{s['runs']} clean runs ({int(s['clean_rate'] * 100)}% grounded + read-only)"
            if s["runs"] else "No recorded runs yet — manual (L0)."
        )
        return {"connection_id": connection_id, "level": level, "label": _LEVELS[level],
                "signals": s, "reason": reason}
    except Exception as exc:
        logger.debug("autonomy_level(%s) floored to L0: %s", connection_id, exc)
        return {"connection_id": connection_id, "level": 0, "label": _LEVELS[0],
                "signals": {}, "reason": "Autonomy computation failed — manual (L0)."}


# usage_count → a per-skill rung, capped by the connection's earned level (a skill can't be more
# autonomous than the connection that owns it). Evaluated high → low.
_USAGE_RUNGS = ((3, 20), (2, 5), (1, 1))


def skill_autonomy(usage_count: int, connection_id: str) -> dict:
    """Per-skill autonomy from its reuse count, capped by the connection's earned level."""
    usage_level = 0
    for level, min_uses in _USAGE_RUNGS:
        if (usage_count or 0) >= min_uses:
            usage_level = level
            break
    conn_level = autonomy_level(connection_id).get("level", 0)
    level = min(usage_level, conn_level)
    return {"connection_id": connection_id, "usage_count": usage_count,
            "level": level, "label": _LEVELS[level]}
