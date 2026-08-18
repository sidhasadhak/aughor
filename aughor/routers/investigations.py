"""Investigations — chat, investigate, HITL feedback, history, outcomes, reindex."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
from dataclasses import dataclass, field
from typing import AsyncGenerator, Callable, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from aughor.agent.state import AgentState
from aughor.db.connection import open_connection_for
from aughor.kernel.concurrency import ContextThreadPoolExecutor
from aughor.db.history import (
    complete_investigation,
    create_investigation,
    fail_investigation,
    get_investigation,
    get_session_turns,
    list_investigations,
    pause_investigation,
    save_chat_turn,
)
from aughor.db.registry import BUILTIN_ID
from aughor.security.authz import get_principal
from aughor.routers._shared import (
    explorers_for_connection as _explorers_for_connection,
    get_schema_cached as _get_schema_cached,
)

logger = logging.getLogger(__name__)
from aughor.licensing import Capability, gate

router = APIRouter(tags=["investigations"])


def _record_memory(inv_id: str, connection_id: str, question: str, state: dict) -> None:
    """Persist this run's reflection signals (confidence/surprise/plausibility/
    pitfalls) into the unified agent memory.  Best-effort: never breaks the stream."""
    try:
        from aughor.memory import record_run
        record_run(inv_id, connection_id, question, state)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "run-reflection memory record is best-effort; the investigation result is already delivered",
                 counter="investigation.memory_record")
    # Graduated skill promotion: once a connection has EARNED L2 trust, a
    # high-confidence, grounded, read-only run auto-crystallizes into a reusable
    # learned skill — stored under the exact graph.schema_name the planner reads
    # from, gated by a read-only EXPLAIN dry-run.  Below L2 it's left as a
    # candidate for the UI to confirm.  Best-effort: never breaks the stream.
    # (auto_crystallize opens a connection only for L2+ skill-worthy runs.)
    try:
        from aughor.memory.skills import auto_crystallize
        auto_crystallize(inv_id, connection_id)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "skill auto-crystallization is best-effort post-run promotion; the answer is unaffected",
                 counter="investigation.skill_crystallize")


# ── SSE + stream helpers ──────────────────────────────────────────────────────

def _sse(event_type: str, data: dict) -> str:
    return f"data: {json.dumps({'type': event_type, **data})}\n\n"


def _error_event(exc: "BaseException | None" = None, *, message: str = "",
                 reason: str = "") -> dict:
    """The payload for an ``error`` SSE frame — the ONE place its shape is decided (Wave R4).

    This was assembled independently at fifteen sites, each emitting a bare
    ``{"message": str(e)}``, so a rate limit, a wrong API key, a retired model id and a
    timed-out run all reached the user as the same red line of prose — and the whole
    classification Waves R1 and R2 built stopped at the provider boundary instead of
    reaching the person waiting.

    ``message`` is unchanged from what each site already produced; the typed fields
    (``reason``/``retryable``/``recovery``/``hint``) ride alongside, so every existing
    consumer is byte-identical until it opts in.
    """
    from aughor.agent.answer_errors import error_event

    return error_event(exc, message=message, reason=reason)


#: The follow-up ask, shared by both branches of the quick path's merged
#: narrative+follow-ups call (Wave 2 / 2.1). The deep paths build the whole prompt from
#: `aughor/agent/followups.py`; here the ask has to ride inside the narrative prompt,
#: because merging the two into ONE narrator call is what stopped this path spending
#: two round-trips per answer. Same voice instruction either way: a chip is typed into
#: the composer verbatim when clicked, so it must read as the user's own words.
_FOLLOWUP_CLAUSE = (
    "suggest exactly 3 follow-up questions written AS THE USER would type them "
    "(max 12 words each) — concrete operations on THIS result, using its real column "
    "names: change the grouping, change the window, filter to a segment, or chase the "
    "biggest mover. Never write about the user ('the user could…'); write what they "
    "would say ('break this out by region')."
)

#: What each guard flag means, in the voice the narrator should explain it in. Only
#: the flags that CHANGED or QUALIFIED the answer appear — a guard that ran and found
#: nothing is not news, and narrating it would train the reader to skip the prose.
_GUARD_PROSE = {
    "grounded": "the first draft's number did not match the result cells, so it was corrected",
    "defan": "the SQL was rewritten to stop a join counting rows more than once",
    "narration_inversion": "this value varies by group and is not uniform across every row",
    "measure_grain": "the measure may be summed at the wrong grain (per-unit vs per-line)",
    "id_arithmetic": "the total multiplies a measure by an id/key column, so its magnitude is unreliable",
    # Not a guard rewrite — an assumption the user asked us to make. It belongs in the
    # same breath as the rest: everything here is something the reader must account for
    # when reading the number (Wave 3 / 2.3).
    "assumed": "the question had more than one reasonable reading and you asked for a "
               "best guess, so ONE reading was chosen — say which one you answered",
}


def _guard_note(rcpt: dict) -> str:
    """The guard interventions of this turn, as an instruction to the narrator.

    Wave 2 / 2.2. The receipts already reach the UI as frames; this puts them in front
    of the ANSWERING model so a correction is explained in the answer's own voice —
    "restriction becomes visible direction" — instead of arriving only as a clause
    appended to the headline.

    Explicitly asks for one plain sentence and forbids re-deriving the number: the
    model must explain what happened, not relitigate the corrected value.
    """
    notes = [prose for key, prose in _GUARD_PROSE.items() if rcpt.get(key)]
    e1 = rcpt.get("e1_messages") or []
    if e1:
        notes.append("a trust check flagged the result: " + "; ".join(str(m) for m in e1[:2]))
    if not notes:
        return ""
    return ("\n\nWHAT THE GUARDS DID — explain this to the user in ONE plain sentence, "
            "in your own words, as part of the narrative. Do not restate the number and "
            "do not apologise; say what it means for reading the answer:\n- "
            + "\n- ".join(notes))


def _explore_subq_event(a) -> dict:
    """The `subq_answer` progress-event payload for one completed sub-question (T3-3: per-subq
    evidence + progress, so the wave path isn't a multi-minute silent gap). Carries the sub-question's
    own columns+rows, which the frontend's per-step ``ResultChartCard`` renders as a chart — so once
    every sub-question's evidence is forwarded (not just the last), each step charts itself."""
    d = a.model_dump()
    d["rows"] = (getattr(a, "rows", None) or [])[:30]
    return d


async def _reduced_subq_answers(agent, inv_id, fallback):
    """The authoritative, reducer-accumulated `subq_answers` from graph state — the streaming router's
    manual dict-merge clobbers the `operator.add` channel (each node delta overwrites it), so the final
    `explore_report` used to forward only the LAST sub-question's SQL+rows. Re-read the checkpoint so
    ALL sub-questions' evidence is forwarded; fall back to the clobbered list on any read error."""
    try:
        import asyncio as _a
        st = await _a.to_thread(lambda: agent.get_state({"configurable": {"thread_id": inv_id}}))
        vals = getattr(st, "values", None) or {}
        return vals.get("subq_answers") or fallback
    except Exception:
        return fallback


def _ada_sqls(ada) -> list[str]:
    """Every executed SQL in an ADA report — walks the report dict collecting
    string values under 'sql' keys. More reliable than query_history, which can
    be empty on some terminal paths (the false-drift cause)."""
    out: list[str] = []

    def _walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "sql" and isinstance(v, str) and v.strip():
                    out.append(v)
                else:
                    _walk(v)
        elif isinstance(o, list):
            for v in o:
                _walk(v)

    _walk(ada if isinstance(ada, dict) else {})
    seen, uniq = set(), []
    for x in out:
        if x not in seen:
            seen.add(x); uniq.append(x)
    return uniq


def _note_finding_on_graph(*, connection_id: str, receipt_id: str | None,
                           headline: str, sql: str, tables: list[str]) -> None:
    """Land this answer on the connection knowledge graph as a `finding` node.

    Keyed by the receipt id, so the incremental node and the one a later full rebuild
    projects from the same receipt are the SAME node — a rebuild supersedes, it never
    duplicates. Never raises: an answer must not fail because a graph write did.

    No schema is passed on purpose. The receipt path's ``schema`` is the schema *text*
    handed to metric enforcement, not a schema *name*, and feeding it to the store
    would address a graph file named after a DDL blob. ``note_finding`` resolves the
    target itself and declines when a connection has several graphs rather than
    guessing which schema the answer belongs to.
    """
    if not receipt_id or not headline:
        return
    try:
        from aughor.ontology.context_graph_build import note_finding
        note_finding(
            connection_id,
            {"id": receipt_id, "text": headline, "sql": sql, "tables": tables,
             "source": "evidence_ledger", "generated_at": ""},
        )
    except Exception:
        logger.debug("graph finding write failed", exc_info=True)


def _write_answer_receipt(*, kind: str, natural_key: str, question: str,
                          sqls: list[str], headline: str, schema: str,
                          connection_id: str, canvas_id: str = "",
                          guard_edges: list | None = None,
                          payload_extra: dict | None = None) -> dict:
    """K3-wide Trust Receipt for any user-facing answer (chat / ADA / monitor):

    Returns ``{"learning": …|None, "activations": …|None}`` — the per-run Learning Receipt (Wave 1·E4) and
    Activation Receipt (Wave 1·E3), each present only when its flag is on and the run had something to
    report — so a streaming caller can emit them as SSE events.
    a versioned ledger artifact with HONEST lineage + B-7 metric enforcement.
    Records only verifiable provenance — executed SQL(s), input tables, the
    registered metrics available, whether the governed formula was USED or the
    answer DRIFTED, plus any guard edges the caller proved fired. Best-effort;
    never raises into the answer path."""
    try:
        from aughor.kernel.ledger import Ledger
        sqls = [s for s in (sqls or []) if s]
        lineage: list = [("source_sql", "sql", s) for s in sqls[:6]]
        seen: set[str] = set()
        for s in sqls:
            for t in _extract_tables(s):
                if t not in seen:
                    seen.add(t)
                    lineage.append(("input", f"table:{t}", None))
        enf = None
        try:
            from aughor.semantic.metrics import list_metrics, filter_metrics_to_schema
            from aughor.semantic.enforcement import (
                check_metric_enforcement, enforcement_summary, propose_undefined_metrics,
            )
            # Keep every surviving grain for enforcement: a query matches one grain,
            # so collapsing first would mislabel a correct answer as drift.
            # check_metric_enforcement collapses its own verdicts to one-per-name.
            cms = filter_metrics_to_schema(list_metrics(), schema, dedupe=False)
            _av_seen: set[str] = set()
            for m in cms:
                if m.name in _av_seen:  # one "available" badge per metric name
                    continue
                _av_seen.add(m.name)
                lineage.append(("metric_available", f"metric:{m.name}", m.sql))
            verdicts = check_metric_enforcement(question, " ".join(sqls), cms)
            for v in verdicts:
                rel = "metric_used" if v["status"] == "used" else "metric_drift"
                lineage.append((rel, f"metric:{v['metric']}", v["detail"]))
            enf = enforcement_summary(verdicts)
            # B-7 propose-to-define: KPI concepts the question names that nothing
            # governs yet — surfaced so the user can define them (then they're enforced).
            for p in propose_undefined_metrics(question, cms):
                lineage.append(("metric_proposed", f"metric:{p['slug']}",
                                f"no governed definition for “{p['phrase']}” — define it to enforce"))
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "metric-enforcement lineage on the Trust Receipt is best-effort; the receipt still writes without it",
                     counter="chat.receipt_metrics")
        for e in (guard_edges or []):
            lineage.append(e)
        # Wave P1 — the graph nodes the planner was actually SHOWN before writing this
        # SQL. `last_cited_nodes()` has been populated on every read-back since Wave C2
        # and read by nothing but its own tests: the receipt's own flag description
        # claimed "the block the context receipt shows names exactly what grounded the
        # plan", which was true of the prompt and not of the receipt. One consumer closes
        # it. Empty when the read-back experiment is off — the trace is then built from
        # the tables and metrics this answer demonstrably used, which every answer records.
        try:
            from aughor.ontology.context_graph_readback import last_cited_nodes
            for _nid in last_cited_nodes()[:12]:
                lineage.append(("grounded_in_graph", _nid, None))
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "graph citations on the Trust Receipt are best-effort; the receipt still writes without them",
                     counter="chat.receipt_graph_citations")
        # I6 — surface ambiguity handling on the Trust Receipt: any resolution THIS question
        # matched in the Ambiguity Ledger (settled earlier by a probe / the user / a reviewer) is
        # recorded, so "this answer followed a previously-resolved reading" is inspectable — the
        # machinery made honest to the user. Best-effort.
        _resolved_ambig: list = []
        try:
            from aughor.semantic.ambiguity_ledger import retrieve_resolutions
            for _r, _sc in retrieve_resolutions(question, connection_id, top_k=3):
                _resolved_ambig.append({"subject": _r.subject, "reading": _r.resolved_reading,
                                        "source": _r.resolution_source})
                lineage.append(("resolved_ambiguity", f"reading:{_r.subject[:60]}",
                                f"{_r.resolved_reading} (resolved by {_r.resolution_source})"))
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "ambiguity-ledger lineage on the Trust Receipt is best-effort; the receipt still writes without it",
                     counter="chat.receipt_ambiguity")
        # Per-run Learning Receipt (Wave 1·E4): what the closed loop DID this run — readings reused /
        # corrections (from the resolutions above) plus runtime events (crystallized, trusted replay).
        # Flag-gated (learning.receipt) → None when off; best-effort, never breaks the receipt.
        _learning = None
        try:
            from aughor.agent.learning_receipt import build_learning_receipt
            _learning = build_learning_receipt(_resolved_ambig)
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "learning receipt is best-effort; the Trust Receipt still writes without it",
                     counter="chat.receipt_learning")
        # Activation Receipt (Wave 1·E3): which self-gating guards fired this run + the trigger that fired
        # each. Flag-gated (capabilities.receipt) → None when off; best-effort, never breaks the receipt.
        _activations = None
        try:
            from aughor.agent.learning_receipt import build_activation_receipt
            _activations = build_activation_receipt()
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "activation receipt is best-effort; the Trust Receipt still writes without it",
                     counter="chat.receipt_activations")
        # Stamp per-run compute onto the artifact so the Trust Receipt shows what the
        # answer cost. For job-backed answers (ADA) the job row carries the full total
        # too; for the synchronous quick-answer path this is the only sink.
        from aughor.kernel import metering
        _cost = metering.snapshot()
        # WP-10: stamp the coder model used, so the public receipt's model{role,id} is honest
        # (the model at answer time, not the config at read time). Best-effort.
        _model = None
        try:
            from aughor.llm.provider import get_provider
            _model = {"role": "coder", "id": getattr(get_provider("coder"), "model", None)}
        except Exception:
            _model = None
        # Wave H2: the persona this answer was produced AS, read from the ambient contextvar
        # rather than threaded through — so a scheduled agent run (H1) and an interactive one
        # stamp identically. This function is the ONE place every user-facing answer is
        # receipted (chat / ADA / monitor), so stamping here attributes all three by
        # construction. Absent when nobody asked as an agent — an unbound answer says so by
        # omission rather than carrying an empty agent that reads like a real one.
        _agent = None
        try:
            from aughor.custom_agents.context import current_agent
            _a = current_agent()
            _agent = {"id": _a.id, "name": _a.name} if _a is not None else None
        except Exception:
            _agent = None
        _receipt_id = Ledger.default().artifact_write(
            kind, natural_key,
            {"question": question, "headline": headline or question,
             "sql": sqls[0] if sqls else "", "tables": sorted(seen),
             **({"cost": _cost} if _cost is not None else {}),
             **({"model": _model} if _model else {}),
             **({"agent": _agent} if _agent else {}),
             **({"resolved_ambiguities": _resolved_ambig} if _resolved_ambig else {}),
             **({"learning": _learning} if _learning else {}),
             **({"activations": _activations} if _activations else {}),
             **(payload_extra or {})},
            conn_id=connection_id, canvas_id=canvas_id or None, lineage=lineage,
        )
        if enf is not None:
            Ledger.default().emit("metric.enforcement", enf,
                                  conn_id=connection_id, canvas_id=canvas_id or None)
        # Wave L1: the answer becomes a `finding` node on the connection knowledge graph
        # NOW, so the next question can read back what this one learned. This is the one
        # place every user-facing answer (chat / ADA / monitor) is receipted, so wiring
        # here covers all three callers by construction rather than by three edits.
        # Gated by `graph.build`, best-effort, and the finding shape is exactly what
        # `load_investigation_findings` would rebuild from the same receipt.
        _note_finding_on_graph(
            connection_id=connection_id, receipt_id=_receipt_id,
            headline=headline or question, sql=sqls[0] if sqls else "",
            tables=sorted(seen),
        )
        # `receipt_id` is the stable artifact id → the unified GET /receipt/{id} (WP-10); a
        # streaming caller emits it so the UI's "Why this number" opens the public receipt.
        return {"learning": _learning, "activations": _activations, "receipt_id": _receipt_id}
    except Exception:
        logger.debug("%s receipt write failed", kind, exc_info=True)
    return {"learning": None, "activations": None, "receipt_id": None}


#: Public name for the Trust-Receipt writer. The converse tool loop's `run_sql`
#: (agent/converse_tools.py) writes a receipt for a primitive answer the same way the
#: core writes one for its own — one writer, two callers, one receipt shape.
write_answer_receipt = _write_answer_receipt


_TABLE_RE = re.compile(r'\b(?:FROM|JOIN)\s+(?:\w+\.)?(\w+)', re.IGNORECASE)
# Matches CTE definitions: anything of the form `name AS (`  (only valid for CTEs in SQL)
_CTE_DEF_RE = re.compile(r'\b(\w+)\s+AS\s*\(', re.IGNORECASE)


_DIM_NOUN_RE = re.compile(
    r"\b(categor(?:y|ies)|segments?|tiers?|brands?|channels?|regions?|countr(?:y|ies)|"
    r"types?|classes|groups?|statuses|brackets?|cohorts?)\b", re.I)
_GROUP_ID_COL_RE = re.compile(r"(^|_)(id|key|code|sk|pk)$|_id$|_key$|_code$", re.I)


def _breakdown_grain_hint(question: str, sql: str, dialect: str = "duckdb") -> str:
    """Catch a breakdown grouped at TOO FINE a grain: the question names a categorical
    dimension ('top product CATEGORIES', 'by brand') but the SQL GROUPs BY an id/key column
    (product_id) instead, so it ranks individual rows, not the category. High-precision: fires
    only when EVERY group-by column is id-like AND the question names a real dimension noun."""
    try:
        import sqlglot
        from sqlglot import exp
        tree = sqlglot.parse_one(sql, read=dialect)
        grp = tree.find(exp.Group)
        if not grp:
            return ""
        select_exprs = tree.expressions if isinstance(tree, exp.Select) else []
        gcols: list[str] = []
        for e in grp.expressions:
            if isinstance(e, exp.Column):
                gcols.append(e.name)
            elif isinstance(e, exp.Literal) and getattr(e, "is_int", False):
                idx = int(e.this) - 1
                if 0 <= idx < len(select_exprs):
                    gcols.append(select_exprs[idx].alias_or_name or "")
        gcols = [c for c in gcols if c]
        if not gcols or not all(_GROUP_ID_COL_RE.search(c) for c in gcols):
            return ""
        m = _DIM_NOUN_RE.search(question or "")
        if not m:
            return ""
        noun = m.group(0)
        return (
            f"BREAKDOWN GRAIN MISMATCH: the question asks for a breakdown by '{noun}', but the query "
            f"GROUPs BY an id/key column ({', '.join(gcols)}) — that ranks individual rows, not {noun}. "
            f"GROUP BY the '{noun}' categorical column instead (JOIN to its lookup table and group by the "
            f"name/label if the dimension lives there), and aggregate the metric within each {noun}."
        )
    except Exception:
        return ""


def _extract_tables(sql: str) -> list[str]:
    """Base tables referenced by `sql`, CTEs excluded. Uses the shared analyze()
    AST facade (correct on aliases/subqueries/schema-qualified names); falls back
    to a regex scan for inputs that don't parse as a single statement — some call
    sites pass several queries space-joined into one blob, which the parser rejects."""
    from aughor.sql.analyze import analyze
    facts = analyze(sql)
    if facts.ok and facts.tables:
        return sorted(facts.tables)
    # Regex fallback: multi-statement blobs (and anything else the parser can't read).
    cte_names = {m.group(1).lower() for m in _CTE_DEF_RE.finditer(sql)}
    seen: dict[str, None] = {}
    for m in _TABLE_RE.finditer(sql):
        t = m.group(1)
        if t.lower() not in seen and t.lower() not in cte_names:
            seen[t.lower()] = None
    return list(seen.keys())


_DIRECT_SIGNALS = re.compile(
    r'\b(show|list|what is|what are|what was|what were|how many|how much|'
    r'top \d|top\d|give me|fetch|get me|display|count|sum|total|average|avg|'
    r'breakdown|share of|distribution of|calculate|find|return)\b',
    re.IGNORECASE,
)
_INVESTIGATE_SIGNALS = re.compile(
    r'\b(why|cause|caused|causing|driver|drivers|reason|explain|diagnose|'
    r'investigate|what changed|what.s behind|contributing|anomaly|spike|drop|decline|surge)\b',
    re.IGNORECASE,
)


def _looks_direct(question: str) -> bool:
    if bool(_INVESTIGATE_SIGNALS.search(question)):
        return False
    return bool(_DIRECT_SIGNALS.search(question))


def _pb_serialize(entries) -> list[dict]:
    """Shape matched playbook entries for the `playbook_refs` SSE event so the UI
    can show them and offer keep / modify / remove."""
    out = []
    for e in entries or []:
        out.append({
            "id": e.id,
            "recommendation": e.recommendation,
            "trigger_condition": e.trigger_condition,
            "status": e.status,
            "tags": e.tags[:6],
            "historical_success_rate": e.historical_success_rate,
            "source_kb_id": e.source_kb_id,
        })
    return out


# Sentinel for _aiter_sync — see why a sentinel (not except StopIteration) below.
_AITER_DONE = object()


async def _aiter_sync(sync_iter):
    """Bridge a SYNC iterator (LangGraph's .stream()) into an async generator.

    Uses a sentinel rather than `except StopIteration`: `await run_in_executor(..., next, it)`
    marshals the iterator's terminal StopIteration through a Future, and asyncio REFUSES to
    set StopIteration on a Future ("StopIteration ... cannot be raised into a Future"),
    converting it to a TypeError that `except StopIteration` never catches. That TypeError
    leaked out at stream-end, so a cleanly-completed investigation was routed through the
    except/salvage path instead of clean post-loop finalization. `next(it, _AITER_DONE)`
    returns the sentinel on exhaustion, so the loop ends cleanly.
    """
    import contextvars
    loop = asyncio.get_running_loop()
    it = iter(sync_iter)
    # Carry the run's context (the metering RunMetrics + org) into every graph step. `run_in_executor`
    # does not propagate contextvars on its own, so without this a node's record_llm/record_query/
    # record_activation would miss the run's accumulator and the ADA Trust Receipt would show empty
    # cost/learning/activations. The progress variant already does this (via ctx.run for its sink).
    ctx = contextvars.copy_context()
    while True:
        item = await loop.run_in_executor(None, ctx.run, next, it, _AITER_DONE)
        if item is _AITER_DONE:
            break
        yield item


async def _aiter_sync_with_progress(sync_iter, progress_q, ctx):
    """`_aiter_sync` + a concurrent drain of the per-dimension progress queue (P2,
    `ada.progress_events`).

    Each graph node's ``next()`` runs inside ``ctx`` — the copied context that carries the progress
    sink — so a scan's worker threads (a ``ContextThreadPoolExecutor``, which copies ``ctx`` again)
    can push progress DURING the node instead of only when it returns as ``phase_complete``. Note that
    ``run_in_executor`` does NOT propagate contextvars on its own, which is exactly why the node is run
    via ``ctx.run`` rather than bare ``next``.

    Progress items are yielded wrapped as ``{"__ada_progress__": payload}`` (the router turns them into
    a ``phase_progress`` SSE event); graph node events pass through unchanged. Fail-safe: graph events
    are never dropped, and any progress still queued after the graph finishes is discarded (stale)."""
    loop = asyncio.get_running_loop()
    it = iter(sync_iter)
    next_graph = asyncio.ensure_future(loop.run_in_executor(None, ctx.run, next, it, _AITER_DONE))
    next_prog = asyncio.ensure_future(progress_q.get())
    try:
        while True:
            done, _pending = await asyncio.wait(
                {next_graph, next_prog}, return_when=asyncio.FIRST_COMPLETED)
            if next_prog in done:
                _p = next_prog.result()
                # Three payload types share the sink queue: a report-delta (R6) and a
                # guard receipt (A4) are self-tagged and pass through verbatim; a
                # phase-progress marker is wrapped.
                if isinstance(_p, dict) and ("__report_delta__" in _p or "__guard_receipt__" in _p):
                    yield _p
                else:
                    yield {"__ada_progress__": _p}
                next_prog = asyncio.ensure_future(progress_q.get())
            if next_graph in done:
                item = next_graph.result()
                if item is _AITER_DONE:
                    break
                yield item
                next_graph = asyncio.ensure_future(
                    loop.run_in_executor(None, ctx.run, next, it, _AITER_DONE))
    finally:
        next_prog.cancel()
        next_graph.cancel()


def _investigation_stream(graph_stream):
    """The deep-run event iterator: interleaves per-dimension ``phase_progress`` markers
    into the stream, so a scan node reports progress DURING execution and not only at
    ``phase_complete``."""
    import contextvars

    from aughor.agent.progress import set_progress_sink
    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue(maxsize=2000)
    ctx = contextvars.copy_context()
    ctx.run(set_progress_sink, loop, q)   # bind the sink INSIDE ctx so nodes run with it visible
    return _aiter_sync_with_progress(graph_stream, q, ctx)


def _stall_summary(merged: dict) -> str:
    """Build a human-readable terminal message when an investigation ends without
    a report.  Prefers the agent's own last verdict/finding, then falls back to a
    digest of the SQL errors that blocked it."""
    scores = merged.get("evidence_scores") or []
    if scores:
        last = scores[-1]
        finding = getattr(last, "key_finding", None) or (last.get("key_finding") if isinstance(last, dict) else None)
        if finding:
            return f"Investigation ended without a conclusive report. Last assessment: {str(finding)[:400]}"

    qh = merged.get("query_history") or []
    errs: list[str] = []
    for r in qh:
        e = getattr(r, "error", None) if not isinstance(r, dict) else r.get("error")
        if e and e not in errs:
            errs.append(str(e))
    total = len(qh)
    failed = len(errs)
    if errs:
        shown = "; ".join(errs[:3])
        return (
            f"Investigation could not complete: {failed} of {total} "
            f"{'query' if total == 1 else 'queries'} failed and no conclusive "
            f"answer could be formed. Errors: {shown[:500]}"
        )
    return (
        "Investigation ended without producing a report. No conclusive evidence "
        "was gathered — try rephrasing the question or narrowing the time range."
    )


def _try_salvage(merged: dict, inv_id: str, question: str, connection_id: str, schema: str = ""):
    """Best-effort terminal synthesis when the graph stops without a report.

    A SOTA investigation must never end with nothing: if ANY evidence was gathered
    (explore sub-answers or ADA phases), synthesise a best-effort report from it,
    persist it, and return the SSE string to emit. Returns ``None`` only when there
    is genuinely no evidence to salvage. Never raises."""
    try:
        merged.get("query_mode")
        qh = merged.get("query_history") or []

        # Explore: synthesise from whatever sub-questions completed.
        if merged.get("subq_answers"):
            from aughor.agent.explore import synthesize_exploration
            out = synthesize_exploration(merged)
            er = out.get("explore_report")
            if er:
                sq_raw = [sq.model_dump() for sq in merged.get("sub_questions", [])]
                sa_raw = [a.model_dump() for a in merged.get("subq_answers", [])]
                explore_save = {"_report_type": "explore", **er.model_dump(),
                                "sub_questions": sq_raw, "subq_answers": sa_raw,
                                "_partial": True}
                complete_investigation(inv_id, report=explore_save, hypotheses=[],
                                       query_history=qh, question=question,
                                       connection_id=connection_id, skip_index=False)
                return _sse("explore_report", {
                    "explore_report": er.model_dump(), "sub_questions": sq_raw,
                    "subq_answers": sa_raw, "query_count": len(qh),
                    "investigation_id": inv_id, "query_mode": "explore", "partial": True,
                })

        # ADA / investigate: synthesise from whatever phases completed.
        if merged.get("investigation_phases"):
            from aughor.agent.investigate import ada_synthesize
            out = ada_synthesize(merged)
            ada = out.get("answer_report")
            if ada:
                ada_save = (dict(ada) if isinstance(ada, dict) else ada.model_dump())
                ada_save["_report_type"] = "investigate"
                ada_save["_partial"] = True
                complete_investigation(inv_id, report=ada_save,
                                       hypotheses=merged.get("hypotheses", []),
                                       query_history=qh, question=question,
                                       connection_id=connection_id, skip_index=False)
                _write_answer_receipt(
                    kind="ada_report", natural_key=f"ada:{connection_id}:{inv_id}",
                    question=question, sqls=_ada_sqls(ada_save) or [r.sql for r in qh if getattr(r, "sql", None)],
                    headline=(ada_save.get("headline", "") if isinstance(ada_save, dict) else ""),
                    schema=schema, connection_id=connection_id,
                    payload_extra={"investigation_id": inv_id, "partial": True},
                )
                payload = ada_save if isinstance(ada, dict) else ada.model_dump()
                return _sse("answer_report", {
                    "answer_report": payload, "investigation_id": inv_id,
                    "query_mode": "investigate", "mode": "investigate", "partial": True,
                })
    except Exception:
        return None
    return None


def _ambiguity_probe_enabled() -> bool:
    """Whether the structural-ambiguity probe is opted in.

    Reads the current variable, then the retired one. `AUGHOR_SOMA_CLARIFY` named the
    SOMA-SQL paper the technique came from rather than what the probe does; it still works
    so an operator's existing .env does not silently stop opting in on the day we renamed
    it. Set `AUGHOR_AMBIGUITY_CLARIFY` going forward.
    """
    for var in ("AUGHOR_AMBIGUITY_CLARIFY", "AUGHOR_SOMA_CLARIFY"):
        raw = os.getenv(var)
        if raw is not None:
            return raw.strip().lower() in ("1", "true", "yes", "on")
    return False



async def salvage_orphaned_investigation(
    inv_id: str, connection_id: str, canvas_id: Optional[str], question: str,
) -> None:
    """Crash-recovery for an investigation orphaned by a process restart. Reads its
    LangGraph checkpoint (persisted SqliteSaver, keyed by inv_id) and runs the same
    proven `_try_salvage` the timeout/exception paths use — synthesising a partial
    report from whatever evidence (ADA phases / explore answers) was gathered before
    the crash. Recovery instead of sweep-to-failed; always reaches a terminal status
    (complete on salvage, failed when there's nothing to recover). Runs as a
    supervised kernel job, so it carries its own job.state lifecycle + heartbeat."""
    db = None
    try:
        from aughor.agent.graph import build_graph_generic
        from aughor.canvas.scope import resolve_execution_scope
        # One scope resolver — unlike the old inline block this ALSO pins the derived owning
        # schema of a table-list-scoped canvas (the salvage-path sibling-schema leak fix).
        db = resolve_execution_scope(connection_id, canvas_id).open()
        agent = build_graph_generic(db, hitl=False)
        config = {"configurable": {"thread_id": inv_id}}
        try:
            st = await asyncio.to_thread(lambda: agent.get_state(config))
            merged = dict(st.values) if st and getattr(st, "values", None) else {}
        except Exception:
            logger.debug("salvage: checkpoint read failed for %s", inv_id, exc_info=True)
            merged = {}
        salvaged = None
        if merged:
            salvaged = await asyncio.to_thread(_try_salvage, merged, inv_id, question, connection_id, "")
        if salvaged:
            logger.info("boot recovery: salvaged a partial report for orphaned investigation %s", inv_id)
        else:
            fail_investigation(inv_id, status="failed")
            logger.info("boot recovery: nothing to salvage for %s — marked failed", inv_id)
    except Exception:
        logger.warning("boot recovery: salvage crashed for %s", inv_id, exc_info=True)
        try:
            fail_investigation(inv_id, status="failed")
        except Exception:
            logger.debug("salvage fallback fail_investigation failed for %s", inv_id, exc_info=True)
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                logger.debug("salvage: db close failed for %s", inv_id, exc_info=True)


