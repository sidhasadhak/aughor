"""Arc NV-6 — three more things the trust checks say at the comparison, from the profiler's facts.

The NVIDIA study's §5.3 fix was half built: the profiler reads a text column's date notation and the ENTITY MODEL
prints it, but the checks that run on every statement still caught the comparison as text and said nothing of the
notation. Its §5.4 named two deterministic pre-execution checks worth taking. All three read `col_facts` — the
profiled notation, range and meaning — and say NOTHING without them; the integer-division check also reads the
dialect, because DuckDB divides to a fraction and Postgres does not.
"""
from __future__ import annotations

from aughor.sql.trust_checks import run_trust_checks

FACTS = {
    "superstore.order date": {"format": "MM/DD/YYYY", "format_note": "text dates written MM/DD/YYYY", "value_range": None,
                              "value_interpretation": "", "dtype": "VARCHAR"},
    "order date": {"format": "MM/DD/YYYY", "format_note": "", "value_range": None, "value_interpretation": "", "dtype": "VARCHAR"},
    "bookings.flown_on": {"format": "", "format_note": "ambiguous: every one of 3 distinct values parses as both DD/MM/YYYY and MM/DD/YYYY",
                          "value_range": None, "value_interpretation": "", "dtype": "VARCHAR"},
    "flown_on": {"format": "", "format_note": "ambiguous: both", "value_range": None, "value_interpretation": "", "dtype": "VARCHAR"},
    "payments.fraud_score": {"format": "", "format_note": "", "value_range": (0.0, 0.202),
                             "value_interpretation": "fraction 0–1 (likely percentage)", "dtype": "numeric"},
    "fraud_score": {"format": "", "format_note": "", "value_range": (0.0, 0.202), "value_interpretation": "fraction 0–1", "dtype": "numeric"},
    "orders.gmv_eur": {"format": "", "format_note": "", "value_range": (12.0, 4800.0), "value_interpretation": "currency", "dtype": "numeric"},
    "gmv_eur": {"format": "", "format_note": "", "value_range": (12.0, 4800.0), "value_interpretation": "currency", "dtype": "numeric"},
}
TYPES = {"orders.id": "integer", "id": "integer", "orders.n_items": "bigint", "n_items": "bigint",
         "orders.gmv_eur": "numeric", "gmv_eur": "numeric", "orders.customer_id": "integer", "customer_id": "integer"}


def _hits(sql, **kw):
    return {f.pattern: f.message for f in run_trust_checks(sql, **kw)}


# ── a text date compared as text ──────────────────────────────────────────────────────────

def test_a_text_date_compared_to_a_literal_names_the_notation():
    h = _hits('SELECT COUNT(*) FROM superstore WHERE "Order Date" > \'6/1/2017\'', col_facts=FACTS)
    assert "E1-text-date-compare" in h
    m = h["E1-text-date-compare"]
    assert "written MM/DD/YYYY" in m and "character by character" in m and "'11/8/2016'" in m
    assert "`> '6/1/2017'`" in m and 'STRPTIME("Order Date"' in m      # the operator as written, the name quoted as SQL needs it


def test_between_order_by_and_min_max_on_a_text_date_fire_too():
    for sql in ('SELECT * FROM superstore WHERE "Order Date" BETWEEN \'1/1/2017\' AND \'3/1/2017\'',
                'SELECT * FROM superstore ORDER BY "Order Date"',
                'SELECT MAX("Order Date") FROM superstore'):
        assert "E1-text-date-compare" in _hits(sql, col_facts=FACTS), sql


def test_an_ambiguous_notation_is_said_as_ambiguous_and_no_cast_is_offered():
    m = _hits("SELECT * FROM bookings WHERE flown_on < '05/06/2026'", col_facts=FACTS)["E1-text-date-compare"]
    assert "AMBIGUOUS" in m and "a person declares the notation" in m and "STRPTIME" not in m


