"""Trust economy (Bet 4) + evals-as-spec gate (Bet 2) — 2026-06-27.

Trust tiers are earned from human verdicts (external signal). Activation requires evals to
pass + full binding. See aughor/packs/trust.py, evalgate.py.
"""
from aughor.packs.trust import autonomy_tier, routing_weight, tier_allows, SHADOW, ASSISTED, TRUSTED
from aughor.packs.evalgate import evaluate_activation, EvalResult
from aughor.packs.models import Pack, PackManifest, PackEval


# ── trust economy ─────────────────────────────────────────────────────────────

def test_insufficient_sample_is_shadow():
    assert autonomy_tier({"total": 2, "acceptance_rate": 1.0}) == SHADOW
    assert autonomy_tier({"total": 0, "acceptance_rate": None}) == SHADOW


def test_strong_record_earns_trusted():
    assert autonomy_tier({"total": 40, "acceptance_rate": 0.9}) == TRUSTED


def test_moderate_record_is_assisted():
    assert autonomy_tier({"total": 10, "acceptance_rate": 0.65}) == ASSISTED


def test_poor_record_stays_shadow():
    assert autonomy_tier({"total": 30, "acceptance_rate": 0.4}) == SHADOW


def test_routing_weight_rewards_and_penalises():
    assert routing_weight({"total": 50, "acceptance_rate": 0.9}) > 1.0
    assert routing_weight({"total": 50, "acceptance_rate": 0.4}) < 1.0
    assert routing_weight({"total": 1, "acceptance_rate": 1.0}) == 1.0   # no evidence → neutral


def test_tier_permissions():
    assert tier_allows(TRUSTED, "act")
    assert not tier_allows(ASSISTED, "act")
    assert tier_allows(ASSISTED, "route")
    assert not tier_allows(SHADOW, "route")
    assert tier_allows(SHADOW, "propose")


# ── evals-as-spec gate ────────────────────────────────────────────────────────

def _pack_with_evals(n=2):
    return Pack(manifest=PackManifest(id="p", name="P"),
                evals=[PackEval(question=f"q{i}") for i in range(n)])


def test_activation_blocked_until_evals_pass_and_deployed():
    pack = _pack_with_evals()
    results = [EvalResult("q0", True), EvalResult("q1", False)]
    d = evaluate_activation(pack, results, binding_pinned=True, binding_verified=True)
    assert not d.can_activate
    assert d.pass_rate == 0.5
    assert any("failing" in r for r in d.reasons)


def test_activation_allowed_when_all_pass_and_deployed():
    pack = _pack_with_evals()
    results = [EvalResult("q0", True), EvalResult("q1", True)]
    d = evaluate_activation(pack, results, binding_pinned=True, binding_verified=True)
    assert d.can_activate and d.pass_rate == 1.0 and d.reasons == []


def test_activation_blocked_when_not_deployed_even_if_evals_pass():
    # The exact confusing case: 100% pass but blocked because nothing is pinned.
    pack = _pack_with_evals()
    d = evaluate_activation(pack, [EvalResult("q0", True), EvalResult("q1", True)],
                            binding_pinned=False)
    assert not d.can_activate
    assert d.pass_rate == 1.0                                   # evals DID pass
    assert any("not deployed" in r for r in d.reasons)         # but it's not deployed


def test_activation_blocked_when_pinned_but_unverified():
    pack = _pack_with_evals()
    d = evaluate_activation(pack, [EvalResult("q0", True), EvalResult("q1", True)],
                            binding_pinned=True, binding_verified=False)
    assert not d.can_activate and any("not verified" in r for r in d.reasons)


def test_activation_blocked_when_pinned_missing_roles():
    pack = _pack_with_evals()
    d = evaluate_activation(pack, [EvalResult("q0", True), EvalResult("q1", True)],
                            binding_pinned=True, missing_roles=["cohort_anchor"])
    assert not d.can_activate and any("missing role" in r for r in d.reasons)


def test_activation_blocked_without_evals():
    pack = Pack(manifest=PackManifest(id="p", name="P"))
    d = evaluate_activation(pack, [], binding_pinned=True, binding_verified=True)
    assert not d.can_activate and any("no evals" in r for r in d.reasons)
