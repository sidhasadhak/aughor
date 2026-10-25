"""Arc TC, TC-5 — `govern.justifications`: the governance feed by a window, from a cursor, and as a
file; a reason to read a run's payload or export the ledger, recorded once as `access.justified`.

The feed tests seed their own events in a window in 2001, so what other tests journal into the
same store (all of it dated today) cannot fall inside it.
"""
from __future__ import annotations

import csv
import io
import json
import uuid

import pytest
from fastapi.testclient import TestClient

from aughor.kernel.ledger import Ledger

_ENV = "AUGHOR_GOVERN_JUSTIFICATIONS"
_DAY = "2001-02-03"


@pytest.fixture()
def client():
    from aughor.api import app
    return TestClient(app)


def _at(seq: int, at: str, table: str = "events") -> None:
    led = Ledger.default()
    with led._lock, led._conn:
        led._conn.execute(f"UPDATE {table} SET at = ? WHERE seq = ?", (at, seq))


def _tag(at: str, label: str) -> int:
    seq = Ledger.default().emit("govern.tag", {"action": "set", "key": "tc5", "value": label,
                                               "securable": f"table:{label}"})
    _at(seq, at)
    return seq


def _metric_change(at: str, label: str) -> int:
    seq = Ledger.default().emit("metric.governance", {"action": "update", "metric": label,
                                                      "from": "draft", "to": "approved"})
    _at(seq, at)
    return seq


def _guardrail(at: str, *, blocked: bool) -> int:
    seq = Ledger.default().session_event_insert({
        "trace_id": f"tc5-{uuid.uuid4().hex[:6]}", "kind": "guardrail", "name": "tc5",
        "ok": not blocked, "org_id": "default",
        "payload": {"guardrail": "tc5", "blocked": blocked, "detail": "tc5 seeded"}})
    _at(seq, at, table="session_events")
    return seq


def _next(day: str) -> str:
    from datetime import date, timedelta
    return (date.fromisoformat(day) + timedelta(days=1)).isoformat()


def _prev(day: str) -> str:
    from datetime import date, timedelta
    return (date.fromisoformat(day) - timedelta(days=1)).isoformat()


def _seed_window(day: str = _DAY) -> dict:
    """Five governance events and one guardrail block inside a day of 2001 (each test its own
    day, so tests sharing the store never share a window), one guardrail ALLOW (never in the
    feed), and one event just outside each edge."""
    return {
        "before": _tag(f"{_prev(day)}T23:59:59.900000+00:00", "before"),
        "t1": _tag(f"{day}T01:00:00.000000+00:00", "t1"),
        "m1": _metric_change(f"{day}T02:00:00.000000+00:00", "m1"),
        "t2": _tag(f"{day}T02:00:00.000000+00:00", "t2"),          # a tie with m1
        "block": _guardrail(f"{day}T03:00:00.000000+00:00", blocked=True),
        "allow": _guardrail(f"{day}T03:30:00.000000+00:00", blocked=False),
        "m2": _metric_change(f"{day}T04:00:00.000000+00:00", "m2"),
        "t3": _tag(f"{day}T23:59:59.999000+00:00", "t3"),
        "after": _tag(f"{_next(day)}T00:00:00.000000+00:00", "after"),
    }


def _window(day: str = _DAY, **extra) -> dict:
    return {"since": day, "until": _next(day), **extra}


def _summaries(events: list[dict]) -> list[str]:
    return [e["summary"] for e in events]


# ── off ──────────────────────────────────────────────────────────────────────────────────────

def test_off_the_feed_reads_no_window_and_the_export_does_not_exist(client, monkeypatch):
    monkeypatch.delenv(_ENV, raising=False)
    plain = client.get("/audit/feed", params={"limit": 50})
    windowed = client.get("/audit/feed", params={"limit": 50, "since": _DAY, "until": "2001-02-04",
                                                 "cursor": "anything"})
    assert plain.status_code == windowed.status_code == 200
    assert plain.json() == windowed.json(), "since/until/cursor changed the feed while off"
    assert set(plain.json()) == {"categories", "category", "count", "events"}

    off = client.get("/audit/feed/export", params={"format": "csv"})
    absent = client.get("/audit/feed/no-such-route", params={"format": "csv"})
    assert off.status_code == absent.status_code == 404 and off.content == absent.content


def test_off_a_payload_read_and_an_export_need_no_reason(client, monkeypatch):
    monkeypatch.delenv(_ENV, raising=False)
    _fake_run(monkeypatch, "tc5-off-run")
    assert client.get("/traces/tc5-off-run").status_code == 200
    assert client.get("/ledger/v1/export", params={"kinds": "claim", "limit": 1}).status_code == 200
    kinds = [e["kind"] for e in Ledger.default().events(trace_id="tc5-off-run", limit=10)]
    assert "trace.payload_access" in kinds and "access.justified" not in kinds


# ── the window and the cursor ────────────────────────────────────────────────────────────────

