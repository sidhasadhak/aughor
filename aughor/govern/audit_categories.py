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
    "enforcement",         # a governed limit or rule was applied: a usage cap set or hit, a
                           # guardrail BLOCK, a job cancelled for its budget, a governed
                           # metric's formula enforced or drifted from. Admitted 2026-10-04
                           # (phase 0 of the 2027 study, ROADMAP §3.53: one audit sink) —
                           # the four kinds below sat in GOVERNANCE_SHAPED_UNCATEGORIZED
                           # as a product decision nobody had taken.
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
    # KI-1 (§3.10) — the intake lane: a bundle upload and its human resolutions.
    # Governance because every accept changes a governed definition somewhere; the
    # per-store trails (metric.governance, trusted_query.governance) carry the detail.
    "intake.governance": "governance_change",
    # HB-6 — installing a pack's function layer mints level grants for its group and
    # lands declared automations: reach changed, which is what this category means.
    # Its sibling `pack.status_changed` stays operational above — a status flip grants
    # nobody anything.
    "pack.installed": "governance_change",
    "llm_call": "model_call",
    # JD-4 — a decider's prompt-builder arguments, captured only while an operator's window
    # is open. That is exactly what `data_access` says it covers: "a run's captured payloads
    # (which carry … when a capture window is open, prompt content)". NOT operational
    # telemetry: an auditor asking "what content did we store, and when" filters here.
    "decision_replay": "data_access",
    # Arc VA decision ③ — admins may read any trace's payloads, and every such read is
    # auditable. Filed as data_access because that is what an auditor asking "who saw
    # what" filters on; the `kind` separates it from query execution within that view.
    "trace.payload_access": "data_access",
    # DE-2b — every call an outside agent (the MCP client) makes to the API, allowed or
    # refused, with its principal, the tool it named, the level the route needed and the
    # policy's, and bounded arguments. Data access because that is the question an auditor
    # asks of an agent: what did it reach, as whom.
    "mcp.tool_call": "data_access",
    # MI-1 — the two feedback doors. Both have been writing to the ledger since they
    # shipped, neither was categorized, so the governance feed could not show that a
    # person had ever graded anything. They are split by design (`chat.feedback` keys on
    # turn_id, `trace.feedback` on trace_id) and stay two kinds under one category.
    "chat.feedback": "human_verdict",
    "trace.feedback": "human_verdict",
    # Phase 0 (2026-10-04) — the enforcement trail. `govern.cap` is a cap set, cleared or hit;
    # `budget.exceeded` is the kernel cancelling a job for a governed cap; `metric.enforcement`
    # is the governed-formula check on every metric-bearing answer; `guardrail` is the
    # allow-AND-block trail, of which the feed carries the BLOCKS only (the reader says why).
    "govern.cap": "enforcement",
    "budget.exceeded": "enforcement",
    "metric.enforcement": "enforcement",
    "guardrail": "enforcement",
    # The 2027 study's phases 4 and 5 — what an action did on its own authority. The L5 agent
    # choosing and running a declared action (or being held), and a declared undo fired: both are
    # the gate's decision on an action, which is what an auditor asking "what ran, and under what"
    # filters by.
    "action.autonomous": "action_decision",
    "action.undone": "action_decision",
    # Phases 4 and 7 — reach changed. A graduation or a demotion moves what an action may do; a
    # service principal minted or revoked, a sign-in to an outside tool server and a foreign
    # method registered each change who or what may act or be believed — the same sense in which
    # `pack.installed` is governance and a status flip is not.
    "authority.graduated": "governance_change",
    "authority.demoted": "governance_change",
    "service_principal.minted": "governance_change",
    "mcp.oauth": "governance_change",
    "method.registered": "governance_change",
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
    # Arc BR-5: a Day subscription pausing the automation it replaces after seven delivered
    # mornings — a consequence of a decision already taken (§6 item 34(e)), shown on the
    # automation itself (its pause and its run history), like explorer.resumed
    "brief.superseded_automation",
    "investigation.dispatched", "investigations.swept", "job.foreign", "job.orphaned",
    "job.state", "monitor.alert", "node.span", "pack.status_changed", "phase_complete",
    "playbook.use", "store.wal_drift", "eval.graduation", "ontology.build",
    # PENDING items 8 and 12: a re-check's verdict and a question that framed on nothing are
    # operational readings — a correction a re-check SENDS is judged and journaled as a departure.
    "answer.rechecked", "framing.miss",
    # ON-0a: a measurement pass over a built ontology (cardinality, lifecycles, pack
    # claims) — operational, like the build it follows; the gated edit is journaled by RBAC.
    "ontology.measure",
    # ON-7b: an explorer's run — one model call and the counts of what it proposed, wrote and was refused. Each write
    # goes through ON-7's gated doors, which RBAC journals like any person's edit; this is the run's telemetry.
    "ontology.explore",
    # The 2027 study's Record at work: an inquiry woken or opened by a weak signal, a mission's report
    # composed, a decision's outcome measured, a prediction scored. Readings of the ledger about the
    # business — each is its own entry in the Record, where a person reads it; none grants, changes or
    # decides what anyone may see or do.
    "inquiry.signal", "inquiry.woke", "mission.reported", "outcome.booked", "prediction.scored",
    # Phase 7: a pack written as a draft, and a pack demoted on its measured record. Like
    # `pack.status_changed` above: neither grants anybody anything — installing is what does.
    "pack.uploaded", "pack.demoted",
})

