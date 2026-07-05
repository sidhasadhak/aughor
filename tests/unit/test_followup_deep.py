"""Follow-up composition on the DEEP path (/investigate + /ask→deep).

The quick /chat path already composes a follow-up on the prior turn (see
test_followup.py). This covers the parity fix for the deep/direct path: a follow-up
question anchors the run on the previous query via an origin_finding built from
history, and route_question no longer wipes that seed for the direct/explore branches.
"""
from __future__ import annotations

from types import SimpleNamespace

from aughor.routers.investigations import _followup_origin, InvestigateRequest


# ── _followup_origin — the base a follow-up composes on ──────────────────────────

_PRIOR = {
    "question": "How much GMV per brand tier?",
    "sql": "SELECT brand_tier, SUM(quantity*unit_price_eur) AS gmv FROM luxexperience.order_items GROUP BY brand_tier",
    "columns": ["brand_tier", "gmv"],
    "headline": "Luxury leads net GMV at 16.8M",
    "key_rows": [["luxury", 16800000], ["ultra", 16200000]],
}


def test_followup_origin_anchors_on_prior_query():
    o = _followup_origin([_PRIOR])
    assert o is not None
    assert "compose on the previous query" in o["finding"].lower()
    assert _PRIOR["question"] in o["finding"]           # the base question is named
    assert o["sql"] == _PRIOR["sql"]                    # the base query is carried
    assert "luxexperience.order_items" in o["tables"]   # tables parsed from the base SQL
    assert "luxury" in o["result_cells"]                # the result digest rides along
    assert o["narrative"] == _PRIOR["headline"]


def test_followup_origin_accepts_object_shape():
    o = _followup_origin([SimpleNamespace(**_PRIOR)])
    assert o is not None and o["sql"] == _PRIOR["sql"]


def test_followup_origin_uses_the_most_recent_turn():
    older = {**_PRIOR, "sql": "SELECT 1", "question": "older"}
    o = _followup_origin([older, _PRIOR])
    assert o["sql"] == _PRIOR["sql"]  # last turn wins


def test_followup_origin_none_without_a_usable_base():
    assert _followup_origin([]) is None
    assert _followup_origin([{"question": "x", "sql": ""}]) is None
    assert _followup_origin([{"question": "x"}]) is None


# ── route_question preserves the seed for the direct branch ──────────────────────

def test_route_question_preserves_prior_analyses_seed_on_direct(monkeypatch):
    import aughor.agent.nodes as nodes
    from aughor.agent.state import RouteDecision

    monkeypatch.setattr(nodes, "classify_question",
                        lambda q: ("direct", RouteDecision(mode="direct", confidence=0.9, reasoning="test")))
    state = {"question": "just the ultra tier", "connection_id": "c",
             "prior_analyses": ["FOLLOW-UP base: prior query + result"]}
    out = nodes.route_question(state)
    assert out["query_mode"] == "direct"
    # the seed the deep path injected must survive into the direct branch (was wiped to [])
    assert out["prior_analyses"] == ["FOLLOW-UP base: prior query + result"]


# ── the endpoint accepts history (wire parity with /chat + /ask) ─────────────────

def test_investigate_request_accepts_history():
    req = InvestigateRequest(question="follow up", connection_id="c",
                             history=[{"question": "q", "sql": "SELECT 1", "columns": [], "headline": "", "key_rows": []}])
    assert len(req.history) == 1 and req.history[0].sql == "SELECT 1"
