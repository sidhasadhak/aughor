"""The Aughor MCP server — Aughor's GOVERNED intelligence as Model Context Protocol
tools, for any MCP client (Claude Desktop / Claude Code / Cursor).

Design principle (from docs/MOTHERDUCK_LEARNINGS.md R5): expose governed *intelligence*
tools, **not a raw ``query`` tool**. A generic text-to-SQL MCP hands the model a SQL
runner and hopes the model writes a correct, fan-out-safe, metric-consistent query.
Aughor instead exposes ``ask`` / ``deep_analysis`` / ``get_metric`` / ``get_briefing`` —
tools that run Aughor's full governed path (write SQL → ground every number in real
rows → enforce registered metric definitions → attach the guards that fired) and return
a verified answer **with a Trust Receipt**. MotherDuck makes the client smart; Aughor
makes the tool smart.

Each tool is a thin wrapper over the running Aughor REST API (see client.AughorClient),
so the governed path, cost metering, agent budgets, and capability gating all execute in
the API process exactly as they do for the web app.
"""
from __future__ import annotations

from typing import Annotated, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from aughor.mcp.client import AughorClient

_INSTRUCTIONS = """\
Aughor is an autonomous, governed data-intelligence platform over a connected warehouse.
These tools return VERIFIED answers, not raw SQL — Aughor writes and runs the SQL, grounds
every number in real rows, and enforces governed metric definitions.

How to use this server:
1. Call `list_connections` FIRST — the other tools need a `connection` id from it.
2. For a specific question, use `ask` (fast; returns the answer + a Trust Receipt). Prefer
   it over writing SQL yourself — the answer is governed and grounded, not plausible.
3. For a "why / root-cause / driver" question that needs multi-step evidence, use
   `deep_analysis` (slower; runs the autonomous deep analysis and returns a report).
4. `get_metric` returns the EXACT governed value of a registered metric — use it instead of
   re-deriving a formula. `list_findings` / `get_briefing` surface what Aughor already
   discovered in the background. `explore` kicks off background discovery.
5. `list_jobs` / `get_job` / `cancel_job` are the agent fleet — running and finished work.
6. When an answer was slow or wrong, debug it: `list_runs` → `inspect_run` (where the time
   went, what it cost, what failed) → `read_run_span` for the one span that matters. Do not
   ask for a whole trace; the summary plus one span is the surface, by design.

Every answer is auditable: `ask` and `deep_analysis` results carry a `receipt` with the
executed SQL, the input tables, and the trust guards that fired.
"""

mcp = FastMCP("Aughor", instructions=_INSTRUCTIONS)
_client = AughorClient()


@mcp.tool()
async def list_connections() -> list[dict]:
    """List the data warehouses/connections Aughor can analyze. CALL THIS FIRST — every
    other tool needs a `connection` id from here. Returns each connection's id, name,
    dialect, and (for multi-schema connections) its schema names."""
    return await _client.list_connections()


@mcp.tool()
async def ask(
    question: Annotated[str, Field(description="A natural-language analytical question, e.g. 'What was total revenue last quarter?'")],
    connection: Annotated[str, Field(description="A connection id from list_connections.")],
    canvas: Annotated[Optional[str], Field(description="Optional canvas id to scope the question to a curated set of tables.")] = None,
) -> dict:
    """Ask a natural-language analytical question and get a GOVERNED answer with a Trust
    Receipt. Aughor writes the SQL, runs it against the warehouse, grounds every number in
    real result rows, enforces any governed metric definitions involved, and returns the
    headline answer + the exact SQL + a sample of result rows + the receipt (the guards
    that fired and the governed metrics used).

    Prefer this over writing SQL yourself: the answer is verified, not plausible. Use it for
    direct questions ("how many…", "what is…", "top N…", "trend of…"). For open-ended
    "why did X happen / what's driving Y" questions, use `deep_analysis` instead.

    Returns: {answer, sql, columns, rows (sample), row_count, trusted_metrics, receipt, …}.
    """
    return await _client.ask(question, connection, canvas=canvas)


