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
    "data_access",         # data was read: a query against a connection, or a run's
                           # captured payloads (which carry SQL and, when a capture
                           # window is open, prompt content)
    "governance_change",   # a governed definition or tag changed
    "action_decision",     # the approval gate allowed, auto-allowed or blocked an action
    "model_call",          # an LLM call (the cost/usage trail — G3a)
    "human_verdict",       # a person graded an answer or a run (MI-1). Its own category
                           # because none of the four above fits: a thumbs is not a call,
                           # not a definition change, and not the approval gate. It is the
                           # scarce signal the platform collects and could not surface.
)

#: Ledger event kind → category. The one place that mapping lives.
KIND_CATEGORY: dict[str, str] = {
    "action.approval": "action_decision",
    "govern.tag": "governance_change",
    "metric.governance": "governance_change",
    # KI-0 (§3.10) — the trusted-SQL door's lifecycle trail (seed / edit / propose /
    # approve / reject / deprecate / delete). Same shape as metric.governance: an
    # approved trusted query is a governed definition every later answer leans on.
    "trusted_query.governance": "governance_change",
    "llm_call": "model_call",
    # Arc VA decision ③ — admins may read any trace's payloads, and every such read is
    # auditable. Filed as data_access because that is what an auditor asking "who saw
    # what" filters on; the `kind` separates it from query execution within that view.
    "trace.payload_access": "data_access",
    # MI-1 — the two feedback doors. Both have been writing to the ledger since they
    # shipped, neither was categorized, so the governance feed could not show that a
    # person had ever graded anything. They are split by design (`chat.feedback` keys on
    # turn_id, `trace.feedback` on trace_id) and stay two kinds under one category.
    "chat.feedback": "human_verdict",
    "trace.feedback": "human_verdict",
}

#: The non-Ledger sink: the append-only `audit_log` table is entirely data access.
AUDIT_TABLE_CATEGORY = "data_access"

#: MI-1 — reviewed and judged NOT governance: operational telemetry, lifecycle and
#: progress. Listed rather than inferred so the ratchet below can fail CLOSED. The old
#: ratchet compared a hand-written list of emitted kinds against this module's hand-written
#: map; both sides were the same edit, so a kind nobody remembered was absent from BOTH and
#: the assertion passed. That is how `chat.feedback` and `trace.feedback` stayed invisible
#: from the day they shipped. Now the emitted set is DISCOVERED from the tree, and every
#: discovered kind must be claimed here or categorized above.
NON_GOVERNANCE_KINDS: frozenset[str] = frozenset({
    "agent.handoff", "api.started", "automation.run", "birth.done", "birth.step",
    "brief.delivered", "error.tolerated", "exploration.skipped", "explorer.resumed",
    "investigation.dispatched", "investigations.swept", "job.foreign", "job.orphaned",
    "job.state", "monitor.alert", "node.span", "pack.status_changed", "phase_complete",
    "playbook.use", "store.wal_drift", "eval.graduation", "ontology.build",
})

