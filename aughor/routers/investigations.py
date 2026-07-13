"""Investigations — chat, investigate, HITL feedback, history, outcomes, reindex."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import AsyncGenerator, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from aughor.agent.state import AgentState
from aughor.db.connection import open_connection_for
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
        # I6 — surface ambiguity handling on the Trust Receipt: any resolution THIS question
        # matched in the Ambiguity Ledger (settled earlier by a probe / the user / a reviewer) is
        # recorded, so "this answer followed a previously-resolved reading" is inspectable — the
        # machinery made honest to the user. Best-effort; gated with the ledger (closed_loop).
        _resolved_ambig: list = []
        try:
            from aughor.verify.priors import closed_loop_enabled
            if closed_loop_enabled():
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
        # too; for the synchronous chat/insight path this is the only sink.
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
        _receipt_id = Ledger.default().artifact_write(
            kind, natural_key,
            {"question": question, "headline": headline or question,
             "sql": sqls[0] if sqls else "", "tables": sorted(seen),
             **({"cost": _cost} if _cost is not None else {}),
             **({"model": _model} if _model else {}),
             **({"resolved_ambiguities": _resolved_ambig} if _resolved_ambig else {}),
             **({"learning": _learning} if _learning else {}),
             **({"activations": _activations} if _activations else {}),
             **(payload_extra or {})},
            conn_id=connection_id, canvas_id=canvas_id or None, lineage=lineage,
        )
        if enf is not None:
            Ledger.default().emit("metric.enforcement", enf,
                                  conn_id=connection_id, canvas_id=canvas_id or None)
        # `receipt_id` is the stable artifact id → the unified GET /receipt/{id} (WP-10); a
        # streaming caller emits it so the UI's "Why this number" opens the public receipt.
        return {"learning": _learning, "activations": _activations, "receipt_id": _receipt_id}
    except Exception:
        logger.debug("%s receipt write failed", kind, exc_info=True)
    return {"learning": None, "activations": None, "receipt_id": None}


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
                yield {"__ada_progress__": next_prog.result()}
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
    """The deep-run event iterator. With ``ada.progress_events`` on, interleaves per-dimension
    ``phase_progress`` markers into the stream (a scan node reports progress DURING execution, not only
    at ``phase_complete``); off → plain ``_aiter_sync`` (byte-identical, no sink, no extra tasks)."""
    try:
        from aughor.kernel.flags import flag_enabled
        on = flag_enabled("ada.progress_events")
    except Exception:
        on = False
    if not on:
        return _aiter_sync(graph_stream)
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
    # Drilling into a known briefing finding: its insight id. When set (and not
    # `deep`), the explorer's pre-computed Finding Dossier is served as the trace —
    # a deterministic ledger read, NOT a second ADA run. `deep` is the explicit
    # "Investigate deeper" escalation: run ADA, seeded with that dossier.
    insight_id: Optional[str] = None
    deep: bool = False
    # Recent conversation turns (question + SQL + result digest), so a follow-up in a
    # canvas composes on the previous query instead of starting cold — parity with the
    # quick /chat path. Same shape /chat + /ask accept.
    history: list[ChatHistoryTurn] = []


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
    # I4 — the reading the user chose when answering a clarify (the chip text / typed detail).
    # When present, it crystallizes into the Ambiguity Ledger (source=user) so the class never
    # re-ambiguates on this connection. `clarify_subject` is the original ambiguous question
    # (defaults to `question`); `clarify_source` is the clarify kind ("ambiguous_term" → a value
    # choice, else an interpretation choice).
    clarify_reading: str = ""
    clarify_subject: str = ""
    clarify_source: str = ""
    # Pass-throughs preserved from the investigate path.
    deep: bool = False
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


_VALID_CHART_TYPES = {"auto", "bar", "bar_horizontal", "bar_vertical", "line", "area", "pie", "pareto", "stacked_bar", "scatter",
                      "multi_line", "heatmap", "treemap", "combo"}

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
    # MindsDB-style: chart config generated alongside SQL so chart always matches data
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


class _InsightResult(BaseModel):
    """Rich analytical insight generated from SQL results — anomaly detection, trend, comparison."""
    narrative: str = Field(default="", description="2-3 tight sentences that lead with the answer and wrap decisive numbers in **bold**.")
    anomalies: list[str] = Field(default_factory=list, description="List of detected anomalies or unexpected patterns.")
    trend: str = Field(default="stable", description="One of: up, down, stable, mixed.")
    confidence: str = Field(default="medium", description="One of: high, medium, low.")


class _PostAnswer(_InsightResult):
    """Combined post-answer enrichment: analytical insight + follow-up questions
    in ONE narrator call (was two separate narrator round-trips per answer).
    Inherits insight fields; adds the follow-up list with the same coercion guard."""
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
    out = []
    for m in _HL_NUM_RE.finditer(text or ""):
        try:
            out.append(float(m.group(1).replace(",", "")) * {"b": 1e9, "m": 1e6, "k": 1e3}.get((m.group(2) or "").lower(), 1.0))
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

    def _grounded(n):
        if _approx_in(n, pool):
            return True
        return scalar_like and (_approx_in(n, [p * 100 for p in pool])
                                or _approx_in(n, [p / 100 for p in pool if p]))

    unmatched = [n for n in _headline_numbers(headline)
                 if abs(n) >= floor and not (2000 <= n <= 2099 and n == int(n)) and not _grounded(n)]
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
        from aughor.profile import store as _pstore
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


def build_history_section(history, *, followup: bool = False) -> str:
    """Render the conversation context injected into the chat SQL prompt.

    Carries each recent turn's question + SQL + columns + headline AND a small **result
    digest** (sample rows) so a follow-up can resolve references ("that", "the top one",
    "those regions") against real values — not just column names (Phase 4). When the new
    question is a detected follow-up, the header instructs the generator to **compose on
    the most recent query as the base** (keep its metric/filters/grain/window unless the
    ask changes them), which is what makes "now break that down by region" reliable.

    Duck-typed over ``ChatHistoryTurn`` so it is unit-testable with plain stand-ins."""
    if not history:
        return ""
    recent = list(history)[-3:]
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


async def _stream_chat(
    question: str,
    connection_id: str,
    history: list[ChatHistoryTurn],
    request: Request,
    session_id: str = "",
    canvas_id: Optional[str] = None,
    skip_clarify: bool = False,
) -> AsyncGenerator[str, None]:
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
    _es = resolve_execution_scope(connection_id, canvas_id,
                                  schema_context_builder=build_canvas_schema_context)
    connection_id = _es.connection_id                # canvas's primary connection wins
    canvas_scope_schema = _es.declared_schema        # raw declared → the prompt note
    canvas_scope_tables = list(_es.tables)
    canvas_scope_full = _es.is_full_schema
    canvas_scope_eff_schema = _es.eff_schema
    try:
        db = _es.open()
    except KeyError as e:
        yield _sse("error", {"message": str(e)})
        return
    except Exception as e:
        yield _sse("error", {"message": f"Could not connect: {e}"})
        return

    # Effective currency symbol for prose: tables/charts already honour the org currency,
    # but the LLM authored ledes in '$'. Resolve once; applied to headline + narrative below.
    _cur_sym = _resolve_currency_symbol(connection_id, canvas_scope_eff_schema)

    try:
        from aughor.agent.prompts import CHAT_PROMPT, CHAT_SQL_SYSTEM
        from aughor.llm.provider import get_provider
        # Shared grounding producers (Rec 5): the same block functions the
        # `GET /ask/context` receipt calls, so the receipt shows exactly what the
        # answer path was grounded on (no drift). dialect_rules_block() == the old
        # get_chat_rules_block() verbatim.
        from aughor.agent.grounding import dialect_rules_block

        rules_block = dialect_rules_block()

        from aughor.agent.followup import is_followup
        history_section = build_history_section(history, followup=is_followup(question))

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
            from aughor.process.causal import build_causal_context_section
            s = build_causal_context_section(question, conn_id=connection_id)
            return (s + "\n") if s else ""

        def _docs() -> str:
            from aughor.knowledge.indexer import build_external_context_section
            s = build_external_context_section(question, top_k=2)
            return (s + "\n\n") if s else ""

        def _pb_match():
            from aughor.playbook.retriever import retrieve_for_metric_and_phases
            return retrieve_for_metric_and_phases([question], limit=4)

        async def _safe(fn):
            try:
                return await asyncio.to_thread(fn)
            except Exception:
                return ""

        async def _safe_list(fn):
            try:
                return await asyncio.to_thread(fn)
            except Exception:
                return []

        (
            schema, kb_patterns_section, conn_kb_section, sql_examples_section,
            exploration_section, causal_section, document_section,
            pb_entries,
        ) = await asyncio.gather(
            # WCH-12: the connection-scoped schema cache (300s TTL) — was bypassed
            # here, re-walking information_schema on EVERY chat. Cache miss still
            # introspects; hits within the window skip it.
            asyncio.to_thread(_get_schema_cached, connection_id, db),
            _safe(_kb), _safe(_ckb), _safe(_sqlex),
            _safe(_expl), _safe(_causal), _safe(_docs), _safe_list(_pb_match),
        )

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

        # Build structured Data Catalog from linked tables (MindsDB-style),
        # expanded with FK neighbours so bridge/output tables a multi-table
        # question needs only via a join are present.
        semantic_layer_section = ""
        try:
            from aughor.tools.data_catalog import build_data_catalog
            from aughor.tools.schema import parse_schema_tables, fk_neighbor_expand, temporal_dimension_tables
            linked_tables = list(parse_schema_tables(schema).keys())
            if linked_tables:
                # Add the date/time dimension first (before FK expansion + the
                # 10-table cap) so a temporal question keeps it.
                for _dt in temporal_dimension_tables(_full_schema, linked_tables, question):
                    if _dt not in linked_tables:
                        linked_tables.append(_dt)
                linked_tables = fk_neighbor_expand(_full_schema, linked_tables, cap=10)
                # M24c: verified semantic layer (object sets + computed properties)
                # for the linked entities — only items validated against the live DB.
                try:
                    from aughor.ontology.store import load_latest_ontology
                    from aughor.ontology.semantic_block import render_semantic_layer
                    semantic_layer_section = render_semantic_layer(
                        load_latest_ontology(connection_id), linked_tables
                    )
                except Exception:
                    semantic_layer_section = ""
                data_catalog = await asyncio.to_thread(
                    lambda: build_data_catalog(db, linked_tables)
                )
                if data_catalog:
                    schema = data_catalog
        except Exception:
            logger.warning("Data Catalog build failed; using linked schema text", exc_info=True)

        # Hard cap: max 10 tables in context (MindsDB best practice)
        try:
            from aughor.tools.data_catalog import enforce_context_cap
            schema = enforce_context_cap(schema, max_tables=10)
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "10-table context cap is best-effort; answering from the uncapped schema context",
                     counter="chat.context_cap")

        # ── final_text path (MindsDB-style): definitional questions answered from KB ──
        definitional = re.search(
            r"^(what is|what are|what does|define|explain|meaning of)",
            question,
            re.IGNORECASE,
        )
        if definitional:
            try:
                from aughor.semantic.kb_retriever import has_strong_kb_match, retrieve_for_planning
                if has_strong_kb_match(question, threshold=0.75, top_k=3):
                    kb_answer = retrieve_for_planning(question, top_k=3) or ""
                    # Also pull connection KB
                    try:
                        from aughor.semantic.connection_kb import retrieve_for_question as _ckb_fn
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
                        yield _sse("mode", {"query_mode": "final_text"})
                        yield _sse("headline", {"headline": _answer_text})
                        yield _sse("done", {})
                        try:
                            await asyncio.to_thread(
                                lambda: save_chat_turn(
                                    question=question, connection_id=connection_id,
                                    headline=_answer_text[:2000], sql="", session_id=session_id,
                                    columns=[], rows=[], chart_type="none", tables_used=[],
                                    intent="", approach=[],
                                    canvas_id=canvas_id,
                                )
                            )
                        except Exception as exc:
                            from aughor.kernel.errors import tolerate
                            tolerate(exc, "definitional-answer turn save is best-effort; the answer was already streamed",
                                     counter="chat.turn_save")
                        return
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

        # M24c: verified semantic layer — object sets (named WHERE filters) and
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

        # Semantic Compiler fast-path (backlog #11): for the safe analytical shapes
        # (scalar / timeseries / breakdown / ranking) assemble grounded SQL deterministically
        # from the verified ontology instead of free-form generation. The LLM still writes the
        # headline/chart/approach around it, but the executed SQL is the compiled one — which
        # can't hallucinate columns or fan out. Coverage-gated + fallback-safe (None → no-op).
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
        # SOMA structural-ambiguity probe (3b) — execution-grounded. On a structural-suspect
        # question the cheap deterministic clarify left quiet (e.g. "top products" — by units or
        # revenue?), generate candidate readings, execute them on THIS connection, and ask only if
        # their results materially diverge (the labels become grounded chips). LLM machinery + N
        # executions, so it is opt-in (AUGHOR_SOMA_CLARIFY) and fail-open. Greenlit by the measurement
        # chain (evals/ambiguity_eval + evals/its_structural).
        if (not skip_clarify
                and os.getenv("AUGHOR_SOMA_CLARIFY", "0").lower() in ("1", "true", "yes", "on")):
            try:
                from aughor.agent.soma import (is_structural_suspect, generate_candidate_readings,
                                               assess_structural_ambiguity)
                if is_structural_suspect(question):
                    _cands = await asyncio.to_thread(generate_candidate_readings, question, schema)
                    if len(_cands) >= 2:
                        def _soma_ex(_sql):
                            _r = db.execute("soma_probe", _sql)
                            return (not _r.error, _r.rows or [], _r.error or "")
                        _sv = await asyncio.to_thread(
                            assess_structural_ambiguity, question, _cands, _soma_ex)
                        if _sv.ambiguous:
                            yield _sse("clarify", _sv.to_event())
                            yield _sse("done", {})
                            return
            except Exception:
                logger.debug("SOMA probe failed; proceeding to answer", exc_info=True)

        # ── Ground-first resolution (flag `ask.resolve_first`) ────────────────
        # Decide ONCE, deterministically, whether this is answerable as asked —
        # BEFORE the model writes SQL — and hand the generator the settled facts so
        # it can't silently downgrade the grain or invent a filter value. Off →
        # `_resolution` stays None → byte-identical.
        _resolution = None
        try:
            from aughor.kernel.flags import flag_enabled as _rf_flag
            if _rf_flag("ask.resolve_first"):
                from aughor.semantic.answer_resolution import resolve as _resolve_answer
                _resolution = _resolve_answer(question, schema=_full_schema, db=db,
                                              connection_id=connection_id,
                                              eff_schema=canvas_scope_eff_schema)
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "ground-first resolution is best-effort; answering without it",
                     counter="chat.resolve")

        # Honest abstention: a clear filter entity isn't in the data → say so with
        # what IS present, instead of running an empty filter and narrating around
        # the emptiness (the "Mytheresa isn't a franchise here" case).
        if _resolution is not None and _resolution.feasibility == "not_answerable":
            _abstain = _resolution.caveat
            yield _sse("mode", {"query_mode": "final_text"})
            yield _sse("headline", {"headline": _abstain})
            yield _sse("done", {})
            try:
                await asyncio.to_thread(lambda: save_chat_turn(
                    question=question, connection_id=connection_id, headline=_abstain[:2000],
                    sql="", session_id=session_id, columns=[], rows=[], chart_type="none",
                    tables_used=[], intent="", approach=[], canvas_id=canvas_id))
            except Exception as exc:
                from aughor.kernel.errors import tolerate
                tolerate(exc, "abstention turn save is best-effort; the message was already streamed",
                         counter="chat.resolve_abstain_save")
            yield _sse("followups", {"questions": [
                "What values are available to filter by?",
                "Show the same measure without that filter",
            ]})
            return

        # Constrain generation with what the resolution settled (entity binding,
        # grain ceiling). Highest-priority block → prepended above everything else.
        if _resolution is not None and _resolution.prompt_constraints:
            prompt = _resolution.prompt_constraints + "\n\n" + prompt

        from aughor.agent.complexity import assess_complexity
        _cx = assess_complexity(question)
        # Run the (blocking) LLM call in a worker thread so the event loop stays
        # free to serve other pages (catalog/inbox/home) while the query runs.
        answer: _ChatAnswer = await asyncio.to_thread(
            lambda: get_provider("coder").complete(
                system=CHAT_SQL_SYSTEM, user=prompt, response_model=_ChatAnswer,
            )
        )

        final_sql = answer.sql
        # Trust-receipt provenance signals — recorded ONLY when a guard
        # demonstrably fires this turn (honest lineage, not aspirational).
        _rcpt = {"compiled": False, "defan": False, "grounded": False, "lint": False}
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
                yield _sse("compiled", {
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
                        final_sql = _rw
                        _adopted = True
                        _rcpt["defan"] = True
                        yield _sse("sql", {"sql": final_sql})
                        yield _sse("fanout", {"hub": _ff.hub_root, "satellites": _ff.satellites, "corrected": True})
                if not _adopted:
                    _fanout_fix_hint = _ff.to_prompt_text()
                    yield _sse("fanout", {"hub": _ff.hub_root, "satellites": _ff.satellites})
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "fan-out detection/de-fan guard is best-effort; executing the original SQL",
                     counter="chat.fanout_guard")

        # ── Lint before execution — catch known anti-patterns in code, not prompts ──
        from aughor.sql.lint import lint as _lint_sql, error_hint as _lint_hint, has_errors as _lint_has_errors
        from aughor.sql.writer import SqlWriter
        _lint_issues = _lint_sql(final_sql, dialect=db.dialect)
        if _lint_has_errors(_lint_issues):
            try:
                _writer = SqlWriter(db, schema_str=schema)
                _lint_fix = await asyncio.to_thread(
                    lambda: _writer.fix(
                        final_sql,
                        "SQL quality issues detected before execution",
                        hint=_lint_hint(_lint_issues),
                        max_retries=1,
                    )
                )
                if _lint_fix.ok:
                    final_sql = _lint_fix.sql
                    _rcpt["lint"] = True
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
                _fw = await asyncio.to_thread(check_filter_value_domains, db, final_sql)
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
                final_sql, _pf_receipt = await asyncio.to_thread(
                    preflight_repair, db, final_sql, schema
                )
            except Exception as _e:
                logger.debug("chat pre-flight validation is best-effort; skipped: %s", _e)

        yield _sse("sql", {"sql": final_sql})
        result = await asyncio.to_thread(db.execute, "chat", final_sql)

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
                fix = await asyncio.to_thread(
                    lambda: _writer2.fix(final_sql, _fix_error, hint=_combined_hint, max_retries=2)
                )
                if fix.ok:
                    retry = await asyncio.to_thread(db.execute, "chat", fix.sql)
                    if not retry.error and (retry.row_count > 0 or not _chat_zero_diag or _semantic_fix_hint or _fanout_fix_hint or _scope_fix_hint or _filter_fix_hint or _grain_fix_hint or _idmath_fix_hint or _ratio_fix_hint):
                        final_sql = fix.sql
                        result = retry
                        yield _sse("sql", {"sql": final_sql})
            except Exception as exc:
                from aughor.kernel.errors import tolerate
                tolerate(exc, "post-execution SQL repair is best-effort; serving the original result/error",
                         counter="chat.sql_repair")

        if result.error:
            from aughor.agent.escalate import assess_escalation
            _esc = assess_escalation(question, columns=result.columns, rows=result.rows, error=result.error)
            if _esc.should_offer:
                yield _sse("escalate", _esc.to_event())
            yield _sse("error", {"message": result.error})
            return

        # Ground the headline in the ACTUAL rows — the coder's headline is a pre-execution
        # prediction and can contradict the data it ran on.
        _grounded_headline = _ground_headline(answer.headline, result.columns, result.rows)
        _rcpt["grounded"] = (_grounded_headline or "") != (answer.headline or "")
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
        except Exception as _e:
            logger.debug("chat id-arithmetic backstop is best-effort; skipped: %s", _e)
        # WP-1e — E1 function-semantics checks on the LIVE answer (flag `trust.e1_live`):
        # pure-AST footguns (timestamp bounded by a date-only literal, lexicographic
        # ORDER BY on numeric text, text↔numeric compare) previously ran only on
        # /query/validate — never on an answer a user actually saw. WARN-only: the
        # headline gets the caveat, the SQL is never rewritten (the E1 contract).
        from aughor.kernel.flags import flag_enabled as _flag_enabled
        if final_sql and _flag_enabled("trust.e1_live"):
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
                    logger.info("[chat] E1 trust-check caveat applied to headline: %s",
                                [t.pattern for t in _e1_hits])
            except Exception as _e:
                logger.debug("chat E1 checks are best-effort; skipped: %s", _e)
        # Deterministic concentration→pareto (the renderer never sees the question).
        answer.chart_type = _maybe_pareto(question, result.columns, result.rows, answer.chart_type)
        yield _sse("columns", {"columns": result.columns})
        yield _sse("rows", {"rows": result.rows[:10000]})
        _grounded_headline = _apply_currency(_grounded_headline, _cur_sym)
        yield _sse("headline", {"headline": _grounded_headline})
        yield _sse("chart_type", {"chart_type": answer.chart_type})
        if answer.chart_config:
            yield _sse("chart_config", {"chart_config": answer.chart_config})
        yield _sse("tables_used", {"tables": _extract_tables(final_sql)})
        if answer.intent or answer.approach:
            yield _sse("analysis", {"intent": answer.intent, "steps": answer.approach})
        if pb_entries:
            yield _sse("playbook_refs", {"items": _pb_serialize(pb_entries)})
        if _trusted_used:
            yield _sse("trusted", {"items": _trusted_used})

        # Phase 5 — progressive escalation: if the cheap answer is inconclusive (empty on an
        # analytical question, or a causal "why" answered by a single figure), OFFER a deep
        # investigation (a suggestion the user clicks — not a forced re-run).
        from aughor.agent.escalate import assess_escalation
        _esc = assess_escalation(question, columns=result.columns, rows=result.rows)
        if _esc.should_offer:
            yield _sse("escalate", _esc.to_event())

        # Persist, then mark DONE the moment the answer is ready — so the
        # "Completed in …" time reflects when the user got their answer, not when
        # the post-answer enrichment (inspect + follow-ups) finishes.
        _chat_inv_id = ""
        try:
            _chat_inv_id = await asyncio.to_thread(
                lambda: save_chat_turn(
                    question=question, connection_id=connection_id, headline=_grounded_headline or question,
                    sql=final_sql or "", session_id=session_id, columns=result.columns,
                    rows=result.rows, chart_type=answer.chart_type,
                    tables_used=_extract_tables(final_sql or ""),
                    intent=answer.intent, approach=answer.approach,
                    canvas_id=canvas_id,
                )
            )
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
                    yield _sse(_evt, _receipts[_evt])
            # WP-10: hand the UI the stable receipt id so "Why this number" opens the unified
            # public receipt (GET /receipt/{id}) — one contract across every answer mode.
            if _receipts.get("receipt_id"):
                yield _sse("receipt_id", {"receipt_id": _receipts["receipt_id"]})

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
        yield _sse("done", {"inv_id": _chat_inv_id, "has_receipt": bool(_chat_inv_id and final_sql)})

        # ── Post-answer enrichment (streams in after DONE, never delays it) ──
        # ONE narrator call produces BOTH the analytical insight and the
        # follow-up questions (was two separate round-trips). For trivial result
        # shapes (a single scalar / empty set) there's no trend to interpret, so
        # we ask only for follow-ups and skip the narrative — same single call.
        _insight_dict = None
        _insight_worth_it = len(result.rows) >= 2 or (len(result.rows) == 1 and len(result.columns) >= 3)
        try:
            # Bounded sample: up to 20 rows × 8 columns. For a time series, weight toward the
            # most recent periods so the narrative leads with current state, not year-one.
            _sample_rows, _is_ts = _narrator_sample(result.columns, result.rows)
            _sample_cols = result.columns[:8]
            _rows_text = "\n".join(
                ", ".join(str(r[i]) for i in range(len(_sample_cols))) for r in _sample_rows
            )
            if _insight_worth_it:
                _ts_clause = (
                    " This result is a TIME SERIES shown as the series start then the most recent periods: "
                    "LEAD WITH THE MOST RECENT period and its current trend, and state the net change since "
                    "the start — do NOT anchor the narrative on the earliest period."
                    if _is_ts else ""
                )
                _system = (
                    "You are an analytical data interpreter writing for a clean published brief. "
                    "Given a user question, the SQL that answered it, and a sample of the results: "
                    "(1) produce a tight analytical insight (2-3 sentences) that LEADS WITH THE ANSWER, "
                    "wraps each decisive number in **double asterisks** for bold (e.g. **$2,112**, **+18%**), "
                    "names any genuine anomaly (unexpected value, spike, drop, outlier) in plain words, and "
                    "states the overall trend and your confidence. Start with the finding — no preamble, no "
                    "hedging, no 'the data shows' scaffolding. Use ONLY numbers present in the results; never "
                    "invent values, and bold never licenses invented precision." + _ts_clause + " "
                    "Then (2) suggest exactly 3 concise follow-up data questions (max 12 words each)."
                )
            else:
                _system = (
                    "Given a user question and its answer, suggest exactly 3 concise follow-up data questions "
                    "(max 12 words each). Leave the narrative empty."
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
            _user = (
                f"Question: {question}\n"
                f"SQL: {final_sql}\n"
                f"Answer: {answer.headline}\n"
                f"{_rows_label}\n"
                f"Columns: {', '.join(_sample_cols)}\n"
                f"{_rows_text}"
                f"{_res_note}"
            )
            # CK-0.2 token-streaming (flag `ask.stream_text`, default ON): dual-emit the
            # narrative as `insight_delta` frames while the narrator writes it, then let
            # the existing terminal `insight` event carry the authoritative final value —
            # self-healing (a dropped delta costs nothing; old clients ignore the unknown
            # event). Flag off = the exact pre-streaming blocking call, byte-identical.
            from aughor.kernel.flags import flag_enabled as _stream_flag
            if _stream_flag("ask.stream_text"):
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
                                               name="insight-stream")
                _pa_thread.start()
                # Drain partials → SSE deltas, throttled (grew ≥12 chars since the last
                # emit, or >150ms elapsed) so a chatty stream can't spam frames. Deltas
                # go out strictly BEFORE the terminal `insight` event, and only when the
                # insight is worth narrating (same gate the terminal event uses).
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
                    _item = await asyncio.to_thread(_pa_poll)
                    if _item is _POLL_EMPTY:
                        continue
                    if _item is None:
                        break
                    if not (_insight_worth_it and isinstance(_item, str)):
                        continue
                    _now = _time.monotonic()
                    if len(_item) - _last_len >= 12 or _now - _last_ts > 0.150:
                        _last_len, _last_ts = len(_item), _now
                        yield _sse("insight_delta",
                                   {"narrative": _apply_currency(_item, _cur_sym)})
                await asyncio.to_thread(_pa_thread.join)
                if "exc" in _pa_result:
                    raise _pa_result["exc"]
                _pa: _PostAnswer = _pa_result["pa"]
            else:
                _pa = await asyncio.to_thread(
                    lambda: get_provider("narrator").complete(
                        system=_system,
                        user=_user,
                        response_model=_PostAnswer,
                        temperature=0.2,
                    )
                )
            if _insight_worth_it and _pa.narrative:
                _insight_dict = {
                    "narrative": _apply_currency(_pa.narrative, _cur_sym),
                    "anomalies": _pa.anomalies[:3],
                    "trend": _pa.trend,
                    "confidence": _pa.confidence,
                }
                yield _sse("insight", _insight_dict)
                # Persist insight so it survives page reload / history navigation
                if _chat_inv_id:
                    try:
                        from aughor.db.history import update_chat_turn_insight
                        await asyncio.to_thread(lambda: update_chat_turn_insight(_chat_inv_id, _insight_dict))
                    except Exception as exc:
                        from aughor.kernel.errors import tolerate
                        tolerate(exc, "insight persistence is best-effort; the insight was already streamed this session",
                                 counter="chat.insight_persist")
            if _pa.questions:
                yield _sse("followups", {"questions": _pa.questions[:3]})
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "post-answer insight/follow-up enrichment is best-effort; the answer is already done",
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
                _ir = await asyncio.to_thread(
                    lambda: _inspect_sql(question, final_sql, result.columns, result.rows,
                                         schema=_full_schema)
                )
                if not _ir.valid and _ir.issues:
                    yield _sse("inspect_warning", {
                        "issues":        _ir.issues,
                        "suggested_fix": _ir.suggested_fix,
                    })
            except Exception as exc:
                from aughor.kernel.errors import tolerate
                tolerate(exc, "post-answer semantic inspect is best-effort validation; skipping the warning",
                         counter="chat.inspect")

    except Exception as e:
        yield _sse("error", {"message": str(e)})
    finally:
        try:
            db.close()
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "chat stream connection close is best-effort cleanup",
                     counter="chat.db_close")


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
        yield _sse("error", {"message": str(e)})
        return
    except Exception as e:
        yield _sse("error", {"message": f"Could not connect: {e}"})
        return

    # ── Tier 0: the trace is a READ, not a re-run ──────────────────────────────
    # Drilling into a known finding? The explorer already did the deep analysis and
    # captured it in the Finding Dossier. Serve that as the trace — a deterministic
    # ledger lookup by insight id (no semantic-match guess, no ADA, no SQL, no LLM).
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

    inv_id = create_investigation(question, connection_id, canvas_id=canvas_id, agent_id=_current_agent_id())
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
            schema = link_schema(question, schema, top_k_tables=4, top_k_cols=8, connection_id=connection_id)
        except Exception:
            logger.warning("Schema-linking pre-filter failed (agentic path); using full schema", exc_info=True)
        # Build structured Data Catalog (MindsDB-style) from linked tables
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
                for _dt in temporal_dimension_tables(full_schema, linked_tables, question):
                    if _dt not in linked_tables:
                        linked_tables.append(_dt)
                linked_tables = fk_neighbor_expand(full_schema, linked_tables, cap=10)
                # Scope the expansion to the canvas schema: temporal/FK expansion walks the
                # FULL schema and can pull a sibling schema's same-named table (netflix.products
                # into a missimi investigation), which then becomes a cross-schema reference the
                # explore planner copies verbatim (bypassing search_path). Drop out-of-scope tables.
                if scope_schema:
                    _allow = scope_schema.strip().lower()
                    linked_tables = [t for t in linked_tables
                                     if "." not in t or t.split(".")[0].strip().lower() == _allow]
                data_catalog = await asyncio.to_thread(
                    lambda: build_data_catalog(db, linked_tables)
                )
        except Exception:
            logger.warning("Data Catalog build failed (agentic path); using linked schema", exc_info=True)

        # Hard cap: max 10 tables in context (MindsDB best practice)
        try:
            from aughor.tools.data_catalog import enforce_context_cap
            schema = enforce_context_cap(schema, max_tables=10)
            if data_catalog:
                data_catalog = enforce_context_cap(data_catalog, max_tables=10)
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "10-table context cap is best-effort; investigating with the uncapped schema context",
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

        # Prefer structured Data Catalog as the primary schema context (MindsDB-style)
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
        from aughor.kernel.flags import flag_enabled as _flag_enabled
        _clarify_gate = _flag_enabled("ada.clarify_gate")
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
            "schema_context": schema_for_agent, "unresolved_tensions": [], "scan_context": "", "events_context": "",
            "hypotheses": [], "current_hypothesis_idx": 0, "query_history": [], "evidence_scores": [],
            "pitfalls": [], "prior_analyses": _seed_priors, "origin_finding": _origin, "iteration": 0,
            "max_iterations": int(os.getenv("AUGHOR_MAX_ITER", "6")),
            "report": None, "hitl_enabled": hitl, "human_feedback": None,
            "query_mode": None, "route_reasoning": None, "route_confidence": None, "replan_decision": None,
            # /investigate IS the explicit Deep Analysis surface — the user chose depth.
            # route_question honors this and never lets the LLM classifier downgrade the
            # run to a 'direct' lookup (live incident: "Where are we losing money?" ran as
            # 3 flat queries with a fake 'direct' hypothesis, zero decomposition). The /ask
            # auto-router doesn't set it, so auto-depth behavior is unchanged.
            "requested_mode": "investigate",
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
            if "__ada_progress__" in event:            # P2 live per-dimension progress (flag-gated)
                yield _sse("phase_progress", event["__ada_progress__"])
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
                    from aughor.llm.provider import get_provider as _gp
                    fq: _FollowUpBase = _gp("narrator").complete(system="Suggest exactly 3 concise follow-up investigation questions (max 15 words each).", user=f"Original question: {question}\nFindings: {ada.get('headline', '') if isinstance(ada, dict) else str(ada)[:200]}", response_model=_FollowUpBase)
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
                _ada_rcpt = _write_answer_receipt(
                    kind="ada_report", natural_key=f"ada:{connection_id}:{inv_id}",
                    question=question, sqls=_ada_sqls(ada) or [r.sql for r in qh if getattr(r, "sql", None)],
                    headline=(ada.get("headline", "") if isinstance(ada, dict) else ""),
                    schema=full_schema, connection_id=connection_id, canvas_id=canvas_id,
                    payload_extra={"investigation_id": inv_id},
                )
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
                    from aughor.llm.provider import get_provider as _gp
                    fqx: _FollowUpBase = _gp("narrator").complete(system="Suggest exactly 3 concise follow-up questions (max 15 words each).", user=f"Original question: {question}\nFindings: {er.headline}", response_model=_FollowUpBase)
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
                    from aughor.llm.provider import get_provider as _gp
                    rep = merged["report"]
                    summary = getattr(rep, "summary", "") or getattr(rep, "headline", "")
                    fqr: _FollowUpBase = _gp("narrator").complete(system="Suggest exactly 3 concise follow-up investigation questions (max 15 words each).", user=f"Original question: {question}\nFindings: {str(summary)[:300]}", response_model=_FollowUpBase)
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
            salvaged = _try_salvage(merged, inv_id, question, connection_id, schema=full_schema)
            if salvaged:
                yield salvaged
            else:
                yield _sse("error", {"message": f"Investigation timed out after {_TIMEOUT}s."})
                fail_investigation(inv_id, status="timed_out")
        elif not report_emitted:
            # The graph terminated without reaching a synthesis node — e.g. every
            # query errored and the loop exhausted its iterations. First try a
            # best-effort synthesis from whatever evidence exists; only if there's
            # genuinely nothing to salvage do we surface a terminal stall message.
            salvaged = _try_salvage(merged, inv_id, question, connection_id, schema=full_schema)
            if salvaged:
                yield salvaged
            else:
                yield _sse("error", {"message": _stall_summary(merged)})
                fail_investigation(inv_id, status="failed")

    except Exception as e:
        # An unhandled node exception still shouldn't lose partial work — salvage
        # a best-effort report from gathered evidence before surfacing the error.
        salvaged = _try_salvage(merged, inv_id, question, connection_id, schema=full_schema)
        if salvaged:
            yield salvaged
        else:
            fail_investigation(inv_id, status="failed")
            yield _sse("error", {"message": str(e)})
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
    chosen = next((r for r in readings if r.get("label") == clarify_choice), readings[0])
    patch: dict = {"_clarify_pending": None}
    if chosen.get("sql"):
        intake = dict(merged.get("_ada_intake") or {})
        intake["metric_sql"] = chosen["sql"]
        intake["metric_is_ratio"] = bool(chosen.get("is_ratio"))
        patch["_ada_intake"] = intake
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
                 counter="ada.clarify_crystallize")
    return patch


async def _stream_resume(inv_id: str, feedback: str, request: Request,
                         keep_subquestions: Optional[list[int]] = None,
                         clarify_choice: Optional[str] = None) -> AsyncGenerator[str, None]:
    inv = get_investigation(inv_id)
    if not inv:
        yield _sse("error", {"message": "Investigation not found"})
        yield _sse("done", {})
        return
    if inv.get("status") != "paused":
        yield _sse("error", {"message": f"Investigation is not paused (status: {inv.get('status')})"})
        yield _sse("done", {})
        return
    # Resume with the canvas scope (declared schema + derived owning-schema pin) if applicable.
    from aughor.canvas.scope import resolve_execution_scope
    try:
        db = resolve_execution_scope(inv["connection_id"], inv.get("canvas_id")).open()
    except Exception as e:
        yield _sse("error", {"message": str(e)})
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
                yield _sse("error", {"message": "Timed out waiting for synthesis."})
                fail_investigation(inv_id, status="timed_out")
                return
            if "__ada_progress__" in event:            # P2 live per-dimension progress (flag-gated)
                yield _sse("phase_progress", event["__ada_progress__"])
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
        yield _sse("error", {"message": str(e)})
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
    chat/insight path is not a kernel job, so it has no JobKernel._run (to flush its
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
        yield _sse("error", {"message": f"Answer stopped — {be.reason} exceeded. "
                                        f"Raise the Insight agent's budget in Fleet → Agents."})
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
    return StreamingResponse(
        _metered_stream(
            _stream_chat(req.question, conn_id, req.history, request,
                         session_id=req.session_id, canvas_id=req.canvas_id),
            budget=_insight_budget(conn_id),
        ),
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
            ):
                await queue.put(sse)
        finally:
            # Always release the client drainer, even on cancellation/error.
            queue.put_nowait(_STREAM_END)

    job_id = await kernel().submit(
        "investigation", _drive,
        conn_id=connection_id, canvas_id=canvas_id,
        payload={"question": question[:200]},
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
            insight_id=req.insight_id, deep=req.deep, history=req.history,
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
        and not req.deep and not req.insight_id and not req.canvas_id
        and not req.history and not req.skip_clarify
    )


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
    from aughor.kernel.flags import flag_enabled

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
            answer_federated, question, sel.conn_ids, reconcile=flag_enabled("join.key_reconciliation"),
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


def _program_eligible(req) -> bool:
    """Whether a ``/ask`` turn may answer via plan-as-program (Rec 4): only a truly FRESH auto turn — not a
    depth override, deep-drill, dossier, canvas/conversational follow-up, or a clarify-answer. Mirrors
    ``_federation_eligible``. Flag-gated on ``plan.program`` (default off), checked first for the short-circuit."""
    from aughor.kernel.flags import flag_enabled
    return bool(
        flag_enabled("plan.program") and req.depth == "auto"
        and not req.deep and not req.insight_id and not req.canvas_id
        and not req.history and not req.skip_clarify
    )


async def _stream_program(pr, conn_id: str) -> AsyncGenerator[str, None]:
    """Stream an already-computed plan-as-program ``ProgramResult`` as ``/ask`` events (Rec 4 answer-path).

    Emits a program ``route`` receipt (step count + rationale) then the final table using the same primitives
    the quick path uses (columns/rows/headline/sql/tables_used), so it renders in the existing answer surface.
    The program was already run ONCE by the caller — this only serializes the result (never re-runs it)."""
    n_steps = len(pr.program.steps) if pr.program else 0
    why = (pr.program.rationale if (pr.program and pr.program.rationale)
           else f"Answered via a deterministic {n_steps}-step program (plan→validate→run).")
    yield _sse("route", {
        "depth": "program", "mode": "program", "tier": "complex",
        "score": 1.0, "confidence": 1.0, "ambiguous": False,
        "why": why, "alternatives": ["quick", "deep"], "forced": None, "downgraded_from": None,
        "steps": n_steps,
    })
    r = pr.result
    streamed = r.rows[:10000]
    more = f" (showing first {len(streamed):,})" if r.row_count > len(streamed) else ""
    yield _sse("columns", {"columns": r.columns})
    yield _sse("rows", {"rows": streamed})
    yield _sse("headline", {"headline": f"Answered via a {n_steps}-step program — {r.row_count:,} rows{more}."})
    yield _sse("sql", {"sql": r.sql})
    yield _sse("tables_used", {"tables": _extract_tables(r.sql)})
    if pr.warnings:
        yield _sse("program_warnings", {"warnings": pr.warnings})
    yield _sse("done", {})


async def _stream_ask(req: "AskRequest", request: Request, conn_id: str) -> AsyncGenerator[str, None]:
    """The unified door: decide depth, emit the `route` receipt, then delegate to the
    existing quick (Insight) or deep (ADA/explore) body unchanged.

    The depth call is license-safe — a deep route degrades to quick when the
    connection lacks DEEP_ANALYSIS — and the legacy `deep`/`insight_id` flags still
    drive the "Investigate deeper" escalation and the dossier drill through one door.
    """
    from aughor.agent.ask_router import decide_ask_route
    from aughor.licensing import has_capability

    # I4 — if this turn is the user ANSWERING a clarify (a reading chosen from the chips),
    # crystallize that choice into the Ambiguity Ledger (source=user) BEFORE we answer, so the
    # resolution is an authoritative prior on this turn and every future one — the class never
    # re-ambiguates on this connection. Gated with the ledger (closed_loop); best-effort.
    if req.clarify_reading:
        from aughor.verify.priors import closed_loop_enabled
        if closed_loop_enabled():
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
    # Budget is one ask/turn — the user's answer comes back with skip_clarify set.
    # Flag `ask.clarify` (env AUGHOR_ASK_CLARIFY) is the rare DEFAULT-ON flag.
    from aughor.kernel.flags import flag_enabled

    if (req.depth == "auto" and not req.deep and not req.insight_id and not req.skip_clarify
            and flag_enabled("ask.clarify")):
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

    # Plan-as-program (Rec 4 answer-path): on a fresh single-connection auto turn, answer via a deterministic
    # typed program (plan→validate→run over this connection) instead of the single-shot route. The program
    # runs ONCE here; on any failure or empty answer we fall through to the normal routing below — a program
    # that can't answer must never dead-end the turn. Flag-gated on `plan.program` → default off = byte-identical.
    if _program_eligible(req):
        from aughor.kernel.errors import tolerate
        pr = None
        try:
            from aughor.agent.program_planner import answer_program
            from aughor.org.context import current_org_id
            pr = await asyncio.to_thread(answer_program, req.question, conn_id,
                                         org_id=current_org_id() or "")
        except Exception as exc:  # noqa: BLE001 — best-effort; fall through to normal routing
            tolerate(exc, "plan-as-program is best-effort; fall through to normal routing",
                     counter="ask.program_failed")
        if pr is not None and not pr.result.error:
            async for _ev in _stream_program(pr, conn_id):
                yield _ev
            return
        if pr is not None:
            tolerate(Exception(pr.result.error or "program produced no answer"),
                     "plan-as-program returned no answer; fall through to normal routing",
                     counter="ask.program_no_answer")

    has_deep = has_capability(Capability.DEEP_ANALYSIS, conn_id=conn_id)
    # decide_ask_route may consult the LLM intent classifier on borderline questions,
    # so run it off the event loop.
    route = await asyncio.to_thread(
        decide_ask_route, req.question,
        depth_override=req.depth, deep_flag=req.deep,
        insight_id=req.insight_id, has_deep=has_deep,
    )
    yield _sse("route", route.to_event())

    if route.depth == "deep":
        async for sse in _investigation_job_streamed(
            req.question, conn_id, request,
            hitl=req.hitl, skip_cache=req.skip_cache, canvas_id=req.canvas_id,
            schema_scope=req.schema_name, seed_sql=req.seed_sql,
            seed_context=req.seed_context, insight_id=req.insight_id, deep=req.deep,
            history=req.history,  # follow-up composition on the deep path (parity with quick)
        ):
            yield sse
    else:
        async for sse in _metered_stream(
            _stream_chat(req.question, conn_id, req.history, request,
                         session_id=req.session_id, canvas_id=req.canvas_id,
                         skip_clarify=req.skip_clarify),
            budget=_insight_budget(conn_id),
        ):
            yield sse


@router.post("/ask")
async def ask_endpoint(req: AskRequest, request: Request):
    """One conversational entry — the router picks quick vs deep (auto+transparency).

    Not gated on DEEP_ANALYSIS as a dependency: a quick answer only needs chat access,
    and a deep route is capability-checked inside `_stream_ask` (degrade, never bypass).
    `/chat` and `/investigate` remain as-is for back-compat through the transition.
    """
    if os.getenv("AUGHOR_UNIFIED_ASK", "1").lower() in ("0", "false", "no", "off"):
        raise HTTPException(status_code=404, detail="unified /ask is disabled")
    conn_id = _resolve_conn(req)
    agent = _resolve_ask_agent(req)
    if agent is not None:
        conn_id = _apply_agent_bindings(req, agent, conn_id)
    stream = _stream_ask(req, request, conn_id)
    stream = _stream_with_session(req.session_id, stream)  # ambient session → trace attribution
    if agent is not None:
        stream = _stream_as_agent(agent, stream)
    return StreamingResponse(
        stream,
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
    the same blocks the answer path assembles from the same producers). 404 when
    the flag is off, so the default path is byte-identical.
    """
    from aughor.kernel.flags import flag_enabled
    if not flag_enabled("ask.context_receipt"):
        raise HTTPException(status_code=404,
                            detail="grounding-context receipt is disabled (flag ask.context_receipt)")
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
    """The user-defined agent this ask runs as, or None (flag off / no agent_id)."""
    if not req.agent_id:
        return None
    from aughor.kernel.flags import flag_enabled
    if not flag_enabled("agents.user_defined"):
        raise HTTPException(status_code=404,
                            detail="user-defined agents are disabled (flag agents.user_defined)")
    from aughor.user_agents import get_agent
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
    from aughor.user_agents.context import current_agent
    agent = current_agent()
    return agent.id if agent is not None else ""


