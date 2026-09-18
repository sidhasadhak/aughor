"""Materialising an industry metric must produce SQL this connection can run.

`materialise` copied the pack's formula verbatim, so a metric that passed the role gate
landed as a `defined` metric whose SQL still read `{{role.order_item.returned_at}}` — a
governed definition nobody can run. The resolver already existed one module away
(`packs.gate4.bind_expression`); it was simply never reached from the door a person uses.

Two traps this file holds, both found live on theLook (2026-09-19):

1. **The role gate is not the attribute gate.** `missing_roles` is computed per ROLE, so a
   formula naming an attribute the connection never bound passes it and then renders a
   raw token into the stored SQL.

2. **The quote character is not portable, and getting it wrong is SILENT.** gate4 wraps
   the bound column in double quotes — right for DuckDB, catastrophic on BigQuery, where
   `"returned_at"` is a STRING LITERAL and never NULL. Measured: the metric read 1.0, a
   100% return rate, where the same formula over the bare column reads 0.0987. SQL that
   fails is a bug report; SQL that runs and lies is a wrong number on a dashboard.
"""
import re

import pytest

from aughor.semantic import metric_catalogue as mc

BINDING = {"bindings": {"order_item": {"table": "order_items",
                                       "columns": {"returned_at": "returned_at",
                                                   "sale_price": "sale price"}}}}


@pytest.fixture()
def bound(monkeypatch):
    from aughor.packs import bindings
    monkeypatch.setattr(bindings, "load_binding", lambda *a, **k: BINDING)
    return BINDING


def test_a_bound_attribute_becomes_its_column(bound):
    sql, unresolved = mc._resolve_roles(
        "SUM(CASE WHEN {{role.order_item.returned_at}} IS NOT NULL THEN 1.0 ELSE 0.0 END)",
        "retail", "conn", "thelook")
    assert unresolved == []
    assert "{{role" not in sql, "a stored formula must carry no placeholders"
    assert "returned_at" in sql


def test_an_ordinary_identifier_is_left_UNQUOTED(bound):
    """The portable choice. A double-quoted identifier is a string on BigQuery and MySQL;
    a backtick is a string elsewhere. An ordinary column needs neither."""
    sql, _ = mc._resolve_roles("{{role.order_item.returned_at}}", "retail", "conn", "s")
    assert sql.strip() == "returned_at"
    assert '"' not in sql and "`" not in sql


def test_the_bigquery_string_literal_trap_cannot_come_back(bound):
    """The exact shape that read 1.0 instead of 0.0987 on theLook."""
    sql, _ = mc._resolve_roles(
        "SUM(CASE WHEN {{role.order_item.returned_at}} IS NOT NULL THEN 1.0 ELSE 0.0 END)",
        "retail", "conn", "s")
    assert '"returned_at"' not in sql, (
        'a double-quoted identifier is a STRING on BigQuery — always non-NULL, so this '
        'CASE matches every row and the metric silently reads 1.0'
    )


def test_an_identifier_that_needs_quoting_gets_the_dialect_s_own(bound, monkeypatch):
    """A column with a space cannot go bare — and must not get the wrong character."""
    from aughor.db import registry, connection as dbconn
    monkeypatch.setattr(registry, "get_dsn", lambda c: ("bigquery", ""))
    monkeypatch.setattr(dbconn, "connection_traits", lambda t: {"dialect": "bigquery"})
    sql, _ = mc._resolve_roles("{{role.order_item.sale_price}}", "retail", "conn", "s")
    assert sql.strip() == "`sale price`", f"bigquery quotes with backticks, got {sql!r}"


def test_an_unbound_ATTRIBUTE_is_reported_even_though_its_role_is_bound(bound):
    """The gap the role-level check cannot see: theLook binds `order_item` and has no
    `cancelled` column at all."""
    sql, unresolved = mc._resolve_roles(
        "{{role.order_item.cancelled}} = 1", "retail", "conn", "s")
    assert unresolved == ["order_item.cancelled"]
    assert "{{role.order_item.cancelled}}" in sql, "unresolved tokens survive for the caller to refuse on"


def test_a_connection_with_no_binding_at_all_reports_every_attribute(monkeypatch):
    from aughor.packs import bindings
    monkeypatch.setattr(bindings, "load_binding", lambda *a, **k: None)
    _, unresolved = mc._resolve_roles(
        "{{role.order_item.returned_at}} / {{role.order_item.sale_price}}",
        "retail", "conn", "s")
    assert sorted(unresolved) == ["order_item.returned_at", "order_item.sale_price"]


def test_the_token_pattern_matches_what_gate3_mandates():
    """gate 3 refuses any formula that is not written in this token, so the resolver must
    read exactly it — spacing included."""
    assert mc._ROLE_TOKEN.search("{{role.order_item.returned_at}}")
    assert mc._ROLE_TOKEN.search("{{ role.order_item.returned_at }}")
    assert not mc._ROLE_TOKEN.search("{{rolex.order_item.returned_at}}")
    assert not re.search(r"\{\{", "returned_at")