def test_no_facts_no_notation_check():
    assert "E1-text-date-compare" not in _hits('SELECT * FROM superstore WHERE "Order Date" > \'6/1/2017\'')
    assert "E1-text-date-compare" not in _hits('SELECT * FROM superstore WHERE "Order Date" > \'6/1/2017\'', col_facts={})


def test_a_typed_date_column_is_not_a_text_date():
    facts = {"orders.order_date": {"format": "", "format_note": "", "value_range": None, "value_interpretation": "", "dtype": "DATE"}}
    assert "E1-text-date-compare" not in _hits("SELECT * FROM orders WHERE order_date > '2026-01-01'", col_facts=facts)


# ── integer division ──────────────────────────────────────────────────────────────────────

def test_a_ratio_of_counts_truncates_on_postgres_and_is_said():
    m = _hits("SELECT COUNT(*) / COUNT(DISTINCT customer_id) FROM orders", dialect="postgres")["E1-integer-division"]
    assert "truncates" in m and "* 1.0 /" in m


def test_two_integer_columns_divided_on_postgres_fire_and_a_numeric_one_does_not():
    assert "E1-integer-division" in _hits("SELECT n_items / id FROM orders", dialect="postgres", col_types=TYPES)
    assert "E1-integer-division" not in _hits("SELECT gmv_eur / n_items FROM orders", dialect="postgres", col_types=TYPES)
    assert "E1-integer-division" not in _hits("SELECT n_items / id FROM orders", dialect="postgres")   # types unknown: no guess


def test_duckdb_and_bigquery_divide_to_a_fraction_so_nothing_is_said():
    for d in ("duckdb", "bigquery", "snowflake", "mysql"):
        assert "E1-integer-division" not in _hits("SELECT COUNT(*) / COUNT(DISTINCT customer_id) FROM orders", dialect=d), d


def test_a_decimal_literal_or_a_cast_is_already_the_fix():
    assert "E1-integer-division" not in _hits("SELECT COUNT(*) * 1.0 / COUNT(DISTINCT customer_id) FROM orders", dialect="postgres")
    assert "E1-integer-division" not in _hits("SELECT CAST(COUNT(*) AS DOUBLE PRECISION) / COUNT(DISTINCT customer_id) FROM orders", dialect="postgres")


# ── scale ─────────────────────────────────────────────────────────────────────────────────

def test_a_percent_compared_to_a_fraction_is_said_with_the_fraction_to_use():
    m = _hits("SELECT * FROM payments WHERE fraud_score > 15", col_facts=FACTS)["E1-scale-mismatch"]
    assert "fraction of 1" in m and "observed 0–0.202" in m and "Compare to 0.15" in m


def test_a_literal_a_hundred_times_the_maximum_is_a_different_scale():
    m = _hits("SELECT * FROM orders WHERE gmv_eur > 480000", col_facts=FACTS)["E1-scale-mismatch"]
    assert "at least 100× its maximum" in m and "keeps no row" in m


def test_a_literal_within_the_observed_range_says_nothing():
    assert "E1-scale-mismatch" not in _hits("SELECT * FROM orders WHERE gmv_eur > 4000", col_facts=FACTS)
    assert "E1-scale-mismatch" not in _hits("SELECT * FROM payments WHERE fraud_score > 0.15", col_facts=FACTS)
    assert "E1-scale-mismatch" not in _hits("SELECT * FROM orders WHERE gmv_eur > 480000")      # no facts: no guess


# ── the facts' source ─────────────────────────────────────────────────────────────────────

def test_the_source_is_registered_by_the_profiler_side_and_the_platform_imports_nothing_of_it():
    """`test_platform_agent_boundary` bit on the first full run: trust_checks imported tools. The dependency is inverted."""
    import ast
    import pathlib
    from aughor.sql import trust_checks as T
    from aughor.tools import profile_cache as PC
    assert T._COLUMN_FACTS_SOURCE is PC.load_column_facts
    src = pathlib.Path(T.__file__).read_text()
    imported = {n.module for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ImportFrom) and n.module}
    assert not any(m.startswith("aughor.tools") for m in imported)