#: MI-1 held four governance-shaped kinds out of the feed — `govern.cap`, `guardrail`,
#: `metric.enforcement`, `budget.exceeded` — because admitting them was a product decision
#: (one of them, the guardrail ALLOW trail, was 1,074 of the local ledger's rows against
#: 500 per sink). The decision was taken 2026-10-04 (phase 0 of the 2027 study, ROADMAP
#: §3.53): all four are in the feed under `enforcement`, and the guardrail reader carries
#: blocks only, so the allow trail stays where a block RATE is computed from it and never
#: swamps a reader. The set stays declared, empty, so the ratchet below keeps its shape
#: and the next kind someone wants to hold out has a named place to be held.
GOVERNANCE_SHAPED_UNCATEGORIZED: frozenset[str] = frozenset()


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
    if kind == "mcp.tool_call":
        verdict = "allowed" if p.get("allowed") else f"refused ({p.get('code') or '?'})"
        return (f"agent {p.get('actor') or 'mcp'} called {p.get('tool') or p.get('route') or '?'}"
                f" — {verdict}; needs {p.get('required_level') or '?'}, policy {p.get('policy_level') or '?'}")
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
    if kind == "action.autonomous":
        ran = "ran" if p.get("acted") else "held"
        return (f"the autonomous agent {ran} {p.get('action_id') or 'no action'} toward mission "
                f"{str(p.get('mission') or '?')[:12]}" + (f" — {p.get('decision')}" if p.get("decision") else ""))
    if kind == "action.undone":
        done = "undone" if p.get("undone") else f"not undone ({p.get('status') or '?'})"
        return f"{p.get('action_id', '?')} on {p.get('scope') or '*'}: {done}"
    if kind == "authority.graduated":
        return (f"{p.get('action_id', '?')} on {p.get('scope') or '*'} graduated to L{p.get('level', '?')}"
                + (f" inside mission {str(p.get('mission'))[:12]}" if p.get("mission") else ""))
    if kind == "authority.demoted":
        revoked = p.get("grants_revoked") or 0
        return (f"{p.get('action_id', '?')} on {p.get('scope') or '*'} demoted: {str(p.get('why') or '?')[:120]}"
                + (f" ({revoked} standing grant{'s' if revoked != 1 else ''} withdrawn)" if revoked else ""))
    if kind == "service_principal.minted":
        what = ("minted" if not p.get("rotated") else "rotated") if p.get("active") else "revoked"
        return f"service principal {p.get('name', '?')} {what}"
    if kind == "mcp.oauth":
        return (f"{p.get('action', '?')} on tool server {str(p.get('server_id') or '?')[:16]}"
                + (f" — {str(p.get('detail'))[:80]}" if p.get("detail") else ""))
    if kind == "method.registered":
        state = "withdrawn" if p.get("active") is False else "registered"
        return f"{p.get('kind') or 'method'} {p.get('method', '?')} {state}"
    if kind == "intake.governance":
        act = p.get("action", "?")
        if act == "resolve":
            return (f"resolved intake {str(p.get('bundle') or '?')[:16]}: "
                    f"{p.get('accepted', 0)} accepted, {p.get('dismissed', 0)} dismissed")
        return (f"{act} intake bundle {str(p.get('bundle') or '?')[:16]}"
                f" ({p.get('staged', 0)} staged, {p.get('refused', 0)} refused)")
    if kind == "llm_call":
        return f"{p.get('role') or 'model'} call"
    if kind == "decision_replay":
        return f"captured replay arguments for a {p.get('site') or 'decision'} pick"
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
    if kind == "govern.cap":
        limit = p.get("limit")
        return (f"{p.get('action', '?')} cap on {p.get('metric') or '?'} for "
                f"{p.get('subject') or p.get('scope') or '?'}"
                + (f" at {limit}" if limit is not None else ""))
    if kind == "budget.exceeded":
        return (f"job cancelled for {p.get('agent') or 'an agent'}: "
                f"{p.get('reason') or 'a governed cap was exceeded'}")
    if kind == "metric.enforcement":
        drift = [str(d) for d in (p.get("drift") or [])]
        used = p.get("enforced")
        head = ("governed formula used" if used else
                "governed formula improvised" if used is not None else "governed metric checked")
        return head + (f" — drift on {', '.join(drift)[:80]}" if drift else "")
    if kind == "guardrail":
        detail = str(p.get("detail") or "").strip()
        return (f"guardrail {p.get('guardrail') or '?'} blocked"
                + (f" {p.get('agent_id')}" if p.get("agent_id") else "")
                + (f" — {detail[:60]}" if detail else ""))
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


