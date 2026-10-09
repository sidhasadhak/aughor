"""Arc OC-3 — a claim is about what its run's question was framed on, not the whole connection (ROADMAP §3.56).

Before: every one of the Record's 192 live claims was about a connection — an answer about late dispatch or completed
orders included — so a release that changed the dispatch promise could not tell which numbers it changed the meaning
of. While `ontology.release` is on, a deep analysis whose question was framed books its observation and findings about
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


def test_on_the_claim_is_about_the_frames_subject(ledger, monkeypatch):
    from aughor.record.claims import get
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda name: name == "ontology.release")
    claim = get(_book({"kind": "segment", "key": "completed_orders"}))
    assert (claim.about.kind, claim.about.key, claim.statement.object_set) == ("segment", "completed_orders",
                                                                              "completed_orders")


def test_off_the_claim_is_about_its_connection_as_before(ledger, monkeypatch):
    from aughor.record.claims import get
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda name: False)
    claim = get(_book({"kind": "segment", "key": "completed_orders"}))
    assert (claim.about.kind, claim.about.key, claim.statement.object_set) == ("connection", "c", "")


def test_a_claim_about_a_segment_is_one_a_release_touches(ledger, monkeypatch):
    # The point of the subject: OC-2's restatement finds this claim when the rule that derives the segment changes.
    from aughor.ontology.release import _touches
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda name: name == "ontology.release")
    monkeypatch.setattr("aughor.dashboard.store.list_cards", lambda **k: [])
    cid = _book({"kind": "segment", "key": "completed_orders"})
    assert [c["id"] for c in _touches("c", {"completed_orders"}, [])["claims"]] == [cid]
