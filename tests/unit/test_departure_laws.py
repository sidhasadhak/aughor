"""HB-2 remainder — the departure gate's laws beyond the ratchet's labeled corpus: the pieces
each law is built from (precision-aware grounding, sentence claims, SLA parsing), the
receipt that travels (law 8), the owner's answer remembered (law 6), the ledger growing in
place, and the doors that serve it.

The ratchet (`test_departure_gate_ratchet.py`) locks WHAT each law decides; this file locks
how the decision is carried, recorded and answered.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from aughor.govern import departure_store as ds
from aughor.govern.departure import (
    HELD_OWNER,
    Measurement,
    departure_link,
    earliest,
    gate_departure,
    line_holds,
    parse_moment,
    receipt_line,
    sla_hours,
)


@pytest.fixture(autouse=True)
def _own_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_DEPARTURES_DB", str(tmp_path / "departures.db"))
    monkeypatch.delenv("AUGHOR_WEB_URL", raising=False)


@pytest.fixture()
def client():
    from aughor.api import app
    return TestClient(app)


def _gate(text, **kw):
    base = dict(kind="slack_post", org_id="default", conn_id="", text=text,
                automation_id=kw.pop("automation_id", "laws"), automation_name="Laws",
                target="#ops")
    base.update(kw)
    return gate_departure(**base)


_READINGS = {
    "subject": "definition of refund rate", "metric_label": "refund rate",
    "metric_name": "refund_rate", "question": "“refund rate” can be computed two ways",
    "options": ["Governed: refund_rate", "As I read the question"],
    "previews": ["= 2.10%", "= 7.80%"],
    "readings": [{"label": "Governed: refund_rate", "sql": "SUM(refunds) / COUNT(*)"},
                 {"label": "As I read the question", "sql": "SUM(refund_value) / SUM(value)"}]}


# ── the pieces ────────────────────────────────────────────────────────────────────

def test_a_number_written_in_full_claims_its_last_significant_digit():
    from aughor.explorer.grounding import extract_numerals, numeral_matches_measure as m

    def n(tok):
        return extract_numerals(tok)[0]
    assert not m(n("99,441"), 101033.0)          # the finding guard's 2% would accept this
    assert m(n("99,441"), 99441.0)
    assert m(n("4,100"), 4097.0) and not m(n("4,100"), 4151.0)   # "4,100" means ±50
    assert m(n("22,128.43"), 22128.4321) and not m(n("22,128.43"), 22128.5)
    assert m(n("9.35%"), 9.3517)
    assert m(n("2.5M"), 2_490_000.0)             # abbreviated: rounding by construction


def test_sentence_claims_reads_the_strongest_claim_and_never_a_negation():
    from aughor.agent.claim_type import sentence_claims
    found = {t for _s, t, _v in sentence_claims(
        "Revenue rose 4%. The campaign drove it. Churn is correlated with tenure. "
        "Orders are on track to double. Delays were not caused by the carrier.")}
    assert found == {"causal", "associational", "predictive"}
    assert sentence_claims("Delays were not caused by the carrier.") == []


def test_an_sla_is_read_as_a_duration_or_not_at_all():
    assert sla_hours("24h") == 24 and sla_hours("within 2 days") == 48
    assert sla_hours("daily by 6am UTC") == 24 and sla_hours("30 minutes") == 0.5
    assert sla_hours("when finance signs off") is None


def test_a_bare_date_means_the_end_of_that_day():
    moment = parse_moment("2026-09-16")
    assert (moment.hour, moment.minute) == (23, 59)
    assert parse_moment("2018-09-11 19:48:28").tzinfo is not None
    assert earliest(["2026-09-16", "2018-09-11 19:48:28", "nonsense"]) == "2018-09-11 19:48:28"


# ── law 8 — the receipt travels ───────────────────────────────────────────────────

def test_the_receipt_names_source_definition_as_of_guards_and_row(monkeypatch):
    stamp = Measurement(source="promise dispatch of order_to_delivery",
                        values=[111456.0, 10423.0], rates=[0.093517],
                        measured_at=datetime.now(timezone.utc).isoformat(),
                        as_of="2018-09-11 19:48:28")
    monkeypatch.setattr("aughor.govern.departure_basis.declared_thing",
                        lambda s, c: {"kind": "promise", "measured": True,
                                      "label": "promise dispatch of order_to_delivery"})
    v = _gate("Dispatch broke on 10,423 of 111,456 order lines (9.35%).", conn_id="c1",
              about="promise:order_to_delivery.dispatch", measurement=stamp)
    assert v.state == "departed", v.reason_sentence()
    line = v.receipt_line()
    assert line.startswith("Receipt: promise dispatch of order_to_delivery")
    assert "defined by promise dispatch of order_to_delivery (declared, measured)" in line
    assert "as of 2018-09-11" in line and "re-measure" in line
    assert f"departure {v.record_id}" in line
    row = ds.get_departure(v.record_id)
    assert json.loads(row["receipt"])["departure_id"] == v.record_id
    assert json.loads(row["guards"])["remeasure"] == "passed"
    assert row["about"] == "promise:order_to_delivery.dispatch"


def test_the_receipt_links_to_the_departures_screen_only_when_the_origin_is_known(monkeypatch):
    assert departure_link("abc123") == ""
    monkeypatch.setenv("AUGHOR_WEB_URL", "https://aughor.example.test/")
    link = departure_link("abc123")
    assert link == ("https://aughor.example.test/?tab=agentic-ops&layer=departures"
                    "&departure=abc123")
    assert receipt_line({"source": "x", "departure_id": "abc123", "link": link,
                         "guards": {}}).endswith(link)


def test_held_lines_are_recorded_and_counted_on_the_receipt():
    v = _gate("Weekly summary.", kind="briefing", dated_records=True,
              held_lines=["“discount → refunds”: a causal relationship departs only on a "
                          "falsifier's verdict"])
    assert v.state == "departed"
    assert "2 lines held at departure" not in v.receipt_line()     # the count, not the prose
    assert "1 line held at departure" in v.receipt_line()
    assert "causal" in json.loads(ds.get_departure(v.record_id)["checks"])["held_lines"]


# ── law 6 — the owner is asked, once ─────────────────────────────────────────────

def test_divergent_readings_hold_for_the_owner_with_the_question_recorded(monkeypatch):
    monkeypatch.setattr("aughor.govern.departure_basis.owner_for_disagreement",
                        lambda d, c: "group:finance")
    v = _gate("", conn_id="c1", disagreement=_READINGS)
    assert v.state == HELD_OWNER and v.addressed_to == "group:finance"
    assert "group:finance is asked" in v.reason_sentence()
    row = ds.get_departure(v.record_id)
    assert row["addressed_to"] == "group:finance"
    assert json.loads(row["question"])["readings"][1]["sql"] == "SUM(refund_value) / SUM(value)"


def test_an_accuracy_hold_still_asks_the_owner(monkeypatch):
    monkeypatch.setattr("aughor.govern.departure_basis.owner_for_disagreement",
                        lambda d, c: "group:finance")
    v = _gate("Reminder: 1,200 refunds are pending.", conn_id="c1", disagreement=_READINGS)
    assert v.state == "held" and v.addressed_to == "group:finance"


def test_the_answer_is_remembered_in_the_ambiguity_ledger(client, monkeypatch):
    monkeypatch.setattr("aughor.govern.departure_basis.owner_for_disagreement",
                        lambda d, c: "")
    v = _gate("", conn_id="conn-law6", disagreement=_READINGS)
    assert v.state == HELD_OWNER
    assert "no owner is routable" in v.reason_sentence()

    bad = client.post(f"/departures/{v.record_id}/answer", json={"reading": "neither"})
    assert bad.status_code == 422 and "not one of the readings" in bad.json()["detail"]
    assert client.post("/departures/nope/answer", json={"reading": "x"}).status_code == 404

    resp = client.post(f"/departures/{v.record_id}/answer",
                       json={"reading": "As I read the question"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["departure"]["answer"] == "As I read the question"
    assert body["resolution_id"]
    from aughor.semantic.ambiguity_ledger import list_resolutions
    remembered = [r for r in list_resolutions("conn-law6")
                  if r.subject == "definition of refund rate"]
    assert remembered and remembered[0].resolved_reading == "As I read the question"
    assert remembered[0].resolved_sql == "SUM(refund_value) / SUM(value)"
    assert remembered[0].resolution_source == "user"


def test_a_departure_that_asked_nothing_cannot_be_answered(client):
    v = _gate("All quiet.")
    resp = client.post(f"/departures/{v.record_id}/answer", json={"reading": "x"})
    assert resp.status_code == 422 and "asked no question" in resp.json()["detail"]


# ── lines of an assembled message ─────────────────────────────────────────────────

def test_a_line_is_judged_on_its_own(monkeypatch):
    monkeypatch.setattr("aughor.semantic.metrics.list_metrics", lambda **_: [])
    assert line_holds("Orders rose 4% this week.", conn_id="c1") == []
    assert line_holds("Conversion rate was 3.4% yesterday.", conn_id="c1")
    assert line_holds("Conversion rate [critical]: 3.4% vs 5%", conn_id="c1", declared=True) == []
    assert line_holds("The promotion drove repeat orders.", conn_id="c1")
    assert line_holds("Orders will double next quarter.", conn_id="c1")


# ── the ledger grows in place, and its doors serve it decoded ─────────────────────

_PRE_REMAINDER_DDL = """
CREATE TABLE departures (
    id TEXT PRIMARY KEY, ts TEXT NOT NULL DEFAULT '', org_id TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT '', state TEXT NOT NULL DEFAULT '',
    conn_id TEXT NOT NULL DEFAULT '', automation_id TEXT NOT NULL DEFAULT '',
    automation_name TEXT NOT NULL DEFAULT '', actor TEXT NOT NULL DEFAULT '',
    target TEXT NOT NULL DEFAULT '', addressed_to TEXT NOT NULL DEFAULT '',
    reasons TEXT NOT NULL DEFAULT '[]', checks TEXT NOT NULL DEFAULT '{}',
    text_preview TEXT NOT NULL DEFAULT '', investigation_id TEXT NOT NULL DEFAULT '',
    verdict TEXT NOT NULL DEFAULT '', verdict_note TEXT NOT NULL DEFAULT '',
    verdict_at TEXT NOT NULL DEFAULT '');
