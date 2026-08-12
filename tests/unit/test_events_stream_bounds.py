"""An SSE stream that outlives the invocation serving it.

`while True` with `is_disconnected()` as the only exit assumes a server that can
hold a socket indefinitely. Serverless cannot: the platform kills the invocation at
`maxDuration` (300s in vercel.json) and logs a Runtime Timeout. Measured over one
30-minute window in production: **19 of them**, each burning a full 300s slot and
~300 journal reads, on a deployment already cold-starting 43 times in that window.

Three changes, pinned here:

  * the stream CLOSES ITSELF before the platform kills it, turning a platform error
    into an ordinary reconnect that EventSource performs on its own;
  * it emits `id:` per event, so a reconnecting browser sends `Last-Event-ID` and
    resumes EXACTLY — without it, EventSource replays from the URL's original
    `since_seq`, which is why the client had to dedupe by seq;
  * it BACKS OFF while the journal is quiet, instead of reading once a second per
    open stream forever.

The bound is off by default: a long-lived self-hosted server should keep its stream.
"""
from __future__ import annotations

import asyncio
import importlib

import pytest


@pytest.fixture
def events_mod(monkeypatch):
    """Reload the router so module-level bounds pick up the patched environment."""
    def _load(**env):
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        import aughor.routers.events as m
        return importlib.reload(m)
    yield _load
    import aughor.routers.events as m
    importlib.reload(m)


class _Req:
    """A request that never reports a disconnect — exactly the serverless case that
    let the loop run until the platform killed it."""

    def __init__(self, headers: dict | None = None):
        self.headers = headers or {}

    async def is_disconnected(self):
        return False


def _drain(gen, limit=200):
    async def _run():
        out = []
        async for chunk in gen:
            out.append(chunk)
            if len(out) >= limit:
                break
        return out
    return asyncio.run(_run())


def test_the_bound_is_off_by_default_for_a_long_lived_server(events_mod, monkeypatch):
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("AUGHOR_SSE_MAX_SECONDS", raising=False)
    m = events_mod()
    assert m._MAX_STREAM_SECONDS == 0.0, "a self-hosted server must keep its stream open"


def test_serverless_gets_a_bound_below_the_platform_limit(events_mod):
    m = events_mod(VERCEL="1")
    assert 0 < m._MAX_STREAM_SECONDS < 300, (
        "the stream must close BEFORE vercel.json's maxDuration, or the platform "
        "kills it and the close is not graceful")


def test_an_explicit_override_wins(events_mod):
    m = events_mod(VERCEL="1", AUGHOR_SSE_MAX_SECONDS="12")
    assert m._MAX_STREAM_SECONDS == 12.0


def test_the_stream_closes_itself_when_bounded(events_mod, monkeypatch):
    """The claim: a stream that nobody disconnects still ENDS."""
    m = events_mod(AUGHOR_SSE_MAX_SECONDS="0.25")
    monkeypatch.setattr(m, "_POLL_SECONDS", 0.01)
    monkeypatch.setattr(m, "_POLL_IDLE_MAX", 0.01)

    class _Led:
        def events(self, **kw):
            return []
    monkeypatch.setattr(m.Ledger, "default", staticmethod(lambda: _Led()))

    resp = asyncio.run(m.stream_events(_Req()))
    chunks = _drain(resp.body_iterator, limit=500)

    assert any("cycling" in c for c in chunks), "the stream never closed itself"
    assert chunks[-1].startswith(": "), "it should end on a comment, invisible to subscribers"


def test_events_carry_an_id_so_a_reconnect_can_resume(events_mod, monkeypatch):
    """Without `id:`, EventSource replays from the ORIGINAL since_seq on reconnect."""
    m = events_mod(AUGHOR_SSE_MAX_SECONDS="0.25")
    monkeypatch.setattr(m, "_POLL_SECONDS", 0.01)
    monkeypatch.setattr(m, "_POLL_IDLE_MAX", 0.01)

    class _Led:
        def __init__(self):
            self.sent = False

        def events(self, **kw):
            if self.sent:
                return []
            self.sent = True
            return [{"seq": 41, "kind": "k", "conn_id": None}]
    monkeypatch.setattr(m.Ledger, "default", staticmethod(lambda: _Led()))

    chunks = _drain(asyncio.run(m.stream_events(_Req(), since_seq=40)).body_iterator, limit=500)
    assert any(c.startswith("id: 41\n") for c in chunks), "no id: — a reconnect cannot resume"


def test_last_event_id_beats_the_query_cursor(events_mod, monkeypatch):
    """The browser's own resume point is newer than the URL it first connected with."""
    m = events_mod(AUGHOR_SSE_MAX_SECONDS="0.25")
    monkeypatch.setattr(m, "_POLL_SECONDS", 0.01)
    monkeypatch.setattr(m, "_POLL_IDLE_MAX", 0.01)

    seen: list = []

    class _Led:
        def events(self, **kw):
            seen.append(kw.get("since_seq"))
            return []
    monkeypatch.setattr(m.Ledger, "default", staticmethod(lambda: _Led()))

    req = _Req({"last-event-id": "99"})
    _drain(asyncio.run(m.stream_events(req, since_seq=5)).body_iterator, limit=500)

    assert 99 in seen, f"resumed from the stale query cursor instead of Last-Event-ID: {seen[:3]}"
    assert 5 not in seen


def test_a_quiet_journal_is_not_read_once_a_second_forever(events_mod, monkeypatch):
    """The back-off. 19 streams x 300 reads was the measured production load."""
    m = events_mod(AUGHOR_SSE_MAX_SECONDS="0.4")
    monkeypatch.setattr(m, "_POLL_SECONDS", 0.01)
    monkeypatch.setattr(m, "_POLL_IDLE_MAX", 0.2)

    reads = {"n": 0}

    class _Led:
        def events(self, **kw):
            reads["n"] += 1
            return []
    monkeypatch.setattr(m.Ledger, "default", staticmethod(lambda: _Led()))

    _drain(asyncio.run(m.stream_events(_Req())).body_iterator, limit=500)

    # Unbacked-off at 0.01s this would be ~40 reads in 0.4s; the back-off to 0.2s
    # caps it far below that.
    assert reads["n"] < 20, f"the poll did not back off while idle ({reads['n']} reads)"
