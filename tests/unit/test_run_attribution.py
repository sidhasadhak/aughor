"""Arc TC, TC-2 — every change says what made it: the run and trace on edit history and on the action audit, read as an
object's timeline (flag `actions.run_attribution`).

Before: the edit layer recorded who, never which run (`actions/overlay.py` held no run or trace id), so an edit an
automation made read "by automation:<id>" and could not be joined to the run that made it or to what that run spent.
What these hold, through the real executor, the real automation engine and the real resolver on the seeded samples:

- the falsifier (§3.59): an edit an automation makes carries THAT run's id — and its audit row and ledger entry do too;
- a person's edit outside any run records none and says "by a person, outside any run";
- a row from before the stamp never reads as "outside any run";
- the run is bound where runs start — the ask door, the kernel's job runner, `run_automation` — innermost wins;
- an object's timeline reads edits and actions oldest first, each with its run and that run's cost, "not metered" said;
- with the flag off, every record and every read is the one written before this wave.
"""
from __future__ import annotations

import asyncio
import re
import uuid

import pytest

from aughor import telemetry
from aughor.actions import attribution as A
from aughor.actions import overlay as OVL
from aughor.actions.executor import default_object_resolver, execute_kinetic_action
from aughor.kernel.flags import flag_overrides
from tests.unit.test_object_actions import CONN, ORDER, _action, _Borrowed, _declare, db, graph  # noqa: F401 — fixtures by name
from tests.unit.test_one_row_policy_at_every_door import as_reader, sql_door  # noqa: F401 — fixtures by name
from tests.unit.test_ontology_security import secured  # noqa: F401 — fixtures by name

FLAG = A.FLAG
MARK = {"display_name": "Flag", "kind": "annotate", "risk": "low", "object_type": "order",
        "params": [{"name": "order", "kind": "object", "object_type": "order"}],
        "edits": [{"object": "order", "property": "review_status", "value": "flagged", "note": ""}]}
#: The history row's keys before TC-2 — what a read with the flag off must still return, exactly.
HISTORY_KEYS = {"id", "edit_id", "org_id", "connection_id", "object_type", "table", "column", "row_key", "event",
                "body", "previous", "note", "actor", "origin", "source", "version", "at"}
#: The action-audit payload's keys before TC-2 (`recent_audit` adds seq and at).
AUDIT_KEYS = {"seq", "at", "action", "risk", "decision", "scope", "actor", "org_id", "detail"}


@pytest.fixture(autouse=True)
def ledger(tmp_path, monkeypatch):
    """A ledger of this test's own: the action audit, the action entries and the session log a timeline reads are all
    kept there, so one test's actions never appear on the next one's object."""
    from aughor.kernel.ledger import Ledger
    led = Ledger(tmp_path / "system.db")
    monkeypatch.setattr("aughor.kernel.ledger.Ledger.default", staticmethod(lambda: led))
    return led


@pytest.fixture
def on():
    with flag_overrides({FLAG: True}):
        yield


@pytest.fixture
def off():
    with flag_overrides({FLAG: False}):
        yield


def _press(graph, *, actor: str = "ana", key: str = ORDER):  # noqa: F811
    action = _action(graph, "mark")
    return execute_kinetic_action(action, {"order": f"order:{key}"}, actor=actor, scope=CONN, approved=True,
                                  schema_name="ecommerce", resolver=default_object_resolver(action, CONN, "ecommerce"))


def _stored_run_columns() -> list[tuple]:
    c = OVL._conn()
    try:
        return [tuple(r) for r in c.execute("SELECT run_id, run_kind, trace_id FROM overlay_edit_history "
                                            "WHERE connection_id = ? ORDER BY at, version", (CONN,)).fetchall()]
    finally:
        c.close()


def _audit(decision: str = "") -> list[dict]:
    from aughor.govern.actions import recent_audit
    return [r for r in recent_audit(limit=200) if r.get("action") == "kinetic.mark" and r.get("scope") == CONN
            and (not decision or r.get("decision") == decision)]


def _entries() -> list[dict]:
    from aughor.actions.authority import executions
    return executions("mark", CONN)