def _from_session_replays(limit: int) -> list[AuditEvent]:
    """Replay captures — read through ``session_events``, like model calls, and for the same
    reason: the generic ``events`` reader returns NOTHING for a session-event kind. Pointing a
    ledger sink at ``decision_replay`` would satisfy the categorisation ratchet and render an
    empty feed on a system writing captures — a guard passing for the wrong reason.

    🔒 The ``detail`` carries METADATA ONLY. The captured payload (the user's question, the
    analyst's intake, prior answers) is exactly what the capture window gates, and copying it
    into an audit row would turn the feed into a second, ungated read path for it. What an
    auditor needs is THAT content was stored, when, for which decision — not the content.
    """
    from aughor.kernel.ledger import Ledger
    from aughor.obs.session_log import DECISION_REPLAY
    from aughor.security.authz import tenant_scope

    try:
        rows = Ledger.default().session_events(kind=DECISION_REPLAY, limit=limit,
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
            category="data_access", kind=DECISION_REPLAY,
            at=str(e.get("at") or e.get("created_at") or ""),
            actor=str(e.get("user_id") or ""), org_id=str(e.get("org_id") or ""),
            conn_id=str(e.get("conn_id") or ""),
            summary=f"captured replay arguments for a {p.get('site') or 'decision'} pick",
            detail={"site": p.get("site"), "builder": p.get("builder"),
                    "decision_id": p.get("decision_id"),
                    "prompt_fingerprint": p.get("prompt_fingerprint"),
                    "truncated": sorted(k for k, v in p.items()
                                        if k.endswith("_truncated") and v)}))
    return out


