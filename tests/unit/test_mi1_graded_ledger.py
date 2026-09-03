"""MI-1 / MI-0 — the platform grades what it already runs, and stops exporting what it
was not asked to.

Four things are proven here, and the fourth is the point of the whole slice:

* a guard fire is DURABLE (it used to reach an SSE sink and nothing else),
* it is trace-gated, so tests, scripts and the eval plane still cost nothing,
* an automation tick records whose work it was and which trace it ran under,
* and ONE SQL query can walk run -> executed SQL -> guard fire. Before this slice that
  query could not be written at all, which is the receipt §3.9 asks for.
"""
from __future__ import annotations

from aughor.security.audit import AuditLogger, GuardVerdicts


def _tel():
    """The CURRENT telemetry module, resolved per call.

    `test_telemetry.py::_reload_telemetry` re-imports `aughor.telemetry`, so a module-scope
    binding here could hold a module object that is no longer the one the code under test
    reads — binding a ContextVar nobody looks at. That made these tests pass alone and fail
    in the suite, which is worse than failing outright. The reload now keeps `sys.modules`
    and the package attribute in sync (that divergence WAS the bug); resolving per call
    here, the way production code does, keeps these tests honest either way.
    """
    import aughor.telemetry as tel
    return tel


# ── the guard verdict survives the run ───────────────────────────────────────────────

def test_a_guard_fire_is_persisted_under_its_trace():
    with _tel().bind_trace("trace-mi1-a"):
        GuardVerdicts.record(pattern="E1-date-boundary", subject="orders.created_at",
                             phase="execute", sql="SELECT 1", detail="bounded by a date")
    rows = GuardVerdicts.recent(trace_id="trace-mi1-a")
    assert len(rows) == 1
    assert rows[0]["pattern"] == "E1-date-boundary"
    assert rows[0]["subject"] == "orders.created_at"
    assert rows[0]["phase"] == "execute"


def test_a_verdict_with_no_trace_is_dropped_not_orphaned():
    """The same law the session log applies. A row that can join to nothing is noise
    that makes the table look healthier than it is — and this gating is what keeps the
    checks free for the eval plane, which runs them outside any trace."""
    GuardVerdicts.record(pattern="E1-untraced-probe", subject="x", sql="SELECT 1")
    assert GuardVerdicts.recent(pattern="E1-untraced-probe") == []


def test_trust_checks_persist_from_the_shared_seam_not_the_callers():
    """Four sites run these checks; recording at each would be four chances to miss one.
    Calling the pure function is enough to leave a durable row."""
    from aughor.sql.trust_checks import run_trust_checks

    sql = "SELECT * FROM orders WHERE created_at BETWEEN '2026-01-01' AND '2026-01-31'"
    with _tel().bind_trace("trace-mi1-b"):
        issues = run_trust_checks(sql, col_types={"orders.created_at": "TIMESTAMP"},
                                  phase="quick")
    assert issues, "fixture no longer trips E1 — the test below would prove nothing"
    rows = GuardVerdicts.recent(trace_id="trace-mi1-b")
    assert {r["pattern"] for r in rows} == {i.pattern for i in issues}
    assert all(r["phase"] == "quick" for r in rows)


def test_a_rewrite_receipt_persists_without_any_hook_registered():
    """The kernel seam records directly rather than through a registered hook: the only
    hook that exists is the agent's SSE forwarder, so riding it would mean a bare
    platform, an automation tick and the quick path recorded nothing."""
    from aughor.kernel.registries.execution_hooks import emit_guard_receipt

    with _tel().bind_trace("trace-mi1-c"):
        emit_guard_receipt("fanout_defan", "rewrote_sql", detail="join fans out",
                           before="SELECT 1", after="SELECT 2")
    rows = GuardVerdicts.recent(trace_id="trace-mi1-c")
    assert [r["pattern"] for r in rows] == ["fanout_defan"]
    assert rows[0]["phase"] == "rewrote_sql"


# ── the run can say whose work it was ────────────────────────────────────────────────

def test_an_automation_run_records_its_agent_and_trace():
    """`AutomationRun.agent_id` has been declared since VA-9b and silently dropped by the
    named INSERT ever since — this store's fourth half-added field. `trace_id` is new."""
    from aughor.automations.models import AutomationRun
    from aughor.automations.store import append_run, get_run

    with _tel().bind_trace("trace-mi1-d"):
        run = append_run(AutomationRun(automation_id="auto-1", outcome="fired",
                                       agent_id="agent-7"))
    stored = get_run(run.id)
    assert stored is not None
    assert stored.agent_id == "agent-7", "the INSERT is dropping agent_id again"
    assert stored.trace_id == "trace-mi1-d", "the ambient trace did not reach the row"


# ── the receipt §3.9 asks for ────────────────────────────────────────────────────────

def test_one_query_walks_run_to_executed_sql_to_guard_fire():
    """MI-1's stated receipt. Both tables live in AUGHOR_AUDIT_DB precisely so this is a
    single-store join instead of a cross-database reconstruction."""
    import sqlite3

    from aughor.security import audit as audit_mod

    trace = "trace-mi1-receipt"
    sql = "SELECT * FROM orders WHERE created_at BETWEEN '2026-01-01' AND '2026-01-31'"
    with _tel().bind_trace(trace):
        AuditLogger.log(connection_id="conn-1", hypothesis_id="h1", sql=sql, row_count=3)
        GuardVerdicts.record(pattern="E1-date-boundary", subject="orders.created_at",
                             phase="execute", sql=sql, detail="bounded by a date literal")

    c: sqlite3.Connection = audit_mod._connect()
    try:
        rows = c.execute(
            """SELECT a.trace_id, a.connection_id, a.row_count, g.pattern, g.subject
                 FROM audit_log a
                 JOIN guard_verdicts g ON g.trace_id = a.trace_id
                WHERE a.trace_id = ?""",
            (trace,),
        ).fetchall()
    finally:
        c.close()

    assert len(rows) == 1
    assert rows[0]["connection_id"] == "conn-1"
    assert rows[0]["pattern"] == "E1-date-boundary"
    assert rows[0]["subject"] == "orders.created_at"


# ── MI-0: the export obeys the custody window ────────────────────────────────────────

def test_the_question_leaves_the_box_only_inside_a_capture_window(monkeypatch):
    """`langfuse.trace.input` put the raw question on the OTLP wire on every run. It is an
    export, not a read, so no break-glass ever fired on it and nothing audited it."""
    from aughor.obs import prompt_window

    monkeypatch.setattr(prompt_window, "active", lambda: False)
    closed = _tel()._trace_input("who churned in Q3?", "conn-1")
    assert "question" not in closed, "the question is exported with the window shut"
    assert closed["connection_id"] == "conn-1", "metadata is free under §6.4"

    monkeypatch.setattr(prompt_window, "active", lambda: True)
    assert _tel()._trace_input("who churned in Q3?", "conn-1")["question"] \
        == "who churned in Q3?"


def test_a_broken_window_read_fails_safe_to_no_capture(monkeypatch):
    """Same posture as every read in prompt_window: an error means no window."""
    from aughor.obs import prompt_window

    def _boom():
        raise RuntimeError("store unavailable")

    monkeypatch.setattr(prompt_window, "active", _boom)
    assert "question" not in _tel()._trace_input("secret question", "conn-1")
