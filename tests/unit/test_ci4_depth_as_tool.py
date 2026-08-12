"""CI-4 — Analysis Mode adopts the conversation, one carve-out at a time.

Two carve-outs dissolve here: a seeded-SQL turn and a dossier drill stop bypassing the
converse body and instead hand their origin finding TO it, rendered by the same code
the deep path anchors on. And the conversation gains the `deep_analysis` tool — depth
becomes something the conversation reaches for, through Wave H5's neutral runner (the
one door), never a second pipeline.

The two carve-outs that remain are asserted too, with their reasons: an explicit
escalation is a command, not a question; and a router-chosen deep route keeps its
dedicated body until investigation frames can stream through a converse turn.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from aughor.agent import converse_tools as ct
from aughor.routers import investigations as inv


def _req(**kw):
    defaults = dict(escalate=False, insight_id=None, seed_sql=None, seed_context="")
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def _route(depth="quick", forced=None):
    return SimpleNamespace(depth=depth, forced=forced)


@pytest.fixture
def _flag_on(monkeypatch):
    monkeypatch.setenv("AUGHOR_ASK_CONVERSE", "1")


# ── eligibility: the carve-outs that dissolved, and the two that remain ──────────────

def test_a_seeded_sql_turn_is_no_longer_a_bypass(_flag_on):
    """seed_sql used to disqualify converse — and the quick body then IGNORED the seed
    entirely. The conversation takes the turn (and the seed rides in as context)."""
    assert inv._converse_eligible(_req(seed_sql="SELECT 1"), _route("quick")) is True


def test_a_dossier_drill_is_taken_by_the_conversation(_flag_on):
    """insight_id forces route.depth='deep' with forced='dossier' — deep by ROUTING
    convention, not because the user asked for a report. The conversation takes it,
    holding the finding as context and the deep_analysis tool in reserve."""
    assert inv._converse_eligible(
        _req(insight_id="i1"), _route("deep", forced="dossier")) is True


def test_an_explicit_escalation_keeps_the_investigation_body(_flag_on):
    """A command, not a question — re-deciding it with a model turn would be latency
    with no information."""
    assert inv._converse_eligible(
        _req(escalate=True), _route("deep", forced="deep_flag")) is False


def test_a_router_chosen_deep_route_keeps_its_body(_flag_on):
    """Until the investigation's frames can stream through a converse turn (CI-6a's
    renderer), the dedicated body is the better surface for a genuinely deep question."""
    assert inv._converse_eligible(_req(), _route("deep")) is False


def test_the_flag_still_gates_everything(monkeypatch):
    monkeypatch.delenv("AUGHOR_ASK_CONVERSE", raising=False)
    assert inv._converse_eligible(_req(seed_sql="SELECT 1"), _route("quick")) is False


# ── the origin finding rides into the conversation ───────────────────────────────────

@pytest.mark.anyio
async def test_the_origin_finding_is_handed_to_the_conversation(monkeypatch):
    """One source of truth, two readers: the SAME _build_origin_finding the deep path
    anchors on renders the context the conversation receives."""
    async def _fake_origin(conn_id, insight_id, seed_context, seed_sql):
        return {"finding": "March revenue tripled", "sql": "SELECT 1"}

    monkeypatch.setattr(inv, "_build_origin_finding", _fake_origin)

    prose = await inv._origin_prose_for(_req(insight_id="i1"), "c1")

    assert "March revenue tripled" in prose
    assert "ALREADY ESTABLISHED" in prose, "the deep path's own rendering must serve"


@pytest.mark.anyio
async def test_a_cold_start_turn_carries_no_origin(monkeypatch):
    async def _explodes(*a):  # pragma: no cover — must never be called
        raise AssertionError("origin resolution ran for a cold-start turn")

    monkeypatch.setattr(inv, "_build_origin_finding", _explodes)

    assert await inv._origin_prose_for(_req(), "c1") == ""


@pytest.mark.anyio
async def test_an_unresolvable_origin_degrades_not_fails(monkeypatch):
    """A finding that cannot be resolved must degrade the turn to a plain
    conversation — never fail it."""
    async def _boom(*a):
        raise RuntimeError("dossier store down")

    monkeypatch.setattr(inv, "_build_origin_finding", _boom)

    assert await inv._origin_prose_for(_req(insight_id="gone"), "c1") == ""


# ── the deep_analysis tool ───────────────────────────────────────────────────────────

def test_deep_analysis_joins_the_converse_roster():
    assert "deep_analysis" in [s.name for s in ct.converse_tools("c1")]


def test_the_tool_submits_through_the_one_door(monkeypatch):
    """The body is Wave H5's neutral runner — the same build_ask_stream door every
    caller uses — and the return value is the HANDLE, because a submitted run's
    report does not exist yet and pretending otherwise would be the tool lying."""
    from aughor import runners

    monkeypatch.setattr("aughor.licensing.has_capability",
                        lambda cap, **kw: True)
    seen = {}

    def _fake_run(req, *, caller=""):
        seen["question"] = req.question
        seen["connection_id"] = req.connection_id
        seen["caller"] = caller
        return runners.InvestigationRun("executed", "job j1", job_id="j1",
                                        basis="submitted")

    monkeypatch.setattr("aughor.runners.run_investigation", _fake_run)

    out = ct.deep_analysis("c1", {"question": "why did margin fall?"})

    assert seen == {"question": "why did margin fall?", "connection_id": "c1",
                    "caller": "converse"}
    assert out["status"] == "executed" and out["job_id"] == "j1"
    assert "background" in out["note"], "the model must be able to say where it lands"


def test_a_missing_capability_is_a_value_not_a_silent_downgrade(monkeypatch):
    """The route silently downgrades deep→quick without the licence; a TOOL named
    deep_analysis that did the same would be lying about itself."""
    monkeypatch.setattr("aughor.licensing.has_capability",
                        lambda cap, **kw: False)

    out = ct.deep_analysis("c1", {"question": "why?"})

    assert out["status"] == "unavailable"
    assert "plan" in out["reason"]


def test_a_refused_run_reports_its_sentence(monkeypatch):
    from aughor import runners

    monkeypatch.setattr("aughor.licensing.has_capability",
                        lambda cap, **kw: True)
    monkeypatch.setattr(
        "aughor.runners.run_investigation",
        lambda req, caller="": runners.InvestigationRun(
            "refused", "this agent may not investigate"))

    out = ct.deep_analysis("c1", {"question": "why?"})

    assert out["status"] == "refused"
    assert out["reason"] == "this agent may not investigate"


def test_no_question_is_an_answer_not_a_crash():
    assert "error" in ct.deep_analysis("c1", {})