@mcp.tool()
async def deep_analysis(
    question: Annotated[str, Field(description="An open-ended analytical question, e.g. 'Why did margin fall in Q3?' or 'What's driving low review scores?'")],
    connection: Annotated[str, Field(description="A connection id from list_connections.")],
    schema: Annotated[Optional[str], Field(description="Optional schema name to scope a multi-schema connection.")] = None,
    deep: Annotated[bool, Field(description="True (default) runs the full deep analysis; False serves a pre-computed finding dossier when the question maps to one.")] = True,
    fresh: Annotated[bool, Field(description="Skip the similar-investigation cache and force a new run.")] = False,
) -> dict:
    """Run Aughor's autonomous deep analysis — a multi-step, evidence-gathering
    run for "why / root-cause / driver" questions that one query can't answer. The
    agent forms hypotheses, runs and verifies queries (fan-out- and grain-safe), and
    synthesizes a report with findings and recommendations, plus a Trust Receipt.

    Slower than `ask` (seconds to a few minutes). This call drives the run to completion and
    returns the report; if it exceeds the timeout it returns an `investigation_id` and
    status='running' — then poll `get_investigation(investigation_id)` for the finished
    report. Use `ask` for direct factual questions.

    Returns: {status, investigation_id, report, report_kind, hypotheses, from_cache, receipt}.
    """
    return await _client.deep_analysis(question, connection, schema=schema, deep=deep, skip_cache=fresh)


@mcp.tool()
async def get_investigation(
    investigation_id: Annotated[str, Field(description="The id returned by deep_analysis.")],
) -> dict:
    """Fetch a deep-analysis report by its id — use this to poll for a report after
    `deep_analysis` returned status='running', or to re-read a past run."""
    return await _client.get_investigation(investigation_id)


@mcp.tool()
async def get_metric(
    name: Annotated[Optional[str], Field(description="A governed metric name. Omit to list all registered metrics.")] = None,
    connection: Annotated[Optional[str], Field(description="A connection id — when given with `name`, also computes the metric's current value against that connection.")] = None,
) -> dict:
    """Read Aughor's GOVERNED metrics. With no `name`, lists every registered metric (name,
    label, formula, governance status). With a `name` and a `connection`, also computes the
    metric's CURRENT value by running its registered SQL — the exact governed number, so you
    bind to the same definition Aughor enforces everywhere instead of improvising a formula.

    Returns: {metrics:[…]} when listing, or {name, definition, value, unit, sql} for one metric.
    """
    return await _client.get_metric(connection=connection, name=name)


@mcp.tool()
async def list_findings(
    connection: Annotated[str, Field(description="A connection id from list_connections.")],
    schema: Annotated[Optional[str], Field(description="Optional schema name to scope a multi-schema connection.")] = None,
    limit: Annotated[int, Field(description="Max findings to return (default 25).", ge=1, le=100)] = 25,
) -> dict:
    """List the insights Aughor's background explorer has already discovered for a connection
    — each a verified finding with its confidence, novelty, domain, and the SQL behind it.
    These are pre-computed (a $0 read), so prefer this before asking Aughor to re-derive what
    it already found. If `count` is 0, the connection hasn't been explored yet — call `explore`.
    """
    return await _client.list_findings(connection, schema=schema, limit=limit)


@mcp.tool()
async def get_briefing(
    connection: Annotated[str, Field(description="A connection id from list_connections.")],
    schema: Annotated[Optional[str], Field(description="Optional schema name to scope a multi-schema connection.")] = None,
    refresh: Annotated[bool, Field(description="Rebuild the briefing from the latest findings (re-validates against live data) instead of returning the cached narrative.")] = False,
) -> dict:
    """Get Aughor's executive Briefing for a connection — the synthesized, impact-ranked
    narrative of what matters right now (the lead verdict, supporting signals, citations),
    built from the explorer's findings and the governed north-star metrics. The fastest way
    to understand a business's current state. `available=false` means there's nothing to brief
    yet (explore the connection first)."""
    return await _client.get_briefing(connection, schema=schema, refresh=refresh)


