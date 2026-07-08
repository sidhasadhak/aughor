"""Unit tests for the batched-foreach remote-join primitive (Rec 2, Stage 1).

Two real in-memory DuckDB connections stand in for two heterogeneous sources; a counting wrapper
proves the N+1-avoidance (one right query per key-chunk, distinct keys only).
"""
from __future__ import annotations

from pathlib import Path

import duckdb

from aughor.connectors.remote_join import batched_foreach_join
from aughor.db.connection import DuckDBConnection


def _duck(*stmts: str) -> DuckDBConnection:
    conn = DuckDBConnection.__new__(DuckDBConnection)
    conn._path = Path(":memory:")
    conn._conn = duckdb.connect(":memory:")
    conn._connection_id = "test"
    conn._schema_name = None
    for s in stmts:
        conn._conn.execute(s)
    return conn


class _Counting:
    """Wraps a connection and counts execute() calls — to assert the join is N+1-free."""
    def __init__(self, conn):
        self.conn = conn
        self.calls = 0

    def execute(self, hyp, sql):
        self.calls += 1
        return self.conn.execute(hyp, sql)


def _left(conn: DuckDBConnection, sql: str):
    return conn.execute("__left__", sql)


# ── basic cross-source join ──────────────────────────────────────────────────

def test_inner_join_across_two_connections():
    left_conn = _duck(
        "CREATE TABLE orders (order_id INT, cust VARCHAR)",
        "INSERT INTO orders VALUES (1,'C1'),(2,'C2'),(3,'C1')",
    )
    right_conn = _duck(
        "CREATE TABLE customers (cust VARCHAR, name VARCHAR)",
        "INSERT INTO customers VALUES ('C1','Alice'),('C2','Bob'),('C3','Carol')",
    )
    left = _left(left_conn, "SELECT order_id, cust FROM orders ORDER BY order_id")

    out = batched_foreach_join(left, "cust", right_conn, "cust", right_table="customers",
                               right_cols=["cust", "name"])

    assert out.row_count == 3
    assert "name" in out.columns
    names = [r[out.columns.index("name")] for r in out.rows]
    assert names == ["Alice", "Bob", "Alice"]          # order 3 (C1) rejoined to Alice
    # left 'cust' preserved and right 'cust' disambiguated, not clobbered
    assert out.columns[:2] == ["order_id", "cust"]


def test_join_is_n_plus_one_free_and_dedups_keys():
    left_conn = _duck(
        "CREATE TABLE orders (cust VARCHAR)",
        "INSERT INTO orders VALUES ('C1'),('C2'),('C1'),('C2'),('C1')",  # 5 rows, 2 distinct
    )
    right_conn = _Counting(_duck(
        "CREATE TABLE customers (cust VARCHAR, name VARCHAR)",
        "INSERT INTO customers VALUES ('C1','Alice'),('C2','Bob')",
    ))
    left = _left(left_conn, "SELECT cust FROM orders")

    out = batched_foreach_join(left, "cust", right_conn, "cust", right_table="customers")

    assert right_conn.calls == 1        # ONE right query for all 5 left rows (2 distinct keys)
    assert out.row_count == 5


def test_left_join_keeps_unmatched_rows_inner_drops_them():
    left_conn = _duck(
        "CREATE TABLE orders (order_id INT, cust VARCHAR)",
        "INSERT INTO orders VALUES (1,'C1'),(2,'C9')",   # C9 has no customer
    )
    right_conn = _duck(
        "CREATE TABLE customers (cust VARCHAR, name VARCHAR)",
        "INSERT INTO customers VALUES ('C1','Alice')",
    )
    left = _left(left_conn, "SELECT order_id, cust FROM orders ORDER BY order_id")

    inner = batched_foreach_join(left, "cust", right_conn, "cust", right_table="customers", how="inner")
    assert inner.row_count == 1                          # order 2 dropped

    left2 = _left(left_conn, "SELECT order_id, cust FROM orders ORDER BY order_id")
    outer = batched_foreach_join(left2, "cust", right_conn, "cust", right_table="customers", how="left")
    assert outer.row_count == 2                          # order 2 kept
    name_i = outer.columns.index("name")
    assert outer.rows[1][name_i] is None                 # ... with a null right side


def test_key_chunking_issues_one_query_per_chunk():
    left_conn = _duck(
        "CREATE TABLE orders (cust VARCHAR)",
        "INSERT INTO orders VALUES ('C1'),('C2'),('C3'),('C4'),('C5')",
    )
    right_conn = _Counting(_duck(
        "CREATE TABLE customers (cust VARCHAR)",
        "INSERT INTO customers VALUES ('C1'),('C2'),('C3'),('C4'),('C5')",
    ))
    left = _left(left_conn, "SELECT cust FROM orders")

    batched_foreach_join(left, "cust", right_conn, "cust", right_table="customers", key_chunk=2)

    assert right_conn.calls == 3        # ceil(5 distinct keys / chunk 2)


def test_key_literal_with_quote_is_escaped():
    left_conn = _duck(
        "CREATE TABLE orders (cust VARCHAR)",
        "INSERT INTO orders VALUES ('O''Brien')",       # a key containing a single quote
    )
    right_conn = _duck(
        "CREATE TABLE customers (cust VARCHAR, name VARCHAR)",
        "INSERT INTO customers VALUES ('O''Brien','Bond')",
    )
    left = _left(left_conn, "SELECT cust FROM orders")

    out = batched_foreach_join(left, "cust", right_conn, "cust", right_table="customers")
    assert out.row_count == 1
    assert out.rows[0][out.columns.index("name")] == "Bond"


