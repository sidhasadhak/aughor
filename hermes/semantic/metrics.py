"""
Metrics Catalog — Phase 1e.

Named business KPI formulas stored in data/metrics.json and injected into
every schema context so the LLM uses the same approved SQL expression for
MRR, CAC, LTV, etc. rather than re-deriving them on every investigation.

Relationship to the Business Glossary:
  Glossary  = what data IS  (table/column semantics, grain, caveats)
  Metrics   = what to COMPUTE (approved SQL formulas, dimensions, filters)

If a metric overlaps with a glossary column annotation, the Metrics Catalog
takes precedence for formula definitions.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

_DEFAULT_PATH = Path(__file__).parent.parent.parent / "data" / "metrics.json"


class MetricDefinition(BaseModel):
    name: str = Field(description="Unique snake_case identifier, e.g. 'mrr'")
    label: str = Field(description="Human-readable display name, e.g. 'Monthly Recurring Revenue'")
    sql: str = Field(description="Approved SQL expression, e.g. \"SUM(amount) FILTER (WHERE status='active')\"")
    tables: list[str] = Field(default_factory=list, description="Tables this metric draws from")
    dimensions: list[str] = Field(default_factory=list, description="Columns the metric can be sliced by")
    filters: list[str] = Field(default_factory=list, description="Default WHERE conditions always applied")
    unit: Optional[str] = Field(default=None, description="Display unit: '$', '%', 'days', etc.")
    caveats: Optional[str] = Field(default=None, description="Finance/data-team approved caveats or exclusions")


# ── Persistence ───────────────────────────────────────────────────────────────

def _load_raw(path: Path | None = None) -> list[dict]:
    p = path or _DEFAULT_PATH
    if not p.exists():
        return []
    with open(p) as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def _save_raw(metrics: list[dict], path: Path | None = None) -> None:
    p = path or _DEFAULT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        json.dump(metrics, f, indent=2)


# ── Public API ────────────────────────────────────────────────────────────────

def list_metrics(path: Path | None = None) -> list[MetricDefinition]:
    return [MetricDefinition(**m) for m in _load_raw(path)]


def get_metric(name: str, path: Path | None = None) -> MetricDefinition | None:
    for m in _load_raw(path):
        if m.get("name") == name:
            return MetricDefinition(**m)
    return None


def save_metric(metric: MetricDefinition, path: Path | None = None) -> None:
    """Upsert a metric by name."""
    raw = _load_raw(path)
    for i, m in enumerate(raw):
        if m.get("name") == metric.name:
            raw[i] = metric.model_dump()
            _save_raw(raw, path)
            return
    raw.append(metric.model_dump())
    _save_raw(raw, path)


def delete_metric(name: str, path: Path | None = None) -> bool:
    """Remove a metric by name. Returns True if found and deleted."""
    raw = _load_raw(path)
    new = [m for m in raw if m.get("name") != name]
    if len(new) == len(raw):
        return False
    _save_raw(new, path)
    return True


# ── Schema injection ──────────────────────────────────────────────────────────

def build_metrics_block(path: Path | None = None) -> str:
    """
    Return a METRICS CATALOG block to append to the schema context string.
    Returns "" if no metrics are defined.
    """
    metrics = list_metrics(path)
    if not metrics:
        return ""

    lines = [
        "METRICS CATALOG (use these exact SQL expressions — do not re-derive):",
    ]
    for m in metrics:
        parts = [f"  {m.name.upper()} ({m.label}): {m.sql}"]
        if m.unit:
            parts[0] += f"  [{m.unit}]"
        if m.tables:
            lines.append(parts[0])
            lines.append(f"    Tables: {', '.join(m.tables)}")
        else:
            lines.append(parts[0])
        if m.dimensions:
            lines.append(f"    Slice by: {', '.join(m.dimensions)}")
        if m.filters:
            lines.append(f"    Always filter: {'; '.join(m.filters)}")
        if m.caveats:
            lines.append(f"    ⚠ {m.caveats}")
    return "\n".join(lines)
