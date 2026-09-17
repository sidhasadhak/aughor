"""Primary-timestamp selection — guards against date-NAMED integer columns being
vouched as timestamps (ClickBench EventDate::USMALLINT → "USMALLINT vs DATE").
See aughor/tools/profiler.py:_select_timestamp_cols."""
from aughor.tools.profiler import _select_timestamp_cols, _NUMERIC_TYPES, _semantic_type


# ── the USMALLINT regex fix ───────────────────────────────────────────────────

def test_numeric_regex_matches_duckdb_unsigned_ints():
    for t in ("USMALLINT", "UTINYINT", "UINTEGER", "UBIGINT", "UHUGEINT"):
        assert _NUMERIC_TYPES.search(t), f"{t} should be numeric"


def test_numeric_regex_still_matches_signed_and_floats():
    for t in ("INTEGER", "INT", "BIGINT", "SMALLINT", "TINYINT", "HUGEINT",
              "DOUBLE", "DECIMAL(18,2)", "FLOAT", "NUMERIC"):
        assert _NUMERIC_TYPES.search(t), f"{t} should be numeric"


def test_numeric_regex_excludes_temporal_and_text():
    for t in ("DATE", "TIMESTAMP", "TIMESTAMPTZ", "VARCHAR", "BOOLEAN"):
        assert not _NUMERIC_TYPES.search(t), f"{t} should NOT be numeric"


# ── _select_timestamp_cols ────────────────────────────────────────────────────

def test_prefers_real_timestamp_typed_columns():
    cols = [("id", "BIGINT"), ("order_ts", "TIMESTAMP"), ("created_at", "DATE")]
    assert _select_timestamp_cols(cols) == ["order_ts", "created_at"]


def test_clickbench_eventdate_usmallint_is_excluded():
    # the canonical bug: date-NAMED but integer-typed → must NOT be a timestamp
    cols = [("WatchID", "BIGINT"), ("EventDate", "USMALLINT"), ("UserID", "BIGINT")]
    assert _select_timestamp_cols(cols) == []


def test_yyyymmdd_integer_date_excluded():
    cols = [("sales_amount", "DECIMAL"), ("order_date", "INTEGER")]
    assert _select_timestamp_cols(cols) == []


def test_named_string_date_is_allowed_fallback():
    # a VARCHAR date column has no numeric type → date-literal comparison works
    cols = [("amount", "DOUBLE"), ("event_date", "VARCHAR")]
    assert _select_timestamp_cols(cols) == ["event_date"]


def test_typed_column_wins_over_named_integer():
    cols = [("EventDate", "USMALLINT"), ("EventTime", "TIMESTAMP")]
    assert _select_timestamp_cols(cols) == ["EventTime"]


def test_key_like_timestamps_excluded():
    # date_key / time_id are surrogate keys, not filterable timestamps
    cols = [("date_key", "INTEGER"), ("snapshot_at", "TIMESTAMP")]
    assert _select_timestamp_cols(cols) == ["snapshot_at"]


def test_no_timestamp_columns_at_all():
    cols = [("a", "BIGINT"), ("b", "VARCHAR"), ("c", "DOUBLE")]
    assert _select_timestamp_cols(cols) == []


# ── camelCase identifier classification (the franchiseID distribution bug) ────────
# camelCase ids (franchiseID, supplierID, customerID) were lowercased before the
# snake_case _KEY_PATTERN check, so "_id$" never matched → they fell through to the
# numeric branch as "measure" and got numeric percentiles in the Catalog. They must
# classify as "key" so the distribution profiler skips them.

def _st(col, dtype, *, is_fk=False, distinct=5000, rows=5000, null=0.0, vr=(1, 9999)):
    return _semantic_type(col, dtype, is_fk, distinct, rows, null, vr)


def test_camelcase_ids_classified_as_key():
    for col in ("franchiseID", "supplierID", "customerID", "transactionID", "eventGUID", "orderNum"):
        assert _st(col, "BIGINT") == "key", f"{col} should be a key, not a measure"


def test_snake_case_ids_still_keys():
    for col in ("order_id", "customer_id", "supplier_pk", "row_uuid"):
        assert _st(col, "VARCHAR") == "key"


def test_real_measures_unaffected():
    for col in ("lifetime_spend", "revenue", "quantity", "total_amount"):
        assert _st(col, "DECIMAL") == "measure"


def test_plain_words_ending_in_id_are_not_keys():
    # the lookbehind requires an uppercase suffix after a lowercase letter, so these
    # all-lowercase numeric columns must NOT be mistaken for ids
    for col in ("valid", "void", "grid", "solid", "humid", "rapid"):
        assert _st(col, "BIGINT") == "measure", f"{col} should not be classified as a key"


# ── _robust_date_range reads every populated month ────────────────────────────

def _months(n_months: int, sparse_head: int, cls=None):
    """`ev.ts` holds one row a month for the first `sparse_head` months from 1950-01, then ten a month."""
    from pathlib import Path

    import duckdb

    from aughor.db.connection import DuckDBConnection

    cls = cls or DuckDBConnection
    c = cls.__new__(cls)
    c._path = Path(":memory:")
    c._conn = duckdb.connect(":memory:")
    c._connection_id = "test"
    c._schema_name = None
    c._conn.execute(
        "CREATE TABLE ev AS SELECT (DATE '1950-01-01' + to_months(m::INT))::TIMESTAMP AS ts "
        f"FROM (SELECT m, unnest(range(CASE WHEN m < {sparse_head} THEN 1 ELSE 10 END)) "
        f"FROM range({n_months}) r(m))")
    return c


def test_dense_date_range_reads_every_month_past_the_answer_cap():
    """900 populated months, 1950-01 to 2024-12. The month read went through `execute`, which keeps the first 500
    rows of the ascending list, so the dense region ended at 1991-08, 33 years short of the data, and that is the
    range the explorer's windowing prefers over the raw one (measured 2026-09-17)."""
    from aughor.db.connection import MAX_ROWS
    from aughor.tools.profiler import _robust_date_range

    assert MAX_ROWS < 900
    assert _robust_date_range(_months(900, sparse_head=60), '"ev"', '"ts"') == (
        "1955-01-01 00:00:00", "2024-12-01 00:00:00")


def test_dense_date_range_is_unknown_when_the_connection_cuts_the_month_read():
    """Part of the months cannot place the dense region's end, so a cut read answers None and the caller keeps the
    absolute range."""
    from aughor.db.connection import DatabaseConnection, DuckDBConnection
    from aughor.tools.profiler import _robust_date_range

    class _Capped(DuckDBConnection):
        execute_bounded = DatabaseConnection.execute_bounded

    assert _robust_date_range(_months(900, sparse_head=60, cls=_Capped), '"ev"', '"ts"') is None
