"""Tests for active filter-literal binding (aughor/sql/join_guard.repair_filter_literals /
bind_filter_literals): rewrite a guessed enum literal to its confirmed stored value.

Contract: rewrite ONLY the literal in the comparison on the exact (table, column) named by a
probe-confirmed warning — never other identical strings; fail-open otherwise.
"""
from __future__ import annotations

import sqlite3

from aughor.sql.join_guard import (FilterDomainWarning, repair_filter_literals,
                                   bind_filter_literals)


def _w(table, col, bad, sugg, op="="):
    return FilterDomainWarning(table=table, col=col, bad_value=bad,
                               valid_values=[sugg], suggestion=sugg, op=op)


def test_rewrites_matching_equality_literal():
    sql = "SELECT id FROM orders WHERE status = 'cancelled'"
    out = repair_filter_literals(sql, [_w("orders", "status", "cancelled", "canceled")], dialect="sqlite")
    assert out is not None and "'canceled'" in out and "cancelled" not in out


def test_rewrites_only_the_filtered_column_not_other_identical_strings():
    # 'cancelled' also appears as a SELECT alias literal — it must NOT be touched.
    sql = "SELECT 'cancelled' AS label, id FROM orders WHERE status = 'cancelled'"
    out = repair_filter_literals(sql, [_w("orders", "status", "cancelled", "canceled")], dialect="sqlite")
    assert out is not None
    assert out.count("'cancelled'") == 1 and "'canceled'" in out   # alias kept, filter bound


def test_rewrites_within_in_list_only_the_bad_value():
    sql = "SELECT id FROM orders WHERE status IN ('cancelled', 'shipped')"
    out = repair_filter_literals(sql, [_w("orders", "status", "cancelled", "canceled", op="IN")], dialect="sqlite")
    assert out is not None and "'canceled'" in out and "'shipped'" in out and "cancelled" not in out


def test_no_suggestion_no_change():
    sql = "SELECT id FROM orders WHERE status = 'whoknows'"
    w = FilterDomainWarning(table="orders", col="status", bad_value="whoknows",
                            valid_values=["a", "b"], suggestion=None)
    assert repair_filter_literals(sql, [w], dialect="sqlite") is None


def test_bind_filter_literals_real_sqlite(tmp_path):
    """End-to-end via the product SQLiteConnection: a query filtering a non-existent spelling is
    detected against the live domain and bound to the stored value, then returns rows."""
    from aughor.connectors.file.sqlite import SQLiteConnection

    db_file = tmp_path / "orders.sqlite"
    seed = sqlite3.connect(str(db_file))
    seed.executescript("""
        CREATE TABLE orders (id INTEGER, status TEXT);
        INSERT INTO orders VALUES (1,'canceled'),(2,'shipped'),(3,'canceled'),(4,'delivered');
    """)
    seed.commit(); seed.close()

    conn = SQLiteConnection(dsn=str(db_file), connection_id="filter_test")
    bad_sql = "SELECT COUNT(*) AS n FROM orders WHERE status = 'cancelled'"   # wrong spelling → 0 rows
    assert conn.execute("probe", bad_sql).rows[0][0] in ("0", 0)             # really returns 0

    bound, applied = bind_filter_literals(conn, bad_sql, dialect="sqlite")
    assert applied and "'canceled'" in bound
    # the bound query now finds the 2 'canceled' rows
    assert int(conn.execute("probe2", bound).rows[0][0]) == 2
    conn.close()


def test_bind_filter_literals_corrects_wrong_case(tmp_path):
    """The Scout 'Womenswear' bug: a wrong-CASE enum value passes dry_run as valid but returns
    zero rows; binding corrects it to the stored casing against the live domain."""
    from aughor.connectors.file.sqlite import SQLiteConnection

    db_file = tmp_path / "products.sqlite"
    seed = sqlite3.connect(str(db_file))
    seed.executescript("""
        CREATE TABLE products (id INTEGER, category TEXT);
        INSERT INTO products VALUES (1,'womenswear'),(2,'menswear'),(3,'womenswear');
    """)
    seed.commit(); seed.close()

    conn = SQLiteConnection(dsn=str(db_file), connection_id="case_test")
    bad_sql = "SELECT COUNT(*) AS n FROM products WHERE category = 'Womenswear'"  # wrong case → 0 rows
    assert int(conn.execute("probe", bad_sql).rows[0][0]) == 0

    bound, applied = bind_filter_literals(conn, bad_sql, dialect="sqlite")
    assert applied and "'womenswear'" in bound and "Womenswear" not in bound
    assert int(conn.execute("probe2", bound).rows[0][0]) == 2                   # now finds both rows
    conn.close()