def test_the_facts_are_read_from_the_profile_cache_newest_first_and_cached_per_connection(monkeypatch):
    from aughor.sql import trust_checks as T
    from aughor.tools import profile_cache as PC
    cache = {"c9:fp1": {"columns": {"main.superstore.Order Date": {
        "table": "main.superstore", "column": "Order Date", "dtype": "VARCHAR", "date_format": "MM/DD/YYYY",
        "date_format_note": "text dates written MM/DD/YYYY", "value_range": None, "value_interpretation": None},
        "main.superstore.Sales": {"table": "main.superstore", "column": "Sales", "dtype": "DOUBLE", "value_range": [0.44, 22638.48],
                                  "value_interpretation": "currency"},
        "main.superstore.Row ID": {"table": "main.superstore", "column": "Row ID", "dtype": "INTEGER"}}}}
    monkeypatch.setattr(PC, "_load", lambda: cache)
    T.forget_column_facts()
    facts = PC.load_column_facts("c9")
    assert facts[("main.superstore", "Order Date")]["format"] == "MM/DD/YYYY"
    assert facts[("main.superstore", "Sales")]["value_range"] == (0.44, 22638.48)
    m = T.connection_column_facts("c9")
    assert m["superstore.order date"]["format"] == "MM/DD/YYYY" and m["main.superstore.sales"]["value_range"] == (0.44, 22638.48)
    assert "main.superstore.row id" not in m                     # a column with no fact to say is not carried
    # read through run_trust_checks by connection id alone, the bare table name resolving against the qualified key
    hits = run_trust_checks('SELECT * FROM superstore WHERE "Order Date" > \'6/1/2017\'', connection_id="c9")
    assert any(h.pattern == "E1-text-date-compare" for h in hits)
    monkeypatch.setattr(PC, "_load", lambda: {})
    assert T.connection_column_facts("c9")["superstore.order date"]["format"] == "MM/DD/YYYY"   # cached
    T.forget_column_facts("c9")
    assert T.connection_column_facts("c9") == {}


def test_a_saved_profile_drops_the_cached_facts(monkeypatch):
    from aughor.sql import trust_checks as T
    T._COLFACTS_CACHE["c-saved"] = {"x": {}}
    from aughor.tools import profile_cache as PC
    class Store:
        def put(self, key, value): pass
        def trim_prefix(self, prefix, n): pass
    monkeypatch.setattr(PC, "_store", Store())
    PC.save_profiles("c-saved", "fp", {}, {})
    assert "c-saved" not in T._COLFACTS_CACHE


# ── the frame says a path is followed whole ───────────────────────────────────────────────

def test_a_multi_hop_path_is_followed_whole_and_a_one_hop_path_needs_no_such_line():
    from aughor.ontology.framing import Frame, FrameDriver, FrameMoment, render_frame_block
    # a frame renders only when the question reached something declared: one stage's moment is enough here
    moment = FrameMoment(text="shipped", process="fulfilment", process_label="Fulfilment", stage="shipped", entity="Order", timestamp="shipped_at")
    two = FrameDriver(path="order.customer.country", label="country", entity="Country", object_type="country", property="country")
    one = FrameDriver(path="order.status", label="status", entity="Order", object_type="order", property="status")
    block = render_frame_block(Frame(question="why did returns rise", moments=[moment], drivers=[two, one]))
    assert "Candidate drivers" in block
    assert "Follow a path whole" in block and "Never shorten a path" in block
    block1 = render_frame_block(Frame(question="why did returns rise", moments=[moment], drivers=[one]))
    assert "Candidate drivers" in block1 and "Follow a path whole" not in block1
