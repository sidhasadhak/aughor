"""Arc TC-1 (ROADMAP §3.59) — which revision of an agent said this, behind `agents.revision_on_answers`.

The premise, measured at 48d5016b: `UserAgent.config_rev` was read by the agents router and the evals and stamped
nowhere an answer is kept. A receipt said `{id, name}` and a stored chat turn said nothing but the `agent_id` column,
so an agent edited between two answers gave two answers that could not be told apart.

Held here:
* off, a receipt names the agent exactly as before (`{id, name}`), a stored turn's report is byte-for-byte the report
  of the same turn with no agent, and a stale `expected_rev` is ignored — the save is taken;
* on, the receipt and the turn carry `rev`, the revision of the configuration the answer RAN under (the activated
  record, not the stored one, which may have moved while it answered); an unbound answer carries no agent either way;
* on, a save or a restore sent with the revision its caller read is refused with 409 naming both revisions when the
  agent has moved since, and writes nothing; sent with the current one, or not sent, it is taken.

Hermetic: the conftest-redirected agents, history and ledger stores. No model calls, no warehouse.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

import aughor.routers.investigations as inv
from aughor.custom_agents import create_agent, delete_agent, get_agent, list_agents, update_agent
from aughor.custom_agents.context import activate_agent, answer_stamp, release_agent
from aughor.custom_agents.revisions import list_revisions
import aughor.custom_agents.store as agent_store
from aughor.db.history import get_session_turns, save_chat_turn

FLAG = "agents.revision_on_answers"


@pytest.fixture(autouse=True)
def _clean_store():
    yield
    for a in list_agents():
        delete_agent(a.id)


def _flag(monkeypatch, on: bool):
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda name: on and name == FLAG)


class _Cap:
    def __init__(self):
        self.payloads: list[dict] = []

    def artifact_write(self, kind, natural_key, payload, *, conn_id=None, canvas_id=None, lineage=None):
        self.payloads.append(payload)


@pytest.fixture
def cap_ledger(monkeypatch):
    from aughor.kernel.ledger import Ledger
    cap = _Cap()
    # On the CLASS: patching the shared default instance leaves the class's own method pinned on it when the patch is
    # undone (the undo sets the bound method back as an instance attribute), so every later test that patches
    # `Ledger.artifact_write` patches nothing for that instance.
    monkeypatch.setattr(Ledger, "artifact_write", lambda self, *a, **k: cap.artifact_write(*a, **k))
    monkeypatch.setattr(Ledger, "emit", lambda self, *a, **k: None)
    return cap


@pytest.fixture
def agent():
    return create_agent("Revision Analyst", instructions="Segment by cohort first.", doc_ids=["d1"])


def _receipt(cap) -> dict:
    inv._write_answer_receipt(kind="chat_answer", natural_key=f"chat:tc1:{uuid.uuid4().hex[:6]}",
                              question="how many orders?", sqls=["SELECT 1"], headline="",
                              schema="", connection_id="tc1-conn")
    assert cap.payloads, "the receipt should have been written"
    return cap.payloads[-1]


def _as(agent_record, fn):
    token = activate_agent(agent_record)
    try:
        return fn()
    finally:
        release_agent(token)


# ── the flag is registered off ────────────────────────────────────────────────────────

def test_the_flag_is_registered_off_by_default(monkeypatch):
    from aughor.kernel.flags import FLAG_DEFAULT, FLAG_ENV, flag_disposition, flag_enabled
    monkeypatch.delenv(FLAG_ENV[FLAG], raising=False)
    # part of the platform since 2026-10-28 (ROADMAP §3.65): on with nothing set, never a switch
    assert FLAG not in FLAG_DEFAULT and flag_disposition(FLAG) == "always_on"
    assert flag_enabled(FLAG) is True


# ── the receipt ───────────────────────────────────────────────────────────────────────

def test_off_a_receipt_names_the_agent_exactly_as_before(cap_ledger, agent, monkeypatch):
    _flag(monkeypatch, False)
    payload = _as(agent, lambda: _receipt(cap_ledger))
    assert payload["agent"] == {"id": agent.id, "name": "Revision Analyst"}


def test_on_a_receipt_names_the_revision_the_answer_ran_under(cap_ledger, agent, monkeypatch):
    _flag(monkeypatch, True)
    payload = _as(agent, lambda: _receipt(cap_ledger))
    assert payload["agent"] == {"id": agent.id, "name": "Revision Analyst", "rev": agent.config_rev}
    assert len(payload["agent"]["rev"]) == 12


def test_an_agent_edited_while_it_answered_is_stamped_with_the_revision_it_ran_under(cap_ledger, agent, monkeypatch):
    """The activated record is what built the prompt; the stored one may have moved since. Stamping the stored one
    would credit the answer to a configuration that did not give it."""
    _flag(monkeypatch, True)

    def _edit_then_answer():
        update_agent(agent.id, instructions="Ignore cohorts. Report totals only.")
        return _receipt(cap_ledger)

    payload = _as(agent, _edit_then_answer)
    stored = get_agent(agent.id)
    assert stored.config_rev != agent.config_rev
    assert payload["agent"]["rev"] == agent.config_rev


def test_an_unbound_answer_carries_no_agent_either_way(cap_ledger, monkeypatch):
    for on in (False, True):
        _flag(monkeypatch, on)
        assert "agent" not in _receipt(cap_ledger)


def test_the_revision_is_inside_the_public_receipts_signature():
    from aughor.trust.receipt import build_public_receipt, verify
    raw = {"artifact": {"id": "art_1", "kind": "chat_answer", "created_at": "2026-10-26T00:00:00Z",
                        "conn_id": "c", "payload": {"question": "q", "headline": "h",
                                                    "agent": {"id": "ua_1", "name": "A", "rev": "abc123def456"}}},
           "lineage": [], "cost": None}
    signed = build_public_receipt(raw, signed=True)
    assert signed["agent"]["rev"] == "abc123def456" and verify(signed) is True
    assert verify({**signed, "agent": {**signed["agent"], "rev": "000000000000"}}) is False


# ── the stored chat turn ──────────────────────────────────────────────────────────────

def _raw_report(inv_id: str) -> str:
    from aughor.db import history
    c = history._conn()
    try:
        return c.execute("SELECT report_json FROM investigations WHERE id = ?", (inv_id,)).fetchone()["report_json"]
    finally:
        c.close()


def _turn(session_id: str) -> str:
    return save_chat_turn(question="how many orders?", connection_id="tc1-conn", headline="12 orders",
                          sql="SELECT 1", session_id=session_id, columns=["n"], rows=[[12]])


def test_off_a_turn_the_agent_answered_is_byte_for_byte_the_unbound_turn(agent, monkeypatch):
    _flag(monkeypatch, False)
    s_agent, s_plain = f"tc1a_{uuid.uuid4().hex[:6]}", f"tc1p_{uuid.uuid4().hex[:6]}"
    with_agent = _as(agent, lambda: _turn(s_agent))
    plain = _turn(s_plain)
    assert _raw_report(with_agent) == _raw_report(plain)
    (t_agent,), (t_plain,) = get_session_turns(s_agent), get_session_turns(s_plain)
    assert "agent" not in t_agent and set(t_agent) == set(t_plain)


def test_on_a_turn_names_the_agent_and_the_revision_that_answered_it(agent, monkeypatch):
    _flag(monkeypatch, True)
    session = f"tc1on_{uuid.uuid4().hex[:6]}"
    _as(agent, lambda: _turn(session))
    (turn,) = get_session_turns(session)
    assert turn["agent"] == {"id": agent.id, "name": "Revision Analyst", "rev": agent.config_rev}
    # the turn and the receipt are stamped by one builder, so they cannot name the agent differently
    assert turn["agent"] == _as(agent, lambda: answer_stamp(agent))


def test_on_an_unbound_turn_carries_no_agent(monkeypatch):
    _flag(monkeypatch, True)
    session = f"tc1u_{uuid.uuid4().hex[:6]}"
    _turn(session)
    (turn,) = get_session_turns(session)
    assert "agent" not in turn


# ── the precondition, in the store ────────────────────────────────────────────────────

def test_a_save_against_a_stale_revision_raises_and_writes_nothing(agent):
    read_at = agent.config_rev
    update_agent(agent.id, instructions="Ignore cohorts. Report totals only.")
    moved = get_agent(agent.id)
    history_before = list_revisions(agent.id)
    # read from the module at use time: other tests reload the store, which rebinds the class
    with pytest.raises(agent_store.RevisionConflict) as caught:
        update_agent(agent.id, expected_rev=read_at, instructions="Something else entirely.", name="Renamed")
    assert caught.value.expected == read_at and caught.value.current == moved.config_rev
    assert read_at in str(caught.value) and moved.config_rev in str(caught.value)
    after = get_agent(agent.id)
    assert after.model_dump() == moved.model_dump()
    assert list_revisions(agent.id) == history_before


def test_a_save_against_the_current_revision_is_taken(agent):
    saved = update_agent(agent.id, expected_rev=agent.config_rev, instructions="Ignore cohorts.")
    assert saved.instructions == "Ignore cohorts." and saved.config_rev != agent.config_rev


# ── the precondition, at the doors ────────────────────────────────────────────────────

@pytest.fixture()
def client():
    from aughor.api import app
    return TestClient(app)


def _stale(agent) -> str:
    """The revision a caller read, made stale by an edit after the read."""
    read_at = agent.config_rev
    update_agent(agent.id, instructions="Ignore cohorts. Report totals only.")
    return read_at


def test_on_a_patch_against_a_stale_revision_is_refused_naming_both(client, agent, monkeypatch):
    _flag(monkeypatch, True)
    read_at = _stale(agent)
    current = get_agent(agent.id).config_rev
    r = client.patch(f"/agents/custom/{agent.id}", json={"instructions": "Mine.", "expected_rev": read_at})
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail["status"] == "revision_conflict"
    assert detail["expected_rev"] == read_at and detail["current_rev"] == current
    assert read_at in detail["message"] and current in detail["message"]
    assert get_agent(agent.id).instructions == "Ignore cohorts. Report totals only."


def test_on_a_patch_against_the_current_revision_or_none_is_taken(client, agent, monkeypatch):
    _flag(monkeypatch, True)
    r = client.patch(f"/agents/custom/{agent.id}", json={"instructions": "One.", "expected_rev": agent.config_rev})
    assert r.status_code == 200 and r.json()["instructions"] == "One."
    r = client.patch(f"/agents/custom/{agent.id}", json={"instructions": "Two."})
    assert r.status_code == 200 and r.json()["instructions"] == "Two."


def test_off_a_stale_revision_is_ignored_and_the_patch_is_taken(client, agent, monkeypatch):
    _flag(monkeypatch, False)
    read_at = _stale(agent)
    r = client.patch(f"/agents/custom/{agent.id}", json={"instructions": "Mine.", "expected_rev": read_at})
    assert r.status_code == 200 and r.json()["instructions"] == "Mine."


def test_on_a_restore_against_a_stale_revision_is_refused(client, agent, monkeypatch):
    _flag(monkeypatch, True)
    read_at = _stale(agent)
    r = client.post(f"/agents/custom/{agent.id}/revisions/1/restore", params={"expected_rev": read_at})
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["current_rev"] == get_agent(agent.id).config_rev
    assert get_agent(agent.id).instructions == "Ignore cohorts. Report totals only."
    r = client.post(f"/agents/custom/{agent.id}/revisions/1/restore",
                    params={"expected_rev": get_agent(agent.id).config_rev})
    assert r.status_code == 200 and r.json()["agent"]["instructions"] == "Segment by cohort first."