@mcp.tool()
async def explore(
    connection: Annotated[str, Field(description="A connection id from list_connections.")],
    schema: Annotated[Optional[str], Field(description="Optional schema name; omit to explore every schema of a multi-schema connection.")] = None,
) -> dict:
    """Kick off Aughor's autonomous background exploration of a connection — it profiles the
    data, maps entities and lifecycles, and surfaces findings with no prompting. Returns
    immediately (the work runs in the background as a fleet job); poll `list_findings` /
    `get_briefing` for results, or `list_jobs` to watch progress. Subject to the connection's
    agent governance (a paused Scout agent won't auto-run)."""
    return await _client.explore(connection, schema=schema)


@mcp.tool()
async def list_jobs(
    state: Annotated[Optional[str], Field(description="Filter by lifecycle state, e.g. 'active', 'succeeded', 'failed'.")] = None,
    connection: Annotated[Optional[str], Field(description="Filter to one connection id.")] = None,
    limit: Annotated[int, Field(description="Max jobs to return (default 50).", ge=1, le=500)] = 50,
) -> list:
    """List Aughor's agent fleet — recent and in-flight background jobs (explorations =
    Scout, investigations = Analyst), each tagged with its agent, status, the compute it
    spent (tokens · queries · rows · time), and duration. The legible view of the autonomy
    Aughor runs."""
    return await _client.list_jobs(state=state, connection=connection, limit=limit)


@mcp.tool()
async def get_job(
    job_id: Annotated[str, Field(description="A job id from list_jobs.")],
) -> dict:
    """Get one fleet job by id — its agent, state, cost, and duration."""
    return await _client.get_job(job_id)


@mcp.tool()
async def cancel_job(
    job_id: Annotated[str, Field(description="A job id from list_jobs.")],
) -> dict:
    """Cancel an in-flight fleet job (e.g. a long exploration or investigation)."""
    return await _client.cancel_job(job_id)


# ── Wave S6 — knowledge tools over the stores this program built ────────────────────
#
# In-process reads rather than REST round-trips, deliberately and against the module's
# general rule: these four read committed artifacts and local stores, so a hop through the
# API would add latency and a second failure mode to answer a question the process can
# already answer. The governed path still runs in the API for everything that EXECUTES —
# `ask`, `deep_analysis`, `explore` are unchanged.
#
# Every tool that returns table-derived data goes through G5's clearance trim. MCP is an
# EXTERNAL agent surface: skipping the trim here would be a bigger hole than skipping it
# internally, because the consumer is not a person who might notice.

@mcp.tool()
async def search_graph(
    connection: Annotated[str, Field(description="A connection id from list_connections.")],
    query: Annotated[str, Field(description="What to look for — a table, metric, term or topic.")],
    limit: Annotated[int, Field(description="Max nodes to return (default 10).", ge=1, le=50)] = 10,
) -> dict:
    """Search Aughor's connection knowledge graph — the tables, governed metrics, glossary
    terms and past findings it has already established for a connection, with the measured
    join overlap between tables. This is a $0 read of what Aughor already knows: prefer it
    before asking Aughor to re-derive anything. `available=false` means no graph has been
    built yet. A `notice` means some results were withheld by data governance — the data
    exists, your credentials do not reach it."""
    from aughor.mcp.knowledge_tools import search_graph as _search

    return _search(connection, query, limit=limit)


@mcp.tool()
async def describe_entity(
    connection: Annotated[str, Field(description="A connection id from list_connections.")],
    entity: Annotated[str, Field(description="A table or entity name, e.g. 'orders'.")],
) -> dict:
    """Everything Aughor knows about one entity — its columns, domain, verified joins with
    their MEASURED value-domain overlap, glossary terms and past findings. The same slice
    Aughor's own entity page renders, so an agent and a human asking about `orders` get one
    answer. `available=false` with a `notice` means the entity exists but is withheld by
    data governance."""
    from aughor.mcp.knowledge_tools import describe_entity as _describe

    return _describe(connection, entity)


@mcp.tool()
async def get_table_health(
    connection: Annotated[str, Field(description="A connection id from list_connections.")],
    table: Annotated[str, Field(description="The table to report health for.")],
) -> dict:
    """Data-quality verdicts for a table — which declared checks passed, which failed, how
    many violations, and how STALE each verdict is. Use it before trusting a number from a
    table: a verdict computed against yesterday's data is not authoritative today.
    `checked=false` means no checks have run — which is NOT the same as healthy."""
    from aughor.mcp.knowledge_tools import get_table_health as _health

    return _health(connection, table)


