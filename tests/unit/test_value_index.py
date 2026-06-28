"""Tests for the trigram-blocked value index (aughor/sql/value_index.py) and the high-cardinality
filter-literal binding it powers (aughor/sql/join_guard._highcard_bind_warnings).

Contract: approximate-match a guessed literal to its nearest real value via shingle blocking +
similarity rerank, and (in the guard) bind ONLY a literal that is execution-confirmed absent from a
high-cardinality column — never second-guess a value that actually exists.
"""
from __future__ import annotations

import sqlite3

from aughor.sql.value_index import ValueIndex


def test_exact_match_scores_one():
    idx = ValueIndex(["San Francisco", "San Diego", "Sacramento"])
    assert idx.best_match("San Francisco") == "San Francisco"


def test_close_typo_binds_above_cutoff():
    idx = ValueIndex(["San Francisco", "Los Angeles", "San Diego"])
    assert idx.best_match("San Franciso", cutoff=0.82) == "San Francisco"   # missing 'c'


def test_unrelated_needle_returns_none():
    idx = ValueIndex(["San Francisco", "Los Angeles"])
    assert idx.best_match("Tokyo", cutoff=0.82) is None


def test_case_insensitive_dedup():
    idx = ValueIndex(["Apple", "apple", "APPLE", "Banana"])
    assert len(idx) == 2   # 'apple' variants collapse


def test_short_values_are_indexable():
    idx = ValueIndex(["NY", "NJ", "CA", "CT"])
    assert idx.best_match("NY") == "NY"


def test_blocking_scales_finds_match_among_many():
    # high-cardinality domain: trigram blocking must still surface the right value
    vals = [f"customer_{i:05d}" for i in range(5000)] + ["Wakefield Industries"]
    idx = ValueIndex(vals)
    assert idx.best_match("Wakfield Industries", cutoff=0.82) == "Wakefield Industries"


def test_highcard_binding_end_to_end_real_sqlite(tmp_path):
    """A filter on a high-cardinality (>50 distinct) name column with a misspelled literal is bound to
    the stored value — the path the ≤50-distinct enumeration deliberately skips."""
    from aughor.connectors.file.sqlite import SQLiteConnection
    from aughor.sql.join_guard import bind_filter_literals

    db_file = tmp_path / "people.sqlite"
    seed = sqlite3.connect(str(db_file))
    seed.execute("CREATE TABLE people (id INTEGER, name TEXT)")
    # 120 distinct names → high-cardinality (well above the 50 enumeration cap)
    rows = [(i, f"Person Number {i:04d}") for i in range(120)]
    rows.append((999, "Wakefield Industries"))
    seed.executemany("INSERT INTO people VALUES (?, ?)", rows)
    seed.commit(); seed.close()

    conn = SQLiteConnection(dsn=str(db_file), connection_id="highcard_test")
    bad = "SELECT id FROM people WHERE name = 'Wakfield Industries'"   # misspelled → 0 rows
    assert conn.execute("p", bad).rows == []

    bound, applied = bind_filter_literals(conn, bad, dialect="sqlite")
    assert applied and "Wakefield Industries" in bound
    assert conn.execute("p2", bound).rows[0][0] in (999, "999")
    conn.close()


def test_highcard_does_not_touch_a_real_value(tmp_path):
    """If the literal actually exists in the high-cardinality column, leave it alone (no spurious bind)."""
    from aughor.connectors.file.sqlite import SQLiteConnection
    from aughor.sql.join_guard import bind_filter_literals

    db_file = tmp_path / "people2.sqlite"
    seed = sqlite3.connect(str(db_file))
    seed.execute("CREATE TABLE people (id INTEGER, name TEXT)")
    rows = [(i, f"Person Number {i:04d}") for i in range(120)]
    seed.executemany("INSERT INTO people VALUES (?, ?)", rows)
    seed.commit(); seed.close()

    conn = SQLiteConnection(dsn=str(db_file), connection_id="highcard_test2")
    ok_sql = "SELECT id FROM people WHERE name = 'Person Number 0042'"   # a real value
    bound, applied = bind_filter_literals(conn, ok_sql, dialect="sqlite")
    assert not applied and bound.strip() == ok_sql.strip()
    conn.close()
