"""Arc ED, ED-1 (ROADMAP §3.58) — one row policy at every door.

OC-7 declares on Order that the fulfilment group sees shipped and delivered orders and support sees cancelled and
refunded ones, and that total_amount is finance's alone (`test_ontology_security`). The object doors applied that; a
connection's own door — where a quick answer, a deep analysis and the SQL editor run their statements — did not, so
Ana could count every order in an answer while her object listing showed her own.

The falsifier is ROADMAP's: the same reader gets one count from the object door and another from a statement through
the connection's door → stop. Held here on the seeded samples warehouse through the real DuckDB connection and the
real object compiler. A connection whose released ontology declares nothing reads every statement as it did.
"""
from __future__ import annotations

import pytest

from aughor.ontology import security_sql
from aughor.org.context import reset_actor, set_actor
from aughor.semantic.object_query import ObjectQuery, compile_object_query
from aughor.sql.rls import EntityRule, PolicyRefused, apply_entity_rules
from tests.unit.test_object_actions import CONN, ORDER, _Borrowed, db, graph  # noqa: F401 — fixtures by name
from tests.unit.test_ontology_security import RETURNED, SHIPPED, secured  # noqa: F401 — fixtures by name

COUNT = "SELECT COUNT(*) FROM orders"


@pytest.fixture
def sql_door(secured):  # noqa: F811
    return secured


@pytest.fixture
def as_reader(monkeypatch):
    """Run as a request acting for ``who`` — the context the API's middleware sets on every request."""
    tokens: list = []

    def _as(who: str) -> None:
        monkeypatch.setenv("AUGHOR_LOCAL_USER", who)
        tokens.append(set_actor(who))
    yield _as
    for t in reversed(tokens):
        reset_actor(t)


def _count(db, sql=COUNT):  # noqa: F811
    result = db.execute("q", sql)
    assert not result.error, result.error
    return int(result.rows[0][0]), result


def _object_door_count(graph, db):  # noqa: F811
    compiled = compile_object_query(ObjectQuery(object_type="order", measures=[{"agg": "count"}]), graph)
    with security_sql.object_door():
        return int(db.execute("o", compiled.sql).rows[0][0])


def _every(db, status_in=None):  # noqa: F811
    where = f" WHERE status IN ({', '.join(repr(s) for s in sorted(status_in))})" if status_in else ""
    return int(db.execute("all", COUNT + where).rows[0][0])            # no request acts for anyone: unfiltered


# ── the falsifier ───────────────────────────────────────────────────────────────

def test_a_reader_counts_the_same_orders_through_either_door(sql_door, db, as_reader):  # noqa: F811
    shipped, returned, every = _every(db, SHIPPED), _every(db, RETURNED), _every(db)
    assert 0 < shipped < every and 0 < returned < every
    as_reader("ana")
    n, result = _count(db)
    assert n == _object_door_count(sql_door, db) == shipped
    assert any("only the Order objects user:ana may see are shown — fulfilment: status in delivered, shipped" in c
               for c in result.caveats), result.caveats
    assert "object-policy:Order" in result.doors
    as_reader("ben")
    assert _count(db)[0] == _object_door_count(sql_door, db) == returned


def test_a_reader_in_no_group_counts_none_and_is_told_which_groups_would(sql_door, db, as_reader):  # noqa: F811
    as_reader("carl")
    n, result = _count(db)
    assert n == 0
    assert any("user:carl is in none of its groups (fulfilment, support)" in c for c in result.caveats)


def test_a_join_and_a_subquery_read_only_the_readers_orders(sql_door, db, as_reader):  # noqa: F811
    as_reader("ana")
    n, _ = _count(db, "SELECT COUNT(*) FROM (SELECT o.order_id FROM orders o JOIN customers c "
                      "ON c.customer_id = o.customer_id) AS x")
    assert n == _every(db, SHIPPED)


# ── a masked property ───────────────────────────────────────────────────────────

def test_a_statement_that_reads_a_masked_property_is_refused_with_why(sql_door, db, as_reader):  # noqa: F811
    as_reader("ana")
    for sql in ("SELECT SUM(total_amount) FROM orders", "SELECT * FROM orders",
                "SELECT o.* FROM orders o", "SELECT status FROM orders WHERE total_amount > 100"):
        result = db.execute("q", sql)
        assert result.error and result.error.startswith("[OBJECT POLICY] refused"), (sql, result.error)
        assert "Order.total_amount is confidential — masked for user:ana; finance may read it" in result.error
        assert "blocked:object-policy" in result.doors
    assert _count(db, "SELECT COUNT(status) FROM orders")[0] == _every(db, SHIPPED)
    as_reader("ben")                                                           # finance reads it
    assert not db.execute("q", "SELECT SUM(total_amount) FROM orders").error


