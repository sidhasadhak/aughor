"""Regression tests for the post-assessment quality fixes (2026-06-08):
A) headline grounding, B) missing-column repair diagnosis, C) unsafe-metric guard.
Each locks a concrete bug found by reading real outputs."""
from aughor.routers.investigations import _ground_headline
from aughor.agent.investigate import (
    _missing_column_hint, _unsafe_metric_sql, _safe_metric_fallback,
    _build_grounded_schema, _filter_schema,
)

_SCHEMA = """TABLE: analytics.invoices  (1000 rows)
  invoice_id  BIGINT
  order_id  BIGINT
  revenue_net  DOUBLE

TABLE: analytics.orders  (1000 rows)
  order_id  BIGINT
  order_ts  TIMESTAMP
  customer_id  BIGINT

TABLE: analytics.unrelated  (10 rows)
  foo  BIGINT
  bar  VARCHAR"""


# ── A. Headline grounding ─────────────────────────────────────────────────────
def test_headline_grounds_wrong_leader_and_number():
    rows = [["EUROPE", 45793265459.71], ["ASIA", 45613415042.56],
            ["AMERICA", 45306943255.21], ["MIDDLE EAST", 44885458787.76]]
    out = _ground_headline("Total revenue by region, with AMERICA leading at $1.62B",
                           ["region", "total_revenue"], rows)
    assert out != "Total revenue by region, with AMERICA leading at $1.62B"
    assert "EUROPE" in out and "45" in out and "AMERICA" not in out


def test_headline_grounds_wrong_scalar():
    out = _ground_headline("Average order value for completed orders is $184,112.61",
                           ["average_order_value"], [["150398.22"]])
    assert "150,398" in out and "184,112" not in out


def test_headline_unchanged_when_consistent():
    # correct leader + number present → untouched
    rows = [["PROD-1", 49749.45], ["PROD-2", 47080.06]]
    hl = "PROD-1 leads the top 10 with $49,749.45"
    assert _ground_headline(hl, ["product_id", "revenue"], rows) == hl


def test_headline_accepts_legitimate_total():
    # a headline citing the column SUM (≈$226.6B) must NOT be flagged
    rows = [["EUROPE", 45793265459.71], ["ASIA", 45613415042.56],
            ["AMERICA", 45306943255.21], ["AFRICA", 45000000000.0],
            ["MIDDLE EAST", 44885458787.76]]
    hl = "Total revenue across all regions is $226.6B"
    assert _ground_headline(hl, ["region", "total_revenue"], rows) == hl


# ── B. Missing-column repair diagnosis ────────────────────────────────────────
def test_missing_column_hint_extracts_and_instructs_join():
    h = _missing_column_hint('Binder Error: Table "invoices" does not have a column named "order_ts"')
    assert h and "order_ts" in h and "JOIN" in h


def test_missing_column_hint_surfaces_candidate_bindings():
    h = _missing_column_hint('Referenced column "order_ts" not found!\nCandidate bindings: "invoices.order_id"')
    assert h and "invoices.order_id" in h


def test_missing_column_hint_silent_on_unrelated():
    assert _missing_column_hint("syntax error near SELECT") is None
    assert _missing_column_hint('Table with name "x" does not exist!') is None


# ── C. Unsafe-metric guard ────────────────────────────────────────────────────
def test_unsafe_metric_flags_subquery_in_aggregate():
    bad = ("SUM(gross_margin_usd - (SELECT COALESCE(SUM(spend_usd),0) "
           "FROM marketing_ledger) / COUNT(DISTINCT order_id))")
    assert _unsafe_metric_sql(bad)
    assert _safe_metric_fallback(bad) == "SUM(gross_margin_usd)"


def test_unsafe_metric_flags_product_of_aggregates():
    assert _unsafe_metric_sql("SUM(price)*SUM(qty)")


def test_unsafe_metric_silent_on_clean():
    for ok in ("SUM(final_price_usd * quantity)", "SUM(revenue_net)",
               "SUM(margin_usd) - SUM(spend_usd)", "COUNT(DISTINCT order_id)"):
        assert _unsafe_metric_sql(ok) is None


# ── ADA grounding: join-complete schema ───────────────────────────────────────
def test_grounded_schema_includes_date_columns_host_table():
    """The metric is on `invoices`; the timestamp is on `orders`. The old metric-only
    filter dropped `orders` (so the coder hallucinated a date column); the grounded
    schema must include `orders` + a join hint."""
    old = _filter_schema(_SCHEMA, ["analytics.invoices"])
    new = _build_grounded_schema(_SCHEMA, "analytics.invoices", [],
                                 "analytics.orders.order_ts", "Why did revenue change monthly?")
    assert "order_ts" not in old            # the bug
    assert "order_ts" in new                # the fix — orders is now visible
    assert "foo" not in new                 # still focused (unrelated table excluded)
    assert "JOIN PATHS" in new and "order_id" in new   # explicit join keys provided


def test_grounded_schema_expands_fk_neighbour_without_date_table():
    """Even without an explicit date table, an FK neighbour holding needed columns is added."""
    new = _build_grounded_schema(_SCHEMA, "analytics.invoices", [], "", "revenue by customer")
    assert "analytics.orders" in new        # reached via FK on order_id
    assert "foo" not in new


def test_grounded_schema_falls_back_safely_on_garbage():
    # never raises; returns at least the metric table block
    out = _build_grounded_schema(_SCHEMA, "analytics.invoices", None, None, None)
    assert "invoices" in out


# ── ADA grounding: date-column resolution ─────────────────────────────────────
def test_resolve_hallucinated_date_column_to_joinable_table():
    from aughor.agent.investigate import _resolve_date_column
    r, changed = _resolve_date_column(
        "analytics.invoices.invoice_date", "analytics.invoices", _SCHEMA + """
TABLE: analytics.orders2  (1 rows)
  order_id  BIGINT
  order_ts  TIMESTAMP""", [])
    assert changed and r.endswith("order_ts")   # resolved to the real timestamp on a joinable table


def test_resolve_leaves_valid_date_column_untouched():
    from aughor.agent.investigate import _resolve_date_column
    r, changed = _resolve_date_column("analytics.orders.order_ts", "analytics.orders", _SCHEMA, [])
    assert not changed and r == "analytics.orders.order_ts"


# ── ADA grounding: resolver works on the Data Catalog (## markdown) format ─────
_CATALOG = """## analytics.invoices

| Column | Type | Nullable |
|---|---|---|
| order_id | VARCHAR | YES |
| revenue_net | DOUBLE | YES |

Sample (5 rows):
| order_id | revenue_net |
|---|---|
| ORD-1 | 112.2 |

## analytics.orders

| Column | Type | Nullable |
|---|---|---|
| order_id | VARCHAR | YES |
| order_ts | TIMESTAMP | YES |
"""


def test_resolver_handles_data_catalog_markdown_format():
    from aughor.agent.investigate import _typed_columns, _resolve_date_column
    typed = _typed_columns(_CATALOG)
    assert ("order_ts", "TIMESTAMP") in typed.get("analytics.orders", [])
    assert "order_id" not in [c for c, _ in typed.get("analytics.orders", []) if c == "ORD-1"]  # sample rows ignored
    r, changed = _resolve_date_column("analytics.invoices.order_id", "analytics.invoices", _CATALOG, [])
    assert changed and r == "analytics.orders.order_ts"
