"""JD-5 — the hosted Jev binding behind JD-1's seam. Hermetic: the transport is injected,
no network, no model call. What is pinned, gate by gate:

* configuration is LOUD — no key, or no model id, is a stated reason, never a default;
* the flag off means the provider it was handed, byte-for-byte untouched;
* a PII-bearing bundle is withheld WHOLE — nothing is posted, and the reason says why;
* an outbound block is an unavailable answer, not an exception into the query path;
* a bundle Jev cannot answer is re-judged by the HOUSE tier (the fallback guarantee), so an
  outage degrades to yesterday's cascade — and never floods the champion;
* the seam dispatches to a judge-shaped backend after its own misuse checks;
* the cascade's notes NAME the third party where the Trust Receipt will read them.
"""
from __future__ import annotations

import pytest

from aughor.judgment.jev import FallbackJudge, JevJudge, cheap_judge_for, configured_judge
from aughor.judgment.seam import Noul, judge


def _post_answering(p_for):
    sent = []

    def post(url, body, headers):
        sent.append((url, body, headers))
        return {"model": "jev-test", "usage": {"input_tokens": 10, "output_tokens": 2},
                "answers": {qid: {"type": "noul", "noul": p_for(qid)}
                            for qid in body["questions"]}}
    return post, sent


class HouseTier:
    """A seam-shaped LLM provider: `complete` answers every r<gi> field with 0.9."""

    def __init__(self):
        self.calls = 0

    def complete(self, *, system, user, response_model, **kw):
        self.calls += 1
        return response_model(**{f: 0.9 for f in response_model.model_fields})


# ── configuration is loud ─────────────────────────────────────────────────────────────────