def _from_session_guardrails(limit: int) -> list[AuditEvent]:
    """Guardrail BLOCKS — a session-event kind, like model calls, and read the same way.

    Both halves of a guardrail verdict are written (`govern/guardrails.py`: a rate needs its
    denominator), so the raw trail is mostly allows — 1,074 of 1,074 rows on the local
    ledger when MI-1 measured it. The feed carries the blocks: what a reader asking "what
    was stopped, and why" wants, and nothing an allow would drown. The allow count stays
    where the block rate is computed from it. Over-read by a margin so a window of allows
    still yields the blocks inside it; the merged feed re-sorts and caps.
    """
    from aughor.kernel.ledger import Ledger
    from aughor.obs.session_log import GUARDRAIL
    from aughor.security.authz import tenant_scope

    try:
        rows = Ledger.default().session_events(kind=GUARDRAIL, limit=max(limit, 1) * 4,
                                               org_id=tenant_scope()) or []
    except Exception as exc:
        from aughor.kernel.errors import tolerate

        tolerate(exc, "one audit sink being unreadable must not blank the whole feed",
                 counter="govern.audit_feed_sink")
        return []
    out: list[AuditEvent] = []
    for e in rows:
        p = e.get("payload") or {}
        blocked = bool(p.get("blocked")) or e.get("ok") is False
        if not blocked:
            continue
        out.append(AuditEvent(
            category="enforcement", kind="guardrail",
            at=str(e.get("at") or e.get("created_at") or ""),
            actor=str(p.get("agent_id") or e.get("user_id") or ""),
            org_id=str(e.get("org_id") or ""), conn_id=str(e.get("conn_id") or ""),
            summary=_summarize("guardrail", p),
            detail={"guardrail": p.get("guardrail"), "detail": p.get("detail"),
                    "agent_id": p.get("agent_id")}))
        if len(out) >= limit:
            break
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
#: Kinds written to ``session_events`` rather than the generic ledger. The ``_from_ledger``
#: reader returns NOTHING for these, so each rides a dedicated reader below. Declared HERE,
#: beside the readers, so the categorisation ratchet reads it from the code instead of a
#: hand-kept exemption in the test — which was `{"llm_call"}` until 2026-09-21, and went red the
#: moment a second session-event kind arrived for the identical reason. A list copied beside its
#: expectation is the shape that cannot fail; `tests/unit/test_govern_audit_feed.py` now also
#: proves each of these readers actually returns an event, since exempting a kind from the
#: string check is only safe if something else shows its reader works.
SESSION_EVENT_KINDS: frozenset[str] = frozenset({"llm_call", "decision_replay", "guardrail"})


_SINKS: list[tuple[str, Callable[[int], list[AuditEvent]]]] = [
    ("data_access", _from_audit_table),
    ("data_access", lambda n: _from_ledger("trace.payload_access", n)),
    ("data_access", lambda n: _from_ledger("mcp.tool_call", n)),
    ("action_decision", lambda n: _from_ledger("action.approval", n)),
    ("action_decision", lambda n: _from_ledger("action.autonomous", n)),
    ("action_decision", lambda n: _from_ledger("action.undone", n)),
    ("governance_change", lambda n: _from_ledger("govern.tag", n)),
    ("governance_change", lambda n: _from_ledger("metric.governance", n)),
    ("governance_change", lambda n: _from_ledger("trusted_query.governance", n)),
    ("governance_change", lambda n: _from_ledger("intake.governance", n)),
    ("governance_change", lambda n: _from_ledger("pack.installed", n)),
    ("governance_change", lambda n: _from_ledger("authority.graduated", n)),
    ("governance_change", lambda n: _from_ledger("authority.demoted", n)),
    ("governance_change", lambda n: _from_ledger("service_principal.minted", n)),
    ("governance_change", lambda n: _from_ledger("mcp.oauth", n)),
    ("governance_change", lambda n: _from_ledger("method.registered", n)),
    ("model_call", _from_session_log),
    ("data_access", _from_session_replays),
    # A mapping entry alone renders NOTHING: `feed` walks this list, not KIND_CATEGORY.
    # The two lists are parallel and hand-maintained, which is why the ratchet now
    # asserts they agree rather than trusting that whoever edited one edited the other.
    ("human_verdict", lambda n: _from_ledger("chat.feedback", n)),
    ("human_verdict", lambda n: _from_ledger("trace.feedback", n)),
    # Phase 0 (2026-10-04) — the enforcement trail, one sink per kind.
    ("enforcement", lambda n: _from_ledger("govern.cap", n)),
    ("enforcement", lambda n: _from_ledger("budget.exceeded", n)),
    ("enforcement", lambda n: _from_ledger("metric.enforcement", n)),
    ("enforcement", _from_session_guardrails),
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
