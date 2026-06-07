"""
Metrics Catalog — Phase 1e + M21.

Named business KPI formulas stored in data/metrics.json and injected into
every schema context so the LLM uses the same approved SQL expression for
MRR, CAC, LTV, etc. rather than re-deriving them on every investigation.

M21 elevates metrics from SQL formulas to governed semantic contracts:
each metric can carry an owner, freshness SLA, quality tests, lineage,
and documented anti-patterns that the LLM is instructed to never use.

Relationship to the Business Glossary:
  Glossary  = what data IS  (table/column semantics, grain, caveats)
  Metrics   = what to COMPUTE (approved SQL formulas, dimensions, filters)
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
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
    # Health scorecard fields (M13a)
    target_value: Optional[float] = Field(default=None, description="Target value for health scorecard")
    warning_threshold: Optional[float] = Field(default=None, description="Yellow-zone boundary (absolute value)")
    critical_threshold: Optional[float] = Field(default=None, description="Red-zone boundary (absolute value)")
    target_period: Optional[str] = Field(default=None, description="'monthly', 'quarterly', 'ytd'")
    benchmark_source: Optional[str] = Field(default=None, description="e.g. 'internal: FY2025 plan'")
    # Governance fields (M21)
    owner: Optional[str] = Field(default=None, description="Team or person responsible, e.g. 'Revenue team'")
    freshness_sla: Optional[str] = Field(default=None, description="Human description of SLA, e.g. 'daily by 6am UTC'")
    freshness_check_sql: Optional[str] = Field(default=None, description="SQL returning the latest data timestamp for this metric")
    quality_tests: list[str] = Field(default_factory=list, description="SQL assertions that must be true; failure = metric flagged unreliable")
    lineage: list[str] = Field(default_factory=list, description="Source tables and transformation descriptions")
    wrong_usage_examples: list[str] = Field(default_factory=list, description="Anti-patterns with explanations — injected as NEVER rules")
    approved_by: Optional[str] = Field(default=None, description="Who approved this definition, e.g. 'Finance'")
    approved_at: Optional[str] = Field(default=None, description="ISO date of approval, e.g. '2026-01-15'")


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
    # Metrics feed the schema-linker's table/column hints — refresh that cache.
    try:
        from aughor.tools.schema_linker import invalidate_hints
        invalidate_hints()  # metrics are global → clear all connections
    except Exception:
        pass


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


# ── Quality validation + freshness ────────────────────────────────────────────

class QualityTestResult(BaseModel):
    test_sql: str
    passed: bool
    error: Optional[str] = None


class ValidationResult(BaseModel):
    metric: str
    passed: bool
    results: list[QualityTestResult]
    message: str


class FreshnessResult(BaseModel):
    metric: str
    latest_data_at: Optional[str]
    sla: Optional[str]
    ok: bool
    message: str


def validate_metric(metric: MetricDefinition, conn) -> ValidationResult:
    """Run all quality_tests for a metric against conn. Each test must return a truthy scalar."""
    if not metric.quality_tests:
        return ValidationResult(
            metric=metric.name,
            passed=True,
            results=[],
            message="No quality tests defined.",
        )

    results: list[QualityTestResult] = []
    all_passed = True
    for sql in metric.quality_tests:
        try:
            qr = conn.execute(sql)
            rows = qr.rows if qr else []
            # A test passes when it returns a single truthy value
            if rows:
                first = rows[0]
                val = first[0] if isinstance(first, (list, tuple)) else list(first.values())[0]
                passed = bool(val)
            else:
                passed = False
            results.append(QualityTestResult(test_sql=sql, passed=passed))
            if not passed:
                all_passed = False
        except Exception as exc:
            results.append(QualityTestResult(test_sql=sql, passed=False, error=str(exc)))
            all_passed = False

    failed = sum(1 for r in results if not r.passed)
    message = (
        f"All {len(results)} test(s) passed."
        if all_passed
        else f"{failed} of {len(results)} test(s) failed."
    )
    return ValidationResult(metric=metric.name, passed=all_passed, results=results, message=message)


def check_freshness(metric: MetricDefinition, conn) -> FreshnessResult:
    """Run freshness_check_sql and return the latest data timestamp."""
    if not metric.freshness_check_sql:
        return FreshnessResult(
            metric=metric.name,
            latest_data_at=None,
            sla=metric.freshness_sla,
            ok=True,
            message="No freshness check SQL defined.",
        )

    try:
        qr = conn.execute(metric.freshness_check_sql)
        rows = qr.rows if qr else []
        latest = None
        if rows:
            first = rows[0]
            raw = first[0] if isinstance(first, (list, tuple)) else list(first.values())[0]
            if raw is not None:
                latest = str(raw)
        return FreshnessResult(
            metric=metric.name,
            latest_data_at=latest,
            sla=metric.freshness_sla,
            ok=latest is not None,
            message=f"Latest data at: {latest}" if latest else "Could not determine latest data timestamp.",
        )
    except Exception as exc:
        return FreshnessResult(
            metric=metric.name,
            latest_data_at=None,
            sla=metric.freshness_sla,
            ok=False,
            message=f"Freshness check failed: {exc}",
        )


# ── Schema injection ──────────────────────────────────────────────────────────

def _schema_tables_and_columns(schema_text: str) -> tuple[set[str], set[str]]:
    """Parse a schema string into its real (table-name, column-name) sets.
    Uses the schema parser so we match against ACTUAL columns, not arbitrary
    text — a metric/description that merely mentions a column name in prose must
    not count as that column being present."""
    try:
        from aughor.tools.schema import _parse_schema_tables
        parsed = _parse_schema_tables(schema_text)
        tables = {t.split(".")[-1].lower() for t in parsed}
        cols = {c.lower() for cols in parsed.values() for c in cols}
        return tables, cols
    except Exception:
        return set(), set()


def _metric_matches_schema(metric, tables: set[str], cols: set[str]) -> bool:
    """True if every table and dimension the metric declares is present in the
    target connection's schema. Metrics are stored globally, so without this a
    metric authored for one connection (e.g. SALES on `final_price_usd`) leaks a
    wrong, column-mismatched formula into every other connection's prompt — a
    real NL2SQL-corrupting bug surfaced by the golden-SQL eval. Conservative:
    only drops a metric when a declared table/dimension is genuinely absent."""
    for tbl in (metric.tables or []):
        if tbl.split(".")[-1].lower() not in tables:
            return False
    for dim in (metric.dimensions or []):
        if dim.split(".")[-1].lower() not in cols:
            return False
    return True


def build_metrics_block(path: Path | None = None, schema_text: str = "") -> str:
    """
    Return a METRICS CATALOG block to append to the schema context string.
    Returns "" if no metrics are defined.

    M21: now includes governance context — approved-by badge, freshness lag
    warnings, lineage, and NEVER rules from wrong_usage_examples so the LLM
    can't accidentally use a known-bad formula.

    When ``schema_text`` is supplied, metrics whose declared tables/columns are
    absent from that schema are filtered out — metrics are global, so this stops
    one connection's metric from polluting another connection's prompt.
    """
    metrics = list_metrics(path)
    if schema_text:
        _tables, _cols = _schema_tables_and_columns(schema_text)
        if _tables:  # only filter when a schema actually parsed (else keep all)
            metrics = [m for m in metrics if _metric_matches_schema(m, _tables, _cols)]
    if not metrics:
        return ""

    lines = [
        "METRICS CATALOG (use these exact SQL expressions — do not re-derive):",
    ]
    for m in metrics:
        header = f"  {m.name.upper()} ({m.label}): {m.sql}"
        if m.unit:
            header += f"  [{m.unit}]"
        if m.approved_by:
            header += f"  ✓ {m.approved_by}-approved"
        lines.append(header)
        if m.tables:
            lines.append(f"    Tables: {', '.join(m.tables)}")
        if m.dimensions:
            lines.append(f"    Slice by: {', '.join(m.dimensions)}")
        if m.filters:
            lines.append(f"    Always filter: {'; '.join(m.filters)}")
        if m.caveats:
            lines.append(f"    ⚠ {m.caveats}")
        if m.freshness_sla:
            lines.append(f"    ⏱ Freshness: {m.freshness_sla}")
        if m.lineage:
            lines.append(f"    Lineage: {'; '.join(m.lineage)}")
        for bad in m.wrong_usage_examples:
            lines.append(f"    ✗ NEVER: {bad}")
    return "\n".join(lines)
