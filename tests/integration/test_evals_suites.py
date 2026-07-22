"""Wave E3 — suites, runs, and the runner's measurement discipline.

The store is ordinary CRUD; what needs testing is the part that makes a run a
*measurement*: replication, the flaky classifier, per-case causal attribution,
the separation of "guards found nothing" from "the answer is right", and the
config snapshot without which two runs cannot be compared.
"""
from __future__ import annotations

import duckdb
import pytest

from aughor.evals import (
    EvalCase,
    EvalObservation,
    reference_checker,
    reference_target,
    run_suite,
    store,
)
from aughor.evals.store import FLAKY, STABLE_FAIL, STABLE_PASS


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    """Point the evals DB at a tmp file per test. The module resolves its path at
    import, so the module-level constant is patched too."""
    monkeypatch.setenv("AUGHOR_EVALS_DB", str(tmp_path / "evals.db"))
    monkeypatch.setattr(store, "_DB_PATH", tmp_path / "evals.db")
    yield


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "t.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE t(id INT, v INT)")
    con.execute("INSERT INTO t VALUES (1,10),(2,20),(3,30)")
    con.close()
    from aughor.db.connection import DuckDBConnection
    conn = DuckDBConnection(str(path), connection_id="e3test")
    yield conn
    conn.close()


def _suite_with(cases):
    s = store.create_suite("s", target="reference")
    store.add_cases(s["id"], cases)
    return s["id"]


# ── store ─────────────────────────────────────────────────────────────────────

def test_suite_case_run_roundtrip():
    sid = _suite_with([{"question": "q1", "artifact": "SELECT 1"}])
    assert [s["id"] for s in store.list_suites()] == [sid]
    assert len(store.list_cases(sid)) == 1

    run_id = store.start_run(sid, iterations=2, config={"backend": "x"})
    assert store.get_run(run_id)["status"] == store.RUNNING
    store.record_result(run_id, "c1", 0, passed=True, duration_ms=1.0, fired=[])
    store.finish_run(run_id, summary={"total": 1})
    run = store.get_run(run_id)
    assert run["status"] == store.SUCCEEDED
    assert run["summary"]["total"] == 1
    assert run["config"]["backend"] == "x"
    assert len(store.run_results(run_id)) == 1


def test_delete_suite_cascades():
    """Orphan cases would quietly inflate every later count."""
    sid = _suite_with([{"question": "q", "artifact": "SELECT 1"}])
    run_id = store.start_run(sid)
    store.record_result(run_id, "c", 0, passed=True)

    assert store.delete_suite(sid) is True
    assert store.list_cases(sid) == []
    assert store.list_runs(sid) == []
    assert store.run_results(run_id) == []


def test_rows_are_org_scoped():
    from aughor.org.context import reset_org_id, set_org_id

    sid = _suite_with([{"question": "mine", "artifact": "SELECT 1"}])
    token = set_org_id("someone-else")
    try:
        assert store.list_suites() == []
        assert store.get_suite(sid) is None
        assert store.list_cases(sid) == []
    finally:
        reset_org_id(token)
    assert store.get_suite(sid) is not None


# ── the measurement discipline ────────────────────────────────────────────────

def test_reference_replay_is_fully_correct(db):
    """The harness gate in miniature: replaying known-correct SQL must score
    100%, because there is no model variance to hide a runner defect behind."""
    sid = _suite_with([
        {"question": "all rows", "artifact": "SELECT id, v FROM t ORDER BY id",
         "expected": {"reference_sql": "SELECT id, v FROM t ORDER BY id"}},
        {"question": "total", "artifact": "SELECT SUM(v) FROM t",
         "expected": {"reference_sql": "SELECT SUM(v) FROM t"}},
    ])
    summary = run_suite(sid, reference_target(db), checker=reference_checker(db))
    assert summary.accuracy == 1.0
    assert summary.errors == 0