def _persona_for_investigation(inv_id: str):
    """The user-agent persona a checkpointed deep run was launched AS, or None.

    Resume (plan/clarify-gate feedback) never passes through /ask, so the
    persona is re-read from the run's persisted state (`agent_id`). Fail-open:
    a missing checkpoint, an unknown/disabled agent, or the flag being off all
    resume the run WITHOUT the persona rather than blocking it."""
    from aughor.kernel.flags import flag_enabled
    if not flag_enabled("agents.user_defined"):
        return None
    try:
        from aughor.agent.graph import read_checkpoint_values
        agent_id = read_checkpoint_values(inv_id).get("agent_id") or ""
        if not agent_id:
            return None
        from aughor.user_agents import get_agent
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
    from aughor.user_agents.context import activate_agent, release_agent
    token = activate_agent(agent)
    try:
        yield _sse("agent", {"agent_id": agent.id, "name": agent.name,
                             "connection_id": agent.connection_id,
                             "doc_count": len(agent.doc_ids)})
        async for event in stream:
            yield event
    finally:
        release_agent(token)


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


@router.post("/investigations/{inv_id}/feedback")
async def submit_feedback(inv_id: str, req: FeedbackRequest, request: Request):
    stream = _stream_resume(inv_id, req.feedback, request, keep_subquestions=req.keep_subquestions,
                            clarify_choice=req.clarify_choice)
    # agents.user_defined — a deep run launched AS an agent resumes AS it: the
    # persona persists in the run's checkpointed state (resume never passes
    # through /ask). Fail-open: no persona → resume unchanged.
    persona = _persona_for_investigation(inv_id)
    if persona is not None:
        stream = _stream_as_agent(persona, stream)
    return StreamingResponse(
        stream,
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


@router.get("/investigations/{inv_id}/export")
def export_investigation(inv_id: str, format: str = "pdf", narrate: bool = False,
                         principal=Depends(get_principal)):
    """Download a stored analysis as a polished PDF or PowerPoint (`format=pdf|pptx`).

    `narrate=true` prepends an LLM-authored executive summary (best-effort; the
    export still succeeds if the model is slow or unavailable)."""
    from fastapi.responses import Response
    from aughor.export import export_report
    from aughor.security.authz import check_owner

    check_owner("investigation", inv_id, principal)  # SEC-05: no cross-org export
    inv = get_investigation(inv_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Investigation not found")
    fmt = (format or "pdf").lower()
    if fmt not in ("pdf", "pptx"):
        raise HTTPException(status_code=400, detail="format must be 'pdf' or 'pptx'")
    try:
        data, filename, media_type = export_report(inv, fmt, narrate=narrate)
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
            from aughor.process.causal import promote_on_outcome
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
