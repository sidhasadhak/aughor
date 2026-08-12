"""PE-2..PE-5 — the prompt diet and its verification half.

The measured specimen (roadmap §2.6): 3,833 tokens, of which the static instruction
tail was 1,731 (45%) and an inapplicable playbook 428 (11%), against 850 of evidence.
The diet moves the writing contract to the system prompt (stable prefix), turns the
correctness lectures into deterministic post-checks with one named-violation retry,
filters change-triggered playbook entries out of cross-sectional prompts, stops
cutting findings mid-word, and refuses degenerate seeds before spending a run.

The SIZE test is a ratchet: the static text can only shrink. It measures the same
thing the RTF specimen measured, so the number is comparable.
"""
from __future__ import annotations

from types import SimpleNamespace

from aughor.agent import report_checks as rc
from aughor.agent.investigate import _degenerate_seed_verdict, _trim_to_boundary
from aughor.agent.prompts_investigate import (
    ADA_SYNTHESIZE_PROMPT,
    BASELINE_GUARDRAILS,
    SYNTHESIS_CORE_RULES,
    synthesis_system_prompt,
)
from aughor.playbook.models import PlaybookEntry
from aughor.playbook.retriever import filter_by_approach


# ── the ratchet: static prompt text only shrinks ─────────────────────────────────

def test_static_prompt_text_stays_dieted():
    """The specimen's static tail was ~6,930 chars riding EVERY synthesis call.
    Capable tier now carries the template skeleton + core rules; baseline adds the
    guardrails. Both budgets are ratchets — lower them when you shrink further,
    never raise them without a measurement saying why."""
    skeleton = ADA_SYNTHESIZE_PROMPT.format(
        question="", phases_summary="", evidence_log="", events_section="",
        metric_targets_section="", playbook_section="", org_intelligence_section="",
        external_context_section="")
    capable_static = len(skeleton) + len(SYNTHESIS_CORE_RULES)
    assert capable_static < 2000, f"capable-tier static text grew to {capable_static} chars"
    baseline_static = capable_static + len(BASELINE_GUARDRAILS)
    assert baseline_static < 3400, f"baseline-tier static text grew to {baseline_static} chars"


def test_system_prompt_tiers_the_guardrails(monkeypatch):
    import aughor.llm.profile as profile

    monkeypatch.setattr(profile, "profile_for",
                        lambda role="narrator", **k: SimpleNamespace(capable=True))
    assert "MATERIALITY" not in synthesis_system_prompt(), \
        "a capable model gets the short contract; the checks verify instead"
    monkeypatch.setattr(profile, "profile_for",
                        lambda role="narrator", **k: SimpleNamespace(capable=False))
    baseline = synthesis_system_prompt()
    assert "GROUNDING" in baseline and "SIGN CONVENTION" in baseline
    assert "REPORT RULES:" in baseline, "core rules ride every tier"


# ── the checks: verify what the prose used to lecture ────────────────────────────

def _wf(cause, amount, pct):
    return {"cause": cause, "amount_label": amount, "pct_of_total": pct,
            "controllable": True, "structural": False}


def test_sign_contradiction_is_caught():
    v = rc.check_signs([_wf("discounting", "-$287K", 42.0)])
    assert v and "opposite signs" in v[0]
    assert rc.check_signs([_wf("discounting", "-$287K", -42.0)]) == []
    assert rc.check_signs([_wf("mix shift", "$120K", 30.0)]) == [], \
        "an unsigned label is a style choice, not a contradiction"


def test_waterfall_sum_gap_is_caught():
    assert rc.check_waterfall_sums([_wf("a", "-$1K", -20.0), _wf("b", "-$2K", -10.0)])
    assert rc.check_waterfall_sums([_wf("a", "-$1K", -60.0), _wf("b", "-$2K", -40.0)]) == []
    assert rc.check_waterfall_sums([_wf("a", "-$1K", -100.0)]) == [], \
        "a single entry can't be checked for completeness"


