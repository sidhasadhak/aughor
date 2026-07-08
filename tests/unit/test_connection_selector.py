"""Unit tests for the deterministic cross-source connection selector (Rec 2, answer-path).

No LLM, no DB: the greedy set-cover and tokenizer are pure, and `select_connections` is exercised with a
monkeypatched schema provider.
"""
from __future__ import annotations

import aughor.db.connection as conn_mod
from aughor.agent.connection_selector import _greedy_select, _terms, select_connections


# ── tokenizer ────────────────────────────────────────────────────────────────

def test_terms_keeps_entities_drops_filler_and_singularizes():
    t = _terms("Show me the orders by customer region")
    assert "orders" in t and "order" in t     # singularized so orders↔order match
    assert "customer" in t and "region" in t
    assert "show" not in t and "the" not in t and "me" not in t    # filler dropped


# ── greedy set-cover ───────────────────────────────────────────────────────────

def test_greedy_picks_minimal_covering_set():
    matched = {"A": {"order", "amount"}, "B": {"customer", "region"}, "C": set()}
    assert set(_greedy_select(matched, 3)) == {"A", "B"}          # C grounds nothing → excluded


def test_greedy_returns_single_when_one_connection_covers_everything():
    matched = {"A": {"order", "customer", "region"}, "B": {"customer"}, "C": {"region"}}
    assert _greedy_select(matched, 3) == ["A"]                    # B/C add no new coverage


def test_greedy_respects_max_sources():
    matched = {"A": {"a"}, "B": {"b"}, "C": {"c"}, "D": {"d"}}
    assert len(_greedy_select(matched, 3)) == 3                    # capped, doesn't take all four


def test_greedy_empty_when_nothing_matches():
    assert _greedy_select({}, 3) == []


# ── select_connections (schema-relevance) ────────────────────────────────────

def _patch_schemas(monkeypatch, schemas: dict[str, str]):
    class _C:
        def __init__(self, s):
            self._s = s

        def get_schema(self):
            return self._s
    monkeypatch.setattr(conn_mod, "open_connection_for", lambda cid: _C(schemas[cid]))


def test_select_spanning_subset_ignores_irrelevant_source(monkeypatch):
    _patch_schemas(monkeypatch, {
        "orders_c": "TABLE orders (order_id, cust, amount)",
        "crm_c":    "TABLE customers (cust, region)",
        "prod_c":   "TABLE products (product_id, price, sku)",
    })
    sel = select_connections("orders with each customer's region", ["orders_c", "crm_c", "prod_c"])
    assert set(sel.conn_ids) == {"orders_c", "crm_c"}     # products is not relevant → dropped
    assert sel.multi_source is True


def test_select_single_source_when_question_sits_in_one(monkeypatch):
    _patch_schemas(monkeypatch, {
        "orders_c": "TABLE orders (order_id, cust, amount)",
        "crm_c":    "TABLE customers (cust, region)",
    })
    sel = select_connections("total order amount", ["orders_c", "crm_c"])
    assert sel.conn_ids == ["orders_c"]
    assert sel.multi_source is False
