"""Phase 2 of the 2027 study, P2-1 and P2-3 — the durable inquiry and the typed run verdict
(`aughor/record/inquiry.py`).

What these hold: a person's ask opens an inquiry, and a second ask on the same subject within a
fortnight wakes it instead of doubling it; a completed run lands on its inquiry with its
hypotheses as claims (state from the verdict; a refuted one warranted by the run), its open items
with what would settle each, a typed verdict, and the inquiry's own state — waiting with a wake
date when something is open, closed when nothing is; a failed run books a typed verdict by code
over the recorded reason and leaves the inquiry open; a refuted hypothesis is memory the next run
on the connection reads back, refuses when proposed again, and says so; the heartbeat wakes a
waiting inquiry on its date and a restated claim wakes the inquiries that established it; a fired
monitor alert opens an inquiry; and the skeptic challenges from a second binding where the install
has two, recorded either way.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from aughor.agent.state import Hypothesis
from aughor.db.history import complete_investigation, create_investigation, fail_investigation
from aughor.record import claims as C
from aughor.record import inquiry as I
from aughor.routers import record as R

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


def _conn():
    return "conn-" + uuid.uuid4().hex[:6]


@pytest.fixture(autouse=True)
def _lag(monkeypatch):
    import aughor.settling.store as settling
    monkeypatch.setattr(settling, "learned_lag_days", lambda conn_id: 3)


# ── opening and waking ─────────────────────────────────────────────────────────────────────

def test_an_ask_opens_an_inquiry_and_a_second_on_the_same_subject_wakes_it():
    conn = _conn()
    q = I.open_inquiry(question="Why did revenue fall last week?", connection_id=conn, opened_by="person:ana",
                       run_id="run-1", now=NOW)
    assert q.state == "open" and q.subject == "revenue-fall" and q.opened_by == "person:ana"
    assert q.key.startswith(f"inquiry:{conn}:revenue-fall:") and q.extra["first_run"] == "run-1"
    again = I.open_inquiry(question="why did Revenue fall?", connection_id=conn, opened_by="person:bo",
                           run_id="run-2", now=NOW + timedelta(days=2))
    assert again.key == q.key and again.version == 2 and again.extra["pending_runs"] == ["run-2"]
    other = I.open_inquiry(question="Why did returns rise?", connection_id=conn, opened_by="person:bo", now=NOW)
    assert other.key != q.key and other.subject == "returns-rise"
    assert I.for_run("run-2", conn_id=conn).key == q.key and I.for_run("ghost") is None


def test_the_subject_prefers_the_declared_metric():
    assert I.subject_of("why did it move?", "Total Sales") == "total-sales"
    assert I.subject_of("How many orders did we get each day last week?") == "many-orders-get-each"


# ── a run lands on its inquiry ─────────────────────────────────────────────────────────────

def _hyps():
    return [Hypothesis(id="H1", description="late dispatch drove the returns", confidence=0.2, verdict="refuted",
                       key_finding="returns rose equally for on-time and late dispatch"),
            Hypothesis(id="H2", description="a packaging change in the north region", confidence=0.8,
                       verdict="confirmed", key_finding="north returns doubled after week 36"),
            Hypothesis(id="H3", description="a courier change", verdict="inconclusive", key_finding=""),
            Hypothesis(id="H4", description="weather", verdict="untested")]


def test_a_completed_run_books_its_hypotheses_as_claims_and_leaves_the_inquiry_waiting_on_its_gaps():
    conn = _conn()
    inv_id = create_investigation("Why did returns rise?", conn)
    I.open_inquiry(question="Why did returns rise?", connection_id=conn, opened_by="person:ana", run_id=inv_id, now=NOW)
    report = {"headline": "Returns rose on a packaging change in the north",
              "data_gaps": ["September is still settling: 21 of 30 days", "No courier data is connected"]}
    complete_investigation(inv_id, report=report, hypotheses=_hyps(), query_history=[], question="Why did returns rise?",
                           connection_id=conn, skip_index=True, cache=False)
    q = I.for_run(inv_id, conn_id=conn)
    assert q is not None and len(q.hypotheses) == 4
    states = {C.get(cid).extra["hypothesis_id"]: C.get(cid).state for cid in q.hypotheses}
    assert states == {"H1": "refuted", "H2": "supported", "H3": "open", "H4": "abandoned"}
    refuted = next(C.get(cid) for cid in q.hypotheses if C.get(cid).state == "refuted")
    assert refuted.kind == "hypothesis" and refuted.tier == "said" and refuted.author_kind == "agent"
    assert [(w.kind, w.ref) for w in refuted.warrants] == [("run", inv_id)]
    assert refuted.extra["evidence"].startswith("returns rose equally")
    assert [o.settled_by for o in q.open] == ["the connection's settling lag: 3 days",
                                             "unstated — the report named the gap without what would close it"]
    assert q.state == "waiting" and q.waiting_for == "days to settle"
    assert q.next_check == (datetime.now(timezone.utc).date() + timedelta(days=3)).isoformat()
    assert [(r.run, r.verdict) for r in q.runs] == [(inv_id, "answered")]
    assert I.run_verdict(inv_id)["verdict"] == "answered" and I.run_verdict(inv_id)["inquiry"] == q.key
    assert "pending_runs" not in q.extra


def test_a_run_with_nothing_open_closes_its_inquiry_as_answered_and_a_refuted_cause_is_contradicted():
    conn = _conn()
    inv_id = create_investigation("q", conn)
    I.open_inquiry(question="q", connection_id=conn, opened_by="person", run_id=inv_id, now=NOW)
    report = {"headline": "Revenue fell because of the price rise", "data_gaps": [],
              "causal_checks": {"refutation": {"status": "refuted", "reason": "a promotion overlapped"}}}
    complete_investigation(inv_id, report=report, hypotheses=[], query_history=[], question="q", connection_id=conn,
                           skip_index=True, cache=False)
    q = I.for_run(inv_id, conn_id=conn)
    assert q.state == "closed" and q.closed_as == "answered" and q.next_check == ""
    assert q.runs[-1].verdict == "contradicted" and "promotion overlapped" in q.runs[-1].why
    assert I.run_verdict(inv_id)["verdict"] == "contradicted"


def test_a_run_from_before_inquiries_still_lands_on_one():
    conn = _conn()
    inv_id = create_investigation("Why did margin slip?", conn)       # no inquiry opened for it
    complete_investigation(inv_id, report={"headline": "Margin slipped on discounts"}, hypotheses=[], query_history=[],
                           question="Why did margin slip?", connection_id=conn, skip_index=True, cache=False)
    q = I.for_run(inv_id, conn_id=conn)
    assert q is not None and q.opened_by == "person" and q.state == "closed"


# ── typed verdicts ─────────────────────────────────────────────────────────────────────────

def test_a_failure_is_classified_by_code_over_its_reason_and_the_inquiry_stays_open():
    conn = _conn()
    inv_id = create_investigation("q", conn)
    I.open_inquiry(question="q", connection_id=conn, opened_by="person", run_id=inv_id, now=NOW)
    fail_investigation(inv_id, status="failed", reason="Investigation could not complete: 3 of 3 queries failed "
                                                       "and no conclusive answer could be formed. Errors: syntax")
    q = I.for_run(inv_id, conn_id=conn)
    assert q.state == "open" and q.runs[-1].verdict == "tool_failed"
    assert I.run_verdict(inv_id)["verdict"] == "tool_failed" and "queries failed" in I.run_verdict(inv_id)["why"]
    # a run with no inquiry still books its verdict — never an empty result
    lone = create_investigation("q2", conn)
    fail_investigation(lone, status="timed_out", reason="timed out after 600s")
    assert I.run_verdict(lone)["verdict"] == "out_of_budget" and I.for_run(lone) is None


@pytest.mark.parametrize("status,reason,kind", [
    ("timed_out", "", "out_of_budget"),
    ("failed", "the run exceeded its cost cap", "out_of_budget"),
    ("failed", "withheld: clearance 2 is below the table's 3", "withheld"),
    ("failed", "no governed definition for 'margin'", "no_definition"),
    ("failed", "Investigation ended without producing a report. No conclusive evidence was gathered", "no_data"),
    ("failed", "the second reading contradicts the first", "contradicted"),
    ("failed", "KeyError: 'rows'", "tool_failed"),
    ("failed", "", "tool_failed"),
])
def test_classify_failure(status, reason, kind):
    assert I.classify_failure(status, reason) == kind


def test_verdict_tallies_count_every_run():
    conn = _conn()
    a, b = create_investigation("a", conn), create_investigation("b", conn)
    complete_investigation(a, report={"headline": "h"}, hypotheses=[], query_history=[], question="a", connection_id=conn,
                           skip_index=True, cache=False)
    fail_investigation(b, status="failed", reason="no rows came back")
    t = I.verdict_tallies(conn_id=conn)
    assert t["answered"] == 1 and t["no_data"] == 1 and sum(t.values()) == 2
    assert R.record_run_verdicts(connection_id=conn)["no_data"] == 1


# ── refuted hypotheses are memory ──────────────────────────────────────────────────────────

def test_the_next_run_reads_back_refuted_hypotheses_refuses_them_and_says_so():
    conn = _conn()
    first = create_investigation("Why did returns rise?", conn)
    I.open_inquiry(question="Why did returns rise?", connection_id=conn, opened_by="person", run_id=first, now=NOW)
    complete_investigation(first, report={"headline": "h"}, hypotheses=_hyps(), query_history=[],
                           question="Why did returns rise?", connection_id=conn, skip_index=True, cache=False)
    block, refuted = I.refuted_block(conn)
    assert len(refuted) == 1 and "late dispatch drove the returns" in block and "ALREADY REFUTED" in block
    assert "refuted because: returns rose equally" in block
    proposed = [Hypothesis(id="A", description="Late dispatch is driving the returns"),
                Hypothesis(id="B", description="A price change in the catalogue")]
    kept, refused = I.refuse_already_refuted(proposed, refuted)
    assert [h.id for h in kept] == ["B"] and refused[0]["refuted_by"] == refuted[0].id
    assert refused[0]["overlap"] >= I.SAME_HYPOTHESIS
    second = create_investigation("Why did returns rise again?", conn)
    I.open_inquiry(question="Why did returns rise again?", connection_id=conn, opened_by="person", run_id=second,
                   now=NOW + timedelta(days=30))
    I.record_refused(second, conn, refused)
    assert I.refused_for_run(second, conn)[0]["hypothesis"] == "Late dispatch is driving the returns"
    caveat = I.refused_caveat(I.refused_for_run(second, conn))
    assert caveat.startswith("Not re-tested: 1 hypothesis the Record holds as already refuted")
    # the deep analysis's own report says it when it reaches a refuted cause again
    from aughor.agent.investigate import _note_refuted_before
    report = {"headline": "Late dispatch drove the returns", "data_gaps": [], "causal_checks": {"claims": []}}
    matched = _note_refuted_before(report, conn)
    assert matched and report["causal_checks"]["refuted_before"][0]["refuted_by"] == refuted[0].id
    assert report["data_gaps"][0].startswith("Refuted before: an earlier run on this connection tested")
    assert _note_refuted_before({"headline": "Weather", "data_gaps": []}, conn) == []
    # a connection with nothing refuted plans exactly as before
    assert I.refuted_block(_conn()) == ("", [])


# ── waking ─────────────────────────────────────────────────────────────────────────────────

def test_the_heartbeat_wakes_a_waiting_inquiry_on_its_date_and_a_restated_claim_wakes_its_inquiry():
    conn = _conn()
    q = I.open_inquiry(question="q", connection_id=conn, opened_by="person", now=NOW)
    q.state, q.next_check, q.waiting_for = "waiting", "2026-01-01", "days to settle"
    q = I._book(q)
    assert any(x.key == q.key for x in I.due(NOW))
    woken = I.wake_due(NOW)
    assert any(x.key == q.key for x in woken)
    now_q = I.latest(q.key)
    assert now_q.state == "open" and now_q.next_check == "" and "2026-01-01" in now_q.woke[-1]["why"]
    assert not any(x.key == q.key for x in I.due(NOW))
    from aughor.automations.scheduler import wake_due_inquiries_hourly
    assert wake_due_inquiries_hourly(now=1e12, force=True) == 0        # nothing left due
    # a claim the inquiry established is restated → it wakes
    cid = C.book(C.Claim(kind="observation", tier="measured", about=C.About(kind="connection", key=conn),
                         statement=C.Statement(text="12"), warrants=[C.Warrant(kind="run", ref="r")]),
                 key=C.claim_key("obs", uuid.uuid4().hex[:6]))
    now_q.claims.append(cid)
    now_q.state = "waiting"
    I._book(now_q)
    woke = I.wake_for_claim(cid, why="restated")
    assert [x.key for x in woke] == [q.key] and I.latest(q.key).state == "open"


def test_a_person_closes_an_inquiry_with_lessons_through_the_door():
    conn = _conn()
    q = I.open_inquiry(question="q", connection_id=conn, opened_by="person", now=NOW)
    view = R.close_record_inquiry(q.id, R.CloseInquiryRequest(closed_as="overtaken",
                                                              lessons=[{"believed": "a courier change",
                                                                        "turned_out": "a packaging change"}]),
                                  principal=None)
    assert view["state"] == "closed" and view["closed_as"] == "overtaken" and view["lessons"][0]["turned_out"] == "a packaging change"
    assert view["extra"]["closed_by"] == "unidentified"
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        R.close_record_inquiry(q.id, R.CloseInquiryRequest(closed_as="done"), principal=None)
    assert any(x["id"] == view["id"] for x in R.list_record_inquiries(connection_id=conn, state="closed"))


# ── signals open inquiries ─────────────────────────────────────────────────────────────────

def test_a_fired_monitor_alert_opens_an_inquiry_without_spending_a_run():
    from aughor.monitors.models import Monitor, MonitorAlert
    from aughor.monitors.notify import dispatch_alert
    conn = _conn()
    monitor = Monitor(conn_id=conn, name="Refund rate", metric_name="refund_rate", notification_channel="in_app")
    alert = MonitorAlert(monitor_id=monitor.id, monitor_name=monitor.name, conn_id=conn, metric_name="refund_rate",
                         triggered_at=NOW.isoformat(), alert_on="above", severity="warning",
                         current_value=12.4, threshold=10.0, message="refund rate above its band")
    assert dispatch_alert(alert, monitor) is None                      # in-app: nothing to send
    opened = I.list_inquiries(conn_id=conn, subject="refund-rate")
    assert len(opened) == 1 and opened[0].opened_by == f"monitor:{monitor.id}" and opened[0].runs == []
    assert opened[0].question.startswith("Why did refund_rate")
    dispatch_alert(alert, monitor)                                      # the same signal again wakes, never doubles
    assert len(I.list_inquiries(conn_id=conn, subject="refund-rate")) == 1


# ── the skeptic's second binding ───────────────────────────────────────────────────────────

def test_the_skeptic_challenges_from_a_second_binding_where_the_install_has_two(monkeypatch):
    from aughor.agent import explore
    from aughor.agent.investigate import _refutation_record
    providers = {"coder": SimpleNamespace(model="qwen-coder"), "narrator": SimpleNamespace(model="llama-narrator")}
    monkeypatch.setattr(explore, "get_provider", lambda role="coder", **kw: providers[role])
    provider, binding = explore.skeptic_binding()
    assert provider is providers["narrator"] and binding == {"role": "narrator", "model": "llama-narrator", "second_binding": True}
    providers["narrator"] = SimpleNamespace(model="qwen-coder")        # one model for both roles
    provider, binding = explore.skeptic_binding()
    assert provider is providers["coder"] and binding["second_binding"] is False and "one model" in binding["why"]
    verdict = explore._RefutationVerdict(refuted=True, reason="a promotion overlapped", binding=binding)
    rec = _refutation_record(verdict)
    assert rec["status"] == "refuted" and rec["binding"]["second_binding"] is False
    assert _refutation_record(None)["status"] == "not_run"
