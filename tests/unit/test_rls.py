"""Unit tests for the RBAC row-policy injector + resolver (Rec 7)."""
from __future__ import annotations

import sqlglot
import pytest

import aughor.rbac.row_policy as rp
from aughor.rbac.row_policy import resolve_row_filters
from aughor.sql.rls import inject_row_filters


# ── inject_row_filters (AST rewrite) ──────────────────────────────────────────

def test_inject_wraps_base_table():
    out = inject_row_filters("SELECT * FROM orders", {"orders": "org_id = 'o1'"}, "duckdb")
    assert "org_id = 'o1'" in out
    sqlglot.parse_one(out, read="duckdb")            # still valid SQL


def test_inject_preserves_alias_in_join():
    sql = "SELECT o.amount, c.name FROM orders o JOIN customers c ON o.cust = c.id"
    out = inject_row_filters(sql, {"orders": "org_id = 'o1'"}, "duckdb")
    low = out.lower()
    assert out.count("org_id = 'o1'") == 1           # ONLY orders wrapped (filter appears once)
    assert " as o" in low                            # wrapped subquery keeps the alias `o`
    assert "customers" in low                        # customers still referenced (untouched)
    sqlglot.parse_one(out, read="duckdb")            # o.amount still resolves against the aliased subquery


def test_inject_no_policied_table_is_noop():
    sql = "SELECT * FROM products"
    assert inject_row_filters(sql, {"orders": "org_id = 'o1'"}, "duckdb") == sql


def test_inject_empty_filters_is_noop():
    assert inject_row_filters("SELECT * FROM orders", {}, "duckdb") == "SELECT * FROM orders"


def test_inject_cte_collision_fails_closed():
    with pytest.raises(Exception):
        inject_row_filters("WITH orders AS (SELECT 1 AS n) SELECT * FROM orders",
                           {"orders": "org_id = 'o1'"}, "duckdb")


def test_inject_unparseable_raises():
    with pytest.raises(Exception):
        inject_row_filters("SELECT ((( FROM", {"orders": "x = 1"}, "duckdb")


# ── resolve_row_filters (policy resolution) ───────────────────────────────────

def test_resolve_owner_is_unrestricted(monkeypatch):
    monkeypatch.setattr(rp, "ROW_POLICIES", {"viewer": {"orders": "org_id = '{org_id}'"}})
    assert resolve_row_filters(["owner"], "o1", "u1") == {}


def test_resolve_viewer_substitutes_placeholders(monkeypatch):
    monkeypatch.setattr(rp, "ROW_POLICIES", {"viewer": {"orders": "org_id = '{org_id}'"}})
    assert resolve_row_filters(["viewer"], "o1", "u1") == {"orders": "org_id = 'o1'"}


def test_resolve_escapes_single_quote(monkeypatch):
    monkeypatch.setattr(rp, "ROW_POLICIES", {"viewer": {"orders": "org_id = '{org_id}'"}})
    assert resolve_row_filters(["viewer"], "o'; DROP", "u1") == {"orders": "org_id = 'o''; DROP'"}


def test_resolve_most_permissive_role_wins(monkeypatch):
    monkeypatch.setattr(rp, "ROW_POLICIES", {
        "viewer": {"orders": "org_id = '{org_id}' AND private = FALSE"},
        "analyst": {"orders": "org_id = '{org_id}'"}})
    assert resolve_row_filters(["viewer", "analyst"], "o1", "u1") == {"orders": "org_id = 'o1'"}


def test_resolve_no_policy_for_role_is_unrestricted(monkeypatch):
    monkeypatch.setattr(rp, "ROW_POLICIES", {"analyst": {"orders": "x = 1"}})
    assert resolve_row_filters(["viewer"], "o1", "u1") == {}
