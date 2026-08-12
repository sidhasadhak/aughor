"""K2 — the Event Spine's UI face: one SSE channel over the kernel journal.

Replaces the frontend's seven independent polling loops (ChatPanel 500ms,
Briefing 3s, ExplorationBadge 10s, DomainIntel 10s, ExplorationPanel 12s,
ActivityLog, SystemPanel) with pushes: panels subscribe once and refetch when a
relevant event lands. Polling survives client-side only as a slow degraded
fallback.

The stream tails the ledger's append-only events table (indexed `seq > ?`
query, microseconds on SQLite) — deliberately simple and crash-proof rather
than an in-process pub/sub: the journal IS the source of truth, so a dropped
connection resumes from `since_seq` with zero loss.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from aughor.kernel.ledger import Ledger

logger = logging.getLogger(__name__)
router = APIRouter()

_POLL_SECONDS = 1.0          # journal tail cadence (server-side, indexed query)
_POLL_IDLE_MAX = 5.0         # …backed off to this while the journal stays quiet
_HEARTBEAT_SECONDS = 25.0    # SSE comment keep-alive

#: How long one stream may run before closing itself so the client reconnects.
#:
#: `while True` with `is_disconnected()` as the only exit assumes a server that can
#: hold a socket indefinitely. On serverless it cannot: the platform kills the
#: invocation at `maxDuration` (300s in vercel.json) and logs a Runtime Timeout —
#: 19 of them in one measured 30-minute window, each burning a full 300s slot and
#: ~300 journal reads. Closing FIRST turns a platform error into an ordinary
#: reconnect, which EventSource does on its own.
#:
#: 0 disables the bound — a long-lived self-hosted server should keep its stream.
_MAX_STREAM_SECONDS = float(
    os.getenv("AUGHOR_SSE_MAX_SECONDS", "").strip()
    or (240.0 if os.getenv("VERCEL") else 0.0)
)


@router.get("/events/recent")
def recent_events(
    conn_id: Optional[str] = None,
    kind: Optional[str] = None,
    since_seq: Optional[int] = None,
    limit: int = 100,
):
    """Recent journal events, newest first — initial state + debugging."""
    return Ledger.default().events(
        kind=kind, conn_id=conn_id, since_seq=since_seq, limit=min(int(limit), 500)
    )


@router.get("/events/stream")
async def stream_events(request: Request, conn_id: Optional[str] = None, since_seq: int = 0):
    """SSE stream of kernel events. `conn_id` scopes to one connection (events
    with no conn_id — e.g. api.started — always pass). `since_seq` resumes
    after a dropped connection without losing events."""
    led = Ledger.default()

    async def _gen():
        started = time.monotonic()
        last = int(since_seq)
        # A browser reconnecting sends the id of the last event it SAW. Honour it:
        # EventSource replays from the URL's original `since_seq` otherwise, so a
        # long session re-sent everything from where it first connected and leant on
        # the client to dedupe. `id:` below is what makes the header arrive.
        resume = (request.headers.get("last-event-id") or "").strip()
        if resume.isdigit():
            last = max(last, int(resume))
        if last == 0:
            # Start at the journal head — the client wants new events, not history.
            head = led.events(limit=1)
            last = head[0]["seq"] if head else 0
        yield f"data: {json.dumps({'kind': 'stream.open', 'seq': last})}\n\n"
        poll = _POLL_SECONDS
        beat = time.monotonic()
        while True:
            if await request.is_disconnected():
                return
            if _MAX_STREAM_SECONDS and time.monotonic() - started >= _MAX_STREAM_SECONDS:
                # A COMMENT, not an event: comments never reach subscribers, so
                # cycling stays invisible to every consumer of the bus. EventSource
                # sees the close and reconnects with Last-Event-ID by itself.
                yield ": cycling\n\n"
                return
            try:
                rows = led.events(since_seq=last, limit=200)
            except Exception:
                logger.warning("event stream: journal read failed", exc_info=True)
                rows = []
            if rows:
                poll = _POLL_SECONDS          # busy again — back to the fast cadence
                for ev in reversed(rows):     # events() is newest-first
                    last = max(last, ev["seq"])
                    if conn_id and ev.get("conn_id") not in (None, conn_id):
                        continue
                    yield f"id: {ev['seq']}\ndata: {json.dumps(ev, default=str)}\n\n"
            else:
                # An idle journal was still read once a second per open stream. Back
                # off while nothing is happening; the next event costs at most one
                # extra interval of latency.
                poll = min(poll * 1.5, _POLL_IDLE_MAX)
            now = time.monotonic()
            if now - beat >= _HEARTBEAT_SECONDS:
                beat = now
                yield ": keep-alive\n\n"
            await asyncio.sleep(poll)

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
