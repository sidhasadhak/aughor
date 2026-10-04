"""PENDING (Hub): "a deep report does not record whether its cause-and-effect claims survived
their own checks". The deep run's one check that can refute a conclusion — the skeptic pass —
runs only on a HIGH-confidence verdict that changes a decision; when it SURVIVED nothing was
recorded, and a report the skeptic never saw read exactly like one it could not break. The
departure gate learned of a refutation by matching a sentence in the caveats.

Now the report carries `causal_checks` (licence · the causal sentences a reader sees · what
became of the check), an unchallenged cause is said among the caveats, and the gate reads the
typed record — saying, on a passed causal claim, whether it was ever challenged.
"""
from __future__ import annotations

from aughor.agent.investigate import _attach_causal_checks
from aughor.govern import departure

CAUSAL = "Revenue fell because the March price rise drove customers away."


def _report(**over):
    return {"headline": CAUSAL, "executive_summary": "Orders fell 12% after the change.",
            "closing_summary": "", "recommendations": [{"action": "Review the price rise."}],
            "data_gaps": ["March is still settling."], **over}


def test_an_unchallenged_cause_is_recorded_and_said():
    report = _report()
    _attach_causal_checks(report, "causal", {"status": "not_run", "why": "this verdict is MEDIUM"})
    checks = report["causal_checks"]
    assert checks["licence"] == "causal"
    assert checks["claims"] == [{"sentence": CAUSAL, "verb": "drove"}]
    assert checks["refutation"]["status"] == "not_run"
    assert report["data_gaps"][-1] == ("Not independently challenged: this report names a cause, and "
                                       "no check tried to refute it — this verdict is MEDIUM.")


def test_a_cause_that_survived_is_recorded_and_needs_no_caveat():
    report = _report()
    _attach_causal_checks(report, "causal", {"status": "survived", "reason": "no confounder found"})
    assert report["causal_checks"]["refutation"]["status"] == "survived"
    assert report["data_gaps"] == ["March is still settling."]


def test_a_descriptive_report_records_no_claim_and_says_nothing():
    report = _report(headline="Revenue was $1.2M in March.", recommendations=[])
    _attach_causal_checks(report, "descriptive", {"status": "not_run", "why": "x"})
    assert report["causal_checks"]["claims"] == []
    assert report["data_gaps"] == ["March is still settling."]


def test_the_gate_reads_the_typed_record(monkeypatch):
    stored: dict = {}
    monkeypatch.setattr("aughor.govern.departure_basis._analysis_record",
                        lambda inv: {"report": stored} if inv == "inv1" else {})

    stored.update(intake_notes="CLAIM LICENCE: causal — an intervention in the data.",
                  causal_checks={"licence": "causal", "claims": [],
                                 "refutation": {"status": "refuted", "reason": "a promo overlapped"}})
    held = departure._claims(CAUSAL, "inv1")              # no caveat sentence to match any more
    assert held.outcome == departure.HOLDS and "recorded a refutation" in held.summary

    stored["causal_checks"]["refutation"] = {"status": "not_run", "why": "MEDIUM"}
    passed = departure._claims(CAUSAL, "inv1")
    assert passed.outcome == departure.PASSED
    assert passed.summary.endswith("— the cause was never put to a refutation check")

    stored["causal_checks"]["refutation"] = {"status": "survived", "reason": "held"}
    assert departure._claims(CAUSAL, "inv1").summary.endswith(
        "— the cause survived the analysis's refutation check")