@mcp.tool()
async def list_trusted_queries(
    connection: Annotated[str, Field(description="A connection id from list_connections.")],
    limit: Annotated[int, Field(description="Max queries to return (default 25).", ge=1, le=100)] = 25,
) -> dict:
    """The verified query patterns for a connection, each with the WARRANT it carries:
    `human_pinned` (a person settled this question), `eval_promoted` (it passed every eval
    run), or `recorded`. Reuse the SQL structure of a trusted query rather than writing a
    new one — and prefer a human-pinned pattern over a promoted one when both exist."""
    from aughor.mcp.knowledge_tools import list_trusted_queries as _trusted

    return _trusted(connection, limit=limit)


# ── traces (VA-5) ────────────────────────────────────────────────────────────────
# Three tools, narrowing: which runs → one run's shape → one span's payload. There is
# deliberately no "fetch the whole trace" tool. That response is 1.2 MB for a 1,140-event
# run on a real store, roughly 300k tokens — a tool whose SUCCESS case exhausts the
# caller's context is not a usable tool, and the roadmap's own risk note says to page by
# span rather than load whole.


@mcp.tool()
async def list_runs(
    limit: Annotated[int, Field(description="Max runs to return (default 20, newest first).", ge=1, le=100)] = 20,
    investigation: Annotated[Optional[str], Field(description="Only runs that touched this investigation id.")] = None,
    agent: Annotated[Optional[str], Field(description="Only runs by this agent id.")] = None,
) -> dict:
    """Recent Aughor runs, newest first — the index into the trace surface.

    One summary per run: its question, when it started, how many events, tool calls and
    model calls it made, and how many errored. Use it to FIND the run you care about, then
    call `inspect_run` with its `trace_id`. Debugging a slow or wrong answer starts here."""
    return {"runs": await _client.list_runs(
        limit=limit, investigation_id=investigation, agent_id=agent)}


@mcp.tool()
async def inspect_run(
    trace_id: Annotated[str, Field(description="A trace id from list_runs.")],
    top: Annotated[int, Field(description="How many entries in each ranked list (default 8).", ge=1, le=50)] = 8,
) -> dict:
    """What happened in one run: where the time went, what it cost, and what failed.

    Returns a SUMMARY, not the event log — the shape of the run, its slowest spans, its
    longest waits, token usage per model, and any errors. `time.idle_pct` is the number
    worth reading first: a run can be slow because the work is slow, or because it spent
    most of the wall clock waiting, and those have opposite fixes. It is computed over the
    union of span intervals, so it stays true when the run did work in parallel.

    Span inputs and outputs are NOT included. Once the summary tells you which span matters,
    fetch that one with `read_run_span` — paying for one step instead of the whole run."""
    return await _client.inspect_run(trace_id, top=top)


@mcp.tool()
async def read_run_span(
    trace_id: Annotated[str, Field(description="A trace id from list_runs.")],
    span_id: Annotated[str, Field(description="A span id from inspect_run's slowest_spans or errors.")],
) -> dict:
    """One span's input and output — the drill-down `inspect_run` points at.

    Use it on the span the summary identified: the slowest one, or the one that errored.
    Returns that span's call payload (e.g. the SQL that ran, or the tool's arguments) and
    its result, with any credential in them masked.

    This read is AUDITED: Aughor journals who read whose run, because payload access is
    governed rather than merely permitted."""
    return await _client.run_span(trace_id, span_id)


# ── DS-14: an enabled automation, exposed as a tool ──────────────────────────────
#
# The eighteen tools above are STATIC — they are what this version of Aughor can do, and
# they are the same on every install. An automation is the opposite: it is what THIS
# deployment's people built, it appears and disappears at runtime, and no decorator can
# know its name. So these are registered dynamically at server start from the one route
# that says which chains their owners opted in.
#
# Opt-in, never automatic. A deployment's automations are its private machinery; exposing
# every one of them to any MCP client because the server happens to front the API would
# be the opposite of the governed posture the rest of this file exists for.
#
# The tool is a thin wrapper over `POST /automations/{id}/run` — the SAME route the web
# app's "Run now" presses. That is the whole design: the caller changes, the governance
# does not. The chain runs in the one engine, writes a run row that Activity reads, and a
# governed write inside it still parks for the approval gate (DS-8) rather than firing
# because the request arrived over MCP.

