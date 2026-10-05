"""The arc's close-out, C4 — a run proposed with its cost (the 2027 study §H) and the two weak signals
§K named as missing: the settling lag itself changing and a declared process's early stages slowing
(`aughor/record/inquiry.propose_run`, `aughor/record/signals.py`).

What these hold: an inquiry a signal opened, or that woke, carries a proposed run with what it costs on
THIS install — the median tokens and minutes of its own metered runs with their count, a dollar floor
with the unpriced calls said, the charter's ceiling — and what the run could change; with no metered run
the ceiling is the only number and the proposal says so; with nothing open no run is proposed; the
settling lag moving opens an inquiry and a first verdict or a small move does not; an early stage
slowing or a promise breaking more opens an inquiry, a last stage's lag and a first measurement do not;
both hooks sit where the platform already takes the readings; every signal is journaled and catalogued.
"""
from __future__ import annotations

import inspect
import uuid
from datetime import datetime, timedelta, timezone

from aughor.kernel.ledger import Ledger
from aughor.record import claims as C
from aughor.record import inquiry as I
from aughor.record import signals as S
from aughor.routers import record as R

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


def _conn():
    return "conn-" + uuid.uuid4().hex[:6]


def _job(conn: str, tokens: int, minutes: float, kind: str = "investigation", state: str = "SUCCEEDED"):
    jid = "job-" + uuid.uuid4().hex[:8]
    started = NOW - timedelta(minutes=minutes)
    Ledger.default().job_insert({"id": jid, "kind": kind, "conn_id": conn, "state": state, "attempt": 1,
                                 "created_at": started.isoformat(), "started_at": started.isoformat(), "finished_at": NOW.isoformat()})
    Ledger.default().job_update(jid, metrics=__import__("json").dumps({"total_tokens": tokens, "llm_calls": 3}))
    return jid


def test_a_signal_opened_inquiry_proposes_its_run_with_what_it_costs_here(monkeypatch):
    conn = _conn()
    for tokens, mins in ((40_000, 3.0), (60_000, 5.0), (80_000, 4.0)):
        _job(conn, tokens, mins)
    _job(conn, 0, 1.0)                                    # the outer twin of a nested run: 0 tokens, left out
    _job(conn, 500_000, 20.0, state="FAILED")             # a failed run is not what a run costs
    _job(conn, 9_000, 1.0, kind="automation")             # another kind
    monkeypatch.setattr("aughor.obs.session_log.recent_sessions",
                        lambda **kw: [{"conn_id": conn, "investigation_id": "inv1", "cost_usd": 0.12, "unpriced_calls": 0, "llm_calls": 4},
                                      {"conn_id": conn, "investigation_id": "inv2", "cost_usd": 0.20, "unpriced_calls": 0, "llm_calls": 5},
                                      {"conn_id": conn, "investigation_id": "inv3", "cost_usd": 0.05, "unpriced_calls": 2, "llm_calls": 3},
                                      {"conn_id": "other", "investigation_id": "inv4", "cost_usd": 9.0, "unpriced_calls": 0, "llm_calls": 1}])
    cost = I.run_cost_estimate(conn)
    assert cost["n"] == 3 and cost["tokens"] == 60_000 and cost["minutes"] == 4.0
    assert cost["usd_floor"] == 0.16 and cost["usd_n"] == 2 and cost["unpriced_calls"] == 2
    assert cost["ceiling"]["charter"] == "analyst" and cost["ceiling"]["tokens"] and cost["ceiling"]["seconds"]
    assert cost["from"].startswith("the install's own 3 metered runs") and "2 model calls unpriced" in cost["from"]
    q = I.open_inquiry(question="Why did returns rise?", connection_id=conn, opened_by="monitor:m1", subject="returns", now=NOW)
    p = q.extra["proposed_run"]
    assert p["proposed"] is True and p["kind"] == "investigation" and p["cost"]["tokens"] == 60_000 and p["could_change"]["open_items"] == []
    assert "cheapest test goes first" in p["rule"] and p["proposed_at"] == NOW.isoformat()
    # a connection with no metered run: the ceiling is the only number, said
    empty = I.run_cost_estimate(_conn())
    assert empty["n"] == 0 and empty["tokens"] is None and empty["from"].startswith("no metered run") and empty["ceiling"]["tokens"]
    # the door recomputes and keeps it
    view = R.propose_record_inquiry_run(q.id)
    assert view["extra"]["proposed_run"]["proposed"] is True and view["version"] == 2


def test_a_woken_inquiry_proposes_its_run_and_one_with_nothing_open_proposes_none():
    conn = _conn()
    q = I.open_inquiry(question="Why did margin fall?", connection_id=conn, opened_by="person:ana", run_id="run-" + uuid.uuid4().hex[:6], now=NOW)
    assert "proposed_run" not in q.extra                   # a person's ask has its run running: nothing to propose
    hyp = C.book(C.Claim(kind="hypothesis", tier="said", about=C.About(kind="connection", key=conn),
                         statement=C.Statement(text="discounts widened"), author="inquirer", author_kind="agent", state="open"),
                 key=C.claim_key("hypothesis", conn, "x", "1"), conn_id=conn)
    q.hypotheses.append(hyp)
    q.open = [I.OpenItem(what="the settled figures for last week", settled_by="the connection's settling lag: 3 days"),
              I.OpenItem(what="the discount table's grain", settled_by="")]
    q.state, q.next_check = "waiting", "2026-10-04"
    q = I._book(q)
    woke = I.wake(q, why="its check date came", now=NOW)
    p = woke.extra["proposed_run"]
    assert p["proposed"] is True and [o["what"] for o in p["could_change"]["open_items"]][0] == "the settled figures for last week"
    assert p["could_change"]["open_hypotheses"][0]["claim"] == hyp
    # nothing open after a run: no run is proposed, and the proposal says why
    woke.open, woke.hypotheses = [], []
    woke.runs = [I.RunNote(run="r1", verdict="answered", why="done", at=NOW.isoformat())]
    none = I.propose_run(woke, now=NOW)
    assert none["proposed"] is False and "nothing is open" in none["why"] and "cost" not in none
    closed = I.close_inquiry(woke, closed_as="answered")
    assert I.propose_run(closed)["why"] == "the inquiry is closed"


