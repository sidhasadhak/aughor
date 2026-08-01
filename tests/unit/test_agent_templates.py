"""Wave H4 — hiring an analyst from a Domain Expertise Pack.

The test carrying the wave's argument is
:func:`test_suggested_questions_are_not_written_as_goldens`. H4 was scoped as "the pack's
question/eval YAML seeded as goldens, so a template agent is born measured". It cannot be,
and faking it would be worse than not doing it: a golden is graded by EXECUTING its
``reference_sql`` (``NOT NULL`` in the schema), a pack's evals carry behavioural
expectations rather than SQL, and its metric recipes are prose with ``{{role.*}}``
placeholders that only resolve against a specific connection. The only way to fill the gap
would be to generate the SQL with the same model the golden exists to grade — a suite the
model wrote for itself, under a pass chip that reads as evidence.

So a hired agent is born with a STANCE, and earns its chip only once real ground truth
exists. The suggestions say what they still need.
"""
from __future__ import annotations

import pytest

from aughor.custom_agents import delete_agent, get_agent, list_agents
from aughor.custom_agents.store import list_goldens
from aughor.custom_agents.templates import (
    NEEDS_REFERENCE_SQL, compose_instructions, create_from_template, get_template,
    list_templates,
)

PACK = "customer-analytics"


@pytest.fixture(autouse=True)
def _clean_agents():
    yield
    for a in list_agents():
        delete_agent(a.id)


# ── the projection ──────────────────────────────────────────────────────────────────

def test_the_shipped_pack_is_offered_as_a_template():
    ids = [t["pack_id"] for t in list_templates()]
    assert PACK in ids


def test_a_template_carries_the_packs_stance_as_instructions():
    """`instructions` is prose written for a model to read, which is exactly what
    expertise.md already is — so this is a concatenation, not a translation."""
    tpl = get_template(PACK)
    assert tpl is not None
    assert "cohorts" in tpl["instructions"].lower()
    assert "customer-data analyst" in tpl["instructions"].lower()   # the persona line
    assert "retention" in [d.lower() for d in tpl["domains"]]


def test_an_unknown_pack_is_none_not_an_empty_template():
    """An empty template would create a nameless agent with no stance and look like it
    worked."""
    assert get_template("no-such-pack") is None


def test_instructions_keep_the_role_when_the_stance_must_be_cut():
    from aughor.custom_agents.models import INSTRUCTIONS_MAX

    out = compose_instructions("A retention analyst.", "x" * (INSTRUCTIONS_MAX * 2))
    assert len(out) == INSTRUCTIONS_MAX
    assert out.startswith("A retention analyst.")


def test_a_stanceless_pack_still_yields_the_role():
    assert compose_instructions("Just a role.", "") == "Just a role."


def test_the_documents_own_title_is_dropped_but_its_headings_are_kept():
    """"# Customer Analytics — reasoning stance" titles the file and instructs nothing; the
    sub-headings organise the guidance and must survive."""
    out = compose_instructions("Role.", "# Doc title\n\nThink in cohorts.\n\n## Anchor\nSignup vs first purchase.")
    assert "Doc title" not in out
    assert "Think in cohorts." in out and "## Anchor" in out


def test_a_stance_that_is_only_a_title_falls_back_to_the_role():
    assert compose_instructions("Role.", "# Just a title") == "Role."


# ── hiring ──────────────────────────────────────────────────────────────────────────

def test_hiring_binds_the_pack_rather_than_absorbing_it():
    """The pack stays the authority: improving its recipes improves every agent hired
    from it. Copying its content into the agent row would fork that."""
    made = create_from_template(PACK, connection_id="conn-h4")
    agent = get_agent(made["agent"]["id"])
    assert agent is not None
    assert agent.pack_ids == [PACK]
    assert agent.connection_id == "conn-h4"
    assert "cohorts" in agent.instructions.lower()


def test_a_hire_can_be_renamed_without_losing_the_stance():
    made = create_from_template(PACK, name="Churn Desk")
    agent = get_agent(made["agent"]["id"])
    assert agent.name == "Churn Desk"
    assert agent.instructions


def test_hiring_from_an_unknown_pack_creates_nothing():
    assert create_from_template("no-such-pack") is None
    assert list_agents() == []


# ── the honest half ─────────────────────────────────────────────────────────────────

def test_suggested_questions_are_not_written_as_goldens():
    """The wave's argument. A pack cannot supply reference SQL, so nothing is written to
    the suite — an unmeasured agent must not present a measured one's evidence."""
    made = create_from_template(PACK)
    agent_id = made["agent"]["id"]

    assert list_goldens(agent_id) == []
    assert get_agent(agent_id).last_eval is None, "a hire must not be born with a pass chip"
    assert made["suggested_goldens"], "the domain's questions should still reach the creator"


def test_every_suggestion_states_what_it_still_needs():
    """A UI rendering "0 goldens" with no reason has told the user nothing actionable."""
    tpl = get_template(PACK)
    assert all(s["needs"] == NEEDS_REFERENCE_SQL for s in tpl["suggested_goldens"])
    assert all(s["question"].strip() for s in tpl["suggested_goldens"])


def test_the_suggestions_are_the_domains_own_questions():
    tpl = get_template(PACK)
    asked = [s["question"] for s in tpl["suggested_goldens"]]
    assert "How is retention trending by cohort?" in asked          # canonical
    assert any("acquisition-mix" in q for q in asked)               # diagnostic
