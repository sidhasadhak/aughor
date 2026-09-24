"""Overnight / weekly Intelligence Digest — M20c.

Aggregates:
  - Recent monitor alerts (last 7 days by default)
  - New exploration insights from the KB
  - New causal edges added since last digest
  - Open recommendations from the action hub

Returns a structured AlertSummary (Pydantic) and a Markdown render.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_ADJECTIVE = {"day": "Daily", "week": "Weekly", "month": "Monthly", "year": "Yearly"}


def period_adjective(period: str) -> str:
    """"Daily" for "day". The header was ``period.capitalize() + "ly"``, which every daily
    alert summary ever sent printed as "Dayly" (measured 2026-09-23; only "Weekly" had a test)."""
    return _ADJECTIVE.get(period, f"{str(period).capitalize()}ly")


class AlertSummarySection(BaseModel):
    title: str
    items: list[str] = Field(default_factory=list)
    #: HB-2 — what kind of claim this section's lines make, so the departure gate judges each
    #: line by it: ``monitor_alerts`` (dated records a person declared) · ``findings`` ·
    #: ``causal_links`` · ``recommendations`` · ``review_queue`` · ``held``.
    kind: str = ""


class AlertSummary(BaseModel):
    conn_id: str
    period: str                     # "week" | "day"
    generated_at: str
    sections: list[AlertSummarySection] = Field(default_factory=list)
    alert_count: int = 0
    critical_count: int = 0

    def to_markdown(self) -> str:
        lines = [
            f"# Aughor Intelligence Digest — {period_adjective(self.period)}",
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

def build_alert_summary(conn_id: str, period: str = "week") -> AlertSummary:
    """Aggregate recent activity into a AlertSummary.

    Args:
        conn_id: Connection to scope the digest to.
        period:  'week' (7 days) or 'day' (24 hours).
    """
    days = 7 if period == "week" else 1
    since = datetime.now(timezone.utc) - timedelta(days=days)
    since_iso = since.isoformat()
    now_iso = datetime.now(timezone.utc).isoformat()

    sections: list[AlertSummarySection] = []
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
            sections.append(AlertSummarySection(title="Monitor Alerts", items=items,
                                                 kind="monitor_alerts"))
    except Exception as exc:
        logger.debug("Digest: monitor alerts section failed: %s", exc)

    # ── 2. New exploration insights ─────────────────────────────────────────
    try:
        # This section was dead for EVERY connection: it imported a function that
        # never existed (load_exploration_state) and read store keys from an old
        # shape (phase_7/phase_4) — both silently swallowed. Read the real store:
        # aggregated insights across per-schema runs.
        import re as _re

        from aughor.explorer.store import load_aggregate
        state = load_aggregate(conn_id)
        raw_insights = []
        for ins in state.get("insights", []) or []:
            if ins.get("invalid"):
                continue
            text = (ins.get("finding") or "").strip()
            if text and len(text) > 20:
                # First sentence — split on sentence boundary, not every '.',
                # or "dropped 38.8%" truncates to "dropped 38."
                first = _re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0].strip()
                first = first if first.endswith((".", "!", "?")) else first + "."
                # HB-2 law 4 — a finding leaving in a briefing says when it was found: its
                # numbers are that day's measurement, and the reader is told so.
                found = str(ins.get("generated_at") or "")[:10]
                raw_insights.append(f"{first} (found {found})" if found else first)
        if raw_insights:
            sections.append(AlertSummarySection(
                title="Exploration Insights",
                items=raw_insights[:8],
                kind="findings",
            ))
    except Exception as exc:
        logger.debug("Digest: exploration section failed: %s", exc)

    # ── 3. Causal edges ─────────────────────────────────────────────────────
    try:
        from aughor.lifecycle.causal import load_causal_graph
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
                sections.append(AlertSummarySection(title="Top Causal Relationships", items=items,
                                                     kind="causal_links"))
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
            sections.append(AlertSummarySection(title="Open Recommendations", items=items,
                                                 kind="recommendations"))
    except Exception as exc:
        logger.debug("Digest: recommendations section failed: %s", exc)

    # ── 5. Evidence claims summary ──────────────────────────────────────────
    try:
        # Count claims needing review
        from pathlib import Path as _P

        from aughor.db.backend import connect_store, is_postgres
        from aughor.db.sqlite_util import resolve_db_path
        _ev_path = resolve_db_path("AUGHOR_EVIDENCE_DB", _P("data") / "evidence_ledger.db")
        # The file-existence guard is meaningless on Postgres — there the store's
        # schema exists (or the query fails into this function's best-effort catch).
        if is_postgres() or _ev_path.exists():
            with connect_store(_ev_path, row_factory=True) as _c:
                unreviewed = _c.execute(
                    "SELECT COUNT(*) AS n FROM evidence_claims WHERE owner_feedback IS NULL"
                ).fetchone()["n"]
            if unreviewed:
                sections.append(AlertSummarySection(
                    title="Evidence Review Queue",
                    items=[f"{unreviewed} claim(s) awaiting validation — open the Evidence tab to review."],
                    kind="review_queue",
                ))
    except Exception as exc:
        logger.debug("Digest: evidence section failed: %s", exc)

    return AlertSummary(
        conn_id=conn_id,
        period=period,
        generated_at=now_iso,
        sections=sections,
        alert_count=alert_count,
        critical_count=critical_count,
    )