# ── fail-safe ────────────────────────────────────────────────────────────────

def test_right_query_error_returns_error_result_not_silent_left():
    left_conn = _duck(
        "CREATE TABLE orders (cust VARCHAR)",
        "INSERT INTO orders VALUES ('C1')",
    )
    left = _left(left_conn, "SELECT cust FROM orders")

    class _Boom:
        def execute(self, hyp, sql):
            raise RuntimeError("connection down")

    out = batched_foreach_join(left, "cust", _Boom(), "cust", right_table="customers")
    assert out.error is not None and out.row_count == 0    # honest failure, not left rows posing as success
    assert "join failed" in out.error


def test_numeric_keys_match_across_int_and_double_sources():
    # the SAME entity is INT 101 on one source, DOUBLE 101.0 on the other — must still join
    left_conn = _duck("CREATE TABLE a (cid INTEGER)", "INSERT INTO a VALUES (101),(102)")
    right_conn = _duck(
        "CREATE TABLE b (cid DOUBLE, v VARCHAR)",
        "INSERT INTO b VALUES (101.0,'X'),(102.0,'Y')",
    )
    left = _left(left_conn, "SELECT cid FROM a ORDER BY cid")

    out = batched_foreach_join(left, "cid", right_conn, "cid", right_table="b")

    assert out.row_count == 2
    vs = [r[out.columns.index("v")] for r in out.rows]
    assert vs == ["X", "Y"]


def test_missing_left_key_returns_left_unchanged():
    left_conn = _duck(
        "CREATE TABLE orders (cust VARCHAR)",
        "INSERT INTO orders VALUES ('C1')",
    )
    right_conn = _duck("CREATE TABLE customers (cust VARCHAR)")
    left = _left(left_conn, "SELECT cust FROM orders")

    out = batched_foreach_join(left, "not_a_column", right_conn, "cust", right_table="customers")
    assert out.rows == left.rows


# ── self-healing cross-source key reconciliation (Stage 2b) ───────────────────

def _skew_sources():
    """Same entities, different key FORMAT across the two sources: bid_N (left) vs bref_N (right)."""
    left = _duck(
        "CREATE TABLE orders (order_id INT, book VARCHAR)",
        "INSERT INTO orders VALUES (1,'bid_1'),(2,'bid_2'),(3,'bid_3')",
    )
    right = _duck(
        "CREATE TABLE reviews (book_ref VARCHAR, stars INT)",
        "INSERT INTO reviews VALUES ('bref_1',5),('bref_2',4),('bref_3',3)",
    )
    return left, right


def test_raw_join_misses_format_skewed_keys():
    left_conn, right_conn = _skew_sources()
    left = _left(left_conn, "SELECT order_id, book FROM orders ORDER BY order_id")
    out = batched_foreach_join(left, "book", right_conn, "book_ref", right_table="reviews")   # reconcile off
    assert out.row_count == 0        # no raw overlap between bid_N and bref_N


def test_reconcile_heals_format_skewed_cross_source_keys():
    left_conn, right_conn = _skew_sources()
    left = _left(left_conn, "SELECT order_id, book FROM orders ORDER BY order_id")
    out = batched_foreach_join(left, "book", right_conn, "book_ref", right_table="reviews", reconcile=True)
    assert out.row_count == 3                       # digits/strip-prefix normalization reconciles them
    assert "stars" in out.columns
    assert "reconciled" in out.sql
    stars = [r[out.columns.index("stars")] for r in out.rows]
    assert stars == ["5", "4", "3"]


def test_right_side_can_be_a_grounded_subquery():
    left_conn = _duck("CREATE TABLE orders (cust VARCHAR)", "INSERT INTO orders VALUES ('C1'),('C2')")
    right_conn = _duck(
        "CREATE TABLE customers (cust VARCHAR, region VARCHAR, active BOOLEAN)",
        "INSERT INTO customers VALUES ('C1','EU',true),('C2','US',false),('C3','EU',true)",
    )
    left = _left(left_conn, "SELECT cust FROM orders")

    out = batched_foreach_join(
        left, "cust", right_conn, "cust",
        right_sql="SELECT cust, region FROM customers WHERE active = true",
    )

    assert out.row_count == 1        # only C1 is active among the ordered custs (C2 filtered out)
    assert out.rows[0][out.columns.index("region")] == "EU"


def test_reconcile_absent_for_truly_disjoint_cross_source_keys():
    left_conn = _duck("CREATE TABLE a (k VARCHAR)", "INSERT INTO a VALUES ('C001'),('C002')")
    right_conn = _duck("CREATE TABLE b (k VARCHAR, v INT)", "INSERT INTO b VALUES ('CMP1',1),('CMP2',2)")
    left = _left(left_conn, "SELECT k FROM a")
    out = batched_foreach_join(left, "k", right_conn, "k", right_table="b", reconcile=True, how="left")
    assert out.row_count == 2                        # no transform reconciles → left join, nulls kept
    vi = out.columns.index("v")
    assert all(r[vi] is None for r in out.rows)