def test_missing_key_and_missing_model_are_stated_reasons_not_defaults(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("AUGHOR_JEV_MODEL", raising=False)
    j, why = configured_judge()
    assert j is None and "TYPESAFE_API_KEY" in why
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    j, why = configured_judge()
    assert j is None and "AUGHOR_JEV_MODEL" in why, "no model id may ship as a default"
    monkeypatch.setenv("AUGHOR_JEV_MODEL", "jev-test")
    j, why = configured_judge()
    assert j is not None and why == "" and j.model == "jev-test"


def test_flag_off_hands_back_the_exact_provider(monkeypatch):
    monkeypatch.delenv("AUGHOR_SEMOPS_JEV_CHEAP_TIER", raising=False)
    house = HouseTier()
    got, note = cheap_judge_for(house)
    assert got is house and note == ""


def test_flag_on_but_unconfigured_says_so_instead_of_silently_doing_nothing(monkeypatch):
    monkeypatch.setenv("AUGHOR_SEMOPS_JEV_CHEAP_TIER", "1")
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    house = HouseTier()
    got, note = cheap_judge_for(house)
    assert got is house and "TYPESAFE_API_KEY" in note


# ── the PII gate fails closed, and nothing is posted ─────────────────────────────────────

def test_a_pii_bearing_bundle_is_withheld_whole_and_never_posted():
    post, sent = _post_answering(lambda qid: 0.9)
    j = JevJudge("k", "jev-test", post=post)
    state = "Predicate: p\n\nRows (index: text):\n[0] alice@example.com wrote in\n[1] a plain row"
    out = j.judge(state, [Noul("r0", "Row [0] satisfies."), Noul("r1", "Row [1] satisfies.")])
    assert sent == [], "a redactable value must stop the POST itself, not just the answer"
    assert all(not a.available for a in out.values())
    assert all("withheld" in a.reason for a in out.values())


def test_a_clean_bundle_posts_once_and_reads_probabilities():
    post, sent = _post_answering(lambda qid: 0.9 if qid == "r0" else 0.2)
    j = JevJudge("k", "jev-test", post=post)
    out = j.judge("Predicate: p\n\nRows (index: text):\n[0] a coat\n[1] a mug",
                  [Noul("r0", "Row [0] satisfies."), Noul("r1", "Row [1] satisfies.")])
    assert len(sent) == 1
    url, body, headers = sent[0]
    assert headers["Authorization"] == "Bearer k" and body["model"] == "jev-test"
    assert out["r0"].value is True and out["r0"].distribution["true"] == pytest.approx(0.9)
    assert out["r1"].value is False and out["r1"].distribution["true"] == pytest.approx(0.2)


def test_an_outbound_block_is_an_unavailable_answer(monkeypatch):
    from aughor.govern.outbound import OutboundBlocked

    def blocked(*a, **kw):
        raise OutboundBlocked("typesafe", "cap reached")
    post, sent = _post_answering(lambda qid: 0.9)
    j = JevJudge("k", "jev-test", post=post)
    monkeypatch.setattr(j, "_with_backoff", blocked)
    out = j.judge("Rows (index: text):\n[0] a coat", [Noul("r0", "Row [0] satisfies.")])
    assert sent == [] and not out["r0"].available and "cap reached" in out["r0"].reason


# ── the fallback guarantee: an outage is yesterday, never a champion flood ───────────────

def test_a_dead_jev_bundle_is_rejudged_by_the_house_tier():
    def dead(url, body, headers):
        raise RuntimeError("HTTP 500: down")
    house = HouseTier()
    fj = FallbackJudge(JevJudge("k", "jev-test", post=dead), house)
    out = fj.judge("Rows (index: text):\n[0] a coat", [Noul("r0", "Row [0] satisfies.")])
    assert house.calls == 1 and out["r0"].available and out["r0"].value is True
    assert fj.fell_back == 1 and fj.fallback_reasons


def test_a_partial_bundle_is_kept_not_retried():
    """One unreadable answer among good ones is band signal, not an outage."""
    def post(url, body, headers):
        return {"answers": {"r0": {"type": "noul", "noul": 0.9},
                            "r1": {"type": "noul", "noul": None}}}
    house = HouseTier()
    fj = FallbackJudge(JevJudge("k", "jev-test", post=post), house)
    out = fj.judge("Rows (index: text):\n[0] a\n[1] b",
                   [Noul("r0", "Row [0] satisfies."), Noul("r1", "Row [1] satisfies.")])
    assert house.calls == 0 and fj.fell_back == 0
    assert out["r0"].available and not out["r1"].available


def test_the_fallback_never_reaches_the_champion_instead(monkeypatch):
    """The whole promise in one run: Jev down + banded cascade on → the CHEAP house tier
    answers, and the champion sees only the rows the band genuinely escalates (none here)."""
    from aughor.agent.state import QueryResult
    from aughor.semops import operators as ops

    def dead(url, body, headers):
        raise RuntimeError("HTTP 503: down")
    house, champ = HouseTier(), HouseTier()
    monkeypatch.setattr(ops, "get_provider",
                        lambda role="fast", **kw: champ if role == "coder" else house)
    monkeypatch.setenv("AUGHOR_SEMOPS_JEV_CHEAP_TIER", "1")
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    monkeypatch.setenv("AUGHOR_JEV_MODEL", "jev-test")
    import aughor.judgment.jev as jev_mod
    monkeypatch.setattr(jev_mod, "_http_post", dead)
    qr = QueryResult(hypothesis_id="t", sql="SELECT 1", columns=["note"],
                     rows=[[f"row {i}"] for i in range(6)], row_count=6)
    out = ops.semantic_filter(qr, "note", "keepers", validate_sample=4)
    assert house.calls == 1, "the house tier answers the fallen bundle"
    assert champ.calls == 0, "an outage must not become a champion flood"
    assert out.result.row_count == 6
    assert any("answered by the house tier" in n for n in out.notes)


# ── the seam dispatches, and the notes name the third party ──────────────────────────────

def test_the_seam_dispatches_to_a_judge_shaped_backend_after_its_own_checks():
    post, sent = _post_answering(lambda qid: 0.8)
    j = JevJudge("k", "jev-test", post=post)
    out = judge("Rows (index: text):\n[0] a coat", [Noul("r0", "Row [0] satisfies.")],
                provider=j)
    assert sent and out["r0"].available
    with pytest.raises(ValueError):
        judge("s", [Noul("r0", "a"), Noul("r0", "b")], provider=j)
    assert len(sent) == 1, "misuse must be refused BEFORE the backend is consulted"


def test_the_cascade_notes_name_the_third_party(monkeypatch):
    from aughor.agent.state import QueryResult
    from aughor.semops import operators as ops
    post, sent = _post_answering(lambda qid: 0.9)
    house, champ = HouseTier(), HouseTier()
    monkeypatch.setattr(ops, "get_provider",
                        lambda role="fast", **kw: champ if role == "coder" else house)
    monkeypatch.setenv("AUGHOR_SEMOPS_JEV_CHEAP_TIER", "1")
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    monkeypatch.setenv("AUGHOR_JEV_MODEL", "jev-test")
    import aughor.judgment.jev as jev_mod
    monkeypatch.setattr(jev_mod, "_http_post", post)
    qr = QueryResult(hypothesis_id="t", sql="SELECT 1", columns=["note"],
                     rows=[["a coat"], ["a parka"]], row_count=2)
    out = ops.semantic_filter(qr, "note", "keepers", validate_sample=2)
    assert any("TypeSafe Jev (jev-test)" in n and "third party" in n for n in out.notes)
    assert house.calls == 0 and champ.calls == 0 and len(sent) == 1