# ── Request models ────────────────────────────────────────────────────────────

class InvestigateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    question: str
    connection_id: str = BUILTIN_ID
    canvas_id: Optional[str] = None
    hitl: bool = False
    skip_cache: bool = False
    # Scope a non-canvas investigation to a specific schema (multi-schema
    # connections) — mirrors how a canvas scopes. None = whole connection.
    schema_name: Optional[str] = Field(default=None, alias="schema")
    # Seed context for "pull the thread" from a briefing: the originating finding
    # text (seed_context) and the exact query that produced it (seed_sql). ada_intake
    # already reads scan_context, so seeding is additive — no graph change.
    seed_sql: Optional[str] = None
    seed_context: str = ""
    # Drilling into a known briefing finding: its stored finding id. When set (and not
    # `deep`), the explorer's pre-computed Finding Dossier is served as the trace —
    # a deterministic ledger read, NOT a second ADA run. `deep` is the explicit
    # "Investigate deeper" escalation: run ADA, seeded with that dossier.
    insight_id: Optional[str] = None
    # `escalate` is the explicit "go deeper than the saved finding" flag. It is NOT the
    # `depth` knob — the two were both spelled `deep` on the same request, which is how
    # one word came to mean two things. Accepts the old name `deep` on the wire.
    escalate: bool = Field(default=False, alias="deep")
    # Recent conversation turns (question + SQL + result digest), so a follow-up in a
    # canvas composes on the previous query instead of starting cold — parity with the
    # quick /chat path. Same shape /chat + /ask accept.
    history: list[ChatHistoryTurn] = []
    # P4 pause posture — see AskRequest.allow_clarify.
    allow_clarify: bool = True


class FeedbackRequest(BaseModel):
    feedback: str
    # P3 plan gate: when resuming from a plan_pending pause, the indices of the
    # sub-questions the user chose to keep (drop the rest before the fan-out runs).
    # None = no plan edit (ordinary HITL resume).
    keep_subquestions: Optional[list[int]] = None
    # P4 clarify gate: when resuming from a clarify_pending pause, the LABEL of the metric
    # reading the user chose (matches one of the offered `options`). None = no clarify choice.
    clarify_choice: Optional[str] = None


class ChatHistoryTurn(BaseModel):
    question: str
    sql: str
    columns: list[str] = []
    headline: str = ""
    # A small sample of the prior result (top rows) so a follow-up can resolve
    # references — "that", "the top one", "those regions" — against real values (Phase 4).
    key_rows: list = []


class ChatRequest(BaseModel):
    question: str
    connection_id: str
    canvas_id: Optional[str] = None
    history: list[ChatHistoryTurn] = []
    session_id: str = ""


class AskRequest(BaseModel):
    """The unified entry (Phase 0 of the Insight+Deep merge, docs/UNIFIED_ANSWER_PATH.md).

    A superset of ChatRequest + the investigate pass-throughs. `depth` defaults to
    `auto` (the router decides); `quick`/`deep` are the auto+transparency re-run
    overrides. The legacy `deep`/`insight_id` flags keep the dossier-drill and
    "Investigate deeper" escalations working through the one door.
    """
    model_config = ConfigDict(populate_by_name=True)
    question: str
    connection_id: str = BUILTIN_ID
    canvas_id: Optional[str] = None
    history: list[ChatHistoryTurn] = []
    session_id: str = ""
    schema_name: Optional[str] = Field(default=None, alias="schema")
    depth: Literal["auto", "quick", "deep"] = "auto"
    # Answer AS this user-defined agent (flag `agents.user_defined`): its pinned
    # instructions lead the prompt, retrieval is scoped to its documents, and its
    # connection binding wins (a conflicting explicit connection is a 409).
    agent_id: Optional[str] = None
    # Set when the user answered (or dismissed) a clarifying question — bypass the
    # clarify gate so we don't ask again about the now-clarified request.
    skip_clarify: bool = False
    # P4 pause posture (replaces the deleted `deep_analysis.clarify_gate` flag,
    # 2026-08-06): may this run PAUSE to ask which metric reading was meant? A
    # headless consumer that cannot answer an interrupt passes False and gets a
    # complete (silently-chosen) report instead of a truncated run. The data
    # trigger (a material reading divergence) is unchanged — this only decides
    # whether the run may stop to ask a human.
    allow_clarify: bool = True
    # I4 — the reading the user chose when answering a clarify (the chip text / typed detail).
    # When present, it crystallizes into the Ambiguity Ledger (source=user) so the class never
    # re-ambiguates on this connection. `clarify_subject` is the original ambiguous question
    # (defaults to `question`); `clarify_source` is the clarify kind ("ambiguous_term" → a value
    # choice, else an interpretation choice).
    clarify_reading: str = ""
    clarify_subject: str = ""
    clarify_source: str = ""
    # R13 — a named research starter's declared path: "investigate" pins the deep
    # investigation, "explore" pins the landscape wave (both bypass the router's
    # classifier — deterministic, explicit per request). None = auto routing.
    mode: Optional[Literal["investigate", "explore"]] = None
    # R13/R10 seam — the starter's purpose tag; pure provenance (carried on the
    # route receipt so a starter run is legible as one).
    purpose: str = ""
    # Pass-throughs preserved from the investigate path. `escalate` accepts the old wire
    # name `deep`; it is the dossier-escalation flag, not the `depth` knob above.
    escalate: bool = Field(default=False, alias="deep")
    insight_id: Optional[str] = None
    seed_sql: Optional[str] = None
    seed_context: str = ""
    hitl: bool = False
    skip_cache: bool = False


class OutcomeRequest(BaseModel):
    rec_text: str
    status: str
    metric_name: Optional[str] = None
    metric_before: Optional[float] = None
    metric_after: Optional[float] = None


# Concentration / 80-20 intent — only the QUESTION carries this, so the chart
# selection has to read it here (the renderer never sees the question). Models
# inconsistently emit a share column or the literal "pareto" chart_type, so this
# makes the intent deterministic.
_CONCENTRATION_RE = re.compile(
    r"80[\s/_-]?20|pareto|concentrat|cumulative\s+share|long\s+tail|"
    r"(few|handful|top)\b.{0,40}\b(drive|account|make up|generate)\b.{0,20}\b(most|majority|bulk)",
    re.IGNORECASE,
)
_PARETO_BLOCK = {"line", "none", "heatmap", "scatter", "stacked_bar", "multi_line", "area"}
_ID_COL_RE = re.compile(r"(^|_)(id|key|sk|pk|code)$", re.IGNORECASE)


def _maybe_pareto(question: str, columns: list[str], rows: list, current: str) -> str:
    """Force a Pareto when the question asks about concentration/80-20 and the
    result is a single category(+id) ranking over a measure. The renderer
    computes the cumulative curve itself, so no share column is required."""
    if current in _PARETO_BLOCK:
        return current
    if not question or not _CONCENTRATION_RE.search(question):
        return current
    if not columns or len(rows) < 4:
        return current
    sample = rows[0]
    if not isinstance(sample, (list, tuple)):
        return current

    def _numlike(v: object) -> bool:
        # QueryResult stringifies every cell, so numbers arrive as strings.
        if isinstance(v, bool):
            return False
        if isinstance(v, (int, float)):
            return True
        if isinstance(v, str):
            s = v.strip().replace(",", "")
            if not s or s == "NULL":
                return False
            try:
                float(s)
                return True
            except ValueError:
                return False
        return False

    num_idx = [i for i, v in enumerate(sample) if _numlike(v)]
    cat_idx = [i for i in range(len(columns)) if i not in num_idx]
    # A ranking = at least one dimension + at least one measure. When the only
    # dimension is an id (numeric → counted above), still treat it as a ranking.
    if num_idx and cat_idx:
        return "pareto"
    if len(num_idx) >= 2 and any(_ID_COL_RE.search(c) for c in columns):
        return "pareto"
    return current


def _coerce_list_str(v: object) -> list[str]:
    """Coerce a value that should be list[str] but may arrive as a JSON-encoded
    string from local models (Ollama/qwen).  Handles:
      - already a list                  → items cast to str
      - '["a","b","c"]'                 → single JSON array string
      - '["a"]\\n["b"]'                 → one array per line (qwen quirk)
      - plain multi-line text           → each non-empty line becomes an item
    """
    if isinstance(v, list):
        return [str(item) for item in v]
    if not isinstance(v, str) or not v.strip():
        return []
    try:
        parsed = json.loads(v)
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    except (json.JSONDecodeError, ValueError):
        pass
    steps: list[str] = []
    for line in v.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed_line = json.loads(line)
            if isinstance(parsed_line, list):
                steps.extend(str(item) for item in parsed_line)
            else:
                steps.append(str(parsed_line))
        except (json.JSONDecodeError, ValueError):
            steps.append(line)
    return steps


class _ChatAnswer(BaseModel):
    sql: str
    headline: str
    chart_type: str = "auto"
    intent: str = ""         # "You want to see…" — plain-English restatement of the question
    approach: list[str] = [] # 3-5 concise steps describing how the answer is calculated
    # Chart config generated alongside SQL so the chart always matches the data
    chart_config: dict = Field(default_factory=dict, description=
        "Vega-Lite chart configuration: {type, x_field, y_field, color_field, title}. "
        "Empty dict if the result is not chartable.")

    @field_validator("approach", mode="before")
    @classmethod
    def coerce_approach(cls, v: object) -> list[str]:
        return _coerce_list_str(v)


class _FollowUpBase(BaseModel):
    """Shared model for all follow-up question responses.
    Guards against local models (Ollama/qwen) returning questions as a
    JSON-encoded string instead of a proper list."""
    questions: list[str] = []

    @field_validator("questions", mode="before")
    @classmethod
    def coerce_questions(cls, v: object) -> list[str]:
        return _coerce_list_str(v)


class _NarrativeResult(BaseModel):
    """The prose enrichment attached to a quick answer — anomaly detection, trend, comparison."""
    narrative: str = Field(default="", description="2-3 tight sentences that lead with the answer and wrap decisive numbers in **bold**.")
    anomalies: list[str] = Field(default_factory=list, description="List of detected anomalies or unexpected patterns.")
    trend: str = Field(default="stable", description="One of: up, down, stable, mixed.")
    confidence: str = Field(default="medium", description="One of: high, medium, low.")


class _PostAnswer(_NarrativeResult):
    """Combined post-answer enrichment: the narrative + follow-up questions
    in ONE narrator call (was two separate narrator round-trips per answer).
    Inherits the narrative fields; adds the follow-up list with the same coercion guard."""
    questions: list[str] = Field(default_factory=list, description="Exactly 3 concise follow-up data questions, max 12 words each.")

    @field_validator("questions", mode="before")
    @classmethod
    def coerce_questions(cls, v: object) -> list[str]:
        return _coerce_list_str(v)

class _ClarifyingQuestions(BaseModel):
    """Clarifying questions generated before a deep analysis to narrow scope."""
    questions: list[str] = Field(default_factory=list, description="1-2 concise clarifying questions (max 15 words each).")
    context_note: str = Field(default="", description="One sentence explaining why these questions matter.")
# ── Chat streaming ────────────────────────────────────────────────────────────

# ── Headline grounding ────────────────────────────────────────────────────────
# The coder emits a headline alongside the SQL BEFORE execution (a prediction), so it
# can name a leader/number the actual rows contradict ("AMERICA leading at $1.62B" when
# the data shows EUROPE at $45.8B). We validate the emitted headline against the real
# rows and replace it with a grounded one ONLY on a genuine contradiction.
_HL_NUM_RE = re.compile(r"-?\$?\s?([\d][\d,]*(?:\.\d+)?)\s*([bmk])?\b", re.I)
_LEADER_RE = re.compile(r"\b(lead|leads|leading|tops?|topping|highest|most|largest|biggest|#1)\b", re.I)
_MONEY_COL_RE = re.compile(r"revenue|sales|price|value|spend|cost|profit|margin|gmv|income|amount|aov", re.I)


def _hl_to_float(v):
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except Exception:
        return None


def _headline_numbers(text):
    return [n for n, _ in _headline_numbers_with_precision(text)]


def _headline_numbers_with_precision(text):
    """(value, decimals) per number in the prose — ``decimals`` is how many the headline
    itself shows (None when a magnitude suffix like 1.2M scales it, where the shown
    decimals no longer describe the value's precision)."""
    out = []
    for m in _HL_NUM_RE.finditer(text or ""):
        try:
            raw = m.group(1).replace(",", "")
            suffix = (m.group(2) or "").lower()
            val = float(raw) * {"b": 1e9, "m": 1e6, "k": 1e3}.get(suffix, 1.0)
            decimals = None if suffix else (len(raw.split(".")[1]) if "." in raw else 0)
            out.append((val, decimals))
        except Exception:
            pass
    return out


def _col_is_numeric(rows, idx):
    return any(idx < len(r) and _hl_to_float(r[idx]) is not None for r in rows[:8])


def _approx_in(x, pool, tol=0.02):
    return any((abs(x) < 1 if p == 0 else abs(x - p) / abs(p) <= tol) for p in pool)


def _humanize_col(col):
    return re.sub(r"_+", " ", str(col or "")).strip().title()


def _fmt_value(col, v):
    f = _hl_to_float(v)
    if f is None:
        return str(v)
    money = bool(_MONEY_COL_RE.search(str(col or "")))
    a = abs(f)
    if a >= 1e9:
        s = f"{f / 1e9:.2f}B"
    elif a >= 1e6:
        s = f"{f / 1e6:.2f}M"
    elif f == int(f):
        s = f"{int(f):,}"
    else:
        s = f"{f:,.2f}"
    return ("$" + s) if money else s


def _primary_num_idx(columns, rows):
    fallback = None
    for i, c in enumerate(columns):
        if not _col_is_numeric(rows, i):
            continue
        cl = str(c).lower()
        if re.search(r"(^|_)(id|key|sk|code|count|n)($|_)", cl) or re.search(r"pct|percent|share|_of_total", cl):
            fallback = i if fallback is None else fallback
            continue
        return i
    return fallback


def _ground_headline(headline, columns, rows):
    """Return the headline unchanged when it is consistent with the data; otherwise a
    grounded replacement built from the actual top row. Conservative: only fires on a
    clear contradiction (a sizable number matching nothing — not even a column sum/mean
    — or a superlative naming a non-leader entity)."""
    if not headline or not rows or not columns:
        return headline
    # pool of acceptable numbers: individual cell values (top rows) + each column's sum & mean
    pool = [f for r in rows[:8] for f in (_hl_to_float(v) for v in r) if f is not None]
    for ci in range(len(columns)):
        vals = [_hl_to_float(r[ci]) for r in rows if ci < len(r)]
        vals = [v for v in vals if v is not None]
        if vals:
            pool.append(sum(vals))
            pool.append(sum(vals) / len(vals))
    # A SINGLE-ROW result is one metric VALUE — the headline restates exactly that number,
    # so ground EVERY number, not just big ones. This catches a fabricated rate ("repeat
    # rate is 42.3%" when the only cell is 28.62) that the >=100 floor lets through. For a
    # multi-row breakdown keep the floor (small numbers there are structural: "top 10",
    # "across 5 types"). Match scale-tolerantly so a rate stored as a fraction (0.2862)
    # still grounds a "28.62%" claim; skip bare years (a 2025 isn't a data claim).
    scalar_like = len(rows) == 1
    floor = 0.0 if scalar_like else 100.0

    def _grounded(n, decimals=None):
        # A single-row result is one number the narrator RESTATES; the 2% band that
        # forgives "$1.2M" for 1,187,432 also forgave "3.99 days" for 3.96 (Superstore
        # 2026-08-14 — a wrong digit, not a rounding). For a scalar, hold the claim to
        # what the cell rounds to at the precision the headline itself shows: 3.96 →
        # "3.96" / "4.0" / "4" all ground; "3.99" does not. Scale variants (a fraction
        # stated as a percent) keep the same rule.
        if scalar_like and decimals is not None:
            cands = pool + [p * 100 for p in pool] + [p / 100 for p in pool if p]
            return any(round(p, decimals) == round(n, decimals) for p in cands)
        if _approx_in(n, pool):
            return True
        return scalar_like and (_approx_in(n, [p * 100 for p in pool])
                                or _approx_in(n, [p / 100 for p in pool if p]))

    unmatched = [n for n, d in _headline_numbers_with_precision(headline)
                 if abs(n) >= floor and not (2000 <= n <= 2099 and n == int(n))
                 and not _grounded(n, d)]
    cat_idx = next((i for i in range(len(columns)) if not _col_is_numeric(rows, i)), None)
    leader_bad = False
    if cat_idx is not None and _LEADER_RE.search(headline) and cat_idx < len(rows[0]):
        leader = str(rows[0][cat_idx])
        named = [str(r[cat_idx]) for r in rows[:8]
                 if cat_idx < len(r) and str(r[cat_idx]) and str(r[cat_idx]).lower() in headline.lower()]
        if named and leader.lower() not in headline.lower():
            leader_bad = True
    if not unmatched and not leader_bad:
        return headline
    num_idx = _primary_num_idx(columns, rows)
    if num_idx is None or num_idx >= len(rows[0]):
        return headline
    # Render a rate/percent metric with a trailing % (a fraction 0.x is shown as x%).
    _raw = _hl_to_float(rows[0][num_idx])
    if _raw is not None and re.search(r"rate|percent|pct|share|ratio|_of_total", str(columns[num_idx]).lower()):
        fval = f"{_raw * 100:.2f}%" if abs(_raw) <= 1 else f"{_raw:.2f}%"
    else:
        fval = _fmt_value(columns[num_idx], rows[0][num_idx])
    metric = _humanize_col(columns[num_idx])
    if cat_idx is not None and len(rows) > 1 and cat_idx < len(rows[0]):
        return f"{rows[0][cat_idx]} leads {metric.lower()} at {fval}"
    return f"{metric}: {fval}"


def _resolve_currency_symbol(connection_id: str, schema_name: Optional[str]) -> str:
    """Effective currency symbol for a connection+schema — override-wins over the inferred
    profile, falling back to USD '$'. The app/workspace override applies even when no profile
    is loaded, so an EUR org gets '€' regardless. Best-effort; returns '$' on any failure."""
    try:
        from aughor.business_profile import store as _pstore
        from aughor.orgsettings import resolve_currency
        from aughor.knowledge.triage import currency_symbol
        prof = _pstore.load(connection_id, schema_name)
        code = resolve_currency(getattr(prof, "currency_code", None) or "")
        return currency_symbol(code)
    except Exception:
        return "$"


def _apply_currency(text: str, sym: str) -> str:
    """Rewrite '$<number>' → the business currency symbol in prose (headline/narrative).
    No-op for USD. Mirrors the briefing's `_cur()` so chat ledes match the rest of the UI."""
    if not text or sym == "$":
        return text
    return re.sub(r"\$(?=\s?[\d.])", sym, text)


_TIME_COL_RE = re.compile(r"(month|date|day|week|quarter|year|period|timestamp|_ts$)", re.I)
_DATE_VAL_RE = re.compile(r"^\s*(?:19|20)\d{2}(?:[-/Q]\d{1,2}(?:[-/]\d{1,2})?)?\s*$")


def _is_time_series(columns, rows) -> bool:
    """True when the result's FIRST column is a time bucket (by name or value shape) and
    there are ≥3 rows — i.e. a trend the narrator should read recent-first."""
    if not columns or not rows or len(rows) < 3:
        return False
    if _TIME_COL_RE.search(str(columns[0])):
        return True
    vals = [str(r[0]) for r in rows[:5] if r]
    return bool(vals) and all(_DATE_VAL_RE.match(v) for v in vals)


def _narrator_sample(columns, rows, n: int = 20):
    """Rows to feed the post-answer narrator. For a long ASCENDING time series, weight the
    sample toward the MOST RECENT periods (the series start row kept for net-change framing)
    so the narrative leads with the current state — not year-one of a multi-year dataset
    (the Q15 'anchored on 2022' bug). Returns (sample_rows, is_time_series)."""
    if _is_time_series(columns, rows) and len(rows) > n:
        return [rows[0]] + rows[-(n - 1):], True
    return rows[:n], False


def _prior_turn_context(history) -> str:
    """The previous turn's question — the ground-first resolver mines it for entities a
    follow-up inherits (so "break that down by platform" keeps the earlier filter). Handles
    both the pydantic ChatHistoryTurn and a plain dict; empty when there is no prior turn."""
    for turn in reversed(history or []):
        q = getattr(turn, "question", None)
        if q is None and isinstance(turn, dict):
            q = turn.get("question")
        if isinstance(q, str) and q.strip():
            return q.strip()
    return ""


def _history_window() -> int:
    """Verbatim conversation-history window (turns rendered with SQL + sample rows).
    Env-tunable (``AUGHOR_CHAT_HISTORY_WINDOW``); 4 by default — up from the original
    hardcoded 3, still small because only recent turns carry resolvable references and
    each verbatim turn costs prompt budget."""
    import os as _os
    try:
        return int(_os.getenv("AUGHOR_CHAT_HISTORY_WINDOW", "4"))
    except ValueError:
        return 4


def resolve_history(history, session_id: str):
    """The effective conversation history for this turn (CI-1).

    Prefer what the CLIENT sent — it is the freshest view of the turns the user is
    looking at, and the store save races the next request. When the client sent none
    but a ``session_id`` is set, reconstruct from the store so memory belongs to the
    SESSION rather than to whichever client is holding it: a reload, another device, the
    MCP server, a scheduled task, any non-web caller then all see the same thread.
    Fail-open: reconstruction returns [] on any error, i.e. the exact pre-CI-1 behaviour
    (inject nothing)."""
    if history:
        return history
    if not session_id:
        return history
    try:
        from aughor.db.history import reconstruct_session_history
        return reconstruct_session_history(session_id)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "server-side history reconstruction is best-effort; the turn "
                      "proceeds with no injected memory (pre-CI-1 behaviour)",
                 counter="chat.history_reconstruct_failed")
        return history


def build_prior_answers_section(priors) -> str:
    """Render the "you have asked this before" block (CI-1b).

    Distinct from CONVERSATION HISTORY on purpose: those turns are THIS conversation and
    are context to compose on; these are the same question answered in an EARLIER
    session, and the only honest use of them is comparison. The instruction says exactly
    that — answer from today's data, then say whether it moved — because a prior headline
    restated as current is the staleness class this repo keeps paying for (a briefing
    citing a deleted table, a cached finding outliving its rows).

    Deliberately carries the headline and the date only, never the prior SQL: re-running
    an old query is the model's decision to make from today's schema, not something to
    copy."""
    priors = list(priors or [])
    if not priors:
        return ""
    lines = [
        "PREVIOUSLY ASKED — this same question was answered in an earlier session. "
        "Answer from TODAY's data first, then say plainly whether the picture is "
        "unchanged or what moved. Never restate a previous answer as if it were current, "
        "and never cite its numbers as this turn's evidence:",
    ]
    for p in priors:
        when = str(p.get("asked_at", ""))[:10] or "an earlier session"
        head = (p.get("headline") or "").strip() or "(no headline recorded)"
        value = (p.get("prior_result") or "").strip()
        # The VALUE is what makes this comparable. Most stored headlines are captions
        # ("Returns table row count"), so a block carrying only titles would ask for a
        # comparison it gave the model nothing to compare.
        lines.append(f"  • {when}: {head}" + (f" — answered: {value}" if value else ""))
    return "\n".join(lines) + "\n"


def resolve_prior_answers(question: str, connection_id: str, session_id: str):
    """Prior-session answers to this question, or []. Fail-open (CI-1b)."""
    try:
        from aughor.db.history import find_prior_answers
        return find_prior_answers(question, connection_id, exclude_session=session_id)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "cross-session recall is best-effort; the turn answers without it",
                 counter="chat.prior_answers_failed")
        return []


def build_history_section(history, *, followup: bool = False) -> str:
    """Render the conversation context injected into the chat SQL prompt.

    Carries each recent turn's question + SQL + columns + headline AND a small **result
    digest** (sample rows) so a follow-up can resolve references ("that", "the top one",
    "those regions") against real values — not just column names (Phase 4). When the new
    question is a detected follow-up, the header instructs the generator to **compose on
    the most recent query as the base** (keep its metric/filters/grain/window unless the
    ask changes them), which is what makes "now break that down by region" reliable.

    Duck-typed over ``ChatHistoryTurn`` so it is unit-testable with plain stand-ins.

    CI-1: the most recent ``window`` turns render verbatim (SQL + sample rows); anything
    older collapses to a single deterministic summary line naming those questions — no LLM
    call, so a long conversation keeps its thread without paying to summarize every turn.
    The verbatim window stays small because only the recent turns carry references worth
    resolving; the summary line is enough for the model to know a topic was already
    covered (the CI-0 "asked 52 times" case)."""
    if not history:
        return ""
    turns = list(history)
    window = max(1, _history_window())
    recent = turns[-window:]
    older = turns[:-window]
    if followup:
        header = (
            "CONVERSATION HISTORY — THIS LOOKS LIKE A FOLLOW-UP. Treat the MOST RECENT query "
            "below as the base: keep its metric, filters, grain, and time window unless the new "
            "question changes them, and resolve 'that' / 'those' / 'the top one' against its "
            "sample result. Do NOT start from scratch."
        )
    else:
        header = ("CONVERSATION HISTORY (use to resolve 'also', 'add', 'filter by', 'that', "
                  "'those', 'the top one', 'break down', 'compare to'):")
    lines = [header]
    if older:
        earlier = "; ".join(
            (getattr(t, "question", "") or "").strip()[:80] for t in older[-8:]
            if (getattr(t, "question", "") or "").strip())
        if earlier:
            lines.append(f"Earlier in this conversation ({len(older)} prior turn(s)): {earlier}")
    for i, t in enumerate(recent, 1):
        q = getattr(t, "question", "") or ""
        sql = getattr(t, "sql", "") or ""
        cols = getattr(t, "columns", None) or []
        head = getattr(t, "headline", "") or ""
        key_rows = getattr(t, "key_rows", None) or []
        lines.append(f"[Turn {i}] Q: {q!r}")
        if sql:
            lines.append(f"         SQL: {sql}")
        if cols:
            lines.append(f"         Columns: {', '.join(cols[:6])}")
        if head:
            lines.append(f"         Headline: {head}")
        if key_rows:
            preview = " ; ".join(
                " | ".join(str(c) for c in (row or [])[:6]) for row in key_rows[:3]
            )
            lines.append(f"         Result (sample): {preview}")
    return "\n".join(lines) + "\n"


def _execute_chat_sql(db, sql: str, *, label: str = "chat"):
    """Run a quick-path statement inside a tool span.

    The quick path calls ``db.execute`` directly rather than going through the
    guarded executor, which is why it emitted no spans at all — the SQL that
    actually ran was missing from the record, so a quick answer could not be
    reconstructed even once a trace existed. Spanning it here restores that
    without touching execution semantics (the span is a no-op when the obs flags
    are off).

    Called off the event loop by design: the sink's sqlite write then happens on a
    worker thread instead of blocking the stream. It used to get there through its
    own ``asyncio.to_thread``; now the whole of ``_answer_core`` is already on that
    thread, so this is a direct call and the property is inherited rather than
    re-established. Contextvars — trace id, span stack, identity — are copied at
    the one remaining hop, so the row still lands correlated.
    """
    from aughor import telemetry
    attrs: dict = {"sql": sql, "query_id": label}
    with telemetry.mlflow_tool_span("sql.execute", attrs):
        result = db.execute(label, sql)
        # Report what came back. The span re-reads its attributes on exit, so this
        # lands as the row's row_count — "the query ran" and "the query returned
        # nothing" are different facts and a zero-row answer is usually the
        # interesting one.
        attrs["row_count"] = getattr(result, "row_count", None)
        return result


@dataclass
class _AnswerCoreResult:
    """What a quick answer IS, once the frames are someone else's problem.

    The SSE frames are the ordered LOG of the turn; this is its terminal state.
    Both matter, and they carry different things: `emit` says what happened and
    when, this says what the answer came out as. A caller with a no-op emit —
    the converse `answer_question` tool — sees only this, which is why
    ``guard_receipts`` lives here as well as on the wire. Its sibling tool
    ``run_sql`` already returns ``guard_receipts`` and ``caveats`` in its dict and
    the converse system prompt tells the model to narrate exactly those; a core
    that only emitted them would make the richer tool the weaker one.

    Everything copied off ``_ChatAnswer`` is COPIED, never aliased: the caveat
    guards rewrite ``chart_type`` and merge into ``chart_config`` in place, so
    handing back the model object would hand back something still being mutated.
    """

    #: How the turn ended — one per `return` in the core, so a caller can tell a
    #: refusal ("abstained") from a failure ("query_failed") without parsing prose.
    #: DELIBERATE terminal states only: an unexpected infrastructure failure produces
    #: no result at all — the core RAISES, through the `finally` that closes the
    #: connection, and the caller owns the envelope (the SSE wrapper renders the
    #: terminal `error` frame; the converse tool loop records a failed step). Pinned
    #: by a bridge test; do not add a catch-all outcome without moving both callers.
    outcome: str
    error: str = ""

    # ── the answer ───────────────────────────────────────────────────────────
    #: The GROUNDED headline, after the currency pass — never `answer.headline`,
    #: which is the model's pre-execution prediction (what `headline_delta` types).
    headline: str = ""
    sql: str = ""
    columns: list = field(default_factory=list)
    rows: list = field(default_factory=list)          # untruncated; the wire caps at 10k
    row_count: Optional[int] = None

    # ── why it is trustworthy ────────────────────────────────────────────────
    guard_receipts: list[dict] = field(default_factory=list)
    receipt: dict = field(default_factory=dict)
    caveats: list[str] = field(default_factory=list)

    # ── copied out of _ChatAnswer ────────────────────────────────────────────
    chart_type: str = "auto"
    chart_config: dict = field(default_factory=dict)
    intent: str = ""
    approach: list[str] = field(default_factory=list)
    tables_used: list = field(default_factory=list)

    # ── path-specific ────────────────────────────────────────────────────────
    mode: str = ""                       # "final_text" on the two no-SQL paths only
    clarify: Optional[dict] = None
    escalate: Optional[dict] = None
    inv_id: str = ""
    receipt_id: str = ""
    trusted: list = field(default_factory=list)
    playbook_refs: list = field(default_factory=list)
    narrative: Optional[dict] = None
    followups: list[str] = field(default_factory=list)


#: Stream terminator, not an outcome. `_run_core`'s `finally` pushes it on BOTH the
#: return and the raise path; the consumer breaks on it and then awaits the future,
#: which is where success-vs-raise is actually decided.
_CORE_DONE = object()


def _answer_core_workers() -> int:
    """Pool size for `_ANSWER_CORE_POOL` — a deployment knob, read once at import."""
    try:
        return max(1, int(os.getenv("AUGHOR_ANSWER_CORE_WORKERS", "8")))
    except ValueError:
        return 8


#: The answer core's OWN bounded pool — never the loop's default executor.
#:
#: A core occupies its worker for the WHOLE turn, provider round-trips included — tens
#: of seconds — while the default executor (`api.py` sizes it min(32, cpu+4)) is shared
#: by every router's short `run_in_executor` hop (metrics, catalog, system, query,
#: actions). Parking turns there let a handful of concurrent questions head-of-line
#: block an unrelated millisecond hop for the length of a turn (measured with a
#: 1-worker probe: 3.4 s wait vs 0.66 s max before the split). A dedicated pool bounds
#: concurrent turns instead of starving neighbours: the (N+1)th question queues HERE,
#: visibly, rather than freezing unrelated endpoints invisibly.
#:
#: `ContextThreadPoolExecutor` rather than the stdlib one because it copies contextvars
#: per submitted task — the property `asyncio.to_thread` gave and an explicit-executor
#: `run_in_executor` does not — so the metering accumulator and job id reach the core
#: regardless of whether `api.py`'s lifespan ever installed the context DEFAULT
#: executor (tests, MCP, and any non-lifespan caller never run that install).
_ANSWER_CORE_POOL = ContextThreadPoolExecutor(
    max_workers=_answer_core_workers(), thread_name_prefix="answer-core")


class _CoreCancelled(BaseException):
    """The client went away; stop paying for the rest of the turn.

    A ``BaseException`` for the same reason ``BudgetExceeded`` is one (see
    ``_metered_stream``): the core is riddled with fail-open ``except Exception:
    tolerate(...)`` blocks, and an ``Exception``-derived cancellation would be
    swallowed by the nearest one and the core would sail on.
    """