def test_the_14_dollar_specimen_shape_is_caught():
    """Question claims a figure; the report never engages it — the exact specimen."""
    v = rc.check_question_addressed(
        "Investigate: The total revenue generated across all orders is $14.",
        "Revenue is most concentrated in the luxury segment at 67.6% of GMV.")
    assert v and "never mentions it" in v[0]
    assert rc.check_question_addressed(
        "Investigate: The total revenue generated across all orders is $14.",
        "Total revenue is not $14 — the measured total is 45.4M EUR; the seed "
        "figure comes from a 2-row scratch table.") == []
    assert rc.check_question_addressed("Where are we losing money?", "anything") == []


def test_grounding_catches_fabricated_bold_numbers():
    evidence = "region | metric\nWest | 725457.82\nEast | 678781.24"
    v = rc.check_grounding("West leads at **725457.82** but East is **999123** behind.",
                           evidence)
    assert v and "**999123" in v[0]
    assert rc.check_grounding("West leads at **725,457.82**.", evidence) == []
    assert rc.check_grounding("roughly **$2.1M** across **3** regions", evidence) == [], \
        "compact forms and tiny integers are out of scope — never cry wolf"


# ── PE-3: playbook entries match the question's shape ────────────────────────────

def _entry(cond):
    return PlaybookEntry(id="x", trigger_metric="gmv", trigger_condition=cond,
                         recommendation="do something")


def test_temporal_playbook_entries_never_enter_cross_sectional_prompts():
    entries = [_entry("GMV up, ec_aov flat"), _entry("refund_rate above target")]
    kept = filter_by_approach(entries, cross_sectional=True)
    assert [e.trigger_condition for e in kept] == ["refund_rate above target"]
    assert filter_by_approach(entries, cross_sectional=False) == entries, \
        "temporal prompts keep everything"


# ── PE-4: never mid-word ─────────────────────────────────────────────────────────

def test_truncation_lands_on_boundaries():
    text = ("Clienteling has the lowest total GMV at 3639570 EUR. This indicates "
            "lower volume, not poor efficiency per transaction overall.")
    cut = _trim_to_boundary(text, 60)
    assert cut.endswith((".", "…")), cut
    assert not cut.endswith(("ef", "effi", "lo")), "never a half-word"
    assert _trim_to_boundary("short", 60) == "short"
    long_cut = _trim_to_boundary(text, 80)
    assert long_cut == "Clienteling has the lowest total GMV at 3639570 EUR.", \
        "a sentence end within budget wins over a longer word cut"


# ── PE-5: refuse before spending ─────────────────────────────────────────────────

def _conn(count):
    def execute(label, sql):
        return SimpleNamespace(error=None, rows=[[str(count)]])
    return SimpleNamespace(execute=execute)


def test_degenerate_seed_is_refused_with_a_verdict():
    verdict = _degenerate_seed_verdict(
        _conn(2), "rearm_single.orders",
        ["luxexperience.orders.platform", "luxexperience.orders.segment"], "GMV")
    assert verdict and "doesn't hold up" in verdict
    assert "rearm_single.orders" in verdict and "luxexperience" in verdict


def test_healthy_seeds_pass_the_gate():
    assert _degenerate_seed_verdict(
        _conn(112439), "luxexperience.orders",
        ["luxexperience.orders.platform"], "GMV") is None, "big table passes"
    assert _degenerate_seed_verdict(
        _conn(2), "rearm_single.orders",
        ["rearm_single.orders.status"], "GMV") is None, \
        "tiny but self-consistent stays answerable by the scan itself"

    def _boom(label, sql):
        raise RuntimeError("connection lost")
    assert _degenerate_seed_verdict(
        SimpleNamespace(execute=_boom), "a.b", ["c.d.e"], "GMV") is None, \
        "fail-open: a gate error must never eat a real question"