def _automation():
    from aughor.automations.models import Automation, Condition, Effect
    return Automation(name="flag the order", conn_id=CONN,
                      conditions=[Condition(kind="schedule", config={"cron": "0 9 * * 1"})],
                      effects=[Effect(kind="kinetic_action", alias="flag",
                                      config={"action_id": "mark", "schema_name": "ecommerce",
                                              "params": {"order": f"order:{ORDER}"}})],
                      max_retries=0)


def _run_automation(automation):
    from aughor.automations.engine import run_automation
    return run_automation(automation, persist=False, manual=True, probe=lambda *a, **k: True,
                          sleeper=lambda _s: None, rng=lambda: 0.0)


# ── the falsifier ────────────────────────────────────────────────────────────────────

def test_an_edit_an_automation_makes_carries_that_runs_id(graph, db, on):  # noqa: F811
    """§3.59's falsifier, through the real engine and the real executor: an edit made by an automation shows its run."""
    _declare(graph, "mark", MARK)
    automation = _automation()
    run = _run_automation(automation)
    assert [e.status for e in run.effects] == ["executed"], run.effects
    rows = OVL.edit_history(CONN, object_type="order", row_key=ORDER)
    assert len(rows) == 1
    row = rows[0]
    assert (row["run_id"], row["run_kind"], row["trace_id"]) == (run.id, "automation", run.id)
    assert row["run"] == {"id": run.id, "kind": "automation", "trace_id": run.id}
    assert row["actor"] == f"automation:{automation.id}"
    assert row["said"] == f"by automation:{automation.id}, through an automation (run {run.id[:8]})"
    # …and the action audit and the action's ledger entry name the same run
    executed = _audit("executed")
    assert executed and (executed[0]["run_id"], executed[0]["run_kind"], executed[0]["trace_id"]) == (
        run.id, "automation", run.id)
    entry = _entries()[0]
    assert (entry["run_id"], entry["run_kind"], entry["trace_id"]) == (run.id, "automation", run.id)


def test_an_adopted_monitor_runs_as_a_monitor_and_the_innermost_run_wins(graph, db, on):  # noqa: F811
    """The run kind follows the automation (a monitor adopted as one reads `monitor`), and a run started inside another
    run — here the scheduler's job — names itself, not the run around it, which is restored on the way out."""
    from aughor.automations.adopt import MONITOR_PREFIX
    _declare(graph, "mark", MARK)
    monitor = _automation().model_copy(update={"id": f"{MONITOR_PREFIX}m1"})
    with telemetry.bind_run("the-tick-job", "agent"):
        run = _run_automation(monitor)
        assert telemetry.current_run() == ("the-tick-job", "agent")
    row = OVL.edit_history(CONN, object_type="order", row_key=ORDER)[0]
    assert (row["run_id"], row["run_kind"], row["trace_id"]) == (run.id, "monitor", run.id)
    assert row["run_said"] == f"through a monitor (run {run.id[:8]})"


# ── a person, outside any run ────────────────────────────────────────────────────────

def test_a_persons_edit_outside_any_run_records_none_and_says_so(graph, db, on):  # noqa: F811
    _declare(graph, "mark", MARK)
    assert telemetry.current_run() == ("", "")
    assert _press(graph).status == "executed"
    OVL.withdraw_edit(OVL.object_edits(CONN)[0].id, CONN, actor="ben")
    rows = OVL.edit_history(CONN, object_type="order", row_key=ORDER)
    assert [(r["event"], r["run_kind"], r["run_id"], r["run"]) for r in rows] == [
        ("withdrawn", A.OUTSIDE, "", None), ("set", A.OUTSIDE, "", None)]
    assert [r["said"] for r in rows] == ["by a person, outside any run"] * 2
    assert _audit("executed")[0]["run_kind"] == A.OUTSIDE


def test_a_machine_outside_any_run_is_named_never_called_a_person():
    said = A.describe({"run_kind": A.OUTSIDE, "actor": "agent:autonomy"})["said"]
    assert said == "by agent:autonomy, outside any run"


def test_a_row_from_before_the_stamp_never_reads_as_outside_any_run(graph, db):  # noqa: F811
    _declare(graph, "mark", MARK)
    with flag_overrides({FLAG: False}), telemetry.bind_run("a-run", "automation"):
        _press(graph)
    with flag_overrides({FLAG: True}):
        row = OVL.edit_history(CONN, object_type="order", row_key=ORDER)[0]
    assert (row["run"], row["run_recorded"]) == (None, False)
    assert row["run_said"] == "which run made it was not recorded"