def _answer_core(
    question: str,
    connection_id: str,
    history: list[ChatHistoryTurn],
    *,
    emit: Callable[[str, dict], None],
    cancelled: Callable[[], bool] = lambda: False,
    session_id: str = "",
    canvas_id: Optional[str] = None,
    skip_clarify: bool = False,
    purpose: str = "",
    schema_scope: Optional[str] = None,
    assumed_default: bool = False,
    persist_question: str = "",
) -> "_AnswerCoreResult":
    """Answer one question, synchronously, reporting progress through ``emit``.

    This is the whole quick-answer pipeline, and it is SYNC because it always was:
    every ``await`` it used to carry was an ``asyncio.to_thread`` around blocking
    work, offloaded so the event loop could keep streaming. The ``async def`` bought
    the streaming INTERFACE, not the computation — so the interface moved out to
    ``_stream_chat`` and the computation stayed here, where a plain function call
    can reach it. That is what lets the converse ``answer_question`` tool run the
    real answer path instead of a reimplementation of it.

    ``emit`` takes the same frame name and flat payload ``_sse`` does, so the
    wrapper's job is to re-encode that pair verbatim. Callers that want the answer
    without the narration pass a no-op and read the returned ``_AnswerCoreResult``.
    (Written without a call-shaped example on purpose: the frame-parity guard parses
    this file as text, and prose that looks like an emission site is read as one.)

    ``cancelled()`` is checked three ways: ``emit`` raises ``_CoreCancelled`` once the
    wrapper has set the flag, the two 250 ms poll ticks that straddle the coder and
    narrator round-trips check it, and ``_checkpoint()`` runs before each silent paid
    phase (the context gather, the resolver, the compiler, the ambiguity probe, the
    execute) — because the happy path emits NOTHING between opening the connection and
    the first headline delta, and a disconnect there used to buy the whole prelude.
    Nothing interrupts a blocking call mid-flight — there is no cancel primitive on any
    of these connections — so cancellation is cooperative and honest about its
    granularity: the turn stops at the next checkpoint, closes ``db`` on the way out,
    and emits no partial terminal frames.

    ``persist_question`` labels the saved history row when the question the PIPELINE
    ran is not the question the USER asked — which is exactly the converse case: the
    model rephrases, and a row filed under the rephrasing is a turn its owner cannot
    find again. It is a label only. Everything that decides the answer still reads
    ``question``, so an unset ``persist_question`` leaves every caller byte-identical.
    """
    #: Guard receipts go BOTH ways, through one helper, so the frame and the return
    #: value cannot drift apart: nine sites, one place that decides what a receipt is.
    receipts: list[dict] = []

    #: What the saved turn is FILED under. Defaults to the question that was answered.
    _persist_q = persist_question or question

    #: What the user has actually SEEN so far, recorded off the frames rather than
    #: gathered from locals at cancel time. The partial the user is looking at IS the
    #: frames — reading it anywhere else would be reconstructing a second version of it
    #: that can disagree. Only the answer-shaped frames are kept; progress chatter is
    #: not part of an answer. Consumed by the cancel handler at the bottom.
    _seen: dict = {}

    #: Whether this turn already wrote its own history row. The answer path keeps working
    #: after it emits `done` — narrative, insight and follow-ups are all post-answer — so a
    #: client that leaves during that tail cancels a turn that is, as far as the user is
    #: concerned, finished and saved. Without this the cancel handler wrote a SECOND row
    #: for it, and the conversation came back with the answer followed by a phantom
    #: interrupted copy of the same question. Caught by reloading mid-enrichment; no unit
    #: test would have posed it, because it only exists in the gap between `done` and the
    #: end of the function.
    _turn_persisted = False

    def _record(name: str, payload: dict) -> None:
        if name == "headline":
            _seen["headline"] = payload.get("headline") or _seen.get("headline") or ""
        elif name == "headline_delta":
            # Replace-semantics, same as the client: the last delta is the whole text.
            _seen["headline"] = payload.get("headline") or _seen.get("headline") or ""
        elif name == "sql":
            _seen["sql"] = payload.get("sql") or ""
        elif name == "columns":
            _seen["columns"] = list(payload.get("columns") or [])
        elif name == "rows":
            _seen["rows"] = list(payload.get("rows") or [])
        elif name == "chart_type":
            _seen["chart_type"] = payload.get("chart_type") or "auto"

    _emit_inner = emit

    def emit(name: str, payload: dict) -> None:   # noqa: F811 — deliberate rebind
        # Record BEFORE forwarding: `emit` is also a cancellation checkpoint (it raises
        # once the wrapper sets the flag), so recording after would drop the very frame
        # the user was looking at when they walked away.
        _record(name, payload)
        _emit_inner(name, payload)

    def _receipt(payload: dict) -> None:
        receipts.append(payload)
        emit("guard_receipt", payload)

    def _checkpoint() -> None:
        # Cooperative cancellation for the stretches that EMIT nothing. `emit` raises
        # once the wrapper sets the flag and both 250 ms poll loops check it too — but
        # the happy path's prelude (context gather, prompt assembly, resolution,
        # compilation, the ambiguity probe) is silent, so a client that disconnected
        # there used to keep paying: the whole context fan-out plus up to three provider
        # round-trips before the first drain tick noticed. Checked before each paid
        # phase; the raise unwinds through the `finally` below, so the connection is
        # closed at the checkpoint and no partial terminal frames are emitted.
        if cancelled():
            raise _CoreCancelled()

    # Resolve canvas scope so table names resolve correctly AND the model only
    # sees in-scope tables. Multi-dataset connections (local_upload) expose every
    # dataset and carry schema_name=None with a table-list scope, so the
    # schema_name override below constrains nothing — without an explicit table
    # filter a Bakehouse canvas can answer from the ecommerce schema.
    # One scope resolver (ExecutionScope): the declared schema drives the explicit
    # "DEFAULT SCHEMA"/"ALLOWED TABLES" prompt block, while eff_schema PINS search_path —
    # the declared schema, else the single owning schema derived from a schema-qualified
    # table list (missimi.orders → 'missimi'). Without the pin an unqualified `FROM orders`
    # leaks to a sibling schema's same-named table (missimi silently answering from netflix).
    from aughor.canvas.scope import resolve_execution_scope
    from aughor.tools.schema import build_canvas_schema_context
    # Parity with the Deep path: build the canvas schema FRESH (live information_schema),
    # never by filtering the conn-keyed cached string — a snapshot predating a new upload
    # silently DROPPED the missing tables (live incident: Insight declared "no sales
    # transaction table available" while reading its sibling from the same schema).
    # `schema_scope` pins a NON-canvas run to one schema, exactly as a canvas's declared schema
    # pins a canvas run. Omitting it was why a quick answer ignored the shared schema selector
    # (the deep path already forwarded it) — and why a user agent's schema_scope binding didn't
    # constrain a quick answer either.
    _es = resolve_execution_scope(connection_id, canvas_id, schema_scope=schema_scope,
                                  schema_context_builder=build_canvas_schema_context)
    connection_id = _es.connection_id                # canvas's primary connection wins
    canvas_scope_schema = _es.declared_schema        # raw declared → the prompt note
    canvas_scope_tables = list(_es.tables)
    canvas_scope_full = _es.is_full_schema
    canvas_scope_eff_schema = _es.eff_schema
    try:
        db = _es.open()
    except KeyError as e:
        # A KeyError from the scope resolver means the connection id does not exist —
        # a terminal state, not a hiccup. Classified explicitly because the generic
        # fallback says "retrying is usually safe", and re-asking a question against a
        # connection that is not there fails identically every time.
        emit("error", _error_event(e, reason="not_found"))
        return _AnswerCoreResult(outcome="not_found", error=str(e))
    except Exception as e:
        # The connection exists but would not open (server down, bad credentials in the
        # DSN, network). That one IS worth retrying, so it keeps the classifier's verdict.
        emit("error", _error_event(e, message=f"Could not connect: {e}"))
        return _AnswerCoreResult(outcome="connect_failed",
                                 error=f"Could not connect: {e}")

    # Terminal state the frames below also carry. Declared here, not at the emit
    # sites, so every one of the six early returns can hand back a fully-formed
    # result instead of a partially-bound one.
    _esc_event: Optional[dict] = None
    _tables_used: list = []
    _playbook_refs: list = []
    _receipt_id = ""
    _followups: list[str] = []
    _narrative_dict: Optional[dict] = None

    try:
        _checkpoint()   # the client can be gone before the turn starts paying
        # Effective currency symbol for prose: tables/charts already honour the org
        # currency, but the LLM authored ledes in '$'. Resolve once; applied to headline
        # + narrative below. INSIDE the try on purpose: this used to run between
        # `_es.open()` and the block whose `finally` closes `db`, so a raise here leaked
        # the connection (instrumented: opened=1 closed=0, on the pre-split tree too).
        # Everything that runs after the open belongs under the `finally` that owns it.
        _cur_sym = _resolve_currency_symbol(connection_id, canvas_scope_eff_schema)
        from aughor.agent.prompts import CHAT_PROMPT
        from aughor.llm.provider import get_provider
        # Shared grounding producers (Rec 5): the same block functions the
        # `GET /ask/context` receipt calls, so the receipt shows exactly what the
        # answer path was grounded on (no drift). dialect_rules_block() == the old
        # get_chat_rules_block() verbatim.
        from aughor.agent.grounding import dialect_rules_block

        rules_block = dialect_rules_block()

        from aughor.agent.followup import is_followup
        history_section = build_history_section(history, followup=is_followup(question))
        # CI-1b — cross-session recall. Appended to the same block so it reaches the
        # prompt without a new parameter through the core's already-long signature; the
        # section states its own register, so the two never read as one conversation.
        # A follow-up is skipped: "now break that down" is not a repeat of anything, and
        # matching it against a stored question would be noise at best.
        if not is_followup(question):
            history_section += build_prior_answers_section(
                resolve_prior_answers(question, connection_id, session_id))

        _schema_name = getattr(db, "_schema_name", None)
        schema_qualifier = (_schema_name or "main") if db.dialect == "duckdb" else (_schema_name or "public")

        # ── Context retrieval — independent, side-effect-free fetches run
        # CONCURRENTLY (none consumes another's output; results slot into fixed
        # prompt sections, so completion order is irrelevant). Cuts the prelude
        # wait from the sum of these calls to roughly the slowest single one.
        def _kb() -> str:
            from aughor.semantic.kb_retriever import retrieve_for_planning
            s = retrieve_for_planning(question, top_k=2) or ""
            return (s + "\n\n") if s else ""

        def _ckb() -> str:
            from aughor.semantic.connection_kb import retrieve_for_question as _r
            s = _r(question, connection_id)
            return (s + "\n\n") if s else ""

        def _sqlex() -> str:
            from aughor.tools.prior_analyses import search_sql_examples
            return search_sql_examples(question, connection_id) or ""

        def _expl() -> str:
            from aughor.explorer.store import render_exploration_annotations
            s = render_exploration_annotations(connection_id)
            return (s + "\n\n") if s else ""

        def _causal() -> str:
            from aughor.lifecycle.causal import build_causal_context_section
            s = build_causal_context_section(question, conn_id=connection_id)
            return (s + "\n") if s else ""

        def _docs() -> str:
            from aughor.knowledge.indexer import build_external_context_section
            s = build_external_context_section(question, top_k=2)
            return (s + "\n\n") if s else ""

        def _pb_match():
            from aughor.playbook.retriever import retrieve_for_metric_and_phases
            return retrieve_for_metric_and_phases([question], limit=4)

        def _safe(fn):
            try:
                return fn()
            except Exception:
                return ""

        def _safe_list(fn):
            try:
                return fn()
            except Exception:
                return []

        # A DEDICATED pool, not the default executor: the core itself already
        # occupies a default-executor worker, and eight producers submitted back
        # into the same bounded pool by enough concurrent turns is a classic
        # thread-pool deadlock (every worker waiting on work only that pool can
        # run). ContextThreadPoolExecutor is the codebase's idiom for this and
        # copies contextvars per worker, so the metering accumulator and job id
        # reach all eight — the property `asyncio.gather` had for free.
        # Only `_get_schema_cached` is unwrapped, so it is the only member that can
        # raise; reading its future FIRST reproduces gather's return_exceptions=False
        # behaviour at the same point. `with` then waits for the seven best-effort
        # fetches before propagating, where gather would abandon them — a deliberate
        # difference: they hold HTTP connections and the turn is dying anyway.
        # And it DECLARES itself (Wave R5): the prelude was concurrent before too, but as
        # an `asyncio.gather`, which the parallel-safety checkpoint cannot see. Writing it
        # as a thread pool without the label would have made a region that was merely
        # invisible into one that looks accounted for — so the ratchet in
        # `test_parallel_safety.py` is right to insist, and this is the honest label.
        from aughor.kernel.parallel_safety import fanout_region as _fanout_region
        with _fanout_region("ask.prelude_context"), ContextThreadPoolExecutor(
                max_workers=8, thread_name_prefix="ask-prelude") as _prelude:
            # WCH-12: the connection-scoped schema cache (300s TTL) — was bypassed
            # here, re-walking information_schema on EVERY chat. Cache miss still
            # introspects; hits within the window skip it.
            _f_schema = _prelude.submit(_get_schema_cached, connection_id, db)
            _f_ctx = [_prelude.submit(_safe, _fn)
                      for _fn in (_kb, _ckb, _sqlex, _expl, _causal, _docs)]
            _f_pb = _prelude.submit(_safe_list, _pb_match)
            schema = _f_schema.result()
            (kb_patterns_section, conn_kb_section, sql_examples_section,
             exploration_section, causal_section, document_section) = [
                _f.result() for _f in _f_ctx]
            pb_entries = _f_pb.result()
        _checkpoint()   # the gather is the prelude's longest silent stretch

        # Restrict the schema to the canvas's scoped tables. Table-list scopes on
        # multi-dataset connections have schema_name=None, so the schema_name
        # override doesn't constrain anything — filter explicitly, mirroring the
        # Deep Analysis path's build_canvas_schema_context. Falls back to the full
        # schema if filtering yields nothing.
        if canvas_scope_tables and not canvas_scope_full:
            if (_es.schema_context or "").strip():
                # Fresh canvas schema (live introspection — same source Deep uses).
                # Filtering the conn-keyed cached string instead silently dropped any
                # canvas table the stale snapshot didn't know about yet.
                schema = _es.schema_context
            else:
                try:
                    from aughor.tools.schema import get_schema_for_tables
                    _scoped = get_schema_for_tables(schema, canvas_scope_tables)
                    if _scoped and _scoped.strip():
                        schema = _scoped
                except Exception:
                    logger.warning("Canvas table-scope filter failed; using full schema", exc_info=True)

        # Governed-metric grounding — built AFTER schema (needs the column set to
        # filter connection-scoped metrics) and BEFORE schema-linking (grounds on the
        # full schema). Rec 5: the SAME producer the GET /ask/context receipt renders
        # (unified bindings + measure grain + feasibility gap), so the receipt shows
        # exactly what grounded this answer — no drift. Byte-identical to the prior
        # inline block; the "SAME resolver as Deep" property (unified_metric_grounding,
        # not the global build_metrics_block) is preserved inside the producer.
        from aughor.agent.grounding import (governed_metrics as _grounding_metrics,
                                            schema_slice as _grounding_schema_slice)
        metrics_section = _grounding_metrics(question, connection_id, db=db, schema=schema,
                                             eff_schema=canvas_scope_eff_schema)

        # Schema-linking pre-filter: narrow schema to relevant tables/columns for this
        # question (reduces hallucination 30-60%). Shared Rec 5 producer — falls back to
        # the full schema on failure, byte-identical to the prior inline try/except.
        _full_schema = schema  # keep the un-narrowed schema for FK-neighbour expansion
        schema = _grounding_schema_slice(question, connection_id, schema=schema)

        # Build structured Data Catalog from linked tables,
        # expanded with FK neighbours so bridge/output tables a multi-table
        # question needs only via a join are present.
        semantic_layer_section = ""
        try:
            from aughor.tools.data_catalog import build_data_catalog
            from aughor.tools.schema import parse_schema_tables, fk_neighbor_expand, temporal_dimension_tables
            from aughor.tools.schema_linker import rank_tables_for_context
            from aughor.llm.profile import profile_for as _pf_cat
            linked_tables = list(parse_schema_tables(schema).keys())
            if linked_tables:
                _cat_cap = _pf_cat("coder").context_table_cap
                # The date/time dimension is PINNED, not merely appended: a temporal
                # question never names it, so it scores zero and any relevance cut drops
                # it first — the exact table the expansion exists to keep.
                _pinned = [t for t in temporal_dimension_tables(_full_schema, linked_tables, question)
                           if t not in linked_tables]
                # Rank + cap BEFORE building the catalog. The linker returns the schema
                # untouched when nothing matched (recall safety), so an open-ended
                # question used to hand every table in the canvas to a builder that pays
                # 5 sample rows each.
                linked_tables = rank_tables_for_context(
                    question, _full_schema, linked_tables + _pinned,
                    cap=_cat_cap, connection_id=connection_id, pinned=_pinned)
                # FK completion keeps its own historical bound of 10 and deliberately does
                # NOT follow `_cat_cap`: on a capable model that is 24, which would let this
                # path fill a narrow linker result out to 24 tables — a widening that has
                # nothing to do with the fix above. This ranking change may only narrow.
                linked_tables = fk_neighbor_expand(_full_schema, linked_tables, cap=10)
                # M24c: verified semantic layer (segments + computed properties)
                # for the linked entities — only items validated against the live DB.
                try:
                    from aughor.ontology.store import load_latest_ontology
                    from aughor.ontology.semantic_block import render_semantic_layer
                    semantic_layer_section = render_semantic_layer(
                        load_latest_ontology(connection_id), linked_tables
                    )
                except Exception:
                    semantic_layer_section = ""
                data_catalog = build_data_catalog(db, linked_tables,
                                                  schema=canvas_scope_eff_schema or None)
                if data_catalog:
                    schema = data_catalog
        except Exception:
            logger.warning("Data Catalog build failed; using linked schema text", exc_info=True)

        # Hard cap on tables in context — profile-derived (A3): the linker output
        # is rank-ordered, so a first-N cut here keeps the top-N ranked tables.
        try:
            from aughor.llm.profile import profile_for
            from aughor.tools.data_catalog import enforce_context_cap
            schema = enforce_context_cap(schema, max_tables=profile_for("coder").context_table_cap)
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "table context cap is best-effort; answering from the uncapped schema context",
                     counter="chat.context_cap")

        # ── final_text path: definitional questions answered from KB ──
        definitional = re.search(
            r"^(what is|what are|what does|define|explain|meaning of)",
            question,
            re.IGNORECASE,
        )
        if definitional:
            try:
                # READER register, never the planning one: retrieve_for_planning is a
                # prompt-injection block ("RELEVANT SQL AND DOMAIN PATTERNS (apply when
                # writing queries): …") and this path's output IS the user's answer —
                # eleven stored turns carry that block verbatim as their headline
                # (CI-0 finding 4).
                from aughor.semantic.kb_retriever import has_strong_kb_match, retrieve_for_reader
                if has_strong_kb_match(question, threshold=0.75, top_k=3):
                    kb_answer = retrieve_for_reader(question, top_k=3) or ""
                    # Also pull connection KB — same register rule.
                    try:
                        from aughor.semantic.connection_kb import retrieve_for_reader as _ckb_fn
                        ckb = _ckb_fn(question, connection_id)
                        if ckb:
                            kb_answer = kb_answer + "\n\n" + ckb
                    except Exception as exc:
                        from aughor.kernel.errors import tolerate
                        tolerate(exc, "connection-KB enrichment of the definitional answer is best-effort; the global-KB answer still serves",
                                 counter="chat.kb_definitional")
                    if kb_answer.strip():
                        _answer_text = kb_answer.strip()
                        # Emit as `headline` — the only text channel the chat turn
                        # renders for a no-SQL answer (final_text/definitional path).
                        # The previous `answer` event had no frontend handler, so the
                        # turn rendered blank. `mode` tags it so it shows as a Quick turn.
                        emit("mode", {"query_mode": "final_text"})
                        emit("headline", {"headline": _answer_text})
                        emit("done", {})
                        try:
                            save_chat_turn(
                                question=_persist_q, connection_id=connection_id,
                                headline=_answer_text[:2000], sql="", session_id=session_id,
                                columns=[], rows=[], chart_type="none", tables_used=[],
                                intent="", approach=[],
                                canvas_id=canvas_id,
                            )
                        except Exception as exc:
                            from aughor.kernel.errors import tolerate
                            tolerate(exc, "definitional-answer turn save is best-effort; the answer was already streamed",
                                     counter="chat.turn_save")
                        return _AnswerCoreResult(
                            outcome="kb_definitional", mode="final_text",
                            headline=_answer_text, guard_receipts=receipts)
            except Exception as exc:
                from aughor.kernel.errors import tolerate
                tolerate(exc, "KB-grounded definitional fast-path is best-effort; falling through to the SQL answer path",
                         counter="chat.kb_definitional")

        # Inject schema-prefix note when canvas-scoped
        if canvas_scope_schema:
            schema = (
                f"DEFAULT SCHEMA: {canvas_scope_schema}\n"
                "CRITICAL: Every table reference in SQL MUST include this schema prefix "
                f"(e.g. {canvas_scope_schema}.table_name). Do NOT use bare table names.\n\n"
                + schema
            )
        elif canvas_scope_tables and not canvas_scope_full:
            # Table-list scope (multi-dataset connection, schema_name=None): name
            # the allowed universe so the model can't wander into another dataset.
            schema = (
                "ALLOWED TABLES — this canvas is scoped to ONLY these tables:\n"
                f"{chr(10).join('  - ' + t for t in canvas_scope_tables)}\n"
                "CRITICAL: Query ONLY these tables, using the exact schema prefixes shown. "
                "Do NOT reference any other schema or dataset.\n\n"
                + schema
            )

        prompt = CHAT_PROMPT.format(
            schema=schema,
            history_section=history_section,
            question=question,
            schema_qualifier=schema_qualifier,
            kb_patterns_section=kb_patterns_section,
            conn_kb_section=conn_kb_section,
            sql_examples_section=sql_examples_section,
            metrics_section=metrics_section,
            exploration_section=exploration_section,
            causal_section=causal_section,
            document_section=document_section,
        )
        if rules_block:
            prompt = rules_block + prompt
        # User-agent brief (flag `agents.user_defined`) — the active agent's pinned
        # instructions lead the prompt, rules_block-style. Empty (inert) when no
        # agent is active.
        from aughor.agent.grounding import agent_brief as _grounding_agent_brief
        _agent_brief = _grounding_agent_brief()  # == agent_brief_block() (shared Rec 5 producer)
        if _agent_brief:
            prompt = _agent_brief + prompt
        # Pack steering — the third and last consumer of the shared producer (explore and
        # the deep-analysis intake are the others). Sits beside the agent brief on purpose:
        # creating a custom agent can bind BOTH, and before this the brief arrived here
        # while the pack's grounded recipes did not — so an agent built around a domain
        # answered quick questions with none of that domain's definitions. Inert unless a
        # pack is active AND deployed on this connection, so the prompt is byte-identical.
        from aughor.agent.grounding import pack_brief as _grounding_pack
        _pack_sec = _grounding_pack(question, connection_id, canvas_scope_eff_schema or "")
        if _pack_sec:
            prompt = _pack_sec + prompt
        # "Ask this briefing" — ground the answer in the brief the user is LOOKING AT, read
        # server-side from the same `conn:schema` cache entry the Briefing rendered (never
        # posted up by the client, so it can't drift from what's on screen or be spoofed).
        # Best-effort and empty when no brief is cached: no context beats invented context.
        try:
            from aughor.knowledge.brief_context import brief_block_for_scope
            _brief_sec = brief_block_for_scope(connection_id, canvas_scope_schema, canvas_id)
            if _brief_sec:
                prompt = _brief_sec + "\n" + prompt
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "brief grounding is best-effort; answering without the brief",
                     counter="chat.brief_section")
        # Playbook context — when org playbook items match this question, give them
        # to the model AND surface them to the user (emitted below) so they can
        # keep / modify / remove them.
        if pb_entries:
            try:
                from aughor.playbook.retriever import build_playbook_prompt_section
                _pbsec = build_playbook_prompt_section(pb_entries)
                if _pbsec:
                    prompt = _pbsec + "\n" + prompt
            except Exception as exc:
                from aughor.kernel.errors import tolerate
                tolerate(exc, "playbook prompt enrichment is best-effort; answering without playbook context",
                         counter="chat.playbook_section")

        # M24c: verified semantic layer — segments (named WHERE filters) and
        # computed properties for the linked entities, all executed against the
        # live DB. Prepended below the trusted block so trusted patterns stay on top.
        if semantic_layer_section:
            prompt = semantic_layer_section + "\n\n" + prompt

        # Trusted query templates (authoritative, data-team-reviewed). When the
        # question matches a verified pattern, inject it at the top so the model
        # reuses its exact structure — fixes model-reasoning gaps (fan-out, grain)
        # that prompt rules can't. Surfaced to the user via `trusted` SSE below.
        _trusted_used = []
        try:
            from aughor.semantic.trusted_queries import retrieve_trusted, build_trusted_block
            _tmatches = retrieve_trusted(question, connection_id)
            _tblk = build_trusted_block(_tmatches)
            if _tblk:
                prompt = _tblk + "\n" + prompt
                _trusted_used = [{"question": tq.question, "note": tq.note, "score": sc}
                                 for tq, sc in _tmatches]
        except Exception:
            _trusted_used = []

        # P1 close-the-loop: alongside verified patterns, inject any past human
        # corrections (reject/correct verdicts) for this database so the model does
        # not repeat a mistake a reviewer already flagged. Flag-gated + empty when
        # nothing relevant matches, so the default path is byte-for-byte unchanged.
        try:
            from aughor.agent.grounding import correction_priors
            _cblk = correction_priors(question, connection_id)  # == build_corrections_section (shared Rec 5)
            if _cblk:
                prompt = _cblk + "\n" + prompt
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "human-corrections prompt section is best-effort; answering without correction priors",
                     counter="chat.corrections_section")

        # ── Ground-first resolution (flag `ask.resolve_first`) ────────────────
        # Decide ONCE, deterministically, whether this is answerable as asked —
        # BEFORE anything model-shaped runs. This sits ABOVE the semantic compiler
        # and the ambiguity probe deliberately: both spend an LLM call parsing/probing
        # the question, which is wasted work (cost + latency) when the verdict is
        # an honest abstention. Best-effort: a resolver failure leaves `_resolution`
        # None and the answer proceeds ungrounded rather than not at all.
        _checkpoint()   # before the resolver — the first of the prelude's paid calls
        _resolution = None
        try:
            from aughor.semantic.answer_resolution import resolve as _resolve_answer
            # Conversation-aware: a follow-up inherits the prior turn's entity/filter so a
            # mode switch or a "break that down" doesn't lose the earlier grounding. Empty
            # for a fresh question, which is what makes this single-turn-safe — the
            # follow-up test is the gate, not a flag.
            _prior_ctx = _prior_turn_context(history) if is_followup(question) else ""
            _resolution = _resolve_answer(question, schema=_full_schema, db=db,
                                          connection_id=connection_id,
                                          eff_schema=canvas_scope_eff_schema,
                                          prior_context=_prior_ctx)
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "ground-first resolution is best-effort; answering without it",
                     counter="chat.resolve")

        # Honest abstention: a clear filter entity isn't in the data → say so with
        # what IS present, instead of running an empty filter and narrating around
        # the emptiness (the "Mytheresa isn't a franchise here" case). But NEVER dead-end a
        # FOLLOW-UP when conversation-context is on — the entity/reference may be implicit from
        # the conversation, so let the history-aware generator answer instead of a terminal stop.
        _abstain_ok = not is_followup(question)
        if _resolution is not None and _resolution.feasibility == "not_answerable" and _abstain_ok:
            _abstain = _resolution.caveat
            emit("mode", {"query_mode": "final_text"})
            emit("headline", {"headline": _abstain})
            emit("done", {})
            try:
                save_chat_turn(
                    question=_persist_q, connection_id=connection_id, headline=_abstain[:2000],
                    sql="", session_id=session_id, columns=[], rows=[], chart_type="none",
                    tables_used=[], intent="", approach=[], canvas_id=canvas_id)
            except Exception as exc:
                from aughor.kernel.errors import tolerate
                tolerate(exc, "abstention turn save is best-effort; the message was already streamed",
                         counter="chat.resolve_abstain_save")
            _followups = [
                "What values are available to filter by?",
                "Show the same measure without that filter",
            ]
            emit("followups", {"questions": _followups})
            return _AnswerCoreResult(
                outcome="abstained", mode="final_text", headline=_abstain,
                followups=_followups, guard_receipts=receipts)

        # Semantic Compiler fast-path (backlog #11): for the safe analytical shapes
        # (scalar / timeseries / breakdown / ranking) assemble grounded SQL deterministically
        # from the verified ontology instead of free-form generation. The LLM still writes the
        # headline/chart/approach around it, but the executed SQL is the compiled one — which
        # can't hallucinate columns or fan out. Coverage-gated + fallback-safe (None → no-op).
        _checkpoint()   # before the compiler round-trip
        _compiled_sql = None
        _compiled_intent = None
        if os.getenv("AUGHOR_COMPILER", "1").strip().lower() in ("1", "true", "yes", "on"):
            try:
                from aughor.semantic.compiler import compile_question
                # Pass the schema we already fetched (_full_schema) so metric resolution
                # inside the compiler doesn't re-introspect it — ~16s per compile (profiled).
                # CRITICAL: scope the compiler to the canvas's schema. Without it, a missimi
                # canvas loaded the connection-wide (generic demo) ontology whose entities lack
                # missimi's real measures/dimensions — so the compiler resolved the WRONG column
                # (installments→total_amount, days_out_of_stock→COUNT, brand→category) and, because
                # the compiled SQL OVERRIDES the LLM's, served a confidently wrong answer.
                _cc = compile_question(question, connection_id, schema_name=canvas_scope_eff_schema,
                                       dialect=db.dialect, schema_text=_full_schema)
                if _cc:
                    _compiled_sql, _compiled_intent = _cc
                    prompt = ("GROUNDED REFERENCE QUERY (assembled from the verified semantic layer — "
                              "its table, columns and aggregate are correct and fan-out-safe). Use it as "
                              "your TRUSTED BASIS, but ADAPT it to fully answer the question: add any "
                              "filter (date range, status), computed condition (e.g. delivered_ts > "
                              "estimated_delivery), ratio / derived metric (e.g. revenue / spend), GROUP BY "
                              "dimension, or JOIN the question needs that it does not already include. If it "
                              "answers the question exactly as written, run it verbatim:\n"
                              f"{_compiled_sql}\n\n" + prompt)
            except Exception:
                _compiled_sql = None

        # Deterministic complexity assessment (cost-tiered routing, Part 2). We assess
        # every question and surface the tier on the Trust Receipt, but the user-facing
        # SQL answer deliberately stays on the frontier "coder" model: a deceptively
        # "simple" question can be grain-tricky (e.g. "items per order"), and Aughor's
        # proven combination is the frontier model + deterministic guards — routing the
        # answer to a cheaper model would just shift work onto the guards. The cost lever
        # is applied to the robust routing *decision* instead (classify_question). See
        # docs/NL2SQL_WINNING_FORMULA_2026.md.
        # Structural-ambiguity probe (3b) — execution-grounded. On a structural-suspect
        # question the cheap deterministic clarify left quiet (e.g. "top products" — by units or
        # revenue?), generate candidate readings, execute them on THIS connection, and ask only if
        # their results materially diverge (the labels become grounded chips). LLM machinery + N
        # executions, so it is opt-in (AUGHOR_AMBIGUITY_CLARIFY) and fail-open. Greenlit by the measurement
        # chain (evals/ambiguity_eval + evals/its_structural).
        _checkpoint()   # before the ambiguity probe (an LLM call plus N executions)
        if (not skip_clarify and _ambiguity_probe_enabled()):
            try:
                from aughor.agent.ambiguity_probe import (is_structural_suspect, generate_candidate_readings,
                                               assess_structural_ambiguity)
                if is_structural_suspect(question):
                    _cands = generate_candidate_readings(question, schema)
                    if len(_cands) >= 2:
                        def _probe_ex(_sql):
                            _r = db.execute("ambiguity_probe", _sql)
                            return (not _r.error, _r.rows or [], _r.error or "")
                        _sv = assess_structural_ambiguity(question, _cands, _probe_ex)
                        if _sv.ambiguous:
                            _clarify = _sv.to_event()
                            emit("clarify", _clarify)
                            emit("done", {})
                            return _AnswerCoreResult(outcome="clarify", clarify=_clarify,
                                                     guard_receipts=receipts)
            except Exception:
                logger.debug("ambiguity probe failed; proceeding to answer", exc_info=True)

        # Constrain generation with what the resolution settled (entity binding,
        # grain ceiling). The resolution itself ran ABOVE the compiler; the prepend
        # happens here — after every other prompt section — so the settled facts
        # stay the topmost block the generator sees.
        if _resolution is not None and _resolution.prompt_constraints:
            prompt = _resolution.prompt_constraints + "\n\n" + prompt

        from aughor.agent.complexity import assess_complexity
        _cx = assess_complexity(question)
        # Run the (blocking) LLM call in a worker thread so the event loop stays
        # free to serve other pages (catalog/inbox/home) while the query runs.
        # CK-0.2: token-stream the coder's `headline` field as it is written, filling the
        # otherwise-dead SQL-generation wait with the answer's headline typing in. The deltas
        # are the RAW (pre-grounding) headline; the terminal grounded `headline` event below is
        # authoritative and overwrites the stream (self-healing, mirroring the `narrative` stream).
        # Flag off = the exact pre-streaming blocking call, byte-identical.
        # Chart-grammar: the system prompt no longer offers the combo chart (one measure
        # per exhibit; the renderer's deterministic dual-axis gate is the only door).
        # The legacy vocabulary still exists for the benchmark and custom-agent quality
        # paths, which were never gated by this and keep `CHAT_SQL_SYSTEM`.
        from aughor.agent.prompts import chat_sql_system as _chat_sql_system
        _chat_system = _chat_sql_system(exhibit_grammar=True)
        import queue as _hq_mod
        import threading as _hthreading
        import time as _htime
        _hl_q = _hq_mod.Queue()
        _hl_result: dict = {}

        def _hl_worker() -> None:
            # complete_streaming falls back to blocking complete() on any streaming failure,
            # so "exc" only means BOTH paths failed — re-raised below, exactly as today.
            try:
                _hl_result["ans"] = get_provider("coder").complete_streaming(
                    system=_chat_system, user=prompt, response_model=_ChatAnswer,
                    text_field="headline", on_text=_hl_q.put,
                )
            except Exception as worker_exc:
                _hl_result["exc"] = worker_exc
            finally:
                _hl_q.put(None)   # sentinel: the stream is over

        _hl_thread = _hthreading.Thread(target=_hl_worker, daemon=True, name="headline-stream")
        _hl_thread.start()
        # Drain partials → SSE deltas, throttled (grew ≥6 chars or >120ms) — a headline is
        # short, so a tighter throttle than the narrative keeps it typing smoothly.
        _hl_last_len, _hl_last_ts = 0, _htime.monotonic()
        _HL_EMPTY = object()

        def _hl_poll():
            try:
                return _hl_q.get(True, 0.25)
            except _hq_mod.Empty:
                return _HL_EMPTY

        while True:
            _hitem = _hl_poll()
            if _hitem is _HL_EMPTY:
                # Cancellation checkpoint. This branch ticks every 250 ms for the
                # whole coder round-trip — one of the two longest un-emitting
                # stretches of the turn — so a client that left stops paying here
                # rather than at the next frame.
                if cancelled():
                    raise _CoreCancelled()
                continue
            if _hitem is None:
                break
            if not isinstance(_hitem, str):
                continue
            _hnow = _htime.monotonic()
            if len(_hitem) - _hl_last_len >= 6 or _hnow - _hl_last_ts > 0.120:
                _hl_last_len, _hl_last_ts = len(_hitem), _hnow
                emit("headline_delta", {"headline": _hitem})
        _hl_thread.join()
        if "exc" in _hl_result:
            raise _hl_result["exc"]
        answer: _ChatAnswer = _hl_result["ans"]

        final_sql = answer.sql
        # Trust-receipt provenance signals — recorded ONLY when a guard
        # demonstrably fires this turn (honest lineage, not aspirational).
        _rcpt = {"compiled": False, "defan": False, "grounded": False, "lint": False,
                 # Wave 3 / 2.3 — the user pressed "Answer anyway": the question was
                 # open to more than one reading and they asked for a best guess. That
                 # is an ASSUMPTION the answer rests on, and until now it was recorded
                 # nowhere — `guard:ambiguous_question` fires off re-derived complexity,
                 # not off the user's own decision to skip.
                 "assumed": bool(assumed_default)}
        # The semantic compiler offers a grounded reference query as a HINT in the prompt above;
        # it no longer OVERRIDES the LLM. Overriding served confidently-wrong answers whenever the
        # compiler could not faithfully express the question — a computed late-delivery condition, a
        # ratio like ROAS, a year filter, or a cross-entity join (brands⋈products): it compiled a
        # plausible-but-wrong shape and ran THAT instead of the LLM's correct SQL. We record the
        # receipt + emit the badge only when the LLM adopted the grounded query verbatim.
        if _compiled_sql:
            _norm = lambda s: " ".join((s or "").lower().split())
            if _norm(final_sql) == _norm(_compiled_sql):
                _rcpt["compiled"] = True
                emit("compiled", {
                    "intent_type": _compiled_intent.intent_type,
                    "entity": _compiled_intent.entity or _compiled_intent.table,
                    "measure": _compiled_intent.measure or _compiled_intent.metric,
                    "dimension": _compiled_intent.dimension,
                })

        # ── Semantic column alignment — deterministic pre-execution check ─────
        # Catches wrong entity column (e.g. product_id used for seller analysis)
        # and injects a fix hint into SqlWriter if a rewrite is needed.
        _semantic_fix_hint = ""
        try:
            from aughor.tools.semantic_validator import check_entity_column_alignment
            _sem_warnings = check_entity_column_alignment(question, final_sql, schema)
            if _sem_warnings:
                _semantic_fix_hint = " | ".join(w.to_prompt_text() for w in _sem_warnings)
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "entity-column alignment pre-check is best-effort; executing the SQL without the hint",
                     counter="chat.semantic_alignment")

        # ── Fan-out detection (M24d) — multi-fact join amplification ───────────
        # Conservative, zero-false-positive detector (validated on 121 official
        # TPC-H/TPC-DS queries). When ≥2 satellites of a shared hub are aggregated
        # across a direct join, the totals over-count; the hint drives a directed
        # pre-aggregate rewrite below (adopted only if it re-executes cleanly).
        _fanout_fix_hint = ""
        try:
            from aughor.sql.fanout import detect_fanout, defan, dimension_ratio_chasm
            from aughor.tools.schema import parse_schema_tables as _pst
            _pst_cols = _pst(_full_schema)
            _ff = detect_fanout(final_sql, _pst_cols, dialect=db.dialect) or \
                dimension_ratio_chasm(final_sql, _pst_cols, dialect=db.dialect)
            if _ff:
                # Deterministic de-fan FIRST (the LLM-rewrite path is only ~20%
                # reliable on a known fan-out — it returns plausible CTEs that still
                # double-count). The DISTINCT-dedup (parent_fanout) and per-satellite
                # pre-aggregate (chasm) rewrites are exact + filter-preserving (TPC-H
                # verified). Adopt only if it dry-runs clean; else fall back to the hint.
                _rw = defan(final_sql, _ff, dialect=db.dialect)
                _adopted = False
                if _rw and _rw.strip() != final_sql.strip():
                    _dry_ok, _ = db.dry_run(_rw)
                    if _dry_ok:
                        _before_sql = final_sql
                        final_sql = _rw
                        _adopted = True
                        _rcpt["defan"] = True
                        emit("sql", {"sql": final_sql})
                        emit("fanout", {"hub": _ff.hub_root, "satellites": _ff.satellites, "corrected": True})
                        _receipt({
                            "guard": "fanout_defan", "action": "rewrote_sql",
                            "detail": (f"join fans out {_ff.hub_root} across "
                                       f"{', '.join(_ff.satellites or [])} - replaced with the "
                                       "exact pre-aggregated rewrite"),
                            "before": _before_sql[:2000], "after": final_sql[:2000]})
                if not _adopted:
                    _fanout_fix_hint = _ff.to_prompt_text()
                    emit("fanout", {"hub": _ff.hub_root, "satellites": _ff.satellites})
                    _receipt({
                        "guard": "fanout_defan", "action": "hinted",
                        "detail": ("fan-out detected but no provable rewrite exists; the "
                                   "repair hint goes back to the model instead")})
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "fan-out detection/de-fan guard is best-effort; executing the original SQL",
                     counter="chat.fanout_guard")

        # ── Lint before execution — catch known anti-patterns in code, not prompts ──
        from aughor.sql.lint import lint as _lint_sql, error_hint as _lint_hint, has_errors as _lint_has_errors
        from aughor.sql.writer import SqlWriter
        _lint_issues = _lint_sql(final_sql, dialect=db.dialect)
        # Entity-count grain (2026-08-14): "how many orders" answered by COUNT(*) on a
        # line-item table counts the wrong thing (Superstore: 806 vs 406). Deterministic,
        # precision-first (aughor/sql/grain_intent.py); rides the SAME repair round as
        # lint so it costs no extra call and its before/after lands on the receipt.
        try:
            from aughor.sql.grain_intent import count_star_over_finer_grain as _csfg
            from aughor.sql.lint import LintIssue as _LintIssue
            from aughor.tools.schema import parse_schema_tables as _pst_grain
            _cols_in_scope = [c for cols in _pst_grain(_full_schema).values() for c in cols]
            _grain_dx = _csfg(question, final_sql, _cols_in_scope)
            if _grain_dx:
                _lint_issues = list(_lint_issues) + [_LintIssue(
                    severity="error", rule="count_star_entity_grain",
                    message=_grain_dx, hint=_grain_dx)]
                _receipt({"guard": "count_star_entity_grain", "action": "hinted",
                          "detail": _grain_dx[:400]})
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "entity-count grain check is best-effort; the SQL runs as written",
                     counter="chat.entity_grain")
        if _lint_has_errors(_lint_issues):
            try:
                _writer = SqlWriter(db, schema_str=schema)
                # A4 - the repair round sees what the guards already did, so a fix
                # cannot undo an adopted de-fan without knowing it existed.
                _lint_hint_txt = _lint_hint(_lint_issues)
                if _rcpt.get("defan"):
                    _lint_hint_txt += (
                        "\nGUARD ALREADY APPLIED: the SQL was de-fanned (pre-aggregated "
                        "to avoid join over-counting) - preserve that structure in your fix.")
                _before_lint = final_sql
                _lint_fix = _writer.fix(
                    final_sql,
                    "SQL quality issues detected before execution",
                    hint=_lint_hint_txt,
                    max_retries=1,
                )
                if _lint_fix.ok:
                    final_sql = _lint_fix.sql
                    _rcpt["lint"] = True
                    _receipt({
                        "guard": "sql_lint", "action": "rewrote_sql",
                        "detail": "; ".join(i.message for i in _lint_issues[:3])[:400],
                        "before": _before_lint[:2000], "after": final_sql[:2000]})
            except Exception as exc:
                from aughor.kernel.errors import tolerate
                tolerate(exc, "lint auto-fix is non-fatal; proceeding with the original SQL",
                         counter="chat.lint_fix")

        # ── Scope guard — block cross-schema leakage on a scoped canvas ──────────
        # search_path pins BARE names to the canvas schema, but an EXPLICITLY
        # qualified reference to a sibling schema (e.g. `netflix.orders` for a missimi
        # canvas) bypasses search_path and would silently answer from the wrong
        # dataset. Detect any out-of-scope schema reference and force a repair.
        _scope_fix_hint = ""
        if canvas_scope_eff_schema and final_sql:
            try:
                from aughor.sql.tables import extract_tables
                _allowed = canvas_scope_eff_schema.strip().lower()
                # CTE-safe extraction: a sibling-schema ref hidden inside a CTE body
                # (WITH x AS (SELECT * FROM netflix.orders) ...) is still surfaced,
                # while CTE aliases (no schema) never false-trigger.
                _oos = sorted({
                    f"{_r.schema}.{_r.table}"
                    for _r in extract_tables(final_sql, db.dialect)
                    if _r.schema and _r.schema.strip().lower()
                    not in (_allowed, "information_schema", "pg_catalog", "system")
                })
                if _oos:
                    _scope_fix_hint = (
                        f"OUT-OF-SCOPE TABLES {_oos}: this question is scoped to the "
                        f"'{canvas_scope_eff_schema}' schema ONLY. Rewrite using exclusively "
                        f"{canvas_scope_eff_schema}.* tables — never reference another schema."
                    )
            except Exception as _e:
                logger.debug("chat scope guard is best-effort; skipped: %s", _e)

        # ── Filter value-domain guard — catch a guessed enum value ──────────────
        # `order_status = 'cancelled'` when the data holds 'canceled' runs clean but
        # silently matches ZERO rows, so every rate reads 0%. Probe the column's real
        # domain and force a repair when an enumerable value is a near-miss typo.
        _filter_fix_hint = ""
        if final_sql:
            try:
                from aughor.sql.join_guard import check_filter_value_domains
                _fw = check_filter_value_domains(db, final_sql)
                if _fw:
                    _filter_fix_hint = " | ".join(w.to_prompt_text() for w in _fw)
            except Exception as _e:
                logger.debug("chat filter value-domain guard is best-effort; skipped: %s", _e)

        # ── Breakdown-grain guard — "top product CATEGORIES" grouped by product_id ──
        # The model sometimes groups a categorical breakdown at too fine a grain (an id),
        # ranking individual rows instead of the named dimension. Repair toward the dimension.
        _grain_fix_hint = ""
        if final_sql:
            try:
                _grain_fix_hint = _breakdown_grain_hint(question, final_sql, db.dialect)
            except Exception as _e:
                logger.debug("chat breakdown-grain guard is best-effort; skipped: %s", _e)

        # ── id-arithmetic guard — a measure multiplied by a key fabricates a magnitude ──
        # `SUM(unit_price * order_item_id)` for "revenue" multiplies price by the row's
        # PRIMARY KEY (the €150M scar when order_items has no quantity column); it runs clean
        # and over-counts silently. Force a repair toward aggregating the measure alone.
        _idmath_fix_hint = ""
        if final_sql:
            try:
                from aughor.sql.fanout import measure_times_key_arithmetic
                _idmath_fix_hint = measure_times_key_arithmetic(final_sql, dialect=db.dialect) or ""
            except Exception as _e:
                logger.debug("chat id-arithmetic guard is best-effort; skipped: %s", _e)

        # ── ratio-of-sums guard — AVG(a/b) is the wrong recipe for a group-level rate ──
        # Averaging per-row ratios over-weights small-denominator rows (the freight-%
        # 1.48%-vs-2.17% scar). Force a repair toward SUM(a)/NULLIF(SUM(b),0).
        _ratio_fix_hint = ""
        if final_sql:
            try:
                from aughor.sql.fanout import avg_of_row_ratios
                _ratio_fix_hint = avg_of_row_ratios(final_sql, dialect=db.dialect) or ""
            except Exception as _e:
                logger.debug("chat ratio-of-sums guard is best-effort; skipped: %s", _e)

        # R6 (mode cross-pollination) — Insight had parent-fanout + dimension-ratio-chasm, but ADA's
        # Verifier also runs the three aggregate-over-chasm detectors (the "SUM(inventory) after
        # joining 2.4M line-items, inflating ~1000x" class) that Insight could miss. Run the full
        # Verifier battery for parity and feed any hit into the same repair path. Best-effort.
        _chasm_fix_hint = ""
        if final_sql:
            try:
                from aughor.agent.verifier import Verifier as _Verifier
                from aughor.tools.schema import parse_schema_tables as _pst_chasm
                _vhits = _Verifier.scan([final_sql], _pst_chasm(schema), db.dialect)
                if _vhits:
                    _chasm_fix_hint = " | ".join(_vhits)
            except Exception as _e:
                logger.debug("chat chasm battery is best-effort; skipped: %s", _e)

        # R1/R2 (mode cross-pollination) — VALIDATE-THEN-EXECUTE via the SHARED safety pipeline.
        # Insight used to execute-then-repair, so a hallucinated column reached the result path as a
        # raw binder error before any repair ran. preflight_repair runs the one chain all modes share
        # (identifier repair -> dry-run -> deterministic candidate substitution -> typed LLM fix)
        # BEFORE the user-facing execute, so there is no failed first attempt visible to the user.
        if final_sql:
            try:
                from aughor.sql.safety import preflight_repair
                final_sql, _pf_receipt = preflight_repair(db, final_sql, schema)
            except Exception as _e:
                logger.debug("chat pre-flight validation is best-effort; skipped: %s", _e)

        # R7 — the grounded-literal contract: a value entity resolution BOUND (verified
        # present in the data) must reach the SQL verbatim; a re-spelled drift of the
        # SAME entity is repaired deterministically, dry-run-vetted. Self-gating —
        # `_resolution` exists only when ask.resolve_first ran. Fail-open.
        if final_sql and _resolution is not None and _resolution.entity_bindings:
            try:
                from aughor.sql.grounded_literals import enforce_grounded_literals
                final_sql, _gl_repairs = enforce_grounded_literals(
                    final_sql, _resolution.entity_bindings,
                    getattr(db, "dialect", "duckdb"), db.dry_run,
                )
                if _gl_repairs:
                    from aughor.stats import stats as _gl_stats
                    _gl_stats.inc("grounded_literal_repairs")
                    logger.info("grounded-literal contract repaired %d literal(s): %s",
                                len(_gl_repairs), _gl_repairs)
            except Exception as _gl_exc:
                logger.debug("grounded-literal enforcement skipped: %s", _gl_exc)

        _checkpoint()   # before the user-facing execute — the query is not free either
        emit("sql", {"sql": final_sql})
        result = _execute_chat_sql(db, final_sql)

        from aughor.agent.investigate import _zero_row_suspicious
        _chat_zero_diag = None
        if not result.error and result.row_count == 0:
            _chat_zero_diag = _zero_row_suspicious(final_sql)

        # Also trigger a rewrite when semantic column warnings exist, even if
        # the SQL executed successfully (wrong columns produce wrong results silently).
        if result.error or _chat_zero_diag or _semantic_fix_hint or _fanout_fix_hint or _scope_fix_hint or _filter_fix_hint or _grain_fix_hint or _idmath_fix_hint or _ratio_fix_hint or _chasm_fix_hint:
            _writer2 = SqlWriter(db, schema_str=schema)
            _fix_error = (
                result.error or
                (_scope_fix_hint if _scope_fix_hint else None) or
                (_filter_fix_hint if _filter_fix_hint else None) or
                (_grain_fix_hint if _grain_fix_hint else None) or
                (_idmath_fix_hint if _idmath_fix_hint else None) or
                (_ratio_fix_hint if _ratio_fix_hint else None) or
                (_semantic_fix_hint if _semantic_fix_hint else None) or
                (_fanout_fix_hint if _fanout_fix_hint else None) or
                "Query returned 0 rows — the SQL logic is likely wrong."
            )
            _combined_hint = " | ".join(filter(None, [_chat_zero_diag or "", _scope_fix_hint, _filter_fix_hint, _grain_fix_hint, _idmath_fix_hint, _ratio_fix_hint, _semantic_fix_hint, _fanout_fix_hint, _chasm_fix_hint]))
            try:
                fix = _writer2.fix(final_sql, _fix_error, hint=_combined_hint, max_retries=2)
                if fix.ok:
                    retry = _execute_chat_sql(db, fix.sql)
                    if not retry.error and (retry.row_count > 0 or not _chat_zero_diag or _semantic_fix_hint or _fanout_fix_hint or _scope_fix_hint or _filter_fix_hint or _grain_fix_hint or _idmath_fix_hint or _ratio_fix_hint):
                        final_sql = fix.sql
                        result = retry
                        emit("sql", {"sql": final_sql})
            except Exception as exc:
                from aughor.kernel.errors import tolerate
                tolerate(exc, "post-execution SQL repair is best-effort; serving the original result/error",
                         counter="chat.sql_repair")

        if result.error:
            from aughor.agent.escalate import assess_escalation
            _esc = assess_escalation(question, columns=result.columns, rows=result.rows, error=result.error)
            _esc_event = _esc.to_event() if _esc.should_offer else None
            if _esc_event is not None:
                emit("escalate", _esc_event)
            emit("error", _error_event(message=result.error, reason="query_failed"))
            return _AnswerCoreResult(
                outcome="query_failed", error=result.error, sql=final_sql,
                columns=list(result.columns or []), rows=list(result.rows or []),
                row_count=result.row_count, guard_receipts=receipts,
                receipt=dict(_rcpt), caveats=list(result.caveats or []),
                escalate=_esc_event, intent=answer.intent,
                approach=list(answer.approach or []),
                trusted=list(_trusted_used or []))

        # Ground the headline in the ACTUAL rows — the coder's headline is a pre-execution
        # prediction and can contradict the data it ran on.
        _grounded_headline = _ground_headline(answer.headline, result.columns, result.rows)
        _rcpt["grounded"] = (_grounded_headline or "") != (answer.headline or "")
        if _rcpt["grounded"]:
            _receipt({
                "guard": "headline_grounding", "action": "rewrote_headline",
                "detail": ("the model's headline was a pre-execution prediction; it was "
                           "re-grounded in the rows the query actually returned"),
                "before": (answer.headline or "")[:2000],
                "after": (_grounded_headline or "")[:2000]})
        # Narration-inversion caveat: a per-group value stated as UNIVERSAL ("all
        # orders have 3 items") over a varying result. We can't drop a user's answer,
        # so qualify it inline instead of asserting a falsehood. High-precision, so
        # this fires rarely; non-destructive (the claim stays, only gets a caveat).
        from aughor.agent.verify import inverted_universal_claim
        if inverted_universal_claim(_grounded_headline, result.rows):
            _grounded_headline = (
                f"{(_grounded_headline or '').rstrip('. ')} — note: this value varies "
                "across the data and is not uniform across every row."
            )
            _rcpt["narration_inversion"] = True
            logger.info("[chat] narration-inversion caveat applied to headline")
            _receipt({
                "guard": "narration_inversion", "action": "caveated_headline",
                "detail": ("a per-group value was stated as universal over a varying "
                           "result; the claim now carries its qualification")})
        # Measure-grain caveat (backstop to the prevention block): if the executed SQL
        # summed a measure at the WRONG grain (per-unit without ×quantity, or per-line
        # ×quantity), flag the number instead of asserting it. Data-detected + cached.
        from aughor.semantic.measure_grain import connection_measure_grains, measure_grain_misuse
        from aughor.tools.schema import parse_schema_tables as _parse_tc
        _mg, _qc = connection_measure_grains(connection_id, db, _parse_tc(_full_schema))
        if _mg and final_sql and measure_grain_misuse(final_sql, _mg, _qc, dialect=db.dialect):
            _grounded_headline = (
                f"{(_grounded_headline or '').rstrip('. ')} — caution: a measure may be "
                "summed at the wrong grain (per-unit vs per-line); verify the total."
            )
            _rcpt["measure_grain"] = True
            logger.info("[chat] measure-grain caveat applied to headline")
            _receipt({
                "guard": "measure_grain", "action": "caveated_headline",
                "detail": ("a measure may be summed at the wrong grain "
                           "(per-unit vs per-line); the total carries a caution")})
        # id-arithmetic backstop: if the repair couldn't eliminate a measure×key product
        # (or a SUM/AVG over an id), the number is fabricated — caveat it instead of asserting.
        try:
            from aughor.sql.fanout import measure_times_key_arithmetic as _idmath
            if final_sql and _idmath(final_sql, dialect=db.dialect):
                _grounded_headline = (
                    f"{(_grounded_headline or '').rstrip('. ')} — caution: this total multiplies a "
                    "measure by an id/key column, so the magnitude is not trustworthy."
                )
                _rcpt["id_arithmetic"] = True
                logger.info("[chat] id-arithmetic caveat applied to headline")
                _receipt({
                    "guard": "id_arithmetic", "action": "caveated_headline",
                    "detail": ("the total multiplies a measure by an id/key column; "
                               "the magnitude is flagged untrustworthy")})
        except Exception as _e:
            logger.debug("chat id-arithmetic backstop is best-effort; skipped: %s", _e)
        # WP-1e — E1 function-semantics checks on the LIVE answer (flag `trust.e1_live`):
        # pure-AST footguns (timestamp bounded by a date-only literal, lexicographic
        # ORDER BY on numeric text, text↔numeric compare) previously ran only on
        # /query/validate — never on an answer a user actually saw. WARN-only: the
        # headline gets the caveat, the SQL is never rewritten (the E1 contract).
        if final_sql:
            try:
                from aughor.sql.trust_checks import connection_column_types, run_trust_checks
                # Real column types (cached) so the date-boundary check distinguishes a genuine
                # TIMESTAMP footgun from a DATE column merely named `*_at`/`*_ts` (WP-1f: the DATE
                # false positive the name heuristic would raise otherwise).
                _e1_ct = connection_column_types(connection_id, db)
                _e1_hits = run_trust_checks(final_sql, col_types=_e1_ct or None, dialect=db.dialect)
                if _e1_hits:
                    _e1_msgs = "; ".join(t.message for t in _e1_hits[:2])
                    _grounded_headline = (
                        f"{(_grounded_headline or '').rstrip('. ')} — caution: {_e1_msgs}"
                    )
                    _rcpt["e1_checks"] = [t.pattern for t in _e1_hits]
                    # Patterns are identifiers for the receipt; the MESSAGES are the
                    # prose the narrator needs (2.2) — "ratio_denominator" told to a
                    # reader explains nothing.
                    _rcpt["e1_messages"] = [t.message for t in _e1_hits[:2]]
                    logger.info("[chat] E1 trust-check caveat applied to headline: %s",
                                [t.pattern for t in _e1_hits])
                    _receipt({
                        "guard": "e1_trust_checks", "action": "caveated_headline",
                        "detail": _e1_msgs[:400]})
            except Exception as _e:
                logger.debug("chat E1 checks are best-effort; skipped: %s", _e)
        # Deterministic concentration→pareto (the renderer never sees the question).
        _chart_before = answer.chart_type
        answer.chart_type = _maybe_pareto(question, result.columns, result.rows, answer.chart_type)
        if answer.chart_type != _chart_before:
            _receipt({
                "guard": "concentration_pareto", "action": "overrode_chart",
                "detail": ("the question asks about concentration (80/20) over a ranked "
                           "measure; a Pareto states that claim, the picked chart did not"),
                "before": _chart_before, "after": answer.chart_type})
        # Chart-grammar exhibit for the quick answer — computed from the result grid alone
        # (severity ramp for a single-rate ranking; point labels for a scatter). Rides inside
        # chart_config so no new event/persistence surface is needed; absent when the
        # grid has no exhibit to compute.
        from aughor.agent.exhibit import quick_exhibit
        _exh = quick_exhibit(result.columns, result.rows, answer.chart_type)
        if _exh:
            answer.chart_config = {**(answer.chart_config or {}), "exhibit": _exh}
        emit("columns", {"columns": result.columns})
        emit("rows", {"rows": result.rows[:10000]})
        _grounded_headline = _apply_currency(_grounded_headline, _cur_sym)
        emit("headline", {"headline": _grounded_headline})
        emit("chart_type", {"chart_type": answer.chart_type})
        if answer.chart_config:
            emit("chart_config", {"chart_config": answer.chart_config})
        _tables_used = _extract_tables(final_sql)
        emit("tables_used", {"tables": _tables_used})
        if answer.intent or answer.approach:
            emit("analysis", {"intent": answer.intent, "steps": answer.approach})
        if pb_entries:
            _playbook_refs = _pb_serialize(pb_entries)
            emit("playbook_refs", {"items": _playbook_refs})
        if _trusted_used:
            emit("trusted", {"items": _trusted_used})

        # Phase 5 — progressive escalation: if the cheap answer is inconclusive (empty on an
        # analytical question, or a causal "why" answered by a single figure), OFFER a deep
        # investigation (a suggestion the user clicks — not a forced re-run).
        from aughor.agent.escalate import assess_escalation
        _esc = assess_escalation(question, columns=result.columns, rows=result.rows)
        _esc_event = _esc.to_event() if _esc.should_offer else None
        if _esc_event is not None:
            emit("escalate", _esc_event)

        # Persist, then mark DONE the moment the answer is ready — so the
        # "Completed in …" time reflects when the user got their answer, not when
        # the post-answer enrichment (inspect + follow-ups) finishes.
        _chat_inv_id = ""
        try:
            _chat_inv_id = save_chat_turn(
                question=_persist_q, connection_id=connection_id,
                headline=_grounded_headline or question,
                sql=final_sql or "", session_id=session_id, columns=result.columns,
                rows=result.rows, chart_type=answer.chart_type,
                tables_used=_extract_tables(final_sql or ""),
                intent=answer.intent, approach=answer.approach,
                canvas_id=canvas_id, purpose=purpose,
            )
            _turn_persisted = True
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "chat turn save is best-effort; the answer was already streamed (turn just won't appear in history)",
                     counter="chat.turn_save")

        # K3-wide: the chat answer becomes a versioned ledger artifact with
        # provenance — so EVERY user-facing number carries a Trust Receipt, not
        # just explorer findings. Lineage records ONLY what verifiably happened
        # this turn (executed SQL, input tables, guards that fired, registered
        # metrics available for this connection, trusted queries used).
        if _chat_inv_id and final_sql:
            _guards = []
            if _rcpt["compiled"]:
                _guards.append(("validated_by", "guard:semantic_compiler", "SQL synthesized deterministically from a typed intent"))
            if _rcpt["defan"]:
                _guards.append(("validated_by", "guard:fan_out_defan", "rewrote SQL to prevent join over-counting"))
            if _rcpt["grounded"]:
                _guards.append(("validated_by", "guard:numeric_grounding", "headline corrected to match the result cells"))
            if _rcpt["lint"]:
                _guards.append(("validated_by", "guard:sql_lint", "auto-fixed a SQL quality issue before execution"))
            if _rcpt.get("narration_inversion"):
                _guards.append(("flagged", "guard:narration_inversion", "a per-group value was stated as universal; caveated inline"))
            if _rcpt.get("measure_grain"):
                _guards.append(("flagged", "guard:measure_grain", "a measure may be summed at the wrong grain (per-unit vs per-line); caveated inline"))
            if _rcpt.get("id_arithmetic"):
                _guards.append(("flagged", "guard:id_arithmetic", "a measure was multiplied by an id/key column; magnitude caveated inline"))
            if _rcpt.get("assumed"):
                # The user's own "answer anyway" — a DISCLOSED assumption, recorded on
                # the receipt so the reader can see what the answer rests on.
                _guards.append(("flagged", "guard:assumed_reading",
                                "the question was open to more than one reading and a best guess was requested; "
                                "one reading was chosen and is disclosed in the answer"))
            if _cx.ambiguous:
                # The #1 NL2SQL challenge (ambiguity): the question was under-specified.
                # Surface it honestly on the receipt rather than silently guessing.
                _guards.append(("flagged", "guard:ambiguous_question",
                                "the question was under-specified (no explicit metric/time window); answered with a default reading — refine for a different cut"))
            for _tq in (_trusted_used or []):
                _guards.append(("trusted", f"query:{(_tq.get('question') or '')[:60]}", _tq.get('note')))
            _receipts = _write_answer_receipt(
                kind="chat_answer", natural_key=f"chat:{connection_id}:{_chat_inv_id}",
                question=question, sqls=[final_sql], headline=_grounded_headline or question,
                schema=schema, connection_id=connection_id, canvas_id=canvas_id,
                guard_edges=_guards,
                payload_extra={"chart_type": answer.chart_type, "row_count": len(result.rows),
                               "complexity_tier": _cx.tier},
            )
            # Surface the per-run receipts live (Wave 1·E4 learning · E3 activations); each is flag-gated.
            for _evt in ("learning", "activations"):
                if _receipts.get(_evt):
                    emit(_evt, _receipts[_evt])
            # WP-10: hand the UI the stable receipt id so "Why this number" opens the unified
            # public receipt (GET /receipt/{id}) — one contract across every answer mode.
            if _receipts.get("receipt_id"):
                _receipt_id = _receipts["receipt_id"]
                emit("receipt_id", {"receipt_id": _receipt_id})

            # Self-improving loop: notice ontology gaps from this real query (e.g. a
            # currency measure aggregated with no canonical metric covering it) and
            # accrue a reviewable recommendation. Best-effort, post-answer — never
            # touches the response stream.
            try:
                from aughor.ontology.recommendations import observe as _observe_gaps
                from aughor.ontology.store import load_latest_ontology as _llo
                _observe_gaps(connection_id, getattr(db, "_schema_name", None) or "default",
                              question, final_sql, _llo(connection_id), dialect=db.dialect)
            except Exception as exc:
                from aughor.kernel.errors import tolerate
                tolerate(exc, "ontology-gap observation is a best-effort post-answer loop; never touches the response",
                         counter="chat.ontology_gaps")

        # Carry the turn id so the client can fetch this answer's Trust Receipt.
        emit("done", {"inv_id": _chat_inv_id, "has_receipt": bool(_chat_inv_id and final_sql)})

        # ── Post-answer enrichment (streams in after DONE, never delays it) ──
        # ONE narrator call produces BOTH the narrative and the follow-up
        # questions (was two separate round-trips). For trivial result
        # shapes (a single scalar / empty set) there's no trend to interpret, so
        # we ask only for follow-ups and skip the narrative — same single call.
        _narrative_dict = None
        _narrative_worth_it = len(result.rows) >= 2 or (len(result.rows) == 1 and len(result.columns) >= 3)
        try:
            # Bounded sample: up to 20 rows × 8 columns. For a time series, weight toward the
            # most recent periods so the narrative leads with current state, not year-one.
            _sample_rows, _is_ts = _narrator_sample(result.columns, result.rows)
            _sample_cols = result.columns[:8]
            _rows_text = "\n".join(
                ", ".join(str(r[i]) for i in range(len(_sample_cols))) for r in _sample_rows
            )
            if _narrative_worth_it:
                _ts_clause = (
                    " This result is a TIME SERIES shown as the series start then the most recent periods: "
                    "LEAD WITH THE MOST RECENT period and its current trend, and state the net change since "
                    "the start — do NOT anchor the narrative on the earliest period."
                    if _is_ts else ""
                )
                _system = (
                    "You are an analytical data interpreter writing for a clean published brief. "
                    "Given a user question, the SQL that answered it, and a sample of the results: "
                    "(1) produce a tight analytical narrative (2-3 sentences) that LEADS WITH THE ANSWER, "
                    "wraps each decisive number in **double asterisks** for bold (e.g. **$2,112**, **+18%**), "
                    "names any genuine anomaly (unexpected value, spike, drop, outlier) in plain words, and "
                    "states the overall trend and your confidence. Start with the finding — no preamble, no "
                    "hedging, no 'the data shows' scaffolding. Use ONLY numbers present in the results; never "
                    "invent values, and bold never licenses invented precision." + _ts_clause + " "
                    "Then (2) " + _FOLLOWUP_CLAUSE
                )
            else:
                _system = (
                    "Given a user question and its answer, " + _FOLLOWUP_CLAUSE
                    + " Leave the narrative empty."
                )
            _rows_label = (
                f"Results (TIME SERIES — series start then the {len(_sample_rows) - 1} most "
                f"recent of {len(result.rows)} periods, oldest→newest):"
                if _is_ts else f"Results (sample of {len(_sample_rows)} rows):"
            )
            # The resolution's single caveat leads the narrator too, so the
            # narrative + follow-ups agree with the answer instead of re-deciding.
            _res_note = ""
            if _resolution is not None and _resolution.caveat:
                _res_note = (f"\n\nGROUNDED FACT — state this once, honestly, and do NOT speculate "
                             f"about other tables or grains: {_resolution.caveat}.")
            # The reader's declared organization — industry, reporting currency, fiscal
            # year. This block existed but had only three callers (profile inference,
            # the explorer, the brief), so the most-used surface in the product could
            # not see facts the operator had explicitly stated. Empty string when
            # nothing is declared, so an unconfigured org's prompt is unchanged.
            _org_note = ""
            try:
                from aughor.orgsettings import org_context
                _org_note = org_context(reading="this answer")
                if _org_note:
                    _org_note = "\n\n" + _org_note.rstrip("\n")
            except Exception as _org_exc:
                from aughor.kernel.errors import tolerate
                tolerate(_org_exc, "org context is additive; the answer stands without it",
                         counter="ask.org_context")
            # Wave 2 / 2.2 — the narration half of the guard receipts.
            #
            # `_grounded_headline`, not `answer.headline`: the headline the USER sees
            # (line ~2174) is the one the grounding rewrite corrected and the guards
            # appended their cautions to. The narrator was being handed the RAW model
            # claim, so the prose could confidently restate a number the headline had
            # already retracted — the answer disagreeing with itself, by construction.
            #
            # `_guard_note` then lets the model SPEAK those interventions instead of
            # the user meeting them only as a clause bolted onto the headline. The
            # guards are already visible as receipt frames (A4/B2); this is the other
            # half of P1 — the answering model sees them too.
            _user = (
                f"Question: {question}\n"
                f"SQL: {final_sql}\n"
                f"Answer: {_grounded_headline}\n"
                f"{_rows_label}\n"
                f"Columns: {', '.join(_sample_cols)}\n"
                f"{_rows_text}"
                f"{_org_note}"
                f"{_res_note}"
                f"{_guard_note(_rcpt)}"
            )
            # CK-0.2 token-streaming (flag `ask.stream_text`, default ON): stream the
            # narrative as `narrative_delta` frames while the narrator writes it, then let
            # the terminal `narrative` event carry the authoritative final value —
            # self-healing (a dropped delta costs nothing; old clients ignore the unknown
            # event).
            import queue as _queue
            import threading as _threading
            import time as _time

            _pa_q: _queue.Queue = _queue.Queue()
            _pa_result: dict = {}

            def _pa_worker() -> None:
                # complete_streaming falls back to the blocking complete() internally
                # on ANY streaming failure, so "exc" only means BOTH paths failed —
                # re-raised below into the enclosing tolerate, exactly like today.
                try:
                    _pa_result["pa"] = get_provider("narrator").complete_streaming(
                        system=_system, user=_user, response_model=_PostAnswer,
                        temperature=0.2, text_field="narrative", on_text=_pa_q.put,
                    )
                except Exception as worker_exc:
                    _pa_result["exc"] = worker_exc
                finally:
                    _pa_q.put(None)   # sentinel: the stream is over

            _pa_thread = _threading.Thread(target=_pa_worker, daemon=True,
                                           name="narrative-stream")
            _pa_thread.start()
            # Drain partials → SSE deltas, throttled (grew ≥12 chars since the last
            # emit, or >150ms elapsed) so a chatty stream can't spam frames. Deltas
            # go out strictly BEFORE the terminal `narrative` event, and only when the
            # answer is worth narrating (same gate the terminal event uses).
            _last_len, _last_ts = 0, _time.monotonic()
            _POLL_EMPTY = object()  # poll-timeout marker, distinct from the None sentinel

            def _pa_poll():
                # A poll timeout is the loop's heartbeat, not a failure — return a
                # marker instead of swallowing queue.Empty at the call site.
                try:
                    return _pa_q.get(True, 0.25)
                except _queue.Empty:
                    return _POLL_EMPTY

            while True:
                _item = _pa_poll()
                if _item is _POLL_EMPTY:
                    # The other 250 ms heartbeat, straddling the narrator call —
                    # same cancellation checkpoint as the coder drain above.
                    if cancelled():
                        raise _CoreCancelled()
                    continue
                if _item is None:
                    break
                if not (_narrative_worth_it and isinstance(_item, str)):
                    continue
                _now = _time.monotonic()
                if len(_item) - _last_len >= 12 or _now - _last_ts > 0.150:
                    _last_len, _last_ts = len(_item), _now
                    _delta_payload = {"narrative": _apply_currency(_item, _cur_sym)}
                    emit("narrative_delta", _delta_payload)
                    # DUAL-EMIT, one release only: the retired `insight_delta` name
                    # carries the IDENTICAL payload so a client deployed before the
                    # rename keeps typing the partial. Delete once no such client
                    # remains; the frontend already prefers `narrative_delta`.
                    emit("insight_delta", _delta_payload)
            _pa_thread.join()
            if "exc" in _pa_result:
                raise _pa_result["exc"]
            _pa: _PostAnswer = _pa_result["pa"]
            if _narrative_worth_it and _pa.narrative:
                _narrative_dict = {
                    "narrative": _apply_currency(_pa.narrative, _cur_sym),
                    "anomalies": _pa.anomalies[:3],
                    "trend": _pa.trend,
                    "confidence": _pa.confidence,
                }
                emit("narrative", _narrative_dict)
                # DUAL-EMIT, one release only: the retired `insight` name carries the
                # IDENTICAL payload (same dict object) so a client deployed before the
                # rename still receives the terminal value. Delete once no such client
                # remains; the frontend already prefers `narrative`.
                emit("insight", _narrative_dict)
                # Persist so the narrative survives page reload / history navigation.
                # The stored key stays `report_json["insight"]` (db/history.py) — a
                # persisted identity; renaming it would orphan every stored turn.
                if _chat_inv_id:
                    try:
                        from aughor.db.history import update_chat_turn_insight
                        update_chat_turn_insight(_chat_inv_id, _narrative_dict)
                    except Exception as exc:
                        from aughor.kernel.errors import tolerate
                        tolerate(exc, "narrative persistence is best-effort; it was already streamed this session",
                                 counter="chat.insight_persist")
            if _pa.questions:
                _followups = list(_pa.questions[:3])
                emit("followups", {"questions": _followups})
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "post-answer narrative/follow-up enrichment is best-effort; the answer is already done",
                     counter="chat.post_answer")

        # Semantic inspect — logical validation. Phase 3 of the ground-first
        # redesign: when the resolution ran, its verdict already settled entity /
        # grain / measure / scope (the exact five things this LLM re-checks), so we
        # SKIP the redundant round-trip — the first guard the resolution replaces
        # rather than adds to. (Deletion roadmap — the other post-hoc guards it
        # subsumes: entity-column alignment, breakdown-grain, id-arithmetic
        # guard+backstop, ratio-of-sums, measure-grain caveat, scope guard — are
        # staged follow-ons, not removed here.) When it runs (resolution off), it
        # is grounded on the schema slice so it cannot invent columns.
        if _resolution is None:
            try:
                from aughor.sql.inspect import inspect as _inspect_sql
                _ir = _inspect_sql(question, final_sql, result.columns, result.rows,
                                   schema=_full_schema)
                if not _ir.valid and _ir.issues:
                    emit("inspect_warning", {
                        "issues":        _ir.issues,
                        "suggested_fix": _ir.suggested_fix,
                    })
            except Exception as exc:
                from aughor.kernel.errors import tolerate
                tolerate(exc, "post-answer semantic inspect is best-effort validation; skipping the warning",
                         counter="chat.inspect")

        return _AnswerCoreResult(
            outcome="answered",
            headline=_grounded_headline or "",
            sql=final_sql or "",
            columns=list(result.columns or []),
            rows=list(result.rows or []),
            row_count=result.row_count,
            guard_receipts=receipts,
            receipt=dict(_rcpt),
            caveats=list(result.caveats or []),
            chart_type=answer.chart_type,
            chart_config=dict(answer.chart_config or {}),
            intent=answer.intent,
            approach=list(answer.approach or []),
            tables_used=_tables_used,
            escalate=_esc_event,
            inv_id=_chat_inv_id,
            receipt_id=_receipt_id,
            trusted=list(_trusted_used or []),
            playbook_refs=_playbook_refs,
            narrative=_narrative_dict,
            followups=_followups,
        )
    except _CoreCancelled:
        # The user stopped, or walked away and the client went with them. Everything the
        # turn produced up to here was streamed and then, until now, dropped: the persist
        # at the end of the happy path is the ONLY writer, and cancellation raises long
        # before it. So an interrupted turn left no trace — not in History, not anywhere —
        # and reloading the page lost an answer the user had already partly read.
        #
        # It is filed as `interrupted`, never `complete`: a turn stopped mid-flight has no
        # verified answer, and "complete" would claim one. That is the same distinction
        # `UNCERTAIN_RESULT` draws for a dropped stream — interrupted is not failed either,
        # because nothing went wrong.
        #
        # Best-effort by construction. A turn the user abandoned must not be able to raise
        # on its way out, so a failed flush is swallowed and the cancellation continues.
        try:
            if not _turn_persisted and (_seen.get("headline") or _seen.get("sql")):
                save_chat_turn(
                    question=_persist_q, connection_id=connection_id,
                    headline=_seen.get("headline") or question,
                    sql=_seen.get("sql") or "", session_id=session_id,
                    columns=_seen.get("columns") or [], rows=_seen.get("rows") or [],
                    chart_type=_seen.get("chart_type") or "none",
                    tables_used=_extract_tables(_seen.get("sql") or ""),
                    canvas_id=canvas_id, purpose=purpose,
                    status="interrupted",
                )
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "interrupted-turn flush is best-effort; the turn was already "
                          "abandoned and the cancellation must not be blocked by it",
                     counter="chat.interrupted_flush")
        raise
    finally:
        try:
            db.close()
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "chat stream connection close is best-effort cleanup",
                     counter="chat.db_close")


