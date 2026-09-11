"""ON-0 — the prompt-reach ratchet (ROADMAP §3.15).

`aughor.ontology.prompt_reach` measures which ontology fields can change what a model
sees: a field reaches a prompt block iff changing it changes the block's text. This test
pins that measurement so it moves only DELIBERATELY:

* a field that reached a block on 2026-09-10 must still reach it — a renderer edit that
  silently drops a field from a prompt fails here, by name;
* reach may GROW (ON-6's whole job) — add the new block to the baseline in the same PR,
  which is the reviewable act the vocabulary ratchet made standard;
* the walk must still see the whole model — a collapsed field count means the walker
  broke, and an empty audit passes every baseline (the vocabulary ratchet's own lesson).

Measured 2026-09-10 on the fixture graph: 59 of 142 fields reach at least one block;
156 walked since ON-0a added `measured_cardinality`, `cardinality_note`, `core_claims` (unreached by
design — claims are never rendered), `lifecycle_verified` (a gate), `lifecycle_note` (reaches ENTITY MODEL),
and ON-1 added `api_name`, `backing.*` and the link names (unreached: the prompt still names tables).
"""
from __future__ import annotations

import pytest

from aughor.ontology import prompt_reach as pr

#: field path → the blocks it reached on 2026-09-10. A block may be ADDED to a field
#: (reach grew); removing one needs the renderer change that justifies it, in the same PR.
REACH_BASELINE: dict[str, set[str]] = {
    "entities.*.id": {'entity_model'},
    "entities.*.display_name": {'entity_model', 'semantic_layer'},
    "entities.*.identity_key": {'entity_model'},
    "entities.*.grain_verified": {'entity_model'},
    "entities.*.entity_type": {'entity_model'},
    "entities.*.has_lifecycle": {'entity_model'},
    "entities.*.lifecycle_column": {'intake_entity_context'},
    "entities.*.lifecycle_states": {'entity_model'},
    "entities.*.terminal_states": {'entity_model', 'intake_entity_context'},
    "entities.*.active_filter": {'entity_model', 'intake_entity_context'},
    "entities.*.lifecycle_verified": {'entity_model'},   # ON-0a: the gate on the lifecycle-check line
    "entities.*.lifecycle_note": {'entity_model'},       # ON-0a: the lifecycle check travels with the claim
    "entities.*.segments.*.display_name": {'semantic_layer'},
    "entities.*.segments.*.filter_sql": {'semantic_layer'},
    "entities.*.segments.*.verified": {'semantic_layer'},
    "entities.*.created_at_col": {'entity_model'},
    "entities.*.default_filters": {'entity_model'},
    "entities.*.exclude_when": {'entity_model'},
    "entities.*.computed_properties[].label": {'semantic_layer'},
    "entities.*.computed_properties[].formula_sql": {'semantic_layer'},
    "entities.*.computed_properties[].unit": {'semantic_layer'},
    "entities.*.computed_properties[].verified": {'semantic_layer'},
    "relationships.*.from_entity": {'relationships'},
    "relationships.*.to_entity": {'relationships'},
    "relationships.*.verb": {'relationships'},
    "relationships.*.cardinality": {'relationships'},
    "relationships.*.from_table": {'relationships'},
    "relationships.*.from_col": {'relationships'},
    "relationships.*.to_table": {'relationships'},
    "relationships.*.to_col": {'relationships'},
    "relationships.*.join_confidence": {'relationships'},
    "relationships.*.nullable": {'relationships'},
    "relationships.*.value_overlap": {'relationships'},
    "metrics.*.id": {'metric_contract'},
    "metrics.*.display_name": {'metric_contract'},
    "metrics.*.description": {'metric_contract'},
    "metrics.*.formula_sql": {'metric_contract'},
    "metrics.*.grain": {'metric_contract'},
    "metrics.*.unit": {'metric_contract'},
    "metrics.*.tables": {'metric_contract'},
    "metrics.*.known_divergent_calculations": {'metric_contract'},
    "metrics.*.target_value": {'metric_contract'},
    "metrics.*.warning_threshold": {'metric_contract'},
    "metrics.*.critical_threshold": {'metric_contract'},
    "metrics.*.target_period": {'metric_contract'},
    "metrics.*.benchmark_source": {'metric_contract'},
    "metrics.*.verified": {'metric_contract'},
    "metrics.*.verification_note": {'metric_contract'},
    "actions.*.id": {'entity_model', 'query_templates'},
    "actions.*.description": {'entity_model', 'query_templates'},
    "actions.*.entity": {'query_templates'},
    "actions.*.business_rules_enforced": {'query_templates'},
    "actions.*.returns": {'query_templates'},
    "kinetic_actions.*.id": {'actions_declared'},
    "kinetic_actions.*.description": {'actions_declared'},
    "kinetic_actions.*.kind": {'actions_declared'},
    "kinetic_actions.*.params[].name": {'actions_declared'},
    "kinetic_actions.*.params[].data_type": {'actions_declared'},
    "kinetic_actions.*.params[].required": {'actions_declared'},
    "kinetic_actions.*.params[].default_value": {'actions_declared'},
    "kinetic_actions.*.submission_criteria[].expr": {'actions_declared'},
    # ON-4 (2026-09-11): the proposer is told how to pass an object and what an accept will set.
    "kinetic_actions.*.params[].kind": {'actions_declared'},
    "kinetic_actions.*.params[].object_type": {'actions_declared'},
    "kinetic_actions.*.edits[].object": {'actions_declared'},
    "kinetic_actions.*.edits[].property": {'actions_declared'},
    "kinetic_actions.*.edits[].value": {'actions_declared'},
}

