"""The doors the Record's pages write through (the 2027 study §V, screens 4 to 7 and 9).

What these hold: a person's hypothesis is a named claim at tier ``said`` and a refuted one like it
is said beside it, never a refusal; an inquiry is handed to a person and nothing else; a check date
makes it wait and clearing one wakes it; a claim marked wrong is RESTATED — the wrong version kept —
as the person's corrected statement, a hypothesis as refuted, a prediction refused; a restatement
wakes the inquiries that established the claim and reopens the decisions that stood on it, again
when what replaced it is itself replaced; an option or a dissent added after booking is dated and
named and what was chosen does not move; an edited mission keeps the day of its next report; a
past report is read by its id and only under its own mission; and when no sign-in names the
caller, the name a form carries is kept as ``person:`` — never as an authenticated ``user:``.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from aughor.record import claims as C
from aughor.record import decisions as D
from aughor.record import inquiry as I
from aughor.record import mission as M
from aughor.record import receipt_lines as RL
from aughor.routers import record as R

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _own_stores(tmp_path, monkeypatch):
    import aughor.settling.store as settling
    monkeypatch.setattr(settling, "learned_lag_days", lambda conn_id: 3)
    monkeypatch.setenv("AUGHOR_DEPARTURES_DB", str(tmp_path / "departures.db"))


def _conn():
    return "conn-" + uuid.uuid4().hex[:6]


def _observation(conn: str, text: str = "APAC revenue was 2.53M last week", inv: str = "") -> str:
    inv = inv or "inv-" + uuid.uuid4().hex[:6]
    claim = C.Claim(kind="observation", tier="measured", about=C.About(kind="connection", key=conn),
                    statement=C.Statement(text=text, metric="revenue", value=2.53, unit="M"), as_of="2026-10-01",
                    warrants=[C.Warrant(kind="run", ref="receipt-1", detail="SELECT 1")],
                    author="analyst", author_kind="agent", extra={"investigation_id": inv})
    return C.book(claim, key=C.claim_key("observation", "answer", conn, inv), conn_id=conn)


def _decision(conn: str, relied_on: list[str]) -> str:
    return R.declare_record_decision(R.DeclareDecisionRequest(
        question="Extend the APAC renewal credit?", chosen="Extend it", options=["End it"],
        relied_on=relied_on, connection_id=conn, decided_by="user:ana"), principal=None)["id"]


# ── who is acting ──────────────────────────────────────────────────────────────────────────

def test_a_typed_name_is_a_person_and_never_reads_as_a_signed_in_user():
    class P:
        user_id = "ana@example.com"
    assert R._actor(P(), "someone else") == "user:ana@example.com"     # a sign-in always wins
    assert R._actor(None, "ana") == "person:ana"
    assert R._actor(None, "user:ana") == "user:ana"                    # a full principal is kept as typed
    assert R._actor(None, "  ") == ""


# ── the inquiry's page ─────────────────────────────────────────────────────────────────────

def test_a_persons_hypothesis_is_a_named_claim_and_a_refuted_one_like_it_is_said_beside_it():
    conn = _conn()
    q = I.open_inquiry(question="Why did returns rise?", connection_id=conn, opened_by="person:ana", run_id="r1", now=NOW)
    with pytest.raises(I.InquiryRefused, match="say who holds it"):
        I.add_hypothesis(q, text="a courier change", by="unidentified", now=NOW)
    with pytest.raises(I.InquiryRefused, match="say who holds it"):
        I.add_hypothesis(q, text="a courier change", by="agent:analyst", now=NOW)
    booked, note = I.add_hypothesis(q, text="a courier change in the north", by="person:bo", now=NOW)
    assert note == {} and booked.version == q.version + 1 and len(booked.hypotheses) == 1
    claim = C.get(booked.hypotheses[0])
    assert (claim.kind, claim.tier, claim.state, claim.author, claim.author_kind) == ("hypothesis", "said", "open", "person:bo", "person")
    assert booked.extra["proposed_run"]["could_change"]["open_hypotheses"][0]["claim"] == claim.id
    # the Record already holds one like it as refuted on this connection: said, and still booked
    refuted = C.Claim(kind="hypothesis", tier="said", about=C.About(kind="connection", key=conn), state="refuted",
                      statement=C.Statement(text="late dispatch drove the returns"), as_of="2026-10-01",
                      author="inquirer", author_kind="agent", extra={"evidence": "equal for on-time and late"})
    rid = C.book(refuted, key=C.claim_key("hypothesis", conn, "old"), conn_id=conn)
    again, note = I.add_hypothesis(booked, text="late dispatch drove the returns", by="person:bo")
    assert note["refuted_by"] == rid and len(again.hypotheses) == 2
    assert C.get(again.hypotheses[1]).extra["resembles_refuted"] == rid
    closed = I.close_inquiry(again, closed_as="answered", by="person:bo")
    with pytest.raises(I.InquiryRefused, match="closed"):
        I.add_hypothesis(closed, text="weather", by="person:bo")
    # the door: the form's name is the author when no sign-in is bound, and a missing one is a 422
    q2 = I.open_inquiry(question="Why did margin slip?", connection_id=conn, opened_by="person:ana", run_id="r2", now=NOW)
    view = R.add_record_inquiry_hypothesis(q2.id, R.HypothesisRequest(text="a discount stacked", by="cy"), principal=None)
    assert view["hypothesis_claims"][0]["author"] == "person:cy" and view["resembles_refuted"] is None
    with pytest.raises(HTTPException) as exc:
        R.add_record_inquiry_hypothesis(q2.id, R.HypothesisRequest(text="a discount stacked"), principal=None)
    assert exc.value.status_code == 422 and "say who holds it" in exc.value.detail


def test_an_inquiry_is_handed_to_a_person_and_the_hand_off_is_on_the_record():
    conn = _conn()
    q = I.open_inquiry(question="Why did churn rise?", connection_id=conn, opened_by="monitor:m1", now=NOW)
    with pytest.raises(I.InquiryRefused, match="handed to a person"):
        I.hand_to(q, owner="agent:explorer", by="person:ana")
    handed = I.hand_to(q, owner="person:bo", by="person:ana", now=NOW)
    assert handed.extra["owner"] == "person:bo" and handed.extra["handed"][-1] == {
        "at": NOW.isoformat(), "by": "person:ana", "from": "", "to": "person:bo"}
    assert I.hand_to(handed, owner="person:bo").version == handed.version          # the same owner writes nothing
    off = R.hand_record_inquiry(q.id, R.HandToRequest(owner="", by="ana"), principal=None)   # an old id lands on the latest
    assert off["extra"]["owner"] == "" and off["extra"]["handed"][-1]["from"] == "person:bo"


def test_a_check_date_makes_an_inquiry_wait_and_clearing_it_wakes_it():
    conn = _conn()
    q = I.open_inquiry(question="Did the price change hold?", connection_id=conn, opened_by="person:ana", run_id="r1", now=NOW)
    with pytest.raises(I.InquiryRefused, match="today or later"):
        I.set_next_check(q, on=(NOW - timedelta(days=1)).date().isoformat(), now=NOW)
    with pytest.raises(I.InquiryRefused, match="YYYY-MM-DD"):
        I.set_next_check(q, on="next tuesday", now=NOW)
    on = (NOW + timedelta(days=9)).date().isoformat()
    waiting = I.set_next_check(q, on=on, by="person:ana", waiting_for="the October cohort to settle", now=NOW)
    assert (waiting.state, waiting.next_check, waiting.waiting_for) == ("waiting", on, "the October cohort to settle")
    due = [x.id for x in I.due(NOW + timedelta(days=9)) if x.connection_id == conn]
    assert due == [waiting.id]                                              # the heartbeat finds it on its day
    cleared = I.set_next_check(waiting, on="", by="person:ana", now=NOW)
    assert cleared.state == "open" and cleared.next_check == "" and "was cleared by person:ana" in cleared.woke[-1]["why"]
    assert I.set_next_check(cleared, on="", now=NOW).version == cleared.version     # nothing to clear writes nothing


# ── a claim marked wrong ───────────────────────────────────────────────────────────────────

def test_a_claim_marked_wrong_is_restated_as_the_persons_statement_and_the_wrong_version_is_kept():
    conn = _conn()
    cid = _observation(conn)
    for who in ("", "unidentified", "agent:analyst"):
        with pytest.raises(C.ClaimRefused, match="say who"):
            C.mark_wrong(cid, by=who, corrected="APAC revenue was 2.72M last week")
    with pytest.raises(C.ClaimRefused, match="corrected statement"):
        C.mark_wrong(cid, by="person:ana", why="late rows")
    with pytest.raises(C.ClaimRefused, match="already held"):
        C.mark_wrong(cid, by="person:ana", corrected="APAC revenue was 2.53M last week")
    out = C.mark_wrong(cid, by="person:ana", corrected="APAC revenue was 2.72M last week", why="two late invoices")
    new = C.get(out["claim_id"])
    assert out["superseded"] == cid and new.version == 2 and new.supersedes == cid
    assert (new.tier, new.author, new.author_kind, new.statement.metric) == ("declared", "person:ana", "person", "revenue")
    assert new.statement.value is None                                 # a person's sentence carries no measured figure
    assert [(w.kind, w.ref) for w in new.warrants] == [("attestation", "person:ana"), ("claim", cid)]
    assert C.get(cid).statement.text == "APAC revenue was 2.53M last week" and C.get(cid).superseded_by == new.id
    # an earlier version's id lands on the current one
    assert C.mark_wrong(cid, by="person:bo", corrected="APAC revenue was 2.70M last week")["superseded"] == new.id
    from aughor.record.corrections import restatements
    assert [(r["believed"], r["replaced_by"]) for r in restatements(conn_id=conn)] == [
        ("APAC revenue was 2.72M last week", "APAC revenue was 2.70M last week")]


def test_a_hypothesis_marked_wrong_is_refuted_with_the_persons_reason_and_a_prediction_is_refused():
    conn = _conn()
    q = I.open_inquiry(question="Why did returns rise?", connection_id=conn, opened_by="person:ana", run_id="r1", now=NOW)
    booked, _ = I.add_hypothesis(q, text="a courier change", by="person:bo", now=NOW)
    hid = booked.hypotheses[0]
    with pytest.raises(C.ClaimRefused, match="says why"):
        C.mark_wrong(hid, by="person:ana")
    out = C.mark_wrong(hid, by="person:ana", why="the courier changed a month after the rise")
    refuted = C.get(out["claim_id"])
    assert refuted.state == "refuted" and refuted.statement.text == "a courier change" and refuted.tier == "said"
    assert refuted.extra["evidence"] == "the courier changed a month after the rise" and refuted.warrants[-1].kind == "attestation"
    with pytest.raises(C.ClaimRefused, match="already held as refuted"):
        C.mark_wrong(hid, by="person:ana", why="again")
    # the inquiry cites the hypothesis as it was recorded; its page reads it as it stands now, once
    assert [(h["id"], h["state"]) for h in R.get_record_inquiry(booked.id)["hypothesis_claims"]] == [(refuted.id, "refuted")]
    # and the run it proposed while the hypothesis was open no longer names it as open
    assert booked.extra["proposed_run"]["could_change"]["open_hypotheses"] != []
    assert I.latest(booked.key).extra["proposed_run"]["could_change"]["open_hypotheses"] == []
    from aughor.record.corrections import refuted_hypotheses
    assert refuted_hypotheses(conn_id=conn)[0]["why"] == "marked wrong by a person"
    prediction = C.Claim(kind="prediction", tier="mined", about=C.About(kind="connection", key=conn), state="open",
                         statement=C.Statement(text="expected: revenue up", metric="revenue"), as_of="2026-10-01")
    pid = C.book(prediction, key=C.claim_key("prediction", conn, "p1"), conn_id=conn)
    with pytest.raises(C.ClaimRefused, match="scored when its day comes"):
        C.mark_wrong(pid, by="person:ana", corrected="revenue fell")


def test_a_restatement_wakes_the_inquiry_and_reopens_the_decision_and_again_when_its_replacement_moves():
    conn = _conn()
    cid = _observation(conn)
    q = I.open_inquiry(question="Why did APAC revenue fall?", connection_id=conn, opened_by="person:ana", run_id="r1", now=NOW)
    q.claims, q.state, q.next_check = [cid], "waiting", "2026-12-01"
    q = I._book(q)
    did = _decision(conn, [cid])
    other = _decision(conn, [])                                         # stands on nothing: never reopened
    out = R.mark_record_claim_wrong(cid, R.MarkWrongRequest(corrected="APAC revenue was 2.72M last week", by="ana"), principal=None)
    assert out["superseded"] == cid and out["tier"] == "declared" and out["author"] == "person:ana"
    assert len(out["woke_inquiries"]) == 1 and len(out["reopened_decisions"]) == 1
    woke = I.latest(q.key)
    assert woke.state == "open" and woke.woke[-1]["why"] == f"claim {cid} it established was marked wrong by person:ana"
    held = R.get_record_inquiry(woke.id)["established_claims"]
    assert [(c["id"], c["cited_as"], c["restated_since"]) for c in held] == [(out["id"], cid, True)]
    view = R.get_record_decision(did)                                  # the old id reads the old version…
    assert view["reopened_by"] == "" and view["superseded_by"] == out["reopened_decisions"][0]
    reopened = R.get_record_decision(out["reopened_decisions"][0])     # …and the new one names what replaced its ground
    assert reopened["reopened_by"] == out["id"] and reopened["reopened_by_claim"]["statement"]["text"].endswith("2.72M last week")
    assert reopened["extra"]["reopened"][-1]["why"] == "a claim it relied on was marked wrong by person:ana"
    assert reopened["relied_on_claims"][0]["superseded_by"] == out["id"]      # cited as recorded then, and marked as replaced
    # the corrected claim still names the decision that stood on the version it corrected
    assert R.get_record_claim(out["id"])["relied_on_by"] == [reopened["id"]] == R.get_record_claim(cid)["relied_on_by"]
    assert R.get_record_decision(other)["superseded_by"] == ""
    # a person answers: it stands, and why — the reopening stays in its history
    with pytest.raises(HTTPException) as exc:
        R.settle_record_decision_reopening(reopened["id"], R.StandsRequest(why=" "), principal=None)
    assert exc.value.status_code == 422
    stands = R.settle_record_decision_reopening(reopened["id"], R.StandsRequest(why="2.72M still clears the bar", by="ana"), principal=None)
    assert stands["reopened_by"] == "" and stands["extra"]["reopened"][-1]["settled_by"] == "person:ana"
    with pytest.raises(HTTPException):
        R.settle_record_decision_reopening(stands["id"], R.StandsRequest(why="again"), principal=None)
    # what replaced the claim is itself replaced: the decision stood on that too, so it reopens again
    again = C.mark_wrong(out["id"], by="person:bo", corrected="APAC revenue was 2.40M last week")
    assert len(again["reopened_decisions"]) == 1
    assert D.get_decision(again["reopened_decisions"][0]).reopened_by == again["claim_id"]


# ── a decision amended ─────────────────────────────────────────────────────────────────────

def test_an_option_or_a_dissent_added_later_is_dated_and_named_and_the_choice_does_not_move():
    conn = _conn()
    did = _decision(conn, [])
    with pytest.raises(ValueError, match="adds an option or a dissent"):
        D.amend_decision(did)
    with pytest.raises(ValueError, match="who disagreed and why"):
        D.amend_decision(did, dissent_who="user:bo")
    with pytest.raises(ValueError, match="already on the decision"):
        D.amend_decision(did, option="end it")
    amended = R.amend_record_decision(did, R.AmendDecisionRequest(
        option="Extend it for enterprise only", dissent=R.DissentIn(who="user:bo", why="it pays customers who would renew anyway"),
        by="ana"), principal=None)
    assert amended["chosen"] == "Extend it" and amended["version"] == 2
    assert [o["description"] for o in amended["options"]] == ["End it", "Extend it", "Extend it for enterprise only"]
    assert amended["dissent"] == [{"who": "user:bo", "why": "it pays customers who would renew anyway"}]
    assert [(a["kind"], a["by"]) for a in amended["extra"]["amendments"]] == [("option", "person:ana"), ("dissent", "person:ana")]
    assert len(D.get_decision(did).options) == 2                       # the version booked at the time stands
    again = R.amend_record_decision(did, R.AmendDecisionRequest(option="Pause it for a quarter"), principal=None)
    assert len(again["options"]) == 4 and again["extra"]["amendments"][-1]["by"] == "unidentified"
    # a scenario booked for the decision as it stood is still its own under every later version
    booked = R.book_record_scenario(did, R.ScenarioRequest(method="identity", metric="credit cost", formula="a * b",
                                                           inputs={"a": 31, "b": 1290}), principal=None)
    later = R.amend_record_decision(did, R.AmendDecisionRequest(option="Credit annual plans only"), principal=None)
    for vid in (did, again["id"], later["id"]):
        assert [s["id"] for s in R.list_record_scenarios(vid)["scenarios"]] == [booked["scenario"]["id"]]


# ── a mission edited, and a past report read ───────────────────────────────────────────────

def test_an_edited_mission_keeps_the_day_of_its_next_report_and_a_past_report_is_read_under_its_own_mission():
    conn = _conn()
    body = dict(name="Protect margin " + uuid.uuid4().hex[:4], objective=R.ObjectiveIn(metric="gross margin", direction="up"),
                connections=[conn], owner="user:ana", state="active", cadence="monthly")
    with pytest.raises(HTTPException) as exc:                           # nobody signed in and nobody named
        R.write_record_mission(R.MissionRequest(**body), principal=None)
    assert exc.value.status_code == 422 and "people write missions" in exc.value.detail
    first = R.write_record_mission(R.MissionRequest(**body, written_by="ana"), principal=None)
    assert first["written_by"] == "person:ana" and first["version"] == 1
    m = M.get_mission(first["id"])
    m.review.next_report_on, m.extra["last_report_headline"] = "2026-11-20", "ahead"
    kept = M._book(m)
    edited = R.write_record_mission(R.MissionRequest(**{**body, "key": kept.key, "budget": R.BudgetIn(interruptions_per_week=5)},
                                                     written_by="ana"), principal=None)
    assert edited["version"] == kept.version + 1 and edited["budget"]["interruptions_per_week"] == 5
    assert edited["review"]["next_report_on"] == "2026-11-20" and edited["extra"]["last_report_headline"] == "ahead"
    faster = R.write_record_mission(R.MissionRequest(**{**body, "key": kept.key, "cadence": "weekly"}, written_by="ana"), principal=None)
    assert faster["review"]["next_report_on"] != "2026-11-20"           # a new cadence sets a new day
    # a report is read by its id, in full, and only under the mission that wrote it
    current = M.latest(kept.key)
    rid, _ = M.book_report(current, {"period": {"from": "2026-09-01", "to": "2026-09-30"}, "headline": "held",
                                     "objective": {"verdict": "on_track"}})
    got = R.get_record_mission_past_report(first["id"], rid)
    assert got["booked"] is True and got["report"]["headline"] == "held" and got["report"]["id"] == rid
    stranger = R.write_record_mission(R.MissionRequest(**{**body, "name": "Another " + uuid.uuid4().hex[:4]}, written_by="ana"), principal=None)
    with pytest.raises(HTTPException) as exc:
        R.get_record_mission_past_report(stranger["id"], rid)
    assert exc.value.status_code == 404


# ── scenarios from the page ────────────────────────────────────────────────────────────────

def test_history_resolves_the_metrics_definition_and_a_method_that_projects_nothing_is_refused_with_its_reason(monkeypatch):
    conn = _conn()
    did = _decision(conn, [])
    monkeypatch.setattr(R, "_metric_spec", lambda metric, connection_id: None)
    with pytest.raises(HTTPException) as exc:
        R.book_record_scenario(did, R.ScenarioRequest(method="history", metric="renewals"), principal=None)
    assert exc.value.status_code == 422 and "no approved definition" in exc.value.detail
    with pytest.raises(HTTPException) as exc:                           # no past decision like it has a measured outcome
        R.book_record_scenario(did, R.ScenarioRequest(method="intervention", metric="renewals"), principal=None)
    assert exc.value.status_code == 422 and "only 0 past decisions of this kind" in exc.value.detail
    cases = R.list_record_decision_cases(did, metric="renewals")
    assert cases == {"cases": [], "needed": 3, "measurable": False}
    # three past decisions that asked the same question, each with a measured effect: method 4 projects
    for effect in (4.0, 6.0, 5.0):
        past = _decision(conn, [])
        D.book_outcome(D.Outcome(of=past, measured_on="2026-09-01", effect=D.Effect(value=effect, method="history"),
                                 verdict="as_expected", measured_by="user:ana"))
    assert len(R.list_record_decision_cases(did, metric="")["cases"]) == 3
    out = R.book_record_scenario(did, R.ScenarioRequest(method="intervention", metric="renewals"), principal=None)
    assert out["projection"]["value"] == 5.0 and out["projection"]["backtest"]["n"] == 3
    assert out["prediction"]["extra"]["method"] == "intervention" and out["scenario"]["methods"] == ["intervention"]


# ── who else was told ──────────────────────────────────────────────────────────────────────

def test_a_claims_page_reads_who_was_told_from_the_answer_behind_it_and_says_when_there_is_none(monkeypatch):
    conn = _conn()
    cid = _observation(conn, inv="inv-told")
    monkeypatch.setattr(RL, "_told", lambda inv: [{"at": "2026-10-02", "state": "departed", "addressed_to": "user:bo",
                                                    "departure_id": "d1"}] if inv == "inv-told" else [])
    told, note = RL.told_about(C.get(cid))
    assert [t["departure_id"] for t in told] == ["d1"] and note == ""
    quiet, note = RL.told_about(C.get(_observation(conn, text="EMEA revenue was 1.1M", inv="inv-quiet")))
    assert quiet == [] and "has passed the departure gate" in note
    declared = C.Claim(kind="definition", tier="declared", about=C.About(kind="connection", key=conn),
                       statement=C.Statement(text="an active customer ordered in the last 90 days"),
                       author="user:ana", author_kind="person")
    did = C.book(declared, key=C.claim_key("definition", conn, "active"), conn_id=conn)
    nobody, note = RL.told_about(C.get(did))
    assert nobody == [] and "did not come from an answer" in note
    assert R.get_record_claim(cid)["told"][0]["addressed_to"] == "user:bo"


# ── set aside: "not now" on what waits on a person ─────────────────────────────────────────

def test_setting_an_item_aside_hides_it_until_its_day_and_writes_nothing_on_the_item():
    from aughor.record import set_aside as SA
    conn = _conn()
    did = _decision(conn, [])
    before = D.get_decision(did)
    for bad, why in (({"item_kind": "mission"}, "wait on a person here"), ({"why": " "}, "says why"),
                     ({"until": "soon"}, "YYYY-MM-DD"), ({"until": NOW.date().isoformat()}, "a later day"),
                     ({"ref": "no-such-decision"}, "no such decision")):
        args = {"item_kind": "decision", "ref": did, "until": "2026-10-15", "why": "waiting for finance close", **bad}
        with pytest.raises(SA.SetAsideRefused, match=why):
            SA.set_aside(**args, now=NOW)
    s = SA.set_aside(item_kind="decision", ref=did, until="2026-10-15", why="waiting for finance close", by="person:amit",
                     title='What became of "Extend it"?', now=NOW)
    assert (s.status, s.ref, s.seen, s.connection_id) == ("active", before.key, did, conn)
    after = D.get_decision(did)                                        # the decision itself: not a word written
    assert (after.version, after.superseded_by, after.outcome, after.extra) == (before.version, "", "", before.extra)
    mine = lambda out, part: [x for x in out[part] if x["ref"] == before.key]      # noqa: E731
    assert [x["why"] for x in mine(SA.listing(now=NOW), "active")] == ["waiting for finance close"]
    # the day comes: it is back, and the listing says why
    on_the_day = SA.listing(now=NOW + timedelta(days=10))
    assert mine(on_the_day, "active") == [] and mine(on_the_day, "returned")[0]["back_because"] == "its day came (2026-10-15)"
    # long after, it is no longer listed as returned
    assert mine(SA.listing(now=NOW + timedelta(days=60)), "returned") == []
    # restored before its day: gone from both lists, kept in its history
    SA.restore(item_kind="decision", ref=before.key, by="person:amit", now=NOW)
    assert mine(SA.listing(now=NOW), "active") == [] and mine(SA.listing(now=NOW), "returned") == []
    with pytest.raises(SA.SetAsideRefused):
        SA.restore(item_kind="decision", ref=before.key, now=NOW)
    # set aside again by any version's id: the same item, a new version of the same set-aside
    again = SA.set_aside(item_kind="decision", ref=did, until="2026-10-20", why="still waiting", now=NOW)
    assert again.version == 3 and again.ref == before.key and again.restored_at == ""


def test_a_set_aside_item_returns_early_when_the_record_behind_it_changes():
    from aughor.record import set_aside as SA
    conn = _conn()
    cid = _observation(conn)
    did = _decision(conn, [cid])
    key = D.get_decision(did).key
    q = I.open_inquiry(question="Why did APAC revenue fall?", connection_id=conn, opened_by="person:ana", run_id="r1", now=NOW)
    q.claims, q.state, q.next_check = [cid], "waiting", "2026-12-01"
    q = I._book(q)
    SA.set_aside(item_kind="decision", ref=did, until="2026-10-15", why="waiting for finance close", now=NOW)
    SA.set_aside(item_kind="inquiry", ref=q.id, until="2026-10-15", why="not this week", now=NOW)
    find = lambda part, ref: next((x for x in SA.listing(now=NOW)[part] if x["ref"] == ref), None)      # noqa: E731
    assert find("active", key)["status"] == "active" and find("active", q.key)["status"] == "active"
    # the claim both stood on is corrected: the decision reopens, the inquiry wakes — both are back early
    C.mark_wrong(cid, by="person:bo", corrected="APAC revenue was 2.72M last week")
    assert find("active", key) is None and find("returned", key)["back_because"] == "a claim it relied on was restated"
    assert find("active", q.key) is None and "marked wrong by person:bo" in find("returned", q.key)["back_because"]
    # a departure and a proposed action have one id for life: they return on their day and not before
    held = R.set_record_item_aside(R.SetAsideRequest(kind="departure", ref="dep-1", until="2099-01-01", why="next sprint", by="amit"),
                                   principal=None)
    assert (held["status"], held["ref"], held["by"], held["seen"]) == ("active", "dep-1", "person:amit", "")
    assert any(x["ref"] == "dep-1" for x in R.list_record_set_aside()["active"])
    back = R.restore_record_item(R.RestoreRequest(kind="departure", ref="dep-1", by="amit"), principal=None)
    assert back["restored_by"] == "person:amit" and not any(x["ref"] == "dep-1" for x in R.list_record_set_aside()["active"])
    with pytest.raises(HTTPException) as exc:
        R.set_record_item_aside(R.SetAsideRequest(kind="decision", ref=did, until="2020-01-01", why="x"), principal=None)
    assert exc.value.status_code == 422