#: The public seam for the converse `answer_question` tool (aughor/agent/converse_tools.py)
#: — a second caller of the SAME body the SSE wrapper streams from, which is what makes
#: tool/direct parity hold by construction rather than by assertion. Public on purpose:
#: the private-import ratchet (test_kernel_contracts) is right that another module should
#: not reach for an `_internal`, and an alias beats a rename that would orphan the
#: transcript, bridge and scope nets all pointing at `_answer_core`.
answer_core = _answer_core


async def _core_frames(
    run: Callable[[Callable[[str, dict], None], Callable[[], bool]], object],
) -> AsyncGenerator[tuple, None]:
    """Run a sync body on the answer pool and yield the ``(type, payload)`` pairs it emits.

    The sync->async frame bridge, once, for both bodies that need it. It yields TUPLES,
    never encoded SSE, and that is deliberate on two counts: the caller decides the
    envelope, and this function names no frame — so the frame-parity guard, which reads
    this file as text, still finds every frame declared at a literal emission site
    rather than hidden behind a shared relay.

    ``run(emit, cancelled)`` is the body. ``emit`` takes a frame name and a flat payload
    and raises ``_CoreCancelled`` once the consumer has gone away; ``cancelled()`` is the
    same signal for the stretches that emit nothing.

    The mechanism is the repo's existing sync->async bridge (``agent/progress.py``,
    feeding the deep path): one producer thread, ``call_soon_threadsafe`` scheduling each
    ``put_nowait`` on the loop in FIFO order, so emission order survives the hop, and an
    unbounded queue so the producer never stalls. What changes semantically is that a
    slow client no longer back-pressures the computation: the answer is computed and
    persisted at full speed and the queue buffers. Depth is bounded in practice because
    both delta loops are throttled at the source.

    How a caller knows finished-from-raised: it does not ask the sentinel, this awaits
    the future. ``_CORE_DONE`` only terminates the STREAM; ``await fut`` then either
    returns the body's result or re-raises its exception INSIDE the consumer's frame,
    where an ``except Exception -> error`` and ``_metered_stream``'s ``BudgetExceeded``
    handler both work exactly as they did when this was one function.
    """
    loop = asyncio.get_running_loop()
    frames: asyncio.Queue = asyncio.Queue()
    cancel = threading.Event()

    def _emit(t: str, p: dict) -> None:        # runs on the WORKER thread
        if cancel.is_set():
            raise _CoreCancelled()
        loop.call_soon_threadsafe(frames.put_nowait, (t, p))

    def _work():
        try:
            return run(_emit, cancel.is_set)
        finally:
            loop.call_soon_threadsafe(frames.put_nowait, _CORE_DONE)

    # On the dedicated pool, not `asyncio.to_thread`: to_thread borrows a DEFAULT-executor
    # worker for the whole turn, and that pool is shared with every router's short
    # offload hop — see `_ANSWER_CORE_POOL` for the measured head-of-line blocking this
    # caused. The pool copies contextvars per task, so metering still crosses the hop.
    fut = loop.run_in_executor(_ANSWER_CORE_POOL, _work)
    try:
        while True:
            item = await frames.get()
            if item is _CORE_DONE:
                break
            yield item
        await fut                              # success vs raise is decided HERE
    finally:
        cancel.set()
        if not fut.done():
            # The body cannot be interrupted mid-call, and awaiting it here would
            # hold teardown for the rest of the turn. Retrieve the exception in a
            # callback instead, so an orphan that raises does not log
            # "Task exception was never retrieved".
            fut.add_done_callback(lambda f: f.cancelled() or f.exception())