#: The walk saw this many leaf fields on 2026-09-10. It may grow with the model; a fall
#: means a class stopped being walked, not that the ontology got smaller.
FIELDS_WALKED = 174   # 142 on 2026-09-10; +5 ON-0a (cardinality, lifecycle, core_claims); +9 ON-1 (api names, backing) — all unreached by design; +9 ON-4 (object params, the action's object type, declared edits); +9 ON-3b (the display property's name, source and measurement, the backing's rows, a link's business-verb name) — unreached by design: the map and describe_entity read them as tools, never as prompt text


@pytest.fixture(scope="module")
def measured() -> pr.Audit:
    return pr.audit()


def test_every_block_renders_on_the_fixture(measured):
    """A renderer returning "" on a fully-populated graph would make every field under
    it read as unreached — the audit must never be blind to its own blind spot."""
    empty = [name for name, n in measured.rendered.items() if n == 0]
    assert not empty, f"blocks rendered empty on the fixture: {empty}"
    assert set(measured.rendered) == {b.name for b in pr.BLOCKS}


def test_walk_still_covers_the_model(measured):
    assert len(measured.rows) >= FIELDS_WALKED, (
        f"the walk saw {len(measured.rows)} fields, baseline {FIELDS_WALKED} — a class stopped "
        "being walked (or a field was removed: lower FIELDS_WALKED in the same PR, deliberately)")


def test_no_field_lost_a_prompt_it_reached(measured):
    """The ratchet. Reach may grow; a field may not silently fall out of a prompt."""
    now = {r.path: set(r.blocks) for r in measured.rows}
    lost = {path: sorted(blocks - now.get(path, set()))
            for path, blocks in REACH_BASELINE.items()
            if blocks - now.get(path, set())}
    assert not lost, (
        "these fields stopped reaching a prompt block they reached on 2026-09-10 "
        f"(edit the renderer back, or lower the baseline in the same PR and say why): {lost}")


def test_reach_growth_is_recorded(measured):
    """The reverse direction is not a failure — it is ON-6 doing its job — but it must be
    RECORDED: a field that newly reaches a block updates the baseline in the same PR, so
    the next reader sees the measured state, not a stale one."""
    now = {r.path: set(r.blocks) for r in measured.rows}
    grew = {path: sorted(blocks - REACH_BASELINE.get(path, set()))
            for path, blocks in now.items()
            if blocks - REACH_BASELINE.get(path, set())}
    assert not grew, (
        "reach GREW — good; record it: add these blocks to REACH_BASELINE in this PR "
        f"so the baseline stays the measurement: {grew}")


def test_action_census_counts_files(tmp_path):
    (tmp_path / "c1" / "s1" / "action").mkdir(parents=True)
    (tmp_path / "c1" / "s1" / "action" / "a.yaml").write_text("target_kind: action\n")
    (tmp_path / "c1" / "s1" / "action" / "b.yaml").write_text("target_kind: action\n")
    (tmp_path / "c2" / "default" / "entity").mkdir(parents=True)
    (tmp_path / "c2" / "default" / "entity" / "Order.yaml").write_text("target_kind: entity\n")
    assert pr.action_census(tmp_path) == {"c1/s1": ["a", "b"]}
    assert pr.action_census(tmp_path / "missing") == {}


def test_intake_context_is_byte_identical_to_the_inline_block():
    """The block extracted from agent/investigate.py must render exactly what the inline
    code rendered — the extraction exists so the audit can see it, not to change it."""
    from aughor.ontology.semantic_block import entity_intake_fields, render_entity_context

    order = pr.fixture_graph().entities["Order"]
    fields = entity_intake_fields(order)
    assert fields == {
        "ontology_entity_id": "Order",
        "active_filter": "order_status NOT IN ('delivered', 'canceled')",
        "lifecycle_column": "order_status",
        "terminal_states": ["delivered", "canceled"],
        "lifecycle_states": ["placed", "shipped", "delivered", "canceled"],
    }
    text = render_entity_context(fields)
    assert text == (
        "\nONTOLOGY ENTITY CONTEXT (auto-derived — treat as authoritative):\n"
        "  active_filter: order_status NOT IN ('delivered', 'canceled')\n"
        "  ↳ ALWAYS apply this filter to every query on the metric table "
        "unless you are explicitly counting terminal/inactive rows.\n"
        "  lifecycle_column: order_status  terminal_states: ['delivered', 'canceled']\n"
        "  ↳ When computing active counts, exclude rows whose "
        "order_status is in ['delivered', 'canceled']."
    )
    assert render_entity_context({}) == ""
    assert render_entity_context({"lifecycle_column": "s"}).startswith("\nONTOLOGY ENTITY CONTEXT")
