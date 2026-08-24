"""The trace index — filtered, counted, then paginated, in that order.

The surface this feeds used to be a fixed list of recent runs with no filters at all. The
tempting shortcut is to fetch a page and narrow it in the browser: it looks identical to
the reader and answers a different question — "the matching runs" versus "the matching
runs among the last fifty" — and a total taken after the slice would confirm the wrong
one. These tests pin the order, because the order is the whole contract.
"""
from __future__ import annotations

import pytest

from aughor.obs import session_log


@pytest.fixture()
def runs(monkeypatch):
    """Install a set of folded runs, bypassing the ledger."""
    def _install(rows):
        monkeypatch.setattr(session_log, "recent_sessions",
                            lambda **kw: [dict(r) for r in rows])
        return rows
    return _install


def run(trace_id: str, **over) -> dict:
    return {"trace_id": trace_id, "started": "2026-08-25T10:00:00Z", "question": "",
            "answer": "", "events": 3, "tool_calls": 0, "llm_calls": 1, "errors": 0,
            "investigation_id": None, "session_id": None, "agent_id": None,
            "conn_id": None, "ok": True, "duration_ms": 100.0, "user_id": None,
            "ended_at": "2026-08-25T10:00:01Z", "prompt_tokens": 0,
            "completion_tokens": 0, "total_tokens": 0, "cost_usd": 0.0,
            "unpriced_calls": 0, "calls_without_usage": 0, **over}


def test_the_total_counts_matches_not_the_page(runs):
    """A total taken after the slice would report the page size and look right."""
    runs([run(f"t{i}", user_id="u1") for i in range(30)]
         + [run(f"x{i}", user_id="u2") for i in range(5)])

    out = session_log.session_index(user_id="u1", limit=10)

    assert len(out["rows"]) == 10
    assert out["total"] == 30, "the count is of everything that matched, not of the page"


def test_a_filter_reaches_past_the_first_page(runs):
    """The defect a client-side filter cannot avoid: a match on page three is invisible."""
    rows = [run(f"t{i}") for i in range(40)]
    rows[35]["question"] = "why did revenue drop"
    runs(rows)

    out = session_log.session_index(q="revenue", limit=10)

    assert out["total"] == 1
    assert out["rows"][0]["trace_id"] == "t35"


def test_paging_walks_the_filtered_set(runs):
    runs([run(f"t{i}", total_tokens=500) for i in range(25)])

    first = session_log.session_index(min_tokens=100, limit=10, offset=0)
    third = session_log.session_index(min_tokens=100, limit=10, offset=20)

    assert [r["trace_id"] for r in first["rows"]][0] == "t0"
    assert len(third["rows"]) == 5 and third["total"] == 25


# ── the three states, told apart ──────────────────────────────────────────────────

def test_status_separates_ok_error_and_no_recorded_result(runs):
    runs([run("ok1", ok=True), run("bad", ok=False),
          run("errs", ok=True, errors=2), run("live", ok=None, duration_ms=None)])

    assert {r["trace_id"] for r in session_log.session_index(status="ok")["rows"]} == {"ok1", "errs"}
    # A run that finished with errors is a failure to a reader hunting failures, even
    # though its final response arrived.
    assert {r["trace_id"] for r in session_log.session_index(status="error")["rows"]} == {"bad", "errs"}
    # NOT "running": only the /ask and /chat door emits a final response, so most runs
    # without one are finished. Measured live at 53 of 73, the oldest four days old.
    assert {r["trace_id"] for r in session_log.session_index(status="unfinished")["rows"]} == {"live"}


def test_duration_and_token_thresholds_are_inclusive_of_the_boundary(runs):
    runs([run("fast", duration_ms=50.0, total_tokens=10),
          run("slow", duration_ms=5000.0, total_tokens=9000)])

    assert [r["trace_id"] for r in session_log.session_index(min_duration_ms=5000)["rows"]] == ["slow"]
    assert [r["trace_id"] for r in session_log.session_index(max_duration_ms=50)["rows"]] == ["fast"]
    assert [r["trace_id"] for r in session_log.session_index(min_tokens=9000)["rows"]] == ["slow"]


def test_search_reads_the_answer_as_well_as_the_question(runs):
    """A person looking for a run remembers what came back as often as what went in."""
    runs([run("a", question="revenue by region"),
          run("b", answer="Revenue fell 8% in EMEA"),
          run("c", question="unrelated")])

    assert {r["trace_id"] for r in session_log.session_index(q="revenue")["rows"]} == {"a", "b"}


def test_the_window_is_reported_rather_than_implied(runs):
    """`total` is a total WITHIN the scan, and a count with no stated window is a claim
    about all of history that nobody checked."""
    runs([run("t1")])

    assert session_log.session_index(scan=1234)["scanned_events"] == 1234


# ── through the route, because a filter the route drops is a filter nobody has ────────

def test_the_route_passes_every_filter_through(monkeypatch):
    """The index can be perfect and the endpoint still ignore it — that exact shape (a
    capture already firing into a sink the route never set) cost a wave once already."""
    from fastapi.testclient import TestClient

    from aughor.api import app

    seen: dict = {}

    def _spy(**kwargs):
        seen.update(kwargs)
        return {"rows": [], "total": 0, "limit": kwargs.get("limit", 0),
                "offset": kwargs.get("offset", 0), "scanned_events": 4000}

    monkeypatch.setattr(session_log, "session_index", _spy)
    client = TestClient(app)

    res = client.get("/traces", params={
        "status": "error", "user_id": "u9", "q": "revenue", "min_duration_ms": 1000,
        "max_duration_ms": 9000, "min_tokens": 500, "limit": 10, "offset": 20,
        "since": "2026-08-01T00:00:00Z", "until": "2026-08-25T00:00:00Z",
    })

    assert res.status_code == 200
    assert seen["status"] == "error" and seen["user_id"] == "u9" and seen["q"] == "revenue"
    assert seen["min_duration_ms"] == 1000 and seen["max_duration_ms"] == 9000
    assert seen["min_tokens"] == 500 and seen["limit"] == 10 and seen["offset"] == 20
    assert seen["since"] and seen["until"]


def test_the_route_reports_the_match_count_and_its_window(monkeypatch):
    """A page of rows with no total cannot say whether anything is past it."""
    from fastapi.testclient import TestClient

    from aughor.api import app

    monkeypatch.setattr(session_log, "session_index", lambda **kw: {
        "rows": [run("t1")], "total": 87, "limit": 25, "offset": 0, "scanned_events": 4000})

    body = TestClient(app).get("/traces").json()

    assert body["total"] == 87 and body["scanned_events"] == 4000
    assert len(body["traces"]) == 1
