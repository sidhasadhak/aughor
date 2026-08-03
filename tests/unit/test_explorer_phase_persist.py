"""Regression tests for the two explorer observability fixes.

F-phase-sync: _save_state() mirrors the LIVE self._status.phase into the persisted
  state on every save, so the exploration JSON reflects mid-run progress (it used to
  stay 'pending' until the terminal COMPLETE/FAILED write).
F-concurrency: explore() is a thin concurrency-bounded wrapper over _explore_run(),
  gated by a shared semaphore sized from AUGHOR_MAX_CONCURRENT_EXPLORERS.
"""
import asyncio

from aughor.explorer import agent as agent_mod
from aughor.explorer.agent import SchemaExplorer, _get_explorer_semaphore
from aughor.explorer.models import ExplorationPhase


def _bare_explorer():
    """A SchemaExplorer with just the attributes _save_state touches (no DB)."""
    ex = SchemaExplorer.__new__(SchemaExplorer)
    ex.canvas_id = None
    ex.connection_id = "testconn"
    ex.schema_name = None
    ex._store_key = "testconn"   # connection-level run keys state by the bare connection id
    ex._state = {"phase": "pending"}

    class _Status:
        phase = ExplorationPhase.DISTRIBUTION

    ex._status = _Status()
    return ex


def test_save_state_mirrors_live_phase(monkeypatch):
    ex = _bare_explorer()
    captured = {}
    monkeypatch.setattr(agent_mod._store, "save",
                        lambda cid, state: captured.update(cid=cid, state=dict(state)))
    ex._save_state()
    assert captured["cid"] == "testconn"
    # disk phase now tracks the live status phase, not the stale 'pending'
    assert captured["state"]["phase"] == ExplorationPhase.DISTRIBUTION.value


def test_schema_scoped_run_keys_state_by_conn_and_schema(monkeypatch):
    # A per-schema run must persist state under {conn}__{schema} so each schema of a
    # multi-schema connection gets its OWN exploration state (the missimi=0 fix).
    ex = SchemaExplorer.__new__(SchemaExplorer)
    ex.canvas_id = None
    ex.connection_id = "workspace"
    ex.schema_name = "missimi"
    ex._store_key = "workspace__missimi"

    class _Status:
        phase = ExplorationPhase.DOMAIN_INTEL

    ex._status = _Status()
    ex._state = {"phase": "pending"}
    captured = {}
    monkeypatch.setattr(agent_mod._store, "save",
                        lambda cid, state: captured.update(cid=cid))
    ex._save_state()
    assert captured["cid"] == "workspace__missimi"


def test_leaks_schema_drops_cross_schema_sql():
    # A schema-scoped run must reject SQL that escapes its schema (the scoped DuckDB can
    # still execute another schema's tables).
    ex = SchemaExplorer.__new__(SchemaExplorer)
    ex.schema_name = "bakehouse"
    assert ex._leaks_schema("SELECT * FROM missimi.orders") is True
    assert ex._leaks_schema("SELECT * FROM bakehouse.sales_transactions b JOIN bakehouse.suppliers s ON 1=1") is False
    ex.schema_name = None   # connection-level run never restricts
    assert ex._leaks_schema("SELECT * FROM missimi.orders") is False


def test_save_state_accepts_plain_string_phase(monkeypatch):
    ex = _bare_explorer()
    ex._status.phase = "domain_intel"  # already a string (defensive)
    captured = {}
    monkeypatch.setattr(agent_mod._store, "save",
                        lambda cid, state: captured.update(state=dict(state)))
    ex._save_state()
    assert captured["state"]["phase"] == "domain_intel"


def test_cancelled_run_marks_status_terminal(monkeypatch):
    """Tier-0 #1 (the budget-cancel WEDGE): a CancelledError mid-run must leave the in-memory
    status TERMINAL (FAILED), not stuck at domain_intel — otherwise the next start/spawn sees a
    stale 'still running' explorer and refuses. Drive a cancel in Phase 8 and assert the handler
    marks it terminal."""
    import pytest

    ex = SchemaExplorer.__new__(SchemaExplorer)
    ex.connection_id = "c"
    ex.schema_name = None
    ex._store_key = "c"
    ex._state = {}
    ex._rate_seconds = 0

    class _Status:
        phase = ExplorationPhase.PENDING
        error = None
        domain_intel_skipped = False
        domain_intel_note = None
        tables_total = columns_total = joins_total = 0

    ex._status = _Status()
    monkeypatch.setattr(ex, "_load_profiler_data", lambda: ({"t": object()}, {}, {"joins": []}))
    monkeypatch.setattr(ex, "_compute_time_window", lambda *a, **k: None)
    monkeypatch.setattr(ex, "_compute_macro_context", lambda *a, **k: None)
    monkeypatch.setattr(ex, "_save_state", lambda: None)
    monkeypatch.setattr(ex, "_journal", lambda *a, **k: None)

    async def _cancel(*a, **k):
        raise asyncio.CancelledError()

    monkeypatch.setattr(ex, "_phase8_domain_intelligence", _cancel)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(ex._explore_run(domain_intel_only=True))   # skips 3-7, cancels in Phase 8

    assert ex._status.phase == ExplorationPhase.FAILED          # terminal, not stuck at domain_intel
    assert "cancelled" in (ex._status.error or "").lower()


