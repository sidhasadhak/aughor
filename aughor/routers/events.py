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
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from aughor.kernel.ledger import Ledger

logger = logging.getLogger(__name__)
router = APIRouter()

_POLL_SECONDS = 1.0          # journal tail cadence (server-side, indexed query)
_HEARTBEAT_EVERY = 25        # SSE comment keep-alive, in tail ticks


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
        last = int(since_seq)
        if last == 0:
            # Start at the journal head — the client wants new events, not history.
            head = led.events(limit=1)
            last = head[0]["seq"] if head else 0
        yield f"data: {json.dumps({'kind': 'stream.open', 'seq': last})}\n\n"
        tick = 0
        while True:
            if await request.is_disconnected():
                return
            try:
                rows = led.events(since_seq=last, limit=200)
            except Exception:
                logger.warning("event stream: journal read failed", exc_info=True)
                rows = []
            if rows:
                for ev in reversed(rows):     # events() is newest-first
                    last = max(last, ev["seq"])
                    if conn_id and ev.get("conn_id") not in (None, conn_id):
                        continue
                    yield f"data: {json.dumps(ev, default=str)}\n\n"
            tick += 1
            if tick % _HEARTBEAT_EVERY == 0:
                yield ": keep-alive\n\n"
            await asyncio.sleep(_POLL_SECONDS)

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
