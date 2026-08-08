"""Wave CR1–CR4 — the control room's read routes are views, and honest ones.

Each test seeds the store the route folds from (the isolated test stores — see
conftest's AUGHOR_*_DB env) and asserts the response's honesty properties: the
empty state names the flag, the kind vocabulary comes from the data, charter
and persona rows are labelled, the needs-human count equals the sum of its
sources, and unmetered runs are counted rather than rendered as zero.
"""
from __future__ import annotations

import pytest

from aughor.kernel.ledger import Ledger


@pytest.fixture()
def ledger() -> Ledger:
    return Ledger.default()


def _seed_trace(ledger: Ledger, trace_id: str, *, agent_id: str | None = None) -> None:
    rows = [
        {"trace_id": trace_id, "kind": "user_request", "name": "ask",
         "payload": {"question": f"q for {trace_id}"}, "agent_id": agent_id},
        {"trace_id": trace_id, "kind": "tool_call", "name": "sql.execute",
         "span_id": f"{trace_id}-s1", "agent_id": agent_id},
        {"trace_id": trace_id, "kind": "tool_call_result", "name": "sql.execute",
         "span_id": f"{trace_id}-s1", "ok": True, "duration_ms": 12.5, "row_count": 3,
         "agent_id": agent_id},
        {"trace_id": trace_id, "kind": "llm_call", "name": "m1", "provider": "openrouter",
         "model": "m1:free", "ok": True, "duration_ms": 900.0, "prompt_tokens": 100,
         "completion_tokens": 20, "total_tokens": 120, "agent_id": agent_id},
        {"trace_id": trace_id, "kind": "final_response", "name": "ask", "ok": True,
         "duration_ms": 1500.0, "payload": {"headline": "H"}, "agent_id": agent_id},
    ]
    for r in rows:
        ledger.session_event_insert(r)


# ── CR1: traces ──────────────────────────────────────────────────────────────────

def test_trace_list_and_waterfall_render_seeded_events(client, ledger):
    _seed_trace(ledger, "tr-cr1")

    listing = client.get("/traces").json()
    assert listing["measured"] is True
    assert any(t["trace_id"] == "tr-cr1" for t in listing["traces"])

    trace = client.get("/traces/tr-cr1").json()
    assert trace["question"] == "q for tr-cr1"
    assert trace["ok"] is True
    assert [e["kind"] for e in trace["events"]] == [
        "user_request", "tool_call", "tool_call_result", "llm_call", "final_response"]
    # The span tree pairs entry/exit rows and carries the real columns.
    (span,) = trace["spans"]
    assert span["name"] == "sql.execute" and span["ok"] is True
    assert span["duration_ms"] == 12.5 and span["row_count"] == 3
    # llm_call rows have no span id — they are trace-level events, never
    # fabricated into the tree.
    assert all(s["name"] != "m1" for s in trace["spans"])


def test_unknown_trace_is_404(client):
    assert client.get("/traces/tr-nope").status_code == 404


def test_an_empty_store_is_a_confident_empty(client, ledger):
    """Recording is permanent (the flag was hardwired 2026-08-01), so a quiet store
    means nothing happened — never "something was watching but switched off"."""
    ledger.session_events_clear()

    assert client.get("/traces/tr-any").status_code == 404
    listing = client.get("/traces").json()
    assert listing["measured"] is True and listing["traces"] == []


# ── CR2: activity ────────────────────────────────────────────────────────────────

