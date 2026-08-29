"""The chat door reaches the explore wave — the seam a live soak found dark.

The wave (multi-cut landscape scan) was BUILT and its /ask auto-path routing was
CORRECT, yet no chat turn could reach it: the Agent chip sends mode="investigate",
which takes /investigate — a door that pinned ``requested_mode`` without ever
consulting the wide detector (found live 2026-08-29: a textbook wide question ran
as a single deep analysis with `explore.route_wide` overridden ON). Built-but-
unreachable is the failure mode this repo keeps rediscovering, so the last test
here drives the REAL endpoint handler and fails the moment the door stops passing
the wide verdict through.

Hermetic: routing is deterministic (no model in the path); the flag rides
``flag_overrides``; the job-streamed body is spied, never run.
"""
from __future__ import annotations

import pytest

from aughor.kernel.flags import flag_overrides
from aughor.routers.investigations import (
    InvestigateRequest,
    _investigate_requested_mode,
    investigate,
)

WIDE = "Characterize how discount varies across the business"


def _req(**kw) -> InvestigateRequest:
    return InvestigateRequest(question=kw.pop("question", WIDE), **kw)


def test_wide_question_with_flag_routes_explore():
    with flag_overrides({"explore.route_wide": True}):
        assert _investigate_requested_mode(_req()) == "explore"


def test_flag_off_keeps_the_pin():
    # The wide check runs first and is pure; with the flag off the door behaves
    # byte-identically to before this seam existed.
    assert _investigate_requested_mode(_req()) == "investigate"


def test_causal_why_stays_a_single_investigation():
    with flag_overrides({"explore.route_wide": True}):
        assert _investigate_requested_mode(
            _req(question="Why did revenue dip most recently, and what drove it?")
        ) == "investigate"


def test_seeded_turns_keep_the_pin():
    # A finding drill, seed SQL, or an escalation anchors ONE question — never a
    # landscape, no matter how the question is phrased.
    with flag_overrides({"explore.route_wide": True}):
        assert _investigate_requested_mode(_req(seed_sql="SELECT 1")) == "investigate"
        assert _investigate_requested_mode(_req(insight_id="f-1")) == "investigate"
        assert _investigate_requested_mode(_req(escalate=True)) == "investigate"


@pytest.mark.anyio
async def test_the_chat_door_hands_the_wave_the_wide_verdict(monkeypatch):
    # THE seam: drive the real handler and assert the mode reaches the dispatch —
    # this is the test that fails while the wave is built but unreachable.
    from aughor.routers import investigations as inv

    seen: dict = {}

    def spy(question, connection_id, request, **kw):
        seen.update(kw)

        async def _gen():
            yield "data: {}\n\n"
        return _gen()

    monkeypatch.setattr(inv, "_investigation_job_streamed", spy)
    monkeypatch.setattr(inv, "_resolve_conn", lambda req: "conn-test")
    with flag_overrides({"explore.route_wide": True}):
        await investigate(_req(), request=None)

    assert seen.get("requested_mode") == "explore"
