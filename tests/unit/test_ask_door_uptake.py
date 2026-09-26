"""SP-15's measure — the share of held rows whose Ask door was used, from the session log.

Pinned: the ask door's request event records the object the palette was summoned from;
the meter joins it to the ledger's held rows; a row asked about that is not held is
counted apart, not as uptake; an unreadable store reports unmeasured, never zero; the
departures summary serves it.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from aughor import telemetry
from aughor.api import app
from aughor.govern.departure_store import record_departure
from aughor.obs import session_log
from aughor.obs.ask_door_uptake import ask_door_uptake

client = TestClient(app)


@pytest.fixture(autouse=True)
def _own_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_DEPARTURES_DB", str(tmp_path / "departures.db"))


def _row(id_, state):
    return record_departure(id=id_, org_id="default", kind="briefing", state=state, conn_id="c1",
                            automation_id="a1", automation_name="Daily", actor="automation:a1",
                            target="sb:#c", reasons=json.dumps(["held" if state != "departed" else ""]),
                            checks="{}", guards=json.dumps({"remeasure": "held"} if state != "departed" else {}),
                            text_preview="x", investigation_id="")


def _asked(trace: str, focus: dict | None):
    with telemetry.bind_trace(trace):
        session_log.emit(session_log.USER_REQUEST, name="ask", conn_id="c1",
                         payload={"question": "why held?", "depth": "quick",
                                  **({"focus": focus} if focus else {})})


def test_the_meter_joins_held_rows_to_the_requests_that_named_them():
    _row("held-a", "held"); _row("held-b", "held_owner"); _row("gone-c", "departed")
    _asked("t1", {"kind": "departure", "id": "held-a"})
    _asked("t2", {"kind": "departure", "id": "held-a"})        # asked twice: one row
    _asked("t3", {"kind": "departure", "id": "gone-c"})        # a departed row: apart
    _asked("t4", {"kind": "automation", "id": "a1"})           # another kind: not this meter
    _asked("t5", None)                                          # a plain ask
    out = ask_door_uptake()
    assert out["measured"] is True
    assert out["held"] == 2 and out["asked"] == 1 and out["rate"] == 0.5
    assert out["asked_about_rows_not_held"] == 1
    assert out["by_day"] and out["by_day"][0]["asked"] == 1


def test_nothing_held_is_not_a_rate():
    out = ask_door_uptake()
    assert out["measured"] is True and out["held"] == 0 and out["rate"] is None


def test_an_unreadable_store_reports_unmeasured_never_zero(monkeypatch):
    from aughor.obs import ask_door_uptake as m
    monkeypatch.setattr("aughor.govern.departure_store.list_departures",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("locked")))
    out = m.ask_door_uptake()
    assert out == {"held": None, "asked": None, "rate": None, "by_day": [], "measured": False}


def test_the_departures_summary_serves_it():
    _row("held-z", "held")
    _asked("t9", {"kind": "departure", "id": "held-z"})
    body = client.get("/departures/summary").json()
    assert body["by_state"]["held"] == 1
    assert body["ask_door"]["held"] == 1 and body["ask_door"]["asked"] == 1


def test_the_ask_door_records_the_focus_on_its_request_event():
    """The writer half: `stream_with_session_log(focus=…)` puts it on the request event."""
    import asyncio

    from aughor.routers.investigations import stream_with_session_log

    async def _body():
        yield "data: " + json.dumps({"type": "headline", "headline": "x"}) + "\n\n"

    async def _drain():
        return [c async for c in stream_with_session_log(
            _body(), question="why held?", conn_id="c1", door="ask",
            focus={"kind": "departure", "id": "held-q"})]

    asyncio.run(_drain())
    from aughor.kernel.ledger import Ledger
    reqs = Ledger.default().session_events(kind=session_log.USER_REQUEST, limit=50)
    mine = [r for r in reqs if (r.get("payload") or {}).get("question") == "why held?"]
    assert mine and mine[0]["payload"]["focus"] == {"kind": "departure", "id": "held-q"}
