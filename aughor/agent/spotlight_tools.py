"""SP-1 — Spotlight's Know roster: org-level platform reads for conversation (§3.11).

CI-2 gave conversation the *connection's* surfaces (graph, findings, briefing, packs).
This module gives it the *platform's* surfaces — connections, spend, runs, cadence,
answer-quality, table popularity — so the questions an operator actually asks ("how many
connections do we have?", "what did last week cost?", "which table gets queried the
most?") stop dead-ending. The user's own four acceptance questions (§3.11, 2026-09-05)
are this roster's receipt suite; each tool below names the question it exists to answer.

Rules, inherited rather than invented:

* **Every tool is a read.** Same contract as :mod:`aughor.agent.platform_tools`, stated
  in the same absolute terms: a roster where "every tool is a read" is nearly true is
  worse than one where it is exactly true. Spotlight's Act limb lives next door in
  :mod:`aughor.agent.spotlight_act` (SP-3), the way ``action_tools`` does.
* **Claims are bound to tool results** (CI-3's latitude law): these tools exist so the
  model never answers a platform-state question from priors. Where a number is UNKNOWN
  the result says so in its own field — an unpriced call is not a free call, an unmined
  popularity store is not an unpopular table, and a thin verdict sample is not an
  accuracy. The honesty fields are the answer, not padding around it.
* **Org scope rides the contextvar** (``current_org_id``), exactly as the /usage and
  /learning surfaces do; connection-flavoured reads bind the conversation's connection
  by closure, so the model cannot name a connection it was not given.
* **The context window is the budget.** Grouped results are capped and say when cut.
* **Every result carries a pre-composed `summary` sentence** (added 2026-09-06 after a
  live re-drive on a different chat model): the numbers, honesty clauses and units,
  already worded — because a model re-deriving prose from fields garbled a
  deterministic count (reported 32/27/5 where the tool said 22/18/4) and turned USD
  into €. The summary is built from the SAME locals as the fields, so the two cannot
  disagree; the descriptions tell the model to quote it verbatim.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from aughor.agent.tool_loop import ToolSpec

logger = logging.getLogger(__name__)

#: Quotable in an answer verbatim — the narrator's disclosure for windowed questions.
_POPULARITY_SCOPE = ("cumulative mined history since this connection was first profiled "
                     "— these counts cannot be filtered to a date window; report them as "
                     "all-time and say so when the question asked for a window")

_MAX_GROUPS = 8
_MAX_CONNECTIONS = 50
_MAX_POPULAR = 15
_MAX_TREND_WEEKS = 4
_USAGE_SCAN = 20_000
_MAX_TRACES = 20
_TRACE_SCAN = 4_000
_MAX_AUDIT = 50


def _org() -> str:
    from aughor.org.context import current_org_id
    return current_org_id()


def list_platform_connections(args: dict) -> dict:
    """Every connection this deployment has — the "how many, and what are they" read."""
    from aughor.db.registry import list_connections

    conns = list_connections(org_id=_org() or None)
    out = [{
        "id": c.get("id", ""),
        "name": c.get("name") or c.get("id", ""),
        "type": c.get("conn_type") or c.get("type") or "",
    } for c in conns[:_MAX_CONNECTIONS]]
    shown = ", ".join(f"{c['name']} ({c['type']})" if c['type'] else c['name']
                      for c in out[:6])
    extra = f", +{len(conns) - 6} more" if len(conns) > 6 else ""
    res = {
        "count": len(conns),
        "summary": f"This deployment has {len(conns)} data connections: {shown}{extra}.",
        "connections": out,
    }
    if len(conns) > _MAX_CONNECTIONS:
        res["note"] = f"listing capped at {_MAX_CONNECTIONS} of {len(conns)}"
    return res


def platform_usage(args: dict) -> dict:
    """Windowed model usage and cost — calls, tokens, USD — grouped by one axis.

    Reads the session log through its own windowed reader (``since`` is the ledger's
    documented ISO bound) and rolls up with the pure grouper, so this tool and the
    /usage page cannot disagree about arithmetic. The honesty fields travel:
    ``calls_without_usage`` (backend reported no token counts — UNKNOWN, not zero) and
    ``unpriced_calls`` (no declared price — cost UNKNOWN, not free). ``cost_is_complete``
    is true only when nothing was unpriced.
    """
    from aughor.kernel.ledger import Ledger
    from aughor.obs.session_log import LLM_CALL
    from aughor.obs.usage import AXES, rollup

    days = max(1, min(int(args.get("days") or 7), 90))
    by = str(args.get("by") or "model").strip().lower()
    # The parameter prose offers plain words (agent, connection, user, org) so the
    # tool-prose ratchet holds; map them onto the rollup's real axis names.
    by = {"agent": "agent_id", "connection": "conn_id", "user": "user_id",
          "org": "org_id"}.get(by, by)
    if by not in AXES:
        return {"error": f"unknown axis {by!r}", "known_axes": sorted(AXES)}
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    events = Ledger.default().session_events(
        kind=LLM_CALL, org_id=_org() or None, since=since, limit=_USAGE_SCAN)
    report = rollup(events, axes=(by,))

    total_tokens = sum(r.total_tokens for r in report.rows)
    cost_usd = round(sum(r.cost_usd for r in report.rows), 4)
    unpriced = sum(r.unpriced_calls for r in report.rows)
    no_usage = sum(r.calls_without_usage for r in report.rows)
    groups = [{
        by: r.key.get(by, ""), "calls": r.calls, "total_tokens": r.total_tokens,
        "cost_usd": round(r.cost_usd, 4),
    } for r in report.rows[:_MAX_GROUPS]]

    plain = {"agent_id": "agent", "conn_id": "connection", "user_id": "user",
             "org_id": "org"}.get(by, by)
    top = f" Most-used {plain}: {groups[0][by]} ({groups[0]['calls']} calls, "           f"{groups[0]['total_tokens']:,} tokens)." if groups else ""
    complete = unpriced == 0 and no_usage == 0
    cost_line = (f"Cost ${cost_usd:.2f} USD (complete — every call priced)." if complete
                 else f"Cost ${cost_usd:.2f} USD is a FLOOR, not the full spend — "
                      f"{unpriced} calls have no declared price and {no_usage} "
                      f"reported no token usage.")
    res = {
        "window_days": days, "since": since, "grouped_by": by,
        "summary": (f"Last {days} days: {report.total_calls} model calls, "
                    f"{total_tokens:,} tokens.{top} {cost_line}"),
        "total_calls": report.total_calls, "total_tokens": total_tokens,
        "cost_usd": cost_usd, "cost_is_complete": complete,
        "unpriced_calls": unpriced, "calls_without_usage": no_usage,
        "groups": groups,
    }
    if len(report.rows) > _MAX_GROUPS:
        res["note"] = f"groups capped at {_MAX_GROUPS} of {len(report.rows)}"
    if report.total_calls >= _USAGE_SCAN:
        res["note_scan"] = (f"scan cap {_USAGE_SCAN} reached — totals cover the newest "
                            f"{_USAGE_SCAN} calls of the window, not necessarily all of it")
    return res


def platform_runs(args: dict) -> dict:
    """Runs across the platform in a trailing window — deep-analysis runs from the
    history store, automation ticks counted BY OUTCOME at the automations store.

    The automation half is a store-level COUNT over the window, never a scan of the
    newest N rows: the live drive on 2026-09-06 caught the scan variant reporting
    5 fired where the windowed truth was 83 (a busy deployment ticks >10k times a
    week). A soft caveat under a 16× wrong number is not honesty — the right query is.
    """
    from aughor.automations.store import count_runs_since
    from aughor.db.history import investigation_counts_since

    days = max(1, min(int(args.get("days") or 7), 90))
    floor_day = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")

    inv = investigation_counts_since(days)
    outcomes = count_runs_since(floor_day)
    total_ticks = sum(outcomes.values())
    still = max(inv["started"] - inv["finished"], 0)
    ticks = ", ".join(f"{k.replace('_', ' ')} {v:,}"
                      for k, v in sorted(outcomes.items(), key=lambda kv: -kv[1]))
    return {
        "window_days": days, "since_day": floor_day,
        "summary": (f"Last {days} days (since {floor_day}): {inv['started']} "
                    f"deep-analysis runs started — {inv['succeeded']} succeeded, "
                    f"{inv['failed']} failed"
                    + (f", {still} still running" if still else "")
                    + f". Automation ticks: {total_ticks:,} total"
                    + (f" — {ticks}." if ticks else ".")),
        "deep_runs": inv,
        "automation_runs": {"total": total_ticks, "by_outcome": outcomes},
    }


def investigation_cadence(args: dict) -> dict:
    """Deep runs per calendar month plus the monthly average — the cadence read."""
    from aughor.db.history import investigations_by_month

    months = max(1, min(int(args.get("months") or 6), 36))
    out = investigations_by_month(months)
    counts = [p["started"] for p in out["series"]] or [0]
    out["summary"] = (f"Last {out['months']} calendar months: "
                      f"{out['monthly_average']} deep-analysis runs per month on "
                      f"average (range {min(counts)}–{max(counts)}; months with "
                      f"zero runs are counted, not skipped).")
    return out


def answer_accuracy(connection_id: str, args: dict) -> dict:
    """The graded quality of answers — verdict counts, acceptance rate, and the size of
    the graded sample, which is the number that decides how much the rate means.

    Bound to the conversation's connection by closure, like every other tool: the
    binding law ("a tool that cannot express the wrong connection cannot be talked
    into it") applies to reads too. An org-wide variant is a later, deliberate tool."""
    from aughor.feedback.verdicts import verdict_stats
    from aughor.semantic.trusted_queries import list_trusted

    cid = connection_id
    stats = verdict_stats(cid or None)
    trend = (stats.get("trend") or [])[-_MAX_TREND_WEEKS:]
    total = int(stats.get("total") or 0)
    rate = stats.get("acceptance_rate")
    tq = len(list_trusted(cid)) if cid else None
    res = {
        "connection_id": cid or "(all)",
        "graded_total": total,
        "verdict_counts": stats.get("counts") or {},
        "acceptance_rate": rate,
        "recent_weeks": trend,
        "trusted_queries": tq,
    }
    if total == 0:
        res["caveat"] = ("no graded verdicts yet — there is no accuracy number to "
                         "report, which is different from accuracy being low")
        res["summary"] = ("No graded verdicts yet on this connection — no accuracy "
                          "number exists to report; that is an absence of grading, "
                          "not low accuracy."
                          + (f" {tq} verified query patterns exist." if tq else ""))
    else:
        rate_pct = f"{round(rate * 100, 1)}%" if rate is not None else "n/a"
        if total < 30:
            res["caveat"] = (f"only {total} graded verdicts — quote the rate WITH the "
                             "sample size; grading volume is what firms this number up")
            res["summary"] = (f"Acceptance rate {rate_pct} over only {total} graded "
                              f"verdicts on this connection — a thin sample; the rate "
                              f"means little until grading volume grows."
                              + (f" {tq} verified query patterns exist." if tq else ""))
        else:
            res["summary"] = (f"Acceptance rate {rate_pct} over {total} graded "
                              f"verdicts on this connection."
                              + (f" {tq} verified query patterns exist." if tq else ""))
    return res


def table_popularity(connection_id: str, args: dict) -> dict:
    """Which tables (and columns) real queries touch most, from the mined popularity
    store — THE source for that question; never answered with warehouse SQL.

    Counts are CUMULATIVE since mining began and cannot be filtered to a date window;
    the `scope` field says so in words the narrator can quote, because the live drive
    on 2026-09-06 showed what happens otherwise: asked "in the last 7 days", the model
    distrusted the un-windowed counts it was holding, wrote a warehouse query for an
    answer the warehouse cannot give, got 0, and reported 0 over real data. An empty
    store is reported as NOT MINED — an unmined store and an unqueried warehouse look
    identical in the counts, and only one of those is a finding."""
    from aughor.sql.popularity import load_popularity

    top = max(1, min(int(args.get("top") or 10), _MAX_POPULAR))
    counts = load_popularity(connection_id)
    tables = sorted((counts.get("table") or {}).items(), key=lambda kv: -kv[1])
    columns = sorted((counts.get("column") or {}).items(), key=lambda kv: -kv[1])
    if not tables and not columns:
        return {
            "connection_id": connection_id, "mined": False,
            "scope": _POPULARITY_SCOPE,
            "summary": ("The popularity store holds nothing for this connection — "
                        "not mined yet (mining runs with the schema birth job); an "
                        "unmined store is not an unqueried warehouse."),
            "answer": ("the popularity store holds nothing for this connection — say "
                       "'not mined yet', never 'nothing is queried'; mining runs with "
                       "the schema birth job"),
        }
    q_total = int(sum(n for _, n in tables))
    top3 = ", ".join(f"{t} ({n:,})" for t, n in tables[:3])
    return {
        "connection_id": connection_id, "mined": True,
        "scope": _POPULARITY_SCOPE,
        "summary": (f"All-time since mining began — this cannot be filtered to a "
                    f"date window: {q_total:,} queries touching {len(tables):,} "
                    f"distinct tables and {len(columns):,} distinct columns on this "
                    f"connection. Top tables: {top3}."),
        "queries_mined": q_total,
        "distinct_tables": len(tables),
        "distinct_columns": len(columns),
        "top_tables": [{"table": t, "queries": n} for t, n in tables[:top]],
        "top_columns": [{"column": c, "queries": n} for c, n in columns[:top]],
    }


def platform_traces(args: dict) -> dict:
    """Recent runs from the session ledger — or one run's anatomy, by trace id.

    METADATA ONLY, deliberately: names, timings, counts, error classes. Span
    payloads (the actual inputs and outputs) are §6.4's gated class — reading one
    is an audited act on the Traces page, and a conversational read that skipped
    that audit would be the break-glass without the glass. This tool cannot
    express the request, which is the binding law applied to depth."""
    from aughor.obs.session_log import recent_sessions, recover_session

    trace_id = str(args.get("trace_id") or "").strip()
    if not trace_id:
        days = max(1, min(int(args.get("days") or 7), 90))
        limit = max(1, min(int(args.get("limit") or 10), _MAX_TRACES))
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        rows = recent_sessions(org_id=_org() or None, limit=limit, since=since,
                               scan=_TRACE_SCAN)
        failed = sum(1 for r in rows if not r.get("ok"))
        out = [{k: r.get(k) for k in (
            "trace_id", "started", "question", "ok", "errors", "tool_calls",
            "llm_calls", "duration_ms", "total_tokens", "agent_id", "conn_id")}
            for r in rows]
        return {
            "window_days": days, "since": since,
            "summary": (f"Newest {len(rows)} runs of the last {days} days"
                        + (f" — {failed} of them not ok" if failed else ", all ok")
                        + ". Metadata only; span-level inputs and outputs live on "
                          "the Traces page behind the audited read."),
            "runs": out,
            "note": (f"folded from the newest {_TRACE_SCAN} ledger events — a "
                     f"busier window may hold older runs this scan did not reach"),
        }

    events = recover_session(trace_id, org_id=_org() or None)
    if not events:
        return {"trace_id": trace_id, "found": False,
                "summary": (f"No trace {trace_id!r} is visible here — it does not "
                            f"exist, or it belongs to another org; the two look "
                            f"identical from this side.")}
    from aughor.obs.trace_summary import build_summary
    s = build_summary(trace_id, events)
    slowest = [{k: sp.get(k) for k in ("name", "kind", "duration_ms", "pct_of_run")}
               for sp in (s.get("slowest_spans") or [])[:5]]
    errors = [{k: e.get(k) for k in ("name", "kind", "error_class")}
              for e in (s.get("errors") or [])[:5]]
    counts, time = s.get("counts") or {}, s.get("time") or {}
    ok = bool(s.get("ok"))
    n_err = int(counts.get("errors") or 0)
    err_line = (f" {n_err} error{'s' if n_err != 1 else ''} — first: "
                f"{errors[0]['name']} ({errors[0]['error_class']})."
                if errors else "")
    slow_line = (f" Slowest step: {slowest[0]['name']} "
                 f"({slowest[0]['duration_ms']} ms)." if slowest else "")
    return {
        "trace_id": trace_id, "found": True, "ok": ok,
        "summary": (f"Run {trace_id[:8]}…: {'ok' if ok else 'NOT ok'}, "
                    f"{counts.get('spans', 0)} steps, "
                    f"{counts.get('model_calls', 0)} model calls, "
                    f"{int(round(float(time.get('wall_ms') or 0)))} ms wall."
                    f"{err_line}{slow_line} "
                    f"Metadata only — step inputs and outputs are the audited "
                    f"read on the Traces page."),
        "question": s.get("question"), "started_at": s.get("started_at"),
        "counts": counts, "time": time, "models": s.get("models"),
        "slowest_steps": slowest, "errors": errors,
    }


def platform_audit(args: dict) -> dict:
    """The unified governance feed — every audited act, one merged stream.

    The body is `govern.audit_categories.feed`, THE aggregator the /audit surface
    reads: per-sink newest windows merged and sorted, tenant scoping inside each
    sink. This tool adds nothing but the conversation-shaped cap and the honesty
    line about what a per-sink window means."""
    from aughor.govern.audit_categories import CATEGORIES, feed

    category = str(args.get("category") or "").strip().lower() or None
    limit = max(1, min(int(args.get("limit") or 20), _MAX_AUDIT))
    try:
        events = feed(category=category, limit=limit)
    except ValueError:
        return {"error": f"unknown category {category!r}",
                "known_categories": sorted(CATEGORIES),
                "summary": (f"No audit category named {category!r} — the "
                            f"categories are: {', '.join(sorted(CATEGORIES))}.")}
    rows = [{"category": e.category, "kind": e.kind, "at": e.at,
             "actor": e.actor, "summary": e.summary} for e in events]
    cats = sorted({r["category"] for r in rows})
    scope_line = (f"the {category} category" if category
                  else f"all categories ({', '.join(cats) or 'none present'})")
    return {
        "category": category or "(all)",
        "summary": (f"Newest {len(rows)} audit events across {scope_line}, "
                    f"newest first. This merges each audit sink's most recent "
                    f"window — it is a recency feed, not a complete history "
                    f"count."),
        "events": rows,
        "known_categories": sorted(CATEGORIES),
    }


# ── the roster ───────────────────────────────────────────────────────────────────────

_DAYS_PARAMS = {
    "type": "object",
    "properties": {"days": {"type": "integer",
                            "description": "Trailing window in days (default 7, max 90)."}},
}
_USAGE_PARAMS = {
    "type": "object",
    "properties": {
        "days": {"type": "integer",
                 "description": "Trailing window in days (default 7, max 90)."},
        "by": {"type": "string",
               "description": "Grouping axis: model, provider, feature, agent, "
                              "connection, user or org (default model)."},
    },
}
_MONTHS_PARAMS = {
    "type": "object",
    "properties": {"months": {"type": "integer",
                              "description": "Trailing calendar months (default 6)."}},
}
_ACCURACY_PARAMS: dict = {"type": "object", "properties": {}}
_TOP_PARAMS = {
    "type": "object",
    "properties": {"top": {"type": "integer",
                           "description": "How many tables/columns to list (default 10)."}},
}
_EMPTY_PARAMS: dict = {"type": "object", "properties": {}}
_TRACES_PARAMS = {
    "type": "object",
    "properties": {
        "trace_id": {"type": "string",
                     "description": "Inspect ONE run by its trace id (from a "
                                    "listing); omit to list recent runs."},
        "days": {"type": "integer",
                 "description": "Listing window in days (default 7, max 90)."},
        "limit": {"type": "integer",
                  "description": "How many runs to list (default 10, max 20)."},
    },
}
_AUDIT_PARAMS = {
    "type": "object",
    "properties": {
        "category": {"type": "string",
                     "description": "Optional filter: data_access, "
                                    "governance_change, action_decision, "
                                    "model_call or human_verdict. Omit for all."},
        "limit": {"type": "integer",
                  "description": "How many events (default 20, max 50)."},
    },
}


def spotlight_tools(connection_id: str, *, session_id: str = "") -> list[ToolSpec]:
    """SP-1's org-level Know reads, bound the same way as every other roster: the
    connection by closure, nothing model-nameable that the caller did not grant."""
    return [
        ToolSpec(
            name="list_platform_connections",
            description=(
                "List every data connection this deployment has — count, names, engine "
                "types. Use this for 'how many connections / what are we connected to' "
                "questions about the PLATFORM; for the tables inside the current "
                "connection use list_tables. Quote the summary field verbatim for the numbers — never re-derive them from the other fields."
            ),
            parameters=_EMPTY_PARAMS,
            run=lambda a: list_platform_connections(a),
        ),
        ToolSpec(
            name="platform_usage",
            description=(
                "Model usage and cost for a trailing window — calls, tokens, USD — "
                "grouped by model, provider, feature, agent, connection or user. "
                "Use this for 'what did we spend / which agent burns the most tokens' "
                "questions. Read the honesty fields before quoting: unpriced or "
                "usage-less calls make the totals a floor, not the whole truth, and "
                "you must say so. Quote the summary field verbatim for the numbers — never re-derive them from the other fields."
            ),
            parameters=_USAGE_PARAMS,
            run=lambda a: platform_usage(a),
        ),
        ToolSpec(
            name="platform_runs",
            description=(
                "How much ran on the platform in a trailing window: deep-analysis "
                "runs started / succeeded / failed (failed runs are part of started, "
                "never a separate pile), and automation ticks counted by outcome "
                "(fired, not fired, gated, paused, error) with a real windowed count "
                "— no scan cap. Use this for 'how many runs happened' and 'is "
                "anything failing' questions. Quote the summary field verbatim for the numbers — never re-derive them from the other fields."
            ),
            parameters=_DAYS_PARAMS,
            run=lambda a: platform_runs(a),
        ),
        ToolSpec(
            name="investigation_cadence",
            description=(
                "Deep-analysis runs per calendar month with the monthly average. Use "
                "this for 'how many analyses do we run in a month on average' "
                "questions; months with zero runs are listed as zero, not omitted. Quote the summary field verbatim for the numbers — never re-derive them from the other fields."
            ),
            parameters=_MONTHS_PARAMS,
            run=lambda a: investigation_cadence(a),
        ),
        ToolSpec(
            name="answer_accuracy",
            description=(
                "The graded quality of this platform's answers: human verdict counts, "
                "the acceptance rate, the recent weekly trend, and how many verified "
                "query patterns exist. ALWAYS quote the rate together with "
                "the graded total — a rate over a thin sample is a different claim than "
                "one over a thick sample, and the caveat field says which you have. Quote the summary field verbatim for the numbers — never re-derive them from the other fields."
            ),
            parameters=_ACCURACY_PARAMS,
            run=lambda a: answer_accuracy(connection_id, a),
        ),
        ToolSpec(
            name="table_popularity",
            description=(
                "THE authoritative source for which tables and columns real queries "
                "touch most on this connection, and how many distinct tables have "
                "been queried — mined from actual query history. Never answer that "
                "question by writing SQL against the warehouse: the warehouse holds "
                "the business data, not the platform's query log, and such a query "
                "returns a confident wrong 0. Counts are all-time since mining began "
                "and cannot be windowed to N days — when the user asks for a window, "
                "report the all-time counts and say they are all-time (quote the "
                "scope field). If the result says mined=false, answer 'not mined "
                "yet' — never report an empty store as 'nothing gets queried'. Quote the summary field verbatim for the numbers — never re-derive them from the other fields."
            ),
            parameters=_TOP_PARAMS,
            run=lambda a: table_popularity(connection_id, a),
        ),
        ToolSpec(
            name="platform_traces",
            description=(
                "Recent runs across the platform (what ran, when, how long, what "
                "failed) — or, given a trace id, ONE run's anatomy: step counts, "
                "timing, models, slowest steps, error classes. Use this for 'what "
                "just ran', 'why was that slow', 'show me that failure' questions. "
                "Metadata only: it never returns a step's inputs or outputs — those "
                "are an audited read on the Traces page, and you must say so if "
                "asked for them. Quote the summary field verbatim for the numbers "
                "— never re-derive them from the other fields."
            ),
            parameters=_TRACES_PARAMS,
            run=lambda a: platform_traces(a),
        ),
        ToolSpec(
            name="platform_audit",
            description=(
                "The unified audit feed — who did what, newest first, across every "
                "governance sink: data access, governance changes, action "
                "decisions, model calls, human verdicts. Use this for 'who "
                "changed / approved / accessed what' questions about the PLATFORM. "
                "It is a recency feed of each sink's newest window, not a complete "
                "history count — never present its length as a total. Quote the "
                "summary field verbatim for the numbers — never re-derive them "
                "from the other fields."
            ),
            parameters=_AUDIT_PARAMS,
            run=lambda a: platform_audit(a),
        ),
    ]
