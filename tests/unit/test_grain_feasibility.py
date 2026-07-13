"""Grain-feasibility gate — the deterministic time-grain twin of metric_feasibility.

Locks the "massive disconnect" scenario: a monthly question answered with yearly
data must yield ONE grounded verdict (abstain when no finer path, repair when one
exists), not five contradictory subsystem opinions.
"""
from __future__ import annotations

from aughor.semantic.grain_feasibility import (
    columns_grain, grain_gap, measure_terms, requested_time_grain,
)

# Real receipt schema format: "  name  TYPE" (two spaces, name, two+ spaces, type).
_FIN_ONLY = """\
TABLE: luxexperience.financial_summary  (25 rows)
  net_sales_eur_m  DOUBLE
  platform  VARCHAR
  fiscal_year  BIGINT
  gmv_eur_m  BIGINT
TABLE: luxexperience.dim_date  (1826 rows)
  month  BIGINT
  date  DATE
  fiscal_year  BIGINT
"""

_WITH_MONTHLY = _FIN_ONLY + """\
TABLE: luxexperience.monthly_sales  (60 rows)
  order_month  VARCHAR
  platform  VARCHAR
  net_sales_eur_m  DOUBLE
"""

_RESULT_COLS = ["fiscal_year", "net_sales_eur_m", "gmv_eur_m"]


# ── requested grain detection ─────────────────────────────────────────────────

def test_requested_time_grain():
    assert requested_time_grain("Show me month wise sales for mytheresa") == "monthly"
    assert requested_time_grain("monthly revenue") == "monthly"
    assert requested_time_grain("daily active users") == "daily"
    assert requested_time_grain("week by week churn") == "weekly"
    assert requested_time_grain("quarterly GMV") == "quarterly"
    assert requested_time_grain("year over year growth") == "yearly"
    assert requested_time_grain("total sales for mytheresa") is None
    # finest wins when several appear
    assert requested_time_grain("monthly trend across the year") == "monthly"


# ── column → grain ────────────────────────────────────────────────────────────

def test_columns_grain():
    assert columns_grain(["fiscal_year"]) == "yearly"
    assert columns_grain(["order_month", "net_sales"]) == "monthly"
    assert columns_grain(["date", "amount"]) == "daily"
    assert columns_grain(["fiscal_quarter"]) == "quarterly"
    assert columns_grain(["net_sales", "platform"]) is None       # no time column
    assert columns_grain(["date", "fiscal_year"]) == "daily"      # finest wins


def test_measure_terms_strips_units():
    assert set(measure_terms(_RESULT_COLS)) == {"net_sales", "gmv"}
    assert measure_terms(["fiscal_year"]) == []                   # time col dropped


# ── the verdict: abstain vs repair ────────────────────────────────────────────

def test_abstain_when_no_finer_path():
    # The Mytheresa case: monthly asked, yearly delivered, and dim_date has month
    # but NO sales measure — so there is no finer path to net sales → abstain.
    g = grain_gap("Show me month wise sales for mytheresa", _RESULT_COLS, _FIN_ONLY)
    assert g is not None
    assert (g.requested, g.delivered) == ("monthly", "yearly")
    assert g.feasible_via is None and g.feasible is False
    assert "only reported at yearly grain" in g.caveat("net sales")


def test_repair_when_finer_path_exists():
    g = grain_gap("month wise sales", _RESULT_COLS, _WITH_MONTHLY)
    assert g is not None and g.feasible is True
    assert g.feasible_via == "luxexperience.monthly_sales"
    assert "monthly_sales" in g.caveat()


def test_no_gap_when_already_at_requested_grain():
    assert grain_gap("month wise sales", ["order_month", "net_sales_eur_m"], _FIN_ONLY) is None


def test_no_gap_when_no_temporal_ask():
    assert grain_gap("total sales for mytheresa", _RESULT_COLS, _FIN_ONLY) is None


def test_dim_date_alone_is_not_a_finer_path_for_sales():
    # dim_date has month/date but no measure — must NOT be offered as a repair target.
    g = grain_gap("monthly net sales", _RESULT_COLS, _FIN_ONLY)
    assert g is not None and g.feasible_via is None


def test_never_raises_on_garbage():
    assert grain_gap(None, None, None) is None
    assert grain_gap("monthly", ["net_sales_eur_m"], "not a schema {{{") is not None  # gap, no path


def test_no_gap_when_delivered_finer_than_requested():
    # Asked yearly, delivered monthly → over-delivered, not a gap.
    assert grain_gap("yearly sales", ["order_month", "net_sales_eur_m"], _FIN_ONLY) is None