def test_the_window_holds_its_edges_and_the_feed_reads_blocks_only(client, monkeypatch):
    monkeypatch.setenv(_ENV, "1")
    _seed_window()
    body = client.get("/audit/feed", params=_window(limit=100)).json()
    labels = _summaries(body["events"])
    assert labels == ["set tc5=t3 on table:t3", "update metric m2 (draft → approved)",
                      "guardrail tc5 blocked — tc5 seeded", "set tc5=t2 on table:t2",
                      "update metric m1 (draft → approved)", "set tc5=t1 on table:t1"], labels
    assert not any("before" in s or "after" in s for s in labels), "an edge leaked into the window"
    assert body["since"].startswith(_DAY) and body["until"].startswith("2001-02-04")
    assert body["next_cursor"] is None


def test_the_cursor_pages_without_repeats_or_gaps_and_holds_as_events_arrive(client, monkeypatch):
    monkeypatch.setenv(_ENV, "1")
    day = "2001-03-03"
    _seed_window(day)
    whole = _summaries(client.get("/audit/feed", params=_window(day, limit=100)).json()["events"])
    assert len(whole) == 6

    first = client.get("/audit/feed", params=_window(day, limit=3)).json()
    assert _summaries(first["events"]) == whole[:3] and first["next_cursor"]
    _tag(f"{day}T12:00:00.000000+00:00", "late")           # arrives between the pages, inside page 1's span
    pages, cursor = list(first["events"]), first["next_cursor"]
    while cursor:
        page = client.get("/audit/feed", params=_window(day, limit=3, cursor=cursor)).json()
        pages += page["events"]
        cursor = page["next_cursor"]
    got = _summaries(pages)
    assert got == whole, "a page repeated, skipped or moved when an event arrived"


def test_a_boundary_second_is_cut_exactly_or_refused_by_name(client, monkeypatch):
    """A store is bounded to the second; the window is exact. Rows past `until` inside its
    second are read and dropped, and the sink is asked again until it yields what the page
    needs — or, past the read cap, the page is refused by name, never paged past rows unread."""
    monkeypatch.setenv(_ENV, "1")
    day = "2001-06-03"
    _tag(f"{day}T10:00:00.700000+00:00", "late-a")
    _tag(f"{day}T10:00:00.600000+00:00", "late-b")
    inside = _tag(f"{day}T10:00:00.200000+00:00", "inside")
    _metric_change(f"{day}T09:00:00.000000+00:00", "earlier")
    window = {"since": day, "until": f"{day}T10:00:00.500Z", "limit": 1}

    first = client.get("/audit/feed", params=window).json()
    assert _summaries(first["events"]) == ["set tc5=inside on table:inside"], (inside, first)
    second = client.get("/audit/feed", params={**window, "cursor": first["next_cursor"]}).json()
    assert _summaries(second["events"]) == ["update metric earlier (draft → approved)"]
    assert second["next_cursor"] is None

    import aughor.govern.audit_categories as ac
    monkeypatch.setattr(ac, "WINDOW_READ_MAX", 2)
    refused = client.get("/audit/feed", params=window)
    assert refused.status_code == 422 and "one second" in refused.json()["detail"]


def test_a_window_or_cursor_the_feed_cannot_read_is_refused(client, monkeypatch):
    monkeypatch.setenv(_ENV, "1")
    assert client.get("/audit/feed", params={"since": "last tuesday"}).status_code == 422
    assert client.get("/audit/feed", params={"since": "2001-02-04", "until": _DAY}).status_code == 422
    bad = client.get("/audit/feed", params={"cursor": "not-a-cursor"})
    assert bad.status_code == 422 and "cursor" in bad.json()["detail"]
    assert client.get("/audit/feed", params={"category": "nope"}).status_code == 400


def test_the_export_is_the_windowed_feed_as_a_file(client, monkeypatch):
    monkeypatch.setenv(_ENV, "1")
    day = "2001-04-03"
    _seed_window(day)
    feed = client.get("/audit/feed", params=_window(day, limit=100)).json()["events"]
    assert len(feed) == 6
    import aughor.govern.audit_categories as ac
    monkeypatch.setattr(ac, "EXPORT_PAGE", 2)              # the file is three pages, walked by the cursor

    as_csv = client.get("/audit/feed/export", params=_window(day, format="csv"))
    assert as_csv.status_code == 200 and as_csv.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(as_csv.text)))
    assert rows[0] == ["at", "category", "kind", "actor", "org_id", "conn_id", "summary", "detail"]
    assert [r[6] for r in rows[1:]] == _summaries(feed)

    as_lines = client.get("/audit/feed/export", params=_window(day, format="jsonl"))
    assert [json.loads(x) for x in as_lines.text.splitlines()] == feed
    assert client.get("/audit/feed/export", params=_window(day, format="xml")).status_code == 422


# ── a reason to read ─────────────────────────────────────────────────────────────────────────

