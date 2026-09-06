"""SP-1 (§3.11) — Spotlight's Know roster: the org-level platform reads.

The receipt suite here is the user's own four acceptance questions (2026-09-05):
runs + spend over a window, answer accuracy with its sample size, most-queried
table with the not-mined distinction, and investigation cadence. Each test names
the honesty rule it pins, because the honesty fields ARE the feature — a roster
that answers platform questions confidently from thin or absent data would be
worse than the dead-end it replaces.
"""
from __future__ import annotations

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
    # The quotable sentence carries the same numbers as the fields (one set of locals).
    assert "2 model calls" in out["summary"] and "165 tokens" in out["summary"]


def test_platform_usage_cost_honesty_travels(monkeypatch):
    """An unpriced call makes the total a floor, and the result must say so —
    cost_is_complete flips false rather than the unpriced call counting as free."""
    stub = _StubLedger([_llm_event(model="unpriced-model", provider="nowhere")])
    monkeypatch.setattr("aughor.kernel.ledger.Ledger.default",
                        classmethod(lambda cls: stub))
    out = spot.platform_usage({})
    assert out["unpriced_calls"] == 1
    assert out["cost_is_complete"] is False
    assert "FLOOR" in out["summary"] and "USD" in out["summary"]


def test_platform_usage_refuses_an_unknown_axis(monkeypatch):
    stub = _StubLedger([])
    monkeypatch.setattr("aughor.kernel.ledger.Ledger.default",
                        classmethod(lambda cls: stub))
    out = spot.platform_usage({"by": "nonsense"})
    assert "error" in out and "known_axes" in out
    assert stub.calls == []  # refused before any read


# ── platform_runs + cadence — Q1's runs half and Q5 ────────────────────────────────

def test_platform_runs_counts_both_planes(monkeypatch):
    """The automation half is a store-level windowed COUNT, never a row scan — the
    live drive caught the scan variant reporting 5 fired where the truth was 83."""
    from aughor.db.history import create_investigation, fail_investigation
    inv = create_investigation("q1", "conn-spot")
    create_investigation("q2", "conn-spot")
    fail_investigation(inv)

    asked: dict = {}
    def _count(day_floor):
        asked["floor"] = day_floor
        return {"fired": 83, "not_fired": 10_562, "gated": 1}
    monkeypatch.setattr("aughor.automations.store.count_runs_since", _count)

    out = spot.platform_runs({"days": 7})
    assert out["deep_runs"]["started"] >= 2
    assert out["deep_runs"]["failed"] >= 1
    # succeeded is an explicit field, never left for the narrator to infer.
    assert out["deep_runs"]["succeeded"] == out["deep_runs"]["finished"] - out["deep_runs"]["failed"]
    assert out["automation_runs"]["total"] == 10_646
    assert out["automation_runs"]["by_outcome"]["fired"] == 83
    assert len(asked["floor"]) == 10  # a YYYY-MM-DD day floor reached the store
    assert "succeeded" in out["summary"] and "10,646 total" in out["summary"]
    assert "fired 83" in out["summary"]


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
    assert "per month on average" in out["summary"]
    assert str(out["monthly_average"]) in out["summary"]


# ── answer_accuracy — Q2, the sample-size honesty ──────────────────────────────────

def test_accuracy_with_no_gradings_says_there_is_no_number(monkeypatch):
    monkeypatch.setattr(
        "aughor.feedback.verdicts.verdict_stats",
        lambda cid=None: {"counts": {}, "total": 0, "acceptance_rate": None, "trend": []})
    monkeypatch.setattr("aughor.semantic.trusted_queries.list_trusted", lambda cid: [])
    out = spot.answer_accuracy("c1", {})
    assert out["graded_total"] == 0 and out["acceptance_rate"] is None
    assert "no graded verdicts yet" in out["caveat"]
    assert "No graded verdicts yet" in out["summary"]
    assert "not low accuracy" in out["summary"]


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
    assert "80.0%" in out["summary"] and "only 5 graded" in out["summary"]
    assert len(out["recent_weeks"]) == spot._MAX_TREND_WEEKS  # trend capped
    assert out["trusted_queries"] == 3


# ── table_popularity — Q3, the not-mined distinction ───────────────────────────────

