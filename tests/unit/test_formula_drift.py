"""Fix #159 — registry formula-drift coherence layer. The deeper check under the alias↔claim
signal: a finding that ASSERTS a registered metric whose SQL structurally drifts from that
metric's governed formula, caught even with no revealing result alias. High-precision: the
governed signature is matched ALIAS-INSENSITIVELY (a correct `SUM(o.total_amount)` is NOT a
drift — the bug `check_metric_enforcement` has on its own), and a hard reject fires only when
a wrong-usage column the metric warns against is actually present."""
from __future__ import annotations

from types import SimpleNamespace

from aughor.explorer.agent import (
    _drifted_registered_metric, _asserted_registered, _wrong_usage_idents,
    _alias_stripped_norm, verify_insight,
)
from aughor.semantic.metrics import list_metrics

_REVENUE = SimpleNamespace(
    name="revenue", label="Revenue", sql="SUM(total_amount)",
    wrong_usage_examples=["SUM(order_items.line_total) — line-item grain diverges ~4.3x.",
                          "SUM(total_amount) joined to order_items without de-duplicating fans out."],
)


# ── alias-insensitive normalization (the false-positive fix) ───────────────────────

def test_alias_strip_makes_prefixed_query_match_the_bare_formula():
    bare = _alias_stripped_norm("SELECT SUM(total_amount) FROM orders")
    pref = _alias_stripped_norm("SELECT SUM(o.total_amount) FROM orders o")
    assert "sumtotalamount" in bare and "sumtotalamount" in pref   # both contain the signature


# ── wrong-usage identifier extraction (underscore-only, no SQL keywords) ───────────

def test_wrong_usage_idents_are_snake_case_columns_only():
    idents = _wrong_usage_idents(_REVENUE)
    assert "line_total" in idents and "order_items" in idents
    assert "from" not in idents and "select" not in idents


# ── asserted-with-value targeting ──────────────────────────────────────────────────

def test_asserted_requires_a_value_in_the_clause():
    assert _asserted_registered("Revenue reached 1.2M last quarter.", [_REVENUE])      # has a number
    assert not _asserted_registered("Revenue is worth investigating further.", [_REVENUE])  # no number


# ── the guard: drift caught only with a corroborating wrong column ─────────────────

def _drift_via_stub(finding, sql, monkeypatch):
    # list_metrics is imported inside the function from its source module — patch there.
    monkeypatch.setattr("aughor.semantic.metrics.list_metrics", lambda: [_REVENUE])
    return _drifted_registered_metric(finding, sql)


def test_line_total_grain_drift_is_flagged(monkeypatch):
    why = _drift_via_stub("Revenue was 4.1M last month.", "SELECT SUM(line_total) FROM order_items", monkeypatch)
    # fires on a wrong-usage identifier the metric warns against (the table or the column).
    assert why and "formula drift" in why and ("line_total" in why or "order_items" in why)


def test_correct_governed_formula_passes_even_with_alias_prefix(monkeypatch):
    # the case that made raw check_metric_enforcement emit a false 'drift'.
    assert _drift_via_stub("Revenue was 4.1M.", "SELECT SUM(o.total_amount) FROM orders o", monkeypatch) is None


def test_drift_without_a_wrong_usage_column_is_not_dropped(monkeypatch):
    # governed formula absent but no warned-against column present → conservative, no hard reject.
    assert _drift_via_stub("Revenue was 4.1M.", "SELECT SUM(net_sales) FROM ledger", monkeypatch) is None


def test_unasserted_metric_is_ignored(monkeypatch):
    # 'revenue' not asserted with a value → nothing to check.
    assert _drift_via_stub("Margins look healthy across regions.",
                           "SELECT SUM(line_total) FROM order_items", monkeypatch) is None


# ── wired into the emission gate, against the REAL registry ────────────────────────

def test_gate_rejects_a_line_total_revenue_finding_real_registry():
    if not any(getattr(m, "name", "") == "revenue" and (getattr(m, "sql", "") or "")
               for m in list_metrics()):
        import pytest
        pytest.skip("no governed 'revenue' metric registered in this env")
    rows = [[4_100_000.0]]
    ok, reason = verify_insight(
        rows, finding_text="Total revenue reached $4.1M.",
        sql="SELECT SUM(line_total) AS r FROM order_items", columns=["r"])
    assert ok is False and "formula drift" in reason


def test_gate_accepts_governed_revenue_real_registry():
    rows = [[4_100_000.0]]
    ok, _ = verify_insight(
        rows, finding_text="Total revenue reached $4.1M.",
        sql="SELECT SUM(o.total_amount) AS r FROM orders o", columns=["r"])
    assert ok is True
