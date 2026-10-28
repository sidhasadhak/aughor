"""Arc TC, TC-5 — a reason to read (flag ``govern.justifications``; ROADMAP §6 item 4).

§6 item 4 decided it 2026-09-02: metadata is admin-visible without ceremony, but reading a prompt
or a response body is a break-glass — *an explicit act, with a reason recorded, written to the
audit log*. The act and the audit shipped (`trace.payload_access`: who read whose run); the
reason did not. This is that half, for the two doors that hand over what was said and done rather
than how much: reading a run's payload, and exporting the ledger.

**One kind for every door that asks.** Each read is journaled once as ``access.justified`` — the
reason, who gave it, what was read — to the ledger's journal, which the governance feed already
reads under ``data_access``. Not a new sink: the repo has had five audit sinks and the sixth is
forbidden (`govern/audit_categories.py`). While the flag is on, a payload read writes this event
INSTEAD of ``trace.payload_access`` — it carries every fact that one did, so a read is never
journaled twice.

**Refused by name, recorded or not served.** A read without a reason is a 422 that says what is
missing. A reason that cannot be recorded is a 503 and the payload is not served: a required
reason that is not kept is not required. (With the flag off, the payload-access journal stays
best-effort, as it was.)
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException

#: The journal kind every reason is recorded as.
KIND = "access.justified"
#: What a reason may say, at most — a sentence, not a document.
REASON_MAX = 500

#: What each door hands over, in the words its refusal uses.
WHAT = {
    "run_payload": "reading a run's payload",
    "ledger_export": "exporting the ledger",
}


def required() -> bool:
    """Whether a reason is asked for — the organisation's choice since 2026-10-28 (ROADMAP §3.65). Settings that
    cannot be read fall back to the defaults, which read the former flag's variable, as an unset setting does."""
    from aughor.orgsettings.allows import allows
    return allows("reason_to_read_runs")


def require_reason(reason: Any, what: str) -> str:
    """The reason, trimmed — or a 422 that names what is missing and where it goes."""
    text = str(reason or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail={
            "refused": "reason_required",
            "why": (f"{WHAT.get(what, what).capitalize()} needs a reason: pass `reason`. It is "
                    "recorded with who read it on the governance feed, under data access."),
        })
    return text[:REASON_MAX]


def record(what: str, reason: str, **facts: Any) -> int:
    """Journal one justified read. Raises a 503 when it cannot be recorded — the caller must not
    serve what the reason was asked for."""
    try:
        from aughor.kernel.ledger import Ledger
        from aughor.org.context import current_user_id
        from aughor.security.authz import caller
        trace_id = facts.get("trace_id")
        return Ledger.default().emit(
            "access.justified",
            {"what": what, "reason": reason, "by": current_user_id() or caller(), **facts},
            **({"trace_id": trace_id} if trace_id else {}))
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "a reason that cannot be recorded withholds the read it was given for",
                 counter="govern.justification_unrecorded")
        raise HTTPException(status_code=503, detail={
            "refused": "reason_unrecorded",
            "why": (f"The reason for {WHAT.get(what, what)} could not be recorded, so nothing was "
                    "served. Try again; nothing was read."),
        }) from exc