async def _stream_chat(
    question: str,
    connection_id: str,
    history: list[ChatHistoryTurn],
    session_id: str = "",
    canvas_id: Optional[str] = None,
    skip_clarify: bool = False,
    purpose: str = "",
    schema_scope: Optional[str] = None,
    assumed_default: bool = False,
) -> AsyncGenerator[str, None]:
    """The streaming half: run ``_answer_core`` on a worker thread and yield what it says.

    A nested function cannot yield on behalf of its caller, so the moment the core's
    48 ``yield _sse(...)`` became ``emit(...)`` the function stopped streaming — the
    bridge in :func:`_core_frames` is what gives it back, and why the two changes had to
    land together.

    All this adds to the bridge is the ENVELOPE: re-encode each relayed pair, and render
    a raised failure as the terminal ``error`` frame. `aclose()` is explicit because the
    bridge is now a nested generator: without it, a client that leaves mid-turn would
    leave the inner generator's cancellation to whenever the garbage collector got
    around to it, and the core would keep paying in the meantime.
    """
    def _run(emit, cancelled):
        return _answer_core(
            question, connection_id, history, emit=emit, cancelled=cancelled,
            session_id=session_id, canvas_id=canvas_id, skip_clarify=skip_clarify,
            purpose=purpose, schema_scope=schema_scope,
            assumed_default=assumed_default,
        )

    _bridge = _core_frames(_run)
    try:
        async for _frame_type, _frame_payload in _bridge:
            yield _sse(_frame_type, _frame_payload)
    except _CoreCancelled:
        pass
    except Exception as e:
        yield _sse("error", _error_event(e))
    finally:
        await _bridge.aclose()


#: Inner frames a converse turn does NOT forward. The rule: forward what describes the
#: WORK, suppress what describes the TURN'S LIFECYCLE — because only the wrapper knows
#: when a converse turn is over, and a tool does not.
#:
#: * ``done`` is the one that matters. Relayed raw, the client's DONE action fires while
#:   the model is still deciding whether to call another tool: the turn renders finished
#:   mid-conversation. Its ``inv_id``/``has_receipt`` are real, though, so they are kept
#:   and re-issued on the converse turn's own ``done`` rather than thrown away.
#: * ``error`` marks a DELIBERATE terminal state the core then returns from. Here that
#:   comes back to the model as a value it can recover from, so a red terminal frame
#:   followed by more work would be a lie about the turn.
#: * ``clarify`` — the inner core may hit the ambiguity probe and offer chips on a
#:   sub-question the user never asked.
#: * ``followups`` are about the model's sub-question, not the user's.
#: * ``mode`` — the wrapper decides ``final_text`` for the whole turn; a forwarded inner
#:   one would mislabel a turn that did produce SQL.
_CONVERSE_SUPPRESSED = frozenset({"done", "error", "clarify", "followups", "mode"})


async def _stream_converse(
    question: str,
    connection_id: str,
    history: list[ChatHistoryTurn],
    session_id: str = "",
    canvas_id: Optional[str] = None,
    origin_prose: str = "",
) -> AsyncGenerator[str, None]:
    """Serve one `/ask` turn as a CONVERSATION (`ask.converse`, EXPERIMENT, default off).

    Same shape as :func:`_stream_chat` — the shared bridge, a different body — and
    deliberately so: one copy of the concurrency design, two bodies riding it.

    What the user sees is mostly frames they already know. A converse turn that calls
    ``answer_question`` runs the SAME ``answer_core`` the fast path streams from, so its
    ``sql`` / ``columns`` / ``rows`` / ``guard_receipt`` frames mean exactly what they
    always meant and are forwarded verbatim. Synthesizing them instead from the tool's
    returned dict would be a second emission site for the same values, guaranteed to
    drift from the first; suppressing them would make the SMARTER path the one with no
    visible receipts, which is the wrong asymmetry to build.

    Only ``converse_step`` is new, because only "the model chose a tool" is new. The
    turn's terminal ``headline`` is the model's own prose and lands last, where the
    client's replace-semantics make it win over the tool's inner headline — which is
    what lets a converse turn render with no frontend work at all.

    Budget exhaustion ends on a ``headline``, not an ``error``: the loop's own comment
    is the argument ("an answer we did not reach" beats a half-derived guess), and an
    ``error`` frame renders red and discards the step trail the user can already see.
    The machine-readable marker rides on ``done`` instead.
    """
    def _run(emit, cancelled):
        from aughor.agent.converse_tools import converse
        from aughor.obs import session_log

        turn: dict = {"steps": 0, "sql": False, "inv_id": "", "has_receipt": False}

        def _forward(_frame_type: str, _frame_payload: dict) -> None:
            """The tools' frames, minus the lifecycle. Named ``_frame_type`` on purpose:
            it is the same relay claim `_stream_chat` makes — every name it carries was
            declared literally at an ``emit`` call the frame-parity parser already read."""
            if _frame_type == "done":
                # Keep the inner turn's identity; it is the row "Why this number" hangs
                # off. Taken as a PAIR so a later tool without a receipt cannot leave
                # `has_receipt` true against a different turn's id.
                if _frame_payload.get("inv_id"):
                    turn["inv_id"] = _frame_payload["inv_id"]
                    turn["has_receipt"] = bool(_frame_payload.get("has_receipt"))
                return
            if _frame_type in _CONVERSE_SUPPRESSED:
                return
            if _frame_type == "sql":
                turn["sql"] = True
            emit(_frame_type, _frame_payload)

        def _on_step(step) -> None:
            # The loop's ONLY cancellation checkpoint. `answer_core` checkpoints inside
            # itself, so the gap this closes is BETWEEN steps: without it a client that
            # left still buys every remaining provider round-trip.
            if cancelled():
                raise _CoreCancelled()
            turn["steps"] += 1
            emit("converse_step", {
                "index": turn["steps"],
                "tool": step.tool,
                "arguments": {k: str(v)[:400] for k, v in (step.arguments or {}).items()},
                "ok": step.ok,
                "detail": str(step.detail or "")[:500],
                "result_chars": step.result_chars,
            })
            # The trail, in the log the flag's exit receipt reads. `name=step.tool` folds
            # into the existing per-tool reliability aggregate, which is the honest place
            # for it — these ARE tool calls.
            session_log.emit(session_log.TOOL_CALL_RESULT, name=step.tool,
                             conn_id=connection_id, ok=step.ok,
                             payload={"body": "converse", "detail": str(step.detail or "")})

        # CI-1b — the conversation body gets the same two memories the quick body does:
        # this session's turns, and what this question was answered before elsewhere.
        # CI-4 adds the third: the origin finding a seeded/dossier turn is ABOUT,
        # rendered by the same code the deep path anchors on.
        _memory = (build_history_section(history)
                   + build_prior_answers_section(
                       resolve_prior_answers(question, connection_id, session_id)))
        if origin_prose:
            _memory = origin_prose + "\n\n" + _memory if _memory else origin_prose
        result = converse(connection_id, question,
                          extra_context=_memory,
                          on_step=_on_step, tool_emit=_forward,
                          session_id=session_id, canvas_id=canvas_id)

        answer = (result.answer or "").strip()
        if not answer:
            # Say what actually happened. `stop_reason` distinguishes three different
            # failures that used to share one sentence, and the sentence named the one
            # that was usually WRONG: a turn that stopped after a single step of a
            # budget of eight still reported "I ran out of steps", which sends the
            # reader off to narrow a question that was never the problem.
            steps_n = len(result.steps)
            if result.stop_reason == "budget":
                answer = (
                    f"I ran out of steps before reaching an answer ({steps_n} tool "
                    "calls). What each step found is above — ask a narrower question "
                    "and I can finish it."
                )
            elif result.stop_reason == "silent":
                answer = (
                    f"I stopped without an answer after {steps_n} "
                    f"{'step' if steps_n == 1 else 'steps'} — the model returned no "
                    "tool call and no text, twice. What each step found is above. "
                    "Asking again usually clears it."
                )
            else:
                answer = (
                    f"I finished without producing an answer ({steps_n} tool "
                    f"{'call' if steps_n == 1 else 'calls'}). What each step found is "
                    "above — asking again, or more specifically, usually gets there."
                )
        if not turn["sql"]:
            # No SQL this turn ⇒ the same shape the core's own no-SQL paths use, so a
            # text-only converse answer renders exactly like a definitional one does.
            emit("mode", {"query_mode": "final_text"})
        emit("headline", {"headline": answer})
        emit("done", {"inv_id": turn["inv_id"], "has_receipt": turn["has_receipt"],
                      "body": "converse", "stop_reason": result.stop_reason,
                      "steps": len(result.steps)})

        # Wave 6's input: which body served this turn, and what it cost. Emitted HERE,
        # not sniffed off the wire by `stream_with_session_log` — widening that sniff
        # would change what an OFF-state run logs too.
        session_log.emit(
            session_log.TOOL_CALL, name="ask.converse", conn_id=connection_id,
            ok=bool(result.answer), row_count=len(result.steps),
            payload={"body": "converse", "stop_reason": result.stop_reason,
                     "tools": [s.tool for s in result.steps],
                     "injected_chars": result.injected_chars,
                     "reinjection_ratio": round(result.reinjection_ratio, 2)},
        )
        return result

    _bridge = _core_frames(_run)
    try:
        async for _frame_type, _frame_payload in _bridge:
            yield _sse(_frame_type, _frame_payload)
    except _CoreCancelled:
        pass
    except Exception as e:
        # The ONLY terminal error on this path: something escaped `converse()` itself —
        # a dead provider, a 401. A tool that raises never gets here; the loop already
        # records it as a failed step the model can recover from.
        yield _sse("error", _error_event(e))
    finally:
        await _bridge.aclose()


# ── Investigation streaming ───────────────────────────────────────────────────

def _render_origin_prose(o: dict) -> str:
    """Render an origin finding as a compact prior-analysis note — for the
    direct/explore branches, which read ``prior_analyses``. (The ADA branch reads the
    structured ``origin_finding`` directly; see ``ada_intake``.)"""
    parts = [f"ALREADY ESTABLISHED by background exploration (do not re-derive): {o.get('finding', '')}"]
    if o.get("result_cells"):
        parts.append(f"Grounded result values: {o['result_cells']}")
    if o.get("structural"):
        parts.append("Verified joins: " + "; ".join(o["structural"]))
    if o.get("sql"):
        parts.append(f"Source SQL already run:\n{o['sql']}")
    return "\n".join(parts)


async def _build_origin_finding(
    connection_id: str,
    insight_id: Optional[str],
    seed_context: str,
    seed_sql: Optional[str],
) -> Optional[dict]:
    """The structured, already-established finding this investigation is DRILLING — or
    None for a cold-start question.

    The SINGLE source of truth for "what known result am I explaining": the ADA branch
    reads it directly (``ada_intake`` anchors its metric/tables/window on it instead of
    re-deriving), and the report carries its provenance (``insight_id``).

    Prefers the dossier (the explorer's captured derivation) resolved from
    ``insight_id``; falls back to the lightweight ``seed_context``/``seed_sql`` a caller
    passed inline (a finding predating dossier capture, or a chart drill). Best-effort.
    """
    from aughor.explorer.scope import tables_in_sql
    if insight_id:
        try:
            from aughor.kernel.ledger import Ledger
            rec = await asyncio.to_thread(
                Ledger.default().receipt, f"insight:{connection_id}:{insight_id}")
            dossier = ((rec or {}).get("artifact", {}).get("payload", {}) or {}).get("dossier")
            if dossier:
                sc = dossier.get("structural_ctx") or {}
                joins = []
                for j in (sc.get("joins") or [])[:6]:
                    joins.append(f"{j.get('from_table')}→{j.get('to_table')} {j.get('cardinality')}"
                                 + ("" if j.get("verified") else f" ({j.get('orphan_count')} orphans)"))
                _sql = (dossier.get("sql") or "").strip()
                return {
                    "insight_id": insight_id,
                    "finding": (dossier.get("finding") or "").strip(),
                    "sql": _sql,
                    "tables": sorted(tables_in_sql(_sql)) if _sql else [],
                    "result_cells": (dossier.get("result_cells") or "").strip(),
                    "structural": joins,
                    "narrative": (dossier.get("narrative") or "").strip(),
                }
        except Exception:
            logger.debug("origin dossier lookup failed; falling back to inline seed", exc_info=True)

    _sc = (seed_context or "").strip()
    _sq = (seed_sql or "").strip()
    if _sc or _sq:
        return {
            "insight_id": insight_id or "",
            "finding": _sc,
            "sql": _sq,
            "tables": sorted(tables_in_sql(_sq)) if _sq else [],
            "result_cells": "",
            "structural": [],
            "narrative": "",
        }
    return None


def _followup_origin(history: list) -> Optional[dict]:
    """A structured origin_finding built from the PREVIOUS turn — the base a follow-up
    question composes on. Same shape as ``_build_origin_finding`` so ada_intake anchors
    on it and the direct/explore branches see it via prior_analyses. The ``finding`` text
    is a compose-on-base directive; the ``sql`` is the base query to keep/extend."""
    from aughor.explorer.scope import tables_in_sql
    if not history:
        return None
    prior = history[-1]
    _get = (lambda k: getattr(prior, k, None)) if not isinstance(prior, dict) else prior.get
    _sql = (_get("sql") or "").strip()
    if not _sql:
        return None
    _q = (_get("question") or "").strip()
    _headline = (_get("headline") or "").strip()
    key_rows = _get("key_rows") or []
    _cells = "; ".join(" | ".join(str(c) for c in (row or [])[:6]) for row in key_rows[:3])
    directive = (
        f"FOLLOW-UP — compose on the previous query. Prior question: \"{_q}\". Keep its "
        f"metric, filters, grain and time window unless this question changes them, and "
        f"resolve 'that' / 'those' / 'the top one' against its result. Do NOT start from scratch."
    )
    return {
        "insight_id": "",
        "finding": directive,
        "sql": _sql,
        "tables": sorted(tables_in_sql(_sql)),
        "result_cells": _cells,
        "structural": [],
        "narrative": _headline,
    }


