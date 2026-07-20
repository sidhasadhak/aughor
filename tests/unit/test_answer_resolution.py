"""Ground-first answer resolution — the single deterministic verdict computed
before SQL generation. Fully hermetic: schema strings + a fake db, no LLM.
"""
from __future__ import annotations

from aughor.semantic import answer_resolution as R

# luxexperience: Mytheresa IS an annotated `platform` value; net sales are annual.
# brand_collaborations is a DECOY — it ALSO has platform=Mytheresa and a daily
# launch_date, but no net-sales measure (est_gmv is a different measure). The real
# luxexperience data has exactly this shape and it broke the naive scan: the entity
# bound to brand_collaborations and its launch_date was mistaken for a monthly-sales
# path. Measure-first resolution must bind to financial_summary and read yearly.
_LUX = """\
TABLE: luxexperience.financial_summary  (25 rows)
  net_sales_eur_m  DOUBLE
  platform  VARCHAR  -- [NET-A-PORTER, Mytheresa, YOOX, THE OUTNET, MR PORTER]
  fiscal_year  BIGINT
  gmv_eur_m  BIGINT
TABLE: luxexperience.brand_collaborations  (40 rows)
  platform  VARCHAR  -- [MR PORTER, Mytheresa, NET-A-PORTER]
  launch_date  DATE
  est_gmv_eur  DOUBLE
TABLE: luxexperience.dim_date  (1826 rows)
  month  BIGINT
  date  DATE
  fiscal_year  BIGINT
"""

# franchise: high-card `name`, no value annotation — Mytheresa is simply absent.
_FRANCHISE = """\
TABLE: main.sales_franchises  (48 rows)
  franchiseID  BIGINT
  name  VARCHAR
  city  VARCHAR
TABLE: main.sales_transactions  (3333 rows)
  dateTime  TIMESTAMP
  product  VARCHAR
  totalPrice  BIGINT
"""

_MONTHLY = _LUX + """\
TABLE: luxexperience.monthly_sales  (60 rows)
  order_month  VARCHAR
  platform  VARCHAR  -- [Mytheresa, YOOX]
  net_sales_eur_m  DOUBLE
"""


class _FakeDB:
    """Minimal DatabaseConnection stand-in: .rows(sql,label) returns canned rows."""
    def __init__(self, hits=None):
        self.hits = hits or {}     # substring in sql -> rows
        self.seen = []

    def rows(self, sql, label=None):
        self.seen.append(sql)
        for needle, rows in self.hits.items():
            if needle in sql:
                return rows
        return []


# ── entity binding (found via annotation) ─────────────────────────────────────

def test_binds_entity_to_the_measure_table_not_the_decoy():
    # Both financial_summary and brand_collaborations carry platform=Mytheresa; the
    # answer is about SALES, so it must bind to financial_summary (the sales table).
    r = R.resolve("Show me month wise sales for mytheresa", schema=_LUX)
    assert [b.value for b in r.entity_bindings] == ["Mytheresa"]
    b = r.entity_bindings[0]
    assert (b.table, b.column) == ("luxexperience.financial_summary", "platform")
    assert "financial_summary.platform = 'Mytheresa'" in r.prompt_constraints
    assert "brand_collaborations" not in r.prompt_constraints


# ── time-grain gap (monthly asked, yearly available) ──────────────────────────

def test_grain_gap_when_measure_is_annual_only():
    # The decoy's daily launch_date must NOT be mistaken for a monthly-sales path.
    r = R.resolve("Show me month wise sales for mytheresa", schema=_LUX)
    assert r.requested_grain == "monthly" and r.available_grain == "yearly"
    assert r.grain_feasible_via is None
    assert r.feasibility == "answerable_with_caveat"
    assert "only reported at yearly grain" in r.caveat
    assert "answer at yearly" in r.prompt_constraints


def test_grain_repair_path_when_finer_table_exists():
    r = R.resolve("month wise sales for mytheresa", schema=_MONTHLY)
    assert r.grain_feasible_via == "luxexperience.monthly_sales"
    assert r.feasibility == "answerable"          # a finer path exists → not a caveat
    assert "query `luxexperience.monthly_sales`" in r.prompt_constraints


# ── not-answerable (entity confirmed absent via a bounded db probe) ────────────