# ── where runs start ─────────────────────────────────────────────────────────────────

def test_the_ask_door_binds_its_turn_as_a_run_named_by_its_trace():
    from aughor.routers.investigations import stream_with_session_log
    seen: list[tuple] = []

    async def inner():
        seen.append((telemetry.current_run(), telemetry.current_trace_id()))
        yield "data: {}\n\n"

    async def drain():
        async for _ in stream_with_session_log(inner(), question="how many orders?", conn_id=CONN):
            pass

    asyncio.run(drain())
    (run_id, kind), trace = seen[0]
    assert kind == "chat" and run_id and run_id == trace
    assert telemetry.current_run() == ("", "")


@pytest.mark.parametrize("job_kind,run_kind", [("monitor", "monitor"), ("profile", "agent")])
def test_a_kernel_job_is_its_own_run(tmp_path, monkeypatch, job_kind, run_kind):
    from datetime import datetime, timezone

    from aughor.kernel.jobs import JobKernel, JobState
    from aughor.kernel.ledger import Ledger
    led = Ledger(tmp_path / "system.db")
    monkeypatch.setattr("aughor.kernel.ledger.Ledger.default", staticmethod(lambda: led))
    job_id = f"job-{uuid.uuid4().hex[:6]}"
    led.job_insert({"id": job_id, "kind": job_kind, "state": JobState.PENDING, "attempt": 1,
                    "created_at": datetime.now(timezone.utc).isoformat()})
    seen: list[tuple] = []

    async def _work():
        seen.append(telemetry.current_run())

    with telemetry.bind_run("asking-turn", "chat"):           # a job submitted from a turn is still its own run
        asyncio.run(JobKernel(led)._run(job_id, _work, None))
    assert seen == [(job_id, run_kind)]


# ── one object's timeline ────────────────────────────────────────────────────────────

def _price(monkeypatch):
    from aughor.obs import usage
    monkeypatch.setitem(usage.PRICES, ("tc2-test", "tc2-model"), usage.Price(1.0, 2.0, "2026-10-26"))
    usage.price_for.cache_clear()


def test_the_timeline_reads_every_change_oldest_first_with_its_run_and_cost(graph, db, client, monkeypatch, on):  # noqa: F811
    from aughor.obs import session_log
    _declare(graph, "mark", MARK)
    _price(monkeypatch)
    _press(graph, actor="ana")                                            # a person, outside any run
    trace = f"t-{uuid.uuid4().hex[:8]}"
    with telemetry.bind_trace(trace), telemetry.bind_run(trace, "chat"):
        # the turn spent two priced model calls, then the edit was withdrawn inside it
        session_log.emit(session_log.LLM_CALL, name="answer", provider="tc2-test", model="tc2-model",
                         prompt_tokens=1_000_000, completion_tokens=0)
        session_log.emit(session_log.LLM_CALL, name="answer", provider="tc2-test", model="tc2-model",
                         prompt_tokens=0, completion_tokens=500_000)
        OVL.withdraw_edit(OVL.object_edits(CONN)[0].id, CONN, actor="ana")
    with telemetry.bind_run("lost-run", "automation"):                     # a run the session log never saw
        _press(graph, actor="automation:a1")
    other = str(db.execute("k", f"SELECT order_id FROM orders WHERE order_id <> '{ORDER}' LIMIT 1").rows[0][0])
    _press(graph, actor="ben", key=other)                                 # another order's change is not on this one
    got = client.get("/actions/edits/timeline", params={"connection_id": CONN, "object_type": "order",
                                                         "row_key": ORDER})
    assert got.status_code == 200, got.text
    timeline = got.json()["timeline"]
    # oldest first, to the microsecond — all five land inside one second here; an action's entry is booked once it ran,
    # so it follows the edit it made
    assert [(e["what"], e.get("event") or e.get("status")) for e in timeline] == [
        ("edit", "set"), ("action", "executed"), ("edit", "withdrawn"), ("edit", "set"), ("action", "executed")]
    assert [e["said"] for e in timeline] == [
        "by a person, outside any run", "by a person, outside any run",
        f"by a person, through a question asked (run {trace[:8]})",
        "by automation:a1, through an automation (run lost-run)",
        "by automation:a1, through an automation (run lost-run)"]
    cost = timeline[2]["run"]["cost"]
    assert (cost["metered"], cost["model_calls"], cost["tokens"], cost["usd"]) == (True, 2, 1_500_000, 2.0)
    assert cost["said"] == "$2.0000 over 2 model calls"
    lost = timeline[3]["run"]["cost"]
    assert (lost["metered"], lost["usd"]) == (False, None)
    assert lost["said"] == "not metered: no trace was kept for this run"


