"""SP-1 (§3.11) — Spotlight's Know roster: the org-level platform reads.

The receipt suite here is the user's own four acceptance questions (2026-09-05):
runs + spend over a window, answer accuracy with its sample size, most-queried
table with the not-mined distinction, and investigation cadence. Each test names
the honesty rule it pins, because the honesty fields ARE the feature — a roster
that answers platform questions confidently from thin or absent data would be
worse than the dead-end it replaces.
"""
from __future__ import annotations

from types import SimpleNamespace

import aughor.agent.spotlight_tools as spot
from aughor.sql.popularity import PopularitySignal, save_popularity


def _llm_event(*, model="m:free", pt=100, ct=50, provider="openrouter") -> dict:
    return {"provider": provider, "model": model, "ok": True, "duration_ms": 10.0,
            "prompt_tokens": pt, "completion_tokens": ct, "total_tokens": pt + ct,
            "user_id": "", "org_id": "default", "conn_id": "", "agent_id": "",
            "payload": {"role": "coder"}}


class _StubLedger:
    def __init__(self, rows):
        self.rows = rows
        self.calls: list[dict] = []

    def session_events(self, **kw):
        self.calls.append(kw)
        return self.rows


# ── platform_usage — Q1's token/spend half ──────────────────────────────────────────

def test_platform_usage_windows_the_read_and_totals_the_rollup(monkeypatch):
    stub = _StubLedger([_llm_event(), _llm_event(model="b:free", pt=10, ct=5)])
    monkeypatch.setattr("aughor.kernel.ledger.Ledger.default",
                        classmethod(lambda cls: stub))
    out = spot.platform_usage({"days": 7, "by": "model"})
    assert out["window_days"] == 7 and out["grouped_by"] == "model"
    assert out["total_calls"] == 2 and out["total_tokens"] == 165
    # The read was windowed at the LEDGER, not filtered client-side after an
    # unwindowed scan: `since` is the reader's documented ISO bound.
    kw = stub.calls[0]
    assert kw["since"] and kw["kind"] and kw["limit"] == spot._USAGE_SCAN
    assert {g["model"] for g in out["groups"]} == {"m:free", "b:free"}


def test_platform_usage_cost_honesty_travels(monkeypatch):
    """An unpriced call makes the total a floor, and the result must say so —
    cost_is_complete flips false rather than the unpriced call counting as free."""
    stub = _StubLedger([_llm_event(model="unpriced-model", provider="nowhere")])
    monkeypatch.setattr("aughor.kernel.ledger.Ledger.default",
                        classmethod(lambda cls: stub))
    out = spot.platform_usage({})
    assert out["unpriced_calls"] == 1
    assert out["cost_is_complete"] is False


def test_platform_usage_refuses_an_unknown_axis(monkeypatch):
    stub = _StubLedger([])
    monkeypatch.setattr("aughor.kernel.ledger.Ledger.default",
                        classmethod(lambda cls: stub))
    out = spot.platform_usage({"by": "nonsense"})
    assert "error" in out and "known_axes" in out
    assert stub.calls == []  # refused before any read


# ── platform_runs + cadence — Q1's runs half and Q5 ────────────────────────────────

def test_platform_runs_counts_both_planes(monkeypatch):
    from aughor.db.history import create_investigation, fail_investigation
    inv = create_investigation("q1", "conn-spot")
    create_investigation("q2", "conn-spot")
    fail_investigation(inv)

    runs = [SimpleNamespace(model_dump=lambda d=d: d) for d in (
        {"started_at": "2099-01-01T00:00:00", "outcome": "fired"},       # future: inside
        {"started_at": "1999-01-01 00:00:00", "outcome": "error"},       # far past: outside
    )]
    monkeypatch.setattr("aughor.automations.store.get_runs", lambda limit=500: runs)

    out = spot.platform_runs({"days": 7})
    assert out["deep_runs"]["started"] >= 2
    assert out["deep_runs"]["failed"] >= 1
    # Day-substring windowing: the ISO-T future row is in, the space-form 1999 row out.
    assert out["automation_runs"]["by_outcome"] == {"fired": 1}


