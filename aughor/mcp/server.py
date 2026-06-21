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

from typing import Annotated, Any, Optional

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
   `deep_analysis` (slower; runs the autonomous Deep Analysis agent and returns a report).
4. `get_metric` returns the EXACT governed value of a registered metric — use it instead of
   re-deriving a formula. `list_findings` / `get_briefing` surface what Aughor already
   discovered in the background. `explore` kicks off background discovery.
5. `list_jobs` / `get_job` / `cancel_job` are the agent fleet — running and finished work.

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
    deep: Annotated[bool, Field(description="True (default) runs the full Deep Analysis agent; False serves a pre-computed finding dossier when the question maps to one.")] = True,
    fresh: Annotated[bool, Field(description="Skip the similar-investigation cache and force a new run.")] = False,
) -> dict:
    """Run Aughor's autonomous Deep Analysis agent (ADA) — a multi-step, evidence-gathering
    investigation for "why / root-cause / driver" questions that one query can't answer. The
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
    """Fetch a Deep Analysis report by its investigation id — use this to poll for a report
    after `deep_analysis` returned status='running', or to re-read a past investigation."""
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