def test_not_found_when_db_probe_confirms_absence():
    db = _FakeDB(hits={})          # every existence probe returns no rows
    r = R.resolve("month wise sales for mytheresa", schema=_FRANCHISE, db=db)
    assert r.not_found == ["mytheresa"]
    assert r.feasibility == "not_answerable"
    assert "not present in this data" in r.caveat
    # it actually probed the string dimension columns
    assert any("sales_franchises" in s for s in db.seen)


def test_no_false_abstain_without_db():
    # Same absent entity, but no db to confirm → must NOT abstain (high precision).
    r = R.resolve("month wise sales for mytheresa", schema=_FRANCHISE, db=None)
    assert r.not_found == []
    assert r.feasibility in ("answerable", "answerable_with_caveat")


def test_binds_entity_found_via_db_probe():
    db = _FakeDB(hits={"sales_franchises": [["Mytheresa"]]})
    r = R.resolve("sales for mytheresa", schema=_FRANCHISE, db=db)
    assert r.not_found == []
    assert any(b.value == "Mytheresa" and b.column == "name" for b in r.entity_bindings)


# ── no over-firing ────────────────────────────────────────────────────────────

def test_plain_question_is_answerable_with_no_constraints():
    r = R.resolve("what were total sales", schema=_LUX)
    assert r.feasibility == "answerable"
    assert r.prompt_constraints == ""
    assert r.caveat == ""


def test_no_temporal_ask_has_no_grain_constraint():
    r = R.resolve("sales for mytheresa", schema=_LUX)
    assert r.requested_grain is None
    # entity still binds
    assert any(b.value == "Mytheresa" for b in r.entity_bindings)


def test_never_raises_on_garbage():
    assert R.resolve(None, schema=None).feasibility == "answerable"
    assert R.resolve("monthly sales {{{", schema="not a schema").feasibility in (
        "answerable", "answerable_with_caveat")


# ── finer-grain fallback: the transactional fact path (order_date exists) ──────
# The REAL luxexperience shape: governed net_sales is YEARLY (financial_summary), but
# an `orders` fact carries gmv_eur at order_date (daily) on the same platform dim — so
# "monthly sales" IS answerable from orders. brand_collaborations (est_gmv + launch_date)
# and clienteling_interactions (gmv_influenced + interaction_date) are traps: an estimate
# and an indirect proxy must never win over the orders fact.
_LUX_TXN = """\
TABLE: luxexperience.financial_summary  (25 rows)
  net_sales_eur_m  DOUBLE
  gmv_eur_m  BIGINT
  platform  VARCHAR  -- [NET-A-PORTER, Mytheresa, YOOX]
  fiscal_year  BIGINT
TABLE: luxexperience.brand_collaborations  (40 rows)
  platform  VARCHAR  -- [Mytheresa, NET-A-PORTER]
  launch_date  DATE
  est_gmv_eur  DOUBLE
TABLE: luxexperience.clienteling_interactions  (900 rows)
  platform  VARCHAR  -- [Mytheresa, YOOX]
  interaction_date  DATE
  gmv_influenced_eur  DOUBLE
TABLE: luxexperience.orders  (120000 rows)
  order_id  VARCHAR
  platform  VARCHAR  -- [Mytheresa, YOOX, NET-A-PORTER]
  order_date  DATE
  fiscal_year  BIGINT
  gmv_eur  DOUBLE
"""


def test_monthly_sales_uses_transactional_fact_when_summary_is_annual():
    # net_sales is yearly-only, but orders.order_date exists → monthly IS answerable
    # from the orders fact (NOT a false "monthly unavailable").
    r = R.resolve("Show me month wise sales for mytheresa", schema=_LUX_TXN)
    assert r.feasibility == "answerable"
    assert r.grain_feasible_via == "luxexperience.orders"
    # the entity FILTER is rebound onto the grain table so FILTER + GRAIN name ONE table
    assert r.entity_bindings and r.entity_bindings[0].table == "luxexperience.orders"
    assert "orders.platform = 'Mytheresa'" in r.prompt_constraints
    assert "query `luxexperience.orders`" in r.prompt_constraints
    # honest about the measure swap (gmv, not the governed net_sales)
    assert "gmv_eur" in r.grain_note and "net_sales_eur_m" in r.grain_note
    # the decoy + the indirect proxy are never chosen
    assert "brand_collaborations" not in r.prompt_constraints
    assert "clienteling" not in r.prompt_constraints