def test_flaky_case_is_not_rounded_up_to_a_pass(db):
    """A case that passes some iterations and not others is its own verdict.
    Counting it as a pass is how a suite talks itself into a green number."""
    sid = _suite_with([{"question": "q", "artifact": "SELECT 1"}])
    calls = {"n": 0}

    def flapping(case: EvalCase) -> EvalObservation:
        calls["n"] += 1
        # error on odd iterations only
        return EvalObservation(sql="SELECT 1",
                               error="" if calls["n"] % 2 == 0 else "boom")

    summary = run_suite(sid, flapping, iterations=3)
    assert summary.flaky == 1
    assert summary.stable_pass == 0
    assert summary.pass_rate == 0.0, "a flaky case must not count toward the pass rate"
    assert summary.outcomes[0].verdict == FLAKY


def test_stable_verdicts(db):
    sid = _suite_with([{"question": "q", "artifact": "SELECT 1"}])
    good = run_suite(sid, lambda c: EvalObservation(sql="SELECT 1"), iterations=3)
    assert good.outcomes[0].verdict == STABLE_PASS

    bad = run_suite(sid, lambda c: EvalObservation(sql="SELECT 1", error="always"),
                    iterations=3)
    assert bad.outcomes[0].verdict == STABLE_FAIL


def test_causal_attribution_records_which_evaluators_fired(db):
    """Aggregate deltas lie at small n. "Did my change touch THIS case, and did
    that case flip" needs per-case evaluator attribution, which cannot be
    reconstructed from a stored percentage."""
    sid = _suite_with([{"question": "q", "artifact": "DELETE FROM t"}])
    summary = run_suite(sid, reference_target(db))

    outcome = summary.outcomes[0]
    assert "guard.readonly" in outcome.fired
    assert summary.fired_counts["guard.readonly"] == 1

    rows = store.run_results(summary.run_id)
    assert rows and "guard.readonly" in rows[0]["fired"]
    assert any(s["evaluator"] == "guard.readonly" for s in rows[0]["scores"])


def test_unstable_evaluator_is_singled_out(db):
    """An evaluator that fires in some iterations but not others is a sharper
    flake signal than the case-level verdict."""
    sid = _suite_with([{"question": "q", "artifact": "SELECT 1"}])
    calls = {"n": 0}

    def flapping(case: EvalCase) -> EvalObservation:
        calls["n"] += 1
        # a mutating statement only on the first iteration → readonly fires once
        return EvalObservation(sql="DELETE FROM t" if calls["n"] == 1 else "SELECT 1")

    from aughor.trust import Scope
    def target(case):
        case.scope = Scope(conn=db, dialect="duckdb")
        return flapping(case)

    summary = run_suite(sid, target, iterations=3)
    assert summary.outcomes[0].unstable_evaluators == ["guard.readonly"]


def test_guard_clean_and_correct_are_separate_claims(db):
    """A query can be correct and still trip an advisory guard. Conflating the
    two would make either number meaningless."""
    sid = _suite_with([{
        "question": "sum",
        "artifact": "SELECT SUM(v) FROM t",
        "expected": {"reference_sql": "SELECT SUM(v) FROM t"},
    }])
    summary = run_suite(sid, reference_target(db), checker=reference_checker(db))
    assert summary.accuracy == 1.0             # the answer is right
    assert summary.pass_rate in (0.0, 1.0)     # guard-clean is a different axis
    assert summary.correctness_known == 1


def test_cases_without_an_expectation_are_not_scored_as_misses(db):
    sid = _suite_with([{"question": "no expectation", "artifact": "SELECT 1"}])
    summary = run_suite(sid, reference_target(db), checker=reference_checker(db))
    assert summary.correctness_known == 0
    assert summary.accuracy is None, "an unmeasured case must not become a failure"


def test_run_records_the_model_it_ran_under(db):
    """The ratchet's five historical runs have no model column, so their
    0.62-0.66 spread cannot be compared with anything — a later number would
    silently mix a harness change with a model change."""
    sid = _suite_with([{"question": "q", "artifact": "SELECT 1"}])
    summary = run_suite(sid, reference_target(db))

    cfg = store.get_run(summary.run_id)["config"]
    assert "backend" in cfg
    assert "models" in cfg and "coder" in cfg["models"]
    assert "flags" in cfg
    assert cfg["iterations"] == 1


