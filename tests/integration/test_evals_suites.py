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


# ── E6: the flag promotion gate ─────────────────────────────────────────────────

_REG = {"demo.flag", "other.flag"}
_CLEAN = {"run_id": "r1", "suite_id": "s1", "total": 3, "pass_rate": 1.0, "errors": 0, "flaky": 0}


def test_graduation_unknown_flag_is_blocked():
    from aughor.evals.promotion import evaluate_graduation
    d = evaluate_graduation("nope.flag", _CLEAN, registered_flags=_REG)
    assert not d.can_graduate
    assert any("not in the flag registry" in r for r in d.reasons)


def test_graduation_needs_a_run():
    from aughor.evals.promotion import evaluate_graduation
    d = evaluate_graduation("demo.flag", None, registered_flags=_REG)
    assert not d.can_graduate
    assert any("no run" in r for r in d.reasons)


def test_graduation_blocked_by_errors_and_by_flaky():
    """A graduation cannot rest on a run that errored or that was flaky — flaky is
    E3's first-class verdict precisely so stability is not rounded away here."""
    from aughor.evals.promotion import evaluate_graduation
    err = evaluate_graduation("demo.flag", {**_CLEAN, "errors": 1}, registered_flags=_REG)
    assert not err.can_graduate and any("errored" in r for r in err.reasons)
    flaky = evaluate_graduation("demo.flag", {**_CLEAN, "flaky": 2}, registered_flags=_REG)
    assert not flaky.can_graduate and any("flaky" in r for r in flaky.reasons)


def test_graduation_is_judged_against_the_baseline():
    from aughor.evals.promotion import evaluate_graduation
    below = evaluate_graduation("demo.flag", {**_CLEAN, "pass_rate": 0.60},
                                registered_flags=_REG, baseline_pass_rate=0.65)
    assert not below.can_graduate and below.bar == 0.65
    assert any("below the bar" in r for r in below.reasons)

    # Beating the bar is necessary but NOT sufficient: a baseline implies an A/B, and an
    # A/B without its noise floor is how a flag graduates on jitter (Wave L2 found the
    # gate saying yes to a +0.023 delta that fidelity was refusing against a 0.182 band).
    unfloored = evaluate_graduation("demo.flag", {**_CLEAN, "pass_rate": 0.66},
                                    registered_flags=_REG, baseline_pass_rate=0.65)
    assert not unfloored.can_graduate
    assert any("no floor evidence" in r for r in unfloored.reasons)

    from aughor.evals import fidelity as _FI
    quiet = _FI.compare([{"pass_rate": 0.650, "total": 100}, {"pass_rate": 0.651, "total": 100}],
                        [{"pass_rate": 0.660, "total": 100}, {"pass_rate": 0.661, "total": 100}],
                        axis="pass_rate")
    earned = evaluate_graduation("demo.flag", {**_CLEAN, "pass_rate": 0.66},
                                 registered_flags=_REG, baseline_pass_rate=0.65,
                                 delta=quiet)
    assert earned.can_graduate and earned.reasons == []
    assert earned.pass_rate == 0.66 and earned.baseline_pass_rate == 0.65


def test_graduation_without_a_baseline_demands_a_clean_run():
    """With no baseline to beat, min_pass_rate (default 1.0) is the bar — a candidate
    must be clean rather than merely non-regressive against nothing."""
    from aughor.evals.promotion import evaluate_graduation
    assert not evaluate_graduation("demo.flag", {**_CLEAN, "pass_rate": 0.99},
                                   registered_flags=_REG).can_graduate
    assert evaluate_graduation("demo.flag", _CLEAN, registered_flags=_REG).can_graduate


def test_graduate_a_real_flag_over_http_and_receipt_it(client, db):
    """The E6 decision gate: graduate exactly one REAL flag through the gate, and prove
    the load-bearing property — graduation records receipted EVIDENCE and does NOT flip
    the flag (a ledger-on/code-off override is the very drift the 2026-07-22 audit removed)."""
    from aughor.db import registry
    from aughor.kernel.flags import flag_state

    conn_id = registry.add_connection("evals-grad", "duckdb", str(db._path))
    sid = client.post("/evals/suites", json={
        "name": "grad", "target": "reference", "connection_id": conn_id}).json()["id"]
    client.post(f"/evals/suites/{sid}/cases", json={"cases": [
        {"question": "rows", "artifact": "SELECT id, v FROM t ORDER BY id"}]})
    client.post(f"/evals/suites/{sid}/run", json={"iterations": 3})

    flag = "ada.evidence_stubs"          # a real, default-OFF flag (the E4 A/B candidate)
    before = flag_state(flag)
    assert before == "off"

    # A caller-supplied baseline carries no provenance: nothing says the two numbers came
    # from runs that agree with themselves. The route therefore REFUSES it, and says why,
    # rather than graduating on a bar it cannot see the noise around.
    r = client.post(f"/evals/flags/{flag}/graduate",
                    json={"suite_id": sid, "baseline_pass_rate": 1.0})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["can_graduate"] is False and body["flag"] == flag
    assert any("no floor evidence" in x for x in body["reasons"])
    assert body["receipt_id"] and body["current_default"] is False

    # …and a clean run judged against min_pass_rate (no baseline ⇒ no A/B ⇒ nothing to
    # floor-verify) still graduates, so the gate did not become unpassable.
    r2 = client.post(f"/evals/flags/{flag}/graduate", json={"suite_id": sid})
    assert r2.status_code == 200 and r2.json()["can_graduate"] is True

    grads = client.get("/evals/graduations", params={"flag": flag}).json()["graduations"]
    assert len(grads) == 2                       # the refusal is receipted too

    # THE anti-drift guarantee — the gate recorded evidence, it did not turn the flag on.
    assert flag_state(flag) == before == "off"


def test_graduate_without_a_run_reports_the_blocker_not_a_500(client):
    sid = client.post("/evals/suites", json={"name": "empty"}).json()["id"]
    r = client.post("/evals/flags/ada.evidence_stubs/graduate", json={"suite_id": sid})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["can_graduate"] is False
    assert any("no run" in x for x in body["reasons"])
    assert body["suite_id"] == sid          # pinned from the request even with no run