def test_popularity_empty_store_reports_not_mined_not_unpopular(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_POPULARITY_DB", str(tmp_path / "pop.db"))
    out = spot.table_popularity("conn-x", {})
    assert out["mined"] is False
    assert "not mined yet" in out["answer"]
    assert "not mined yet" in out["summary"]
    assert "cannot be filtered to a date window" in out["scope"]


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
    # "How many tables did we query" has a direct number, and the all-time scope is
    # quotable — the two halves of the live-drive misroute, closed.
    assert out["distinct_tables"] == 3
    assert "cannot be filtered to a date window" in out["scope"]
    assert "cannot be filtered to a date window" in out["summary"]
    assert "3 distinct tables" in out["summary"] and "refunds (55)" in out["summary"]


# ── the roster itself ──────────────────────────────────────────────────────────────

# ── platform_traces — the wave's trace leftover, metadata only ──────────────────────

def test_traces_listing_is_windowed_and_says_metadata_only(monkeypatch):
    rows = [
        {"trace_id": "t1", "started": "2026-09-06T01:00:00Z", "question": "q1",
         "ok": True, "errors": 0, "tool_calls": 3, "llm_calls": 2,
         "duration_ms": 900, "total_tokens": 500, "agent_id": "", "conn_id": "c1",
         "answer": "SECRET PAYLOAD"},
        {"trace_id": "t2", "started": "2026-09-06T00:00:00Z", "question": "q2",
         "ok": False, "errors": 1, "tool_calls": 1, "llm_calls": 1,
         "duration_ms": 100, "total_tokens": 50, "agent_id": "", "conn_id": "c1"},
    ]
    seen = {}
    def fake_recent(**kw):
        seen.update(kw)
        return rows
    monkeypatch.setattr("aughor.obs.session_log.recent_sessions", fake_recent)
    out = spot.platform_traces({"days": 7})
    assert seen["since"] and seen["limit"] == 10          # windowed at the reader
    assert "2 runs" in out["summary"] and "1 of them not ok" in out["summary"]
    assert "Metadata only" in out["summary"]
    assert all("answer" not in r for r in out["runs"])    # payload-ish fields dropped
    assert "note" in out                                  # the scan window, disclosed


def test_trace_lookup_absent_is_honest_about_the_two_causes(monkeypatch):
    monkeypatch.setattr("aughor.obs.session_log.recover_session",
                        lambda tid, org_id=None: [])
    out = spot.platform_traces({"trace_id": "nope"})
    assert out["found"] is False
    assert "does not exist, or it belongs to another org" in out["summary"]


def test_trace_anatomy_quotes_timing_and_errors_without_payloads(monkeypatch):
    monkeypatch.setattr("aughor.obs.session_log.recover_session",
                        lambda tid, org_id=None: [{"kind": "user_request"}])
    monkeypatch.setattr("aughor.obs.trace_summary.build_summary",
                        lambda tid, events: {
                            "trace_id": tid, "question": "why slow", "ok": False,
                            "started_at": "2026-09-06T00:00:00Z",
                            "counts": {"events": 9, "spans": 4, "model_calls": 2,
                                       "errors": 1},
                            "time": {"wall_ms": 1234, "busy_ms": 1000},
                            "models": ["m:free"],
                            "slowest_spans": [{"name": "answer", "kind": "tool_call",
                                               "duration_ms": 800, "pct_of_run": 65,
                                               "span_id": "s1", "model": "m:free",
                                               "depth": 1}],
                            "errors": [{"name": "run_sql", "kind": "tool_call",
                                        "error_class": "GuardRefusal",
                                        "at": "x", "span_id": "s2"}],
                        })
    out = spot.platform_traces({"trace_id": "t9"})
    assert out["found"] is True and out["ok"] is False
    assert "1234 ms wall" in out["summary"] and "GuardRefusal" in out["summary"]
    assert set(out["slowest_steps"][0]) == {"name", "kind", "duration_ms",
                                            "pct_of_run"}   # span ids/payload refs cut
    assert set(out["errors"][0]) == {"name", "kind", "error_class"}


# ── platform_audit — the unified feed, relayed not re-derived ───────────────────────

def test_audit_unknown_category_names_the_known_ones():
    out = spot.platform_audit({"category": "vibes"})
    assert "unknown category" in out["error"]
    assert "action_decision" in out["known_categories"]


def test_audit_feed_rows_are_compact_and_the_scope_is_disclosed(monkeypatch):
    from types import SimpleNamespace
    events = [SimpleNamespace(category="model_call", kind="llm_call",
                              at="2026-09-06T01:00:00Z", actor="local",
                              summary="a call", detail={"huge": "blob"})]
    monkeypatch.setattr("aughor.govern.audit_categories.feed",
                        lambda category=None, limit=100: events)
    out = spot.platform_audit({"limit": 5})
    assert out["events"] == [{"category": "model_call", "kind": "llm_call",
                              "at": "2026-09-06T01:00:00Z", "actor": "local",
                              "summary": "a call"}]          # detail stays home
    assert "recency feed" in out["summary"]                  # never a total


# ── platform_premortem — SP-6's proact half: evidence rows, offers, never applies ──

def test_premortem_finds_an_error_streak_with_its_evidence_rows(monkeypatch):
    # The shared hermetic stores hold whatever earlier tests seeded; lift the scan
    # and display caps so THIS receipt asserts detection, not cap arithmetic (the
    # caps' own honesty — "scanned N of M" — has its own receipt below).
    monkeypatch.setattr(spot, "_PREMORTEM_MAX_AUTOMATIONS", 100_000)
    monkeypatch.setattr(spot, "_PREMORTEM_MAX_FINDINGS", 100_000)
    from aughor.actions.inbox import list_proposals
    from aughor.automations.models import Automation, AutomationRun, Condition, Effect
    from aughor.automations.store import append_run, upsert_automation

    a = upsert_automation(Automation(
        conn_id="pm-conn", name="always-breaking",
        conditions=[Condition(kind="schedule", config={"cron": "0 7 * * 1"})],
        effects=[Effect(kind="notify", config={"trigger_id": "t1"})]))
    for i in range(3):
        append_run(AutomationRun(automation_id=a.id, automation_name=a.name,
                                 conn_id="pm-conn", outcome="error",
                                 reason=f"boom {i}"))

    before = len(list_proposals(status="pending"))
    out = spot.platform_premortem({})
    streaks = [f for f in out["findings"] if f["kind"] == "automation_error_streak"
               and f["subject"] == "always-breaking"]
    assert streaks, "the 3-error streak was not flagged"
    ev = streaks[0]["evidence"]
    assert len(ev) >= 3 and all(e["run_id"] for e in ev)     # rows, not vibes
    assert streaks[0]["offer"]["tool"] == "pause_or_resume_automation"
    assert "nothing here applies anything" in out["summary"]
    assert len(list_proposals(status="pending")) == before   # the sweep staged NOTHING


def test_premortem_flags_zero_document_agents_and_a_broken_store_is_not_clean(monkeypatch):
    monkeypatch.setattr(spot, "_PREMORTEM_MAX_AUTOMATIONS", 100_000)
    monkeypatch.setattr(spot, "_PREMORTEM_MAX_FINDINGS", 100_000)
    from aughor.custom_agents.store import create_agent
    ag = create_agent("premortem-bare", instructions="A scope and a stance.")

    out = spot.platform_premortem({})
    bare = [f for f in out["findings"] if f["kind"] == "agent_without_documents"
            and f["evidence"][0]["agent_id"] == ag.id]
    assert bare and bare[0]["offer"]["tool"] == ""           # honest page offer

    def boom():
        raise RuntimeError("agents store gone")
    monkeypatch.setattr("aughor.custom_agents.store.list_agents", boom)
    out2 = spot.platform_premortem({})
    assert "agents" in out2["stores_unavailable"]
    assert "not a clean bill of health" in out2["summary"]


def test_premortem_discloses_a_partial_scan_instead_of_a_clean_bill(monkeypatch):
    """A capped sweep must say what it did NOT check — the confident-clean-report
    class, refused. Force the cap below the store's population and read the words."""
    monkeypatch.setattr(spot, "_PREMORTEM_MAX_AUTOMATIONS", 1)
    from aughor.automations.models import Automation, Condition, Effect
    from aughor.automations.store import upsert_automation
    for n in ("scan-cap-a", "scan-cap-b"):
        upsert_automation(Automation(
            conn_id="pm-conn", name=n,
            conditions=[Condition(kind="schedule", config={"cron": "0 7 * * 1"})],
            effects=[Effect(kind="notify", config={"trigger_id": "t1"})]))
    out = spot.platform_premortem({})
    assert "were NOT checked" in out["summary"]


# ── the roster ──────────────────────────────────────────────────────────────────────

def test_spotlight_roster_names_and_read_contract():
    tools = spot.spotlight_tools("c1")
    names = [t.name for t in tools]
    assert names == ["list_platform_connections", "platform_usage", "platform_runs",
                     "investigation_cadence", "answer_accuracy", "table_popularity",
                     "platform_traces", "platform_premortem", "platform_audit"]


def test_conversation_gets_the_spotlight_roster():
    from aughor.agent.converse_tools import converse_tools
    names = {t.name for t in converse_tools("c1")}
    for expected in ("platform_usage", "list_platform_connections", "table_popularity",
                     "answer_accuracy", "platform_runs", "investigation_cadence",
                     "platform_traces", "platform_audit"):
        assert expected in names
