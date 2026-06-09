"""Primary-timestamp selection — guards against date-NAMED integer columns being
vouched as timestamps (ClickBench EventDate::USMALLINT → "USMALLINT vs DATE").
See aughor/tools/profiler.py:_select_timestamp_cols."""
from aughor.tools.profiler import _select_timestamp_cols, _NUMERIC_TYPES


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