async def _stream_investigation(
    question: str,
    connection_id: str,
    request: Request,
    hitl: bool = False,
    skip_cache: bool = False,
    canvas_id: Optional[str] = None,
    schema_scope: Optional[str] = None,
    seed_sql: Optional[str] = None,
    seed_context: str = "",
    insight_id: Optional[str] = None,
    deep: bool = False,
    history: Optional[list] = None,
    requested_mode: str = "investigate",
    purpose: str = "",
    allow_clarify: bool = True,
) -> AsyncGenerator[str, None]:
    _TIMEOUT = int(os.getenv("AUGHOR_TIMEOUT_SECONDS", "600"))

    # One scope resolver (ExecutionScope). A canvas pins its own connection + declared
    # schema + table filter; a non-canvas investigation (e.g. a briefing "pull the thread")
    # honours schema_scope instead (canvas wins when both are present). eff_schema derives
    # the single owning schema of a schema-qualified table list so bare names + the explore
    # linker's full-schema FK expansion can't leak to a sibling schema — the deep path used
    # to leave this None (missimi deep answering from another demo dataset).
    from aughor.canvas.scope import resolve_execution_scope
    from aughor.tools.schema import build_canvas_schema_context
    _es = resolve_execution_scope(connection_id, canvas_id, schema_scope=schema_scope,
                                  schema_context_builder=build_canvas_schema_context)
    connection_id = _es.connection_id
    canvas_schema_context = _es.schema_context
    scope_schema = _es.eff_schema

    try:
        db = _es.open()
    except KeyError as e:
        # A KeyError from the scope resolver means the connection id does not exist —
        # a terminal state, not a hiccup. Classified explicitly because the generic
        # fallback says "retrying is usually safe", and re-asking a question against a
        # connection that is not there fails identically every time.
        yield _sse("error", _error_event(e, reason="not_found"))
        return
    except Exception as e:
        # The connection exists but would not open (server down, bad credentials in the
        # DSN, network). That one IS worth retrying, so it keeps the classifier's verdict.
        yield _sse("error", _error_event(e, message=f"Could not connect: {e}"))
        return

    # ── Tier 0: the trace is a READ, not a re-run ──────────────────────────────
    # Drilling into a known finding? The explorer already did the deep analysis and
    # captured it in the Finding Dossier. Serve that as the trace — a deterministic
    # ledger lookup by the finding's id (no semantic-match guess, no ADA, no SQL, no LLM).
    # `deep` is the explicit escalation past the dossier into a fresh investigation.
    if insight_id and not deep:
        try:
            from aughor.kernel.ledger import Ledger
            rec = await asyncio.to_thread(
                Ledger.default().receipt, f"insight:{connection_id}:{insight_id}")
            dossier = ((rec or {}).get("artifact", {}).get("payload", {}) or {}).get("dossier")
            if dossier:
                yield _sse("start", {"question": question, "connection_id": connection_id,
                                     "investigation_id": None, "insight_id": insight_id})
                yield _sse("dossier_report", {"dossier": dossier, "insight_id": insight_id,
                                              "connection_id": connection_id})
                yield _sse("done", {})
                return
            logger.debug("no dossier for insight %s — falling through to live investigation", insight_id)
        except Exception:
            logger.debug("dossier short-circuit failed; falling through", exc_info=True)

    from aughor.tools.prior_analyses import find_similar_investigation
    cache_hit = None if (skip_cache or _looks_direct(question)) else await asyncio.to_thread(find_similar_investigation, question, connection_id)
    if cache_hit:
        cached_id, score = cache_hit
        cached = get_investigation(cached_id)
        if cached and cached.get("report"):
            cached_report = cached["report"]
            report_type = cached_report.get("_report_type") if isinstance(cached_report, dict) else None
            yield _sse("start", {"question": question, "connection_id": connection_id, "investigation_id": cached_id})
            if cached.get("hypotheses"):
                yield _sse("hypotheses", {"hypotheses": cached["hypotheses"]})
            qh = cached.get("query_history") or []
            if report_type == "investigate":
                yield _sse("answer_report", {"answer_report": cached_report, "investigation_id": cached_id, "query_mode": "investigate", "mode": "investigate", "from_cache": True, "cached_question": cached["question"], "cache_score": round(score, 3)})
            elif report_type == "explore":
                yield _sse("explore_report", {"explore_report": cached_report, "sub_questions": cached_report.get("sub_questions", []), "subq_answers": cached_report.get("subq_answers", []), "query_count": cached.get("query_count", len(qh)), "investigation_id": cached_id, "query_mode": "explore", "from_cache": True, "cached_question": cached["question"], "cache_score": round(score, 3)})
            else:
                yield _sse("report", {"report": cached_report, "hypotheses": cached.get("hypotheses") or [], "query_count": cached.get("query_count", len(qh)), "query_history": qh, "investigation_id": cached_id, "from_cache": True, "cached_question": cached["question"], "cache_score": round(score, 3)})
            yield _sse("done", {})
            return

    inv_id = create_investigation(question, connection_id, canvas_id=canvas_id,
                                  agent_id=_current_agent_id(), purpose=purpose)
    from aughor import telemetry as _telemetry
    trace_id = _telemetry.new_trace(inv_id, question, connection_id)
    yield _sse("start", {"question": question, "connection_id": connection_id, "investigation_id": inv_id, "trace_id": trace_id})

    # Surface matched org-playbook items up front (they're also injected into ADA
    # synthesis). The user can keep / modify / remove them from the result.
    try:
        from aughor.playbook.retriever import retrieve_for_metric_and_phases
        _pb = await asyncio.to_thread(lambda: retrieve_for_metric_and_phases([question], limit=4))
        if _pb:
            yield _sse("playbook_refs", {"items": _pb_serialize(_pb)})
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "surfacing matched playbook items is best-effort; the investigation proceeds without them",
                 counter="investigation.playbook_refs")

    # Pause EVERY explorer bound to this connection — the connection explorer AND any
    # canvas explorers on the same connection — so background exploration doesn't contend
    # with the investigation's queries. (Previously only the connection explorer paused,
    # so a canvas explorer kept hammering the DB through the run.) Skip ones already paused
    # (e.g. user-paused) so we only resume what we actually paused.
    _paused_explorers = []
    for _e in _explorers_for_connection(connection_id):
        try:
            _e.pause()
            # Tag the pause as investigation-owned: the kernel supervisor's
            # backstop only auto-resumes these (never a user-initiated pause)
            # if this stream dies without reaching its finally-block.
            _e._paused_by_investigation = True
            _paused_explorers.append(_e)
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "explorer pause before investigation is best-effort; an unpaused explorer only adds DB contention",
                     counter="investigation.explorer_pause")

    merged: dict = {}  # bound before try so the except/salvage path can read partial state
    try:
        full_schema = await asyncio.to_thread(_get_schema_cached, connection_id, db)  # WCH-12: cached (was bypassed)
        # When a Canvas is active, use the pre-filtered canvas schema context so the
        # agent only sees the tables selected for that Canvas.
        schema = canvas_schema_context if canvas_schema_context else full_schema
        # Inject a schema-prefix note so the LLM always uses fully-qualified names
        if scope_schema:
            schema = (
                f"DEFAULT SCHEMA: {scope_schema}\n"
                "CRITICAL: Every table reference in SQL MUST include this schema prefix "
                f"(e.g. {scope_schema}.table_name). Do NOT use bare table names.\n\n"
                + schema
            )
        # Schema-linking pre-filter: narrow to relevant tables/columns per question.
        try:
            from aughor.tools.schema_linker import link_schema
            schema = link_schema(question, schema, connection_id=connection_id)
        except Exception:
            logger.warning("Schema-linking pre-filter failed (agentic path); using full schema", exc_info=True)
        # Build structured Data Catalog from linked tables
        data_catalog = ""
        try:
            from aughor.tools.data_catalog import build_data_catalog
            from aughor.tools.schema import parse_schema_tables, fk_neighbor_expand, temporal_dimension_tables
            linked_tables = list(parse_schema_tables(schema).keys())
            if linked_tables:
                # Complete the join paths BEFORE building the catalog (mirrors the /chat path):
                # schema-linking picks ~4 tables by keyword, missing bridge/parent tables a join
                # needs — e.g. the timestamp on `orders` when revenue is on `invoices`. Without
                # this the ADA coder can't see the date column and hallucinates one on the metric
                # table. Expand against the FULL schema, capped at 10 tables.
                from aughor.llm.profile import profile_for as _pf
                from aughor.tools.schema_linker import rank_tables_for_context
                _cat_cap = _pf("coder").context_table_cap
                # Pinned, then ranked+capped, then FK-completed — see the /chat path for
                # why the temporal dimension cannot ride along as a plain append.
                _pinned = [t for t in temporal_dimension_tables(full_schema, linked_tables, question)
                           if t not in linked_tables]
                linked_tables = rank_tables_for_context(
                    question, full_schema, linked_tables + _pinned,
                    cap=_cat_cap, connection_id=connection_id, pinned=_pinned)
                linked_tables = fk_neighbor_expand(full_schema, linked_tables, cap=_cat_cap)
                # Scope the expansion to the canvas schema: temporal/FK expansion walks the
                # FULL schema and can pull a sibling schema's same-named table (netflix.products
                # into a missimi investigation), which then becomes a cross-schema reference the
                # explore planner copies verbatim (bypassing search_path). Drop out-of-scope tables.
                if scope_schema:
                    _allow = scope_schema.strip().lower()
                    linked_tables = [t for t in linked_tables
                                     if "." not in t or t.split(".")[0].strip().lower() == _allow]
                data_catalog = await asyncio.to_thread(
                    lambda: build_data_catalog(db, linked_tables, schema=scope_schema or None)
                )
        except Exception:
            logger.warning("Data Catalog build failed (agentic path); using linked schema", exc_info=True)

        # Hard cap on tables in context — profile-derived (A3), rank-preserving.
        try:
            from aughor.llm.profile import profile_for
            from aughor.tools.data_catalog import enforce_context_cap
            _cap = profile_for("coder").context_table_cap
            schema = enforce_context_cap(schema, max_tables=_cap)
            if data_catalog:
                data_catalog = enforce_context_cap(data_catalog, max_tables=_cap)
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "table context cap is best-effort; investigating with the uncapped schema context",
                     counter="investigation.context_cap")

        # P2 Agent Context surface: expose the assembled working context (which tables
        # the agent is actually looking at, the token budget they cost, the join edges)
        # so the user has visibility + a handle to trim it. Flag-gated; an extra SSE
        # event is ignored by clients that don't render it, so it's safe to emit.
        if os.getenv("AUGHOR_CONTEXT_SURFACE", "").strip().lower() in ("1", "true", "yes", "on"):
            try:
                from aughor.tools.context_manifest import build_context_manifest
                _manifest = build_context_manifest(data_catalog or schema)
                yield _sse("context_assembled", _manifest.to_dict())
            except Exception:
                logger.debug("context_assembled emit failed (best-effort)", exc_info=True)

        # Prefer structured Data Catalog as the primary schema context
        schema_for_agent = data_catalog if data_catalog else schema

        # Inject the UNIFIED metric grounding so ADA resolves a metric (e.g. "revenue")
        # to the SAME approved SQL the /chat path uses — closing the "revenue means two
        # different things" / "Insight vs Deep disagree" gap. ONE resolver, both paths:
        # the governed catalog (with NEVER rules) + the connection's north-star + verified
        # ontology formulas. No-op when none exist.
        try:
            from aughor.semantic.canonical import unified_metric_grounding
            # Pass the schema we already fetched (full_schema, cached above) so the metric
            # schema-filter doesn't RE-INTROSPECT it — that redundant fetch was ~16s per
            # investigation on big warehouses (profiled), duplicating this same schema.
            # Use the EFFECTIVE scope schema (canvas OR an explicit schema-scoped run) so the
            # connection's GOVERNED north-star metrics for THIS schema are injected (RC2).
            _canon = unified_metric_grounding(connection_id, scope_schema, schema_text=full_schema,
                                              question=question)
            if _canon:
                schema_for_agent = f"{schema_for_agent}\n\n{_canon}"
        except Exception:
            logger.warning("Canonical metrics injection failed (agentic path)", exc_info=True)

        from aughor.agent.graph import build_graph_generic
        # P3 editable plan gate: when on, the explore graph pauses after decomposition
        # (before the expensive fan-out) so the user can review/edit the sub-question
        # plan. Opt-in via AUGHOR_PLAN_GATE; off by default so the path is unchanged.
        _plan_gate = os.getenv("AUGHOR_PLAN_GATE", "").strip().lower() in ("1", "true", "yes", "on")
        # The clarify gate ARMS an interrupt node, and an armed interrupt with nobody
        # to answer it ends the run without a report — so the CALLER decides
        # (`allow_clarify`, default True; a headless consumer passes False). This
        # dissolved the `deep_analysis.clarify_gate` flag (2026-08-06): the posture
        # is a property of the REQUEST, not of the deployment's env.
        _clarify_gate = bool(allow_clarify)
        agent = build_graph_generic(db, hitl=hitl, plan_gate=_plan_gate, clarify_gate=_clarify_gate)

        # ONE structured origin finding — the single source of truth for "what known
        # result is this investigation drilling" (insight_id dossier, or an inline
        # seed_context/seed_sql). The ADA branch reads origin_finding directly
        # (ada_intake anchors its spec on it); for the direct/explore branches we render
        # it into prior_analyses (the channel those read). scan_context stays empty —
        # exploratory_scan overwrites it, so seeding there is a no-op.
        _origin = await _build_origin_finding(connection_id, insight_id, seed_context, seed_sql)
        # Follow-up composition (the quick /chat path already does this via
        # build_history_section). When THIS question is a continuation and no explicit
        # drill seed was given, anchor the run on the previous turn's query — the same
        # origin_finding channel ADA reads + prior_analyses the direct/explore branches
        # read — so "break that down / for luxury only / that one" composes on the base
        # instead of starting from scratch.
        if _origin is None and history:
            from aughor.agent.followup import is_followup
            if is_followup(question):
                _origin = _followup_origin(history)
        _seed_priors = [_render_origin_prose(_origin)] if _origin else []

        # AL-05 (Semantic plane) — resolve the ontology / metrics / profile / KB once here and
        # carry it on the run state, so every node reads one consistent SemanticContext instead of
        # re-consulting ad-hoc. Flag-gated + fail-open in the helper → None (no-op) when off.
        from aughor.semantic.context import resolve_if_enabled as _resolve_semantic
        _semantic_context = _resolve_semantic(question, connection_id,
                                              scope_schema=scope_schema or None,
                                              schema_text=schema_for_agent or "")

        initial_state: AgentState = {
            "question": question, "connection_id": connection_id, "investigation_id": inv_id,
            "trace_id": trace_id,
            # agents.user_defined — persist the active persona so a plan/clarify-gate
            # resume (which never passes through /ask) can re-activate it.
            "agent_id": _current_agent_id(),
            "_allow_clarify": _clarify_gate,
            "schema_context": schema_for_agent, "unresolved_tensions": [], "scan_context": "", "events_context": "",
            "hypotheses": [], "current_hypothesis_idx": 0, "query_history": [], "evidence_scores": [],
            "pitfalls": [], "prior_analyses": _seed_priors, "origin_finding": _origin, "iteration": 0,
            "max_iterations": int(os.getenv("AUGHOR_MAX_ITER", "6")),
            "report": None, "hitl_enabled": hitl, "human_feedback": None,
            "query_mode": None, "route_reasoning": None, "route_confidence": None, "replan_decision": None,
            # Deep-path mode. Defaults to "investigate" so /investigate — the explicit Deep
            # Analysis surface — stays pinned: route_question honors it and never lets the LLM
            # classifier downgrade the run to a 'direct' lookup (live incident: "Where are we
            # losing money?" ran as 3 flat queries with a fake 'direct' hypothesis, zero
            # decomposition). /ask now passes its route verdict through here — normally
            # "investigate", or "explore" when the deterministic wide-question detector fires
            # under explore.route_wide (R9) — reaching the already-built explore wave with no
            # graph change (route_question honors requested_mode ∈ {investigate, explore}).
            "requested_mode": requested_mode,
            "sub_questions": [], "current_subq_idx": 0, "subq_answers": [], "explore_report": None,
            "investigation_phases": [], "answer_report": None, "_ada_intake": None,
            "canvas_id": canvas_id, "canvas_schema_context": canvas_schema_context,
            "scope_schema": scope_schema or "",
            "data_catalog": data_catalog or "",
            "subq_data_portrait": {},
            "final_text_answer": "",
            "semantic_context": _semantic_context,
        }

        import time
        merged = initial_state.copy()
        deadline = time.monotonic() + _TIMEOUT
        timed_out = False
        report_emitted = False  # did the graph reach a terminal synthesis node?

        async for event in _investigation_stream(agent.stream(initial_state, config={"configurable": {"thread_id": inv_id}})):
            # A supervised kernel job (K1) completes SERVER-SIDE even if the streaming client goes away: a
            # tab close or a transient disconnect must not discard a multi-minute investigation — nor write
            # its Trust Receipt outside the job's metering (which is exactly what an early abort did: an
            # empty cost/learning/activation receipt). The run stays bounded by the deadline below, and an
            # explicit stop still cancels through the kernel. (Previously a disconnect failed it as timed_out.)
            if time.monotonic() > deadline:
                timed_out = True
                break
            if "__report_delta__" in event:            # R6 live synthesis prose (flag-gated via the sink)
                yield _sse("report_delta", {"executive_summary": event["__report_delta__"]})
                continue
            if "__ada_progress__" in event:            # P2 live per-dimension progress (flag-gated)
                yield _sse("phase_progress", event["__ada_progress__"])
                continue
            if "__guard_receipt__" in event:           # A4 - a guard made an intervention visible
                yield _sse("guard_receipt", event["__guard_receipt__"])
                continue
            if "__interrupt__" in event:
                # Distinguish a plan-gate pause (P3 — before the explore fan-out) from the
                # ada_synthesize HITL pause by checking which node the graph is about to run.
                try:
                    _next = agent.get_state({"configurable": {"thread_id": inv_id}}).next or ()
                except Exception:
                    _next = ()
                if "clarify_gate" in _next:
                    # P4: a material metric-reading ambiguity — surface the two readings (with their
                    # probed previews) for the user to choose; the run resumes via /feedback.
                    _cp = merged.get("_clarify_pending") or {}
                    yield _sse("clarify_pending", {
                        "investigation_id": inv_id,
                        "subject": _cp.get("subject", ""),
                        "metric_label": _cp.get("metric_label", ""),
                        "question": _cp.get("question", ""),
                        "options": _cp.get("options", []),
                        "previews": _cp.get("previews", []),
                    })
                elif "plan_gate" in _next:
                    _subqs = merged.get("sub_questions", [])
                    _n = len(_subqs)
                    yield _sse("plan_pending", {
                        "investigation_id": inv_id,
                        "sub_questions": [sq.model_dump() if hasattr(sq, "model_dump") else sq for sq in _subqs],
                        "chain_length": _n,
                        # Cheap pre-flight cost estimate (feeds P6): the observed ~8k tokens
                        # per sub-question on the frontier model × chain length.
                        "estimated_tokens": _n * 8000,
                    })
                else:
                    yield _sse("paused", {"investigation_id": inv_id, "hypotheses": [h.model_dump() for h in merged.get("hypotheses", [])], "scores": [s.model_dump() for s in merged.get("evidence_scores", [])]})
                pause_investigation(inv_id)
                yield _sse("done", {})
                return

            node_name = next(iter(event))
            partial = event[node_name] or {}
            merged = {**merged, **partial}

            if node_name == "route_question":
                yield _sse("mode", {"query_mode": merged.get("query_mode"), "route_reasoning": merged.get("route_reasoning"), "route_confidence": merged.get("route_confidence")})
                # For investigate/explore modes, stream clarifying questions after routing
                # so the user sees what the agent is about to probe before it runs expensive queries.
                if merged.get("query_mode") in ("investigate", "explore"):
                    try:
                        from aughor.llm.provider import get_provider  # was unresolved here (latent NameError)
                        _cq_system = (
                            "You are a senior data analyst about to run a deep investigation. "
                            "Given the user's question, ask 1-2 short clarifying questions that would "
                            "sharpen the analysis. Focus on time range, metric definition, or segment. "
                            "Also write a one-sentence note explaining why these matter."
                        )
                        _cq: _ClarifyingQuestions = await asyncio.to_thread(
                            lambda: get_provider("narrator").complete(
                                system=_cq_system,
                                user=f"Question: {question}",
                                response_model=_ClarifyingQuestions,
                                temperature=0.3,
                            )
                        )
                        if _cq.questions:
                            yield _sse("clarifying_questions", {
                                "questions": _cq.questions[:2],
                                "context_note": _cq.context_note,
                            })
                    except Exception as exc:
                        from aughor.kernel.errors import tolerate
                        tolerate(exc, "clarifying-questions generation is best-effort stream enrichment; the investigation continues",
                                 counter="investigation.clarifying_questions")
            elif node_name == "decompose" and merged.get("hypotheses"):
                yield _sse("hypotheses", {"hypotheses": [h.model_dump() for h in merged["hypotheses"]]})
            elif node_name == "plan_and_execute":
                history = merged.get("query_history", [])
                recent = history[-3:]
                pitfalls = merged.get("pitfalls", [])
                yield _sse("queries_executed", {"iteration": merged.get("iteration", 0), "hypothesis_idx": merged.get("current_hypothesis_idx", 0), "queries": [{"sql": r.sql, "row_count": r.row_count, "error": r.error, "stats": [s.model_dump() for s in (r.stats or [])]} for r in recent], "corrections": [p.model_dump() for p in pitfalls[-(len(recent)):]], "stats": [s.model_dump() for r in recent for s in (r.stats or [])]})
            elif node_name == "score_evidence":
                scores = merged.get("evidence_scores", [])
                if scores:
                    yield _sse("score", {"iteration": merged.get("iteration", 0), "score": scores[-1].model_dump(), "hypotheses": [h.model_dump() for h in merged.get("hypotheses", [])]})
            elif node_name in ("ada_intake", "ada_baseline", "ada_cross_section", "ada_decompose", "ada_dimensional", "ada_behavioral"):
                phases = merged.get("investigation_phases", [])
                if phases:
                    yield _sse("phase_complete", {"phase": phases[-1], "all_phases": phases})
            elif node_name == "ada_synthesize" and merged.get("answer_report"):
                ada = merged["answer_report"]
                qh = merged.get("query_history", [])
                yield _sse("tables_used", {"tables": _extract_tables(" ".join(r.sql for r in qh if r.sql))})
                yield _sse("answer_report", {"answer_report": ada, "investigation_id": inv_id, "query_mode": "investigate", "mode": "investigate"})
                try:
                    from aughor.agent.followups import (
                        artifact_from_history, followup_system, followup_user)
                    from aughor.llm.provider import get_provider as _gp
                    # 2.1 — the executed queries are right here in `qh`; this site used
                    # to send only the question and a headline, so the suggestions could
                    # not name a real column.
                    # to_thread, like every other LLM call on this path: `complete` is
                    # synchronous down to a blocking TLS read, and this generator runs ON
                    # the event loop — calling it inline froze the whole API (every route,
                    # /health included) for the length of the round-trip.
                    fq: _FollowUpBase = await asyncio.to_thread(
                        lambda: _gp("narrator").complete(
                            system=followup_system(),
                            user=followup_user(
                                question,
                                headline=(ada.get("headline", "") if isinstance(ada, dict)
                                          else str(ada)[:200]),
                                **artifact_from_history(qh)),
                            response_model=_FollowUpBase))
                    yield _sse("followups", {"questions": fq.questions[:3]})
                except Exception as exc:
                    from aughor.kernel.errors import tolerate
                    tolerate(exc, "follow-up suggestions are best-effort; the report was already emitted",
                             counter="investigation.followups")
                ada_save = dict(ada) if isinstance(ada, dict) else ada
                ada_save["_report_type"] = "investigate"
                if insight_id and isinstance(ada_save, dict):
                    ada_save["origin_insight_id"] = insight_id  # provenance: drilled from this finding
                await asyncio.to_thread(lambda: complete_investigation(inv_id, report=ada_save, hypotheses=merged.get("hypotheses", []), query_history=qh, question=question, connection_id=connection_id, skip_index=False, origin_insight_id=insight_id))
                # K3-wide: the ADA report carries a Trust Receipt too (executed
                # queries → input tables → metric enforcement), so an agentic
                # answer self-justifies like a chat answer and an explorer finding.
                # Wave S2 — a deep answer reports its trusted-query provenance like a quick
                # one. The list comes from the intake that BUILT the prompt
                # (`data_understanding.trusted_used`), never from re-running retrieval here:
                # recomputing would claim a pattern for a run whose grounding step failed
                # silently. Same edge shape as the chat path, so one receipt reader serves both.
                _ada_guards = [("trusted", f"query:{(_t.get('question') or '')[:60]}", _t.get("note"))
                               for _t in ((merged.get("_ada_intake") or {}).get("trusted_used") or [])]
                # to_thread for the same reason as the follow-up call above: the receipt
                # write reaches the ledger AND `note_finding`, whose graph write goes out
                # over TLS. Inline it blocked the loop for seconds at the end of every
                # run — the residual stall that survived fixing the LLM calls.
                _ada_rcpt = await asyncio.to_thread(
                    lambda: _write_answer_receipt(
                        kind="ada_report", natural_key=f"ada:{connection_id}:{inv_id}",
                        question=question, sqls=_ada_sqls(ada) or [r.sql for r in qh if getattr(r, "sql", None)],
                        headline=(ada.get("headline", "") if isinstance(ada, dict) else ""),
                        schema=full_schema, connection_id=connection_id, canvas_id=canvas_id,
                        guard_edges=_ada_guards,
                        payload_extra={"investigation_id": inv_id},
                    ))
                # WP-10: hand the UI the unified receipt id so a deep answer opens the same
                # "Why this number" drawer as a quick answer (GET /receipt/{id}).
                if _ada_rcpt.get("receipt_id"):
                    yield _sse("receipt_id", {"receipt_id": _ada_rcpt["receipt_id"]})
                await asyncio.to_thread(_record_memory, inv_id, connection_id, question, merged)
                report_emitted = True
            elif node_name == "decompose_exploration":
                yield _sse("explore_plan", {"sub_questions": [sq.model_dump() for sq in merged.get("sub_questions", [])]})
            elif node_name == "plan_and_execute_subq":
                history = merged.get("query_history", [])
                idx = merged.get("current_subq_idx", 0)
                subqs = merged.get("sub_questions", [])
                current_subq = subqs[idx] if idx < len(subqs) else None
                recent = [r for r in history if r.hypothesis_id == (current_subq.id if current_subq else "")][-3:]
                yield _sse("queries_executed", {"iteration": merged.get("iteration", 0), "hypothesis_idx": idx, "subq_id": current_subq.id if current_subq else "", "queries": [{"sql": r.sql, "row_count": r.row_count, "error": r.error, "stats": [s.model_dump() for s in (r.stats or [])]} for r in recent], "corrections": [p.model_dump() for p in merged.get("pitfalls", [])[-2:]], "stats": [s.model_dump() for r in recent for s in (r.stats or [])]})
            elif node_name == "reason_over_result":
                answers = merged.get("subq_answers", [])
                if answers:
                    yield _sse("subq_answer", _explore_subq_event(answers[-1]))
            elif node_name == "plan_and_execute_wave":
                # T3-3(b): the parallel-wave path had NO stream branch — a multi-minute silent gap
                # between the plan and the report. Emit one progress event per sub-question the wave
                # just finished (each already carries its own SQL + rows + chart).
                for _a in (partial.get("subq_answers") or []):
                    yield _sse("subq_answer", _explore_subq_event(_a))
            elif node_name == "synthesize_exploration" and merged.get("explore_report"):
                er = merged["explore_report"]
                # T3-3(a): forward EVERY sub-question's evidence (re-read the reduced state, not the
                # clobbered merge). T3-4: attach a shape-verified chart to each.
                answers = await _reduced_subq_answers(agent, inv_id, merged.get("subq_answers", []))
                qh = merged.get("query_history", [])
                sq_raw = [sq.model_dump() for sq in merged.get("sub_questions", [])]
                sa_raw = [a.model_dump() for a in answers]
                yield _sse("tables_used", {"tables": _extract_tables(" ".join(r.sql for r in qh if r.sql))})
                yield _sse("explore_report", {"explore_report": er.model_dump(), "sub_questions": sq_raw, "subq_answers": sa_raw, "query_count": len(qh), "investigation_id": inv_id, "query_mode": "explore"})
                try:
                    from aughor.agent.followups import (
                        artifact_from_history, followup_system, followup_user)
                    from aughor.llm.provider import get_provider as _gp
                    # to_thread — see the ada_synthesize site above: inline, this blocks
                    # the event loop for the whole LLM round-trip.
                    fqx: _FollowUpBase = await asyncio.to_thread(
                        lambda: _gp("narrator").complete(
                            system=followup_system(),
                            user=followup_user(question, headline=er.headline,
                                               **artifact_from_history(qh)),
                            response_model=_FollowUpBase))
                    yield _sse("followups", {"questions": fqx.questions[:3]})
                except Exception as exc:
                    from aughor.kernel.errors import tolerate
                    tolerate(exc, "follow-up suggestions are best-effort; the report was already emitted",
                             counter="investigation.followups")
                explore_save = {"_report_type": "explore", **er.model_dump(), "sub_questions": sq_raw, "subq_answers": sa_raw}
                await asyncio.to_thread(lambda: complete_investigation(inv_id, report=explore_save, hypotheses=[], query_history=qh, question=question, connection_id=connection_id, skip_index=False))
                await asyncio.to_thread(_record_memory, inv_id, connection_id, question, merged)
                report_emitted = True
            elif node_name == "synthesize" and merged.get("report"):
                qh = merged.get("query_history", [])
                yield _sse("tables_used", {"tables": _extract_tables(" ".join(r.sql for r in qh if r.sql))})
                yield _sse("report", {"report": merged["report"].model_dump(), "hypotheses": [h.model_dump() for h in merged.get("hypotheses", [])], "query_count": len(qh), "query_history": [{"hypothesis_id": r.hypothesis_id, "sql": r.sql, "row_count": r.row_count, "error": r.error, "columns": r.columns, "rows": r.rows[:50], "stats": [s.model_dump() for s in (r.stats or [])]} for r in qh], "investigation_id": inv_id, "query_mode": merged.get("query_mode")})
                try:
                    from aughor.agent.followups import (
                        artifact_from_history, followup_system, followup_user)
                    from aughor.llm.provider import get_provider as _gp
                    rep = merged["report"]
                    summary = getattr(rep, "summary", "") or getattr(rep, "headline", "")
                    # to_thread — see the ada_synthesize site above: inline, this blocks
                    # the event loop for the whole LLM round-trip.
                    fqr: _FollowUpBase = await asyncio.to_thread(
                        lambda: _gp("narrator").complete(
                            system=followup_system(),
                            user=followup_user(question, headline=str(summary)[:300],
                                               **artifact_from_history(qh)),
                            response_model=_FollowUpBase))
                    yield _sse("followups", {"questions": fqr.questions[:3]})
                except Exception as exc:
                    from aughor.kernel.errors import tolerate
                    tolerate(exc, "follow-up suggestions are best-effort; the report was already emitted",
                             counter="investigation.followups")
                await asyncio.to_thread(lambda: complete_investigation(inv_id, report=merged["report"], hypotheses=merged.get("hypotheses", []), query_history=qh, question=question, connection_id=connection_id, skip_index=merged.get("query_mode") == "direct", origin_insight_id=insight_id))
                await asyncio.to_thread(_record_memory, inv_id, connection_id, question, merged)
                report_emitted = True

        if timed_out:
            # Even on timeout, salvage a partial report from gathered evidence first.
            salvaged = await asyncio.to_thread(
                _try_salvage, merged, inv_id, question, connection_id, schema=full_schema)
            if salvaged:
                yield salvaged
            else:
                yield _sse("error", _error_event(
                    message=f"Investigation timed out after {_TIMEOUT}s.", reason="run_timeout"))
                fail_investigation(inv_id, status="timed_out")
        elif not report_emitted:
            # The graph terminated without reaching a synthesis node — e.g. every
            # query errored and the loop exhausted its iterations. First try a
            # best-effort synthesis from whatever evidence exists; only if there's
            # genuinely nothing to salvage do we surface a terminal stall message.
            salvaged = await asyncio.to_thread(
                _try_salvage, merged, inv_id, question, connection_id, schema=full_schema)
            if salvaged:
                yield salvaged
            else:
                yield _sse("error", _error_event(message=_stall_summary(merged), reason="stalled"))
                fail_investigation(inv_id, status="failed")

    except Exception as e:
        # An unhandled node exception still shouldn't lose partial work — salvage
        # a best-effort report from gathered evidence before surfacing the error.
        # to_thread: salvage runs a synthesis, so inline it would block the loop on the
        # very path where the run is already in trouble. Safe to await here — this
        # catches Exception, so a CancelledError teardown never reaches it.
        salvaged = await asyncio.to_thread(
            _try_salvage, merged, inv_id, question, connection_id, schema=full_schema)
        if salvaged:
            yield salvaged
        else:
            fail_investigation(inv_id, status="failed")
            yield _sse("error", _error_event(e))
    finally:
        # Orphan reconcile. If we reach here with the row still 'running', no
        # terminal handler ran — the dominant cause is a client disconnect:
        # Starlette cancels the SSE coroutine with asyncio.CancelledError, which
        # is a BaseException and so slips past every `except Exception` above,
        # straight into this finally. Without this, the investigation orphans in
        # 'running' (no terminal event, no UI resolution) until the 60-min sweep.
        # fail_investigation journals the transition, so the event spine stays
        # consistent. Runs FIRST so it survives even if later cleanup is cut short.
        try:
            _inv_now = get_investigation(inv_id)
            if _inv_now and _inv_now.get("status") == "running":
                fail_investigation(inv_id, status="failed")
        except Exception:
            logger.debug("finally orphan-reconcile failed", exc_info=True)
        _telemetry.end_trace(trace_id)
        for _e in _paused_explorers:
            try:
                _e.resume()
                _e._paused_by_investigation = False
            except Exception as exc:
                from aughor.kernel.errors import tolerate
                tolerate(exc, "explorer resume after investigation is best-effort; the supervisor backstop re-resumes investigation-paused explorers",
                         counter="investigation.explorer_resume")
        db.close()
        yield _sse("done", {})


# ── HITL resume streaming ─────────────────────────────────────────────────────

def _filter_kept_subquestions(subqs: list, keep_idx: list[int]) -> list:
    """Keep only the sub-questions at the given indices, preserving order (P3 plan edit).
    Out-of-range indices are ignored; the caller treats an empty result as 'no valid edit'
    (and won't wipe the plan) rather than resuming an empty investigation."""
    keep = set(keep_idx)
    return [sq for i, sq in enumerate(subqs) if i in keep]


