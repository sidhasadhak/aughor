"""Wave E4b — replicates, fixture provenance and the frozen-semantics guard, end to end.

The store is pointed at a tmp file; `data/evals.db` is the default and a suite that wrote
there would be the third time a test run has damaged live data.

What is worth pinning here is the difference between the two guards. A polluted connection
invalidates the WHOLE grid, so it aborts before anything runs. A fixture that moves mid-grid
invalidates the cells on either side of the move, so it is recorded on the cell and the run
continues — the surviving cells are still usable and discarding them would cost more than
the warning does.
"""
from __future__ import annotations

import duckdb
import pytest

from aughor.evals import store
from aughor.evals.experiments import Cell, MeasurementIntegrityError
from aughor.evals.fidelity import assess
from aughor.evals.runner import run_experiment
from aughor.evals.targets import reference_checker, reference_target
from aughor.kernel.flags import clear_flag

FLAG = "deep_analysis.evidence_stubs"
TABLES = ["orders"]


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_EVALS_DB", str(tmp_path / "evals.db"))
    monkeypatch.setattr(store, "_DB_PATH", tmp_path / "evals.db")
    monkeypatch.setenv("AUGHOR_FALLBACK_DISABLED", "1")
    monkeypatch.setenv("AUGHOR_EVALS_EXPERIMENTS", "1")
    # Schema loads call `semantic.autoseed.seed_missing_tables`, which makes REAL LLM requests
    # against the 1,000/day budget. Nothing here measures the seeder. Patch the ATTRIBUTE, not
    # the env var: `_ENABLED` is resolved at module import, so a `setenv` here is a no-op —
    # the same trap `test_program_planner.py` sidesteps.
    monkeypatch.setattr("aughor.semantic.autoseed._ENABLED", False)
    yield
    clear_flag(FLAG)
    clear_flag("evals.experiments")


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "fix.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE orders(id INT, amount INT)")
    con.execute("INSERT INTO orders VALUES (1,100),(2,250),(3,90)")
    con.close()
    from aughor.db.connection import DuckDBConnection
    conn = DuckDBConnection(str(path), connection_id="e4btest")
    yield conn
    conn.close()


@pytest.fixture
def suite():
    s = store.create_suite("e4b", target="reference")
    store.add_case(s["id"], question="all", artifact="SELECT * FROM orders ORDER BY id")
    return s["id"]


def _cells():
    return [Cell(label="baseline"), Cell(label="variant", flags={FLAG: True})]


# ── replicates ────────────────────────────────────────────────────────────────

def test_replicates_produce_one_run_per_repetition(db, suite):
    results = run_experiment(suite, lambda: reference_target(db), _cells(),
                             replicates=3, checker=reference_checker(db))
    assert [len(r.runs) for r in results] == [3, 3]
    assert all(r.error == "" for r in results)


def test_each_replicate_is_stored_with_its_index(db, suite):
    run_experiment(suite, lambda: reference_target(db), _cells()[:1],
                   replicates=3, checker=reference_checker(db))
    reps = sorted(r["config"]["replicate"] for r in store.list_runs(suite))
    assert reps == [0, 1, 2]


def test_run_property_still_reads_the_first_replicate(db, suite):
    """E4a's single-replicate callers keep working."""
    results = run_experiment(suite, lambda: reference_target(db), _cells()[:1],
                             replicates=2, checker=reference_checker(db))
    assert results[0].run is results[0].runs[0]


def test_replicated_grid_feeds_the_fidelity_harness(db, suite):
    """The deterministic reference target has a noise floor of exactly zero, which is the
    cleanest possible demonstration that the floor is measured rather than assumed."""
    results = run_experiment(suite, lambda: reference_target(db), _cells(),
                             replicates=3, checker=reference_checker(db))
    report = assess({r.label: r.runs for r in results}, baseline="baseline")

    assert report.floors["pass_rate"].verified is True
    assert report.floors["pass_rate"].band == 0.0
    assert report.floors["pass_rate"].replicates == 3


# ── fixture provenance ────────────────────────────────────────────────────────

def test_the_fixture_version_is_stamped_on_every_stored_run(db, suite):
    run_experiment(suite, lambda: reference_target(db), _cells(),
                   replicates=2, checker=reference_checker(db),
                   fixture=db, fixture_tables=TABLES)
    versions = {r["config"]["data_version"] for r in store.list_runs(suite)}
    assert len(versions) == 1
    assert next(iter(versions))


def test_a_fixture_that_moves_mid_grid_is_recorded_not_hidden(db, suite, monkeypatch):
    """The cell that ran across the move did not see the same data as the ones before it.

    The move is simulated at the probe rather than by writing to the fixture, because a
    local DuckDB file is opened read_only precisely so a run cannot mutate it — the
    property this test would otherwise have to break in order to exercise.
    """
    from aughor.evals import experiments as X

    versions = iter(["fp:aaa", "fp:bbb", "fp:bbb", "fp:bbb"])
    monkeypatch.setattr(X, "data_version_of", lambda conn, tables=None: next(versions))

    results = run_experiment(suite, lambda: reference_target(db), _cells(),
                             checker=reference_checker(db),
                             fixture=db, fixture_tables=TABLES)

    assert results[0].warnings, "the move must be reported on the cell that spanned it"
    assert "fixture moved" in results[0].warnings[0]
    assert "not attributable" in results[0].warnings[0]
    assert results[1].warnings == [], "the settled fixture must not keep warning"


def test_a_still_fixture_produces_no_warning(db, suite):
    results = run_experiment(suite, lambda: reference_target(db), _cells(),
                             checker=reference_checker(db),
                             fixture=db, fixture_tables=TABLES)
    assert all(r.warnings == [] for r in results)


def test_omitting_the_fixture_leaves_the_stamp_empty_rather_than_faked(db, suite):
    results = run_experiment(suite, lambda: reference_target(db), _cells()[:1],
                             checker=reference_checker(db))
    assert results[0].fixture_version is None


# ── the frozen-semantics guard ────────────────────────────────────────────────

def test_a_polluted_connection_aborts_the_whole_grid(db, suite, monkeypatch):
    """Unlike a cell failure, this is not recorded and survived: exploration insights steer
    the model's metric choice, so every cell is measuring something neither of them varied."""
    from aughor.evals import experiments as X

    monkeypatch.setattr(X, "volatile_semantic_state",
                        lambda cid: {"exploration_bytes": 4096, "ontology": "present"})

    with pytest.raises(MeasurementIntegrityError) as exc:
        run_experiment(suite, lambda: reference_target(db), _cells(),
                       checker=reference_checker(db), connection_id="polluted")
    assert "exploration insights" in str(exc.value)


def test_pollution_can_be_allowed_deliberately(db, suite, monkeypatch):
    from aughor.evals import experiments as X

    monkeypatch.setattr(X, "volatile_semantic_state",
                        lambda cid: {"exploration_bytes": 4096, "ontology": "present"})

    results = run_experiment(suite, lambda: reference_target(db), _cells(),
                             checker=reference_checker(db), connection_id="polluted",
                             allow_exploration=True)
    assert all(r.error == "" for r in results)


def test_a_clean_connection_passes_the_guard(db, suite, monkeypatch):
    from aughor.evals import experiments as X

    monkeypatch.setattr(X, "volatile_semantic_state",
                        lambda cid: {"exploration_bytes": 0, "ontology": "none"})

    results = run_experiment(suite, lambda: reference_target(db), _cells(),
                             checker=reference_checker(db), connection_id="clean")
    assert all(r.error == "" for r in results)
