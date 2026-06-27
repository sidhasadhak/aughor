"""Dry-run binding verification (P1b live half, 2026-06-27). See aughor/packs/dryrun.py."""
from aughor.packs import dry_run_binding


class FakeConn:
    def __init__(self, bad=None):
        self.bad = bad or set()      # tables/cols that fail
        self.calls = []

    def dry_run(self, sql):
        self.calls.append(sql)
        for b in self.bad:
            if b in sql:
                return (False, f"no such column/table near {b}")
        return (True, "")


def test_all_columns_dry_run_ok():
    binding = {
        "customer": {"table": "customers", "column": "customer_unique_id"},
        "event": {"table": "orders", "column": "order_purchase_ts"},
        "active_definition": {"value": "purchased_in_window"},   # skipped (value role)
    }
    conn = FakeConn()
    ok, errors = dry_run_binding(conn, binding)
    assert ok and errors == []
    assert all("LIMIT 0" in s for s in conn.calls)
    assert len(conn.calls) == 2   # value-role not probed


def test_bad_column_is_reported():
    binding = {"customer": {"table": "customers", "column": "ghost_col"}}
    ok, errors = dry_run_binding(FakeConn(bad={"ghost_col"}), binding)
    assert not ok and any("customer" in e for e in errors)


def test_dry_run_swallows_exceptions():
    class Boom:
        def dry_run(self, sql):
            raise RuntimeError("conn dead")
    ok, errors = dry_run_binding(Boom(), {"c": {"table": "t", "column": "x"}})
    assert not ok and "conn dead" in errors[0]


def test_identifier_sanitised():
    conn = FakeConn()
    dry_run_binding(conn, {"c": {"table": "t; DROP TABLE x", "column": "col"}})
    # semicolons stripped → can't break out into a second statement; the table is mangled
    # into one harmless (invalid) identifier.
    assert ";" not in conn.calls[0]
    assert conn.calls[0].startswith("SELECT col FROM tDROPTABLEx LIMIT 0")