def _apply_clarify_choice(merged: dict, clarify_choice: Optional[str], connection_id: str) -> dict:
    """P4 clarify resume: bind the metric to the reading the user chose and crystallize the choice.
    Returns a state patch — the updated `_ada_intake` (metric_sql/metric_is_ratio bound to the chosen
    reading) and a cleared `_clarify_pending` (so the passthrough gate falls through to the real branch
    on resume). Returns {} when nothing is pending. An unmatched/absent choice defaults to the FIRST
    reading (the governed one). Fail-open — the ledger write never blocks the resume."""
    pending = merged.get("_clarify_pending") or {}
    readings = pending.get("readings") or []
    if not readings:
        return {}
    matched = next((r for r in readings if r.get("label") == clarify_choice), None)
    chosen = matched if matched is not None else readings[0]
    patch: dict = {"_clarify_pending": None}
    if chosen.get("sql"):
        intake = dict(merged.get("_ada_intake") or {})
        intake["metric_sql"] = chosen["sql"]
        intake["metric_is_ratio"] = bool(chosen.get("is_ratio"))
        patch["_ada_intake"] = intake
    if matched is None:
        # The run still binds the governed default so it can finish — but that is OUR
        # fallback, not the user's answer, and it must not be written down as one.
        # `crystallize_user_choice` records at USER authority, which outranks a probe
        # and persists for the whole connection: a stale or garbled resume would
        # durably teach the system a reading nobody picked. Provenance is required,
        # and there is no provenance here.
        logger.info("[clarify] resume choice %r matched no reading; binding the governed "
                    "default for this run WITHOUT crystallizing it", clarify_choice)
        from aughor.stats import bump
        bump("deep_analysis.clarify_unmatched")
        return patch
    try:
        from aughor.org.context import current_org_id
        from aughor.semantic.ambiguity_ledger import Reading, crystallize_user_choice
        crystallize_user_choice(
            connection_id, pending.get("subject") or "", chosen.get("label") or "",
            org_id=current_org_id() or "", resolved_sql=chosen.get("sql") or "",
            readings=[Reading(label=r.get("label", ""), sql_evidence=r.get("sql", "")) for r in readings])
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "crystallizing the clarify choice is best-effort; the run still binds the reading",
                 counter="deep_analysis.clarify_crystallize")
    return patch


async def _stream_resume(inv_id: str, feedback: str, request: Request,
                         keep_subquestions: Optional[list[int]] = None,
                         clarify_choice: Optional[str] = None) -> AsyncGenerator[str, None]:
    inv = get_investigation(inv_id)
    if not inv:
        yield _sse("error", _error_event(message="Investigation not found", reason="not_found"))
        yield _sse("done", {})
        return
    if inv.get("status") != "paused":
        yield _sse("error", _error_event(
            message=f"Investigation is not paused (status: {inv.get('status')})", reason="invalid_state"))
        yield _sse("done", {})
        return
    # Resume with the canvas scope (declared schema + derived owning-schema pin) if applicable.
    from aughor.canvas.scope import resolve_execution_scope
    try:
        db = resolve_execution_scope(inv["connection_id"], inv.get("canvas_id")).open()
    except Exception as e:
        yield _sse("error", _error_event(e))
        yield _sse("done", {})
        return

    try:
        from aughor.agent.graph import build_graph_generic
        agent = build_graph_generic(db, hitl=True)
        config = {"configurable": {"thread_id": inv_id}}
        checkpoint = agent.get_state(config)
        merged: dict = dict(checkpoint.values) if checkpoint else {}
        _patch: dict = {"human_feedback": feedback}
        # P3: apply the user's plan edit — keep only the chosen sub-questions before the
        # fan-out resumes. Guard against an empty plan (a "reject all" is a cancel, not a
        # resume). sub_questions is a plain (replaceable) state field, so update_state sets it.
        if keep_subquestions is not None:
            _kept = _filter_kept_subquestions(merged.get("sub_questions", []), keep_subquestions)
            if _kept:
                _patch["sub_questions"] = _kept
                _patch["current_subq_idx"] = 0
        # P4 clarify gate: bind the metric to the reading the user chose, clear the pending clarify (so
        # the passthrough gate falls through to the real branch), and crystallize the choice to the
        # Ambiguity Ledger (source=user) so this connection never re-asks. Fail-open: an unmatched choice
        # just resumes on the parsed reading.
        _clar_patch = _apply_clarify_choice(merged, clarify_choice, inv.get("connection_id") or "")
        if _clar_patch:
            _patch.update(_clar_patch)
        agent.update_state(config, _patch)

        import time
        _TIMEOUT = int(os.getenv("AUGHOR_TIMEOUT_SECONDS", "600"))
        deadline = time.monotonic() + _TIMEOUT

        async for event in _investigation_stream(agent.stream(None, config=config)):
            # Same K1 rule: the resumed job completes server-side despite a client disconnect (bounded by
            # the deadline; explicit stop still cancels). An early abort here wrote an empty receipt too.
            if time.monotonic() > deadline:
                yield _sse("error", _error_event(
                    message="Timed out waiting for synthesis.", reason="run_timeout"))
                fail_investigation(inv_id, status="timed_out")
                return
            if "__report_delta__" in event:            # R6 live synthesis prose (flag-gated via the sink)
                yield _sse("report_delta", {"executive_summary": event["__report_delta__"]})
                continue
            if "__ada_progress__" in event:            # P2 live per-dimension progress (flag-gated)
                yield _sse("phase_progress", event["__ada_progress__"])
                continue
            if "__guard_receipt__" in event:           # A4 - a guard made an intervention visible
                yield _sse("guard_receipt", event["__guard_receipt__"])
                continue
            if "__interrupt__" in event:
                continue
            node_name = next(iter(event))
            # A resumed interrupt node (e.g. the P3 plan_gate) streams a None value for
            # the node it resumes into; guard the merge so it doesn't blow up the resume.
            merged = {**merged, **(event[node_name] or {})}
            if node_name == "synthesize" and merged.get("report"):
                qh = merged.get("query_history", [])
                yield _sse("report", {"report": merged["report"].model_dump(), "hypotheses": [h.model_dump() for h in merged.get("hypotheses", [])], "query_count": len(qh), "query_history": [{"hypothesis_id": r.hypothesis_id, "sql": r.sql, "row_count": r.row_count, "error": r.error, "columns": r.columns, "rows": r.rows[:50], "stats": [s.model_dump() for s in (r.stats or [])]} for r in qh], "investigation_id": inv_id})
                complete_investigation(inv_id, report=merged["report"], hypotheses=merged.get("hypotheses", []), query_history=qh, question=inv["question"], connection_id=inv.get("connection_id", ""))
                _record_memory(inv_id, inv.get("connection_id", ""), inv["question"], merged)
            elif node_name == "reason_over_result":
                # P3 plan-gate resume streams the EXPLORE path too — surface each
                # sub-question answer as it lands (this loop only handled the ADA path before).
                answers = merged.get("subq_answers", [])
                if answers:
                    yield _sse("subq_answer", _explore_subq_event(answers[-1]))
            elif node_name == "plan_and_execute_wave":
                for _a in (event[node_name] or {}).get("subq_answers", []) or []:
                    yield _sse("subq_answer", _explore_subq_event(_a))
            elif node_name == "synthesize_exploration" and merged.get("explore_report"):
                er = merged["explore_report"]
                answers = await _reduced_subq_answers(agent, inv_id, merged.get("subq_answers", []))
                qh = merged.get("query_history", [])
                sq_raw = [sq.model_dump() for sq in merged.get("sub_questions", [])]
                sa_raw = [a.model_dump() for a in answers]
                yield _sse("tables_used", {"tables": _extract_tables(" ".join(r.sql for r in qh if r.sql))})
                yield _sse("explore_report", {"explore_report": er.model_dump(), "sub_questions": sq_raw, "subq_answers": sa_raw, "query_count": len(qh), "investigation_id": inv_id, "query_mode": "explore"})
                explore_save = {"_report_type": "explore", **er.model_dump(), "sub_questions": sq_raw, "subq_answers": sa_raw}
                complete_investigation(inv_id, report=explore_save, hypotheses=[], query_history=qh, question=inv["question"], connection_id=inv.get("connection_id", ""))
                _record_memory(inv_id, inv.get("connection_id", ""), inv["question"], merged)
    except Exception as e:
        fail_investigation(inv_id, status="failed")
        yield _sse("error", _error_event(e))
    finally:
        # Same orphan-reconcile as the main stream: a client disconnect raises
        # CancelledError (BaseException) past the except handlers, so fail any row
        # still 'running' here — keeps it off the 60-min sweep and on the spine.
        try:
            _inv_now = get_investigation(inv_id)
            if _inv_now and _inv_now.get("status") == "running":
                fail_investigation(inv_id, status="failed")
        except Exception:
            logger.debug("resume finally orphan-reconcile failed", exc_info=True)
        db.close()
        yield _sse("done", {})


# ── Routes ────────────────────────────────────────────────────────────────────

async def _metered_stream(gen: AsyncGenerator[str, None],
                          budget: tuple | None = None) -> AsyncGenerator[str, None]:
    """Meter a synchronous streaming answer + enforce its budget in-context. The
    quick-answer path is not a kernel job, so it has no JobKernel._run (to flush its
    compute) and no heartbeat (to enforce a budget). We set the per-run accumulator
    for the whole iteration — the receipt reads it via metering.snapshot() — and arm
    the Insight agent's budget; the LLM funnel raises BudgetExceeded (a BaseException,
    so it unwinds past the answer path's fail-open try/excepts), surfaced here as a
    clean error event. Output is otherwise passed through unchanged."""
    from aughor.kernel import metering
    token = metering.start()
    btoken = metering.set_budget(*budget) if budget else None
    try:
        async for chunk in gen:
            yield chunk
    except metering.BudgetExceeded as be:
        yield _sse("error", _error_event(
            be, message=f"Answer stopped — {be.reason} exceeded. "
                        f"Raise the Insight agent's budget in Fleet → Agents.",
            reason="budget_exceeded"))
    finally:
        if btoken is not None:
            metering.clear_budget(btoken)
        metering.reset(token)


def _insight_budget(conn_id: str):
    """Resolve the Insight agent's Org/workspace-governed token + time budget."""
    try:
        from aughor.kernel.agents import effective_governance
        from aughor.workspace.store import workspace_for_connection
        gov = effective_governance("insight", workspace_for_connection(conn_id))
        return (gov.token_budget, gov.time_budget_s)
    except Exception:
        return None


def _resolve_conn(req) -> str:
    """A canvas-scoped request resolves to the canvas's underlying connection."""
    conn_id = req.connection_id
    if req.canvas_id:
        from aughor.canvas.store import resolve_connection_id
        resolved = resolve_connection_id(req.canvas_id)
        if resolved:
            conn_id = resolved
    return conn_id


@router.post("/chat")
async def chat_endpoint(req: ChatRequest, request: Request):
    conn_id = _resolve_conn(req)
    # The legacy door gets the same session log as /ask — it has its own endpoint
    # rather than going through build_ask_stream, so without this it stays dark.
    stream = stream_with_session_log(
        _stream_chat(req.question, conn_id, req.history,
                     session_id=req.session_id, canvas_id=req.canvas_id),
        question=req.question, conn_id=conn_id, door="chat",
        canvas_id=req.canvas_id or "")
    return StreamingResponse(
        _metered_stream(stream, budget=_insight_budget(conn_id)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


_STREAM_END = object()   # queue sentinel: the investigation generator finished


async def _investigation_job_streamed(
    question: str,
    connection_id: str,
    request: Request,
    *,
    hitl: bool = False,
    skip_cache: bool = False,
    canvas_id: Optional[str] = None,
    schema_scope: Optional[str] = None,
    seed_sql: Optional[str] = None,
    seed_context: str = "",
    insight_id: Optional[str] = None,
    deep: bool = False,
    history: Optional[list] = None,
    requested_mode: str = "investigate",
    purpose: str = "",
    allow_clarify: bool = True,
) -> AsyncGenerator[str, None]:
    """Run the investigation as a first-class supervised kernel job (K1).

    `_stream_investigation` is left UNCHANGED — it just executes inside the job's
    task instead of the request coroutine, with its SSE events bridged to the
    client over an in-process queue. That alone makes a live investigation a real
    job: a `job.state` PENDING→RUNNING→SUCCEEDED|FAILED|CANCELLED lifecycle on the
    event spine, a heartbeat (orphan detection), kernel-driven cancellation, and
    artifacts auto-stamped with `created_by_job` (the contextvar is set around the
    coro) — the same supervision the explorer already has. Latency is unchanged:
    the queue hop is in-process and `await queue.put` preserves natural backpressure.
    """
    from aughor.kernel.jobs import kernel
    queue: asyncio.Queue = asyncio.Queue()

    async def _drive() -> None:
        try:
            async for sse in _stream_investigation(
                question, connection_id, request,
                hitl=hitl, skip_cache=skip_cache, canvas_id=canvas_id,
                schema_scope=schema_scope, seed_sql=seed_sql, seed_context=seed_context,
                insight_id=insight_id, deep=deep, history=history,
                requested_mode=requested_mode, purpose=purpose,
                allow_clarify=allow_clarify,
            ):
                await queue.put(sse)
        finally:
            # Always release the client drainer, even on cancellation/error.
            queue.put_nowait(_STREAM_END)

    job_id = await kernel().submit(
        "investigation", _drive,
        conn_id=connection_id, canvas_id=canvas_id,
        # R10 — the starter's purpose tag rides the job row, so Fleet/jobs
        # are queryable per purpose.
        payload={"question": question[:200], **({"purpose": purpose} if purpose else {})},
    )
    logger.debug("investigation job %s submitted", job_id)
    while True:
        item = await queue.get()
        if item is _STREAM_END:
            break
        yield item


@router.post("/investigate", dependencies=[gate(Capability.DEEP_ANALYSIS)])
async def investigate(req: InvestigateRequest, request: Request):
    conn_id = _resolve_conn(req)
    return StreamingResponse(
        _investigation_job_streamed(
            req.question, conn_id, request,
            hitl=req.hitl, skip_cache=req.skip_cache, canvas_id=req.canvas_id,
            schema_scope=req.schema_name, seed_sql=req.seed_sql, seed_context=req.seed_context,
            insight_id=req.insight_id, deep=req.escalate, history=req.history,
            allow_clarify=req.allow_clarify,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _federation_eligible(req) -> bool:
    """Whether a ``/ask`` turn may auto-federate: only a truly FRESH auto turn qualifies — not a depth
    override, deep-drill, dossier, canvas follow-up, conversational follow-up (``history``), or a
    clarify-answer (``skip_clarify``). Follow-ups compose on the prior turn via the normal path, and a
    clarify-answer carries a refinement the federated planner wouldn't see — so federation is first-turn
    only. Flag-gated on ``federation.planner`` (default off), checked first for the short-circuit."""
    from aughor.kernel.flags import flag_enabled
    return bool(
        flag_enabled("federation.planner") and req.depth == "auto"
        and not req.escalate and not req.insight_id and not req.canvas_id
        and not req.history and not req.skip_clarify
    )


def _converse_eligible(req, route) -> bool:
    """Whether this ``/ask`` turn may be served by the converse body instead of the quick one.

    Flag first, for the short-circuit: ``converse_available()`` reads ``ask.converse`` at
    CALL time (never at import), which is what keeps the experiment flippable in a running
    process — a module-level read turns ``monkeypatch.setenv`` into a no-op and is how tests
    once spent the real LLM budget.

    CI-4 shrank the carve-outs, one at a time as the plan requires. The seeded-SQL and
    dossier-drill flags stopped being bypasses: such a turn now carries its
    origin finding INTO the conversation as context (see ``_origin_prose_for``), and the
    conversation — which owns a ``deep_analysis`` tool — decides whether the question
    needs the full investigation. A dossier drill is recognisable on the route as
    ``forced == "dossier"``; it is deep by ROUTING convention, not because the user asked
    for a report, which is exactly why the conversation may take it.

    Two carve-outs remain, each with a live reason. ``escalate`` is the user's explicit
    "investigate deeper" — a command, not a question, and spending a model turn to
    re-decide it would be latency with no information. A router-chosen ``deep`` route
    (minus the dossier case) keeps the dedicated body until the investigation's frames
    can stream through a converse turn (the CI-6a renderer is the missing half).
    """
    from aughor.agent.converse_tools import converse_available
    if not converse_available() or req.escalate:
        return False
    return route.depth != "deep" or route.forced == "dossier"


async def _origin_prose_for(req, conn_id: str) -> str:
    """The origin finding a seeded/dossier turn carries, rendered for the conversation.

    One source of truth, two readers: ``_build_origin_finding`` is the SAME resolver the
    deep path anchors on, and ``_render_origin_prose`` the same rendering the direct
    branches inject — so the conversation is handed exactly what the investigation
    would have been, never a re-derivation. Empty for a cold-start turn, and
    best-effort: a finding that cannot be resolved must degrade the turn to a plain
    conversation, not fail it.
    """
    if not (req.insight_id or req.seed_sql or req.seed_context):
        return ""
    try:
        origin = await _build_origin_finding(conn_id, req.insight_id,
                                             req.seed_context or "", req.seed_sql)
        return _render_origin_prose(origin) if origin else ""
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "an unresolvable origin finding degrades the turn to a plain "
                 "conversation", counter="ask.converse_origin")
        return ""


def _federation_candidates(conn_id: str, cap: int = 15) -> list[str]:
    """Org-visible connection ids (the current one first) — the candidate pool for cross-source
    selection on the ``/ask`` path. Bounded so a large connection roster can't blow up the selector."""
    from aughor.db.registry import list_connections
    try:
        from aughor.security.authz import org_visible_conn_ids
        visible = org_visible_conn_ids()
    except Exception:
        visible = None
    ids: list[str] = [conn_id] if conn_id else []
    for c in list_connections():
        cid = c.get("id")
        if not cid or cid in ids:
            continue
        if visible is not None and cid not in visible:
            continue
        ids.append(cid)
    return ids[:cap]


def _conn_names(conn_ids: list[str]) -> list[str]:
    from aughor.db.registry import list_connections
    by_id = {c.get("id"): (c.get("name") or c.get("id")) for c in list_connections()}
    return [by_id.get(cid, cid) for cid in conn_ids]


async def _stream_federated(question: str, sel) -> AsyncGenerator[str, None]:
    """Answer a cross-source question via the federated planner and stream it as ``/ask`` events.

    Emits a federated ``route`` receipt (transparency: which sources, and the terms each grounded),
    then the merged table using the same primitives the quick path uses (columns/rows/headline/sql/
    tables_used), so it renders in the existing answer surface."""
    from aughor.agent.federated_planner import answer_federated

    names = _conn_names(sel.conn_ids)
    yield _sse("route", {
        "depth": "federated", "mode": "federated", "tier": "complex",
        "score": 1.0, "confidence": 1.0, "ambiguous": False,
        "why": f"Question spans {len(sel.conn_ids)} sources ({', '.join(names)}); answering across them.",
        "alternatives": ["quick"], "forced": None, "downgraded_from": None,
        "sources": sel.conn_ids, "matched": sel.matched,
    })
    # answer_federated catches planning errors and the engine is fail-safe, but a stale conn id (deleted
    # between selection and execution) could still raise on open — never let that break the /ask stream.
    try:
        ans = await asyncio.to_thread(
            answer_federated, question, sel.conn_ids, reconcile=True,
        )
        r = ans.result
    except Exception as exc:  # noqa: BLE001 — the stream must always end cleanly
        from aughor.kernel.errors import tolerate
        tolerate(exc, "federated answer failed after routing; stream an honest error",
                 counter="ask.federation_answer_failed")
        yield _sse("headline", {"headline": f"Cross-source answer failed — {str(exc)[:120]}"})
        yield _sse("done", {})
        return
    if r.error:
        yield _sse("headline", {"headline": f"Cross-source answer unavailable — {r.error}"})
        yield _sse("done", {})
        return
    streamed = r.rows[:10000]
    more = f" (showing first {len(streamed):,})" if r.row_count > len(streamed) else ""
    yield _sse("columns", {"columns": r.columns})
    yield _sse("rows", {"rows": streamed})
    yield _sse("headline",
               {"headline": f"Answered across {len(names)} sources ({', '.join(names)}) — {r.row_count:,} rows{more}."})
    yield _sse("sql", {"sql": r.sql})
    yield _sse("tables_used", {"tables": names})
    yield _sse("done", {})


# ── Overview / "interesting facts about this schema" (the default first-look) ──
# The widest-possible question, answered as a deterministic profile of the
# whole dataset, not an investigation of one metric. Detection is a phrasing regex AND
# the ABSENCE of a named metric/entity/time window — so a specific question still routes
# normally. Fully deterministic (no LLM) → graduated to Auto (flag `ask.overview`).
_OVERVIEW_RE = re.compile(
    r"\b(interesting facts?|tell me about|what'?s (notable|interesting|here|in "
    r"(this|the))|describe (this|the) (data|schema|dataset|tables?)|summar(y|ize|ise)"
    r"|overview of|show me around|what can i ask|explore (this|the) (data|schema|dataset)"
    r"|get to know|first look|what'?s in (this|the) (data|schema|dataset))\b", re.I)


_OVERVIEW_GENERIC = re.compile(
    r"\b(this|that|the|these|those|my|our|data|dataset|datasets|schema|table|tables|"
    r"here|about|me|show|give|tell|please|some|any)\b", re.I)


def _is_overview_question(question: str) -> bool:
    q = (question or "").strip()
    if not _OVERVIEW_RE.search(q):
        return False
    # signal-absence guard: strip the overview phrasing + generic dataset nouns, then
    # require NO leftover metric/entity/time — so "tell me about REVENUE" (a real ask)
    # still routes normally while "what's notable in this dataset" stays an overview.
    residual = _OVERVIEW_GENERIC.sub(" ", _OVERVIEW_RE.sub(" ", q))
    from aughor.semantic.answer_resolution import (
        entity_candidates, question_measures, requested_time_grain)
    return (not question_measures(residual) and not entity_candidates(residual)
            and requested_time_grain(residual) is None)


def _overview_eligible(req) -> bool:
    """Whether a ``/ask`` turn is a widest-scope overview ask. A fresh auto turn (may be
    in a canvas — that's the schema scope) whose phrasing asks for an overview and names
    no metric/entity/time window. Self-gating: the four request predicates below plus
    the question shape ARE the trigger, which is why it needed no flag of its own."""
    return bool(
        req.depth == "auto"
        and not req.escalate and not req.insight_id and not req.history and not req.skip_clarify
        and _is_overview_question(req.question)
    )


async def _stream_overview(question: str, conn_id: str, req) -> AsyncGenerator[str, None]:
    """Stream the deterministic interesting-facts tour as ``/ask`` events. Resolves the
    canvas/connection scope exactly like ``_stream_chat`` (so tables + eff_schema are
    right), builds the fact tour off the event loop, and emits one ``overview_report``.
    No LLM, no metering — bounded and deterministic. Any failure degrades to an honest
    headline, never a dead-ended turn."""
    from aughor.canvas.scope import resolve_execution_scope
    from aughor.tools.schema import build_canvas_schema_context, parse_schema_tables
    yield _sse("route", {
        "depth": "overview", "mode": "overview", "tier": "overview",
        "score": 1.0, "confidence": 1.0, "ambiguous": False,
        "why": "a broad overview — profiling the whole dataset for its most notable facts",
        "alternatives": ["quick", "deep"], "forced": None, "downgraded_from": None,
    })
    try:
        _es = resolve_execution_scope(conn_id, req.canvas_id,
                                      schema_context_builder=build_canvas_schema_context)
        cid = _es.connection_id
        eff_schema = _es.eff_schema or ""
        db = _es.open()
    except Exception as e:
        yield _sse("headline", {"headline": f"Couldn't open the connection for an overview: {e}"})
        yield _sse("done", {})
        return

    # scoped table set: the canvas's tables, else every table across the connection's schema(s).
    # Keep names schema-QUALIFIED — on a multi-schema connection (a workspace with `main` +
    # `luxexperience`) stripping the qualifier and profiling bare names either collides same-named
    # tables across schemas or fails to resolve non-default-schema tables, fixating the tour on one
    # schema. build_overview._qual passes qualified names through untouched, so every schema is
    # profiled and each fact card carries its true `schema.table`.
    tables = list(_es.tables) if (_es.tables and not _es.is_full_schema) else []
    if not tables:
        try:
            sch = await asyncio.to_thread(_get_schema_cached, cid, db)
            tables = list(parse_schema_tables(sch).keys())
        except Exception:
            tables = []

    rep = None
    try:
        from aughor.overview import build_overview
        from aughor.overview.drills import load_priors
        # Learned per-connection prior: fold this connection's "explore this fact" drill
        # history into the ranking so the tour surfaces the lenses/tables this user explores.
        _priors = await asyncio.to_thread(load_priors, cid)
        # R14 — fold mined query popularity into the same table prior (the boost is
        # saturating + capped, so a hot table nudges, never buries a notable fact).
        try:
            from aughor.sql.popularity import merge_popularity_into_priors
            _priors = await asyncio.to_thread(merge_popularity_into_priors, _priors, cid)
        except Exception as _pop_exc:
            from aughor.kernel.errors import tolerate as _tolerate
            _tolerate(_pop_exc, "popularity prior fold is best-effort",
                      counter="obs.popularity", conn_id=cid or None)
        rep = await asyncio.to_thread(build_overview, db, cid, tables,
                                      schema=eff_schema, entity_hint="rows", limit=8, priors=_priors)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "overview fact tour is best-effort; degrading to an honest headline",
                 counter="ask.overview_failed")

    if rep is not None and rep.facts:
        _report = rep.to_dict()
        yield _sse("overview_report", {"overview_report": _report})
        yield _sse("headline", {"headline": rep.summary})
        # Persist the tour so it survives reload + appears in canvas History (the turn is
        # otherwise ephemeral — the reason the cards vanished on refresh). Best-effort.
        try:
            await asyncio.to_thread(lambda: save_chat_turn(
                question=question, connection_id=cid, headline=rep.summary[:2000],
                sql="", session_id=getattr(req, "session_id", "") or "",
                columns=[], rows=[], chart_type="none", tables_used=[], intent="",
                approach=[], canvas_id=req.canvas_id, overview_report=_report))
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "overview turn save is best-effort; the tour was already streamed",
                     counter="ask.overview_save")
    else:
        yield _sse("headline", {"headline": (
            "I couldn't surface overview facts for this dataset — try asking about a "
            "specific measure, or open a table in the catalog.")})
    yield _sse("done", {})


class OverviewDrillRequest(BaseModel):
    """Capture signal for the learned overview prior: the user clicked "explore this fact"
    on an overview card. ``lens``/``table`` are the card's coordinates; the connection (a
    canvas pins its own) scopes the prior read back by the next tour."""
    connection_id: str = ""
    canvas_id: Optional[str] = None
    lens: str = ""
    table: str = ""


@router.post("/overview/drill", status_code=204)
async def record_overview_drill(req: OverviewDrillRequest) -> None:
    """Record an overview "explore this fact" drill so this connection's next tour learns
    which lenses/tables the user explores (``overview.drills`` → ``build_overview`` priors).
    Fire-and-forget from the client; best-effort and never raises. Resolves the connection
    the same way ``_stream_overview`` does, so capture and read-back share one key."""
    from aughor.canvas.scope import resolve_execution_scope
    from aughor.overview.drills import record_drill
    try:
        cid = resolve_execution_scope(req.connection_id, req.canvas_id).connection_id
    except Exception:
        cid = req.connection_id
    await asyncio.to_thread(record_drill, cid, req.lens, req.table)


async def _stream_ask(req: "AskRequest", request: Request, conn_id: str) -> AsyncGenerator[str, None]:
    """The unified door: decide depth, emit the `route` receipt, then delegate to a body.

    THREE bodies now, not two: quick, deep (ADA/explore), and — behind `ask.converse`,
    an EXPERIMENT that is off by default — the conversational one. The two originals are
    unchanged; converse swaps which body answers a quick turn, never which door it
    entered by, so the overview branch, the clarify gate and federation all still run
    first exactly as they did.

    The depth call is license-safe — a deep route degrades to quick when the connection
    lacks DEEP_ANALYSIS — and the legacy escalation and dossier-drill flags still reach
    the deep body through this one door.
    """
    from aughor.agent.ask_router import decide_ask_route
    from aughor.licensing import has_capability

    # I4 — if this turn is the user ANSWERING a clarify (a reading chosen from the chips),
    # crystallize that choice into the Ambiguity Ledger (source=user) BEFORE we answer, so the
    # resolution is an authoritative prior on this turn and every future one — the class never
    # re-ambiguates on this connection. Best-effort.
    if req.clarify_reading:
        try:
            from aughor.org.context import current_org_id
            from aughor.semantic.ambiguity_ledger import crystallize_user_choice
            crystallize_user_choice(
                conn_id, req.clarify_subject or req.question, req.clarify_reading,
                org_id=current_org_id() or "", clarify_source=req.clarify_source)
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "clarify-choice crystallization is best-effort",
                     counter="ask.clarify_crystallize")

    # Ask-vs-guess (Phase 3): when the question is materially ambiguous and this is a
    # fresh auto turn (not an explicit depth override, deep-drill, dossier, or a turn
    # already answering a clarification), ask ONE targeted question instead of guessing.
    # Budget is one ask/turn — the user's answer comes back with skip_clarify set, which
    # is the per-turn bypass a caller actually uses.
    # Overview / "interesting facts about this schema" — the widest-scope ask. Checked
    # BEFORE the clarify gate on purpose: an under-specified "tell me about this data" is
    # exactly the case where an overview IS the answer, not a clarifying question.
    if _overview_eligible(req):
        async for _ev in _stream_overview(req.question, conn_id, req):
            yield _ev
        return

    if (req.depth == "auto" and not req.escalate and not req.insight_id
            and not req.skip_clarify):
        from aughor.agent.clarify import assess_clarification
        decision = assess_clarification(req.question)
        if decision.should_ask:
            yield _sse("clarify", decision.to_event())
            yield _sse("done", {})
            return

    # Cross-source federation (Rec 2 answer-path): on a fresh auto turn, if the question spans MULTIPLE of
    # the org's connections, answer across them via the federated planner instead of the single-connection
    # path. A deterministic selector (no LLM) decides; only a genuinely multi-source question federates.
    # Flag-gated on `federation.planner` → default off = byte-identical. Fail-safe: any error falls through
    # to the normal routing below.
    if _federation_eligible(req):
        try:
            from aughor.agent.connection_selector import select_connections
            candidates = _federation_candidates(conn_id)
            sel = (await asyncio.to_thread(select_connections, req.question, candidates)
                   if len(candidates) >= 2 else None)
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "cross-source selection is best-effort; fall through to single-connection",
                     counter="ask.federation_select_failed")
            sel = None
        if sel is not None and sel.multi_source:
            async for _ev in _stream_federated(req.question, sel):
                yield _ev
            return

    has_deep = has_capability(Capability.DEEP_ANALYSIS, conn_id=conn_id)
    # decide_ask_route may consult the LLM intent classifier on borderline questions,
    # so run it off the event loop.
    route = await asyncio.to_thread(
        decide_ask_route, req.question,
        depth_override=req.depth, deep_flag=req.escalate,
        insight_id=req.insight_id, has_deep=has_deep,
        mode_override=req.mode,   # R13 — a named starter's declared path
    )
    # Decided BEFORE the receipt is emitted, so the receipt can say which body served the
    # turn — that key is Wave 6's population-level converse/fast-path ratio. It is a KEY on
    # an existing frame, not a new frame: the dispatcher reads named keys, so an extra one
    # is inert, and minting a second routing frame for the same decision would be exactly
    # the parallel vocabulary this wave is trying not to create.
    _use_converse = _converse_eligible(req, route)
    # CI-1 — resolve the effective conversation history ONCE, here, before any body runs:
    # the client's turns when it sent them, else a server-side reconstruction from the
    # session store so a reload / another device / the MCP server / a scheduled task all
    # get the memory the session already holds. Every downstream body reads req.history,
    # so replacing it at this seam covers quick, converse, and deep at once.
    _client_history = bool(req.history)
    req.history = resolve_history(req.history, req.session_id)
    _route_ev = route.to_event()
    if req.purpose:
        _route_ev["purpose"] = req.purpose   # R13/R10 — starter provenance on the receipt
    if _use_converse:
        _route_ev["body"] = "converse"
    # The route receipt measures the memory it injected — turns and chars — the same
    # discipline PE-1 applied to prompt spend: a feature you cannot see the size of is
    # one you cannot tell is working. `reconstructed` distinguishes server-rebuilt memory
    # from client-supplied, which is exactly the gap CI-1 closed.
    _hist = req.history or []
    _route_ev["history_turns"] = len(_hist)
    _route_ev["history_chars"] = len(build_history_section(_hist)) if _hist else 0
    _route_ev["history_reconstructed"] = bool(_hist) and not bool(_client_history)
    yield _sse("route", _route_ev)

    if route.depth == "deep" and not _use_converse:
        async for sse in _investigation_job_streamed(
            req.question, conn_id, request,
            hitl=req.hitl, skip_cache=req.skip_cache, canvas_id=req.canvas_id,
            schema_scope=req.schema_name, seed_sql=req.seed_sql,
            seed_context=req.seed_context, insight_id=req.insight_id, deep=req.escalate,
            history=req.history,  # follow-up composition on the deep path (parity with quick)
            # R9 — carry the route verdict's mode so a wide question reaches the explore wave.
            # Normally "investigate"; "explore" only when the deterministic wide detector fired
            # under explore.route_wide. (depth=="deep" ⇒ mode ∈ {investigate, explore}.)
            requested_mode=route.mode,
            allow_clarify=req.allow_clarify,
            purpose=req.purpose,  # R10 — starter provenance on the job row + run record
        ):
            yield sse
    else:
        # The two quick bodies are PEERS under one meter, not two parallel branches with
        # two budget lookups: whichever answers, a turn costs what the same governed
        # budget allows. Converse needs it more, not less — it makes SEVERAL provider
        # calls where the fast path makes a handful.
        _body = (
            _stream_converse(req.question, conn_id, req.history,
                             session_id=req.session_id, canvas_id=req.canvas_id,
                             # CI-4 — a seeded/dossier turn hands its finding to the
                             # conversation instead of bypassing it.
                             origin_prose=await _origin_prose_for(req, conn_id))
            if _use_converse else
            _stream_chat(req.question, conn_id, req.history,
                         session_id=req.session_id, canvas_id=req.canvas_id,
                         skip_clarify=req.skip_clarify, purpose=req.purpose,
                         schema_scope=req.schema_name,
                         # "Answer anyway" = skipped WITHOUT supplying a reading. When a
                         # reading did come back the choice is recorded and crystallized,
                         # so there is nothing to disclose.
                         assumed_default=bool(req.skip_clarify and not req.clarify_reading))
        )
        async for sse in _metered_stream(_body, budget=_insight_budget(conn_id)):
            yield sse