def test_activity_filters_and_reports_only_emitted_kinds(client, ledger):
    ledger.session_events_clear()
    _seed_trace(ledger, "tr-cr2a", agent_id="ua_x")
    _seed_trace(ledger, "tr-cr2b")
    ledger.session_event_insert({"trace_id": "tr-cr2b", "kind": "execution_error",
                                 "name": "ask", "ok": False, "error_class": "Boom"})

    body = client.get("/activity").json()
    assert body["measured"] is True
    # The vocabulary is the data's, and nothing else.
    assert set(body["kinds"]) == {"user_request", "tool_call", "tool_call_result",
                                  "llm_call", "final_response", "execution_error"}

    errors = client.get("/activity", params={"errors_only": True}).json()["events"]
    assert errors and all(e["ok"] is False for e in errors)

    scoped = client.get("/activity", params={"agent_id": "ua_x"}).json()["events"]
    assert scoped and all(e["agent_id"] == "ua_x" for e in scoped)

    paged = client.get("/activity", params={"limit": 3}).json()["events"]
    assert len(paged) == 3


# ── CR3: fleet ───────────────────────────────────────────────────────────────────

def test_fleet_labels_rows_and_counts_unmetered_runs(client, ledger):
    import json as _json
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    ledger.job_insert({"id": "job-cr3-1", "kind": "investigation", "state": "SUCCEEDED",
                       "attempt": 1, "created_at": now})
    ledger.job_update("job-cr3-1",
                      metrics=_json.dumps({"total_tokens": 500, "query_count": 4}))
    ledger.job_insert({"id": "job-cr3-2", "kind": "investigation", "state": "FAILED",
                       "attempt": 1, "created_at": now})

    body = client.get("/control-room/fleet").json()
    kinds = {r["kind"] for r in body["rows"]}
    assert kinds <= {"charter", "persona"}
    analyst = next(r for r in body["rows"] if r["id"] == "analyst")
    assert analyst["kind"] == "charter" and analyst["spend_source"] == "job_metering"
    assert analyst["runs"] >= 2
    assert analyst["metered_runs"] >= 1
    assert analyst["unmetered_runs"] >= 1, "a run with no metrics is counted, not zeroed"
    assert body["tiles"]["concurrency"]["max_concurrent_jobs"] >= 1
    assert "exploration" in body["tiles"]["concurrency"]["unbounded_kinds"]


def test_fleet_orphaned_restarts_are_not_agent_errors(client, ledger):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    ledger.job_insert({"id": "job-cr3-orphan", "kind": "profile", "state": "FAILED",
                       "attempt": 1, "created_at": now})
    ledger.job_update("job-cr3-orphan", error="server restart (orphaned)")
    # Wave 4 / 4.1b — the real shape an orphaned JOB now takes. The error-string
    # match above never fired for a job (that wording belongs to investigations), so
    # every restart-killed job was landing in `failed`; the terminal status is the
    # authority now, and a key that must equal a whole sentence is how a guard goes
    # blind.
    ledger.job_insert({"id": "job-cr3-interrupted", "kind": "profile",
                       "state": "INTERRUPTED", "attempt": 1, "created_at": now})
    ledger.job_update("job-cr3-interrupted",
                      error="lease lapsed (orphaned) — its result is uncertain "
                            "and was not replayed")

    body = client.get("/control-room/fleet").json()
    curator = next(r for r in body["rows"] if r["id"] == "curator")
    assert curator["orphaned"] >= 2, "both the legacy and the status-based orphan count"
    assert curator["failed"] == 0, "an orphaned restart must not read as an agent failure"
    assert body["tiles"]["orphaned_runs"] >= 2


# ── CR4: needs a human ───────────────────────────────────────────────────────────

