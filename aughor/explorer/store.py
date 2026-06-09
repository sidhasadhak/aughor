"""
Persistence for exploration state and findings.
Connection-scoped: data/exploration_{connection_id}.json
Canvas-scoped:     data/exploration_canvas_{canvas_id}.json
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from aughor.explorer.models import ExplorationPhase

_DATA_DIR = Path("data")


def _path(connection_id: str) -> Path:
    return _DATA_DIR / f"exploration_{connection_id}.json"


def _canvas_path(canvas_id: str) -> Path:
    return _DATA_DIR / f"exploration_canvas_{canvas_id}.json"


def _empty() -> dict:
    return {
        "schema_fingerprint": None,
        "phase": ExplorationPhase.PENDING.value,
        "null_meanings": {},        # {"table:column": {meaning, business_rule, ...}}
        "join_verifications": [],   # [{"key", "orphan_count", "verified", "cardinality", ...}]
        "lifecycle_maps": {},       # {"table": {status_column, states, terminal_states, ...}}
        "distributions": {},        # {"table:column": {shape, p25, p50, p75, ...}}
        "insights": [],             # [{id, domain, angle, finding, sql, novelty, ...}]
        "domain_budgets": {},       # {domain: queries_used}
        "domain_coverage": {},      # {domain: [angles_covered]}
    }


def load(connection_id: str) -> dict:
    p = _path(connection_id)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return _empty()


def save(connection_id: str, state: dict) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        _path(connection_id).write_text(json.dumps(state, indent=2, default=str))
    except Exception:
        pass


def is_complete(connection_id: str, schema_fingerprint: str | None = None) -> bool:
    """True if exploration is marked complete (and optionally fingerprint matches)."""
    state = load(connection_id)
    if state.get("phase") != ExplorationPhase.COMPLETE.value:
        return False
    if schema_fingerprint is not None:
        return state.get("schema_fingerprint") == schema_fingerprint
    return True


def get_insights(connection_id: str) -> list[dict]:
    return load(connection_id).get("insights", [])


def get_domain_insights(connection_id: str) -> dict[str, list[dict]]:
    """Return insights grouped by domain."""
    grouped: dict[str, list[dict]] = {}
    for ins in get_insights(connection_id):
        d = ins.get("domain", "General")
        grouped.setdefault(d, []).append(ins)
    return grouped


def extend_domain_budget(connection_id: str, domain: str, extra: int = 5) -> int:
    """Add `extra` queries to a domain's budget cap. Returns the new cap value."""
    state = load(connection_id)
    key = f"{domain}__cap"
    current = state.get("domain_budgets", {}).get(key, 15)
    new_cap = current + extra
    state.setdefault("domain_budgets", {})[key] = new_cap
    save(connection_id, state)
    return new_cap


def get_lifecycle_maps(connection_id: str) -> dict:
    return load(connection_id).get("lifecycle_maps", {})


def get_null_meanings(connection_id: str) -> dict:
    return load(connection_id).get("null_meanings", {})


_NULL_MEANING_LABELS: dict[str, str] = {
    "pending":                  "event not yet occurred",
    "not_applicable_terminal":  "entity in terminal state — will never occur",
    "missing":                  "data quality issue — value should exist",
    "mixed":                    "pattern varies by status (check lifecycle)",
    "not_applicable":           "always populated (null rate ≈ 0)",
    "unknown":                  "meaning unclear",
}


