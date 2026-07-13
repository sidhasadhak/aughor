"""Ground-first answer resolution — the single deterministic verdict computed
before SQL generation. Fully hermetic: schema strings + a fake db, no LLM.
"""
from __future__ import annotations

from aughor.semantic import answer_resolution as R

# luxexperience: Mytheresa IS an annotated `platform` value; net sales are annual.
_LUX = """\
TABLE: luxexperience.financial_summary  (25 rows)
  net_sales_eur_m  DOUBLE
  platform  VARCHAR  -- [NET-A-PORTER, Mytheresa, YOOX, THE OUTNET, MR PORTER]
  fiscal_year  BIGINT
  gmv_eur_m  BIGINT
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

def test_binds_entity_from_annotation():
    r = R.resolve("Show me month wise sales for mytheresa", schema=_LUX)
    assert [b.value for b in r.entity_bindings] == ["Mytheresa"]
    b = r.entity_bindings[0]
    assert (b.table, b.column) == ("luxexperience.financial_summary", "platform")
    assert "financial_summary.platform = 'Mytheresa'" in r.prompt_constraints


# ── time-grain gap (monthly asked, yearly available) ──────────────────────────

def test_grain_gap_when_measure_is_annual_only():
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
