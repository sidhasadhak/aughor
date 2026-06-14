"""Cascade-aware hypothesis scoring — the routing wiring, proven deterministically.

Mocks the proxy/oracle providers so the real score_evidence_cascade logic is exercised
without an LLM: disabled → oracle only; enabled → clear-cut verdicts accept the cheap
proxy (no oracle call), the ambiguous middle escalates, and any proxy failure falls back
to the oracle.
"""
import aughor.agent.hypothesis_cascade as hc
from aughor.agent.state import EvidenceScore
from aughor.llm.cascade import default_thresholds


def _score(conf: float, verdict: str = "confirmed") -> EvidenceScore:
    return EvidenceScore(
        hypothesis_id="h1", confidence=conf, verdict=verdict, key_finding="k", should_continue=False
    )


class _Stub:
    def __init__(self, score: EvidenceScore | None = None, exc: Exception | None = None):
        self.calls = 0
        self._score = score
        self._exc = exc

    def complete(self, system, user, response_model):
        self.calls += 1
        if self._exc:
            raise self._exc
        return self._score


def _wire(monkeypatch, proxy: _Stub, oracle: _Stub, *, enabled: bool):
    monkeypatch.setenv("AUGHOR_CASCADE_HYPOTHESIS", "1" if enabled else "0")
    monkeypatch.setattr(hc, "get_proxy_provider", lambda: proxy)
    monkeypatch.setattr(hc, "get_provider", lambda role="coder": oracle)
    monkeypatch.setattr(hc, "load_thresholds", lambda: default_thresholds(0.85, 0.15))


def test_disabled_uses_oracle_only(monkeypatch):
    proxy, oracle = _Stub(_score(0.95)), _Stub(_score(0.70))
    _wire(monkeypatch, proxy, oracle, enabled=False)
    score, by = hc.score_evidence_cascade("s", "u")
    assert by == "oracle" and score.confidence == 0.70
    assert proxy.calls == 0 and oracle.calls == 1


def test_clearcut_confirmed_accepts_proxy(monkeypatch):
    proxy, oracle = _Stub(_score(0.95, "confirmed")), _Stub(_score(0.70))
    _wire(monkeypatch, proxy, oracle, enabled=True)
    score, by = hc.score_evidence_cascade("s", "u")
    assert by == "proxy" and score.confidence == 0.95   # >= tau_pos → accept, no oracle
    assert proxy.calls == 1 and oracle.calls == 0


def test_clearcut_refuted_accepts_proxy(monkeypatch):
    proxy, oracle = _Stub(_score(0.05, "refuted")), _Stub(_score(0.70))
    _wire(monkeypatch, proxy, oracle, enabled=True)
    score, by = hc.score_evidence_cascade("s", "u")
    assert by == "proxy" and score.confidence == 0.05   # <= tau_neg → accept, no oracle
    assert oracle.calls == 0


def test_ambiguous_escalates_to_oracle(monkeypatch):
    proxy, oracle = _Stub(_score(0.50, "inconclusive")), _Stub(_score(0.80, "confirmed"))
    _wire(monkeypatch, proxy, oracle, enabled=True)
    score, by = hc.score_evidence_cascade("s", "u")
    assert by == "oracle" and score.confidence == 0.80   # middle band → oracle decides
    assert proxy.calls == 1 and oracle.calls == 1


def test_proxy_failure_falls_back_to_oracle(monkeypatch):
    proxy, oracle = _Stub(exc=RuntimeError("proxy down")), _Stub(_score(0.70))
    _wire(monkeypatch, proxy, oracle, enabled=True)
    score, by = hc.score_evidence_cascade("s", "u")
    assert by == "oracle" and score.confidence == 0.70
    assert oracle.calls == 1
