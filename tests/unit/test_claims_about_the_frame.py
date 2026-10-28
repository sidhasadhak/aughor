"""Arc OC-3 — a claim is about what its run's question was framed on, not the whole connection (ROADMAP §3.56).

Before: every one of the Record's 192 live claims was about a connection — an answer about late dispatch or completed
orders included — so a release that changed the dispatch promise could not tell which numbers it changed the meaning
of. Now a deep analysis whose question was framed books its observation and findings about
the frame's subject: the segment a promise or rule derives, or the entity a lag or a keyed metric starts from, with
the rule set the number was computed over and the metric. A frame that defines nothing leaves the claim as it was.
"""
from __future__ import annotations

import json
from types import SimpleNamespace as NS

import pytest

from aughor.ontology.framing import frame_about, frame_question
from aughor.ontology.models import OntologyGraph

THELOOK = "evals/ablation_thelook_business_ontology.json"
OLIST = "evals/ablation_olist_business_ontology.json"
REVENUE = NS(name="revenue", label="Revenue", entity="OrderItem", sql="SELECT SUM(sale_price) FROM order_items",
             approved_by="finance", entity_confirmed_by="ana")


def _graph(path: str) -> OntologyGraph:
    return OntologyGraph.model_validate(json.loads(open(path).read()))


def test_a_promise_frame_makes_a_claim_about_its_late_segment():
    about = frame_about(frame_question("What percentage of order lines broke the dispatch promise?", _graph(OLIST)))
    assert about["kind"] == "segment" and about["key"].startswith("late_")
    assert about["metric"].endswith("_breach_rate")


def test_a_rule_frame_makes_a_claim_about_the_rule():
    assert frame_about(frame_question("How many completed orders were placed in 2025?", _graph(THELOOK))) == \
        {"kind": "segment", "key": "completed_orders"}


def test_a_keyed_metric_over_a_rule_is_about_its_entity_computed_over_the_rule():
    frame = frame_question("What was revenue from completed orders in 2025?", _graph(THELOOK), metrics=[REVENUE])
    assert frame_about(frame) == {"kind": "type", "key": "OrderItem", "object_set": "completed_orders",
                                  "metric": "revenue"}


def test_a_frame_that_defines_nothing_leaves_the_claim_about_its_connection():
    assert frame_about(frame_question("How many users signed up last week?", _graph(THELOOK))) == {}
    assert frame_about(None) == {} and frame_about({}) == {}


# ── booked through the receipt writer ─────────────────────────────────────────────────────────

@pytest.fixture
def ledger(tmp_path, monkeypatch):
    from aughor.kernel.ledger import Ledger
    led = Ledger(str(tmp_path / "system.db"))
    monkeypatch.setattr(Ledger, "default", classmethod(lambda cls: led))
    return led


def _book(about: dict) -> str:
    from aughor.record.writers import book_from_receipt
    out = book_from_receipt(kind="chat_answer", natural_key="chat:c:inv1", receipt_id="rcpt-1", connection_id="c",
                            question="How many completed orders were placed in 2025?",
                            headline="31,204 completed orders were placed in 2025", sql="SELECT COUNT(*) FROM orders",
                            payload_extra={"about": about} if about else {})
    return out["observation"]


def test_the_claim_is_about_the_frames_subject(ledger, monkeypatch):
    from aughor.record.claims import get
    claim = get(_book({"kind": "segment", "key": "completed_orders"}))
    assert (claim.about.kind, claim.about.key, claim.statement.object_set) == ("segment", "completed_orders",
                                                                              "completed_orders")


def test_a_claim_about_a_segment_is_one_a_release_touches(ledger, monkeypatch):
    # The point of the subject: OC-2's restatement finds this claim when the rule that derives the segment changes.
    from aughor.ontology.release import _touches
    monkeypatch.setattr("aughor.cards.store.list_cards", lambda **k: [])
    cid = _book({"kind": "segment", "key": "completed_orders"})
    assert [c["id"] for c in _touches("c", {"completed_orders"}, [])["claims"]] == [cid]



def test_a_deep_report_s_claims_reach_the_run_s_inquiry():
    """The run lands on its inquiry at completion and its receipt — which books the claims — is written after, so the
    inquiry read none: 23 inquiries with runs on the live install held 0 claims (2026-10-26). The receipt writer now
    hands what it booked to the run's inquiry."""
    import uuid

    from aughor.kernel.ledger import DEEP_REPORT_KIND
    from aughor.record import inquiry as I
    from aughor.record.writers import book_from_receipt
    conn, run = "c-" + uuid.uuid4().hex[:6], "inv-" + uuid.uuid4().hex[:6]
    q = I.attach_run_result(run_id=run, connection_id=conn, question="Why did margin fall?",
                            report={"headline": "Margin fell on one shop", "data_gaps": []}, hypotheses=[])
    assert q.claims == []
    out = book_from_receipt(kind=DEEP_REPORT_KIND, natural_key=f"ada:{conn}:{run}", receipt_id="rcpt-" + run,
                            connection_id=conn, question="Why did margin fall?", headline="Margin fell on one shop",
                            sql="SELECT 1", payload_extra={"investigation_id": run})
    assert out["observation"]
    after = I.for_run(run, conn_id=conn)
    assert after.claims == [out["observation"]] and after.id != q.id
    # booked again (a re-run of the receipt), nothing is added twice and no version is written
    I.attach_run_claims(run, conn, [out["observation"]])
    assert I.for_run(run, conn_id=conn).id == after.id