def test_a_target_that_raises_fails_one_case_not_the_run(db):
    """One bad case must not cost you the other results."""
    sid = _suite_with([
        {"question": "ok", "artifact": "SELECT 1"},
        {"question": "boom", "artifact": "SELECT 2"},
    ])

    def target(case: EvalCase) -> EvalObservation:
        if case.question == "boom":
            raise RuntimeError("target exploded")
        return EvalObservation(sql=case.artifact)

    summary = run_suite(sid, target)
    assert summary.total == 2
    assert summary.errors == 1
    assert summary.stable_pass == 1
    assert store.get_run(summary.run_id)["status"] == store.SUCCEEDED


# ── the API surface + the consolidation ───────────────────────────────────────

def test_suite_crud_over_http(client):
    created = client.post("/evals/suites", json={"name": "http suite"})
    assert created.status_code == 201, created.text
    sid = created.json()["id"]

    assert client.post(f"/evals/suites/{sid}/cases", json={
        "cases": [{"question": "q", "artifact": "SELECT 1"}]}).status_code == 201

    got = client.get(f"/evals/suites/{sid}")
    assert got.status_code == 200
    assert len(got.json()["cases"]) == 1

    assert client.delete(f"/evals/suites/{sid}").status_code == 200
    assert client.get(f"/evals/suites/{sid}").status_code == 404


def test_eval_suite_capability_now_gates_something(client, monkeypatch):
    """`eval.suite` was declared in the licensing table and sold as Enterprise
    while gating NOTHING — there was not one gate(Capability.EVAL_SUITE) call
    site. This is the test that it is real."""
    from aughor.licensing import Capability

    calls: list = []

    def deny(cap, conn_id=None):
        calls.append(cap)
        return cap is not Capability.EVAL_SUITE

    monkeypatch.setattr("aughor.licensing.deps.has_capability", deny)
    r = client.get("/evals/suites")
    assert r.status_code == 402, r.text
    assert r.json()["detail"]["capability"] == "eval.suite"
    assert Capability.EVAL_SUITE in calls


def test_evaluators_endpoint_describes_the_set(client):
    body = client.get("/evals/evaluators").json()
    assert body["deterministic_count"] == len(body["evaluators"])
    names = {e["name"] for e in body["evaluators"]}
    assert "guard.readonly" in names
    readonly = next(e for e in body["evaluators"] if e["name"] == "guard.readonly")
    assert readonly["severity"] == "block"


def test_dead_eval_run_stub_is_gone(client):
    """It was ungated, hardcoded live=False so it scored reference SQL against
    itself, read a CWD-relative path into an unpackaged directory (a permanent
    503 from a wheel), and had zero callers. Keeping a broken ungated endpoint
    because it happened to exist is worse than removing it."""
    assert client.post("/eval/run").status_code == 404


def test_run_a_suite_over_http(client, db, monkeypatch, tmp_path):
    """End-to-end through the API against a registered connection."""
    from aughor.db import registry

    conn_id = registry.add_connection("evals-http", "duckdb", str(db._path))
    created = client.post("/evals/suites", json={
        "name": "run me", "target": "reference", "connection_id": conn_id})
    sid = created.json()["id"]
    client.post(f"/evals/suites/{sid}/cases", json={"cases": [
        {"question": "rows", "artifact": "SELECT id, v FROM t ORDER BY id",
         "expected": {"reference_sql": "SELECT id, v FROM t ORDER BY id"}}]})

    r = client.post(f"/evals/suites/{sid}/run", json={"iterations": 2})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    assert body["accuracy"] == 1.0
    assert body["iterations"] == 2
    assert body["config"]["backend"]

    runs = client.get("/evals/runs", params={"suite_id": sid}).json()["runs"]
    assert len(runs) == 1
    detail = client.get(f"/evals/runs/{runs[0]['id']}").json()
    assert len(detail["results"]) == 2      # 1 case x 2 iterations


def test_dry_run_leaves_no_trace(db):
    sid = _suite_with([{"question": "q", "artifact": "SELECT 1"}])
    summary = run_suite(sid, reference_target(db), persist=False)
    assert summary.run_id == "dry"
    assert store.list_runs(sid) == []
