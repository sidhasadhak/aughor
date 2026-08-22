"""Creating a custom agent — the paths a user actually walks, and the traps in them.

Every case here was found by mapping the flow end to end against what the runtime reads.
The theme is one rule: **a creation path must not produce an agent that its own editor
refuses to save**, and a field the form offers must mean something when the agent answers.
"""
from __future__ import annotations

import pytest


def _packs_dir():
    from pathlib import Path
    return Path(__file__).resolve().parents[2] / "packs"


# ── the trap on the primary creation path ────────────────────────────────────────

def test_hiring_from_a_pack_produces_an_agent_its_editor_can_save(client):
    """THE trap. `create_from_template` binds `pack_ids=[pack_id]` with no validation,
    while PATCH validated against `active_packs()` — status == "active" only. The one pack
    that ships is `status: draft`, so the primary creation path produced an agent whose
    very next Save returned 422 about a binding the user never chose.

    The asymmetry was the bug, not the draft status: `packs/intake.py` ALREADY gates
    steering on active-plus-pinned at RUN time, so refusing the id at WRITE time is a
    second, stricter gate that contradicts the first.
    """
    templates = client.get("/agents/templates").json()["templates"]
    if not templates:
        pytest.skip("no packs on disk to create from")
    made = client.post("/agents/custom/from-template",
                       json={"pack_id": templates[0]["pack_id"]})
    assert made.status_code == 201, made.text
    agent = made.json()["agent"]
    try:
        # Exactly what the configure step's save sends: the whole form, including the
        # pack_ids that creating from a pack bound for us.
        saved = client.patch(f"/agents/custom/{agent['id']}", json={
            "name": agent["name"], "instructions": agent["instructions"],
            "connection_id": agent["connection_id"], "schema_scope": agent["schema_scope"],
            "doc_ids": agent["doc_ids"], "pack_ids": agent["pack_ids"],
        })
        assert saved.status_code == 200, (
            f"the editor refused a binding that creation made: {saved.text}")
    finally:
        client.delete(f"/agents/custom/{agent['id']}")


def test_an_unknown_pack_id_is_still_refused(client):
    """Loosening the gate must not mean accepting anything — a typo is still a 422."""
    made = client.post("/agents/custom", json={"name": "pack probe"})
    agent = made.json()
    try:
        r = client.patch(f"/agents/custom/{agent['id']}",
                         json={"pack_ids": ["no-such-pack-anywhere"]})
        assert r.status_code == 422
        assert "no-such-pack-anywhere" in r.text
    finally:
        client.delete(f"/agents/custom/{agent['id']}")


# ── the golden that belonged to somebody else ────────────────────────────────────

def test_deleting_a_golden_requires_it_to_belong_to_that_agent(client):
    """`DELETE /agents/custom/{agent_id}/goldens/{golden_id}` ignored the agent id — the
    path parameter was decorative, so any agent's URL could delete any golden."""
    a = client.post("/agents/custom", json={"name": "owner agent"}).json()
    b = client.post("/agents/custom", json={"name": "other agent"}).json()
    try:
        g = client.post(f"/agents/custom/{a['id']}/goldens",
                        json={"question": "how many orders?",
                              "reference_sql": "SELECT count(*) FROM orders"})
        assert g.status_code == 201, g.text
        golden_id = g.json()["id"]

        stolen = client.delete(f"/agents/custom/{b['id']}/goldens/{golden_id}")
        assert stolen.status_code == 404, (
            "one agent deleted another's golden — the agent id in the path is not decorative")
        assert client.get(f"/agents/custom/{a['id']}/goldens").json(), "the golden survived"

        ok = client.delete(f"/agents/custom/{a['id']}/goldens/{golden_id}")
        assert ok.status_code == 200 and ok.json()["deleted"] == golden_id
    finally:
        client.delete(f"/agents/custom/{a['id']}")
        client.delete(f"/agents/custom/{b['id']}")


# ── what the runtime actually reads ──────────────────────────────────────────────

def test_the_governing_fields_are_exactly_what_changes_an_answer():
    """A creation form may only offer fields that reach the runtime. These five are read
    by `agent_brief_block`, the document scope, the pack pool and the ask bindings; the
    digest that decides whether an eval is still valid is computed over the same set, so
    the two definitions cannot drift apart."""
    from aughor.custom_agents.models import GOVERNING_FIELDS

    assert set(GOVERNING_FIELDS) == {
        "instructions", "connection_id", "schema_scope", "doc_ids", "pack_ids"}


def test_an_agent_with_no_documents_sees_none_rather_than_the_global_corpus():
    """The surprise a creation form has to disclose: empty `doc_ids` is RESTRICTIVE, not
    neutral. `agent_doc_ids()` returns an empty set for an active agent, and the retrieval
    seam returns "" for that — so an agent created without documents sees FEWER than an
    ask with no agent at all. Pinned so the behaviour cannot change silently under a form
    that explains it."""
    from aughor.custom_agents.context import activate_agent, agent_doc_ids, release_agent
    from aughor.custom_agents.models import UserAgent
    from aughor.knowledge.indexer import build_external_context_section

    assert agent_doc_ids() is None, "no agent active → unrestricted"
    token = activate_agent(UserAgent(id="ua_probe", name="Probe", doc_ids=[]))
    try:
        assert agent_doc_ids() == set()
        assert build_external_context_section("anything") == ""
    finally:
        release_agent(token)


def test_a_created_agent_is_live_immediately(client):
    """There is no draft state: a POST puts the agent in the chat picker at once. Recorded
    because a creation flow that implies otherwise would be lying about the consequence."""
    made = client.post("/agents/custom", json={"name": "instantly live"})
    agent = made.json()
    try:
        assert made.status_code == 201
        assert agent["enabled"] is True
        listed = {a["id"] for a in client.get("/agents/custom").json()}
        assert agent["id"] in listed
    finally:
        client.delete(f"/agents/custom/{agent['id']}")
