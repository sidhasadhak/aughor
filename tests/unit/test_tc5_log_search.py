"""Arc TC, TC-5 — `GET /obs/logs`: the lines `/traces/{id}/logs` reads for one run, searched
across every run of the last thirty days, from the journal's own rows (no copy).

Each test seeds lines carrying a word of its own, so what other tests journaled into the same
store cannot make a count pass or fail here.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from aughor.kernel.ledger import Ledger


@pytest.fixture()
def client():
    from aughor.api import app
    return TestClient(app)


def _word() -> str:
    return f"tc5word{uuid.uuid4().hex[:10]}"


def _line(kind: str, payload: dict, *, trace: str, job: str | None = None) -> int:
    return Ledger.default().emit(kind, payload, trace_id=trace, job_id=job)


def _job(kind: str) -> str:
    jid = f"tc5-job-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc).isoformat()
    Ledger.default().job_insert({"id": jid, "kind": kind, "state": "SUCCEEDED", "created_at": now,
                                 "attempt": 1})
    return jid


def _search(client, **params) -> dict:
    r = client.get("/obs/logs", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_a_search_reads_across_runs_newest_first_and_says_what_it_searched(client):
    w = _word()
    t1, t2 = f"tc5-tr-{uuid.uuid4().hex[:6]}", f"tc5-tr-{uuid.uuid4().hex[:6]}"
    first = _line("error.tolerated", {"reason": f"{w} could not read", "error": "KeyError", "counter": "x.y"}, trace=t1)
    second = _line("job.state", {"state": "RUNNING", "note": w}, trace=t2)
    _line("job.state", {"state": "RUNNING", "note": w}, trace="")      # written under no run

    body = _search(client, q=w.upper())                                 # matched case-folded
    seqs = [ln["seq"] for ln in body["lines"]]
    assert seqs == [second, first], "not newest first, or a line outside any run was read"
    assert {ln["trace_id"] for ln in body["lines"]} == {t1, t2}
    tolerated = next(ln for ln in body["lines"] if ln["seq"] == first)
    assert tolerated["reason"].startswith(w) and tolerated["payload"] is None
    searched = body["searched"]
    assert searched["window_days"] == 30 and searched["runs"] >= 2 and searched["lines"] >= 2
    assert searched["oldest_line_at"] and searched["oldest_line_at"] >= searched["since"]
    assert searched["kept_sooner"]["kinds"], "the sweep that keeps some kinds fewer days goes unsaid"
    assert body["next_cursor"] is None and body["stopped_early"] is False


def test_the_level_is_read_from_the_line(client):
    w = _word()
    tr = f"tc5-tr-{uuid.uuid4().hex[:6]}"
    failed = _line("job.state", {"state": "FAILED", "w": w}, trace=tr)
    survived = _line("error.tolerated", {"reason": w, "error": "E", "counter": "c"}, trace=tr)
    ran = _line("job.state", {"state": "RUNNING", "w": w}, trace=tr)

    levels = {ln["seq"]: ln["level"] for ln in _search(client, q=w)["lines"]}
    assert levels == {failed: "error", survived: "warning", ran: "info"}
    assert [ln["seq"] for ln in _search(client, q=w, level="error")["lines"]] == [failed]
    assert client.get("/obs/logs", params={"q": w, "level": "loud"}).status_code == 422


def test_the_kind_of_run_is_the_jobs_and_request_outside_one(client):
    w = _word()
    explored = _line("exploration.phase", {"phase": "profile", "w": w},
                     trace=f"tc5-tr-{uuid.uuid4().hex[:6]}", job=_job("exploration"))
    asked = _line("trace.feedback", {"verdict": "helpful", "note": w}, trace=f"tc5-tr-{uuid.uuid4().hex[:6]}")

    body = _search(client, q=w)
    kinds = {ln["seq"]: ln["run_kind"] for ln in body["lines"]}
    assert kinds == {explored: "exploration", asked: "request"}
    assert {"exploration", "request"} <= set(body["run_kinds"])
    assert [ln["seq"] for ln in _search(client, q=w, run_kind="request")["lines"]] == [asked]


def test_the_cursor_pages_without_repeats_or_gaps(client):
    w = _word()
    tr = f"tc5-tr-{uuid.uuid4().hex[:6]}"
    seeded = [_line("job.state", {"state": "RUNNING", "n": i, "w": w}, trace=tr) for i in range(5)]

    seen, cursor, pages = [], None, 0
    while True:
        params = {"q": w, "limit": 2, **({"cursor": cursor} if cursor else {})}
        body = _search(client, **params)
        seen += [ln["seq"] for ln in body["lines"]]
        pages += 1
        cursor = body["next_cursor"]
        if not cursor:
            break
        assert pages < 10, "the cursor never ends"
    assert seen == sorted(seeded, reverse=True)
    bad = client.get("/obs/logs", params={"q": w, "cursor": "not-a-cursor"})
    assert bad.status_code == 422 and "cursor" in bad.json()["detail"]


def test_a_line_older_than_the_window_is_not_searched(client):
    w = _word()
    tr = f"tc5-tr-{uuid.uuid4().hex[:6]}"
    old = _line("job.state", {"state": "FAILED", "w": w}, trace=tr)
    new = _line("job.state", {"state": "FAILED", "w": w}, trace=tr)
    led = Ledger.default()
    with led._lock, led._conn:
        led._conn.execute("UPDATE events SET at = ? WHERE seq = ?",
                          ((datetime.now(timezone.utc) - timedelta(days=31)).isoformat(), old))

    assert [ln["seq"] for ln in _search(client, q=w)["lines"]] == [new]


def test_a_wildcard_in_the_words_is_a_character(client):
    w = _word()
    tr = f"tc5-tr-{uuid.uuid4().hex[:6]}"
    literal = _line("job.state", {"note": f"{w}a_b"}, trace=tr)
    _line("job.state", {"note": f"{w}axb"}, trace=tr)
    assert [ln["seq"] for ln in _search(client, q=f"{w}a_b")["lines"]] == [literal]
