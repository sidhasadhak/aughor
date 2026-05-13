"""Schema introspection — builds the context string fed to the LLM."""
from __future__ import annotations

import duckdb


_TABLE_DESCRIPTIONS: dict[str, str] = {
    "customers": "One row per customer. Use for segment/region breakdowns.",
    "daily_revenue": "One row per customer per day. Source of truth for revenue figures.",
    "events": "Business events (outages, promotions, etc.) that may correlate with metric movements.",
    "kpi_daily": "Pre-aggregated daily KPIs by region and segment. Fastest table for trend queries.",
}

_COLUMN_HINTS: dict[str, str] = {
    "daily_revenue.status": "'success' or 'failed' — failed rows indicate payment failures",
    "customers.segment": "'SMB' or 'Enterprise'",
    "customers.region": "'APAC', 'EMEA', or 'NA'",
    "kpi_daily.metric": "e.g. 'revenue', 'churn_count', 'new_customers'",
    "events.event_type": "'outage', 'promotion', 'holiday', 'product_launch'",
}


def build_schema_context(conn: duckdb.DuckDBPyConnection) -> str:
    """Return a rich schema description for the LLM, including row counts and hints."""
    tables = [row[0] for row in conn.execute("SHOW TABLES").fetchall()]
    parts: list[str] = []

    for table in sorted(tables):
        try:
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except Exception:
            count = "?"

        desc = _TABLE_DESCRIPTIONS.get(table, "")
        header = f"TABLE: {table}  ({count:,} rows)"
        if desc:
            header += f"  — {desc}"
        parts.append(header)

        cols = conn.execute(f"DESCRIBE {table}").fetchall()
        for col in cols:
            col_name, col_type = col[0], col[1]
            hint_key = f"{table}.{col_name}"
            hint = _COLUMN_HINTS.get(hint_key, "")
            line = f"  {col_name}  {col_type}"
            if hint:
                line += f"  [{hint}]"
            parts.append(line)

        # Show a sample of distinct values for key categorical columns
        categorical = [c[0] for c in cols if "VARCHAR" in c[1] or "TEXT" in c[1]]
        for col_name in categorical[:3]:
            try:
                vals = conn.execute(
                    f"SELECT DISTINCT {col_name} FROM {table} LIMIT 8"
                ).fetchall()
                sample = ", ".join(str(v[0]) for v in vals if v[0] is not None)
                if sample:
                    parts.append(f"  -- {col_name} sample values: {sample}")
            except Exception:
                pass

        parts.append("")

    # Add date range context
    try:
        date_range = conn.execute(
            "SELECT MIN(date)::VARCHAR, MAX(date)::VARCHAR FROM kpi_daily"
        ).fetchone()
        if date_range:
            parts.append(f"Date range in kpi_daily: {date_range[0]} to {date_range[1]}")
    except Exception:
        pass

    return "\n".join(parts)