def _fake_run(monkeypatch, trace_id: str) -> None:
    from aughor.obs import session_log
    events = [
        {"seq": 1, "kind": session_log.USER_REQUEST, "at": "2026-10-26T10:00:00Z", "span_id": None,
         "parent_span_id": None, "name": "", "user_id": "analyst-3", "trace_id": trace_id,
         "payload": {"question": "top categories?"}},
        {"seq": 2, "kind": session_log.TOOL_CALL_RESULT, "at": "2026-10-26T10:00:01Z", "span_id": "s1",
         "parent_span_id": None, "name": "run_sql", "user_id": "analyst-3", "trace_id": trace_id, "ok": True,
         "payload": {"user_prompt": "top categories?", "response": "Furniture"}},
    ]
    monkeypatch.setattr(session_log, "recover_session", lambda *a, **k: [dict(e) for e in events])


def _journal(trace_id: str) -> list[dict]:
    return Ledger.default().events(trace_id=trace_id, limit=20)


@pytest.mark.parametrize("path", ["/traces/{t}", "/traces/{t}/spans/s1"])
def test_a_payload_read_without_a_reason_is_refused_by_name(client, monkeypatch, path):
    monkeypatch.setenv(_ENV, "1")
    t = f"tc5-run-{uuid.uuid4().hex[:6]}"
    _fake_run(monkeypatch, t)
    for params in ({}, {"reason": "   "}):
        r = client.get(path.format(t=t), params=params)
        assert r.status_code == 422
        assert r.json()["detail"]["refused"] == "reason_required"
        assert "reason" in r.json()["detail"]["why"]
    assert _journal(t) == [], "a refused read was journaled as a read"


@pytest.mark.parametrize("path", ["/traces/{t}", "/traces/{t}/spans/s1"])
def test_a_payload_read_with_a_reason_is_recorded_once_with_it(client, monkeypatch, path):
    monkeypatch.setenv(_ENV, "1")
    t = f"tc5-run-{uuid.uuid4().hex[:6]}"
    _fake_run(monkeypatch, t)
    r = client.get(path.format(t=t), params={"reason": "ticket 4411: the customer disputes this answer"})
    assert r.status_code == 200

    rows = _journal(t)
    assert [e["kind"] for e in rows] == ["access.justified"], "a read must be journaled exactly once"
    p = rows[0]["payload"]
    assert p["what"] == "run_payload" and p["reason"].startswith("ticket 4411")
    assert p["subject_user_id"] == "analyst-3" and p["trace_id"] == t
    assert p["content_events"] == 1 and "by" in p
    from aughor.govern.audit_categories import KIND_CATEGORY, _summarize
    assert KIND_CATEGORY["access.justified"] == "data_access"
    assert "ticket 4411" in _summarize("access.justified", p)


def test_a_reason_that_cannot_be_recorded_withholds_the_payload(client, monkeypatch):
    monkeypatch.setenv(_ENV, "1")
    t = f"tc5-run-{uuid.uuid4().hex[:6]}"
    _fake_run(monkeypatch, t)
    real = Ledger.emit

    def emit(self, kind, *a, **k):
        if kind == "access.justified":
            raise RuntimeError("journal down")
        return real(self, kind, *a, **k)

    monkeypatch.setattr(Ledger, "emit", emit)
    r = client.get(f"/traces/{t}", params={"reason": "audit"})
    assert r.status_code == 503 and r.json()["detail"]["refused"] == "reason_unrecorded"
    assert "events" not in r.json(), "the payload was served without its reason recorded"


def test_a_summary_carries_no_payload_and_needs_no_reason(client, monkeypatch):
    """The boundary, stated: the summary holds no payload, so it is read as before."""
    monkeypatch.setenv(_ENV, "1")
    t = f"tc5-run-{uuid.uuid4().hex[:6]}"
    _fake_run(monkeypatch, t)
    assert client.get(f"/traces/{t}/summary").status_code == 200
    assert [e["kind"] for e in _journal(t)] == ["trace.payload_access"]


def test_exporting_the_ledger_needs_a_reason_and_records_it(client, monkeypatch):
    monkeypatch.setenv(_ENV, "1")
    refused = client.get("/ledger/v1/export", params={"kinds": "claim", "limit": 1})
    assert refused.status_code == 422 and refused.json()["detail"]["refused"] == "reason_required"

    why = f"tc5 quarterly archive {uuid.uuid4().hex[:6]}"
    ok = client.get("/ledger/v1/export", params={"kinds": "claim", "limit": 1, "reason": why})
    assert ok.status_code == 200
    rows = [e for e in Ledger.default().events(kind="access.justified", limit=50)
            if (e.get("payload") or {}).get("reason") == why]
    assert len(rows) == 1
    assert rows[0]["payload"]["what"] == "ledger_export" and rows[0]["payload"]["kinds"] == "claim"
    feed = client.get("/audit/feed", params={"category": "data_access", "limit": 50}).json()["events"]
    assert any(why in e["summary"] for e in feed), "the reason never reached the governance feed"