#: MI-1 — reviewed and judged governance-shaped, deliberately NOT yet in the feed.
#:
#: Found by making the ratchet discover its own population: these four are as
#: governance-relevant as the kinds already mapped — `govern.cap` is named for it,
#: `metric.enforcement` is the enforcement twin of the categorized `metric.governance`,
#: and `guardrail` is the allow-AND-block trail `govern/guardrails.py` deliberately writes
#: both halves of so a block RATE can be computed. They are held out of KIND_CATEGORY
#: because admitting them changes what a user-facing surface RETURNS, and one of them
#: would dominate it: `guardrail` is 1,074 of the local ledger's rows, every one a PII
#: allow, against 500-per-sink. Which of them the feed should carry — and whether a
#: high-volume allow trail belongs in a reader-facing feed at all — is a product decision,
#: not a builder's. Recorded here rather than buried in the exclusion set above, because
#: writing "not governance" about these would be recording a judgment known to be false.
#:
#: `budget.exceeded` was added by the new ratchet itself, on its first run: the kernel
#: cancels a job for breaching a governed cap and says so on the ledger, and no reader of
#: the governance feed could see it. It is here rather than in the list above for the same
#: reason as the other three — it is enforcement, and calling it telemetry would be false.
GOVERNANCE_SHAPED_UNCATEGORIZED: frozenset[str] = frozenset({
    "govern.cap", "guardrail", "metric.enforcement", "budget.exceeded",
})


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
    """Journal events for one governance kind, tenant-scoped (DATA-06).

    Scoped on the ``org_id`` COLUMN (ledger Migration 8), never on ``payload.org_id``:
    payload coverage was measured partial on the live ledger — ``action.approval``
    carried it on 50 of 50 rows, ``govern.tag`` on 0 of 4 — so a payload filter would
    have scoped one governance category correctly and silently emptied another, which
    reads as "a quiet week" rather than as a bug. ``emit`` stamps the column from the
    ambient tenant, so every kind is covered whether or not its producer remembers.
    """
    from aughor.kernel.ledger import Ledger
    from aughor.security.authz import tenant_scope

    try:
        return Ledger.default().events(kind=kind, limit=limit,
                                       org_id=tenant_scope()) or []
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
            # The ledger's column is `at`. `created_at` was read for as long as this
            # sink existed and matched nothing, so every governance event arrived
            # timestamped "" — and `feed` sorts on that, which made "newest first" a
            # claim about 505 identical empty strings.
            category=category, kind=kind, at=str(e.get("at") or e.get("created_at") or ""),
            actor=str(p.get("actor") or p.get("set_by") or p.get("cleared_by")
                      or p.get("read_by") or p.get("by") or ""),
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
    if kind == "trusted_query.governance":
        return (f"{p.get('action', '?')} trusted query "
                f"{str(p.get('trusted_query') or '?')[:16]}"
                f" ({p.get('from') or '—'} → {p.get('to') or '—'})")
    if kind == "llm_call":
        return f"{p.get('role') or 'model'} call"
    if kind in ("chat.feedback", "trace.feedback"):
        subject = p.get("turn_id") or p.get("trace_id") or "?"
        note = str(p.get("note") or "").strip()
        return (f"{p.get('verdict', '?')} on {str(subject)[:12]}"
                + (f" — {note[:60]}" if note else ""))
    if kind == "trace.payload_access":
        who = p.get("read_by") or "unidentified"
        whose = p.get("subject_user_id") or "unattributed"
        content = p.get("content_events") or 0
        return (f"{who} read trace {str(p.get('trace_id') or '?')[:12]} ({whose})"
                + (f" — {content} events with prompt content" if content else ""))
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
    from aughor.security.authz import tenant_scope

    try:
        # Tenant-scoped (DATA-06): session events carry an org_id column, and a model-call
        # row names the model another org runs and what it costs them.
        rows = Ledger.default().session_events(kind=LLM_CALL, limit=limit,
                                               org_id=tenant_scope()) or []
    except Exception as exc:
        from aughor.kernel.errors import tolerate

        tolerate(exc, "one audit sink being unreadable must not blank the whole feed",
                 counter="govern.audit_feed_sink")
        return []
    out: list[AuditEvent] = []
    for e in rows:
        p = e.get("payload") or {}
        out.append(AuditEvent(
            category="model_call", kind="llm_call",
            at=str(e.get("at") or e.get("created_at") or ""),   # session_events.at
            actor=str(e.get("user_id") or ""), org_id=str(e.get("org_id") or ""),
            conn_id=str(e.get("conn_id") or ""),
            summary=f"{p.get('role') or 'model'} call · {e.get('model') or '?'}",
            detail={"provider": e.get("provider"), "model": e.get("model"),
                    "total_tokens": e.get("total_tokens"), "ok": e.get("ok"),
                    "duration_ms": e.get("duration_ms")}))
    return out


def _from_audit_table(limit: int) -> list[AuditEvent]:
    """The append-only query-execution log — the one non-Ledger sink.

    Tenant-scoped (DATA-06): each event's ``detail`` is the whole audit row, ``sql_full``
    included, so an unscoped feed hands one org's statements to another org's admin.
    """
    try:
        from aughor.security.audit import AuditLogger
        from aughor.security.authz import tenant_scope

        records = AuditLogger.recent(limit=limit, org_id=tenant_scope()) or []
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
            at=str(r.get("ts") or r.get("timestamp") or r.get("created_at") or ""),  # audit_log.ts
            actor=str(r.get("org_id") or ""), org_id=str(r.get("org_id") or ""),
            conn_id=str(r.get("connection_id") or ""),
            summary=f"query {verdict}", detail=r))
    return out


#: Sink readers, keyed by the category they contribute to.
_SINKS: list[tuple[str, Callable[[int], list[AuditEvent]]]] = [
    ("data_access", _from_audit_table),
    ("data_access", lambda n: _from_ledger("trace.payload_access", n)),
    ("action_decision", lambda n: _from_ledger("action.approval", n)),
    ("governance_change", lambda n: _from_ledger("govern.tag", n)),
    ("governance_change", lambda n: _from_ledger("metric.governance", n)),
    ("governance_change", lambda n: _from_ledger("trusted_query.governance", n)),
    ("model_call", _from_session_log),
    # A mapping entry alone renders NOTHING: `feed` walks this list, not KIND_CATEGORY.
    # The two lists are parallel and hand-maintained, which is why the ratchet now
    # asserts they agree rather than trusting that whoever edited one edited the other.
    ("human_verdict", lambda n: _from_ledger("chat.feedback", n)),
    ("human_verdict", lambda n: _from_ledger("trace.feedback", n)),
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
