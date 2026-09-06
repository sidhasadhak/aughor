"""The derived experiments surface (`evals/compare.py`) and its routes.

An experiment here is never stored — it is a pair of runs whose RECORDED requests
(`config.cell_requested`) differ on exactly one axis. These tests pin the three laws the
module inherits: classification by what the run recorded (never its label), a case one
cell never reached counts as `unrun` (never as a flip), and a pair whose configs differ
on more than one axis is not an experiment at all.

Hermetic — `tests/conftest.py` points `AUGHOR_EVALS_DB` at a tempdir.
"""
from __future__ import annotations

from aughor.evals import store
from aughor.evals.compare import compare_runs, find_experiments


def _suite_with_cases(n: int = 3) -> tuple[str, list[str]]:
    suite = store.create_suite("compare-fixture", target="reference", connection_id="c1")
    sid = suite["id"]
    store.add_cases(sid, [{"question": f"q{i}", "expected": {}} for i in range(n)])
    return sid, [c["id"] for c in store.list_cases(sid)]


def _run(sid: str, *, flags: dict | None = None, model: str | None = None,
         results: dict[str, tuple[bool, bool | None]] | None = None,
         extra_config: dict | None = None) -> str:
    """One stored run shaped the way `run_experiment` stamps it."""
    config = {"cell": "cell", "cell_requested": {"label": "cell", "model": model,
                                                "temperature": 0, "flags": flags or {}},
              "flag_overrides": flags or {}}
    config.update(extra_config or {})
    run_id = store.start_run(sid, config=config)
    for case_id, (passed, correct) in (results or {}).items():
        store.record_result(run_id, case_id, 0, passed=passed, correct=correct)
    n = len(results or {})
    store.finish_run(run_id, summary={"pass_rate": 1.0, "total": n,
                                      "correct": sum(1 for _, c in (results or {}).values() if c),
                                      "correctness_known": sum(1 for _, c in (results or {}).values()
                                                               if c is not None)})
    return run_id


def test_a_flag_pair_is_found_and_oriented_by_recorded_value_not_label():
    sid, cases = _suite_with_cases()
    on = _run(sid, flags={"explore.x": True},
              results={c: (True, True) for c in cases})
    off = _run(sid, flags={"explore.x": False},
               results={c: (True, True) for c in cases})

    found = find_experiments(sid)
    assert len(found) == 1
    exp = found[0]
    assert exp["axis"] == {"kind": "flag", "name": "explore.x"}
    # Orientation comes from the recorded flag value: `a` is the OFF run even though
    # the ON run is older/newer is irrelevant.
    assert exp["a"]["run_id"] == off
    assert exp["b"]["run_id"] == on


def test_two_moved_axes_are_not_an_experiment():
    sid, cases = _suite_with_cases(1)
    _run(sid, flags={"explore.x": True}, model="m1",
         results={cases[0]: (True, True)})
    _run(sid, flags={"explore.x": False}, model="m2",
         results={cases[0]: (True, True)})
    assert find_experiments(sid) == []


def test_a_model_pair_pairs_when_flags_are_identical():
    sid, cases = _suite_with_cases(1)
    _run(sid, model="m-new", results={cases[0]: (True, True)})
    _run(sid, model="m-old", results={cases[0]: (True, True)})
    found = find_experiments(sid)
    assert len(found) == 1
    assert found[0]["axis"]["kind"] == "model"


def test_runs_without_cell_requested_fall_back_to_flag_overrides():
    sid, cases = _suite_with_cases(1)
    for value in (False, True):
        run_id = store.start_run(sid, config={"flag_overrides": {"legacy.flag": value}})
        store.record_result(run_id, cases[0], 0, passed=True, correct=True)
        store.finish_run(run_id, summary={"pass_rate": 1.0})
    found = find_experiments(sid)
    assert len(found) == 1
    assert found[0]["axis"] == {"kind": "flag", "name": "legacy.flag"}


def test_compare_counts_flips_and_unrun_and_paired_accuracy():
    sid, cases = _suite_with_cases(4)
    gained, lost, same, unrun = cases
    a = _run(sid, flags={"f": False}, results={
        gained: (True, False), lost: (True, True), same: (True, True),
        unrun: (True, True)})
    b = _run(sid, flags={"f": True}, results={
        gained: (True, True), lost: (True, False), same: (True, True)})
    # `unrun` never reached cell b — a killed grid must not read as "the flag lost it".

    out = compare_runs(a, b)
    assert out["flips"] == {"same": 1, "gained": 1, "lost": 1, "other": 0, "unrun": 1}
    assert out["accuracy"]["paired"] == {"cases": 3, "a_correct": 2, "b_correct": 2}
    kinds = {r["case_id"]: r["kind"] for r in out["rows"]}
    assert kinds == {gained: "gained", lost: "lost"}


def test_compare_refuses_runs_from_different_suites():
    import pytest

    sid_a, cases_a = _suite_with_cases(1)
    sid_b, cases_b = _suite_with_cases(1)
    a = _run(sid_a, flags={"f": False}, results={cases_a[0]: (True, True)})
    b = _run(sid_b, flags={"f": True}, results={cases_b[0]: (True, True)})
    with pytest.raises(ValueError):
        compare_runs(a, b)


def test_routes_serve_the_pair_and_the_diff(client):
    sid, cases = _suite_with_cases(1)
    a = _run(sid, flags={"f": False}, results={cases[0]: (True, False)})
    b = _run(sid, flags={"f": True}, results={cases[0]: (True, True)})

    listed = client.get(f"/evals/experiments?suite_id={sid}")
    assert listed.status_code == 200
    exps = listed.json()["experiments"]
    assert len(exps) == 1 and exps[0]["a"]["run_id"] == a

    diff = client.get(f"/evals/experiments/compare?a={a}&b={b}")
    assert diff.status_code == 200
    body = diff.json()
    assert body["flips"]["gained"] == 1
    assert body["axis"] == {"kind": "flag", "name": "f"}

    missing = client.get("/evals/experiments/compare?a=nope&b=nada")
    assert missing.status_code == 404
