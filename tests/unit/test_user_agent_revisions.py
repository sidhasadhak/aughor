"""Wave H6 — an agent's pass chip must name the configuration it measured.

The defect this pins, measured on main before the fix: an agent whose instructions had
been INVERTED ("segment by cohort first" → "ignore cohorts, report totals only") and whose
entire retrieval scope had been stripped (documents, packs and schema all cleared) still
displayed ``passed 5/5``. The number was real once — it was about a different agent. The
evaluate route's own docstring already told users to "run it after editing instructions or
documents to catch regressions", which is the product admitting the chip goes stale and
asking the user to remember.

So the chip is never deleted on edit — that would destroy real evidence about what the
agent used to do — it is LABELLED, and ``eval_basis`` is the label. The revision is a
digest of the governing configuration rather than a save counter, which is what makes the
labelling exact in both directions: edit away and the chip goes stale, edit back to a
measured configuration and it is current again, because it genuinely is that agent again.

Hermetic: the conftest-redirected agents DB and kernel ledger; no LLM, no warehouse.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from aughor.custom_agents import create_agent, delete_agent, get_agent, list_agents, update_agent
from aughor.custom_agents.models import EVAL_CURRENT, EVAL_NONE, EVAL_STALE, EVAL_UNKNOWN
from aughor.custom_agents.revisions import list_revisions, record_revision, revision_config
from aughor.custom_agents.store import record_eval

ORIGINAL = "Segment by cohort first."
INVERTED = "Ignore cohorts. Report totals only."


@pytest.fixture(autouse=True)
def _clean_store():
    yield
    for a in list_agents():
        delete_agent(a.id)


def _agent(**kw):
    base = dict(name="Probe Analyst", instructions=ORIGINAL, doc_ids=["doc-1"],
                pack_ids=["pack-a"], schema_scope="luxexperience")
    base.update(kw)
    return create_agent(**base)


def _passed(agent_id, passed=5, total=5):
    record_eval(agent_id, {"passed": passed, "total": total, "at": "2026-07-30T00:00:00Z"})
    return get_agent(agent_id)


@pytest.fixture()
def client():
    from aughor.api import app
    return TestClient(app)


def _flag_on(monkeypatch):
    import aughor.kernel.flags as flags
    monkeypatch.setattr(flags, "flag_enabled",
                        lambda name: name == "agents.user_defined")


# ── the configuration fingerprint ────────────────────────────────────────────────

def test_reordering_bound_documents_is_not_a_different_agent():
    """A digest over a SET rendered as a list would make drag-and-drop look like an edit."""
    one = _agent(doc_ids=["a", "b"], pack_ids=["p", "q"])
    two = _agent(doc_ids=["b", "a"], pack_ids=["q", "p"])
    assert one.config_rev == two.config_rev


def test_only_the_fields_that_change_behaviour_change_the_revision():
    agent = _agent()
    rev = agent.config_rev

    assert update_agent(agent.id, name="Renamed").config_rev == rev, \
        "a rename changed the configuration fingerprint"
    assert update_agent(agent.id, enabled=False).config_rev == rev, \
        "disabling an agent changed the configuration fingerprint"

    for field, value in (("instructions", INVERTED), ("schema_scope", "other"),
                         ("doc_ids", ["doc-9"]), ("pack_ids", ["pack-z"]),
                         ("connection_id", "conn-x")):
        moved = update_agent(agent.id, **{field: value})
        assert moved.config_rev != rev, f"changing {field} did not change the fingerprint"
        rev = moved.config_rev


# ── the defect ───────────────────────────────────────────────────────────────────

def test_a_chip_earned_before_an_edit_is_labelled_stale_and_kept():
    agent = _agent()
    assert get_agent(agent.id).eval_basis == EVAL_NONE

    assert _passed(agent.id).eval_basis == EVAL_CURRENT

    update_agent(agent.id, instructions=INVERTED)
    after = get_agent(agent.id)

    assert after.eval_basis == EVAL_STALE
    # Kept, not deleted: it is true evidence about a configuration that really existed.
    assert after.last_eval["passed"] == 5 and after.last_eval["total"] == 5


def test_stripping_the_retrieval_scope_also_stales_the_chip():
    """The original defect was not only about instructions — an agent that lost every
    document and pack it was graded with kept its chip too."""
    agent = _agent()
    _passed(agent.id)

    update_agent(agent.id, doc_ids=[], pack_ids=[], schema_scope="")

    assert get_agent(agent.id).eval_basis == EVAL_STALE


def test_editing_back_to_a_measured_configuration_makes_the_chip_current_again():
    """The payoff of a content digest over a save counter: this agent IS the one that was
    measured, so pretending otherwise would be its own kind of dishonesty."""
    agent = _agent()
    _passed(agent.id)
    update_agent(agent.id, instructions=INVERTED)
    assert get_agent(agent.id).eval_basis == EVAL_STALE

    update_agent(agent.id, instructions=ORIGINAL)

    assert get_agent(agent.id).eval_basis == EVAL_CURRENT


def test_a_chip_written_before_revisions_existed_is_unknown_not_current():
    """Rows already in the wild carry no config_rev. Calling those current would launder
    exactly the defect this wave fixed; calling them stale would libel agents nobody has
    touched. Neither can be shown, so neither is claimed."""
    agent = _agent()
    from aughor.custom_agents.store import _connect, _now
    legacy = json.dumps({"passed": 5, "total": 5, "at": "2026-07-01T00:00:00Z"})
    with _connect() as conn:
        conn.execute("UPDATE user_agents SET last_eval = ?, updated_at = ? WHERE id = ?",
                     (legacy, _now(), agent.id))

    assert get_agent(agent.id).eval_basis == EVAL_UNKNOWN


# ── the history ──────────────────────────────────────────────────────────────────

def test_an_agent_is_born_with_a_revision():
    agent = _agent()
    revs = list_revisions(agent.id)
    assert len(revs) == 1 and revs[0]["config_rev"] == agent.config_rev
    assert revs[0]["config"]["instructions"] == ORIGINAL


def test_the_history_records_edits_and_ignores_non_edits():
    agent = _agent()
    update_agent(agent.id, instructions=INVERTED)
    update_agent(agent.id, name="Renamed")            # not a configuration change
    update_agent(agent.id, enabled=False)             # not a configuration change
    assert record_revision(get_agent(agent.id)) is None, "an unchanged save minted a revision"

    revs = list_revisions(agent.id)
    assert [r["version"] for r in revs] == [2, 1]
    assert revs[0]["config"]["instructions"] == INVERTED


def test_restore_puts_the_configuration_back_without_rewinding_history():
    agent = _agent()
    update_agent(agent.id, instructions=INVERTED)
    original = revision_config(agent.id, 1)
    assert original["instructions"] == ORIGINAL

    update_agent(agent.id, **original)

    restored = get_agent(agent.id)
    assert restored.instructions == ORIGINAL
    assert restored.config_rev == agent.config_rev
    # Append-only: three entries, not a rewind back to one.
    assert [r["version"] for r in list_revisions(agent.id)] == [3, 2, 1]


def test_there_is_no_revision_for_an_unknown_version():
    agent = _agent()
    assert revision_config(agent.id, 99) is None


# ── the routes ───────────────────────────────────────────────────────────────────

def test_the_revisions_route_reports_the_current_rev_and_the_chip_basis(client, monkeypatch):
    _flag_on(monkeypatch)
    agent = _agent()
    _passed(agent.id)
    update_agent(agent.id, instructions=INVERTED)

    body = client.get(f"/agents/custom/{agent.id}/revisions").json()

    assert body["current_rev"] == get_agent(agent.id).config_rev
    assert body["eval_basis"] == EVAL_STALE
    assert [r["version"] for r in body["revisions"]] == [2, 1]


def test_restoring_through_the_route_re_earns_a_measured_chip(client, monkeypatch):
    _flag_on(monkeypatch)
    agent = _agent()
    _passed(agent.id)
    update_agent(agent.id, instructions=INVERTED)
    assert get_agent(agent.id).eval_basis == EVAL_STALE

    resp = client.post(f"/agents/custom/{agent.id}/revisions/1/restore")

    assert resp.status_code == 200
    body = resp.json()
    assert body["restored_from"] == 1
    assert body["agent"]["instructions"] == ORIGINAL
    assert body["agent"]["eval_basis"] == EVAL_CURRENT


def test_restoring_a_version_that_does_not_exist_is_a_404(client, monkeypatch):
    _flag_on(monkeypatch)
    agent = _agent()
    assert client.post(f"/agents/custom/{agent.id}/revisions/99/restore").status_code == 404
    assert client.get("/agents/custom/nope/revisions").status_code == 404


def test_the_revision_routes_404_when_the_flag_is_off(client, monkeypatch):
    import aughor.kernel.flags as flags
    monkeypatch.setattr(flags, "flag_enabled", lambda name: False)
    assert client.get("/agents/custom/anything/revisions").status_code == 404
    assert client.post("/agents/custom/anything/revisions/1/restore").status_code == 404
