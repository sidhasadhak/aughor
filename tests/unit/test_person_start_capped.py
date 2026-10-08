"""A person's own Start is capped too (the user, 2026-10-08: "any cap on your own Start").

The first build governed only what the platform spent on its own initiative; a person's Start always
ran, whatever the month's budget said. Now a run a person starts is capped at what is left of the month
under the tighter budget; when nothing is left it is refused with the reason, and runs only when the
person says to run it anyway — a choice recorded under their name.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from aughor.explorer import budget as B


def _standing(remaining, spent_out=False):
    return {"remaining": remaining, "spent_out": spent_out, "sentence": "the connection's monthly exploration "
            "budget of 50,000 tokens is spent", "held_by": "connection" if remaining is not None else None}


def test_a_persons_run_is_capped_at_what_is_left_and_uncapped_without_a_budget(monkeypatch):
    monkeypatch.setattr(B, "standing", lambda c, now=None: _standing(12_000))
    assert B.person_run("wh") == 12_000
    monkeypatch.setattr(B, "standing", lambda c, now=None: _standing(None))
    assert B.person_run("wh") is None


def test_a_spent_budget_refuses_until_the_person_says_run_it_anyway_and_records_it(monkeypatch):
    monkeypatch.setattr(B, "standing", lambda c, now=None: _standing(-500, spent_out=True))
    with pytest.raises(B.BudgetSpent) as refused:
        B.person_run("wh", by="amit")
    assert refused.value.detail()["reason"] == "budget_spent"
    emitted = []

    class _L:
        def emit(self, kind, payload, **kw):
            emitted.append((kind, payload))

    monkeypatch.setattr("aughor.kernel.ledger.Ledger.default", classmethod(lambda cls: _L()))
    assert B.person_run("wh", run_anyway=True, by="amit", what="start") is None
    assert emitted == [("exploration.budget_override", {"connection_id": "wh", "by": "amit", "what": "start",
                                                        "budget": _standing(0)["sentence"]})]


def test_the_doors_answer_409_with_the_reason_and_pass_the_cap_through(monkeypatch):
    from aughor.routers import exploration as X
    monkeypatch.setattr(B, "standing", lambda c, now=None: _standing(-1, spent_out=True))
    with pytest.raises(HTTPException) as e:
        X._person_cap("wh", False, "start")
    assert e.value.status_code == 409 and e.value.detail["reason"] == "budget_spent"

    monkeypatch.setattr(B, "standing", lambda c, now=None: _standing(9_000))
    calls = []

    async def spawn(conn_id, **kw):
        calls.append(kw.get("token_cap"))
        return {"ok": True, "reason": None, "job_id": "j"}

    monkeypatch.setattr(X, "spawn_explorer", spawn)
    monkeypatch.setattr(X, "interrupted_runs", lambda c: ["wh__a", "wh__b", "wh__c"])
    asyncio.run(X.resume_exploration("wh"))
    assert calls == [3_000, 3_000, 3_000], "Continue shares what is left between the datasets it resumes"


def test_a_start_fanned_out_over_datasets_shares_the_cap(monkeypatch):
    from aughor.routers import _shared
    monkeypatch.setattr(_shared, "explorer_refusal", lambda c: "")
    monkeypatch.setattr(_shared, "schemas_of_connection", lambda c: ["a", "b"])
    monkeypatch.setattr("aughor.kernel.agents.is_enabled", lambda agent, ws: False)   # no birth rite
    monkeypatch.setattr("aughor.workspace.store.workspace_for_connection", lambda c: None)
    caps = []

    async def spawn(conn_id, **kw):
        caps.append(kw.get("token_cap"))
        return {"ok": True}

    monkeypatch.setattr(_shared, "spawn_explorer", spawn)

    async def go():
        assert _shared.kickoff_exploration("wh", token_cap=10_000) is True
        await asyncio.sleep(0.01)

    asyncio.run(go())
    assert caps == [5_000, 5_000]
