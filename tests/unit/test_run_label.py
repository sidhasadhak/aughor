"""TJ-3 (2026-09-26): one run label, deterministic, from what the run recorded.

Pinned: positive only when every statement ran, returned rows, no guard but lint fired, the
re-check (when it ran) found the number unchanged and nobody rejected it; negative on an
error, a fan-out or grain fire, a changed re-check or a reject; everything else unlabeled
with the reason — a store that could not be read, a caveating guard, no rows, nothing ran;
the bronze tier and the trajectory's reward read this one rule; the door publishes the
distribution and says whether the label discriminates.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from aughor.api import app
from aughor.learning import reward as rw

client = TestClient(app)


def _t(executions=None, guards=None, answers=None):
    return {"executions": executions, "guards": guards, "answers": answers}


OK_EXEC = [{"sql": "SELECT 1", "row_count": 3, "error": None}]


def test_positive_needs_everything_and_says_so():
    r = rw.run_label(_t(OK_EXEC, [], [{"rechecks": [{"status": "unchanged"}]}]))
    assert r["label"] == "positive" and r["evidence"]["rows"] == 3 and r["evidence"]["recheck"] == "unchanged"
    # Lint is the one guard that does not disqualify; a caveat does (unlabeled), a grain fire negates.
    assert rw.run_label(_t(OK_EXEC, [{"pattern": "lint", "action": "flagged"}], [])) ["label"] == "positive"
    r = rw.run_label(_t(OK_EXEC, [{"pattern": "row_filter", "action": "caveated"}], []))
    assert r["label"] == "unlabeled" and r["reasons"] == ["a guard fired: row_filter"]
    r = rw.run_label(_t(OK_EXEC, [{"pattern": "grain_check", "action": "flagged"}], []))
    assert r["label"] == "negative" and r["reasons"] == ["a grain_check guard fired"]
    assert rw.run_label(_t(OK_EXEC, [{"pattern": "fan-out", "action": "caveated_headline"}], []))["label"] == "negative"
    # A guard that passed is not a fire; one whose action was never recorded is unknown — not clean.
    assert rw.run_label(_t(OK_EXEC, [{"pattern": "grain_check", "action": "passed"}], []))["label"] == "positive"
    r = rw.run_label(_t(OK_EXEC, [{"pattern": "fanout", "action": ""}], []))
    assert r["label"] == "unlabeled" and r["reasons"] == ["a guard's action was not recorded: fanout"]


def test_negative_on_an_error_a_reject_or_a_changed_recheck():
    r = rw.run_label(_t([{"sql": "SELECT", "row_count": 0, "error": "syntax"}], [], []))
    assert r["label"] == "negative" and r["reasons"][0].startswith("a statement failed: syntax")
    r = rw.run_label(_t(OK_EXEC, [], [{"verdict": {"verdict": "reject"}}]))
    assert r["label"] == "negative" and r["reasons"] == ["a person rejected it"] and r["evidence"]["human_verdict"] == "reject"
    r = rw.run_label(_t(OK_EXEC, [], [{"rechecks": [{"status": "unchanged"}, {"status": "changed"}]}]))
    assert r["label"] == "negative" and r["reasons"] == ["the re-check found the number changed"]
    # An accept does not make a failed run positive.
    assert rw.run_label(_t([{"error": "boom"}], [], [{"verdict": {"verdict": "accept"}}]))["label"] == "negative"


def test_unlabeled_is_the_default_and_carries_its_reason():
    assert rw.run_label(_t(None, [], [])) == {"label": "unlabeled", "reasons": ["the execution store could not be read"],
                                             "evidence": {"execution": None, "rows": None, "guard_fires": [], "recheck": None,
                                                          "human_verdict": None, "contradiction": None}}
    assert rw.run_label(_t([], [], []))["reasons"] == ["no statement ran"]
    assert rw.run_label(_t([{"sql": "s", "row_count": 0, "error": None}], [], []))["reasons"] == ["a statement returned no rows"]
    assert rw.run_label(_t(OK_EXEC, None, []))["reasons"] == ["the guard store could not be read"]
    assert rw.run_label({})["label"] == "unlabeled"


def test_the_trajectory_and_the_bronze_tier_read_the_one_rule(monkeypatch):
    from aughor.learning import exporters
    from aughor.obs import trajectory as tj
    good = {"executions": OK_EXEC, "guards": [], "answers": [], "steps": [{"tool": "run_sql", "sql": "SELECT 1"}],
            "reward": {"execution": "ok"}}
    bad = {**good, "executions": [{"sql": "s", "row_count": 0, "error": "boom"}]}
    monkeypatch.setattr(tj, "trajectory_of", lambda trace: good if trace == "t-good" else bad)
    clean, ctx = exporters._trajectory_clean({"trace_id": "t-good"})
    assert clean is True and ctx["label"] == "positive"
    clean, ctx = exporters._trajectory_clean({"trace_id": "t-bad"})
    assert clean is False and ctx["label"] == "negative"
    reward = tj._reward([{"verdict": {"verdict": "reject"}}], OK_EXEC, [])
    assert reward["label"] == "negative" and reward["human_verdict"] == "reject"


def test_the_distribution_says_whether_the_label_discriminates():
    d = rw.distribution([{"label": "positive", "reasons": ["x"]}, {"label": "positive", "reasons": ["x"]}])
    assert d["counts"] == {"positive": 2, "negative": 0, "unlabeled": 0} and d["discriminating"] is False
    d = rw.distribution([{"label": "positive", "reasons": []}, {"label": "negative", "reasons": ["a statement failed: e"]}])
    assert d["n"] == 2 and d["discriminating"] is True and d["reasons"] == {"a statement failed": 1}


def test_the_door_labels_recent_answers_from_their_trajectories(monkeypatch):
    monkeypatch.setattr("aughor.db.history.recent_runs", lambda since, limit=200: [
        {"id": "i1", "kind": "chat", "question": "q1", "connection_id": "c", "completed_at": "2026-09-26T10:00:00",
         "trace_id": "t1", "sql": "SELECT 1"},
        {"id": "i2", "kind": "investigation", "question": "q2", "connection_id": "c", "completed_at": "2026-09-26T09:00:00",
         "trace_id": "t2", "sql": "SELECT 2"}])
    monkeypatch.setattr("aughor.obs.trajectory.trajectory_of", lambda trace: (
        {"executions": OK_EXEC, "guards": [], "answers": []} if trace == "t1"
        else {"executions": [{"error": "boom"}], "guards": [], "answers": []}))
    body = client.get("/learning/run-labels", params={"days": 7, "limit": 10, "rows": "true"}).json()
    assert body["asked"] == 2 and body["counts"] == {"positive": 1, "negative": 1, "unlabeled": 0}
    assert body["discriminating"] is True and [r["label"] for r in body["rows"]] == ["positive", "negative"]
    assert body["by_kind"] == {"chat": {"positive": 1, "negative": 0, "unlabeled": 0},
                               "investigation": {"positive": 0, "negative": 1, "unlabeled": 0}}
    assert body["rows"][0]["sql"] == "SELECT 1" and "step credit" in body["note"]
