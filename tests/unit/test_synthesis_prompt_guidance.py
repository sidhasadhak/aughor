"""Synthesis-prompt guidance for coherence + value-lever depth (2026-06-26).

#11: recommendations must not contradict a 'uniform metric' headline (no segment-rate
lever when the rate is flat). #10: when the rate is flat but cost concentrates, size the
real lever (per-unit reduction / volume) from chain figures instead of re-stating the
flat rate. These are prompt directives — this test guards them against accidental removal
and confirms the template still formats with its placeholders intact.
"""
from aughor.agent.prompts_explore import SYNTHESIZE_EXPLORATION_PROMPT


def test_prompt_formats_with_all_placeholders():
    out = SYNTHESIZE_EXPLORATION_PROMPT.format(
        question="why are refunds high?",
        analysis_ledger="(none)",
        chain_summary="[Q1] ...",
        events_section="",
    )
    assert "ORIGINAL QUESTION: why are refunds high?" in out


def test_prompt_contains_coherence_and_value_lever_guidance():
    p = SYNTHESIZE_EXPLORATION_PROMPT
    assert "RECOMMENDATION COHERENCE" in p
    assert "no rate lever when the rate is flat" in p
    assert "VALUE LEVER" in p
    assert "value × volume" in p
