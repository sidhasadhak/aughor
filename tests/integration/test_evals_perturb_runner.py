"""E4c — robustness as a grid axis, and the request-budget refusal.

The robustness axis is deliberately a FIELD on RunSummary rather than a derived property, so
`fidelity.axis_of` reads it exactly like pass_rate and accuracy — including the part that
matters most, that None (nobody measured it) stays distinguishable from 0.0 (measured, and
every rewording broke it).

The budget guard exists for a failure that is worse than an error: a grid that runs for an
hour, exhausts the day's allowance halfway, and returns a report whose later cells are quota
failures while its earlier cells look fine. A reader cannot see that damage in the numbers.
"""
from __future__ import annotations

import duckdb
import pytest

from aughor.evals import store
from aughor.evals.experiments import (
    Cell,
    MeasurementIntegrityError,
    assert_within_budget,
    estimate_requests,
)
from aughor.evals.fidelity import assess, axis_of
from aughor.evals.perturb import DEFAULT_PERTURBATIONS
from aughor.evals.runner import run_experiment, run_suite
from aughor.evals.targets import reference_checker, reference_target
from aughor.kernel.flags import clear_flag

FLAG = "deep_analysis.evidence_stubs"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_EVALS_DB", str(tmp_path / "evals.db"))
    monkeypatch.setattr(store, "_DB_PATH", tmp_path / "evals.db")
    monkeypatch.setenv("AUGHOR_FALLBACK_DISABLED", "1")
    monkeypatch.setenv("AUGHOR_EVALS_EXPERIMENTS", "1")
    # `_ENABLED` is resolved at module import, so patch the attribute — a setenv here is a
    # no-op. Keeps the seeder's live LLM calls out of a test that does not measure it.
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
    conn = DuckDBConnection(str(path), connection_id="e4ctest")
    yield conn
    conn.close()


@pytest.fixture
def suite():
    s = store.create_suite("e4c", target="reference")
    store.add_case(s["id"], question="All the orders, please?",
                   artifact="SELECT * FROM orders ORDER BY id")
    return s["id"]


def _cells():
    return [Cell(label="baseline"), Cell(label="variant", flags={FLAG: True})]


# ── robustness as an axis ─────────────────────────────────────────────────────

def test_a_reference_replay_is_perfectly_robust(db, suite):
    """The reference target executes the case's stored SQL, which no rewording touches — so
    the axis must read exactly 1.0. A deterministic ceiling is the cleanest check that the
    axis is measured rather than assumed."""
    summary = run_suite(suite, reference_target(db), checker=reference_checker(db),
                        perturbations=DEFAULT_PERTURBATIONS)
    assert summary.robustness == 1.0
    assert summary.brittleness_detail


def test_robustness_is_absent_not_zero_when_unmeasured(db, suite):
    summary = run_suite(suite, reference_target(db), checker=reference_checker(db))
    assert summary.robustness is None
    assert summary.to_dict()["robustness"] is None


def test_fidelity_reads_robustness_like_any_other_axis(db, suite):
    results = run_experiment(suite, lambda: reference_target(db), _cells(),
                             replicates=2, checker=reference_checker(db),
                             perturbations=DEFAULT_PERTURBATIONS)
    a = axis_of(results[0].runs, "robustness")
    assert a.n == 2
    assert a.mean == 1.0

    report = assess({r.label: r.runs for r in results}, baseline="baseline",
                    axes=("pass_rate", "robustness"))
    assert report.floors["robustness"].verified is True
    assert report.floors["robustness"].band == 0.0


def test_an_unmeasured_robustness_axis_does_not_sink_the_composite(db, suite):
    """None must be skipped, not folded to 0.0 — a harmonic composite with a zero in it is
    zero, so this is the difference between 'we did not measure it' and 'it is broken'."""
    results = run_experiment(suite, lambda: reference_target(db), _cells()[:1],
                             replicates=2, checker=reference_checker(db))
    report = assess({r.label: r.runs for r in results}, baseline="baseline",
                    axes=("pass_rate", "robustness"))
    assert report.composite["baseline"] == 1.0


def test_a_brittle_target_scores_below_one(db, suite):
    """A target that answers differently when the question is lower-cased — the shape of a
    pipeline keying on phrasing rather than on the request."""
    honest = reference_target(db)

    def brittle_target(case):
        obs = honest(case)
        if case.question and case.question.islower():
            obs.rows = list(obs.rows) + [[999, 999]]
        return obs

    summary = run_suite(suite, brittle_target, checker=reference_checker(db),
                        perturbations=DEFAULT_PERTURBATIONS)
    assert summary.robustness is not None
    assert summary.robustness < 1.0


# ── the request budget ────────────────────────────────────────────────────────

def test_the_estimate_multiplies_every_factor():
    assert estimate_requests(cells=3, cases=20, replicates=3, iterations=1,
                             perturbations=5, requests_per_case=4) == 4320


def test_perturbations_add_the_original_run_to_the_multiplier():
    """1 + N, not N: the unperturbed run is what the rewordings are compared against."""
    assert estimate_requests(cells=1, cases=1, perturbations=4, requests_per_case=1) == 5


def test_a_zero_cost_target_estimates_zero():
    assert estimate_requests(cells=9, cases=99, replicates=9, requests_per_case=0) == 0


def test_a_grid_over_budget_is_refused_before_it_starts():
    with pytest.raises(MeasurementIntegrityError) as exc:
        assert_within_budget(4320, budget=1000)
    assert "asymmetrically" in str(exc.value)


def test_a_grid_within_budget_passes():
    assert_within_budget(120, budget=1000) is None


def test_no_budget_means_no_ceiling():
    assert_within_budget(10_000_000, budget=0) is None


def test_run_experiment_refuses_an_over_budget_grid(db, suite):
    with pytest.raises(MeasurementIntegrityError):
        run_experiment(suite, lambda: reference_target(db), _cells(),
                       replicates=5, checker=reference_checker(db),
                       perturbations=DEFAULT_PERTURBATIONS,
                       request_budget=10, requests_per_case=4)


def test_run_experiment_runs_when_the_estimate_fits(db, suite):
    results = run_experiment(suite, lambda: reference_target(db), _cells(),
                             checker=reference_checker(db),
                             request_budget=1000, requests_per_case=4)
    assert all(r.error == "" for r in results)


def test_the_budget_check_happens_before_any_cell_is_built(db, suite):
    built = []

    def factory():
        built.append(1)
        return reference_target(db)

    with pytest.raises(MeasurementIntegrityError):
        run_experiment(suite, factory, _cells(), replicates=9,
                       checker=reference_checker(db),
                       request_budget=1, requests_per_case=50)
    assert built == [], "a refused grid must not have started constructing targets"
