"""Regression tests for the post-assessment quality fixes (2026-06-08):
A) headline grounding, B) missing-column repair diagnosis, C) unsafe-metric guard.
Each locks a concrete bug found by reading real outputs."""
from aughor.routers.investigations import (
    _ground_headline, _apply_currency, _is_time_series, _narrator_sample,
)
from aughor.agent.investigate import (
    _missing_column_hint, _unsafe_metric_sql, _safe_metric_fallback,
    _build_grounded_schema, _filter_schema,
)


# ── A3. Currency in chat prose (eval 2026-06-21) ──────────────────────────────
# An EUR org rendered '$' in Insight/Deep ledes; tables/charts already honoured the
# org currency. _apply_currency rewrites '$<number>' → the business symbol in prose.
def test_currency_rewrites_dollar_before_number():
    assert _apply_currency("Revenue is $104.8M across $5.00 orders", "€") == \
        "Revenue is €104.8M across €5.00 orders"


def test_currency_usd_is_a_noop():
    assert _apply_currency("Revenue is $104.8M", "$") == "Revenue is $104.8M"


def test_currency_leaves_bare_dollar_alone():
    # '$' not followed by a number must not be rewritten.
    assert _apply_currency("Costs are in $ terms", "€") == "Costs are in $ terms"


def test_currency_empty_text_safe():
    assert _apply_currency("", "€") == ""


# ── A4. Insight time-series recent-window (eval 2026-06-21, Q15) ───────────────
# Q15 (inventory turnover by month, 2022→2025) narrated "January through August 2022"
# and never reached 2025 — the narrator got rows[:20] (oldest). _narrator_sample now
# recent-weights a long time series so the narrative leads with current state.
_TS_ROWS = [[f"{y}-{m:02d}", round(0.2 + 0.01 * i, 2)]
            for i, (y, m) in enumerate((y, m) for y in (2022, 2023, 2024, 2025) for m in range(1, 13))][:42]


def test_time_series_detected_by_column_name():
    assert _is_time_series(["month", "turnover"], _TS_ROWS) is True
    assert _is_time_series(["customer_country", "rev"], [["DE", 1], ["FR", 2], ["IT", 3]]) is False


def test_time_series_detected_by_value_shape():
    rows = [["2023-Q1", 1], ["2023-Q2", 2], ["2023-Q3", 3]]
    assert _is_time_series(["period", "x"], rows) is True


def test_narrator_sample_recent_weights_long_series():
    sample, is_ts = _narrator_sample(["month", "turnover"], _TS_ROWS, n=20)
    assert is_ts and len(sample) == 20
    assert sample[0] == _TS_ROWS[0]                       # series start kept for net-change framing
    assert any(str(r[0]).startswith("2025") for r in sample)  # most-recent periods present
    assert sample[-1] == _TS_ROWS[-1]


def test_narrator_sample_breakdown_keeps_head():
    rows = [["credit_card", 70.8], ["debit", 70.1], ["voucher", 69.9]]
    sample, is_ts = _narrator_sample(["payment_type", "aov"], rows)
    assert not is_ts and sample == rows


def test_narrator_sample_short_series_unchanged():
    rows = [["2025-01", 1], ["2025-02", 2], ["2025-03", 3]]
    sample, _ = _narrator_sample(["month", "x"], rows, n=20)
    assert sample == rows  # ≤ n rows → all kept

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


# ── A2. Scalar percent/rate grounding (eval 2026-06-21, Q6) ───────────────────
# The repeat-rate result was a single cell 28.62 but the headline asserted 42.3% —
# both < 100, so the old >=100 floor let it through. A single-row result is one
# metric value, so EVERY number in the headline must match it.
def test_headline_grounds_wrong_scalar_percent():
    out = _ground_headline("Overall repeat purchase rate is 42.3%",
                           ["repeat_purchase_rate"], [["28.62"]])
    assert out != "Overall repeat purchase rate is 42.3%"
    assert "28.62%" in out and "42.3" not in out


def test_headline_keeps_correct_scalar_percent():
    hl = "Repeat purchase rate is 28.62%"
    assert _ground_headline(hl, ["repeat_purchase_rate"], [["28.62"]]) == hl


def test_headline_percent_matches_fraction_stored_rate():
    # a rate stored as a fraction (0.2862) still grounds a "28.6%" claim
    hl = "Repeat rate is 28.6%"
    assert _ground_headline(hl, ["repeat_rate"], [["0.2862"]]) == hl


def test_headline_breakdown_small_count_not_flagged():
    # "across 5 payment types" is a row count, not a data value — multi-row keeps the
    # >=100 floor so 5 is never grounded-out; the AOV cells are present and match.
    rows = [["credit_card", "70.82"], ["debit", "70.1"], ["voucher", "69.9"],
            ["paypal", "69.6"], ["boleto", "69.35"]]
    hl = "AOV is roughly flat across 5 payment types (69.35-70.82)"
    assert _ground_headline(hl, ["payment_type", "aov"], rows) == hl


def test_headline_scalar_year_not_flagged():
    hl = "In 2025 revenue was $104.8M"
    assert _ground_headline(hl, ["revenue"], [["104800000"]]) == hl


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


# ── Latency: skip narrator when a phase has no usable data ─────────────────────
def test_has_usable_data():
    from aughor.agent.investigate import _has_usable_data
    class R:
        def __init__(self, err, n): self.error=err; self.row_count=n
    q=object()
    assert _has_usable_data([(q, R(None, 5))]) is True
    assert _has_usable_data([(q, R("boom", 0))]) is False
    assert _has_usable_data([(q, R(None, 0))]) is False
    assert _has_usable_data([(q, R("e", 0)), (q, R(None, 3))]) is True   # one good is enough
    assert _has_usable_data([]) is False
