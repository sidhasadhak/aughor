"""Build-time audit of each north-star metric's ``value_sql``.

The BusinessProfile carries an LLM-written ``value_sql`` per metric — a scalar
query the Briefing runs live to show the metric's current value. The LLM gets the
grain right MOST of the time, but the wrong ones are confidently wrong and become
a headline KPI: a ROAS that joins three satellites of one order key (spend
over-counted 2.3M×), or a "Cart-to-Order Conversion" that filters the DENOMINATOR
to already-converted carts (``WHERE abandoned = 0``) so it reads 100% instead of
18%. A grounded-but-wrong KPI is worse than no KPI.

So before the profile is saved we route every ``value_sql`` through the SAME
authorities the explorer uses on its own SQL:
  1. dry-run (must parse + bind against the real schema);
  2. the static grain/fan-out guards (chasm SUM/COUNT/AVG, integer division,
     count-*-as-parent) — the structural over-count bugs;
  3. the join value-domain guard (fabricated joins like touchpoint_type = channel);
  4. a live range/boundary check — a bounded rate (0..1 / 0..100%) that comes out
     ABOVE its bound, or rounds to either boundary (0 or the max) at display
     precision, is a grain artifact, not a real value. (The classic >1 conversion
     bug and the abandoned=0 → 100% bug both land here.)

A metric that fails is BLANKED (``value_sql = ""``); the Briefing's KPI strip
already drops metrics with no value_sql, so the result is "show nothing" rather
than "show a wrong number". The caller may then try a recipe-grounded
regeneration for blanked metrics that have a curated recipe (see infer.py) — the
audit is what tells it which ones need it.

Entirely best-effort and fail-OPEN per metric: any unexpected error leaves that
metric's value_sql untouched (no worse than before the audit existed).
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)


def _range_kind(unit_or_range: str) -> tuple[str, float | None]:
    """Classify the declared unit into a (kind, max_bound) the live check uses.

    kinds: 'ratio01' (bounded 0..1), 'pct100' (bounded 0..100), 'open' (anything
    else — currency/days/unbounded ratio 0..∞, range-checked only for sign)."""
    u = (unit_or_range or "").lower()
    # An explicitly unbounded ratio (0..∞ / 0-inf) is NOT a bounded rate.
    if re.search(r"0\s*[-.]*\s*(?:∞|inf|infinity)", u) or "0-∞" in u:
        return ("open", None)
    if re.search(r"percent|0\s*-\s*100|0\.\.100|%", u):
        return ("pct100", 100.0)
    if re.search(r"ratio|0\s*-\s*1|0\.\.1", u):
        return ("ratio01", 1.0)
    return ("open", None)


def _first_numeric(rows: list[list]) -> float | None:
    """The single scalar a value_sql is supposed to return — first numeric cell of
    the first row. None if absent/NULL/non-numeric (a value_sql that can't produce
    a scalar is itself a failure)."""
    if not rows:
        return None
    for cell in rows[0]:
        if cell is None or cell == "" or cell == "NULL":
            continue
        try:
            return float(cell)
        except (TypeError, ValueError):
            continue
    return None


def audit_value_sql(value_sql: str, table_cols: dict, conn, unit_or_range: str) -> tuple[bool, str]:
    """Return (ok, reason). ok=False means the value_sql is untrustworthy and
    should be dropped. Fail-open: on any internal error returns (True, "") so a
    flaky audit never discards a metric."""
    sql = (value_sql or "").strip()
    if not sql:
        return (False, "empty")
    try:
        dialect = getattr(conn, "dialect", "duckdb")

        # 1. dry-run: must parse + bind against the real schema.
        try:
            ok, why = conn.dry_run(sql)
            if not ok:
                return (False, f"does not bind: {why}")
        except Exception:
            pass  # dry_run unavailable → fall through to execution, which also binds

        # 2. static grain/fan-out guards — the same DROP signals the explorer uses.
        from aughor.sql.fanout import (
            integer_division_risk, count_star_entity_fanout, count_star_chasm_fanout,
            avg_over_chasm_fanout, sum_over_chasm_fanout,
        )
        grain = (integer_division_risk(sql)
                 or count_star_entity_fanout(sql, table_cols)
                 or count_star_chasm_fanout(sql, table_cols, dialect=dialect)
                 or avg_over_chasm_fanout(sql, table_cols, dialect=dialect)
                 or sum_over_chasm_fanout(sql, table_cols, dialect=dialect))
        if grain:
            return (False, f"grain bug: {grain}")

        # 3. join value-domain guard — fabricated joins (vocabularies don't overlap).
        try:
            from aughor.sql.join_guard import check_join_value_domains
            warns = check_join_value_domains(conn, sql)
            if warns:
                return (False, f"fabricated join: {warns[0].to_prompt_text()}")
        except Exception:
            pass

        # 4. live range/boundary check.
        try:
            res = conn.execute("profile-value-sql", sql)
            if getattr(res, "error", None):
                return (False, f"errors: {res.error}")
            val = _first_numeric(getattr(res, "rows", []) or [])
            if val is None:
                return (False, "no scalar (NULL/empty result)")
            kind, mx = _range_kind(unit_or_range)
            if mx is not None:
                # Above the bound → grain over-count (the >1 conversion bug).
                if val > mx * 1.05:
                    return (False, f"out of range: {val:g} > {mx:g} for '{unit_or_range}'")
                # Rounds to a boundary at display precision → degenerate. A real
                # bounded rate is almost never exactly 0% or 100%; both boundaries
                # are the signature of a broken denominator (abandoned=0 → 100%,
                # ROUND(weight) → 0). Mirrors the KPI strip's existing "drop 0".
                disp = (val / mx) if kind == "ratio01" else (val / 100.0)  # → 0..1
                if round(disp, 3) <= 0.0 or round(disp, 3) >= 1.0:
                    return (False, f"degenerate boundary value {val:g} for bounded rate '{unit_or_range}'")
            else:
                # Open-ended (currency/days/ratio 0..∞): only a rounds-to-zero scalar
                # is degenerate (no card should read $0 / 0d / 0.0).
                if round(val, 4) == 0.0:
                    return (False, f"degenerate zero value for '{unit_or_range}'")
        except Exception:
            pass  # execution failed unexpectedly → don't punish the metric

        return (True, "")
    except Exception as exc:
        logger.debug("value_sql audit errored (fail-open): %s", exc)
        return (True, "")


def audit_chart_sql(chart_sql: str, table_cols: dict, conn) -> tuple[bool, str]:
    """Audit a metric's chart_sql — the SERIES that explains the metric (a trend or a
    top-N breakdown) on the Briefing. Same structural authorities as value_sql (dry-run +
    grain/fan-out guards + join value-domain guard), but the result check is shape-based,
    not range-based: a chart needs ≥2 rows and at least one non-degenerate numeric column
    (a single point, or an all-NULL/all-zero measure, is not a chart). Fail-open."""
    sql = (chart_sql or "").strip()
    if not sql:
        return (False, "empty")
    try:
        dialect = getattr(conn, "dialect", "duckdb")
        try:
            ok, why = conn.dry_run(sql)
            if not ok:
                return (False, f"does not bind: {why}")
        except Exception:
            pass

        from aughor.sql.fanout import (
            integer_division_risk, count_star_entity_fanout, count_star_chasm_fanout,
            avg_over_chasm_fanout, sum_over_chasm_fanout,
        )
        grain = (integer_division_risk(sql)
                 or count_star_entity_fanout(sql, table_cols)
                 or count_star_chasm_fanout(sql, table_cols, dialect=dialect)
                 or avg_over_chasm_fanout(sql, table_cols, dialect=dialect)
                 or sum_over_chasm_fanout(sql, table_cols, dialect=dialect))
        if grain:
            return (False, f"grain bug: {grain}")
        try:
            from aughor.sql.join_guard import check_join_value_domains
            warns = check_join_value_domains(conn, sql)
            if warns:
                return (False, f"fabricated join: {warns[0].to_prompt_text()}")
        except Exception:
            pass

        try:
            res = conn.execute("profile-chart-sql", sql)
            if getattr(res, "error", None):
                return (False, f"errors: {res.error}")
            rows = getattr(res, "rows", []) or []
            if len(rows) < 2:
                return (False, "not a series (need ≥2 rows)")
            # At least one numeric column must carry a non-degenerate value across the
            # series — an all-NULL or all-zero measure draws a flat, meaningless chart.
            width = len(rows[0]) if rows else 0
            has_live_measure = False
            for ci in range(width):
                col = [r[ci] for r in rows if ci < len(r)]
                nums = []
                for c in col:
                    if c is None or c == "" or c == "NULL":
                        continue
                    try:
                        nums.append(float(c))
                    except (TypeError, ValueError):
                        nums = None
                        break  # a text column (label) — not the measure
                if nums and any(n != 0.0 for n in nums):
                    has_live_measure = True
                    break
            if not has_live_measure:
                return (False, "degenerate series (no live numeric column)")
        except Exception:
            pass
        return (True, "")
    except Exception as exc:
        logger.debug("chart_sql audit errored (fail-open): %s", exc)
        return (True, "")


def audit_profile(profile, conn, schema: str) -> dict[str, str]:
    """Audit every metric's value_sql AND chart_sql IN PLACE: blank either if it
    fails and return {metric_name: reason} for the value_sql failures (so the caller
    can try a recipe-grounded regeneration). chart_sql failures are blanked silently
    (the Briefing just shows one fewer explainer chart). Never raises."""
    failures: dict[str, str] = {}
    try:
        from aughor.tools.schema import _parse_schema_tables
        table_cols = _parse_schema_tables(schema)
    except Exception:
        table_cols = {}
    for m in getattr(profile, "north_star_metrics", []) or []:
        vs = (getattr(m, "value_sql", "") or "").strip()
        if vs:
            ok, reason = audit_value_sql(vs, table_cols, conn, getattr(m, "unit_or_range", ""))
            if not ok:
                failures[m.name] = reason
                m.value_sql = ""  # drop it — KPI strip shows nothing rather than a wrong number
        cs = (getattr(m, "chart_sql", "") or "").strip()
        if cs:
            ok, reason = audit_chart_sql(cs, table_cols, conn)
            if not ok:
                logger.info("[profile] chart_sql dropped for %r: %s", m.name, reason)
                m.chart_sql = ""  # no explainer chart for this metric rather than a broken one
    return failures
