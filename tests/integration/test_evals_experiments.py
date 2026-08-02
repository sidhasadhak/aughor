"""Wave E4 — grid experiments through the real suite runner.

The store is pointed at a tmp file (`data/evals.db` is the default and a test that wrote
there would be the third time a suite has damaged live data — see the standing rule about
non-hermetic stores).

The properties under test are the ones that decide whether a grid's numbers mean anything:
a cell's configuration must be in force *while its target is built*, one bad cell must not
cost the whole grid, and the run must record the configuration it resolved to rather than
the one it was handed.
"""
from __future__ import annotations

import duckdb
import pytest

from aughor.evals import store
from aughor.evals.experiments import Cell
from aughor.evals.runner import run_experiment
from aughor.evals.targets import reference_checker, reference_target
from aughor.kernel.flags import clear_flag, flag_enabled

FLAG = "closed_loop"   # a registered, default-off flag (evidence_stubs was deleted 2026-08-01)


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_EVALS_DB", str(tmp_path / "evals.db"))
    monkeypatch.setattr(store, "_DB_PATH", tmp_path / "evals.db")
    monkeypatch.setenv("AUGHOR_FALLBACK_DISABLED", "1")
    monkeypatch.setenv("AUGHOR_EVALS_EXPERIMENTS", "1")
    # The seeder's live LLM calls are not what this file measures. Patch the attribute:
    # `_ENABLED` is resolved at module import, so a setenv here would be a no-op.
    monkeypatch.setattr("aughor.semantic.autoseed._ENABLED", False)
    yield
    clear_flag(FLAG)
    clear_flag("evals.experiments")


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "t.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE t(id INT, v INT)")
    con.execute("INSERT INTO t VALUES (1,10),(2,20),(3,30)")
    con.close()
    from aughor.db.connection import DuckDBConnection
    conn = DuckDBConnection(str(path), connection_id="e4test")
    yield conn
    conn.close()


@pytest.fixture
def suite():
    s = store.create_suite("e4", description="grid", target="reference")
    store.add_case(s["id"], question="all rows", artifact="SELECT * FROM t ORDER BY id")
    return s["id"]


def _cells():
    return [Cell(label="baseline"), Cell(label="stubs-on", flags={FLAG: True})]


def test_one_run_per_cell_each_under_its_own_configuration(db, suite):
    results = run_experiment(
        suite, lambda: reference_target(db), _cells(),
        checker=reference_checker(db))

    assert [r.label for r in results] == ["baseline", "stubs-on"]
    assert all(r.error == "" for r in results)
    assert results[0].config["flag_overrides"] == {}
    assert results[1].config["flag_overrides"] == {FLAG: True}
    assert all(r.discrepancies == [] for r in results)


def test_the_target_is_built_INSIDE_the_cell_context(db, suite):
    """The reason the API takes a factory: topology flags are read at compile time, so a
    target built before the loop would bake in the process-global answer."""
    seen: list[bool] = []

    def factory():
        seen.append(flag_enabled(FLAG))     # what a graph build would have observed
        return reference_target(db)

    run_experiment(suite, factory, _cells(), checker=reference_checker(db))
    assert seen == [False, True]


def test_each_cell_stamps_its_label_and_overrides_on_the_stored_run(db, suite):
    run_experiment(suite, lambda: reference_target(db), _cells(),
                   checker=reference_checker(db))

    runs = store.list_runs(suite)
    labels = {r["config"]["cell"] for r in runs}
    assert labels == {"baseline", "stubs-on"}
    by_label = {r["config"]["cell"]: r["config"] for r in runs}
    assert by_label["stubs-on"]["flag_overrides"] == {FLAG: True}
    assert by_label["baseline"]["flag_overrides"] == {}
    # The integrity precondition is recorded, so a stored run can be audited later for
    # whether the failover chain could have swapped its model.
    assert all(c["fallback_disabled"] is True for c in by_label.values())


def test_one_failing_cell_does_not_abandon_the_grid(db, suite):
    calls = {"n": 0}

    def flaky_factory():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("this cell could not be built")
        return reference_target(db)

    results = run_experiment(suite, flaky_factory, _cells(),
                            checker=reference_checker(db))

    assert results[0].error.startswith("RuntimeError:")
    assert results[0].run is None
    assert results[1].error == ""
    assert results[1].run is not None


