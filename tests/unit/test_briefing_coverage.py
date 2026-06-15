"""The briefing's full-coverage digest — the hierarchical tree-reduce over ALL findings.

When more findings exist than the cited top-8, ``_coverage_digest`` folds every finding into a
per-domain digest (partition-aware) so the narrator sees the whole picture. The LLM is faked; these
assert the drop-detection, per-domain isolation, fail-open, and the prompt wiring.
"""
from __future__ import annotations

import pytest

import aughor.llm.provider as prov
from aughor.knowledge.briefing import (
    BriefingCitation,
    BriefingNarrative,
    _build_user_prompt,
    _coverage_digest,
    _Digest,
    generate_narrative,
)


class FakeProvider:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.digest_prompts: list[str] = []

    def complete(self, *, system, user, response_model, temperature=0.1):
        if response_model is _Digest:
            if self.fail:
                raise RuntimeError("digest LLM down")
            self.digest_prompts.append(user)
            return _Digest(text="DIGEST")
        # the narrator call
        return BriefingNarrative(
            narrative="Synthesis [1].",
            citations=[BriefingCitation(ref="1", insight_id="s0", domain="sales", finding="f")],
            headline_theme="Theme",
        )


@pytest.fixture
def fake(monkeypatch):
    fp = FakeProvider()
    monkeypatch.setattr(prov, "get_provider", lambda role=None: fp)
    return fp


def _domain(prefix: str, n: int) -> list[dict]:
    return [{"id": f"{prefix}{i}", "finding": f"{prefix} finding {i}", "novelty": float(n - i)} for i in range(n)]


def test_no_digest_when_nothing_dropped(fake):
    data = {"sales": _domain("s", 2)}
    out = _coverage_digest(data, cited_ids={"s0", "s1"})   # both cited → nothing dropped
    assert out == ""
    assert fake.digest_prompts == []                        # no LLM calls


def test_digest_folds_all_findings_per_domain(fake):
    data = {"sales": _domain("s", 6), "support": _domain("p", 5)}   # 11 findings
    out = _coverage_digest(data, cited_ids={f"s{i}" for i in range(8)})  # only ~8 cited → 3 dropped

    assert out != ""
    assert "sales: DIGEST" in out and "support: DIGEST" in out       # both domains represented
    assert fake.digest_prompts                                       # LLM was used


def test_digest_never_blends_domains(fake):
    data = {"sales": _domain("s", 6), "support": _domain("p", 6)}
    _coverage_digest(data, cited_ids=set())                          # all dropped → both folded

    sales_prompts = [p for p in fake.digest_prompts if "Domain: sales" in p]
    assert sales_prompts
    # a per-domain summarize prompt must contain only its own findings, never the other domain's
    assert all("support finding" not in p for p in sales_prompts)


def test_digest_fail_open(monkeypatch):
    monkeypatch.setattr(prov, "get_provider", lambda role=None: FakeProvider(fail=True))
    out = _coverage_digest({"sales": _domain("s", 10)}, cited_ids={"s0"})
    assert out == ""                                                 # error → empty, never raises


def test_build_user_prompt_includes_digest():
    prompt = _build_user_prompt([{"finding": "x"}], [], coverage_digest="sales: all good")
    assert "FULL COVERAGE" in prompt
    assert "sales: all good" in prompt


def test_build_user_prompt_omits_digest_when_empty():
    prompt = _build_user_prompt([{"finding": "x"}], [], coverage_digest="")
    assert "FULL COVERAGE" not in prompt


def test_generate_narrative_computes_digest_for_many_findings(fake):
    data = {"sales": _domain("s", 7), "support": _domain("p", 7)}    # 14 > 8 → digest path runs
    result = generate_narrative(data, patterns=[], connection_id="c")
    assert result["narrative"] == "Synthesis [1]."
    assert fake.digest_prompts                                       # the coverage digest was built
