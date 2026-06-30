"""Overnight / weekly Intelligence Digest — M20c.

Aggregates:
  - Recent monitor alerts (last 7 days by default)
  - New exploration insights from the KB
  - New causal edges added since last digest
  - Open recommendations from the action hub

Returns a structured DigestResult (Pydantic) and a Markdown render.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class DigestSection(BaseModel):
    title: str
    items: list[str] = Field(default_factory=list)


class DigestResult(BaseModel):
    conn_id: str
    period: str                     # "week" | "day"
    generated_at: str
    sections: list[DigestSection] = Field(default_factory=list)
    alert_count: int = 0
    critical_count: int = 0

    def to_markdown(self) -> str:
        lines = [
            f"# Aughor Intelligence Digest — {self.period.capitalize()}ly",
            f"*Generated {self.generated_at[:16].replace('T', ' ')} UTC*",
            "",
        ]
        if self.alert_count:
            lines.append(
                f"> **{self.alert_count} monitor alert(s)** this period"
                + (f" · {self.critical_count} critical" if self.critical_count else "")
            )
            lines.append("")
        for section in self.sections:
            if not section.items:
                continue
            lines.append(f"## {section.title}")
            for item in section.items:
                lines.append(f"- {item}")
            lines.append("")
        if not any(s.items for s in self.sections):
            lines.append("*No significant activity this period.*")
        return "\n".join(lines)


# ── Builder ────────────────────────────────────────────────────────────────────

def build_digest(conn_id: str, period: str = "week") -> DigestResult:
    """Aggregate recent activity into a DigestResult.

    Args:
        conn_id: Connection to scope the digest to.
        period:  'week' (7 days) or 'day' (24 hours).
    """
    days = 7 if period == "week" else 1
    since = datetime.now(timezone.utc) - timedelta(days=days)
    since_iso = since.isoformat()
    now_iso = datetime.now(timezone.utc).isoformat()

    sections: list[DigestSection] = []
    alert_count = 0
    critical_count = 0

    # ── 1. Monitor alerts ───────────────────────────────────────────────────
    try:
        from aughor.monitors.store import get_alerts
        all_alerts = get_alerts(conn_id=conn_id, limit=200)
        recent_alerts = [
            a for a in all_alerts
            if a.triggered_at >= since_iso
        ]
        alert_count = len(recent_alerts)
        critical_count = sum(1 for a in recent_alerts if a.severity == "critical")

        if recent_alerts:
            items = []
            for a in recent_alerts[:10]:          # cap to avoid wall of text
                ts = a.triggered_at[:16].replace("T", " ")
                badge = "🔴" if a.severity == "critical" else "🟡"
                items.append(f"{badge} [{ts}] {a.message}")
            if len(recent_alerts) > 10:
                items.append(f"… and {len(recent_alerts) - 10} more alerts")
            sections.append(DigestSection(title="Monitor Alerts", items=items))
    except Exception as exc:
        logger.debug("Digest: monitor alerts section failed: %s", exc)

    # ── 2. New exploration insights ─────────────────────────────────────────
    try:
        from aughor.explorer.store import load_exploration_state
        state = load_exploration_state(conn_id)
        if state:
            raw_insights = []
            # Phase 7 (anomalies) and phase 4 (distributions) findings
            for phase_key in ("phase_7", "phase_4", "data_quality_notes"):
                phase = state.get(phase_key) or {}
                for finding in (phase.get("findings") or []):
                    text = finding.get("interpretation") or finding.get("description") or ""
                    if text and len(text) > 20:
                        raw_insights.append(text.split(".")[0].strip() + ".")
            if raw_insights:
                sections.append(DigestSection(
                    title="Exploration Insights",
                    items=raw_insights[:8],
                ))
    except Exception as exc:
        logger.debug("Digest: exploration section failed: %s", exc)

    # ── 3. Causal edges ─────────────────────────────────────────────────────
    try:
        from aughor.process.causal import load_causal_graph
        graph = load_causal_graph(conn_id)
        if graph:
            edges = graph.get("edges") or []
            # Surface the top-weight edges
            top = sorted(edges, key=lambda e: abs(e.get("weight", 0)), reverse=True)[:5]
            if top:
                items = [
                    f"{e.get('source', '?')} → {e.get('target', '?')} "
                    f"(strength: {e.get('weight', 0):.2f})"
                    for e in top
                ]
                sections.append(DigestSection(title="Top Causal Relationships", items=items))
    except Exception as exc:
        logger.debug("Digest: causal graph section failed: %s", exc)

    # ── 4. Open recommendations ─────────────────────────────────────────────
    try:
        from aughor.routers.actions import _load_actions  # type: ignore
        actions = _load_actions()
        open_recs = [
            a for a in (actions or [])
            if a.get("status") in ("open", "pending", None)
        ][:5]
        if open_recs:
            items = [
                f"{a.get('title', 'Untitled')} — {a.get('description', '')[:80]}"
                for a in open_recs
            ]
            sections.append(DigestSection(title="Open Recommendations", items=items))
    except Exception as exc:
        logger.debug("Digest: recommendations section failed: %s", exc)

    # ── 5. Evidence claims summary ──────────────────────────────────────────
    try:
        # Count claims needing review
        import sqlite3 as _sq
        from pathlib import Path as _P
        _ev_path = _P("data") / "evidence_ledger.db"
        if _ev_path.exists():
            with _sq.connect(str(_ev_path)) as _c:
                _c.row_factory = _sq.Row
                unreviewed = _c.execute(
                    "SELECT COUNT(*) AS n FROM evidence_claims WHERE owner_feedback IS NULL"
                ).fetchone()["n"]
            if unreviewed:
                sections.append(DigestSection(
                    title="Evidence Review Queue",
                    items=[f"{unreviewed} claim(s) awaiting validation — open the Evidence tab to review."],
                ))
    except Exception as exc:
        logger.debug("Digest: evidence section failed: %s", exc)

    return DigestResult(
        conn_id=conn_id,
        period=period,
        generated_at=now_iso,
        sections=sections,
        alert_count=alert_count,
        critical_count=critical_count,
    )