import logging as _logging
import re as _re

_log = _logging.getLogger("aughor.mcp")

#: A tool name an MCP client will accept, derived from the automation's own name.
_SLUG_OK = _re.compile(r"[^a-z0-9_]+")


def automation_tool_name(name: str) -> str:
    """The MCP tool name for an automation, from the name a person gave it.

    Their words, not an id: an agent choosing between tools reads the name, and
    ``run_a1671c53`` tells it nothing. Non-identifier characters collapse to underscores
    so "DS-6 receipt: revenue routing" becomes ``ds_6_receipt_revenue_routing``.
    """
    slug = _SLUG_OK.sub("_", (name or "").strip().lower()).strip("_")
    return slug or "automation"


async def register_automation_tools(client: "AughorClient | None" = None) -> list[str]:
    """Register one tool per exposed automation. Returns the names actually registered.

    Never raises. An MCP server that refuses to start because the API is down — or because
    one automation has an awkward name — is worse than one that starts with its eighteen
    static tools and says what it could not add: the static tools are the ones a client
    needs to diagnose the outage.

    A name that collides with an existing tool is SKIPPED rather than allowed to shadow it.
    Shadowing `ask` with someone's automation called "Ask" would silently replace the
    governed answer path with a chain, which is the kind of substitution nobody would think
    to look for.
    """
    api = client or _client
    try:
        exposed = await api.list_automation_tools()
    except Exception as exc:                       # the API is down, or the route is old
        _log.warning("could not read the exposed automations: %s", exc)
        return []

    taken = set(getattr(mcp._tool_manager, "_tools", {}) or {})
    added: list[str] = []
    for row in exposed:
        automation_id = str(row.get("id") or "")
        if not automation_id:
            continue
        name = str(row.get("tool_name") or "") or automation_tool_name(str(row.get("name") or ""))
        if name in taken:
            _log.warning("automation tool %r collides with an existing tool — skipped", name)
            continue
        mcp.add_tool(_automation_runner(api, automation_id), name=name,
                     description=_automation_description(row))
        taken.add(name)
        added.append(name)
    return added


def _automation_description(row: dict) -> str:
    """What an agent reads when deciding whether to call this chain.

    The steps are named, because "runs an automation" is not a description anyone can
    choose on. A model picking between tools needs to know this one posts to Slack.
    """
    described = str(row.get("description") or "").strip()
    steps = ", ".join(str(s) for s in (row.get("steps") or []) if s)
    parts = [described or f"Run the '{row.get('name')}' automation."]
    if steps:
        parts.append(f"Steps: {steps}.")
    parts.append("Runs through Aughor's governed path — the run appears in Activity, and a "
                 "governed write inside it stops for human approval rather than firing.")
    return " ".join(parts)


def _automation_runner(api: "AughorClient", automation_id: str):
    """One no-argument tool that fires one chain.

    A factory rather than a lambda in the loop: a closure built inline would capture the
    LOOP variable, so every registered tool would run whichever automation happened to be
    last — the classic late-binding bug, and one that would look like the right number of
    tools right up until a client called one.

    No arguments, because an automation is not a function: it carries its own trigger and
    its own step config, and inventing parameters here would be a second authoring surface
    for a chain that already has one.
    """
    async def _run() -> dict:
        run = await api.run_automation(automation_id)
        # A compact verdict, not the whole run record: the caller wants to know whether it
        # fired and what happened, and the full row is in Activity where it belongs.
        return {
            "outcome": run.get("outcome"),
            "reason": run.get("reason"),
            "run_id": run.get("id"),
            "steps": [{"kind": e.get("kind"), "status": e.get("status"),
                       "message": e.get("message")}
                      for e in (run.get("effects") or [])],
        }

    return _run
