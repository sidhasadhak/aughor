"""PENDING.md item 12, first step — how often does a question miss the declared business terms?

The frame matcher reads only the words the business declared (and a person's synonyms); a
question worded otherwise loses the frame silently (§3.15: "Paraphrases stay 0/3"). Nothing
counted it, so how often it happens on a real connection was unknown — and the lift the frame
gives (LuxExperience 5/16 → 16/16) is exactly what such a question loses.

Recorded here: every question framed on a scope that DECLARES definitions (a rule, a process
stage or a promise) and reached none of them — as a ledger event carrying the run's trace id,
NEVER the question's text. Questions are already kept word for word elsewhere (PENDING's A5
line: the decision log, no expiry); a miss record that copied them would be one more. A person
who wants the wording reads it from the session log by the trace id, for as long as that log
keeps it. Free: no model, no warehouse; one event per miss.
"""
from __future__ import annotations

from typing import Any, Optional

KIND = "framing.miss"


def declares_definitions(graph: Any) -> bool:
    """Whether a scope declares anything a question could be framed on — a rule, or a process."""
    return bool(getattr(graph, "rules", None) or getattr(graph, "processes", None))


def record(frame: Any, graph: Any, connection_id: str, schema_name: Optional[str], *,
           trace_id: str = "", inv_id: str = "") -> bool:
    """Record a miss when ``frame`` defines nothing on a scope that declares definitions.
    Returns whether it recorded one. Never raises."""
    try:
        if frame is None or getattr(frame, "defines", False) or not declares_definitions(graph):
            return False
        from aughor.kernel.ledger import Ledger
        if inv_id and any((e.get("payload") or {}).get("inv_id") == inv_id
                          for e in Ledger.default().events(kind=KIND, conn_id=connection_id, limit=50)):
            # a deep run frames its question twice (the door, then the graph's first node) — one
            # question is one miss (found by the branch review, 2026-09-24)
            return False
        Ledger.default().emit(KIND, {"schema": schema_name or "", "inv_id": inv_id,
                                     "words": len(str(getattr(frame, "question", "") or "").split())},
                              conn_id=connection_id, trace_id=trace_id or None)
        return True
    except Exception as exc:  # noqa: BLE001 — counting a miss never breaks the answer it counts
        from aughor.kernel.errors import tolerate
        tolerate(exc, "a framing miss could not be recorded", counter="framing.miss_record")
        return False


def misses(connection_id: str, *, limit: int = 200) -> dict:
    """The recorded misses on a connection, newest first: when, the run's trace id, and — only
    while the session log still keeps it — the question the run was asked."""
    from aughor.kernel.ledger import Ledger
    ledger = Ledger.default()
    rows = ledger.events(kind=KIND, conn_id=connection_id, limit=limit)
    out = []
    for r in rows:
        trace = r.get("trace_id") or ""
        question = ""
        if trace:
            try:
                for ev in ledger.session_events(trace_id=trace, limit=20):
                    payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
                    question = str(payload.get("question") or "")
                    if question:
                        break
            except Exception:  # noqa: BLE001 — an aged-out question reads as not kept, never as an error
                question = ""
        out.append({"at": r.get("at"), "trace_id": trace, "question": question or None})
    return {"connection_id": connection_id, "misses": len(out), "recent": out[:25],
            "note": "a question is shown only while the session log still keeps its run"}
