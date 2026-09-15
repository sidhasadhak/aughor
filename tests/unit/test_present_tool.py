"""AV-0/AV-2 — the answer vocabulary: closed kinds, bounded fields, refused WHOLE.

The refused alternative this schema stands against is an open UI language rendered
from model output. Locked here: unknown kinds and unknown ACTION doors refuse; a
progress part without a real denominator refuses (FL-5's law at the schema); a
refusal renders NOTHING (all-or-nothing); unknown fields do not survive validation;
and the tool is absent from a turn that cannot render.
"""
from __future__ import annotations

from aughor.agent.present_tool import (
    PART_KINDS,
    present,
    present_tools,
    validate_parts,
)


def _facts():
    return {"kind": "fact_set", "title": "Automations",
            "facts": [{"label": "Daily sales to Slack", "value": "daily at 09:00 UTC",
                       "status": "neutral"}]}


def test_the_good_shapes_validate_and_only_known_fields_survive():
    clean, problems = validate_parts([
        {**_facts(), "onClick": "javascript:alert(1)"},          # smuggled field
        {"kind": "status", "label": "muted until first run", "tone": "warn"},
        {"kind": "progress", "label": "backfill", "done": 3, "total": 8},
        {"kind": "section", "title": "How this was measured", "body": "Ran `count(*)`.",
         "collapsed": True},
        {"kind": "action_set", "actions": [
            {"action": "follow_up", "label": "Why muted?", "question": "Why is it muted?"}]},
        {"kind": "proposal_ref", "proposal_id": "prop-1"},
    ])
    assert problems == []
    assert {p["kind"] for p in clean} == PART_KINDS
    assert "onClick" not in clean[0]                              # rebuilt, not passed through


def test_refusals_are_whole_and_name_the_part():
    clean, problems = validate_parts([_facts(), {"kind": "hologram"}])
    assert clean == [] and any("part 2" in p and "hologram" in p for p in problems)

    clean, problems = validate_parts([{"kind": "progress", "label": "x", "done": 5, "total": 0}])
    assert clean == [] and any("total > 0" in p for p in problems)

    clean, problems = validate_parts([{"kind": "action_set", "actions": [
        {"action": "execute_sql", "label": "Run", "question": "…"}]}])
    assert clean == [] and any("names no door" in p for p in problems)

    assert validate_parts([])[1] == ["parts must be a non-empty list"]
    assert "at most" in validate_parts([_facts()] * 13)[1][0]


def test_present_emits_one_frame_or_nothing():
    frames = []
    out = present({"parts": [_facts()]}, emit=lambda t, p: frames.append((t, p)))
    assert out["presented"] is True and "do NOT repeat" in out["summary"]
    assert len(frames) == 1
    t, payload = frames[0]
    assert t == "answer_parts" and payload["version"] == 1
    assert payload["parts"][0]["kind"] == "fact_set"

    frames.clear()
    out = present({"parts": [{"kind": "status", "label": "", "tone": "warn"}]},
                  emit=lambda t, p: frames.append((t, p)))
    assert out["presented"] is False and frames == []             # a refusal renders nothing


def test_the_tool_is_absent_from_a_turn_that_cannot_render():
    assert present_tools(emit=None) == []
    roster = present_tools(emit=lambda t, p: None)
    assert [t.name for t in roster] == ["present"]


def test_converse_offers_present_only_with_a_channel():
    from aughor.agent.converse_tools import converse_tools
    with_channel = {t.name for t in converse_tools("conn-x", emit=lambda t, p: None)}
    without = {t.name for t in converse_tools("conn-x")}
    assert "present" in with_channel and "present" not in without
