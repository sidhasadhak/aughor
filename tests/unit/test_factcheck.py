"""Idea 7 · fact-check a document against the data.

Claims are the clauses that assert a measurement; each is compiled to grounded SQL over the
approved definition, measured, and matched at the precision it was written. The verdict
says why. The whole is an answer envelope filed as a turn.
"""
from __future__ import annotations

from aughor.factcheck import Measurement, claims_in, factcheck
from aughor.factcheck.check import CONTRADICTED, MEASURED, UNCHECKED, check_claim, claim_question

MEMO = (
    "Board memo, September 2026. Revenue in August 2026 was $4.2M across 3 regions, up 12% on "
    "July. We shipped 1,733 orders on 2026-09-01. The plan for 2027 is unchanged."
)


def _measure(value, sql="SELECT 1", note=""):
    return lambda question: Measurement(value=value, sql=sql, rows=1, note=note)


# ── the claims ───────────────────────────────────────────────────────────────────

def test_claims_are_the_clauses_that_assert_a_measurement():
    claims = claims_in(MEMO)
    said = [c.said for c in claims]
    # One clause, two numerals: the sentence is the claim, and both figures ride it.
    assert said == ["$4.2M, 12%", "1,733"]
    # a year, a date's parts, and "3 regions" are not claims a warehouse can confirm
    assert not any("2027" in s or "3" == s for s in said)
    assert claims[0].text.startswith("Revenue in August 2026 was $4.2M")


# ── one claim ────────────────────────────────────────────────────────────────────

def test_a_claim_the_data_confirms_is_measured_and_the_sql_rides_the_verdict():
    claim = claims_in("Revenue in August 2026 was $4.2M.")[0]
    asked: list[str] = []

    def measure(q):
        asked.append(q)
        return Measurement(value=4_190_000.0, sql="SELECT SUM(sale_price) …", rows=1)

    v = check_claim(claim, measure=measure)
    assert v.verdict == MEASURED and v.measured == 4_190_000.0
    assert v.why == "$4.2M is what the data shows (4,190,000.00)"
    assert v.sql == "SELECT SUM(sale_price) …"
    assert asked == [claim_question(claim.text)]
    assert asked[0].startswith('According to the data, what is the actual figure for this claim: "Revenue in August 2026 was $4.2M."?')


def test_a_claim_the_data_refutes_is_contradicted_and_says_how_far_off():
    claim = claims_in("Revenue in August 2026 was $4.2M.")[0]
    v = check_claim(claim, measure=_measure(3_000_000.0, note="excludes cancelled orders"))
    assert v.verdict == CONTRADICTED and v.measured == 3_000_000.0
    assert v.why == "said $4.2M; the data shows 3,000,000.00 (40% off) (caveat: excludes cancelled orders)"


def test_a_percentage_is_checked_against_a_ratio_too():
    claim = claims_in("The return rate was 12% in August.")[0]
    assert check_claim(claim, measure=_measure(0.12)).verdict == MEASURED
    off = check_claim(claim, measure=_measure(0.18))
    assert off.verdict == CONTRADICTED and "(33% off)" in off.why


def test_the_unchecked_verdicts_each_say_why():
    claim = claims_in("Revenue was $4.2M.")[0]
    table = check_claim(claim, measure=lambda q: Measurement(sql="SELECT …", rows=12))
    assert table.verdict == UNCHECKED and table.why == "the data answered with 12 rows, not one number"
    failed = check_claim(claim, measure=lambda q: Measurement(error="permission denied", sql="SELECT …"))
    assert failed.why == "the query failed: permission denied"
    empty = check_claim(claim, measure=lambda q: Measurement(sql="SELECT …", rows=0))
    assert empty.why == "the query returned no number"
    nothing = check_claim(claim, measure=lambda q: Measurement(note="I could not find a revenue table"))
    assert nothing.why == "the platform could not turn the claim into a query — I could not find a revenue table"
    blown = check_claim(claim, measure=lambda q: (_ for _ in ()).throw(RuntimeError("model down")))
    assert blown.verdict == UNCHECKED and blown.why == "the check failed: model down"


# ── the document ─────────────────────────────────────────────────────────────────

def test_the_document_becomes_an_envelope_and_is_filed_as_a_turn():
    from aughor.db.history import get_investigation

    memo = MEMO + " The return rate was 9% in August."

    def measure(question):
        if "1,733" in question:
            return Measurement(note="no shipments table")
        if "return rate" in question:
            return Measurement(value=0.09, sql="SELECT rr", rows=1)
        return Measurement(value=3_000_000.0, sql="SELECT rev", rows=1)

    env = factcheck(memo, "c-memo", measure=measure)
    assert env.headline == "3 numeric claims: 1 match the data, 1 contradicted, 1 could not be checked."
    assert env.grid is not None and env.grid.columns == ["claim", "said", "measured", "verdict", "why"]
    assert [r[3] for r in env.grid.rows] == [CONTRADICTED, UNCHECKED, MEASURED]
    assert env.body.startswith('- CONTRADICTED — "Revenue in August 2026 was $4.2M across 3 regions, up 12% on July.": '
                               'said $4.2M; the data shows 3,000,000.00 (40% off)')
    assert env.caveats[0].startswith("A contradicted claim is measured with the approved definition")
    assert env.caveats[1] == "1 claim could not be checked — each row says why; an approved definition makes a metric checkable."
    assert env.provenance.mode == "factcheck" and env.provenance.connection_id == "c-memo"
    assert len(env.provenance.sql) == 2
    assert env.question.startswith("fact-check (text): Board memo")
    row = get_investigation(env.provenance.investigation_id)
    assert row is not None and row["kind"] == "chat"
    assert row["report"]["envelope"]["headline"] == env.headline


def test_a_long_memo_is_capped_and_the_cap_is_named():
    memo = " ".join(f"Line {i} revenue was ${i + 1},000." for i in range(30))
    env = factcheck(memo, "c-cap", measure=lambda q: Measurement(), cap=5)
    assert env.headline.startswith("5 numeric claims")
    assert "further claims beyond the cap of 5 were not checked" in env.body


def test_no_claims_is_an_honest_envelope():
    env = factcheck("We opened 3 stores in 2026.", "c-none", measure=lambda q: Measurement())
    assert env.headline == "No numeric claims to check: nothing in the text states a measurement."
    assert env.grid is None and env.caveats == []


def test_the_door_checks_pasted_text(monkeypatch):
    from fastapi.testclient import TestClient

    from aughor.api import app

    monkeypatch.setattr("aughor.factcheck.check.default_measurer",
                        lambda cid, schema=None, session_id="": _measure(4_190_000.0))
    client = TestClient(app)
    r = client.post("/factcheck", json={"text": "Revenue in August 2026 was $4.2M.", "connection_id": "c-door"})
    assert r.status_code == 200
    body = r.json()
    assert body["envelope"]["headline"] == "1 numeric claim: 1 match the data, 0 contradicted, 0 could not be checked."
    assert body["investigation_id"] == body["envelope"]["provenance"]["investigation_id"]
    assert client.post("/factcheck", json={"text": "   ", "connection_id": "c-door"}).status_code == 400