def test_manifest_nq_pops_cell_and_builds_deterministic_question():
    """Tier-1 #4 wiring: _manifest_nq pops the next uncovered manifest cell whose table is in
    scope and builds a deterministic next-question (zero LLM), marking it attempted so the run
    advances rather than repeats."""
    from aughor.explorer.coverage_manifest import ManifestCell
    from aughor.tools.profiler import ColumnProfile, TableProfile

    ex = SchemaExplorer.__new__(SchemaExplorer)
    ex._manifest_cells = [ManifestCell("amount", "orders", "headline", None, "profiled_measure")]
    ex._manifest_attempted = set()
    ex._state = {}
    ex._cp_by_key = {("orders", "amount"):
                     ColumnProfile("orders", "amount", "DOUBLE", "measure", unit="USD", value_range=(0, 100))}
    ex._tp_by_table = {"orders": TableProfile("orders")}

    class _NQ:
        def __init__(self, question, sql, angle, why):
            self.question, self.sql, self.angle, self.why = question, sql, angle, why

    nq = ex._manifest_nq({"orders": ["amount"]}, _NQ)
    assert nq is not None and "SUM(amount)" in nq.sql and nq.angle == "amount:headline"
    # the cell is now attempted → no cell left → falls back (None)
    assert ex._manifest_nq({"orders": ["amount"]}, _NQ) is None
    # the attempt was persisted to state so a re-run skips it (Tier-2 coverage tracker)
    assert ex._state["manifest_covered"]["cells"] == [["amount", "orders", "headline", None]]
    # a cell whose table isn't in this domain's scope is skipped
    ex._manifest_attempted.clear()
    assert ex._manifest_nq({"other_table": ["x"]}, _NQ) is None


def test_manifest_coverage_skips_cells_covered_by_a_prior_run():
    """Tier-2: a cell already covered (seeded into _manifest_attempted from persisted state) is
    not re-attempted — re-runs skip the covered frontier and stay cheap."""
    from aughor.explorer.coverage_manifest import ManifestCell
    from aughor.tools.profiler import ColumnProfile, TableProfile

    ex = SchemaExplorer.__new__(SchemaExplorer)
    ex._manifest_cells = [ManifestCell("amount", "orders", "headline", None, "profiled_measure")]
    ex._manifest_attempted = {("amount", "orders", "headline", None)}   # covered by a prior run
    ex._state = {}
    ex._cp_by_key = {("orders", "amount"):
                     ColumnProfile("orders", "amount", "DOUBLE", "measure", unit="USD", value_range=(0, 100))}
    ex._tp_by_table = {"orders": TableProfile("orders")}

    class _NQ:
        def __init__(self, question, sql, angle, why):
            self.question, self.sql, self.angle, self.why = question, sql, angle, why

    assert ex._manifest_nq({"orders": ["amount"]}, _NQ) is None        # already covered → skipped


def test_explorer_semaphore_sized_from_env(monkeypatch):
    monkeypatch.setattr(agent_mod, "_MAX_CONCURRENT_EXPLORERS", 2)

    async def _check():
        sem = _get_explorer_semaphore()
        assert isinstance(sem, asyncio.Semaphore)
        assert sem._value == 2
        # same instance reused WITHIN a loop (a shared cap, not one per explorer)
        assert _get_explorer_semaphore() is sem
        return sem

    first = asyncio.run(_check())
    # …and a DIFFERENT instance in a new loop. A Semaphore binds to the loop it is
    # awaited on, so reusing one across loops raises "bound to a different event loop"
    # and, if it was left acquired, deadlocks every later awaiter.
    second = asyncio.run(_check())
    assert second is not first


def test_the_semaphore_is_not_reused_across_event_loops(monkeypatch):
    """The regression this guards: one process-global semaphore, acquired in a loop that
    then closed, wedged the whole test suite — every later `async with sem` waited on a
    slot no live task would ever release.

    Cap pinned to 1 so a single un-released acquire exhausts it; at the default of 2,
    `locked()` stays False after one acquire and the test would prove nothing.
    """
    monkeypatch.setattr(agent_mod, "_MAX_CONCURRENT_EXPLORERS", 1)

    async def _acquire_and_abandon():
        sem = _get_explorer_semaphore()
        await sem.acquire()          # deliberately never released
        return sem.locked()

    assert asyncio.run(_acquire_and_abandon()) is True

    async def _fresh_loop_is_unblocked():
        sem = _get_explorer_semaphore()
        assert sem.locked() is False          # a new loop, a new slot
        async with sem:                        # must not hang
            return True

    assert asyncio.run(_fresh_loop_is_unblocked()) is True


def test_explore_wrapper_runs_under_semaphore(monkeypatch):
    """explore() must acquire the shared slot and delegate to _explore_run."""
    monkeypatch.setattr(agent_mod, "_MAX_CONCURRENT_EXPLORERS", 1)
    ex = SchemaExplorer.__new__(SchemaExplorer)
    ex.connection_id = "c"
    seen = {}

    async def fake_run(domain_intel_only=False):
        sem = _get_explorer_semaphore()
        seen["held_during_run"] = sem.locked()      # slot taken while running
        seen["domain_intel_only"] = domain_intel_only

    async def _drive():
        await ex.explore(domain_intel_only=True)
        # slot released after the run completes — checked INSIDE the loop that owns it,
        # because the semaphore now lives and dies with its loop.
        return _get_explorer_semaphore().locked()

    ex._explore_run = fake_run
    assert asyncio.run(_drive()) is False
    assert seen["held_during_run"] is True
    assert seen["domain_intel_only"] is True