def render_exploration_annotations(connection_id: str) -> str:
    """
    Return a formatted intelligence block for injection into the schema context.

    Only includes sections that have data.  Returns "" when exploration has not
    yet produced any findings (pending / failed phase, or no data written yet).
    """
    state = load(connection_id)
    phase = state.get("phase", "pending")
    if phase in ("pending", "failed"):
        return ""

    sections: list[str] = []

    # ── Null semantics ────────────────────────────────────────────────────────
    null_meanings: dict = state.get("null_meanings", {})
    meaningful = {k: v for k, v in null_meanings.items()
                  if v.get("meaning") not in ("not_applicable", "unknown")}
    if meaningful:
        lines = [
            "NULL SEMANTICS (verified — NULL in these columns carries business meaning):"
        ]
        for key, nm in meaningful.items():
            col_label = key.replace(":", ".")
            label = _NULL_MEANING_LABELS.get(nm.get("meaning", ""), nm.get("meaning", ""))
            rate = nm.get("null_rate", 0)
            line = f"  {col_label}: NULL = {label}  ({rate:.0%} null rate)"
            if nm.get("business_rule"):
                line += f"\n    rule: {nm['business_rule']}"
            lines.append(line)
        sections.append("\n".join(lines))

    # ── Entity lifecycle ───────────────────────────────────────────────────────
    lifecycle_maps: dict = state.get("lifecycle_maps", {})
    if lifecycle_maps:
        lines = ["ENTITY LIFECYCLE (verified state machines):"]
        for table, lm in lifecycle_maps.items():
            col = lm.get("status_column", "?")
            active   = lm.get("active_states", [])
            terminal = lm.get("terminal_states", [])
            active_str   = ", ".join(active)   if active   else "—"
            terminal_str = ", ".join(terminal) if terminal else "—"
            lines.append(f"  {table}.{col}")
            lines.append(f"    active:   {active_str}")
            lines.append(f"    terminal: {terminal_str}")
            if terminal:
                tl = ", ".join(f"'{s}'" for s in terminal)
                lines.append(f"    active filter: {col} NOT IN ({tl})")
        sections.append("\n".join(lines))

    # ── Join verification ──────────────────────────────────────────────────────
    join_verifications: list = state.get("join_verifications", [])
    broken = [j for j in join_verifications if not j.get("verified") and j.get("orphan_count", 0) > 0]
    if broken:
        lines = ["JOIN INTEGRITY (caution — orphaned FK rows detected):"]
        for j in broken:
            lines.append(
                f"  {j['from_table']}.{j['from_col']} → {j['to_table']}.{j['to_col']}"
                f"  ({j['orphan_count']:,} orphan rows)"
            )
        sections.append("\n".join(lines))

    # ── Domain intelligence insights ──────────────────────────────────────────
    insights: list = state.get("insights", [])
    if insights:
        # Group by domain for the schema context block
        by_domain: dict[str, list] = {}
        for ins in insights:
            d = ins.get("domain", "General")
            by_domain.setdefault(d, []).append(ins)
        lines = ["BUSINESS INTELLIGENCE (domain-level findings, autonomously discovered):"]
        for domain, dins in by_domain.items():
            lines.append(f"  [{domain}]")
            for ins in dins[:4]:
                lines.append(f"    • {ins.get('finding', '')}")
        sections.append("\n".join(lines))

    if not sections:
        return ""

    header = (
        "EXPLORATION INTELLIGENCE"
        f" [{ExplorationPhase(phase).name if phase in ExplorationPhase._value2member_map_ else phase}]"  # type: ignore[attr-defined]
        " — background cartography, treat as authoritative:"
    )
    return header + "\n\n" + "\n\n".join(sections)


# ── Canvas-scoped variants ────────────────────────────────────────────────────

def load_canvas(canvas_id: str) -> dict:
    p = _canvas_path(canvas_id)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return _empty()


def save_canvas(canvas_id: str, state: dict) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        _canvas_path(canvas_id).write_text(json.dumps(state, indent=2, default=str))
    except Exception:
        pass


def get_insights_canvas(canvas_id: str) -> list[dict]:
    return load_canvas(canvas_id).get("insights", [])


def get_domain_insights_canvas(canvas_id: str) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for ins in get_insights_canvas(canvas_id):
        d = ins.get("domain", "General")
        grouped.setdefault(d, []).append(ins)
    return grouped


def extend_domain_budget_canvas(canvas_id: str, domain: str, extra: int = 5) -> int:
    state = load_canvas(canvas_id)
    key = f"{domain}__cap"
    current = state.get("domain_budgets", {}).get(key, 15)
    new_cap = current + extra
    state.setdefault("domain_budgets", {})[key] = new_cap
    save_canvas(canvas_id, state)
    return new_cap


def promote_insight(canvas_id: str, insight_id: str) -> bool:
    """Mark a canvas insight as promoted to Org intelligence. Returns True on success."""
    state = load_canvas(canvas_id)
    for ins in state.get("insights", []):
        if ins.get("id") == insight_id:
            ins["promoted_to_org"] = True
            ins["promotion_confidence"] = ins.get("confidence", 0.0)
            save_canvas(canvas_id, state)
            return True
    return False


def promote_insight_conn(connection_id: str, insight_id: str) -> Optional[dict]:
    """Mark a connection-scoped insight as promoted to Org intelligence.

    Returns the promoted insight dict on success, None if the insight is not found.
    Mirrors promote_insight() but operates on connection-scoped exploration state
    (data/exploration_{connection_id}.json) so Briefing/Hub findings that live at
    the connection level — not just canvas insights — can be promoted org-wide.
    """
    state = load(connection_id)
    for ins in state.get("insights", []):
        if ins.get("id") == insight_id:
            ins["promoted_to_org"] = True
            ins["promotion_confidence"] = ins.get("confidence", 0.0)
            save(connection_id, state)
            return ins
    return None


def canvas_has_state(canvas_id: str) -> bool:
    return _canvas_path(canvas_id).exists()