def test_needs_human_count_equals_the_sum_of_its_sources(client, monkeypatch, tmp_path):
    from aughor.db import history

    monkeypatch.setattr(history, "_DB_PATH", str(tmp_path / "history.db"))
    history.create_investigation("why did margin collapse", "conn-cr4")
    rows = history.list_investigations(limit=10)
    inv_id = rows[0]["id"]
    history.pause_investigation(inv_id)

    from aughor.actions.inbox import StagedProposal, stage_proposal
    proposal = stage_proposal(StagedProposal(
        connection_id="conn-cr4", action_id="create_ticket", params={"title": "t"},
        reasoning="margin fell", run_id="run-cr4", call_id="call-cr4"))

    body = client.get("/control-room/needs-human").json()
    assert body["count"] == sum(body["sources"].values())
    sources = {r["source"] for r in body["rows"]}
    assert {"kinetic_inbox", "paused_run"} <= sources

    paused = next(r for r in body["rows"] if r["source"] == "paused_run")
    assert paused["id"] == inv_id
    assert paused["resolve"]["feedback"] == f"/investigations/{inv_id}/feedback"
    assert paused["waiting_ms"] is not None and paused["waiting_ms"] >= 0
    assert paused["since_basis"] == "paused_event", (
        "waiting time must come from the investigation.paused ledger event")

    inbox_row = next(r for r in body["rows"] if r["source"] == "kinetic_inbox")
    assert inbox_row["id"] == proposal.id

    # Resolving through the native surface removes the row here — one store,
    # no copies (the J10 gate).
    from aughor.actions.inbox import reject_proposal
    assert reject_proposal(proposal.id, actor="test") is True
    after = client.get("/control-room/needs-human").json()
    assert all(r["id"] != proposal.id for r in after["rows"])
    assert after["sources"]["kinetic_inbox"] == body["sources"]["kinetic_inbox"] - 1


# ── CR5: run graphs ──────────────────────────────────────────────────────────────

def test_automation_runs_route_spans_all_automations(client):
    body = client.get("/automations/runs")
    assert body.status_code == 200
    assert "runs" in body.json()


def test_investigation_graph_view_is_honest_about_a_missing_checkpoint(
        client, monkeypatch, tmp_path):
    from aughor.db import history

    monkeypatch.setattr(history, "_DB_PATH", str(tmp_path / "history.db"))
    inv_id = history.create_investigation("q", "conn-cr5")

    body = client.get(f"/investigations/{inv_id}/graph").json()
    assert body["investigation_id"] == inv_id
    assert body["checkpoint"]["exists"] is False
    assert body["branch"] == "unknown", "no checkpoint must not produce a guessed picture"
    assert body["topology"] == []
    assert body["resume"] is None
    assert body["interrupt"]["paused"] is False


def test_deep_run_trace_resolves_its_investigation(client, ledger, monkeypatch, tmp_path):
    """A deep run's trace IS its investigation id (telemetry.new_trace returns it
    verbatim) and its span rows carry no investigation_id column — the door wrapper
    only brackets /ask and /chat. The trace route must resolve the direct match, or
    every deep run's feedback tab degrades to 'nothing to attach to' (found live)."""
    from aughor.db import history

    monkeypatch.setattr(history, "_DB_PATH", str(tmp_path / "history.db"))
    inv_id = history.create_investigation("why did jobs fail", "conn-cr1")
    ledger.session_event_insert({"trace_id": inv_id, "kind": "tool_call",
                                 "name": "ada_intake", "span_id": "s1"})

    body = client.get(f"/traces/{inv_id}").json()
    assert body["investigation_id"] == inv_id
    assert body["question"] == "why did jobs fail"

    listing = client.get("/traces", params={"investigation_id": inv_id}).json()
    assert any(t["trace_id"] == inv_id for t in listing["traces"]), (
        "the H3 drill-in must find a deep run by its investigation id")


def test_fleet_always_lists_user_defined_agents(client):
    """User-defined agents are a PERMANENT surface (flag endgame Wave 2, 2026-08-06,
    receipt df89c044999a): the CRUD routes always answer, so the fleet table and the
    roster can never disagree about what exists — the two-views hazard the old
    flag-off half of this test guarded is structurally gone."""
    from aughor.custom_agents.store import create_agent

    create_agent(name="Ghost Persona", instructions="x")
    got = client.get("/control-room/fleet").json()
    assert any(r["kind"] == "persona" and r["name"] == "Ghost Persona"
               for r in got["rows"])