def test_the_timeline_is_read_as_the_edit_history_is(sql_door, graph, db, as_reader, monkeypatch, on):  # noqa: F811
    """Arc ED, ED-1 holds here too: an object outside the reader's rows has its edits AND its actions withheld, and the
    count said — a timeline is not a way round the row policy the edit history keeps."""
    monkeypatch.setattr("aughor.db.connection.open_connection_for", lambda conn: _Borrowed(db))
    _declare(graph, "mark", MARK)
    refunded = str(db.execute("k", "SELECT order_id FROM orders WHERE status = 'refunded' LIMIT 1").rows[0][0])
    as_reader("ben")                                                        # support sees refunded orders
    assert _press(graph, actor="ben", key=refunded).status == "executed"
    from aughor.routers.actions import get_object_timeline
    seen = get_object_timeline(object_type="order", row_key=refunded, connection_id=CONN)
    assert [e["what"] for e in seen["timeline"]] == ["edit", "action"] and "withheld" not in seen
    as_reader("ana")                                                        # fulfilment does not
    held = get_object_timeline(object_type="order", row_key=refunded, connection_id=CONN)
    assert held["timeline"] == []
    assert held["withheld"] == [{"object_type": "Order", "count": 2, "why": held["withheld"][0]["why"]}]


def test_not_metered_is_said_never_zero():
    gone = A.run_cost({"id": "r1", "kind": "automation", "trace_id": f"t-{uuid.uuid4().hex}"})
    assert gone["metered"] is False and gone["usd"] is None and gone["model_calls"] is None
    assert gone["said"].startswith("not metered: the session log holds nothing for this run")


def test_an_unpriced_call_is_counted_beside_the_dollars(monkeypatch):
    from aughor.obs import session_log
    _price(monkeypatch)
    trace = f"t-{uuid.uuid4().hex[:8]}"
    with telemetry.bind_trace(trace):
        session_log.emit(session_log.LLM_CALL, name="a", provider="tc2-test", model="tc2-model",
                         prompt_tokens=1_000_000, completion_tokens=0)
        session_log.emit(session_log.LLM_CALL, name="b", provider="nobody", model="unpriced",
                         prompt_tokens=10, completion_tokens=10)
    cost = A.run_cost({"id": trace, "kind": "chat", "trace_id": trace})
    assert (cost["usd"], cost["unpriced_calls"]) == (1.0, 1)
    assert cost["said"] == "at least $1.0000 over 2 model calls — 1 without a price or a token count"


# ── off: byte-identical ──────────────────────────────────────────────────────────────

def test_off_every_record_and_read_is_the_one_written_before(graph, db, client, off):  # noqa: F811
    _declare(graph, "mark", MARK)
    with telemetry.bind_trace("t-off"), telemetry.bind_run("r-off", "automation"):
        assert _press(graph).status == "executed"
        OVL.withdraw_edit(OVL.object_edits(CONN)[0].id, CONN, actor="ben")
    rows = OVL.edit_history(CONN, object_type="order", row_key=ORDER)
    assert [set(r) for r in rows] == [HISTORY_KEYS, HISTORY_KEYS]
    assert all(re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00", r["at"]) for r in rows)  # to the second
    assert _stored_run_columns() == [("", "", ""), ("", "", "")]           # nothing stamped, though a run was in force
    assert [set(r) for r in _audit()] == [AUDIT_KEYS, AUDIT_KEYS]                  # executed, and the accept
    assert not {"run_id", "run_kind", "trace_id"} & set(_entries()[0])
    history = client.get("/actions/edits/history", params={"connection_id": CONN, "row_key": ORDER}).json()
    assert [set(h) for h in history["history"]] == [HISTORY_KEYS, HISTORY_KEYS]
    timeline = client.get("/actions/edits/timeline", params={"connection_id": CONN, "object_type": "order",
                                                              "row_key": ORDER})
    assert timeline.status_code == 404 and timeline.json()["detail"] == "An object's timeline is off on this install."
