"""PENDING item 18 — the SQL checks see the tables they check.

Reproduced 2026-09-24: the quick and deep paths REPLACE the schema text with the Data Catalog
(`investigations.py`, "schema = data_catalog"), and the parser every check shares read the
catalog's markdown as no tables at all — `parse_schema_tables(catalog) == {}`. So on every
default answer identifier-case repair returned at its first line, the SQL fixer diagnosed with
no column lists and the verifier's chasm battery scanned against an empty map.

Also here: a repair the quick path asked for because a check fired was adopted as soon as it
RAN, without asking the check again; and the conversation's `describe_table` promised types and
sample values and returned names.
"""
from __future__ import annotations

import inspect

import duckdb
import pytest

from aughor.db.schema_render import parse_schema_tables, schema_block


@pytest.fixture()
def shop(tmp_path):
    path = tmp_path / "shop.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE orders (Order_ID INTEGER, customerID VARCHAR, Amount DOUBLE)")
    con.execute("CREATE TABLE customers (customerID VARCHAR, Region VARCHAR)")
    con.execute("INSERT INTO orders VALUES (1, 'c1', 10.5), (2, 'c2', 20.0), (3, 'c1', 5.0)")
    con.execute("INSERT INTO customers VALUES ('c1', 'EU'), ('c2', 'US')")
    con.close()
    from aughor.db.connection import DuckDBConnection
    db = DuckDBConnection(str(path), connection_id="checks-see-tables")
    yield db
    db.close()


def _catalog(db) -> str:
    from aughor.tools.data_catalog import build_data_catalog
    return build_data_catalog(db, ["orders", "customers"])


def test_the_catalog_parses_to_its_tables_and_columns(shop):
    catalog = _catalog(shop)
    assert catalog.startswith("## orders")                       # the real catalog, not a copy
    assert parse_schema_tables(catalog) == {
        "orders": ["Order_ID", "customerID", "Amount"],
        "customers": ["customerID", "Region"],
    }                                                            # sample rows are not columns


def test_a_markdown_heading_that_is_not_a_table_stays_out():
    text = "## Notes\n\nRevenue is recognised at shipment.\n\n## orders\n\n| Column | Type | Nullable |\n" \
           "|---|---|---|\n| id | INTEGER | NO |\n"
    assert parse_schema_tables(text) == {"orders": ["id"]}


def test_the_house_and_inline_forms_parse_exactly_as_before():
    house = "TABLE: main.orders (3 rows)\n  id           INTEGER\n  amount       DOUBLE\n\nJOIN HINTS:\n  x"
    inline = "TABLE: orders (3 rows) [id INTEGER, amount DOUBLE]"
    assert parse_schema_tables(house) == {"main.orders": ["id", "amount"]}
    assert parse_schema_tables(inline) == {"orders": ["id", "amount"]}


def test_identifier_repair_runs_on_the_catalog(shop):
    """The repair the default path skipped: `customerid` → `customerID`, `amount` → `Amount`."""
    from aughor.sql.safety import preflight_repair
    sql = "SELECT customerid, SUM(amount) AS total FROM orders GROUP BY customerid"

    repaired, receipt = preflight_repair(shop, sql, schema=_catalog(shop))

    assert receipt.get("identifiers_repaired") is True
    assert '"customerID"' in repaired or "customerID" in repaired
    assert "Amount" in repaired


def test_a_repair_that_still_trips_its_check_is_not_adopted():
    from aughor.routers.investigations import _checks_still_firing
    cols = {"order_items": ["order_item_id", "unit_price", "order_id"]}
    still_wrong = "SELECT SUM(unit_price * order_item_id) AS revenue FROM order_items"
    fixed = "SELECT SUM(unit_price) AS revenue FROM order_items"

    assert _checks_still_firing(still_wrong, {"idmath"}, question="revenue", dialect="duckdb",
                                full_cols=cols, schema_cols=cols) == ["idmath"]
    assert _checks_still_firing(fixed, {"idmath"}, question="revenue", dialect="duckdb",
                                full_cols=cols, schema_cols=cols) == []
    # a check that did not ask for the repair is not the repair's to clear
    assert _checks_still_firing(still_wrong, {"ratio"}, question="revenue", dialect="duckdb",
                                full_cols=cols, schema_cols=cols) == []


def test_the_quick_path_rechecks_before_it_adopts_a_repair():
    """Wiring guard, the idiom of the frame's: a re-check nothing calls is the gap this closes."""
    from aughor.routers.investigations import _answer_core
    src = inspect.getsource(_answer_core)
    assert "_checks_still_firing(" in src and '"repair_recheck"' in src


def test_describe_table_returns_what_it_promises(monkeypatch):
    from aughor.agent import converse_tools
    schema = ("TABLE: main.orders (3 rows)\n"
              "  id           INTEGER\n"
              "  status       VARCHAR  -- e.g. 'shipped', 'returned'\n"
              "TABLE: main.customers (2 rows)\n"
              "  id           INTEGER\n")
    monkeypatch.setattr(converse_tools, "_connection",
                        lambda cid: type("C", (), {"get_schema": lambda self: schema})())

    out = converse_tools.describe_table("c1", {"table": "orders"})

    assert out["columns"] == ["id", "status"]
    assert "VARCHAR" in out["schema"] and "'shipped'" in out["schema"]
    assert "customers" not in out["schema"]


def test_schema_block_reads_both_forms():
    assert schema_block("TABLE: t (1 rows) [a INT]\nTABLE: u [b INT]", "t") == "TABLE: t (1 rows) [a INT]"
    catalog = "## t\n\n| Column | Type | Nullable |\n|---|---|---|\n| a | INT | NO |\n\n## u\n"
    assert schema_block(catalog, "t").startswith("## t") and "| a | INT" in schema_block(catalog, "t")
    assert schema_block(catalog, "missing") == ""