# ── what it leaves alone ────────────────────────────────────────────────────────

def test_with_nothing_declared_every_statement_reads_as_it_did(graph, db, as_reader):  # noqa: F811
    as_reader("ana")
    n, result = _count(db)
    assert n == _every(db) and not result.caveats and "object-policy:Order" not in result.doors
    assert not db.execute("q", "SELECT SUM(total_amount) FROM orders").error
    from aughor.db.connection import enforce_row_policy
    assert enforce_row_policy(db, "q", COUNT) == (COUNT, None)


def test_a_schedule_and_the_platforms_own_statements_count_every_order(sql_door, db, as_reader):  # noqa: F811
    every = _every(db)                                                         # no actor: a schedule, an automation run
    as_reader("ana")
    result = db.execute("probe", COUNT, internal=True)
    assert int(result.rows[0][0]) == every


def test_the_object_page_still_reads_its_row_and_masks_the_amount(sql_door, db, as_reader):  # noqa: F811
    from aughor.semantic.object_instances import get_object
    as_reader("ana")
    page = get_object(sql_door, db, "order", ORDER)                           # O000123 is delivered: Ana's
    amount = next(p for p in page.properties if p["name"] == "total_amount")
    assert amount["value"] is None and "masked for user:ana" in amount["withheld"]


def test_two_readers_never_share_a_cached_result(sql_door, as_reader, monkeypatch):
    from aughor.db.connection import result_cache_tenancy
    assert result_cache_tenancy() is None                                     # no request: the key it always was
    as_reader("ana")
    ana = result_cache_tenancy()
    as_reader("ben")
    ben = result_cache_tenancy()
    assert ana and ben and ana != ben


# ── edit history ────────────────────────────────────────────────────────────────

def test_edit_history_is_read_as_the_reader_may(sql_door, db, as_reader, monkeypatch):  # noqa: F811
    monkeypatch.setattr("aughor.db.connection.open_connection_for", lambda conn: _Borrowed(db))
    refunded = str(db.execute("k", "SELECT order_id FROM orders WHERE status = 'refunded' LIMIT 1").rows[0][0])
    rows = [{"object_type": "order", "row_key": ORDER, "column": "total_amount", "body": "5", "previous": "4"},
            {"object_type": "order", "row_key": ORDER, "column": "review_flag", "body": "true", "previous": ""},
            {"object_type": "order", "row_key": refunded, "column": "review_flag", "body": "true", "previous": ""},
            {"object_type": "", "table": "orders", "row_key": "", "column": "status", "body": "a note", "previous": ""}]
    as_reader("ana")
    shown, withheld = security_sql.history_as_read(CONN, rows)
    assert [r["row_key"] for r in shown] == [ORDER, ORDER, ""]
    assert shown[0]["body"] == shown[0]["previous"] == "" and "masked for user:ana" in shown[0]["masked"]
    assert shown[1]["body"] == "true" and "masked" not in shown[1]
    assert withheld == [{"object_type": "Order", "count": 1, "why": withheld[0]["why"]}]
    assert "only the Order objects user:ana may see" in withheld[0]["why"]


def test_edit_history_it_cannot_check_is_withheld_and_said(sql_door, as_reader, monkeypatch):
    def _down(conn):
        raise RuntimeError("warehouse down")
    monkeypatch.setattr("aughor.db.connection.open_connection_for", _down)
    as_reader("ana")
    shown, withheld = security_sql.history_as_read(CONN, [{"object_type": "order", "row_key": ORDER,
                                                           "column": "status", "body": "x", "previous": ""}])
    assert shown == [] and withheld[0]["count"] == 1 and "could not be checked" in withheld[0]["why"]


# ── the rewrite itself ──────────────────────────────────────────────────────────

RULE = EntityRule(table="orders", entity="Order", predicate="(__rp.\"status\" IN ('shipped'))",
                  masked=(("total_amount", "Order.total_amount is confidential"),))


