"""Routing + injection — making a pack steer the engine (2026-06-27).

select_pack picks the owning specialist by intent overlap (active packs only, above a floor);
build_injection assembles the steering payload with template tokens filled from the binding +
profile. See aughor/packs/routing.py, inject.py.
"""
from pathlib import Path

from aughor.packs import load_pack, select_pack, rank_packs, build_injection
from aughor.packs.models import Pack, PackManifest, PackQuestions

REPO = Path(__file__).resolve().parents[2]


def _pack(pid, status="active", tags=None, canonical=None, domains=None):
    return Pack(
        manifest=PackManifest(id=pid, name=pid, status=status, domains=domains or []),
        questions=PackQuestions(intent_tags=tags or [], canonical=canonical or []),
    )


def test_selects_pack_by_intent_overlap():
    retention = _pack("retention", tags=["retention", "cohort", "churn"])
    supply = _pack("supply", tags=["inventory", "stockout", "lead time"])
    hit = select_pack("why is churn rising for the latest cohort?", [retention, supply])
    assert hit is not None and hit[0].id == "retention"


def test_below_floor_returns_none_generalist():
    retention = _pack("retention", tags=["retention", "cohort"])
    assert select_pack("what is the weather today", [retention]) is None


def test_draft_packs_are_not_routed():
    draft = _pack("retention", status="draft", tags=["retention", "churn"])
    assert select_pack("churn and retention", [draft]) is None


def test_rank_packs_orders_by_score():
    a = _pack("a", tags=["retention", "churn", "cohort"])
    b = _pack("b", tags=["retention"])
    ranked = rank_packs("retention churn cohort analysis", [a, b])
    assert [p.id for p, _ in ranked][0] == "a"


def test_injection_fills_template_tokens_from_binding_and_profile():
    pack = load_pack(REPO / "packs" / "customer-analytics")
    binding = {
        "customer": {"table": "dim_customers", "column": "customer_id"},
        "event": {"table": "fct_orders", "column": "order_ts"},
        "cohort_anchor": {"table": "dim_customers", "column": "signup_ts"},
        "active_definition": {"value": "purchased_in_window"},
    }
    inj = build_injection(pack, binding=binding, business_model="transactional", currency_code="USD")
    # persona {{business_model}} resolved
    assert "{{business_model}}" not in inj.persona
    assert "transactional" in inj.persona
    # metric grain {{role.cohort_anchor}} resolved to the bound column
    grain = next(m["grain"] for m in inj.metrics if m["name"] == "Cohort Retention")
    assert "dim_customers.signup_ts" in grain
    assert inj.default_temporal_grain == "cohort"
    assert inj.diagnostics  # carried through


def test_injection_leaves_unknown_tokens_untouched():
    pack = Pack(manifest=PackManifest(id="x", name="x"), expertise="see {{role.ghost}} and {{nope}}")
    inj = build_injection(pack, binding={})
    assert "{{role.ghost}}" in inj.persona and "{{nope}}" in inj.persona
