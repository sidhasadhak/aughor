"""Wave H5 — the ONE way a caller without an HTTP request runs an investigation.

Lifted verbatim out of ``automations/engine.py::_dispatch_investigate``, where it worked
but could only ever have one caller. Both callers now sit above it as peers:

    automations._dispatch_investigate  ─┐
                                        ├─→  run_investigation  ─→  build_ask_stream
    kinetic._dispatch_trigger_investig ─┘

Three properties carry the weight, and they are the three decisions Wave H deferred:

**Risk tier.** Starting an investigation is a read-path analysis — it issues SELECTs and
writes an investigation row, never a source mutation — but it SPENDS the LLM budget. So
it is not ``read_only``, and the kinetic executor enforces that as a floor rather than
trusting the declaration (:func:`aughor.kinetic.executor._risk_of`). Metering is not
added here: ``submit_background_tick`` already makes the run a supervised kernel job, so
the tokens land on the job's meter and count against the charter's budget.

**Async submission.** Submitted, never awaited — the caller's tick or HTTP request must
not block for the minutes a deep run takes. With no live loop (a unit test, pre-startup,
the CLI) ``submit_background_tick`` declines and the work runs inline, which is the path
every scheduler in the codebase already takes.

**The receipt.** A submitted run has no receipt id at the moment it is submitted, and
inventing one would be a lie. So :class:`InvestigationRun` carries ``basis``: ``inline``
means ``investigation_id``/``receipt_id`` are the real ids of a completed run;
``submitted`` means the job id is the handle and the ids are not knowable yet. They are
not simply dropped — when the drain resolves them it appends an ``investigation.dispatched``
ledger event carrying the join (job ↔ investigation ↔ receipt ↔ agent), readable at
``GET /events/recent?kind=investigation.dispatched`` and on the live ``/events/stream``.
Note that is the KERNEL event log, not ``/obs/activity`` — Activity tails the session log,
which is a different store answering a different question (what a run did, not what started
it).

Nothing here re-implements a rule. The persona pre-check delegates to the ask path's own
:func:`~aughor.routers.investigations.ask_agent_refusal`, so a binding rule can never hold
on the HTTP path and not on a scheduled one.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

_KIND = "investigation"          # the kernel job kind (Fleet groups runs by it)
DISPATCH_EVENT = "investigation.dispatched"


@dataclass(frozen=True)
class InvestigationRequest:
    """What to investigate, in the terms the one ask door already takes.

    Deliberately NOT ``AskRequest``: that is an HTTP body with two dozen fields for
    clarify state, canvas binding and re-run overrides. A runner caller has a question, a
    connection and (optionally) a persona; anything more would be a second answer path
    growing a second set of options.
    """
    question: str
    connection_id: str
    schema_name: Optional[str] = None
    agent_id: Optional[str] = None
    depth: str = "deep"


@dataclass
class InvestigationRun:
    """What happened. ``status`` is one of:

    * ``refused``   — a gate said no BEFORE any work started; ``message`` is the authored
      sentence, verbatim. Nothing was submitted and no budget was spent.
    * ``executed``  — submitted (``basis="submitted"``) or completed (``basis="inline"``).
    * ``failed``    — ran inline and the stream reported an error. Only reachable on the
      inline path: a submitted run's failure belongs to the job, not to the submit.
    """
    status: str
    message: str = ""
    job_id: str = ""
    investigation_id: str = ""
    receipt_id: str = ""
    basis: str = ""                  # "" | "inline" | "submitted"

    @property
    def ok(self) -> bool:
        return self.status == "executed"


def _ask_request(req: InvestigationRequest):
    from aughor.routers.investigations import AskRequest
    return AskRequest(question=req.question, connection_id=req.connection_id,
                      depth=req.depth, schema_name=req.schema_name,
                      agent_id=req.agent_id or None)


def refusal_for(req: InvestigationRequest) -> str:
    """Why this investigation cannot run as its agent, or ``""`` when it can.

    Asked BEFORE submitting because the ask path raises its persona refusals as
    ``HTTPException`` — right for an HTTP caller, lost for one whose tick has already
    reported the effect as dispatched by the time a background job unwraps. The authored
    sentence then lands in the run history instead of vanishing. A second, identical
    resolution happens inside the stream when the work runs: idempotent by construction,
    and the door stays one.
    """
    if not req.agent_id:
        return ""
    from aughor.routers.investigations import ask_agent_refusal
    return ask_agent_refusal(_ask_request(req)) or ""


def _note_dispatch(caller: str, req: InvestigationRequest, seen: dict) -> None:
    """Append the join a submitted run cannot return synchronously.

    Without this, an investigation started by an automation or a declared action is a job
    id in one store and an investigation in another with nothing connecting them. Cheap
    (one local insert per dispatched run, not per event) and best-effort — a broken
    ledger must never fail work that has already succeeded.
    """
    try:
        from aughor.kernel.jobs import current_job_id
        from aughor.kernel.ledger import Ledger
        Ledger.default().emit(
            DISPATCH_EVENT,
            {"caller": caller, "agent_id": req.agent_id or "",
             "question": req.question[:500],
             "investigation_id": seen.get("investigation_id", ""),
             "receipt_id": seen.get("receipt_id", ""),
             "ok": not seen.get("error"),
             **({"error": seen["error"]} if seen.get("error") else {})},
            conn_id=req.connection_id, job_id=current_job_id() or None,
        )
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "recording the investigation dispatch join is best-effort; the run itself already happened",
                 counter="runners.investigation.note_dispatch", conn_id=req.connection_id)


def run_investigation(
    req: InvestigationRequest,
    *,
    idempotency_key: Optional[str] = None,
    caller: str = "",
) -> InvestigationRun:
    """Run ``req`` on the real answer path, as a supervised kernel job when one can be had.

    The work drains :func:`~aughor.routers.investigations.build_ask_stream` in-process —
    the same technique the evals ``ask_target`` uses, on the same documented
    ``request=None`` seam — so a scheduled or action-triggered investigation is the same
    investigation a person gets, with the persona applied by the one door rather than by a
    copy of its rules.

    ``idempotency_key`` must include everything that makes the work a DIFFERENT run: the
    same question asked as two personas is two investigations and must not collapse onto
    one. ``caller`` is recorded on the dispatch event so a run can be traced back to what
    started it.
    """
    refusal = refusal_for(req)
    if refusal:
        return InvestigationRun("refused", refusal)

    seen: dict = {}

    def _work() -> None:
        import asyncio
        import json as _json

        from aughor.routers.investigations import build_ask_stream

        async def _drain() -> None:
            async for frame in build_ask_stream(_ask_request(req), None):
                if not frame.startswith("data: "):
                    continue
                try:
                    payload = _json.loads(frame[6:])
                except Exception:
                    continue
                kind = payload.get("type")
                # The ids the caller could not be told synchronously. Sniffed off the
                # stream rather than plumbed through it, the same way the session-log
                # door wrapper correlates a deep run to its investigation.
                if kind == "start" and payload.get("investigation_id"):
                    seen["investigation_id"] = str(payload["investigation_id"])
                elif kind == "receipt_id" and payload.get("receipt_id"):
                    seen["receipt_id"] = str(payload["receipt_id"])
                elif kind == "error":
                    seen["error"] = str(payload.get("message", ""))[:2000]

        asyncio.run(_drain())
        _note_dispatch(caller, req, seen)

    from aughor.kernel.jobs import submit_background_tick
    job_id = submit_background_tick(
        _KIND, _work, conn_id=req.connection_id, idempotency_key=idempotency_key,
    )
    if job_id is None:
        # No live loop — run inline, as the monitor/brief schedulers do. This is the only
        # path that can report a failure, because it is the only one that has waited.
        _work()
        if seen.get("error"):
            return InvestigationRun("failed", seen["error"], basis="inline",
                                    investigation_id=seen.get("investigation_id", ""),
                                    receipt_id=seen.get("receipt_id", ""))
        return InvestigationRun("executed", "ran inline (no kernel loop)", basis="inline",
                                investigation_id=seen.get("investigation_id", ""),
                                receipt_id=seen.get("receipt_id", ""))
    return InvestigationRun("executed", f"job {job_id}", job_id=job_id, basis="submitted")
