"""Monitor + MonitorAlert data models."""
from __future__ import annotations

import uuid
from typing import Literal, Optional

from pydantic import BaseModel, Field


def _new_id() -> str:
    return str(uuid.uuid4())


class Monitor(BaseModel):
    """A scheduled metric check."""

    id: str = Field(default_factory=_new_id)
    conn_id: str = Field(description="Connection this monitor runs against")
    name: str = Field(description="Human-readable label, e.g. 'Revenue drop alert'")
    metric_name: Optional[str] = Field(
        default=None,
        description="Name of a MetricDefinition in the catalog; used to resolve SQL. "
                    "Set to None for custom_sql monitors.",
    )
    custom_sql: Optional[str] = Field(
        default=None,
        description="Explicit scalar SQL expression; overrides metric_name SQL when set.",
    )
    reanchor_window: bool = Field(
        default=False,
        description="When True, slide the SQL's absolute date window to the data's live "
                    "activity edge at run time (relative trailing window). Set for monitors "
                    "created from a Briefing finding so a frozen window can't go stale.",
    )
    # Scheduling
    check_cron: str = Field(
        default="0 * * * *",
        description="Cron expression (UTC) for how often to check. Default = hourly.",
    )
    grace_period_hours: float = Field(
        default=4.0,
        description="Anti-flap debounce: after an alert fires, suppress further alerts of the "
                    "same-or-lower severity until this many hours pass — so a sustained breach "
                    "reminds at most once per window instead of every cron tick, and a metric "
                    "oscillating around a threshold doesn't spam. Escalations (warning→critical) "
                    "always fire immediately; set to 0 to disable suppression.",
    )
    # Alert condition
    alert_on: Literal[
        "threshold_cross",   # value crosses warning_threshold or critical_threshold
        "trend_reversal",    # sign of rolling change flips (up→down or down→up)
        "anomaly",           # z-score / STL seasonal deviation > sigma_threshold
        "segment_drift",     # Chi-squared distribution shift across a dimension
        "data_freshness",    # MAX(updated_at) hasn't advanced within freshness_sla_hours
        "any_change",        # fire on every non-null value change
    ] = "threshold_cross"

    # Threshold-based options
    warning_threshold: Optional[float] = Field(
        default=None,
        description="Yellow-zone boundary. For 'lower is worse' metrics, set this above target.",
    )
    critical_threshold: Optional[float] = Field(
        default=None,
        description="Red-zone boundary.",
    )
    threshold_direction: Literal["below", "above"] = Field(
        default="below",
        description="'below' = alert when value falls below threshold (e.g. revenue). "
                    "'above' = alert when value rises above threshold (e.g. error rate).",
    )

    # Anomaly options
    sigma_threshold: float = Field(
        default=2.5,
        description="Number of standard deviations from rolling mean to trigger anomaly alert.",
    )
    history_days: int = Field(
        default=30,
        description="How many days of history to use for anomaly / trend calculations.",
    )

    # Segment drift options
    dimension_column: Optional[str] = Field(
        default=None,
        description="Column to slice metric by for segment drift detection (e.g. 'region').",
    )
    drift_p_threshold: float = Field(
        default=0.05,
        description="Chi-squared p-value threshold below which drift is considered significant.",
    )

    # Data freshness options
    freshness_table: Optional[str] = Field(
        default=None,
        description="Table to check MAX(updated_at) on for freshness monitors.",
    )
    freshness_column: str = Field(
        default="updated_at",
        description="Timestamp column for freshness check.",
    )
    freshness_sla_hours: float = Field(
        default=24.0,
        description="Expected maximum gap (hours) between the latest row and now.",
    )

    # Notification
    notification_channel: str = Field(
        default="in_app",
        description="Delivery channel: 'in_app' | 'slack' | 'email' (only in_app wired currently).",
    )
    enabled: bool = True
    created_at: str = Field(default="")
    updated_at: str = Field(default="")


class MonitorAlert(BaseModel):
    """A fired monitor alert, persisted to data/monitor_alerts.db."""

    id: str = Field(default_factory=_new_id)
    monitor_id: str
    monitor_name: str = ""
    conn_id: str = ""
    metric_name: Optional[str] = None
    triggered_at: str = Field(description="ISO-8601 UTC timestamp")
    alert_on: str = ""
    severity: Literal["warning", "critical", "info"] = "warning"
    current_value: Optional[float] = None
    previous_value: Optional[float] = None
    threshold: Optional[float] = None
    message: str = ""
    acknowledged: bool = False
    acknowledged_at: Optional[str] = None
