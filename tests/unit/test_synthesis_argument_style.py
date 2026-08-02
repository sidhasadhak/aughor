"""R16 P2 — the argument-style writing contract on the synthesis prompt.

Flag `report.argument_style` appends the Genie-study writing rules (verdict
first, numbers bold inline, entities by identifier, hedged causes) to the
narrator's system prompt at the one seam that writes report-level prose.
Flag off = the pre-R16 prompt, byte-identical.
"""
from __future__ import annotations

from aughor.agent.prompts_investigate import synthesis_system_prompt as _synthesis_system_prompt


def test_the_prompt_carries_the_writing_contract():
    p = _synthesis_system_prompt()
    assert p.startswith("You are a senior data analyst")   # the base contract survives
    assert "argue like an analyst" in p
    assert "bold inline" in p
    assert "identifier" in p                            # entities named by ID
    assert "verdict sentence FIRST" in p
    assert "hedge honestly" in p
    assert "Never present a hypothesis as a finding" in p
