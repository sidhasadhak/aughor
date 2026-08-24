"""Rot guard: every tool name mentioned in prose the MODEL reads must be a tool the
model actually has.

Tool descriptions cross-reference each other on purpose ("use run_sql when you have
exact SQL", "a complete question belongs to answer_question", "use describe_table for
the columns") — routing lives in the descriptions, once, so the system prompt does not
carry a drifting second copy. The cost of that design is that a rename or removal
turns the survivors' descriptions into instructions to call a tool that no longer
exists, and nothing else can tell: the model just fails to route, quietly. The
2026-08-14 repair instructions (``run_sql`` → ``repair.next_tool``) widened the surface.

WrenAI ships the same guard for its CLI (test_served_content_guard.py: every
``wren <cmd>`` in agent-facing content must resolve on the real command tree, and a
meta-test asserts the scan actually found something). Ours is over the LIVE roster —
``converse_tools(...)`` constructed, not grepped — so it cannot go blind to a rename
the way a source scan would (the [[grep-and-count-false-negatives]] lesson).

Two triggers, both cheap:
  * a ``snake_case`` token in a description that LOOKS like a tool name and is not
    one — the description is talking about a tool that does not exist;
  * a ``next_tool`` in the repair table that is not on the roster.
"""
from __future__ import annotations

import re

from aughor.agent import converse_tools as ct

# Tokens shaped like a tool name: two+ lowercase words joined by underscores. Plain
# words (`caveats`, `sql`) never match; neither do dotted counters or CamelCase.
_TOOLISH = re.compile(r"\b[a-z]+(?:_[a-z]+)+\b")

# snake_case tokens that legitimately appear in descriptions and are NOT tools —
# field names of the payloads the tools return. Keep this list SHORT and named:
# a growing exemption list is the guard going blind one entry at a time.
_PAYLOAD_FIELDS = {
    "row_count", "guard_receipts", "next_tool", "session_id", "canvas_id",
    "connection_id", "user_question", "reference_sql", "accept_sql",
    "order_id", "customer_id", "created_at", "sub_category",
    # A field on every entry `list_packs` returns. The tool's prose has to name it,
    # because a pack listed with it false is one the model must NOT then try to read.
    "applies_to_this_connection",
}


def _roster() -> dict[str, str]:
    return {t.name: t.description for t in ct.converse_tools("guard-conn")}


def test_descriptions_only_name_tools_the_model_has():
    roster = _roster()
    names = set(roster)
    assert len(names) >= 5, "the roster failed to construct — the guard would pass vacuously"
    offenders: list[str] = []
    for name, desc in roster.items():
        for tok in set(_TOOLISH.findall(desc or "")):
            if tok in names or tok in _PAYLOAD_FIELDS:
                continue
            offenders.append(f"{name}: mentions {tok!r}")
    assert not offenders, (
        "tool prose names a tool the model does not have (rename it, or add the token to "
        "_PAYLOAD_FIELDS if it is a payload field, with a reason):\n  " + "\n  ".join(offenders))


def test_repair_routing_only_names_tools_the_model_has():
    names = set(_roster())
    for kind, (next_tool, step) in ct._NEXT_TOOL.items():
        assert next_tool in names, f"repair kind {kind!r} routes to missing tool {next_tool!r}"
        for tok in set(_TOOLISH.findall(step)):
            assert tok in names or tok in _PAYLOAD_FIELDS, (
                f"repair kind {kind!r} instruction mentions {tok!r}, not a tool")


def test_the_guard_actually_scans_cross_references():
    # Meta-guard (WrenAI's `test_at_least_one_invocation_was_validated`): if the
    # descriptions stopped cross-referencing tools, or the regex stopped matching,
    # the guard above would pass by finding nothing. Prove it found real references.
    roster = _roster()
    names = set(roster)
    hits = sum(1 for desc in roster.values()
               for tok in set(_TOOLISH.findall(desc or "")) if tok in names)
    assert hits >= 3, f"only {hits} cross-references found — the scan is not seeing the prose"
