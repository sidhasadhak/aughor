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
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

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


def _formula_columns(sql_expr: str) -> set[str]:
    """Bare column names referenced in a metric FORMULA fragment, via sqlglot.
    Best-effort: returns an empty set on any parse trouble so the caller adds NO
    formula-column constraint (over-injection is safer than wrongly dropping a
    valid metric). Function names / literals are not columns, so they're excluded."""
    try:
        import sqlglot
        from sqlglot import exp
        tree = sqlglot.parse_one(f"SELECT {sql_expr}", read="duckdb")
    except Exception:
        return set()
    if tree is None:
        return set()
    return {c.name.lower() for c in tree.find_all(exp.Column) if c.name}


def _metric_matches_schema(metric, tables: set[str], cols: set[str]) -> bool:
    """True if every table, dimension AND formula column the metric declares is
    present in the target connection's schema. Metrics are stored globally, so
    without this a metric authored for one connection (e.g. SALES on
    `final_price_usd`) leaks a wrong, column-mismatched formula into every other
    connection's prompt — a real NL2SQL-corrupting bug surfaced by the golden-SQL
    eval. The formula-column check closes the half the table/dimension checks
    miss: a metric like `revenue = SUM(total_amount)` must NOT inject into a
    connection whose orders has `o_totalprice`/`final_price_usd` and no
    `total_amount` (observed leaking AVG(total_amount) into beautycommerce, which
    has neither). Conservative: only drops when a declared name is genuinely absent."""
    for tbl in (metric.tables or []):
        if tbl.split(".")[-1].lower() not in tables:
            return False
    for dim in (metric.dimensions or []):
        if dim.split(".")[-1].lower() not in cols:
            return False
    for col in _formula_columns(getattr(metric, "sql", "") or ""):
        if col not in cols:
            return False
    return True


def _apply_ontology_overlay(
    metrics: list[MetricDefinition], connection_id: str
) -> list[MetricDefinition]:
    """M24c — unify metrics through the connection's validated ontology.

    The ontology lifts every metrics.json formula into an OntologyMetric, the
    enricher may *correct* the formula, and the validator executes it against the
    live DB. Here we overlay that result onto the global catalog so the generator
    receives the corrected formula — and never receives a formula the validator
    proved wrong on this connection (e.g. the SUM(a)*SUM(b) product-of-sums bug).

    Only applied when the ontology has actually been validated; otherwise the
    global catalog is returned unchanged (conservative — never drop blindly).
    """
    try:
        from aughor.ontology.store import load_latest_ontology
        graph = load_latest_ontology(connection_id)
    except Exception:
        graph = None
    if graph is None or not getattr(graph, "validated", False) or not graph.metrics:
        return metrics

    onto: dict[str, object] = {}
    for om in graph.metrics.values():
        onto[re.sub(r"[^\w]", "_", (om.display_name or om.id).lower())] = om
        onto[om.id] = om

    out: list[MetricDefinition] = []
    for m in metrics:
        om = onto.get(re.sub(r"[^\w]", "_", m.name.lower()))
        if om is None:
            out.append(m)
            continue
        if not getattr(om, "verified", False):
            # An unverified ontology metric means the validator could not confirm THE
            # ONTOLOGY'S formula — which says nothing about the curated catalog formula
            # unless they are the SAME. Drop the catalog metric ONLY when the failed
            # ontology formula matches it (the original SUM(a)*SUM(b) product-of-sums
            # case); otherwise the curated, Finance-approved catalog is highest
            # authority and wins. (Without this, a connection whose ontology carries a
            # wrong templated SUM(total_amount) — e.g. beautycommerce — silently strips
            # the correct catalog revenue/AOV from the LLM prompt.)
            om_sql = (getattr(om, "formula_sql", "") or "").strip()
            if om_sql and om_sql == (m.sql or "").strip():
                continue  # validator tested THIS exact formula and it failed → drop
            out.append(m)
            continue
        new_sql = getattr(om, "formula_sql", "") or ""
        if new_sql.strip() and new_sql.strip() != (m.sql or "").strip():
            m = m.model_copy(update={"sql": new_sql})  # corrected formula
        out.append(m)
    return out


def _dedupe_by_name(metrics: list) -> list:
    """Collapse duplicate metric NAMES to one survivor (the LAST occurrence,
    matching ``save_metric``'s most-recent-wins upsert) and log each conflict.

    A metric name is its identity — ``save_metric`` upserts by name — so two
    entries sharing a name is an invariant violation. It only surfaces once a
    schema keeps both grains of the same KPI (e.g. ``orders`` AND ``order_items``
    both present), and the damage is real: the catalog gets injected into the
    prompt twice with CONFLICTING formulas, enforcement double-counts, and the
    Trust Receipt collides React keys. We restore the invariant at the
    schema-scoped consumer boundary; the raw file is left untouched (so the
    metrics-management UI still shows the conflict for a human to clean)."""
    by_name: dict[str, object] = {}
    first_seen: list[str] = []
    for m in metrics:
        name = getattr(m, "name", None)
        if name is None:
            continue
        if name in by_name:
            logger.warning(
                "metric catalog has a duplicate name %r — keeping the most recent "
                "formula %r, dropping the earlier %r; clean data/metrics.json (a "
                "name must be unique, or scope these per connection)",
                name, getattr(m, "sql", ""), getattr(by_name[name], "sql", ""),
            )
        else:
            first_seen.append(name)
        by_name[name] = m
    return [by_name[n] for n in first_seen]


def filter_metrics_to_schema(metrics: list, schema_text: str) -> list:
    """Drop metrics whose declared tables/columns are absent from ``schema_text``,
    then collapse any duplicate names to a single governed definition.
    Public boundary so other modules (the canonical resolver) reuse the schema
    match without importing this module's internals. Returns ``metrics``
    name-deduped when no schema parses (can't prove absence, but a duplicate
    name is always wrong)."""
    if not schema_text:
        return _dedupe_by_name(metrics)
    tables, cols = _schema_tables_and_columns(schema_text)
    if not tables:
        return _dedupe_by_name(metrics)
    return _dedupe_by_name([m for m in metrics if _metric_matches_schema(m, tables, cols)])


def build_metrics_block(
    path: Path | None = None, schema_text: str = "", connection_id: str = ""
) -> str:
    """
    Return a METRICS CATALOG block to append to the schema context string.
    Returns "" if no metrics are defined.

    M21: now includes governance context — approved-by badge, freshness lag
    warnings, lineage, and NEVER rules from wrong_usage_examples so the LLM
    can't accidentally use a known-bad formula.

    When ``schema_text`` is supplied, metrics whose declared tables/columns are
    absent from that schema are filtered out — metrics are global, so this stops
    one connection's metric from polluting another connection's prompt.

    When ``connection_id`` is supplied, formulas are unified through that
    connection's validated ontology (M24c): corrected formulas are used and
    formulas the validator proved wrong are dropped.
    """
    metrics = list_metrics(path)
    if schema_text:
        _tables, _cols = _schema_tables_and_columns(schema_text)
        if _tables:  # only filter when a schema actually parsed (else keep all)
            metrics = [m for m in metrics if _metric_matches_schema(m, _tables, _cols)]
    if connection_id:
        metrics = _apply_ontology_overlay(metrics, connection_id)
    metrics = _dedupe_by_name(metrics)  # never inject the same KPI twice with conflicting formulas
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