def test_the_settling_lag_moving_is_a_signal_that_opens_an_inquiry_and_a_small_move_or_a_first_verdict_is_not():
    learned = lambda d, **kw: {"days": d, "source": "learned", "still_moving": [], "horizon": 14, **kw}  # noqa: E731
    assert S.settling_signal(learned(None, source=None), learned(5)) is None            # the first verdict is a baseline
    assert S.settling_signal(learned(5), learned(6)) is None                              # one day is noise
    assert S.settling_signal(learned(12), learned(14)) is None                            # 2 days, under half of 12
    sig = S.settling_signal(learned(3), learned(7))
    assert sig["signal"] == "settling_lag" and sig["before"] == 3 and sig["after"] == 7 and "3 to 7 days" in sig["text"]
    big = S.settling_signal(learned(3), {"days": 15, "source": "beyond_horizon", "still_moving": ["order_items"], "horizon": 14})
    assert "3 to 15 days" in big["text"] and "still moving: order_items" in big["text"]
    sig2 = S.settling_signal(learned(14), {"days": 15, "source": "beyond_horizon", "still_moving": ["order_items"], "horizon": 14})
    assert "stopped settling" in sig2["text"] and "order_items" in sig2["text"]      # no big move, but a table stopped settling
    assert S.settling_signal(learned(5), {"days": None, "source": None, "still_moving": [], "horizon": 0}) is None
    conn = _conn()
    q = S.on_settling_sampled(conn, learned(3), learned(7))
    assert q is not None and q.opened_by == "settling" and q.subject == "settling-lag" and "3 to 7 days" in q.question
    assert q.extra["proposed_run"]["proposed"] is True
    again = S.on_settling_sampled(conn, learned(7), learned(12))                       # the same subject within a fortnight: one inquiry
    assert again.key == q.key and again.version >= q.version
    assert S.on_settling_sampled(conn, learned(7), learned(8)) is None
    events = Ledger.default().events(kind="inquiry.signal", conn_id=conn)
    assert events and events[0]["payload"]["signal"] == "settling_lag" and events[0]["payload"]["inquiry"]
    from aughor.kernel.events import CATALOGUE
    assert "inquiry.signal" in CATALOGUE
    from aughor.settling import sampler
    assert "on_settling_sampled" in inspect.getsource(sampler.run_settling_samples_daily)


def _measured(stages):
    return {"id": "order_to_delivery", "entity": "Order", "stages": stages}


def test_an_early_stage_slowing_or_a_promise_breaking_more_opens_an_inquiry_and_the_last_stage_does_not():
    before = _measured([{"name": "placed"}, {"name": "dispatched", "p90_days": 2.0, "promise": {"name": "dispatch", "breach_rate": 0.04}},
                        {"name": "delivered", "p90_days": 6.0, "promise": {"name": "delivery", "breach_rate": 0.10}}])
    same = S.process_signals("order_to_delivery", before, before)
    assert same == [] and S.process_signals("order_to_delivery", None, before) == []       # a first measurement is a baseline
    after = _measured([{"name": "placed"}, {"name": "dispatched", "p90_days": 3.0, "promise": {"name": "dispatch", "breach_rate": 0.11}},
                       {"name": "delivered", "p90_days": 12.0, "promise": {"name": "delivery", "breach_rate": 0.12}}])
    sigs = S.process_signals("order_to_delivery", before, after)
    kinds = {(s["signal"], s["stage"]) for s in sigs}
    assert ("stage_slowed", "dispatched") in kinds and ("promise_breaking", "dispatched") in kinds
    assert ("stage_slowed", "delivered") not in kinds                                     # the last stage's lag is the KPI, not the early signal
    assert ("promise_breaking", "delivered") not in kinds                                  # two points is under the five the rule asks
    slowed = next(s for s in sigs if s["signal"] == "stage_slowed")
    assert slowed["before"] == 2.0 and slowed["after"] == 3.0 and "p90 2.0 → 3.0 days" in slowed["text"]
    conn = _conn()
    opened = S.on_process_measured(conn, "order_to_delivery", {"measured": before}, {"measured": after})
    assert len(opened) == 2 and {q.opened_by for q in opened} == {"process:order_to_delivery"}
    assert any("dispatched stage" in q.question for q in opened) and all(q.extra["proposed_run"]["proposed"] for q in opened)
    assert S.on_process_measured(conn, "order_to_delivery", None, {"measured": after}) == []
    from aughor.ontology import processes
    assert "on_process_measured" in inspect.getsource(processes.measure_override_processes)