def test_gmv_question_ignores_estimate_decoy_and_prefers_the_fact():
    # est_gmv matches the "gmv" synonym literally, but an ESTIMATE must never anchor the
    # entity or serve the grain — orders (actual gmv_eur, a fact table) wins over both
    # the estimate decoy and the indirect clienteling proxy.
    r = R.resolve("weekly gmv for mytheresa", schema=_LUX_TXN)
    assert r.feasibility == "answerable"
    assert r.grain_feasible_via == "luxexperience.orders"
    assert r.entity_bindings[0].table == "luxexperience.orders"
    assert "brand_collaborations" not in r.prompt_constraints
    assert "clienteling" not in r.prompt_constraints


def test_fallback_does_not_invent_a_path_when_none_exists():
    # Regression: with NO fact table (only the annual summary + est decoy), the honest
    # "monthly unavailable" caveat still stands — the fallback must not fabricate a path.
    r = R.resolve("month wise sales for mytheresa", schema=_LUX)
    assert r.grain_feasible_via is None
    assert r.grain_note == ""
    assert r.feasibility == "answerable_with_caveat"
    assert "only reported at yearly grain" in r.caveat


def test_non_revenue_measure_has_no_transactional_substitute():
    # The fallback is scoped to revenue-type asks; a "customers" question does NOT get
    # silently answered from a gmv fact (that would be a wrong-measure answer).
    r = R.resolve("monthly customers for mytheresa", schema=_LUX_TXN)
    assert r.grain_feasible_via is None  # no customers measure at a finer grain here


# ── no false abstain: probe every candidate column, ranked by the question ────────
# The reported regression: "contra-revenue categories … in womenswear" abstained
# ("womenswear is not present in this data") even though womenswear IS a category value —
# because the measure ('revenue') bound to a summary table and the probe stopped after a
# fixed cap, never reaching the category column that holds the value.
_CONTRA = """\
TABLE: lux.financial_summary  (60 rows)
  platform  VARCHAR
  segment  VARCHAR
  owner  VARCHAR
  region  VARCHAR
  country  VARCHAR
  channel  VARCHAR
  brand  VARCHAR
  vendor  VARCHAR
  revenue_eur  DOUBLE
TABLE: lux.order_items  (100000 rows)
  order_id  BIGINT
  category  VARCHAR  -- [womenswear, menswear, shoes, accessories]
  refund_eur  DOUBLE
"""


def test_category_value_resolves_not_falsely_absent():
    # End-to-end: 8 summary dims sort ahead of order_items.category (the 9th), and the measure
    # binds to the summary table — the exact shape that used to false-abstain. The question
    # names "categories", so the category column floats up and womenswear resolves.
    db = _FakeDB(hits={"category": [["womenswear"]]})
    r = R.resolve("What contra-revenue categories are driving losses in womenswear?",
                  schema=_CONTRA, db=db)
    assert r.not_found == []                    # was ['womenswear'] before the fix
    assert any(b.column == "category" and b.value == "womenswear" for b in r.entity_bindings)


def test_sweeps_past_the_old_cap_before_binding():
    # No dimension hint in the question: the value still binds because the probe sweeps EVERY
    # candidate column (order_items.category is the 9th) instead of stopping at the old 8-cap.
    db = _FakeDB(hits={"order_items": [["womenswear"]]})   # value lives only in order_items
    out = R._db_find_value(db, _CONTRA, "womenswear")
    assert out == ("lux.order_items", "category", "womenswear")


def test_genuinely_absent_value_still_abstains():
    # The contract cuts both ways: a value in NO column is still confirmed absent (after the
    # full sweep), so ground-first honesty is preserved.
    db = _FakeDB(hits={})                       # every probe returns no rows
    assert R._db_find_value(db, _CONTRA, "blorpwear") == "absent"


def test_question_named_column_is_probed_first():
    # Ranking optimisation: a column the question names is probed before the summary dims, so
    # the common filter-by-<dimension> case binds in the first probe, not after a full sweep.
    db = _FakeDB(hits={"category": [["womenswear"]]})
    out = R._db_find_value(db, _CONTRA, "womenswear", question="losses by category")
    assert out == ("lux.order_items", "category", "womenswear")
    assert "category" in db.seen[0]             # the named column went first