def test_cadence_lists_zero_months_and_averages_over_all_of_them():
    from aughor.db.history import create_investigation
    create_investigation("q-cadence", "conn-spot2")
    out = spot.investigation_cadence({"months": 3})
    assert len(out["series"]) == 3
    assert out["series"][-1]["started"] >= 1          # this month has the row
    assert any(p["started"] == 0 for p in out["series"][:-1]) or all(
        p["started"] > 0 for p in out["series"])       # zero months present, not omitted
    total = sum(p["started"] for p in out["series"])
    assert out["monthly_average"] == round(total / 3, 1)


# ── answer_accuracy — Q2, the sample-size honesty ──────────────────────────────────

def test_accuracy_with_no_gradings_says_there_is_no_number(monkeypatch):
    monkeypatch.setattr(
        "aughor.feedback.verdicts.verdict_stats",
        lambda cid=None: {"counts": {}, "total": 0, "acceptance_rate": None, "trend": []})
    monkeypatch.setattr("aughor.semantic.trusted_queries.list_trusted", lambda cid: [])
    out = spot.answer_accuracy("c1", {})
    assert out["graded_total"] == 0 and out["acceptance_rate"] is None
    assert "no graded verdicts yet" in out["caveat"]


def test_accuracy_thin_sample_carries_the_caveat(monkeypatch):
    monkeypatch.setattr(
        "aughor.feedback.verdicts.verdict_stats",
        lambda cid=None: {"counts": {"accept": 4, "reject": 1}, "total": 5,
                          "acceptance_rate": 0.8, "trend": [{"week": "2026-W36"}] * 9})
    monkeypatch.setattr("aughor.semantic.trusted_queries.list_trusted",
                        lambda cid: [object()] * 3)
    out = spot.answer_accuracy("c1", {})
    assert out["acceptance_rate"] == 0.8 and out["graded_total"] == 5
    assert "only 5 graded" in out["caveat"]
    assert len(out["recent_weeks"]) == spot._MAX_TREND_WEEKS  # trend capped
    assert out["trusted_queries"] == 3


# ── table_popularity — Q3, the not-mined distinction ───────────────────────────────

def test_popularity_empty_store_reports_not_mined_not_unpopular(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_POPULARITY_DB", str(tmp_path / "pop.db"))
    out = spot.table_popularity("conn-x", {})
    assert out["mined"] is False
    assert "not mined yet" in out["answer"]


def test_popularity_mined_counts_rank_and_cap(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_POPULARITY_DB", str(tmp_path / "pop.db"))
    save_popularity(PopularitySignal(
        connection_id="conn-x",
        table_counts={"orders": 40, "users": 12, "refunds": 55},
        column_counts={"orders.total": 30},
        n_queries=60, mined_at=1.0))
    out = spot.table_popularity("conn-x", {"top": 2})
    assert out["mined"] is True
    assert [t["table"] for t in out["top_tables"]] == ["refunds", "orders"]
    assert out["top_columns"][0]["column"] == "orders.total"


# ── the roster itself ──────────────────────────────────────────────────────────────

def test_spotlight_roster_names_and_read_contract():
    tools = spot.spotlight_tools("c1")
    names = [t.name for t in tools]
    assert names == ["list_platform_connections", "platform_usage", "platform_runs",
                     "investigation_cadence", "answer_accuracy", "table_popularity"]


def test_conversation_gets_the_spotlight_roster():
    from aughor.agent.converse_tools import converse_tools
    names = {t.name for t in converse_tools("c1")}
    for expected in ("platform_usage", "list_platform_connections", "table_popularity",
                     "answer_accuracy", "platform_runs", "investigation_cadence"):
        assert expected in names