def test_the_rewrite_keeps_aliases_and_reaches_every_reference():
    out, applied = apply_entity_rules("SELECT o.status FROM orders o JOIN orders p ON p.order_id = o.order_id", [RULE])
    assert applied == [RULE, RULE]
    assert out.count("FROM orders AS __rp WHERE (__rp.\"status\" IN ('shipped'))") == 2
    assert ") AS o JOIN" in out and ") AS p ON" in out


def test_another_schemas_table_and_an_untouched_statement_are_left_as_written():
    qualified = EntityRule(table="orders", schema="ecommerce", entity="Order", predicate="TRUE")
    sql = "SELECT  status FROM   stage.orders"
    assert apply_entity_rules(sql, [qualified]) == (sql, [])
    sql = "SELECT 1 FROM customers"
    assert apply_entity_rules(sql, [RULE]) == (sql, [])


def test_the_condition_is_written_in_the_engines_dialect():
    out, _ = apply_entity_rules("SELECT COUNT(*) FROM shop.orders", [RULE], dialect="bigquery")
    assert "__rp.`status` IN ('shipped')" in out


def test_a_cte_that_shadows_a_policied_table_is_refused():
    with pytest.raises(PolicyRefused, match="shadows"):
        apply_entity_rules("WITH orders AS (SELECT 1 AS x) SELECT * FROM orders", [RULE])


def test_another_tables_star_and_column_are_not_the_masked_ones():
    out, _ = apply_entity_rules("SELECT c.*, o.status FROM customers c JOIN orders o ON o.customer_id = c.id", [RULE])
    assert "__rp" in out
    with pytest.raises(PolicyRefused, match="SELECT \\*"):
        apply_entity_rules("SELECT o.* FROM customers c JOIN orders o ON o.customer_id = c.id", [RULE])


def test_a_table_whose_policy_cannot_be_applied_is_refused():
    held = EntityRule(table="order_items", entity="LateOrder", refused="order_items is read by LateOrder's query")
    with pytest.raises(PolicyRefused, match="LateOrder's query"):
        apply_entity_rules("SELECT COUNT(*) FROM order_items", [held])


# ── over HTTP: the request's actor reaches the door, and the object doors stay theirs ──────────────────────────────

def test_the_sql_editor_and_the_object_listing_agree_over_http(sql_door, db, client, monkeypatch):  # noqa: F811
    """The SQL editor's statement is narrowed through the request the middleware frames; the object listing's own
    statements (a `SELECT *` under its row policy) are left to it by its router's dependency, not refused."""
    monkeypatch.setattr("aughor.routers.ontology.served_ontology_graph", lambda conn, schema=None: sql_door)
    monkeypatch.setattr("aughor.db.connection.open_connection_for", lambda conn, *a, **k: _Borrowed(db))
    monkeypatch.setattr("aughor.routers.query._check_conn_org", lambda request, conn: None)
    monkeypatch.setenv("AUGHOR_LOCAL_USER", "ana")
    shipped = _every(db, SHIPPED)
    listed = client.post("/objects/list", params={"connection_id": CONN, "schema_name": "ecommerce"},
                         json={"entity": "Order", "columns": ["status"], "limit": 200})
    assert listed.status_code == 200 and listed.json()["total"] == shipped, listed.text
    ran = client.post("/query/run", json={"conn_id": CONN, "sql": COUNT})
    assert ran.status_code == 200, ran.text
    assert int(ran.json()["rows"][0][0]) == shipped
    assert any("only the Order objects user:ana may see" in c for c in ran.json().get("caveats") or []), ran.json()
    masked = client.post("/query/run", json={"conn_id": CONN, "sql": "SELECT SUM(total_amount) FROM orders"})
    assert "[OBJECT POLICY] refused" in masked.text, masked.text


def test_a_process_that_never_loaded_the_policies_refuses_rather_than_runs_unfiltered(sql_door, db, as_reader):  # noqa: F811
    """The door reads the policies through a registry the agent fills at bootstrap. A host that forgot to fill it must
    not run a request's statement as if nothing were declared."""
    from aughor.agent.bootstrap import _register_object_policies
    from aughor.kernel.registries import object_policies
    as_reader("ana")
    object_policies.clear()
    try:
        result = db.execute("q", COUNT)
        assert result.error and "not loaded in this process" in result.error
    finally:
        _register_object_policies()
    assert _count(db)[0] == _every(db, SHIPPED)
