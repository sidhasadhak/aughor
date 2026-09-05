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
  worse than one where it is exactly true. Spotlight's Act limb (SP-3) will live next
  door when it exists, the way ``action_tools`` does.
* **Claims are bound to tool results** (CI-3's latitude law): these tools exist so the
  model never answers a platform-state question from priors. Where a number is UNKNOWN
  the result says so in its own field — an unpriced call is not a free call, an unmined
  popularity store is not an unpopular table, and a thin verdict sample is not an
  accuracy. The honesty fields are the answer, not padding around it.
* **Org scope rides the contextvar** (``current_org_id``), exactly as the /usage and
  /learning surfaces do; connection-flavoured reads bind the conversation's connection
  by closure, so the model cannot name a connection it was not given.
* **The context window is the budget.** Grouped results are capped and say when cut.
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
    res = {"count": len(conns), "connections": out}
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

    res = {
        "window_days": days, "since": since, "grouped_by": by,
        "total_calls": report.total_calls, "total_tokens": total_tokens,
        "cost_usd": cost_usd, "cost_is_complete": unpriced == 0,
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
    return {
        "window_days": days, "since_day": floor_day,
        "deep_runs": inv,
        "automation_runs": {"total": sum(outcomes.values()), "by_outcome": outcomes},
    }


def investigation_cadence(args: dict) -> dict:
    """Deep runs per calendar month plus the monthly average — the cadence read."""
    from aughor.db.history import investigations_by_month

    months = max(1, min(int(args.get("months") or 6), 36))
    return investigations_by_month(months)


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
    res = {
        "connection_id": cid or "(all)",
        "graded_total": total,
        "verdict_counts": stats.get("counts") or {},
        "acceptance_rate": stats.get("acceptance_rate"),
        "recent_weeks": trend,
        "trusted_queries": len(list_trusted(cid)) if cid else None,
    }
    if total == 0:
        res["caveat"] = ("no graded verdicts yet — there is no accuracy number to "
                         "report, which is different from accuracy being low")
    elif total < 30:
        res["caveat"] = (f"only {total} graded verdicts — quote the rate WITH the "
                         "sample size; grading volume is what firms this number up")
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
            "answer": ("the popularity store holds nothing for this connection — say "
                       "'not mined yet', never 'nothing is queried'; mining runs with "
                       "the schema birth job"),
        }
    return {
        "connection_id": connection_id, "mined": True,
        "scope": _POPULARITY_SCOPE,
        "queries_mined": int(sum(n for _, n in tables)),
        "distinct_tables": len(tables),
        "distinct_columns": len(columns),
        "top_tables": [{"table": t, "queries": n} for t, n in tables[:top]],
        "top_columns": [{"column": c, "queries": n} for c, n in columns[:top]],
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
                "connection use list_tables."
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
                "you must say so."
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
                "anything failing' questions."
            ),
            parameters=_DAYS_PARAMS,
            run=lambda a: platform_runs(a),
        ),
        ToolSpec(
            name="investigation_cadence",
            description=(
                "Deep-analysis runs per calendar month with the monthly average. Use "
                "this for 'how many analyses do we run in a month on average' "
                "questions; months with zero runs are listed as zero, not omitted."
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
                "one over a thick sample, and the caveat field says which you have."
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
                "yet' — never report an empty store as 'nothing gets queried'."
            ),
            parameters=_TOP_PARAMS,
            run=lambda a: table_popularity(connection_id, a),
        ),
    ]
