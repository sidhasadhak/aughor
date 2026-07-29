"""Wave G3 — usage attribution: report the axes that carry information, count the rest.

Hermetic: :func:`rollup` is pure over already-read session-log events, so none of this
needs a Ledger.

The two carrying the wave's argument are :func:`test_a_blank_axis_is_counted_not_grouped`
(a usage page whose biggest row is ``""`` has taught its reader nothing) and
:func:`test_an_unpriced_call_is_not_a_free_one` (a missing input that rounds to zero makes
every aggregate above it quietly wrong).
"""
from __future__ import annotations

import pytest

from aughor.obs.usage import (
    COST_SQL,
    DEFAULT_AXES,
    PRICES,
    Price,
    price_for,
    rollup,
)


def _call(*, provider="openrouter", model="m:free", role="coder", ok=True,
          pt=100, ct=50, ms=200.0, user_id="", org_id="default") -> dict:
    total = None if pt is None else (pt or 0) + (ct or 0)
    return {"provider": provider, "model": model, "ok": ok, "duration_ms": ms,
            "prompt_tokens": pt, "completion_tokens": ct, "total_tokens": total,
            "user_id": user_id, "org_id": org_id, "conn_id": "",
            "payload": {"role": role}}


# ── grouping ────────────────────────────────────────────────────────────────────────

def test_groups_by_the_default_axes():
    r = rollup([_call(model="a:free"), _call(model="a:free"), _call(model="b:free")])
    assert r.axes == DEFAULT_AXES
    assert r.total_calls == 3
    assert [(row.key["model"], row.calls) for row in r.rows] == [("a:free", 2), ("b:free", 1)]


def test_feature_axis_reads_the_runtime_role():
    """Measured, not assumed: the source suggests `role` is empty (twelve call sites pass
    ``role=""``) while the DATA says it is 100% populated, because the role is resolved at
    runtime from the model tier and never appears as a literal."""
    r = rollup([_call(role="coder"), _call(role="coder"), _call(role="narrator")],
               axes=("feature",))
    assert [(row.key["feature"], row.calls) for row in r.rows] == [("coder", 2), ("narrator", 1)]


def test_multiple_axes_compose():
    r = rollup([_call(provider="gemini", model="g", role="fast"),
                _call(provider="gemini", model="g", role="coder")],
               axes=("provider", "model", "feature"))
    assert len(r.rows) == 2
    assert all(row.key["provider"] == "gemini" for row in r.rows)


def test_an_unknown_axis_raises_rather_than_being_ignored():
    """Silently dropping an axis returns a report answering a different question than the
    one asked — the failure a usage page can least afford."""
    with pytest.raises(ValueError, match="unknown usage axis"):
        rollup([_call()], axes=("provider", "nonsense"))


# ── the honest half ─────────────────────────────────────────────────────────────────

def test_a_blank_axis_is_counted_not_grouped():
    """`user_id` is 0% populated in practice. Folding blanks into one group makes it read
    as a real cohort and the page look broken; counting them says something true."""
    r = rollup([_call(user_id=""), _call(user_id=""), _call(user_id="alice")],
               axes=("user_id",))
    assert r.unattributed["user_id"] == 2
    labels = {row.key["user_id"] for row in r.rows}
    assert "(unattributed)" in labels and "alice" in labels


def test_coverage_is_reported_per_axis():
    r = rollup([_call(user_id="alice"), _call(user_id="")], axes=("user_id",))
    assert r.to_dict()["coverage"]["user_id"] == 0.5


def test_a_fully_attributed_axis_reports_no_gap():
    r = rollup([_call(provider="gemini"), _call(provider="openrouter")], axes=("provider",))
    assert r.unattributed["provider"] == 0
    assert r.to_dict()["coverage"]["provider"] == 1.0


def test_missing_usage_is_unknown_not_zero():
    """Several backends omit usage entirely; folding that into 0 makes every cost
    aggregate above it silently wrong."""
    r = rollup([_call(pt=None, ct=None)])
    row = r.rows[0]
    assert row.calls_without_usage == 1
    assert row.total_tokens == 0
    assert not row.cost_is_complete


# ── cost ────────────────────────────────────────────────────────────────────────────

def test_free_models_are_priced_at_zero_deliberately():
    """`:free` is a FACT about this platform's working tier, not a missing price."""
    p = price_for("openrouter", "nvidia/nemotron-3-ultra-550b-a55b:free")
    assert p is not None and p.input_per_1m == 0.0
    r = rollup([_call(model="nvidia/nemotron-3-ultra-550b-a55b:free")])
    assert r.rows[0].cost_usd == 0.0
    assert r.rows[0].unpriced_calls == 0
    assert r.rows[0].cost_is_complete


def test_an_unpriced_call_is_not_a_free_one():
    """The number that is wrong is the one somebody will put in a budget."""
    r = rollup([_call(provider="anthropic", model="claude-opus-5")])
    row = r.rows[0]
    assert row.unpriced_calls == 1
    assert row.cost_usd == 0.0          # the PRICED portion is genuinely zero...
    assert not row.cost_is_complete     # ...and the row says so rather than implying free


def test_a_declared_price_is_applied_per_million_tokens(monkeypatch):
    monkeypatch.setitem(PRICES, ("acme", "big"), Price(10.0, 30.0, "2026-07-28"))
    r = rollup([_call(provider="acme", model="big-1", pt=1_000_000, ct=1_000_000)])
    assert r.rows[0].cost_usd == pytest.approx(40.0)
    assert r.rows[0].cost_is_complete


def test_the_longest_matching_prefix_wins(monkeypatch):
    monkeypatch.setitem(PRICES, ("acme", "big"), Price(10.0, 10.0, "2026-07-28"))
    monkeypatch.setitem(PRICES, ("acme", "big-pro"), Price(99.0, 99.0, "2026-07-28"))
    assert price_for("acme", "big-pro-1").input_per_1m == 99.0
    assert price_for("acme", "big-lite").input_per_1m == 10.0


def test_an_undeclared_provider_has_no_price():
    assert price_for("nobody", "anything") is None


def test_every_declared_price_carries_the_date_it_was_taken():
    """A price with no date is a claim that cannot be audited or refreshed."""
    assert all(p.as_of for p in PRICES.values())


# ── failures and shape ──────────────────────────────────────────────────────────────

def test_failure_rate_and_mean_latency():
    r = rollup([_call(ok=True, ms=100.0), _call(ok=False, ms=300.0)])
    row = r.rows[0].to_dict()
    assert row["failures"] == 1 and row["failure_rate"] == 0.5
    assert row["mean_ms"] == 200.0


def test_empty_input_is_an_empty_report():
    r = rollup([])
    assert r.total_calls == 0 and r.rows == []
    assert r.to_dict()["coverage"] == {a: 0.0 for a in DEFAULT_AXES}


def test_the_documented_sql_names_real_columns():
    """The copy-paste SQL lives beside the code computing the same numbers so the two
    cannot drift; an agent writing its own query needs the column names to be real."""
    for column in ("provider", "model", "prompt_tokens", "completion_tokens",
                   "total_tokens", "duration_ms", "kind"):
        assert column in COST_SQL
    assert "llm_call" in COST_SQL
