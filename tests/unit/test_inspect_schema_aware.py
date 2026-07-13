"""Semantic inspector is schema-grounded (Grain S2) — it stops inventing columns.

Hermetic: the narrator provider is stubbed to capture the prompt it receives, so we
assert the wiring (schema block present, grain rule toggled) without an LLM.
"""
from __future__ import annotations

import aughor.sql.inspect as I


class _StubProvider:
    def __init__(self):
        self.last_user = ""
        self.last_system = ""

    def complete(self, system, user, response_model=None, **kw):
        self.last_system, self.last_user = system, user
        return I._InspectAnswer(valid=True, issues=[], suggested_fix="")


def _patch(monkeypatch):
    stub = _StubProvider()
    monkeypatch.setattr(I, "get_provider", lambda _name: stub)
    return stub


def test_schema_is_injected_into_the_prompt(monkeypatch):
    stub = _patch(monkeypatch)
    schema = "TABLE: fin  (5 rows)\n  net_sales_eur_m  DOUBLE\n  fiscal_year  BIGINT\n"
    I.inspect("month wise sales", "SELECT fiscal_year, net_sales_eur_m FROM fin",
              ["fiscal_year", "net_sales_eur_m"], [[2021, 1.0]], schema=schema)
    assert "SCHEMA (the only columns that exist)" in stub.last_user
    assert "fiscal_year  BIGINT" in stub.last_user
    assert "never invent a plausible-sounding column" in stub.last_user


def test_no_schema_block_when_schema_absent(monkeypatch):
    stub = _patch(monkeypatch)
    I.inspect("q", "SELECT 1", ["n"], [[1]])
    assert "SCHEMA (the only columns that exist)" not in stub.last_user


def test_skip_grain_adds_the_defer_rule(monkeypatch):
    stub = _patch(monkeypatch)
    I.inspect("monthly sales", "SELECT fiscal_year FROM fin", ["fiscal_year"], [[2021]],
              schema="TABLE: fin\n  fiscal_year  BIGINT\n", skip_grain=True)
    assert "Do NOT flag time-GRAIN mismatches" in stub.last_user


def test_grain_rule_absent_by_default(monkeypatch):
    stub = _patch(monkeypatch)
    I.inspect("q", "SELECT 1", ["n"], [[1]])
    assert "Do NOT flag time-GRAIN mismatches" not in stub.last_user


def test_never_raises_on_provider_error(monkeypatch):
    def _boom(_name):
        raise RuntimeError("no provider")
    monkeypatch.setattr(I, "get_provider", _boom)
    r = I.inspect("q", "SELECT 1", ["n"], [[1]])
    assert r.valid is True   # degrades to valid on any error
