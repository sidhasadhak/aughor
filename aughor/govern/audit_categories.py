"""Wave G3b — one category vocabulary over the audit trails that already exist.

**This is consolidation, not a new sink.** Surveying first found governance events being
written to five mutually-unaware places:

    aughor/security/audit.py        the `audit_log` SQLite table — every query execution
    govern.actions.audit()          Ledger `action.approval` — the G1 gate's decisions
    govern.tag_store                Ledger `govern.tag` — G2 tag set/clear
    routers/metrics.py              Ledger `metric.governance` — lifecycle transitions
    obs/session_log.py              Ledger `llm_call` — every model call (J8/G3a)

Each is correct in isolation and none knows about the others, so "what happened in this
org last week" has no answer that spans them. That is the shape this repo keeps paying
for — Wave E found five mutually-unaware eval surfaces, Wave V found thirteen dialects of
"out of date" — and the lesson both times was that the fix is a shared vocabulary over the
existing stores, never a sixth store that has to be kept in sync with the five.

So nothing here writes. :func:`feed` reads the sinks that exist and labels each event with
a :data:`CATEGORIES` member, and :func:`uncategorized_kinds` is the ratchet that stops a
sixth sink from appearing unlabelled.

**Why categories rather than just kinds.** A kind says which code emitted the event; a
category says what a reader is looking for. "Show me every governance change" should not
require knowing that metric transitions live under one kind, tag edits under another, and
approval decisions under a third — that knowledge is exactly what goes stale.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

#: The reader-facing vocabulary. Small on purpose: a category nobody would filter by is a
#: category that only adds a decision to whoever emits the next event.
CATEGORIES: tuple[str, ...] = (
    "data_access",         # a query ran against a connection
    "governance_change",   # a governed definition or tag changed
    "action_decision",     # the approval gate allowed, auto-allowed or blocked an action
    "model_call",          # an LLM call (the cost/usage trail — G3a)
)

#: Ledger event kind → category. The one place that mapping lives.
KIND_CATEGORY: dict[str, str] = {
    "action.approval": "action_decision",
    "govern.tag": "governance_change",
    "metric.governance": "governance_change",
    "llm_call": "model_call",
}

#: The non-Ledger sink: the append-only `audit_log` table is entirely data access.
AUDIT_TABLE_CATEGORY = "data_access"


@dataclass
class AuditEvent:
    """One governance-relevant event, normalized across sinks."""

    category: str
    kind: str
    at: str = ""
    actor: str = ""
    org_id: str = ""
    conn_id: str = ""
    summary: str = ""
    detail: dict[str, Any] | None = None

    def to_dict(self) -> dict:
        return {"category": self.category, "kind": self.kind, "at": self.at,
                "actor": self.actor, "org_id": self.org_id, "conn_id": self.conn_id,
                "summary": self.summary, "detail": self.detail or {}}


def category_for(kind: str) -> Optional[str]:
    """The category a Ledger kind belongs to, or ``None`` when nothing claims it."""
    return KIND_CATEGORY.get(str(kind or ""))


def uncategorized_kinds(emitted_kinds: set[str]) -> list[str]:
    """Governance-shaped kinds that no category claims — the ratchet's input.

    Takes the emitted set rather than discovering it, so the check stays pure and the
    caller (a test) owns how the tree is scanned.
    """
    return sorted(k for k in emitted_kinds if k not in KIND_CATEGORY)


def _ledger_events(kind: str, limit: int) -> list[dict]:
    from aughor.kernel.ledger import Ledger

    try:
        return Ledger.default().events(kind=kind, limit=limit) or []
    except Exception as exc:
        from aughor.kernel.errors import tolerate

        tolerate(exc, "one audit sink being unreadable must not blank the whole feed",
                 counter="govern.audit_feed_sink")
        return []


def _from_ledger(kind: str, limit: int) -> list[AuditEvent]:
    category = KIND_CATEGORY[kind]
    out: list[AuditEvent] = []
    for e in _ledger_events(kind, limit):
        p = e.get("payload") or {}
        out.append(AuditEvent(
            category=category, kind=kind, at=str(e.get("created_at") or ""),
            actor=str(p.get("actor") or p.get("set_by") or p.get("cleared_by") or ""),
            org_id=str(p.get("org_id") or e.get("org_id") or ""),
            conn_id=str(e.get("conn_id") or p.get("scope") or ""),
            summary=_summarize(kind, p), detail=p))
    return out


def _summarize(kind: str, p: dict) -> str:
    """A one-line, reader-facing description. Per-kind because the interesting field
    differs, and a generic dump of the payload is not a summary."""
    if kind == "action.approval":
        return f"{p.get('decision', '?')} {p.get('action', '?')} on {p.get('scope') or '*'}"
    if kind == "govern.tag":
        act = p.get("action", "?")
        return (f"{act} {p.get('key', '?')}"
                + (f"={p.get('value')}" if act == "set" else "")
                + f" on {p.get('securable', '?')}")
    if kind == "metric.governance":
        return (f"{p.get('action', '?')} metric {p.get('metric', '?')}"
                f" ({p.get('from', '?')} → {p.get('to', '?')})")
    if kind == "llm_call":
        return f"{p.get('role') or 'model'} call"
    return kind


def _from_session_log(limit: int) -> list[AuditEvent]:
    """Model calls — read through ``session_events``, NOT ``events``.

    The session log is a separate query path on the Ledger, and the generic ``events``
    reader returns nothing for ``llm_call`` even with hundreds recorded. Found by probing
    the live Ledger rather than by a test: every unit test here builds its own events, so
    a reader pointed at an empty path passes them all and reports "no model calls" on a
    system making them constantly. The same wrong-source shape L1 hit when the receipt
    store was never read at all.
    """
    from aughor.kernel.ledger import Ledger
    from aughor.obs.session_log import LLM_CALL

    try:
        rows = Ledger.default().session_events(kind=LLM_CALL, limit=limit) or []
    except Exception as exc:
        from aughor.kernel.errors import tolerate

        tolerate(exc, "one audit sink being unreadable must not blank the whole feed",
                 counter="govern.audit_feed_sink")
        return []
    out: list[AuditEvent] = []
    for e in rows:
        p = e.get("payload") or {}
        out.append(AuditEvent(
            category="model_call", kind="llm_call", at=str(e.get("created_at") or ""),
            actor=str(e.get("user_id") or ""), org_id=str(e.get("org_id") or ""),
            conn_id=str(e.get("conn_id") or ""),
            summary=f"{p.get('role') or 'model'} call · {e.get('model') or '?'}",
            detail={"provider": e.get("provider"), "model": e.get("model"),
                    "total_tokens": e.get("total_tokens"), "ok": e.get("ok"),
                    "duration_ms": e.get("duration_ms")}))
    return out


def _from_audit_table(limit: int) -> list[AuditEvent]:
    """The append-only query-execution log — the one non-Ledger sink."""
    try:
        from aughor.security.audit import AuditLogger

        records = AuditLogger.recent(limit=limit) or []
    except Exception as exc:
        from aughor.kernel.errors import tolerate

        tolerate(exc, "one audit sink being unreadable must not blank the whole feed",
                 counter="govern.audit_feed_sink")
        return []
    out: list[AuditEvent] = []
    for r in records:
        verdict = r.get("verdict") or "?"
        out.append(AuditEvent(
            category=AUDIT_TABLE_CATEGORY, kind="query.execution",
            at=str(r.get("timestamp") or r.get("created_at") or ""),
            actor=str(r.get("org_id") or ""), org_id=str(r.get("org_id") or ""),
            conn_id=str(r.get("connection_id") or ""),
            summary=f"query {verdict}", detail=r))
    return out


#: Sink readers, keyed by the category they contribute to.
_SINKS: list[tuple[str, Callable[[int], list[AuditEvent]]]] = [
    ("data_access", _from_audit_table),
    ("action_decision", lambda n: _from_ledger("action.approval", n)),
    ("governance_change", lambda n: _from_ledger("govern.tag", n)),
    ("governance_change", lambda n: _from_ledger("metric.governance", n)),
    ("model_call", _from_session_log),
]


def feed(*, category: Optional[str] = None, limit: int = 100,
         per_sink: int = 500) -> list[AuditEvent]:
    """Recent governance events across every sink, newest first.

    ``category`` filters to one member of :data:`CATEGORIES`; an unknown value raises
    rather than returning an empty list, because "no events" and "you asked for a category
    that does not exist" are different answers and only one of them is actionable.

    A sink that cannot be read contributes nothing and is counted — the feed degrades to
    the sinks that answer rather than failing whole, but never silently claims completeness
    it does not have.
    """
    if category is not None and category not in CATEGORIES:
        raise ValueError(f"unknown audit category {category!r} — known: {list(CATEGORIES)}")

    events: list[AuditEvent] = []
    for sink_category, read in _SINKS:
        if category is not None and sink_category != category:
            continue
        # Tolerated HERE rather than only inside the readers: a sink added later that
        # raises before reaching a reader's own guard would otherwise blank the entire
        # feed, and a governance surface that returns nothing is indistinguishable from
        # a quiet week.
        try:
            events.extend(read(per_sink))
        except Exception as exc:
            from aughor.kernel.errors import tolerate

            tolerate(exc, "one audit sink being unreadable must not blank the whole feed",
                     counter="govern.audit_feed_sink")
    events.sort(key=lambda e: e.at, reverse=True)
    return events[:max(1, int(limit))]
