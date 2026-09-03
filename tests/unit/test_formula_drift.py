"""Fix #159 — registry formula-drift coherence layer. The deeper check under the alias↔claim
signal: a finding that ASSERTS a registered metric whose SQL structurally drifts from that
metric's governed formula, caught even with no revealing result alias. High-precision: the
governed signature is matched ALIAS-INSENSITIVELY (a correct `SUM(o.total_amount)` is NOT a
drift — the bug `check_metric_enforcement` has on its own), and a hard reject fires only when
a wrong-usage column the metric warns against is actually present."""
from __future__ import annotations

from types import SimpleNamespace

from aughor.explorer.agent import verify_insight
from aughor.explorer.metric_coherence import (
    drifted_registered_metric, _asserted_registered, _wrong_usage_idents, _alias_stripped_norm,
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
    return drifted_registered_metric(finding, sql)


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


# ── the advisory is split by AUDIENCE (report-quality catalogue ⑥) ─────────────────
#
# A guard's reason becomes a finding's `trust_caveat`, and `_evidence_confidence_ceiling`
# concatenates a trust caveat verbatim into `confidence_justification` — which renders in
# the customer PDF (`export/document.py`) while the web view hides it. So an imperative
# aimed at whoever writes the query ("Recompute with the governed formula…") shipped to
# readers who can do nothing with it. Measured on the live corpus 2026-09-02: three stored
# reports carried that sentence, the most recent from the day before.
#
# These lock the split rather than the wording: a reason may DIAGNOSE, and must not
# INSTRUCT, because only one of those two audiences reads a report.

#: Second-person remedies. Not a general prose linter — the specific shape that leaked.
_REMEDY_VERBS = ("recompute", "re-run", "rerun", "relabel", "fix the", "check the query",
                 "use the governed", "adjust the")


def _drift_reason() -> str:
    reason = drifted_registered_metric(
        "Revenue rose 12% last quarter.",
        "SELECT SUM(order_items.line_total) AS revenue FROM order_items")
    assert reason, "the guard must still FIRE — a vacuous pass would make the rest trivial"
    return reason


def test_the_reader_facing_reason_carries_no_repair_instruction():
    lowered = _drift_reason().lower()
    for verb in _REMEDY_VERBS:
        assert verb not in lowered, (
            f"the trust caveat instructs the reader to {verb!r}; it reaches "
            f"confidence_justification and renders in the customer PDF")


def test_the_reader_facing_reason_does_not_leak_the_governed_SQL():
    """The formula is the fixer's material. In a narrative sentence it reads as leaked
    implementation, and a reader cannot act on it either way."""
    assert "SUM(total_amount)" not in _drift_reason()


def test_it_still_SAYS_the_number_is_not_the_governed_metric():
    """The half a reader genuinely needs: distrust this number. Dropping the remedy must
    not drop the diagnosis — that would trade a useless sentence for a silent one."""
    reason = _drift_reason()
    assert "Revenue" in reason
    assert "different way" in reason or "not Revenue" in reason


def test_the_caveat_still_trips_the_headline_reframe():
    """`_COMPUTATION_ERROR_CAVEAT_RE` matches on the literal words "formula drift" to
    reframe the headline. The phrase is load-bearing text, not a label, so a reword that
    dropped it would silently un-wire the reframe while every other test stayed green."""
    from aughor.agent.investigate import _COMPUTATION_ERROR_CAVEAT_RE
    assert _COMPUTATION_ERROR_CAVEAT_RE.search(_drift_reason())
