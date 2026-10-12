"""A package's roles can be proposed and bound on any engine, and a binding is checked column by column.

2026-10-13, LuxExperience (Postgres): "Bind roles" led nowhere. Proposing read the schema through a DuckDB handle,
raised on Postgres into a bare `except`, and answered "provide table_cols or a reachable connection_id"; and the
dry run probed a role's table but never the columns its attributes were bound to, which are what a recipe reads.
"""
from __future__ import annotations

import types

from aughor.packs.dryrun import dry_run_binding

LUX = ("TABLE: luxexperience.order_items\n  order_item_id  TEXT\n  order_id  TEXT\n  unit_price_eur  NUMERIC\n"
       "  returned  BOOLEAN\n"
       "TABLE: luxexperience.web_sessions\n  session_id  TEXT\n  session_start  TEXT\n  order_id  TEXT\n"
       "  converted  BOOLEAN\n"
       "TABLE: gold_finance.ledger\n  entry_id  TEXT\n")


def test_proposing_reads_a_postgres_connection_through_its_schema_text(client, monkeypatch):
    import aughor.tools.schema as S

    def duckdb_only(*a, **k):
        raise TypeError("not a DuckDB connection")

    monkeypatch.setattr(S, "build_schema_context", duckdb_only)
    monkeypatch.setattr("aughor.routers.connections.open_connection_for", lambda c: types.SimpleNamespace())
    opened: list = []
    fake = types.SimpleNamespace(get_schema=lambda: LUX, close=lambda: None)
    monkeypatch.setattr("aughor.db.connection.open_connection_for_with_schema",
                        lambda c, schema_name=None: opened.append(schema_name) or fake)
    r = client.post("/packs/retail/propose-bindings", json={"connection_id": "dcc63d83", "schema": "luxexperience"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert opened == ["luxexperience"]
    assert body["total"] >= 2 and "order_item" in body["proposals"] and "cart" in body["proposals"]
    tables = {c.get("table") for c in body["proposals"].values() if c.get("table")}
    assert "gold_finance.ledger" not in tables                       # kept to the schema asked about


def test_the_dry_run_probes_every_column_a_recipe_reads():
    ran: list[str] = []
    conn = types.SimpleNamespace(dry_run=lambda sql: (ran.append(sql), (True, ""))[1])
    ok, errors = dry_run_binding(conn, {"order_item": {"table": "luxexperience.order_items",
                                                       "columns": {"returned_at": "returned", "sale_price": "unit_price_eur"}}})
    assert ok and errors == []
    assert ran == ["SELECT returned, unit_price_eur FROM luxexperience.order_items LIMIT 0"]


def test_a_column_that_is_not_there_fails_the_binding_with_the_role_named():
    conn = types.SimpleNamespace(dry_run=lambda sql: (False, "column \"returned_at\" does not exist"))
    ok, errors = dry_run_binding(conn, {"order_item": {"table": "order_items", "columns": {"returned_at": "returned_at"}}})
    assert not ok and errors == ['order_item: column "returned_at" does not exist']