def build_ask_stream(req: "AskRequest", request: "Request | None") -> AsyncGenerator[str, None]:
    """The composed `/ask` event generator — the ONE source of the ask stream, shared by the
    legacy `ask_endpoint` and the AG-UI `/agui/run` translator so both stay byte-identical.

    Resolves the connection + optional user-agent and applies the agent's conn/schema bindings
    (which mutates ``req.schema_name`` and may raise ``HTTPException`` 409) BEFORE building the
    generator — exactly as the endpoint always did — so those surface as HTTP errors, not as
    mid-stream SSE. ``request`` is threaded only for ``_stream_ask``'s signature parity; nothing
    on the path dereferences it (a caller with no HTTP request may pass ``None``)."""
    conn_id = _resolve_conn(req)
    agent = _resolve_ask_agent(req)
    if agent is not None:
        conn_id = _apply_agent_bindings(req, agent, conn_id)
    stream = _stream_ask(req, request, conn_id)
    # Innermost: binds the run's trace id (so the quick path is correlated at all)
    # and records request/response, seeing the identity the outer wrappers pin.
    stream = stream_with_session_log(
        stream, question=req.question, conn_id=conn_id, door="ask", depth=req.depth,
        canvas_id=req.canvas_id or "", schema=req.schema_name or "",
        purpose=req.purpose or "", agent_id=req.agent_id or "")
    stream = _stream_with_session(req.session_id, stream)  # ambient session → trace attribution
    if agent is not None:
        stream = _stream_as_agent(agent, stream)
    return stream


def ask_agent_refusal(req: "AskRequest") -> str:
    """Why this ask cannot run as its ``agent_id``, or "" when it can (or none is set).

    The public form of the persona resolution :func:`build_ask_stream` performs inline, for
    callers that must decide BEFORE a run starts. ``build_ask_stream`` raises its refusals as
    ``HTTPException`` — correct for an HTTP caller, lost for a scheduled one, whose tick has
    already reported the effect as dispatched by the time a submitted job unwraps. Wave H1's
    automation effect asks here first and puts the sentence in its run history instead.

    Same authority, same sentences: this delegates to the very functions the stream uses, so a
    rule can never hold on one path and not the other. Note it mutates ``req.schema_name`` the
    way the stream does — callers pass the request they are about to run, or a probe copy.
    """
    try:
        agent = _resolve_ask_agent(req)
        if agent is not None:
            _apply_agent_bindings(req, agent, _resolve_conn(req))
    except HTTPException as exc:
        return str(exc.detail)
    return ""


@router.post("/ask")
async def ask_endpoint(req: AskRequest, request: Request):
    """One conversational entry — the router picks quick vs deep (auto+transparency).

    Not gated on DEEP_ANALYSIS as a dependency: a quick answer only needs chat access,
    and a deep route is capability-checked inside `_stream_ask` (degrade, never bypass).
    `/chat` and `/investigate` remain as-is for back-compat through the transition.
    """
    if os.getenv("AUGHOR_UNIFIED_ASK", "1").lower() in ("0", "false", "no", "off"):
        raise HTTPException(status_code=404, detail="unified /ask is disabled")
    return StreamingResponse(
        build_ask_stream(req, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/ask/context")
def ask_context_endpoint(
    connection: str = Query(..., description="connection id"),
    question: str = Query(..., description="the question to ground"),
    principal=Depends(get_principal),
):
    """The grounding-context receipt (flag ``ask.context_receipt``) — the exact
    grounding blocks the SQL writer would be given for this question on this
    connection: schema slice, glossary, governed-metric bindings, ambiguity-ledger
    priors, dialect rules, trusted templates, and the active agent/pack brief.

    The input-side twin of the Trust Receipt. Read-only, deterministic (re-derives
    the same blocks the answer path assembles from the same producers).
    """
    from aughor.agent.grounding import build_grounding_context
    from aughor.db.connection import open_connection_for
    try:
        db = open_connection_for(connection)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Connection {connection!r} not found")
    try:
        schema = _get_schema_cached(connection, db) or ""
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "grounding receipt: schema fetch best-effort; schema-dependent blocks skipped",
                 counter="ask.context_receipt.schema")
        schema = ""
    ctx = build_grounding_context(question, connection, db=db, schema=schema,
                                  eff_schema=getattr(db, "_schema_name", None))
    return {"receipt": ctx.to_dict(), "markdown": ctx.to_markdown()}


def _resolve_ask_agent(req: "AskRequest"):
    """The user-defined agent this ask runs as, or None (no agent_id named)."""
    if not req.agent_id:
        return None
    from aughor.custom_agents import get_agent
    agent = get_agent(req.agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"No such agent '{req.agent_id}'")
    if not agent.enabled:
        raise HTTPException(status_code=409, detail=f"agent '{agent.name}' is disabled")
    return agent


def _apply_agent_bindings(req: "AskRequest", agent, conn_id: str) -> str:
    """Enforce the agent's connection + schema bindings on this ask.

    Fail-closed: an EXPLICIT conflicting value is a 409, never a silent
    override; an unset/default value is bound to the agent's. Returns the
    effective connection id."""
    if agent.connection_id:
        if req.connection_id not in (BUILTIN_ID, agent.connection_id):
            raise HTTPException(
                status_code=409,
                detail=f"agent '{agent.name}' is bound to connection "
                       f"'{agent.connection_id}' (asked: '{req.connection_id}')")
        conn_id = agent.connection_id
    if agent.schema_scope:
        if req.schema_name and req.schema_name != agent.schema_scope:
            raise HTTPException(
                status_code=409,
                detail=f"agent '{agent.name}' is scoped to schema "
                       f"'{agent.schema_scope}' (asked: '{req.schema_name}')")
        req.schema_name = agent.schema_scope
    return conn_id


def _current_agent_id() -> str:
    """The active user-agent's id for state seeding ("" when none)."""
    from aughor.custom_agents.context import current_agent
    agent = current_agent()
    return agent.id if agent is not None else ""


def persona_for_investigation(inv_id: str):
    """The user-agent persona a checkpointed deep run was launched AS, or None.

    Resume (plan/clarify-gate feedback) never passes through /ask, so the
    persona is re-read from the run's persisted state (`agent_id`). Fail-open:
    a missing checkpoint or an unknown/disabled agent resumes the run WITHOUT
    the persona rather than blocking it."""
    try:
        from aughor.agent.graph import read_checkpoint_values
        agent_id = read_checkpoint_values(inv_id).get("agent_id") or ""
        if not agent_id:
            return None
        from aughor.custom_agents import get_agent
        persona = get_agent(agent_id)
        return persona if (persona is not None and persona.enabled) else None
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "persona re-activation on resume is best-effort; resuming without it",
                 counter="agents.resume_persona")
        return None


async def _stream_as_agent(agent, stream: AsyncGenerator[str, None]) -> AsyncGenerator[str, None]:
    """Run the ask stream with the user-agent contextvar active, so the prompt
    brief and the document-retrieval scope see the agent everywhere (threads
    included — ContextThreadPoolExecutor propagates contextvars)."""
    from aughor.custom_agents.context import activate_agent, release_agent
    token = activate_agent(agent)
    try:
        yield _sse("agent", {"agent_id": agent.id, "name": agent.name,
                             "connection_id": agent.connection_id,
                             "doc_count": len(agent.doc_ids)})
        async for event in stream:
            yield event
    finally:
        release_agent(token)


#: SSE types the session log needs to notice. Checked as cheap substrings before
#: paying for a JSON parse — the stream is mostly high-frequency delta frames and
#: an observability sink must not tax every one of them.
_SESSION_LOG_SNIFF = ('"start"', '"error"', '"headline"', '"receipt_id"')


async def stream_with_session_log(
    stream: AsyncGenerator[str, None], *, question: str, conn_id: str,
    door: str = "ask", depth: str = "", canvas_id: str = "", schema: str = "",
    purpose: str = "", agent_id: str = "",
) -> AsyncGenerator[str, None]:
    """Record the run in the session log (flag ``obs.session_log``).

    Takes primitives rather than a request model so every door can use it —
    ``/ask`` (via ``build_ask_stream``, which also serves ``/agui/run``) and the
    legacy ``/chat``, which has its own endpoint and would otherwise stay dark.

    Applied INNERMOST so the outer session/agent wrappers have already pinned
    their contextvars by the time this emits — identity attribution then costs
    nothing to thread.

    This is where the quick path stops being invisible. ``new_trace`` is called
    in exactly one place, inside the deep path, so a quick turn minted no trace
    id at all; binding one here means every span the run opens inherits it,
    quick and deep alike, with no change to the emitters themselves.

    On the deep path the investigation keeps its own id for its spans (it is
    created further down, after routing). Rather than fight that, we sniff it off
    the ``start`` frame and record it as ``investigation_id``, so the two
    correlate without either side having to know about the other.

    A no-op wrapper when the flag is off: no id is minted, nothing is parsed.
    """
    from aughor.obs import session_log
    if not session_log.enabled():
        async for event in stream:
            yield event
        return

    import json as _json
    import time as _t
    import uuid as _uuid
    from aughor import telemetry as _tel

    run_id = _uuid.uuid4().hex[:8]
    inv_id: str | None = None
    failed: str | None = None
    headline: str = ""
    receipt_id: str | None = None
    t0 = _t.monotonic()
    with _tel.bind_trace(run_id):
        session_log.emit(
            session_log.USER_REQUEST, name=door, trace_id=run_id, conn_id=conn_id,
            payload={"question": question, "depth": depth, "canvas_id": canvas_id,
                     "schema": schema, "purpose": purpose, "agent_id": agent_id},
        )
        try:
            async for event in stream:
                if any(h in event for h in _SESSION_LOG_SNIFF):
                    try:
                        frame = _json.loads(event[6:]) if event.startswith("data: ") else {}
                    except Exception:
                        frame = {}
                    kind = frame.get("type")
                    if kind == "start" and frame.get("investigation_id"):
                        inv_id = frame["investigation_id"]
                    elif kind == "headline":
                        # The answer, not just that there was one. A run whose
                        # output was never captured cannot become a test case,
                        # which is what the rest of this arc is for.
                        headline = str(frame.get("headline") or "")[:2000]
                    elif kind == "receipt_id":
                        receipt_id = frame.get("receipt_id")
                    elif kind == "error":
                        failed = str(frame.get("message") or "")[:2000]
                        session_log.emit(
                            session_log.EXECUTION_ERROR, name=door, trace_id=run_id,
                            investigation_id=inv_id, conn_id=conn_id, ok=False,
                            payload={"message": failed},
                        )
                yield event
        except BaseException as exc:
            # A cancelled or crashed stream must leave the same evidence as a
            # clean failure — otherwise the log's most interesting runs are
            # exactly the ones missing from it. `failed` must be set too, or the
            # finally below closes the run as ok=True and the log calls the
            # crash a success.
            failed = str(exc)[:2000]
            session_log.emit(
                session_log.EXECUTION_ERROR, name=door, trace_id=run_id,
                investigation_id=inv_id, conn_id=conn_id, ok=False,
                error_class=type(exc).__name__,
                payload={"message": str(exc)[:2000]},
            )
            raise
        finally:
            session_log.emit(
                session_log.FINAL_RESPONSE, name=door, trace_id=run_id,
                investigation_id=inv_id, conn_id=conn_id, ok=failed is None,
                duration_ms=round((_t.monotonic() - t0) * 1000, 1),
                payload={**({"headline": headline} if headline else {}),
                         **({"receipt_id": receipt_id} if receipt_id else {}),
                         **({"error": failed} if failed else {})},
            )


async def _stream_with_session(session_id: str, stream: AsyncGenerator[str, None]) -> AsyncGenerator[str, None]:
    """Run the ask stream with the conversation session contextvar active, so the
    telemetry seam can attribute the investigation trace to its session ambiently
    (MLflow Sessions view) — propagates into the deep-run job + waves like the
    agent persona does. No-op wrapper when there's no session id."""
    from aughor.org.context import reset_session_id, set_session_id
    token = set_session_id(session_id or "")
    try:
        async for event in stream:
            yield event
    finally:
        reset_session_id(token)


def _job_id_for_investigation(inv_id: str) -> Optional[str]:
    """The kernel job running (or that ran) this investigation — read from the
    journal, where every investigation.* event is job-stamped. No extra state."""
    from aughor.kernel.ledger import Ledger
    for e in Ledger.default().events(kind="investigation.created", limit=300):
        if (e.get("payload") or {}).get("investigation_id") == inv_id:
            return e.get("job_id")
    return None


@router.post("/investigations/{inv_id}/cancel")
def cancel_investigation_route(inv_id: str):
    """Cancel an in-flight investigation by cancelling its supervised kernel job.
    The job's CancelledError unwinds the stream's finally (which reconciles the
    'running' row to failed); the kernel records the job CANCELLED."""
    from aughor.kernel.jobs import kernel
    job_id = _job_id_for_investigation(inv_id)
    if not job_id:
        raise HTTPException(status_code=404, detail="No kernel job found for this investigation")
    cancelled = kernel().cancel(job_id)
    return {"investigation_id": inv_id, "job_id": job_id, "cancelled": cancelled}


def build_resume_stream(inv_id: str, request: "Request | None", *, feedback: str = "",
                        keep_subquestions: "Optional[list[int]]" = None,
                        clarify_choice: "Optional[str]" = None) -> AsyncGenerator[str, None]:
    """The composed resume stream — shared by the legacy `/feedback` endpoint and the AG-UI
    translator so both resume a paused investigation identically (incl. the agent-persona wrap)."""
    stream = _stream_resume(inv_id, feedback, request, keep_subquestions=keep_subquestions,
                            clarify_choice=clarify_choice)
    # agents.user_defined — a deep run launched AS an agent resumes AS it: the persona persists in
    # the run's checkpointed state (resume never passes through /ask). Fail-open: no persona → unchanged.
    persona = persona_for_investigation(inv_id)
    if persona is not None:
        stream = _stream_as_agent(persona, stream)
    return stream


@router.post("/investigations/{inv_id}/feedback")
async def submit_feedback(inv_id: str, req: FeedbackRequest, request: Request):
    return StreamingResponse(
        build_resume_stream(inv_id, request, feedback=req.feedback,
                            keep_subquestions=req.keep_subquestions, clarify_choice=req.clarify_choice),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/investigations")
def get_investigations(limit: int = 50, workspace_id: str | None = None):
    """Recent investigations/chats. When `workspace_id` is given, only those whose
    connection belongs to that workspace are returned (data-path tenancy)."""
    from aughor.metastore import accessible_catalog_ids
    allowed = accessible_catalog_ids(workspace_id)
    if allowed is None:
        return list_investigations(limit=limit)
    # Fetch wider when scoping so a workspace's items aren't truncated by the global
    # newest-first limit before filtering, then trim back to `limit`.
    rows = list_investigations(limit=max(limit, 200))
    scoped = [r for r in rows if r.get("connection_id") in allowed]
    return scoped[:limit]


@router.get("/investigations/indexed-ids")
def get_indexed_ids():
    from aughor.tools.prior_analyses import INVESTIGATIONS_COLLECTION
    from aughor.semantic.vector_store import scroll_payloads
    payloads = scroll_payloads(INVESTIGATIONS_COLLECTION)
    return {"ids": [p["inv_id"] for p in payloads if p.get("inv_id")]}


@router.get("/investigations/{inv_id}")
def get_investigation_detail(inv_id: str, principal=Depends(get_principal)):
    from aughor.security.authz import check_owner
    check_owner("investigation", inv_id, principal)  # SEC-05: no cross-org read
    inv = get_investigation(inv_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return inv


@router.get("/investigations/{inv_id}/graph")
def get_investigation_graph(inv_id: str, principal=Depends(get_principal)):
    """The deep run's phase view (Wave CR5b): the FIXED topology it runs, the
    phases the checkpoint recorded, and — for a paused run — which gate it is
    waiting at, derived from state markers and labelled as such.

    Deliberately not a DAG editor and deliberately not `agent.get_state().next`:
    the authoritative next-node read needs a compiled graph over an open
    warehouse connection, which a read-only view must not require. Resume goes
    through the existing feedback endpoint.
    """
    from aughor.agent.graph import read_checkpoint_state
    from aughor.security.authz import check_owner

    check_owner("investigation", inv_id, principal)
    inv = get_investigation(inv_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Investigation not found")

    cp = read_checkpoint_state(inv_id)
    values = cp.get("values") or {}
    phases = list(values.get("investigation_phases") or [])
    sub_questions = list(values.get("sub_questions") or [])
    clarify_pending = values.get("_clarify_pending") or None

    # Branch, from what the checkpoint actually holds. A run with no checkpoint
    # reports unknown rather than a guessed picture. A run paused at the clarify
    # gate has no phases yet — the pending clarify marker is the deep-analysis tell.
    #
    # The wire value stays "ada": clients (including web/lib/api.ts) compare against it,
    # and the node ids in `topology` below are the graph's real, frozen node names. The
    # response carries an additive `branch_label` for anything that wants to DISPLAY the
    # branch without learning the acronym.
    if phases or clarify_pending:
        branch = "ada"
    elif sub_questions:
        branch = "explore"
    elif cp.get("exists"):
        branch = "direct"
    else:
        branch = "unknown"

    # The fixed topologies (aughor/agent/graph.py _compile) — flag-gated
    # variants resolved at read time so the picture matches what would run.
    from aughor.agent.graph import topology_flags

    variants = topology_flags()
    if branch == "ada":
        middle = (["ada_phase_wave"] if variants["ada_parallel_phases"]
                  else ["ada_baseline", "ada_decompose", "ada_dimensional"])
        xsec = ("ada_cross_section_multilens" if variants["ada_parallel_lenses"]
                else "ada_cross_section")
        topology = ["route_question", "exploratory_scan", "ada_intake", "clarify_gate",
                    xsec, *middle, "ada_behavioral", "ada_synthesize"]
    elif branch == "explore":
        executor = ("plan_and_execute_wave" if variants["explore_parallel"]
                    else "plan_and_execute_subq")
        topology = ["route_question", "exploratory_scan_explore",
                    "decompose_exploration", "plan_gate", executor,
                    "synthesize_exploration"]
    elif branch == "direct":
        topology = ["route_question", "plan_queries", "execute_planned_queries",
                    "score_evidence", "replan", "synthesize"]
    else:
        topology = []

    paused = inv.get("status") == "paused"
    gate = None
    if paused:
        if clarify_pending:
            gate = "clarify_gate"
        elif branch == "explore":
            gate = "plan_gate"
        elif branch == "ada":
            gate = "ada_synthesize"

    return {
        "investigation_id": inv_id,
        "status": inv.get("status"),
        "branch_label": {"ada": "Deep analysis", "explore": "Survey",
                         "direct": "Quick answer"}.get(branch, "Unknown"),
        "question": inv.get("question"),
        "branch": branch,
        "topology": topology,
        "phases": phases,
        "sub_questions": sub_questions,
        "interrupt": {"paused": paused, "gate": gate,
                      "basis": "state_markers" if paused else None,
                      "clarify_pending": clarify_pending},
        "checkpoint": {"exists": cp.get("exists", False), "step": cp.get("step"),
                       "last_writers": cp.get("last_writers", [])},
        "resume": {"feedback": f"/investigations/{inv_id}/feedback"} if paused else None,
    }


@router.get("/investigations/{inv_id}/export")
def export_investigation(inv_id: str, format: str = "pdf", narrate: bool = False,
                         principal=Depends(get_principal)):
    """Download a stored analysis as a polished PDF or PowerPoint (`format=pdf|pptx`).

    `narrate=true` prepends an LLM-authored executive summary (best-effort; the
    export still succeeds if the model is slow or unavailable)."""
    from fastapi.responses import Response
    from aughor.security.authz import check_owner

    check_owner("investigation", inv_id, principal)  # SEC-05: no cross-org export
    inv = get_investigation(inv_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Investigation not found")
    fmt = (format or "pdf").lower()
    if fmt not in ("pdf", "pptx"):
        raise HTTPException(status_code=400, detail="format must be 'pdf' or 'pptx'")

    # Imported after the authz/existence checks so a caller who may not read this
    # investigation learns nothing about the deployment's configuration, and guarded
    # separately from the render below: `aughor.export` pulls the extra's whole dependency
    # closure at import time, and an ImportError here is the same CONFIGURATION state as
    # ExportUnavailable — not a fault. Catching it only around export_report() let the
    # matplotlib import escape as a 500.
    try:
        from aughor.export import ExportUnavailable, export_report
    except ImportError as exc:
        logger.warning("export requested but its extra failed to import: %s", exc)
        raise HTTPException(status_code=501, detail=(
            "Report export needs the 'export' extra (reportlab, python-pptx, matplotlib). "
            f"Install it with:  uv sync --extra export   —  underlying import error: {exc}"))

    try:
        # The router resolves the effective currency (org override → profile) and injects
        # it — the platform-side export must not import agent-side settings itself.
        _sym = _resolve_currency_symbol(inv.get("connection_id") or "", inv.get("schema_name"))
        data, filename, media_type = export_report(inv, fmt, narrate=narrate, money_symbol=_sym)
    except ExportUnavailable as exc:
        # A deployment without the `export` extra is a CONFIGURATION state, not a fault:
        # say so, and name the fix. A 500 would send the operator hunting a bug.
        logger.warning("export requested but unavailable: %s", exc)
        raise HTTPException(status_code=501, detail=str(exc))
    except Exception:  # never leak a stack trace to the client
        logger.exception("export failed for %s", inv_id)
        raise HTTPException(status_code=500, detail="export failed")
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/investigations", status_code=200)
def clear_investigations(workspace_id: str | None = None):
    """Bulk-delete investigations the caller can see — platform-wide, or scoped to a
    workspace's connections when `workspace_id` is given. Cascades evidence claims
    and the RAG vector index. Returns a count summary of what was removed."""
    from aughor.db.purge import purge_investigations_bulk
    from aughor.metastore import accessible_catalog_ids

    allowed = accessible_catalog_ids(workspace_id)
    # allowed is None → unscoped (clear everything); else restrict to those connections.
    return purge_investigations_bulk(None if allowed is None else list(allowed))


@router.delete("/investigations/{inv_id}", status_code=204)
def delete_investigation_endpoint(inv_id: str, principal=Depends(get_principal)):
    """Delete one investigation and its full footprint (history row, evidence
    claims, RAG vector entry). 404 if it doesn't exist."""
    from aughor.db.purge import purge_investigation_artifacts
    from aughor.security.authz import check_owner
    check_owner("investigation", inv_id, principal)  # SEC-05: no cross-org delete
    counts = purge_investigation_artifacts(inv_id)
    if not counts.get("investigations"):
        raise HTTPException(status_code=404, detail="Investigation not found")


@router.post("/investigations/reindex", dependencies=[gate(Capability.DEEP_ANALYSIS)])
def reindex_investigations():
    from aughor.tools.prior_analyses import index_investigation
    rows = list_investigations(limit=1000)
    indexed, skipped = 0, 0
    for row in rows:
        if not row.get("headline"):
            skipped += 1
            continue
        full = get_investigation(row["id"])
        if not full or not full.get("report"):
            skipped += 1
            continue
        key_findings = [f.get("claim", "") for f in (full["report"].get("key_findings") or [])]
        index_investigation(inv_id=row["id"], question=row["question"], headline=row["headline"], key_findings=key_findings, connection_id=row.get("connection_id", ""))
        indexed += 1
    return {"indexed": indexed, "skipped": skipped}


@router.get("/chat-sessions")
def list_chat_sessions_route(conn_id: Optional[str] = None, limit: int = 30):
    """Recent chat sessions for the threads rail (CI-6a) — id, opening question as the
    title, turn count, last activity. Org-scoped in the store, like the turns read."""
    from aughor.db.history import list_chat_sessions
    return list_chat_sessions(conn_id, limit=limit)


@router.get("/chat-sessions/{session_id}/turns")
def get_chat_session_turns(session_id: str):
    turns = get_session_turns(session_id)
    if not turns:
        raise HTTPException(status_code=404, detail="Session not found")
    return turns


@router.get("/answer/{connection_id}/{inv_id}/receipt")
def get_answer_receipt(connection_id: str, inv_id: str):
    """K3-wide Trust Receipt for an agentic (deep-analysis) answer report — executed
    queries, input tables, registered metrics + B-7 enforcement verdict. 404 for
    investigations produced before receipts."""
    from aughor.kernel.ledger import Ledger
    # natural_key stays `ada:` — a persisted storage identity; renaming it would
    # orphan every receipt written before this rename. Only the URL path is de-ADA'd.
    rec = Ledger.default().receipt(f"ada:{connection_id}:{inv_id}")
    if rec is None:
        raise HTTPException(status_code=404, detail="No receipt for this report")
    return rec


@router.get("/ada/{connection_id}/{inv_id}/receipt", deprecated=True)
def get_ada_receipt(connection_id: str, inv_id: str):
    """@deprecated Use `/answer/{connection_id}/{inv_id}/receipt`. Kept one release
    for the `ADA`→answer rename (REC-U9)."""
    return get_answer_receipt(connection_id, inv_id)


@router.get("/chat/{connection_id}/{turn_id}/receipt")
def get_chat_receipt(connection_id: str, turn_id: str):
    """K3-wide Trust Receipt for a chat answer — the executed SQL, input tables,
    registered metrics available, and the guards that fired this turn. Makes
    every user-facing number self-justifying, not just explorer findings. 404
    until the answer is produced under the receipt-emitting path (older turns
    have none)."""
    from aughor.kernel.ledger import Ledger
    rec = Ledger.default().receipt(f"chat:{connection_id}:{turn_id}")
    if rec is None:
        raise HTTPException(status_code=404, detail="No receipt for this answer")
    return rec


@router.post("/investigations/{inv_id}/recommendations/{rec_index}/outcome", status_code=201)
def log_recommendation_outcome(inv_id: str, rec_index: int, req: OutcomeRequest):
    from aughor.playbook.outcomes import log_outcome, update_playbook_success_rates
    outcome = log_outcome(inv_id=inv_id, rec_index=rec_index, rec_text=req.rec_text, status=req.status, metric_name=req.metric_name, metric_before=req.metric_before, metric_after=req.metric_after)  # type: ignore[arg-type]
    if req.status in ("verified", "implemented", "rejected"):
        update_playbook_success_rates()
        try:
            from aughor.lifecycle.causal import promote_on_outcome
            promote_on_outcome(inv_id, contradicted=(req.status == "rejected"))
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "causal-playbook promotion on outcome is best-effort; the outcome itself is already logged",
                     counter="investigation.outcome_promote")
    return outcome.model_dump()


@router.get("/investigations/{inv_id}/outcomes")
def get_investigation_outcomes(inv_id: str):
    from aughor.playbook.outcomes import load_outcomes_for_inv
    return [o.model_dump() for o in load_outcomes_for_inv(inv_id)]


# ── Agent Context surface (P2) ────────────────────────────────────────────────

class RescopeRequest(BaseModel):
    connection_id: str
    keep: list[str] = Field(default_factory=list)   # explicit table allowlist the user wants
    schema_name: Optional[str] = None
    expand_fk: bool = True                           # pull in FK bridge tables so joins resolve


@router.post("/investigations/context/rescope")
def rescope_context(req: RescopeRequest):
    """Re-derive the agent's working context after a user trims/adds tables, and report
    the new token budget vs the full schema. Deterministic — no LLM, no agent run — so
    the ribbon can preview the effect of a scope edit instantly (AI FDE resource-ribbon
    idea). `keep` is the desired table set; the response also lists all_tables so the UI
    knows what is addable."""
    from aughor.tools.context_manifest import build_context_manifest, rescope_schema
    db = open_connection_for(req.connection_id)
    try:
        raw = getattr(db, "_conn", None)
        if raw is None:
            raise HTTPException(status_code=400, detail="connection does not expose a schema for rescoping")
        full_schema = _get_schema_cached(req.connection_id, db)
    finally:
        db.close()
    full = build_context_manifest(full_schema)
    _scoped, manifest = rescope_schema(full_schema, keep=req.keep, expand_fk=req.expand_fk)
    return {
        "manifest": manifest.to_dict(),
        "all_tables": full.tables,
        "full_tokens": full.estimated_tokens,
        "scoped_tokens": manifest.estimated_tokens,
        "token_delta": full.estimated_tokens - manifest.estimated_tokens,
    }


# ── Evidence Ledger endpoints ─────────────────────────────────────────────────

class EvidenceFeedbackRequest(BaseModel):
    feedback: str   # "validated" | "disputed" | "needs_context"
    note: Optional[str] = None


@router.get("/investigations/evidence/recent")
def get_recent_evidence(connection_id: str, canvas_id: Optional[str] = None, limit: int = 50):
    """Return recent evidence claims across a scope (connection, optionally a canvas),
    newest-first — the scope-level Evidence layer. The ledger keys only by
    investigation_id, so we resolve the scope to its investigation IDs first.

    Registered before /investigations/{inv_id}/evidence so the literal 'evidence'
    segment can't be captured as an investigation id.
    """
    from aughor.db.history import list_investigation_ids
    from aughor.evidence import store as _ev_store
    inv_ids = list_investigation_ids(connection_id, canvas_id)
    claims = _ev_store.get_recent_claims_for_investigations(inv_ids, limit)
    return [c.model_dump() for c in claims]


@router.get("/investigations/{inv_id}/evidence")
def get_investigation_evidence(inv_id: str):
    """Return all evidence claims for an investigation, ordered by confidence."""
    from aughor.evidence import store as _ev_store
    claims = _ev_store.get_claims_for_investigation(inv_id)
    return [c.model_dump() for c in claims]


@router.post("/investigations/{inv_id}/evidence/{claim_id}/feedback")
def submit_claim_feedback(inv_id: str, claim_id: str, req: EvidenceFeedbackRequest):
    """Set owner feedback on an evidence claim."""
    from aughor.evidence import store as _ev_store
    VALID = {"validated", "disputed", "needs_context"}
    if req.feedback not in VALID:
        raise HTTPException(status_code=422, detail=f"feedback must be one of {VALID}")
    updated = _ev_store.update_feedback(claim_id, req.feedback, req.note)
    if not updated:
        raise HTTPException(status_code=404, detail="Claim not found")
    return updated.model_dump()
