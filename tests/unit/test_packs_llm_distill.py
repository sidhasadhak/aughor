"""LLM flywheel distiller (Bet 1 enhancement, 2026-06-27).

Distils subtler pack learnings from a verified run's summary, behind the same is_compoundable
gate. Provider injected as a fake here. See aughor/packs/flywheel.py.
"""
from aughor.packs import llm_distill_deltas
from aughor.agent.state import VerificationManifest


def _verified():
    return VerificationManifest(checks=[], coverage=1.0, earned_confidence=0.9,
                                confidence_band="high", data_trust=1.0, signals=[])


def _unverified():
    return VerificationManifest(checks=[], coverage=0.5, earned_confidence=0.3,
                                confidence_band="low", data_trust=0.5, signals=[])


class FakeProvider:
    def __init__(self, deltas):
        self._deltas = deltas
        self.called = False

    def complete(self, system, user, response_model):
        self.called = True
        return response_model(deltas=self._deltas)


def test_llm_distil_returns_deltas_on_verified_run():
    fp = FakeProvider([
        {"kind": "caveat", "target": "orders.order_purchase_ts", "content": "nulls before 2022"},
        {"kind": "diagnostic", "target": "", "content": "always split retention by acquisition channel"},
        {"kind": "junk", "target": "", "content": "ignored — bad kind"},
        {"kind": "caveat", "target": "x", "content": ""},  # empty content dropped
    ])
    out = llm_distill_deltas("ca", _verified(), "chain summary text", provider=fp)
    assert fp.called
    kinds = sorted(d.kind for d in out)
    assert kinds == ["caveat", "diagnostic"]   # junk + empty dropped
    assert any(d.target == "orders.order_purchase_ts" for d in out)


def test_llm_distil_gated_off_for_unverified_run():
    fp = FakeProvider([{"kind": "caveat", "target": "t.c", "content": "x"}])
    out = llm_distill_deltas("ca", _unverified(), "summary", provider=fp)
    assert out == [] and fp.called is False    # never even calls the LLM on an unverified run


def test_llm_distil_empty_summary_is_safe():
    fp = FakeProvider([{"kind": "caveat", "target": "t.c", "content": "x"}])
    assert llm_distill_deltas("ca", _verified(), "  ", provider=fp) == []


def test_llm_distil_provider_error_safe():
    class Boom:
        def complete(self, **k):
            raise RuntimeError("llm down")
    assert llm_distill_deltas("ca", _verified(), "summary", provider=Boom()) == []
