"""The event catalogue — every kind the kernel journal is written with, published (the 2027 study
§Q "Events out"; phase 7, P7-2).

Automations could already send a webhook on a change, but there was no stable catalogue of what the
platform journals: an outside tool could not know which kinds exist or what each payload carries. This
module is that catalogue, held to the code by a ratchet (`tests/unit/test_event_catalogue.py`): every
literal kind the source emits must be here, so a new kind is a decision somebody wrote down, and a row
here names what the payload carries. `GET /ledger/v1/events/catalogue` serves it; `GET /ledger/v1/events`
reads the journal by kind from a cursor; a subscription (`record/subscriptions.py`) delivers the kinds an
outside tool asked for as webhooks.

A row's `payload` names the keys a reader may rely on; `category` is the governance feed's word for it
(`govern/audit_categories.py`), so the catalogue and the feed never disagree about what a kind is.
"""
from __future__ import annotations

from typing import Any

#: kind → what it records, the payload keys a reader may rely on, and where it is emitted.
CATALOGUE: dict[str, dict[str, Any]] = {
    # ── the Record (phases 1–6) ────────────────────────────────────────────────────────────
    "claim.restated": {"what": "a claim was restated: a new version under its key, the old kept", "payload": ["claim_id", "supersedes", "key", "kind", "tier", "author", "text", "metric", "value", "unit", "as_of"], "emitted_by": "record/claims.book"},
    "claim.refuted": {"what": "a hypothesis was tested false", "payload": ["claim_id", "key", "tier", "text", "evidence", "run"], "emitted_by": "record/claims.book"},
    "outcome.booked": {"what": "a decision's outcome was measured", "payload": ["outcome_id", "decision", "verdict", "against_expectation", "actual", "baseline"], "emitted_by": "record/decisions.book_outcome"},
    "prediction.scored": {"what": "a prediction's range was Final and it was scored", "payload": ["claim_id", "key", "metric", "method", "scored_against", "actual", "low", "high", "tier"], "emitted_by": "record/scenario.score_prediction"},
    "inquiry.woke": {"what": "a waiting inquiry woke", "payload": ["inquiry_id", "key", "why", "question"], "emitted_by": "record/inquiry.wake"},
    "inquiry.signal": {"what": "a weak signal opened or woke an inquiry: the settling lag moved, a process's early stage slowed or a promise is breaking more", "payload": ["signal", "connection_id", "inquiry", "text", "before", "after"], "emitted_by": "record/signals"},
    "mission.reported": {"what": "a mission's report was composed, booked and delivered", "payload": ["mission", "report", "verdict", "delivery"], "emitted_by": "record/mission.report_now"},
    "authority.graduated": {"what": "an action graduated on a receipt: to L4, or to L5 inside a mission", "payload": ["action_id", "scope", "receipt", "by", "level", "mission"], "emitted_by": "actions/authority.graduate, grant_l5"},
    "action.autonomous": {"what": "the L5 agent chose among the declared actions toward a mission and ran one, or was held", "payload": ["mission", "action_id", "decision", "entry", "status", "acted"], "emitted_by": "actions/autonomy.act"},
    "authority.demoted": {"what": "an action was demoted and its grants withdrawn", "payload": ["action_id", "scope", "why", "grants_revoked", "entry"], "emitted_by": "actions/authority.demote"},
    "authority.ceiling": {"what": "a person capped an action on a connection at a level, or lifted the cap", "payload": ["action_id", "scope", "level", "by", "why", "entry"], "emitted_by": "actions/authority.set_ceiling"},
    "action.undone": {"what": "an execution's declared undo was fired: whether it undid it, and the compensating entry", "payload": ["action_id", "scope", "entry", "undo_entry", "status", "undone", "by"], "emitted_by": "actions/authority.undo"},
    "answer.rechecked": {"what": "a past answer was re-run and compared", "payload": ["investigation_id", "status", "changed", "cause"], "emitted_by": "answer/recheck"},
    "ledger.delivered": {"what": "a subscription's delivery of an event: sent, failed, or held at the departure gate with why", "payload": ["subscription", "event", "status", "http_status", "why", "departure", "url_host"], "emitted_by": "record/subscriptions.notify"},
    "ledger.subscribed": {"what": "a subscription to events out was created or withdrawn", "payload": ["subscription", "kinds", "active", "by"], "emitted_by": "record/subscriptions"},
    "method.registered": {"what": "a forecaster, estimator or simulator was registered with its backtest", "payload": ["method", "kind", "by", "backtest"], "emitted_by": "record/methods.register"},
    "service_principal.minted": {"what": "a service principal was minted or revoked", "payload": ["name", "by", "active"], "emitted_by": "security/service_principals"},
    # ── packs (phases 6–7) ─────────────────────────────────────────────────────────────────
    "pack.status_changed": {"what": "a pack moved between draft, active and deprecated", "payload": ["pack_id", "from", "to", "actor", "source", "partial"], "emitted_by": "packs/promote.set_status"},
    "pack.installed": {"what": "a pack's function layer was installed", "payload": ["pack_id", "actor", "group", "grants"], "emitted_by": "packs/install"},
    "pack.uploaded": {"what": "a pack was uploaded through the kit and written as a draft", "payload": ["pack_id", "by", "files", "warnings"], "emitted_by": "packs/kit.upload"},
    "pack.demoted": {"what": "a pack was demoted on its measured record", "payload": ["pack_id", "by", "record", "why"], "emitted_by": "packs/record.demote"},
    "playbook.use": {"what": "a play was rendered into an analysis prompt, pinned to its version", "payload": ["entry_id", "version", "receipt", "used_in"], "emitted_by": "playbook/store.emit_playbook_use"},
    # ── governance ─────────────────────────────────────────────────────────────────────────
    "action.approval": {"what": "the approval gate's decision on a governed action", "payload": ["action", "risk", "decision", "scope", "actor", "detail"], "emitted_by": "govern/actions"},
    "govern.tag": {"what": "a securable's governance tags changed", "payload": ["action"], "emitted_by": "govern/tag_store"},
    "govern.cap": {"what": "a usage cap was set, changed or fired", "payload": ["action"], "emitted_by": "govern/cap_store"},
    "budget.exceeded": {"what": "a job was cancelled for exceeding a governed cap", "payload": ["agent", "reason"], "emitted_by": "kernel/jobs"},
    "metric.governance": {"what": "a governed metric was created, changed or deleted", "payload": ["metric", "action", "at"], "emitted_by": "routers/metrics"},
    "metric.enforcement": {"what": "a governed metric definition was enforced on an answer", "payload": ["metric", "enforced"], "emitted_by": "routers/investigations"},
    "trusted_query.governance": {"what": "a trusted query was created, approved or changed", "payload": ["trusted_query", "connection_id", "action", "actor", "from", "to"], "emitted_by": "semantic/trusted_verify, routers/learning"},
    "intake.governance": {"what": "an intake bundle was uploaded or a person resolved an item", "payload": ["action"], "emitted_by": "routers/intake"},
    "eval.graduation": {"what": "a flag's graduation decision was recorded", "payload": ["flag", "can_graduate", "pass_rate", "reasons"], "emitted_by": "routers/evals"},
    "mcp.tool_call": {"what": "an agent's call through the MCP door, allowed or refused", "payload": ["actor", "tool", "route", "allowed", "code", "required_level", "policy_level"], "emitted_by": "rbac/agent_gate"},
    "mcp.oauth": {"what": "a person signed in to an OAuth-authenticated MCP server, failed to, or signed out", "payload": ["server_id", "action", "by", "detail"], "emitted_by": "mcpservers/oauth"},
    "chat.feedback": {"what": "a person's verdict on a chat turn", "payload": ["turn_id", "verdict", "note"], "emitted_by": "routers/query"},
    "trace.feedback": {"what": "a person's verdict on a run", "payload": ["trace_id", "verdict", "note", "by"], "emitted_by": "routers/obs"},
    "trace.payload_access": {"what": "a run's captured payload was read", "payload": ["trace_id"], "emitted_by": "routers/obs"},
    "monitor.alert": {"what": "a monitor fired an alert", "payload": ["monitor_id", "monitor_name", "severity", "metric", "current_value", "message"], "emitted_by": "monitors/store"},
    "automation.run": {"what": "an automation ticked: its outcome, reason and effects", "payload": ["automation_id", "automation_name", "outcome", "reason", "effects"], "emitted_by": "automations/store"},
    "brief.delivered": {"what": "a scheduled Briefing was delivered, or failed to be", "payload": ["subscription_id", "name", "period", "status", "error"], "emitted_by": "briefing/delivery"},
    "agent.handoff": {"what": "one agent handed a phase to another inside a deep analysis", "payload": ["from", "to", "phase"], "emitted_by": "agent/handoff"},
    # ── operations ─────────────────────────────────────────────────────────────────────────
    "api.started": {"what": "the API process started", "payload": [], "emitted_by": "api"},
    "error.tolerated": {"what": "an error was tolerated and the work went on without it", "payload": ["reason", "error", "counter"], "emitted_by": "kernel/errors.tolerate"},
    "job.state": {"what": "a kernel job changed state", "payload": ["state", "kind", "error"], "emitted_by": "kernel/jobs"},
    "job.orphaned": {"what": "a job was found running with no process", "payload": ["kind"], "emitted_by": "kernel/jobs"},
    "job.foreign": {"what": "a job belonged to another process", "payload": ["kind"], "emitted_by": "kernel/jobs"},
    "store.wal_drift": {"what": "a store's WAL drifted from the ledger", "payload": ["store"], "emitted_by": "kernel"},
    "node.span": {"what": "a graph node's timing", "payload": ["name", "ms"], "emitted_by": "telemetry"},
    "phase_complete": {"what": "a deep analysis finished a phase", "payload": ["phase", "all_phases"], "emitted_by": "agent/analyst"},
    "investigations.swept": {"what": "stale investigations were swept", "payload": ["swept"], "emitted_by": "db/history"},
    "explorer.resumed": {"what": "the explorer resumed on a connection", "payload": ["connection_id"], "emitted_by": "explorer"},
    "exploration.skipped": {"what": "exploration was skipped on a connection, with the reason", "payload": ["reason", "connection_id"], "emitted_by": "routers/_shared"},
    "exploration.rearmed": {"what": "the continuous loop started one of a dataset's jobs (structure, questions or both), with why", "payload": ["reason", "job", "connection_id", "schema"], "emitted_by": "explorer/continuous"},
    "exploration.watched": {"what": "a dataset's metrics were read for a newly settled period, SQL only", "payload": ["connection_id", "schema", "grains", "daily"], "emitted_by": "explorer/continuous"},
    "exploration.first_insight": {"what": "an exploration found its first finding", "payload": ["insight"], "emitted_by": "explorer/agent"},
    "exploration.insight": {"what": "an exploration booked a finding", "payload": ["insight"], "emitted_by": "explorer/agent"},
    "exploration.phase": {"what": "an exploration moved to a phase", "payload": ["phase"], "emitted_by": "explorer/agent"},
    "ontology.measure": {"what": "a measurement pass ran over a built ontology", "payload": ["ok", "schema", "relationships", "lifecycles"], "emitted_by": "routers/ontology"},
    "ontology.explore": {"what": "the business explorer ran on a scope", "payload": ["ok", "schema", "run", "backend", "model", "said", "written", "refused"], "emitted_by": "routers/ontology"},
    "ontology.build": {"what": "an ontology build ended", "payload": ["ok", "entities", "stage", "error"], "emitted_by": "routers/ontology"},
    "birth.step": {"what": "a step of a connection's birth", "payload": ["connection_id", "schema"], "emitted_by": "routers/_shared"},
    "birth.done": {"what": "a connection's birth completed", "payload": ["connection_id"], "emitted_by": "routers/_shared"},
    "brief.superseded_automation": {"what": "a Day subscription paused the automation it replaces", "payload": ["automation_id"], "emitted_by": "briefing"},
}

#: Kinds an outside tool may subscribe to as webhooks — the Record's own, where a payload is a fact about the business.
SUBSCRIBABLE: tuple[str, ...] = ("claim.restated", "claim.refuted", "outcome.booked", "prediction.scored", "mission.reported",
                                 "authority.graduated", "authority.demoted", "pack.demoted")


def catalogue() -> list[dict[str, Any]]:
    """Every kind with its category on the governance feed."""
    try:
        from aughor.govern.audit_categories import KIND_CATEGORY, NON_GOVERNANCE_KINDS
    except Exception:  # noqa: BLE001
        KIND_CATEGORY, NON_GOVERNANCE_KINDS = {}, frozenset()
    out = []
    for kind, row in sorted(CATALOGUE.items()):
        category = KIND_CATEGORY.get(kind) or ("operational" if kind in NON_GOVERNANCE_KINDS else "record")
        out.append({"kind": kind, **row, "category": category, "subscribable": kind in SUBSCRIBABLE})
    return out


def is_catalogued(kind: str) -> bool:
    return kind in CATALOGUE
