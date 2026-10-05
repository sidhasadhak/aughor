"""Phase 5 of the 2027 study, P5-4 — scenario method 4 fed from Outcome entries and nothing else
(`record/scenario.intervention`), the confirmed-cause graph grown from the install's own reviewed
decisions (`lifecycle/causal.promote_on_record_outcome`), and a procedure's success rate learned
from outcomes, not from use, said with its count (`playbook/outcomes.update_playbook_success_rates`).

What these hold: method 4 needs the kind of decision, projects nothing below three past cases and
says how many it has, and above the floor projects the mean measured effect with its band, the
count and how many went the wanted way; it is on the ladder's interface and a prediction under it
carries its method; the review's measured verdict confirms or weakens the investigation's proposed
causes and leaves them alone when it could not tell, and the outcome says what was written back;
a play's rate is counted from the Record's verdicts first, then from people's answers where the
Record has none, stored with n and its source, and the prompt says "held in 1 of 2 reviewed
outcomes", never a bare percentage.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from aughor.lifecycle import causal as CG
from aughor.playbook import outcomes as O
from aughor.record import claims as C
from aughor.record import decisions as D
from aughor.record import scenario as S


@pytest.fixture(autouse=True)
def _hermetic(tmp_path, monkeypatch):
    monkeypatch.setattr(O, "_DEFAULT_PATH", tmp_path / "recommendation_outcomes.json")
    monkeypatch.setenv("AUGHOR_CAUSAL_PROPOSALS_FILE", str(tmp_path / "causal_proposals.json"))
    monkeypatch.setenv("AUGHOR_CAUSAL_GRAPH_FILE", str(tmp_path / "causal_graph.json"))
    monkeypatch.setenv("AUGHOR_PLAYBOOK_PATH", str(tmp_path / "playbook.json"))
    import aughor.settling.store as settling
    monkeypatch.setattr(settling, "learned_lag_days", lambda conn_id: None)


def _conn():
    return "conn-" + uuid.uuid4().hex[:6]


def _reviewed(conn: str, *, question: str, action: str, effect: float, verdict: str, metric: str = "gross margin") -> str:
    did = D.book_decision(D.Decision(question=question, chosen="yes", decided_by="user:ana", connection_id=conn,
                                     actions=[action] if action else [],
                                     source=D.Source(kind="declared", ref=uuid.uuid4().hex[:8])),
                          expectation=D.Expectation(metric=metric, direction="up", low=1, high=3, unit="%"), author="user:ana")
    D.book_outcome(D.Outcome(of=did, measured_on="2026-11-01", actual=100 + effect, baseline=100.0,
                             effect=D.Effect(value=effect, low=effect - 2, high=effect + 2, method="history"),
                             verdict=verdict, why="measured", against_expectation="inside"))
    return did


# ── method 4 ───────────────────────────────────────────────────────────────────────────────

def test_method_4_needs_a_decision_kind_and_projects_nothing_below_three_cases_saying_how_many():
    conn = _conn()
    none = S.intervention(metric="gross margin", connection_id=conn)
    assert none.value is None and "needs the kind of decision" in none.note
    _reviewed(conn, question="pause the summer promotion?", action="pause_promo", effect=2.0, verdict="as_expected")
    one = S.intervention(metric="gross margin", connection_id=conn, action_id="pause_promo")
    assert one.value is None and one.backtest == {"n": 1} and "only 1 past decision" in one.note and "3 are the least" in one.note
    assert one.must_say == ["1 past case — too few to project from"]
    with pytest.raises(C.ClaimRefused, match="projected nothing"):
        S.predict(metric="gross margin", projection=one, settles_on="2026-12-01", author="system", connection_id=conn)


def test_method_4_reads_outcome_entries_and_nothing_else_and_says_its_count():
    conn = _conn()
    _reviewed(conn, question="pause the summer promotion?", action="pause_promo", effect=2.0, verdict="as_expected")
    _reviewed(conn, question="pause the autumn promotion?", action="pause_promo", effect=3.0, verdict="better")
    _reviewed(conn, question="pause the winter promotion?", action="pause_promo", effect=-1.0, verdict="worse")
    _reviewed(conn, question="raise the price on slow sellers?", action="change_price", effect=9.0, verdict="better")   # another kind
    _reviewed(conn, question="pause the spring promotion?", action="pause_promo", effect=5.0, verdict="better", metric="returns")  # another metric
    unreviewed = D.book_decision(D.Decision(question="pause the flash promotion?", chosen="yes", decided_by="user:ana",
                                            connection_id=conn, actions=["pause_promo"],
                                            source=D.Source(kind="declared", ref=uuid.uuid4().hex[:8])))
    cases = S.intervention_cases(metric="gross margin", connection_id=conn, action_id="pause_promo")
    assert len(cases) == 3 and {c["matched_on"] for c in cases} == {"action"} and unreviewed not in {c["decision"] for c in cases}
    p = S.intervention(metric="gross margin", connection_id=conn, action_id="pause_promo", unit="%")
    assert p.method == "intervention" and p.value == pytest.approx(4 / 3, abs=1e-6) and p.low < p.value < p.high
    assert p.coverage == 0.8 and p.backtest == {"n": 3, "held": 2, "worse": 1, "cannot_tell": 0}
    assert p.must_say[0].startswith("3 past decisions of this kind on this install, each measured against the metric's own history")
    assert p.must_say[1] == "2 of 3 went the wanted way; read from Outcome entries and nothing else"
    assert len(p.inputs["cases"]) == 3 and p.inputs["matched_on"] == ["action"]
    # by the question asked, when no declared action ran
    by_q = S.intervention(metric="gross margin", connection_id=conn, like="pause the promotion")
    assert by_q.backtest["n"] == 3 and by_q.inputs["matched_on"] == ["question"]
    # on the ladder's interface, and a prediction under it carries the method
    via = S.project("intervention", metric="gross margin", connection_id=conn, action_id="pause_promo")
    assert via.value == p.value
    with pytest.raises(ValueError, match="four built"):
        S.project("learned")
    pid = S.predict(metric="gross margin", projection=p, settles_on="2026-12-01", author="system", connection_id=conn, direction="up")
    pred = C.get(pid)
    assert pred.extra["method"] == "intervention" and pred.tier == "mined" and pred.extra["backtest"]["n"] == 3
    assert "(intervention)" in pred.statement.text


# ── the confirmed-cause graph grows from reviewed decisions ────────────────────────────────

def test_the_reviews_measured_verdict_confirms_or_weakens_the_proposed_causes():
    inv = "inv-" + uuid.uuid4().hex[:6]
    CG.save_proposals(inv, [CG.CausalProposal(from_signal="late dispatch", to_signal="refund rate", inv_id=inv, conn_id="c1")])
    assert CG.load_causal_graph("c1") == []
    told = CG.promote_on_record_outcome(inv, "cannot_tell")
    assert told == {"affected": 0, "did": "nothing: the review could not tell", "verdict": "cannot_tell"} and CG.load_causal_graph("c1") == []
    assert CG.promote_on_record_outcome(inv, "better")["did"] == "confirmed"
    edges = CG.load_causal_graph("c1")
    assert len(edges) == 1 and edges[0].weight == 1 and edges[0].confirmed_by == [inv]
    assert CG.promote_on_record_outcome(inv, "as_expected")["affected"] == 1 and CG.load_causal_graph("c1")[0].weight == 2
    assert CG.promote_on_record_outcome(inv, "worse")["did"] == "weakened" and CG.load_causal_graph("c1")[0].weight == 1
    CG.promote_on_record_outcome(inv, "worse")
    assert CG.load_causal_graph("c1") == []                   # at weight 0 the edge is gone
    assert CG.promote_on_record_outcome("inv-none", "better")["did"].startswith("nothing: no proposed causes")


def test_the_review_writes_back_to_the_graph_and_the_outcome_says_so():
    from aughor.record.byproducts import decision_from_recommendation, outcome_from_review
    conn, inv = _conn(), "inv-" + uuid.uuid4().hex[:6]
    CG.save_proposals(inv, [CG.CausalProposal(from_signal="a price rise", to_signal="total sales", inv_id=inv, conn_id=conn)])
    rec = O.RecOutcome(id=f"{inv}_rec_0", inv_id=inv, rec_index=0, rec_text="Roll back the price rise on basics",
                       status="accepted", metric_name="total sales", connection_id=conn, metric_before=100.0,
                       baseline_value=100.0, review_value=150.0, reviewed_at="2026-11-01T09:00:00+00:00",
                       review_window="2026-10-25 → 2026-10-31 (7 days)", history_value=100.0, history_low=90.0,
                       history_high=110.0, history_n=6, history_note="6 prior windows")
    decision_from_recommendation(rec, chosen="accept", decided_by="user:ana", connection_id=conn,
                                 expectation=D.Expectation(metric="total sales", direction="up", low=2, high=4, unit="%"))
    oid = outcome_from_review(rec)
    booked = D.outcome_by_id(oid)
    assert booked.verdict == "better"
    # the one outcome version the review books says what it wrote back — no restatement for bookkeeping
    assert booked.writes_back == ["prediction scored", "confirmed-cause graph: confirmed 1 edge"]
    assert D.latest_decision(D.Source(kind="recommendation", ref=rec.id)).outcome == oid
    assert CG.load_causal_graph(conn)[0].to_signal == "total sales"


# ── a procedure's success rate learned from outcomes, said with its count ──────────────────

def test_a_plays_rate_is_learned_from_the_records_verdicts_with_its_count_and_said_so():
    from aughor.playbook.models import PlaybookEntry
    from aughor.playbook.retriever import build_playbook_prompt_section
    from aughor.playbook.store import get_entry, save_entry
    from aughor.record.byproducts import decision_from_recommendation
    conn = _conn()
    play = PlaybookEntry(id="p-" + uuid.uuid4().hex[:6], trigger_metric="total_sales", trigger_condition="total sales down",
                         recommendation="Raise the free-shipping threshold", status="active")
    save_entry(play)
    assert "[no outcome data yet]" in build_playbook_prompt_section([play])
    assert O.update_playbook_success_rates() == 0
    recs = []
    for i, verdict in enumerate(["better", "worse"]):
        inv = "inv-" + uuid.uuid4().hex[:6]
        rec = O.log_outcome(inv_id=inv, rec_index=0, rec_text="Raise the free-shipping threshold", status="accepted",
                            metric_name="total sales")
        did = decision_from_recommendation(rec, chosen="accept", decided_by="user:ana", connection_id=conn)
        D.book_outcome(D.Outcome(of=did, measured_on="2026-11-01", actual=1.0, baseline=1.0,
                                 effect=D.Effect(value=1.0 if verdict == "better" else -1.0, method="history"), verdict=verdict, why="measured"))
        recs.append(rec)
    assert O.update_playbook_success_rates() == 1
    learned = get_entry(play.id)
    assert learned.outcome_n == 2 and learned.historical_success_rate == 0.5 and learned.rate_source == "record"
    assert learned.version == play.version                   # a rate is bookkeeping, not advice: no new version
    assert "[held in 1 of 2 reviewed outcomes]" in build_playbook_prompt_section([learned])
    assert "%" not in build_playbook_prompt_section([learned]).split("Raise the free-shipping")[1].split("]")[0]
    # a person's answer counts where the Record has not measured the record; a measured one is not double counted
    O.log_outcome(inv_id="inv-" + uuid.uuid4().hex[:6], rec_index=0, rec_text="Raise the free-shipping threshold", status="verified")
    O.log_outcome(inv_id=recs[1].inv_id, rec_index=0, rec_text="Raise the free-shipping threshold", status="verified")
    assert O.update_playbook_success_rates() == 1
    learned = get_entry(play.id)
    assert learned.outcome_n == 3 and learned.historical_success_rate == pytest.approx(2 / 3) and learned.rate_source == "record+answers"
    assert "[held in 2 of 3 reviewed outcomes]" in build_playbook_prompt_section([learned])
    assert datetime.now(timezone.utc).year >= 2026