def test_a_failed_cell_does_not_leak_its_pins_into_the_next(db, suite):
    from aughor.llm import provider as P

    def boom_then_check():
        if P.current_run_model() == "pinned/model":
            raise RuntimeError("fail inside the pinned cell")
        return reference_target(db)

    cells = [Cell(label="pinned", model="pinned/model"), Cell(label="clean")]
    results = run_experiment(suite, boom_then_check, cells,
                            checker=reference_checker(db))

    assert results[0].error != ""
    assert results[1].error == ""
    assert P.current_run_model() is None


def test_refuses_to_run_when_the_flag_is_off(db, suite, monkeypatch):
    """Silently running every cell under one configuration would yield a grid of identical
    numbers — which reads as 'the variant made no difference'."""
    monkeypatch.setenv("AUGHOR_EVALS_EXPERIMENTS", "0")
    with pytest.raises(RuntimeError) as exc:
        run_experiment(suite, lambda: reference_target(db), _cells())
    assert "evals.experiments" in str(exc.value)


def test_refuses_to_run_while_the_fallback_chain_is_live(db, suite, monkeypatch):
    """Aborts the grid rather than recording one global fault as N cell failures — the same
    blast radius as the frozen-semantics guard, because the condition is process-global."""
    from aughor.evals.experiments import MeasurementIntegrityError

    monkeypatch.delenv("AUGHOR_FALLBACK_DISABLED", raising=False)
    with pytest.raises(MeasurementIntegrityError):
        run_experiment(suite, lambda: reference_target(db), _cells(),
                       checker=reference_checker(db))


def test_plain_run_suite_still_records_the_override_layer(db, suite):
    """Every run records it, not just experiment runs — a run that executed inside a cell
    and did not say so gets filed under the wrong configuration."""
    from aughor.evals.experiments import applied
    from aughor.evals.runner import run_suite

    with applied(Cell(label="ad-hoc", flags={FLAG: True})):
        summary = run_suite(suite, reference_target(db), checker=reference_checker(db))

    assert summary.config["flag_overrides"] == {FLAG: True}
    assert summary.config["fallback_disabled"] is True


# ── E4 loose end: grids from a scheduler, budget guard as the precondition ──────

def test_schedule_refuses_over_budget_BEFORE_a_job_exists(db, suite):
    """The budget guard is the precondition — a grid over its allowance is refused
    synchronously at schedule time, so no job id is ever handed back for a doomed run."""
    import asyncio

    from aughor.evals.experiments import MeasurementIntegrityError
    from aughor.evals.runner import schedule_experiment

    with pytest.raises(MeasurementIntegrityError):
        # 2 cells × 1 case × 1 req/case = 2 estimated, against a budget of 1.
        asyncio.run(schedule_experiment(
            suite, lambda: reference_target(db), _cells(), checker=reference_checker(db),
            request_budget=1, requests_per_case=1))


def test_schedule_refuses_while_the_fallback_chain_is_live(db, suite, monkeypatch):
    import asyncio

    from aughor.evals.experiments import MeasurementIntegrityError
    from aughor.evals.runner import schedule_experiment

    monkeypatch.delenv("AUGHOR_FALLBACK_DISABLED", raising=False)
    with pytest.raises(MeasurementIntegrityError):
        asyncio.run(schedule_experiment(
            suite, lambda: reference_target(db), _cells(), checker=reference_checker(db)))


def test_schedule_refuses_when_the_flag_is_off(db, suite, monkeypatch):
    import asyncio

    from aughor.evals.runner import schedule_experiment

    monkeypatch.setenv("AUGHOR_EVALS_EXPERIMENTS", "0")
    with pytest.raises(RuntimeError) as exc:
        asyncio.run(schedule_experiment(suite, lambda: reference_target(db), _cells()))
    assert "evals.experiments" in str(exc.value)


def test_schedule_runs_the_grid_as_a_supervised_job(db, suite):
    """The happy path: an eligible grid is submitted, runs off the event loop, and its cells
    land in the store — same result as an inline run, without blocking the caller."""
    import asyncio

    from aughor.evals.runner import schedule_experiment
    from aughor.kernel.jobs import JobState, kernel

    async def go():
        job_id = await schedule_experiment(
            suite, lambda: reference_target(db), _cells(), checker=reference_checker(db))
        task = kernel()._tasks.get(job_id)
        if task is not None:
            await task                       # let the background job finish before we assert
        return job_id

    job_id = asyncio.run(go())

    job = kernel().ledger.job_get(job_id)
    assert job is not None and job["kind"] == "eval_experiment"
    assert job["state"] == JobState.SUCCEEDED
    # both cells persisted, each under its own configuration — the inline result, scheduled.
    labels = {r["config"]["cell"] for r in store.list_runs(suite)}
    assert labels == {"baseline", "stubs-on"}
