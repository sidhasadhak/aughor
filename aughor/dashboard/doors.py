"""What every door that makes a card shares: the guard it is run through, and the card a
finding becomes.

These lived inside ``routers/dashboard.py`` and were the router's own. Arc CT's CT-5 makes
cards from a second place — an approved cockpit proposal — and a card made there is owed the
same guarantee as one pinned from the Briefing: it ran cleanly through the guard battery
before it was stored. So the guard and the builder moved here, and both doors call them.

Nothing here knows about HTTP. A refusal is :class:`GuardRefused`, whose ``str`` is the
sentence to show; the router turns it into a status code, a proposal into a refusal.
"""
from __future__ import annotations

from typing import Any, Optional

from aughor.dashboard.models import CardProvenance, DashboardCard
from aughor.kernel.errors import tolerate


class GuardRefused(Exception):
    """A query that may not become a card. ``missing_connection`` tells the two reasons
    apart: the connection could not be opened, or the query did not run cleanly on it."""

    def __init__(self, sentence: str, *, missing_connection: bool = False) -> None:
        super().__init__(sentence)
        self.missing_connection = missing_connection


def run_guarded(connection_id: str, sql: str, *, query_id: str, schema: Optional[str] = None):
    """Open the connection, run ``sql`` through the deterministic guard battery, and return
    the clean result — or raise :class:`GuardRefused`. Nothing is stored either way."""
    from aughor.db.connection import open_connection_for, open_connection_for_with_schema
    from aughor.sql.executor import execute_guarded

    try:
        db = (
            open_connection_for_with_schema(connection_id, schema_name=schema)
            if schema else open_connection_for(connection_id)
        )
    except Exception as e:
        raise GuardRefused(f"Connection not found: {e}", missing_connection=True)
    try:
        result = execute_guarded(db, sql, query_id=query_id, schema=schema)
    finally:
        try:
            db.close()
        except Exception as exc:
            tolerate(exc, "dashboard: connection close failed after guarded query", counter="dashboard.db_close")
    if result.error:
        raise GuardRefused(f"Query failed the trust guards, not pinned: {result.error}")
    return result


def scalar_of(result: Any) -> Optional[float]:
    """A single numeric cell → the card's tracked value; else None (chart/table card)."""
    if result.error or result.row_count != 1 or len(result.columns or []) != 1:
        return None
    try:
        return float((result.rows or [[None]])[0][0])
    except (TypeError, ValueError, IndexError):
        return None


def kind_of(result: Any) -> str:
    """What a card drawn from this result is: one number is a figure, anything else a chart."""
    return "kpi" if scalar_of(result) is not None else "chart"


def clip_title(title: str, fallback: str) -> str:
    """A human card label: the given title (or the fallback when blank), clipped to ~120 chars."""
    t = (title or "").strip() or fallback
    return (t[:117].rstrip() + "…") if len(t) > 120 else t


def card_from_finding(connection_id: str, finding: dict, *, kind: str, title: Optional[str] = None,
                      scope: str = "canvas", scope_ref: str = "", card_id: str = "") -> DashboardCard:
    """The card a finding becomes, linked back to the finding and to its receipt. Not stored:
    the caller stores it, once the query has passed :func:`run_guarded`."""
    found = str(finding.get("id") or "")
    said = (finding.get("finding") or "").strip()
    return DashboardCard(
        id=card_id,
        connection_id=connection_id,
        scope=scope,
        scope_ref=scope_ref,
        source="insight",
        kind=kind,
        title=clip_title(title or said, "Pinned finding"),
        sql=(finding.get("sql") or "").strip(),
        provenance=CardProvenance(
            insight_id=found,
            receipt_ref=f"insight:{connection_id}:{found}",
        ),
        links=[found],
    )