INSERT INTO departures (id, ts, kind, state, automation_id, reasons, checks)
VALUES ('old1', '2026-09-16T20:09:53Z', 'slack_post', 'departed', 'watch', '[]',
        '{"trust": "clean"}');
"""


def test_a_ledger_written_before_the_remainder_opens_with_its_rows_intact(tmp_path, monkeypatch):
    path = tmp_path / "old-departures.db"
    conn = sqlite3.connect(path)
    conn.executescript(_PRE_REMAINDER_DDL)
    conn.close()
    monkeypatch.setenv("AUGHOR_DEPARTURES_DB", str(path))

    old = ds.get_departure("old1")
    assert old["state"] == "departed" and old["question"] == "{}" and old["guards"] == "{}"
    v = _gate("All quiet.", automation_id="after-upgrade")
    assert ds.get_departure(v.record_id)["guards"] != "{}"


def test_the_doors_serve_rows_decoded_and_count_what_is_owed(client, monkeypatch):
    monkeypatch.setattr("aughor.govern.departure_basis.owner_for_disagreement",
                        lambda d, c: "")
    departed = _gate("Nothing to report.", automation_id="doors")
    asked = _gate("", conn_id="c1", automation_id="doors", disagreement=_READINGS)
    probation = _gate("All quiet.", automation_id="doors-prob", probation=True,
                      declared_by="user:ana")

    rows = client.get("/departures", params={"automation_id": "doors"}).json()["departures"]
    by_id = {r["id"]: r for r in rows}
    assert isinstance(by_id[departed.record_id]["checks"], dict)
    assert isinstance(by_id[departed.record_id]["reasons"], list)
    assert by_id[asked.record_id]["question"]["metric_label"] == "refund rate"

    owed = {r["id"] for r in client.get("/departures", params={"awaiting": True}).json()["departures"]}
    assert owed == {asked.record_id, probation.record_id}

    summary = client.get("/departures/summary").json()
    assert summary["awaiting"] == 2
    assert summary["by_state"]["departed"] == 1 and summary["by_state"]["held_owner"] == 1

    one = client.get(f"/departures/{probation.record_id}").json()
    assert one["guards"]["probation"] == "held" and one["addressed_to"] == "user:ana"


def test_a_repeat_is_judged_only_against_what_actually_departed():
    """A held first send was never heard; the same message later is not a repeat of it."""
    first = _gate("Nightly load finished.", automation_id="rep", probation=True,
                  declared_by="user:ana")
    assert first.state == "held_probation"
    second = _gate("Nightly load finished.", automation_id="rep")
    assert second.state == "departed"
    third = _gate("Nightly load finished.", automation_id="rep")
    assert third.state == "held" and "already departed" in third.reason_sentence()
    fourth = _gate("Nightly load finished.", automation_id="rep", target="#elsewhere")
    assert fourth.state == "departed"


def test_a_measurement_older_than_the_window_is_re_executed_first():
    calls: list = []

    def again(claims):
        calls.append([n.text for n in claims])
        return ([4100.0], [])

    stale = Measurement(source="analysis 1", values=[4100.0],
                        measured_at=(datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
                        remeasure=again)
    v = _gate("Orders reached 4,100 this week.", measurement=stale)
    assert v.state == "departed" and calls == [["4,100"]]
    assert "re-executed at departure" in v.checks["remeasure"]


def test_a_code_rendered_alert_is_grounded_by_construction():
    """"1440m" is a window in minutes — read as a numeral it is 1.44 billion. An alert's
    template prints exactly the values it measured, so nothing is matched token by token."""
    alert = Measurement(source="alert rule 'errors'", values=[0.25, 0.2, 40.0],
                        measured_at=datetime.now(timezone.utc).isoformat(), rendered=True)
    v = _gate("errors [warning]: error_rate=0.25 crosses >= 0.2 over 40 run(s) in 1440m",
              kind="agent_alert", measurement=alert,
              declared_definition="alert rule 'errors' (declared)")
    assert v.state == "departed", v.reason_sentence()
    assert "grounded by construction" in v.checks["remeasure"]


# ── A4: a measurement's caveat travels with the number it measured ───────────────────────────

_IMPOSSIBLE = ("counted as kept although impossible: 4,199 of the 50,048 Return objects reached refunded "
               "BEFORE received_at, so their lag is negative and none of them can break the promise — "
               "without them the rate is 25.41%, not 23.27%")


def test_a_promises_caveat_rides_the_receipt_rather_than_stopping_at_the_record(monkeypatch):
    """The LuxExperience shape. Every other surface already showed a promise's flags — the panel
    in red, the object door as query caveats, the frame as notes — and the one that dropped them
    was the one that leaves the building. A number departing at 23.27% when 4,199 of its 50,048
    objects were refunded BEFORE they arrived is the defect this carries."""
    stamp = Measurement(source="promise refund of Return to refund",
                        values=[50048.0, 11648.0], rates=[0.232737],
                        measured_at=datetime.now(timezone.utc).isoformat(),
                        as_of="2025-08-14", caveats=[_IMPOSSIBLE])
    monkeypatch.setattr("aughor.govern.departure_basis.declared_thing",
                        lambda s, c: {"kind": "promise", "measured": True,
                                      "label": "promise refund of Return to refund"})
    v = _gate("The refund promise broke on 11,648 of 50,048 returns (23.27%).", conn_id="c1",
              about="promise:return_to_refund.refund", measurement=stamp)
    assert v.state == "departed", v.reason_sentence()

    line = v.receipt_line()
    assert "caveat: counted as kept although impossible" in line
    assert "25.41%, not 23.27%" in line, "the alternative rate is the actionable half"
    assert line.index("caveat:") < line.index("checked:"), \
        "a caveat after a list of green ticks reads as a footnote to reassurance"

    row = ds.get_departure(v.record_id)
    assert json.loads(row["receipt"])["caveats"] == [_IMPOSSIBLE]


def test_a_caveat_qualifies_a_number_and_never_holds_it(monkeypatch):
    """Deliberate, and the user's call to change: a gate that blocked on every caveat would
    teach senders to stop writing them. The flag is information, not a refutation."""
    stamp = Measurement(source="promise refund of Return to refund",
                        values=[50048.0, 11648.0], rates=[0.232737],
                        measured_at=datetime.now(timezone.utc).isoformat(),
                        as_of="2025-08-14", caveats=[_IMPOSSIBLE, "never broken: none of them"])
    monkeypatch.setattr("aughor.govern.departure_basis.declared_thing",
                        lambda s, c: {"kind": "promise", "measured": True,
                                      "label": "promise refund of Return to refund"})
    v = _gate("The refund promise broke on 11,648 of 50,048 returns (23.27%).", conn_id="c1",
              about="promise:return_to_refund.refund", measurement=stamp)
    assert v.state == "departed"
    assert v.guards["definition"] == "passed" and v.guards["remeasure"] == "passed"
    assert v.receipt_line().count("caveat: ") == 2, "every caveat travels, not just the first"


def test_a_measurement_with_no_caveat_leaves_the_receipt_exactly_as_it_was(monkeypatch):
    """The no-op half: a clean promise must not grow an empty 'caveat:' fragment."""
    stamp = Measurement(source="promise dispatch of order_to_delivery",
                        values=[111456.0, 10423.0], rates=[0.093517],
                        measured_at=datetime.now(timezone.utc).isoformat(),
                        as_of="2018-09-11 19:48:28")
    monkeypatch.setattr("aughor.govern.departure_basis.declared_thing",
                        lambda s, c: {"kind": "promise", "measured": True,
                                      "label": "promise dispatch of order_to_delivery"})
    v = _gate("Dispatch broke on 10,423 of 111,456 order lines (9.35%).", conn_id="c1",
              about="promise:order_to_delivery.dispatch", measurement=stamp)
    assert v.state == "departed"
    assert "caveat" not in v.receipt_line()
    assert json.loads(ds.get_departure(v.record_id)["receipt"])["caveats"] == []
