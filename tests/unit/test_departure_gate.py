"""HB-2 — the departure gate (govern/departure.py): trust hold, tie-out at the gate,
probation addressing, and the ledger that records every decision.

The wave's receipt sentence lives in ``test_hb2_receipt.py`` (a send held at departure by
a failing tie-out on real SQL); these lock the gate's own logic, dependency-light.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from aughor.govern import departure_store as ds
from aughor.govern.departure import TRUST_BANNER, gate_departure


def _gate(text, **kw):
    base = dict(kind="slack_post", org_id="default", conn_id="", text=text,
                automation_id=kw.pop("automation_id", "auto1"),
                automation_name="Test chain", target="#ops")
    base.update(kw)
    return gate_departure(**base)


# ── trust: the banner holds, and it is the SAME banner the reframe writes ─────────

def test_the_reframes_own_banner_is_held_at_departure():
    """Round trip: the deep run's reframe composes its banner from TRUST_BANNER, and the
    gate detects exactly that text — a reword in either place breaks this pair, which is
    the point (the 2026-09-16 incident departed BECAUSE nothing re-checked trust between
    the report and the send)."""
    from aughor.agent.investigate import _reframe_on_trust_caveat

    class _Synth:
        confidence = "HIGH"
        confidence_justification = ""
        headline = ""
        executive_summary = "Net revenue rose 9.1% on 2026-09-08."
        data_gaps: list = []

    synth = _Synth()
    phases = [{"findings": [{"trust_caveat": "metric formula drift: the finding asserts "
                             "Revenue but the query computes it a different way",
                             "rows": [["2026-09-08", "9.1"]]}]}]
    assert _reframe_on_trust_caveat(synth, phases) is True
    v = _gate(synth.executive_summary)
    assert v.state == "held"
    assert "trust check" in v.reason_sentence()


def test_clean_text_departs():
    v = _gate("All metrics nominal today; nothing unusual to report.")
    assert v.state == "departed" and not v.held


# ── tie-out: validate_metric runs at the gate ─────────────────────────────────────

_REVENUE = SimpleNamespace(name="revenue", label="Revenue", sql="SUM(total_amount)",
                           tables=["orders"], dimensions=[],
                           quality_tests=["SELECT COUNT(*) = 0 FROM orders WHERE total_amount IS NULL"],
                           wrong_usage_examples=[])


def _stub_metrics(monkeypatch):
    monkeypatch.setattr("aughor.semantic.metrics.list_metrics", lambda **_: [_REVENUE])


def test_failing_tieout_holds(monkeypatch):
    _stub_metrics(monkeypatch)
    monkeypatch.setattr("aughor.db.connection.open_connection_for", lambda cid: object())
    monkeypatch.setattr("aughor.semantic.metrics.validate_metric",
                        lambda m, db: SimpleNamespace(passed=False,
                                                      message="1 of 1 quality tests failed"))
    v = _gate("Revenue reached 4,100 this week.", conn_id="c1")
    assert v.state == "held"
    assert "tie-out" in v.reason_sentence() and "revenue" in v.reason_sentence()


def test_passing_tieout_departs(monkeypatch):
    _stub_metrics(monkeypatch)
    monkeypatch.setattr("aughor.db.connection.open_connection_for", lambda cid: object())
    monkeypatch.setattr("aughor.semantic.metrics.validate_metric",
                        lambda m, db: SimpleNamespace(passed=True, message="ok"))
    v = _gate("Revenue reached 4,100 this week.", conn_id="c1")
    assert v.state == "departed"
    assert "passed" in v.checks["tie_out"]


def test_unavailable_tieout_is_recorded_not_held(monkeypatch):
    """An infrastructure error is not a failing number: the departure proceeds, and the
    record says the tie-out could not run — never a silent pass."""
    _stub_metrics(monkeypatch)

    def _boom(cid):
        raise RuntimeError("warehouse down")
    monkeypatch.setattr("aughor.db.connection.open_connection_for", _boom)
    v = _gate("Revenue reached 4,100 this week.", conn_id="c1")
    assert v.state == "departed"
    assert "unavailable" in v.checks["tie_out"]


def test_unasserted_metric_runs_no_tieout(monkeypatch):
    _stub_metrics(monkeypatch)

    def _never(cid):  # pragma: no cover - the assertion IS that this is never reached
        raise AssertionError("tie-out must not open a connection for unasserted text")
    monkeypatch.setattr("aughor.db.connection.open_connection_for", _never)
    v = _gate("Margins look stable across regions.", conn_id="c1")
    assert v.state == "departed"


# ── probation: addressing, inertness, and accuracy outranking it ──────────────────

def test_probation_holds_to_the_declarer():
    v = _gate("All quiet.", probation=True, declared_by="user:ana")
    assert v.state == "held_probation"
    row = ds.get_departure(v.record_id)
    assert row["addressed_to"] == "user:ana" and row["state"] == "held_probation"


def test_probation_without_declarer_is_inert():
    """Identity off ⇒ no declarer ⇒ nobody to address the review to — probation waits on
    OIDC exactly as HB-1's enforcement does."""
    v = _gate("All quiet.", probation=True, declared_by="")
    assert v.state == "departed"
    assert "inert" in v.checks["probation"]


def test_accuracy_hold_outranks_probation():
    """A wrong number is held from EVERYONE — the declarer does not receive what the
    channel was spared."""
    v = _gate(f"⚠ {TRUST_BANNER} and the figures below are NOT reliable: x. Do not read.",
              probation=True, declared_by="user:ana")
    assert v.state == "held"                      # not held_probation
    assert ds.get_departure(v.record_id)["addressed_to"] == ""


# ── the ledger: every decision recorded, and a broken ledger never un-holds ───────

def test_departed_rows_are_recorded_too():
    assert not _gate("Nothing to report.", automation_id="ledger-auto").held
    rows = ds.list_departures(automation_id="ledger-auto")
    assert rows and rows[0]["state"] == "departed"
    assert json.loads(rows[0]["checks"])["trust"] == "clean"


def test_broken_ledger_does_not_unhold(monkeypatch):
    def _boom(**kw):
        raise RuntimeError("disk full")
    monkeypatch.setattr("aughor.govern.departure_store.record_departure", _boom)
    v = _gate(f"⚠ {TRUST_BANNER}: bad. Do not read.")
    assert v.state == "held" and v.record_id == ""


# ── verdicts and precision ────────────────────────────────────────────────────────

def test_precision_counts_correct_as_useful():
    for i, verdict in enumerate(("accept", "correct", "reject")):
        v = _gate("All quiet.", automation_id="prec-auto", probation=True,
                  declared_by="user:ana")
        ds.mark_departure(v.record_id, verdict)
    stats = ds.precision_for("prec-auto")
    assert stats["marked"] == 3
    assert stats["precision"] == pytest.approx(2 / 3)
